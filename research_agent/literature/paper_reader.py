"""Extract ideas: extract unverified hypotheses from selected papers."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_agent.core.config import AgentConfig
from research_agent.core.llm_client import LLMClient
from research_agent.core.output import append_jsonl, ok_response, write_markdown_report
from research_agent.core.state import advance_phase, read_state_json, write_state_json
from research_agent.interfaces.front_agent_contract import require_phase

EXTRACT_SYSTEM_PROMPT = """You are a research idea extractor for RL and control projects.
Given a paper's abstract and the project objective, extract actionable ideas for reward shaping or control optimization.
Return JSON only."""

EXTRACT_USER_PROMPT = """Paper title: {title}
Paper abstract: {abstract}
Paper categories: {categories}

Project objective: {objective}
Focus areas: {focus}

Extract 1-3 concrete ideas for improving the project based on this paper.
Return JSON:
{{"ideas": [{{"description": "<idea>", "category": "<category>", "feasibility": "high|medium|low"}}]}}"""


def extract_ideas(
    work_dir: Path,
    config: AgentConfig,
    mock_llm: bool = False,
) -> dict:
    """Extract ideas from selected papers.

    Traverses selected papers, combines with knowledge base,
    extracts reward shaping ideas, filters rejected hypotheses.

    Args:
        work_dir: .research-agent work directory.
        config: Agent configuration.
        mock_llm: If True, skip LLM calls and use keyword-based fallback.

    Returns:
        Response dict with extracted ideas.
    """
    require_phase(work_dir, "literature_selected")

    # Load selected papers
    papers = _load_selected_papers(work_dir)
    if not papers:
        return ok_response({
            "ideas_extracted": 0,
            "message": "No selected papers found. Run 'select-papers' first.",
        })

    # Try LLM extraction
    llm_client = None
    if not mock_llm:
        try:
            llm_client = LLMClient(
                config.llm.model_dump(),
                log_path=work_dir / "logs" / "llm_calls.jsonl",
            )
        except Exception:
            pass

    max_ideas = config.literature.max_extracted_ideas
    objective = config.objective

    all_ideas: list[dict] = []
    idea_counter = 0
    errors: list[dict] = []
    total = min(len(papers), 20)

    for idx, paper in enumerate(papers[:20]):
        paper_id = paper.get("paper_id", "?")
        title = paper.get("title", "?")[:60]
        _log_progress(f"[extract-ideas] {idx+1}/{total} {paper_id} {title}")

        try:
            ideas = _extract_from_paper(paper, objective, llm_client)
        except Exception as e:
            errors.append({
                "paper_id": paper_id,
                "error": str(e)[:200],
            })
            _log_progress(f"[extract-ideas]   ERROR: {str(e)[:80]}")
            continue

        for idea in ideas:
            idea_counter += 1
            idea_record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "idea_id": f"idea_{idea_counter:03d}",
                "source_paper": paper_id,
                "description": idea.get("description", ""),
                "category": idea.get("category", "uncategorized"),
                "feasibility": idea.get("feasibility", "medium"),
                "related_hypotheses": [],
                "status": "open",
            }
            all_ideas.append(idea_record)

        _log_progress(f"[extract-ideas]   -> {len(ideas)} idea(s)")

    # Dedup by description similarity
    all_ideas = _dedup_ideas(all_ideas)

    # Truncate by max_ideas (feasibility priority)
    feasibility_order = {"high": 0, "medium": 1, "low": 2}
    all_ideas.sort(key=lambda x: feasibility_order.get(x.get("feasibility", "medium"), 1))
    all_ideas = all_ideas[:max_ideas]

    # Write outputs
    log_path = work_dir / "logs" / "extracted_ideas.jsonl"
    for idea in all_ideas:
        append_jsonl(log_path, idea)

    md = _generate_markdown(all_ideas)
    write_markdown_report(work_dir / "reports" / "extracted_ideas.md", md)

    # Update state
    state = read_state_json(work_dir)
    state["literature"]["extracted_ideas"] = "logs/extracted_ideas.jsonl"
    state = advance_phase(state, "ideas_extracted")
    write_state_json(work_dir, state)

    result: dict[str, Any] = {
        "ideas_extracted": len(all_ideas),
        "papers_processed": total,
        "errors": len(errors),
        "source": "mock" if mock_llm else ("llm" if llm_client else "fallback"),
        "ideas": [
            {
                "idea_id": i["idea_id"],
                "source_paper": i["source_paper"],
                "description": i["description"],
                "category": i["category"],
                "feasibility": i["feasibility"],
                "related_hypotheses": i["related_hypotheses"],
            }
            for i in all_ideas
        ],
        "total": len(all_ideas),
        "log_path": "logs/extracted_ideas.jsonl",
        "report_path": "reports/extracted_ideas.md",
        "next_action": "Call 'run-plan' to start experiment execution.",
    }
    if errors:
        result["error_details"] = errors[:5]
    return ok_response(result)


def _load_selected_papers(work_dir: Path) -> list[dict]:
    """Load selected papers from selected_reward_evidence.jsonl."""
    log_path = work_dir / "logs" / "selected_reward_evidence.jsonl"
    papers: list[dict] = []
    if not log_path.exists():
        return papers
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    papers.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return papers


def _extract_from_paper(
    paper: dict,
    objective: Any,
    llm_client: LLMClient | None,
) -> list[dict]:
    """Extract ideas from a single paper."""
    if llm_client is None:
        # Fallback: generate a generic idea from paper categories
        categories = paper.get("categories", [])
        return [{
            "description": f"Apply techniques from '{paper.get('title', 'unknown')}' to improve {', '.join(categories[:2])}",
            "category": categories[0] if categories else "uncategorized",
            "feasibility": "medium",
        }]

    response = llm_client.call(
        system_prompt=EXTRACT_SYSTEM_PROMPT,
        user_prompt=EXTRACT_USER_PROMPT.format(
            title=paper.get("title", ""),
            abstract=paper.get("abstract", "")[:500],
            categories=", ".join(paper.get("categories", [])),
            objective=getattr(objective, "description", "") or getattr(objective, "name", ""),
            focus=", ".join(getattr(objective, "focus", [])[:5]),
        ),
        max_tokens=1024,
    )
    if response.parsed:
        return response.parsed.get("ideas", [])
    return []


def _dedup_ideas(ideas: list[dict]) -> list[dict]:
    """Deduplicate ideas by description similarity."""
    seen_descriptions: set[str] = set()
    seen_papers: set[str] = set()
    unique: list[dict] = []

    for idea in ideas:
        desc = idea.get("description", "").lower().strip()
        paper = idea.get("source_paper", "")

        # Same description or same source paper with similar idea
        if desc in seen_descriptions:
            continue
        if paper and paper in seen_papers:
            # Keep the one with higher feasibility
            for i, existing in enumerate(unique):
                if existing.get("source_paper") == paper:
                    feas_order = {"high": 2, "medium": 1, "low": 0}
                    if feas_order.get(idea.get("feasibility", "medium"), 1) > \
                       feas_order.get(existing.get("feasibility", "medium"), 1):
                        unique[i] = idea
                    break
            continue

        seen_descriptions.add(desc)
        if paper:
            seen_papers.add(paper)
        unique.append(idea)

    return unique


def _generate_markdown(ideas: list[dict]) -> str:
    """Generate Markdown report for extracted ideas."""
    lines = ["# Extracted Ideas", ""]
    lines.append(f"**Total ideas:** {len(ideas)}")
    lines.append("")

    by_category: dict[str, list[dict]] = {}
    for idea in ideas:
        cat = idea.get("category", "uncategorized")
        by_category.setdefault(cat, []).append(idea)

    for cat, cat_ideas in sorted(by_category.items()):
        lines.append(f"## {cat} ({len(cat_ideas)} ideas)")
        lines.append("")
        for idea in cat_ideas:
            lines.append(f"- **{idea.get('idea_id', '?')}** [{idea.get('feasibility', '?')}] "
                         f"{idea.get('description', 'N/A')}")
            lines.append(f"  Source: `{idea.get('source_paper', 'N/A')}` | Status: {idea.get('status', 'open')}")
        lines.append("")

    return "\n".join(lines)


def _log_progress(msg: str) -> None:
    """Print progress to stderr (not stdout, which is reserved for JSON)."""
    print(msg, file=sys.stderr, flush=True)
