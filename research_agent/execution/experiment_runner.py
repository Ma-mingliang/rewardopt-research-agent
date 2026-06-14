"""Experiment runner: execute train/eval commands as subprocesses."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_agent.core.config import AgentConfig
from research_agent.execution.metric_parser import parse_metrics


@dataclass(frozen=True)
class RunResult:
    """Result of a single train/eval run."""
    command: str
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    metrics: dict[str, float | None] = field(default_factory=dict)
    timed_out: bool = False
    diagnostics: dict[str, Any] | None = None


def run_train(
    project_path: Path,
    config: AgentConfig,
    seed: int,
    extra_env: dict[str, str] | None = None,
    timeout_override: int | None = None,
    checkpoint_dir: Path | None = None,
    python_executable: str | None = None,
) -> RunResult:
    """Run training command for a single seed.

    Args:
        project_path: Project root directory.
        config: Agent configuration.
        seed: Random seed.
        extra_env: Additional environment variables.
        timeout_override: Override timeout from config.
        checkpoint_dir: Directory to save best model checkpoint.

    Returns:
        RunResult with stdout, stderr, metrics, and timing.
    """
    command = config.execution.train_command
    if not command:
        return RunResult(
            command="(empty)",
            return_code=1,
            stdout="",
            stderr="train_command is not configured",
            duration_seconds=0.0,
        )

    # Format command with seed
    formatted_command = command.replace("{seed}", str(seed))

    # Pass checkpoint_dir via environment variable
    env = dict(extra_env) if extra_env else {}
    if checkpoint_dir:
        env["RA_CHECKPOINT_DIR"] = str(checkpoint_dir)

    timeout = timeout_override or config.execution.timeout_seconds_per_seed
    return _run_subprocess(project_path, formatted_command, timeout, env or None,
                           python_executable=python_executable)


def run_eval(
    project_path: Path,
    config: AgentConfig,
    seed: int,
    work_dir: Path | None = None,
    extra_env: dict[str, str] | None = None,
    timeout_override: int | None = None,
    python_executable: str | None = None,
    observer: Any | None = None,
    candidate_id: str = "",
) -> RunResult:
    """Run evaluation command for a single seed and parse metrics.

    Args:
        project_path: Project root directory.
        config: Agent configuration.
        seed: Random seed.
        work_dir: .research-agent work dir for artifact lookup.
        extra_env: Additional environment variables.
        timeout_override: Override timeout from config.
        python_executable: Python executable for subprocess.
        observer: Optional RunObserver for diagnostics.
        candidate_id: Candidate ID for diagnostic file naming.

    Returns:
        RunResult with parsed metrics and diagnostics.
    """
    command = config.execution.eval_command
    if not command:
        diag = _build_diagnostic(
            candidate_id=candidate_id, stage="eval",
            failure_type="subprocess_failed", failed=True,
            returncode=1, command="(empty)", resolved_command="(empty)",
            execution_python=python_executable or "",
            cwd=str(project_path), error_message="eval_command is not configured",
            diagnostic_summary="eval_command is not configured",
        )
        return RunResult(
            command="(empty)",
            return_code=1,
            stdout="",
            stderr="eval_command is not configured",
            duration_seconds=0.0,
            diagnostics=diag,
        )

    formatted_command = command.replace("{seed}", str(seed))
    timeout = timeout_override or config.execution.timeout_seconds_per_seed

    result = _run_subprocess(project_path, formatted_command, timeout, extra_env,
                              python_executable=python_executable)

    # Parse metrics from output
    metrics_parser_ok = True
    metrics_parser_error = ""
    try:
        metrics = parse_metrics(result.stdout, result.stderr, config, work_dir)
    except Exception as e:
        metrics_parser_ok = False
        metrics_parser_error = str(e)[:500]
        metrics = {}

    # Build diagnostics
    from research_agent.core.eval_diagnostics import EvalFailureType, classify_eval_failure
    failure_type = classify_eval_failure(
        returncode=result.return_code,
        timed_out=result.timed_out,
        stdout=result.stdout,
        stderr=result.stderr,
        metrics=metrics,
        metrics_parser_ok=metrics_parser_ok,
        metrics_parser_error=metrics_parser_error,
        execution_python_exists=bool(python_executable and Path(python_executable).exists()),
    )

    # Save stdout/stderr if observer available
    stdout_path = ""
    stderr_path = ""
    if observer and observer.is_active and candidate_id:
        run_dir = observer.run_dir
        stdout_path = str(run_dir / f"{candidate_id}_eval_stdout.txt")
        stderr_path = str(run_dir / f"{candidate_id}_eval_stderr.txt")
        try:
            if result.stdout:
                Path(stdout_path).write_text(result.stdout[:50000], encoding="utf-8")
            if result.stderr:
                Path(stderr_path).write_text(result.stderr[:50000], encoding="utf-8")
        except Exception:
            pass

    diag = _build_diagnostic(
        candidate_id=candidate_id, stage="eval",
        failure_type=failure_type.value,
        failed=failure_type != EvalFailureType.NONE,
        returncode=result.return_code,
        command=command,
        resolved_command=result.command,
        execution_python=python_executable or "",
        cwd=str(project_path),
        duration_ms=int(result.duration_seconds * 1000),
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        stdout_tail=result.stdout[-1000:] if result.stdout else "",
        stderr_tail=result.stderr[-1000:] if result.stderr else "",
        metrics_keys=list(metrics.keys()),
        metrics_empty=not bool(metrics),
        metrics_parser_ok=metrics_parser_ok,
        metrics_parser_error=metrics_parser_error,
        env_path=str(project_path / "env.py"),
        env_eval_hash="",  # computed by caller if needed
        error_message=result.stderr[:500] if result.return_code != 0 else "",
        diagnostic_summary=_summarize_failure(failure_type, result.return_code, metrics),
    )

    # Emit diagnostic events via observer
    if observer and observer.is_active:
        observer.emit("metrics_parse_end",
                      candidate_id=candidate_id,
                      metrics_parser_ok=metrics_parser_ok,
                      metrics_keys=list(metrics.keys()),
                      metrics_empty=not bool(metrics))
        if failure_type == EvalFailureType.METRICS_EMPTY:
            observer.emit("metrics_empty", candidate_id=candidate_id,
                          stdout_path=stdout_path, stderr_path=stderr_path)

    return RunResult(
        command=result.command,
        return_code=result.return_code,
        stdout=result.stdout,
        stderr=result.stderr,
        duration_seconds=result.duration_seconds,
        metrics=metrics,
        timed_out=result.timed_out,
        diagnostics=diag,
    )


def run_full_eval(
    project_path: Path,
    config: AgentConfig,
    seeds: list[int] | None = None,
    work_dir: Path | None = None,
    extra_env: dict[str, str] | None = None,
    checkpoint_dir: Path | None = None,
    python_executable: str | None = None,
    observer: Any | None = None,
    candidate_id: str = "",
) -> list[RunResult]:
    """Run evaluation across multiple seeds.

    Args:
        project_path: Project root directory.
        config: Agent configuration.
        seeds: Seeds to evaluate (defaults to config.execution.full_eval_seeds).
        work_dir: .research-agent work dir for artifact lookup.
        extra_env: Additional environment variables.
        checkpoint_dir: Directory to save best model checkpoint.
        python_executable: Python executable for subprocess.
        observer: Optional RunObserver for diagnostics.
        candidate_id: Candidate ID for diagnostic file naming.

    Returns:
        List of RunResult, one per seed.
    """
    if seeds is None:
        seeds = config.execution.full_eval_seeds

    # Pass checkpoint_dir via environment
    env = dict(extra_env) if extra_env else {}
    if checkpoint_dir:
        env["RA_CHECKPOINT_DIR"] = str(checkpoint_dir)

    results: list[RunResult] = []
    for seed in seeds:
        result = run_eval(project_path, config, seed, work_dir, env or None,
                          python_executable=python_executable,
                          observer=observer, candidate_id=candidate_id)
        results.append(result)

    return results


def aggregate_metrics(results: list[RunResult]) -> dict[str, dict[str, float]]:
    """Aggregate metrics across multiple seed runs.

    Returns:
        Dict mapping metric names to {mean, std, min, max, values}.
    """
    if not results:
        return {}

    # Collect all metric names
    all_metric_names: set[str] = set()
    for r in results:
        all_metric_names.update(k for k, v in r.metrics.items() if v is not None)

    aggregated: dict[str, dict[str, float]] = {}
    for name in sorted(all_metric_names):
        values = [r.metrics[name] for r in results if r.metrics.get(name) is not None]
        if not values:
            continue

        mean = sum(values) / len(values)
        if len(values) > 1:
            variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
            std = variance ** 0.5
        else:
            std = 0.0

        aggregated[name] = {
            "mean": round(mean, 6),
            "std": round(std, 6),
            "min": round(min(values), 6),
            "max": round(max(values), 6),
            "n": len(values),
            "values": [round(v, 6) for v in values],
        }

    return aggregated


def _run_subprocess(
    project_path: Path,
    command: str,
    timeout: int,
    extra_env: dict[str, str] | None,
    python_executable: str | None = None,
) -> RunResult:
    """Run a command as subprocess and capture output.

    If python_executable is provided, resolves {python} placeholder in command
    or prepends the executable to commands starting with 'python'.
    """
    import os

    # Resolve execution Python in command
    if python_executable:
        if "{python}" in command:
            command = command.replace("{python}", python_executable)
        else:
            stripped = command.strip()
            for prefix in ("python3 ", "python "):
                if stripped.startswith(prefix):
                    command = python_executable + stripped[len(prefix) - 1:]
                    break

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    start = time.monotonic()
    timed_out = False

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return_code = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired as e:
        timed_out = True
        return_code = -1
        stdout = e.stdout or ""
        stderr = e.stderr or ""
    except Exception as e:
        return_code = -1
        stdout = ""
        stderr = str(e)

    duration = time.monotonic() - start

    return RunResult(
        command=command,
        return_code=return_code,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=round(duration, 2),
        timed_out=timed_out,
    )


def _build_diagnostic(
    candidate_id: str = "",
    stage: str = "eval",
    failure_type: str = "none",
    failed: bool = False,
    returncode: int = 0,
    command: str = "",
    resolved_command: str = "",
    execution_python: str = "",
    cwd: str = "",
    duration_ms: int = 0,
    stdout_path: str = "",
    stderr_path: str = "",
    stdout_tail: str = "",
    stderr_tail: str = "",
    metrics_keys: list[str] | None = None,
    metrics_empty: bool = False,
    metrics_parser_ok: bool = True,
    metrics_parser_error: str = "",
    env_path: str = "",
    env_eval_hash: str = "",
    error_message: str = "",
    diagnostic_summary: str = "",
) -> dict[str, Any]:
    """Build a diagnostic dict for a single eval run."""
    from research_agent.core.eval_diagnostics import build_repro_command, hash_file

    repro = build_repro_command(
        execution_python=execution_python,
        eval_command=command,
        cwd=cwd,
        candidate_id=candidate_id,
    )

    env_hash = env_eval_hash or hash_file(env_path) if env_path else ""

    return {
        "candidate_id": candidate_id,
        "stage": stage,
        "failure_type": failure_type,
        "failed": failed,
        "returncode": returncode,
        "command": command,
        "resolved_command": resolved_command,
        "repro_command": repro,
        "execution_python": execution_python,
        "cwd": cwd,
        "duration_ms": duration_ms,
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "metrics_keys": metrics_keys or [],
        "metrics_empty": metrics_empty,
        "metrics_parser_ok": metrics_parser_ok,
        "metrics_parser_error": metrics_parser_error,
        "env_path": env_path,
        "env_hash": env_hash,
        "error_message": error_message,
        "diagnostic_summary": diagnostic_summary,
    }


def _summarize_failure(failure_type, returncode: int, metrics: dict) -> str:
    """Generate a human-readable summary of the failure."""
    from research_agent.core.eval_diagnostics import EvalFailureType

    if failure_type == EvalFailureType.NONE:
        return "Evaluation completed successfully"
    if failure_type == EvalFailureType.METRICS_EMPTY:
        return "evaluate.py completed (returncode=0) but no parseable metrics were found in stdout"
    if failure_type == EvalFailureType.METRICS_PARSE_FAILED:
        return "Metrics parser threw an exception while processing eval output"
    if failure_type == EvalFailureType.METRICS_FILE_MISSING:
        return "Metrics output file was not created by evaluate.py"
    if failure_type == EvalFailureType.EVAL_SCRIPT_CRASHED:
        return f"evaluate.py crashed with returncode={returncode}"
    if failure_type == EvalFailureType.EVAL_TIMEOUT:
        return "evaluate.py timed out"
    if failure_type == EvalFailureType.MODEL_MISSING:
        return "Model file does not exist at expected path"
    if failure_type == EvalFailureType.MODEL_LOAD_FAILED:
        return "Model file exists but could not be loaded"
    if failure_type == EvalFailureType.ENV_IMPORT_FAILED:
        return "env.py could not be imported or compiled"
    if failure_type == EvalFailureType.EXECUTION_PYTHON_MISSING:
        return "execution_python executable does not exist"
    if failure_type == EvalFailureType.SUBPROCESS_FAILED:
        return f"Subprocess failed with returncode={returncode}"
    return f"Unknown failure type: {failure_type}"
