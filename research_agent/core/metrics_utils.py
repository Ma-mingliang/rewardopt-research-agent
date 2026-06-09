"""Metrics format utilities for consistent handling across the framework.

All metrics in the framework use flat format: {"reward": 930.85, "lateral_error": 0.004}
Nested format (from aggregate_metrics) is converted to flat when needed.
"""

from __future__ import annotations

from typing import Any


def flatten_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    """Convert nested metrics to flat format.

    Input:  {"reward": {"mean": 930.85, "std": 0.0, ...}}  (nested)
    Output: {"reward": 930.85}  (flat)

    Also handles already-flat metrics: {"reward": 930.85} -> {"reward": 930.85}
    """
    result = {}
    for name, val in metrics.items():
        if isinstance(val, dict):
            # Nested format: extract mean
            result[name] = float(val.get("mean", 0))
        elif isinstance(val, (int, float)):
            # Already flat
            result[name] = float(val)
        elif val is not None:
            # Try to convert
            try:
                result[name] = float(val)
            except (ValueError, TypeError):
                pass
    return result


def get_metric_value(metrics: dict[str, Any], name: str, default: float = 0.0) -> float:
    """Get a single metric value, handling both flat and nested formats."""
    val = metrics.get(name)
    if val is None:
        return default
    if isinstance(val, dict):
        return float(val.get("mean", default))
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def format_metrics_for_display(metrics: dict[str, Any]) -> str:
    """Format metrics dict to compact string for display."""
    parts = []
    for name, val in metrics.items():
        if isinstance(val, dict):
            mean = val.get("mean", 0)
        else:
            mean = float(val) if val is not None else 0
        parts.append(f"{name}={mean:.4f}")
    return ", ".join(parts) if parts else "(none)"


def format_metrics_for_changelog(metrics: dict[str, Any]) -> str:
    """Format metrics dict for CHANGELOG.md entry."""
    lines = []
    for name, val in metrics.items():
        if isinstance(val, dict):
            mean = val.get("mean", 0)
            std = val.get("std", 0)
            lines.append(f"- **{name}:** {mean:.4f} (std: {std:.4f})")
        else:
            mean = float(val) if val is not None else 0
            lines.append(f"- **{name}:** {mean:.4f}")
    return "\n".join(lines) if lines else "- (none)"
