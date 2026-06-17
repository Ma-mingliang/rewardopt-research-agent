"""Tests for template diversity scheduler (v0.8.7)."""

from __future__ import annotations

import pytest

from research_agent.reward_methods.diversity_scheduler import DiversityScheduler
from research_agent.reward_methods.schema import RewardMethodRecord


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


# Diverse fixture: 4 methods from 4 different categories
DIVERSE_POOL = [
    _make_record("pbrs_001", "A_potential_based_reward"),
    _make_record("safety_002", "B_safety_constraint_reward"),
    _make_record("curriculum_003", "C_curriculum_subgoal_reward"),
    _make_record("adaptive_004", "D_adaptive_dynamic_reward"),
]


class TestDiversitySchedulerInit:
    def test_initial_state(self):
        sched = DiversityScheduler()
        assert sched.category_counts == {}
        assert sched.selected_method_ids == []
        assert sched.compute_diversity_score() == 1.0

    def test_custom_weight(self):
        sched = DiversityScheduler(diversity_weight=0.5)
        assert sched._diversity_weight == 0.5


class TestRecordSelection:
    def test_single_selection(self):
        sched = DiversityScheduler()
        sched.record_selection("pbrs_001", "A_potential_based_reward")
        assert sched.category_counts == {"A_potential_based_reward": 1}
        assert sched.selected_method_ids == ["pbrs_001"]

    def test_multiple_selections_same_category(self):
        sched = DiversityScheduler()
        sched.record_selection("pbrs_001", "A_potential_based_reward")
        sched.record_selection("pbrs_002", "A_potential_based_reward")
        assert sched.category_counts == {"A_potential_based_reward": 2}

    def test_multiple_categories(self):
        sched = DiversityScheduler()
        sched.record_selection("pbrs_001", "A_potential_based_reward")
        sched.record_selection("safety_002", "B_safety_constraint_reward")
        assert sched.category_counts == {
            "A_potential_based_reward": 1,
            "B_safety_constraint_reward": 1,
        }


class TestDiversityScore:
    def test_uniform_is_one(self):
        sched = DiversityScheduler()
        sched.record_selection("m1", "cat_a")
        sched.record_selection("m2", "cat_b")
        sched.record_selection("m3", "cat_c")
        score = sched.compute_diversity_score()
        assert score == pytest.approx(1.0, abs=0.01)

    def test_all_same_is_zero(self):
        sched = DiversityScheduler()
        for i in range(5):
            sched.record_selection(f"m{i}", "cat_a")
        score = sched.compute_diversity_score()
        assert score == pytest.approx(0.0, abs=0.01)

    def test_empty_is_one(self):
        sched = DiversityScheduler()
        assert sched.compute_diversity_score() == 1.0


class TestRankForDiversity:
    def test_first_ranking_preserves_order(self):
        """With no prior selections, all methods are equally ranked."""
        sched = DiversityScheduler()
        ranked = sched.rank_for_diversity(DIVERSE_POOL)
        assert len(ranked) == 4

    def test_exclude_ids_removes_methods(self):
        sched = DiversityScheduler()
        ranked = sched.rank_for_diversity(DIVERSE_POOL, exclude_ids={"pbrs_001"})
        ids = [m.method_id for m in ranked]
        assert "pbrs_001" not in ids
        assert len(ranked) == 3

    def test_diversity_boosts_underrepresented(self):
        """After selecting cat_a twice, cat_b/c/d should rank higher."""
        sched = DiversityScheduler(diversity_weight=1.0)
        sched.record_selection("pbrs_001", "A_potential_based_reward")
        sched.record_selection("pbrs_002", "A_potential_based_reward")
        ranked = sched.rank_for_diversity(DIVERSE_POOL)
        # A should rank last since it's over-represented
        assert ranked[-1].category == "A_potential_based_reward"

    def test_empty_pool_returns_empty(self):
        sched = DiversityScheduler()
        assert sched.rank_for_diversity([]) == []

    def test_all_excluded_returns_empty(self):
        sched = DiversityScheduler()
        exclude = {m.method_id for m in DIVERSE_POOL}
        assert sched.rank_for_diversity(DIVERSE_POOL, exclude_ids=exclude) == []


class TestIntegrationWithSelector:
    """Verify diversity scheduler + MethodSelector work together."""

    def test_selector_picks_different_methods_across_iterations(self):
        from research_agent.reward_methods.selector import MethodSelector

        sched = DiversityScheduler()
        # Simulate 3 iterations with top_k=1
        selected_ids = []
        for _ in range(3):
            ranked = sched.rank_for_diversity(
                DIVERSE_POOL, exclude_ids=set(selected_ids),
            )
            selector = MethodSelector(ranked)
            selected = selector.select(top_k=1)
            assert len(selected) == 1
            sched.record_selection(selected[0].method_id, selected[0].category)
            selected_ids.append(selected[0].method_id)

        # All 3 should be different methods from different categories
        assert len(set(selected_ids)) == 3

    def test_exhaustion_when_more_iterations_than_methods(self):
        """When iterations > pool size, scheduler should still work (just fewer options)."""
        from research_agent.reward_methods.selector import MethodSelector

        sched = DiversityScheduler()
        selected_ids = []
        for _ in range(5):
            ranked = sched.rank_for_diversity(
                DIVERSE_POOL, exclude_ids=set(selected_ids),
            )
            if not ranked:
                break
            selector = MethodSelector(ranked)
            selected = selector.select(top_k=1)
            if not selected:
                break
            sched.record_selection(selected[0].method_id, selected[0].category)
            selected_ids.append(selected[0].method_id)

        # Should have selected all 4 before running out
        assert len(selected_ids) == 4
        assert len(set(selected_ids)) == 4
