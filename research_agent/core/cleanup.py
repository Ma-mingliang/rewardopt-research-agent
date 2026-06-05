"""Cleanup: remove temporary artifacts and reset transient state."""

from __future__ import annotations

from pathlib import Path

from research_agent.core.output import ok_response
from research_agent.core.state import read_state_json, write_state_json


def cleanup(work_dir: Path, full: bool = False) -> dict:
    """Clean up temporary files and reset transient state.

    Args:
        work_dir: .research-agent work directory.
        full: If True, also remove logs and artifacts. If False, only remove lock and tmp files.

    Returns:
        Response dict with cleanup results.
    """
    removed: list[str] = []

    # Always remove lock
    lock_path = work_dir / "lock"
    if lock_path.exists():
        lock_path.unlink()
        removed.append("lock")

    # Remove state.json.tmp
    tmp_path = work_dir / "state.json.tmp"
    if tmp_path.exists():
        tmp_path.unlink()
        removed.append("state.json.tmp")

    # Remove lock.tmp
    lock_tmp = work_dir / "lock.tmp"
    if lock_tmp.exists():
        lock_tmp.unlink()
        removed.append("lock.tmp")

    if full:
        # Clear logs
        logs_dir = work_dir / "logs"
        if logs_dir.exists():
            for f in logs_dir.iterdir():
                if f.is_file() and f.suffix == ".jsonl":
                    # Truncate but keep the file
                    f.write_text("", encoding="utf-8")
                    removed.append(f"logs/{f.name}")

        # Clear artifacts
        artifacts_dir = work_dir / "artifacts"
        if artifacts_dir.exists():
            for f in artifacts_dir.iterdir():
                if f.is_file():
                    f.unlink()
                    removed.append(f"artifacts/{f.name}")

        # Clear patches
        patches_dir = work_dir / "patches"
        if patches_dir.exists():
            for f in patches_dir.iterdir():
                if f.is_file():
                    f.unlink()
                    removed.append(f"patches/{f.name}")

        # Clear cache
        cache_dir = work_dir / "cache"
        if cache_dir.exists():
            for f in cache_dir.iterdir():
                if f.is_file():
                    f.unlink()
                    removed.append(f"cache/{f.name}")

    return ok_response({
        "removed": removed,
        "full": full,
    })
