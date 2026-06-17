"""Undefined symbol guard for candidate patches.

Detects undefined helper methods and unresolved symbols in patches,
and triggers appropriate repair strategies instead of generic rejection.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_agent.core.repair_classifier import (
    IssueType,
    RepairIssue,
    RepairStrategy,
    detect_undefined_helpers_in_patch,
)


@dataclass(frozen=True)
class UndefinedSymbolDecision:
    """Decision from undefined symbol guard analysis."""
    passed: bool
    unresolved_calls: list[str] = field(default_factory=list)
    unresolved_methods: list[str] = field(default_factory=list)
    unresolved_functions: list[str] = field(default_factory=list)
    missing_helper_methods: list[str] = field(default_factory=list)
    reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    repair_issues: list[RepairIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "passed": self.passed,
            "unresolved_calls": self.unresolved_calls,
            "unresolved_methods": self.unresolved_methods,
            "unresolved_functions": self.unresolved_functions,
            "missing_helper_methods": self.missing_helper_methods,
            "reason": self.reason,
            "diagnostics": self.diagnostics,
            "repair_issues": [issue.to_dict() for issue in self.repair_issues],
        }


# Patterns for detecting method/function calls
_SELF_METHOD_PATTERN = re.compile(r'self\.(\w+)\s*\(')
_FUNCTION_CALL_PATTERN = re.compile(r'(?<!\w)(\w+)\s*\(')

# Helper method prefixes that should be checked
_HELPER_PREFIXES = [
    '_compute_', '_calculate_', '_get_', '_reward_', '_penalty_',
    '_potential_', '_shaping_', '_bonus_', '_cost_',
]

# Built-in and safe names that should NOT be flagged
_SAFE_NAMES = {
    # Python builtins
    'print', 'len', 'range', 'enumerate', 'zip', 'map', 'filter',
    'min', 'max', 'sum', 'abs', 'round', 'int', 'float', 'str',
    'bool', 'list', 'dict', 'set', 'tuple', 'type', 'isinstance',
    'hasattr', 'getattr', 'setattr', 'delattr', 'super', 'property',
    'staticmethod', 'classmethod', 'staticmethod',
    # Math/numpy
    'math', 'np', 'numpy', 'torch', 'sin', 'cos', 'tan', 'atan',
    'atan2', 'sqrt', 'log', 'exp', 'pi', 'inf', 'nan',
    'clip', 'abs', 'sum', 'mean', 'std', 'var',
    # Common methods
    'append', 'extend', 'insert', 'remove', 'pop', 'clear',
    'sort', 'reverse', 'copy', 'count', 'index',
    'keys', 'values', 'items', 'get', 'update', 'setdefault',
    'join', 'split', 'strip', 'lstrip', 'rstrip',
    'format', 'encode', 'decode',
    # Gym/Gymnasium
    'reset', 'step', 'close', 'render', 'seed',
    # Type conversions
    'float32', 'float64', 'int32', 'int64',
}

# Names that look like variables (not methods)
_VARIABLE_LIKE_NAMES = {
    'reward', 'done', 'truncated', 'info', 'obs', 'action',
    'state', 'next_state', 'value', 'q_value', 'advantage',
    'loss', 'gradient', 'optimizer', 'scheduler',
}


def check_undefined_symbols(
    patch_diff: str,
    class_source: str = "",
    module_source: str = "",
    candidate_id: str = "",
    available_reward_variables: list[str] | None = None,
) -> UndefinedSymbolDecision:
    """Check for undefined symbols in a patch diff.

    Args:
        patch_diff: The unified diff to analyze.
        class_source: Source code of the class being modified.
        module_source: Source code of the module being modified.
        candidate_id: The candidate identifier.
        available_reward_variables: List of available reward variables.

    Returns:
        UndefinedSymbolDecision with analysis results.
    """
    available_reward_variables = available_reward_variables or []
    repair_issues = []
    unresolved_calls = []
    unresolved_methods = []
    missing_helper_methods = []

    # Extract added lines from diff
    added_lines = []
    for line in patch_diff.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line[1:])

    # Get available methods from class source
    available_methods = _extract_methods_from_source(class_source)
    available_functions = _extract_functions_from_source(module_source)

    # Check each added line for undefined calls
    for line_num, line in enumerate(added_lines, 1):
        # Check self.method() calls
        self_calls = _SELF_METHOD_PATTERN.findall(line)
        for call in self_calls:
            if call in _SAFE_NAMES:
                continue
            if call not in available_methods:
                # Check if it's a helper method
                if any(call.startswith(prefix) for prefix in _HELPER_PREFIXES):
                    missing_helper_methods.append(call)
                    repair_issues.append(RepairIssue(
                        issue_type=IssueType.UNDEFINED_HELPER_METHOD,
                        candidate_id=candidate_id,
                        root_cause=f"Undefined helper method 'self.{call}()' called in patch",
                        failing_symbol=call,
                        failing_line=line_num,
                        recommended_strategy=RepairStrategy.MISSING_HELPER_REPAIR,
                        repairable=True,
                        diagnostics={
                            "call_type": "self_method",
                            "line": line.strip(),
                        },
                    ))
                else:
                    unresolved_methods.append(call)

        # Check function() calls (not self.method())
        func_calls = _FUNCTION_CALL_PATTERN.findall(line)
        for call in func_calls:
            if call in _SAFE_NAMES:
                continue
            if call in _VARIABLE_LIKE_NAMES:
                continue
            if call in available_functions:
                continue
            if call in available_methods:
                continue
            # Check if it's a helper function
            if any(call.startswith(prefix) for prefix in _HELPER_PREFIXES):
                missing_helper_methods.append(call)
                repair_issues.append(RepairIssue(
                    issue_type=IssueType.UNDEFINED_HELPER_METHOD,
                    candidate_id=candidate_id,
                    root_cause=f"Undefined helper function '{call}()' called in patch",
                    failing_symbol=call,
                    failing_line=line_num,
                    recommended_strategy=RepairStrategy.MISSING_HELPER_REPAIR,
                    repairable=True,
                    diagnostics={
                        "call_type": "function",
                        "line": line.strip(),
                    },
                ))

    # Deduplicate
    missing_helper_methods = list(set(missing_helper_methods))
    unresolved_methods = list(set(unresolved_methods))
    unresolved_calls = list(set(unresolved_calls))

    # Determine if guard passed
    passed = len(missing_helper_methods) == 0 and len(unresolved_methods) == 0

    # Build reason
    if passed:
        reason = "All symbols resolved"
    else:
        parts = []
        if missing_helper_methods:
            parts.append(f"missing_helper_methods: {', '.join(missing_helper_methods)}")
        if unresolved_methods:
            parts.append(f"unresolved_methods: {', '.join(unresolved_methods)}")
        reason = "; ".join(parts)

    return UndefinedSymbolDecision(
        passed=passed,
        unresolved_calls=unresolved_calls,
        unresolved_methods=unresolved_methods,
        unresolved_functions=[],
        missing_helper_methods=missing_helper_methods,
        reason=reason,
        diagnostics={
            "added_lines_count": len(added_lines),
            "available_methods_count": len(available_methods),
            "available_functions_count": len(available_functions),
            "available_variables_count": len(available_reward_variables),
        },
        repair_issues=repair_issues,
    )


def _extract_methods_from_source(source: str) -> set[str]:
    """Extract method names from class source code."""
    methods = set()
    if not source:
        return methods

    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.add(item.name)
    except SyntaxError:
        # Fallback to regex if AST fails
        pattern = re.compile(r'def\s+(\w+)\s*\(')
        methods = set(pattern.findall(source))

    return methods


def _extract_functions_from_source(source: str) -> set[str]:
    """Extract function names from module source code."""
    functions = set()
    if not source:
        return functions

    try:
        tree = ast.parse(source)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.add(node.name)
    except SyntaxError:
        # Fallback to regex if AST fails
        pattern = re.compile(r'def\s+(\w+)\s*\(')
        functions = set(pattern.findall(source))

    return functions


def check_patch_compiles(patch_diff: str, env_path: Path) -> tuple[bool, str]:
    """Check if a patch compiles without errors.

    Args:
        patch_diff: The unified diff to apply and check.
        env_path: Path to the env.py file.

    Returns:
        Tuple of (success, error_message).
    """
    import subprocess
    import tempfile

    # Create a temporary copy for testing
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
        temp_path = Path(f.name)
        f.write(env_path.read_text(encoding='utf-8'))

    try:
        # Apply patch
        patch_content = patch_diff.encode('utf-8')
        result = subprocess.run(
            ['git', 'apply', '--check'],
            input=patch_content,
            capture_output=True,
            text=True,
            cwd=env_path.parent,
        )
        if result.returncode != 0:
            return False, f"Patch apply failed: {result.stderr}"

        # Actually apply
        result = subprocess.run(
            ['git', 'apply'],
            input=patch_content,
            capture_output=True,
            text=True,
            cwd=env_path.parent,
        )
        if result.returncode != 0:
            return False, f"Patch apply failed: {result.stderr}"

        # Try to compile
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                source = f.read()
            compile(source, str(env_path), 'exec')
            return True, ""
        except SyntaxError as e:
            return False, f"SyntaxError: {e}"

    finally:
        # Clean up
        temp_path.unlink(missing_ok=True)
