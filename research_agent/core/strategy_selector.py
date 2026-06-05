"""Strategy selection: map task types to optimizer plugins."""

from __future__ import annotations

import json
from pathlib import Path

from research_agent.core.output import ok_response
from research_agent.core.state import advance_phase, read_state_json, write_state_json
from research_agent.interfaces.front_agent_contract import require_phase
from research_agent.interfaces.json_protocol import (
    write_strategy_json,
    write_strategy_markdown,
)

# Strategy selection rules: task_type -> optimizer
_TASK_OPTIMIZER_MAP = {
    "reward_optimization": "reward",
    "controller_residual_optimization": "residual_control",
    "safety_constraint_optimization": "reward",  # handled jointly with residual_control
    "hpo": "hpo",
    "curriculum_learning": "curriculum",
    "observation_optimization": "observation",
    "action_space_optimization": "action_space",
}

_TASKS_NEEDING_HUMAN_REVIEW: set[str] = set()


def select_strategy(work_dir: Path) -> dict:
    """Select optimizer strategies based on task classification.

    V1 rules:
    - reward_optimization -> optimizers/reward
    - controller_residual_optimization -> optimizers/residual_control
    - safety_constraint_optimization -> handled jointly by reward + residual_control
    - observation/action_space -> human review required

    Args:
        work_dir: .research-agent work directory.

    Returns:
        Response dict with selected strategies.
    """
    require_phase(work_dir, "classified")

    state = read_state_json(work_dir)

    # Load task classification
    classification_path = work_dir / "reports" / "task_classification.json"
    classification = state.get("task_classification", {})
    if classification_path.exists() and classification_path.stat().st_size > 0:
        with open(classification_path, encoding="utf-8") as f:
            try:
                classification = json.load(f)
            except json.JSONDecodeError:
                pass

    task_types = classification.get("task_types", [])
    selected_optimizers = set()
    reasoning = []
    human_review_needed = []

    for task_type in task_types:
        if task_type in _TASKS_NEEDING_HUMAN_REVIEW:
            human_review_needed.append(task_type)
            reasoning.append(f"{task_type}: requires human review (V1 limitation)")
            continue

        optimizer = _TASK_OPTIMIZER_MAP.get(task_type)
        if optimizer:
            selected_optimizers.add(optimizer)
            reasoning.append(f"{task_type} -> optimizers/{optimizer}")
        else:
            reasoning.append(f"{task_type}: no optimizer mapping, suggestion only")

    # safety_constraint_optimization triggers both reward and residual_control
    if "safety_constraint_optimization" in task_types:
        selected_optimizers.add("residual_control")
        reasoning.append("safety_constraint_optimization also activates residual_control")

    selected = sorted(selected_optimizers)

    output = ok_response({
        "selected_optimizers": selected,
        "reasoning": reasoning,
        "human_review_needed": human_review_needed,
        "task_types": task_types,
    })

    # Write reports
    write_strategy_json(work_dir, output)
    md = _generate_markdown(output)
    write_strategy_markdown(work_dir, md)

    # Update state
    state = read_state_json(work_dir)
    state["strategy_selection"] = {
        "selected_optimizers": selected,
        "report": "reports/strategy_selection.md",
        "json": "reports/strategy_selection.json",
    }
    state = advance_phase(state, "strategy_selected")
    write_state_json(work_dir, state)

    return output


def _generate_markdown(data: dict) -> str:
    """Generate Markdown report for strategy selection."""
    lines = ["# Strategy Selection Report", ""]

    selected = data.get("selected_optimizers", [])
    lines.append(f"## Selected Optimizers ({len(selected)})")
    lines.append("")
    for opt in selected:
        lines.append(f"- `optimizers/{opt}`")
    lines.append("")

    lines.append("## Reasoning")
    lines.append("")
    for r in data.get("reasoning", []):
        lines.append(f"- {r}")
    lines.append("")

    human = data.get("human_review_needed", [])
    if human:
        lines.append("## Requiring Human Review")
        lines.append("")
        for h in human:
            lines.append(f"- {h}")

    return "\n".join(lines)
