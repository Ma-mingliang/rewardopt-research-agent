"""Checkpoint and resume support for optimizer runs.

Provides file-based run state persistence so that:
- Completed iterations are not re-run after resume
- Candidate IDs continue from last checkpoint
- Method IDs and candidate history persist
- LLM request hashes prevent duplicate calls
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class RunCheckpoint:
    """Checkpoint state for an optimizer run."""
    run_id: str = ""
    current_iteration: int = 0
    completed_iterations: list[int] = field(default_factory=list)
    next_candidate_index: int = 1
    candidate_ids_seen: list[str] = field(default_factory=list)
    request_hashes_seen: list[str] = field(default_factory=list)
    method_ids_tried: list[str] = field(default_factory=list)
    candidate_diff_history: list[dict[str, Any]] = field(default_factory=list)
    candidate_bank_records: list[dict[str, Any]] = field(default_factory=list)
    last_checkpoint_time: str = ""
    resume_supported: bool = True
    resumed_from_checkpoint: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "run_id": self.run_id,
            "current_iteration": self.current_iteration,
            "completed_iterations": self.completed_iterations,
            "next_candidate_index": self.next_candidate_index,
            "candidate_ids_seen": self.candidate_ids_seen,
            "request_hashes_seen": self.request_hashes_seen,
            "method_ids_tried": self.method_ids_tried,
            "candidate_diff_history": self.candidate_diff_history,
            "candidate_bank_records": self.candidate_bank_records,
            "last_checkpoint_time": self.last_checkpoint_time,
            "resume_supported": self.resume_supported,
            "resumed_from_checkpoint": self.resumed_from_checkpoint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunCheckpoint:
        """Create from dictionary."""
        return cls(
            run_id=data.get("run_id", ""),
            current_iteration=data.get("current_iteration", 0),
            completed_iterations=data.get("completed_iterations", []),
            next_candidate_index=data.get("next_candidate_index", 1),
            candidate_ids_seen=data.get("candidate_ids_seen", []),
            request_hashes_seen=data.get("request_hashes_seen", []),
            method_ids_tried=data.get("method_ids_tried", []),
            candidate_diff_history=data.get("candidate_diff_history", []),
            candidate_bank_records=data.get("candidate_bank_records", []),
            last_checkpoint_time=data.get("last_checkpoint_time", ""),
            resume_supported=data.get("resume_supported", True),
            resumed_from_checkpoint=data.get("resumed_from_checkpoint", False),
        )


def save_checkpoint(checkpoint: RunCheckpoint, run_dir: Path) -> Path:
    """Save checkpoint to run directory.

    Args:
        checkpoint: The checkpoint to save.
        run_dir: Directory to save checkpoint in.

    Returns:
        Path to saved checkpoint file.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = run_dir / "run_state.json"

    checkpoint.last_checkpoint_time = datetime.now(timezone.utc).isoformat()

    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump(checkpoint.to_dict(), f, indent=2, ensure_ascii=False)

    return checkpoint_path


def load_checkpoint(run_dir: Path) -> RunCheckpoint | None:
    """Load checkpoint from run directory.

    Args:
        run_dir: Directory containing checkpoint.

    Returns:
        RunCheckpoint if found, None otherwise.
    """
    checkpoint_path = run_dir / "run_state.json"
    if not checkpoint_path.exists():
        return None

    try:
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return RunCheckpoint.from_dict(data)
    except (json.JSONDecodeError, KeyError):
        return None


def generate_candidate_id(prefix: str, index: int) -> str:
    """Generate unique candidate ID.

    Args:
        prefix: Prefix for the ID (e.g., 'reward').
        index: Index number.

    Returns:
        Candidate ID like 'reward_c001'.
    """
    return f"{prefix}_c{index:03d}"


def is_iteration_completed(checkpoint: RunCheckpoint, iteration: int) -> bool:
    """Check if an iteration has been completed."""
    return iteration in checkpoint.completed_iterations


def mark_iteration_completed(checkpoint: RunCheckpoint, iteration: int) -> None:
    """Mark an iteration as completed."""
    if iteration not in checkpoint.completed_iterations:
        checkpoint.completed_iterations.append(iteration)
        checkpoint.completed_iterations.sort()


def add_candidate_id(checkpoint: RunCheckpoint, candidate_id: str) -> bool:
    """Add candidate ID to seen list.

    Returns:
        True if ID was new, False if duplicate.
    """
    if candidate_id in checkpoint.candidate_ids_seen:
        return False
    checkpoint.candidate_ids_seen.append(candidate_id)
    return True


def add_request_hash(checkpoint: RunCheckpoint, request_hash: str) -> bool:
    """Add request hash to seen list.

    Returns:
        True if hash was new, False if duplicate.
    """
    if request_hash in checkpoint.request_hashes_seen:
        return False
    checkpoint.request_hashes_seen.append(request_hash)
    return True


def get_next_candidate_id(checkpoint: RunCheckpoint, prefix: str = "reward") -> str:
    """Get next unique candidate ID and increment counter.

    Args:
        prefix: Prefix for the ID.

    Returns:
        Next candidate ID.
    """
    candidate_id = generate_candidate_id(prefix, checkpoint.next_candidate_index)
    checkpoint.next_candidate_index += 1
    return candidate_id


def add_method_tried(checkpoint: RunCheckpoint, method_id: str) -> None:
    """Add method ID to tried list."""
    if method_id not in checkpoint.method_ids_tried:
        checkpoint.method_ids_tried.append(method_id)


def add_candidate_diff(checkpoint: RunCheckpoint, candidate_id: str, diff: str, method_ids: list[str]) -> None:
    """Add candidate diff to history."""
    checkpoint.candidate_diff_history.append({
        "candidate_id": candidate_id,
        "diff_hash": hashlib.sha256(diff.encode()).hexdigest()[:16] if diff else "",
        "method_ids": method_ids,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


def add_candidate_bank_record(checkpoint: RunCheckpoint, record: dict[str, Any]) -> bool:
    """Add candidate bank record.

    Returns:
        True if record was new, False if duplicate.
    """
    candidate_id = record.get("candidate_id", "")
    for existing in checkpoint.candidate_bank_records:
        if existing.get("candidate_id") == candidate_id:
            return False
    checkpoint.candidate_bank_records.append(record)
    return True


def get_proposal_only_summary(checkpoint: RunCheckpoint) -> dict[str, Any]:
    """Get proposal-only mode summary.

    Returns:
        Summary dictionary with proposal-only specific fields.
    """
    return {
        "proposal_only": True,
        "proposal_candidate_count": len(checkpoint.candidate_ids_seen),
        "validation_ready_candidate_count": len([
            r for r in checkpoint.candidate_bank_records
            if r.get("validation_passed", False)
        ]),
        "candidate_bank_size": len(checkpoint.candidate_bank_records),
        "candidate_id_unique_count": len(set(checkpoint.candidate_ids_seen)),
        "duplicate_candidate_id_count": len(checkpoint.candidate_ids_seen) - len(set(checkpoint.candidate_ids_seen)),
        "llm_transport_retry_count": 0,  # Updated by transport layer
        "llm_transport_failure_count": 0,
        "llm_ssl_error_count": 0,
        "llm_timeout_count": 0,
        "llm_rate_limit_count": 0,
        "resume_supported": checkpoint.resume_supported,
        "resumed_from_checkpoint": checkpoint.resumed_from_checkpoint,
        "completed_iterations": len(checkpoint.completed_iterations),
        "method_ids_tried": len(checkpoint.method_ids_tried),
    }


# Import hashlib for diff hashing
import hashlib
