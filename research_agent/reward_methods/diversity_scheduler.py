"""Template diversity scheduler for method pool selection.

Ensures that across multiple iterations, candidates are drawn from
diverse reward categories rather than repeating the same template type.
"""

from __future__ import annotations

from collections import Counter

from research_agent.reward_methods.schema import RewardMethodRecord


class DiversityScheduler:
    """Re-rank method pool to favor under-represented categories.

    Tracks category usage across iterations and applies a diversity
    bonus to methods from categories that have been selected less often.
    """

    def __init__(self, diversity_weight: float = 0.3) -> None:
        self._diversity_weight = diversity_weight
        self._category_counts: Counter[str] = Counter()
        self._selected_method_ids: list[str] = []

    @property
    def category_counts(self) -> dict[str, int]:
        return dict(self._category_counts)

    @property
    def selected_method_ids(self) -> list[str]:
        return list(self._selected_method_ids)

    def record_selection(self, method_id: str, category: str) -> None:
        """Record that a method was selected in an iteration."""
        self._selected_method_ids.append(method_id)
        self._category_counts[category] += 1

    def compute_diversity_score(self) -> float:
        """Compute current diversity score [0, 1].

        1.0 = perfectly uniform across categories.
        0.0 = all selections from one category.
        """
        if not self._category_counts:
            return 1.0
        total = sum(self._category_counts.values())
        n_cats = len(self._category_counts)
        if n_cats <= 1:
            return 0.0 if total > 0 else 1.0
        max_per_cat = total / n_cats
        return 1.0 - sum(abs(c - max_per_cat) for c in self._category_counts.values()) / (2 * total)

    def rank_for_diversity(
        self,
        pool: list[RewardMethodRecord],
        exclude_ids: set[str] | None = None,
    ) -> list[RewardMethodRecord]:
        """Re-rank pool to favor under-represented categories.

        Methods from categories with fewer prior selections get a
        diversity bonus that moves them up the ranking. Methods whose
        IDs are in exclude_ids are removed entirely.

        Returns a new sorted list (does not mutate the input).
        """
        exclude = exclude_ids or set()
        filtered = [m for m in pool if m.method_id not in exclude]
        if not filtered:
            return []

        if not self._category_counts:
            return filtered

        max_count = max(self._category_counts.values()) if self._category_counts else 1

        def sort_key(m: RewardMethodRecord) -> tuple[float, str]:
            cat_count = self._category_counts.get(m.category, 0)
            # Diversity bonus: categories with fewer selections rank higher
            diversity_bonus = (max_count - cat_count) * self._diversity_weight
            # Negate so higher bonus = earlier in sort
            return (-diversity_bonus, m.category)

        return sorted(filtered, key=sort_key)
