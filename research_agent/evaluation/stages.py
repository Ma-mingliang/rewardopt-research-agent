"""Data structures for staged evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StageName(str, Enum):
    STATIC_VALIDATION = "static_validation"
    STATIC_REPAIR = "static_repair"
    SMOKE_TRAIN = "smoke_train"
    RUNTIME_REPAIR = "runtime_repair"
    SHORT_TRAIN = "short_train"
    MEDIUM_TRAIN = "medium_train"
    FULL_EVAL = "full_eval"


class StageDecision(str, Enum):
    PASS = "pass"
    REPAIR = "repair"
    PROMOTE = "promote"
    DEFER = "defer"
    NEEDS_MORE_SEEDS = "needs_more_seeds"
    REJECT_CATASTROPHIC = "reject_catastrophic"
    REJECT_VALIDATION_FAILED = "reject_validation_failed"
    REJECT_RUNTIME_FAILED = "reject_runtime_failed"
    REJECT_POLICY_VIOLATION = "reject_policy_violation"
    REJECT_REPAIR_EXHAUSTED = "reject_repair_exhausted"
    INFRA_FAILED = "infra_failed"


class FailureClass(str, Enum):
    STATIC_SYNTAX = "static_syntax"
    STATIC_DIFF = "static_diff"
    RUNTIME_CODE = "runtime_code"
    RUNTIME_INFRA = "runtime_infra"
    RUNTIME_TIMEOUT = "runtime_timeout"
    TRAIN_CRASH = "train_crash"
    EVAL_FAILED = "eval_failed"
    UNKNOWN = "unknown"


@dataclass
class StageResult:
    stage: StageName
    decision: StageDecision
    failure_class: FailureClass = FailureClass.UNKNOWN
    repairable: bool = False
    attempt: int = 0
    max_attempts: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    next_stage: StageName | None = None
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "decision": self.decision.value,
            "failure_class": self.failure_class.value,
            "repairable": self.repairable,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "reason": self.reason,
            "duration_ms": self.duration_ms,
            "metrics": self.metrics,
            "diagnostics": self.diagnostics,
        }


@dataclass
class CandidateStagedResult:
    candidate_id: str
    final_decision: StageDecision
    stages: list[StageResult] = field(default_factory=list)
    repairs_attempted: int = 0
    static_repairs: int = 0
    runtime_repairs: int = 0
    promoted_to_full_eval: bool = False
    deferred: bool = False
    rejection_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "final_decision": self.final_decision.value,
            "stages": [s.to_dict() for s in self.stages],
            "repairs_attempted": self.repairs_attempted,
            "static_repairs": self.static_repairs,
            "runtime_repairs": self.runtime_repairs,
            "promoted_to_full_eval": self.promoted_to_full_eval,
            "deferred": self.deferred,
            "rejection_reason": self.rejection_reason,
        }
