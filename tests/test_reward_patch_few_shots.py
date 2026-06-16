"""Tests for reward patch few-shot examples (v0.8.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_agent.agents.reward_agent.prompts import load_few_shot_examples


EXAMPLES_PATH = Path(__file__).resolve().parent.parent / "docs" / "examples" / "reward_patch_few_shots.yaml"


class TestLoadFewShotExamples:
    def test_file_exists(self):
        assert EXAMPLES_PATH.exists(), f"Few-shot examples not found: {EXAMPLES_PATH}"

    def test_loads_valid_yaml(self):
        result = load_few_shot_examples(str(EXAMPLES_PATH))
        assert result is not None
        assert len(result) > 100
        assert "Example:" in result

    def test_contains_all_examples(self):
        result = load_few_shot_examples(str(EXAMPLES_PATH))
        assert "pbrs_potential_shaping" in result
        assert "tracking_error_penalty" in result
        assert "control_energy_penalty" in result
        assert "stability_fall_penalty" in result

    def test_contains_before_after_diff(self):
        result = load_few_shot_examples(str(EXAMPLES_PATH))
        assert "Before:" in result
        assert "After:" in result
        assert "Diff:" in result

    def test_contains_semantic_metadata(self):
        result = load_few_shot_examples(str(EXAMPLES_PATH))
        assert "Why semantic:" in result
        assert "Forbidden cosmetic:" in result
        assert "Required changed terms:" in result

    def test_contains_available_variables(self):
        result = load_few_shot_examples(str(EXAMPLES_PATH))
        assert "Available variables used:" in result

    def test_missing_file_returns_fallback(self):
        result = load_few_shot_examples("/nonexistent/path/examples.yaml")
        assert result is not None
        assert "No few-shot" in result or "raw text" in result

    def test_default_path(self):
        # Default path should resolve correctly
        result = load_few_shot_examples()
        assert result is not None
        assert "Example:" in result


class TestFewShotExampleContent:
    """Verify the content quality of each few-shot example."""

    @pytest.fixture(autouse=True)
    def load_yaml(self):
        import yaml
        with open(EXAMPLES_PATH, encoding="utf-8") as f:
            self.data = yaml.safe_load(f)
        self.examples = self.data.get("examples", [])

    def test_has_four_examples(self):
        assert len(self.examples) == 4

    def test_each_example_has_required_fields(self):
        required = [
            "id", "method_category", "intent", "available_variables_used",
            "before_snippet", "after_snippet", "diff", "why_semantic",
            "forbidden_cosmetic", "required_changed_terms",
        ]
        for ex in self.examples:
            for field in required:
                assert field in ex, f"Example {ex.get('id')} missing field: {field}"

    def test_diffs_are_nonempty(self):
        for ex in self.examples:
            diff = ex.get("diff", "")
            assert len(diff.strip()) > 10, f"Example {ex['id']} has empty diff"
            assert "@@" in diff, f"Example {ex['id']} diff missing @@ hunk header"

    def test_diffs_have_additions(self):
        for ex in self.examples:
            diff = ex.get("diff", "")
            assert any(l.startswith("+") for l in diff.splitlines()), \
                f"Example {ex['id']} diff has no addition lines"

    def test_diffs_have_deletions_or_context(self):
        for ex in self.examples:
            diff = ex.get("diff", "")
            has_context = any(l.startswith(" ") for l in diff.splitlines() if l.strip())
            has_deletion = any(l.startswith("-") for l in diff.splitlines())
            assert has_context or has_deletion, \
                f"Example {ex['id']} diff has no context or deletion lines"

    def test_before_after_snippets_nonempty(self):
        for ex in self.examples:
            assert len(ex.get("before_snippet", "").strip()) > 0, \
                f"Example {ex['id']} has empty before_snippet"
            assert len(ex.get("after_snippet", "").strip()) > 0, \
                f"Example {ex['id']} has empty after_snippet"

    def test_required_changed_terms_nonempty(self):
        for ex in self.examples:
            terms = ex.get("required_changed_terms", [])
            assert len(terms) > 0, f"Example {ex['id']} has no required_changed_terms"

    def test_available_variables_nonempty(self):
        for ex in self.examples:
            vars_list = ex.get("available_variables_used", [])
            assert len(vars_list) > 0, f"Example {ex['id']} has no available_variables_used"
