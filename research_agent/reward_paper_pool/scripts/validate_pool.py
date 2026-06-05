#!/usr/bin/env python3
"""Validate Reward Function Paper Pool V1 quality gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from pool_common import HRLL_LAYERS, load_taxonomy, normalize_title, pool_path, read_jsonl


def _count_categories(papers: List[Dict[str, Any]], categories: List[str]) -> Dict[str, int]:
    counts = {category: 0 for category in categories}
    for paper in papers:
        for category in paper.get("categories", []):
            if category in counts:
                counts[category] += 1
    return counts


def _duplicate_ratio(papers: List[Dict[str, Any]]) -> float:
    if not papers:
        return 0.0
    titles = [normalize_title(p.get("title", "")) for p in papers if p.get("title")]
    unique = set(titles)
    return round((len(titles) - len(unique)) / max(len(titles), 1), 4)


def _validate_report(report: Dict[str, Any]) -> str:
    lines = ["# Reward Paper Pool Validation Report", ""]
    lines.append(f"Hard checks passed: {'YES' if report['hard_checks_passed'] else 'NO'}")
    lines.append("")
    lines.append("## Summary")
    for key, value in report["summary"].items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Hard Checks")
    for check in report["checks"]:
        icon = "PASS" if check["passed"] else "FAIL"
        lines.append(f"- {icon}: {check['name']} ({check['detail']})")
    lines.append("")
    lines.append("## Category Counts")
    for category, count in report["category_counts"].items():
        lines.append(f"- {category}: {count}")
    lines.append("")
    return "\n".join(lines)


def run_validate(base_dir: Path | None = None) -> Dict[str, Any]:
    base = pool_path(base_dir)
    taxonomy = load_taxonomy(base)
    categories = list(taxonomy["categories"].keys())
    papers = read_jsonl(base / "paper_pool.jsonl")
    methods = read_jsonl(base / "method_pool.jsonl")
    repos = read_jsonl(base / "github_pool.jsonl")

    category_counts = _count_categories(papers, categories)
    method_counts = {category: 0 for category in categories}
    template_counts = {category: 0 for category in categories}
    for method in methods:
        category = method.get("category")
        if category in method_counts:
            method_counts[category] += 1
            if method.get("implementation_template"):
                template_counts[category] += 1

    checks = []
    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    missing_category = {c: count for c, count in category_counts.items() if count < taxonomy["categories"][c]["min_papers"]}
    add("each category has >= 10 papers", not missing_category, json.dumps(missing_category, ensure_ascii=False))
    bad_papers = [p.get("paper_id", p.get("title", "")) for p in papers if not p.get("title") or not p.get("abstract") or not p.get("url")]
    add("each paper has title abstract url", not bad_papers, f"bad={len(bad_papers)}")
    bad_methods = [
        m.get("method_id", "")
        for m in methods
        if not m.get("method_name") or not m.get("category") or not m.get("core_idea") or not m.get("implementation_template")
    ]
    add("each method has required fields", not bad_methods, f"bad={len(bad_methods)}")
    linked_repos = [r for r in repos if r.get("related_papers")]
    add("at least 5 github repos linked", len(linked_repos) >= 5, f"linked={len(linked_repos)}")
    dup_ratio = _duplicate_ratio(papers)
    add("duplicate papers <= 5%", dup_ratio <= 0.05, f"duplicate_ratio={dup_ratio}")
    lacking_templates = {c: n for c, n in template_counts.items() if n < 3}
    add("each category has >= 3 method templates", not lacking_templates, json.dumps(lacking_templates, ensure_ascii=False))
    add("8 categories exist", len(categories) == 8, f"categories={len(categories)}")
    add("total papers >= 80", len(papers) >= 80, f"papers={len(papers)}")
    add("github projects >= 10", len(repos) >= 10, f"repos={len(repos)}")
    add("method_pool >= 30", len(methods) >= 30, f"methods={len(methods)}")
    residual_methods = [m for m in methods if set(m.get("applicable_layers", [])) & {"lqr_residual", "stanley_residual"}]
    add("at least 10 methods apply to HRRL/residual control", len(residual_methods) >= 10, f"methods={len(residual_methods)}")
    for layer in ("lqr_residual", "stanley_residual", "safety_gate"):
        count = sum(1 for m in methods if layer in m.get("applicable_layers", []))
        add(f"at least 5 methods apply to {layer}", count >= 5, f"methods={count}")

    report = {
        "hard_checks_passed": all(c["passed"] for c in checks),
        "summary": {
            "total_papers": len(papers),
            "total_methods": len(methods),
            "total_github_repos": len(repos),
            "linked_github_repos": len(linked_repos),
            "duplicate_ratio": dup_ratio,
        },
        "category_counts": category_counts,
        "method_counts": method_counts,
        "checks": checks,
    }
    (base / "validation_report.md").write_text(_validate_report(report), encoding="utf-8")
    return report


def main() -> None:
    report = run_validate()
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
