#!/usr/bin/env python3
"""Extract reward modification methods from normalized papers."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml

from pool_common import HRLL_LAYERS, keyword_hits, load_dotenv, load_taxonomy, pool_path, read_jsonl, truncate, write_jsonl

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _method_slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return slug[:80] or "reward_method"


def _layers_for(category: str, text: str) -> List[str]:
    lower = (text or "").lower()
    layers = []
    if category == "F_residual_aware_reward" or "residual" in lower:
        layers.extend(["lqr_residual", "stanley_residual"])
    if category in {"A_potential_based_reward", "C_curriculum_subgoal_reward", "D_adaptive_dynamic_reward"}:
        layers.extend(["path_tracking", "stanley_residual"])
    if category == "B_safety_constraint_reward" or "safety" in lower or "barrier" in lower:
        layers.append("safety_gate")
    if category == "E_hierarchical_reward":
        layers.extend(["lqr_residual", "stanley_residual", "balance_control"])
    if not layers:
        layers.append("path_tracking")
    return sorted(set(layers), key=HRLL_LAYERS.index)


def rule_based_method(paper: Dict[str, Any], category: str, taxonomy: Dict[str, Any]) -> Dict[str, Any]:
    meta = taxonomy["categories"][category]
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}"
    layers = _layers_for(category, text)
    method_name = meta.get("title", category)
    if category == "A_potential_based_reward":
        core = "Use potential differences, such as tracking error improvement, as a shaping term while preserving policy incentives."
        formula = "gamma * Phi(s_next) - Phi(s)"
        template = "tracking_improvement = abs(e_t) - abs(e_t1); reward += k_phi * tracking_improvement"
        metrics = ["tracking_error", "heading_error"]
    elif category == "B_safety_constraint_reward":
        core = "Gate task reward with explicit penalties for safety, constraint, or barrier violations."
        formula = "reward -= lambda_violation * max(0, constraint_value)"
        template = "reward -= collision_penalty if min_distance < safe_distance else 0.0"
        metrics = ["constraint_violation", "collision_distance", "risk_score"]
    elif category == "C_curriculum_subgoal_reward":
        core = "Reward stage progress and subgoal completion before exposing the full task objective."
        formula = "reward += beta_stage * progress_to_subgoal"
        template = "reward += stage_weight[current_stage] * (prev_dist_to_subgoal - dist_to_subgoal)"
        metrics = ["subgoal_distance", "stage_success", "progress"]
    elif category == "D_adaptive_dynamic_reward":
        core = "Adapt reward component weights as training progresses or as objective errors change."
        formula = "reward = sum(w_i(t) * r_i for i in components)"
        template = "weights = schedule(step, error_stats); reward = sum(weights[k] * terms[k] for k in terms)"
        metrics = ["training_step", "tracking_error", "constraint_violation"]
    elif category == "E_hierarchical_reward":
        core = "Separate high-level subtask or goal reward from low-level control reward."
        formula = "reward = manager_reward + worker_reward"
        template = "reward = goal_progress_reward + low_level_tracking_reward - control_cost"
        metrics = ["goal_progress", "tracking_error", "subtask_success"]
    elif category == "F_residual_aware_reward":
        core = "Keep the classical controller intact and penalize residual action magnitude or roughness."
        formula = "reward = task_reward - lambda_res * ||u_residual||^2"
        template = "u = u_base + u_res; reward -= lambda_res * dot(u_res, u_res) + lambda_smooth * norm(u_res - prev_u_res)"
        metrics = ["residual_norm", "tracking_error", "action_smoothness"]
    elif category == "G_llm_reward_generation":
        core = "Use an LLM to generate or refine executable reward code from task descriptions and training feedback."
        formula = "reward = execute(llm_generated_reward_code)"
        template = "reward_fn = load_candidate_reward_code(); reward = reward_fn(obs, action, next_obs, logs)"
        metrics = ["training_return", "success_rate", "reward_code_score"]
    else:
        core = "Train or infer a reward model from demonstrations, preferences, or human feedback."
        formula = "reward = reward_model(state, action)"
        template = "reward = reward_model.predict(obs, action); reward -= safety_penalty"
        metrics = ["preference_score", "demo_similarity", "model_uncertainty"]
    return {
        "method_id": f"{_method_slug(category)}_{_method_slug(paper.get('paper_id', paper.get('title', '')))}",
        "category": category,
        "source_papers": [paper.get("paper_id", "")],
        "method_name": method_name,
        "core_idea": core,
        "reward_formula": formula,
        "applicable_layers": layers,
        "applicable_metrics": metrics,
        "implementation_template": template,
        "risks": ["reward hacking if proxy metrics dominate task success", "must be gated against unsafe behavior"],
        "confidence": "medium",
    }


def _load_llm_client(base: Path):
    load_dotenv()
    cfg_path = REPO_ROOT / "config.yaml"
    if not cfg_path.exists():
        return None
    with open(cfg_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    try:
        from agent_llm_client import AgentLLMClient
    except Exception:
        return None
    client = AgentLLMClient(config.get("agent_pipeline", {}).get("llm", {}))
    return client if client.is_configured() else None


def _llm_extract(client: Any, paper: Dict[str, Any], category: str, taxonomy: Dict[str, Any]) -> Dict[str, Any] | None:
    prompt = {
        "category": category,
        "category_definition": taxonomy["categories"][category].get("title", category),
        "paper": {
            "paper_id": paper.get("paper_id"),
            "title": paper.get("title"),
            "abstract": truncate(paper.get("abstract", ""), 3500),
            "github_url": paper.get("github_url"),
        },
        "required_fields": [
            "method_name",
            "core_idea",
            "reward_formula",
            "applicable_layers",
            "applicable_metrics",
            "implementation_template",
            "risks",
            "confidence",
        ],
    }
    system = (
        "Extract one concrete reward modification method from the provided paper metadata. "
        "Use only the given title/abstract/README-level evidence. Return strict JSON."
    )
    try:
        result = client.call_json(system, json.dumps(prompt, ensure_ascii=False))
    except Exception:
        return None
    if not isinstance(result, dict) or not result.get("method_name") or not result.get("implementation_template"):
        return None
    confidence = result.get("confidence", "medium")
    if confidence == "high":
        confidence = "medium"
    return {
        "method_id": f"{_method_slug(category)}_{_method_slug(paper.get('paper_id', paper.get('title', '')))}",
        "category": category,
        "source_papers": [paper.get("paper_id", "")],
        "method_name": result.get("method_name", ""),
        "core_idea": result.get("core_idea", ""),
        "reward_formula": result.get("reward_formula", ""),
        "applicable_layers": [l for l in result.get("applicable_layers", []) if l in HRLL_LAYERS] or _layers_for(category, paper.get("abstract", "")),
        "applicable_metrics": result.get("applicable_metrics", []),
        "implementation_template": result.get("implementation_template", ""),
        "risks": result.get("risks", []),
        "confidence": confidence,
    }


def run_extract(base_dir: Path | None = None, use_llm: bool = True) -> List[Dict[str, Any]]:
    base = pool_path(base_dir)
    taxonomy = load_taxonomy(base)
    papers = read_jsonl(base / "paper_pool.jsonl")
    methods = []
    client = _load_llm_client(base) if use_llm else None
    for category in taxonomy["categories"]:
        category_papers = [p for p in papers if category in p.get("categories", [])]
        category_papers.sort(key=lambda p: p.get("relevance_score", 0), reverse=True)
        for paper in category_papers[:20]:
            method = _llm_extract(client, paper, category, taxonomy) if client else None
            methods.append(method or rule_based_method(paper, category, taxonomy))
    write_jsonl(base / "method_pool.jsonl", methods)
    return methods


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()
    methods = run_extract(use_llm=not args.no_llm)
    print(f"wrote {len(methods)} methods")


if __name__ == "__main__":
    main()
