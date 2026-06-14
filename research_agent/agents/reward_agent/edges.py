"""Conditional routing functions for the reward proposal agent."""

from __future__ import annotations

from research_agent.agents.reward_agent.state import RewardAgentState


def should_continue_or_return(state: RewardAgentState) -> str:
    """Decide next step after validation.

    Returns:
        "return" — validation passed or limits exhausted
        "try_auto_indent" — indentation error, try auto-fix
        "llm_fix" — other error, ask LLM to fix
    """
    if state.get("validation_ok"):
        return "return"

    if state.get("attempt", 0) >= state.get("max_attempts", 3):
        return "return"

    if state.get("total_llm_calls", 0) >= state.get("max_total_llm_calls", 6):
        return "return"

    error = (state.get("validation_error") or state.get("last_error") or "").lower()
    if "indent" in error or "expected an indented block" in error:
        return "try_auto_indent"

    return "llm_fix"
