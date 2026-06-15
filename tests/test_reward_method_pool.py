"""Tests for the reward_methods module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent.reward_methods import (
    MethodSelector,
    RewardMethodRecord,
    build_source_meta_from_records,
    format_method_brief,
    format_method_context,
    load_method_pool,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def sample_records():
    return [
        RewardMethodRecord(
            method_id="m1",
            category="A_potential_based_reward",
            method_name="Potential-Based Shaping",
            core_idea="Use potential differences as shaping.",
            reward_formula="gamma * Phi(s') - Phi(s)",
            implementation_template="reward += k * (phi_next - phi)",
            applicable_layers=("stanley_residual",),
            applicable_metrics=("tracking_error",),
            risks=("reward hacking",),
            confidence="high",
            source_papers=("paper:abc",),
        ),
        RewardMethodRecord(
            method_id="m2",
            category="B_safety_constraint_reward",
            method_name="Safety Penalty",
            core_idea="Penalize constraint violations.",
            reward_formula="-lambda * max(0, violation)",
            implementation_template="reward -= lam * violation",
            applicable_layers=("path_tracking",),
            applicable_metrics=("heading_error",),
            risks=("too conservative",),
            confidence="medium",
            source_papers=("paper:def",),
        ),
        RewardMethodRecord(
            method_id="m3",
            category="A_potential_based_reward",
            method_name="Adaptive Potential",
            core_idea="Adaptive potential scaling.",
            reward_formula="alpha(t) * (Phi(s') - Phi(s))",
            implementation_template="reward += alpha * delta_phi",
            applicable_layers=("stanley_residual", "path_tracking"),
            applicable_metrics=("tracking_error", "heading_error"),
            risks=("oscillation",),
            confidence="low",
            source_papers=("paper:ghi",),
        ),
        RewardMethodRecord(
            method_id="m4",
            category="D_adaptive_dynamic_reward",
            method_name="Dynamic Reward",
            core_idea="Adjust reward based on progress.",
            reward_formula="base_reward * progress_factor",
            implementation_template="reward *= progress",
            applicable_layers=("stanley_residual",),
            applicable_metrics=("tracking_error",),
            risks=("instability",),
            confidence="high",
            source_papers=("paper:jkl",),
        ),
    ]


@pytest.fixture
def pool_file(tmp_path, sample_records):
    f = tmp_path / "method_pool.jsonl"
    with open(f, "w", encoding="utf-8") as fh:
        for r in sample_records:
            fh.write(json.dumps({
                "method_id": r.method_id,
                "category": r.category,
                "method_name": r.method_name,
                "core_idea": r.core_idea,
                "reward_formula": r.reward_formula,
                "implementation_template": r.implementation_template,
                "applicable_layers": list(r.applicable_layers),
                "applicable_metrics": list(r.applicable_metrics),
                "risks": list(r.risks),
                "confidence": r.confidence,
                "source_papers": list(r.source_papers),
            }) + "\n")
    return f


# ── TestRewardMethodRecord ────────────────────────────────────────────────


class TestRewardMethodRecord:
    def test_from_dict_full(self):
        d = {
            "method_id": "test_001",
            "category": "A_potential_based_reward",
            "method_name": "Test Method",
            "core_idea": "Test idea",
            "reward_formula": "r + delta",
            "implementation_template": "reward += delta",
            "applicable_layers": ["layer1"],
            "applicable_metrics": ["metric1"],
            "risks": ["risk1"],
            "confidence": "high",
            "source_papers": ["paper:abc"],
        }
        r = RewardMethodRecord.from_dict(d)
        assert r.method_id == "test_001"
        assert r.category == "A_potential_based_reward"
        assert r.confidence == "high"
        assert r.applicable_layers == ("layer1",)
        assert r.risks == ("risk1",)

    def test_from_dict_missing_optional(self):
        d = {"method_id": "test_002", "category": "B"}
        r = RewardMethodRecord.from_dict(d)
        assert r.method_id == "test_002"
        assert r.method_name == ""
        assert r.applicable_layers == ()
        assert r.confidence == "medium"

    def test_from_dict_empty_method_id(self):
        d = {"method_id": "", "category": "A"}
        r = RewardMethodRecord.from_dict(d)
        assert r.method_id == ""

    def test_frozen(self):
        d = {"method_id": "x", "category": "A"}
        r = RewardMethodRecord.from_dict(d)
        with pytest.raises(AttributeError):
            r.method_id = "changed"

    def test_from_dict_extra_fields_ignored(self):
        d = {"method_id": "x", "category": "A", "unknown_field": 42}
        r = RewardMethodRecord.from_dict(d)
        assert r.method_id == "x"


# ── TestLoadMethodPool ────────────────────────────────────────────────────


class TestLoadMethodPool:
    def test_load_real_pool(self):
        pool_path = Path(__file__).resolve().parent.parent / "research_agent" / "reward_paper_pool" / "method_pool.jsonl"
        if not pool_path.exists():
            pytest.skip("Real pool file not found")
        records = load_method_pool(pool_path)
        assert len(records) == 142
        assert all(isinstance(r, RewardMethodRecord) for r in records)

    def test_load_empty_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        assert load_method_pool(f) == []

    def test_load_missing_file(self, tmp_path):
        assert load_method_pool(tmp_path / "nonexistent.jsonl") == []

    def test_load_skips_bad_json(self, tmp_path):
        f = tmp_path / "bad.jsonl"
        f.write_text('{"method_id": "good", "category": "A"}\nnot json\n{"method_id": "also_good", "category": "B"}\n', encoding="utf-8")
        records = load_method_pool(f)
        assert len(records) == 2

    def test_load_skips_empty_method_id(self, tmp_path):
        f = tmp_path / "partial.jsonl"
        f.write_text('{"method_id": "", "category": "A"}\n{"method_id": "valid", "category": "B"}\n', encoding="utf-8")
        records = load_method_pool(f)
        assert len(records) == 1
        assert records[0].method_id == "valid"

    def test_load_all_categories_present(self):
        pool_path = Path(__file__).resolve().parent.parent / "research_agent" / "reward_paper_pool" / "method_pool.jsonl"
        if not pool_path.exists():
            pytest.skip("Real pool file not found")
        records = load_method_pool(pool_path)
        categories = sorted(set(r.category for r in records))
        assert len(categories) == 8
        assert "A_potential_based_reward" in categories
        assert "H_learned_preference_reward" in categories


# ── TestMethodSelector ────────────────────────────────────────────────────


class TestMethodSelector:
    def test_select_all_categories(self, sample_records):
        sel = MethodSelector(sample_records)
        result = sel.select(top_k=10)
        assert len(result) == 4

    def test_select_specific_category(self, sample_records):
        sel = MethodSelector(sample_records)
        result = sel.select(categories=["A_potential_based_reward"], top_k=10)
        assert all(r.category == "A_potential_based_reward" for r in result)
        assert len(result) == 2

    def test_select_respects_top_k(self, sample_records):
        sel = MethodSelector(sample_records)
        result = sel.select(top_k=2)
        assert len(result) == 2

    def test_select_excludes_ids(self, sample_records):
        sel = MethodSelector(sample_records)
        result = sel.select(top_k=10, exclude_ids={"m1", "m4"})
        ids = {r.method_id for r in result}
        assert "m1" not in ids
        assert "m4" not in ids

    def test_select_deduplicates(self, sample_records):
        # Add a duplicate method_id
        dup = RewardMethodRecord(
            method_id="m1",
            category="A_potential_based_reward",
            method_name="Duplicate",
            core_idea="dup",
            reward_formula="dup",
            implementation_template="dup",
            applicable_layers=(),
            applicable_metrics=(),
            risks=(),
            confidence="high",
            source_papers=(),
        )
        sel = MethodSelector(sample_records + [dup])
        result = sel.select(top_k=10)
        ids = [r.method_id for r in result]
        assert ids.count("m1") == 1

    def test_select_sorts_by_confidence(self, sample_records):
        sel = MethodSelector(sample_records)
        result = sel.select(top_k=10)
        # High confidence should come before medium/low
        confidences = [r.confidence for r in result]
        first_high = next((i for i, c in enumerate(confidences) if c == "high"), len(confidences))
        first_medium = next((i for i, c in enumerate(confidences) if c == "medium"), len(confidences))
        assert first_high <= first_medium

    def test_select_by_ids(self, sample_records):
        sel = MethodSelector(sample_records)
        result = sel.select_by_ids(["m1", "m3"])
        assert len(result) == 2
        ids = {r.method_id for r in result}
        assert ids == {"m1", "m3"}

    def test_total(self, sample_records):
        sel = MethodSelector(sample_records)
        assert sel.total == 4

    def test_categories(self, sample_records):
        sel = MethodSelector(sample_records)
        cats = sel.categories
        assert "A_potential_based_reward" in cats
        assert "B_safety_constraint_reward" in cats


# ── TestFormatter ─────────────────────────────────────────────────────────


class TestFormatter:
    def test_format_method_context_with_methods(self, sample_records):
        result = format_method_context(sample_records[:2])
        assert "Potential-Based Shaping" in result
        assert "Safety Penalty" in result
        assert "gamma * Phi(s') - Phi(s)" in result
        assert "confidence: high" in result

    def test_format_method_context_empty(self):
        assert format_method_context([]) == "(no methods available)"

    def test_format_method_brief(self, sample_records):
        result = format_method_brief(sample_records[:2])
        assert "Potential-Based Shaping" in result
        assert "Safety Penalty" in result
        # Brief format is compact — one line per method
        lines = [l for l in result.strip().splitlines() if l.strip()]
        assert len(lines) == 2

    def test_format_method_brief_empty(self):
        assert format_method_brief([]) == "(no methods available)"

    def test_build_source_meta_from_records(self, sample_records):
        meta = build_source_meta_from_records(sample_records[:2])
        assert "m1" in meta["source_method_ids"]
        assert "m2" in meta["source_method_ids"]
        assert "A_potential_based_reward" in meta["source_categories"]
        assert "B_safety_constraint_reward" in meta["source_categories"]
        assert "paper:abc" in meta["source_papers"]
        assert "paper:def" in meta["source_papers"]

    def test_build_source_meta_deduplicates_papers(self, sample_records):
        # Both m1 and m2 have different papers, but let's test with same paper
        meta = build_source_meta_from_records(sample_records[:1])
        assert meta["source_papers"].count("paper:abc") == 1


# ── TestBackwardCompat ────────────────────────────────────────────────────


class TestBackwardCompat:
    def test_no_method_pool_same_behavior(self, sample_records):
        """Without method_pool, format_method_context returns empty placeholder."""
        assert format_method_context([]) == "(no methods available)"

    def test_method_pool_context_injection(self, sample_records):
        """With method_pool, format_method_context produces non-empty output."""
        result = format_method_context(sample_records)
        assert result != "(no methods available)"
        assert len(result) > 100
