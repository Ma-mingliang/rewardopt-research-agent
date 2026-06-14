"""Tests for the observability module (RunObserver)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def observer(tmp_path):
    """Create a RunObserver for testing."""
    from research_agent.core.observability import RunObserver

    return RunObserver(
        run_log_dir=str(tmp_path / "runs"),
        optimizer="test_optimizer",
        project_path=str(tmp_path),
        agent_python=sys.executable,
        execution_python="/fake/python.exe",
        fallback_used=False,
        mock_llm=True,
        max_iterations=1,
        batch_size=1,
    )


class TestRunObserver:
    def test_creates_run_dir(self, observer, tmp_path):
        """RunObserver creates the run directory."""
        assert observer.run_dir.exists()
        assert "test_optimizer" in observer.run_id

    def test_emit_writes_jsonl(self, observer):
        """emit() writes valid JSON lines to events.jsonl."""
        observer.emit("test_event", key1="value1", key2=42)
        observer.emit("test_event2", key3=True)

        assert observer.events_path.exists()
        lines = observer.events_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

        for line in lines:
            record = json.loads(line)
            assert "timestamp" in record
            assert "run_id" in record
            assert "event_type" in record
            assert record["optimizer"] == "test_optimizer"

        r1 = json.loads(lines[0])
        assert r1["event_type"] == "test_event"
        assert r1["key1"] == "value1"
        assert r1["key2"] == 42

    def test_emit_includes_environment_fields(self, observer):
        """emit() includes agent_python, execution_python, fallback_used."""
        observer.emit("env_check")
        lines = observer.events_path.read_text(encoding="utf-8").strip().splitlines()
        record = json.loads(lines[0])
        assert record["agent_python"] == sys.executable
        assert record["execution_python"] == "/fake/python.exe"
        assert record["fallback_used"] is False

    def test_emit_redacts_api_keys(self, observer):
        """emit() redacts fields containing api_key or secret."""
        observer.emit("security_check", api_key="sk-123456", my_secret="password123", normal="ok")
        lines = observer.events_path.read_text(encoding="utf-8").strip().splitlines()
        record = json.loads(lines[0])
        assert record["api_key"] == "<redacted>"
        assert record["my_secret"] == "<redacted>"
        assert record["normal"] == "ok"

    def test_emit_truncates_long_tails(self, observer):
        """emit() truncates stdout_tail/stderr_tail to 1000 chars."""
        long_text = "x" * 2000
        observer.emit("tail_check", stdout_tail=long_text)
        lines = observer.events_path.read_text(encoding="utf-8").strip().splitlines()
        record = json.loads(lines[0])
        assert len(record["stdout_tail"]) < 2000  # must be truncated
        assert "truncated" in record["stdout_tail"]

    def test_write_summary_creates_json(self, observer):
        """write_summary() creates a valid summary.json."""
        observer.track_candidate("rejected", rejection_reason="empty_patch", llm_calls=1)
        observer.track_candidate("evaluated", llm_calls=2)
        observer.write_summary()

        assert observer.summary_path.exists()
        summary = json.loads(observer.summary_path.read_text(encoding="utf-8"))

        assert summary["run_id"] == observer.run_id
        assert summary["optimizer"] == "test_optimizer"
        assert summary["mock_llm"] is True
        assert summary["candidates_total"] == 2
        assert summary["candidates_rejected"] == 1
        assert summary["candidates_ready"] == 1
        assert summary["llm_calls_total"] == 3
        assert summary["rejection_reasons"]["empty_patch"] == 1
        assert "started_at" in summary
        assert "ended_at" in summary
        assert summary["event_log"] == "events.jsonl"

    def test_write_summary_includes_execution_python(self, observer):
        """summary.json includes execution_python."""
        observer.write_summary()
        summary = json.loads(observer.summary_path.read_text(encoding="utf-8"))
        assert summary["execution_python"] == "/fake/python.exe"
        assert summary["fallback_used"] is False

    def test_close_prevents_further_events(self, observer):
        """After close(), emit() is a no-op."""
        observer.emit("before_close")
        observer.close()
        observer.emit("after_close")

        lines = observer.events_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["event_type"] == "before_close"

    def test_context_manager(self, tmp_path):
        """RunObserver works as a context manager."""
        from research_agent.core.observability import RunObserver

        with RunObserver(
            run_log_dir=str(tmp_path / "runs"),
            optimizer="ctx_test",
            project_path=str(tmp_path),
        ) as obs:
            obs.emit("inside_ctx")
            assert obs.is_active

        assert not obs.is_active
        assert obs.summary_path.exists()

    def test_track_candidate_counts(self, observer):
        """track_candidate() updates counters correctly."""
        observer.track_candidate("rejected", rejection_reason="empty_patch")
        observer.track_candidate("rejected", rejection_reason="train_failed")
        observer.track_candidate("evaluated")
        observer.track_candidate("rejected", rejection_reason="empty_patch")

        assert observer._candidates_total == 4
        assert observer._candidates_rejected == 3
        assert observer._candidates_ready == 1
        assert observer._rejection_reasons["empty_patch"] == 2
        assert observer._rejection_reasons["train_failed"] == 1

    def test_summary_json_parseable(self, observer):
        """summary.json is always valid JSON, even with special characters."""
        observer.emit("special", message="line1\nline2\ttab")
        observer.write_summary()
        summary = json.loads(observer.summary_path.read_text(encoding="utf-8"))
        assert summary["run_id"] == observer.run_id

    def test_no_api_key_in_events(self, observer):
        """Events must not contain actual API keys."""
        observer.emit("security", api_key="sk-real-key-12345", OPENAI_API_KEY="sk-also-real")
        lines = observer.events_path.read_text(encoding="utf-8").strip().splitlines()
        for line in lines:
            assert "sk-real-key-12345" not in line
            assert "sk-also-real" not in line

    def test_run_id_format(self, observer):
        """run_id follows YYYYMMDD_HHMMSS_<optimizer>_<hex> format."""
        import re
        pattern = r"^\d{8}_\d{6}_test_optimizer_[a-f0-9]{6}$"
        assert re.match(pattern, observer.run_id), f"run_id '{observer.run_id}' doesn't match pattern"

    def test_track_full_eval_success(self, observer):
        """track_full_eval increments total but not failed on success."""
        observer.track_full_eval(failed=False)
        observer.track_full_eval(failed=False)
        assert observer._full_eval_total == 2
        assert observer._full_eval_failed == 0

    def test_track_full_eval_failure(self, observer):
        """track_full_eval increments failure counters."""
        observer.track_full_eval(failed=True, failure_type="metrics_empty")
        observer.track_full_eval(failed=True, failure_type="eval_script_crashed")
        observer.track_full_eval(failed=True, failure_type="metrics_empty")
        assert observer._full_eval_total == 3
        assert observer._full_eval_failed == 3
        assert observer._full_eval_failure_types["metrics_empty"] == 2
        assert observer._full_eval_failure_types["eval_script_crashed"] == 1

    def test_track_full_eval_timeout(self, observer):
        """eval_timeout increments timeout counter."""
        observer.track_full_eval(failed=True, failure_type="eval_timeout")
        assert observer._eval_timeout_count == 1

    def test_track_full_eval_model_missing(self, observer):
        """model_missing increments model_missing counter."""
        observer.track_full_eval(failed=True, failure_type="model_missing")
        assert observer._model_missing_count == 1

    def test_track_full_eval_metrics_parse_failed(self, observer):
        """metrics_parse_failed increments parse failed counter."""
        observer.track_full_eval(failed=True, failure_type="metrics_parse_failed")
        assert observer._metrics_parse_failed_count == 1

    def test_track_full_eval_stores_repro_command(self, observer):
        """Last failed eval repro command is stored."""
        observer.track_full_eval(
            failed=True, failure_type="metrics_empty",
            repro_command="cd /d D:/project && python evaluate.py",
        )
        assert observer._last_failed_eval_repro_command == "cd /d D:/project && python evaluate.py"

    def test_write_summary_includes_full_eval_fields(self, observer):
        """summary.json includes full eval diagnostic fields."""
        observer.track_full_eval(failed=True, failure_type="metrics_empty",
                                 repro_command="test_cmd")
        observer.write_summary()
        summary = json.loads(observer.summary_path.read_text(encoding="utf-8"))
        assert summary["full_eval_total"] == 1
        assert summary["full_eval_failed"] == 1
        assert summary["full_eval_failure_types"]["metrics_empty"] == 1
        assert summary["eval_timeout_count"] == 0
        assert summary["model_missing_count"] == 0
        assert summary["metrics_parse_failed_count"] == 1
        assert summary["last_failed_eval_repro_command"] == "test_cmd"

    def test_write_summary_full_eval_defaults_zero(self, observer):
        """summary.json has zero defaults when no full evals run."""
        observer.write_summary()
        summary = json.loads(observer.summary_path.read_text(encoding="utf-8"))
        assert summary["full_eval_total"] == 0
        assert summary["full_eval_failed"] == 0
        assert summary["full_eval_failure_types"] == {}
        assert summary["last_failed_eval_repro_command"] is None

    def test_emit_full_eval_events(self, observer):
        """Can emit full_eval_preflight/failed events."""
        observer.emit("full_eval_preflight_start", candidate_id="c001")
        observer.emit("full_eval_preflight_end", candidate_id="c001", preflight_ok=False)
        observer.emit("full_eval_failed", candidate_id="c001", failure_type="model_missing")
        lines = observer.events_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3
        r0 = json.loads(lines[0])
        assert r0["event_type"] == "full_eval_preflight_start"
        r2 = json.loads(lines[2])
        assert r2["event_type"] == "full_eval_failed"
        assert r2["failure_type"] == "model_missing"
