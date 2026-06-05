"""CLI entry point for research-agent."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

from research_agent.core.config import AgentConfig, load_config
from research_agent.core.exceptions import ResearchAgentError
from research_agent.core.output import error_response, ok_response, print_json
from research_agent.core.state import (
    advance_phase,
    initial_state,
    read_state_json,
    write_state_json,
    cleanup_tmp_file,
    acquire_lock,
    release_lock,
    clear_stale_lock,
)


def _find_work_dir(project_path: Path) -> Path:
    """Get the .research-agent work directory for a project."""
    return project_path / ".research-agent"


def _ensure_work_dir(work_dir: Path) -> None:
    """Create work directory structure if it doesn't exist."""
    dirs = [
        work_dir / "reports",
        work_dir / "logs",
        work_dir / "patches",
        work_dir / "cache",
        work_dir / "artifacts",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def _load_config_or_default(work_dir: Path) -> AgentConfig:
    """Load config, falling back to defaults."""
    return load_config(work_dir)


@click.group()
@click.version_option(version="1.0.0")
def main():
    """Research Optimization Agent Platform."""
    pass


# --- init ---

@main.command()
@click.option("--project", required=True, type=click.Path(exists=True), help="Project root path")
def init(project: str):
    """Initialize research-agent for a project."""
    project_path = Path(project).resolve()
    work_dir = _find_work_dir(project_path)

    # Check idempotency
    if work_dir.exists():
        state_path = work_dir / "state.json"
        if state_path.exists():
            try:
                state = read_state_json(work_dir)
                if state.get("phase") != "initialized":
                    print_json(error_response(
                        "ALREADY_INITIALIZED",
                        f"Project already initialized at phase '{state.get('phase')}'. "
                        "Delete .research-agent/ to re-initialize.",
                        "Continue with other commands, or delete .research-agent/ to start fresh.",
                    ))
                    sys.exit(1)
            except Exception:
                pass  # Corrupt state — allow re-init

    # Create directory structure
    _ensure_work_dir(work_dir)

    # Copy default config
    default_config_path = Path(__file__).parent.parent.parent / "configs" / "default.yaml"
    config_path = work_dir / "config.yaml"
    if not config_path.exists() and default_config_path.exists():
        import shutil
        shutil.copy2(default_config_path, config_path)

    # Create empty report files
    report_files = [
        "front_agent_objective.md",
        "project_understanding.md",
        "project_understanding.json",
        "task_classification.json",
        "strategy_selection.md",
        "strategy_selection.json",
        "experiment_plan.md",
        "experiment_plan.json",
        "arxiv_papers.md",
        "paper_taxonomy.md",
        "selected_reward_evidence.md",
        "candidate_ledger.md",
        "extracted_ideas.md",
        "knowledge_base.md",
        "final_report.md",
        "final_report.json",
    ]
    for fname in report_files:
        fpath = work_dir / "reports" / fname
        if not fpath.exists():
            fpath.touch()

    # Create empty log files
    log_files = [
        "events.jsonl",
        "experiments.jsonl",
        "candidates.jsonl",
        "paper_taxonomy.jsonl",
        "selected_reward_evidence.jsonl",
        "extracted_ideas.jsonl",
        "arxiv_papers.jsonl",
        "llm_calls.jsonl",
    ]
    for fname in log_files:
        fpath = work_dir / "logs" / fname
        if not fpath.exists():
            fpath.touch()

    # Write initial state
    config = load_config(work_dir)
    config.project.path = str(project_path)
    state = initial_state(str(project_path), ".research-agent")
    write_state_json(work_dir, state)

    # Write updated config with project path
    with open(config_path, encoding="utf-8") as f:
        raw_config = yaml.safe_load(f) or {}
    raw_config.setdefault("project", {})["path"] = str(project_path)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(raw_config, f, default_flow_style=False, allow_unicode=True)

    print_json(ok_response({
        "phase": "initialized",
        "work_dir": str(work_dir),
        "project_path": str(project_path),
        "next_action": "Call 'understand --project <path>' to analyze the project.",
    }))


# --- understand ---

@main.command()
@click.option("--project", required=True, type=click.Path(exists=True), help="Project root path")
@click.option("--json", "json_output", is_flag=True, help="Output JSON to stdout")
def understand(project: str, json_output: bool):
    """Analyze project structure and identify optimization targets."""
    project_path = Path(project).resolve()
    work_dir = _find_work_dir(project_path)

    if not work_dir.exists():
        print_json(error_response(
            "NOT_INITIALIZED",
            "Project not initialized. Run 'init --project <path>' first.",
        ))
        sys.exit(1)

    config = _load_config_or_default(work_dir)
    cleanup_tmp_file(work_dir)

    from research_agent.core.project_understanding import understand_project

    try:
        result = understand_project(project_path, work_dir, config)

        # Update state
        state = read_state_json(work_dir)
        state["project_understanding"] = {
            "report": "reports/project_understanding.md",
            "json": "reports/project_understanding.json",
            "project_type": result.get("project_type", []),
        }
        state = advance_phase(state, "understood")
        write_state_json(work_dir, state)

        if json_output:
            print_json(result)
        else:
            md_path = work_dir / "reports" / "project_understanding.md"
            if md_path.exists():
                print(md_path.read_text(encoding="utf-8"))
            else:
                print_json(result)

    except ResearchAgentError as e:
        print_json(e.to_dict())
        sys.exit(1)


# --- classify-task ---

@main.command("classify-task")
@click.option("--json", "json_output", is_flag=True, help="Output JSON to stdout")
def classify_task_cmd(json_output: bool):
    """Classify research tasks from project understanding."""
    work_dir = _find_work_dir_from_cwd()
    if work_dir is None:
        print_json(error_response(
            "NOT_INITIALIZED",
            "No .research-agent directory found. Run 'init' first.",
        ))
        sys.exit(1)

    config = _load_config_or_default(work_dir)

    from research_agent.core.task_classifier import classify_task

    try:
        result = classify_task(work_dir, config)
        print_json(result)
    except ResearchAgentError as e:
        print_json(e.to_dict())
        sys.exit(1)


# --- select-strategy ---

@main.command("select-strategy")
@click.option("--json", "json_output", is_flag=True, help="Output JSON to stdout")
def select_strategy_cmd(json_output: bool):
    """Select optimizer strategies based on task classification."""
    work_dir = _find_work_dir_from_cwd()
    if work_dir is None:
        print_json(error_response(
            "NOT_INITIALIZED",
            "No .research-agent directory found. Run 'init' first.",
        ))
        sys.exit(1)

    from research_agent.core.strategy_selector import select_strategy

    try:
        result = select_strategy(work_dir)
        if json_output:
            print_json(result)
        else:
            md_path = work_dir / "reports" / "strategy_selection.md"
            if md_path.exists():
                print(md_path.read_text(encoding="utf-8"))
            else:
                print_json(result)
    except ResearchAgentError as e:
        print_json(e.to_dict())
        sys.exit(1)


# --- plan-experiments ---

@main.command("plan-experiments")
@click.option("--json", "json_output", is_flag=True, help="Output JSON to stdout")
def plan_experiments_cmd(json_output: bool):
    """Generate experiment plan with baseline and optimizer phases."""
    work_dir = _find_work_dir_from_cwd()
    if work_dir is None:
        print_json(error_response(
            "NOT_INITIALIZED",
            "No .research-agent directory found. Run 'init' first.",
        ))
        sys.exit(1)

    config = _load_config_or_default(work_dir)

    from research_agent.core.experiment_planner import plan_experiments

    try:
        result = plan_experiments(work_dir, config)
        if json_output:
            print_json(result)
        else:
            md_path = work_dir / "reports" / "experiment_plan.md"
            if md_path.exists():
                print(md_path.read_text(encoding="utf-8"))
            else:
                print_json(result)
    except ResearchAgentError as e:
        print_json(e.to_dict())
        sys.exit(1)


# --- search-papers ---

@main.command("search-papers")
@click.option("--topic", default=None, help="Explicit search topic override")
@click.option("--json", "json_output", is_flag=True, help="Output JSON to stdout")
def search_papers_cmd(topic: str | None, json_output: bool):
    """Search arxiv for papers relevant to the project objective."""
    work_dir = _find_work_dir_from_cwd()
    if work_dir is None:
        print_json(error_response(
            "NOT_INITIALIZED",
            "No .research-agent directory found. Run 'init' first.",
        ))
        sys.exit(1)

    config = _load_config_or_default(work_dir)

    from research_agent.literature.arxiv_searcher import search_papers

    try:
        result = search_papers(work_dir, config, topic_override=topic)
        if json_output:
            print_json(result)
        else:
            md_path = work_dir / "reports" / "arxiv_papers.md"
            if md_path.exists():
                print(md_path.read_text(encoding="utf-8"))
            else:
                print_json(result)
    except ResearchAgentError as e:
        print_json(e.to_dict())
        sys.exit(1)


# --- classify-papers ---

@main.command("classify-papers")
@click.option("--json", "json_output", is_flag=True, help="Output JSON to stdout")
def classify_papers_cmd(json_output: bool):
    """Classify found papers into taxonomy categories."""
    work_dir = _find_work_dir_from_cwd()
    if work_dir is None:
        print_json(error_response(
            "NOT_INITIALIZED",
            "No .research-agent directory found. Run 'init' first.",
        ))
        sys.exit(1)

    config = _load_config_or_default(work_dir)

    from research_agent.literature.paper_classifier import classify_papers

    try:
        result = classify_papers(work_dir, config)
        if json_output:
            print_json(result)
        else:
            md_path = work_dir / "reports" / "paper_taxonomy.md"
            if md_path.exists():
                print(md_path.read_text(encoding="utf-8"))
            else:
                print_json(result)
    except ResearchAgentError as e:
        print_json(e.to_dict())
        sys.exit(1)


# --- select-papers ---

@main.command("select-papers")
@click.option("--top-k", default=None, type=int, help="Override top-K selection count")
@click.option("--json", "json_output", is_flag=True, help="Output JSON to stdout")
def select_papers_cmd(top_k: int | None, json_output: bool):
    """Select top-K papers by relevance score."""
    work_dir = _find_work_dir_from_cwd()
    if work_dir is None:
        print_json(error_response(
            "NOT_INITIALIZED",
            "No .research-agent directory found. Run 'init' first.",
        ))
        sys.exit(1)

    config = _load_config_or_default(work_dir)

    from research_agent.literature.paper_selector import select_papers

    try:
        result = select_papers(work_dir, config, top_k_override=top_k)
        if json_output:
            print_json(result)
        else:
            md_path = work_dir / "reports" / "selected_reward_evidence.md"
            if md_path.exists():
                print(md_path.read_text(encoding="utf-8"))
            else:
                print_json(result)
    except ResearchAgentError as e:
        print_json(e.to_dict())
        sys.exit(1)


# --- extract-ideas ---

@main.command("extract-ideas")
@click.option("--json", "json_output", is_flag=True, help="Output JSON to stdout")
def extract_ideas_cmd(json_output: bool):
    """Extract research ideas from selected papers."""
    work_dir = _find_work_dir_from_cwd()
    if work_dir is None:
        print_json(error_response(
            "NOT_INITIALIZED",
            "No .research-agent directory found. Run 'init' first.",
        ))
        sys.exit(1)

    config = _load_config_or_default(work_dir)

    from research_agent.literature.paper_reader import extract_ideas

    try:
        result = extract_ideas(work_dir, config)
        if json_output:
            print_json(result)
        else:
            md_path = work_dir / "reports" / "extracted_ideas.md"
            if md_path.exists():
                print(md_path.read_text(encoding="utf-8"))
            else:
                print_json(result)
    except ResearchAgentError as e:
        print_json(e.to_dict())
        sys.exit(1)


# --- run-plan ---

@main.command("run-plan")
@click.option("--json", "json_output", is_flag=True, help="Output JSON to stdout")
def run_plan_cmd(json_output: bool):
    """Execute the full experiment plan."""
    work_dir = _find_work_dir_from_cwd()
    if work_dir is None:
        print_json(error_response(
            "NOT_INITIALIZED",
            "No .research-agent directory found. Run 'init' first.",
        ))
        sys.exit(1)

    config = _load_config_or_default(work_dir)

    from research_agent.core.executor import run_plan

    try:
        result = run_plan(work_dir, config)
        print_json(result)
    except ResearchAgentError as e:
        print_json(e.to_dict())
        sys.exit(1)


# --- run ---

@main.command("run")
@click.option("--phase", required=True, help="Phase ID to execute")
@click.option("--json", "json_output", is_flag=True, help="Output JSON to stdout")
def run_phase_cmd(phase: str, json_output: bool):
    """Execute a single experiment phase."""
    work_dir = _find_work_dir_from_cwd()
    if work_dir is None:
        print_json(error_response(
            "NOT_INITIALIZED",
            "No .research-agent directory found. Run 'init' first.",
        ))
        sys.exit(1)

    config = _load_config_or_default(work_dir)

    from research_agent.core.executor import run_phase

    try:
        result = run_phase(work_dir, config, phase_id=phase)
        print_json(result)
    except ResearchAgentError as e:
        print_json(e.to_dict())
        sys.exit(1)


# --- status ---

@main.command()
@click.option("--json", "json_output", is_flag=True, help="Output JSON to stdout")
@click.option("--clear-stale-lock", is_flag=True, help="Clear stale lock if PID is dead")
def status(json_output: bool, clear_stale_lock: bool):
    """Show current project status."""
    work_dir = _find_work_dir_from_cwd()
    if work_dir is None:
        print_json(error_response(
            "NOT_INITIALIZED",
            "No .research-agent directory found. Run 'init' first.",
        ))
        sys.exit(1)

    if clear_stale_lock:
        cleared = clear_stale_lock(work_dir)
        if cleared:
            print("Stale lock cleared.")
        else:
            print("No stale lock found.")

    try:
        state = read_state_json(work_dir)
        print_json(ok_response({
            "phase": state.get("phase"),
            "project_path": state.get("project_path"),
            "resource_usage": state.get("resource_usage"),
            "stop_reason": state.get("stop_reason"),
            "progress": state.get("progress"),
            "applied_patches": state.get("applied_patches"),
        }))
    except ResearchAgentError as e:
        print_json(e.to_dict())
        sys.exit(1)


# --- propose-candidate ---

@main.command("propose-candidate")
@click.option("--optimizer", required=True, type=click.Choice(["reward", "residual_control"]), help="Optimizer to use")
@click.option("--json", "json_output", is_flag=True, help="Output JSON to stdout")
def propose_candidate_cmd(optimizer: str, json_output: bool):
    """Propose a new candidate patch using the specified optimizer."""
    work_dir = _find_work_dir_from_cwd()
    if work_dir is None:
        print_json(error_response("NOT_INITIALIZED", "No .research-agent directory found."))
        sys.exit(1)

    config = _load_config_or_default(work_dir)
    state = read_state_json(work_dir)
    project_path = Path(state.get("project_path", ""))

    from research_agent.optimizers.reward.optimizer import RewardOptimizer
    from research_agent.optimizers.residual_control.optimizer import ResidualControlOptimizer

    try:
        if optimizer == "reward":
            opt = RewardOptimizer(work_dir, config, project_path)
        else:
            opt = ResidualControlOptimizer(work_dir, config, project_path)

        # Load experiment plan phase
        import json as _json
        plan_path = work_dir / "reports" / "experiment_plan.json"
        plan = {}
        if plan_path.exists():
            with open(plan_path, encoding="utf-8") as f:
                plan = _json.load(f).get("plan", {})

        # Find the optimizer phase
        phase = None
        for p in plan.get("phases", []):
            if p.get("optimizer") == optimizer:
                phase = p
                break

        if phase is None:
            print_json(error_response("NO_PHASE", f"No phase found for optimizer '{optimizer}'."))
            sys.exit(1)

        baseline = state.get("baseline_metrics", {})
        candidate = opt.propose_candidate(phase, baseline)

        print_json(ok_response({
            "candidate_id": candidate.candidate_id,
            "optimizer": candidate.optimizer,
            "description": candidate.description,
            "status": candidate.status,
        }))
    except ResearchAgentError as e:
        print_json(e.to_dict())
        sys.exit(1)


# --- generate-report ---

@main.command("generate-report")
@click.option("--json", "json_output", is_flag=True, help="Output JSON to stdout")
def generate_report_cmd(json_output: bool):
    """Generate final report from execution results."""
    work_dir = _find_work_dir_from_cwd()
    if work_dir is None:
        print_json(error_response("NOT_INITIALIZED", "No .research-agent directory found."))
        sys.exit(1)

    config = _load_config_or_default(work_dir)

    from research_agent.core.report_generator import generate_report

    try:
        result = generate_report(work_dir, config)
        if json_output:
            print_json(result)
        else:
            md_path = work_dir / "reports" / "final_report.md"
            if md_path.exists():
                print(md_path.read_text(encoding="utf-8"))
            else:
                print_json(result)
    except ResearchAgentError as e:
        print_json(e.to_dict())
        sys.exit(1)


# --- resume ---

@main.command()
@click.option("--json", "json_output", is_flag=True, help="Output JSON to stdout")
def resume_cmd(json_output: bool):
    """Resume an interrupted experiment run."""
    work_dir = _find_work_dir_from_cwd()
    if work_dir is None:
        print_json(error_response("NOT_INITIALIZED", "No .research-agent directory found."))
        sys.exit(1)

    from research_agent.core.resume import resume

    try:
        result = resume(work_dir)
        print_json(result)
    except ResearchAgentError as e:
        print_json(e.to_dict())
        sys.exit(1)


# --- cleanup ---

@main.command()
@click.option("--full", is_flag=True, help="Full cleanup (logs, artifacts, patches, cache)")
@click.option("--json", "json_output", is_flag=True, help="Output JSON to stdout")
def cleanup_cmd(full: bool, json_output: bool):
    """Clean up temporary files and reset transient state."""
    work_dir = _find_work_dir_from_cwd()
    if work_dir is None:
        print_json(error_response("NOT_INITIALIZED", "No .research-agent directory found."))
        sys.exit(1)

    from research_agent.core.cleanup import cleanup

    try:
        result = cleanup(work_dir, full=full)
        print_json(result)
    except ResearchAgentError as e:
        print_json(e.to_dict())
        sys.exit(1)


# --- git-snapshot ---

@main.command("git-snapshot")
@click.option("--message", required=True, help="Commit message")
@click.option("--json", "json_output", is_flag=True, help="Output JSON to stdout")
def git_snapshot_cmd(message: str, json_output: bool):
    """Create a git commit snapshot."""
    work_dir = _find_work_dir_from_cwd()
    if work_dir is None:
        print_json(error_response("NOT_INITIALIZED", "No .research-agent directory found."))
        sys.exit(1)

    state = read_state_json(work_dir)
    project_path = Path(state.get("project_path", ""))

    from research_agent.core.git_guard import git_snapshot

    try:
        result = git_snapshot(project_path, work_dir, message)
        print_json(result)
    except ResearchAgentError as e:
        print_json(e.to_dict())
        sys.exit(1)


def _find_work_dir_from_cwd() -> Path | None:
    """Find .research-agent in current directory or parents."""
    cwd = Path.cwd()
    work_dir = cwd / ".research-agent"
    if work_dir.exists():
        return work_dir
    # Check parent
    parent_work_dir = cwd.parent / ".research-agent"
    if parent_work_dir.exists():
        return parent_work_dir
    return None


if __name__ == "__main__":
    main()
