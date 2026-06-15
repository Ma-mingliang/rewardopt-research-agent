"""Tests for staged evaluation data structures, classification, and config."""

from __future__ import annotations

import pytest

from research_agent.core.config import AgentConfig, StagedEvaluationConfig
from research_agent.evaluation.orchestrator import get_staged_config, should_use_staged_eval
from research_agent.evaluation.repair import classify_failure, is_infra_error
from research_agent.evaluation.stages import (
    CandidateStagedResult,
    FailureClass,
    StageDecision,
    StageName,
    StageResult,
)


class TestEnums:
    def test_stage_name_values(self):
        assert len(StageName) == 7
        assert StageName.STATIC_VALIDATION.value == "static_validation"
        assert StageName.FULL_EVAL.value == "full_eval"

    def test_stage_decision_values(self):
        assert len(StageDecision) == 11
        assert StageDecision.PASS.value == "pass"
        assert StageDecision.REJECT_CATASTROPHIC.value == "reject_catastrophic"
        assert StageDecision.INFRA_FAILED.value == "infra_failed"

    def test_failure_class_values(self):
        assert len(FailureClass) == 8
        assert FailureClass.RUNTIME_CODE.value == "runtime_code"
        assert FailureClass.RUNTIME_INFRA.value == "runtime_infra"


class TestStageResult:
    def test_to_dict_roundtrip(self):
        sr = StageResult(
            stage=StageName.SMOKE_TRAIN,
            decision=StageDecision.PASS,
            duration_ms=1234,
            reason="test reason",
        )
        d = sr.to_dict()
        assert d["stage"] == "smoke_train"
        assert d["decision"] == "pass"
        assert d["duration_ms"] == 1234
        assert d["reason"] == "test reason"
        assert d["failure_class"] == "unknown"
        assert d["repairable"] is False

    def test_to_dict_with_failure(self):
        sr = StageResult(
            stage=StageName.SMOKE_TRAIN,
            decision=StageDecision.REPAIR,
            failure_class=FailureClass.RUNTIME_CODE,
            repairable=True,
            attempt=2,
            max_attempts=3,
        )
        d = sr.to_dict()
        assert d["failure_class"] == "runtime_code"
        assert d["repairable"] is True
        assert d["attempt"] == 2


class TestCandidateStagedResult:
    def test_to_dict(self):
        csr = CandidateStagedResult(
            candidate_id="c1",
            final_decision=StageDecision.PROMOTE,
            stages=[
                StageResult(stage=StageName.SMOKE_TRAIN, decision=StageDecision.PASS),
            ],
            promoted_to_full_eval=True,
        )
        d = csr.to_dict()
        assert d["candidate_id"] == "c1"
        assert d["final_decision"] == "promote"
        assert len(d["stages"]) == 1
        assert d["promoted_to_full_eval"] is True
        assert d["deferred"] is False


class TestClassifyFailure:
    def test_code_error_nameerror(self):
        assert classify_failure("NameError: name 'x' is not defined") == FailureClass.RUNTIME_CODE

    def test_code_error_typeerror(self):
        assert classify_failure("TypeError: unsupported operand") == FailureClass.RUNTIME_CODE

    def test_code_error_reward(self):
        assert classify_failure("Error in __calculate_reward function") == FailureClass.RUNTIME_CODE

    def test_infra_cuda(self):
        assert classify_failure("CUDA out of memory") == FailureClass.RUNTIME_INFRA

    def test_infra_module_not_found(self):
        assert classify_failure("ModuleNotFoundError: No module named 'torch'") == FailureClass.RUNTIME_INFRA

    def test_infra_permission(self):
        assert classify_failure("PermissionError: [Errno 13] Permission denied") == FailureClass.RUNTIME_INFRA

    def test_timeout(self):
        assert classify_failure("Training timed out after 3600s") == FailureClass.RUNTIME_TIMEOUT

    def test_train_crash(self):
        assert classify_failure("Traceback (most recent call last):\n  File ...") == FailureClass.TRAIN_CRASH

    def test_unknown(self):
        assert classify_failure("Some random output with no errors") == FailureClass.UNKNOWN

    def test_empty_text(self):
        assert classify_failure("") == FailureClass.UNKNOWN

    def test_none_text(self):
        assert classify_failure(None) == FailureClass.UNKNOWN


class TestIsInfraError:
    def test_cuda_is_infra(self):
        assert is_infra_error("torch.cuda.OutOfMemoryError") is True

    def test_nameerror_not_infra(self):
        assert is_infra_error("NameError: x not defined") is False

    def test_module_not_found_is_infra(self):
        assert is_infra_error("No module named 'gym'") is True


class TestConfig:
    def test_staged_eval_disabled_by_default(self):
        cfg = StagedEvaluationConfig()
        assert cfg.enabled is False
        assert cfg.max_static_repair_attempts == 3
        assert cfg.max_runtime_repair_attempts == 2
        assert cfg.smoke_train_enabled is True
        assert cfg.short_train_enabled is False
        assert cfg.uncertainty_policy == "conservative"

    def test_agent_config_has_staged_evaluation(self):
        cfg = AgentConfig()
        assert hasattr(cfg, "staged_evaluation")
        assert cfg.staged_evaluation.enabled is False


class TestOrchestrator:
    def test_should_use_staged_eval_false_by_default(self):
        cfg = AgentConfig()
        assert should_use_staged_eval(cfg) is False

    def test_should_use_staged_eval_true_when_enabled(self):
        cfg = AgentConfig()
        cfg.staged_evaluation.enabled = True
        assert should_use_staged_eval(cfg) is True

    def test_get_staged_config_default(self):
        cfg = AgentConfig()
        sc = get_staged_config(cfg)
        assert sc["enabled"] is False
        assert sc["max_static_repair_attempts"] == 3

    def test_get_staged_config_enabled(self):
        cfg = AgentConfig()
        cfg.staged_evaluation.enabled = True
        cfg.staged_evaluation.short_train_enabled = True
        sc = get_staged_config(cfg)
        assert sc["enabled"] is True
        assert sc["short_train_enabled"] is True
