"""State management: atomic write, file locking, resume logic."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from research_agent.core.exceptions import StateFileCorruptError

# --- State schema ---

PHASE_VALUES = (
    "initialized", "understood", "classified", "strategy_selected", "planned",
    "literature_searched", "literature_classified", "literature_selected",
    "ideas_extracted", "running_plan",
    "completed", "budget_exhausted", "interrupted", "error",
)

TERMINAL_PHASES = frozenset({"completed", "budget_exhausted", "interrupted", "error"})


def initial_state(project_path: str, work_dir: str) -> dict:
    """Return the initial state.json dict."""
    from pathlib import Path
    # Always resolve path to avoid encoding issues
    resolved_path = str(Path(project_path).resolve())
    return {
        "version": 1,
        "project_path": resolved_path,
        "work_dir": work_dir,
        "phase": "initialized",
        "front_agent": {
            "caller": None,
            "objective_written": False,
            "objective_file": "front_agent_objective.json",
        },
        "project_understanding": {
            "report": "reports/project_understanding.md",
            "json": "reports/project_understanding.json",
            "project_type": [],
        },
        "task_classification": {
            "task_types": [],
            "confidence": 0.0,
            "report": "reports/task_classification.json",
        },
        "strategy_selection": {
            "selected_optimizers": [],
            "report": "reports/strategy_selection.md",
            "json": "reports/strategy_selection.json",
        },
        "experiment_plan": {
            "report": "reports/experiment_plan.md",
            "json": "reports/experiment_plan.json",
            "phases": [],
        },
        "git": {
            "project_is_git_repo": None,
            "baseline_commit": None,
            "current_best_commit": None,
            "rollback_target_commit": None,
            "pre_run_stash": None,
            "dirty_worktree_policy": "abort",
        },
        "current_best": None,
        "candidate_queue": [],
        "needs_more_evidence": [],
        "literature": {
            "arxiv_papers": None,
            "paper_taxonomy": None,
            "selected_evidence": None,
            "extracted_ideas": None,
        },
        "resource_usage": {
            "wall_clock_seconds": 0,
            "gpu_seconds": None,
            "candidates": 0,
            "full_evals": 0,
        },
        "stop_reason": None,
        "progress": None,
        "applied_patches": [],
    }


# --- Atomic write ---


def write_state_json(work_dir: Path, state: dict) -> None:
    """Write state.json with retry for Windows file locking.

    Uses direct file write with retry. Does not verify to avoid race conditions.
    """
    state_path = work_dir / "state.json"

    for attempt in range(5):
        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
                f.flush()
            return
        except OSError:
            if attempt < 4:
                import time
                time.sleep(0.2 * (attempt + 1))
            else:
                raise


def read_state_json(work_dir: Path) -> dict:
    """Read and parse state.json with crash recovery.

    1. Try state.json.
    2. If corrupt, try state.json.tmp (may be latest write from a crash).
    3. If neither exists, raise FileNotFoundError.
    4. If both corrupt, raise StateFileCorruptError.
    """
    state_path = work_dir / "state.json"
    tmp_path = work_dir / "state.json.tmp"

    # Check if files exist
    if not state_path.exists() and not tmp_path.exists():
        raise FileNotFoundError(f"state.json not found in {work_dir}")

    for path in (state_path, tmp_path):
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    content = f.read()
                    if not content.strip():
                        continue
                    return json.loads(content)
            except (json.JSONDecodeError, OSError):
                continue

    raise StateFileCorruptError("Neither state.json nor state.json.tmp is parseable")


def cleanup_tmp_file(work_dir: Path) -> None:
    """Remove orphaned state.json.tmp on startup (self-healing)."""
    tmp_path = work_dir / "state.json.tmp"
    if tmp_path.exists():
        try:
            tmp_path.unlink()
        except OSError:
            pass


# --- File locking ---


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with given PID is alive (cross-platform)."""
    try:
        if os.name == "nt":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (ProcessLookupError, OSError):
        return False


def acquire_lock(work_dir: Path, command: str, timeout_seconds: int = 300) -> bool:
    """Acquire the lock file. Returns True on success, False on timeout.

    Uses file-based lock with PID detection (no fcntl, cross-platform).
    """
    lock_path = work_dir / "lock"
    deadline = time.monotonic() + timeout_seconds

    while True:
        if lock_path.exists():
            try:
                with open(lock_path, encoding="utf-8") as f:
                    lock_data = json.load(f)
                pid = lock_data.get("pid")
                if pid and _is_pid_alive(pid):
                    if time.monotonic() >= deadline:
                        return False
                    time.sleep(1)
                    continue
                # Stale lock — take it over
            except (json.JSONDecodeError, OSError):
                pass

        # Try to create lock atomically
        lock_data = {
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "command": command,
        }
        try:
            if os.name == "nt":
                # Windows: use open with 'x' mode for exclusive creation
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(lock_data, f)
                return True
            else:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(lock_data, f)
                return True
        except FileExistsError:
            # Race condition — retry
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)
            continue


def release_lock(work_dir: Path) -> None:
    """Release the lock file."""
    lock_path = work_dir / "lock"
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def read_lock(work_dir: Path) -> dict | None:
    """Read lock file contents. Returns None if not present or unreadable."""
    lock_path = work_dir / "lock"
    if not lock_path.exists():
        return None
    try:
        with open(lock_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def clear_stale_lock(work_dir: Path) -> bool:
    """Clear stale lock if PID is dead. Returns True if cleared."""
    lock = read_lock(work_dir)
    if lock is None:
        return False
    pid = lock.get("pid")
    if pid and _is_pid_alive(pid):
        return False
    release_lock(work_dir)
    return True


# --- Phase transition ---

_VALID_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "initialized": ("understood",),
    "understood": ("classified",),
    "classified": ("strategy_selected",),
    "strategy_selected": ("planned",),
    "planned": ("literature_searched",),
    "literature_searched": ("literature_classified",),
    "literature_classified": ("literature_selected",),
    "literature_selected": ("ideas_extracted", "running_plan"),
    "ideas_extracted": ("running_plan",),
    "running_plan": ("completed", "budget_exhausted", "interrupted", "error"),
}


def advance_phase(state: dict, new_phase: str) -> dict:
    """Validate and advance the phase. Returns new state dict (immutable)."""
    current = state["phase"]
    valid = _VALID_TRANSITIONS.get(current, ())
    if new_phase not in valid:
        raise ValueError(f"Invalid phase transition: {current} -> {new_phase}")
    return {**state, "phase": new_phase}


def can_resume(state: dict) -> bool:
    """Check if the state is resumable."""
    return state["phase"] in ("running_plan", "interrupted")


# --- Applied patches ---


def add_applied_patch(state: dict, candidate_id: str) -> dict:
    """Add a patch entry to applied_patches. Returns new state."""
    patches = list(state.get("applied_patches", []))
    patches.append({
        "candidate_id": candidate_id,
        "applied_at": datetime.now(timezone.utc).isoformat(),
    })
    return {**state, "applied_patches": patches}


def remove_applied_patch(state: dict, candidate_id: str) -> dict:
    """Remove a patch entry from applied_patches. Returns new state."""
    patches = [
        p for p in state.get("applied_patches", [])
        if p.get("candidate_id") != candidate_id
    ]
    return {**state, "applied_patches": patches}


def clear_applied_patches(state: dict) -> dict:
    """Clear all applied patches. Returns new state."""
    return {**state, "applied_patches": []}
