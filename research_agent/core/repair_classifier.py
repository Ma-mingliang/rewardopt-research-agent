"""Error-class-specific repair classifier for candidate patches.

Classifies patch errors into specific categories and maps them to appropriate
repair strategies, replacing the generic 'patch_repair_exhausted' approach.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IssueType(str, Enum):
    """Error types for patch classification."""
    INDENTATION_ERROR = "indentation_error"
    SYNTAX_ERROR = "syntax_error"
    AST_PARSE_ERROR = "ast_parse_error"
    UNDEFINED_HELPER_METHOD = "undefined_helper_method"
    UNRESOLVED_SYMBOL = "unresolved_symbol"
    UNAVAILABLE_VARIABLE = "unavailable_variable"
    PATCH_OUTSIDE_CONTEXT = "patch_outside_context"
    COSMETIC_PATCH = "cosmetic_patch"
    NO_REWARD_TERM_CHANGE = "no_reward_term_change"
    DUPLICATE_PATCH = "duplicate_patch"
    VALIDATION_ERROR = "validation_error"
    COMPILE_ERROR = "compile_error"


class RepairStrategy(str, Enum):
    """Repair strategies mapped to issue types."""
    SYNTAX_AWARE_REPAIR = "syntax_aware_repair"
    MISSING_HELPER_REPAIR = "missing_helper_repair"
    VARIABLE_GROUNDED_REGENERATION = "variable_grounded_regeneration"
    SEMANTIC_REGENERATION = "semantic_regeneration"
    DIVERSITY_REGENERATION = "diversity_regeneration"
    LOCAL_HUNK_REGENERATION = "local_hunk_regeneration"
    VALIDATION_GUIDED_REPAIR = "validation_guided_repair"


# Mapping from issue type to repair strategy
ISSUE_STRATEGY_MAP: dict[IssueType, RepairStrategy] = {
    IssueType.INDENTATION_ERROR: RepairStrategy.SYNTAX_AWARE_REPAIR,
    IssueType.SYNTAX_ERROR: RepairStrategy.SYNTAX_AWARE_REPAIR,
    IssueType.AST_PARSE_ERROR: RepairStrategy.SYNTAX_AWARE_REPAIR,
    IssueType.COMPILE_ERROR: RepairStrategy.SYNTAX_AWARE_REPAIR,
    IssueType.UNDEFINED_HELPER_METHOD: RepairStrategy.MISSING_HELPER_REPAIR,
    IssueType.UNRESOLVED_SYMBOL: RepairStrategy.MISSING_HELPER_REPAIR,
    IssueType.UNAVAILABLE_VARIABLE: RepairStrategy.VARIABLE_GROUNDED_REGENERATION,
    IssueType.PATCH_OUTSIDE_CONTEXT: RepairStrategy.LOCAL_HUNK_REGENERATION,
    IssueType.COSMETIC_PATCH: RepairStrategy.SEMANTIC_REGENERATION,
    IssueType.NO_REWARD_TERM_CHANGE: RepairStrategy.SEMANTIC_REGENERATION,
    IssueType.DUPLICATE_PATCH: RepairStrategy.DIVERSITY_REGENERATION,
    IssueType.VALIDATION_ERROR: RepairStrategy.VALIDATION_GUIDED_REPAIR,
}


@dataclass(frozen=True)
class RepairIssue:
    """A single classified repair issue."""
    issue_type: IssueType
    candidate_id: str
    root_cause: str
    failing_symbol: str = ""
    failing_line: int = 0
    traceback_tail: str = ""
    recommended_strategy: RepairStrategy = RepairStrategy.SYNTAX_AWARE_REPAIR
    repairable: bool = True
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "issue_type": self.issue_type.value,
            "candidate_id": self.candidate_id,
            "root_cause": self.root_cause,
            "failing_symbol": self.failing_symbol,
            "failing_line": self.failing_line,
            "traceback_tail": self.traceback_tail[:500],
            "recommended_strategy": self.recommended_strategy.value,
            "repairable": self.repairable,
            "diagnostics": self.diagnostics,
        }


# Patterns for detecting undefined helper methods
_HELPER_CALL_PATTERNS = [
    # self._xxx() or self.__xxx()
    re.compile(r'self\.(_\w+)\s*\('),
    # _xxx() without self (module-level or nested function)
    re.compile(r'(?<!\w)(_\w+)\s*\('),
]

# Patterns that should NOT be flagged as undefined
_BUILTIN_SAFE_PATTERNS = {
    # Python builtins
    '_print', '_len', '_range', '_enumerate', '_zip', '_map', '_filter',
    '_min', '_max', '_sum', '_abs', '_round', '_int', '_float', '_str',
    '_bool', '_list', '_dict', '_set', '_tuple', '_type', '_isinstance',
    '_hasattr', '_getattr', '_setattr', '_delattr',
    # Common library methods
    '_np', '_math', '_torch', '_json', '_os', '_sys', '_Path',
    # Gym/Gymnasium
    '_reset', '_step', '_close', '_render', '_seed',
}

# Known helper method prefixes that should be checked
_HELPER_PREFIXES = [
    '_compute_', '_calculate_', '_get_', '_reward_', '_penalty_',
    '_potential_', '_shaping_', '_bonus_', '_cost_',
]


def classify_error(
    candidate_id: str,
    error_type: str,
    error_message: str,
    traceback_tail: str = "",
    patch_diff: str = "",
    failing_line: int = 0,
    available_methods: list[str] | None = None,
) -> RepairIssue:
    """Classify an error and return a RepairIssue with recommended strategy.

    Args:
        candidate_id: The candidate identifier.
        error_type: The error type string (e.g., 'SyntaxError', 'NameError').
        error_message: The error message.
        traceback_tail: Last lines of traceback.
        patch_diff: The patch diff that caused the error.
        failing_line: Line number where error occurred.
        available_methods: List of methods available in the class/module.

    Returns:
        RepairIssue with classification and recommended strategy.
    """
    available_methods = available_methods or []

    # Normalize error type
    error_type_lower = error_type.lower().replace(" ", "_")

    # Check for undefined helper methods
    if _is_undefined_helper_error(error_type, error_message, traceback_tail):
        failing_symbol = _extract_failing_symbol(error_message, traceback_tail)
        return RepairIssue(
            issue_type=IssueType.UNDEFINED_HELPER_METHOD,
            candidate_id=candidate_id,
            root_cause=f"Undefined helper method '{failing_symbol}' called in patch",
            failing_symbol=failing_symbol,
            failing_line=failing_line,
            traceback_tail=traceback_tail,
            recommended_strategy=RepairStrategy.MISSING_HELPER_REPAIR,
            repairable=True,
            diagnostics={
                "error_type": error_type,
                "error_message": error_message,
                "patch_calls_undefined": True,
            },
        )

    # Check for unresolved symbols (variables)
    if _is_unresolved_symbol_error(error_type, error_message):
        failing_symbol = _extract_failing_symbol(error_message, traceback_tail)
        return RepairIssue(
            issue_type=IssueType.UNRESOLVED_SYMBOL,
            candidate_id=candidate_id,
            root_cause=f"Unresolved symbol '{failing_symbol}' in patch",
            failing_symbol=failing_symbol,
            failing_line=failing_line,
            traceback_tail=traceback_tail,
            recommended_strategy=RepairStrategy.VARIABLE_GROUNDED_REGENERATION,
            repairable=True,
            diagnostics={
                "error_type": error_type,
                "error_message": error_message,
            },
        )

    # Check for syntax errors
    if _is_syntax_error(error_type, error_message):
        issue_type = IssueType.SYNTAX_ERROR
        if "indent" in error_message.lower() or "indentation" in error_type.lower():
            issue_type = IssueType.INDENTATION_ERROR
        return RepairIssue(
            issue_type=issue_type,
            candidate_id=candidate_id,
            root_cause=f"Syntax error: {error_message[:200]}",
            failing_line=failing_line,
            traceback_tail=traceback_tail,
            recommended_strategy=RepairStrategy.SYNTAX_AWARE_REPAIR,
            repairable=True,
            diagnostics={
                "error_type": error_type,
                "error_message": error_message,
            },
        )

    # Check for compile errors
    if _is_compile_error(error_type, error_message):
        return RepairIssue(
            issue_type=IssueType.COMPILE_ERROR,
            candidate_id=candidate_id,
            root_cause=f"Compile error: {error_message[:200]}",
            failing_line=failing_line,
            traceback_tail=traceback_tail,
            recommended_strategy=RepairStrategy.SYNTAX_AWARE_REPAIR,
            repairable=True,
            diagnostics={
                "error_type": error_type,
                "error_message": error_message,
            },
        )

    # Check for AST parse errors
    if _is_ast_parse_error(error_type, error_message):
        return RepairIssue(
            issue_type=IssueType.AST_PARSE_ERROR,
            candidate_id=candidate_id,
            root_cause=f"AST parse error: {error_message[:200]}",
            failing_line=failing_line,
            traceback_tail=traceback_tail,
            recommended_strategy=RepairStrategy.SYNTAX_AWARE_REPAIR,
            repairable=True,
            diagnostics={
                "error_type": error_type,
                "error_message": error_message,
            },
        )

    # Check for validation errors
    if _is_validation_error(error_type, error_message):
        return RepairIssue(
            issue_type=IssueType.VALIDATION_ERROR,
            candidate_id=candidate_id,
            root_cause=f"Validation error: {error_message[:200]}",
            failing_line=failing_line,
            traceback_tail=traceback_tail,
            recommended_strategy=RepairStrategy.VALIDATION_GUIDED_REPAIR,
            repairable=True,
            diagnostics={
                "error_type": error_type,
                "error_message": error_message,
            },
        )

    # Default: treat as compile error with syntax repair
    return RepairIssue(
        issue_type=IssueType.COMPILE_ERROR,
        candidate_id=candidate_id,
        root_cause=f"Unclassified error: {error_type} - {error_message[:200]}",
        failing_line=failing_line,
        traceback_tail=traceback_tail,
        recommended_strategy=RepairStrategy.SYNTAX_AWARE_REPAIR,
        repairable=True,
        diagnostics={
            "error_type": error_type,
            "error_message": error_message,
            "unclassified": True,
        },
    )


def detect_undefined_helpers_in_patch(
    patch_diff: str,
    available_methods: list[str] | None = None,
) -> list[str]:
    """Detect undefined helper method calls in a patch diff.

    Args:
        patch_diff: The unified diff to analyze.
        available_methods: List of methods available in the class/module.

    Returns:
        List of undefined helper method names.
    """
    available_methods = set(available_methods or [])
    undefined_helpers = []

    # Extract added lines from diff
    added_lines = []
    for line in patch_diff.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line[1:])

    # Check each added line for helper calls
    for line in added_lines:
        for pattern in _HELPER_CALL_PATTERNS:
            matches = pattern.findall(line)
            for match in matches:
                # Skip builtins and safe patterns
                if match in _BUILTIN_SAFE_PATTERNS:
                    continue
                # Check if it's a helper method (starts with _ and has a prefix)
                if any(match.startswith(prefix) for prefix in _HELPER_PREFIXES):
                    if match not in available_methods:
                        undefined_helpers.append(match)
                # Also check self._xxx() calls
                elif match.startswith("_") and match not in available_methods:
                    # Only flag if it looks like a helper method (not a variable)
                    if "(" in line[line.find(match):]:
                        undefined_helpers.append(match)

    return list(set(undefined_helpers))


def _is_undefined_helper_error(error_type: str, error_message: str, traceback_tail: str) -> bool:
    """Check if error is from an undefined helper method."""
    # NameError with helper-like names
    if "nameerror" in error_type.lower():
        # Check if the undefined name looks like a helper method
        symbol = _extract_failing_symbol(error_message, traceback_tail)
        if symbol and any(symbol.startswith(prefix) for prefix in _HELPER_PREFIXES):
            return True
        # Also check for self._xxx patterns
        if "self." in traceback_tail or "self." in error_message:
            return True
    # AttributeError for missing methods
    if "attributeerror" in error_type.lower():
        if "has no attribute" in error_message.lower():
            symbol = _extract_failing_symbol(error_message, traceback_tail)
            if symbol and symbol.startswith("_"):
                return True
    return False


def _is_unresolved_symbol_error(error_type: str, error_message: str) -> bool:
    """Check if error is from an unresolved symbol."""
    if "nameerror" in error_type.lower():
        # Not a helper method, but still undefined
        return True
    return False


def _is_syntax_error(error_type: str, error_message: str) -> bool:
    """Check if error is a syntax error."""
    error_type_lower = error_type.lower()
    return "syntaxerror" in error_type_lower or "indentationerror" in error_type_lower


def _is_compile_error(error_type: str, error_message: str) -> bool:
    """Check if error is a compile error."""
    return "compile" in error_type.lower() or "compilation" in error_type.lower()


def _is_ast_parse_error(error_type: str, error_message: str) -> bool:
    """Check if error is an AST parse error."""
    return "ast" in error_type.lower() or "parse" in error_type.lower()


def _is_validation_error(error_type: str, error_message: str) -> bool:
    """Check if error is a validation error."""
    return "validation" in error_type.lower() or "semantic" in error_type.lower()


def _extract_failing_symbol(error_message: str, traceback_tail: str) -> str:
    """Extract the failing symbol from error message or traceback."""
    # Try to extract from NameError message
    name_match = re.search(r"name '(\w+)' is not defined", error_message)
    if name_match:
        return name_match.group(1)

    # Try to extract from AttributeError message
    attr_match = re.search(r"has no attribute '(\w+)'", error_message)
    if attr_match:
        return attr_match.group(1)

    # Try to extract from traceback
    func_match = re.search(r"(\w+)\s*\(", traceback_tail)
    if func_match:
        return func_match.group(1)

    return ""
