"""Front agent contract validation.

Ensures required prerequisites are met before commands proceed.
"""

from __future__ import annotations

from pathlib import Path

from research_agent.core.exceptions import DependencyMissingError
from research_agent.core.state import read_state_json


def require_objective(work_dir: Path) -> None:
    """Check that objective has been written by front agent.

    Raises DependencyMissingError if objective is missing.
    """
    state = read_state_json(work_dir)
    if not state.get("front_agent", {}).get("objective_written", False):
        raise DependencyMissingError(
            error_code="OBJECTIVE_MISSING",
            message="Objective is required before planning experiments.",
            next_action="Write objective to front_agent_objective.json, then retry.",
        )


def require_phase(work_dir: Path, required_phase: str) -> None:
    """Check that the state has reached at least the required phase.

    Raises DependencyMissingError if not reached.
    """
    state = read_state_json(work_dir)
    phase_order = [
        "initialized", "understood", "classified", "strategy_selected", "planned",
        "literature_searched", "literature_classified", "literature_selected",
        "ideas_extracted", "running_plan",
    ]
    current = state.get("phase", "initialized")
    try:
        current_idx = phase_order.index(current)
        required_idx = phase_order.index(required_phase)
    except ValueError:
        raise DependencyMissingError(
            error_code="INVALID_PHASE",
            message=f"Unknown phase: {current} or {required_phase}",
            next_action="Check state.json phase field.",
        )
    if current_idx < required_idx:
        phase_commands = {
            "understood": "understand",
            "classified": "classify-task",
            "strategy_selected": "select-strategy",
            "planned": "plan-experiments",
        }
        cmd = phase_commands.get(required_phase, required_phase)
        raise DependencyMissingError(
            error_code=f"NOT_{required_phase.upper()}",
            message=f"Phase must be at least '{required_phase}', currently '{current}'.",
            next_action=f"Call '{cmd}' first.",
        )


def require_task_classification(work_dir: Path) -> None:
    """Check that task classification has been done."""
    require_phase(work_dir, "classified")


def require_strategy_selection(work_dir: Path) -> None:
    """Check that strategy selection has been done."""
    require_phase(work_dir, "strategy_selected")


def require_experiment_plan(work_dir: Path) -> None:
    """Check that experiment plan has been generated."""
    require_phase(work_dir, "planned")
