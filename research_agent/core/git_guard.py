"""Git guard: manage git operations for experiment tracking."""

from __future__ import annotations

import subprocess
from pathlib import Path

from research_agent.core.output import ok_response
from research_agent.core.state import read_state_json, write_state_json


def git_init_check(project_path: Path) -> dict:
    """Check if project is a git repo and record in state.

    Returns:
        Response dict with git status.
    """
    is_repo = _is_git_repo(project_path)

    if not is_repo:
        return ok_response({
            "is_git_repo": False,
            "message": "Project is not a git repository. Run 'git init' first.",
        })

    branch = _get_current_branch(project_path)
    dirty = _is_dirty(project_path)

    return ok_response({
        "is_git_repo": True,
        "branch": branch,
        "dirty": dirty,
    })


def git_snapshot(project_path: Path, work_dir: Path, message: str) -> dict:
    """Create a git commit snapshot of current state.

    Args:
        project_path: Project root.
        work_dir: .research-agent work dir.
        message: Commit message.

    Returns:
        Response dict with commit hash.
    """
    if not _is_git_repo(project_path):
        return {"ok": False, "error": "Not a git repository"}

    # Stage all changes
    _run_git(project_path, ["add", "-A"])

    # Check if there's anything to commit
    status = _run_git(project_path, ["status", "--porcelain"])
    if not status.strip():
        return ok_response({
            "commit": None,
            "message": "No changes to commit",
        })

    # Commit
    _run_git(project_path, ["commit", "-m", message])

    # Get commit hash
    commit_hash = _run_git(project_path, ["rev-parse", "HEAD"]).strip()

    return ok_response({
        "commit": commit_hash,
        "message": message,
    })


def git_rollback(project_path: Path, commit_hash: str) -> dict:
    """Rollback to a specific commit.

    Args:
        project_path: Project root.
        commit_hash: Target commit to rollback to.

    Returns:
        Response dict.
    """
    if not _is_git_repo(project_path):
        return {"ok": False, "error": "Not a git repository"}

    _run_git(project_path, ["checkout", commit_hash, "--", "."])

    return ok_response({
        "rolled_back_to": commit_hash,
    })


def git_guard_pre_run(project_path: Path, work_dir: Path) -> dict:
    """Pre-run git guard: snapshot current state before experiments.

    Records baseline commit in state.json.
    """
    if not _is_git_repo(project_path):
        return ok_response({"skipped": True, "reason": "Not a git repo"})

    # Check dirty worktree
    dirty = _is_dirty(project_path)
    state = read_state_json(work_dir)

    if dirty and state.get("git", {}).get("dirty_worktree_policy") == "abort":
        return {
            "ok": False,
            "error": "DIRTY_WORKTREE",
            "message": "Worktree is dirty. Commit or stash changes before running experiments.",
        }

    # Snapshot
    result = git_snapshot(project_path, work_dir, "research-agent: pre-run snapshot")
    commit = result.get("commit")

    if commit:
        state = read_state_json(work_dir)
        state["git"]["baseline_commit"] = commit
        write_state_json(work_dir, state)

    return ok_response({
        "baseline_commit": commit,
        "dirty": dirty,
    })


def git_guard_post_run(project_path: Path, work_dir: Path, accepted: bool) -> dict:
    """Post-run git guard: commit if accepted, rollback if rejected.

    Args:
        project_path: Project root.
        work_dir: .research-agent work dir.
        accepted: Whether the candidate was accepted.
    """
    if not _is_git_repo(project_path):
        return ok_response({"skipped": True, "reason": "Not a git repo"})

    state = read_state_json(work_dir)
    config = _load_git_config(work_dir)

    if accepted:
        # Commit the accepted change
        result = git_snapshot(project_path, work_dir, "research-agent: accepted candidate")
        commit = result.get("commit")
        if commit:
            state = read_state_json(work_dir)
            state["git"]["current_best_commit"] = commit
            write_state_json(work_dir, state)

            # Auto-push if configured
            if config.get("auto_push_best"):
                remote = config.get("push_remote", "origin")
                branch = config.get("push_branch")
                push_args = ["push", remote]
                if branch:
                    push_args.append(branch)
                _run_git(project_path, push_args)

        return ok_response({"accepted": True, "commit": commit})
    else:
        # Rollback to baseline
        baseline = state.get("git", {}).get("baseline_commit")
        if baseline:
            git_rollback(project_path, baseline)
        return ok_response({"accepted": False, "rolled_back_to": baseline})


def _is_git_repo(path: Path) -> bool:
    result = _run_git(path, ["rev-parse", "--is-inside-work-tree"])
    return result.strip() == "true"


def _get_current_branch(path: Path) -> str:
    return _run_git(path, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()


def _is_dirty(path: Path) -> bool:
    result = _run_git(path, ["status", "--porcelain"])
    return bool(result.strip())


def _load_git_config(work_dir: Path) -> dict:
    import yaml
    config_path = work_dir / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("git", {})
    except Exception:
        return {}


def _run_git(path: Path, args: list[str]) -> str:
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
