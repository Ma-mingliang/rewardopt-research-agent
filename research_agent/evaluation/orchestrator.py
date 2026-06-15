"""Staged evaluation orchestrator — entry points for config checks."""

from __future__ import annotations

from typing import Any


def should_use_staged_eval(config) -> bool:
    """Check if staged evaluation is enabled."""
    staged_cfg = getattr(config, "staged_evaluation", None)
    if staged_cfg is None:
        return False
    return getattr(staged_cfg, "enabled", False)


def get_staged_config(config) -> dict[str, Any]:
    """Extract staged eval config from AgentConfig as dict."""
    staged_cfg = getattr(config, "staged_evaluation", None)
    if staged_cfg is None:
        return {"enabled": False}
    return {
        "enabled": getattr(staged_cfg, "enabled", False),
        "max_static_repair_attempts": getattr(staged_cfg, "max_static_repair_attempts", 3),
        "max_runtime_repair_attempts": getattr(staged_cfg, "max_runtime_repair_attempts", 2),
        "smoke_train_enabled": getattr(staged_cfg, "smoke_train_enabled", True),
        "short_train_enabled": getattr(staged_cfg, "short_train_enabled", False),
        "medium_train_enabled": getattr(staged_cfg, "medium_train_enabled", False),
        "reject_on_infra_failure": getattr(staged_cfg, "reject_on_infra_failure", False),
        "uncertainty_policy": getattr(staged_cfg, "uncertainty_policy", "conservative"),
    }
