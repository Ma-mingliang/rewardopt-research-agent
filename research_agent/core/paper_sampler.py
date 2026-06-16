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

    Category-based selection flow:
    1. User selects relevant categories via set_active_categories()
    2. Pick 2 methods from current category
    3. After category exhausted, move to next category
    4. Track improvement per category
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

        # Category-based selection state
        self._active_categories: list[str] = []  # user-selected categories in priority order
        self._current_cat_index: int = 0  # index into _active_categories
        self._category_improvements: dict[str, list[float]] = {}  # cat_id -> list of scores

    def set_active_categories(self, categories: list[str]):
        """Set the active categories for optimization (user-confirmed).

        Args:
            categories: List of category IDs in priority order.
        """
        self._active_categories = list(categories)
        self._current_cat_index = 0
        print(f"[SAMPLER] Active categories: {categories}", flush=True)

    def get_all_categories(self) -> list[dict]:
        """Return all categories with their method counts (for user selection)."""
        result = []
        for cat_id in self._sorted_categories():
            methods = self._methods_by_category.get(cat_id, [])
            tried = sum(1 for m in methods if m.get("method_id") in self._tried_ids)
            result.append({
                "category": cat_id,
                "total": len(methods),
                "tried": tried,
                "remaining": len(methods) - tried,
                "priority": self._taxonomy.get(cat_id, {}).get("priority", "B"),
                "description": self._taxonomy.get(cat_id, {}).get("description", ""),
            })
        return result

    def record_category_result(self, category: str, score: float):
        """Record the fair eval score for a category (for tracking improvement).

        Args:
            category: Category ID.
            score: Composite score from fair eval (positive = improvement).
        """
        if category not in self._category_improvements:
            self._category_improvements[category] = []
        self._category_improvements[category].append(score)

    def get_next_batch(self, batch_size: int = 2) -> tuple[list[dict], bool]:
        """Pick next batch from current active category.

        Selection logic:
        1. Pick from _active_categories[_current_cat_index]
        2. If current category has fewer methods than batch_size, fill from next categories
        3. If current category exhausted, move to next
        4. If all categories exhausted, return empty

        Args:
            batch_size: Number of methods to pick.

        Returns:
            Tuple of (list of method dicts, did_fallback).
            Empty list if all exhausted.
        """
        if not self._active_categories:
            # Fallback: use all categories sorted by priority
            return self._get_batch_from_all(batch_size), False

        while self._current_cat_index < len(self._active_categories):
            cat_id = self._active_categories[self._current_cat_index]
            methods = self._methods_by_category.get(cat_id, [])
            untried = [m for m in methods if m.get("method_id") not in self._tried_ids]
            untried.sort(key=lambda m: {"high": 0, "medium": 1, "low": 2}.get(m.get("confidence", "low"), 2))

            if untried:
                batch = [self._enrich_with_paper(m) for m in untried[:batch_size]]
                did_fallback = False

                # Fill from next categories if batch is undersized
                if len(batch) < batch_size:
                    remaining = batch_size - len(batch)
                    batch_ids = {m.get("method_id") for m in batch}
                    for next_idx in range(self._current_cat_index + 1, len(self._active_categories)):
                        if remaining <= 0:
                            break
                        next_cat = self._active_categories[next_idx]
                        next_methods = self._methods_by_category.get(next_cat, [])
                        next_untried = [
                            m for m in next_methods
                            if m.get("method_id") not in self._tried_ids
                            and m.get("method_id") not in batch_ids
                        ]
                        next_untried.sort(key=lambda m: {"high": 0, "medium": 1, "low": 2}.get(m.get("confidence", "low"), 2))
                        for m in next_untried:
                            if remaining <= 0:
                                break
                            batch.append(self._enrich_with_paper(m))
                            batch_ids.add(m.get("method_id"))
                            remaining -= 1
                            did_fallback = True

                    if did_fallback:
                        print(f"[SAMPLER] Cross-category fallback: filled batch to {len(batch)} methods", flush=True)

                return batch, did_fallback
            else:
                # Current category exhausted, move to next
                print(f"[SAMPLER] Category '{cat_id}' exhausted, moving to next.", flush=True)
                self._current_cat_index += 1

        return [], False  # All categories exhausted

    def _get_batch_from_all(self, batch_size: int) -> list[dict]:
        """Fallback: pick from all categories sorted by priority."""
        for cat_id in self._sorted_categories():
            methods = self._methods_by_category.get(cat_id, [])
            untried = [m for m in methods if m.get("method_id") not in self._tried_ids]
            untried.sort(key=lambda m: {"high": 0, "medium": 1, "low": 2}.get(m.get("confidence", "low"), 2))
            batch = []
            for method in untried:
                if len(batch) >= batch_size:
                    return batch
                batch.append(self._enrich_with_paper(method))
            if batch:
                return batch
        return []

    def get_current_category(self) -> str | None:
        """Return the currently active category, or None if exhausted."""
        if self._active_categories and self._current_cat_index < len(self._active_categories):
            return self._active_categories[self._current_cat_index]
        return None

    def get_category_improvements(self) -> dict[str, dict]:
        """Return improvement stats per category."""
        result = {}
        for cat_id, scores in self._category_improvements.items():
            if scores:
                result[cat_id] = {
                    "mean_score": sum(scores) / len(scores),
                    "max_score": max(scores),
                    "count": len(scores),
                    "improved": sum(1 for s in scores if s > 0),
                }
        return result

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
        """Sort taxonomy categories by priority (S > A > B), then by id.

        Falls back to categories from methods_by_category if taxonomy is empty.
        """
        if self._taxonomy:
            cats = list(self._taxonomy.items())
            cats.sort(key=lambda item: (_PRIORITY_ORDER.get(item[1].get("priority", "B"), 2), item[0]))
            return [cat_id for cat_id, _ in cats]
        # Fallback: use categories from method pool, sorted alphabetically
        return sorted(self._methods_by_category.keys())

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
