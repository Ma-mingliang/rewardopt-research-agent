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
    EMPTY_DIFF_RETRY_PROMPT,
    FIX_PROMPT,
    FIX_SYSTEM_PROMPT,
    PROPOSE_SYSTEM_PROMPT,
    PROPOSE_USER_PROMPT,
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

    if observer and observer.is_active:
        observer.emit("node_end", node="initialize_node", candidate_id=candidate_id,
                       duration_ms=int((time.monotonic() - t0) * 1000),
                       has_code=bool(code), file_name=file_name)

    return {
        "reward_code": code,
        "file_name": file_name,
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


def propose_node(state: RewardAgentState, config: RunnableConfig) -> dict:
    """Call LLM to propose a reward modification.

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
    code = state.get("reward_code", "")
    file_name = state.get("file_name", "env.py")
    forbidden = state.get("forbidden_changes", [])

    response = llm_client.call(
        system_prompt=PROPOSE_SYSTEM_PROMPT,
        user_prompt=PROPOSE_USER_PROMPT.format(
            file=file_name,
            code=code,
            baseline=baseline_str,
            allowed=allowed,
            forbidden=forbidden,
            ideas=ideas_str,
        ),
        max_tokens=4096,
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

    # Empty diff retry sub-loop
    empty_attempt = 0
    max_empty = state.get("max_empty_diff_attempts", 3)
    while not diff and empty_attempt < max_empty:
        empty_attempt += 1
        print(f"[LLM] Empty diff returned, retry {empty_attempt}/{max_empty}", flush=True)
        retry_response = llm_client.call(
            system_prompt=PROPOSE_SYSTEM_PROMPT,
            user_prompt=EMPTY_DIFF_RETRY_PROMPT.format(
                code=code,
                baseline=baseline_str,
                ideas=ideas_str,
                allowed=json.dumps(allowed, indent=2),
            ),
            max_tokens=4096,
        )
        total_calls += 1
        if retry_response.parsed:
            diff = retry_response.parsed.get("diff", "")
            if diff:
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

    if observer and observer.is_active:
        observer.emit("node_end", node="propose_node", candidate_id=candidate_id,
                       status="proposed", diff_lines=len(diff.splitlines()),
                       total_llm_calls=total_calls, empty_diff_attempt=empty_attempt,
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
