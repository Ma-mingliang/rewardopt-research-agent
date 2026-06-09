"""Executor: orchestrate experiment plan execution across phases."""

from __future__ import annotations

import json
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path


def _auto_fix_compilation(
    file_path: Path,
    optimizer,
    max_attempts: int = 30,
) -> tuple[bool, str]:
    """Try to auto-fix ALL compilation errors in a Python file.

    Will NOT give up until code compiles or max_attempts exhausted.
    Strategies (tried in order, cycling through them):
    1. Pattern-based fixes: indentation, missing colons, unmatched brackets
    2. LLM single-line fix (for large files)
    3. LLM full-file fix (for small files)
    4. LLM block rewrite (after repeated failures on same error)

    Args:
        file_path: Path to the Python file to fix.
        optimizer: Optimizer instance (provides llm_client access).
        max_attempts: Maximum fix attempts (default 30, high to ensure success).

    Returns:
        (True, "") if file compiles after fix, (False, error_message) if all attempts fail.
    """
    if not file_path.exists():
        return False, f"File not found: {file_path}"

    # Quick check: does it already compile?
    try:
        content = file_path.read_text(encoding="utf-8-sig")
        compile(content.lstrip("﻿"), str(file_path), "exec")
        return True, ""
    except SyntaxError:
        pass

    # Save original content for rollback on failure
    original_content = file_path.read_text(encoding="utf-8-sig")

    last_error = ""
    same_error_count = 0  # Track how many times we've seen the same error

    for attempt in range(max_attempts):
        try:
            content = file_path.read_text(encoding="utf-8-sig")
            compile(content.lstrip("﻿"), str(file_path), "exec")
            print(f"[AUTO-FIX] Compilation succeeded after {attempt} fix attempts", flush=True)
            return True, ""
        except SyntaxError as e:
            error_msg = str(e)
            error_line = e.lineno
            error_text = f"{error_msg}|{error_line}"

            # Track repeated same errors
            if error_text == last_error:
                same_error_count += 1
            else:
                same_error_count = 0
                last_error = error_text

            print(f"[AUTO-FIX] Attempt {attempt+1}/{max_attempts}: line {error_line}: {error_msg[:120]}", flush=True)

            lines = content.splitlines()

            # === Strategy 1: Pattern-based fixes ===
            fixed = _try_pattern_fix(lines, error_line, error_msg)
            if fixed is not None:
                lines[error_line - 1] = fixed
                # Write full content (bracket fix may have modified other lines in-place)
                new_content = "\n".join(lines)
                file_path.write_text(new_content, encoding="utf-8-sig")
                print(f"[AUTO-FIX] Pattern fix applied at line {error_line}", flush=True)
                continue

            # === Strategy 2: LLM-based fix ===
            llm = getattr(optimizer, "llm_client", None)
            if llm is None:
                print("[AUTO-FIX] No LLM client available, cannot auto-fix", flush=True)
                return False, error_msg

            # Build context around the error
            ctx_radius = 15 if same_error_count < 3 else 25  # Wider context for stubborn errors
            ctx_start = max(0, (error_line or 1) - ctx_radius - 1)
            ctx_end = min(len(lines), (error_line or 1) + ctx_radius)
            ctx_lines = []
            for i in range(ctx_start, ctx_end):
                marker = " >>> " if i == (error_line or 1) - 1 else "     "
                ctx_lines.append(f"{i+1:4d}{marker}{lines[i]}")
            target_context = "\n".join(ctx_lines)

            # Choose strategy based on file size and attempt number
            if same_error_count >= 3:
                # Stubborn error: ask LLM to rewrite the surrounding block
                fix_prompt = f"""A Python file has a PERSISTENT SyntaxError that previous fixes could not resolve.
You MUST fix this error. Analyze the context carefully and rewrite the problematic block.

File: {file_path.name}
Error line: {error_line}
Error: {error_msg}
This SAME error has persisted through {same_error_count} fix attempts.

Context (error line marked with >>>):
```
{target_context}
```

Full file (for reference):
```python
{content}
```

Return JSON: {{"fixed_content": "<entire corrected file content>"}}"""
            elif len(lines) > 500:
                # Large file: fix single line
                fix_prompt = f"""A Python file has a SyntaxError after a reward function patch was applied.
Fix ONLY the error line to resolve the SyntaxError. Do NOT change the logic.

File: {file_path.name}
Error line: {error_line}
Error: {error_msg}

Context (error line marked with >>>):
```
{target_context}
```

Return JSON: {{"fixed_line": "<corrected line content for line {error_line}>"}}"""
            else:
                # Small file: fix full content
                fix_prompt = f"""A Python file has a SyntaxError after a reward function patch was applied.
Fix ONLY the error line and surrounding lines to resolve the SyntaxError.
Do NOT change the logic, only fix the syntax.

File: {file_path.name}
Error line: {error_line}
Error: {error_msg}

Full file content:
```python
{content}
```

Return JSON: {{"fixed_content": "<entire corrected file content>"}}"""

            try:
                sys_prompt = (
                    "You are a Python syntax fixer. Fix the SyntaxError by correcting only the problematic lines. "
                    "Preserve all logic and structure. Return valid JSON only."
                )
                response = llm.call(
                    system_prompt=sys_prompt,
                    user_prompt=fix_prompt,
                    max_tokens=8192,
                )
                if response.parsed:
                    if "fixed_content" in response.parsed:
                        fixed_content = response.parsed["fixed_content"]
                        try:
                            compile(fixed_content.lstrip("﻿"), str(file_path), "exec")
                        except SyntaxError as fix_err:
                            print(f"[AUTO-FIX] LLM fix still has error: {fix_err}", flush=True)
                            file_path.write_text(fixed_content, encoding="utf-8-sig")
                            continue
                        # Verify reward function still exists
                        if not _has_reward_function_from_content(fixed_content):
                            print(f"[AUTO-FIX] LLM fix removed reward function, skipping (attempt {attempt+1})", flush=True)
                            continue
                        file_path.write_text(fixed_content, encoding="utf-8-sig")
                        print(f"[AUTO-FIX] LLM fix succeeded (attempt {attempt+1})", flush=True)
                        return True, ""
                    elif "fixed_line" in response.parsed:
                        fixed_line = response.parsed["fixed_line"]
                        if error_line and error_line <= len(lines):
                            lines[error_line - 1] = fixed_line
                            new_content = "\n".join(lines)
                            try:
                                compile(new_content.lstrip("﻿"), str(file_path), "exec")
                            except SyntaxError as fix_err:
                                print(f"[AUTO-FIX] LLM line fix still has error: {fix_err}", flush=True)
                                file_path.write_text(new_content, encoding="utf-8-sig")
                                continue
                            # Verify reward function still exists
                            if not _has_reward_function_from_content(new_content):
                                print(f"[AUTO-FIX] LLM line fix removed reward function, skipping (attempt {attempt+1})", flush=True)
                                continue
                            file_path.write_text(new_content, encoding="utf-8-sig")
                            print(f"[AUTO-FIX] LLM line fix succeeded (attempt {attempt+1})", flush=True)
                            return True, ""
                print(f"[AUTO-FIX] LLM returned no usable fix content", flush=True)
                continue
            except Exception as llm_err:
                print(f"[AUTO-FIX] LLM call failed: {llm_err}", flush=True)
                continue

    # All attempts exhausted - final check
    try:
        content = file_path.read_text(encoding="utf-8-sig")
        compile(content.lstrip("﻿"), str(file_path), "exec")
        return True, ""
    except SyntaxError as final_err:
        # Restore original content on failure
        file_path.write_text(original_content, encoding="utf-8-sig")
        return False, str(final_err)


def _repair_patch_diff(
    optimizer,
    patch_diff: str,
    error_message: str,
    target_file: str = "env.py",
) -> str | None:
    """Use LLM to repair a failed patch diff.

    Args:
        optimizer: Optimizer instance (provides llm_client access).
        patch_diff: The original unified diff that failed to apply.
        error_message: The error message from the failed patch application.
        target_file: The target file name for the patch.

    Returns:
        Repaired diff string if successful, None if all attempts fail.
    """
    llm = getattr(optimizer, "llm_client", None)
    if llm is None:
        return None

    repair_prompt = f"""A unified diff failed to apply. Analyze the error and generate a corrected diff.

Original diff:
```
{patch_diff}
```

Error: {error_message}

Common causes of patch application failures:
1. Line number mismatch (context lines don't match the actual file)
2. Wrong file path in --- / +++ headers
3. Incorrect @@ line count headers
4. Missing or extra context lines
5. Whitespace/indentation differences

Generate a corrected unified diff that will apply cleanly to {target_file}.
The diff must:
- Start with --- a/{target_file} and +++ b/{target_file}
- Have correct @@ headers with accurate line counts
- Include enough context lines (3+) for reliable matching
- Preserve the intended code changes

Return JSON: {{"fixed_diff": "<corrected unified diff>"}}"""

    sys_prompt = (
        "You are a unified diff repair specialist. Fix the diff so it applies cleanly. "
        "Return valid JSON only."
    )

    try:
        response = llm.call(
            system_prompt=sys_prompt,
            user_prompt=repair_prompt,
            max_tokens=4096,
        )
        if response.parsed and "fixed_diff" in response.parsed:
            return response.parsed["fixed_diff"]
    except Exception as e:
        print(f"[PATCH-FIX] LLM repair call failed: {e}", flush=True)

    return None


def _fix_training_error(
    project_path: Path,
    optimizer,
    error_output: str,
    max_attempts: int = 30,
) -> tuple[bool, str]:
    """Try to fix runtime training errors using LLM analysis.

    When training fails (non-zero return code), this function:
    1. Captures the full error output (stderr + stdout)
    2. Uses LLM to analyze the error and suggest fixes to env.py
    3. Applies the fix, re-verifies compilation
    4. Returns (True, "") if fix was applied, (False, error) if all attempts fail

    Args:
        project_path: Path to the project root.
        optimizer: Optimizer instance (provides llm_client access).
        error_output: Combined stderr + stdout from the failed training run.
        max_attempts: Maximum fix attempts (default 30).

    Returns:
        (True, "") if fix was applied successfully, (False, error_message) otherwise.
    """
    env_file = project_path / "env.py"
    if not env_file.exists():
        return False, "env.py not found"

    llm = getattr(optimizer, "llm_client", None)
    if llm is None:
        return False, "No LLM client available"

    # Save original content for rollback on failure
    original_content = env_file.read_text(encoding="utf-8-sig")

    # Truncate error output to avoid exceeding LLM context
    error_tail = error_output[-3000:] if len(error_output) > 3000 else error_output

    for attempt in range(max_attempts):
        try:
            content = env_file.read_text(encoding="utf-8-sig")

            # Extract the most relevant error lines
            error_lines = []
            for line in error_tail.splitlines():
                line_stripped = line.strip()
                if any(kw in line_stripped.lower() for kw in [
                    "error", "exception", "traceback", "failed",
                    "importerror", "modulenotfounderror", "attributeerror",
                    "typeerror", "valueerror", "runtimeerror", "keyerror",
                    "indexerror", "nameerror", "syntaxerror", "indentationerror",
                ]):
                    error_lines.append(line)

            error_summary = "\n".join(error_lines[-20:]) if error_lines else error_tail[-1000:]

            fix_prompt = f"""A Python training script failed at runtime. The error is likely in env.py.
Analyze the error and fix ONLY the problematic code in env.py. Do NOT change the reward logic.

Error output (last 3000 chars):
```
{error_tail}
```

Key error lines:
```
{error_summary}
```

Current env.py content:
```python
{content}
```

Common causes of training failures:
1. Import errors: missing or wrong module names
2. AttributeError: calling methods that don't exist on objects
3. TypeError: wrong argument types or counts
4. ValueError: invalid parameter values
5. RuntimeError: environment initialization failures (e.g., pybullet)
6. KeyError/ IndexError: accessing missing dict keys or list indices

Return JSON: {{"analysis": "<brief root cause>", "fixed_content": "<entire corrected env.py content>"}}"""

            sys_prompt = (
                "You are a Python runtime error fixer. Analyze the training error and fix env.py. "
                "Preserve the reward function logic. Only fix runtime errors. Return valid JSON only."
            )

            response = llm.call(
                system_prompt=sys_prompt,
                user_prompt=fix_prompt,
                max_tokens=8192,
            )

            if response.parsed and "fixed_content" in response.parsed:
                fixed_content = response.parsed["fixed_content"]
                analysis = response.parsed.get("analysis", "")

                # Verify compilation before writing
                try:
                    compile(fixed_content.lstrip("﻿"), str(env_file), "exec")
                except SyntaxError as ce:
                    print(f"[TRAIN-FIX] Attempt {attempt+1}/{max_attempts}: LLM fix has syntax error: {ce}", flush=True)
                    # Try auto-fix on the LLM's output (write, fix, check)
                    env_file.write_text(fixed_content, encoding="utf-8-sig")
                    fix_ok, fix_err = _auto_fix_compilation(env_file, optimizer, max_attempts=30)
                    if not fix_ok:
                        print(f"[TRAIN-FIX] Attempt {attempt+1}: auto-fix also failed: {fix_err}", flush=True)
                        # Restore original content
                        env_file.write_text(original_content, encoding="utf-8-sig")
                        continue
                    # Verify __calculate_reward still exists after auto-fix
                    if not _has_reward_function(env_file):
                        print(f"[TRAIN-FIX] Attempt {attempt+1}: auto-fix removed reward function, reverting", flush=True)
                        env_file.write_text(original_content, encoding="utf-8-sig")
                        continue
                    print(f"[TRAIN-FIX] Attempt {attempt+1}: syntax fixed after LLM fix", flush=True)
                    return True, ""

                # Verify __calculate_reward still exists
                if not _has_reward_function_from_content(fixed_content):
                    print(f"[TRAIN-FIX] Attempt {attempt+1}: LLM fix removed reward function, skipping", flush=True)
                    continue

                # Compilation OK, write the fix
                env_file.write_text(fixed_content, encoding="utf-8-sig")
                print(f"[TRAIN-FIX] Attempt {attempt+1}/{max_attempts}: applied fix (analysis: {analysis[:100]})", flush=True)
                return True, ""
            else:
                print(f"[TRAIN-FIX] Attempt {attempt+1}/{max_attempts}: LLM returned no fix content", flush=True)
                continue

        except Exception as e:
            print(f"[TRAIN-FIX] Attempt {attempt+1}/{max_attempts}: LLM call failed: {e}", flush=True)
            continue

    # Restore original content on failure
    env_file.write_text(original_content, encoding="utf-8-sig")
    return False, f"All {max_attempts} fix attempts failed"


def _has_reward_function(file_path: Path) -> bool:
    """Check if a Python file contains the __calculate_reward function."""
    try:
        content = file_path.read_text(encoding="utf-8-sig")
        return _has_reward_function_from_content(content)
    except OSError:
        return False


def _has_reward_function_from_content(content: str) -> bool:
    """Check if Python source content contains the __calculate_reward function."""
    import ast
    try:
        tree = ast.parse(content.lstrip("﻿"))
        return any(
            isinstance(node, ast.FunctionDef) and node.name == "__calculate_reward"
            for node in ast.walk(tree)
        )
    except SyntaxError:
        return False


def _try_pattern_fix(lines: list[str], error_line: int | None, error_msg: str) -> str | None:
    """Try to fix common syntax errors using pattern matching.

    Returns the fixed line if a fix was applied, None otherwise.
    For bracket fixes, modifies lines in-place and returns a sentinel.
    """
    if not error_line or error_line < 1 or error_line > len(lines):
        return None

    error_msg_lower = error_msg.lower()
    line = lines[error_line - 1]
    stripped = line.lstrip()

    # === Fix 1: Indentation errors ===
    if "indent" in error_msg_lower:
        fixed = _fix_indentation(lines, error_line - 1)
        if fixed is not None:
            return fixed

    # === Fix 2: Missing colon ===
    if "expected ':'" in error_msg or "invalid syntax" in error_msg_lower:
        # Check if the line is a compound statement missing a colon
        compound_keywords = ["if ", "elif ", "else", "for ", "while ", "def ", "class ",
                             "try", "except", "finally", "with ", "async def ", "async for ", "async with "]
        for kw in compound_keywords:
            if stripped.startswith(kw) and not stripped.rstrip().endswith(":"):
                # Check if it's not a multi-line statement (ending with backslash or open bracket)
                if not stripped.rstrip().endswith("\\") and not stripped.rstrip().endswith("("):
                    return line.rstrip() + ":"

    # === Fix 3: Unmatched brackets ===
    if "unexpected EOF" in error_msg_lower or "unexpected end of file" in error_msg_lower:
        # Count unmatched brackets in the entire file
        open_parens = 0
        open_brackets = 0
        open_braces = 0
        for l in lines:
            for ch in l:
                if ch == "(": open_parens += 1
                elif ch == ")": open_parens -= 1
                elif ch == "[": open_brackets += 1
                elif ch == "]": open_brackets -= 1
                elif ch == "{": open_braces += 1
                elif ch == "}": open_braces -= 1
        # Add closing brackets to the last non-empty line
        if open_parens > 0 or open_brackets > 0 or open_braces > 0:
            last_idx = len(lines) - 1
            while last_idx >= 0 and not lines[last_idx].strip():
                last_idx -= 1
            if last_idx >= 0:
                suffix = ")" * open_parens + "]" * open_brackets + "}" * open_braces
                lines[last_idx] = lines[last_idx] + suffix
                # Return the fixed last line; caller writes full content via lines
                return lines[last_idx]

    # === Fix 4: Missing closing parenthesis on the error line ===
    if "')'" in error_msg or "']'" in error_msg or "'}'" in error_msg:
        open_p = line.count("(") - line.count(")")
        open_b = line.count("[") - line.count("]")
        open_c = line.count("{") - line.count("}")
        if open_p > 0:
            return line.rstrip() + ")" * open_p
        if open_b > 0:
            return line.rstrip() + "]" * open_b
        if open_c > 0:
            return line.rstrip() + "}" * open_c

    # === Fix 5: Tab/space mixing ===
    if "tab" in error_msg_lower or "inconsistent" in error_msg_lower:
        # Convert tabs to spaces
        if "\t" in line:
            return line.expandtabs(4)

    return None


def _fix_indentation(lines: list[str], line_idx: int) -> str | None:
    """Try to fix indentation at a specific line.

    Returns the fixed line if a fix was applied, None otherwise.
    """
    if line_idx < 0 or line_idx >= len(lines):
        return None

    line = lines[line_idx]
    stripped = line.lstrip()
    if not stripped:
        return None

    current_indent = len(line) - len(stripped)

    # Find the expected indentation from surrounding lines
    prev_indent = None
    for i in range(line_idx - 1, max(-1, line_idx - 10), -1):
        if lines[i].strip():
            prev_indent = len(lines[i]) - len(lines[i].lstrip())
            break

    next_indent = None
    for i in range(line_idx + 1, min(len(lines), line_idx + 10)):
        if lines[i].strip():
            next_indent = len(lines[i]) - len(lines[i].lstrip())
            break

    # Common indentation levels: 4, 8, 12, 16, 20 (multiples of 4)
    if prev_indent is not None and next_indent is not None:
        if prev_indent == next_indent and current_indent != prev_indent:
            return " " * prev_indent + stripped
        if current_indent not in (prev_indent, next_indent):
            target = prev_indent
            return " " * target + stripped
    elif prev_indent is not None:
        if current_indent != prev_indent and abs(current_indent - prev_indent) > 4:
            return " " * prev_indent + stripped
    elif next_indent is not None:
        if current_indent != next_indent and abs(current_indent - next_indent) > 4:
            return " " * next_indent + stripped

    # Try snapping to nearest multiple of 4
    if current_indent % 4 != 0:
        snapped = round(current_indent / 4) * 4
        return " " * snapped + stripped

    return None


def _persist_state(work_dir: Path, state: dict, resource_usage: dict | None = None) -> None:
    """Safely persist state to disk. Never raises exceptions.

    Args:
        work_dir: .research-agent work directory.
        state: Current state dict.
        resource_usage: If provided, merged into state before writing.
    """
    try:
        current = read_state_json(work_dir)
        if resource_usage:
            current["resource_usage"] = resource_usage
        # Merge key fields from state
        for key in ("current_best", "applied_patches", "baseline_fair_eval", "baseline_metrics"):
            if key in state:
                current[key] = state[key]
        # Ensure project_path is resolved
        if "project_path" in current:
            current["project_path"] = str(Path(current["project_path"]).resolve())
        write_state_json(work_dir, current)
    except Exception as e:
        print(f"[WARNING] State persistence failed: {e}", flush=True)
from typing import Any

from research_agent.core.config import AgentConfig
from research_agent.core.exceptions import BudgetExhaustedError, GuardViolationError, PatchApplyError
from research_agent.core.git_guard import git_guard_pre_run, git_guard_post_run
from research_agent.core.output import append_jsonl, ok_response, write_json_report
from research_agent.core.patch_manager import PatchManager
from research_agent.core.state import (
    add_applied_patch,
    advance_phase,
    read_state_json,
    remove_applied_patch,
    write_state_json,
    acquire_lock,
    release_lock,
)
from research_agent.core.version_tracker import (
    VersionTracker,
    extract_modified_files,
    extract_reward_formula,
    extract_source_methods,
)
from research_agent.execution.experiment_runner import (
    RunResult,
    aggregate_metrics,
    run_eval,
    run_full_eval,
    run_train,
)
from research_agent.execution.metric_parser import check_safety_metrics, parse_metrics


def run_plan(work_dir: Path, config: AgentConfig, mock_llm: bool = False) -> dict:
    """Execute the full experiment plan phase by phase.

    Workflow per phase:
    1. Acquire lock
    2. Run baseline or optimizer experiments
    3. Evaluate and check safety
    4. Update state
    5. Release lock

    Args:
        work_dir: .research-agent work directory.
        config: Agent configuration.
        mock_llm: If True, optimizer skips LLM calls.

    Returns:
        Response dict with execution results.
    """
    state = read_state_json(work_dir)
    plan = _load_plan(work_dir)
    if not plan:
        return _error_result("NO_PLAN", "No experiment plan found. Run 'plan-experiments' first.")

    phases = plan.get("phases", [])
    if not phases:
        return _error_result("NO_PHASES", "Experiment plan has no phases.")

    project_path = Path(state.get("project_path", ""))
    if not project_path.exists():
        return _error_result("PROJECT_NOT_FOUND", f"Project path not found: {project_path}")

    # Git guard pre-run: snapshot before experiments
    git_guard_pre_run(project_path, work_dir)

    # Check budget
    budget = plan.get("global_budget", {})
    resource_usage = state.get("resource_usage", {
        "wall_clock_seconds": 0,
        "gpu_seconds": 0,
        "candidates_proposed": 0,
        "full_evals_run": 0,
    })

    # Load extracted ideas for optimizers (fallback)
    ideas = _load_ideas(work_dir)

    # Initialize paper sampler for iterative method selection
    sampler = _init_sampler(work_dir)

    # Execute phases in order
    phase_results: list[dict] = []
    for phase in phases:
        phase_id = phase.get("phase_id", "")

        # Skip already completed phases
        if phase.get("status") == "completed":
            phase_results.append({"phase_id": phase_id, "status": "skipped"})
            continue

        # Check budget before each phase
        if _is_budget_exhausted(resource_usage, budget, config):
            break

        result = _execute_phase(work_dir, config, phase, project_path, resource_usage, ideas, sampler, mock_llm)
        phase_results.append(result)

        # Update resource usage
        resource_usage["wall_clock_seconds"] += result.get("duration_seconds", 0)
        if result.get("status") == "completed":
            phase["status"] = "completed"

    # Write final state
    state = read_state_json(work_dir)
    state["resource_usage"] = resource_usage
    state["execution_results"] = phase_results

    # Determine final status
    all_completed = all(p.get("status") == "completed" for p in phases)
    budget_exhausted = _is_budget_exhausted(resource_usage, budget, config)

    # Transition through running_plan first
    current_phase = state.get("phase", "ideas_extracted")
    _can_enter_running_plan = {
        "ideas_extracted", "literature_selected",
        "literature_classified", "literature_searched", "planned",
    }
    if current_phase in _can_enter_running_plan:
        # Force phase to ideas_extracted if pipeline is incomplete
        if current_phase != "ideas_extracted":
            state["phase"] = "ideas_extracted"
        state = advance_phase(state, "running_plan")

    if budget_exhausted and not all_completed:
        state["stop_reason"] = "budget_exhausted"
        state = advance_phase(state, "budget_exhausted")
    elif all_completed:
        state = advance_phase(state, "completed")
    else:
        state["stop_reason"] = "partial"
        state = advance_phase(state, "completed")

    write_state_json(work_dir, state)

    # Git guard post-run
    accepted = any(
        (r.get("best_candidate") or {}).get("status") == "accepted"
        for r in phase_results
    )
    git_guard_post_run(project_path, work_dir, accepted)

    # Write execution report
    _write_execution_report(work_dir, phase_results, resource_usage)

    return ok_response({
        "phases_executed": len([r for r in phase_results if r.get("status") != "skipped"]),
        "phases_completed": len([r for r in phase_results if r.get("status") == "completed"]),
        "resource_usage": resource_usage,
        "stop_reason": state.get("stop_reason", "completed"),
        "phase_results": phase_results,
        "report_path": "reports/execution_report.json",
    })


def run_phase(work_dir: Path, config: AgentConfig, phase_id: str, mock_llm: bool = False) -> dict:
    """Execute a single phase by phase_id.

    Args:
        work_dir: .research-agent work directory.
        config: Agent configuration.
        phase_id: ID of the phase to execute.
        mock_llm: If True, optimizer skips LLM calls.

    Returns:
        Response dict with phase execution result.
    """
    state = read_state_json(work_dir)
    plan = _load_plan(work_dir)
    if not plan:
        return _error_result("NO_PLAN", "No experiment plan found. Run 'plan-experiments' first.")

    phases = plan.get("phases", [])
    target_phase = None
    for phase in phases:
        if phase.get("phase_id") == phase_id:
            target_phase = phase
            break

    if target_phase is None:
        return _error_result("PHASE_NOT_FOUND", f"Phase '{phase_id}' not found in plan.")

    project_path = Path(state.get("project_path", ""))
    if not project_path.exists():
        return _error_result("PROJECT_NOT_FOUND", f"Project path not found: {project_path}")

    resource_usage = state.get("resource_usage", {
        "wall_clock_seconds": 0,
        "gpu_seconds": 0,
        "candidates_proposed": 0,
        "full_evals_run": 0,
    })

    ideas = _load_ideas(work_dir)
    sampler = _init_sampler(work_dir)
    result = _execute_phase(work_dir, config, target_phase, project_path, resource_usage, ideas, sampler, mock_llm)

    # Update state
    state = read_state_json(work_dir)
    state["resource_usage"] = resource_usage
    if result.get("status") == "completed":
        target_phase["status"] = "completed"
    write_state_json(work_dir, state)

    return ok_response(result)


def _execute_phase(
    work_dir: Path,
    config: AgentConfig,
    phase: dict,
    project_path: Path,
    resource_usage: dict,
    ideas: list[dict] | None = None,
    sampler=None,
    mock_llm: bool = False,
) -> dict:
    """Execute a single experiment phase."""
    phase_id = phase.get("phase_id", "unknown")
    start_time = time.monotonic()

    # Acquire lock
    if not acquire_lock(work_dir, f"run-phase {phase_id}"):
        return {
            "phase_id": phase_id,
            "status": "locked",
            "error": "Another execution is in progress.",
        }

    try:
        if phase_id == "baseline":
            result = _execute_baseline(work_dir, config, phase, project_path)
        elif phase_id == "joint-validation":
            result = _execute_joint_validation(work_dir, config, phase, project_path)
        else:
            result = _execute_optimizer_phase(
                work_dir, config, phase, project_path, resource_usage, ideas, sampler, mock_llm,
            )
    finally:
        release_lock(work_dir)

    result["duration_seconds"] = round(time.monotonic() - start_time, 2)

    # Log experiment
    log_path = work_dir / "logs" / "experiments.jsonl"
    append_jsonl(log_path, {
        "phase_id": phase_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **result,
    })

    return result


def _execute_baseline(
    work_dir: Path,
    config: AgentConfig,
    phase: dict,
    project_path: Path,
) -> dict:
    """Execute baseline phase: train + fair eval to establish baseline metrics."""
    seeds = config.execution.full_eval_seeds

    # Setup checkpoint directory
    checkpoint_dir = project_path / "model" / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # Train with checkpoint saving
    for seed in seeds:
        train_result = run_train(project_path, config, seed, checkpoint_dir=checkpoint_dir)
        if train_result.return_code != 0:
            return {
                "phase_id": "baseline",
                "status": "failed",
                "error": f"Training failed for seed {seed}",
                "stderr": train_result.stderr[:500],
            }

    # Evaluate using correct checkpoint path (not broken eval_command with {seed})
    best_model = checkpoint_dir / "best_model.zip"
    aggregated = {}
    if best_model.exists():
        import subprocess as sp
        import sys
        eval_script = project_path / ".research-agent" / "evaluate.py"
        python_exe = sys.executable
        n_eps = config.evaluation.test_episodes
        cmd = f'"{python_exe}" "{eval_script}" "{best_model}" --episodes {n_eps}'
        proc = sp.run(cmd, shell=True, cwd=str(project_path), capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            return {
                "phase_id": "baseline",
                "status": "failed",
                "error": f"Evaluation failed",
                "stderr": proc.stderr[:500],
            }
        # Parse metrics
        from research_agent.execution.metric_parser import _extract_from_text
        metric_regex = config.metrics.metric_regex or {
            "completion_rate": r"completion_rate\s*=\s*([\d.]+)",
            "reward": r"reward\s*=\s*([\d.]+)",
            "lateral_error": r"lateral_error\s*=\s*([\d.]+)",
        }
        parsed = {}
        for name, pattern in metric_regex.items():
            val = _extract_from_text(proc.stdout, proc.stderr, name, pattern)
            parsed[name] = val
        aggregated = {name: {"mean": v, "std": 0.0, "min": v, "max": v, "n": 1, "values": [v]}
                      for name, v in parsed.items() if v is not None}
    else:
        return {
            "phase_id": "baseline",
            "status": "failed",
            "error": "No best_model.zip produced by training",
        }

    # Save baseline metrics
    baseline_path = work_dir / "artifacts" / "baseline_metrics.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    with open(baseline_path, "w", encoding="utf-8") as f:
        json.dump(aggregated, f, indent=2)

    # Archive baseline checkpoint
    best_model = checkpoint_dir / "best_model.zip"
    if best_model.exists():
        shutil.copy2(best_model, checkpoint_dir / "best_baseline.zip")

    # Save baseline files (env.py etc.) for fair comparison
    _save_baseline_files(project_path, work_dir, config)

    # Fair evaluation: test best model with N episodes
    fair_eval = {}
    if best_model.exists():
        n_eps = config.evaluation.test_episodes
        print(f"[BASELINE] Running {n_eps}-episode fair evaluation...", flush=True)
        fair_eval = _run_fair_evaluation(project_path, work_dir, best_model, config)
        if fair_eval.get("ok"):
            fm = fair_eval["metrics"]
            print(f"[BASELINE] Fair eval: reward={fm.get('reward')}, "
                  f"completion_rate={fm.get('completion_rate')}, "
                  f"lateral_error={fm.get('lateral_error')}", flush=True)

    # Update state
    state = read_state_json(work_dir)
    state["baseline_metrics"] = aggregated
    if fair_eval.get("ok"):
        state["baseline_fair_eval"] = fair_eval["metrics"]
    write_state_json(work_dir, state)

    return {
        "phase_id": "baseline",
        "status": "completed",
        "metrics": aggregated,
        "fair_eval": fair_eval.get("metrics", {}),
        "checkpoint": str(checkpoint_dir / "best_baseline.zip"),
    }


def _run_fair_evaluation(
    project_path: Path,
    work_dir: Path,
    checkpoint_path: Path,
    config: AgentConfig,
    n_episodes: int | None = None,
    timeout: int = 600,
) -> dict:
    """Run fair evaluation with file backup/restore for env.py.

    Workflow:
    1. Backup current modifiable files
    2. Restore baseline files from artifacts
    3. Run evaluate.py with checkpoint
    4. Restore modified files from backup

    Args:
        project_path: Project root directory.
        work_dir: .research-agent work directory.
        checkpoint_path: Path to the model .zip checkpoint.
        config: Agent configuration (for metric_regex).
        n_episodes: Number of test episodes (default from config).
        timeout: Timeout in seconds.

    Returns:
        Dict with: ok, metrics, stdout, error.
    """
    import subprocess as sp
    import sys

    if n_episodes is None:
        n_episodes = config.evaluation.test_episodes

    # Step 1: Backup current modifiable files
    modifiable_files = config.evaluation.modifiable_files
    backup_contents = {}
    for fname in modifiable_files:
        fpath = project_path / fname
        if fpath.exists():
            backup_contents[fname] = fpath.read_text(encoding="utf-8")

    # Step 2: Restore baseline files
    for fname in modifiable_files:
        src = work_dir / "artifacts" / f"baseline_{fname}"
        dst = project_path / fname
        if src.exists():
            shutil.copy2(src, dst)

    # Step 3: Run evaluate.py
    eval_script = project_path / ".research-agent" / "evaluate.py"
    if not eval_script.exists():
        # Fallback to test_best_model.py for HRRL2 compatibility
        eval_script = project_path / "test_best_model.py"

    python_exe = sys.executable
    cmd = f'"{python_exe}" "{eval_script}" "{checkpoint_path}" --episodes {n_episodes}'

    result = {"ok": False, "metrics": {}, "stdout": "", "error": ""}
    try:
        proc = sp.run(
            cmd, shell=True, cwd=str(project_path),
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0:
            result["error"] = proc.stderr[:500]
            result["stdout"] = proc.stdout[:500]
        else:
            # Parse metrics from stdout
            from research_agent.execution.metric_parser import _extract_from_text
            metric_regex = config.metrics.metric_regex
            if not metric_regex:
                # Default regex patterns
                metric_regex = {
                    "completion_rate": r"completion_rate\s*=\s*([\d.]+)",
                    "reward": r"reward\s*=\s*([\d.]+)",
                    "lateral_error": r"lateral_error\s*=\s*([\d.]+)",
                }
            metrics = {}
            for name, pattern in metric_regex.items():
                val = _extract_from_text(proc.stdout, proc.stderr, name, pattern)
                metrics[name] = val
            result = {"ok": True, "metrics": metrics, "stdout": proc.stdout[:2000], "error": ""}
    except sp.TimeoutExpired:
        result["error"] = "timeout"
    except Exception as e:
        result["error"] = str(e)

    # Step 4: Restore modified files from backup
    for fname, content in backup_contents.items():
        (project_path / fname).write_text(content, encoding="utf-8")

    return result


def _save_baseline_files(project_path: Path, work_dir: Path, config: AgentConfig) -> None:
    """Save baseline copies of modifiable files."""
    artifacts_dir = work_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    for fname in config.evaluation.modifiable_files:
        src = project_path / fname
        if src.exists():
            shutil.copy2(src, artifacts_dir / f"baseline_{fname}")


def _execute_optimizer_phase(
    work_dir: Path,
    config: AgentConfig,
    phase: dict,
    project_path: Path,
    resource_usage: dict,
    ideas: list[dict] | None = None,
    sampler=None,
    mock_llm: bool = False,
) -> dict:
    """Execute an optimizer phase with full propose→apply→eval→accept→rollback cycle.

    Uses PaperSampler for iterative method selection when available.
    Each candidate gets a fresh batch of 1-2 methods from the next untried category.

    For each candidate (up to phase budget):
    1. Get next method batch from sampler (or fallback to static ideas)
    2. Optimizer proposes a candidate patch using these ideas
    3. PatchManager applies the patch (compilation check)
    4. Full eval (trains model with modified reward)
    5. Fair evaluation (eval with baseline reward)
    6. Accept/reject decision (composite scoring)
    7. If accepted: git snapshot, update state
    8. If rejected: rollback patch

    Note: Screening eval removed — RL early episodes often fail,
    so single-seed screening unfairly rejects good candidates.
    """
    phase_id = phase.get("phase_id", "unknown")
    optimizer_name = phase.get("optimizer", "unknown")
    budget = phase.get("budget", {})

    # Load baseline metrics
    state = read_state_json(work_dir)
    baseline_metrics = state.get("baseline_metrics", {})

    # Get optimizer class
    from research_agent.optimizers import get_optimizer_class
    try:
        opt_cls = get_optimizer_class(optimizer_name)
    except KeyError:
        return {
            "phase_id": phase_id,
            "status": "failed",
            "error": f"Unknown optimizer: {optimizer_name}",
        }

    optimizer = opt_cls(work_dir, config, project_path, mock_llm=mock_llm)
    patch_manager = PatchManager(project_path, work_dir)

    # Pre-run confirmation: show config and ask user to confirm
    max_steps = config.execution.max_steps
    print("=" * 80, flush=True)
    print(f"[OPTIMIZER CONFIG] phase={phase_id} optimizer={optimizer_name}", flush=True)
    print(f"  Training steps per candidate: {max_steps}", flush=True)
    print(f"  Train command: {config.execution.train_command}", flush=True)
    print(f"  Full eval seeds: {config.execution.full_eval_seeds}", flush=True)
    print(f"  Test episodes: {config.evaluation.test_episodes}", flush=True)
    print(f"  Wall clock limit: {config.budget.wall_clock_hours}h", flush=True)

    # Check API key
    import os
    api_key_env = config.llm.api_key_env
    api_key = os.environ.get(api_key_env, "")
    if not api_key and not mock_llm:
        print(f"\n[WARNING] {api_key_env} not set. LLM calls will fail.", flush=True)
        key_input = input(f"Enter {api_key_env} (or 'skip' to use mock-llm): ").strip()
        if key_input and key_input.lower() != "skip":
            os.environ[api_key_env] = key_input
            print(f"[OK] {api_key_env} set", flush=True)
        else:
            mock_llm = True
            print(f"[OK] Using mock-llm mode", flush=True)
    elif api_key:
        print(f"  API key: {api_key_env}={api_key[:8]}...", flush=True)

    # Initialize auto_push early for baseline verification
    git_cfg = getattr(config, 'git', None)
    auto_push = getattr(git_cfg, 'auto_push', False) if git_cfg else False

    # Verify baseline_env.py consistency
    baseline_env_path = work_dir / "artifacts" / "baseline_env.py"
    current_env_path = project_path / "env.py"
    if baseline_env_path.exists() and current_env_path.exists():
        import hashlib
        baseline_hash = hashlib.md5(baseline_env_path.read_bytes()).hexdigest()
        current_hash = hashlib.md5(current_env_path.read_bytes()).hexdigest()
        if baseline_hash != current_hash:
            print(f"\n[WARNING] baseline_env.py differs from current env.py!", flush=True)
            print(f"  baseline_env.py: {baseline_hash}", flush=True)
            print(f"  current env.py:  {current_hash}", flush=True)
            if not auto_push:
                fix_input = input("Update baseline_env.py to match current env.py? [y/N]: ").strip().lower()
                if fix_input in ("y", "yes"):
                    import shutil
                    shutil.copy2(current_env_path, baseline_env_path)
                    print("[OK] baseline_env.py updated", flush=True)
                else:
                    print("[WARNING] Continuing with mismatched baseline_env.py", flush=True)
            else:
                # Auto-update in auto_push mode
                import shutil
                shutil.copy2(current_env_path, baseline_env_path)
                print("[AUTO] baseline_env.py updated to match current env.py", flush=True)
    elif not baseline_env_path.exists():
        print(f"\n[WARNING] baseline_env.py not found in artifacts/", flush=True)
        if current_env_path.exists():
            import shutil
            shutil.copy2(current_env_path, baseline_env_path)
            print(f"[AUTO] Created baseline_env.py from current env.py", flush=True)

    # Set active categories on sampler
    if sampler is not None:
        active_cats = config.optimizer.active_categories
        if active_cats:
            sampler.set_active_categories(active_cats)
            print(f"  Active categories: {active_cats}", flush=True)
        else:
            all_cats = sampler.get_all_categories()
            print(f"  Available categories ({len(all_cats)}):", flush=True)
            for cat in all_cats:
                print(f"    {cat['category']}: {cat['remaining']} methods remaining (priority={cat['priority']})", flush=True)

    print("=" * 80, flush=True)

    # Git repo confirmation
    from research_agent.core.git_guard import _is_git_repo, _run_git, git_snapshot
    is_repo = _is_git_repo(project_path)
    git_remote = None
    git_branch = None
    if is_repo:
        current_branch = _run_git(project_path, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
        remotes = _run_git(project_path, ["remote"]).strip().split("\n")
        print(f"\n[GIT] Current branch: {current_branch}", flush=True)
        print(f"[GIT] Available remotes: {remotes}", flush=True)

        # Check if git push is pre-configured
        git_cfg = getattr(config, 'git', None)
        auto_push = getattr(git_cfg, 'auto_push', False) if git_cfg else False
        if auto_push:
            git_remote = getattr(git_cfg, 'push_remote', None) or (remotes[0] if remotes else None)
            git_branch = getattr(git_cfg, 'push_branch', None) or current_branch
            print(f"[GIT] Auto-push configured: {git_remote}/{git_branch}", flush=True)
        else:
            push_input = input(f"Push to remote? (remote name or 'skip') [{remotes[0] if remotes else 'skip'}]: ").strip()
            if push_input and push_input.lower() != "skip":
                git_remote = push_input
                git_branch = input(f"Push to branch? [{current_branch}]: ").strip() or current_branch
                print(f"[GIT] Will push to {git_remote}/{git_branch}", flush=True)
            else:
                print("[GIT] Will commit locally (no push)", flush=True)
    else:
        print("[GIT] Not a git repo, will skip git operations", flush=True)

    # Show summary
    print(f"\n[SUMMARY] What will happen:", flush=True)
    print(f"  1. Each candidate: train {max_steps} steps -> evaluate -> fair eval -> accept/reject", flush=True)
    print(f"  2. Estimated time per candidate: ~5 minutes", flush=True)
    if sampler is not None:
        remaining = sum(
            sum(1 for m in methods if m.get("method_id") not in sampler._tried_ids)
            for methods in sampler._methods_by_category.values()
        )
        print(f"  3. Methods remaining: {remaining}", flush=True)
    print("=" * 80, flush=True)

    if auto_push:
        print("[AUTO] Configuration auto-confirmed (auto_push=true)", flush=True)
    else:
        confirm = input("Confirm above configuration? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("[ABORT] User cancelled optimizer.", flush=True)
            return {"phase_id": phase_id, "status": "cancelled", "reason": "user_declined"}

    # Initialize version tracker
    version_tracker = VersionTracker(work_dir)

    candidates_evaluated = 0
    best_candidate = None
    candidate_results = []

    # Checkpoint base directory
    checkpoint_base = project_path / "model" / "checkpoints"

    # Stopping: only wall_clock and category exhaustion
    wall_clock_limit = config.budget.wall_clock_hours * 3600
    start_time = time.monotonic()

    while True:
        # Check wall clock
        elapsed = time.monotonic() - start_time
        if elapsed >= wall_clock_limit:
            print(f"\n[STOP] Wall clock limit reached ({config.budget.wall_clock_hours}h)", flush=True)
            break

        # 1. Get fresh ideas for this candidate (category-based selection)
        candidate_ideas = ideas
        batch: list[dict] = []
        current_category = None
        if sampler is not None:
            current_category = sampler.get_current_category()
            batch = sampler.get_next_batch(batch_size=2)
            if not batch:
                print(f"\n[STOP] All categories exhausted.", flush=True)
                break
            candidate_ideas = batch
            cat_display = current_category or "auto"
            print(f"\n[CATEGORY] Current: {cat_display} | Methods: {[m.get('method_id','')[:20] for m in batch]}", flush=True)

        # 2. Propose candidate
        version_id = version_tracker.next_version_id()

        # Per-version checkpoint directory
        version_checkpoint_dir = checkpoint_base / version_id
        version_checkpoint_dir.mkdir(parents=True, exist_ok=True)

        candidate = optimizer.propose_candidate(phase, baseline_metrics, candidate_ideas)
        resource_usage["candidates_proposed"] = resource_usage.get("candidates_proposed", 0) + 1

        # Extract version tracking info
        modified_files = extract_modified_files(candidate)
        reward_formula = extract_reward_formula(candidate, candidate_ideas)
        source_methods = extract_source_methods(candidate_ideas)

        # Helper to mark methods with final status
        def _mark_batch(status: str, accepted: bool | None = None, reason: str = ""):
            if batch and sampler is not None:
                sampler.mark_used(
                    batch,
                    candidate_id=candidate.candidate_id,
                    status=status,
                    phase_id=phase_id,
                    accepted=accepted,
                    reason=reason,
                    metrics_before=baseline_metrics,
                )

        # Handle empty patch (no-op)
        if not candidate.patch_diff or not candidate.patch_diff.strip():
            candidate.status = "rejected"
            candidate.rejection_reason = "empty_patch"
            optimizer._log_candidate(candidate)
            _mark_batch("noop", reason="empty_patch")

            # Log version with rejection
            version_tracker.log_version(
                version_id=version_id,
                candidate_id=candidate.candidate_id,
                reward_formula=reward_formula,
                modified_files=modified_files,
                metrics_before=baseline_metrics,
                metrics_after=None,
                accepted=False,
                rejection_reason="empty_patch",
                source_methods=source_methods,
                description=candidate.description,
            )

            candidate_results.append(candidate.to_dict())
            continue

        # 3. Apply patch and validate compilation (with LLM repair retry)
        patch_applied = False
        patch_repair_attempts = 30
        for patch_attempt in range(patch_repair_attempts):
            try:
                apply_result = patch_manager.apply_and_validate(candidate)
                if apply_result.get("applied"):
                    patch_applied = True
                    break
                else:
                    # Not applied but no exception
                    reason_str = apply_result.get("reason", "unknown")
                    errors = apply_result.get("errors", [])
                    error_detail = f"{reason_str}: {'; '.join(errors[:3])}" if errors else reason_str
                    print(f"[PATCH-FIX] Attempt {patch_attempt+1}: apply failed - {error_detail}", flush=True)

                    # Try LLM repair
                    if patch_attempt < patch_repair_attempts - 1:
                        repaired = _repair_patch_diff(optimizer, candidate.patch_diff, error_detail)
                        if repaired:
                            candidate.patch_diff = repaired
                            print(f"[PATCH-FIX] Attempt {patch_attempt+1}: LLM repaired diff, retrying...", flush=True)
                            continue

            except PatchApplyError as e:
                print(f"[PATCH-FIX] Attempt {patch_attempt+1}: PatchApplyError - {e.message[:100]}", flush=True)

                # Try LLM repair
                if patch_attempt < patch_repair_attempts - 1:
                    repaired = _repair_patch_diff(optimizer, candidate.patch_diff, e.message)
                    if repaired:
                        candidate.patch_diff = repaired
                        print(f"[PATCH-FIX] Attempt {patch_attempt+1}: LLM repaired diff, retrying...", flush=True)
                        continue

        if not patch_applied:
            candidate.status = "rejected"
            candidate.rejection_reason = f"Patch apply failed after {patch_repair_attempts} repair attempts"
            optimizer._log_candidate(candidate)
            _mark_batch("error", accepted=False, reason=candidate.rejection_reason)
            version_tracker.log_version(
                version_id=version_id,
                candidate_id=candidate.candidate_id,
                reward_formula=reward_formula,
                modified_files=modified_files,
                metrics_before=baseline_metrics,
                metrics_after=None,
                accepted=False,
                rejection_reason=candidate.rejection_reason,
                source_methods=source_methods,
                description=candidate.description,
            )
            candidate_results.append(candidate.to_dict())
            continue

        # Track applied patch in memory (write at end of iteration)
        state = read_state_json(work_dir)
        state = add_applied_patch(state, candidate.candidate_id)

        # 3.5. Independent strategy: ensure env.py is at baseline before training
        # This ensures each candidate is evaluated independently
        baseline_env_path = work_dir / "artifacts" / "baseline_env.py"
        env_file = project_path / "env.py"
        if baseline_env_path.exists() and env_file.exists():
            import shutil
            shutil.copy2(baseline_env_path, env_file)
            print(f"[INDEPENDENT] Restored baseline env.py before training", flush=True)

        # Re-apply the current candidate's patch on top of baseline (with LLM repair retry)
        reapply_ok = False
        for reapply_attempt in range(30):
            try:
                apply_result = patch_manager.apply_patch(candidate)
                if apply_result.get("applied"):
                    reapply_ok = True
                    break
                # Not applied, try LLM repair
                reason = apply_result.get("reason", "unknown")
                print(f"[RE-APPLY] Attempt {reapply_attempt+1}: failed - {reason}", flush=True)
                if reapply_attempt < 29:
                    repaired = _repair_patch_diff(optimizer, candidate.patch_diff, reason)
                    if repaired:
                        candidate.patch_diff = repaired
                        continue
            except PatchApplyError as e:
                print(f"[RE-APPLY] Attempt {reapply_attempt+1}: PatchApplyError - {e.message[:100]}", flush=True)
                if reapply_attempt < 29:
                    repaired = _repair_patch_diff(optimizer, candidate.patch_diff, e.message)
                    if repaired:
                        candidate.patch_diff = repaired
                        continue

        if not reapply_ok:
            candidate.status = "rejected"
            candidate.rejection_reason = "Patch re-apply failed after LLM repair attempts"
            optimizer._log_candidate(candidate)
            _mark_batch("error", accepted=False, reason=candidate.rejection_reason)
            version_tracker.log_version(
                version_id=version_id,
                candidate_id=candidate.candidate_id,
                reward_formula=reward_formula,
                modified_files=modified_files,
                metrics_before=baseline_metrics,
                metrics_after=None,
                accepted=False,
                rejection_reason=candidate.rejection_reason,
                source_methods=source_methods,
                description=candidate.description,
            )
            candidate_results.append(candidate.to_dict())
            continue

        # 3.6. Verify env.py compiles after patch — auto-fix if needed
        env_file = project_path / "env.py"
        if env_file.exists():
            try:
                env_content = env_file.read_text(encoding="utf-8-sig")
                compile(env_content.lstrip("﻿"), str(env_file), "exec")
            except SyntaxError:
                # Auto-fix: try indentation fix + LLM fix before rejecting
                print(f"[AUTO-FIX] {version_id}: attempting to fix compilation errors...", flush=True)
                fix_ok, fix_err = _auto_fix_compilation(env_file, optimizer)
                if not fix_ok:
                    candidate.status = "rejected"
                    candidate.rejection_reason = f"Post-patch compilation failed after auto-fix: {fix_err}"
                    optimizer._log_candidate(candidate)
                    _mark_batch("error", accepted=False, reason=candidate.rejection_reason)
                    version_tracker.log_version(
                        version_id=version_id,
                        candidate_id=candidate.candidate_id,
                        reward_formula=reward_formula,
                        modified_files=modified_files,
                        metrics_before=baseline_metrics,
                        metrics_after=None,
                        accepted=False,
                        rejection_reason=candidate.rejection_reason,
                        source_methods=source_methods,
                        description=candidate.description,
                    )
                    candidate_results.append(candidate.to_dict())
                    # Rollback the patch
                    try:
                        patch_manager.rollback_patch(candidate)
                    except Exception:
                        pass
                    continue
                print(f"[AUTO-FIX] {version_id}: compilation fixed successfully", flush=True)

        # 4. Train model with modified reward, then evaluate
        # NOTE: Screening eval removed — RL early episodes often fail,
        # so single-seed screening unfairly rejects good candidates.
        seeds = config.execution.full_eval_seeds
        training_failed = False
        base_timeout = config.execution.timeout_seconds_per_seed

        for seed in seeds:
            print(f"[TRAIN] seed={seed}, timesteps={config.execution.max_steps}", flush=True)
            train_result = run_train(project_path, config, seed, checkpoint_dir=version_checkpoint_dir)

            # Handle timeout: retry with longer timeout
            if train_result.timed_out:
                extended_timeout = int(base_timeout * 2)
                print(f"[TRAIN] TIMEOUT for seed={seed} ({base_timeout}s), retrying with {extended_timeout}s...", flush=True)
                train_result = run_train(project_path, config, seed, checkpoint_dir=version_checkpoint_dir,
                                         timeout_override=extended_timeout)
                if train_result.timed_out:
                    print(f"[TRAIN] Still TIMEOUT after extended retry ({extended_timeout}s)", flush=True)
                    training_failed = True
                    continue
                elif train_result.return_code == 0:
                    print(f"[TRAIN] seed={seed} succeeded on extended timeout retry ({train_result.duration_seconds}s)", flush=True)
                    continue

            if train_result.return_code != 0:
                print(f"[TRAIN] FAILED for seed={seed}: return_code={train_result.return_code}", flush=True)
                print(f"[TRAIN] stderr: {train_result.stderr[:500]}", flush=True)
                print(f"[TRAIN] stdout: {train_result.stdout[-500:]}", flush=True)

                # LLM-based training error fix loop
                error_output = (train_result.stderr or "") + "\n" + (train_result.stdout or "")
                print(f"[TRAIN-FIX] {version_id}: attempting LLM-based fix for training error...", flush=True)
                fix_ok, fix_err = _fix_training_error(project_path, optimizer, error_output)
                if fix_ok:
                    print(f"[TRAIN-FIX] {version_id}: fix applied, retrying training...", flush=True)
                    # Re-verify compilation after fix
                    env_file = project_path / "env.py"
                    try:
                        env_content = env_file.read_text(encoding="utf-8-sig")
                        compile(env_content.lstrip("﻿"), str(env_file), "exec")
                    except SyntaxError:
                        print(f"[TRAIN-FIX] {version_id}: fix introduced syntax error, running auto-fix...", flush=True)
                        _auto_fix_compilation(env_file, optimizer, max_attempts=10)

                    # Retry training with the fix
                    retry_result = run_train(project_path, config, seed, checkpoint_dir=version_checkpoint_dir)
                    if retry_result.return_code != 0:
                        print(f"[TRAIN-FIX] {version_id}: retry still failed after fix (return_code={retry_result.return_code})", flush=True)
                        training_failed = True
                    else:
                        print(f"[TRAIN-FIX] {version_id}: retry succeeded after fix ({retry_result.duration_seconds}s)", flush=True)
                else:
                    print(f"[TRAIN-FIX] {version_id}: could not fix training error: {fix_err}", flush=True)
                    training_failed = True
            else:
                print(f"[TRAIN] seed={seed} done in {train_result.duration_seconds}s", flush=True)

        # If all training attempts failed, reject the candidate
        if training_failed:
            candidate.status = "rejected"
            candidate.rejection_reason = f"Training failed after LLM fix attempts"
            optimizer._log_candidate(candidate)
            _mark_batch("error", accepted=False, reason=candidate.rejection_reason)
            version_tracker.log_version(
                version_id=version_id,
                candidate_id=candidate.candidate_id,
                reward_formula=reward_formula,
                modified_files=modified_files,
                metrics_before=baseline_metrics,
                metrics_after=None,
                accepted=False,
                rejection_reason=candidate.rejection_reason,
                source_methods=source_methods,
                description=candidate.description,
            )
            candidate_results.append(candidate.to_dict())
            # Clean up potentially corrupt checkpoint
            if version_checkpoint_dir.exists():
                try:
                    shutil.rmtree(version_checkpoint_dir)
                    print(f"[CLEANUP] Removed corrupt checkpoint dir {version_checkpoint_dir}", flush=True)
                except OSError:
                    pass
            try:
                patch_manager.rollback_patch(candidate)
            except Exception:
                pass
            continue

        # 5. Fair evaluation with eval failure retry + LLM fix
        # Uses correct checkpoint path (not broken eval_command with {seed})
        version_model = version_checkpoint_dir / "best_model.zip"
        fair_metrics = {}
        eval_max_attempts = 30

        if version_model.exists():
            n_eps = config.evaluation.test_episodes
            eval_script = project_path / ".research-agent" / "evaluate.py"
            python_exe = sys.executable
            eval_timeout = config.execution.timeout_seconds_per_seed

            for eval_attempt in range(eval_max_attempts):
                print(f"[FAIR EVAL] {version_id}: {n_eps} episodes (attempt {eval_attempt+1}/{eval_max_attempts})...", flush=True)
                import subprocess as sp
                cmd = f'"{python_exe}" "{eval_script}" "{version_model}" --episodes {n_eps}'
                try:
                    proc = sp.run(
                        cmd, shell=True, cwd=str(project_path),
                        capture_output=True, text=True, timeout=eval_timeout,
                    )
                    if proc.returncode == 0:
                        fair_metrics = parse_metrics(proc.stdout, proc.stderr, config, work_dir)
                        print(f"[FAIR EVAL] {version_id}: reward={fair_metrics.get('reward')}, "
                              f"completion_rate={fair_metrics.get('completion_rate')}, "
                              f"lateral_error={fair_metrics.get('lateral_error')}", flush=True)
                        break
                    else:
                        print(f"[FAIR EVAL] {version_id}: FAILED (attempt {eval_attempt+1}) - return_code={proc.returncode}", flush=True)
                        eval_error = (proc.stderr or "") + "\n" + (proc.stdout or "")
                        print(f"[FAIR EVAL] stderr: {proc.stderr[:300]}", flush=True)

                        # LLM-based eval error fix
                        if eval_attempt < eval_max_attempts - 1:
                            print(f"[EVAL-FIX] {version_id}: attempting LLM-based fix for eval error...", flush=True)
                            fix_ok, fix_err = _fix_training_error(project_path, optimizer, eval_error)
                            if fix_ok:
                                print(f"[EVAL-FIX] {version_id}: fix applied, retrying eval...", flush=True)
                                # Re-verify compilation after fix
                                env_file = project_path / "env.py"
                                try:
                                    env_content = env_file.read_text(encoding="utf-8-sig")
                                    compile(env_content.lstrip("﻿"), str(env_file), "exec")
                                except SyntaxError:
                                    _auto_fix_compilation(env_file, optimizer, max_attempts=30)
                            else:
                                print(f"[EVAL-FIX] {version_id}: could not fix eval error: {fix_err}", flush=True)
                except sp.TimeoutExpired:
                    print(f"[FAIR EVAL] {version_id}: TIMEOUT (attempt {eval_attempt+1}), retrying with extended timeout...", flush=True)
                    # Retry with 2x timeout
                    try:
                        extended_cmd = f'"{python_exe}" "{eval_script}" "{version_model}" --episodes {n_eps}'
                        proc = sp.run(
                            extended_cmd, shell=True, cwd=str(project_path),
                            capture_output=True, text=True, timeout=eval_timeout * 2,
                        )
                        if proc.returncode == 0:
                            fair_metrics = parse_metrics(proc.stdout, proc.stderr, config, work_dir)
                            print(f"[FAIR EVAL] {version_id}: succeeded on extended timeout retry", flush=True)
                            break
                        else:
                            print(f"[FAIR EVAL] {version_id}: extended retry also failed (return_code={proc.returncode})", flush=True)
                    except sp.TimeoutExpired:
                        print(f"[FAIR EVAL] {version_id}: extended retry also timed out", flush=True)
                    except Exception as e2:
                        print(f"[FAIR EVAL] {version_id}: extended retry exception - {e2}", flush=True)
                except Exception as e:
                    print(f"[FAIR EVAL] {version_id}: EXCEPTION (attempt {eval_attempt+1}) - {e}", flush=True)

            # Update candidate eval result
            candidate.full_eval_result = {
                "metrics": fair_metrics,
                "failed": not bool(fair_metrics),
                "seeds": config.execution.full_eval_seeds,
            }
            if not fair_metrics:
                candidate.status = "rejected"
                candidate.rejection_reason = "Full eval failed after retries"
            else:
                candidate.status = "evaluated"
            optimizer._log_candidate(candidate)
        else:
            print(f"[FAIR EVAL] {version_id}: no checkpoint at {version_model}, skipping eval", flush=True)
            candidate.full_eval_result = {"metrics": {}, "failed": True, "seeds": config.execution.full_eval_seeds}
            candidate.status = "rejected"
            candidate.rejection_reason = "No checkpoint produced"
            optimizer._log_candidate(candidate)

        resource_usage["full_evals_run"] = resource_usage.get("full_evals_run", 0) + 1

        # Persist state after eval
        _persist_state(work_dir, state, resource_usage)

        # 7. Accept or reject using composite scoring
        from research_agent.core.scoring import compute_composite_score, make_accept_decision
        from research_agent.core.metrics_utils import flatten_metrics

        baseline_fair = state.get("baseline_fair_eval", {})
        # Ensure both metrics are in flat format for scoring
        flat_fair = flatten_metrics(fair_metrics)
        flat_baseline = flatten_metrics(baseline_fair)
        scoring = compute_composite_score(flat_fair, flat_baseline, config.evaluation)
        decision = make_accept_decision(scoring, config.evaluation)
        was_accepted = decision["accepted"]

        candidate.rejection_reason = decision["reason"] if not was_accepted else None

        print(f"\n[DECISION] {version_id}: {'ACCEPTED' if was_accepted else 'REJECTED'} "
              f"(score={decision['final_score']:.4f}, reason={decision['reason']})", flush=True)

        # 8. Git commit for every candidate (accepted or rejected)
        if is_repo:
            if was_accepted:
                commit_msg = f"research-agent: ACCEPTED {version_id} ({candidate.candidate_id})\n\nfair_eval={fair_metrics}\nscore={decision['final_score']}"
            else:
                commit_msg = f"research-agent: REJECTED {version_id} ({candidate.candidate_id})\n\nfair_eval={fair_metrics}\nscore={decision['final_score']}\nreason={decision['reason']}"

            try:
                commit_result = git_snapshot(project_path, work_dir, commit_msg)
                commit_hash = commit_result.get("commit", "none")
                print(f"[GIT] Committed {version_id}: {commit_hash[:8] if commit_hash != 'none' else 'no changes'}", flush=True)

                # Push if configured
                if git_remote and commit_hash and commit_hash != "none":
                    try:
                        push_args = ["push", git_remote]
                        if git_branch:
                            push_args.append(git_branch)
                        _run_git(project_path, push_args)
                        print(f"[GIT] Pushed to {git_remote}/{git_branch}", flush=True)
                    except Exception as push_err:
                        print(f"[GIT] Push failed: {push_err}", flush=True)
            except Exception as git_err:
                print(f"[GIT] Commit failed: {git_err}", flush=True)

        # 9. Post-decision operations
        if was_accepted:
            # ACCEPTED: archive checkpoint as current_best
            best_candidate = candidate.to_dict()

            if version_model.exists():
                shutil.copy2(version_model, checkpoint_base / f"{version_id}_best.zip")
                shutil.copy2(version_model, checkpoint_base / "current_best.zip")

            state["current_best"] = candidate.to_dict()
            _mark_batch("accepted", accepted=True)
            print(f"[ACCEPTED] {version_id}: checkpoint archived as current_best.zip", flush=True)
        else:
            # REJECTED: keep checkpoint for reference
            _mark_batch("rejected", accepted=False, reason=decision["reason"])
            print(f"[REJECTED] {version_id}: checkpoint kept for reference", flush=True)

        # 10. Independent strategy: rollback env.py to baseline after each candidate
        # This ensures the next candidate starts from a clean baseline
        if baseline_env_path.exists() and env_file.exists():
            shutil.copy2(baseline_env_path, env_file)
            print(f"[INDEPENDENT] Rolled back env.py to baseline", flush=True)

        # Record category result for tracking improvement
        if sampler is not None and current_category:
            sampler.record_category_result(current_category, decision["final_score"])

        # Log version with fair eval metrics (always recorded)
        version_tracker.log_version(
            version_id=version_id,
            candidate_id=candidate.candidate_id,
            reward_formula=reward_formula,
            modified_files=modified_files,
            metrics_before=baseline_metrics,
            metrics_after=fair_metrics,
            accepted=was_accepted,
            rejection_reason=decision["reason"] if not was_accepted else None,
            source_methods=source_methods,
            description=candidate.description,
        )

        candidate_results.append(candidate.to_dict())
        candidates_evaluated += 1

        # Persist state after each candidate
        _persist_state(work_dir, state, resource_usage)

    # Safety check on current state - use current_best checkpoint with correct eval command
    safety_metrics = {}
    current_best_model = checkpoint_base / "current_best.zip"
    if current_best_model.exists():
        import subprocess as sp
        eval_script = project_path / ".research-agent" / "evaluate.py"
        python_exe = sys.executable
        n_eps = config.evaluation.test_episodes
        cmd = f'"{python_exe}" "{eval_script}" "{current_best_model}" --episodes {n_eps}'
        try:
            proc = sp.run(cmd, shell=True, cwd=str(project_path), capture_output=True, text=True, timeout=600)
            if proc.returncode == 0:
                safety_metrics = parse_metrics(proc.stdout, proc.stderr, config, work_dir)
        except Exception as e:
            print(f"[SAFETY] Eval failed: {e}", flush=True)
    safety_result = check_safety_metrics(
        {k: v for k, v in safety_metrics.items() if isinstance(v, (int, float))},
        config,
    )

    # Write final state
    _persist_state(work_dir, state, resource_usage)

    return {
        "phase_id": phase_id,
        "status": "completed",
        "optimizer": optimizer_name,
        "candidates_evaluated": candidates_evaluated,
        "best_candidate": best_candidate,
        "candidate_results": candidate_results,
        "safety_metrics": aggregated,
        "safety_check": safety_result,
    }


def _execute_joint_validation(
    work_dir: Path,
    config: AgentConfig,
    phase: dict,
    project_path: Path,
) -> dict:
    """Execute joint validation phase with confirmation seeds."""
    confirmation_seeds = config.execution.confirmation_seeds
    if not confirmation_seeds:
        confirmation_seeds = config.execution.full_eval_seeds

    eval_results = run_full_eval(project_path, config, confirmation_seeds, work_dir)

    for r in eval_results:
        if r.return_code != 0:
            return {
                "phase_id": "joint-validation",
                "status": "failed",
                "error": "Joint validation eval failed",
                "stderr": r.stderr[:500],
            }

    aggregated = aggregate_metrics(eval_results)

    # Check safety
    safety_result = check_safety_metrics(
        {k: v["mean"] for k, v in aggregated.items()},
        config,
    )

    # Compare with baseline
    state = read_state_json(work_dir)
    baseline = state.get("baseline_metrics", {})
    comparison = _compare_with_baseline(aggregated, baseline, config)

    return {
        "phase_id": "joint-validation",
        "status": "completed",
        "confirmation_metrics": aggregated,
        "safety_check": safety_result,
        "baseline_comparison": comparison,
    }


def _compare_with_baseline(
    current: dict[str, dict[str, float]],
    baseline: dict[str, dict[str, float]],
    config: AgentConfig,
) -> dict[str, Any]:
    """Compare current metrics with baseline."""
    comparison: dict[str, Any] = {}
    primary_metrics = config.metrics.primary

    for metric in primary_metrics:
        name = metric.get("name", "") if isinstance(metric, dict) else str(metric)
        direction = metric.get("direction", "maximize") if isinstance(metric, dict) else "maximize"

        current_val = current.get(name, {}).get("mean")
        baseline_val = baseline.get(name, {}).get("mean")

        if current_val is None or baseline_val is None:
            comparison[name] = {"status": "missing_data"}
            continue

        if baseline_val == 0:
            pct_change = 0.0
        elif direction == "maximize":
            pct_change = (current_val - baseline_val) / abs(baseline_val)
        else:
            pct_change = (baseline_val - current_val) / abs(baseline_val)

        comparison[name] = {
            "current": current_val,
            "baseline": baseline_val,
            "pct_change": round(pct_change * 100, 4),
            "improved": pct_change > 0,
        }

    return comparison


def _is_budget_exhausted(
    resource_usage: dict,
    budget: dict,
    config: AgentConfig,
) -> bool:
    """Check if wall clock budget is exhausted."""
    max_wall = budget.get("wall_clock_hours", config.budget.wall_clock_hours) * 3600
    return resource_usage.get("wall_clock_seconds", 0) >= max_wall


def _load_plan(work_dir: Path) -> dict | None:
    """Load experiment plan from JSON."""
    path = work_dir / "reports" / "experiment_plan.json"
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("plan", data)
    except (json.JSONDecodeError, OSError):
        return None


def _load_ideas(work_dir: Path) -> list[dict]:
    """Load extracted ideas from JSONL."""
    path = work_dir / "logs" / "extracted_ideas.jsonl"
    if not path.exists():
        return []
    ideas = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    ideas.append(json.loads(line))
    except (json.JSONDecodeError, OSError):
        pass
    return ideas


def _init_sampler(work_dir: Path):
    """Initialize PaperSampler if the reward paper pool exists.

    Returns PaperSampler instance or None if pool is unavailable.
    """
    from research_agent.core.paper_sampler import PaperSampler

    pool_dir = Path(__file__).resolve().parent.parent / "reward_paper_pool"
    if not pool_dir.exists():
        return None
    try:
        return PaperSampler(pool_dir, work_dir)
    except Exception:
        return None


def _write_execution_report(
    work_dir: Path,
    phase_results: list[dict],
    resource_usage: dict,
) -> None:
    """Write execution report to JSON with fair_eval summary."""
    state = read_state_json(work_dir)
    baseline_fair = state.get("baseline_fair_eval", {})
    current_best = state.get("current_best", {})

    # Compute improvement over baseline
    improvement = {}
    if baseline_fair and current_best:
        best_fair = current_best.get("full_eval_result", {}).get("metrics", {})
        for metric_name, b_val in baseline_fair.items():
            c_val = best_fair.get(metric_name, {}).get("mean") if isinstance(best_fair.get(metric_name), dict) else best_fair.get(metric_name)
            if c_val is not None and b_val is not None and b_val != 0:
                pct = (c_val - b_val) / abs(b_val) * 100
                improvement[metric_name] = {"baseline": b_val, "best": c_val, "pct_change": round(pct, 2)}

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phases": phase_results,
        "resource_usage": resource_usage,
        "baseline_fair_eval": baseline_fair,
        "current_best": {
            "candidate_id": current_best.get("candidate_id"),
            "description": current_best.get("description"),
            "status": current_best.get("status"),
        },
        "improvement": improvement,
    }
    write_json_report(work_dir / "reports" / "execution_report.json", report)


def _error_result(error_code: str, message: str) -> dict:
    """Create an error response dict."""
    return {
        "ok": False,
        "error": {
            "error_code": error_code,
            "message": message,
        },
    }
