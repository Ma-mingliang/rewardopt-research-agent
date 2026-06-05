"""Project understanding: analyze project structure and identify optimization targets."""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

from research_agent.core.config import AgentConfig
from research_agent.core.llm_client import LLMClient
from research_agent.core.output import ok_response
from research_agent.interfaces.json_protocol import (
    write_understanding_json,
    write_understanding_markdown,
)

UNDERSTAND_SYSTEM_PROMPT = """You are a research project analyzer for RL and control projects.
Given a list of Python files and their contents, identify:
1. Project type (residual_rl, hierarchical_control, path_tracking, etc.)
2. Control structure (e.g., "Dynamic LQR + LQR Residual")
3. Training and evaluation entry points
4. Optimizable targets (reward functions, penalty terms)
5. Readonly targets (base controllers, algorithms)
6. Metric output locations
7. Optimizer affinity (which optimizer plugins fit)

Return JSON only."""

UNDERSTAND_USER_PROMPT = """Project path: {project_path}

Python files found:
{file_list}

Key file contents (truncated):
{file_contents}

Return JSON:
{{
  "project_type": ["<type1>", "<type2>"],
  "control_structure": "<description>",
  "train_entry": "<path>",
  "eval_entry": "<path>",
  "config_files": ["<file1>"],
  "optimizable_targets": [
    {{"name": "<name>", "file": "<path>", "line_range": [start, end], "type": "reward_function|penalty_term"}}
  ],
  "readonly_targets": [
    {{"name": "<name>", "file": "<path>", "reason": "base_controller_law|algorithm_body"}}
  ],
  "metric_output_locations": [
    {{"metric": "<name>", "source": "eval stdout|<file>", "pattern": "<regex>"}}
  ],
  "optimizer_affinity": ["reward", "residual_control"]
}}"""


def understand_project(
    project_path: Path,
    work_dir: Path,
    config: AgentConfig,
    llm_client: LLMClient | None = None,
) -> dict:
    """Analyze a project and produce understanding report.

    Args:
        project_path: Root directory of the target project.
        work_dir: .research-agent work directory.
        config: Agent configuration.
        llm_client: LLM client (created from config if None).

    Returns:
        Response dict with project understanding data.
    """
    # Scan Python files
    ignore_dirs = set(config.project.ignore_dirs)
    py_files = _scan_python_files(project_path, ignore_dirs)

    # Read key file contents (truncated)
    file_contents = _read_key_files(project_path, py_files, max_files=20, max_chars=5000)

    if llm_client is None:
        llm_client = LLMClient(
            config.llm.model_dump(),
            log_path=work_dir / "logs" / "llm_calls.jsonl",
        )

    # Call LLM
    file_list = "\n".join(f"  - {f}" for f in py_files[:50])
    response = llm_client.call(
        system_prompt=UNDERSTAND_SYSTEM_PROMPT,
        user_prompt=UNDERSTAND_USER_PROMPT.format(
            project_path=project_path,
            file_list=file_list,
            file_contents=file_contents,
        ),
        max_tokens=4096,
    )

    result = response.parsed or {}

    # Build output
    output = ok_response({
        "project_type": result.get("project_type", []),
        "control_structure": result.get("control_structure", "unknown"),
        "train_entry": result.get("train_entry", ""),
        "eval_entry": result.get("eval_entry", ""),
        "config_files": result.get("config_files", []),
        "optimizable_targets": result.get("optimizable_targets", []),
        "readonly_targets": result.get("readonly_targets", []),
        "metric_output_locations": result.get("metric_output_locations", []),
        "optimizer_affinity": result.get("optimizer_affinity", []),
        "report_path": "reports/project_understanding.md",
    })

    # Write reports
    write_understanding_json(work_dir, output)
    md = _generate_markdown(output)
    write_understanding_markdown(work_dir, md)

    return output


def _scan_python_files(project_path: Path, ignore_dirs: set[str]) -> list[str]:
    """Find all Python files, excluding ignored directories."""
    results = []
    for py_file in project_path.rglob("*.py"):
        rel = py_file.relative_to(project_path)
        parts = rel.parts
        if any(part in ignore_dirs for part in parts):
            continue
        results.append(str(rel))
    results.sort()
    return results


def _read_key_files(
    project_path: Path,
    file_list: list[str],
    max_files: int = 20,
    max_chars: int = 5000,
) -> str:
    """Read contents of key files, truncated."""
    # Prioritize files likely to contain reward, train, eval logic
    priority_keywords = ["reward", "train", "eval", "env", "config", "main", "run"]
    sorted_files = sorted(
        file_list,
        key=lambda f: any(kw in f.lower() for kw in priority_keywords),
        reverse=True,
    )

    parts = []
    for fpath in sorted_files[:max_files]:
        full_path = project_path / fpath
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
            if len(content) > max_chars:
                content = content[:max_chars] + "\n... (truncated)"
            parts.append(f"=== {fpath} ===\n{content}")
        except OSError:
            continue

    return "\n\n".join(parts)


def _generate_markdown(data: dict) -> str:
    """Generate Markdown report from understanding data."""
    lines = ["# Project Understanding Report", ""]

    lines.append(f"**Project types:** {', '.join(data.get('project_type', []))}")
    lines.append(f"**Control structure:** {data.get('control_structure', 'N/A')}")
    lines.append(f"**Train entry:** `{data.get('train_entry', 'N/A')}`")
    lines.append(f"**Eval entry:** `{data.get('eval_entry', 'N/A')}`")
    lines.append("")

    opt_targets = data.get("optimizable_targets", [])
    if opt_targets:
        lines.append("## Optimizable Targets")
        lines.append("")
        for t in opt_targets:
            lines.append(f"- `{t.get('name', '?')}` in `{t.get('file', '?')}` "
                         f"(lines {t.get('line_range', '?')}, type: {t.get('type', '?')})")
        lines.append("")

    ro_targets = data.get("readonly_targets", [])
    if ro_targets:
        lines.append("## Readonly Targets")
        lines.append("")
        for t in ro_targets:
            lines.append(f"- `{t.get('name', '?')}` in `{t.get('file', '?')}` "
                         f"(reason: {t.get('reason', '?')})")
        lines.append("")

    affinity = data.get("optimizer_affinity", [])
    if affinity:
        lines.append(f"**Optimizer affinity:** {', '.join(affinity)}")

    return "\n".join(lines)
