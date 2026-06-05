#!/usr/bin/env python3
"""Collect reward-function papers from arXiv."""

from __future__ import annotations

import argparse
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List

import requests

from pool_common import canonical_arxiv_id, load_taxonomy, paper_key, pool_path, write_jsonl


EXPANSION_TERMS = [
    "reinforcement learning reward design",
    "robot learning reward shaping",
    "multi objective reinforcement learning reward",
    "deep reinforcement learning reward function",
]

ARXIV_API_URL = "https://export.arxiv.org/api/query"
USER_AGENT = "research-agent-reward-paper-pool/1.0"
ATOM = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class ArxivApiClient:
    def __init__(self, delay_seconds: float = 3.0, session: requests.Session | None = None, now=None, sleep=None) -> None:
        self.delay_seconds = max(3.0, delay_seconds)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.now = now or time.monotonic
        self.sleep = sleep or time.sleep
        self.last_request_at: float | None = None

    def _wait_for_rate_limit(self) -> None:
        if self.last_request_at is not None:
            elapsed = self.now() - self.last_request_at
            wait_seconds = self.delay_seconds - elapsed
            if wait_seconds > 0:
                self.sleep(wait_seconds)
        self.last_request_at = self.now()

    def get(self, params: Dict[str, Any], timeout_seconds: float) -> requests.Response:
        self._wait_for_rate_limit()
        return self.session.get(ARXIV_API_URL, params=params, timeout=timeout_seconds)


def _entry_text(entry: ET.Element, name: str) -> str:
    child = entry.find(f"atom:{name}", ATOM)
    return (child.text or "").strip() if child is not None else ""


def _format_entry(entry: ET.Element, category: str, query: str) -> Dict[str, Any]:
    entry_id = _entry_text(entry, "id")
    arxiv_id = canonical_arxiv_id(entry_id)
    authors = [
        (author.find("atom:name", ATOM).text or "").strip()
        for author in entry.findall("atom:author", ATOM)
        if author.find("atom:name", ATOM) is not None
    ]
    pdf_url = ""
    for link in entry.findall("atom:link", ATOM):
        if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
            pdf_url = link.attrib.get("href", "")
            break
    published = _entry_text(entry, "published")
    primary = entry.find("arxiv:primary_category", ATOM)
    return {
        "paper_id": f"arxiv:{arxiv_id}" if arxiv_id else "",
        "arxiv_id": arxiv_id,
        "title": _entry_text(entry, "title").replace("\n", " ").strip(),
        "authors": authors,
        "year": int(published[:4]) if published[:4].isdigit() else None,
        "abstract": _entry_text(entry, "summary").replace("\n", " ").strip(),
        "url": entry_id,
        "pdf_url": pdf_url,
        "primary_category": primary.attrib.get("term", "") if primary is not None else "",
        "published_date": published,
        "updated_date": _entry_text(entry, "updated"),
        "categories": [category],
        "matched_keywords": [query],
        "source": "arxiv",
    }


def collect_for_keyword(
    category: str,
    query: str,
    max_results: int = 30,
    start: int = 0,
    timeout_seconds: float = 45.0,
    client: ArxivApiClient | None = None,
) -> List[Dict[str, Any]]:
    client = client or ArxivApiClient()
    resp = client.get(
        {
            "search_query": f'all:"{query}"',
            "start": start,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        },
        timeout_seconds=timeout_seconds,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    return [_format_entry(entry, category, query) for entry in root.findall("atom:entry", ATOM)]


def collect_with_retries(
    category: str,
    query: str,
    max_results: int,
    retries: int = 2,
    timeout_seconds: float = 45.0,
    client: ArxivApiClient | None = None,
) -> List[Dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return collect_for_keyword(
                category,
                query,
                max_results=max_results,
                start=0,
                timeout_seconds=timeout_seconds,
                client=client,
            )
        except requests.RequestException as exc:
            last_error = exc
            response = getattr(exc, "response", None)
            if response is not None and response.status_code == 429:
                if attempt < retries:
                    retry_after = response.headers.get("Retry-After", "")
                    try:
                        wait_seconds = float(retry_after)
                    except ValueError:
                        wait_seconds = 30.0
                    time.sleep(wait_seconds)
                    continue
                raise
            if attempt < retries:
                time.sleep(3.0 * (attempt + 1))
    raise last_error or RuntimeError("arxiv collection failed")


def merge_rows(existing: Dict[str, Dict[str, Any]], rows: Iterable[Dict[str, Any]]) -> None:
    for row in rows:
        key = paper_key(row)
        if key in existing:
            current = existing[key]
            current["categories"] = sorted(set(current.get("categories", [])) | set(row.get("categories", [])))
            current["matched_keywords"] = sorted(set(current.get("matched_keywords", [])) | set(row.get("matched_keywords", [])))
        else:
            existing[key] = row


def run_collect(
    base_dir: Path | None = None,
    max_results: int = 30,
    sleep_seconds: float = 3.0,
    retries: int = 2,
    timeout_seconds: float = 45.0,
) -> List[Dict[str, Any]]:
    base = pool_path(base_dir)
    taxonomy = load_taxonomy(base)
    collected: Dict[str, Dict[str, Any]] = {}
    by_category = {category: 0 for category in taxonomy["categories"]}
    errors = []
    client = ArxivApiClient(delay_seconds=sleep_seconds)

    def flush() -> None:
        rows = list(collected.values())
        if errors:
            rows.append({"source": "arxiv", "status": "partial_failure", "errors": errors})
        write_jsonl(base / "raw" / "arxiv_results.jsonl", rows)

    for category, meta in taxonomy["categories"].items():
        for keyword in meta.get("keywords", []):
            try:
                rows = collect_with_retries(
                    category,
                    keyword,
                    max_results=max_results,
                    retries=retries,
                    timeout_seconds=timeout_seconds,
                    client=client,
                )
                merge_rows(collected, rows)
                by_category[category] += len(rows)
            except Exception as exc:
                errors.append({"category": category, "query": keyword, "error": str(exc)})
            flush()
        if by_category[category] < int(meta.get("min_papers", 10)):
            for term in EXPANSION_TERMS:
                query = f"{meta['title']} {term}"
                try:
                    rows = collect_with_retries(
                        category,
                        query,
                        max_results=max_results,
                        retries=retries,
                        timeout_seconds=timeout_seconds,
                        client=client,
                    )
                    merge_rows(collected, rows)
                    by_category[category] += len(rows)
                except Exception as exc:
                    errors.append({"category": category, "query": query, "error": str(exc)})
                flush()
                if by_category[category] >= int(meta.get("min_papers", 10)):
                    break

    rows = list(collected.values())
    if errors:
        rows.append({"source": "arxiv", "status": "partial_failure", "errors": errors})
    write_jsonl(base / "raw" / "arxiv_results.jsonl", rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-results", type=int, default=30)
    parser.add_argument("--sleep-seconds", type=float, default=3.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    args = parser.parse_args()
    rows = run_collect(
        max_results=args.max_results,
        sleep_seconds=args.sleep_seconds,
        retries=args.retries,
        timeout_seconds=args.timeout_seconds,
    )
    print(f"wrote {len(rows)} arxiv rows")


if __name__ == "__main__":
    main()
