"""Base optimizer interface for all optimizer plugins."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_agent.core.config import AgentConfig
from research_agent.core.llm_client import LLMClient
from research_agent.core.output import append_jsonl
from research_agent.execution.experiment_runner import RunResult, aggregate_metrics, run_eval, run_full_eval


def normalize_allowed_changes(allowed: list) -> list[dict]:
    """Normalize allowed_changes to list[dict] format.

    Handles both string format ('env.py') and dict format ({file: 'env.py', line_range: ...}).
    """
    result = []
    for item in allowed:
        if isinstance(item, str):
            result.append({"file": item, "line_range": None})
        elif isinstance(item, dict):
            result.append(item)
    return result


class Candidate:
    """Represents a proposed code change candidate."""

    def __init__(
        self,
        candidate_id: str,
        optimizer: str,
        description: str,
        patch_diff: str,
        allowed_changes: list[dict],
        source_idea: str = "",
    ):
        self.candidate_id = candidate_id
        self.optimizer = optimizer
        self.description = description
        self.patch_diff = patch_diff
        self.allowed_changes = allowed_changes
        self.source_idea = source_idea
        self.full_eval_result: dict | None = None
        self.status = "proposed"  # proposed -> accepted/rejected
        self.rejection_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "optimizer": self.optimizer,
            "description": self.description,
            "patch_diff": self.patch_diff[:500],
            "source_idea": self.source_idea,
            "status": self.status,
            "full_eval_result": self.full_eval_result,
            "rejection_reason": self.rejection_reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class BaseOptimizer(ABC):
    """Base class for all optimizer plugins."""

    name: str = "base"

    def __init__(
        self,
        work_dir: Path,
        config: AgentConfig,
        project_path: Path,
        mock_llm: bool = False,
    ):
        self.work_dir = work_dir
        self.config = config
        self.project_path = project_path
        self._mock_llm = mock_llm
        self._llm_client: LLMClient | None = None
        self._candidate_counter = 0

    @property
    def llm_client(self) -> LLMClient | None:
        if self._mock_llm:
            return None
        if self._llm_client is None:
            try:
                self._llm_client = LLMClient(
                    self.config.llm.model_dump(),
                    log_path=self.work_dir / "logs" / "llm_calls.jsonl",
                )
            except Exception:
                pass
        return self._llm_client

    def next_candidate_id(self) -> str:
        self._candidate_counter += 1
        return f"{self.name}_c{self._candidate_counter:03d}"

    @abstractmethod
    def propose_candidate(
        self,
        phase: dict,
        baseline_metrics: dict[str, dict[str, float]],
        ideas: list[dict] | None = None,
    ) -> Candidate:
        """Propose a new candidate patch.

        Args:
            phase: Experiment plan phase dict.
            baseline_metrics: Aggregated baseline metrics.
            ideas: Optional extracted ideas to draw from.

        Returns:
            Candidate with patch_diff.
        """
        ...

    def full_eval_candidate(
        self,
        candidate: Candidate,
        config: AgentConfig | None = None,
        checkpoint_dir: Path | None = None,
    ) -> Candidate:
        """Full eval on all seeds.

        Args:
            candidate: Candidate to evaluate.
            config: Override config.
            checkpoint_dir: Directory to save best model checkpoint.

        Returns:
            Candidate with full_eval_result populated.
        """
        cfg = config or self.config
        seeds = cfg.execution.full_eval_seeds

        results = run_full_eval(self.project_path, cfg, seeds, self.work_dir,
                                checkpoint_dir=checkpoint_dir)
        aggregated = aggregate_metrics(results)

        has_failure = any(r.return_code != 0 for r in results)
        candidate.full_eval_result = {
            "metrics": aggregated,
            "failed": has_failure,
            "seeds": seeds,
        }

        if has_failure:
            candidate.status = "rejected"
            candidate.rejection_reason = "Full eval failed"
        else:
            candidate.status = "evaluated"

        self._log_candidate(candidate)
        return candidate

    def compare_with_baseline(
        self,
        candidate: Candidate,
        baseline_metrics: dict[str, dict[str, float]],
    ) -> dict[str, Any]:
        """Compare candidate metrics with baseline.

        Returns:
            Dict with comparison results per metric.
        """
        if not candidate.full_eval_result:
            return {"error": "No full eval result"}

        current = candidate.full_eval_result.get("metrics", {})
        primary_metrics = self.config.metrics.primary
        comparison: dict[str, Any] = {}

        for metric in primary_metrics:
            name = metric.get("name", "") if isinstance(metric, dict) else str(metric)
            direction = metric.get("direction", "maximize") if isinstance(metric, dict) else "maximize"

            current_val = current.get(name, {}).get("mean")
            baseline_val = baseline_metrics.get(name, {}).get("mean")

            if current_val is None or baseline_val is None:
                comparison[name] = {"status": "missing_data"}
                continue

            if baseline_val == 0:
                pct_change = 0.0
            elif direction == "maximize":
                pct_change = (current_val - baseline_val) / abs(baseline_val)
            else:
                pct_change = (baseline_val - current_val) / abs(baseline_val)

            comparison[name] = {
                "current": current_val,
                "baseline": baseline_val,
                "pct_change": round(pct_change * 100, 4),
                "improved": pct_change > 0,
            }

        return comparison

    def accept_or_reject(
        self,
        candidate: Candidate,
        baseline_metrics: dict[str, dict[str, float]],
    ) -> bool:
        """Decide whether to accept or reject a candidate.

        Returns:
            True if accepted, False if rejected.
        """
        comparison = self.compare_with_baseline(candidate, baseline_metrics)

        primary_metrics = self.config.metrics.primary
        min_improvement = self.config.metrics.metric_thresholds.default_min_improvement_pct
        max_regression = self.config.metrics.metric_thresholds.default_max_regression_pct

        for metric in primary_metrics:
            name = metric.get("name", "") if isinstance(metric, dict) else str(metric)
            comp = comparison.get(name, {})

            if comp.get("status") == "missing_data":
                continue

            pct = comp.get("pct_change", 0)

            # Check hard regression on primary score
            if metric.get("hard_min") is not None:
                current = comp.get("current", 0)
                if current < metric["hard_min"]:
                    candidate.status = "rejected"
                    candidate.rejection_reason = f"{name} below hard_min: {current} < {metric['hard_min']}"
                    self._log_candidate(candidate)
                    return False

            # Check regression threshold
            if pct < -max_regression * 100:
                candidate.status = "rejected"
                candidate.rejection_reason = f"{name} regressed {pct:.2f}% (max: -{max_regression*100}%)"
                self._log_candidate(candidate)
                return False

        # Check if at least one primary metric improved
        any_improved = any(
            comparison.get(m.get("name", m) if isinstance(m, dict) else m, {}).get("improved", False)
            for m in primary_metrics
        )

        if any_improved:
            candidate.status = "accepted"
            self._log_candidate(candidate)
            return True
        else:
            candidate.status = "rejected"
            candidate.rejection_reason = "No primary metric improved"
            self._log_candidate(candidate)
            return False

    def _log_candidate(self, candidate: Candidate) -> None:
        log_path = self.work_dir / "logs" / "candidates.jsonl"
        append_jsonl(log_path, candidate.to_dict())
