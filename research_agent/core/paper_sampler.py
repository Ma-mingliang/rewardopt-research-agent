"""Paper sampler: iterative method selection from the reward paper pool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


# Priority order: S first, then A, then B
_PRIORITY_ORDER = {"S": 0, "A": 1, "B": 2}


class PaperSampler:
    """Manages iterative paper/method selection from the reward paper pool.

    Picks 1-2 methods per round from the highest-priority untried category.
    Tracks which methods have been tried via tried_methods.jsonl.
    """

    def __init__(self, pool_dir: Path, work_dir: Path):
        """Load paper_pool, method_pool, taxonomy, and tried_methods.

        Args:
            pool_dir: Path to reward_paper_pool directory.
            work_dir: Path to .research-agent work directory.
        """
        self._pool_dir = pool_dir
        self._work_dir = work_dir

        self._taxonomy = self._load_taxonomy(pool_dir / "taxonomy.yaml")
        self._methods_by_category: dict[str, list[dict]] = self._load_methods(pool_dir / "method_pool.jsonl")
        self._papers_by_id: dict[str, dict] = self._load_papers(pool_dir / "paper_pool.jsonl")
        self._tried_ids: set[str] = self._load_tried(work_dir / "logs" / "tried_methods.jsonl")

    def get_next_batch(self, batch_size: int = 2) -> list[dict]:
        """Pick next 1-2 methods from highest-priority untried category.

        Selection logic:
        - Sort categories by priority (S > A > B)
        - Within each category, prefer methods with confidence "high" first
        - Skip methods already in tried_methods
        - Attach source_paper info from paper_pool

        Returns:
            List of method dicts (may be empty if all tried).
        """
        sorted_cats = self._sorted_categories()
        batch: list[dict] = []

        for cat_id in sorted_cats:
            methods = self._methods_by_category.get(cat_id, [])
            untried = [m for m in methods if m.get("method_id") not in self._tried_ids]
            # Sort by confidence: high > medium > low
            untried.sort(key=lambda m: {"high": 0, "medium": 1, "low": 2}.get(m.get("confidence", "low"), 2))

            for method in untried:
                if len(batch) >= batch_size:
                    return batch
                enriched = self._enrich_with_paper(method)
                batch.append(enriched)

        return batch

    def mark_used(self, methods: list[dict], candidate_id: str = "", status: str = "tried",
                  phase_id: str = "", accepted: bool | None = None, reason: str = "",
                  metrics_before: dict | None = None, metrics_after: dict | None = None):
        """Mark methods as tried (persists to tried_methods.jsonl).

        Args:
            methods: List of method dicts (must have method_id).
            candidate_id: ID of the candidate that used these methods.
            status: Outcome status (tried/accepted/rejected/noop/error).
            phase_id: Phase that consumed these methods.
            accepted: Whether the candidate was accepted (None if unknown).
            reason: Reason for status (e.g. rejection reason).
            metrics_before: Baseline metrics before this candidate.
            metrics_after: Metrics after this candidate.
        """
        from datetime import datetime, timezone

        method_ids = [m.get("method_id", "") for m in methods if m.get("method_id")]
        self._tried_ids.update(method_ids)

        log_path = self._work_dir / "logs" / "tried_methods.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            for method in methods:
                mid = method.get("method_id", "")
                if not mid:
                    continue
                source_papers = method.get("source_papers", [])
                if not source_papers and method.get("source_paper"):
                    sp = method.get("source_paper", {})
                    source_papers = [sp.get("paper_id", "")]
                record = {
                    "method_id": mid,
                    "category": method.get("category", ""),
                    "source_papers": source_papers,
                    "phase_id": phase_id,
                    "candidate_id": candidate_id,
                    "accepted": accepted,
                    "status": status,
                    "reason": reason,
                    "metrics_before": metrics_before,
                    "metrics_after": metrics_after,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                f.write(json.dumps(record) + "\n")

    def remaining_categories(self) -> list[str]:
        """List categories with untried methods."""
        result = []
        for cat_id in self._sorted_categories():
            methods = self._methods_by_category.get(cat_id, [])
            untried = [m for m in methods if m.get("method_id") not in self._tried_ids]
            if untried:
                result.append(cat_id)
        return result

    def summary(self) -> dict:
        """Return summary of tried/remaining methods by category."""
        by_category: dict[str, dict[str, int]] = {}
        for cat_id, methods in self._methods_by_category.items():
            tried = sum(1 for m in methods if m.get("method_id") in self._tried_ids)
            by_category[cat_id] = {"tried": tried, "remaining": len(methods) - tried}

        return {
            "tried": len(self._tried_ids),
            "total": sum(len(m) for m in self._methods_by_category.values()),
            "categories_remaining": len(self.remaining_categories()),
            "by_category": by_category,
        }

    # ── private helpers ──────────────────────────────────

    def _sorted_categories(self) -> list[str]:
        """Sort taxonomy categories by priority (S > A > B), then by id."""
        cats = list(self._taxonomy.items())
        cats.sort(key=lambda item: (_PRIORITY_ORDER.get(item[1].get("priority", "B"), 2), item[0]))
        return [cat_id for cat_id, _ in cats]

    def _enrich_with_paper(self, method: dict) -> dict:
        """Attach source paper info to a method dict."""
        enriched = dict(method)
        source_papers = method.get("source_papers", [])
        if source_papers:
            paper_id = source_papers[0]
            paper = self._papers_by_id.get(paper_id, {})
            enriched["source_paper"] = {
                "paper_id": paper_id,
                "title": paper.get("title", ""),
                "abstract": paper.get("abstract", "")[:500],
            }
        return enriched

    @staticmethod
    def _load_taxonomy(path: Path) -> dict:
        """Load taxonomy.yaml."""
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("categories", {})

    @staticmethod
    def _load_methods(path: Path) -> dict[str, list[dict]]:
        """Load method_pool.jsonl, grouped by category."""
        by_cat: dict[str, list[dict]] = {}
        if not path.exists():
            return by_cat
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    m = json.loads(line)
                    cat = m.get("category", "unknown")
                    by_cat.setdefault(cat, []).append(m)
                except json.JSONDecodeError:
                    continue
        return by_cat

    @staticmethod
    def _load_papers(path: Path) -> dict[str, dict]:
        """Load paper_pool.jsonl, indexed by paper_id."""
        by_id: dict[str, dict] = {}
        if not path.exists():
            return by_id
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    p = json.loads(line)
                    pid = p.get("paper_id", "")
                    if pid:
                        by_id[pid] = p
                except json.JSONDecodeError:
                    continue
        return by_id

    @staticmethod
    def _load_tried(path: Path) -> set[str]:
        """Load tried method IDs from JSONL."""
        tried: set[str] = set()
        if not path.exists():
            return tried
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    mid = entry.get("method_id", "")
                    if mid:
                        tried.add(mid)
                except json.JSONDecodeError:
                    continue
        return tried
