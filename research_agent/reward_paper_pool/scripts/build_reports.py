#!/usr/bin/env python3
"""Build Markdown category reports for the reward paper pool."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from pool_common import HRLL_LAYERS, load_taxonomy, pool_path, read_jsonl


REPORT_FILES = {
    "A_potential_based_reward": "A_potential_based_reward.md",
    "B_safety_constraint_reward": "B_safety_constraint_reward.md",
    "C_curriculum_subgoal_reward": "C_curriculum_subgoal_reward.md",
    "D_adaptive_dynamic_reward.md": "D_adaptive_dynamic_reward.md",
}


def _table(headers: List[str], rows: List[List[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("\n", " ") for cell in row) + " |")
    return "\n".join(lines)


def _report_path(category: str) -> str:
    return f"{category}.md"


def build_category_report(category: str, meta: Dict[str, Any], papers: List[Dict[str, Any]], repos: List[Dict[str, Any]], methods: List[Dict[str, Any]]) -> str:
    paper_rows = [
        [p.get("year", ""), f"[{p.get('title', '')}]({p.get('url', '')})", p.get("venue", ""), round(float(p.get("relevance_score", 0)), 3)]
        for p in papers[:15]
    ]
    repo_rows = [
        [f"[{r.get('repo', '')}]({r.get('url', '')})", r.get("stars", 0), ", ".join(r.get("reward_files", [])[:3]), r.get("license", "")]
        for r in repos[:10]
    ] or [["No linked repository yet", "", "", ""]]
    method_rows = [
        [m.get("method_name", ""), ", ".join(m.get("applicable_layers", [])), m.get("implementation_template", "")]
        for m in methods[:8]
    ] or [["No extracted method yet", "", ""]]
    lines = [
        f"# {category}: {meta.get('title', category)}",
        "",
        "## Category Definition",
        ", ".join(meta.get("feature_signals", [])),
        "",
        "## Typical Reward Formula",
        f"`{meta.get('typical_formula', '')}`",
        "",
        "## Representative Papers",
        _table(["Year", "Paper", "Venue", "Score"], paper_rows) if paper_rows else "No selected papers yet.",
        "",
        "## GitHub Implementations",
        _table(["Repo", "Stars", "Reward Files", "License"], repo_rows),
        "",
        "## HRRL Transfer",
        "Use the method only as a local reward component and keep safety checks outside the learned residual action.",
        "",
        "## Control Layer Fit",
        _table(["Layer", "Fit"], [[layer, "high" if any(layer in m.get("applicable_layers", []) for m in methods) else "unknown"] for layer in HRLL_LAYERS]),
        "",
        "## Agent-Executable Modification Templates",
        _table(["Method", "Layers", "Template"], method_rows),
        "",
        "## Risks And Reward Hacking",
        "- Proxy rewards can dominate true task success.",
        "- Safety penalties should be hard-gated where violations are unacceptable.",
        "- Dynamic or generated rewards require regression checks against baseline controllers.",
        "",
    ]
    return "\n".join(lines)


def run_build(base_dir: Path | None = None) -> Dict[str, int]:
    base = pool_path(base_dir)
    taxonomy = load_taxonomy(base)
    papers = read_jsonl(base / "paper_pool.jsonl")
    repos = read_jsonl(base / "github_pool.jsonl")
    methods = read_jsonl(base / "method_pool.jsonl")
    out_dir = base / "category_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for category, meta in taxonomy["categories"].items():
        cp = [p for p in papers if category in p.get("categories", [])]
        cr = [r for r in repos if category in r.get("categories", [])]
        cm = [m for m in methods if m.get("category") == category]
        (out_dir / _report_path(category)).write_text(build_category_report(category, meta, cp, cr, cm), encoding="utf-8")
        counts[category] = len(cp)
    return counts


def main() -> None:
    counts = run_build()
    print(f"built {len(counts)} category reports")


if __name__ == "__main__":
    main()
