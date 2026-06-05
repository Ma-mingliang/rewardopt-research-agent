"""Patch manager: apply, rollback, validate, and track candidate patches."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from research_agent.core.exceptions import PatchApplyError, PatchRollbackError
from research_agent.core.git_guard import git_rollback, git_snapshot
from research_agent.core.output import ok_response


class PatchManager:
    """Manages patch application, validation, and rollback for optimizer candidates."""

    def __init__(self, project_path: Path, work_dir: Path):
        self.project_path = project_path
        self.work_dir = work_dir
        self._patches_dir = work_dir / "patches"
        self._patches_dir.mkdir(parents=True, exist_ok=True)

    def apply_patch(self, candidate) -> dict:
        """Write patch_diff to disk and apply via git apply.

        Args:
            candidate: Candidate object with candidate_id and patch_diff.

        Returns:
            Response dict with applied status.

        Raises:
            PatchApplyError: If git apply fails.
        """
        patch_diff = candidate.patch_diff
        if not patch_diff or not patch_diff.strip():
            return ok_response({
                "applied": False,
                "candidate_id": candidate.candidate_id,
                "reason": "empty_patch",
            })

        # Write patch file
        patch_path = self._patches_dir / f"{candidate.candidate_id}.patch"
        patch_path.write_text(patch_diff, encoding="utf-8")

        # Try git apply --check first
        result = _run_git(self.project_path, ["apply", "--check", str(patch_path)])
        if result.returncode != 0:
            # Try with --3way fallback
            result3 = _run_git(self.project_path, ["apply", "--3way", str(patch_path)])
            if result3.returncode != 0:
                raise PatchApplyError(
                    str(patch_path),
                    result3.stderr or result.stderr or "git apply failed",
                )

        # Apply for real
        result = _run_git(self.project_path, ["apply", str(patch_path)])
        if result.returncode != 0:
            result3 = _run_git(self.project_path, ["apply", "--3way", str(patch_path)])
            if result3.returncode != 0:
                raise PatchApplyError(
                    str(patch_path),
                    result3.stderr or result.stderr or "git apply failed",
                )

        return ok_response({
            "applied": True,
            "candidate_id": candidate.candidate_id,
            "patch_path": str(patch_path),
        })

    def apply_and_validate(self, candidate, python_executable: str = "python") -> dict:
        """Apply patch and validate that modified Python files compile.

        If validation fails, automatically rolls back the patch.

        Args:
            candidate: Candidate object with patch_diff.
            python_executable: Python interpreter to use for py_compile.

        Returns:
            Response dict with applied, validated status.
        """
        # Apply the patch
        apply_result = self.apply_patch(candidate)
        if not apply_result.get("applied"):
            return apply_result

        # Find modified files from the diff
        modified_files = _extract_modified_files(candidate.patch_diff)

        # Validate each modified Python file compiles
        validation_errors = []
        for file_path in modified_files:
            if not file_path.endswith(".py"):
                continue
            full_path = self.project_path / file_path
            if not full_path.exists():
                continue
            ok, error = _check_compiles(full_path, python_executable)
            if not ok:
                validation_errors.append(f"{file_path}: {error}")

        if validation_errors:
            # Rollback on validation failure
            try:
                self.rollback_patch(candidate)
            except Exception:
                pass
            return {
                "ok": True,
                "applied": False,
                "candidate_id": candidate.candidate_id,
                "reason": "compilation_failed",
                "errors": validation_errors,
            }

        return ok_response({
            "applied": True,
            "validated": True,
            "candidate_id": candidate.candidate_id,
            "files_checked": len([f for f in modified_files if f.endswith(".py")]),
        })

    def validate_syntax(self, candidate, python_executable: str = "python") -> dict:
        """Validate patch syntax without applying.

        Checks:
        1. Diff is parseable (has valid unified diff headers)
        2. Referenced files exist in the project

        Args:
            candidate: Candidate object with patch_diff.
            python_executable: Python interpreter.

        Returns:
            Response dict with validation result.
        """
        patch_diff = candidate.patch_diff
        if not patch_diff or not patch_diff.strip():
            return ok_response({"valid": True, "reason": "empty_patch"})

        # Check diff has valid headers
        files = _extract_modified_files(patch_diff)
        if not files:
            return {
                "ok": False,
                "valid": False,
                "reason": "no_files_in_diff",
                "error": "Patch does not contain any file references",
            }

        # Check referenced files exist
        missing = []
        for f in files:
            full_path = self.project_path / f
            if not full_path.exists():
                # For new files (--- /dev/null), that's OK
                if f != "/dev/null":
                    missing.append(f)

        if missing:
            return {
                "ok": True,
                "valid": False,
                "reason": "missing_files",
                "missing": missing,
            }

        return ok_response({"valid": True, "files": files})

    def rollback_patch(self, candidate) -> dict:
        """Rollback a patch by restoring the working tree.

        Args:
            candidate: Candidate object.

        Returns:
            Response dict.

        Raises:
            PatchRollbackError: If rollback fails.
        """
        # git checkout -- . restores the working tree to the last committed state
        proc = _run_git(self.project_path, ["checkout", "--", "."])
        if proc.returncode != 0:
            raise PatchRollbackError(proc.stderr or "git checkout failed")

        # Also clean untracked files created by the patch
        _run_git(self.project_path, ["clean", "-fd"])

        return ok_response({
            "rolled_back": True,
            "candidate_id": candidate.candidate_id,
        })

    def snapshot(self, message: str) -> dict:
        """Create a git snapshot (commit all changes).

        Args:
            message: Commit message.

        Returns:
            Response dict with commit hash.
        """
        return git_snapshot(self.project_path, self.work_dir, message)

    def rollback_to_commit(self, commit_hash: str) -> dict:
        """Rollback to a specific commit.

        Args:
            commit_hash: Target commit hash.

        Returns:
            Response dict.
        """
        return git_rollback(self.project_path, commit_hash)

    def is_git_repo(self) -> bool:
        """Check if project_path is a git repository."""
        proc = _run_git(self.project_path, ["rev-parse", "--is-inside-work-tree"])
        return proc.stdout.strip() == "true"


def _extract_modified_files(patch_diff: str) -> list[str]:
    """Extract file paths from a unified diff.

    Looks for lines like:
        --- a/path/to/file.py
        +++ b/path/to/file.py
    """
    files = []
    # Match +++ b/path or +++ path (not /dev/null)
    for match in re.finditer(r'^\+\+\+ (?:b/)?(.+)$', patch_diff, re.MULTILINE):
        path = match.group(1).strip()
        if path and path != "/dev/null":
            files.append(path)
    return files


def _check_compiles(file_path: Path, python_executable: str = "python") -> tuple[bool, str]:
    """Check if a Python file compiles without syntax errors.

    Returns:
        (True, "") if compiles, (False, error_message) if not.
    """
    try:
        result = subprocess.run(
            [python_executable, "-m", "py_compile", str(file_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stderr.strip() or "compilation failed"
    except subprocess.TimeoutExpired:
        return False, "py_compile timed out"
    except FileNotFoundError:
        # Python not found, skip validation
        return True, ""
    except Exception as e:
        return False, str(e)


def _run_git(path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the CompletedProcess."""
    try:
        return subprocess.run(
            ["git"] + args,
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args=["git"] + args,
            returncode=-1,
            stdout="",
            stderr="git command timed out",
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(
            args=["git"] + args,
            returncode=-1,
            stdout="",
            stderr="git not found",
        )
