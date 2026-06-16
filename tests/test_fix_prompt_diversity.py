"""Tests for FIX_PROMPT diversity propagation (v0.8.2)."""

from __future__ import annotations

import pytest


class TestSemanticFixPromptTemplates:
    def test_semantic_fix_system_prompt_importable(self):
        from research_agent.agents.reward_agent.prompts import SEMANTIC_FIX_SYSTEM_PROMPT
        assert "reward function optimizer" in SEMANTIC_FIX_SYSTEM_PROMPT.lower()
        assert "cosmetic" in SEMANTIC_FIX_SYSTEM_PROMPT.lower()

    def test_semantic_fix_prompt_importable(self):
        from research_agent.agents.reward_agent.prompts import SEMANTIC_FIX_PROMPT
        assert "{diversity_context}" in SEMANTIC_FIX_PROMPT
        assert "{previous_diff}" in SEMANTIC_FIX_PROMPT
        assert "{line_numbered_context}" in SEMANTIC_FIX_PROMPT
        assert "{existing_reward_terms}" in SEMANTIC_FIX_PROMPT

    def test_semantic_fix_prompt_anti_cosmetic(self):
        from research_agent.agents.reward_agent.prompts import SEMANTIC_FIX_SYSTEM_PROMPT
        lower = SEMANTIC_FIX_SYSTEM_PROMPT.lower()
        assert "blank line" in lower or "cosmetic" in lower
        assert "reward term" in lower

    def test_semantic_fix_prompt_requires_reward_change(self):
        from research_agent.agents.reward_agent.prompts import SEMANTIC_FIX_PROMPT
        lower = SEMANTIC_FIX_PROMPT.lower()
        assert "reward term" in lower


class TestFixPromptDiversityContext:
    def test_diversity_context_builder(self):
        """Test that _build_diversity_context_string produces correct output."""
        from research_agent.agents.reward_agent.nodes import _build_diversity_context_string

        state = {
            "previous_candidate_diffs": ["diff1", "diff2"],
            "previous_method_ids": ["m1", "m2"],
        }
        result = _build_diversity_context_string(state)
        assert "Previously tried method IDs" in result
        assert "m1" in result
        assert "m2" in result
        assert "2 patch(es)" in result

    def test_diversity_context_empty_state(self):
        from research_agent.agents.reward_agent.nodes import _build_diversity_context_string

        state = {}
        result = _build_diversity_context_string(state)
        assert "No previous candidates" in result


class TestContextProposeDiversityRules:
    def test_context_propose_has_diversity_rules(self):
        from research_agent.agents.reward_agent.prompts import CONTEXT_PROPOSE_USER_PROMPT
        assert "CRITICAL DIVERSITY RULES" in CONTEXT_PROPOSE_USER_PROMPT
        assert "cosmetic" in CONTEXT_PROPOSE_USER_PROMPT.lower()
        assert "reward term" in CONTEXT_PROPOSE_USER_PROMPT.lower()

    def test_context_propose_has_diversity_context(self):
        from research_agent.agents.reward_agent.prompts import CONTEXT_PROPOSE_USER_PROMPT
        assert "{diversity_context}" in CONTEXT_PROPOSE_USER_PROMPT
