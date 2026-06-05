"""Reward optimizer: propose reward function modifications."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_agent.core.config import AgentConfig
from research_agent.optimizers.base import BaseOptimizer, Candidate

PROPOSE_SYSTEM_PROMPT = """You are a reward function optimizer for RL and control projects.
Given the current reward function code, baseline metrics, and research ideas,
propose a specific modification to improve the reward function.

Rules:
- Only modify files listed in allowed_changes
- Do NOT change algorithm body, network architecture, optimizer, loss, or replay buffer
- Propose minimal, targeted changes
- Explain what you changed and why

Return JSON only."""

PROPOSE_USER_PROMPT = """Current reward function (from {file}):
```
{code}
```

Baseline metrics:
{baseline}

Allowed changes: {allowed}
Forbidden changes: {forbidden}

Research ideas to consider:
{ideas}

Propose ONE specific modification. Return JSON:
{{"description": "<what you changed>", "diff": "<unified diff>", "rationale": "<why this should improve metrics>"}}"""


class RewardOptimizer(BaseOptimizer):
    """Optimizer for reward function modifications."""

    name = "reward"

    def propose_candidate(
        self,
        phase: dict,
        baseline_metrics: dict[str, dict[str, float]],
        ideas: list[dict] | None = None,
    ) -> Candidate:
        """Propose a reward function modification.

        Uses LLM to generate a patch based on allowed_changes and baseline metrics.
        Falls back to a no-op patch if LLM is unavailable.
        """
        allowed = phase.get("allowed_changes", [])
        forbidden = phase.get("forbidden_changes", [])

        # Read current reward function code
        code = self._read_reward_code(allowed)

        # Format baseline for prompt
        baseline_str = self._format_baseline(baseline_metrics)

        # Format ideas
        ideas_str = self._format_ideas(ideas or [])

        candidate_id = self.next_candidate_id()

        # Build source metadata from ideas
        source_meta = self._build_source_meta(ideas or [])

        # Skip LLM if mock mode
        if self._mock_llm:
            return Candidate(
                candidate_id=candidate_id,
                optimizer=self.name,
                description="No-op candidate (mock-llm mode)",
                patch_diff="",
                allowed_changes=allowed,
                source_idea=json.dumps(source_meta),
            )

        # Try LLM proposal
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
                    desc = response.parsed.get("description", "LLM-proposed change")
                    diff = response.parsed.get("diff", "")
                    rationale = response.parsed.get("rationale", "")
                    return Candidate(
                        candidate_id=candidate_id,
                        optimizer=self.name,
                        description=f"{desc} (rationale: {rationale})",
                        patch_diff=diff,
                        allowed_changes=allowed,
                        source_idea=json.dumps(source_meta),
                    )
            except Exception:
                pass

        # Fallback: no-op candidate (identity patch)
        return Candidate(
            candidate_id=candidate_id,
            optimizer=self.name,
            description="No-op candidate (LLM unavailable)",
            patch_diff="",
            allowed_changes=allowed,
            source_idea=json.dumps(source_meta),
        )

    def _read_reward_code(self, allowed_changes: list[dict]) -> str:
        """Read the current reward function code from allowed files."""
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
                            return "\n".join(lines[max(0, start-1):end])
                        return content[:3000]
                    except OSError:
                        continue
        return "# No reward function file found"

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
            cat = idea.get("category", "")
            desc = idea.get("description", "")
            # Rich method from pool
            if idea.get("implementation_template"):
                core = idea.get("core_idea", desc)
                formula = idea.get("reward_formula", "N/A")
                template = idea.get("implementation_template", "N/A")
                layers = ", ".join(idea.get("applicable_layers", []))
                metrics = ", ".join(idea.get("applicable_metrics", []))
                risks = ", ".join(idea.get("risks", [])[:2])
                lines.append(f"  [{cat}] {core}")
                lines.append(f"    Formula: {formula}")
                lines.append(f"    Template: {template}")
                if layers:
                    lines.append(f"    Layers: {layers}")
                if metrics:
                    lines.append(f"    Metrics: {metrics}")
                if risks:
                    lines.append(f"    Risks: {risks}")
            else:
                lines.append(f"  - [{cat}] {desc}")
        return "\n".join(lines)

    @staticmethod
    def _build_source_meta(ideas: list[dict]) -> dict:
        """Extract source metadata from ideas for candidate tracking."""
        method_ids = []
        categories = []
        source_papers = []
        for idea in ideas:
            mid = idea.get("method_id", "")
            if mid:
                method_ids.append(mid)
            cat = idea.get("category", "")
            if cat and cat not in categories:
                categories.append(cat)
            papers = idea.get("source_papers", [])
            for p in papers:
                if p not in source_papers:
                    source_papers.append(p)
            # Also check source_paper dict
            sp = idea.get("source_paper", {})
            pid = sp.get("paper_id", "")
            if pid and pid not in source_papers:
                source_papers.append(pid)
        return {
            "source_method_ids": method_ids,
            "source_categories": categories,
            "source_papers": source_papers,
            "source_idea": "pool_methods" if method_ids else "extracted_ideas",
        }
