"""Minimal pytest tests for research-agent core modules."""

import json
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def work_dir(tmp_path):
    """Create a temporary work directory with required structure."""
    d = tmp_path / ".research-agent"
    for sub in ["reports", "logs", "patches", "cache", "artifacts"]:
        (d / sub).mkdir(parents=True)
    # Write minimal state
    state = {
        "version": 1,
        "project_path": str(tmp_path),
        "work_dir": ".research-agent",
        "phase": "initialized",
        "front_agent": {"caller": None, "objective_written": False, "objective_file": "front_agent_objective.json"},
        "project_understanding": {},
        "task_classification": {},
        "strategy_selection": {},
        "experiment_plan": {},
        "literature": {"arxiv_papers": None, "paper_taxonomy": None, "selected_evidence": None, "extracted_ideas": None},
        "resource_usage": {"wall_clock_seconds": 0, "gpu_seconds": None, "candidates": 0, "full_evals": 0, "screening_evals": 0},
        "stop_reason": None,
        "applied_patches": [],
    }
    (d / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return d


# === config ===

def test_config_load_defaults():
    from research_agent.core.config import AgentConfig
    cfg = AgentConfig()
    assert cfg.llm.model == "mimo-v2.5-pro"
    assert cfg.budget.wall_clock_hours == 336
    assert cfg.literature.top_k_selected_papers == 5


def test_config_load_from_file(work_dir):
    import yaml
    cfg_path = work_dir / "config.yaml"
    cfg_path.write_text(yaml.dump({"llm": {"model": "test-model"}}), encoding="utf-8")
    from research_agent.core.config import load_config
    cfg = load_config(work_dir)
    assert cfg.llm.model == "test-model"


# === state ===

def test_initial_state():
    from research_agent.core.state import initial_state
    state = initial_state("/project", ".research-agent")
    assert state["phase"] == "initialized"
    assert state["project_path"] == "/project"


def test_write_read_state(work_dir):
    from research_agent.core.state import write_state_json, read_state_json
    state = {"phase": "test", "version": 1}
    write_state_json(work_dir, state)
    loaded = read_state_json(work_dir)
    assert loaded["phase"] == "test"


def test_advance_phase_valid(work_dir):
    from research_agent.core.state import advance_phase
    state = {"phase": "initialized"}
    new = advance_phase(state, "understood")
    assert new["phase"] == "understood"


def test_advance_phase_invalid(work_dir):
    from research_agent.core.state import advance_phase
    state = {"phase": "initialized"}
    with pytest.raises(ValueError, match="Invalid phase transition"):
        advance_phase(state, "completed")


def test_atomic_write(work_dir):
    """Verify atomic write doesn't leave .tmp file."""
    from research_agent.core.state import write_state_json
    write_state_json(work_dir, {"phase": "test", "version": 1})
    tmp_file = work_dir / "state.json.tmp"
    assert not tmp_file.exists()


# === output ===

def test_ok_response():
    from research_agent.core.output import ok_response
    r = ok_response({"key": "value"})
    assert r["ok"] is True
    assert r["key"] == "value"
    assert "timestamp" in r


def test_error_response():
    from research_agent.core.output import error_response
    r = error_response("CODE", "message", "next_action")
    assert r["ok"] is False
    assert r["error_code"] == "CODE"


def test_append_jsonl(tmp_path):
    from research_agent.core.output import append_jsonl
    path = tmp_path / "test.jsonl"
    append_jsonl(path, {"a": 1})
    append_jsonl(path, {"b": 2})
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"a": 1}


# === exceptions ===

def test_exception_to_dict():
    from research_agent.core.exceptions import LLMCallError
    e = LLMCallError(message="test error", retries=3, last_error="timeout")
    d = e.to_dict()
    assert d["ok"] is False
    assert d["error_code"] == "LLM_SERVICE_UNAVAILABLE"
    assert "test error" in d["message"]


# === metric_parser ===

def test_regex_search():
    from research_agent.execution.metric_parser import _regex_search
    assert _regex_search("reward = 0.85", r"reward\s*=\s*([\d.]+)") == 0.85
    assert _regex_search("no match", r"reward\s*=\s*([\d.]+)") is None
    assert _regex_search("", r"pattern") is None


def test_parse_metrics():
    from research_agent.execution.metric_parser import parse_metrics
    from research_agent.core.config import AgentConfig
    cfg = AgentConfig()
    cfg.metrics.metric_regex = {"reward": r"reward\s*=\s*([\d.]+)", "loss": r"loss\s*:\s*([\d.]+)"}
    metrics = parse_metrics("reward = 0.85\nloss: 0.12\n", "", cfg)
    assert metrics["reward"] == 0.85
    assert metrics["loss"] == 0.12


def test_check_safety_metrics():
    from research_agent.execution.metric_parser import check_safety_metrics
    from research_agent.core.config import AgentConfig
    cfg = AgentConfig()
    cfg.metrics.safety = [{"name": "collision", "hard_max": 0.1}]
    assert check_safety_metrics({"collision": 0.05}, cfg)["safe"] is True
    assert check_safety_metrics({"collision": 0.15}, cfg)["safe"] is False


# === experiment_runner ===

def test_aggregate_metrics():
    from research_agent.execution.experiment_runner import RunResult, aggregate_metrics
    results = [
        RunResult(command="eval", return_code=0, stdout="", stderr="", duration_seconds=1.0,
                  metrics={"reward": 0.8}),
        RunResult(command="eval", return_code=0, stdout="", stderr="", duration_seconds=1.0,
                  metrics={"reward": 0.9}),
    ]
    agg = aggregate_metrics(results)
    assert abs(agg["reward"]["mean"] - 0.85) < 0.001
    assert agg["reward"]["n"] == 2


def test_aggregate_empty():
    from research_agent.execution.experiment_runner import aggregate_metrics
    assert aggregate_metrics([]) == {}


# === front_agent_contract ===

def test_require_phase_raises(work_dir):
    from research_agent.interfaces.front_agent_contract import require_phase
    from research_agent.core.exceptions import DependencyMissingError
    with pytest.raises(DependencyMissingError):
        require_phase(work_dir, "understood")


def test_require_objective_raises(work_dir):
    from research_agent.interfaces.front_agent_contract import require_objective
    from research_agent.core.exceptions import DependencyMissingError
    with pytest.raises(DependencyMissingError):
        require_objective(work_dir)


# === literature ===

def test_paper_selector_scoring():
    from research_agent.literature.paper_selector import _compute_metric_match, _compute_recency
    assert _compute_metric_match("reward shaping for control", ["reward", "control"]) == 1.0
    assert _compute_metric_match("nothing here", ["reward", "control"]) == 0.0
    assert _compute_recency("2024-01-01", 2026) == 0.8
    assert _compute_recency("2016-01-01", 2026) == 0.0


def test_paper_classifier_keywords():
    from research_agent.literature.paper_classifier import CATEGORY_KEYWORDS
    assert "reward shaping" in CATEGORY_KEYWORDS
    assert "penalty" in CATEGORY_KEYWORDS["penalty and constraint design"]
