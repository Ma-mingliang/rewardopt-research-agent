"""Optimizer plugin registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from research_agent.optimizers.base import BaseOptimizer

# Lazy registry: maps optimizer name to (module_path, class_name)
_OPTIMIZER_MODULES: dict[str, tuple[str, str]] = {
    "reward": ("research_agent.optimizers.reward.optimizer", "RewardOptimizer"),
    "reward_langgraph": ("research_agent.agents.reward_agent.optimizer", "LangGraphRewardOptimizer"),
    "residual_control": ("research_agent.optimizers.residual_control.optimizer", "ResidualControlOptimizer"),
    "hpo": ("research_agent.optimizers.hpo.optimizer", "HPOOptimizer"),
    "curriculum": ("research_agent.optimizers.curriculum.optimizer", "CurriculumOptimizer"),
    "observation": ("research_agent.optimizers.observation.optimizer", "ObservationOptimizer"),
    "action_space": ("research_agent.optimizers.action_space.optimizer", "ActionSpaceOptimizer"),
}


def get_optimizer_class(name: str) -> type[BaseOptimizer]:
    """Get optimizer class by name with lazy import.

    Args:
        name: Optimizer name (e.g., "reward", "hpo").

    Returns:
        The optimizer class.

    Raises:
        KeyError: If optimizer name is not registered.
    """
    if name not in _OPTIMIZER_MODULES:
        raise KeyError(f"Unknown optimizer: {name}. Available: {list(_OPTIMIZER_MODULES.keys())}")

    module_path, class_name = _OPTIMIZER_MODULES[name]
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def list_optimizers() -> list[str]:
    """Return list of all registered optimizer names."""
    return list(_OPTIMIZER_MODULES.keys())
