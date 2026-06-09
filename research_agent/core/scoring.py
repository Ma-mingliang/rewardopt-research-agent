"""Composite weighted scoring for optimizer accept/reject decisions.

Provides direction-aware normalization with division-by-zero protection,
hard threshold checking, and optional LLM dynamic judgment.
"""

from __future__ import annotations

from typing import Any

from research_agent.core.config import EvaluationConfig, EvalMetricConfig


EPSILON = 1e-6


def compute_composite_score(
    candidate_metrics: dict[str, float],
    baseline_metrics: dict[str, float],
    eval_config: EvaluationConfig,
) -> dict[str, Any]:
    """Compute composite weighted score for a candidate.

    Normalization (direction-aware, division-by-zero safe):
        maximize: score_i = candidate_val / max(baseline_val, epsilon) - 1
        minimize: score_i = 1 - candidate_val / max(baseline_val, epsilon)

    Composite = Σ(weight_i × score_i) / Σ(weight_i)

    Args:
        candidate_metrics: Flat dict {metric_name: value}.
        baseline_metrics: Flat dict {metric_name: value}.
        eval_config: Evaluation configuration with metrics and weights.

    Returns:
        Dict with:
            composite: float (overall score, > 0 means improvement)
            per_metric: dict with per-metric scores and details
            hard_violations: list of hard threshold violations
    """
    per_metric: dict[str, dict] = {}
    hard_violations: list[dict] = []
    weighted_sum = 0.0
    total_weight = 0.0

    for metric_def in eval_config.metrics:
        name = metric_def.name
        direction = metric_def.direction
        weight = metric_def.weight

        c_val = candidate_metrics.get(name)
        b_val = baseline_metrics.get(name)

        if c_val is None or b_val is None:
            per_metric[name] = {"status": "missing", "score": 0.0}
            continue

        # Direction-aware normalization
        if direction == "maximize":
            score = c_val / max(abs(b_val), EPSILON) - 1.0
        else:
            score = 1.0 - c_val / max(abs(b_val), EPSILON)

        per_metric[name] = {
            "status": "ok",
            "candidate": c_val,
            "baseline": b_val,
            "score": round(score, 6),
            "pct_change": round(score * 100, 2),
            "direction": direction,
            "weight": weight,
        }

        # Check hard thresholds
        if metric_def.hard_min is not None and c_val < metric_def.hard_min:
            hard_violations.append({
                "metric": name,
                "value": c_val,
                "threshold": metric_def.hard_min,
                "direction": "below_hard_min",
            })
        if metric_def.hard_max is not None and c_val > metric_def.hard_max:
            hard_violations.append({
                "metric": name,
                "value": c_val,
                "threshold": metric_def.hard_max,
                "direction": "above_hard_max",
            })

        weighted_sum += weight * score
        total_weight += weight

    # Normalize composite score
    composite = weighted_sum / max(total_weight, EPSILON)

    return {
        "composite": round(composite, 6),
        "per_metric": per_metric,
        "hard_violations": hard_violations,
        "has_hard_violation": len(hard_violations) > 0,
    }


def make_accept_decision(
    scoring_result: dict[str, Any],
    eval_config: EvaluationConfig,
    llm_score: float | None = None,
) -> dict[str, Any]:
    """Make accept/reject decision based on scoring and optional LLM judgment.

    Decision logic:
    1. If any hard threshold violated → REJECT
    2. Compute final_score = (1 - llm_weight) × composite + llm_weight × llm_score
    3. If final_score > composite_threshold → ACCEPT, else REJECT

    Args:
        scoring_result: Output from compute_composite_score.
        eval_config: Evaluation configuration.
        llm_score: Optional LLM score in [0, 1]. None if unavailable.

    Returns:
        Dict with:
            accepted: bool
            final_score: float
            composite: float
            llm_score: float or None
            llm_weight: float
            reason: str
    """
    composite = scoring_result["composite"]
    has_violation = scoring_result["has_hard_violation"]

    # Determine LLM score
    effective_llm_weight = eval_config.llm_weight
    if llm_score is None:
        # No LLM available, use 100% static
        effective_llm_weight = 0.0
        llm_score_used = 0.5  # neutral
    else:
        llm_score_used = llm_score

    # Compute final score
    final_score = (1 - effective_llm_weight) * composite + effective_llm_weight * (llm_score_used - 0.5)

    # Decision
    if has_violation:
        violation_names = [v["metric"] for v in scoring_result["hard_violations"]]
        return {
            "accepted": False,
            "final_score": round(final_score, 6),
            "composite": round(composite, 6),
            "llm_score": llm_score,
            "llm_weight": effective_llm_weight,
            "reason": f"Hard threshold violated: {', '.join(violation_names)}",
        }

    if final_score > eval_config.composite_threshold:
        return {
            "accepted": True,
            "final_score": round(final_score, 6),
            "composite": round(composite, 6),
            "llm_score": llm_score,
            "llm_weight": effective_llm_weight,
            "reason": f"Score {final_score:.4f} > threshold {eval_config.composite_threshold}",
        }

    return {
        "accepted": False,
        "final_score": round(final_score, 6),
        "composite": round(composite, 6),
        "llm_score": llm_score,
        "llm_weight": effective_llm_weight,
        "reason": f"Score {final_score:.4f} <= threshold {eval_config.composite_threshold}",
    }
