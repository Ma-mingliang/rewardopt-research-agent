"""Method selection with category filter, confidence sort, and dedup."""

from __future__ import annotations

from research_agent.reward_methods.schema import RewardMethodRecord


class MethodSelector:
    """Select methods from a pool for prompt injection."""

    CONFIDENCE_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}

    def __init__(self, methods: list[RewardMethodRecord]) -> None:
        self._methods = methods

    @property
    def total(self) -> int:
        return len(self._methods)

    @property
    def categories(self) -> list[str]:
        return sorted(set(m.category for m in self._methods))

    def select(
        self,
        categories: list[str] | None = None,
        top_k: int = 5,
        exclude_ids: set[str] | None = None,
    ) -> list[RewardMethodRecord]:
        """Select top-k methods filtered by categories and confidence.

        1. Filter to specified categories (or all if None)
        2. Exclude already-tried method IDs
        3. Sort by confidence (high > medium > low), then category
        4. Deduplicate by method_id (keep first occurrence)
        5. Return top_k results
        """
        exclude = exclude_ids or set()
        pool = self._methods

        if categories:
            cat_set = set(categories)
            pool = [m for m in pool if m.category in cat_set]

        pool = [m for m in pool if m.method_id not in exclude]

        pool.sort(key=lambda m: (
            self.CONFIDENCE_RANK.get(m.confidence, 1),
            m.category,
            m.method_id,
        ))

        seen: set[str] = set()
        deduped: list[RewardMethodRecord] = []
        for m in pool:
            if m.method_id not in seen:
                seen.add(m.method_id)
                deduped.append(m)

        return deduped[:top_k]

    def select_by_ids(self, method_ids: list[str]) -> list[RewardMethodRecord]:
        """Look up specific methods by their IDs."""
        id_set = set(method_ids)
        return [m for m in self._methods if m.method_id in id_set]
