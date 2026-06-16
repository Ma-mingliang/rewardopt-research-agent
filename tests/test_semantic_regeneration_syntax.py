"""Tests for syntax-safe semantic regeneration (v0.8.4+)."""

from __future__ import annotations

import textwrap
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from research_agent.core.executor import (
    _validate_patch_indentation,
    _syntax_safe_compile_check,
    _apply_diff_to_content,
    _attempt_syntax_aware_repair,
    _generate_template_patch,
)
from research_agent.core.proposal_context import ProposalContext


# --- _validate_patch_indentation tests ---

class TestValidatePatchIndentation:
    def test_valid_patch(self):
        diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -954,3 +954,5 @@\n"
            "     tracking_reward = -1.0 * current_error**2\n"
            "+    shaping_penalty = -0.1 * (current_error ** 2)\n"
            "+    reward += shaping_penalty\n"
            "     return reward\n"
        )
        ok, errors = _validate_patch_indentation(diff)
        assert ok is True
        assert errors == []

    def test_tab_space_mixing(self):
        diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -954,3 +954,4 @@\n"
            "     tracking_reward = -1.0 * current_error**2\n"
            "+\t   shaping_penalty = -0.1 * current_error\n"
            "     return reward\n"
        )
        ok, errors = _validate_patch_indentation(diff)
        assert ok is False
        assert any("Tab/space mixing" in e for e in errors)

    def test_tab_only_indentation(self):
        diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -954,3 +954,4 @@\n"
            "     tracking_reward = -1.0 * current_error**2\n"
            "+\tshaping_penalty = -0.1 * current_error\n"
            "     return reward\n"
        )
        ok, errors = _validate_patch_indentation(diff)
        assert ok is False
        assert any("Tab-only" in e for e in errors)

    def test_trailing_whitespace(self):
        diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -954,3 +954,4 @@\n"
            "     tracking_reward = -1.0 * current_error**2\n"
            "+    shaping_penalty = -0.1 * current_error   \n"
            "     return reward\n"
        )
        ok, errors = _validate_patch_indentation(diff)
        assert ok is False
        assert any("Trailing whitespace" in e for e in errors)

    def test_suspicious_indent_spread(self):
        # Mix top-level (0 indent) and deeply nested (20 indent) in same patch
        diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -954,3 +954,5 @@\n"
            "     tracking_reward = -1.0 * current_error**2\n"
            "+global_var = 42\n"
            "+                    deeply_nested = 1\n"
            "     return reward\n"
        )
        ok, errors = _validate_patch_indentation(diff)
        assert ok is False
        assert any("Suspicious indent spread" in e for e in errors)

    def test_empty_patch(self):
        ok, errors = _validate_patch_indentation("")
        assert ok is False
        assert "Empty patch" in errors

    def test_only_removed_lines(self):
        # Only - lines, no + lines -> should pass (nothing to validate)
        diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -954,3 +954,2 @@\n"
            "     tracking_reward = -1.0 * current_error**2\n"
            "-    extra_line = 0\n"
            "     return reward\n"
        )
        ok, errors = _validate_patch_indentation(diff)
        assert ok is True


# --- _apply_diff_to_content tests ---

class TestApplyDiffToContent:
    def test_basic_apply(self):
        original = textwrap.dedent("""\
            def calculate_reward(self):
                reward = 0.0
                tracking_reward = -1.0 * self.error ** 2
                reward += tracking_reward
                return reward
        """)
        diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -3,2 +3,4 @@\n"
            "     tracking_reward = -1.0 * self.error ** 2\n"
            "+    shaping_penalty = -0.1 * (self.error ** 2)\n"
            "+    reward += shaping_penalty\n"
            "     reward += tracking_reward\n"
        )
        result = _apply_diff_to_content(original, diff)
        assert result is not None
        assert "shaping_penalty" in result
        assert "reward += shaping_penalty" in result

    def test_invalid_diff_returns_none(self):
        result = _apply_diff_to_content("hello", "not a diff")
        assert result is None


# --- _syntax_safe_compile_check tests ---

class TestSyntaxSafeCompileCheck:
    def test_valid_python(self, tmp_path):
        original = (
            "def calculate_reward(self):\n"
            "    reward = 0.0\n"
            "    tracking_reward = -1.0 * self.error ** 2\n"
            "    reward += tracking_reward\n"
            "    return reward\n"
        )
        diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -3,2 +3,4 @@\n"
            "     tracking_reward = -1.0 * self.error ** 2\n"
            "+    shaping_penalty = -0.1 * (self.error ** 2)\n"
            "+    reward += shaping_penalty\n"
            "     reward += tracking_reward\n"
        )
        temp_file = tmp_path / "env.py"
        ok, err = _syntax_safe_compile_check(temp_file, diff, original)
        assert ok is True
        assert err == ""

    def test_indentation_error(self, tmp_path):
        original = (
            "def calculate_reward(self):\n"
            "    reward = 0.0\n"
            "    tracking_reward = -1.0 * self.error ** 2\n"
            "    reward += tracking_reward\n"
            "    return reward\n"
        )
        # Bad indentation: mixed tabs and spaces
        diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -3,2 +3,4 @@\n"
            "     tracking_reward = -1.0 * self.error ** 2\n"
            "+\t   shaping_penalty = -0.1 * (self.error ** 2)\n"
            "+    reward += shaping_penalty\n"
            "     reward += tracking_reward\n"
        )
        temp_file = tmp_path / "env.py"
        ok, err = _syntax_safe_compile_check(temp_file, diff, original)
        assert ok is False
        # Should fail on indentation validation or compile
        assert "Indentation" in err or "Tab" in err or "indent" in err.lower() or "SyntaxError" in err or "TabError" in err


# --- _generate_template_patch with safe anchors tests ---

class TestGenerateTemplatePatchSafeAnchors:
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
            indent_unit=4,
            base_indent=8,
        )

    def test_template_uses_anchor_line(self):
        ctx = self._make_proposal_context()
        patch = _generate_template_patch(ctx)
        assert patch is not None
        # Should contain the actual anchor line content
        assert "reward += tracking_reward" in patch
        # Should contain the shaping term
        assert "shaping_penalty" in patch
        # Should use correct indentation (8 + 4 = 12 spaces)
        assert "            reward += shaping_penalty" in patch

    def test_template_no_reward_lines(self):
        ctx = ProposalContext(
            target_file="env.py",
            function_name="test",
            function_start_line=1,
            function_end_line=10,
            line_numbered_context="",
            available_reward_variables=["self", "reward"],
            existing_reward_terms=[],
            existing_reward_expression_lines=[],
        )
        patch = _generate_template_patch(ctx)
        assert patch is None


# --- _attempt_syntax_aware_repair tests ---

class TestAttemptSyntaxAwareRepair:
    def _make_proposal_context(self) -> ProposalContext:
        return ProposalContext(
            target_file="env.py",
            function_name="__calculate_reward",
            function_start_line=950,
            function_end_line=1000,
            class_name="MyEnv",
            class_start_line=10,
            line_numbered_context="  950 >>>     def __calculate_reward(self):\n  951 >>>         reward = 0.0",
            available_reward_variables=["self", "reward", "current_error"],
            existing_reward_terms=["tracking_reward"],
            existing_reward_expression_lines=["  L954: reward += tracking_reward"],
            indent_unit=4,
            base_indent=8,
        )

    def test_no_llm_client(self):
        optimizer = SimpleNamespace(llm_client=None)
        candidate = SimpleNamespace(patch_diff="some diff", candidate_id="test")
        result = _attempt_syntax_aware_repair(
            optimizer, candidate, self._make_proposal_context(),
            "IndentationError", "raw response",
        )
        assert result is None

    def test_successful_repair(self):
        repaired_diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -954,3 +954,5 @@\n"
            "     tracking_reward = -1.0 * current_error**2\n"
            "+    shaping_penalty = -0.1 * (current_error ** 2)\n"
            "+    reward += shaping_penalty\n"
            "     return reward\n"
        )
        mock_response = SimpleNamespace(content=repaired_diff)
        mock_llm = MagicMock()
        mock_llm.call.return_value = mock_response
        optimizer = SimpleNamespace(llm_client=mock_llm)

        candidate = SimpleNamespace(patch_diff="bad diff", candidate_id="test")
        result = _attempt_syntax_aware_repair(
            optimizer, candidate, self._make_proposal_context(),
            "IndentationError: unexpected indent", "raw response",
        )
        assert result is not None
        assert "shaping_penalty" in result
        mock_llm.call.assert_called_once()
