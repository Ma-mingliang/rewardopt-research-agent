"""Tests for PatchManager and optimizer implementations."""

import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def git_project(tmp_path):
    """Create a temporary git project for testing patches."""
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=str(project), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(project), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(project), capture_output=True)

    # Create a sample file
    sample = project / "reward.py"
    sample.write_text("def reward():\n    return 1.0\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(project), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(project), capture_output=True)

    return project


@pytest.fixture
def work_dir(tmp_path):
    """Create a temporary work directory with required structure."""
    d = tmp_path / ".research-agent"
    for sub in ["reports", "logs", "patches", "cache", "artifacts"]:
        (d / sub).mkdir(parents=True)
    state = {
        "version": 1,
        "project_path": str(tmp_path),
        "work_dir": ".research-agent",
        "phase": "ideas_extracted",
        "front_agent": {"caller": None, "objective_written": False},
        "project_understanding": {},
        "task_classification": {},
        "strategy_selection": {},
        "experiment_plan": {},
        "git": {
            "project_is_git_repo": True,
            "baseline_commit": None,
            "current_best_commit": None,
            "rollback_target_commit": None,
            "dirty_worktree_policy": "abort",
        },
        "current_best": None,
        "candidate_queue": [],
        "literature": {},
        "resource_usage": {"wall_clock_seconds": 0, "candidates": 0, "full_evals": 0, "screening_evals": 0},
        "applied_patches": [],
        "baseline_metrics": {"reward": {"mean": 0.5, "std": 0.1}},
    }
    (d / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return d


@pytest.fixture
def config():
    """Create a minimal AgentConfig."""
    from research_agent.core.config import AgentConfig
    cfg = AgentConfig()
    cfg.metrics.primary = [{"name": "reward", "direction": "maximize"}]
    cfg.metrics.metric_regex = {"reward": r"reward\s*=\s*([\d.]+)"}
    cfg.execution.train_command = "echo train"
    cfg.execution.eval_command = "echo reward=0.5"
    cfg.execution.screening_seeds = [42]
    cfg.execution.full_eval_seeds = [42]
    cfg.execution.timeout_seconds_per_seed = 30
    return cfg


# === PatchManager tests ===

class TestPatchManager:
    def test_apply_patch_empty_diff(self, git_project, work_dir):
        """Empty patch should return applied=False."""
        from research_agent.core.patch_manager import PatchManager
        from research_agent.optimizers.base import Candidate

        pm = PatchManager(git_project, work_dir)
        candidate = Candidate(
            candidate_id="test_c001",
            optimizer="reward",
            description="empty",
            patch_diff="",
            allowed_changes=[],
        )
        result = pm.apply_patch(candidate)
        assert result["ok"] is True
        assert result["applied"] is False

    def test_apply_patch_valid_diff(self, git_project, work_dir):
        """Valid patch should be applied successfully."""
        from research_agent.core.patch_manager import PatchManager
        from research_agent.optimizers.base import Candidate

        pm = PatchManager(git_project, work_dir)

        # Create a valid unified diff
        diff = """--- a/reward.py
+++ b/reward.py
@@ -1,2 +1,2 @@
 def reward():
-    return 1.0
+    return 2.0
"""
        candidate = Candidate(
            candidate_id="test_c002",
            optimizer="reward",
            description="increase reward",
            patch_diff=diff,
            allowed_changes=[{"file": "reward.py"}],
        )
        result = pm.apply_patch(candidate)
        assert result["ok"] is True
        assert result["applied"] is True

        # Verify file was modified
        content = (git_project / "reward.py").read_text()
        assert "return 2.0" in content

    def test_rollback_patch(self, git_project, work_dir):
        """Rollback should restore the original file."""
        from research_agent.core.patch_manager import PatchManager
        from research_agent.optimizers.base import Candidate

        pm = PatchManager(git_project, work_dir)

        diff = """--- a/reward.py
+++ b/reward.py
@@ -1,2 +1,2 @@
 def reward():
-    return 1.0
+    return 2.0
"""
        candidate = Candidate(
            candidate_id="test_c003",
            optimizer="reward",
            description="increase reward",
            patch_diff=diff,
            allowed_changes=[{"file": "reward.py"}],
        )
        pm.apply_patch(candidate)
        assert "return 2.0" in (git_project / "reward.py").read_text()

        pm.rollback_patch(candidate)
        assert "return 1.0" in (git_project / "reward.py").read_text()

    def test_snapshot_creates_commit(self, git_project, work_dir):
        """Snapshot should create a git commit."""
        from research_agent.core.patch_manager import PatchManager

        pm = PatchManager(git_project, work_dir)
        # Make a change first
        (git_project / "reward.py").write_text("def reward():\n    return 3.0\n", encoding="utf-8")
        result = pm.snapshot("test commit")
        assert result["ok"] is True

    def test_is_git_repo(self, git_project, work_dir):
        """Should detect git repo."""
        from research_agent.core.patch_manager import PatchManager
        pm = PatchManager(git_project, work_dir)
        assert pm.is_git_repo() is True

    def test_is_not_git_repo(self, tmp_path, work_dir):
        """Should detect non-git directory."""
        from research_agent.core.patch_manager import PatchManager
        non_git = tmp_path / "not_a_repo"
        non_git.mkdir()
        pm = PatchManager(non_git, work_dir)
        assert pm.is_git_repo() is False

    def test_apply_and_validate_valid_patch(self, git_project, work_dir):
        """apply_and_validate should succeed for a valid patch."""
        from research_agent.core.patch_manager import PatchManager
        from research_agent.optimizers.base import Candidate

        pm = PatchManager(git_project, work_dir)
        diff = """--- a/reward.py
+++ b/reward.py
@@ -1,2 +1,2 @@
 def reward():
-    return 1.0
+    return 2.0
"""
        candidate = Candidate(
            candidate_id="test_val01",
            optimizer="reward",
            description="valid patch",
            patch_diff=diff,
            allowed_changes=[{"file": "reward.py"}],
        )
        result = pm.apply_and_validate(candidate)
        assert result["ok"] is True
        assert result["applied"] is True
        assert result["validated"] is True

    def test_apply_and_validate_syntax_error(self, git_project, work_dir):
        """apply_and_validate should rollback on syntax error."""
        from research_agent.core.patch_manager import PatchManager
        from research_agent.optimizers.base import Candidate

        pm = PatchManager(git_project, work_dir)
        # This diff introduces a syntax error (missing colon)
        diff = """--- a/reward.py
+++ b/reward.py
@@ -1,2 +1,2 @@
-def reward():
+def reward()
     return 1.0
"""
        candidate = Candidate(
            candidate_id="test_val02",
            optimizer="reward",
            description="syntax error patch",
            patch_diff=diff,
            allowed_changes=[{"file": "reward.py"}],
        )
        result = pm.apply_and_validate(candidate)
        assert result["applied"] is False
        assert result["reason"] == "compilation_failed"
        # Verify rollback happened
        content = (git_project / "reward.py").read_text()
        assert "def reward():" in content

    def test_validate_syntax_valid_diff(self, git_project, work_dir):
        """validate_syntax should pass for a valid diff."""
        from research_agent.core.patch_manager import PatchManager
        from research_agent.optimizers.base import Candidate

        pm = PatchManager(git_project, work_dir)
        diff = """--- a/reward.py
+++ b/reward.py
@@ -1,2 +1,2 @@
 def reward():
-    return 1.0
+    return 2.0
"""
        candidate = Candidate(
            candidate_id="test_val03",
            optimizer="reward",
            description="valid diff",
            patch_diff=diff,
            allowed_changes=[{"file": "reward.py"}],
        )
        result = pm.validate_syntax(candidate)
        assert result["ok"] is True
        assert result["valid"] is True

    def test_validate_syntax_empty_diff(self, git_project, work_dir):
        """validate_syntax should pass for empty diff."""
        from research_agent.core.patch_manager import PatchManager
        from research_agent.optimizers.base import Candidate

        pm = PatchManager(git_project, work_dir)
        candidate = Candidate(
            candidate_id="test_val04",
            optimizer="reward",
            description="empty",
            patch_diff="",
            allowed_changes=[],
        )
        result = pm.validate_syntax(candidate)
        assert result["ok"] is True
        assert result["valid"] is True

    def test_extract_modified_files(self):
        """_extract_modified_files should parse diff headers."""
        from research_agent.core.patch_manager import _extract_modified_files
        diff = """--- a/reward.py
+++ b/reward.py
@@ -1,2 +1,2 @@
 def reward():
-    return 1.0
+    return 2.0
--- a/config.yaml
+++ b/config.yaml
@@ -1 +1 @@
-lr: 0.001
+lr: 0.01
"""
        files = _extract_modified_files(diff)
        assert "reward.py" in files
        assert "config.yaml" in files


# === Optimizer tests ===

class TestOptimizers:
    def test_reward_optimizer_fallback(self, work_dir, config, git_project):
        """RewardOptimizer should return no-op candidate when LLM unavailable."""
        from research_agent.optimizers.reward.optimizer import RewardOptimizer

        opt = RewardOptimizer(work_dir, config, git_project)
        phase = {
            "allowed_changes": [{"file": "reward.py"}],
            "forbidden_changes": [],
        }
        candidate = opt.propose_candidate(phase, {"reward": {"mean": 0.5}})
        assert candidate.optimizer == "reward"
        assert candidate.candidate_id.startswith("reward_c")
        assert candidate.status == "proposed"

    def test_hpo_optimizer_fallback(self, work_dir, config, git_project):
        """HPOOptimizer should return no-op candidate when LLM unavailable."""
        from research_agent.optimizers.hpo.optimizer import HPOOptimizer

        opt = HPOOptimizer(work_dir, config, git_project)
        phase = {
            "allowed_changes": [{"file": "config.yaml"}],
            "forbidden_changes": [],
        }
        candidate = opt.propose_candidate(phase, {"reward": {"mean": 0.5}})
        assert candidate.optimizer == "hpo"
        assert candidate.candidate_id.startswith("hpo_c")
        assert "No-op" in candidate.description

    def test_curriculum_optimizer_fallback(self, work_dir, config, git_project):
        """CurriculumOptimizer should return no-op candidate when LLM unavailable."""
        from research_agent.optimizers.curriculum.optimizer import CurriculumOptimizer

        opt = CurriculumOptimizer(work_dir, config, git_project)
        phase = {
            "allowed_changes": [{"file": "train.py"}],
            "forbidden_changes": [],
        }
        candidate = opt.propose_candidate(phase, {"reward": {"mean": 0.5}})
        assert candidate.optimizer == "curriculum"
        assert "No-op" in candidate.description

    def test_observation_optimizer_fallback(self, work_dir, config, git_project):
        """ObservationOptimizer should return no-op candidate when LLM unavailable."""
        from research_agent.optimizers.observation.optimizer import ObservationOptimizer

        opt = ObservationOptimizer(work_dir, config, git_project)
        phase = {
            "allowed_changes": [{"file": "env.py"}],
            "forbidden_changes": [],
        }
        candidate = opt.propose_candidate(phase, {"reward": {"mean": 0.5}})
        assert candidate.optimizer == "observation"
        assert "No-op" in candidate.description

    def test_action_space_optimizer_fallback(self, work_dir, config, git_project):
        """ActionSpaceOptimizer should return no-op candidate when LLM unavailable."""
        from research_agent.optimizers.action_space.optimizer import ActionSpaceOptimizer

        opt = ActionSpaceOptimizer(work_dir, config, git_project)
        phase = {
            "allowed_changes": [{"file": "env.py"}],
            "forbidden_changes": [],
        }
        candidate = opt.propose_candidate(phase, {"reward": {"mean": 0.5}})
        assert candidate.optimizer == "action_space"
        assert "No-op" in candidate.description

    def test_candidate_to_dict(self, work_dir, config, git_project):
        """Candidate.to_dict() should return all expected fields."""
        from research_agent.optimizers.reward.optimizer import RewardOptimizer

        opt = RewardOptimizer(work_dir, config, git_project)
        phase = {"allowed_changes": [{"file": "reward.py"}], "forbidden_changes": []}
        candidate = opt.propose_candidate(phase, {"reward": {"mean": 0.5}})
        d = candidate.to_dict()
        assert "candidate_id" in d
        assert "optimizer" in d
        assert "description" in d
        assert "status" in d
        assert "timestamp" in d

    def test_ideas_passed_to_optimizer(self, work_dir, config, git_project):
        """Ideas should be formatted into the prompt."""
        from research_agent.optimizers.reward.optimizer import RewardOptimizer

        opt = RewardOptimizer(work_dir, config, git_project)
        phase = {"allowed_changes": [{"file": "reward.py"}], "forbidden_changes": []}
        ideas = [
            {"description": "Add potential-based shaping", "category": "reward shaping", "feasibility": "high"},
        ]
        # Should not raise, even with ideas
        candidate = opt.propose_candidate(phase, {"reward": {"mean": 0.5}}, ideas)
        assert candidate is not None


# === Optimizer Registry tests ===

class TestOptimizerRegistry:
    def test_list_optimizers(self):
        from research_agent.optimizers import list_optimizers
        names = list_optimizers()
        assert "reward" in names
        assert "reward_langgraph" in names
        assert "residual_control" in names
        assert "hpo" in names
        assert "curriculum" in names
        assert "observation" in names
        assert "action_space" in names
        assert len(names) == 7

    def test_get_optimizer_class(self):
        from research_agent.optimizers import get_optimizer_class
        from research_agent.optimizers.reward.optimizer import RewardOptimizer
        assert get_optimizer_class("reward") is RewardOptimizer

    def test_get_optimizer_class_hpo(self):
        from research_agent.optimizers import get_optimizer_class
        from research_agent.optimizers.hpo.optimizer import HPOOptimizer
        assert get_optimizer_class("hpo") is HPOOptimizer

    def test_get_optimizer_class_unknown(self):
        from research_agent.optimizers import get_optimizer_class
        with pytest.raises(KeyError, match="Unknown optimizer"):
            get_optimizer_class("nonexistent")


# === Strategy Selector tests ===

class TestStrategySelector:
    def test_new_optimizer_mappings(self):
        from research_agent.core.strategy_selector import _TASK_OPTIMIZER_MAP
        assert _TASK_OPTIMIZER_MAP["hpo"] == "hpo"
        assert _TASK_OPTIMIZER_MAP["curriculum_learning"] == "curriculum"
        assert _TASK_OPTIMIZER_MAP["observation_optimization"] == "observation"
        assert _TASK_OPTIMIZER_MAP["action_space_optimization"] == "action_space"


# === Executor lifecycle tests ===

class TestExecutorLifecycle:
    def test_load_ideas(self, work_dir):
        """_load_ideas should read from JSONL."""
        from research_agent.core.executor import _load_ideas

        ideas_path = work_dir / "logs" / "extracted_ideas.jsonl"
        ideas_path.write_text(
            '{"idea_id": "001", "description": "test idea"}\n'
            '{"idea_id": "002", "description": "another idea"}\n',
            encoding="utf-8",
        )
        ideas = _load_ideas(work_dir)
        assert len(ideas) == 2
        assert ideas[0]["idea_id"] == "001"

    def test_load_ideas_missing(self, work_dir):
        """_load_ideas should return empty list if file missing."""
        from research_agent.core.executor import _load_ideas
        ideas = _load_ideas(work_dir)
        assert ideas == []

    def test_compare_with_baseline(self, config):
        """_compare_with_baseline should compute pct_change correctly."""
        from research_agent.core.executor import _compare_with_baseline

        current = {"reward": {"mean": 0.6, "std": 0.05}}
        baseline = {"reward": {"mean": 0.5, "std": 0.1}}
        result = _compare_with_baseline(current, baseline, config)
        assert result["reward"]["improved"] is True
        assert abs(result["reward"]["pct_change"] - 20.0) < 0.01

    def test_is_budget_exhausted(self, config):
        """_is_budget_exhausted should check all budget dimensions."""
        from research_agent.core.executor import _is_budget_exhausted

        budget = {"wall_clock_hours": 1, "max_candidates": 5, "max_full_evals": 10}

        # Not exhausted
        usage = {"wall_clock_seconds": 100, "candidates_proposed": 2, "full_evals_run": 3}
        assert _is_budget_exhausted(usage, budget, config) is False

        # Wall clock exhausted
        usage = {"wall_clock_seconds": 3601, "candidates_proposed": 2, "full_evals_run": 3}
        assert _is_budget_exhausted(usage, budget, config) is True

        # Candidates exhausted
        usage = {"wall_clock_seconds": 100, "candidates_proposed": 5, "full_evals_run": 3}
        assert _is_budget_exhausted(usage, budget, config) is True
