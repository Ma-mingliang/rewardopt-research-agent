"""Missing helper repair strategy for undefined method calls.

Converts undefined helper method calls to inline reward expressions
or provides complete helper method definitions.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_agent.core.repair_classifier import IssueType, RepairIssue


@dataclass(frozen=True)
class MissingHelperRepairResult:
    """Result of missing helper repair attempt."""
    success: bool
    repaired_diff: str = ""
    repair_strategy: str = ""  # "inline_conversion" or "helper_definition"
    undefined_symbol: str = ""
    inline_expression: str = ""
    helper_definition: str = ""
    reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "repaired_diff": self.repaired_diff,
            "repair_strategy": self.repair_strategy,
            "undefined_symbol": self.undefined_symbol,
            "inline_expression": self.inline_expression,
            "helper_definition": self.helper_definition,
            "reason": self.reason,
            "diagnostics": self.diagnostics,
        }


def repair_missing_helper(
    patch_diff: str,
    undefined_symbol: str,
    available_variables: list[str] | None = None,
    available_methods: list[str] | None = None,
    class_source: str = "",
    candidate_id: str = "",
) -> MissingHelperRepairResult:
    """Repair a patch with undefined helper method call.

    Tries two strategies:
    1. Inline conversion: Convert helper call to inline expression
    2. Helper definition: Add complete helper method definition

    Args:
        patch_diff: The original patch diff with undefined helper.
        undefined_symbol: The undefined helper method name.
        available_variables: List of available reward variables.
        available_methods: List of available methods in the class.
        class_source: Source code of the class being modified.
        candidate_id: The candidate identifier.

    Returns:
        MissingHelperRepairResult with repair outcome.
    """
    available_variables = available_variables or []
    available_methods = available_methods or []

    # Strategy 1: Try inline conversion
    inline_result = _try_inline_conversion(
        patch_diff=patch_diff,
        undefined_symbol=undefined_symbol,
        available_variables=available_variables,
        candidate_id=candidate_id,
    )
    if inline_result.success:
        return inline_result

    # Strategy 2: Try helper definition
    helper_result = _try_helper_definition(
        patch_diff=patch_diff,
        undefined_symbol=undefined_symbol,
        available_variables=available_variables,
        available_methods=available_methods,
        class_source=class_source,
        candidate_id=candidate_id,
    )
    if helper_result.success:
        return helper_result

    # Both strategies failed
    return MissingHelperRepairResult(
        success=False,
        undefined_symbol=undefined_symbol,
        reason=f"Both inline_conversion and helper_definition failed for '{undefined_symbol}'",
        diagnostics={
            "inline_result": inline_result.reason,
            "helper_result": helper_result.reason,
        },
    )


def _try_inline_conversion(
    patch_diff: str,
    undefined_symbol: str,
    available_variables: list[str],
    candidate_id: str,
) -> MissingHelperRepairResult:
    """Try to convert undefined helper call to inline expression.

    For potential-based reward: Phi(s) = -k_phi * |error|
    For other helpers: Use available variables to build expression.
    """
    # Extract the helper call pattern
    helper_call_pattern = re.compile(
        rf'(self\.)?{re.escape(undefined_symbol)}\s*\(([^)]*)\)'
    )

    # Find all occurrences in added lines
    added_lines = []
    for line in patch_diff.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line)

    # Check if we can inline this helper
    for line in added_lines:
        match = helper_call_pattern.search(line)
        if match:
            # Determine what the helper is supposed to compute
            inline_expr = _generate_inline_expression(
                undefined_symbol=undefined_symbol,
                available_variables=available_variables,
                call_args=match.group(2),
            )
            if inline_expr:
                # Replace the helper call with inline expression
                repaired_line = helper_call_pattern.sub(inline_expr, line)
                repaired_diff = _replace_line_in_diff(patch_diff, line, repaired_line)

                return MissingHelperRepairResult(
                    success=True,
                    repaired_diff=repaired_diff,
                    repair_strategy="inline_conversion",
                    undefined_symbol=undefined_symbol,
                    inline_expression=inline_expr,
                    reason=f"Converted '{undefined_symbol}()' to inline expression",
                    diagnostics={
                        "original_line": line.strip(),
                        "repaired_line": repaired_line.strip(),
                    },
                )

    return MissingHelperRepairResult(
        success=False,
        undefined_symbol=undefined_symbol,
        reason=f"Cannot generate inline expression for '{undefined_symbol}'",
    )


def _try_helper_definition(
    patch_diff: str,
    undefined_symbol: str,
    available_variables: list[str],
    available_methods: list[str],
    class_source: str,
    candidate_id: str,
) -> MissingHelperRepairResult:
    """Try to add complete helper method definition to the patch.

    Only used when inline conversion is not possible.
    """
    # Generate helper method definition
    helper_def = _generate_helper_definition(
        undefined_symbol=undefined_symbol,
        available_variables=available_variables,
        available_methods=available_methods,
        class_source=class_source,
    )

    if not helper_def:
        return MissingHelperRepairResult(
            success=False,
            undefined_symbol=undefined_symbol,
            reason=f"Cannot generate valid helper definition for '{undefined_symbol}'",
        )

    # Find where to insert the helper definition
    # Look for the class definition and add the method there
    insert_line = _find_insertion_point(class_source, undefined_symbol)
    if insert_line == -1:
        return MissingHelperRepairResult(
            success=False,
            undefined_symbol=undefined_symbol,
            reason="Cannot find insertion point for helper definition",
        )

    # Create the repaired diff with helper definition added
    repaired_diff = _add_helper_to_diff(patch_diff, helper_def, insert_line)

    return MissingHelperRepairResult(
        success=True,
        repaired_diff=repaired_diff,
        repair_strategy="helper_definition",
        undefined_symbol=undefined_symbol,
        helper_definition=helper_def,
        reason=f"Added helper method definition for '{undefined_symbol}'",
        diagnostics={
            "insertion_line": insert_line,
            "helper_definition_lines": helper_def.count("\n") + 1,
        },
    )


def _generate_inline_expression(
    undefined_symbol: str,
    available_variables: list[str],
    call_args: str,
) -> str:
    """Generate inline expression for a helper method call.

    For common reward helpers, use known patterns.
    For others, try to build from available variables.
    """
    # Common reward helper patterns
    if "potential" in undefined_symbol.lower():
        # Potential-based reward: Phi(s) = -k_phi * |error|
        if "current_error" in available_variables:
            return "-0.5 * abs(current_error)"
        elif "error" in available_variables:
            return "-0.5 * abs(error)"
        elif "lateral_error" in available_variables:
            return "-0.5 * abs(lateral_error)"

    if "shaping" in undefined_symbol.lower():
        # Reward shaping: gamma * Phi(s') - Phi(s)
        if "current_error" in available_variables and "previous_error" in available_variables:
            return "0.99 * (-0.5 * abs(previous_error)) - (-0.5 * abs(current_error))"

    if "penalty" in undefined_symbol.lower():
        # Penalty term
        if "current_error" in available_variables:
            return "-1.0 * abs(current_error)"

    if "bonus" in undefined_symbol.lower():
        # Bonus term
        if "progress" in available_variables:
            return "0.1 * progress"

    # Generic fallback: try to use first available variable
    if available_variables:
        var = available_variables[0]
        return f"-0.1 * abs({var})"

    return ""


def _generate_helper_definition(
    undefined_symbol: str,
    available_variables: list[str],
    available_methods: list[str],
    class_source: str,
) -> str:
    """Generate complete helper method definition."""
    # Determine method signature from context
    if "self." in class_source:
        # It's a class method
        indent = _get_class_method_indent(class_source)
    else:
        indent = "    "

    # Generate method body based on name patterns
    if "potential" in undefined_symbol.lower():
        # Potential-based reward
        body = f"""{indent}def {undefined_symbol}(self):
{indent}    \"\"\"Compute potential-based reward.\"\"\"
{indent}    # Phi(s) = -k_phi * |error|
{indent}    k_phi = 0.5
{indent}    if hasattr(self, 'current_error'):
{indent}        return -k_phi * abs(self.current_error)
{indent}    return 0.0"""

    elif "penalty" in undefined_symbol.lower():
        # Penalty term
        body = f"""{indent}def {undefined_symbol}(self):
{indent}    \"\"\"Compute penalty term.\"\"\"
{indent}    if hasattr(self, 'current_error'):
{indent}        return -1.0 * abs(self.current_error)
{indent}    return 0.0"""

    elif "bonus" in undefined_symbol.lower():
        # Bonus term
        body = f"""{indent}def {undefined_symbol}(self):
{indent}    \"\"\"Compute bonus term.\"\"\"
{indent}    if hasattr(self, 'progress'):
{indent}        return 0.1 * self.progress
{indent}    return 0.0"""

    else:
        # Generic helper
        body = f"""{indent}def {undefined_symbol}(self):
{indent}    \"\"\"Compute reward helper.\"\"\"
{indent}    # TODO: Implement this helper
{indent}    return 0.0"""

    return body


def _get_class_method_indent(class_source: str) -> str:
    """Get the indentation level for class methods."""
    # Find first method definition
    match = re.search(r'\n(\s+)def \w+', class_source)
    if match:
        return match.group(1)
    return "    "


def _find_insertion_point(class_source: str, method_name: str) -> int:
    """Find the line number where to insert a new method."""
    lines = class_source.split("\n")
    # Find the last method definition
    last_method_line = -1
    for i, line in enumerate(lines):
        if re.match(r'\s+def \w+', line):
            last_method_line = i

    if last_method_line >= 0:
        return last_method_line + 1

    # If no methods found, find the class body
    for i, line in enumerate(lines):
        if re.match(r'class \w+', line):
            return i + 1

    return -1


def _replace_line_in_diff(diff: str, old_line: str, new_line: str) -> str:
    """Replace a line in a unified diff."""
    lines = diff.split("\n")
    result = []
    for line in lines:
        if line == old_line:
            result.append(new_line)
        else:
            result.append(line)
    return "\n".join(result)


def _add_helper_to_diff(diff: str, helper_def: str, insert_after_line: int) -> str:
    """Add helper method definition to a diff."""
    lines = diff.split("\n")
    result = []

    # Find the hunk that contains the insertion point
    current_new_line = 0
    in_hunk = False
    hunk_start = -1

    for i, line in enumerate(lines):
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            if match:
                current_new_line = int(match.group(1))
                in_hunk = True
                hunk_start = i
        elif line.startswith("+") and not line.startswith("+++"):
            current_new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            pass
        else:
            current_new_line += 1

        # Insert helper definition before the hunk that needs it
        if in_hunk and current_new_line >= insert_after_line and hunk_start >= 0:
            # Insert helper definition lines before this hunk
            for helper_line in helper_def.split("\n"):
                result.append(f"+{helper_line}")
            result.append("+")
            in_hunk = False

        result.append(line)

    return "\n".join(result)
