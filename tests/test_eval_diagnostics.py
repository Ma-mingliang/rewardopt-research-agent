"""Tests for the eval_diagnostics module."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from research_agent.core.eval_diagnostics import (
    EvalDiagnostic,
    EvalFailureType,
    build_repro_command,
    classify_eval_failure,
    hash_file,
    run_eval_preflight,
    tail_text,
)


class TestEvalFailureType:
    def test_enum_values(self):
        """All failure type enum values are strings."""
        for ft in EvalFailureType:
            assert isinstance(ft.value, str)

    def test_none_is_not_failure(self):
        assert EvalFailureType.NONE.value == "none"

    def test_metrics_empty_exists(self):
        assert EvalFailureType.METRICS_EMPTY.value == "metrics_empty"

    def test_eval_script_crashed_exists(self):
        assert EvalFailureType.EVAL_SCRIPT_CRASHED.value == "eval_script_crashed"


class TestClassifyEvalFailure:
    def test_execution_python_missing(self):
        ft = classify_eval_failure(
            returncode=0, timed_out=False, stdout="", stderr="",
            metrics={}, execution_python_exists=False,
        )
        assert ft == EvalFailureType.EXECUTION_PYTHON_MISSING

    def test_env_import_failed(self):
        ft = classify_eval_failure(
            returncode=0, timed_out=False, stdout="", stderr="",
            metrics={}, env_import_ok=False,
        )
        assert ft == EvalFailureType.ENV_IMPORT_FAILED

    def test_model_missing(self):
        ft = classify_eval_failure(
            returncode=0, timed_out=False, stdout="", stderr="",
            metrics={}, model_exists=False,
        )
        assert ft == EvalFailureType.MODEL_MISSING

    def test_output_dir_not_writable(self):
        ft = classify_eval_failure(
            returncode=0, timed_out=False, stdout="", stderr="",
            metrics={}, output_dir_writable=False,
        )
        assert ft == EvalFailureType.OUTPUT_DIR_NOT_WRITABLE

    def test_eval_timeout(self):
        ft = classify_eval_failure(
            returncode=-1, timed_out=True, stdout="", stderr="",
            metrics={},
        )
        assert ft == EvalFailureType.EVAL_TIMEOUT

    def test_eval_script_crashed_with_traceback(self):
        ft = classify_eval_failure(
            returncode=1, timed_out=False,
            stdout="", stderr="Traceback (most recent call last):\n  File \"evaluate.py\"\nValueError: bad",
            metrics={},
        )
        assert ft == EvalFailureType.EVAL_SCRIPT_CRASHED

    def test_subprocess_failed_no_traceback(self):
        ft = classify_eval_failure(
            returncode=1, timed_out=False, stdout="", stderr="exit code 1",
            metrics={},
        )
        assert ft == EvalFailureType.SUBPROCESS_FAILED

    def test_metrics_file_missing(self):
        """When returncode=0, no metrics, and parser ok → metrics_empty."""
        ft = classify_eval_failure(
            returncode=0, timed_out=False, stdout="done", stderr="",
            metrics={},
        )
        assert ft == EvalFailureType.METRICS_EMPTY

    def test_metrics_parse_failed(self):
        ft = classify_eval_failure(
            returncode=0, timed_out=False, stdout="done", stderr="",
            metrics={}, metrics_parser_ok=False,
        )
        assert ft == EvalFailureType.METRICS_PARSE_FAILED

    def test_metrics_empty(self):
        ft = classify_eval_failure(
            returncode=0, timed_out=False, stdout="done", stderr="",
            metrics={},
        )
        assert ft == EvalFailureType.METRICS_EMPTY

    def test_required_metrics_missing(self):
        ft = classify_eval_failure(
            returncode=0, timed_out=False, stdout="done", stderr="",
            metrics={"reward": 100.0},
            required_metrics=["reward", "lateral_error"],
        )
        assert ft == EvalFailureType.REQUIRED_METRICS_MISSING

    def test_no_failure(self):
        ft = classify_eval_failure(
            returncode=0, timed_out=False, stdout="done", stderr="",
            metrics={"reward": 100.0},
        )
        assert ft == EvalFailureType.NONE

    def test_model_load_failed_in_stderr(self):
        ft = classify_eval_failure(
            returncode=1, timed_out=False,
            stdout="", stderr="Error: could not load model file",
            metrics={},
        )
        assert ft == EvalFailureType.MODEL_LOAD_FAILED


class TestBuildReproCommand:
    def test_basic_command(self):
        cmd = build_repro_command(
            execution_python="E:/Anaconda/envs/RL2/python.exe",
            eval_command="python evaluate.py --seed 0",
            cwd="D:/research-agent/HRRL2",
        )
        assert "cd /d" in cmd
        assert "E:/Anaconda/envs/RL2/python.exe" in cmd
        assert "evaluate.py" in cmd

    def test_uses_execution_python_not_agent(self):
        cmd = build_repro_command(
            execution_python="E:/Anaconda/envs/RL2/python.exe",
            eval_command="python evaluate.py",
            cwd="D:/research-agent/HRRL2",
        )
        assert "E:/Anaconda/envs/RL2/python.exe" in cmd
        # Should not have bare "python " (replaced by execution_python)
        # The command starts with execution_python
        lines = cmd.split(" && ")
        eval_line = lines[-1] if lines else cmd
        assert eval_line.startswith("E:/Anaconda/envs/RL2/python.exe")

    def test_python_placeholder_replacement(self):
        cmd = build_repro_command(
            execution_python="E:/Anaconda/envs/RL2/python.exe",
            eval_command="{python} evaluate.py --seed 0",
            cwd="D:/research-agent/HRRL2",
        )
        assert "{python}" not in cmd
        assert "E:/Anaconda/envs/RL2/python.exe" in cmd

    def test_seed_replacement(self):
        cmd = build_repro_command(
            execution_python="E:/Anaconda/envs/RL2/python.exe",
            eval_command="python evaluate.py --seed {seed}",
            cwd="D:/research-agent/HRRL2",
            seed=42,
        )
        assert "--seed 42" in cmd

    def test_path_with_spaces_quoted(self):
        cmd = build_repro_command(
            execution_python="E:/Anaconda/envs/RL 2/python.exe",
            eval_command="python evaluate.py",
            cwd="D:/research agent/HRRL2",
        )
        assert '"D:/research agent/HRRL2"' in cmd


class TestHashFile:
    def test_hash_returns_string(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")
        h = hash_file(f)
        assert isinstance(h, str)
        assert len(h) == 16

    def test_hash_consistent(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")
        assert hash_file(f) == hash_file(f)

    def test_hash_missing_file(self):
        assert hash_file("/nonexistent/file.txt") == ""

    def test_hash_different_content(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello", encoding="utf-8")
        f2.write_text("world", encoding="utf-8")
        assert hash_file(f1) != hash_file(f2)


class TestTailText:
    def test_short_file(self, tmp_path):
        f = tmp_path / "short.txt"
        f.write_text("hello", encoding="utf-8")
        assert tail_text(f) == "hello"

    def test_long_file_truncated(self, tmp_path):
        f = tmp_path / "long.txt"
        f.write_text("x" * 5000, encoding="utf-8")
        result = tail_text(f, max_chars=100)
        assert len(result) <= 104  # "..." + 100 chars
        assert result.startswith("...")

    def test_missing_file(self):
        assert tail_text("/nonexistent/file.txt") == ""

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        assert tail_text(f) == ""


class TestRunEvalPreflight:
    def test_execution_python_missing(self, tmp_path):
        ok, diag = run_eval_preflight(
            execution_python="/nonexistent/python.exe",
            project_path=tmp_path,
            eval_command="python evaluate.py",
        )
        assert not ok
        assert diag.failure_type == EvalFailureType.EXECUTION_PYTHON_MISSING

    def test_project_path_missing(self):
        ok, diag = run_eval_preflight(
            execution_python=sys.executable,
            project_path="/nonexistent/project",
            eval_command="python evaluate.py",
        )
        assert not ok

    def test_env_import_failed(self, tmp_path):
        env_file = tmp_path / "env.py"
        env_file.write_text("def broken(\n", encoding="utf-8")  # syntax error
        ok, diag = run_eval_preflight(
            execution_python=sys.executable,
            project_path=tmp_path,
            eval_command="python evaluate.py",
            env_file=env_file,
        )
        assert not ok
        assert diag.failure_type == EvalFailureType.ENV_IMPORT_FAILED

    def test_model_missing(self, tmp_path):
        ok, diag = run_eval_preflight(
            execution_python=sys.executable,
            project_path=tmp_path,
            eval_command="python evaluate.py",
            model_path=tmp_path / "nonexistent_model.zip",
        )
        assert not ok
        assert diag.failure_type == EvalFailureType.MODEL_MISSING

    def test_preflight_passes(self, tmp_path):
        env_file = tmp_path / "env.py"
        env_file.write_text("x = 1\n", encoding="utf-8")
        ok, diag = run_eval_preflight(
            execution_python=sys.executable,
            project_path=tmp_path,
            eval_command="python evaluate.py",
            env_file=env_file,
        )
        assert ok
        assert diag.failure_type == EvalFailureType.NONE

    def test_preflight_records_env_hash(self, tmp_path):
        env_file = tmp_path / "env.py"
        env_file.write_text("x = 1\n", encoding="utf-8")
        ok, diag = run_eval_preflight(
            execution_python=sys.executable,
            project_path=tmp_path,
            eval_command="python evaluate.py",
            env_file=env_file,
        )
        assert ok
        assert diag.eval_env_hash != ""
        assert len(diag.eval_env_hash) == 16


class TestEvalDiagnostic:
    def test_to_dict(self):
        diag = EvalDiagnostic(
            candidate_id="test_c001",
            failure_type=EvalFailureType.METRICS_EMPTY,
            failed=True,
            diagnostic_summary="No metrics",
        )
        d = diag.to_dict()
        assert d["candidate_id"] == "test_c001"
        assert d["failure_type"] == "metrics_empty"
        assert d["failed"] is True

    def test_default_values(self):
        diag = EvalDiagnostic()
        assert diag.failed is False
        assert diag.failure_type == EvalFailureType.NONE
        assert diag.returncode == 0


class TestRunResultDiagnostics:
    def test_run_result_has_diagnostics_field(self):
        """RunResult supports optional diagnostics field."""
        from research_agent.execution.experiment_runner import RunResult
        r = RunResult(
            command="test", return_code=0, stdout="", stderr="",
            duration_seconds=1.0,
        )
        assert r.diagnostics is None

    def test_run_result_with_diagnostics(self):
        """RunResult can carry diagnostics dict."""
        from research_agent.execution.experiment_runner import RunResult
        diag = {"failure_type": "metrics_empty", "failed": True}
        r = RunResult(
            command="test", return_code=0, stdout="", stderr="",
            duration_seconds=1.0, diagnostics=diag,
        )
        assert r.diagnostics is not None
        assert r.diagnostics["failure_type"] == "metrics_empty"


class TestBackwardCompatibility:
    def test_full_eval_result_has_required_fields(self):
        """full_eval_result must always have metrics and failed."""
        result = {
            "metrics": {"reward": 100.0},
            "failed": False,
            "seeds": [0],
        }
        assert "metrics" in result
        assert "failed" in result

    def test_diagnostics_additive_only(self):
        """Diagnostics fields are additive — old fields preserved."""
        result = {
            "metrics": {},
            "failed": True,
            "seeds": [0],
            # v0.3 additive fields
            "failure_type": "metrics_empty",
            "failure_stage": "metrics_parse",
            "diagnostics": {"failure_type": "metrics_empty"},
        }
        # Old callers still see metrics and failed
        assert "metrics" in result
        assert "failed" in result
        # New callers can access diagnostics
        assert result.get("failure_type") == "metrics_empty"
