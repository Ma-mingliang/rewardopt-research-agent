"""Tests for semantic regeneration (v0.8.4)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from research_agent.core.executor import _extract_diff_from_response, _attempt_semantic_regeneration
from research_agent.core.proposal_context import ProposalContext
from research_agent.core.semantic_patch_gate import SemanticPatchDecision, RejectionReason
from research_agent.core.observability import RunObserver


# --- _extract_diff_from_response tests ---

class TestExtractDiffFromResponse:
    def test_none_input(self):
        assert _extract_diff_from_response(None) is None

    def test_empty_string(self):
        assert _extract_diff_from_response("") is None

    def test_pure_diff(self):
        diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -954,6 +954,8 @@\n"
            "     tracking_reward = -1.0 * current_error**2\n"
            "+    safety_penalty = -0.1 * max(0, angular_velocity - threshold)\n"
            "+    reward += safety_penalty\n"
            "     return reward\n"
        )
        result = _extract_diff_from_response(diff)
        assert result is not None
        assert "--- a/env.py" in result
        assert "+    safety_penalty" in result

    def test_diff_with_preamble_text(self):
        text = (
            "Here is the regenerated patch:\n"
            "\n"
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -954,4 +954,6 @@\n"
            "     tracking_reward = -1.0 * current_error**2\n"
            "+    action_penalty = -0.01 * action_norm\n"
            "+    reward += action_penalty\n"
            "     return reward\n"
        )
        result = _extract_diff_from_response(text)
        assert result is not None
        assert "--- a/env.py" in result
        assert "Here is" not in result

    def test_diff_with_trailing_text(self):
        text = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -954,4 +954,6 @@\n"
            "     tracking_reward = -1.0 * current_error**2\n"
            "+    reward += -0.01 * action_norm\n"
            "     return reward\n"
            "\n"
            "This patch adds an action energy penalty."
        )
        result = _extract_diff_from_response(text)
        assert result is not None
        assert "--- a/env.py" in result
        # Trailing text after diff is included (no clean cutoff)
        assert "return reward" in result

    def test_no_diff_markers_fallback(self):
        text = (
            "+    safety_penalty = -0.1 * max(0, angular_velocity - threshold)\n"
            "-    alpha = 2.0\n"
            "+    alpha = 3.0\n"
        )
        result = _extract_diff_from_response(text)
        # Fallback: has +/- lines, returns whole text
        assert result is not None
        assert "+    safety_penalty" in result

    def test_no_diff_at_all(self):
        text = "This is just a plain text response with no diff content."
        result = _extract_diff_from_response(text)
        assert result is None


# --- _attempt_semantic_regeneration tests ---

class TestAttemptSemanticRegeneration:
    def _make_proposal_context(self) -> ProposalContext:
        return ProposalContext(
            target_file="env.py",
            function_name="__calculate_reward",
            function_start_line=950,
            function_end_line=1000,
            class_name="MyEnv",
            class_start_line=10,
            line_numbered_context="  950 >>>     def __calculate_reward(self):\n  951 >>>         reward = 0.0",
            available_reward_variables=["self", "reward", "current_error", "action"],
            existing_reward_terms=["tracking_reward"],
            existing_reward_expression_lines=["  L954: reward += tracking_reward"],
        )

    def _make_candidate(self, diff: str = "") -> SimpleNamespace:
        return SimpleNamespace(
            candidate_id="test_001",
            patch_diff=diff,
            method_id="test_method",
            ideas=[{"title": "test idea", "description": "add safety penalty"}],
        )

    def _make_decision(self) -> SemanticPatchDecision:
        return SemanticPatchDecision(
            passed=False,
            reason=RejectionReason.COSMETIC_PATCH,
            cosmetic_only=True,
            reward_terms_changed=False,
        )

    def test_no_llm_client(self):
        optimizer = SimpleNamespace(llm_client=None)
        result = _attempt_semantic_regeneration(
            optimizer, self._make_candidate(), self._make_decision(),
            self._make_proposal_context(), {}, "", [],
        )
        assert result is None

    def test_no_proposal_context(self):
        optimizer = SimpleNamespace(llm_client=MagicMock())
        result = _attempt_semantic_regeneration(
            optimizer, self._make_candidate(), self._make_decision(),
            None, "", "", [],
        )
        assert result is None

    def test_successful_regeneration(self):
        mock_response = SimpleNamespace(
            text=(
                "--- a/env.py\n"
                "+++ b/env.py\n"
                "@@ -954,4 +954,6 @@\n"
                "     tracking_reward = -1.0 * current_error**2\n"
                "+    safety_penalty = -0.1 * max(0, angular_velocity - 1.0)\n"
                "+    reward += safety_penalty\n"
                "     return reward\n"
            )
        )
        mock_llm = MagicMock()
        mock_llm.call.return_value = mock_response
        optimizer = SimpleNamespace(llm_client=mock_llm)

        result = _attempt_semantic_regeneration(
            optimizer, self._make_candidate("old diff"), self._make_decision(),
            self._make_proposal_context(), {}, "method context",
            [{"title": "idea1", "description": "desc"}],
        )
        assert result is not None
        assert "safety_penalty" in result
        mock_llm.call.assert_called_once()

    def test_empty_llm_response(self):
        mock_llm = MagicMock()
        mock_llm.call.return_value = SimpleNamespace(text="")
        optimizer = SimpleNamespace(llm_client=mock_llm)

        result = _attempt_semantic_regeneration(
            optimizer, self._make_candidate(), self._make_decision(),
            self._make_proposal_context(), {}, "", [],
        )
        assert result is None

    def test_llm_returns_no_diff(self):
        mock_llm = MagicMock()
        mock_llm.call.return_value = SimpleNamespace(text="I cannot generate a valid patch.")
        optimizer = SimpleNamespace(llm_client=mock_llm)

        result = _attempt_semantic_regeneration(
            optimizer, self._make_candidate(), self._make_decision(),
            self._make_proposal_context(), {}, "", [],
        )
        assert result is None

    def test_regeneration_returns_valid_diff(self):
        """Verify regeneration produces a parseable diff (tracking is done by caller)."""
        mock_response = SimpleNamespace(
            text=(
                "--- a/env.py\n"
                "+++ b/env.py\n"
                "@@ -954,4 +954,6 @@\n"
                "+    reward += -0.01 * action\n"
                "     return reward\n"
            )
        )
        mock_llm = MagicMock()
        mock_llm.call.return_value = mock_response
        optimizer = SimpleNamespace(llm_client=mock_llm)

        result = _attempt_semantic_regeneration(
            optimizer, self._make_candidate("old"), self._make_decision(),
            self._make_proposal_context(), {}, "", [],
        )
        assert result is not None
        assert "--- a/env.py" in result
        assert "+    reward += -0.01 * action" in result


# --- Observability integration ---

class TestRegenerationObservability:
    def test_track_regeneration_success(self, tmp_path):
        observer = RunObserver(
            run_log_dir=str(tmp_path), optimizer="test",
            project_path=str(tmp_path), mock_llm=True,
        )
        observer.track_semantic_regeneration(success=True)
        observer.track_semantic_regeneration(success=True)
        observer.close()

        import json
        summary = json.loads(observer.summary_path.read_text())
        assert summary["semantic_regeneration_attempts"] == 2
        assert summary["semantic_regeneration_successes"] == 2
        assert summary["semantic_regeneration_failures"] == 0

    def test_track_regeneration_failure(self, tmp_path):
        observer = RunObserver(
            run_log_dir=str(tmp_path), optimizer="test",
            project_path=str(tmp_path), mock_llm=True,
        )
        observer.track_semantic_regeneration(success=False)
        observer.close()

        import json
        summary = json.loads(observer.summary_path.read_text())
        assert summary["semantic_regeneration_attempts"] == 1
        assert summary["semantic_regeneration_successes"] == 0
        assert summary["semantic_regeneration_failures"] == 1

    def test_track_regeneration_mixed(self, tmp_path):
        observer = RunObserver(
            run_log_dir=str(tmp_path), optimizer="test",
            project_path=str(tmp_path), mock_llm=True,
        )
        observer.track_semantic_regeneration(success=True)
        observer.track_semantic_regeneration(success=False)
        observer.track_semantic_regeneration(success=True)
        observer.close()

        import json
        summary = json.loads(observer.summary_path.read_text())
        assert summary["semantic_regeneration_attempts"] == 3
        assert summary["semantic_regeneration_successes"] == 2
        assert summary["semantic_regeneration_failures"] == 1
