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


def run_train(
    project_path: Path,
    config: AgentConfig,
    seed: int,
    extra_env: dict[str, str] | None = None,
    timeout_override: int | None = None,
) -> RunResult:
    """Run training command for a single seed.

    Args:
        project_path: Project root directory.
        config: Agent configuration.
        seed: Random seed.
        extra_env: Additional environment variables.
        timeout_override: Override timeout from config.

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

    timeout = timeout_override or config.execution.timeout_seconds_per_seed
    return _run_subprocess(project_path, formatted_command, timeout, extra_env)


def run_eval(
    project_path: Path,
    config: AgentConfig,
    seed: int,
    work_dir: Path | None = None,
    extra_env: dict[str, str] | None = None,
    timeout_override: int | None = None,
) -> RunResult:
    """Run evaluation command for a single seed and parse metrics.

    Args:
        project_path: Project root directory.
        config: Agent configuration.
        seed: Random seed.
        work_dir: .research-agent work dir for artifact lookup.
        extra_env: Additional environment variables.
        timeout_override: Override timeout from config.

    Returns:
        RunResult with parsed metrics.
    """
    command = config.execution.eval_command
    if not command:
        return RunResult(
            command="(empty)",
            return_code=1,
            stdout="",
            stderr="eval_command is not configured",
            duration_seconds=0.0,
        )

    formatted_command = command.replace("{seed}", str(seed))
    timeout = timeout_override or config.execution.timeout_seconds_per_seed

    result = _run_subprocess(project_path, formatted_command, timeout, extra_env)

    # Parse metrics from output
    metrics = parse_metrics(result.stdout, result.stderr, config, work_dir)

    return RunResult(
        command=result.command,
        return_code=result.return_code,
        stdout=result.stdout,
        stderr=result.stderr,
        duration_seconds=result.duration_seconds,
        metrics=metrics,
        timed_out=result.timed_out,
    )


def run_full_eval(
    project_path: Path,
    config: AgentConfig,
    seeds: list[int] | None = None,
    work_dir: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> list[RunResult]:
    """Run evaluation across multiple seeds.

    Args:
        project_path: Project root directory.
        config: Agent configuration.
        seeds: Seeds to evaluate (defaults to config.execution.full_eval_seeds).
        work_dir: .research-agent work dir for artifact lookup.
        extra_env: Additional environment variables.

    Returns:
        List of RunResult, one per seed.
    """
    if seeds is None:
        seeds = config.execution.full_eval_seeds

    results: list[RunResult] = []
    for seed in seeds:
        result = run_eval(project_path, config, seed, work_dir, extra_env)
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
) -> RunResult:
    """Run a command as subprocess and capture output."""
    import os

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
