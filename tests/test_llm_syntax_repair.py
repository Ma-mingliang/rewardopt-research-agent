"""Tests for the syntax-aware LLM patch repair module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent.core.patch_repair import (
    PatchRepairError,
    PatchRepairResult,
    RepairAttemptTracker,
    RepairStrategy,
    build_syntax_repair_prompt,
    extract_error_line,
    extract_error_type,
    extract_local_context,
    make_error_signature,
    parse_repair_response,
    validate_repaired_diff_on_temp_copy,
)


class TestMakeErrorSignature:
    def test_basic_signature(self):
        sig = make_error_signature("IndentationError", "env.py", 983, "expected an indented block after if statement")
        assert "IndentationError" in sig
        assert "env.py" in sig
        assert "983" in sig
        assert "expected an indented block" in sig

    def test_no_line_number(self):
        sig = make_error_signature("SyntaxError", "env.py", None, "invalid syntax")
        assert "none" in sig

    def test_signature_normalization(self):
        sig1 = make_error_signature("IndentationError", "env.py", 983, "Expected  an   indented block")
        sig2 = make_error_signature("IndentationError", "env.py", 983, "expected an indented block")
        # Both should normalize whitespace
        assert sig1.split("|")[3] == sig2.split("|")[3]


class TestExtractErrorLine:
    def test_extract_from_py_compile(self):
        msg = "env.py:983: IndentationError: expected an indented block"
        assert extract_error_line(msg) == 983

    def test_extract_from_traceback(self):
        msg = "  File 'env.py', line 42, in <module>"
        assert extract_error_line(msg) == 42

    def test_no_line_number(self):
        msg = "Some generic error"
        assert extract_error_line(msg) is None


class TestExtractErrorType:
    def test_indentation_error(self):
        msg = "env.py:983: IndentationError: expected an indented block"
        assert extract_error_type(msg) == "IndentationError"

    def test_syntax_error(self):
        msg = "SyntaxError: invalid syntax"
        assert extract_error_type(msg) == "SyntaxError"

    def test_sorry_pattern(self):
        msg = "Sorry: IndentationError: expected an indented block after 'if' statement"
        assert extract_error_type(msg) == "IndentationError"

    def test_unknown_error(self):
        msg = "Something went wrong"
        assert extract_error_type(msg) == "UnknownError"


class TestExtractLocalContext:
    def test_context_with_marker(self, tmp_path: Path):
        f = tmp_path / "test.py"
        lines = [f"line {i}" for i in range(100)]
        f.write_text("\n".join(lines), encoding="utf-8")

        context = extract_local_context(f, 50, radius=5)
        assert ">>>" in context  # marker for error line
        assert "line 49" in context  # 0-indexed line 49 = line 50
        assert "line 50" in context

    def test_context_near_start(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("line 0\nline 1\nline 2\n", encoding="utf-8")
        context = extract_local_context(f, 1, radius=5)
        assert "line 0" in context

    def test_context_missing_file(self, tmp_path: Path):
        context = extract_local_context(tmp_path / "missing.py", 10, radius=5)
        assert "not found" in context


class TestPatchRepairError:
    def test_error_signature_property(self):
        error = PatchRepairError(
            error_type="IndentationError",
            file_path="env.py",
            line_number=983,
            message="expected an indented block after if statement",
        )
        sig = error.error_signature
        assert "IndentationError" in sig
        assert "env.py" in sig
        assert "983" in sig


class TestBuildSyntaxRepairPrompt:
    def _make_error(self) -> PatchRepairError:
        return PatchRepairError(
            error_type="IndentationError",
            file_path="env.py",
            line_number=983,
            message="expected an indented block after if statement",
            failed_diff="@@ -980,6 +980,8 @@\n if condition:\n+    new_line\n+another_line",
            baseline_context="    978     def reward(self):\n    979         if condition:\n>>> 980             pass",
            allowed_changes=["env.py"],
        )

    def test_direct_repair_prompt_includes_error(self):
        error = self._make_error()
        sys_prompt, user_prompt = build_syntax_repair_prompt(
            error, RepairStrategy.DIRECT_DIFF_REPAIR
        )
        assert "IndentationError" in user_prompt
        assert "983" in user_prompt
        assert "unified diff" in sys_prompt.lower()

    def test_direct_repair_prompt_includes_diff(self):
        error = self._make_error()
        _, user_prompt = build_syntax_repair_prompt(
            error, RepairStrategy.DIRECT_DIFF_REPAIR
        )
        assert "@@ -980,6 +980,8 @@" in user_prompt

    def test_direct_repair_prompt_includes_baseline_context(self):
        error = self._make_error()
        _, user_prompt = build_syntax_repair_prompt(
            error, RepairStrategy.DIRECT_DIFF_REPAIR
        )
        assert "def reward" in user_prompt

    def test_local_hunk_prompt_differs_from_direct(self):
        error = self._make_error()
        _, direct_prompt = build_syntax_repair_prompt(
            error, RepairStrategy.DIRECT_DIFF_REPAIR
        )
        _, hunk_prompt = build_syntax_repair_prompt(
            error, RepairStrategy.LOCAL_HUNK_REGENERATION
        )
        assert "regenerate" in hunk_prompt.lower() or "hunk" in hunk_prompt.lower()

    def test_idea_regen_prompt_differs(self):
        error = self._make_error()
        _, prompt = build_syntax_repair_prompt(
            error, RepairStrategy.IDEA_REGENERATION_FROM_BASELINE,
            reward_idea="Add safety penalty"
        )
        assert "safety penalty" in prompt
        assert "scratch" in prompt.lower() or "fresh" in prompt.lower()

    def test_prompt_includes_reward_idea(self):
        error = self._make_error()
        _, prompt = build_syntax_repair_prompt(
            error, RepairStrategy.DIRECT_DIFF_REPAIR,
            reward_idea="Add asymmetric safety penalty"
        )
        assert "asymmetric safety penalty" in prompt

    def test_prompt_includes_allowed_changes(self):
        error = self._make_error()
        _, prompt = build_syntax_repair_prompt(
            error, RepairStrategy.DIRECT_DIFF_REPAIR,
        )
        assert "env.py" in prompt

    def test_prompt_forbids_full_rewrite(self):
        error = self._make_error()
        _, prompt = build_syntax_repair_prompt(
            error, RepairStrategy.DIRECT_DIFF_REPAIR,
        )
        assert "NOT" in prompt or "not" in prompt.lower()


class TestParseRepairResponse:
    def test_json_with_fixed_diff(self):
        response = json.dumps({"fixed_diff": "--- a/env.py\n+++ b/env.py\n@@ -1,3 +1,4 @@\n"})
        result = parse_repair_response(response)
        assert result is not None
        assert "--- a/env.py" in result

    def test_json_with_diff_key(self):
        response = json.dumps({"diff": "--- a/env.py\n+++ b/env.py\n"})
        result = parse_repair_response(response)
        assert result is not None

    def test_raw_diff_output(self):
        response = "--- a/env.py\n+++ b/env.py\n@@ -1,3 +1,4 @@\n+new line"
        result = parse_repair_response(response)
        assert result is not None
        assert "+new line" in result

    def test_empty_response(self):
        assert parse_repair_response("") is None
        assert parse_repair_response(None) is None

    def test_markdown_wrapped_diff(self):
        response = "```diff\n--- a/env.py\n+++ b/env.py\n@@ -1,3 +1,4 @@\n+new line\n```"
        result = parse_repair_response(response)
        assert result is not None


class TestValidateRepairedDiffOnTempCopy:
    def test_valid_diff(self, tmp_path: Path):
        # Create a simple Python file
        env_file = tmp_path / "env.py"
        env_file.write_text("def reward():\n    return 1\n", encoding="utf-8")

        # Simple diff that adds a line
        diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -1,2 +1,3 @@\n"
            " def reward():\n"
            "+    x = 1\n"
            "     return 1\n"
        )

        ok, errors = validate_repaired_diff_on_temp_copy(tmp_path, diff, "env.py", "python")
        assert ok is True
        assert errors == []

    def test_invalid_diff_syntax_error(self, tmp_path: Path):
        env_file = tmp_path / "env.py"
        env_file.write_text("def reward():\n    return 1\n", encoding="utf-8")

        # Diff that introduces syntax error
        diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -1,2 +1,4 @@\n"
            " def reward():\n"
            "+    if True:\n"
            "+    bad_indent = 1\n"
            "     return 1\n"
        )

        ok, errors = validate_repaired_diff_on_temp_copy(tmp_path, diff, "env.py", "python")
        assert ok is False
        assert len(errors) > 0

    def test_missing_file(self, tmp_path: Path):
        diff = "--- a/env.py\n+++ b/env.py\n@@ -1,1 +1,2 @@\n+hello"
        ok, errors = validate_repaired_diff_on_temp_copy(tmp_path, diff, "env.py", "python")
        assert ok is False


class TestRepairStrategy:
    def test_enum_values(self):
        assert RepairStrategy.DIRECT_DIFF_REPAIR.value == "direct_diff_repair"
        assert RepairStrategy.LOCAL_HUNK_REGENERATION.value == "local_hunk_regeneration"
        assert RepairStrategy.IDEA_REGENERATION_FROM_BASELINE.value == "idea_regeneration_from_baseline"

    def test_str(self):
        assert str(RepairStrategy.DIRECT_DIFF_REPAIR) == "RepairStrategy.DIRECT_DIFF_REPAIR"
