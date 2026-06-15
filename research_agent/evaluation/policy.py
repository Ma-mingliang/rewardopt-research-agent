"""RL-aware screening policy for staged evaluation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from research_agent.evaluation.stages import StageDecision


@dataclass
class ScreeningPolicy:
    uncertainty_policy: str = "conservative"
    min_seeds_for_decision: int = 2
    max_cv_threshold: float = 0.5
    min_improvement_pct: float = 0.01


def _coefficient_of_variation(values: list[float]) -> float:
    """Compute CV = std/mean. Returns inf if mean is zero."""
    if not values:
        return float("inf")
    mean = sum(values) / len(values)
    if abs(mean) < 1e-12:
        return float("inf")
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance) / abs(mean)


def evaluate_short_train(
    metrics_by_seed: dict[int, dict[str, float]],
    baseline_metrics: dict[str, float],
    policy: ScreeningPolicy | None = None,
) -> StageDecision:
    """Evaluate short train results with uncertainty awareness.

    Rules (conservative policy):
    - If ALL seeds crash/timeout -> REJECT_CATASTROPHIC
    - If at least one seed succeeds with non-zero metrics -> PROMOTE
    - NEVER reject based on a single seed's poor metrics (RL instability)

    Returns one of: PROMOTE, REJECT_CATASTROPHIC
    """
    if policy is None:
        policy = ScreeningPolicy()

    if not metrics_by_seed:
        return StageDecision.REJECT_CATASTROPHIC

    successful = {
        seed: m for seed, m in metrics_by_seed.items()
        if m and any(v != 0 for v in m.values())
    }

    if not successful:
        return StageDecision.REJECT_CATASTROPHIC

    return StageDecision.PROMOTE


def evaluate_medium_train(
    metrics_by_seed: dict[int, dict[str, float]],
    baseline_metrics: dict[str, float],
    policy: ScreeningPolicy | None = None,
) -> StageDecision:
    """Evaluate medium train results for confirmation.

    Similar to short_train but with variance checking across seeds.
    If metrics show high variance across seeds -> NEEDS_MORE_SEEDS
    Otherwise -> PROMOTE to full_eval
    """
    if policy is None:
        policy = ScreeningPolicy()

    if not metrics_by_seed:
        return StageDecision.REJECT_CATASTROPHIC

    successful = {
        seed: m for seed, m in metrics_by_seed.items()
        if m and any(v != 0 for v in m.values())
    }

    if not successful:
        return StageDecision.REJECT_CATASTROPHIC

    if len(successful) < policy.min_seeds_for_decision:
        return StageDecision.NEEDS_MORE_SEEDS

    # Check variance across seeds for primary metric
    primary_keys = [k for k in next(iter(successful.values())) if not k.startswith("_")]
    if not primary_keys:
        return StageDecision.PROMOTE

    first_key = primary_keys[0]
    values = [m.get(first_key, 0.0) for m in successful.values()]
    cv = _coefficient_of_variation(values)

    if cv > policy.max_cv_threshold:
        return StageDecision.NEEDS_MORE_SEEDS

    return StageDecision.PROMOTE
