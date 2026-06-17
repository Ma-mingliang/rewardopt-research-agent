"""Syntax-aware LLM patch repair with strategy-based fallback.

Replaces the naive 30-attempt retry loop with:
1. Error signature tracking (detect repeated identical failures)
2. Three-tier repair strategy escalation
3. Rich context in repair prompts (baseline + patched code around error)
4. Budget-based fail-fast (max 6 total attempts, max 2 per error signature)
"""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class RepairStrategy(str, Enum):
    DIRECT_DIFF_REPAIR = "direct_diff_repair"
    LOCAL_HUNK_REGENERATION = "local_hunk_regeneration"
    IDEA_REGENERATION_FROM_BASELINE = "idea_regeneration_from_baseline"
    MISSING_HELPER_REPAIR = "missing_helper_repair"
    INLINE_CONVERSION = "inline_conversion"
    VARIABLE_GROUNDED_REGENERATION = "variable_grounded_regeneration"


@dataclass
class PatchRepairError:
    """Structured error information from a failed patch apply or compile."""

    error_type: str  # e.g. IndentationError, SyntaxError, PatchApplyError
    file_path: str
    line_number: int | None
    message: str
    traceback_tail: str = ""
    stderr_tail: str = ""
    stdout_tail: str = ""
    failed_diff: str = ""
    baseline_context: str = ""
    patched_context: str = ""
    target_context: str = ""
    allowed_changes: list[str] = field(default_factory=list)

    @property
    def error_signature(self) -> str:
        """Normalized signature: error_type|file|line|normalized_msg."""
        norm_msg = re.sub(r"\s+", " ", self.message.strip().lower())[:80]
        line_str = str(self.line_number) if self.line_number else "none"
        return f"{self.error_type}|{self.file_path}|{line_str}|{norm_msg}"


@dataclass
class PatchRepairResult:
    """Result of a single repair attempt."""

    repaired_diff: str
    strategy: RepairStrategy
    repair_attempt: int
    error_signature: str
    changed_lines: int = 0
    valid_unified_diff: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)


def make_error_signature(error_type: str, file_path: str, line_number: int | None, message: str) -> str:
    """Build a normalized error signature for dedup."""
    norm_msg = re.sub(r"\s+", " ", message.strip().lower())[:80]
    line_str = str(line_number) if line_number else "none"
    return f"{error_type}|{file_path}|{line_str}|{norm_msg}"


def extract_error_line(error_message: str) -> int | None:
    """Extract line number from error message.

    Handles formats:
    - 'File "env.py", line 983'
    - 'env.py:983: IndentationError: ...'
    - 'line 983'
    """
    # Try "line N" pattern (traceback style)
    match = re.search(r"line (\d+)", error_message)
    if match:
        return int(match.group(1))
    # Try "file:N:" pattern (py_compile style)
    match = re.search(r":(\d+):\s*\w+(?:Error|Exception|Warning)", error_message)
    if match:
        return int(match.group(1))
    return None


def extract_error_type(error_message: str) -> str:
    """Extract exception type from error message.

    Handles formats:
    - 'IndentationError: ...'
    - 'env.py:983: IndentationError: ...'
    - 'Sorry: IndentationError: ...'
    """
    # Try "Sorry: ErrorType:" pattern
    match = re.search(r"Sorry:\s*(\w+(?:Error|Exception))", error_message)
    if match:
        return match.group(1)
    # Try "file:line: ErrorType:" pattern (py_compile style)
    match = re.search(r":\d+:\s*(\w+(?:Error|Exception|Warning))", error_message)
    if match:
        return match.group(1)
    # Try "ErrorType:" at start
    match = re.match(r"^(\w+(?:Error|Exception|Warning))", error_message.strip())
    if match:
        return match.group(1)
    # Try any ErrorType in the message
    match = re.search(r"(\w+(?:Error|Exception|Warning))", error_message)
    if match:
        return match.group(1)
    return "UnknownError"


def extract_local_context(
    file_path: Path,
    line_number: int,
    radius: int = 25,
) -> str:
    """Extract code context around a line number with line markers."""
    if not file_path.exists():
        return "(file not found)"
    try:
        content = file_path.read_text(encoding="utf-8-sig")
        lines = content.splitlines()
        start = max(0, line_number - radius - 1)
        end = min(len(lines), line_number + radius)
        context_lines = []
        for i in range(start, end):
            marker = " >>> " if i == line_number - 1 else "     "
            context_lines.append(f"{i+1:4d}{marker}{lines[i]}")
        return "\n".join(context_lines)
    except Exception:
        return "(could not read file)"


def extract_diff_context(
    diff: str,
    error_line: int,
    radius: int = 25,
) -> str:
    """Extract lines from a diff near the error location."""
    lines = diff.splitlines()
    # Find the hunk that contains the error line
    current_new_line = 0
    hunk_start = 0
    for i, line in enumerate(lines):
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            if match:
                current_new_line = int(match.group(1))
                hunk_start = i
        elif line.startswith("+") and not line.startswith("+++"):
            if abs(current_new_line - error_line) <= radius:
                # Found relevant hunk, return surrounding context
                start = max(hunk_start, i - radius)
                end = min(len(lines), i + radius)
                return "\n".join(lines[start:end])
            current_new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            pass  # removed lines don't increment new line counter
        else:
            current_new_line += 1
    # Fallback: return last 50 lines of diff
    return "\n".join(lines[-50:]) if len(lines) > 50 else diff


def validate_repaired_diff_on_temp_copy(
    project_path: Path,
    diff: str,
    target_file: str = "env.py",
    python_executable: str = "python",
) -> tuple[bool, list[str]]:
    """Apply diff to a temp copy and validate compilation.

    Returns (ok, errors). Does NOT modify the real project file.
    """
    import shutil

    real_file = project_path / target_file
    if not real_file.exists():
        return False, [f"{target_file} not found"]

    # Create temp directory with a copy
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_project = Path(tmpdir) / "project"
        tmp_project.mkdir()
        tmp_file = tmp_project / target_file
        shutil.copy2(real_file, tmp_file)

        # Write diff to temp patch file
        patch_file = Path(tmpdir) / "repair.patch"
        patch_file.write_text(diff, encoding="utf-8")

        # Try git apply
        result = subprocess.run(
            ["git", "apply", "--check", str(patch_file)],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False, [f"git apply failed: {result.stderr.strip()[:200]}"]

        # Actually apply
        result = subprocess.run(
            ["git", "apply", str(patch_file)],
            cwd=str(tmp_project),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False, [f"git apply failed: {result.stderr.strip()[:200]}"]

        # Check compilation
        result = subprocess.run(
            [python_executable, "-m", "py_compile", str(tmp_file)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return False, [f"compilation failed: {result.stderr.strip()[:200]}"]

        # Check AST parse
        try:
            content = tmp_file.read_text(encoding="utf-8-sig")
            ast.parse(content)
        except SyntaxError as e:
            return False, [f"AST parse failed: {e}"]

        # Check reward function extraction
        try:
            tree = ast.parse(content)
            has_reward = any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and "reward" in node.name.lower()
                for node in ast.walk(tree)
            )
            if not has_reward:
                return False, ["no reward function found in patched file"]
        except Exception as e:
            return False, [f"reward extraction check failed: {e}"]

    return True, []


def build_syntax_repair_prompt(
    error: PatchRepairError,
    strategy: RepairStrategy,
    reward_idea: str = "",
    method_pool_context: str = "",
    attempt: int = 1,
) -> tuple[str, str]:
    """Build system + user prompt for syntax-aware repair.

    Returns (system_prompt, user_prompt).
    """
    system_prompt = (
        "You are a Python unified diff repair specialist. "
        "You fix syntax errors in patches so they apply cleanly and compile. "
        "Return ONLY valid JSON. Do NOT output markdown, explanations, or full file rewrites."
    )

    # Build context sections
    sections = []

    sections.append(f"## Error\nType: {error.error_type}\nFile: {error.file_path}\n"
                    f"Line: {error.line_number}\nMessage: {error.message}")

    if error.traceback_tail:
        sections.append(f"## Traceback (last 20 lines)\n```\n{error.traceback_tail}\n```")

    if error.failed_diff:
        sections.append(f"## Failed Unified Diff\n```\n{error.failed_diff}\n```")

    if error.baseline_context:
        sections.append(f"## Baseline Code (around line {error.line_number})\n"
                        f"```\n{error.baseline_context}\n```")

    if error.patched_context:
        sections.append(f"## Patched Code (around line {error.line_number})\n"
                        f"```\n{error.patched_context}\n```")

    if error.target_context:
        sections.append(f"## Target Context\n```\n{error.target_context}\n```")

    if error.allowed_changes:
        sections.append(f"## Allowed Changes\n{', '.join(error.allowed_changes)}")

    if reward_idea:
        sections.append(f"## Reward Idea\n{reward_idea}")

    if method_pool_context:
        sections.append(f"## Method Pool Context\n{method_pool_context}")

    # Strategy-specific instructions
    if strategy == RepairStrategy.DIRECT_DIFF_REPAIR:
        strategy_instruction = (
            "Fix the unified diff so it applies cleanly and the resulting Python file compiles. "
            "Preserve the intended code changes. Fix indentation, line counts, and context lines."
        )
    elif strategy == RepairStrategy.LOCAL_HUNK_REGENERATION:
        strategy_instruction = (
            "The previous diff repair failed with the same error. "
            "Instead of trying to fix the existing diff, regenerate ONLY the hunk around the error line. "
            "Use the baseline code context above to understand the correct structure. "
            "Generate a minimal unified diff that modifies only the necessary lines."
        )
    else:  # IDEA_REGENERATION_FROM_BASELINE
        strategy_instruction = (
            "All previous repair strategies failed. Generate a NEW minimal unified diff from scratch. "
            "Use the baseline code and reward idea above. "
            "Create the smallest possible patch that implements the reward idea. "
            "Do NOT copy the failed diff. Start fresh."
        )

    # Add missing helper repair strategy instructions
    if strategy == RepairStrategy.MISSING_HELPER_REPAIR:
        strategy_instruction = (
            "The patch calls a helper method that is not defined. "
            "You must either:\n"
            "1. Convert the helper call to an inline expression using available variables, OR\n"
            "2. Include the complete helper method definition in the same diff.\n"
            "Do NOT call methods that are not already defined in the provided context. "
            "Prefer inline reward expressions using available variables. "
            "If introducing a helper method, include the complete method definition in the same diff."
        )
    elif strategy == RepairStrategy.INLINE_CONVERSION:
        strategy_instruction = (
            "Convert the undefined helper method call to an inline reward expression. "
            "Use only variables that are available in the current context. "
            "Do NOT call any new helper methods. "
            "Generate a minimal inline expression that implements the reward idea."
        )
    elif strategy == RepairStrategy.VARIABLE_GROUNDED_REGENERATION:
        strategy_instruction = (
            "The previous repair failed because required variables are not available. "
            "Generate a NEW reward expression using ONLY the available variables listed above. "
            "Do NOT use any variables that are not in the available list. "
            "Create a minimal reward term that uses only available variables."
        )

    sections.append(f"## Instructions\n{strategy_instruction}")

    constraints = """## Constraints
- Output ONLY a unified diff (start with @@ or --- / +++)
- Do NOT output markdown code fences
- Do NOT output explanations
- Do NOT rewrite the entire file
- Only modify allowed_changes range
- Fix Python indentation so the file compiles
- For IndentationError: fix the error line and surrounding 20-40 lines
- Do NOT modify: observation space, action space, training protocol, eval protocol, seeds, model architecture
- Do NOT introduce new external imports
- Do NOT delete the reward function
- Keep the diff minimal
- If the current diff structure is unfixable, generate an equivalent minimal reward patch from scratch"""

    sections.append(constraints)

    user_prompt = "\n\n".join(sections)

    return system_prompt, user_prompt


def parse_repair_response(response_text: str) -> str | None:
    """Extract the repaired diff from LLM response.

    Handles JSON with 'fixed_diff' or 'diff' keys, and raw diff output.
    """
    import json

    if not response_text:
        return None

    # Try JSON parse
    try:
        data = json.loads(response_text)
        if isinstance(data, dict):
            return data.get("fixed_diff") or data.get("diff") or None
    except (json.JSONDecodeError, TypeError):
        pass

    # Try to extract diff from raw text
    lines = response_text.strip().splitlines()
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

    return None


class RepairAttemptTracker:
    """Tracks repair attempts, error signatures, and strategy state."""

    def __init__(
        self,
        max_total_attempts: int = 6,
        max_same_error_attempts: int = 2,
        max_strategy_attempts: dict[str, int] | None = None,
    ):
        self.max_total_attempts = max_total_attempts
        self.max_same_error_attempts = max_same_error_attempts
        self.max_strategy_attempts = max_strategy_attempts or {
            "direct_diff_repair": 2,
            "local_hunk_regeneration": 2,
            "idea_regeneration_from_baseline": 2,
            "missing_helper_repair": 2,
            "inline_conversion": 2,
            "variable_grounded_regeneration": 2,
        }

        self.total_attempts = 0
        self.error_signatures: list[str] = []
        self.error_counts: dict[str, int] = {}
        self.strategy_history: list[str] = []
        self.strategy_attempts: dict[str, int] = {}
        self.current_strategy_index = 0

    @property
    def strategies(self) -> list[RepairStrategy]:
        return [
            RepairStrategy.DIRECT_DIFF_REPAIR,
            RepairStrategy.LOCAL_HUNK_REGENERATION,
            RepairStrategy.IDEA_REGENERATION_FROM_BASELINE,
            RepairStrategy.MISSING_HELPER_REPAIR,
            RepairStrategy.INLINE_CONVERSION,
            RepairStrategy.VARIABLE_GROUNDED_REGENERATION,
        ]

    @property
    def current_strategy(self) -> RepairStrategy:
        if self.current_strategy_index < len(self.strategies):
            return self.strategies[self.current_strategy_index]
        return self.strategies[-1]

    def should_continue(self) -> bool:
        """Check if we should continue repairing."""
        if self.total_attempts >= self.max_total_attempts:
            return False
        if self.current_strategy_index >= len(self.strategies):
            return False
        return True

    def record_attempt(self, error_signature: str, strategy: RepairStrategy) -> None:
        """Record a repair attempt."""
        self.total_attempts += 1
        self.error_signatures.append(error_signature)
        self.error_counts[error_signature] = self.error_counts.get(error_signature, 0) + 1
        self.strategy_history.append(strategy.value)
        self.strategy_attempts[strategy.value] = self.strategy_attempts.get(strategy.value, 0) + 1

    def should_switch_strategy(self, error_signature: str) -> bool:
        """Check if the same error has repeated enough to switch strategy."""
        count = self.error_counts.get(error_signature, 0)
        return count >= self.max_same_error_attempts

    def switch_strategy(self) -> RepairStrategy:
        """Move to the next repair strategy."""
        self.current_strategy_index += 1
        if self.current_strategy_index < len(self.strategies):
            return self.strategies[self.current_strategy_index]
        return self.strategies[-1]

    def get_diagnostics(self) -> dict[str, Any]:
        """Get diagnostic information for logging."""
        return {
            "total_attempts": self.total_attempts,
            "error_signatures": self.error_signatures[-5:],  # last 5
            "error_counts": dict(self.error_counts),
            "strategy_history": self.strategy_history,
            "strategy_attempts": dict(self.strategy_attempts),
            "current_strategy": self.current_strategy.value,
            "last_error_signature": self.error_signatures[-1] if self.error_signatures else None,
        }
