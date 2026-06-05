#!/usr/bin/env python3
"""Collect reward-function papers from OpenReview search endpoints."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Dict, List

import requests

from pool_common import load_taxonomy, parse_year, pool_path, title_hash, write_jsonl


BASE_URL = "https://api2.openreview.net/notes/search"


def search_openreview(query: str, limit: int = 30) -> List[Dict[str, Any]]:
    resp = requests.get(BASE_URL, params={"term": query, "limit": limit, "offset": 0}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("notes", []) or data.get("results", []) or []


def _content_value(content: Dict[str, Any], key: str) -> Any:
    value = (content or {}).get(key)
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def format_note(note: Dict[str, Any], category: str, query: str) -> Dict[str, Any]:
    content = note.get("content", {}) or {}
    title = _content_value(content, "title") or note.get("forum") or note.get("id", "")
    abstract = _content_value(content, "abstract") or ""
    authors = _content_value(content, "authors") or []
    if isinstance(authors, str):
        authors = [authors]
    year = parse_year(note.get("cdate") or note.get("pdate") or note.get("tmdate"))
    note_id = note.get("id", title_hash(title))
    return {
        "paper_id": f"openreview:{note_id}",
        "title": title,
        "authors": authors,
        "year": year,
        "venue": "OpenReview",
        "source": "openreview",
        "url": f"https://openreview.net/forum?id={note.get('forum') or note_id}",
        "pdf_url": f"https://openreview.net/pdf?id={note_id}",
        "abstract": abstract,
        "categories": [category],
        "matched_keywords": [query],
        "openreview_id": note_id,
    }


def run_collect(base_dir: Path | None = None, limit: int = 30, sleep_seconds: float = 3.0) -> List[Dict[str, Any]]:
    base = pool_path(base_dir)
    taxonomy = load_taxonomy(base)
    rows: Dict[str, Dict[str, Any]] = {}
    errors = []
    for category, meta in taxonomy["categories"].items():
        for keyword in meta.get("keywords", [])[:4]:
            try:
                for note in search_openreview(keyword, limit=limit):
                    row = format_note(note, category, keyword)
                    key = row["paper_id"]
                    if key in rows:
                        rows[key]["categories"] = sorted(set(rows[key]["categories"]) | {category})
                    else:
                        rows[key] = row
            except Exception as exc:
                errors.append({"category": category, "query": keyword, "error": str(exc)})
            time.sleep(max(3.0, sleep_seconds))
    output = list(rows.values())
    if errors:
        output.append({"source": "openreview", "status": "partial_failure", "errors": errors})
    write_jsonl(base / "raw" / "openreview_results.jsonl", output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--sleep-seconds", type=float, default=3.0)
    args = parser.parse_args()
    rows = run_collect(limit=args.limit, sleep_seconds=args.sleep_seconds)
    print(f"wrote {len(rows)} openreview rows")


if __name__ == "__main__":
    main()
