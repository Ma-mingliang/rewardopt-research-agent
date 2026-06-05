"""Paper classification: categorize papers into reward/control/safety taxonomy."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_agent.core.config import AgentConfig
from research_agent.core.llm_client import LLMClient
from research_agent.core.output import append_jsonl, ok_response, write_markdown_report
from research_agent.core.state import advance_phase, read_state_json, write_state_json
from research_agent.interfaces.front_agent_contract import require_phase

CLASSIFICATION_CATEGORIES = [
    "reward shaping",
    "penalty and constraint design",
    "curriculum reward",
    "robotics locomotion reward",
    "control energy and smoothness",
    "reward hacking and specification gaming",
    "residual control",
    "path tracking control",
]

# Keyword mapping for rule-based fallback
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "reward shaping": ["reward shaping", "reward design", "reward function", "reward engineering"],
    "penalty and constraint design": ["penalty", "constraint", "safety constraint", "barrier function"],
    "curriculum reward": ["curriculum", "curriculum learning", "progressive"],
    "robotics locomotion reward": ["locomotion", "robot", "walking", "quadruped", "bipedal", "humanoid"],
    "control energy and smoothness": ["control energy", "smoothness", "energy efficient", "regularization"],
    "reward hacking and specification gaming": ["reward hacking", "specification gaming", "reward misalignment", "Goodhart"],
    "residual control": ["residual", "residual control", "residual policy", "augmented control"],
    "path tracking control": ["path tracking", "trajectory", "tracking control", "lateral control", "stanley"],
}

CLASSIFY_SYSTEM_PROMPT = """You are a paper classifier for RL and control research.
Given a paper's title and abstract, classify it into one or more categories.
Return JSON only."""

CLASSIFY_USER_PROMPT = """Paper title: {title}
Paper abstract: {abstract}

Available categories: {categories}

Return JSON:
{{"categories": ["<cat1>", "<cat2>"], "confidence": <0-1>}}"""


def classify_papers(work_dir: Path, config: AgentConfig) -> dict:
    """Classify papers from arxiv_papers.jsonl into taxonomy categories.

    Method: keyword pre-classification + LLM fine classification + merge.
    Fallback: pure keyword matching (confidence capped at 0.5).

    Args:
        work_dir: .research-agent work directory.
        config: Agent configuration.

    Returns:
        Response dict with classification results.
    """
    require_phase(work_dir, "literature_searched")

    # Load papers
    papers = _load_papers(work_dir)
    if not papers:
        return ok_response({
            "papers_classified": 0,
            "message": "No papers found. Run 'search-papers' first.",
        })

    # Try LLM classification
    llm_client = None
    use_llm = True
    try:
        llm_client = LLMClient(
            config.llm.model_dump(),
            log_path=work_dir / "logs" / "llm_calls.jsonl",
        )
    except Exception:
        use_llm = False

    categories = config.literature.classification_categories or CLASSIFICATION_CATEGORIES
    classified: list[dict] = []

    for paper in papers:
        result = _classify_single_paper(paper, categories, llm_client if use_llm else None)
        classified.append({**paper, **result})

    # Write outputs
    log_path = work_dir / "logs" / "paper_taxonomy.jsonl"
    for entry in classified:
        record = {
            "paper_id": entry.get("paper_id", ""),
            "title": entry.get("title", ""),
            "categories": entry.get("categories", []),
            "confidence": entry.get("confidence", 0.0),
            "classified_at": datetime.now(timezone.utc).isoformat(),
        }
        append_jsonl(log_path, record)

    md = _generate_markdown(classified)
    write_markdown_report(work_dir / "reports" / "paper_taxonomy.md", md)

    # Update state
    state = read_state_json(work_dir)
    state["literature"]["paper_taxonomy"] = "logs/paper_taxonomy.jsonl"
    state = advance_phase(state, "literature_classified")
    write_state_json(work_dir, state)

    return ok_response({
        "papers_classified": len(classified),
        "log_path": "logs/paper_taxonomy.jsonl",
        "report_path": "reports/paper_taxonomy.md",
        "next_action": "Call 'select-papers' to select top-K evidence.",
    })


def _load_papers(work_dir: Path) -> list[dict]:
    """Load papers from arxiv_papers.jsonl."""
    log_path = work_dir / "logs" / "arxiv_papers.jsonl"
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


def _classify_single_paper(
    paper: dict,
    categories: list[str],
    llm_client: LLMClient | None,
) -> dict:
    """Classify a single paper using keyword + LLM hybrid."""
    title = paper.get("title", "")
    abstract = paper.get("abstract", "")
    text = f"{title} {abstract}".lower()

    # Step 1: Keyword pre-classification
    keyword_cats = []
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw.lower() in text for kw in keywords):
            keyword_cats.append(cat)

    # Step 2: LLM fine classification (if available)
    llm_cats = []
    llm_confidence = 0.0

    if llm_client is not None:
        try:
            response = llm_client.call(
                system_prompt=CLASSIFY_SYSTEM_PROMPT,
                user_prompt=CLASSIFY_USER_PROMPT.format(
                    title=title,
                    abstract=abstract[:500],
                    categories=categories,
                ),
                max_tokens=256,
            )
            if response.parsed:
                llm_cats = response.parsed.get("categories", [])
                llm_confidence = response.parsed.get("confidence", 0.0)
        except Exception:
            pass

    # Step 3: Merge (union of keyword and LLM results)
    merged = list(dict.fromkeys(keyword_cats + llm_cats))  # Deduplicate preserving order
    if not merged:
        merged = ["uncategorized"]

    # Confidence: use LLM confidence if available, else keyword-based
    if llm_confidence > 0:
        confidence = llm_confidence
    elif keyword_cats:
        confidence = 0.5  # Keyword-only fallback cap
    else:
        confidence = 0.3

    return {
        "categories": merged,
        "confidence": round(confidence, 2),
    }


def _generate_markdown(classified: list[dict]) -> str:
    """Generate Markdown report for paper taxonomy."""
    lines = ["# Paper Taxonomy", ""]
    lines.append(f"**Papers classified:** {len(classified)}")
    lines.append("")

    # Group by category
    by_category: dict[str, list[dict]] = {}
    for paper in classified:
        for cat in paper.get("categories", []):
            by_category.setdefault(cat, []).append(paper)

    for cat, papers in sorted(by_category.items()):
        lines.append(f"## {cat} ({len(papers)} papers)")
        lines.append("")
        for p in papers:
            lines.append(f"- `{p.get('paper_id', '?')}` {p.get('title', 'Untitled')} "
                         f"(confidence: {p.get('confidence', 0)})")
        lines.append("")

    return "\n".join(lines)
