"""Graph node functions for the reward proposal agent.

Each node takes the current state and returns a partial state update dict.
"""

from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.runnables import RunnableConfig

from research_agent.agents.reward_agent.state import RewardAgentState
from research_agent.agents.reward_agent.tools import (
    read_reward_code,
    validate_patch,
)
from research_agent.agents.reward_agent.prompts import (
    CONTEXT_PROPOSE_SYSTEM_PROMPT,
    CONTEXT_PROPOSE_USER_PROMPT,
    EMPTY_DIFF_RETRY_PROMPT,
    FIX_PROMPT,
    FIX_SYSTEM_PROMPT,
    PROPOSE_SYSTEM_PROMPT,
    PROPOSE_USER_PROMPT,
)
from research_agent.core.proposal_context import (
    ProposalContext,
    extract_editable_reward_context,
)
from research_agent.optimizers.reward.reward_patch_utils import (
    add_diff_header_if_missing,
    auto_fix_indentation,
    extract_target_context,
    fix_diff_line_counts,
    format_baseline,
    format_ideas,
    parse_error_line,
)


def _get_observer(config: RunnableConfig):
    """Extract observer from config, if available."""
    return config.get("configurable", {}).get("observer")


def _extract_diff_from_text(text: str) -> str:
    """Extract a unified diff from raw LLM response text.

    Handles responses that contain explanation text before/after the diff.
    """
    if not text:
        return ""

    lines = text.strip().splitlines()
    diff_lines = []
    in_diff = False

    for line in lines:
        if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
            in_diff = True
        if in_diff:
            # Skip markdown code fences
            if line.strip().startswith("```"):
                continue
            diff_lines.append(line)

    if diff_lines:
        return "\n".join(diff_lines)
    return ""


# Self-check thresholds
MAX_INITIAL_PATCH_LINES = 80
MAX_MODIFIED_FILES = 1


def initial_patch_self_check(
    diff: str,
    allowed_files: list[str],
    proposal_context: ProposalContext | None = None,
) -> tuple[bool, str, str]:
    """Self-check a proposed patch before validation.

    Returns (passed, reason, cleaned_diff).
    """
    if not diff:
        return False, "empty_diff", diff

    # 1. Strip markdown fences if present (before header check)
    cleaned = diff
    if "```" in cleaned:
        extracted = _extract_diff_from_text(cleaned)
        if not extracted:
            return False, "markdown_only_no_diff", diff
        cleaned = extracted
        diff = cleaned

    # 2. Check for unified diff header
    has_header = diff.startswith("---") or "@@" in diff
    if not has_header:
        return False, "missing_unified_diff_header", diff
    if "```" in cleaned:
        cleaned = _extract_diff_from_text(cleaned)
        if not cleaned:
            return False, "markdown_only_no_diff", diff
        # If we stripped markdown, note it but continue
        diff = cleaned

    # 3. Check modified files
    modified_files = set()
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            modified_files.add(line[6:])
        elif line.startswith("+++ "):
            modified_files.add(line[4:])
    for f in modified_files:
        if f not in allowed_files and f != "/dev/null":
            return False, f"forbidden_file:{f}", diff

    # 4. Check patch size
    diff_lines = diff.splitlines()
    if len(diff_lines) > MAX_INITIAL_PATCH_LINES:
        return False, f"too_large:{len(diff_lines)}>{MAX_INITIAL_PATCH_LINES}", diff

    # 5. Check for full-file rewrite (all lines are + or -)
    change_lines = [l for l in diff_lines if (l.startswith("+") or l.startswith("-")) and not l.startswith("+++") and not l.startswith("---")]
    context_lines = [l for l in diff_lines if l.startswith(" ") or l == ""]
    if change_lines and not context_lines:
        return False, "full_file_rewrite_no_context", diff

    # 6. Check for new imports
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            stripped = line[1:].strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                return False, "new_import", diff

    # 7. Check for mixed tabs/spaces in added lines
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            content = line[1:]
            if "\t" in content and " " in content[:len(content) - len(content.lstrip())]:
                return False, "mixed_tabs_spaces", diff

    # 8. Check if diff targets overlap with editable context
    if proposal_context:
        import re
        hunk_match = re.search(r"@@ -(\d+)", diff)
        if hunk_match:
            hunk_start = int(hunk_match.group(1))
            fn_start = proposal_context.function_start_line
            fn_end = proposal_context.function_end_line
            # Allow some margin (10 lines) for context lines
            margin = 10
            if hunk_start < fn_start - margin or hunk_start > fn_end + margin:
                return False, f"outside_editable_context:hunk_at_{hunk_start}", diff

    return True, "passed", diff


def initialize_node(state: RewardAgentState, config: RunnableConfig) -> dict:
    """Initialize defaults and read reward code."""
    t0 = time.monotonic()
    observer = _get_observer(config)
    candidate_id = state.get("candidate_id", "unknown")

    if observer and observer.is_active:
        observer.emit("node_start", node="initialize_node", candidate_id=candidate_id)

    configurable = config.get("configurable", {})
    optimizer = configurable.get("optimizer")
    project_path = optimizer.project_path if optimizer else state.get("project_path", ".")
    allowed = state.get("allowed_changes", [])

    code = read_reward_code(project_path, allowed)

    file_name = allowed[0].get("file", "env.py") if allowed else "env.py"
    if isinstance(allowed[0], str) if allowed else False:
        file_name = allowed[0]

    # Extract ProposalContext for context-grounded proposals
    proposal_ctx = None
    try:
        allowed_str_list = []
        for a in allowed:
            if isinstance(a, str):
                allowed_str_list.append(a)
            elif isinstance(a, dict):
                allowed_str_list.append(a.get("file", "env.py"))
        proposal_ctx = extract_editable_reward_context(project_path, allowed_str_list or [file_name])
        if observer and observer.is_active and proposal_ctx:
            observer.emit("proposal_context_extracted",
                          candidate_id=candidate_id,
                          function_name=proposal_ctx.function_name,
                          start_line=proposal_ctx.function_start_line,
                          end_line=proposal_ctx.function_end_line,
                          class_name=proposal_ctx.class_name,
                          indent_unit=proposal_ctx.indent_unit)
    except Exception:
        pass  # Fall back to non-context proposal

    if observer and observer.is_active:
        observer.emit("node_end", node="initialize_node", candidate_id=candidate_id,
                       duration_ms=int((time.monotonic() - t0) * 1000),
                       has_code=bool(code), file_name=file_name,
                       has_proposal_context=proposal_ctx is not None)

    return {
        "reward_code": code,
        "file_name": file_name,
        "proposal_context": proposal_ctx,
        "attempt": 0,
        "max_attempts": 3,
        "empty_diff_attempt": 0,
        "max_empty_diff_attempts": 3,
        "total_llm_calls": 0,
        "max_total_llm_calls": 6,
        "validation_ok": False,
        "validation_error": None,
        "last_error": None,
        "final_candidate_status": "pending",
    }


def _build_context_proposal_prompt(state: RewardAgentState) -> tuple[str, str] | None:
    """Build context-grounded proposal prompt from ProposalContext.

    Returns (system_prompt, user_prompt) or None if no context available.
    """
    proposal_ctx: ProposalContext | None = state.get("proposal_context")
    if not proposal_ctx:
        return None

    baseline_str = format_baseline(state.get("baseline_metrics", {}))
    ideas_str = format_ideas(state.get("ideas", []))
    method_context = state.get("method_pool_context", "")
    allowed = state.get("allowed_changes", [])
    forbidden = state.get("forbidden_changes", [])

    existing_terms = ", ".join(proposal_ctx.existing_reward_terms) if proposal_ctx.existing_reward_terms else "(none detected)"

    # Build diversity context (v0.8)
    prev_diffs = state.get("previous_candidate_diffs", [])
    prev_methods = state.get("previous_method_ids", [])
    diversity_parts = []
    if prev_methods:
        diversity_parts.append(f"Previously tried method IDs: {', '.join(set(prev_methods))}")
    if prev_diffs:
        diversity_parts.append(f"Previous candidates produced {len(prev_diffs)} patch(es). Your patch MUST be substantively different.")
        for i, d in enumerate(prev_diffs[-2:], 1):  # Show last 2
            diff_preview = d.strip()[:200]
            diversity_parts.append(f"  Previous patch {i}: {diff_preview}...")
    if not diversity_parts:
        diversity_parts.append("(No previous candidates in this batch)")
    diversity_context = "\n".join(diversity_parts)

    sys_prompt = CONTEXT_PROPOSE_SYSTEM_PROMPT.format(
        target_file=proposal_ctx.target_file,
    )

    user_prompt = CONTEXT_PROPOSE_USER_PROMPT.format(
        function_name=proposal_ctx.function_name,
        target_file=proposal_ctx.target_file,
        class_name=proposal_ctx.class_name or "(top-level)",
        function_start_line=proposal_ctx.function_start_line,
        function_end_line=proposal_ctx.function_end_line,
        indent_unit=proposal_ctx.indent_unit,
        indent_style=proposal_ctx.indentation_style,
        base_indent=proposal_ctx.base_indent,
        line_numbered_context=proposal_ctx.line_numbered_context,
        existing_reward_terms=existing_terms,
        baseline=baseline_str,
        ideas=ideas_str,
        method_context=method_context,
        allowed=allowed,
        forbidden=proposal_ctx.forbidden_summary,
        diversity_context=diversity_context,
    )

    return sys_prompt, user_prompt


def propose_node(state: RewardAgentState, config: RunnableConfig) -> dict:
    """Call LLM to propose a reward modification.

    Uses context-grounded prompt when ProposalContext is available.
    Includes empty-diff retry sub-loop (max 3 retries).
    """
    t0 = time.monotonic()
    observer = _get_observer(config)
    candidate_id = state.get("candidate_id", "unknown")

    if observer and observer.is_active:
        observer.emit("node_start", node="propose_node", candidate_id=candidate_id,
                       attempt=state.get("attempt", 0),
                       total_llm_calls=state.get("total_llm_calls", 0))

    configurable = config.get("configurable", {})
    optimizer = configurable.get("optimizer")
    llm_client = optimizer.llm_client if optimizer else None

    if llm_client is None:
        if observer and observer.is_active:
            observer.emit("node_end", node="propose_node", candidate_id=candidate_id,
                           status="noop", reason="llm_unavailable",
                           duration_ms=int((time.monotonic() - t0) * 1000))
        return {
            "final_candidate_status": "noop",
            "description": "LLM unavailable",
            "patch_diff": "",
        }

    allowed = state.get("allowed_changes", [])
    baseline_str = format_baseline(state.get("baseline_metrics", {}))
    ideas_str = format_ideas(state.get("ideas", []))
    method_context = state.get("method_pool_context", "")
    code = state.get("reward_code", "")
    file_name = state.get("file_name", "env.py")
    forbidden = state.get("forbidden_changes", [])

    # Try context-grounded prompt first
    ctx_prompt = _build_context_proposal_prompt(state)
    use_context = ctx_prompt is not None

    if use_context:
        sys_prompt, user_prompt = ctx_prompt
        if observer and observer.is_active:
            observer.emit("proposal_prompt_built", candidate_id=candidate_id,
                          context_grounded=True, function_name=state.get("proposal_context", ProposalContext()).function_name)
    else:
        sys_prompt = PROPOSE_SYSTEM_PROMPT
        user_prompt = PROPOSE_USER_PROMPT.format(
            file=file_name,
            code=code,
            baseline=baseline_str,
            allowed=allowed,
            forbidden=forbidden,
            ideas=ideas_str,
            method_context=method_context,
        )
        if observer and observer.is_active:
            observer.emit("proposal_prompt_built", candidate_id=candidate_id,
                          context_grounded=False)

    response = llm_client.call(
        system_prompt=sys_prompt,
        user_prompt=user_prompt,
        max_tokens=4096,
        response_format="text" if use_context else "json",
    )

    total_calls = state.get("total_llm_calls", 0) + 1

    if not response.parsed:
        return {
            "last_error": "LLM returned unparseable response",
            "total_llm_calls": total_calls,
        }

    desc = response.parsed.get("description", "LLM-proposed change")
    diff = response.parsed.get("diff", "")
    rationale = response.parsed.get("rationale", "")

    # For context-grounded mode, the raw response text may be a diff directly
    if not diff and use_context and response.text:
        # Try to extract diff from raw text
        diff = _extract_diff_from_text(response.text)
        if diff:
            desc = "Context-grounded proposal"

    # Empty diff retry sub-loop
    empty_attempt = 0
    max_empty = state.get("max_empty_diff_attempts", 3)
    while not diff and empty_attempt < max_empty:
        empty_attempt += 1
        print(f"[LLM] Empty diff returned, retry {empty_attempt}/{max_empty}", flush=True)

        if use_context:
            retry_sys, retry_user = ctx_prompt
            # Add emphasis on non-empty diff
            retry_user += "\n\nCRITICAL: You MUST output a non-empty unified diff. Start with --- or @@."
        else:
            retry_sys = PROPOSE_SYSTEM_PROMPT
            retry_user = EMPTY_DIFF_RETRY_PROMPT.format(
                code=code,
                baseline=baseline_str,
                ideas=ideas_str,
                allowed=json.dumps(allowed, indent=2),
            )

        retry_response = llm_client.call(
            system_prompt=retry_sys,
            user_prompt=retry_user,
            max_tokens=4096,
            response_format="text" if use_context else "json",
        )
        total_calls += 1

        if retry_response.parsed:
            diff = retry_response.parsed.get("diff", "")
        if not diff and use_context and retry_response.text:
            diff = _extract_diff_from_text(retry_response.text)
        if diff:
            if retry_response.parsed:
                desc = retry_response.parsed.get("description", desc)
                rationale = retry_response.parsed.get("rationale", rationale)
            break

    if not diff:
        if observer and observer.is_active:
            observer.emit("node_end", node="propose_node", candidate_id=candidate_id,
                           status="noop", reason="empty_diff_after_retries",
                           empty_diff_attempt=empty_attempt,
                           total_llm_calls=total_calls,
                           duration_ms=int((time.monotonic() - t0) * 1000))
        return {
            "final_candidate_status": "noop",
            "description": "Empty diff after retries",
            "patch_diff": "",
            "total_llm_calls": total_calls,
            "empty_diff_attempt": empty_attempt,
        }

    # Fix diff format
    diff = add_diff_header_if_missing(diff, file_name)
    diff = fix_diff_line_counts(diff)

    # Initial patch self-check
    proposal_ctx: ProposalContext | None = state.get("proposal_context")
    allowed_files = [file_name]
    if observer and observer.is_active:
        observer.emit("initial_patch_self_check_start", candidate_id=candidate_id)

    check_passed, check_reason, diff = initial_patch_self_check(
        diff, allowed_files, proposal_ctx)

    if not check_passed:
        print(f"[SELF-CHECK] Patch rejected: {check_reason}", flush=True)
        if observer and observer.is_active:
            observer.emit("initial_patch_self_check_failed",
                          candidate_id=candidate_id, reason=check_reason)
            if "too_large" in check_reason:
                observer.emit("initial_patch_too_large", candidate_id=candidate_id)
            if "outside_editable_context" in check_reason:
                observer.emit("initial_patch_outside_allowed_context", candidate_id=candidate_id)
            if "markdown" in check_reason:
                observer.emit("initial_patch_markdown_stripped", candidate_id=candidate_id)
        return {
            "last_error": f"Self-check failed: {check_reason}",
            "total_llm_calls": total_calls,
        }

    if observer and observer.is_active:
        observer.emit("initial_patch_self_check_pass", candidate_id=candidate_id,
                       diff_lines=len(diff.splitlines()))
        observer.emit("node_end", node="propose_node", candidate_id=candidate_id,
                       status="proposed", diff_lines=len(diff.splitlines()),
                       total_llm_calls=total_calls, empty_diff_attempt=empty_attempt,
                       context_grounded=use_context,
                       duration_ms=int((time.monotonic() - t0) * 1000))

    return {
        "current_diff": diff,
        "current_description": desc,
        "current_rationale": rationale,
        "total_llm_calls": total_calls,
        "empty_diff_attempt": empty_attempt,
    }


def validate_node(state: RewardAgentState, config: RunnableConfig) -> dict:
    """Validate the current patch in an isolated temp directory."""
    t0 = time.monotonic()
    observer = _get_observer(config)
    candidate_id = state.get("candidate_id", "unknown")

    if observer and observer.is_active:
        observer.emit("node_start", node="validate_node", candidate_id=candidate_id,
                       attempt=state.get("attempt", 0))

    configurable = config.get("configurable", {})
    optimizer = configurable.get("optimizer")
    execution_env = configurable.get("execution_env")

    if not execution_env or not optimizer:
        if observer and observer.is_active:
            observer.emit("node_end", node="validate_node", candidate_id=candidate_id,
                           validation_ok=False, error="Missing execution_env or optimizer",
                           duration_ms=int((time.monotonic() - t0) * 1000))
        return {"validation_ok": False, "validation_error": "Missing execution_env or optimizer"}

    diff = state.get("current_diff")
    if not diff:
        if observer and observer.is_active:
            observer.emit("node_end", node="validate_node", candidate_id=candidate_id,
                           validation_ok=False, error="No diff to validate",
                           duration_ms=int((time.monotonic() - t0) * 1000))
        return {"validation_ok": False, "validation_error": "No diff to validate"}

    allowed = state.get("allowed_changes", [])
    result = validate_patch(
        diff=diff,
        allowed_changes=allowed,
        project_path=optimizer.project_path,
        work_dir=optimizer.work_dir,
        execution_env=execution_env,
    )

    ok = result["ok"]
    error = result.get("error")
    error_line = parse_error_line(error) if not ok and error else None

    if observer and observer.is_active:
        observer.emit("node_end", node="validate_node", candidate_id=candidate_id,
                       validation_ok=ok,
                       validation_error=error[:200] if error else None,
                       error_line=error_line,
                       duration_ms=int((time.monotonic() - t0) * 1000))

    return {
        "validation_ok": ok,
        "validation_error": error,
        "error_line": error_line,
    }


def auto_indent_node(state: RewardAgentState, config: RunnableConfig) -> dict:
    """Try to auto-fix indentation issues."""
    t0 = time.monotonic()
    observer = _get_observer(config)
    candidate_id = state.get("candidate_id", "unknown")

    if observer and observer.is_active:
        observer.emit("node_start", node="auto_indent_node", candidate_id=candidate_id)

    configurable = config.get("configurable", {})
    optimizer = configurable.get("optimizer")
    project_path = optimizer.project_path if optimizer else "."

    diff = state.get("current_diff")
    if not diff:
        if observer and observer.is_active:
            observer.emit("node_end", node="auto_indent_node", candidate_id=candidate_id,
                           status="no_diff", duration_ms=int((time.monotonic() - t0) * 1000))
        return {}

    allowed = state.get("allowed_changes", [])
    fixed = auto_fix_indentation(project_path, diff, allowed)

    if observer and observer.is_active:
        observer.emit("node_end", node="auto_indent_node", candidate_id=candidate_id,
                       fixed=fixed is not None,
                       duration_ms=int((time.monotonic() - t0) * 1000))

    if fixed:
        return {"current_diff": fixed}
    return {"last_error": "Auto-indentation could not fix the issue"}


def llm_fix_node(state: RewardAgentState, config: RunnableConfig) -> dict:
    """Ask LLM to fix a failed diff, with target context."""
    t0 = time.monotonic()
    observer = _get_observer(config)
    candidate_id = state.get("candidate_id", "unknown")

    if observer and observer.is_active:
        observer.emit("node_start", node="llm_fix_node", candidate_id=candidate_id,
                       attempt=state.get("attempt", 0),
                       total_llm_calls=state.get("total_llm_calls", 0))

    configurable = config.get("configurable", {})
    optimizer = configurable.get("optimizer")
    llm_client = optimizer.llm_client if optimizer else None
    project_path = optimizer.project_path if optimizer else "."

    if llm_client is None:
        if observer and observer.is_active:
            observer.emit("node_end", node="llm_fix_node", candidate_id=candidate_id,
                           status="noop", reason="llm_unavailable",
                           duration_ms=int((time.monotonic() - t0) * 1000))
        return {"final_candidate_status": "noop", "description": "LLM unavailable for fix"}

    code = state.get("reward_code", "")
    diff = state.get("current_diff", "")
    error = state.get("validation_error") or state.get("last_error", "")
    attempt = state.get("attempt", 0)
    allowed = state.get("allowed_changes", [])

    error_line = parse_error_line(error)
    target_context = extract_target_context(project_path, error_line, allowed) if error_line else "(could not parse error line)"

    response = llm_client.call(
        system_prompt=FIX_SYSTEM_PROMPT,
        user_prompt=FIX_PROMPT.format(
            code=code,
            diff=diff,
            error=error,
            target_context=target_context,
            attempt=attempt + 1,
        ),
        max_tokens=4096,
    )

    total_calls = state.get("total_llm_calls", 0) + 1
    new_attempt = attempt + 1

    if response.parsed:
        new_diff = response.parsed.get("diff", "")
        if new_diff:
            file_name = state.get("file_name", "env.py")
            new_diff = add_diff_header_if_missing(new_diff, file_name)
            new_diff = fix_diff_line_counts(new_diff)
            if observer and observer.is_active:
                observer.emit("node_end", node="llm_fix_node", candidate_id=candidate_id,
                               status="fixed", new_diff_lines=len(new_diff.splitlines()),
                               attempt=new_attempt, total_llm_calls=total_calls,
                               duration_ms=int((time.monotonic() - t0) * 1000))
            return {
                "current_diff": new_diff,
                "current_description": response.parsed.get("description", state.get("current_description")),
                "current_rationale": response.parsed.get("rationale", state.get("current_rationale")),
                "attempt": new_attempt,
                "total_llm_calls": total_calls,
            }

    if observer and observer.is_active:
        observer.emit("node_end", node="llm_fix_node", candidate_id=candidate_id,
                       status="empty_or_unparseable",
                       attempt=new_attempt, total_llm_calls=total_calls,
                       duration_ms=int((time.monotonic() - t0) * 1000))

    return {
        "attempt": new_attempt,
        "total_llm_calls": total_calls,
        "last_error": "LLM fix returned empty or unparseable response",
    }


def return_candidate_node(state: RewardAgentState, config: RunnableConfig) -> dict:
    """Build final output from state."""
    observer = _get_observer(config)
    candidate_id = state.get("candidate_id", "unknown")

    if observer and observer.is_active:
        observer.emit("node_start", node="return_candidate_node", candidate_id=candidate_id)

    if state.get("validation_ok"):
        if observer and observer.is_active:
            observer.emit("node_end", node="return_candidate_node", candidate_id=candidate_id,
                           final_status="ready",
                           has_diff=bool(state.get("current_diff")),
                           has_description=bool(state.get("current_description")))
        return {
            "final_candidate_status": "ready",
            "patch_diff": state.get("current_diff"),
            "description": state.get("current_description"),
            "rationale": state.get("current_rationale"),
        }

    # Determine why we're returning
    attempt = state.get("attempt", 0)
    max_attempts = state.get("max_attempts", 3)
    total_calls = state.get("total_llm_calls", 0)
    max_calls = state.get("max_total_llm_calls", 6)

    if total_calls >= max_calls:
        reason = f"exhausted ({total_calls}/{max_calls} LLM calls)"
    elif attempt >= max_attempts:
        reason = f"exhausted ({attempt}/{max_attempts} fix attempts)"
    else:
        reason = state.get("last_error") or state.get("validation_error") or "unknown"

    if observer and observer.is_active:
        observer.emit("node_end", node="return_candidate_node", candidate_id=candidate_id,
                       final_status="exhausted", rejection_reason=reason,
                       attempt=attempt, total_llm_calls=total_calls)

    return {
        "final_candidate_status": "exhausted",
        "patch_diff": "",
        "description": f"Could not produce valid patch: {reason}",
        "rationale": "",
    }
