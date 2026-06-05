"""Metric parser: extract metrics from eval stdout/stderr/files using regex."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from research_agent.core.config import AgentConfig


def parse_metrics(
    stdout: str,
    stderr: str,
    config: AgentConfig,
    work_dir: Path | None = None,
) -> dict[str, float | None]:
    """Parse metrics from eval command output.

    Extraction order:
    1. JSON artifact file (if work_dir and artifact path configured)
    2. stdout regex matches (per metric_regex config)
    3. stderr regex matches (fallback)

    Args:
        stdout: Eval command stdout text.
        stderr: Eval command stderr text.
        config: Agent configuration with metric_regex.
        work_dir: Optional work dir for artifact file lookup.

    Returns:
        Dict mapping metric names to float values (None if not found).
    """
    metric_regex = config.metrics.metric_regex
    if not metric_regex:
        return {}

    result: dict[str, float | None] = {}

    # Try JSON artifact first
    artifact_metrics = _try_parse_artifact(work_dir, metric_regex)
    if artifact_metrics:
        for name, value in artifact_metrics.items():
            result[name] = value
        # Fill missing from regex
        for metric_name in metric_regex:
            if metric_name not in result:
                regex_result = _extract_from_text(stdout, stderr, metric_name, metric_regex[metric_name])
                result[metric_name] = regex_result
        return result

    # Regex extraction from stdout/stderr
    for metric_name, pattern in metric_regex.items():
        result[metric_name] = _extract_from_text(stdout, stderr, metric_name, pattern)

    return result


def _try_parse_artifact(
    work_dir: Path | None,
    metric_regex: dict[str, Any],
) -> dict[str, float | None] | None:  # noqa: E501
    """Try to parse metrics from a JSON artifact file."""
    if work_dir is None:
        return None

    artifact_path = work_dir / "artifacts" / "eval_result.json"
    if not artifact_path.exists():
        return None

    try:
        with open(artifact_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(data, dict):
        return None

    result: dict[str, float | None] = {}
    for metric_name in metric_regex:
        value = _deep_get(data, metric_name)
        if value is not None:
            try:
                result[metric_name] = float(value)
            except (ValueError, TypeError):
                result[metric_name] = None
        else:
            result[metric_name] = None

    return result


def _deep_get(data: dict, key: str) -> Any:
    """Get value from nested dict using dot notation or direct key."""
    # Direct key
    if key in data:
        return data[key]
    # Dot notation
    parts = key.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _extract_from_text(
    stdout: str,
    stderr: str,
    metric_name: str,
    pattern: str,
) -> float | None:
    """Extract a metric value from stdout or stderr using regex pattern."""
    # Try stdout first
    value = _regex_search(stdout, pattern)
    if value is not None:
        return value

    # Fallback to stderr
    value = _regex_search(stderr, pattern)
    if value is not None:
        return value

    return None


def _regex_search(text: str, pattern: str) -> float | None:
    """Search text for regex pattern and return first numeric group as float."""
    if not text or not pattern:
        return None

    try:
        match = re.search(pattern, text)
    except re.error:
        return None

    if match is None:
        return None

    # Try to extract numeric value from groups
    for group in match.groups():
        if group is not None:
            try:
                return float(group)
            except (ValueError, TypeError):
                continue

    # Try the entire match
    try:
        return float(match.group(0))
    except (ValueError, TypeError):
        return None


def check_safety_metrics(
    metrics: dict[str, float | None],
    config: AgentConfig,
) -> dict[str, Any]:
    """Check safety metrics against thresholds.

    Returns:
        Dict with 'safe' (bool), 'violations' (list), and 'safety_scores' (dict).
    """
    safety_metrics = config.metrics.safety
    safety_weights = config.metrics.safety_weights
    violations: list[dict] = []
    safety_scores: dict[str, float] = {}

    for sm in safety_metrics:
        name = sm.get("name", "") if isinstance(sm, dict) else str(sm)
        direction = sm.get("direction", "maximize") if isinstance(sm, dict) else "maximize"
        hard_min = sm.get("hard_min", None) if isinstance(sm, dict) else None
        hard_max = sm.get("hard_max", None) if isinstance(sm, dict) else None

        value = metrics.get(name)
        if value is None:
            continue

        safety_scores[name] = value

        if hard_min is not None and value < hard_min:
            violations.append({
                "metric": name,
                "value": value,
                "threshold": hard_min,
                "direction": "below_hard_min",
            })
        if hard_max is not None and value > hard_max:
            violations.append({
                "metric": name,
                "value": value,
                "threshold": hard_max,
                "direction": "above_hard_max",
            })

    return {
        "safe": len(violations) == 0,
        "violations": violations,
        "safety_scores": safety_scores,
    }
