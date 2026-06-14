"""Lightweight structured observability for optimizer runs.

Writes events.jsonl (append-only) and summary.json (on close).
No external dependencies beyond stdlib.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _generate_run_id(optimizer: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"{ts}_{optimizer}_{short}"


class RunObserver:
    """Structured event logger for a single optimizer run."""

    def __init__(
        self,
        run_log_dir: str | Path,
        optimizer: str,
        project_path: str | Path,
        agent_python: str = "",
        execution_python: str = "",
        fallback_used: bool = False,
        mock_llm: bool = False,
        max_iterations: int | None = None,
        batch_size: int = 1,
        extra: dict[str, Any] | None = None,
    ):
        self.run_id = _generate_run_id(optimizer)
        self.run_dir = Path(run_log_dir) / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.events_path = self.run_dir / "events.jsonl"
        self.summary_path = self.run_dir / "summary.json"

        self._optimizer = optimizer
        self._project_path = str(project_path)
        self._agent_python = agent_python
        self._execution_python = execution_python
        self._fallback_used = fallback_used
        self._mock_llm = mock_llm
        self._max_iterations = max_iterations
        self._batch_size = batch_size
        self._extra = extra or {}

        self._started_at = datetime.now(timezone.utc).isoformat()
        self._start_monotonic = time.monotonic()
        self._event_count = 0
        self._closed = False

        # Counters for summary
        self._candidates_total = 0
        self._candidates_ready = 0
        self._candidates_rejected = 0
        self._candidates_trained = 0
        self._candidates_eval_failed = 0
        self._metrics_empty_count = 0
        self._llm_calls_total = 0
        self._rejection_reasons: dict[str, int] = {}

        # Full eval diagnostics counters
        self._full_eval_total = 0
        self._full_eval_failed = 0
        self._full_eval_failure_types: dict[str, int] = {}
        self._eval_timeout_count = 0
        self._model_missing_count = 0
        self._metrics_parse_failed_count = 0
        self._last_failed_eval_repro_command: str | None = None
        self._last_failed_eval_stdout_path: str | None = None
        self._last_failed_eval_stderr_path: str | None = None

    def emit(self, event_type: str, **fields: Any) -> None:
        """Append a structured event to events.jsonl."""
        if self._closed:
            return

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "event_type": event_type,
            "optimizer": self._optimizer,
            "agent_python": self._agent_python,
            "execution_python": self._execution_python,
            "fallback_used": self._fallback_used,
            "project_path": self._project_path,
        }
        record.update(fields)

        # Truncate long stdout/stderr tails
        for key in ("stdout_tail", "stderr_tail"):
            val = record.get(key)
            if isinstance(val, str) and len(val) > 1000:
                record[key] = val[:1000] + "...<truncated>"

        # Never include API keys
        for key in list(record.keys()):
            if "api_key" in key.lower() or "secret" in key.lower():
                record[key] = "<redacted>"

        try:
            with open(self.events_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._event_count += 1
        except Exception:
            pass  # observability must never crash the run

    def track_candidate(self, status: str, rejection_reason: str | None = None, llm_calls: int = 0) -> None:
        """Update summary counters for a candidate."""
        self._candidates_total += 1
        if status in ("ready", "evaluated"):
            self._candidates_ready += 1
        elif status == "rejected":
            self._candidates_rejected += 1
            if rejection_reason:
                self._rejection_reasons[rejection_reason] = self._rejection_reasons.get(rejection_reason, 0) + 1
        self._llm_calls_total += llm_calls

    def track_train(self, success: bool) -> None:
        if success:
            self._candidates_trained += 1

    def track_eval_failed(self) -> None:
        self._candidates_eval_failed += 1

    def track_metrics_empty(self) -> None:
        self._metrics_empty_count += 1

    def track_full_eval(
        self,
        failed: bool = False,
        failure_type: str = "none",
        repro_command: str = "",
        stdout_path: str = "",
        stderr_path: str = "",
    ) -> None:
        """Track a full eval run with diagnostics."""
        self._full_eval_total += 1
        if failed:
            self._full_eval_failed += 1
            self._full_eval_failure_types[failure_type] = (
                self._full_eval_failure_types.get(failure_type, 0) + 1
            )
            if failure_type == "eval_timeout":
                self._eval_timeout_count += 1
            elif failure_type == "model_missing":
                self._model_missing_count += 1
            elif failure_type in ("metrics_parse_failed", "metrics_empty"):
                self._metrics_parse_failed_count += 1
            if repro_command:
                self._last_failed_eval_repro_command = repro_command
            if stdout_path:
                self._last_failed_eval_stdout_path = stdout_path
            if stderr_path:
                self._last_failed_eval_stderr_path = stderr_path

    def write_summary(self, extra: dict[str, Any] | None = None) -> None:
        """Write summary.json."""
        ended_at = datetime.now(timezone.utc).isoformat()
        duration_ms = int((time.monotonic() - self._start_monotonic) * 1000)

        # Try to get git info
        branch = None
        commit = None
        tag = None
        try:
            import subprocess
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self._project_path, text=True, stderr=subprocess.DEVNULL,
            ).strip()
            commit = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=self._project_path, text=True, stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:
            pass

        summary = {
            "run_id": self.run_id,
            "started_at": self._started_at,
            "ended_at": ended_at,
            "duration_ms": duration_ms,
            "project_path": self._project_path,
            "optimizer": self._optimizer,
            "agent_python": self._agent_python,
            "execution_python": self._execution_python,
            "fallback_used": self._fallback_used,
            "branch": branch,
            "commit": commit,
            "tag": tag,
            "mock_llm": self._mock_llm,
            "max_iterations": self._max_iterations,
            "batch_size": self._batch_size,
            "candidates_total": self._candidates_total,
            "candidates_ready": self._candidates_ready,
            "candidates_rejected": self._candidates_rejected,
            "candidates_trained": self._candidates_trained,
            "candidates_eval_failed": self._candidates_eval_failed,
            "metrics_empty_count": self._metrics_empty_count,
            "llm_calls_total": self._llm_calls_total,
            "rejection_reasons": self._rejection_reasons,
            "full_eval_total": self._full_eval_total,
            "full_eval_failed": self._full_eval_failed,
            "full_eval_failure_types": self._full_eval_failure_types,
            "eval_timeout_count": self._eval_timeout_count,
            "model_missing_count": self._model_missing_count,
            "metrics_parse_failed_count": self._metrics_parse_failed_count,
            "last_failed_eval_repro_command": self._last_failed_eval_repro_command,
            "last_failed_eval_stdout_path": self._last_failed_eval_stdout_path,
            "last_failed_eval_stderr_path": self._last_failed_eval_stderr_path,
            "event_log": "events.jsonl",
        }
        if extra:
            summary.update(extra)

        try:
            with open(self.summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def close(self, extra: dict[str, Any] | None = None) -> None:
        self._closed = True
        self.write_summary(extra)

    @property
    def is_active(self) -> bool:
        return not self._closed

    # Context manager support
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
