"""Executor: orchestrate experiment plan execution across phases."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_agent.core.config import AgentConfig
from research_agent.core.exceptions import BudgetExhaustedError, GuardViolationError, PatchApplyError
from research_agent.core.git_guard import git_guard_pre_run, git_guard_post_run
from research_agent.core.output import append_jsonl, ok_response, write_json_report
from research_agent.core.patch_manager import PatchManager
from research_agent.core.state import (
    add_applied_patch,
    advance_phase,
    read_state_json,
    remove_applied_patch,
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


def run_plan(work_dir: Path, config: AgentConfig, mock_llm: bool = False) -> dict:
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
        mock_llm: If True, optimizer skips LLM calls.

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

    # Git guard pre-run: snapshot before experiments
    git_guard_pre_run(project_path, work_dir)

    # Check budget
    budget = plan.get("global_budget", {})
    resource_usage = state.get("resource_usage", {
        "wall_clock_seconds": 0,
        "gpu_seconds": 0,
        "candidates_proposed": 0,
        "full_evals_run": 0,
    })

    # Load extracted ideas for optimizers (fallback)
    ideas = _load_ideas(work_dir)

    # Initialize paper sampler for iterative method selection
    sampler = _init_sampler(work_dir)

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

        result = _execute_phase(work_dir, config, phase, project_path, resource_usage, ideas, sampler, mock_llm)
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
    _can_enter_running_plan = {
        "ideas_extracted", "literature_selected",
        "literature_classified", "literature_searched", "planned",
    }
    if current_phase in _can_enter_running_plan:
        # Force phase to ideas_extracted if pipeline is incomplete
        if current_phase != "ideas_extracted":
            state["phase"] = "ideas_extracted"
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

    # Git guard post-run
    accepted = any(
        (r.get("best_candidate") or {}).get("status") == "accepted"
        for r in phase_results
    )
    git_guard_post_run(project_path, work_dir, accepted)

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


def run_phase(work_dir: Path, config: AgentConfig, phase_id: str, mock_llm: bool = False) -> dict:
    """Execute a single phase by phase_id.

    Args:
        work_dir: .research-agent work directory.
        config: Agent configuration.
        phase_id: ID of the phase to execute.
        mock_llm: If True, optimizer skips LLM calls.

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

    ideas = _load_ideas(work_dir)
    sampler = _init_sampler(work_dir)
    result = _execute_phase(work_dir, config, target_phase, project_path, resource_usage, ideas, sampler, mock_llm)

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
    ideas: list[dict] | None = None,
    sampler=None,
    mock_llm: bool = False,
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
            result = _execute_optimizer_phase(
                work_dir, config, phase, project_path, resource_usage, ideas, sampler, mock_llm,
            )
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
    resource_usage = {}
    resource_usage["full_evals_run"] = len(eval_results)

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
    ideas: list[dict] | None = None,
    sampler=None,
    mock_llm: bool = False,
) -> dict:
    """Execute an optimizer phase with full propose→apply→screen→eval→accept→rollback cycle.

    Uses PaperSampler for iterative method selection when available.
    Each candidate gets a fresh batch of 1-2 methods from the next untried category.

    For each candidate (up to phase budget):
    1. Get next method batch from sampler (or fallback to static ideas)
    2. Optimizer proposes a candidate patch using these ideas
    3. PatchManager applies the patch
    4. Quick screening eval
    5. Full eval if screening passes
    6. Accept/reject decision
    7. If accepted: git snapshot, update state
    8. If rejected: rollback patch
    """
    phase_id = phase.get("phase_id", "unknown")
    optimizer_name = phase.get("optimizer", "unknown")
    budget = phase.get("budget", {})
    max_candidates = budget.get("max_candidates", config.budget.max_candidates or 3)
    max_full_evals = budget.get("max_full_evals", config.budget.max_full_evals or 10)

    # Load baseline metrics
    state = read_state_json(work_dir)
    baseline_metrics = state.get("baseline_metrics", {})

    # Get optimizer class
    from research_agent.optimizers import get_optimizer_class
    try:
        opt_cls = get_optimizer_class(optimizer_name)
    except KeyError:
        return {
            "phase_id": phase_id,
            "status": "failed",
            "error": f"Unknown optimizer: {optimizer_name}",
        }

    optimizer = opt_cls(work_dir, config, project_path, mock_llm=mock_llm)
    patch_manager = PatchManager(project_path, work_dir)

    candidates_evaluated = 0
    best_candidate = None
    candidate_results = []

    for i in range(max_candidates):
        # Check eval budget
        if resource_usage.get("full_evals_run", 0) >= max_full_evals:
            break

        # 1. Get fresh ideas for this candidate
        candidate_ideas = ideas
        batch: list[dict] = []
        if sampler is not None:
            batch = sampler.get_next_batch(batch_size=2)
            if batch:
                candidate_ideas = batch

        # 2. Propose candidate
        candidate = optimizer.propose_candidate(phase, baseline_metrics, candidate_ideas)
        resource_usage["candidates_proposed"] = resource_usage.get("candidates_proposed", 0) + 1

        # Helper to mark methods with final status
        def _mark_batch(status: str, accepted: bool | None = None, reason: str = ""):
            if batch and sampler is not None:
                sampler.mark_used(
                    batch,
                    candidate_id=candidate.candidate_id,
                    status=status,
                    phase_id=phase_id,
                    accepted=accepted,
                    reason=reason,
                    metrics_before=baseline_metrics,
                )

        # Handle empty patch (no-op)
        if not candidate.patch_diff or not candidate.patch_diff.strip():
            candidate.status = "rejected"
            candidate.rejection_reason = "empty_patch"
            optimizer._log_candidate(candidate)
            _mark_batch("noop", reason="empty_patch")
            candidate_results.append({
                "candidate_id": candidate.candidate_id,
                "status": "skipped",
                "reason": "empty_patch",
            })
            continue

        # 3. Apply patch and validate compilation
        try:
            apply_result = patch_manager.apply_and_validate(candidate)
        except PatchApplyError as e:
            candidate.status = "rejected"
            candidate.rejection_reason = f"Patch apply failed: {e.message}"
            optimizer._log_candidate(candidate)
            _mark_batch("error", accepted=False, reason=e.message)
            candidate_results.append({
                "candidate_id": candidate.candidate_id,
                "status": "rejected",
                "reason": e.message,
            })
            continue

        # Check if patch was applied and validated
        if not apply_result.get("applied"):
            candidate.status = "rejected"
            reason_str = apply_result.get("reason", "unknown")
            errors = apply_result.get("errors", [])
            candidate.rejection_reason = f"Patch not applied: {reason_str}"
            if errors:
                candidate.rejection_reason += f" ({'; '.join(errors[:3])})"
            optimizer._log_candidate(candidate)
            _mark_batch("error", accepted=False, reason=candidate.rejection_reason)
            candidate_results.append({
                "candidate_id": candidate.candidate_id,
                "status": "rejected",
                "reason": candidate.rejection_reason,
            })
            continue

        # Update state: track applied patch
        state = read_state_json(work_dir)
        state = add_applied_patch(state, candidate.candidate_id)
        write_state_json(work_dir, state)

        # 4. Screen candidate (quick eval on screening seeds)
        optimizer.screen_candidate(candidate)
        resource_usage["screening_evals"] = resource_usage.get("screening_evals", 0) + 1

        if candidate.status == "rejected":
            # Rollback patch
            try:
                patch_manager.rollback_patch(candidate)
            except Exception:
                pass
            state = read_state_json(work_dir)
            state = remove_applied_patch(state, candidate.candidate_id)
            write_state_json(work_dir, state)
            _mark_batch("rejected", accepted=False, reason=candidate.rejection_reason or "screening_failed")
            candidate_results.append(candidate.to_dict())
            continue

        # 5. Full eval
        optimizer.full_eval_candidate(candidate)
        resource_usage["full_evals_run"] = resource_usage.get("full_evals_run", 0) + 1

        # 6. Accept or reject
        was_accepted = optimizer.accept_or_reject(candidate, baseline_metrics)

        if was_accepted:
            # 7. Snapshot accepted change
            try:
                patch_manager.snapshot(f"research-agent: accepted {candidate.candidate_id}")
            except Exception:
                pass
            best_candidate = candidate.to_dict()

            # Update state with current best
            state = read_state_json(work_dir)
            state["current_best"] = candidate.to_dict()
            write_state_json(work_dir, state)
            _mark_batch("accepted", accepted=True)
        else:
            # 8. Rollback rejected patch
            try:
                patch_manager.rollback_patch(candidate)
            except Exception:
                pass
            state = read_state_json(work_dir)
            state = remove_applied_patch(state, candidate.candidate_id)
            write_state_json(work_dir, state)
            _mark_batch("rejected", accepted=False, reason=candidate.rejection_reason or "no_improvement")

        candidate_results.append(candidate.to_dict())
        candidates_evaluated += 1

    # Safety check on current state
    screening_seeds = config.execution.screening_seeds
    eval_results = run_full_eval(project_path, config, screening_seeds, work_dir)
    aggregated = aggregate_metrics(eval_results)
    safety_result = check_safety_metrics(
        {k: v["mean"] for k, v in aggregated.items()},
        config,
    )

    return {
        "phase_id": phase_id,
        "status": "completed",
        "optimizer": optimizer_name,
        "candidates_evaluated": candidates_evaluated,
        "best_candidate": best_candidate,
        "candidate_results": candidate_results,
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


def _load_ideas(work_dir: Path) -> list[dict]:
    """Load extracted ideas from JSONL."""
    path = work_dir / "logs" / "extracted_ideas.jsonl"
    if not path.exists():
        return []
    ideas = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    ideas.append(json.loads(line))
    except (json.JSONDecodeError, OSError):
        pass
    return ideas


def _init_sampler(work_dir: Path):
    """Initialize PaperSampler if the reward paper pool exists.

    Returns PaperSampler instance or None if pool is unavailable.
    """
    from research_agent.core.paper_sampler import PaperSampler

    pool_dir = Path(__file__).resolve().parent.parent / "reward_paper_pool"
    if not pool_dir.exists():
        return None
    try:
        return PaperSampler(pool_dir, work_dir)
    except Exception:
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
