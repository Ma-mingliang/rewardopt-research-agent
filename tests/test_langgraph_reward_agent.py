"""Tests for the LangGraph reward agent and related components."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def git_project(tmp_path):
    """Create a temporary git project with a reward function file."""
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=str(project), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(project), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(project), capture_output=True)

    # Create a sample reward file with __calculate_reward
    reward_file = project / "env.py"
    reward_file.write_text(
        'import math\n\n'
        'def __calculate_reward(state, action):\n'
        '    """Calculate reward for the agent."""\n'
        '    error = state.get("error", 0.0)\n'
        '    gamma = 0.99\n'
        '    alpha = 2.0\n'
        '    if error > 0.5:\n'
        '        alpha = 4.0\n'
        '    potential = -alpha * error\n'
        '    reward = potential * gamma\n'
        '    return reward\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=str(project), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(project), capture_output=True)

    return project


@pytest.fixture
def work_dir(tmp_path):
    """Create a temporary work directory."""
    d = tmp_path / ".research-agent"
    for sub in ["reports", "logs", "patches", "cache", "artifacts", "validation_tmp"]:
        (d / sub).mkdir(parents=True)
    (d / "config.yaml").write_text("llm: {}\nexecution: {}\n", encoding="utf-8")
    return d


@pytest.fixture
def config():
    """Create a minimal AgentConfig."""
    from research_agent.core.config import AgentConfig
    cfg = AgentConfig()
    cfg.execution.python_executable = sys.executable
    return cfg


@pytest.fixture
def execution_env(git_project, work_dir):
    """Create a minimal ExecutionEnv."""
    from research_agent.core.execution_env import ExecutionEnv
    return ExecutionEnv(
        python_executable=sys.executable,
        project_path=git_project,
        work_dir=work_dir,
    )


@pytest.fixture
def allowed_changes():
    return [{"file": "env.py", "line_range": [3, 12], "symbol": "__calculate_reward"}]


# === Graph compilation ===

class TestGraphCompilation:
    def test_graph_compiles(self):
        from research_agent.agents.reward_agent.graph import build_reward_proposal_graph
        graph = build_reward_proposal_graph()
        assert graph is not None

    def test_graph_is_cached(self):
        from research_agent.agents.reward_agent.graph import build_reward_proposal_graph
        g1 = build_reward_proposal_graph()
        g2 = build_reward_proposal_graph()
        assert g1 is g2


# === State defaults ===

class TestStateDefaults:
    def test_initialize_node_sets_defaults(self, git_project, work_dir, config, allowed_changes):
        from research_agent.agents.reward_agent.nodes import initialize_node
        from research_agent.agents.reward_agent.optimizer import LangGraphRewardOptimizer

        optimizer = LangGraphRewardOptimizer(work_dir, config, git_project, mock_llm=True)
        state = {
            "allowed_changes": allowed_changes,
            "forbidden_changes": [],
            "baseline_metrics": {},
            "ideas": [],
            "candidate_id": "test_c001",
            "source_meta": {},
        }
        result = initialize_node(state, {"configurable": {"optimizer": optimizer}})

        assert result["attempt"] == 0
        assert result["max_attempts"] == 3
        assert result["max_total_llm_calls"] == 6
        assert result["max_empty_diff_attempts"] == 3
        assert result["empty_diff_attempt"] == 0
        assert result["total_llm_calls"] == 0
        assert result["validation_ok"] is False
        assert result["final_candidate_status"] == "pending"
        assert "reward_code" in result
        assert "__calculate_reward" in result["reward_code"]


# === Routing functions ===

class TestRouting:
    def test_validation_ok_returns_return(self):
        from research_agent.agents.reward_agent.edges import should_continue_or_return
        state = {"validation_ok": True, "attempt": 0, "max_attempts": 3,
                 "total_llm_calls": 1, "max_total_llm_calls": 6}
        assert should_continue_or_return(state) == "return"

    def test_max_attempts_returns_return(self):
        from research_agent.agents.reward_agent.edges import should_continue_or_return
        state = {"validation_ok": False, "attempt": 3, "max_attempts": 3,
                 "total_llm_calls": 3, "max_total_llm_calls": 6}
        assert should_continue_or_return(state) == "return"

    def test_total_llm_calls_returns_return(self):
        from research_agent.agents.reward_agent.edges import should_continue_or_return
        state = {"validation_ok": False, "attempt": 1, "max_attempts": 3,
                 "total_llm_calls": 6, "max_total_llm_calls": 6}
        assert should_continue_or_return(state) == "return"

    def test_indent_error_returns_try_auto_indent(self):
        from research_agent.agents.reward_agent.edges import should_continue_or_return
        state = {"validation_ok": False, "attempt": 0, "max_attempts": 3,
                 "total_llm_calls": 1, "max_total_llm_calls": 6,
                 "validation_error": "IndentationError: expected an indented block"}
        assert should_continue_or_return(state) == "try_auto_indent"

    def test_normal_error_returns_llm_fix(self):
        from research_agent.agents.reward_agent.edges import should_continue_or_return
        state = {"validation_ok": False, "attempt": 0, "max_attempts": 3,
                 "total_llm_calls": 1, "max_total_llm_calls": 6,
                 "validation_error": "SyntaxError: invalid syntax"}
        assert should_continue_or_return(state) == "llm_fix"

    def test_missing_fields_dont_keyerror(self):
        from research_agent.agents.reward_agent.edges import should_continue_or_return
        # Should not raise KeyError on missing fields
        result = should_continue_or_return({})
        assert result in ("return", "try_auto_indent", "llm_fix")


# === ExecutionEnv ===

class TestExecutionEnv:
    def test_resolve_from_cli(self, config, git_project, work_dir):
        from research_agent.core.execution_env import resolve_execution_env
        env = resolve_execution_env(
            config, cli_execution_python=sys.executable,
            project_path=git_project, work_dir=work_dir,
        )
        assert env.python_executable == sys.executable

    def test_resolve_from_config(self, git_project, work_dir):
        from research_agent.core.config import AgentConfig
        from research_agent.core.execution_env import resolve_execution_env
        cfg = AgentConfig()
        cfg.execution.python_executable = sys.executable
        env = resolve_execution_env(cfg, project_path=git_project, work_dir=work_dir)
        assert env.python_executable == sys.executable

    def test_resolve_fallback(self, config, git_project, work_dir):
        from research_agent.core.config import AgentConfig
        from research_agent.core.execution_env import resolve_execution_env
        cfg = AgentConfig()  # no python_executable set
        env = resolve_execution_env(cfg, project_path=git_project, work_dir=work_dir)
        assert env.python_executable  # should fall back to sys.executable

    def test_run_python_compile(self, execution_env, git_project):
        from research_agent.core.execution_env import run_python_compile
        test_file = git_project / "env.py"
        ok, err = run_python_compile(execution_env, test_file)
        assert ok is True
        assert err == ""

    def test_run_python_compile_syntax_error(self, execution_env, git_project):
        from research_agent.core.execution_env import run_python_compile
        bad_file = git_project / "bad.py"
        bad_file.write_text("def foo(\n    pass\n", encoding="utf-8")
        ok, err = run_python_compile(execution_env, bad_file)
        assert ok is False
        assert "SyntaxError" in err or "error" in err.lower()


# === Command resolution ===

class TestCommandResolution:
    def test_resolve_python_placeholder(self, execution_env):
        from research_agent.core.execution_env import resolve_command
        cmd = resolve_command("{python} train.py --seed 42", execution_env)
        assert execution_env.python_executable in cmd
        assert "{python}" not in cmd

    def test_resolve_bare_python(self, execution_env):
        from research_agent.core.execution_env import resolve_command
        cmd = resolve_command("python train.py --seed 42", execution_env)
        assert execution_env.python_executable in cmd

    def test_resolve_no_placeholder(self, execution_env):
        from research_agent.core.execution_env import resolve_command
        cmd = resolve_command("bash run.sh", execution_env)
        assert cmd == "bash run.sh"


# === Patch validation isolation ===

class TestPatchValidation:
    def test_validate_patch_isolation(self, git_project, work_dir, execution_env, allowed_changes):
        """After validate_patch fails, original project file hash is unchanged."""
        import hashlib
        from research_agent.agents.reward_agent.tools import validate_patch

        original_hash = hashlib.sha256(
            (git_project / "env.py").read_bytes()
        ).hexdigest()

        bad_diff = (
            "--- a/env.py\n+++ b/env.py\n"
            "@@ -5,2 +5,2 @@\n"
            "     error = state.get(\"error\", 0.0)\n"
            "+    error = state.get(\"error\", 0.0\n"  # syntax error: missing )
        )
        result = validate_patch(bad_diff, allowed_changes, git_project, work_dir, execution_env)

        assert result["ok"] is False
        current_hash = hashlib.sha256(
            (git_project / "env.py").read_bytes()
        ).hexdigest()
        assert current_hash == original_hash

    def test_validate_patch_temp_only(self, git_project, work_dir, execution_env, allowed_changes):
        """PatchManager / patch apply operates on temp dir copy only."""
        from research_agent.agents.reward_agent.tools import validate_patch

        good_diff = (
            "--- a/env.py\n+++ b/env.py\n"
            "@@ -6,3 +6,3 @@\n"
            "     gamma = 0.99\n"
            "-    alpha = 2.0\n"
            "+    alpha = 3.0\n"
            "     if error > 0.5:\n"
        )
        result = validate_patch(good_diff, allowed_changes, git_project, work_dir, execution_env)

        # The temp dir should be cleaned up
        tmp_dir = work_dir / "validation_tmp"
        assert not tmp_dir.exists() or not list(tmp_dir.iterdir())

        # Original file should be unchanged
        content = (git_project / "env.py").read_text()
        assert "alpha = 2.0" in content  # original value still there

    def test_validate_patch_valid_diff(self, git_project, work_dir, execution_env, allowed_changes):
        """Valid diff should pass validation."""
        from research_agent.agents.reward_agent.tools import validate_patch

        good_diff = (
            "--- a/env.py\n+++ b/env.py\n"
            "@@ -6,3 +6,3 @@\n"
            "     gamma = 0.99\n"
            "-    alpha = 2.0\n"
            "+    alpha = 3.0\n"
            "     if error > 0.5:\n"
        )
        result = validate_patch(good_diff, allowed_changes, git_project, work_dir, execution_env)
        assert result["ok"] is True


# === Registry ===

class TestRegistry:
    def test_reward_langgraph_registered(self):
        from research_agent.optimizers import get_optimizer_class
        cls = get_optimizer_class("reward_langgraph")
        assert cls.__name__ == "LangGraphRewardOptimizer"

    def test_reward_backward_compat(self):
        from research_agent.optimizers import get_optimizer_class
        cls = get_optimizer_class("reward")
        assert cls.__name__ == "RewardOptimizer"

    def test_list_optimizers_includes_langgraph(self):
        from research_agent.optimizers import list_optimizers
        names = list_optimizers()
        assert "reward_langgraph" in names
        assert "reward" in names


# === Shared utils ===

class TestRewardPatchUtils:
    def test_fix_diff_line_counts(self):
        from research_agent.optimizers.reward.reward_patch_utils import fix_diff_line_counts
        diff = (
            "--- a/env.py\n+++ b/env.py\n"
            "@@ -1,5 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "-line3\n"
            "+new_line"
        )
        fixed = fix_diff_line_counts(diff)
        assert "@@ -1,3 +1,2 @@" in fixed

    def test_parse_error_line(self):
        from research_agent.optimizers.reward.reward_patch_utils import parse_error_line
        assert parse_error_line("SyntaxError: invalid syntax (env.py, line 5)") == 5
        assert parse_error_line("no line number here") is None

    def test_build_source_meta(self):
        from research_agent.optimizers.reward.reward_patch_utils import build_source_meta
        ideas = [
            {"method_id": "m1", "category": "reward shaping", "source_papers": ["p1"]},
            {"method_id": "m2", "category": "penalty design"},
        ]
        meta = build_source_meta(ideas)
        assert meta["source_method_ids"] == ["m1", "m2"]
        assert meta["source_categories"] == ["reward shaping", "penalty design"]
        assert meta["source_papers"] == ["p1"]

    def test_format_baseline(self):
        from research_agent.optimizers.reward.reward_patch_utils import format_baseline
        metrics = {"reward": {"mean": 0.5, "std": 0.1}}
        result = format_baseline(metrics)
        assert "0.5000" in result
        assert "0.1000" in result

    def test_format_ideas(self):
        from research_agent.optimizers.reward.reward_patch_utils import format_ideas
        ideas = [{"category": "reward shaping", "description": "add potential shaping"}]
        result = format_ideas(ideas)
        assert "reward shaping" in result
        assert "add potential shaping" in result

    def test_add_diff_header_if_missing(self):
        from research_agent.optimizers.reward.reward_patch_utils import add_diff_header_if_missing
        diff = "@@ -1,3 +1,3 @@\n line\n-old\n+new\n"
        result = add_diff_header_if_missing(diff, "env.py")
        assert result.startswith("--- a/env.py")
        assert "+++ b/env.py" in result

    def test_add_diff_header_already_present(self):
        from research_agent.optimizers.reward.reward_patch_utils import add_diff_header_if_missing
        diff = "--- a/env.py\n+++ b/env.py\n@@ -1,3 +1,3 @@\n line\n-old\n+new\n"
        result = add_diff_header_if_missing(diff, "env.py")
        assert result == diff  # unchanged


# === Optimizer integration ===

class TestLangGraphRewardOptimizer:
    def test_mock_empty_diff(self, git_project, work_dir, config, allowed_changes):
        """Mock LLM mode returns noop candidate."""
        from research_agent.agents.reward_agent.optimizer import LangGraphRewardOptimizer

        opt = LangGraphRewardOptimizer(work_dir, config, git_project, mock_llm=True)
        phase = {"allowed_changes": allowed_changes, "forbidden_changes": []}
        candidate = opt.propose_candidate(phase, {"reward": {"mean": 0.5, "std": 0.1}})

        assert candidate.patch_diff == ""
        assert "mock" in candidate.description.lower()
        assert candidate.status == "proposed"

    def test_no_allowed_changes_rejected(self, git_project, work_dir, config):
        from research_agent.agents.reward_agent.optimizer import LangGraphRewardOptimizer

        opt = LangGraphRewardOptimizer(work_dir, config, git_project, mock_llm=True)
        phase = {"allowed_changes": [], "forbidden_changes": []}
        candidate = opt.propose_candidate(phase, {})

        assert candidate.status == "rejected"
        assert "no allowed" in candidate.description.lower()

    def test_full_eval_inherited(self, git_project, work_dir, config):
        """full_eval_candidate should use the same protocol as BaseOptimizer."""
        from research_agent.agents.reward_agent.optimizer import LangGraphRewardOptimizer
        from research_agent.optimizers.base import BaseOptimizer

        opt = LangGraphRewardOptimizer(work_dir, config, git_project, mock_llm=True)
        # Method should be inherited, not overridden
        assert type(opt).full_eval_candidate is BaseOptimizer.full_eval_candidate


# === Prompt content ===

class TestPrompts:
    def test_propose_system_prompt_exists(self):
        from research_agent.agents.reward_agent.prompts import PROPOSE_SYSTEM_PROMPT
        assert "reward function" in PROPOSE_SYSTEM_PROMPT.lower()
        assert "return json" in PROPOSE_SYSTEM_PROMPT.lower()

    def test_fix_prompt_has_placeholders(self):
        from research_agent.agents.reward_agent.prompts import FIX_PROMPT
        assert "{code}" in FIX_PROMPT
        assert "{diff}" in FIX_PROMPT
        assert "{error}" in FIX_PROMPT
        assert "{target_context}" in FIX_PROMPT
        assert "{attempt}" in FIX_PROMPT

    def test_empty_diff_retry_prompt_exists(self):
        from research_agent.agents.reward_agent.prompts import EMPTY_DIFF_RETRY_PROMPT
        assert "empty diff" in EMPTY_DIFF_RETRY_PROMPT.lower()
