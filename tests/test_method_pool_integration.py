"""Integration fixture: verify method pool injection through the full propose_candidate path."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from research_agent.agents.reward_agent.optimizer import LangGraphRewardOptimizer
from research_agent.core.config import AgentConfig
from research_agent.core.observability import RunObserver
from research_agent.reward_methods.schema import RewardMethodRecord


@pytest.fixture
def method_pool():
    return [
        RewardMethodRecord(
            method_id="int_pbrs_001",
            category="A_potential_based_reward",
            method_name="PBRS",
            core_idea="Potential-based shaping.",
            reward_formula="gamma*Phi(s')-Phi(s)",
            implementation_template="reward += gamma*phi_next - phi",
            applicable_layers=("stanley_residual",),
            applicable_metrics=("tracking_error",),
            risks=("reward hacking",),
            confidence="high",
            source_papers=("paper:int1",),
        ),
        RewardMethodRecord(
            method_id="int_risk_002",
            category="B_safety_constraint_reward",
            method_name="Risk Penalty",
            core_idea="Exponential safety penalty.",
            reward_formula="-lambda*exp(k*violation)",
            implementation_template="reward -= lam*exp(k*v)",
            applicable_layers=("path_tracking",),
            applicable_metrics=("heading_error",),
            risks=("conservative",),
            confidence="medium",
            source_papers=("paper:int2",),
        ),
    ]


@pytest.fixture
def observer(tmp_path):
    return RunObserver(
        run_log_dir=str(tmp_path / "runs"),
        optimizer="integration_test",
        project_path=str(tmp_path),
        mock_llm=True,
    )


@pytest.fixture
def config():
    cfg = AgentConfig()
    cfg.optimizer.method_top_k = 3
    return cfg


@pytest.fixture
def phase():
    return {
        "phase_id": "reward",
        "allowed_changes": [{"file": "env.py", "function": "compute_reward"}],
        "forbidden_changes": [],
    }


class TestMethodPoolInjection:
    def test_source_meta_includes_method_pool_fields(self, tmp_path, config, phase, method_pool, observer):
        """propose_candidate with method_pool adds fields to source_meta."""
        optimizer = LangGraphRewardOptimizer(
            work_dir=tmp_path / "work",
            config=config,
            project_path=tmp_path,
            mock_llm=True,
            observer=observer,
        )
        candidate = optimizer.propose_candidate(
            phase=phase,
            baseline_metrics={"reward": {"mean": 100.0, "std": 0.0}},
            ideas=[],
            method_pool=method_pool,
        )
        meta = json.loads(candidate.source_idea)
        assert "method_pool_method_ids" in meta
        assert "int_pbrs_001" in meta["method_pool_method_ids"]
        assert "int_risk_002" in meta["method_pool_method_ids"]
        assert "method_pool_categories" in meta
        assert "A_potential_based_reward" in meta["method_pool_categories"]

    def test_source_meta_without_method_pool(self, tmp_path, config, phase, observer):
        """propose_candidate without method_pool has no method pool fields in source_meta."""
        optimizer = LangGraphRewardOptimizer(
            work_dir=tmp_path / "work",
            config=config,
            project_path=tmp_path,
            mock_llm=True,
            observer=observer,
        )
        candidate = optimizer.propose_candidate(
            phase=phase,
            baseline_metrics={"reward": {"mean": 100.0, "std": 0.0}},
            ideas=[],
        )
        meta = json.loads(candidate.source_idea)
        assert "method_pool_method_ids" not in meta
        assert "method_pool_categories" not in meta

    def test_method_pool_context_injected_into_graph_state(self, tmp_path, config, phase, method_pool, observer):
        """When graph is invoked, initial_state contains method_pool_context and method_pool_ids."""
        optimizer = LangGraphRewardOptimizer(
            work_dir=tmp_path / "work",
            config=config,
            project_path=tmp_path,
            mock_llm=False,
            observer=observer,
        )

        captured_state = {}

        def fake_invoke(state, config=None):
            captured_state.update(state)
            return {
                "final_candidate_status": "noop",
                "patch_diff": "",
                "description": "test",
                "rationale": "",
            }

        with patch.object(type(optimizer), "graph", new_callable=lambda: property(lambda self: MagicMock(invoke=fake_invoke))):
            optimizer.propose_candidate(
                phase=phase,
                baseline_metrics={"reward": {"mean": 100.0, "std": 0.0}},
                ideas=[],
                method_pool=method_pool,
            )

        assert "method_pool_context" in captured_state
        assert "PBRS" in captured_state["method_pool_context"]
        assert "Risk Penalty" in captured_state["method_pool_context"]
        assert "method_pool_ids" in captured_state
        assert "int_pbrs_001" in captured_state["method_pool_ids"]
        assert "int_risk_002" in captured_state["method_pool_ids"]

    def test_method_pool_context_empty_without_pool(self, tmp_path, config, phase, observer):
        """Without method_pool, method_pool_context is empty string in graph state."""
        optimizer = LangGraphRewardOptimizer(
            work_dir=tmp_path / "work",
            config=config,
            project_path=tmp_path,
            mock_llm=False,
            observer=observer,
        )

        captured_state = {}

        def fake_invoke(state, config=None):
            captured_state.update(state)
            return {
                "final_candidate_status": "noop",
                "patch_diff": "",
                "description": "test",
                "rationale": "",
            }

        with patch.object(type(optimizer), "graph", new_callable=lambda: property(lambda self: MagicMock(invoke=fake_invoke))):
            optimizer.propose_candidate(
                phase=phase,
                baseline_metrics={"reward": {"mean": 100.0, "std": 0.0}},
                ideas=[],
            )

        assert captured_state.get("method_pool_context") == ""
        assert captured_state.get("method_pool_ids") == []

    def test_method_pool_respects_top_k(self, tmp_path, config, phase, observer):
        """method_top_k config limits the number of methods injected."""
        config.optimizer.method_top_k = 1

        pool = [
            RewardMethodRecord(
                method_id=f"m{i}", category="A", method_name=f"Method {i}",
                core_idea="", reward_formula="", implementation_template="",
                applicable_layers=(), applicable_metrics=(), risks=(),
                confidence="high", source_papers=(),
            )
            for i in range(5)
        ]

        optimizer = LangGraphRewardOptimizer(
            work_dir=tmp_path / "work",
            config=config,
            project_path=tmp_path,
            mock_llm=True,
            observer=observer,
        )
        candidate = optimizer.propose_candidate(
            phase=phase,
            baseline_metrics={"reward": {"mean": 100.0, "std": 0.0}},
            ideas=[],
            method_pool=pool,
        )
        meta = json.loads(candidate.source_idea)
        assert len(meta["method_pool_method_ids"]) == 1

    def test_method_pool_observer_tracks_usage(self, tmp_path, config, phase, method_pool, observer):
        """Observer emits method_pool_loaded event when pool is loaded."""
        # This test verifies the executor-level observer tracking.
        # The optimizer itself doesn't emit method_pool_loaded — that's done by the executor.
        # But we can verify the observer is accessible from the optimizer.
        optimizer = LangGraphRewardOptimizer(
            work_dir=tmp_path / "work",
            config=config,
            project_path=tmp_path,
            mock_llm=True,
            observer=observer,
        )
        assert optimizer._observer is observer
        assert observer.is_active
