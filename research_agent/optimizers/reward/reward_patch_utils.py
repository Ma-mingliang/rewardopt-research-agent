"""Shared reward patch utilities extracted from RewardOptimizer.

These stateless functions are used by both the legacy RewardOptimizer
and the LangGraph-based LangGraphRewardOptimizer.
"""

from __future__ import annotations

import re
from pathlib import Path


def fix_diff_line_counts(diff: str) -> str:
    """Fix line counts in @@ headers to match actual diff content."""
    lines = diff.split("\n")
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("@@"):
            match = re.match(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@", line)
            if match:
                old_start = match.group(1)
                new_start = match.group(3)

                old_count = 0
                new_count = 0
                j = i + 1
                while j < len(lines):
                    l = lines[j]
                    if l.startswith("@@") or l.startswith("---") or l.startswith("+++"):
                        break
                    if l.startswith("-"):
                        old_count += 1
                    elif l.startswith("+"):
                        new_count += 1
                    elif l.startswith(" ") or l == "":
                        old_count += 1
                        new_count += 1
                    j += 1

                result.append(f"@@ -{old_start},{old_count} +{new_start},{new_count} @@")
                i += 1
                continue
        result.append(line)
        i += 1

    return "\n".join(result)


def parse_error_line(error: str) -> int | None:
    """Extract line number from SyntaxError message."""
    match = re.search(r"line (\d+)", error)
    if match:
        return int(match.group(1))
    return None


def extract_target_context(
    project_path: Path,
    error_line: int,
    allowed_changes: list[dict],
    context_radius: int = 10,
) -> str:
    """Extract code context around the error line with exact indentation."""
    if not allowed_changes:
        return "(no allowed changes specified)"
    file_name = allowed_changes[0].get("file", "env.py") if allowed_changes else "env.py"
    if isinstance(allowed_changes[0], str):
        file_name = allowed_changes[0]
    file_path = project_path / file_name

    if not file_path.exists():
        return "(file not found)"

    try:
        content = file_path.read_text(encoding="utf-8-sig")
        lines = content.splitlines()
        start = max(0, error_line - context_radius - 1)
        end = min(len(lines), error_line + context_radius)
        context_lines = []
        for i in range(start, end):
            marker = " >>> " if i == error_line - 1 else "     "
            context_lines.append(f"{i+1:4d}{marker}{lines[i]}")
        return "\n".join(context_lines)
    except Exception:
        return "(could not read file)"


def auto_fix_indentation(
    project_path: Path,
    diff: str,
    allowed_changes: list[dict],
) -> str | None:
    """Try to automatically fix indentation issues in a diff.

    Returns fixed diff if successful, None if cannot fix.
    """
    lines = diff.split("\n")
    added_lines = []
    for line in lines:
        if line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line[1:])

    if not added_lines:
        return None

    file_name = allowed_changes[0].get("file", "env.py") if allowed_changes else "env.py"
    if isinstance(allowed_changes[0], str):
        file_name = allowed_changes[0]
    file_path = project_path / file_name

    if not file_path.exists():
        return None

    try:
        original = file_path.read_text(encoding="utf-8-sig")
        original_lines = original.splitlines()
    except Exception:
        return None

    header_match = re.search(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@", diff)
    if not header_match:
        return None

    target_start = int(header_match.group(1)) - 1  # 0-indexed

    if target_start >= len(original_lines):
        return None

    ref_line_idx = target_start
    while ref_line_idx >= 0 and original_lines[ref_line_idx].strip() == "":
        ref_line_idx -= 1

    if ref_line_idx < 0:
        return None

    ref_indent = len(original_lines[ref_line_idx]) - len(original_lines[ref_line_idx].lstrip())

    added_indents = []
    for line in added_lines:
        if line.strip():
            added_indents.append(len(line) - len(line.lstrip()))

    if not added_indents:
        return None

    min_indent = min(added_indents)
    max_indent = max(added_indents)

    if max_indent - min_indent > 4:
        fixed_lines = []
        for line in added_lines:
            if line.strip():
                current_indent = len(line) - len(line.lstrip())
                relative_indent = current_indent - min_indent
                new_indent = ref_indent + relative_indent
                fixed_lines.append(" " * new_indent + line.lstrip())
            else:
                fixed_lines.append("")

        result = []
        added_idx = 0
        for line in lines:
            if line.startswith("+") and not line.startswith("+++"):
                if added_idx < len(fixed_lines):
                    result.append("+" + fixed_lines[added_idx])
                    added_idx += 1
            else:
                result.append(line)

        return "\n".join(result)

    return None


def build_source_meta(ideas: list[dict]) -> dict:
    """Extract source metadata from ideas for candidate tracking."""
    method_ids = []
    categories = []
    source_papers = []
    for idea in ideas:
        mid = idea.get("method_id", "")
        if mid:
            method_ids.append(mid)
        cat = idea.get("category", "")
        if cat and cat not in categories:
            categories.append(cat)
        papers = idea.get("source_papers", [])
        for p in papers:
            if p not in source_papers:
                source_papers.append(p)
        sp = idea.get("source_paper", {})
        pid = sp.get("paper_id", "")
        if pid and pid not in source_papers:
            source_papers.append(pid)
    return {
        "source_method_ids": method_ids,
        "source_categories": categories,
        "source_papers": source_papers,
        "source_idea": "pool_methods" if method_ids else "extracted_ideas",
    }


def format_baseline(metrics: dict[str, dict[str, float]]) -> str:
    """Format baseline metrics as a human-readable string."""
    lines = []
    for name, vals in metrics.items():
        mean = vals.get("mean", 0)
        std = vals.get("std", 0)
        lines.append(f"  {name}: {mean:.4f} (std: {std:.4f})")
    return "\n".join(lines) if lines else "  (no baseline metrics)"


def format_ideas(ideas: list[dict]) -> str:
    """Format ideas list as a human-readable string for prompts."""
    if not ideas:
        return "  (no ideas available)"
    lines = []
    for idea in ideas[:5]:
        cat = idea.get("category", "")
        desc = idea.get("description", "")
        if idea.get("implementation_template"):
            core = idea.get("core_idea", desc)
            formula = idea.get("reward_formula", "N/A")
            template = idea.get("implementation_template", "N/A")
            layers = ", ".join(idea.get("applicable_layers", []))
            metrics = ", ".join(idea.get("applicable_metrics", []))
            risks = ", ".join(idea.get("risks", [])[:2])
            lines.append(f"  [{cat}] {core}")
            lines.append(f"    Formula: {formula}")
            lines.append(f"    Template: {template}")
            if layers:
                lines.append(f"    Layers: {layers}")
            if metrics:
                lines.append(f"    Metrics: {metrics}")
            if risks:
                lines.append(f"    Risks: {risks}")
        else:
            lines.append(f"  - [{cat}] {desc}")
    return "\n".join(lines)


def add_diff_header_if_missing(diff: str, file_name: str) -> str:
    """Add unified diff header (--- / +++) if missing."""
    if not diff.startswith("---"):
        return f"--- a/{file_name}\n+++ b/{file_name}\n{diff}"
    return diff
