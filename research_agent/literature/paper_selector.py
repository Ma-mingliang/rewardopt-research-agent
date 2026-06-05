"""Paper selection: deterministic top-K selection using relevance_score formula."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_agent.core.config import AgentConfig
from research_agent.core.llm_client import LLMClient
from research_agent.core.output import append_jsonl, ok_response, write_markdown_report
from research_agent.core.state import advance_phase, read_state_json, write_state_json
from research_agent.interfaces.front_agent_contract import require_phase

# Weights for relevance_score formula
WEIGHTS = {
    "objective_match": 0.35,
    "metric_match": 0.25,
    "state_action_match": 0.15,
    "implementation_feasibility": 0.15,
    "recency_or_influence": 0.10,
}

SCORING_SYSTEM_PROMPT = """You are a paper relevance scorer for RL and control research.
Given a paper's abstract and the project objective, score the paper on multiple dimensions.
Return JSON only with scores from 0.0 to 1.0."""

SCORING_USER_PROMPT = """Paper title: {title}
Paper abstract: {abstract}

Project objective: {objective}
Primary metrics: {metrics}
Focus areas: {focus}

Score the paper on:
1. objective_match: How relevant is the paper's topic to the project objective?
2. state_action_match: How similar is the paper's experimental setup to the target project?
3. implementation_feasibility: How feasible is it to implement the paper's approach?

Return JSON:
{{"objective_match": <0-1>, "state_action_match": <0-1>, "implementation_feasibility": <0-1>}}"""


def select_papers(
    work_dir: Path,
    config: AgentConfig,
    top_k_override: int | None = None,
) -> dict:
    """Select top-K papers using deterministic relevance scoring.

    relevance_score = 0.35 * objective_match + 0.25 * metric_match
                   + 0.15 * state_action_match + 0.15 * implementation_feasibility
                   + 0.10 * recency_or_influence

    Args:
        work_dir: .research-agent work directory.
        config: Agent configuration.
        top_k_override: Override top-K from CLI (--top-k N). Does NOT modify config.

    Returns:
        Response dict with selected papers.
    """
    require_phase(work_dir, "literature_classified")

    # Load classified papers
    papers = _load_classified_papers(work_dir)
    if not papers:
        return ok_response({
            "papers_selected": 0,
            "message": "No classified papers found. Run 'classify-papers' first.",
        })

    # Score papers
    scored_papers = _score_papers(papers, work_dir, config)

    # Select top-K
    top_k = top_k_override or config.literature.top_k_selected_papers
    min_score = config.literature.min_relevance_score

    # Filter by min score
    qualified = [p for p in scored_papers if p.get("relevance_score", 0) >= min_score]

    # Sort by relevance_score descending, stable tiebreak
    qualified.sort(
        key=lambda p: (
            p.get("relevance_score", 0),
            p.get("scores", {}).get("objective_match", 0),
            p.get("scores", {}).get("metric_match", 0),
            p.get("published", "0000"),
            p.get("paper_id", ""),
        ),
        reverse=True,
    )

    selected = qualified[:top_k]

    # Write outputs
    log_path = work_dir / "logs" / "selected_reward_evidence.jsonl"
    for paper in selected:
        append_jsonl(log_path, paper)

    md = _generate_markdown(selected, top_k, min_score)
    write_markdown_report(work_dir / "reports" / "selected_reward_evidence.md", md)

    # Update state
    state = read_state_json(work_dir)
    state["literature"]["selected_evidence"] = "logs/selected_reward_evidence.jsonl"
    state = advance_phase(state, "literature_selected")
    write_state_json(work_dir, state)

    return ok_response({
        "papers_selected": len(selected),
        "top_k": top_k,
        "min_relevance_score": min_score,
        "log_path": "logs/selected_reward_evidence.jsonl",
        "report_path": "reports/selected_reward_evidence.md",
        "next_action": "Call 'extract-ideas' or 'run-plan'.",
    })


def _load_classified_papers(work_dir: Path) -> list[dict]:
    """Load classified papers by merging arxiv_papers.jsonl and paper_taxonomy.jsonl."""
    # Load paper metadata
    papers_path = work_dir / "logs" / "arxiv_papers.jsonl"
    papers_by_id: dict[str, dict] = {}
    if papers_path.exists():
        with open(papers_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        p = json.loads(line)
                        papers_by_id[p.get("paper_id", "")] = p
                    except json.JSONDecodeError:
                        continue

    # Load classifications
    taxonomy_path = work_dir / "logs" / "paper_taxonomy.jsonl"
    if taxonomy_path.exists():
        with open(taxonomy_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        t = json.loads(line)
                        pid = t.get("paper_id", "")
                        if pid in papers_by_id:
                            papers_by_id[pid]["categories"] = t.get("categories", [])
                            papers_by_id[pid]["classification_confidence"] = t.get("confidence", 0)
                    except json.JSONDecodeError:
                        continue

    return list(papers_by_id.values())


def _score_papers(papers: list[dict], work_dir: Path, config: AgentConfig) -> list[dict]:
    """Score all papers using the relevance_score formula."""
    # Try LLM for semantic scores
    llm_client = None
    try:
        llm_client = LLMClient(
            config.llm.model_dump(),
            log_path=work_dir / "logs" / "llm_calls.jsonl",
        )
    except Exception:
        pass

    objective = config.objective
    primary_metrics = [
        m.get("name", "") if isinstance(m, dict) else str(m)
        for m in config.metrics.primary
    ]
    metric_keywords = [m.replace("_", " ").lower() for m in primary_metrics]

    current_year = datetime.now().year
    scored: list[dict] = []

    for paper in papers:
        scores = _score_single_paper(
            paper, objective, metric_keywords, current_year, llm_client,
        )
        relevance = sum(WEIGHTS[k] * scores[k] for k in WEIGHTS)
        scored.append({
            **paper,
            "scores": scores,
            "relevance_score": round(relevance, 4),
        })

    return scored


def _score_single_paper(
    paper: dict,
    objective: Any,
    metric_keywords: list[str],
    current_year: int,
    llm_client: LLMClient | None,
) -> dict[str, float]:
    """Score a single paper on all 5 dimensions."""
    title = paper.get("title", "")
    abstract = paper.get("abstract", "")
    text = f"{title} {abstract}".lower()
    published = paper.get("published", "")

    # metric_match: keyword-based (always deterministic)
    metric_match = _compute_metric_match(text, metric_keywords)

    # recency_or_influence: formula-based
    recency = _compute_recency(published, current_year)

    # LLM-dependent scores
    objective_match = 0.5
    state_action_match = 0.5
    implementation_feasibility = 0.5

    if llm_client is not None:
        try:
            response = llm_client.call(
                system_prompt=SCORING_SYSTEM_PROMPT,
                user_prompt=SCORING_USER_PROMPT.format(
                    title=title,
                    abstract=abstract[:500],
                    objective=getattr(objective, "description", "") or getattr(objective, "name", ""),
                    metrics=", ".join(metric_keywords[:5]),
                    focus=", ".join(getattr(objective, "focus", [])[:5]),
                ),
                max_tokens=512,
                seed=42,
            )
            if response.parsed:
                objective_match = _clamp(response.parsed.get("objective_match", 0.5))
                state_action_match = _clamp(response.parsed.get("state_action_match", 0.5))
                implementation_feasibility = _clamp(response.parsed.get("implementation_feasibility", 0.5))
        except Exception:
            pass  # Use default 0.5

    return {
        "objective_match": objective_match,
        "metric_match": metric_match,
        "state_action_match": state_action_match,
        "implementation_feasibility": implementation_feasibility,
        "recency_or_influence": recency,
    }


def _compute_metric_match(text: str, metric_keywords: list[str]) -> float:
    """Compute metric_match as ratio of primary metric keywords found in text."""
    if not metric_keywords:
        return 0.0
    matched = sum(1 for kw in metric_keywords if kw in text)
    return round(matched / len(metric_keywords), 4)


def _compute_recency(published: str, current_year: int) -> float:
    """Compute recency score: max(0, 1 - (current_year - pub_year) / 10)."""
    try:
        pub_year = int(published[:4])
        return max(0.0, round(1.0 - (current_year - pub_year) / 10, 4))
    except (ValueError, IndexError):
        return 0.5  # Unknown year


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, value))


def _generate_markdown(selected: list[dict], top_k: int, min_score: float) -> str:
    """Generate Markdown report for selected papers."""
    lines = ["# Selected Reward Evidence", ""]
    lines.append(f"**Top-K:** {top_k}")
    lines.append(f"**Min relevance score:** {min_score}")
    lines.append(f"**Papers selected:** {len(selected)}")
    lines.append("")

    for i, paper in enumerate(selected, 1):
        scores = paper.get("scores", {})
        lines.append(f"## {i}. {paper.get('title', 'Untitled')}")
        lines.append(f"- **Paper ID:** `{paper.get('paper_id', 'N/A')}`")
        lines.append(f"- **Relevance Score:** {paper.get('relevance_score', 0):.4f}")
        lines.append(f"- **Published:** {paper.get('published', 'N/A')}")
        lines.append(f"- **Categories:** {', '.join(paper.get('categories', []))}")
        lines.append(f"- **Scores:**")
        for key in WEIGHTS:
            lines.append(f"  - {key}: {scores.get(key, 0):.4f}")
        lines.append("")

    return "\n".join(lines)
