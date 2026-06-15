"""Reward method pool: schema, loader, selector, formatter."""

from research_agent.reward_methods.formatter import (
    build_source_meta_from_records,
    format_method_brief,
    format_method_context,
)
from research_agent.reward_methods.loader import load_method_pool
from research_agent.reward_methods.schema import RewardMethodRecord
from research_agent.reward_methods.selector import MethodSelector

__all__ = [
    "RewardMethodRecord",
    "load_method_pool",
    "MethodSelector",
    "format_method_context",
    "format_method_brief",
    "build_source_meta_from_records",
]
