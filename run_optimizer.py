#!/usr/bin/env python3
"""Run optimizer with version tracking."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import click

from research_agent.core.config import load_config, load_dotenv
from research_agent.core.executor import _execute_optimizer_phase, _init_sampler, _load_plan
from research_agent.core.state import read_state_json, write_state_json
from research_agent.core.version_tracker import VersionTracker


@click.command()
@click.option("--project", required=True, type=click.Path(exists=True), help="Project root path")
@click.option("--max-iterations", default=None, type=int, help="Max iterations to run")
@click.option("--mock-llm", is_flag=True, help="Skip LLM calls")
@click.option("--batch-size", default=2, type=int, help="Methods per batch")
@click.option("--execution-python", default=None, type=str, help="Python executable for project code execution")
@click.option("--optimizer", default=None, type=str, help="Override optimizer (e.g. reward_langgraph)")
@click.option("--run-log-dir", default=None, type=str, help="Directory for run logs (default: .research-agent/runs)")
@click.option("--reward-method-pool", default=None, type=click.Path(), help="Path to method_pool.jsonl for rich context injection")
@click.option("--reward-method-top-k", default=None, type=int, help="Number of methods to inject as context (default: 5)")
@click.option("--staged-eval", is_flag=True, help="Enable staged evaluation pipeline")
@click.option("--max-static-repair-attempts", default=None, type=int, help="Max static repair attempts (default: 3)")
@click.option("--max-runtime-repair-attempts", default=None, type=int, help="Max runtime repair attempts (default: 2)")
@click.option("--short-train/--no-short-train", default=None, help="Enable/disable short train screening")
@click.option("--baseline-manifest", default=None, type=click.Path(),
              help="Path to baseline manifest YAML (default: docs/baselines/hrrl2_operational_baseline.yaml)")
@click.option("--accept-baseline-migration", is_flag=True, default=False,
              help="Allow proceeding when env.py differs from manifest hash")
def main(
    project: str,
    max_iterations: int | None,
    mock_llm: bool,
    batch_size: int,
    execution_python: str | None,
    optimizer: str | None,
    run_log_dir: str | None,
    reward_method_pool: str | None,
    reward_method_top_k: int | None,
    staged_eval: bool,
    max_static_repair_attempts: int | None,
    max_runtime_repair_attempts: int | None,
    short_train: bool | None,
    baseline_manifest: str | None,
    accept_baseline_migration: bool,
):
    """Run optimizer with version tracking.

    Each candidate version is logged to:
    - CHANGELOG.md (human-readable)
    - logs/tried_methods.jsonl (machine-readable)
    - stdout (real-time with flush=True)
    """
    # Load .env files before any LLM config is read
    loaded = load_dotenv([Path.cwd() / ".env", Path(__file__).resolve().parent / ".env"])

    project_path = Path(project).resolve()
    work_dir = project_path / ".research-agent"

    if not work_dir.exists():
        print(f"[ERROR] Work directory not found: {work_dir}", flush=True)
        sys.exit(1)

    config = load_config(work_dir)
    state = read_state_json(work_dir)

    # Apply CLI overrides to config (CLI > config > default)
    if reward_method_pool is not None:
        config.optimizer.method_pool_path = reward_method_pool
    if reward_method_top_k is not None:
        config.optimizer.method_top_k = reward_method_top_k
    if staged_eval:
        config.staged_evaluation.enabled = True
    if max_static_repair_attempts is not None:
        config.staged_evaluation.max_static_repair_attempts = max_static_repair_attempts
    if max_runtime_repair_attempts is not None:
        config.staged_evaluation.max_runtime_repair_attempts = max_runtime_repair_attempts
    if short_train is not None:
        config.staged_evaluation.short_train_enabled = short_train

    # Credential preflight: fail fast if real LLM requested but key is missing
    if not mock_llm:
        import os
        api_key_env = config.llm.api_key_env
        api_key = os.environ.get(api_key_env, "")
        key_present = bool(api_key)
        key_length = len(api_key)
        key_source = "dotenv" if api_key_env in loaded else "shell_env"
        print(f"[CREDENTIAL] key_present={key_present} key_source={key_source} key_length={key_length}", flush=True)
        if not key_present:
            print(f"[ERROR] Real LLM run requested but {api_key_env} is missing or empty.", flush=True)
            print(f"Set it in environment or .env file.", flush=True)
            sys.exit(1)

    # Validate --optimizer override if provided
    if optimizer is not None:
        from research_agent.optimizers import get_optimizer_class
        try:
            get_optimizer_class(optimizer)
        except KeyError:
            available = ", ".join(sorted(__import__("research_agent.optimizers", fromlist=["list_optimizers"]).list_optimizers()))
            print(f"[ERROR] Unknown optimizer: '{optimizer}'", flush=True)
            print(f"Available optimizers: {available}", flush=True)
            sys.exit(1)

    # Resolve run log directory
    if run_log_dir is None:
        run_log_dir_path = work_dir / "runs"
    else:
        run_log_dir_path = Path(run_log_dir).resolve()
    run_log_dir_path.mkdir(parents=True, exist_ok=True)

    # Create RunObserver
    from research_agent.core.observability import RunObserver
    observer = RunObserver(
        run_log_dir=str(run_log_dir_path),
        optimizer=optimizer or "auto",
        project_path=str(project_path),
        agent_python=sys.executable,
        execution_python=execution_python or "",
        fallback_used=execution_python is None,
        mock_llm=mock_llm,
        max_iterations=max_iterations,
        batch_size=batch_size,
    )

    print("=" * 80, flush=True)
    print("[OPTIMIZER START]", flush=True)
    print(f"Project: {project_path}", flush=True)
    print(f"Time: {datetime.now(timezone.utc).isoformat()}", flush=True)
    print(f"Mock LLM: {mock_llm}", flush=True)
    print(f"Max iterations: {max_iterations or 'unlimited'}", flush=True)
    print(f"Batch size: {batch_size}", flush=True)
    print(f"Execution Python: {execution_python or '(fallback to sys.executable)'}", flush=True)
    print(f"Optimizer override: {optimizer or '(from experiment_plan.json)'}", flush=True)
    print(f"Run ID: {observer.run_id}", flush=True)
    print(f"Run log dir: {observer.run_dir}", flush=True)
    print("=" * 80 + "\n", flush=True)
    print("Note: configuration confirmation will happen inside optimizer phase.", flush=True)

    observer.emit("run_start", phase="main")

    # --- Baseline guard ---
    from research_agent.core.baseline_guard import (
        build_baseline_drift_error,
        check_baseline_consistency,
        load_baseline_manifest,
    )
    from research_agent.core.exceptions import BaselineDriftError

    manifest_path = Path(baseline_manifest) if baseline_manifest else (
        Path(__file__).resolve().parent / "docs" / "baselines" / "hrrl2_operational_baseline.yaml"
    )

    if manifest_path.exists():
        try:
            manifest = load_baseline_manifest(manifest_path)
            auto_push = getattr(getattr(config, 'git', None), 'auto_push', False)
            guard_result = check_baseline_consistency(
                project_path=project_path,
                manifest=manifest,
                allow_migration=accept_baseline_migration,
            )
            guard_result.auto_push_detected = auto_push

            observer.emit(
                "baseline_guard_start",
                manifest_path=str(manifest_path),
                manifest_hash=manifest.accepted_operational_baseline_hash,
                auto_push=auto_push,
                allow_migration=accept_baseline_migration,
            )

            if not guard_result.ok:
                observer.emit(
                    "baseline_guard_failed",
                    drift_type=guard_result.drift_type.value,
                    env_hash=guard_result.env_hash,
                    manifest_hash=guard_result.manifest_hash,
                    auto_push=auto_push,
                    allow_migration=accept_baseline_migration,
                )
                observer.emit(
                    "baseline_drift_detected",
                    drift_type=guard_result.drift_type.value,
                    env_hash=guard_result.env_hash,
                    artifact_hash=guard_result.artifact_hash,
                    manifest_hash=guard_result.manifest_hash,
                )
                observer.track_baseline_guard(
                    passed=False,
                    drift_type=guard_result.drift_type.value,
                    manifest_path=str(manifest_path),
                )
                observer.close()
                print(build_baseline_drift_error(guard_result), flush=True)
                raise BaselineDriftError(
                    build_baseline_drift_error(guard_result),
                    drift_type=guard_result.drift_type.value,
                    env_hash=guard_result.env_hash,
                    manifest_hash=guard_result.manifest_hash,
                )
            else:
                observer.emit(
                    "baseline_guard_pass",
                    env_hash=guard_result.env_hash,
                    manifest_hash=guard_result.manifest_hash,
                )
                observer.track_baseline_guard(
                    passed=True,
                    manifest_path=str(manifest_path),
                )
                print(f"[BASELINE GUARD] Passed. env_hash={guard_result.env_hash}", flush=True)
        except FileNotFoundError:
            print(f"[WARNING] Baseline manifest not found: {manifest_path}", flush=True)
            observer.emit("baseline_guard_manifest_missing", manifest_path=str(manifest_path))
    else:
        print(f"[WARNING] Baseline manifest not found: {manifest_path}", flush=True)
        observer.emit("baseline_guard_manifest_missing", manifest_path=str(manifest_path))

    # Initialize sampler
    sampler = _init_sampler(work_dir)
    if sampler is None:
        print("[ERROR] Paper pool not found. Cannot run optimizer.", flush=True)
        sys.exit(1)

    # Load plan
    plan = _load_plan(work_dir)
    if not plan:
        print("[ERROR] No experiment plan found.", flush=True)
        sys.exit(1)

    phases = plan.get("phases", [])
    optimizer_phase = None
    for p in phases:
        if p.get("optimizer") and p.get("status") != "completed":
            optimizer_phase = p
            break

    if optimizer_phase is None:
        print("[INFO] No pending optimizer phases.", flush=True)
        observer.emit("run_end", phase="main", status="no_pending_phases")
        observer.close()
        return

    # Override optimizer from CLI if provided
    if optimizer is not None:
        original_optimizer = optimizer_phase.get("optimizer", "unknown")
        optimizer_phase = dict(optimizer_phase)
        optimizer_phase["optimizer"] = optimizer
        print(f"[CLI] Optimizer override: {original_optimizer} -> {optimizer}", flush=True)
        observer.emit("optimizer_override", original=original_optimizer, override=optimizer)

    resource_usage = state.get("resource_usage", {
        "wall_clock_seconds": 0,
        "gpu_seconds": 0,
        "candidates_proposed": 0,
        "full_evals_run": 0,
    })

    iteration = 0
    while True:
        # Check max iterations
        if max_iterations and iteration >= max_iterations:
            print(f"\n[STOP] Reached max iterations: {max_iterations}", flush=True)
            break

        # Get next batch
        batch = sampler.get_next_batch(batch_size=batch_size)
        if not batch:
            print("\n[STOP] All methods have been tried.", flush=True)
            break

        iteration += 1
        print(f"\n{'=' * 80}", flush=True)
        print(f"[ITERATION {iteration}]", flush=True)
        print(f"Methods: {[m.get('method_id', '') for m in batch]}", flush=True)
        print(f"Categories: {list({m.get('category', '') for m in batch})}", flush=True)
        print(f"{'=' * 80}\n", flush=True)

        # Execute single iteration with state protection
        phase_copy = dict(optimizer_phase)
        phase_copy["budget"] = {**optimizer_phase.get("budget", {}), "max_candidates": 1}

        # Check if work_dir exists
        if not work_dir.exists():
            print(f"[ERROR] Work directory missing: {work_dir}", flush=True)
            # Recreate work directory
            work_dir.mkdir(parents=True, exist_ok=True)
            (work_dir / "logs").mkdir(exist_ok=True)
            (work_dir / "patches").mkdir(exist_ok=True)
            (work_dir / "artifacts").mkdir(exist_ok=True)
            (work_dir / "reports").mkdir(exist_ok=True)
            # Recreate state
            from research_agent.core.state import initial_state
            write_state_json(work_dir, initial_state(str(project_path), ".research-agent"))

        # Save state backup before iteration
        state_backup = None
        try:
            state_backup = read_state_json(work_dir)
        except Exception:
            pass

        try:
            observer.emit("iteration_start", iteration=iteration, phase=phase_copy.get("phase_id", "unknown"))
            result = _execute_optimizer_phase(
                work_dir, config, phase_copy, project_path, resource_usage, batch,
                sampler=sampler, mock_llm=mock_llm,
                execution_python=execution_python,
                observer=observer,
            )
        except Exception as e:
            print(f"[ERROR] Iteration failed: {e}", flush=True)
            # Restore state from backup, but preserve current resource_usage
            try:
                if state_backup:
                    # Read current state to get latest resource_usage (may have been persisted mid-iteration)
                    try:
                        current_state = read_state_json(work_dir)
                        latest_usage = current_state.get("resource_usage", resource_usage)
                    except Exception:
                        latest_usage = resource_usage
                    state_backup["resource_usage"] = latest_usage
                    write_state_json(work_dir, state_backup)
                else:
                    from research_agent.core.state import initial_state
                    fresh = initial_state(str(project_path), ".research-agent")
                    fresh["resource_usage"] = resource_usage
                    write_state_json(work_dir, fresh)
            except Exception as e2:
                print(f"[ERROR] State recovery failed: {e2}", flush=True)
            result = {"status": "failed", "error": str(e)}

        # Print result summary
        print(f"\n[RESULT] Iteration {iteration} completed", flush=True)
        print(f"Status: {result.get('status', 'unknown')}", flush=True)
        print(f"Candidates evaluated: {result.get('candidates_evaluated', 0)}", flush=True)

        observer.emit("iteration_end", iteration=iteration, status=result.get("status", "unknown"),
                       candidates_evaluated=result.get("candidates_evaluated", 0))

        best = result.get("best_candidate")
        if best:
            print(f"Best candidate: {best.get('candidate_id', 'none')}", flush=True)
            print(f"Best status: {best.get('status', 'unknown')}", flush=True)

        # Update state
        try:
            state = read_state_json(work_dir)
            state["resource_usage"] = resource_usage
            write_state_json(work_dir, state)
        except FileNotFoundError:
            # State was deleted, recreate from backup
            if state_backup:
                try:
                    state_backup["resource_usage"] = resource_usage
                    write_state_json(work_dir, state_backup)
                except Exception as e:
                    print(f"[WARN] State recovery failed: {e}", flush=True)
            else:
                print("[WARN] State file missing and no backup available", flush=True)
        except Exception as e:
            print(f"[WARN] State update failed: {e}", flush=True)

        # Check if work_dir still exists after iteration
        if not work_dir.exists():
            print(f"[ERROR] Work directory deleted during iteration {iteration}!", flush=True)

        # Delay between iterations to avoid Windows file locking issues
        time.sleep(2)

    # Final summary
    print("\n" + "=" * 80, flush=True)
    print("[OPTIMIZER COMPLETE]", flush=True)
    print(f"Total iterations: {iteration}", flush=True)
    print(f"Total candidates proposed: {resource_usage.get('candidates_proposed', 0)}", flush=True)
    print(f"Total full evals: {resource_usage.get('full_evals_run', 0)}", flush=True)
    print(f"Changelog: {work_dir / 'CHANGELOG.md'}", flush=True)
    print(f"Tried methods: {work_dir / 'logs' / 'tried_methods.jsonl'}", flush=True)
    print(f"Run log: {observer.run_dir}", flush=True)
    print("=" * 80, flush=True)

    observer.emit("run_end", phase="main", total_iterations=iteration,
                   total_candidates=resource_usage.get("candidates_proposed", 0))
    observer.close()
    print(f"[OBSERVER] Summary written to: {observer.summary_path}", flush=True)


if __name__ == "__main__":
    main()
