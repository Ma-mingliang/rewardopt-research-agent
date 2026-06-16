"""Tests for template diversity tracking and counter consistency (v0.8.6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent.core.observability import RunObserver


class TestTemplateDiversityTracking:
    def _make_observer(self, tmp_path) -> RunObserver:
        return RunObserver(
            run_log_dir=str(tmp_path),
            optimizer="test",
            project_path=str(tmp_path),
            agent_python="python",
            execution_python="python",
            fallback_used=False,
            mock_llm=True,
            proposal_only=True,
            max_iterations=1,
            batch_size=1,
        )

    def test_track_template_selection(self, tmp_path):
        obs = self._make_observer(tmp_path)
        obs.track_template_selection("template_a")
        obs.track_template_selection("template_a")
        obs.track_template_selection("template_b")
        assert obs._template_usage_counts == {"template_a": 2, "template_b": 1}

    def test_compute_template_diversity(self, tmp_path):
        obs = self._make_observer(tmp_path)
        obs.track_template_selection("template_a")
        obs.track_template_selection("template_a")
        obs.track_template_selection("template_b")
        obs.compute_template_diversity()
        assert obs._template_diversity_score == pytest.approx(2 / 3, abs=0.01)
        assert obs._template_low_diversity is False

    def test_low_diversity_detection(self, tmp_path):
        obs = self._make_observer(tmp_path)
        for _ in range(5):
            obs.track_template_selection("template_a")
        obs.compute_template_diversity()
        assert obs._template_low_diversity is True

    def test_template_diversity_in_summary(self, tmp_path):
        obs = self._make_observer(tmp_path)
        obs.track_template_selection("template_a")
        obs.track_template_selection("template_b")
        obs.compute_template_diversity()
        obs.write_summary()
        summary = json.loads(obs.summary_path.read_text())
        assert "template_usage_counts" in summary
        assert "template_diversity_score" in summary
        assert "template_low_diversity" in summary
        assert summary["template_usage_counts"]["template_a"] == 1


class TestSemanticGateCounterConsistency:
    """Verify that semantic_gate_passed_count is incremented in all success paths."""

    def _make_observer(self, tmp_path) -> RunObserver:
        return RunObserver(
            run_log_dir=str(tmp_path),
            optimizer="test",
            project_path=str(tmp_path),
            agent_python="python",
            execution_python="python",
            fallback_used=False,
            mock_llm=True,
            proposal_only=True,
            max_iterations=1,
            batch_size=1,
        )

    def test_gate_passed_increments(self, tmp_path):
        obs = self._make_observer(tmp_path)
        obs.track_semantic_gate(passed=True, reason="passed", cosmetic_only=False, reward_terms_changed=True)
        obs.track_semantic_gate(passed=True, reason="passed", cosmetic_only=False, reward_terms_changed=True)
        obs.write_summary()
        summary = json.loads(obs.summary_path.read_text())
        assert summary["semantic_gate_passed_count"] == 2
        assert summary["semantic_gate_rejected_count"] == 0

    def test_gate_rejected_increments(self, tmp_path):
        obs = self._make_observer(tmp_path)
        obs.track_semantic_gate(passed=False, reason="cosmetic", cosmetic_only=True, reward_terms_changed=False)
        obs.write_summary()
        summary = json.loads(obs.summary_path.read_text())
        assert summary["semantic_gate_passed_count"] == 0
        assert summary["semantic_gate_rejected_count"] == 1
        assert summary["cosmetic_patch_rejected_count"] == 1

    def test_regeneration_pass_tracks_gate(self, tmp_path):
        """Simulate the regeneration success path: gate passed + regeneration tracked."""
        obs = self._make_observer(tmp_path)
        obs.track_semantic_gate(passed=False, reason="cosmetic_patch_rejected", cosmetic_only=True, reward_terms_changed=False)
        obs.track_semantic_gate(passed=True, reason="passed_after_regeneration", cosmetic_only=False, reward_terms_changed=True)
        obs.write_summary()
        summary = json.loads(obs.summary_path.read_text())
        assert summary["semantic_gate_passed_count"] == 1
        assert summary["semantic_gate_rejected_count"] == 1

    def test_syntax_repair_pass_tracks_gate(self, tmp_path):
        obs = self._make_observer(tmp_path)
        obs.track_semantic_gate(passed=False, reason="cosmetic", cosmetic_only=True, reward_terms_changed=False)
        obs.track_semantic_gate(passed=True, reason="passed_after_syntax_repair", cosmetic_only=False, reward_terms_changed=True)
        obs.write_summary()
        summary = json.loads(obs.summary_path.read_text())
        assert summary["semantic_gate_passed_count"] == 1
        assert summary["semantic_gate_rejected_count"] == 1

    def test_template_fallback_pass_tracks_gate(self, tmp_path):
        obs = self._make_observer(tmp_path)
        obs.track_semantic_gate(passed=False, reason="cosmetic", cosmetic_only=True, reward_terms_changed=False)
        obs.track_semantic_gate(passed=True, reason="passed_after_template_fallback", cosmetic_only=False, reward_terms_changed=True)
        obs.write_summary()
        summary = json.loads(obs.summary_path.read_text())
        assert summary["semantic_gate_passed_count"] == 1
        assert summary["semantic_gate_rejected_count"] == 1
