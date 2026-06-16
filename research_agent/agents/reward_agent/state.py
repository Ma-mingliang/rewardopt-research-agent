"""Reward agent state definition."""

from __future__ import annotations

from typing import Any, TypedDict


class RewardAgentState(TypedDict, total=False):
    """State for the reward proposal LangGraph agent."""

    # Input
    allowed_changes: list[dict]
    forbidden_changes: list[str]
    baseline_metrics: dict[str, dict[str, float]]
    ideas: list[dict]
    candidate_id: str
    source_meta: dict
    execution_python: str

    # Code context
    reward_code: str
    file_name: str

    # Context-grounded proposal (v0.7.3)
    proposal_context: Any  # ProposalContext or None

    # Proposal
    current_diff: str | None
    current_description: str | None
    current_rationale: str | None

    # Validation
    validation_ok: bool
    validation_error: str | None
    error_line: int | None

    # Loop control
    attempt: int
    max_attempts: int
    empty_diff_attempt: int
    max_empty_diff_attempts: int
    total_llm_calls: int
    max_total_llm_calls: int
    last_error: str | None

    # Method pool context
    method_pool_context: str
    method_pool_ids: list[str]

    # Diversity context (v0.8)
    previous_candidate_diffs: list[str]
    previous_method_ids: list[str]

    # Output
    final_candidate_status: str  # "ready" | "noop" | "exhausted"
    patch_diff: str | None
    description: str | None
    rationale: str | None
