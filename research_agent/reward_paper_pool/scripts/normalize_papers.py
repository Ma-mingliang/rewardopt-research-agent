#!/usr/bin/env python3
"""Normalize raw paper and repository records into pool JSONL files."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

from pool_common import (
    canonical_arxiv_id,
    classify_text,
    empty_hrll_relevance,
    extract_arxiv_ids,
    infer_hrll_relevance,
    load_taxonomy,
    normalize_title,
    paper_key,
    parse_year,
    pool_path,
    read_jsonl,
    write_jsonl,
)


def _paper_id(row: Dict[str, Any]) -> str:
    arxiv_id = canonical_arxiv_id(row.get("arxiv_id", "") or row.get("url", "") or row.get("paper_id", ""))
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    if row.get("paper_id"):
        return str(row["paper_id"])
    return f"title:{normalize_title(row.get('title', ''))[:80]}"


def _base_paper(row: Dict[str, Any], taxonomy: Dict[str, Any]) -> Dict[str, Any]:
    categories = list(dict.fromkeys(row.get("categories", []) or []))
    text = f"{row.get('title', '')} {row.get('abstract', '')}"
    if not categories:
        categories = sorted(classify_text(text, taxonomy), key=classify_text(text, taxonomy).get, reverse=True)[:2]
    keywords = list(dict.fromkeys(row.get("matched_keywords", []) or row.get("keywords", []) or []))
    return {
        "paper_id": _paper_id(row),
        "title": row.get("title", ""),
        "authors": row.get("authors", []) or [],
        "year": parse_year(row.get("year") or row.get("published_date")) or 0,
        "venue": row.get("venue") or ("arXiv" if row.get("source") == "arxiv" else row.get("source", "")),
        "source": row.get("source", "raw"),
        "url": row.get("url", ""),
        "pdf_url": row.get("pdf_url", ""),
        "github_url": row.get("github_url", ""),
        "abstract": row.get("abstract", ""),
        "categories": categories,
        "keywords": keywords,
        "relevance_score": 0.0,
        "hrll_relevance": empty_hrll_relevance(),
        "status": "raw",
    }


def _score_paper(paper: Dict[str, Any], taxonomy: Dict[str, Any]) -> float:
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}"
    scores = classify_text(text, taxonomy)
    category_bonus = sum(scores.get(c, 0) for c in paper.get("categories", []))
    link_bonus = 2 if paper.get("github_url") else 0
    pdf_bonus = 1 if paper.get("pdf_url") else 0
    return round(min(1.0, (category_bonus + link_bonus + pdf_bonus) / 12.0), 3)


def _merge_paper(existing: Dict[str, Any], paper: Dict[str, Any]) -> None:
    for field in ("title", "url", "pdf_url", "abstract", "venue", "source"):
        if not existing.get(field) and paper.get(field):
            existing[field] = paper[field]
    existing["authors"] = existing.get("authors") or paper.get("authors", [])
    existing["year"] = existing.get("year") or paper.get("year", 0)
    existing["categories"] = sorted(set(existing.get("categories", [])) | set(paper.get("categories", [])))
    existing["keywords"] = sorted(set(existing.get("keywords", [])) | set(paper.get("keywords", [])))
    if paper.get("github_url") and not existing.get("github_url"):
        existing["github_url"] = paper["github_url"]


def _normalize_repo(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "repo": row.get("repo", ""),
        "url": row.get("url", ""),
        "stars": int(row.get("stars") or 0),
        "description": row.get("description", ""),
        "related_papers": list(dict.fromkeys(row.get("related_papers", []) or [])),
        "categories": row.get("categories", []) or [],
        "has_reward_code": bool(row.get("has_reward_code") or row.get("reward_files")),
        "reward_files": row.get("reward_files", []) or [],
        "license": row.get("license", ""),
        "last_updated": row.get("last_updated", ""),
    }


def _is_valid_paper_row(row: Dict[str, Any]) -> bool:
    if row.get("status") == "partial_failure" or row.get("errors"):
        return False
    return bool(row.get("title") and row.get("abstract") and row.get("url"))


def run_normalize(base_dir: Path | None = None) -> Dict[str, int]:
    base = pool_path(base_dir)
    taxonomy = load_taxonomy(base)
    raw_rows = [
        r
        for r in read_jsonl(base / "raw" / "arxiv_results.jsonl") + read_jsonl(base / "raw" / "openreview_results.jsonl")
        if _is_valid_paper_row(r)
    ]
    repos_raw = read_jsonl(base / "raw" / "github_results.jsonl")
    papers: Dict[str, Dict[str, Any]] = {}

    for row in raw_rows:
        paper = _base_paper(row, taxonomy)
        key = paper_key(row)
        if key in papers:
            _merge_paper(papers[key], paper)
        else:
            papers[key] = paper

    repos = []
    arxiv_to_key = {}
    for key, paper in papers.items():
        arxiv_id = canonical_arxiv_id(paper.get("paper_id", ""))
        if arxiv_id:
            arxiv_to_key[f"arxiv:{arxiv_id}"] = key

    for row in repos_raw:
        repo = _normalize_repo(row)
        readme = row.get("readme", "")
        related = set(repo["related_papers"])
        related.update(f"arxiv:{aid}" for aid in extract_arxiv_ids(readme))
        repo["related_papers"] = sorted(related)
        for paper_id in repo["related_papers"]:
            if paper_id in arxiv_to_key:
                papers[arxiv_to_key[paper_id]]["github_url"] = repo["url"]
        repos.append(repo)

    for paper in papers.values():
        paper["hrll_relevance"] = infer_hrll_relevance(f"{paper['title']} {paper['abstract']}", paper.get("categories", []))
        paper["relevance_score"] = _score_paper(paper, taxonomy)

    paper_rows = sorted(papers.values(), key=lambda p: (p.get("paper_id", ""), p.get("title", "")))
    write_jsonl(base / "paper_pool.jsonl", paper_rows)
    write_jsonl(base / "github_pool.jsonl", sorted(repos, key=lambda r: r.get("repo", "")))
    return {"papers": len(paper_rows), "repos": len(repos)}


def main() -> None:
    run_normalize()
    print("normalized paper_pool.jsonl and github_pool.jsonl")


if __name__ == "__main__":
    main()
