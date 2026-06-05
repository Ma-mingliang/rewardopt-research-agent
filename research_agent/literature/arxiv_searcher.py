"""Arxiv paper search: generate queries and search arxiv for relevant papers."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from research_agent.core.config import AgentConfig
from research_agent.core.output import append_jsonl, ok_response, write_markdown_report
from research_agent.core.state import advance_phase, read_state_json, write_state_json
from research_agent.interfaces.front_agent_contract import require_phase

ARXIV_API_URL = "http://export.arxiv.org/api/query"
_POOL_PATH = Path(__file__).resolve().parent.parent / "reward_paper_pool" / "paper_pool.jsonl"


def search_papers(
    work_dir: Path,
    config: AgentConfig,
    topic_override: str | None = None,
    use_pool: bool = False,
) -> dict:
    """Search arxiv for papers relevant to the project objective.

    Query generation strategy:
    - From objective.focus keywords
    - From task_types
    - From recommended_strategies
    - From primary metric names
    - From topic_override (if provided)

    When use_pool=True, reads from the pre-collected reward_paper_pool
    instead of calling the arXiv API.

    Args:
        work_dir: .research-agent work directory.
        config: Agent configuration.
        topic_override: Optional explicit search topic.
        use_pool: If True, read from paper_pool.jsonl instead of arXiv API.

    Returns:
        Response dict with search results.
    """
    require_phase(work_dir, "planned")

    state = read_state_json(work_dir)
    lit_config = config.literature

    if use_pool:
        all_papers = _load_from_pool(config)
        queries = ["(pre-collected pool)"]
    else:
        # Generate queries
        queries = _generate_queries(work_dir, config, topic_override)
        max_queries = lit_config.max_queries
        queries = queries[:max_queries]

        # Search arxiv
        all_papers = []
        seen_ids: set[str] = set()

        for query in queries:
            papers = _search_arxiv(query, lit_config.max_results_per_query)
            for paper in papers:
                pid = paper.get("paper_id", "")
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    all_papers.append(paper)

    # Write outputs
    log_path = work_dir / "logs" / "arxiv_papers.jsonl"
    for paper in all_papers:
        append_jsonl(log_path, paper)

    md = _generate_markdown(all_papers, queries)
    write_markdown_report(work_dir / "reports" / "arxiv_papers.md", md)

    # Update state
    state = read_state_json(work_dir)
    state["literature"]["arxiv_papers"] = "logs/arxiv_papers.jsonl"
    state = advance_phase(state, "literature_searched")
    write_state_json(work_dir, state)

    return ok_response({
        "papers_found": len(all_papers),
        "source": "pool" if use_pool else "arxiv_api",
        "queries_used": queries,
        "log_path": "logs/arxiv_papers.jsonl",
        "report_path": "reports/arxiv_papers.md",
        "next_action": "Call 'classify-papers' to categorize found papers.",
    })


def _generate_queries(
    work_dir: Path,
    config: AgentConfig,
    topic_override: str | None,
) -> list[str]:
    """Generate search queries from objective, task types, and config."""
    queries: list[str] = []

    if topic_override:
        queries.append(topic_override)

    # From objective.focus
    objective = config.objective
    for focus in objective.focus:
        queries.append(f"{focus} reward shaping reinforcement learning")

    # From primary metric names
    for metric in config.metrics.primary:
        name = metric.get("name", "") if isinstance(metric, dict) else str(metric)
        if name:
            queries.append(f"{name.replace('_', ' ')} optimization control")

    # From config objective name/description
    if objective.name:
        queries.append(objective.name.replace("_", " "))
    if objective.description:
        queries.append(objective.description[:100])

    # Load task classification for strategy-based queries
    classification_path = work_dir / "reports" / "task_classification.json"
    if classification_path.exists() and classification_path.stat().st_size > 0:
        try:
            with open(classification_path, encoding="utf-8") as f:
                classification = json.load(f)
            for strategy in classification.get("recommended_strategies", []):
                queries.append(f"{strategy} reinforcement learning")
        except (json.JSONDecodeError, OSError):
            pass

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        q_normalized = q.strip().lower()
        if q_normalized and q_normalized not in seen:
            seen.add(q_normalized)
            unique.append(q.strip())

    return unique


def _load_from_pool(config: AgentConfig) -> list[dict]:
    """Load papers from the pre-collected reward_paper_pool.

    Normalizes pool format to match pipeline expectations:
    - year -> published
    - url -> arxiv_url
    """
    if not _POOL_PATH.exists():
        return []

    papers: list[dict] = []
    with open(_POOL_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Normalize authors: handle both str and dict formats
            raw_authors = raw.get("authors", [])
            authors = []
            for a in raw_authors:
                if isinstance(a, dict):
                    authors.append(a.get("fullname", a.get("name", str(a))))
                else:
                    authors.append(str(a))

            # Normalize to pipeline format
            paper = {
                "paper_id": raw.get("paper_id", ""),
                "title": raw.get("title", ""),
                "abstract": raw.get("abstract", ""),
                "authors": authors,
                "published": str(raw.get("year", raw.get("published", ""))),
                "arxiv_url": raw.get("url", raw.get("arxiv_url", "")),
                "categories": raw.get("categories", []),
            }
            papers.append(paper)

    return papers


def _search_arxiv(query: str, max_results: int) -> list[dict]:
    """Search arxiv API and return parsed paper records."""
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }

    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(ARXIV_API_URL, params=params)
            resp.raise_for_status()
    except (httpx.HTTPStatusError, httpx.TimeoutException, OSError):
        return []

    return _parse_arxiv_xml(resp.text)


def _parse_arxiv_xml(xml_text: str) -> list[dict]:
    """Parse arxiv Atom XML response into paper records."""
    papers: list[dict] = []

    # Simple regex-based XML parsing (no lxml dependency)
    entries = re.split(r"<entry>", xml_text)[1:]  # Skip header

    for entry in entries:
        paper_id = _extract_tag(entry, "id")
        title = _extract_tag(entry, "title").replace("\n", " ").strip()
        abstract = _extract_tag(entry, "summary").replace("\n", " ").strip()
        published = _extract_tag(entry, "published")[:10]  # YYYY-MM-DD

        # Authors
        authors = re.findall(r"<name>(.*?)</name>", entry)

        # Categories
        categories = re.findall(r'<category[^>]*term="([^"]*)"', entry)

        # Arxiv URL
        arxiv_url = paper_id if paper_id else ""

        # Extract arxiv ID
        arxiv_id = ""
        if paper_id:
            match = re.search(r"(\d{4}\.\d{4,5})", paper_id)
            if match:
                arxiv_id = f"arxiv:{match.group(1)}"

        papers.append({
            "paper_id": arxiv_id or paper_id,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "published": published,
            "arxiv_url": arxiv_url,
            "categories": categories,
        })

    return papers


def _extract_tag(xml: str, tag: str) -> str:
    """Extract text content from an XML tag."""
    match = re.search(f"<{tag}[^>]*>(.*?)</{tag}>", xml, re.DOTALL)
    return match.group(1).strip() if match else ""


def _generate_markdown(papers: list[dict], queries: list[str]) -> str:
    """Generate Markdown report for search results."""
    lines = ["# Arxiv Paper Search Results", ""]
    lines.append(f"**Papers found:** {len(papers)}")
    lines.append(f"**Queries used:** {len(queries)}")
    lines.append("")

    lines.append("## Queries")
    lines.append("")
    for i, q in enumerate(queries, 1):
        lines.append(f"{i}. {q}")
    lines.append("")

    lines.append("## Papers")
    lines.append("")
    for paper in papers[:50]:  # Limit display
        lines.append(f"### {paper.get('title', 'Untitled')}")
        lines.append(f"- **ID:** `{paper.get('paper_id', 'N/A')}`")
        lines.append(f"- **Published:** {paper.get('published', 'N/A')}")
        lines.append(f"- **Authors:** {', '.join(paper.get('authors', [])[:5])}")
        lines.append(f"- **Categories:** {', '.join(paper.get('categories', []))}")
        abstract = paper.get("abstract", "")
        if len(abstract) > 300:
            abstract = abstract[:300] + "..."
        lines.append(f"- **Abstract:** {abstract}")
        lines.append("")

    return "\n".join(lines)
