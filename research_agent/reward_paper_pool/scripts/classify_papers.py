#!/usr/bin/env python3
"""Rule-first paper classification for reward method taxonomy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from pool_common import classify_text, infer_hrll_relevance, keyword_hits, load_taxonomy, pool_path, read_jsonl, write_jsonl


def classify_paper(paper: Dict[str, Any], taxonomy: Dict[str, Any]) -> Dict[str, Any]:
    text = f"{paper.get('title', '')} {paper.get('abstract', '')} {' '.join(paper.get('keywords', []))}"
    scores = classify_text(text, taxonomy)
    for category in paper.get("categories", []) or []:
        if category in taxonomy.get("categories", {}):
            scores[category] = scores.get(category, 0) + 2
    if scores:
        categories = sorted(scores, key=scores.get, reverse=True)[:3]
    else:
        categories = paper.get("categories", []) or []
    paper["categories"] = categories
    paper["keywords"] = sorted(set(paper.get("keywords", [])) | {
        hit
        for category in categories
        for hit in keyword_hits(text, taxonomy["categories"][category].get("keywords", []))
    })
    paper["relevance_score"] = round(min(1.0, sum(scores.get(c, 0) for c in categories) / 12.0), 3)
    paper["hrll_relevance"] = infer_hrll_relevance(text, categories)
    paper["status"] = "classified" if categories else "raw"
    return paper


def _write_missing(base: Path, taxonomy: Dict[str, Any], papers: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {category: 0 for category in taxonomy["categories"]}
    for paper in papers:
        for category in paper.get("categories", []):
            if category in counts:
                counts[category] += 1
    missing = {c: meta["min_papers"] - counts.get(c, 0) for c, meta in taxonomy["categories"].items() if counts.get(c, 0) < meta["min_papers"]}
    if missing:
        lines = ["# Missing Reward Paper Categories", ""]
        for category, needed in missing.items():
            meta = taxonomy["categories"][category]
            lines.append(f"## {category}")
            lines.append(f"- Current: {counts.get(category, 0)}")
            lines.append(f"- Need: {needed}")
            lines.append(f"- Suggested expanded keywords: {', '.join(meta.get('keywords', [])[-4:])}")
            lines.append("")
        (base / "missing_categories.md").write_text("\n".join(lines), encoding="utf-8")
    elif (base / "missing_categories.md").exists():
        (base / "missing_categories.md").unlink()
    return counts


def run_classify(base_dir: Path | None = None, use_llm: bool = False) -> Dict[str, int]:
    base = pool_path(base_dir)
    taxonomy = load_taxonomy(base)
    papers = [classify_paper(p, taxonomy) for p in read_jsonl(base / "paper_pool.jsonl")]
    write_jsonl(base / "paper_pool.jsonl", papers)
    return _write_missing(base, taxonomy, papers)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--use-llm", action="store_true")
    args = parser.parse_args()
    counts = run_classify(use_llm=args.use_llm)
    print(json.dumps(counts, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
