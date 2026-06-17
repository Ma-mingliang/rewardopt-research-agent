"""Tests for checkpoint and resume functionality.

Covers:
- Save/load checkpoint
- Iteration completion tracking
- Candidate ID generation
- Method ID tracking
- Proposal-only summary
"""

import pytest
import json
import tempfile
from pathlib import Path

from research_agent.core.checkpoint import (
    RunCheckpoint,
    save_checkpoint,
    load_checkpoint,
    generate_candidate_id,
    is_iteration_completed,
    mark_iteration_completed,
    add_candidate_id,
    add_request_hash,
    get_next_candidate_id,
    add_method_tried,
    add_candidate_diff,
    add_candidate_bank_record,
    get_proposal_only_summary,
)


class TestCheckpointPersistence:
    """Test checkpoint save/load."""

    def test_save_and_load(self):
        """Should save and load checkpoint correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            checkpoint = RunCheckpoint(
                run_id="test_run",
                current_iteration=5,
                completed_iterations=[1, 2, 3],
                next_candidate_index=4,
            )

            save_checkpoint(checkpoint, run_dir)
            loaded = load_checkpoint(run_dir)

            assert loaded is not None
            assert loaded.run_id == "test_run"
            assert loaded.current_iteration == 5
            assert loaded.completed_iterations == [1, 2, 3]
            assert loaded.next_candidate_index == 4

    def test_load_nonexistent(self):
        """Should return None for nonexistent checkpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            loaded = load_checkpoint(run_dir)
            assert loaded is None

    def test_checkpoint_has_timestamp(self):
        """Checkpoint should have timestamp after save."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            checkpoint = RunCheckpoint(run_id="test")
            save_checkpoint(checkpoint, run_dir)
            loaded = load_checkpoint(run_dir)
            assert loaded.last_checkpoint_time != ""


class TestIterationTracking:
    """Test iteration completion tracking."""

    def test_iteration_not_completed(self):
        """Should track incomplete iterations."""
        checkpoint = RunCheckpoint()
        assert is_iteration_completed(checkpoint, 1) is False

    def test_iteration_completed(self):
        """Should track completed iterations."""
        checkpoint = RunCheckpoint()
        mark_iteration_completed(checkpoint, 1)
        assert is_iteration_completed(checkpoint, 1) is True

    def test_iteration_completed_no_duplicates(self):
        """Should not duplicate completed iterations."""
        checkpoint = RunCheckpoint()
        mark_iteration_completed(checkpoint, 1)
        mark_iteration_completed(checkpoint, 1)
        assert checkpoint.completed_iterations.count(1) == 1

    def test_iterations_sorted(self):
        """Completed iterations should be sorted."""
        checkpoint = RunCheckpoint()
        mark_iteration_completed(checkpoint, 3)
        mark_iteration_completed(checkpoint, 1)
        mark_iteration_completed(checkpoint, 2)
        assert checkpoint.completed_iterations == [1, 2, 3]


class TestCandidateID:
    """Test candidate ID generation."""

    def test_generate_candidate_id(self):
        """Should generate correct format."""
        assert generate_candidate_id("reward", 1) == "reward_c001"
        assert generate_candidate_id("reward", 42) == "reward_c042"

    def test_get_next_candidate_id(self):
        """Should increment counter."""
        checkpoint = RunCheckpoint()
        id1 = get_next_candidate_id(checkpoint)
        id2 = get_next_candidate_id(checkpoint)
        assert id1 == "reward_c001"
        assert id2 == "reward_c002"

    def test_add_candidate_id_new(self):
        """Should return True for new ID."""
        checkpoint = RunCheckpoint()
        assert add_candidate_id(checkpoint, "reward_c001") is True

    def test_add_candidate_id_duplicate(self):
        """Should return False for duplicate ID."""
        checkpoint = RunCheckpoint()
        add_candidate_id(checkpoint, "reward_c001")
        assert add_candidate_id(checkpoint, "reward_c001") is False

    def test_candidate_ids_unique_across_resume(self):
        """Should maintain uniqueness after resume."""
        checkpoint1 = RunCheckpoint()
        get_next_candidate_id(checkpoint1)
        get_next_candidate_id(checkpoint1)

        # Simulate resume
        checkpoint2 = RunCheckpoint(
            next_candidate_index=checkpoint1.next_candidate_index
        )
        id3 = get_next_candidate_id(checkpoint2)
        assert id3 == "reward_c003"


class TestRequestHash:
    """Test request hash tracking."""

    def test_add_request_hash_new(self):
        """Should return True for new hash."""
        checkpoint = RunCheckpoint()
        assert add_request_hash(checkpoint, "hash1") is True

    def test_add_request_hash_duplicate(self):
        """Should return False for duplicate hash."""
        checkpoint = RunCheckpoint()
        add_request_hash(checkpoint, "hash1")
        assert add_request_hash(checkpoint, "hash1") is False


class TestMethodTracking:
    """Test method ID tracking."""

    def test_add_method_tried(self):
        """Should track tried methods."""
        checkpoint = RunCheckpoint()
        add_method_tried(checkpoint, "method1")
        assert "method1" in checkpoint.method_ids_tried

    def test_add_method_tried_no_duplicates(self):
        """Should not duplicate methods."""
        checkpoint = RunCheckpoint()
        add_method_tried(checkpoint, "method1")
        add_method_tried(checkpoint, "method1")
        assert checkpoint.method_ids_tried.count("method1") == 1


class TestCandidateBank:
    """Test candidate bank records."""

    def test_add_record_new(self):
        """Should return True for new record."""
        checkpoint = RunCheckpoint()
        record = {"candidate_id": "reward_c001", "diff": "test"}
        assert add_candidate_bank_record(checkpoint, record) is True

    def test_add_record_duplicate(self):
        """Should return False for duplicate record."""
        checkpoint = RunCheckpoint()
        record = {"candidate_id": "reward_c001", "diff": "test"}
        add_candidate_bank_record(checkpoint, record)
        assert add_candidate_bank_record(checkpoint, record) is False


class TestProposalOnlySummary:
    """Test proposal-only summary generation."""

    def test_summary_fields(self):
        """Should include all required fields."""
        checkpoint = RunCheckpoint(
            candidate_ids_seen=["reward_c001", "reward_c002"],
            completed_iterations=[1, 2],
        )
        add_candidate_bank_record(checkpoint, {
            "candidate_id": "reward_c001",
            "validation_passed": True,
        })

        summary = get_proposal_only_summary(checkpoint)

        assert summary["proposal_only"] is True
        assert summary["proposal_candidate_count"] == 2
        assert summary["validation_ready_candidate_count"] == 1
        assert summary["candidate_bank_size"] == 1
        assert summary["candidate_id_unique_count"] == 2
        assert summary["duplicate_candidate_id_count"] == 0
        assert summary["completed_iterations"] == 2
        assert summary["resume_supported"] is True

    def test_summary_duplicate_count(self):
        """Should count duplicate candidate IDs."""
        checkpoint = RunCheckpoint(
            candidate_ids_seen=["reward_c001", "reward_c001"],
        )
        summary = get_proposal_only_summary(checkpoint)
        assert summary["duplicate_candidate_id_count"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
