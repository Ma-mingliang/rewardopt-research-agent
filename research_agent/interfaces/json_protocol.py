"""JSON protocol for front agent ↔ research-agent communication."""

from __future__ import annotations

from pathlib import Path

from research_agent.core.output import write_json_report, write_markdown_report


def write_plan_json(work_dir: Path, plan_data: dict) -> Path:
    """Write experiment_plan.json and return its path."""
    json_path = work_dir / "reports" / "experiment_plan.json"
    write_json_report(json_path, plan_data)
    return json_path


def write_plan_markdown(work_dir: Path, markdown: str) -> Path:
    """Write experiment_plan.md and return its path."""
    md_path = work_dir / "reports" / "experiment_plan.md"
    write_markdown_report(md_path, markdown)
    return md_path


def write_understanding_json(work_dir: Path, data: dict) -> Path:
    """Write project_understanding.json and return its path."""
    json_path = work_dir / "reports" / "project_understanding.json"
    write_json_report(json_path, data)
    return json_path


def write_understanding_markdown(work_dir: Path, markdown: str) -> Path:
    """Write project_understanding.md and return its path."""
    md_path = work_dir / "reports" / "project_understanding.md"
    write_markdown_report(md_path, markdown)
    return md_path


def write_classification_json(work_dir: Path, data: dict) -> Path:
    """Write task_classification.json and return its path."""
    json_path = work_dir / "reports" / "task_classification.json"
    write_json_report(json_path, data)
    return json_path


def write_strategy_json(work_dir: Path, data: dict) -> Path:
    """Write strategy_selection.json and return its path."""
    json_path = work_dir / "reports" / "strategy_selection.json"
    write_json_report(json_path, data)
    return json_path


def write_strategy_markdown(work_dir: Path, markdown: str) -> Path:
    """Write strategy_selection.md and return its path."""
    md_path = work_dir / "reports" / "strategy_selection.md"
    write_markdown_report(md_path, markdown)
    return md_path
