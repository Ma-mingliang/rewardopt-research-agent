"""Tests for semantic patch gate (v0.8.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent.core.semantic_patch_gate import (
    SemanticPatchDecision,
    RejectionReason,
    analyze_patch_semantics,
    _is_reward_term,
    _is_comment,
    _is_blank_or_whitespace,
    _is_coefficient_only_change,
)
from research_agent.core.observability import RunObserver


# --- Test diffs ---

BLANK_LINE_DIFF = (
    "--- a/env.py\n"
    "+++ b/env.py\n"
    "@@ -997,2 +997,3 @@\n"
    "         return reward\n"
    "+    \n"
    "     def reset(self, seed=None, options=None):\n"
)

WHITESPACE_ONLY_DIFF = (
    "--- a/env.py\n"
    "+++ b/env.py\n"
    "@@ -997,2 +997,3 @@\n"
    "         return reward\n"
    "+        \n"
    "     def reset(self, seed=None, options=None):\n"
)

COMMENT_ONLY_DIFF = (
    "--- a/env.py\n"
    "+++ b/env.py\n"
    "@@ -997,2 +997,3 @@\n"
    "         return reward\n"
    "+    # v0.8.2: added comment\n"
    "     def reset(self, seed=None, options=None):\n"
)

REAL_REWARD_DIFF = (
    "--- a/env.py\n"
    "+++ b/env.py\n"
    "@@ -954,6 +954,8 @@\n"
    "     tracking_reward = -1.0 * current_error**2\n"
    "+    safety_penalty = -0.1 * max(0, angular_velocity - threshold)\n"
    "+    reward += safety_penalty\n"
    "     return reward\n"
)

COEFFICIENT_ONLY_DIFF = (
    "--- a/env.py\n"
    "+++ b/env.py\n"
    "@@ -954,4 +954,4 @@\n"
    "     tracking_reward = -1.0 * current_error**2\n"
    "-    alpha = 2.0\n"
    "+    alpha = 3.0\n"
    "     return reward\n"
)

EMPTY_DIFF = ""
WHITESPACE_DIFF = "   \n  \n   \n"


class TestIsRewardTerm:
    def test_reward_assignment(self):
        assert _is_reward_term("reward += bonus")

    def test_potential(self):
        assert _is_reward_term("potential = -alpha * error")

    def test_penalty(self):
        assert _is_reward_term("safety_penalty = -0.1 * max(0, x)")

    def test_tracking_reward(self):
        assert _is_reward_term("tracking_reward = -1.0 * error**2")

    def test_not_reward_term(self):
        assert not _is_reward_term("x = 5")
        assert not _is_reward_term("import os")


class TestIsComment:
    def test_comment(self):
        assert _is_comment("# this is a comment")
        assert _is_comment("    # indented comment")

    def test_not_comment(self):
        assert not _is_comment("reward += 1")
        assert not _is_comment("")


class TestIsBlankOrWhitespace:
    def test_blank(self):
        assert _is_blank_or_whitespace("")
        assert _is_blank_or_whitespace("    ")
        assert _is_blank_or_whitespace("\t")

    def test_not_blank(self):
        assert not _is_blank_or_whitespace("x = 1")


class TestIsCoefficientOnlyChange:
    def test_coefficient_change(self):
        added = ["alpha = 3.0"]
        removed = ["alpha = 2.0"]
        assert _is_coefficient_only_change(added, removed)

    def test_structural_change(self):
        added = ["reward += safety_penalty"]
        removed = ["alpha = 2.0"]
        assert not _is_coefficient_only_change(added, removed)

    def test_different_lengths(self):
        added = ["a = 1", "b = 2"]
        removed = ["a = 1"]
        assert not _is_coefficient_only_change(added, removed)


class TestAnalyzePatchSemantics:
    def test_empty_diff_rejected(self):
        decision = analyze_patch_semantics(EMPTY_DIFF)
        assert not decision.passed
        assert decision.cosmetic_only

    def test_blank_line_only_rejected(self):
        decision = analyze_patch_semantics(BLANK_LINE_DIFF)
        assert not decision.passed
        assert decision.cosmetic_only
        assert decision.blank_line_only
        assert decision.reason == RejectionReason.COSMETIC_PATCH.value

    def test_whitespace_only_rejected(self):
        decision = analyze_patch_semantics(WHITESPACE_ONLY_DIFF)
        assert not decision.passed
        assert decision.cosmetic_only
        assert decision.blank_line_only

    def test_comment_only_rejected(self):
        decision = analyze_patch_semantics(COMMENT_ONLY_DIFF)
        assert not decision.passed
        assert decision.cosmetic_only
        assert decision.comment_only

    def test_real_reward_passes(self):
        decision = analyze_patch_semantics(REAL_REWARD_DIFF)
        assert decision.passed
        assert decision.reward_terms_changed
        assert not decision.cosmetic_only

    def test_coefficient_only_classified(self):
        decision = analyze_patch_semantics(COEFFICIENT_ONLY_DIFF)
        # Coefficient-only change has no reward term patterns in this case
        # because alpha = 3.0 doesn't match reward term patterns
        assert decision.coefficient_only_change is False  # alpha isn't a reward term

    def test_duplicate_rejected(self):
        decision = analyze_patch_semantics(
            REAL_REWARD_DIFF,
            previous_diffs=[REAL_REWARD_DIFF],
        )
        assert not decision.passed
        assert decision.reason == RejectionReason.DUPLICATE_PATCH.value

    def test_no_previous_passes(self):
        decision = analyze_patch_semantics(
            REAL_REWARD_DIFF,
            previous_diffs=None,
        )
        assert decision.passed

    def test_to_dict(self):
        decision = analyze_patch_semantics(REAL_REWARD_DIFF)
        d = decision.to_dict()
        assert "passed" in d
        assert "reward_terms_changed" in d
        assert isinstance(d["reward_terms_added"], list)


class TestSemanticGateObserverIntegration:
    def test_gate_reject_event(self, tmp_path: Path):
        observer = RunObserver(tmp_path, "test", tmp_path)
        observer.emit("semantic_patch_gate_reject",
                      candidate_id="c001",
                      reason="cosmetic_patch_rejected",
                      semantic_change_detected=False,
                      cosmetic_only=True,
                      reward_terms_changed=False,
                      changed_line_count=1)
        observer.track_semantic_gate(
            passed=False,
            reason="cosmetic_patch_rejected",
            cosmetic_only=True,
            reward_terms_changed=False,
        )
        observer.write_summary()

        with open(observer.events_path) as f:
            events = [json.loads(l) for l in f if l.strip()]
        reject_events = [e for e in events if e["event_type"] == "semantic_patch_gate_reject"]
        assert len(reject_events) == 1

        with open(observer.summary_path) as f:
            summary = json.load(f)
        assert summary["semantic_gate_rejected_count"] == 1
        assert summary["cosmetic_patch_rejected_count"] == 1

    def test_gate_pass_event(self, tmp_path: Path):
        observer = RunObserver(tmp_path, "test", tmp_path)
        observer.track_semantic_gate(
            passed=True,
            reason="semantic_reward_change_detected",
            cosmetic_only=False,
            reward_terms_changed=True,
        )
        observer.write_summary()

        with open(observer.summary_path) as f:
            summary = json.load(f)
        assert summary["semantic_gate_passed_count"] == 1
        assert summary["semantic_gate_rejected_count"] == 0

    def test_summary_has_all_fields(self, tmp_path: Path):
        observer = RunObserver(tmp_path, "test", tmp_path)
        observer.write_summary()
        with open(observer.summary_path) as f:
            summary = json.load(f)
        assert "semantic_gate_enabled" in summary
        assert "semantic_gate_passed_count" in summary
        assert "semantic_gate_rejected_count" in summary
        assert "cosmetic_patch_rejected_count" in summary
        assert "no_reward_term_change_count" in summary
        assert "semantic_gate_rejection_reasons" in summary
        assert "cross_iteration_duplicate_patch_count" in summary
        assert "cross_iteration_similarity_max" in summary
        assert "system_preflight_enabled" in summary
        assert "system_preflight_passed" in summary
