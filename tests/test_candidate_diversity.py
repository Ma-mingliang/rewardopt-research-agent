"""Tests for candidate diversity diagnostics (v0.8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent.core.executor import _compute_patch_similarity, _check_candidate_diversity
from research_agent.core.observability import RunObserver
from research_agent.core.paper_sampler import PaperSampler


SAMPLE_DIFF_A = (
    "--- a/env.py\n"
    "+++ b/env.py\n"
    "@@ -954,6 +954,8 @@\n"
    "     tracking_reward = -1.0 * current_error**2\n"
    "+    safety_penalty = -0.1 * max(0, angular_velocity - threshold)\n"
    "+    reward += safety_penalty\n"
    "     return reward\n"
)

SAMPLE_DIFF_B = (
    "--- a/env.py\n"
    "+++ b/env.py\n"
    "@@ -954,6 +954,8 @@\n"
    "     tracking_reward = -1.0 * current_error**2\n"
    "+    energy_penalty = -0.05 * action**2\n"
    "+    reward += energy_penalty\n"
    "     return reward\n"
)

SAMPLE_DIFF_C = (
    "--- a/env.py\n"
    "+++ b/env.py\n"
    "@@ -997,2 +997,3 @@\n"
    "         return reward\n"
    "+    \n"
    "     def reset(self, seed=None, options=None):\n"
)


class TestComputePatchSimilarity:
    def test_identical_diffs(self):
        sim = _compute_patch_similarity(SAMPLE_DIFF_A, SAMPLE_DIFF_A)
        assert sim == 1.0

    def test_different_diffs(self):
        sim = _compute_patch_similarity(SAMPLE_DIFF_A, SAMPLE_DIFF_B)
        assert 0.0 <= sim < 0.5  # Different added lines

    def test_empty_diffs(self):
        assert _compute_patch_similarity("", "") == 0.0
        assert _compute_patch_similarity("", SAMPLE_DIFF_A) == 0.0
        assert _compute_patch_similarity(SAMPLE_DIFF_A, "") == 0.0

    def test_cosmetic_vs_substantive(self):
        sim = _compute_patch_similarity(SAMPLE_DIFF_A, SAMPLE_DIFF_C)
        assert sim < 0.5  # Very different changes

    def test_no_changes(self):
        empty_diff = "--- a/env.py\n+++ b/env.py\n@@ -1,3 +1,3 @@\n line1\n line2\n line3\n"
        assert _compute_patch_similarity(empty_diff, empty_diff) == 1.0


class TestCheckCandidateDiversity:
    def test_duplicate_detected(self, tmp_path: Path):
        observer = RunObserver(tmp_path, "test", tmp_path)
        candidate = type("C", (), {"patch_diff": SAMPLE_DIFF_A})()
        prev = [{"patch_diff": SAMPLE_DIFF_A, "source_method_ids": ["method_1"]}]

        _check_candidate_diversity(
            observer, candidate, [{"method_id": "method_1"}],
            prev, candidate_id="c002",
        )

        # Check events
        with open(observer.events_path) as f:
            events = [json.loads(l) for l in f if l.strip()]
        dup_events = [e for e in events if e["event_type"] == "candidate_duplicate_detected"]
        assert len(dup_events) == 1
        assert dup_events[0]["similarity"] >= 0.95

    def test_low_diversity_detected(self, tmp_path: Path):
        observer = RunObserver(tmp_path, "test", tmp_path)
        # Base diff with 4 changed lines
        base_diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -954,6 +954,10 @@\n"
            "     tracking_reward = -1.0 * current_error**2\n"
            "+    safety_penalty = -0.1 * max(0, angular_velocity - threshold)\n"
            "+    reward += safety_penalty\n"
            "+    energy_penalty = -0.05 * action**2\n"
            "+    progress_bonus = 0.1 * step_ratio\n"
            "     return reward\n"
        )
        # Similar diff: shares 4 of 5 changed lines (Jaccard = 0.8)
        similar_diff = (
            "--- a/env.py\n"
            "+++ b/env.py\n"
            "@@ -954,6 +954,11 @@\n"
            "     tracking_reward = -1.0 * current_error**2\n"
            "+    safety_penalty = -0.1 * max(0, angular_velocity - threshold)\n"
            "+    reward += safety_penalty\n"
            "+    energy_penalty = -0.05 * action**2\n"
            "+    progress_bonus = 0.1 * step_ratio\n"
            "+    smoothness_bonus = 0.02 * (1 - jerk)\n"
            "     return reward\n"
        )
        candidate = type("C", (), {"patch_diff": similar_diff})()
        prev = [{"patch_diff": base_diff, "source_method_ids": ["method_1"]}]

        _check_candidate_diversity(
            observer, candidate, [{"method_id": "method_1"}],
            prev, candidate_id="c002",
        )

        with open(observer.events_path) as f:
            events = [json.loads(l) for l in f if l.strip()]
        div_events = [e for e in events if e["event_type"] == "candidate_low_diversity"]
        assert len(div_events) == 1

    def test_diverse_candidates_no_event(self, tmp_path: Path):
        observer = RunObserver(tmp_path, "test", tmp_path)
        candidate = type("C", (), {"patch_diff": SAMPLE_DIFF_B})()
        prev = [{"patch_diff": SAMPLE_DIFF_A, "source_method_ids": ["method_1"]}]

        _check_candidate_diversity(
            observer, candidate, [{"method_id": "method_2"}],
            prev, candidate_id="c002",
        )

        with open(observer.events_path) as f:
            events = [json.loads(l) for l in f if l.strip()]
        dup_events = [e for e in events if e["event_type"] == "candidate_duplicate_detected"]
        low_events = [e for e in events if e["event_type"] == "candidate_low_diversity"]
        assert len(dup_events) == 0
        assert len(low_events) == 0

    def test_method_overlap_detected(self, tmp_path: Path):
        observer = RunObserver(tmp_path, "test", tmp_path)
        candidate = type("C", (), {"patch_diff": SAMPLE_DIFF_B})()
        prev = [{"patch_diff": SAMPLE_DIFF_A, "source_method_ids": ["method_1"]}]

        _check_candidate_diversity(
            observer, candidate, [{"method_id": "method_1"}],
            prev, candidate_id="c002",
        )

        with open(observer.events_path) as f:
            events = [json.loads(l) for l in f if l.strip()]
        checked = [e for e in events if e["event_type"] == "candidate_diversity_checked"]
        assert len(checked) == 1
        assert checked[0]["is_duplicate_method"] is True

    def test_observer_summary_fields(self, tmp_path: Path):
        observer = RunObserver(tmp_path, "test", tmp_path)
        observer.track_candidate_diversity(
            current_diff=SAMPLE_DIFF_A,
            current_method_ids=["m1"],
            similarity_score=0.98,
            is_duplicate_patch=True,
        )
        observer.track_candidate_diversity(
            current_diff=SAMPLE_DIFF_B,
            current_method_ids=["m2"],
            similarity_score=0.3,
        )
        observer.write_summary()

        with open(observer.summary_path) as f:
            summary = json.load(f)
        assert summary["candidate_diversity_enabled"] is True
        assert summary["duplicate_patch_count"] == 1
        assert summary["candidate_pair_similarity_max"] == 0.98

    def test_summary_includes_diversity_fields(self, tmp_path: Path):
        observer = RunObserver(tmp_path, "test", tmp_path)
        observer.write_summary()
        with open(observer.summary_path) as f:
            summary = json.load(f)
        assert "candidate_diversity_enabled" in summary
        assert "candidate_pair_similarity_max" in summary
        assert "duplicate_patch_count" in summary
        assert "duplicate_method_count" in summary
        assert "low_diversity_candidate_count" in summary
        assert "method_selection_fallback_count" in summary


class TestMethodSelectionFallback:
    def _make_pool(self, tmp_path: Path):
        """Create a minimal method pool for testing."""
        pool_dir = tmp_path / "pool"
        pool_dir.mkdir()

        methods = [
            {"method_id": "m1", "category": "A_potential", "confidence": "high", "source_papers": ["p1"]},
            {"method_id": "m2", "category": "A_potential", "confidence": "medium", "source_papers": ["p2"]},
            {"method_id": "m3", "category": "B_safety", "confidence": "high", "source_papers": ["p3"]},
            {"method_id": "m4", "category": "B_safety", "confidence": "medium", "source_papers": ["p4"]},
        ]
        with open(pool_dir / "method_pool.jsonl", "w") as f:
            for m in methods:
                f.write(json.dumps(m) + "\n")

        taxonomy = {"categories": {
            "A_potential": {"priority": "S", "description": "Potential-based"},
            "B_safety": {"priority": "A", "description": "Safety constraint"},
        }}
        import yaml
        with open(pool_dir / "taxonomy.yaml", "w") as f:
            yaml.dump(taxonomy, f)

        (pool_dir / "paper_pool.jsonl").write_text("")
        return pool_dir

    def test_batch_fills_from_next_category(self, tmp_path: Path):
        pool_dir = self._make_pool(tmp_path)
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "logs").mkdir()

        sampler = PaperSampler(pool_dir, work_dir)
        sampler.set_active_categories(["A_potential", "B_safety"])

        # Get batch of 3, but A_potential only has 2 methods
        batch, fallback = sampler.get_next_batch(batch_size=3)
        assert len(batch) == 3
        assert fallback is True

        method_ids = [m["method_id"] for m in batch]
        assert "m1" in method_ids
        assert "m2" in method_ids
        assert "m3" in method_ids  # From B_safety via fallback

    def test_no_fallback_when_sufficient(self, tmp_path: Path):
        pool_dir = self._make_pool(tmp_path)
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "logs").mkdir()

        sampler = PaperSampler(pool_dir, work_dir)
        sampler.set_active_categories(["A_potential", "B_safety"])

        batch, fallback = sampler.get_next_batch(batch_size=2)
        assert len(batch) == 2
        assert fallback is False

    def test_all_tried_returns_empty(self, tmp_path: Path):
        pool_dir = self._make_pool(tmp_path)
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "logs").mkdir()

        # Mark all as tried
        tried_path = work_dir / "logs" / "tried_methods.jsonl"
        with open(tried_path, "w") as f:
            for mid in ["m1", "m2", "m3", "m4"]:
                f.write(json.dumps({"method_id": mid}) + "\n")

        sampler = PaperSampler(pool_dir, work_dir)
        sampler.set_active_categories(["A_potential", "B_safety"])

        batch, fallback = sampler.get_next_batch(batch_size=2)
        assert batch == []
        assert fallback is False

    def test_no_duplicate_ids_in_batch(self, tmp_path: Path):
        pool_dir = self._make_pool(tmp_path)
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "logs").mkdir()

        sampler = PaperSampler(pool_dir, work_dir)
        sampler.set_active_categories(["A_potential", "B_safety"])

        batch, _ = sampler.get_next_batch(batch_size=4)
        ids = [m["method_id"] for m in batch]
        assert len(ids) == len(set(ids))  # No duplicates


class TestPromptDiversityContext:
    def test_context_prompt_includes_diversity(self):
        """Verify the context-grounded prompt format includes diversity_context."""
        from research_agent.agents.reward_agent.prompts import CONTEXT_PROPOSE_USER_PROMPT
        # Check that {diversity_context} is in the template
        assert "{diversity_context}" in CONTEXT_PROPOSE_USER_PROMPT

    def test_system_prompt_no_markdown(self):
        """Verify system prompt instructs no markdown."""
        from research_agent.agents.reward_agent.prompts import CONTEXT_PROPOSE_SYSTEM_PROMPT
        assert "no markdown" in CONTEXT_PROPOSE_SYSTEM_PROMPT.lower() or \
               "no markdown fences" in CONTEXT_PROPOSE_SYSTEM_PROMPT.lower()


class TestEnvHashUnchanged:
    def test_env_hash_unchanged(self):
        from research_agent.core.eval_diagnostics import hash_file
        env_path = Path("D:/research-agent/HRRL2/env.py")
        if env_path.exists():
            h = hash_file(env_path)
            assert h == "e19703467be71e20"


class TestBaselineGuardNotBypassed:
    def test_baseline_guard_not_disabled(self):
        from research_agent.core.config import AgentConfig
        cfg = AgentConfig()
        assert not hasattr(cfg, "skip_baseline_guard")


class TestFullEvalProtocolUnchanged:
    def test_eval_protocol_not_modified(self):
        from pathlib import Path
        executor_path = Path("D:/research-agent/research_agent/core/executor.py")
        if executor_path.exists():
            content = executor_path.read_text(encoding="utf-8")
            assert "full_eval" in content or "run_full_eval" in content
