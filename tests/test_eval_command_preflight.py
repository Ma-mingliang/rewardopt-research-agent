"""Tests for eval_command placeholder preflight validation."""

import sys
import pytest
from research_agent.core.eval_diagnostics import (
    EvalDiagnostic,
    EvalFailureType,
    build_repro_command,
    run_eval_preflight,
)

_PYTHON = sys.executable


class TestEvalCommandPreflight:
    """Test eval_command placeholder validation in preflight."""

    def test_checkpoint_path_placeholder_passes(self, tmp_path):
        """eval_command with {checkpoint_path} should pass preflight."""
        env_file = tmp_path / "env.py"
        env_file.write_text("import gymnasium\nclass Env: pass\n")
        ok, diag = run_eval_preflight(
            execution_python=_PYTHON,
            project_path=tmp_path,
            eval_command="python evaluate.py {checkpoint_path}",
            env_file=env_file,
        )
        assert ok is True
        assert diag.diagnostic_summary == "Preflight passed"

    def test_seed_placeholder_for_evaluate_script_fails(self, tmp_path):
        """eval_command with evaluate.py {seed} should fail with fix_hint."""
        env_file = tmp_path / "env.py"
        env_file.write_text("import gymnasium\nclass Env: pass\n")
        ok, diag = run_eval_preflight(
            execution_python=_PYTHON,
            project_path=tmp_path,
            eval_command="python evaluate.py {seed}",
            env_file=env_file,
        )
        assert ok is False
        assert diag.failure_type == EvalFailureType.MODEL_LOAD_FAILED
        assert "{checkpoint_path}" in diag.error_message
        assert diag.fix_hint != ""
        assert "{seed}" in diag.fix_hint
        assert "{checkpoint_path}" in diag.fix_hint
        assert diag.expected_placeholder == "{checkpoint_path}"
        assert diag.found_placeholder == "{seed}"

    def test_seed_placeholder_for_non_evaluate_script_passes(self, tmp_path):
        """eval_command with non-evaluate script using {seed} should pass."""
        env_file = tmp_path / "env.py"
        env_file.write_text("import gymnasium\nclass Env: pass\n")
        ok, diag = run_eval_preflight(
            execution_python=_PYTHON,
            project_path=tmp_path,
            eval_command="python run_test.py {seed}",
            env_file=env_file,
        )
        assert ok is True

    def test_both_placeholders_passes(self, tmp_path):
        """eval_command with both {seed} and {checkpoint_path} should pass."""
        env_file = tmp_path / "env.py"
        env_file.write_text("import gymnasium\nclass Env: pass\n")
        ok, diag = run_eval_preflight(
            execution_python=_PYTHON,
            project_path=tmp_path,
            eval_command="python evaluate.py {checkpoint_path} --seed {seed}",
            env_file=env_file,
        )
        assert ok is True

    def test_no_placeholder_passes(self, tmp_path):
        """eval_command without placeholders should pass."""
        env_file = tmp_path / "env.py"
        env_file.write_text("import gymnasium\nclass Env: pass\n")
        ok, diag = run_eval_preflight(
            execution_python=_PYTHON,
            project_path=tmp_path,
            eval_command="python evaluate.py model.zip",
            env_file=env_file,
        )
        assert ok is True

    def test_empty_eval_command_passes(self, tmp_path):
        """Empty eval_command should pass (handled elsewhere)."""
        env_file = tmp_path / "env.py"
        env_file.write_text("import gymnasium\nclass Env: pass\n")
        ok, diag = run_eval_preflight(
            execution_python=_PYTHON,
            project_path=tmp_path,
            eval_command="",
            env_file=env_file,
        )
        assert ok is True


class TestBuildReproCommandCheckpointPath:
    """Test {checkpoint_path} in build_repro_command."""

    def test_replaces_checkpoint_path(self):
        cmd = build_repro_command(
            execution_python=_PYTHON,
            eval_command="python evaluate.py {checkpoint_path}",
            cwd="/project",
            model_path="/project/model/best_model.zip",
        )
        assert "{checkpoint_path}" not in cmd
        assert "/project/model/best_model.zip" in cmd

    def test_replaces_seed_and_checkpoint_path(self):
        cmd = build_repro_command(
            execution_python=_PYTHON,
            eval_command="python evaluate.py {checkpoint_path} --seed {seed}",
            cwd="/project",
            model_path="/project/model/best_model.zip",
            seed=42,
        )
        assert "best_model.zip" in cmd
        assert "42" in cmd
        assert "{checkpoint_path}" not in cmd
        assert "{seed}" not in cmd

    def test_empty_model_path_leaves_placeholder(self):
        cmd = build_repro_command(
            execution_python=_PYTHON,
            eval_command="python evaluate.py {checkpoint_path}",
            cwd="/project",
            model_path="",
        )
        # With empty model_path, placeholder is not replaced
        assert "{checkpoint_path}" in cmd


class TestEvalDiagnosticFields:
    """Test new EvalDiagnostic fields for placeholder diagnostics."""

    def test_has_placeholder_fields(self):
        diag = EvalDiagnostic()
        assert hasattr(diag, "eval_command")
        assert hasattr(diag, "expected_placeholder")
        assert hasattr(diag, "found_placeholder")
        assert hasattr(diag, "fix_hint")

    def test_to_dict_includes_placeholder_fields(self):
        diag = EvalDiagnostic()
        diag.eval_command = "python evaluate.py {seed}"
        diag.expected_placeholder = "{checkpoint_path}"
        diag.found_placeholder = "{seed}"
        diag.fix_hint = "Replace {seed} with {checkpoint_path}"
        d = diag.to_dict()
        assert d["eval_command"] == "python evaluate.py {seed}"
        assert d["expected_placeholder"] == "{checkpoint_path}"
        assert d["found_placeholder"] == "{seed}"
        assert "fix_hint" in d
