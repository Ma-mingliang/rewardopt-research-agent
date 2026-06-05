"""Curriculum optimizer: propose curriculum/schedule modifications."""

from __future__ import annotations

from pathlib import Path

from research_agent.core.config import AgentConfig
from research_agent.optimizers.base import BaseOptimizer, Candidate

PROPOSE_SYSTEM_PROMPT = """You are a curriculum learning optimizer for RL and control projects.
Given the current training setup, baseline metrics, and research ideas,
propose a curriculum or schedule modification to improve training.

Curriculum strategies include:
- Difficulty progression (start easy, increase difficulty)
- Reward shaping schedule (decay bonus rewards over time)
- Domain randomization schedule
- Episode length curriculum
- Task complexity progression
- Adaptive curriculum based on agent performance

Rules:
- Only modify files listed in allowed_changes
- Propose ONE specific curriculum change
- Do NOT change algorithm body, network architecture, optimizer, or loss
- Return valid JSON only.

Return JSON:
{"description": "<what you changed>", "diff": "<unified diff>", "rationale": "<why this should improve metrics>"}}"""

PROPOSE_USER_PROMPT = """Current training code (from {file}):
```
{code}
```

Baseline metrics:
{baseline}

Allowed changes: {allowed}
Forbidden changes: {forbidden}

Research ideas to consider:
{ideas}

Propose ONE specific curriculum learning modification. Return JSON only."""


class CurriculumOptimizer(BaseOptimizer):
    """Optimizer for curriculum and training schedule modifications."""

    name = "curriculum"

    def propose_candidate(
        self,
        phase: dict,
        baseline_metrics: dict[str, dict[str, float]],
        ideas: list[dict] | None = None,
    ) -> Candidate:
        """Propose a curriculum modification.

        Uses LLM to generate a patch based on training code and baseline metrics.
        Falls back to a no-op patch if LLM is unavailable.
        """
        allowed = phase.get("allowed_changes", [])
        forbidden = phase.get("forbidden_changes", [])

        code = self._read_training_code(allowed)
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
                    desc = response.parsed.get("description", "Curriculum change")
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
            description="No-op curriculum candidate (LLM unavailable)",
            patch_diff="",
            allowed_changes=allowed,
            source_idea="fallback",
        )

    def _read_training_code(self, allowed_changes: list[dict]) -> str:
        """Read training code from allowed files."""
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
        return "# No training code file found"

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
