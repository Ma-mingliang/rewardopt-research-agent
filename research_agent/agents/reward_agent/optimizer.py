"""LangGraph-based reward optimizer.

Uses a StateGraph agent for the propose→validate→fix loop.
All project code execution (compile, AST check) goes through execution_python.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_agent.agents.reward_agent.state import RewardAgentState
from research_agent.core.config import AgentConfig
from research_agent.core.execution_env import ExecutionEnv, resolve_execution_env
from research_agent.optimizers.base import BaseOptimizer, Candidate, normalize_allowed_changes
from research_agent.optimizers.reward.reward_patch_utils import build_source_meta


class LangGraphRewardOptimizer(BaseOptimizer):
    """Reward optimizer backed by a LangGraph StateGraph agent."""

    name = "reward_langgraph"

    def __init__(
        self,
        work_dir: Path,
        config: AgentConfig,
        project_path: Path,
        mock_llm: bool = False,
        execution_python: str | None = None,
    ):
        super().__init__(work_dir, config, project_path, mock_llm, execution_python)
        self._execution_env: ExecutionEnv = resolve_execution_env(
            config,
            cli_execution_python=execution_python,
            project_path=project_path,
            work_dir=work_dir,
        )
        self._graph = None

    @property
    def graph(self):
        if self._graph is None:
            from research_agent.agents.reward_agent.graph import build_reward_proposal_graph
            self._graph = build_reward_proposal_graph()
        return self._graph

    def propose_candidate(
        self,
        phase: dict,
        baseline_metrics: dict[str, dict[str, float]],
        ideas: list[dict] | None = None,
    ) -> Candidate:
        """Propose a reward function modification via LangGraph agent.

        Uses a StateGraph for the propose→validate→fix loop with strict
        dual-environment isolation (agent Python for orchestration,
        execution_python for all project code).
        """
        allowed = normalize_allowed_changes(phase.get("allowed_changes", []))
        forbidden = phase.get("forbidden_changes", [])

        if not allowed:
            candidate_id = self.next_candidate_id()
            candidate = Candidate(
                candidate_id=candidate_id,
                optimizer=self.name,
                description="Rejected: no allowed reward target detected",
                patch_diff="",
                allowed_changes=[],
                source_idea="missing_allowed_changes",
            )
            candidate.status = "rejected"
            candidate.rejection_reason = "No allowed reward target detected"
            return candidate

        candidate_id = self.next_candidate_id()
        source_meta = build_source_meta(ideas or [])

        if self._mock_llm:
            return Candidate(
                candidate_id=candidate_id,
                optimizer=self.name,
                description="No-op candidate (mock-llm mode)",
                patch_diff="",
                allowed_changes=allowed,
                source_idea=json.dumps(source_meta),
            )

        # Build initial state for the graph
        initial_state: RewardAgentState = {
            "allowed_changes": allowed,
            "forbidden_changes": forbidden,
            "baseline_metrics": baseline_metrics,
            "ideas": ideas or [],
            "candidate_id": candidate_id,
            "source_meta": source_meta,
            "execution_python": self._execution_env.python_executable,
        }

        # Invoke the graph
        final_state = self.graph.invoke(
            initial_state,
            config={
                "configurable": {
                    "optimizer": self,
                    "execution_env": self._execution_env,
                },
            },
        )

        # Convert final state to Candidate
        status = final_state.get("final_candidate_status", "exhausted")
        diff = final_state.get("patch_diff", "") or ""
        desc = final_state.get("description", "No description")
        rationale = final_state.get("rationale", "")

        candidate = Candidate(
            candidate_id=candidate_id,
            optimizer=self.name,
            description=f"{desc} (rationale: {rationale})" if rationale else desc,
            patch_diff=diff,
            allowed_changes=allowed,
            source_idea=json.dumps(source_meta),
        )

        if status == "ready" and diff:
            candidate.status = "evaluated"
        else:
            candidate.status = "rejected"
            candidate.rejection_reason = desc

        return candidate
