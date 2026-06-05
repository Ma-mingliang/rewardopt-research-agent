"""Resume: allow resuming an interrupted experiment run."""

from __future__ import annotations

from pathlib import Path

from research_agent.core.output import ok_response
from research_agent.core.state import can_resume, read_state_json, write_state_json


def resume(work_dir: Path) -> dict:
    """Resume an interrupted experiment run.

    Checks if the state is resumable (phase is running_plan or interrupted).
    If so, resets the phase to allow run-plan to continue.

    Args:
        work_dir: .research-agent work directory.

    Returns:
        Response dict with resume status.
    """
    state = read_state_json(work_dir)
    phase = state.get("phase", "")

    if can_resume(state):
        # Reset to allow run-plan to continue
        state["phase"] = "ideas_extracted"
        state["stop_reason"] = None
        write_state_json(work_dir, state)

        return ok_response({
            "resumed": True,
            "from_phase": phase,
            "to_phase": "ideas_extracted",
            "message": "Resumed. Call 'run-plan' to continue execution.",
        })

    if phase == "completed":
        return ok_response({
            "resumed": False,
            "reason": "Already completed",
            "message": "Run is already completed. Use 'status' to see results.",
        })

    if phase == "budget_exhausted":
        return ok_response({
            "resumed": False,
            "reason": "Budget exhausted",
            "message": "Budget exhausted. Increase budget in config.yaml to continue.",
        })

    return ok_response({
        "resumed": False,
        "reason": f"Phase '{phase}' is not resumable",
        "message": "Only running_plan or interrupted phases can be resumed.",
    })
