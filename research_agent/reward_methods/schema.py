"""Reward method record schema."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RewardMethodRecord:
    """A single reward shaping method from the method pool."""

    method_id: str
    category: str
    method_name: str
    core_idea: str
    reward_formula: str
    implementation_template: str
    applicable_layers: tuple[str, ...]
    applicable_metrics: tuple[str, ...]
    risks: tuple[str, ...]
    confidence: str
    source_papers: tuple[str, ...]

    @classmethod
    def from_dict(cls, d: dict) -> RewardMethodRecord:
        """Parse from a JSONL record dict. Tolerant of missing/extra fields."""
        to_tuple = lambda v: tuple(v) if isinstance(v, list) else ()
        return cls(
            method_id=d.get("method_id", ""),
            category=d.get("category", ""),
            method_name=d.get("method_name", ""),
            core_idea=d.get("core_idea", ""),
            reward_formula=d.get("reward_formula", ""),
            implementation_template=d.get("implementation_template", ""),
            applicable_layers=to_tuple(d.get("applicable_layers")),
            applicable_metrics=to_tuple(d.get("applicable_metrics")),
            risks=to_tuple(d.get("risks")),
            confidence=d.get("confidence", "medium"),
            source_papers=to_tuple(d.get("source_papers")),
        )
