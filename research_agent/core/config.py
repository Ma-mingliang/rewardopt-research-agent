"""Configuration loading and validation with Pydantic."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str = "openai_compatible"
    model: str = "mimo-v2.5-pro"
    base_url: str = "https://token-plan-sgp.xiaomimimo.com/v1"
    api_key_env: str = "MIMO_API_KEY"
    timeout_seconds: int = 120
    max_retries: int = 3
    retry_delay_seconds: int = 5
    max_tokens: int = 8192
    qps: float = 2.0


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str = ""
    python_file_globs: list[str] = Field(default_factory=lambda: ["**/*.py"])
    ignore_dirs: list[str] = Field(default_factory=lambda: [
        ".git", ".venv", "venv", "__pycache__",
        "logs", "runs", "wandb", "checkpoints", "node_modules",
    ])


class FrontAgentConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    required: bool = True
    allowed_callers: list[str] = Field(default_factory=lambda: [
        "claude_code", "hermes", "codex", "openclaw",
    ])
    require_objective_before_plan: bool = True
    require_json_protocol: bool = True


class ObjectiveConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    description: str = ""
    focus: list[str] = Field(default_factory=list)
    primary_score_threshold: float = 0.05
    hard_primary_regression_policy: str = "reject"
    mean_reward_role: str = "diagnostic_only"


class ConstraintsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    forbidden_changes: list[str] = Field(default_factory=lambda: [
        "algorithm_body", "network_architecture", "optimizer",
        "loss", "replay_buffer", "base_controller_law",
    ])
    require_human_review_for: list[str] = Field(default_factory=lambda: [
        "observation_space_change", "action_space_change",
        "termination_logic_change", "algorithm_selection_change",
    ])


class BudgetConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    wall_clock_hours: int = 336
    gpu_hours: int | None = None
    max_candidates: int | None = None
    max_full_evals: int | None = None
    stop_when_budget_exhausted: bool = True


class JointValidationConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lqr_degradation_threshold: float = 0.90
    stanley_degradation_threshold: float = 0.90
    combined_score_threshold: float = 0.85


class MetricThresholdsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_min_improvement_pct: float = 0.01
    default_max_regression_pct: float = 0.10


class MetricsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    primary: list[dict] = Field(default_factory=list)
    safety: list[dict] = Field(default_factory=list)
    diagnostic: list[dict] = Field(default_factory=list)
    metric_regex: dict[str, Any] = Field(default_factory=dict)
    metric_thresholds: MetricThresholdsConfig = Field(default_factory=MetricThresholdsConfig)
    safety_weights: dict[str, float] = Field(default_factory=dict)
    cv_threshold: float = 0.3
    instability_weight: float = 0.5
    screening_threshold: float = 0.0


class LiteratureConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    require_before_propose: bool = True
    top_k_selected_papers: int = 5
    min_relevance_score: float = 0.60
    max_queries: int = 10
    max_results_per_query: int = 20
    max_extracted_ideas: int = 20
    deterministic_selection: bool = True
    classification_categories: list[str] = Field(default_factory=lambda: [
        "reward shaping", "penalty and constraint design",
        "curriculum reward", "robotics locomotion reward",
        "control energy and smoothness",
        "reward hacking and specification gaming",
        "residual control", "path tracking control",
    ])


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    train_command: str = ""
    eval_command: str = ""
    max_steps: int = 20000
    screening_seeds: list[int] = Field(default_factory=lambda: [42])
    full_eval_seeds: list[int] = Field(default_factory=lambda: [42, 123, 456])
    confirmation_seeds: list[int] = Field(default_factory=lambda: [789, 101112])
    timeout_seconds_per_seed: int = 3600


class GitConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    auto_commit_best: bool = True
    auto_push_best: bool = False
    push_remote: str = "origin"
    push_branch: str | None = None


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    json_output: bool = Field(default=False, alias="json")
    quiet: bool = False
    log_level: str = "INFO"


class AgentConfig(BaseModel):
    """Top-level configuration for research-agent."""

    model_config = ConfigDict(extra="ignore")

    llm: LLMConfig = Field(default_factory=LLMConfig)
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    front_agent: FrontAgentConfig = Field(default_factory=FrontAgentConfig)
    objective: ObjectiveConfig = Field(default_factory=ObjectiveConfig)
    constraints: ConstraintsConfig = Field(default_factory=ConstraintsConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    joint_validation: JointValidationConfig = Field(default_factory=JointValidationConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    literature: LiteratureConfig = Field(default_factory=LiteratureConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)


def load_config(work_dir: Path) -> AgentConfig:
    """Load and validate config from work_dir/config.yaml.

    Falls back to configs/default.yaml for missing keys (Pydantic defaults handle this).
    Project-level config.yaml overrides defaults.
    """
    default_path = Path(__file__).parent.parent.parent / "configs" / "default.yaml"
    config_path = work_dir / "config.yaml"

    raw: dict[str, Any] = {}
    if default_path.exists():
        with open(default_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            overrides = yaml.safe_load(f) or {}
        raw = _deep_merge(raw, overrides)

    return AgentConfig.model_validate(raw)


def _deep_merge(base: dict, overrides: dict) -> dict:
    """Deep merge overrides into base. overrides wins on conflict."""
    result = base.copy()
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
