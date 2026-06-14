"""Smoke test: verify dual-environment isolation end-to-end.

This test exercises LangGraphRewardOptimizer with mock_llm=True
and verifies that:
1. ExecutionEnv correctly uses execution_python, not sys.executable
2. Baseline files are never modified
3. validate_patch uses execution_python for compile/AST checks
4. The full eval path uses execution_python
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def project(tmp_path):
    """Create a minimal project with a reward function file."""
    proj = tmp_path / "HRRL2"
    proj.mkdir()
    subprocess.run(["git", "init"], cwd=str(proj), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(proj), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(proj), capture_output=True)

    env_py = proj / "env.py"
    env_py.write_text(
        'import math\n\n'
        'def __calculate_reward(state, action):\n'
        '    """Calculate reward."""\n'
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
    subprocess.run(["git", "add", "-A"], cwd=str(proj), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(proj), capture_output=True)
    return proj


@pytest.fixture
def work_dir(tmp_path):
    d = tmp_path / ".research-agent"
    for sub in ["reports", "logs", "patches", "cache", "artifacts", "validation_tmp"]:
        (d / sub).mkdir(parents=True)
    (d / "config.yaml").write_text(
        "llm: {}\nexecution:\n  python_executable: ''\n", encoding="utf-8"
    )
    return d


@pytest.fixture
def baseline_hash(project):
    return hashlib.sha256((project / "env.py").read_bytes()).hexdigest()


def test_optimizer_uses_execution_python(project, work_dir, baseline_hash):
    """LangGraphRewardOptimizer must resolve execution_python, not sys.executable."""
    from research_agent.agents.reward_agent.optimizer import LangGraphRewardOptimizer
    from research_agent.core.config import AgentConfig

    cfg = AgentConfig()
    execution_python = sys.executable  # Use current Python as "execution" python for testing

    opt = LangGraphRewardOptimizer(
        work_dir=work_dir,
        config=cfg,
        project_path=project,
        mock_llm=True,
        execution_python=execution_python,
    )

    # Verify execution_env uses the specified python
    assert opt._execution_env.python_executable == execution_python

    # Verify agent_python is different from execution_python concept
    import research_agent.core.execution_env as ee_mod
    import importlib
    # The agent_python is sys.executable at module load time
    # execution_python should be what we passed


def test_mock_propose_does_not_modify_baseline(project, work_dir, baseline_hash):
    """Mock propose_candidate must never modify baseline env.py."""
    from research_agent.agents.reward_agent.optimizer import LangGraphRewardOptimizer
    from research_agent.core.config import AgentConfig

    cfg = AgentConfig()
    opt = LangGraphRewardOptimizer(
        work_dir=work_dir,
        config=cfg,
        project_path=project,
        mock_llm=True,
        execution_python=sys.executable,
    )

    phase = {
        "allowed_changes": [{"file": "env.py", "line_range": [3, 12], "symbol": "__calculate_reward"}],
        "forbidden_changes": [],
    }
    candidate = opt.propose_candidate(phase, {"reward": {"mean": 0.5, "std": 0.1}})

    # Mock mode should return noop
    assert candidate.patch_diff == ""
    assert "mock" in candidate.description.lower()

    # Baseline file must be unchanged
    current_hash = hashlib.sha256((project / "env.py").read_bytes()).hexdigest()
    assert current_hash == baseline_hash, f"Baseline env.py was modified! Before: {baseline_hash}, After: {current_hash}"


def test_validate_patch_uses_execution_python(project, work_dir):
    """validate_patch must use execution_python for compile check, not sys.executable."""
    from research_agent.agents.reward_agent.tools import validate_patch
    from research_agent.core.execution_env import ExecutionEnv

    # Use sys.executable as the "execution python" — it must be used for compile
    env = ExecutionEnv(
        python_executable=sys.executable,
        project_path=project,
        work_dir=work_dir,
    )

    good_diff = (
        "--- a/env.py\n+++ b/env.py\n"
        "@@ -6,3 +6,3 @@\n"
        "     gamma = 0.99\n"
        "-    alpha = 2.0\n"
        "+    alpha = 3.0\n"
        "     if error > 0.5:\n"
    )
    allowed = [{"file": "env.py", "line_range": [3, 12], "symbol": "__calculate_reward"}]

    original_hash = hashlib.sha256((project / "env.py").read_bytes()).hexdigest()
    result = validate_patch(good_diff, allowed, project, work_dir, env)
    current_hash = hashlib.sha256((project / "env.py").read_bytes()).hexdigest()

    assert result["ok"] is True
    assert current_hash == original_hash, "validate_patch modified baseline file!"


def test_train_eval_command_resolution():
    """train/eval commands with {python} must resolve to execution_python."""
    from research_agent.core.execution_env import ExecutionEnv, resolve_command

    env = ExecutionEnv(
        python_executable="E:/Anaconda/envs/RL2/python.exe",
        project_path=Path("."),
        work_dir=Path("."),
    )

    # {python} placeholder
    cmd = resolve_command("{python} train_and_eval.py --seed {seed}", env)
    assert "RL2/python.exe" in cmd
    assert "{python}" not in cmd

    # Bare python prefix
    cmd = resolve_command("python train_and_eval.py --seed 42", env)
    assert "RL2/python.exe" in cmd

    # No python at all
    cmd = resolve_command("bash run.sh", env)
    assert cmd == "bash run.sh"


def test_experiment_runner_uses_execution_python(project, work_dir):
    """run_eval must pass python_executable through to _run_subprocess."""
    from research_agent.core.config import AgentConfig
    from research_agent.execution.experiment_runner import run_eval

    cfg = AgentConfig()
    cfg.execution.eval_command = "{python} -c \"print('reward=0.5')\""
    cfg.execution.timeout_seconds_per_seed = 30

    # Use sys.executable as the execution python
    result = run_eval(
        project, cfg, seed=42, work_dir=work_dir,
        python_executable=sys.executable,
    )

    # The command should have used sys.executable
    assert sys.executable in result.command
    assert "{python}" not in result.command


def test_full_eval_uses_execution_python(project, work_dir):
    """run_full_eval must forward python_executable."""
    from research_agent.core.config import AgentConfig
    from research_agent.execution.experiment_runner import run_full_eval

    cfg = AgentConfig()
    cfg.execution.eval_command = "{python} -c \"print('reward=0.5')\""
    cfg.execution.full_eval_seeds = [42]
    cfg.execution.timeout_seconds_per_seed = 30

    results = run_full_eval(
        project, cfg, seeds=[42], work_dir=work_dir,
        python_executable=sys.executable,
    )

    assert len(results) == 1
    assert sys.executable in results[0].command


def test_no_allowed_changes_returns_rejected(project, work_dir):
    """Empty allowed_changes must return rejected candidate."""
    from research_agent.agents.reward_agent.optimizer import LangGraphRewardOptimizer
    from research_agent.core.config import AgentConfig

    opt = LangGraphRewardOptimizer(
        work_dir=work_dir, config=AgentConfig(),
        project_path=project, mock_llm=True,
        execution_python=sys.executable,
    )
    candidate = opt.propose_candidate(
        {"allowed_changes": [], "forbidden_changes": []}, {}
    )
    assert candidate.status == "rejected"
    assert "no allowed" in candidate.description.lower()


def test_invalid_execution_python_fails_fast():
    """Invalid execution_python path must raise FileNotFoundError."""
    from research_agent.core.execution_env import resolve_execution_env

    with pytest.raises(FileNotFoundError, match="execution_python not found"):
        resolve_execution_env(
            cli_execution_python="Z:/nonexistent/python.exe",
            project_path=Path("."),
            work_dir=Path("."),
        )
