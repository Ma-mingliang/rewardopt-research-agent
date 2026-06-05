"""Task classification: identify research task types from project understanding."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from research_agent.core.config import AgentConfig
from research_agent.core.llm_client import LLMClient
from research_agent.core.output import ok_response
from research_agent.core.state import advance_phase, read_state_json, write_state_json
from research_agent.interfaces.front_agent_contract import require_phase
from research_agent.interfaces.json_protocol import write_classification_json

# All known task types
AVAILABLE_TASK_TYPES = [
    "reward_optimization",
    "controller_residual_optimization",
    "safety_constraint_optimization",
    "algorithm_selection",
    "observation_optimization",
    "action_space_optimization",
    "curriculum_learning",
    "hpo",
]

CLASSIFY_SYSTEM_PROMPT = """You are a research task classifier for RL and control projects.
Given a project understanding report, classify the research tasks into predefined categories.
Return JSON only."""

CLASSIFY_USER_PROMPT = """Project understanding:
{project_understanding}

Available task types: {available_task_types}

Return JSON:
{{
  "task_types": ["<type1>", "<type2>"],
  "confidence": <0-1>,
  "recommended_strategies": ["<strategy1>"],
  "not_recommended": ["<type1>"]
}}"""


def classify_task(
    work_dir: Path,
    config: AgentConfig,
    llm_client: LLMClient | None = None,
) -> dict:
    """Classify research tasks based on project understanding.

    Falls back to rule engine if LLM is unavailable (confidence capped at 0.6).

    Args:
        work_dir: .research-agent work directory.
        config: Agent configuration.
        llm_client: LLM client (created from config if None).

    Returns:
        Response dict with task classification.
    """
    require_phase(work_dir, "understood")

    state = read_state_json(work_dir)

    # Load project understanding
    understanding_path = work_dir / "reports" / "project_understanding.json"
    understanding = state.get("project_understanding", {})
    if understanding_path.exists() and understanding_path.stat().st_size > 0:
        import json
        with open(understanding_path, encoding="utf-8") as f:
            try:
                understanding = json.load(f)
            except json.JSONDecodeError:
                pass  # Use state fallback

    # Try LLM classification
    fallback = None
    result: dict[str, Any] = {}

    if llm_client is None:
        llm_client = LLMClient(
            config.llm.model_dump(),
            log_path=work_dir / "logs" / "llm_calls.jsonl",
        )

    try:
        response = llm_client.call(
            system_prompt=CLASSIFY_SYSTEM_PROMPT,
            user_prompt=CLASSIFY_USER_PROMPT.format(
                project_understanding=understanding,
                available_task_types=AVAILABLE_TASK_TYPES,
            ),
            max_tokens=4096,
        )
        result = response.parsed or {}
    except Exception:
        # Fallback to rule engine
        result = _rule_engine_classify(understanding)
        fallback = "rule_engine"

    output = ok_response({
        "task_types": result.get("task_types", []),
        "confidence": result.get("confidence", 0.0),
        "recommended_strategies": result.get("recommended_strategies", []),
        "not_recommended": result.get("not_recommended", []),
    })
    if fallback:
        output["fallback"] = fallback

    # Write report
    write_classification_json(work_dir, output)

    # Update state
    state = read_state_json(work_dir)
    state["task_classification"] = {
        "task_types": output["task_types"],
        "confidence": output["confidence"],
        "report": "reports/task_classification.json",
    }
    state = advance_phase(state, "classified")
    write_state_json(work_dir, state)

    return output


def _rule_engine_classify(understanding: dict) -> dict:
    """Rule-based classification fallback. Confidence capped at 0.6."""
    project_types = understanding.get("project_type", [])
    affinity = understanding.get("optimizer_affinity", [])
    opt_targets = understanding.get("optimizable_targets", [])

    task_types = []
    strategies = []

    if "residual_rl" in project_types or "residual_control" in affinity:
        task_types.append("controller_residual_optimization")
        strategies.append("residual-aware reward")

    if any(t.get("type") == "reward_function" for t in opt_targets) or "reward" in affinity:
        task_types.append("reward_optimization")
        strategies.append("safety-aware tracking reward")

    if "safety" in str(understanding).lower():
        task_types.append("safety_constraint_optimization")
        strategies.append("potential-based tracking reward")

    if not task_types:
        task_types.append("reward_optimization")
        strategies.append("general reward optimization")

    not_recommended = [
        t for t in AVAILABLE_TASK_TYPES
        if t not in task_types and t not in ("hpo", "curriculum_learning")
    ]

    return {
        "task_types": task_types,
        "confidence": min(0.6, 0.4 + 0.1 * len(task_types)),
        "recommended_strategies": strategies,
        "not_recommended": not_recommended,
    }
