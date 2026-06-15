"""Tests for RL-aware screening policy."""

from __future__ import annotations

import pytest

from research_agent.evaluation.policy import (
    ScreeningPolicy,
    _coefficient_of_variation,
    evaluate_medium_train,
    evaluate_short_train,
)
from research_agent.evaluation.stages import StageDecision


class TestCoefficientOfVariation:
    def test_empty(self):
        assert _coefficient_of_variation([]) == float("inf")

    def test_single_value(self):
        # Single value: std=0, so CV=0
        assert _coefficient_of_variation([5.0]) == 0.0

    def test_identical_values(self):
        assert _coefficient_of_variation([3.0, 3.0, 3.0]) == 0.0

    def test_zero_mean(self):
        assert _coefficient_of_variation([0.0, 0.0]) == float("inf")

    def test_moderate_variance(self):
        values = [1.0, 2.0, 3.0]
        cv = _coefficient_of_variation(values)
        assert 0.4 < cv < 0.6  # ~0.47


class TestScreeningPolicy:
    def test_defaults(self):
        p = ScreeningPolicy()
        assert p.uncertainty_policy == "conservative"
        assert p.min_seeds_for_decision == 2
        assert p.max_cv_threshold == 0.5
        assert p.min_improvement_pct == 0.01

    def test_aggressive(self):
        p = ScreeningPolicy(uncertainty_policy="aggressive", max_cv_threshold=0.3)
        assert p.uncertainty_policy == "aggressive"
        assert p.max_cv_threshold == 0.3


class TestEvaluateShortTrain:
    def test_empty_metrics_reject(self):
        assert evaluate_short_train({}, {}) == StageDecision.REJECT_CATASTROPHIC

    def test_all_crash_reject(self):
        metrics = {42: {}, 123: {}}
        assert evaluate_short_train(metrics, {}) == StageDecision.REJECT_CATASTROPHIC

    def test_all_zeros_reject(self):
        metrics = {42: {"reward": 0.0}, 123: {"reward": 0.0}}
        assert evaluate_short_train(metrics, {}) == StageDecision.REJECT_CATASTROPHIC

    def test_one_success_promote(self):
        metrics = {42: {"reward": 100.0, "tracking_error": 0.5}}
        assert evaluate_short_train(metrics, {}) == StageDecision.PROMOTE

    def test_mixed_one_success_promote(self):
        # One seed crashes (empty), one succeeds -> promote
        metrics = {42: {}, 123: {"reward": 50.0}}
        assert evaluate_short_train(metrics, {}) == StageDecision.PROMOTE

    def test_two_success_promote(self):
        metrics = {42: {"reward": 100.0}, 123: {"reward": 80.0}}
        assert evaluate_short_train(metrics, {}) == StageDecision.PROMOTE

    def test_poor_metrics_still_promote(self):
        # Poor metrics should NOT cause rejection in short train
        metrics = {42: {"reward": 0.001, "tracking_error": 10.0, "fall_rate": 0.9}}
        assert evaluate_short_train(metrics, {}) == StageDecision.PROMOTE


class TestEvaluateMediumTrain:
    def test_empty_metrics_reject(self):
        assert evaluate_medium_train({}, {}) == StageDecision.REJECT_CATASTROPHIC

    def test_all_crash_reject(self):
        assert evaluate_medium_train({42: {}, 123: {}}, {}) == StageDecision.REJECT_CATASTROPHIC

    def test_one_seed_needs_more(self):
        policy = ScreeningPolicy(min_seeds_for_decision=2)
        metrics = {42: {"reward": 100.0}}
        assert evaluate_medium_train(metrics, {}, policy) == StageDecision.NEEDS_MORE_SEEDS

    def test_low_variance_promote(self):
        policy = ScreeningPolicy(min_seeds_for_decision=2, max_cv_threshold=0.5)
        metrics = {42: {"reward": 100.0}, 123: {"reward": 105.0}}
        assert evaluate_medium_train(metrics, {}, policy) == StageDecision.PROMOTE

    def test_high_variance_needs_more_seeds(self):
        policy = ScreeningPolicy(min_seeds_for_decision=2, max_cv_threshold=0.5)
        # CV of [10, 100] is ~0.82 > 0.5
        metrics = {42: {"reward": 10.0}, 123: {"reward": 100.0}}
        assert evaluate_medium_train(metrics, {}, policy) == StageDecision.NEEDS_MORE_SEEDS

    def test_mixed_with_custom_policy(self):
        policy = ScreeningPolicy(min_seeds_for_decision=2, max_cv_threshold=1.0)
        metrics = {42: {"reward": 50.0}, 123: {"reward": 80.0}}
        assert evaluate_medium_train(metrics, {}, policy) == StageDecision.PROMOTE
