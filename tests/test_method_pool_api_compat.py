"""Tests for method_pool kwarg API compatibility (v0.8.6 fix)."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from research_agent.agents.reward_agent.optimizer import LangGraphRewardOptimizer
from research_agent.optimizers.reward.optimizer import RewardOptimizer


class TestProposeCandidateSignature:
    """Verify that propose_candidate signatures are consistent."""

    def test_reward_optimizer_signature(self):
        sig = inspect.signature(RewardOptimizer.propose_candidate)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "phase" in params
        assert "baseline_metrics" in params
        assert "ideas" in params

    def test_langgraph_optimizer_signature(self):
        sig = inspect.signature(LangGraphRewardOptimizer.propose_candidate)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "phase" in params
        assert "baseline_metrics" in params
        assert "ideas" in params
        assert "method_pool" in params
        assert "previous_candidate_diffs" in params
        assert "previous_method_ids" in params


class TestKwargsFiltering:
    """Verify that propose_kwargs filtering works correctly."""

    def test_filter_removes_unsupported_kwargs(self):
        """RewardOptimizer doesn't accept method_pool; it should be filtered out."""
        all_kwargs = {
            "method_pool": ["method_a"],
            "previous_candidate_diffs": ["diff1"],
            "previous_method_ids": ["id1"],
        }
        sig = inspect.signature(RewardOptimizer.propose_candidate)
        accepted = set(sig.parameters.keys()) - {"self"}
        filtered = {k: v for k, v in all_kwargs.items() if k in accepted}
        # RewardOptimizer doesn't accept any of these extras
        assert "method_pool" not in filtered
        assert "previous_candidate_diffs" not in filtered
        assert "previous_method_ids" not in filtered

    def test_filter_keeps_supported_kwargs(self):
        """LangGraphRewardOptimizer accepts all three; nothing should be filtered."""
        all_kwargs = {
            "method_pool": ["method_a"],
            "previous_candidate_diffs": ["diff1"],
            "previous_method_ids": ["id1"],
        }
        sig = inspect.signature(LangGraphRewardOptimizer.propose_candidate)
        accepted = set(sig.parameters.keys()) - {"self"}
        filtered = {k: v for k, v in all_kwargs.items() if k in accepted}
        assert "method_pool" in filtered
        assert "previous_candidate_diffs" in filtered
        assert "previous_method_ids" in filtered

    def test_empty_kwargs_still_works(self):
        """No kwargs should pass through cleanly."""
        sig = inspect.signature(RewardOptimizer.propose_candidate)
        accepted = set(sig.parameters.keys()) - {"self"}
        filtered = {k: v for k, v in {}.items() if k in accepted}
        assert filtered == {}


class TestExecutorProposeCall:
    """Verify the executor's propose call path doesn't raise TypeError."""

    def test_executor_filters_method_pool_for_base_optimizer(self):
        """Simulate the executor's filtering logic with a base optimizer."""
        # Simulate what executor does
        propose_kwargs = {
            "method_pool": ["method_a"],
            "previous_candidate_diffs": ["diff1"],
            "previous_method_ids": ["id1"],
        }

        # Create a mock optimizer with RewardOptimizer's signature
        class MockOptimizer:
            def propose_candidate(self, phase, baseline_metrics, ideas=None):
                return SimpleNamespace(candidate_id="test")

        optimizer = MockOptimizer()
        sig = inspect.signature(optimizer.propose_candidate)
        accepted = set(sig.parameters.keys()) - {"self"}
        filtered = {k: v for k, v in propose_kwargs.items() if k in accepted}

        # Should not raise TypeError
        result = optimizer.propose_candidate({}, {}, [], **filtered)
        assert result.candidate_id == "test"

    def test_executor_passes_method_pool_to_langgraph_optimizer(self):
        """Simulate the executor's filtering logic with LangGraph optimizer."""
        propose_kwargs = {
            "method_pool": ["method_a"],
            "previous_candidate_diffs": ["diff1"],
            "previous_method_ids": ["id1"],
        }

        # Create a mock optimizer with LangGraphRewardOptimizer's signature
        class MockLangGraphOptimizer:
            def propose_candidate(self, phase, baseline_metrics, ideas=None,
                                  method_pool=None, previous_candidate_diffs=None,
                                  previous_method_ids=None):
                return SimpleNamespace(candidate_id="test", method_pool=method_pool)

        optimizer = MockLangGraphOptimizer()
        sig = inspect.signature(optimizer.propose_candidate)
        accepted = set(sig.parameters.keys()) - {"self"}
        filtered = {k: v for k, v in propose_kwargs.items() if k in accepted}

        result = optimizer.propose_candidate({}, {}, [], **filtered)
        assert result.candidate_id == "test"
        assert result.method_pool == ["method_a"]
