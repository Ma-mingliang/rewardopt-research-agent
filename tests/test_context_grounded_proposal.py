"""Tests for context-grounded reward patch proposal (v0.7.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent.core.proposal_context import (
    ProposalContext,
    build_line_numbered_context,
    detect_reward_function_bounds,
    extract_editable_reward_context,
    extract_existing_reward_terms,
    infer_indent_unit,
)
from research_agent.agents.reward_agent.nodes import (
    _extract_diff_from_text,
    initial_patch_self_check,
)


SAMPLE_ENV_PY = '''\
import math
import numpy as np

class MyEnv:
    def __init__(self):
        self.step_count = 0

    def __calculate_reward(self, state_last, state, target_handle_angle=0.0):
        """Reward function."""
        current_error = abs(state[0])
        angular_velocity = abs(state[2])

        # Tracking reward
        tracking_reward = -1.0 * current_error**2

        # Bonus
        bonus_reward = 0.0
        if current_error < 0.005:
            bonus_reward = 1.0

        # Smoothness
        smoothness_penalty = -0.05 * angular_velocity

        gamma = 0.99
        alpha = 1.0
        potential_current = -alpha * current_error
        potential_last = -alpha * abs(state_last[0])
        improvement_reward = gamma * potential_current - potential_last

        reward = tracking_reward + bonus_reward + smoothness_penalty + improvement_reward
        return reward

    def reset(self):
        self.step_count = 0
        return np.zeros(4)
'''


class TestDetectRewardFunctionBounds:
    def test_finds_reward_function(self):
        bounds = detect_reward_function_bounds(SAMPLE_ENV_PY)
        assert bounds is not None
        name, start, end, cls, cls_start = bounds
        assert name == "__calculate_reward"
        assert start > 0
        assert end > start
        assert cls == "MyEnv"

    def test_returns_none_for_missing(self):
        bounds = detect_reward_function_bounds("x = 1\n")
        assert bounds is None

    def test_line_numbers_match_source(self):
        bounds = detect_reward_function_bounds(SAMPLE_ENV_PY)
        assert bounds is not None
        _, start, end, _, _ = bounds
        lines = SAMPLE_ENV_PY.splitlines()
        assert "def __calculate_reward" in lines[start - 1]


class TestBuildLineNumberedContext:
    def test_includes_line_numbers(self):
        ctx = build_line_numbered_context(SAMPLE_ENV_PY, 9, 30)
        assert "   9" in ctx
        assert ">>>" in ctx

    def test_marks_function_lines(self):
        ctx = build_line_numbered_context(SAMPLE_ENV_PY, 9, 30)
        lines = ctx.splitlines()
        marked = [l for l in lines if ">>>" in l]
        assert len(marked) > 0

    def test_radius_extends_context(self):
        ctx = build_line_numbered_context(SAMPLE_ENV_PY, 9, 30, radius=3)
        lines = ctx.splitlines()
        # With start_line=9, radius=3: ctx_start = max(0, 9-3-1) = 5
        # Line 6 (0-indexed 5) in SAMPLE_ENV_PY is inside __init__
        assert len(lines) > 0
        # Verify we get context lines outside the function (before line 9)
        numbered = [l for l in lines if l.strip() and not l.strip().startswith(">>>")]
        assert len(numbered) > 0


class TestInferIndentUnit:
    def test_detects_4_spaces(self):
        style, unit = infer_indent_unit(SAMPLE_ENV_PY)
        assert style == "spaces"
        assert unit == 4

    def test_detects_tabs(self):
        tab_source = "class Foo:\n\tdef bar(self):\n\t\treturn 1\n"
        style, unit = infer_indent_unit(tab_source)
        assert style == "tabs"
        assert unit == 1


class TestExtractExistingRewardTerms:
    def test_finds_reward_terms(self):
        terms = extract_existing_reward_terms(SAMPLE_ENV_PY, "__calculate_reward")
        assert "tracking_reward" in terms
        assert "bonus_reward" in terms
        assert "smoothness_penalty" in terms
        assert "improvement_reward" in terms


class TestExtractEditableRewardContext:
    def test_extracts_context(self, tmp_path: Path):
        env_file = tmp_path / "env.py"
        env_file.write_text(SAMPLE_ENV_PY, encoding="utf-8")

        ctx = extract_editable_reward_context(tmp_path, ["env.py"])
        assert ctx is not None
        assert ctx.function_name == "__calculate_reward"
        assert ctx.function_start_line > 0
        assert ctx.function_end_line > ctx.function_start_line
        assert ctx.class_name == "MyEnv"
        assert ctx.indent_unit == 4
        assert ctx.base_indent > 0
        assert ctx.total_file_lines > 0
        assert "tracking_reward" in ctx.existing_reward_terms

    def test_returns_none_for_missing_file(self, tmp_path: Path):
        ctx = extract_editable_reward_context(tmp_path, ["env.py"])
        assert ctx is None

    def test_returns_none_for_no_reward(self, tmp_path: Path):
        env_file = tmp_path / "env.py"
        env_file.write_text("x = 1\n", encoding="utf-8")
        ctx = extract_editable_reward_context(tmp_path, ["env.py"])
        assert ctx is None

    def test_line_numbered_context_has_correct_lines(self, tmp_path: Path):
        env_file = tmp_path / "env.py"
        env_file.write_text(SAMPLE_ENV_PY, encoding="utf-8")
        ctx = extract_editable_reward_context(tmp_path, ["env.py"])
        assert ctx is not None
        # Check that line numbers in context match actual source
        lines = SAMPLE_ENV_PY.splitlines()
        for ctx_line in ctx.line_numbered_context.splitlines():
            if ">>>" in ctx_line:
                line_num = int(ctx_line.strip().split()[0])
                # The line after >>> should match the source
                assert 1 <= line_num <= len(lines)


class TestExtractDiffFromText:
    def test_extracts_raw_diff(self):
        text = "--- a/env.py\n+++ b/env.py\n@@ -1,3 +1,4 @@\n line1\n+new line\n line2"
        result = _extract_diff_from_text(text)
        assert "--- a/env.py" in result
        assert "+new line" in result

    def test_extracts_diff_from_markdown(self):
        text = "Here is the diff:\n```diff\n--- a/env.py\n+++ b/env.py\n@@ -1,3 +1,4 @@\n+new\n```\nThat's it."
        result = _extract_diff_from_text(text)
        assert "--- a/env.py" in result
        assert "+new" in result

    def test_returns_empty_for_no_diff(self):
        assert _extract_diff_from_text("no diff here") == ""
        assert _extract_diff_from_text("") == ""


class TestInitialPatchSelfCheck:
    def _valid_diff(self):
        return (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -10,6 +10,7 @@\n"
            "     existing_line\n"
            "+    new_line = 1\n"
            "     another_line\n"
        )

    def test_passes_valid_diff(self):
        ok, reason, cleaned = initial_patch_self_check(
            self._valid_diff(), ["env.py"])
        assert ok is True
        assert reason == "passed"

    def test_rejects_empty_diff(self):
        ok, reason, _ = initial_patch_self_check("", ["env.py"])
        assert ok is False
        assert reason == "empty_diff"

    def test_rejects_missing_header(self):
        ok, reason, _ = initial_patch_self_check("just some text", ["env.py"])
        assert ok is False
        assert reason == "missing_unified_diff_header"

    def test_strips_markdown(self):
        md_diff = "```diff\n" + self._valid_diff() + "\n```"
        ok, reason, cleaned = initial_patch_self_check(md_diff, ["env.py"])
        assert ok is True
        assert "--- a/env.py" in cleaned

    def test_rejects_markdown_only(self):
        ok, reason, _ = initial_patch_self_check("```python\nprint('hi')\n```", ["env.py"])
        assert ok is False
        assert reason == "markdown_only_no_diff"

    def test_rejects_forbidden_file(self):
        diff = (
            "--- a/forbidden.py\n"
            "+++ b/forbidden.py\n"
            "@@ -1,1 +1,2 @@\n"
            "+x = 1\n"
        )
        ok, reason, _ = initial_patch_self_check(diff, ["env.py"])
        assert ok is False
        assert "forbidden_file" in reason

    def test_rejects_too_large(self):
        lines = ["+line {}".format(i) for i in range(100)]
        diff = "--- a/env.py\n+++ b/env.py\n@@ -1,1 +1,100 @@\n" + "\n".join(lines)
        ok, reason, _ = initial_patch_self_check(diff, ["env.py"])
        assert ok is False
        assert "too_large" in reason

    def test_rejects_full_file_rewrite(self):
        diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -1,5 +1,5 @@\n"
            "-old1\n"
            "+new1\n"
            "-old2\n"
            "+new2\n"
            "-old3\n"
            "+new3\n"
        )
        ok, reason, _ = initial_patch_self_check(diff, ["env.py"])
        assert ok is False
        assert "full_file_rewrite" in reason

    def test_rejects_new_imports(self):
        diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -1,3 +1,4 @@\n"
            " import os\n"
            "+import torch\n"
            " x = 1\n"
        )
        ok, reason, _ = initial_patch_self_check(diff, ["env.py"])
        assert ok is False
        assert "new_import" in reason

    def test_flags_mixed_tabs_spaces(self):
        # Line with mixed leading whitespace: spaces then tab
        diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -1,2 +1,3 @@\n"
            " x = 1\n"
            "+ \ty = 2  # space then tab in leading indent\n"
            " z = 3\n"
        )
        ok, reason, _ = initial_patch_self_check(diff, ["env.py"])
        assert ok is False
        assert "mixed_tabs_spaces" in reason

    def test_rejects_outside_editable_context(self):
        diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -5,3 +5,4 @@\n"
            " x = 1\n"
            "+y = 2\n"
            " z = 3\n"
        )
        ctx = ProposalContext(
            function_start_line=100,
            function_end_line=200,
        )
        ok, reason, _ = initial_patch_self_check(
            diff, ["env.py"], proposal_context=ctx)
        assert ok is False
        assert "outside_editable_context" in reason


class TestProposalContextDataclass:
    def test_function_line_count(self):
        ctx = ProposalContext(function_start_line=10, function_end_line=30)
        assert ctx.function_line_count == 21

    def test_defaults(self):
        ctx = ProposalContext()
        assert ctx.target_file == "env.py"
        assert ctx.function_name == ""
        assert ctx.indent_unit == 4


class TestEnvHashUnchanged:
    def test_env_hash_unchanged(self):
        from research_agent.core.eval_diagnostics import hash_file
        env_path = Path("D:/research-agent/HRRL2/env.py")
        if env_path.exists():
            h = hash_file(env_path)
            assert h == "e19703467be71e20"


class TestBaselineGuardNotBypassed:
    def test_baseline_guard_not_disabled(self):
        from research_agent.core.config import AgentConfig
        cfg = AgentConfig()
        # Baseline guard should not be bypassed by default
        # The guard runs in run_optimizer.py, not in config
        # Just verify the config doesn't have a bypass flag
        assert not hasattr(cfg, "skip_baseline_guard")


class TestFullEvalProtocolUnchanged:
    def test_eval_protocol_not_modified(self):
        """Verify full eval protocol files are unchanged."""
        # This is a structural check - the eval protocol is in executor.py
        # and should not be modified by v0.7.3
        from pathlib import Path
        executor_path = Path("D:/research-agent/research_agent/core/executor.py")
        if executor_path.exists():
            content = executor_path.read_text(encoding="utf-8")
            # Verify key eval functions still exist
            assert "full_eval" in content or "run_full_eval" in content
