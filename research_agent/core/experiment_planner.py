"""Experiment planner: generate experiment plan with baseline and optimizer phases."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_agent.core.config import AgentConfig
from research_agent.core.exceptions import DependencyMissingError
from research_agent.core.output import ok_response
from research_agent.core.state import advance_phase, read_state_json, write_state_json
from research_agent.interfaces.front_agent_contract import require_objective
from research_agent.interfaces.json_protocol import (
    write_plan_json,
    write_plan_markdown,
)


def plan_experiments(work_dir: Path, config: AgentConfig) -> dict:
    """Generate experiment plan with baseline phase and optimizer phases.

    Pre-conditions (checked in order):
    1. Objective must be written by front agent.
    2. Task classification must exist.
    3. Strategy selection must exist.
    4. Metrics config must have primary metrics and metric_regex.

    Args:
        work_dir: .research-agent work directory.
        config: Agent configuration.

    Returns:
        Response dict with experiment plan.
    """
    # Validate pre-conditions
    require_objective(work_dir)
    _require_config_ready(config)

    state = read_state_json(work_dir)

    # Load task classification and strategy selection
    classification = _load_json_report(work_dir, "task_classification.json")
    strategy = _load_json_report(work_dir, "strategy_selection.json")

    selected_optimizers = strategy.get("selected_optimizers", [])
    task_types = classification.get("task_types", [])

    # Load project understanding (full data with optimizable/readonly targets)
    understanding = _load_json_report(work_dir, "project_understanding.json")

    # Build phases
    phases: list[dict[str, Any]] = []

    # Phase 0: Baseline (always first)
    baseline_phase = _build_baseline_phase(config)
    phases.append(baseline_phase)

    # Generate optimizer phases
    for optimizer_name in selected_optimizers:
        phase = _build_optimizer_phase(optimizer_name, task_types, config, understanding)
        phases.append(phase)

    # Joint validation phase (if multiple optimizers)
    if len(selected_optimizers) > 1:
        jv_phase = _build_joint_validation_phase(selected_optimizers, config)
        phases.append(jv_phase)

    now = datetime.now(timezone.utc).isoformat()
    plan = {
        "version": 1,
        "generated_at": now,
        "project_path": state.get("project_path", ""),
        "objective_name": config.objective.name,
        "global_budget": {
            "wall_clock_hours": config.budget.wall_clock_hours,
            "gpu_hours": config.budget.gpu_hours,
        },
        "phases": phases,
    }

    output = ok_response({
        "phase": "planned",
        "report_path": "reports/experiment_plan.md",
        "json_path": "reports/experiment_plan.json",
        "plan": plan,
        "next_action": "Call 'search-papers --json' before optimizer proposal.",
    })

    # Write reports
    write_plan_json(work_dir, output)
    md = _generate_markdown(plan)
    write_plan_markdown(work_dir, md)

    # Update state
    state = read_state_json(work_dir)
    state["experiment_plan"] = {
        "report": "reports/experiment_plan.md",
        "json": "reports/experiment_plan.json",
        "phases": [p["phase_id"] for p in phases],
    }
    state = advance_phase(state, "planned")
    write_state_json(work_dir, state)

    return output


def _require_config_ready(config: AgentConfig) -> None:
    """Validate that config has required fields for planning."""
    if not config.metrics.primary:
        raise DependencyMissingError(
            error_code="METRICS_MISSING",
            message="No primary metrics defined in config.",
            next_action="Add primary metrics to config.yaml or front_agent_objective.json.",
        )
    if not config.metrics.metric_regex:
        raise DependencyMissingError(
            error_code="METRIC_REGEX_MISSING",
            message="No metric_regex defined in config.",
            next_action="Add metric_regex to config.yaml or front_agent_objective.json.",
        )


def _build_baseline_phase(config: AgentConfig) -> dict:
    """Build the baseline phase (Phase 0)."""
    return {
        "phase_id": "baseline",
        "dependencies": [],
        "optimizer": None,
        "objective_summary": "Establish immutable baseline metrics before any candidate patch.",
        "allowed_changes": [],
        "forbidden_changes": [{"type": "all_project_files"}],
        "train_command": config.execution.train_command,
        "eval_command": config.execution.eval_command,
        "primary_metrics": [m.get("name", m) if isinstance(m, dict) else m for m in config.metrics.primary],
        "safety_metrics": [m.get("name", m) if isinstance(m, dict) else m for m in config.metrics.safety],
        "budget": {
            "timeout_seconds": config.execution.timeout_seconds_per_seed * len(config.execution.full_eval_seeds),
        },
        "rollback_policy": "git_checkout",
        "cleanup_policy": "none",
        "status": "pending",
    }


def _build_optimizer_phase(
    optimizer_name: str,
    task_types: list[str],
    config: AgentConfig,
    understanding: dict,
) -> dict:
    """Build an optimizer phase."""
    # Determine allowed/readonly from project understanding
    opt_targets = understanding.get("optimizable_targets", [])
    ro_targets = understanding.get("readonly_targets", [])

    allowed_changes = [
        {
            "type": t.get("type", "reward_function"),
            "file": t.get("file", ""),
            "line_range": t.get("line_range"),
            "symbol": t.get("name", ""),
        }
        for t in opt_targets
    ]

    forbidden_changes = [
        {
            "type": t.get("reason", "base_controller_law"),
            "file": t.get("file", ""),
            "symbol": t.get("name", ""),
        }
        for t in ro_targets
    ]

    # Add config-level forbidden changes
    for fc in config.constraints.forbidden_changes:
        forbidden_changes.append({"type": fc})

    phase_id = f"{optimizer_name}-optimization" if optimizer_name != "reward" else "reward-optimization"
    relevant_task_types = [
        tt for tt in task_types
        if tt in ("reward_optimization", "controller_residual_optimization", "safety_constraint_optimization")
    ]

    return {
        "phase_id": phase_id,
        "dependencies": ["baseline"],
        "optimizer": optimizer_name,
        "task_types": relevant_task_types,
        "objective_summary": f"Optimize {optimizer_name} based on task types: {', '.join(relevant_task_types)}",
        "allowed_changes": allowed_changes,
        "forbidden_changes": forbidden_changes,
        "train_command": config.execution.train_command,
        "eval_command": config.execution.eval_command,
        "primary_metrics": [m.get("name", m) if isinstance(m, dict) else m for m in config.metrics.primary],
        "safety_metrics": [m.get("name", m) if isinstance(m, dict) else m for m in config.metrics.safety],
        "budget": {
            "timeout_seconds": config.execution.timeout_seconds_per_seed * len(config.execution.full_eval_seeds),
        },
        "rollback_policy": "git_checkout",
        "cleanup_policy": "full",
        "status": "pending",
    }


def _build_joint_validation_phase(optimizers: list[str], config: AgentConfig) -> dict:
    """Build the joint validation phase (Phase 5)."""
    return {
        "phase_id": "joint-validation",
        "dependencies": [f"{opt}-optimization" if opt != "reward" else "reward-optimization" for opt in optimizers],
        "optimizer": None,
        "objective_summary": f"Validate combination of {', '.join(optimizers)} optimizers",
        "allowed_changes": [],
        "forbidden_changes": [],
        "train_command": config.execution.train_command,
        "eval_command": config.execution.eval_command,
        "primary_metrics": [m.get("name", m) if isinstance(m, dict) else m for m in config.metrics.primary],
        "safety_metrics": [m.get("name", m) if isinstance(m, dict) else m for m in config.metrics.safety],
        "budget": {
            "timeout_seconds": config.execution.timeout_seconds_per_seed * len(config.execution.full_eval_seeds),
        },
        "rollback_policy": "git_checkout",
        "cleanup_policy": "none",
        "status": "pending",
    }


def _load_json_report(work_dir: Path, filename: str) -> dict:
    """Load a JSON report file."""
    path = work_dir / "reports" / filename
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _generate_markdown(plan: dict) -> str:
    """Generate Markdown report for experiment plan."""
    lines = ["# Experiment Plan", ""]
    lines.append(f"**Generated:** {plan.get('generated_at', 'N/A')}")
    lines.append(f"**Project:** `{plan.get('project_path', 'N/A')}`")
    lines.append(f"**Objective:** {plan.get('objective_name', 'N/A')}")
    lines.append("")

    budget = plan.get("global_budget", {})
    lines.append("## Global Budget")
    lines.append("")
    lines.append(f"- Wall clock: {budget.get('wall_clock_hours', 'N/A')}h")
    lines.append(f"- GPU hours: {budget.get('gpu_hours', 'N/A')}")
    lines.append(f"- Wall clock: {budget.get('wall_clock_hours', 'N/A')}h")
    lines.append("")

    phases = plan.get("phases", [])
    lines.append(f"## Phases ({len(phases)})")
    lines.append("")

    for phase in phases:
        lines.append(f"### {phase.get('phase_id', '?')}")
        lines.append("")
        lines.append(f"- **Optimizer:** {phase.get('optimizer', 'none (baseline)')}")
        lines.append(f"- **Dependencies:** {', '.join(phase.get('dependencies', [])) or 'none'}")
        lines.append(f"- **Summary:** {phase.get('objective_summary', 'N/A')}")
        lines.append(f"- **Primary metrics:** {', '.join(phase.get('primary_metrics', []))}")
        lines.append(f"- **Safety metrics:** {', '.join(phase.get('safety_metrics', []))}")

        budget = phase.get("budget", {})
        lines.append(f"- **Budget:** wall_clock_hours={budget.get('wall_clock_hours', 'N/A')}h")
        lines.append("")

    return "\n".join(lines)
