"""Executor: orchestrate experiment plan execution across phases."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_agent.core.config import AgentConfig
from research_agent.core.exceptions import BudgetExhaustedError, GuardViolationError
from research_agent.core.output import append_jsonl, ok_response, write_json_report
from research_agent.core.state import (
    advance_phase,
    read_state_json,
    write_state_json,
    acquire_lock,
    release_lock,
)
from research_agent.execution.experiment_runner import (
    RunResult,
    aggregate_metrics,
    run_eval,
    run_full_eval,
    run_train,
)
from research_agent.execution.metric_parser import check_safety_metrics


def run_plan(work_dir: Path, config: AgentConfig) -> dict:
    """Execute the full experiment plan phase by phase.

    Workflow per phase:
    1. Acquire lock
    2. Run baseline or optimizer experiments
    3. Evaluate and check safety
    4. Update state
    5. Release lock

    Args:
        work_dir: .research-agent work directory.
        config: Agent configuration.

    Returns:
        Response dict with execution results.
    """
    state = read_state_json(work_dir)
    plan = _load_plan(work_dir)
    if not plan:
        return _error_result("NO_PLAN", "No experiment plan found. Run 'plan-experiments' first.")

    phases = plan.get("phases", [])
    if not phases:
        return _error_result("NO_PHASES", "Experiment plan has no phases.")

    project_path = Path(state.get("project_path", ""))
    if not project_path.exists():
        return _error_result("PROJECT_NOT_FOUND", f"Project path not found: {project_path}")

    # Check budget
    budget = plan.get("global_budget", {})
    resource_usage = state.get("resource_usage", {
        "wall_clock_seconds": 0,
        "gpu_seconds": 0,
        "candidates_proposed": 0,
        "full_evals_run": 0,
    })

    # Execute phases in order
    phase_results: list[dict] = []
    for phase in phases:
        phase_id = phase.get("phase_id", "")

        # Skip already completed phases
        if phase.get("status") == "completed":
            phase_results.append({"phase_id": phase_id, "status": "skipped"})
            continue

        # Check budget before each phase
        if _is_budget_exhausted(resource_usage, budget, config):
            break

        result = _execute_phase(work_dir, config, phase, project_path, resource_usage)
        phase_results.append(result)

        # Update resource usage
        resource_usage["wall_clock_seconds"] += result.get("duration_seconds", 0)
        if result.get("status") == "completed":
            phase["status"] = "completed"

    # Write final state
    state = read_state_json(work_dir)
    state["resource_usage"] = resource_usage
    state["execution_results"] = phase_results

    # Determine final status
    all_completed = all(p.get("status") == "completed" for p in phases)
    budget_exhausted = _is_budget_exhausted(resource_usage, budget, config)

    # Transition through running_plan first
    current_phase = state.get("phase", "ideas_extracted")
    if current_phase in ("ideas_extracted", "literature_selected"):
        state = advance_phase(state, "running_plan")

    if budget_exhausted and not all_completed:
        state["stop_reason"] = "budget_exhausted"
        state = advance_phase(state, "budget_exhausted")
    elif all_completed:
        state = advance_phase(state, "completed")
    else:
        state["stop_reason"] = "partial"
        state = advance_phase(state, "completed")

    write_state_json(work_dir, state)

    # Write execution report
    _write_execution_report(work_dir, phase_results, resource_usage)

    return ok_response({
        "phases_executed": len([r for r in phase_results if r.get("status") != "skipped"]),
        "phases_completed": len([r for r in phase_results if r.get("status") == "completed"]),
        "resource_usage": resource_usage,
        "stop_reason": state.get("stop_reason", "completed"),
        "phase_results": phase_results,
        "report_path": "reports/execution_report.json",
    })


def run_phase(work_dir: Path, config: AgentConfig, phase_id: str) -> dict:
    """Execute a single phase by phase_id.

    Args:
        work_dir: .research-agent work directory.
        config: Agent configuration.
        phase_id: ID of the phase to execute.

    Returns:
        Response dict with phase execution result.
    """
    state = read_state_json(work_dir)
    plan = _load_plan(work_dir)
    if not plan:
        return _error_result("NO_PLAN", "No experiment plan found. Run 'plan-experiments' first.")

    phases = plan.get("phases", [])
    target_phase = None
    for phase in phases:
        if phase.get("phase_id") == phase_id:
            target_phase = phase
            break

    if target_phase is None:
        return _error_result("PHASE_NOT_FOUND", f"Phase '{phase_id}' not found in plan.")

    project_path = Path(state.get("project_path", ""))
    if not project_path.exists():
        return _error_result("PROJECT_NOT_FOUND", f"Project path not found: {project_path}")

    resource_usage = state.get("resource_usage", {
        "wall_clock_seconds": 0,
        "gpu_seconds": 0,
        "candidates_proposed": 0,
        "full_evals_run": 0,
    })

    result = _execute_phase(work_dir, config, target_phase, project_path, resource_usage)

    # Update state
    state = read_state_json(work_dir)
    state["resource_usage"] = resource_usage
    if result.get("status") == "completed":
        target_phase["status"] = "completed"
    write_state_json(work_dir, state)

    return ok_response(result)


def _execute_phase(
    work_dir: Path,
    config: AgentConfig,
    phase: dict,
    project_path: Path,
    resource_usage: dict,
) -> dict:
    """Execute a single experiment phase."""
    phase_id = phase.get("phase_id", "unknown")
    start_time = time.monotonic()

    # Acquire lock
    if not acquire_lock(work_dir, f"run-phase {phase_id}"):
        return {
            "phase_id": phase_id,
            "status": "locked",
            "error": "Another execution is in progress.",
        }

    try:
        if phase_id == "baseline":
            result = _execute_baseline(work_dir, config, phase, project_path)
        elif phase_id == "joint-validation":
            result = _execute_joint_validation(work_dir, config, phase, project_path)
        else:
            result = _execute_optimizer_phase(work_dir, config, phase, project_path, resource_usage)
    finally:
        release_lock(work_dir)

    result["duration_seconds"] = round(time.monotonic() - start_time, 2)

    # Log experiment
    log_path = work_dir / "logs" / "experiments.jsonl"
    append_jsonl(log_path, {
        "phase_id": phase_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **result,
    })

    return result


def _execute_baseline(
    work_dir: Path,
    config: AgentConfig,
    phase: dict,
    project_path: Path,
) -> dict:
    """Execute baseline phase: train + full eval to establish baseline metrics."""
    seeds = config.execution.full_eval_seeds

    # Train
    for seed in seeds:
        train_result = run_train(project_path, config, seed)
        if train_result.return_code != 0:
            return {
                "phase_id": "baseline",
                "status": "failed",
                "error": f"Training failed for seed {seed}",
                "stderr": train_result.stderr[:500],
            }

    # Evaluate
    eval_results = run_full_eval(project_path, config, seeds, work_dir)
    for r in eval_results:
        if r.return_code != 0:
            return {
                "phase_id": "baseline",
                "status": "failed",
                "error": f"Evaluation failed for seed {r.command}",
                "stderr": r.stderr[:500],
            }

    aggregated = aggregate_metrics(eval_results)

    # Save baseline
    baseline_path = work_dir / "artifacts" / "baseline_metrics.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    with open(baseline_path, "w", encoding="utf-8") as f:
        json.dump(aggregated, f, indent=2)

    # Update state with baseline
    state = read_state_json(work_dir)
    state["baseline_metrics"] = aggregated
    write_state_json(work_dir, state)

    return {
        "phase_id": "baseline",
        "status": "completed",
        "metrics": aggregated,
    }


def _execute_optimizer_phase(
    work_dir: Path,
    config: AgentConfig,
    phase: dict,
    project_path: Path,
    resource_usage: dict,
) -> dict:
    """Execute an optimizer phase.

    This is a placeholder that runs screening evals.
    The actual patch generation is handled by the front agent or optimizer modules.
    """
    phase_id = phase.get("phase_id", "unknown")
    optimizer = phase.get("optimizer", "unknown")
    budget = phase.get("budget", {})

    # Run screening eval on current state
    screening_seeds = config.execution.screening_seeds
    eval_results = run_full_eval(project_path, config, screening_seeds, work_dir)
    resource_usage["full_evals_run"] = resource_usage.get("full_evals_run", 0) + len(eval_results)

    for r in eval_results:
        if r.return_code != 0:
            return {
                "phase_id": phase_id,
                "status": "failed",
                "optimizer": optimizer,
                "error": f"Screening eval failed",
                "stderr": r.stderr[:500],
            }

    aggregated = aggregate_metrics(eval_results)

    # Check safety
    safety_result = check_safety_metrics(
        {k: v["mean"] for k, v in aggregated.items()},
        config,
    )

    return {
        "phase_id": phase_id,
        "status": "completed",
        "optimizer": optimizer,
        "screening_metrics": aggregated,
        "safety_check": safety_result,
    }


def _execute_joint_validation(
    work_dir: Path,
    config: AgentConfig,
    phase: dict,
    project_path: Path,
) -> dict:
    """Execute joint validation phase with confirmation seeds."""
    confirmation_seeds = config.execution.confirmation_seeds
    if not confirmation_seeds:
        confirmation_seeds = config.execution.full_eval_seeds

    eval_results = run_full_eval(project_path, config, confirmation_seeds, work_dir)

    for r in eval_results:
        if r.return_code != 0:
            return {
                "phase_id": "joint-validation",
                "status": "failed",
                "error": "Joint validation eval failed",
                "stderr": r.stderr[:500],
            }

    aggregated = aggregate_metrics(eval_results)

    # Check safety
    safety_result = check_safety_metrics(
        {k: v["mean"] for k, v in aggregated.items()},
        config,
    )

    # Compare with baseline
    state = read_state_json(work_dir)
    baseline = state.get("baseline_metrics", {})
    comparison = _compare_with_baseline(aggregated, baseline, config)

    return {
        "phase_id": "joint-validation",
        "status": "completed",
        "confirmation_metrics": aggregated,
        "safety_check": safety_result,
        "baseline_comparison": comparison,
    }


def _compare_with_baseline(
    current: dict[str, dict[str, float]],
    baseline: dict[str, dict[str, float]],
    config: AgentConfig,
) -> dict[str, Any]:
    """Compare current metrics with baseline."""
    comparison: dict[str, Any] = {}
    primary_metrics = config.metrics.primary

    for metric in primary_metrics:
        name = metric.get("name", "") if isinstance(metric, dict) else str(metric)
        direction = metric.get("direction", "maximize") if isinstance(metric, dict) else "maximize"

        current_val = current.get(name, {}).get("mean")
        baseline_val = baseline.get(name, {}).get("mean")

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


def _is_budget_exhausted(
    resource_usage: dict,
    budget: dict,
    config: AgentConfig,
) -> bool:
    """Check if budget is exhausted."""
    max_wall = budget.get("wall_clock_hours", config.budget.wall_clock_hours) * 3600
    max_candidates = budget.get("max_candidates", config.budget.max_candidates)
    max_evals = budget.get("max_full_evals", config.budget.max_full_evals)

    if resource_usage.get("wall_clock_seconds", 0) >= max_wall:
        return True
    if max_candidates and resource_usage.get("candidates_proposed", 0) >= max_candidates:
        return True
    if max_evals and resource_usage.get("full_evals_run", 0) >= max_evals:
        return True

    return False


def _load_plan(work_dir: Path) -> dict | None:
    """Load experiment plan from JSON."""
    path = work_dir / "reports" / "experiment_plan.json"
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("plan", data)
    except (json.JSONDecodeError, OSError):
        return None


def _write_execution_report(
    work_dir: Path,
    phase_results: list[dict],
    resource_usage: dict,
) -> None:
    """Write execution report to JSON."""
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phases": phase_results,
        "resource_usage": resource_usage,
    }
    write_json_report(work_dir / "reports" / "execution_report.json", report)


def _error_result(error_code: str, message: str) -> dict:
    """Create an error response dict."""
    return {
        "ok": False,
        "error": {
            "error_code": error_code,
            "message": message,
        },
    }
