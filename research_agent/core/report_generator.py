"""Report generator: produce final JSON + Markdown report from execution results."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_agent.core.config import AgentConfig
from research_agent.core.output import ok_response, write_json_report, write_markdown_report
from research_agent.core.state import read_state_json


def generate_report(work_dir: Path, config: AgentConfig) -> dict:
    """Generate final report from all execution artifacts.

    Reads:
    - state.json (phase, resource_usage, baseline_metrics, execution_results)
    - reports/experiment_plan.json
    - logs/candidates.jsonl
    - reports/execution_report.json

    Writes:
    - reports/final_report.json
    - reports/final_report.md

    Returns:
        Response dict with report summary.
    """
    state = read_state_json(work_dir)

    # Load experiment plan
    plan = _load_json(work_dir / "reports" / "experiment_plan.json")

    # Load candidates
    candidates = _load_jsonl(work_dir / "logs" / "candidates.jsonl")

    # Load execution results
    execution = _load_json(work_dir / "reports" / "execution_report.json")

    # Build report
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_path": state.get("project_path", ""),
        "phase": state.get("phase", ""),
        "stop_reason": state.get("stop_reason"),
        "objective": {
            "name": config.objective.name,
            "description": config.objective.description,
        },
        "baseline_metrics": state.get("baseline_metrics", {}),
        "best_candidate": _find_best_candidate(candidates, state),
        "resource_usage": state.get("resource_usage", {}),
        "phases": execution.get("phases", []),
        "candidates_summary": _summarize_candidates(candidates),
        "primary_metrics": _extract_primary_metrics(config),
    }

    # Write JSON report
    write_json_report(work_dir / "reports" / "final_report.json", report)

    # Write Markdown report
    md = _generate_markdown(report)
    write_markdown_report(work_dir / "reports" / "final_report.md", md)

    return ok_response({
        "report_path": "reports/final_report.md",
        "json_path": "reports/final_report.json",
        "phase": report["phase"],
        "stop_reason": report["stop_reason"],
        "candidates_total": report["candidates_summary"]["total"],
        "candidates_accepted": report["candidates_summary"]["accepted"],
    })


def _find_best_candidate(candidates: list[dict], state: dict) -> dict | None:
    """Find the best accepted candidate."""
    accepted = [c for c in candidates if c.get("status") == "accepted"]
    if not accepted:
        return state.get("current_best")
    # Return the most recently accepted
    return accepted[-1]


def _summarize_candidates(candidates: list[dict]) -> dict:
    total = len(candidates)
    by_status: dict[str, int] = {}
    for c in candidates:
        s = c.get("status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1
    return {
        "total": total,
        "accepted": by_status.get("accepted", 0),
        "rejected": by_status.get("rejected", 0),
        "proposed": by_status.get("proposed", 0),
        "screened": by_status.get("screened", 0),
        "evaluated": by_status.get("evaluated", 0),
        "by_status": by_status,
    }


def _extract_primary_metrics(config: AgentConfig) -> list[dict]:
    return [
        {"name": m.get("name", m) if isinstance(m, dict) else m,
         "direction": m.get("direction", "maximize") if isinstance(m, dict) else "maximize"}
        for m in config.metrics.primary
    ]


def _load_json(path: Path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return items


def _generate_markdown(report: dict) -> str:
    lines = ["# Final Report", ""]
    lines.append(f"**Generated:** {report.get('generated_at', 'N/A')}")
    lines.append(f"**Project:** `{report.get('project_path', 'N/A')}`")
    lines.append(f"**Phase:** {report.get('phase', 'N/A')}")
    lines.append(f"**Stop reason:** {report.get('stop_reason', 'completed')}")
    lines.append("")

    # Objective
    obj = report.get("objective", {})
    lines.append("## Objective")
    lines.append(f"- **Name:** {obj.get('name', 'N/A')}")
    lines.append(f"- **Description:** {obj.get('description', 'N/A')}")
    lines.append("")

    # Baseline metrics
    baseline = report.get("baseline_metrics", {})
    lines.append("## Baseline Metrics")
    lines.append("")
    for name, vals in baseline.items():
        if isinstance(vals, dict):
            lines.append(f"- **{name}:** {vals.get('mean', 0):.4f} (std: {vals.get('std', 0):.4f})")
    lines.append("")

    # Best candidate
    best = report.get("best_candidate")
    if best:
        lines.append("## Best Candidate")
        lines.append(f"- **ID:** `{best.get('candidate_id', 'N/A')}`")
        lines.append(f"- **Description:** {best.get('description', 'N/A')}")
        lines.append(f"- **Status:** {best.get('status', 'N/A')}")
        lines.append("")
    else:
        lines.append("## Best Candidate")
        lines.append("No accepted candidate.")
        lines.append("")

    # Candidates summary
    summary = report.get("candidates_summary", {})
    lines.append("## Candidates Summary")
    lines.append(f"- **Total:** {summary.get('total', 0)}")
    lines.append(f"- **Accepted:** {summary.get('accepted', 0)}")
    lines.append(f"- **Rejected:** {summary.get('rejected', 0)}")
    lines.append("")

    # Resource usage
    ru = report.get("resource_usage", {})
    lines.append("## Resource Usage")
    lines.append(f"- **Wall clock:** {ru.get('wall_clock_seconds', 0):.1f}s")
    lines.append(f"- **Full evals:** {ru.get('full_evals_run', 0)}")
    lines.append("")

    return "\n".join(lines)
