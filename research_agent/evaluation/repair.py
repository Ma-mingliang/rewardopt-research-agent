"""Error classification and smoke train for staged evaluation."""

from __future__ import annotations

import time
from pathlib import Path

from research_agent.evaluation.stages import FailureClass, StageDecision, StageName, StageResult

INFRA_ERROR_PATTERNS = [
    "cuda out of memory",
    "torch.cuda.outofmemoryerror",
    "no module named",
    "modulenotfounderror",
    "filenotfounderror",
    "permissionerror",
    "python: command not found",
    "no such file or directory",
    "dll load failed",
    "importerror: libcudart",
]

CODE_ERROR_PATTERNS = [
    "attributeerror",
    "typeerror",
    "valueerror",
    "keyerror",
    "indexerror",
    "nameerror",
    "zerodivisionerror",
    "__calculate_reward",
    "reward",
]


def classify_failure(error_text: str) -> FailureClass:
    """Classify a runtime error from training output."""
    lower = (error_text or "").lower()
    for pat in INFRA_ERROR_PATTERNS:
        if pat in lower:
            return FailureClass.RUNTIME_INFRA
    for pat in CODE_ERROR_PATTERNS:
        if pat in lower:
            return FailureClass.RUNTIME_CODE
    if "timeout" in lower or "timed out" in lower:
        return FailureClass.RUNTIME_TIMEOUT
    if "traceback" in lower:
        return FailureClass.TRAIN_CRASH
    return FailureClass.UNKNOWN


def is_infra_error(error_text: str) -> bool:
    """Return True if the error is infrastructural (not code-fixable)."""
    return classify_failure(error_text) == FailureClass.RUNTIME_INFRA


def run_smoke_train(
    project_path: Path,
    config,
    seed: int,
    execution_python: str | None = None,
    smoke_max_steps: int | None = None,
) -> StageResult:
    """Run a very short training run for crash-only screening.

    Uses max_steps = min(500, config.execution.max_steps // 20) by default.
    Does NOT filter on performance -- only on crash/infra.
    Returns PASS if training completes (even with poor metrics).
    Returns REJECT_CATASTROPHIC only on infra failures.
    Returns REPAIR on code errors.
    """
    from research_agent.execution.experiment_runner import run_train

    max_steps = smoke_max_steps or min(500, config.execution.max_steps // 20)
    t0 = time.monotonic()

    result = run_train(
        project_path,
        config,
        seed,
        max_steps_override=max_steps,
        python_executable=execution_python,
    )

    duration_ms = int((time.monotonic() - t0) * 1000)

    if result.return_code == 0:
        return StageResult(
            stage=StageName.SMOKE_TRAIN,
            decision=StageDecision.PASS,
            duration_ms=duration_ms,
            reason=f"smoke_train completed ({max_steps} steps, {result.duration_seconds:.1f}s)",
        )

    error_text = (result.stderr or "") + "\n" + (result.stdout or "")
    failure_class = classify_failure(error_text)

    if failure_class == FailureClass.RUNTIME_INFRA:
        return StageResult(
            stage=StageName.SMOKE_TRAIN,
            decision=StageDecision.INFRA_FAILED,
            failure_class=failure_class,
            repairable=False,
            duration_ms=duration_ms,
            reason=f"infra failure in smoke_train: {error_text[-300:]}",
        )

    if failure_class == FailureClass.RUNTIME_TIMEOUT:
        return StageResult(
            stage=StageName.SMOKE_TRAIN,
            decision=StageDecision.REPAIR,
            failure_class=failure_class,
            repairable=False,
            duration_ms=duration_ms,
            reason=f"smoke_train timeout ({max_steps} steps)",
        )

    # Code error — repairable
    return StageResult(
        stage=StageName.SMOKE_TRAIN,
        decision=StageDecision.REPAIR,
        failure_class=failure_class,
        repairable=True,
        duration_ms=duration_ms,
        reason=f"smoke_train code error: {error_text[-300:]}",
    )
