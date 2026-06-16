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

        # Method pool counters
        self._method_pool_total = 0
        self._method_pool_selected = 0
        self._method_pool_categories_used: list[str] = []

        # Staged evaluation counters
        self._staged_eval_enabled = False
        self._staged_static_repairs = 0
        self._staged_runtime_repairs = 0
        self._staged_smoke_rejected = 0
        self._staged_infra_failures = 0
        self._staged_short_train_promoted = 0
        self._staged_short_train_deferred = 0
        self._staged_medium_train_promoted = 0
        self._staged_total_stages_run = 0

        # Baseline guard counters
        self._baseline_guard_run = False
        self._baseline_guard_passed = False
        self._baseline_guard_failed = False
        self._baseline_guard_drift_type: str | None = None
        self._baseline_guard_manifest_path: str | None = None

        # Patch repair tracking
        self._patch_repair_attempts_total: int = 0
        self._patch_repair_exhausted_count: int = 0
        self._repeated_patch_repair_error_count: int = 0
        self._syntax_repair_success_count: int = 0
        self._max_patch_apply_repair_attempts: int = 6
        self._max_same_error_repair_attempts: int = 2
        self._repair_strategy_counts: dict[str, int] = {}
        self._last_patch_repair_error_signature: str | None = None

        # Context-grounded proposal tracking (v0.7.3)
        self._context_grounded_proposal_enabled: bool = False
        self._proposal_context_file: str | None = None
        self._proposal_context_function: str | None = None
        self._proposal_context_start_line: int = 0
        self._proposal_context_end_line: int = 0
        self._initial_patch_self_check_passed: int = 0
        self._initial_patch_self_check_failure_reason: str | None = None
        self._initial_patch_line_count: int = 0
        self._initial_patch_modified_files: int = 0
        self._initial_patch_too_large_count: int = 0
        self._initial_patch_outside_allowed_context_count: int = 0

        # Candidate diversity tracking (v0.8)
        self._candidate_diversity_enabled: bool = True
        self._candidate_pair_similarity_max: float = 0.0
        self._duplicate_patch_count: int = 0
        self._duplicate_method_count: int = 0
        self._low_diversity_candidate_count: int = 0
        self._method_selection_fallback_count: int = 0
        self._previous_candidate_diffs: list[str] = []
        self._previous_method_ids: list[str] = []

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

    def track_method_pool_usage(
        self,
        total_available: int,
        selected_count: int,
        categories_used: list[str],
    ) -> None:
        """Track method pool usage for summary."""
        self._method_pool_total = total_available
        self._method_pool_selected = selected_count
        self._method_pool_categories_used = categories_used

    def track_staged_eval_enabled(self) -> None:
        """Mark staged evaluation as enabled for this run."""
        self._staged_eval_enabled = True

    def track_staged_stage(self, decision: str) -> None:
        """Track a staged evaluation stage completion."""
        self._staged_total_stages_run += 1
        if decision == "repair":
            self._staged_static_repairs += 1
        elif decision == "reject_catastrophic":
            self._staged_smoke_rejected += 1
        elif decision == "infra_failed":
            self._staged_infra_failures += 1
        elif decision == "promote":
            self._staged_short_train_promoted += 1
        elif decision == "defer":
            self._staged_short_train_deferred += 1

    def track_staged_runtime_repair(self) -> None:
        """Track a runtime repair attempt."""
        self._staged_runtime_repairs += 1

    def track_baseline_guard(
        self,
        passed: bool,
        drift_type: str = "none",
        manifest_path: str = "",
    ) -> None:
        """Track baseline guard result for summary."""
        self._baseline_guard_run = True
        self._baseline_guard_passed = passed
        self._baseline_guard_failed = not passed
        self._baseline_guard_drift_type = drift_type if not passed else None
        self._baseline_guard_manifest_path = manifest_path or None

    def track_patch_repair(
        self,
        attempts: int = 0,
        exhausted: bool = False,
        repeated_error: bool = False,
        success: bool = False,
        strategy: str = "",
        error_signature: str = "",
        max_attempts: int = 6,
        max_same_error: int = 2,
    ) -> None:
        """Track patch repair attempt for summary."""
        self._patch_repair_attempts_total += attempts
        if exhausted:
            self._patch_repair_exhausted_count += 1
        if repeated_error:
            self._repeated_patch_repair_error_count += 1
        if success:
            self._syntax_repair_success_count += 1
        if strategy:
            self._repair_strategy_counts[strategy] = self._repair_strategy_counts.get(strategy, 0) + 1
        if error_signature:
            self._last_patch_repair_error_signature = error_signature
        self._max_patch_apply_repair_attempts = max_attempts
        self._max_same_error_repair_attempts = max_same_error

    def track_context_grounded_proposal(
        self,
        enabled: bool = False,
        file: str = "",
        function: str = "",
        start_line: int = 0,
        end_line: int = 0,
        self_check_passed: bool = False,
        self_check_failure_reason: str = "",
        patch_line_count: int = 0,
        too_large: bool = False,
        outside_context: bool = False,
    ) -> None:
        """Track context-grounded proposal for summary."""
        if enabled:
            self._context_grounded_proposal_enabled = True
        if file:
            self._proposal_context_file = file
        if function:
            self._proposal_context_function = function
        if start_line:
            self._proposal_context_start_line = start_line
        if end_line:
            self._proposal_context_end_line = end_line
        if self_check_passed:
            self._initial_patch_self_check_passed += 1
        if self_check_failure_reason:
            self._initial_patch_self_check_failure_reason = self_check_failure_reason
        if patch_line_count:
            self._initial_patch_line_count = patch_line_count
        if too_large:
            self._initial_patch_too_large_count += 1
        if outside_context:
            self._initial_patch_outside_allowed_context_count += 1

    def track_candidate_diversity(
        self,
        current_diff: str = "",
        current_method_ids: list[str] | None = None,
        similarity_score: float = 0.0,
        is_duplicate_patch: bool = False,
        is_duplicate_method: bool = False,
        is_low_diversity: bool = False,
        method_selection_fallback: bool = False,
    ) -> None:
        """Track candidate diversity for summary."""
        self._candidate_diversity_enabled = True
        if similarity_score > self._candidate_pair_similarity_max:
            self._candidate_pair_similarity_max = similarity_score
        if is_duplicate_patch:
            self._duplicate_patch_count += 1
        if is_duplicate_method:
            self._duplicate_method_count += 1
        if is_low_diversity:
            self._low_diversity_candidate_count += 1
        if method_selection_fallback:
            self._method_selection_fallback_count += 1
        if current_diff:
            self._previous_candidate_diffs.append(current_diff)
        if current_method_ids:
            self._previous_method_ids.extend(current_method_ids)

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
            "method_pool_total": self._method_pool_total,
            "method_pool_selected": self._method_pool_selected,
            "method_pool_categories_used": self._method_pool_categories_used,
            "staged_eval_enabled": self._staged_eval_enabled,
            "staged_total_stages_run": self._staged_total_stages_run,
            "staged_static_repairs": self._staged_static_repairs,
            "staged_runtime_repairs": self._staged_runtime_repairs,
            "staged_smoke_rejected": self._staged_smoke_rejected,
            "staged_infra_failures": self._staged_infra_failures,
            "staged_short_train_promoted": self._staged_short_train_promoted,
            "staged_short_train_deferred": self._staged_short_train_deferred,
            "baseline_guard_run": self._baseline_guard_run,
            "baseline_guard_passed": self._baseline_guard_passed,
            "baseline_guard_failed": self._baseline_guard_failed,
            "baseline_guard_drift_type": self._baseline_guard_drift_type,
            "baseline_guard_manifest_path": self._baseline_guard_manifest_path,
            "patch_repair_attempts_total": self._patch_repair_attempts_total,
            "patch_repair_exhausted_count": self._patch_repair_exhausted_count,
            "repeated_patch_repair_error_count": self._repeated_patch_repair_error_count,
            "syntax_repair_success_count": self._syntax_repair_success_count,
            "max_patch_apply_repair_attempts": self._max_patch_apply_repair_attempts,
            "max_same_error_repair_attempts": self._max_same_error_repair_attempts,
            "repair_strategy_counts": dict(self._repair_strategy_counts),
            "last_patch_repair_error_signature": self._last_patch_repair_error_signature,
            "context_grounded_proposal_enabled": self._context_grounded_proposal_enabled,
            "proposal_context_file": self._proposal_context_file,
            "proposal_context_function": self._proposal_context_function,
            "proposal_context_start_line": self._proposal_context_start_line,
            "proposal_context_end_line": self._proposal_context_end_line,
            "initial_patch_self_check_passed": self._initial_patch_self_check_passed,
            "initial_patch_self_check_failure_reason": self._initial_patch_self_check_failure_reason,
            "initial_patch_line_count": self._initial_patch_line_count,
            "initial_patch_too_large_count": self._initial_patch_too_large_count,
            "initial_patch_outside_allowed_context_count": self._initial_patch_outside_allowed_context_count,
            "candidate_diversity_enabled": self._candidate_diversity_enabled,
            "candidate_pair_similarity_max": round(self._candidate_pair_similarity_max, 4),
            "duplicate_patch_count": self._duplicate_patch_count,
            "duplicate_method_count": self._duplicate_method_count,
            "low_diversity_candidate_count": self._low_diversity_candidate_count,
            "method_selection_fallback_count": self._method_selection_fallback_count,
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
