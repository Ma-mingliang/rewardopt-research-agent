"""Format method records for LLM prompt injection."""

from __future__ import annotations

from research_agent.reward_methods.schema import RewardMethodRecord


def format_method_context(methods: list[RewardMethodRecord]) -> str:
    """Format methods as rich context for the LLM prompt.

    Per method:
      [category] method_name (confidence: X)
        Core idea: ...
        Formula: ...
        Implementation: ...
        Applicable layers: layer1, layer2
        Applicable metrics: metric1, metric2
        Risks: risk1, risk2
    """
    if not methods:
        return "(no methods available)"

    parts: list[str] = []
    for m in methods:
        lines = [f"[{m.category}] {m.method_name} (confidence: {m.confidence})"]
        if m.core_idea:
            lines.append(f"  Core idea: {m.core_idea}")
        if m.reward_formula:
            lines.append(f"  Formula: {m.reward_formula}")
        if m.implementation_template:
            lines.append(f"  Implementation: {m.implementation_template}")
        if m.applicable_layers:
            lines.append(f"  Applicable layers: {', '.join(m.applicable_layers)}")
        if m.applicable_metrics:
            lines.append(f"  Applicable metrics: {', '.join(m.applicable_metrics)}")
        if m.risks:
            lines.append(f"  Risks: {'; '.join(m.risks)}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def format_method_brief(methods: list[RewardMethodRecord]) -> str:
    """Format methods as compact one-line-per-method summary."""
    if not methods:
        return "(no methods available)"

    parts: list[str] = []
    for m in methods:
        cat_short = m.category.split("_")[0] if "_" in m.category else m.category
        layers = ", ".join(m.applicable_layers) if m.applicable_layers else "n/a"
        parts.append(f"  [{cat_short}] {m.method_name}: {m.reward_formula} | layers: {layers}")

    return "\n".join(parts)


def build_source_meta_from_records(methods: list[RewardMethodRecord]) -> dict:
    """Build source_meta dict compatible with reward_patch_utils.build_source_meta()."""
    method_ids: list[str] = []
    categories: list[str] = []
    papers: list[str] = []

    for m in methods:
        method_ids.append(m.method_id)
        if m.category not in categories:
            categories.append(m.category)
        for p in m.source_papers:
            if p not in papers:
                papers.append(p)

    return {
        "source_method_ids": method_ids,
        "source_categories": categories,
        "source_papers": papers,
    }
