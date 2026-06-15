"""Context-grounded proposal extraction for reward patch generation.

Extracts the reward function from env.py with line numbers, boundaries,
and indentation info so the LLM generates structurally valid patches.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProposalContext:
    """Structured context for a reward patch proposal."""

    target_file: str = "env.py"
    function_name: str = ""
    function_start_line: int = 0
    function_end_line: int = 0
    class_name: str = ""
    class_start_line: int = 0
    local_context_text: str = ""
    line_numbered_context: str = ""
    indentation_style: str = "spaces"
    indent_unit: int = 4
    base_indent: int = 0
    allowed_line_ranges: list[tuple[int, int]] = field(default_factory=list)
    forbidden_summary: str = ""
    existing_reward_terms: list[str] = field(default_factory=list)
    anchor_lines_before: str = ""
    anchor_lines_after: str = ""
    total_file_lines: int = 0

    @property
    def function_line_count(self) -> int:
        return self.function_end_line - self.function_start_line + 1


def detect_reward_function_bounds(
    source_text: str,
    target_function: str = "__calculate_reward",
) -> tuple[str, int, int, str, int] | None:
    """Detect reward function bounds using AST, with regex fallback.

    Returns (function_name, start_line, end_line, class_name, class_start_line)
    or None if not found.
    """
    # Try AST first
    try:
        tree = ast.parse(source_text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name == target_function or "reward" in item.name.lower():
                            return (
                                item.name,
                                item.lineno,
                                item.end_lineno or item.lineno,
                                node.name,
                                node.lineno,
                            )
        # Also check top-level functions
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if "reward" in node.name.lower():
                    return (
                        node.name,
                        node.lineno,
                        node.end_lineno or node.lineno,
                        "",
                        0,
                    )
    except SyntaxError:
        pass

    # Regex fallback
    lines = source_text.splitlines()
    pattern = re.compile(rf"\s+def {re.escape(target_function)}\s*\(")
    for i, line in enumerate(lines):
        if pattern.match(line):
            start = i + 1
            # Find end: next def/class at same or lower indent, or EOF
            base_indent = len(line) - len(line.lstrip())
            end = start
            for j in range(i + 1, len(lines)):
                stripped = lines[j].lstrip()
                if stripped and not stripped.startswith("#"):
                    current_indent = len(lines[j]) - len(stripped)
                    if current_indent <= base_indent and (
                        stripped.startswith("def ") or stripped.startswith("class ")
                    ):
                        end = j
                        break
                end = j + 1
            # Find enclosing class
            class_name = ""
            class_start = 0
            for j in range(i - 1, -1, -1):
                if lines[j].lstrip().startswith("class "):
                    class_name = lines[j].lstrip().split("(")[0].replace("class ", "").strip().rstrip(":")
                    class_start = j + 1
                    break
            return (target_function, start, end, class_name, class_start)

    return None


def build_line_numbered_context(
    source_text: str,
    start_line: int,
    end_line: int,
    radius: int = 5,
) -> str:
    """Build line-numbered context around a function.

    Returns lines with stable line numbers so the LLM knows exact edit locations.
    """
    lines = source_text.splitlines()
    total = len(lines)
    ctx_start = max(0, start_line - radius - 1)
    ctx_end = min(total, end_line + radius)

    result = []
    for i in range(ctx_start, ctx_end):
        line_num = i + 1
        marker = " >>> " if start_line <= line_num <= end_line else "     "
        result.append(f"{line_num:4d}{marker}{lines[i]}")
    return "\n".join(result)


def infer_indent_unit(source_text: str) -> tuple[str, int]:
    """Detect indentation style from source text.

    Returns (style, unit) where style is 'spaces' or 'tabs'.
    """
    lines = source_text.splitlines()
    space_counts: dict[int, int] = {}
    tab_count = 0

    for line in lines:
        if not line or line[0] not in (" ", "\t"):
            continue
        if line[0] == "\t":
            tab_count += 1
        else:
            indent = len(line) - len(line.lstrip())
            if indent > 0:
                space_counts[indent] = space_counts.get(indent, 0) + 1

    if tab_count > sum(space_counts.values()) * 0.5:
        return "tabs", 1

    if not space_counts:
        return "spaces", 4

    # Find GCD of common indent levels
    common_indents = sorted(space_counts.keys())
    if len(common_indents) == 1:
        return "spaces", common_indents[0]

    # Find smallest non-zero indent
    min_indent = min(k for k in common_indents if k > 0)
    # Check if it's a factor of most indents
    matches = sum(v for k, v in space_counts.items() if k % min_indent == 0)
    total = sum(space_counts.values())
    if matches / total > 0.8:
        return "spaces", min_indent

    return "spaces", 4


def extract_existing_reward_terms(source_text: str, function_name: str) -> list[str]:
    """Extract existing reward terms/variables from the reward function."""
    bounds = detect_reward_function_bounds(source_text, function_name)
    if not bounds:
        return []

    _, start, end, _, _ = bounds
    lines = source_text.splitlines()
    func_lines = lines[start - 1 : end]

    terms = set()
    for line in func_lines:
        # Match variable assignments like: reward_name = ...
        match = re.match(r"\s+(\w+)\s*=", line)
        if match:
            name = match.group(1)
            if "reward" in name.lower() or "penalty" in name.lower():
                terms.add(name)

    return sorted(terms)


def extract_editable_reward_context(
    project_path: Path,
    allowed_changes: list[str] | list[dict],
    target_file: str = "env.py",
    target_function: str = "__calculate_reward",
) -> ProposalContext | None:
    """Extract structured context for a reward patch proposal.

    Returns ProposalContext or None if the reward function cannot be found.
    """
    file_path = project_path / target_file
    if not file_path.exists():
        return None

    try:
        source_text = file_path.read_text(encoding="utf-8-sig")
    except Exception:
        return None

    bounds = detect_reward_function_bounds(source_text, target_function)
    if not bounds:
        return None

    func_name, start_line, end_line, class_name, class_start = bounds
    indent_style, indent_unit = infer_indent_unit(source_text)

    # Calculate base indentation
    lines = source_text.splitlines()
    base_indent = 0
    if start_line <= len(lines):
        base_indent = len(lines[start_line - 1]) - len(lines[start_line - 1].lstrip())

    # Build line-numbered context
    numbered_ctx = build_line_numbered_context(source_text, start_line, end_line)

    # Build local context (function body only)
    local_lines = lines[start_line - 1 : end_line]
    local_ctx = "\n".join(local_lines)

    # Allowed line ranges
    allowed_ranges = [(start_line, end_line)]

    # Forbidden summary
    forbidden = [
        "observation space", "action space", "reset logic",
        "train/eval logic", "imports", "model structure",
        "seed", "metrics", "algorithm body",
    ]
    forbidden_summary = ", ".join(forbidden)

    # Existing reward terms
    existing_terms = extract_existing_reward_terms(source_text, func_name)

    # Anchor lines (3 lines before and after function)
    anchor_before_lines = lines[max(0, start_line - 4) : start_line - 1]
    anchor_after_lines = lines[end_line : min(len(lines), end_line + 3)]
    anchor_before = "\n".join(f"  {start_line - len(anchor_before_lines) + i}: {l}" for i, l in enumerate(anchor_before_lines))
    anchor_after = "\n".join(f"  {end_line + 1 + i}: {l}" for i, l in enumerate(anchor_after_lines))

    return ProposalContext(
        target_file=target_file,
        function_name=func_name,
        function_start_line=start_line,
        function_end_line=end_line,
        class_name=class_name,
        class_start_line=class_start,
        local_context_text=local_ctx,
        line_numbered_context=numbered_ctx,
        indentation_style=indent_style,
        indent_unit=indent_unit,
        base_indent=base_indent,
        allowed_line_ranges=allowed_ranges,
        forbidden_summary=forbidden_summary,
        existing_reward_terms=existing_terms,
        anchor_lines_before=anchor_before,
        anchor_lines_after=anchor_after,
        total_file_lines=len(lines),
    )
