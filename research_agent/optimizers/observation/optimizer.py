"""Observation optimizer: propose observation space modifications."""

from __future__ import annotations

from pathlib import Path

from research_agent.core.config import AgentConfig
from research_agent.optimizers.base import BaseOptimizer, Candidate

PROPOSE_SYSTEM_PROMPT = """You are an observation space optimizer for RL and control projects.
Given the current observation space definition, baseline metrics, and research ideas,
propose a modification to the observation space to improve performance.

Observation space modifications include:
- Adding new observation features (e.g., velocity, acceleration, relative positions)
- Removing noisy or redundant features
- Normalizing or transforming existing features
- Adding history/stacking of observations
- Changing observation scaling or bounds
- Adding derived features (e.g., error signals, integrals)

Rules:
- Only modify files listed in allowed_changes
- Propose ONE specific observation space change
- Do NOT change algorithm body, network architecture, optimizer, or loss
- Return valid JSON only.

Return JSON:
{"description": "<what you changed>", "diff": "<unified diff>", "rationale": "<why this should improve metrics>"}}"""

PROPOSE_USER_PROMPT = """Current observation code (from {file}):
```
{code}
```

Baseline metrics:
{baseline}

Allowed changes: {allowed}
Forbidden changes: {forbidden}

Research ideas to consider:
{ideas}

Propose ONE specific observation space modification. Return JSON only."""


class ObservationOptimizer(BaseOptimizer):
    """Optimizer for observation space modifications."""

    name = "observation"

    def propose_candidate(
        self,
        phase: dict,
        baseline_metrics: dict[str, dict[str, float]],
        ideas: list[dict] | None = None,
    ) -> Candidate:
        """Propose an observation space modification.

        Uses LLM to generate a patch based on env wrapper code and baseline metrics.
        Falls back to a no-op patch if LLM is unavailable.
        """
        allowed = phase.get("allowed_changes", [])
        forbidden = phase.get("forbidden_changes", [])

        code = self._read_env_code(allowed)
        baseline_str = self._format_baseline(baseline_metrics)
        ideas_str = self._format_ideas(ideas or [])
        candidate_id = self.next_candidate_id()

        if self.llm_client is not None:
            try:
                response = self.llm_client.call(
                    system_prompt=PROPOSE_SYSTEM_PROMPT,
                    user_prompt=PROPOSE_USER_PROMPT.format(
                        file=allowed[0].get("file", "unknown") if allowed else "unknown",
                        code=code[:2000],
                        baseline=baseline_str,
                        allowed=allowed,
                        forbidden=forbidden,
                        ideas=ideas_str,
                    ),
                    max_tokens=2048,
                )
                if response.parsed:
                    desc = response.parsed.get("description", "Observation change")
                    diff = response.parsed.get("diff", "")
                    rationale = response.parsed.get("rationale", "")
                    return Candidate(
                        candidate_id=candidate_id,
                        optimizer=self.name,
                        description=f"{desc} (rationale: {rationale})",
                        patch_diff=diff,
                        allowed_changes=allowed,
                        source_idea="llm_proposal",
                    )
            except Exception:
                pass

        return Candidate(
            candidate_id=candidate_id,
            optimizer=self.name,
            description="No-op observation candidate (LLM unavailable)",
            patch_diff="",
            allowed_changes=allowed,
            source_idea="fallback",
        )

    def _read_env_code(self, allowed_changes: list[dict]) -> str:
        """Read environment wrapper code from allowed files."""
        for change in allowed_changes:
            file_path = change.get("file", "")
            if file_path:
                full_path = self.project_path / file_path
                if full_path.exists():
                    try:
                        content = full_path.read_text(encoding="utf-8")
                        line_range = change.get("line_range")
                        if line_range and len(line_range) == 2:
                            lines = content.splitlines()
                            start, end = line_range
                            return "\n".join(lines[max(0, start - 1):end])
                        return content[:3000]
                    except OSError:
                        continue
        return "# No environment code file found"

    def _format_baseline(self, metrics: dict[str, dict[str, float]]) -> str:
        lines = []
        for name, vals in metrics.items():
            mean = vals.get("mean", 0)
            std = vals.get("std", 0)
            lines.append(f"  {name}: {mean:.4f} (std: {std:.4f})")
        return "\n".join(lines) if lines else "  (no baseline metrics)"

    def _format_ideas(self, ideas: list[dict]) -> str:
        if not ideas:
            return "  (no ideas available)"
        lines = []
        for idea in ideas[:5]:
            desc = idea.get("description", "")
            cat = idea.get("category", "")
            lines.append(f"  - [{cat}] {desc}")
        return "\n".join(lines)
