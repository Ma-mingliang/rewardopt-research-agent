"""LangGraph StateGraph construction for the reward proposal agent."""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from research_agent.agents.reward_agent.edges import should_continue_or_return
from research_agent.agents.reward_agent.nodes import (
    auto_indent_node,
    initialize_node,
    llm_fix_node,
    propose_node,
    return_candidate_node,
    validate_node,
)
from research_agent.agents.reward_agent.state import RewardAgentState


@lru_cache(maxsize=1)
def build_reward_proposal_graph() -> StateGraph:
    """Build and compile the reward proposal graph.

    Graph flow:
        START → initialize → propose → validate → {should_continue_or_return}
            ├─ "return" → return_candidate → END
            ├─ "try_auto_indent" → auto_indent → validate
            └─ "llm_fix" → llm_fix → validate
    """
    graph = StateGraph(RewardAgentState)

    # Add nodes
    graph.add_node("initialize", initialize_node)
    graph.add_node("propose", propose_node)
    graph.add_node("validate", validate_node)
    graph.add_node("auto_indent", auto_indent_node)
    graph.add_node("llm_fix", llm_fix_node)
    graph.add_node("return_candidate", return_candidate_node)

    # Edges
    graph.add_edge(START, "initialize")
    graph.add_edge("initialize", "propose")
    graph.add_edge("propose", "validate")

    # Conditional routing after validation
    graph.add_conditional_edges(
        "validate",
        should_continue_or_return,
        {
            "return": "return_candidate",
            "try_auto_indent": "auto_indent",
            "llm_fix": "llm_fix",
        },
    )

    # After auto_indent or llm_fix, go back to validate
    graph.add_edge("auto_indent", "validate")
    graph.add_edge("llm_fix", "validate")

    # Terminal
    graph.add_edge("return_candidate", END)

    return graph.compile()
