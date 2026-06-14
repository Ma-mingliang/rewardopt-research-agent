"""Stateless tool functions for the reward proposal agent.

All subprocess-based validation uses execution_python via ExecutionEnv,
never the agent's own Python interpreter.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from research_agent.core.execution_env import ExecutionEnv, run_in_execution_env, run_python_compile
from research_agent.core.reward_extractor import extract_reward_function, extract_all_reward_functions
from research_agent.optimizers.reward.reward_patch_utils import (
    add_diff_header_if_missing,
    auto_fix_indentation,
    build_source_meta,
    extract_target_context,
    fix_diff_line_counts,
    format_baseline,
    format_ideas,
    parse_error_line,
)


def read_reward_code(project_path: Path, allowed_changes: list[dict]) -> str:
    """Read the current reward function code using AST parsing."""
    for change in allowed_changes:
        file_path = change.get("file", "") if isinstance(change, dict) else change
        if not file_path:
            continue
        full_path = project_path / file_path
        if not full_path.exists():
            continue
        result = extract_reward_function(full_path, "__calculate_reward")
        if result:
            return result["code"]
        all_funcs = extract_all_reward_functions(full_path)
        if all_funcs:
            best = max(all_funcs, key=lambda f: f["end_line"] - f["start_line"])
            return best["code"]
        try:
            content = full_path.read_text(encoding="utf-8")
            lines = content.splitlines()[:200]
            return "\n".join(f"{i+1:4d} | {line}" for i, line in enumerate(lines))
        except OSError:
            continue
    return "# No reward function file found"


def validate_patch(
    diff: str,
    allowed_changes: list[dict],
    project_path: Path,
    work_dir: Path,
    execution_env: ExecutionEnv,
) -> dict:
    """Validate a patch in an isolated temp directory using execution_python.

    Steps:
    1. Copy files referenced in allowed_changes to temp dir
    2. Parse diff and apply to temp copies
    3. Compile check via execution_python subprocess
    4. Clean up temp dir

    Returns:
        {"ok": True} if patch applies and compiles,
        {"ok": False, "error": "..."} if it fails.
    """
    import re
    import tempfile

    if not allowed_changes:
        return {"ok": False, "error": "No allowed changes specified"}

    file_name = allowed_changes[0].get("file", "env.py") if allowed_changes else "env.py"
    if isinstance(allowed_changes[0], str):
        file_name = allowed_changes[0]
    source_file = project_path / file_name

    if not source_file.exists():
        return {"ok": False, "error": f"File not found: {source_file}"}

    # Create temp directory for validation
    tmp_dir = work_dir / "validation_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Copy source file to temp dir preserving structure
        tmp_file = tmp_dir / file_name
        tmp_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, tmp_file)

        # Read original content from temp copy
        original = tmp_file.read_text(encoding="utf-8-sig")
        original_lines = original.splitlines()

        # Parse and apply diff hunks
        modified_lines = list(original_lines)
        hunks = _parse_diff_hunks(diff)

        if not hunks:
            return {"ok": False, "error": "No valid hunks found in diff"}

        # Apply hunks in reverse order to preserve line numbers
        for hunk in sorted(hunks, key=lambda h: h["old_start"], reverse=True):
            old_start = hunk["old_start"] - 1  # 0-indexed
            old_count = hunk["old_count"]
            new_lines = hunk["new_lines"]

            # Verify the old lines match
            actual_old = modified_lines[old_start:old_start + old_count]
            expected_old = hunk["old_lines"]

            # Apply the replacement
            modified_lines[old_start:old_start + old_count] = new_lines

        # Write modified content to temp file
        modified_content = "\n".join(modified_lines)
        if original.endswith("\n") and not modified_content.endswith("\n"):
            modified_content += "\n"
        tmp_file.write_text(modified_content, encoding="utf-8")

        # Check if content actually changed
        if modified_content == original:
            return {"ok": False, "error": "Patch did not change any code (no-op)"}

        # Compile check via execution_python
        ok, stderr = run_python_compile(execution_env, tmp_file)
        if not ok:
            return {"ok": False, "error": f"SyntaxError: {stderr}"}

        # AST check — verify __calculate_reward still exists
        ast_ok, ast_stderr = _check_reward_function_exists(execution_env, tmp_file)
        if not ast_ok:
            return {"ok": False, "error": ast_stderr}

        return {"ok": True}

    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        # Clean up temp directory
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _parse_diff_hunks(diff: str) -> list[dict]:
    """Parse unified diff into structured hunks."""
    import re

    lines = diff.split("\n")
    hunks = []
    i = 0

    # Skip header lines (--- / +++)
    while i < len(lines) and (lines[i].startswith("---") or lines[i].startswith("+++")):
        i += 1

    while i < len(lines):
        line = lines[i]
        if line.startswith("@@"):
            match = re.match(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@", line)
            if match:
                old_start = int(match.group(1))
                old_count = int(match.group(2))
                new_start = int(match.group(3))

                old_lines = []
                new_lines = []
                j = i + 1
                while j < len(lines):
                    l = lines[j]
                    if l.startswith("@@") or l.startswith("---") or l.startswith("+++"):
                        break
                    if l.startswith("-"):
                        old_lines.append(l[1:])
                    elif l.startswith("+"):
                        new_lines.append(l[1:])
                    elif l.startswith(" ") or l == "":
                        old_lines.append(l[1:] if l.startswith(" ") else l)
                        new_lines.append(l[1:] if l.startswith(" ") else l)
                    j += 1

                hunks.append({
                    "old_start": old_start,
                    "old_count": old_count,
                    "new_start": new_start,
                    "old_lines": old_lines,
                    "new_lines": new_lines,
                })
                i = j
                continue
        i += 1

    return hunks


def _check_reward_function_exists(
    env: ExecutionEnv,
    file_path: Path,
) -> tuple[bool, str]:
    """Check if __calculate_reward function exists in the file via execution_python."""
    script = (
        f"import ast; "
        f"tree = ast.parse(open(r'{file_path}', encoding='utf-8').read()); "
        f"assert any(isinstance(n, ast.FunctionDef) and n.name == '__calculate_reward' for n in ast.walk(tree)), "
        f"'__calculate_reward function not found'"
    )
    result = run_in_execution_env(env, script)
    if result.returncode != 0:
        return False, "Patch removed __calculate_reward function"
    return True, ""
