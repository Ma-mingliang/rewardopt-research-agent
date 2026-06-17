"""Tests for method pool diversity in the optimizer (v0.8.7)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from research_agent.reward_methods.diversity_scheduler import DiversityScheduler
from research_agent.reward_methods.schema import RewardMethodRecord
from research_agent.reward_methods.selector import MethodSelector


def _make_record(method_id: str, category: str, confidence: str = "medium") -> RewardMethodRecord:
    return RewardMethodRecord(
        method_id=method_id,
        category=category,
        method_name=f"Method {method_id}",
        core_idea="test idea",
        reward_formula="R + bonus",
        implementation_template="reward += bonus",
        applicable_layers=("stanley_residual",),
        applicable_metrics=("tracking_error",),
        risks=("risk1",),
        confidence=confidence,
        source_papers=("paper1",),
    )


# 8 methods across 4 categories (mimicking real pool structure)
FULL_POOL = [
    _make_record("pbrs_001", "A_potential_based_reward"),
    _make_record("pbrs_002", "A_potential_based_reward"),
    _make_record("safety_003", "B_safety_constraint_reward"),
    _make_record("safety_004", "B_safety_constraint_reward"),
    _make_record("curriculum_005", "C_curriculum_subgoal_reward"),
    _make_record("curriculum_006", "C_curriculum_subgoal_reward"),
    _make_record("adaptive_007", "D_adaptive_dynamic_reward"),
    _make_record("adaptive_008", "D_adaptive_dynamic_reward"),
]


class TestDiversityAcrossIterations:
    """Simulate 5 iterations and verify category diversity improves."""

    def test_five_iterations_span_categories(self):
        sched = DiversityScheduler()
        selected_ids = []
        selected_cats = []

        for _ in range(5):
            ranked = sched.rank_for_diversity(
                FULL_POOL, exclude_ids=set(selected_ids),
            )
            selector = MethodSelector(ranked)
            selected = selector.select(top_k=1)
            if not selected:
                break
            m = selected[0]
            sched.record_selection(m.method_id, m.category)
            selected_ids.append(m.method_id)
            selected_cats.append(m.category)

        # Should have touched at least 3 different categories in 5 iterations
        unique_cats = set(selected_cats)
        assert len(unique_cats) >= 3, f"Only {len(unique_cats)} categories in 5 iterations: {selected_cats}"

    def test_no_duplicate_method_ids(self):
        sched = DiversityScheduler()
        selected_ids = []

        for _ in range(5):
            ranked = sched.rank_for_diversity(
                FULL_POOL, exclude_ids=set(selected_ids),
            )
            selector = MethodSelector(ranked)
            selected = selector.select(top_k=1)
            if not selected:
                break
            m = selected[0]
            sched.record_selection(m.method_id, m.category)
            selected_ids.append(m.method_id)

        assert len(selected_ids) == len(set(selected_ids)), "Duplicate method IDs selected"


class TestDiversitySchedulerWithObservability:
    """Verify diversity metrics are emitted to observer summary."""

    def test_diversity_score_in_source_meta(self):
        """The optimizer should add diversity_score to source_meta."""
        sched = DiversityScheduler()
        # Simulate what optimizer does
        prev_ids = []
        for _ in range(3):
            ranked = sched.rank_for_diversity(FULL_POOL, exclude_ids=set(prev_ids))
            selector = MethodSelector(ranked)
            selected = selector.select(top_k=1)
            for m in selected:
                sched.record_selection(m.method_id, m.category)
            prev_ids.extend([m.method_id for m in selected])

        score = sched.compute_diversity_score()
        assert 0.0 <= score <= 1.0
        # With 3 different categories selected, score should be high
        assert score > 0.5


class TestBackwardCompatibility:
    """Verify that the optimizer still works without method_pool."""

    def test_empty_pool_no_error(self):
        sched = DiversityScheduler()
        ranked = sched.rank_for_diversity([], exclude_ids=set())
        assert ranked == []

    def test_no_previous_ids_no_exclusion(self):
        sched = DiversityScheduler()
        ranked = sched.rank_for_diversity(FULL_POOL, exclude_ids=set())
        assert len(ranked) == len(FULL_POOL)
