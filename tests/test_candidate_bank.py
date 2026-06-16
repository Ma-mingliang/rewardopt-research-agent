"""Tests for candidate bank loading and diversity analysis (v0.8.6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent.core.candidate_bank import (
    CandidateRecord,
    DiversityAnalysis,
    RankedCandidate,
    compute_diversity_score,
    compute_proposal_source_penalty,
    compute_reward_term_complexity,
    compute_semantic_rank_score,
    load_candidate_bank,
    rank_candidates,
    write_diversity_summary,
    write_ranked_bank,
)


def _make_record(**overrides) -> CandidateRecord:
    defaults = {
        "candidate_id": "test_c001",
        "iteration": 1,
        "method_ids": ["method_a"],
        "method_categories": ["A_potential_based_reward"],
        "selected_template": "template_a",
        "diff_hash": "abc123",
        "diff_preview": "--- a/env.py\n+++ b/env.py\n@@ -1,3 +1,5 @@\n+shaping = -0.1 * error",
        "reward_terms_added": ["shaping = -0.1 * error"],
        "reward_terms_modified": [],
        "semantic_gate_decision": "passed",
        "syntax_valid": True,
        "validation_passed": True,
        "proposal_source": "semantic_regeneration",
        "rejection_reason": "",
        "duplicate_similarity_max": 0.0,
        "train_called": False,
        "full_eval_called": False,
    }
    defaults.update(overrides)
    return CandidateRecord(**defaults)


class TestLoadCandidateBank:
    def test_load_valid_file(self, tmp_path):
        path = tmp_path / "bank.jsonl"
        record = _make_record()
        with open(path, "w") as f:
            f.write(json.dumps({
                "candidate_id": record.candidate_id,
                "iteration": record.iteration,
                "method_ids": record.method_ids,
                "method_categories": record.method_categories,
                "selected_template": record.selected_template,
                "diff_hash": record.diff_hash,
                "diff_preview": record.diff_preview,
                "reward_terms_added": record.reward_terms_added,
                "reward_terms_modified": record.reward_terms_modified,
                "semantic_gate_decision": record.semantic_gate_decision,
                "syntax_valid": record.syntax_valid,
                "validation_passed": record.validation_passed,
                "proposal_source": record.proposal_source,
                "rejection_reason": record.rejection_reason,
                "duplicate_similarity_max": record.duplicate_similarity_max,
                "train_called": record.train_called,
                "full_eval_called": record.full_eval_called,
            }) + "\n")
        records = load_candidate_bank(path)
        assert len(records) == 1
        assert records[0].candidate_id == "test_c001"
        assert records[0].syntax_valid is True

    def test_load_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.jsonl"
        records = load_candidate_bank(path)
        assert records == []

    def test_load_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        records = load_candidate_bank(path)
        assert records == []

    def test_load_multiple_records(self, tmp_path):
        path = tmp_path / "bank.jsonl"
        with open(path, "w") as f:
            for i in range(3):
                r = _make_record(candidate_id=f"c{i:03d}", diff_hash=f"hash{i}")
                f.write(json.dumps({
                    "candidate_id": r.candidate_id,
                    "iteration": r.iteration,
                    "method_ids": r.method_ids,
                    "method_categories": r.method_categories,
                    "selected_template": r.selected_template,
                    "diff_hash": r.diff_hash,
                    "diff_preview": r.diff_preview,
                    "reward_terms_added": r.reward_terms_added,
                    "reward_terms_modified": r.reward_terms_modified,
                    "semantic_gate_decision": r.semantic_gate_decision,
                    "syntax_valid": r.syntax_valid,
                    "validation_passed": r.validation_passed,
                    "proposal_source": r.proposal_source,
                    "rejection_reason": r.rejection_reason,
                    "duplicate_similarity_max": r.duplicate_similarity_max,
                    "train_called": r.train_called,
                    "full_eval_called": r.full_eval_called,
                }) + "\n")
        records = load_candidate_bank(path)
        assert len(records) == 3

    def test_load_skips_blank_lines(self, tmp_path):
        path = tmp_path / "bank.jsonl"
        r = _make_record()
        with open(path, "w") as f:
            f.write(json.dumps({
                "candidate_id": r.candidate_id, "iteration": r.iteration,
                "method_ids": r.method_ids, "method_categories": r.method_categories,
                "selected_template": r.selected_template, "diff_hash": r.diff_hash,
                "diff_preview": r.diff_preview, "reward_terms_added": r.reward_terms_added,
                "reward_terms_modified": r.reward_terms_modified,
                "semantic_gate_decision": r.semantic_gate_decision,
                "syntax_valid": r.syntax_valid, "validation_passed": r.validation_passed,
                "proposal_source": r.proposal_source, "rejection_reason": r.rejection_reason,
                "duplicate_similarity_max": r.duplicate_similarity_max,
                "train_called": r.train_called, "full_eval_called": r.full_eval_called,
            }) + "\n\n\n")
        records = load_candidate_bank(path)
        assert len(records) == 1


class TestComputeRewardTermComplexity:
    def test_empty_terms(self):
        assert compute_reward_term_complexity([], []) == 1.0

    def test_simple_term(self):
        score = compute_reward_term_complexity(["x = -0.1 * error"], [])
        assert 0.0 < score < 0.5

    def test_conditional_term(self):
        score = compute_reward_term_complexity(
            ["if angular_velocity > 2.0:", "    penalty = -5.0"], [],
        )
        assert score > 0.1

    def test_many_terms(self):
        terms = [f"x{i} = -0.1 * error" for i in range(10)]
        score = compute_reward_term_complexity(terms, [])
        assert score > 0.3


class TestComputeProposalSourcePenalty:
    def test_primary(self):
        assert compute_proposal_source_penalty("primary") == 0.0

    def test_semantic_regeneration(self):
        assert compute_proposal_source_penalty("semantic_regeneration") == 0.05

    def test_syntax_repair(self):
        assert compute_proposal_source_penalty("syntax_repair") == 0.1

    def test_template_fallback(self):
        assert compute_proposal_source_penalty("template_fallback") == 0.2

    def test_unknown_source(self):
        assert compute_proposal_source_penalty("unknown") == 0.15


class TestComputeSemanticRankScore:
    def test_failed_validation_returns_zero(self):
        r = _make_record(validation_passed=False)
        assert compute_semantic_rank_score(r, {}, 1) == 0.0

    def test_valid_candidate(self):
        r = _make_record()
        score = compute_semantic_rank_score(r, {"template_a": 1}, 1)
        assert 0.4 < score < 1.0

    def test_template_novelty_bonus(self):
        r = _make_record(selected_template="rare_template")
        counts = {"rare_template": 1, "common_template": 5}
        score_rare = compute_semantic_rank_score(r, counts, 5)
        r2 = _make_record(selected_template="common_template")
        score_common = compute_semantic_rank_score(r2, counts, 5)
        assert score_rare > score_common

    def test_more_terms_higher_score(self):
        r1 = _make_record(reward_terms_added=["x = 1"])
        r2 = _make_record(reward_terms_added=["x = 1", "y = 2", "z = 3"])
        s1 = compute_semantic_rank_score(r1, {"template_a": 1}, 1)
        s2 = compute_semantic_rank_score(r2, {"template_a": 1}, 1)
        assert s2 >= s1


class TestComputeDiversityScore:
    def test_empty_records(self):
        analysis = compute_diversity_score([])
        assert analysis.total_candidates == 0
        assert analysis.diversity_score == 0.0

    def test_all_same_template(self):
        records = [_make_record(diff_hash=f"h{i}") for i in range(4)]
        analysis = compute_diversity_score(records)
        assert analysis.unique_templates == 1
        assert analysis.low_diversity is True

    def test_all_different_templates(self):
        records = [
            _make_record(selected_template=f"tpl_{i}", diff_hash=f"h{i}")
            for i in range(4)
        ]
        analysis = compute_diversity_score(records)
        assert analysis.unique_templates == 4
        assert analysis.low_diversity is False

    def test_reward_term_frequency(self):
        r1 = _make_record(reward_terms_added=["penalty = -1.0"], diff_hash="h1")
        r2 = _make_record(reward_terms_added=["penalty = -2.0"], diff_hash="h2")
        analysis = compute_diversity_score([r1, r2])
        assert "penalty" in analysis.reward_term_frequency
        assert analysis.reward_term_frequency["penalty"] == 2


class TestRankCandidates:
    def test_empty_records(self):
        assert rank_candidates([]) == []

    def test_ranking_order(self):
        r1 = _make_record(
            diff_hash="h1", proposal_source="primary",
            reward_terms_added=["a = 1", "b = 2", "c = 3"],
        )
        r2 = _make_record(
            diff_hash="h2", proposal_source="template_fallback",
            reward_terms_added=["x = 1"],
        )
        ranked = rank_candidates([r1, r2])
        assert len(ranked) == 2
        assert ranked[0].rank == 1
        assert ranked[1].rank == 2
        assert ranked[0].semantic_rank_score >= ranked[1].semantic_rank_score

    def test_ranks_assigned_sequentially(self):
        records = [_make_record(diff_hash=f"h{i}") for i in range(5)]
        ranked = rank_candidates(records)
        for i, rc in enumerate(ranked):
            assert rc.rank == i + 1


class TestWriteOutputs:
    def test_write_ranked_bank(self, tmp_path):
        r = _make_record()
        ranked = [RankedCandidate(record=r, rank=1, semantic_rank_score=0.6)]
        path = tmp_path / "ranked.jsonl"
        write_ranked_bank(path, ranked)
        assert path.exists()
        data = json.loads(path.read_text().strip())
        assert data["rank"] == 1
        assert data["semantic_rank_score"] == 0.6

    def test_write_diversity_summary(self, tmp_path):
        r = _make_record()
        analysis = compute_diversity_score([r])
        ranked = [RankedCandidate(record=r, rank=1, semantic_rank_score=0.6)]
        path = tmp_path / "summary.md"
        write_diversity_summary(path, analysis, ranked)
        assert path.exists()
        content = path.read_text()
        assert "Diversity Summary" in content
        assert "Rank" in content
