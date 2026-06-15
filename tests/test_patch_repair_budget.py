"""Tests for patch repair budget, strategy switching, and repeated-error fail-fast."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from research_agent.core.config import PatchRepairConfig
from research_agent.core.patch_repair import (
    RepairAttemptTracker,
    RepairStrategy,
    make_error_signature,
)


class TestPatchRepairConfig:
    def test_defaults(self):
        cfg = PatchRepairConfig()
        assert cfg.max_patch_apply_repair_attempts == 6
        assert cfg.max_same_error_repair_attempts == 2
        assert cfg.fail_fast_on_repeated_error is True
        assert cfg.max_strategy_attempts["direct_diff_repair"] == 2
        assert cfg.max_strategy_attempts["local_hunk_regeneration"] == 2
        assert cfg.max_strategy_attempts["idea_regeneration_from_baseline"] == 2

    def test_custom_values(self):
        cfg = PatchRepairConfig(
            max_patch_apply_repair_attempts=10,
            max_same_error_repair_attempts=3,
        )
        assert cfg.max_patch_apply_repair_attempts == 10
        assert cfg.max_same_error_repair_attempts == 3


class TestRepairAttemptTracker:
    def test_initial_state(self):
        tracker = RepairAttemptTracker()
        assert tracker.total_attempts == 0
        assert tracker.should_continue() is True
        assert tracker.current_strategy == RepairStrategy.DIRECT_DIFF_REPAIR

    def test_max_total_attempts(self):
        tracker = RepairAttemptTracker(max_total_attempts=3)
        sig = "IndentationError|env.py|983|test"
        for _ in range(3):
            tracker.record_attempt(sig, tracker.current_strategy)
        assert tracker.should_continue() is False

    def test_same_error_triggers_strategy_switch(self):
        tracker = RepairAttemptTracker(max_same_error_attempts=2)
        sig = "IndentationError|env.py|983|expected an indented block"
        tracker.record_attempt(sig, RepairStrategy.DIRECT_DIFF_REPAIR)
        assert tracker.should_switch_strategy(sig) is False
        tracker.record_attempt(sig, RepairStrategy.DIRECT_DIFF_REPAIR)
        assert tracker.should_switch_strategy(sig) is True

    def test_strategy_switch_advances(self):
        tracker = RepairAttemptTracker()
        assert tracker.current_strategy == RepairStrategy.DIRECT_DIFF_REPAIR
        new_strategy = tracker.switch_strategy()
        assert new_strategy == RepairStrategy.LOCAL_HUNK_REGENERATION
        assert tracker.current_strategy == RepairStrategy.LOCAL_HUNK_REGENERATION

    def test_all_strategies_exhausted(self):
        tracker = RepairAttemptTracker()
        tracker.switch_strategy()  # -> LOCAL_HUNK
        tracker.switch_strategy()  # -> IDEA_REGEN
        final = tracker.switch_strategy()  # -> past end
        assert tracker.current_strategy_index >= len(tracker.strategies)
        assert tracker.should_continue() is False

    def test_different_errors_dont_trigger_switch(self):
        tracker = RepairAttemptTracker(max_same_error_attempts=2)
        sig1 = "IndentationError|env.py|983|error1"
        sig2 = "SyntaxError|env.py|100|error2"
        tracker.record_attempt(sig1, RepairStrategy.DIRECT_DIFF_REPAIR)
        tracker.record_attempt(sig2, RepairStrategy.DIRECT_DIFF_REPAIR)
        assert tracker.should_switch_strategy(sig1) is False

    def test_diagnostics(self):
        tracker = RepairAttemptTracker()
        sig = "IndentationError|env.py|983|test"
        tracker.record_attempt(sig, RepairStrategy.DIRECT_DIFF_REPAIR)
        tracker.record_attempt(sig, RepairStrategy.DIRECT_DIFF_REPAIR)

        diag = tracker.get_diagnostics()
        assert diag["total_attempts"] == 2
        assert diag["last_error_signature"] == sig
        assert diag["error_counts"][sig] == 2
        assert "direct_diff_repair" in diag["strategy_history"]

    def test_error_counts_across_strategies(self):
        tracker = RepairAttemptTracker(max_same_error_attempts=2)
        sig = "IndentationError|env.py|983|test"
        # Same error across different strategies
        tracker.record_attempt(sig, RepairStrategy.DIRECT_DIFF_REPAIR)
        tracker.record_attempt(sig, RepairStrategy.LOCAL_HUNK_REGENERATION)
        # Count is 2 regardless of strategy
        assert tracker.error_counts[sig] == 2


class TestStrategyBehavior:
    """Test that the three strategies are distinct and properly ordered."""

    def test_strategy_order(self):
        strategies = [
            RepairStrategy.DIRECT_DIFF_REPAIR,
            RepairStrategy.LOCAL_HUNK_REGENERATION,
            RepairStrategy.IDEA_REGENERATION_FROM_BASELINE,
        ]
        assert strategies[0].value == "direct_diff_repair"
        assert strategies[1].value == "local_hunk_regeneration"
        assert strategies[2].value == "idea_regeneration_from_baseline"

    def test_tracker_starts_with_direct(self):
        tracker = RepairAttemptTracker()
        assert tracker.current_strategy == RepairStrategy.DIRECT_DIFF_REPAIR


class TestCLIFlagsIntegration:
    """Test that CLI flags properly configure PatchRepairConfig."""

    def test_config_fields_exist(self):
        from research_agent.core.config import AgentConfig
        cfg = AgentConfig()
        assert hasattr(cfg, "patch_repair")
        assert isinstance(cfg.patch_repair, PatchRepairConfig)
        assert cfg.patch_repair.max_patch_apply_repair_attempts == 6

    def test_config_from_dict(self):
        from research_agent.core.config import AgentConfig
        cfg = AgentConfig(patch_repair={"max_patch_apply_repair_attempts": 10})
        assert cfg.patch_repair.max_patch_apply_repair_attempts == 10


class TestObservabilityIntegration:
    """Test that patch repair events are properly tracked in RunObserver."""

    def test_observer_has_patch_repair_fields(self, tmp_path: Path):
        from research_agent.core.observability import RunObserver

        run_dir = tmp_path / "runs"
        observer = RunObserver(
            run_log_dir=str(run_dir),
            optimizer="test",
            project_path=str(tmp_path),
        )

        observer.emit("patch_repair_start", candidate_id="test_c001", max_attempts=6)
        observer.emit("patch_repair_attempt", candidate_id="test_c001", strategy="direct_diff_repair", attempt=1)
        observer.emit("patch_repair_strategy_switch", candidate_id="test_c001",
                       old_strategy="direct_diff_repair", new_strategy="local_hunk_regeneration")
        observer.emit("patch_repair_exhausted", candidate_id="test_c001", total_attempts=6)
        observer.emit("repeated_patch_repair_error", candidate_id="test_c001",
                       last_error_signature="IndentationError|env.py|983|test")

        observer.track_patch_repair(attempts=6, exhausted=True, repeated_error=True)
        observer.close()

        # Verify events.jsonl
        events_path = observer.run_dir / "events.jsonl"
        lines = events_path.read_text(encoding="utf-8").strip().split("\n")
        event_types = [json.loads(line)["event_type"] for line in lines]
        assert "patch_repair_start" in event_types
        assert "patch_repair_attempt" in event_types
        assert "patch_repair_strategy_switch" in event_types
        assert "patch_repair_exhausted" in event_types
        assert "repeated_patch_repair_error" in event_types

        # Verify summary.json
        summary_path = observer.run_dir / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["patch_repair_attempts_total"] == 6
        assert summary["patch_repair_exhausted_count"] == 1
        assert summary["repeated_patch_repair_error_count"] == 1
        assert summary["max_patch_apply_repair_attempts"] == 6

    def test_observer_tracks_success(self, tmp_path: Path):
        from research_agent.core.observability import RunObserver

        run_dir = tmp_path / "runs"
        observer = RunObserver(
            run_log_dir=str(run_dir),
            optimizer="test",
            project_path=str(tmp_path),
        )

        observer.emit("patch_repair_success", candidate_id="test_c001", total_attempts=2)
        observer.track_patch_repair(attempts=2, success=True, strategy="direct_diff_repair")
        observer.close()

        summary_path = observer.run_dir / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["syntax_repair_success_count"] == 1
        assert summary["repair_strategy_counts"]["direct_diff_repair"] == 1


class TestRepeatedErrorFailFast:
    """Test the repeated-error fail-fast mechanism."""

    def test_same_error_signature_detected(self):
        sig1 = make_error_signature("IndentationError", "env.py", 983, "expected an indented block")
        sig2 = make_error_signature("IndentationError", "env.py", 983, "expected an indented block")
        assert sig1 == sig2

    def test_different_errors_not_matched(self):
        sig1 = make_error_signature("IndentationError", "env.py", 983, "expected an indented block")
        sig2 = make_error_signature("SyntaxError", "env.py", 100, "invalid syntax")
        assert sig1 != sig2

    def test_fail_fast_at_2_attempts(self):
        tracker = RepairAttemptTracker(max_same_error_attempts=2, max_total_attempts=6)
        sig = "IndentationError|env.py|983|expected an indented block"

        # First attempt
        tracker.record_attempt(sig, RepairStrategy.DIRECT_DIFF_REPAIR)
        assert tracker.should_switch_strategy(sig) is False
        assert tracker.should_continue() is True

        # Second attempt - same error
        tracker.record_attempt(sig, RepairStrategy.DIRECT_DIFF_REPAIR)
        assert tracker.should_switch_strategy(sig) is True

        # Switch strategy
        new_strategy = tracker.switch_strategy()
        assert new_strategy == RepairStrategy.LOCAL_HUNK_REGENERATION

    def test_full_exhaustion_scenario(self):
        """Simulate: same error repeats through all 3 strategies, exhausts at 6 attempts."""
        tracker = RepairAttemptTracker(max_same_error_attempts=2, max_total_attempts=6)
        sig = "IndentationError|env.py|983|expected an indented block"

        strategies_used = []
        while tracker.should_continue():
            strategy = tracker.current_strategy
            tracker.record_attempt(sig, strategy)
            strategies_used.append(strategy.value)

            if tracker.should_switch_strategy(sig):
                tracker.switch_strategy()

        assert len(strategies_used) <= 6
        assert "direct_diff_repair" in strategies_used
        assert "local_hunk_regeneration" in strategies_used
        assert "idea_regeneration_from_baseline" in strategies_used

    def test_does_not_call_30_times(self):
        """Verify the tracker respects max_total_attempts=6, not 30."""
        tracker = RepairAttemptTracker(max_total_attempts=6)
        sig = "IndentationError|env.py|983|test"
        count = 0
        while tracker.should_continue():
            tracker.record_attempt(sig, tracker.current_strategy)
            count += 1
        assert count == 6
        assert count < 30
