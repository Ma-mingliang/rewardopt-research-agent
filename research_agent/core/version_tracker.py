"""Version tracker: log every candidate/version with full context."""

from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class VersionTracker:
    """Track and log every candidate version with detailed context."""

    def __init__(self, work_dir: Path):
        self.work_dir = work_dir
        self.changelog_path = work_dir / "CHANGELOG.md"
        self.tried_methods_path = work_dir / "logs" / "tried_methods.jsonl"
        self.counter_path = work_dir / "logs" / "version_counter.json"
        self._ensure_files()
        self._version_counter = self._load_counter()

    def _ensure_files(self) -> None:
        """Create tracking files if they don't exist."""
        self.changelog_path.parent.mkdir(parents=True, exist_ok=True)
        self.tried_methods_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.changelog_path.exists():
            with open(self.changelog_path, "w", encoding="utf-8") as f:
                f.write("# Changelog\n\nAll candidate versions with detailed tracking.\n\n")

        if not self.tried_methods_path.exists():
            self.tried_methods_path.touch()

    def _load_counter(self) -> int:
        """Load version counter from file."""
        if self.counter_path.exists():
            try:
                with open(self.counter_path, encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("counter", 0)
            except (json.JSONDecodeError, OSError):
                pass
        return 0

    def _save_counter(self) -> None:
        """Save version counter to file."""
        with open(self.counter_path, "w", encoding="utf-8") as f:
            json.dump({"counter": self._version_counter}, f)

    def next_version_id(self) -> str:
        """Get next version ID and increment counter."""
        self._version_counter += 1
        self._save_counter()
        return f"v{self._version_counter:04d}"

    def log_version(
        self,
        version_id: str,
        candidate_id: str,
        reward_formula: str,
        modified_files: list[dict],
        metrics_before: dict[str, Any],
        metrics_after: dict[str, Any] | None,
        accepted: bool,
        rejection_reason: str | None = None,
        error_traceback: str | None = None,
        source_methods: list[str] | None = None,
        description: str = "",
    ) -> None:
        """Log a candidate version with full context.

        Args:
            version_id: Unique version identifier.
            candidate_id: Candidate ID from optimizer.
            reward_formula: Reward formula or description of change.
            modified_files: List of modified file locations.
            metrics_before: Baseline metrics before this version.
            metrics_after: Metrics after evaluation (None if skipped).
            accepted: Whether this version was accepted.
            rejection_reason: Reason for rejection (if rejected).
            error_traceback: Error traceback (if error occurred).
            source_methods: Source method IDs from paper pool.
            description: Human-readable description.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        # 1. Write to CHANGELOG.md (human-readable)
        self._write_changelog(
            timestamp=timestamp,
            version_id=version_id,
            candidate_id=candidate_id,
            reward_formula=reward_formula,
            modified_files=modified_files,
            metrics_before=metrics_before,
            metrics_after=metrics_after,
            accepted=accepted,
            rejection_reason=rejection_reason,
            error_traceback=error_traceback,
            source_methods=source_methods,
            description=description,
        )

        # 2. Write to tried_methods.jsonl (machine-readable)
        self._write_tried_methods(
            timestamp=timestamp,
            version_id=version_id,
            candidate_id=candidate_id,
            reward_formula=reward_formula,
            modified_files=modified_files,
            metrics_before=metrics_before,
            metrics_after=metrics_after,
            accepted=accepted,
            rejection_reason=rejection_reason,
            error_traceback=error_traceback,
            source_methods=source_methods,
            description=description,
        )

        # 3. Print to stdout with flush
        self._print_to_stdout(
            timestamp=timestamp,
            version_id=version_id,
            candidate_id=candidate_id,
            reward_formula=reward_formula,
            metrics_before=metrics_before,
            metrics_after=metrics_after,
            accepted=accepted,
            rejection_reason=rejection_reason,
            error_traceback=error_traceback,
        )

    def _write_changelog(self, **kwargs: Any) -> None:
        """Append to CHANGELOG.md in human-readable format."""
        from research_agent.core.metrics_utils import format_metrics_for_changelog

        status = "ACCEPTED" if kwargs["accepted"] else "REJECTED"
        status_emoji = "✓" if kwargs["accepted"] else "✗"

        entry = f"""## [{kwargs['timestamp']}] {kwargs['version_id']} - {status_emoji} {status}

**Candidate ID:** `{kwargs['candidate_id']}`
**Description:** {kwargs['description']}

### Reward Formula / Change
```
{kwargs['reward_formula']}
```

### Modified Files
"""
        for file_info in kwargs["modified_files"]:
            file_path = file_info.get("file", "unknown")
            line_range = file_info.get("line_range", "")
            if line_range:
                entry += f"- `{file_path}` (lines {line_range[0]}-{line_range[1]})\n"
            else:
                entry += f"- `{file_path}`\n"

        entry += "\n### Metrics Before (Baseline)\n"
        entry += format_metrics_for_changelog(kwargs["metrics_before"]) + "\n"

        if kwargs["metrics_after"]:
            entry += "\n### Metrics After\n"
            entry += format_metrics_for_changelog(kwargs["metrics_after"]) + "\n"

        if kwargs["rejection_reason"]:
            entry += f"\n### Rejection Reason\n{kwargs['rejection_reason']}\n"

        if kwargs["error_traceback"]:
            entry += f"\n### Error Traceback\n```\n{kwargs['error_traceback']}\n```\n"

        if kwargs["source_methods"]:
            entry += f"\n### Source Methods\n{', '.join(kwargs['source_methods'])}\n"

        entry += "\n---\n\n"

        with open(self.changelog_path, "a", encoding="utf-8") as f:
            f.write(entry)

    def _write_tried_methods(self, **kwargs: Any) -> None:
        """Append to tried_methods.jsonl in JSON format."""
        record = {
            "timestamp": kwargs["timestamp"],
            "version_id": kwargs["version_id"],
            "candidate_id": kwargs["candidate_id"],
            "reward_formula": kwargs["reward_formula"],
            "modified_files": kwargs["modified_files"],
            "metrics_before": kwargs["metrics_before"],
            "metrics_after": kwargs["metrics_after"],
            "accepted": kwargs["accepted"],
            "rejection_reason": kwargs["rejection_reason"],
            "error_traceback": kwargs["error_traceback"],
            "source_methods": kwargs["source_methods"],
            "description": kwargs["description"],
        }

        with open(self.tried_methods_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _print_to_stdout(self, **kwargs: Any) -> None:
        """Print version summary to stdout with flush=True."""
        status = "ACCEPTED" if kwargs["accepted"] else "REJECTED"
        separator = "=" * 80

        output = f"""
{separator}
[VERSION] {kwargs['version_id']} | {kwargs['candidate_id']} | {status}
{separator}
Timestamp: {kwargs['timestamp']}
Reward Formula:
{kwargs['reward_formula']}

Metrics Before: {self._format_metrics(kwargs['metrics_before'])}
"""
        if kwargs["metrics_after"]:
            output += f"Metrics After:  {self._format_metrics(kwargs['metrics_after'])}\n"

        if kwargs["rejection_reason"]:
            output += f"Rejection:      {kwargs['rejection_reason']}\n"

        if kwargs["error_traceback"]:
            output += f"Error:\n{kwargs['error_traceback'][:500]}\n"

        output += separator + "\n"

        print(output, flush=True)

    @staticmethod
    def _format_metrics(metrics: dict[str, Any]) -> str:
        """Format metrics dict to compact string."""
        from research_agent.core.metrics_utils import format_metrics_for_display
        return format_metrics_for_display(metrics)


def extract_modified_files(candidate: Any) -> list[dict]:
    """Extract modified file info from a candidate."""
    files = []
    for change in getattr(candidate, "allowed_changes", []):
        if isinstance(change, dict):
            files.append({
                "file": change.get("file", "unknown"),
                "line_range": change.get("line_range"),
            })
        elif isinstance(change, str):
            files.append({"file": change, "line_range": None})
    return files


def extract_reward_formula(candidate: Any, ideas: list[dict] | None = None) -> str:
    """Extract reward formula from candidate or source ideas."""
    # Try to get from candidate description
    desc = getattr(candidate, "description", "")
    if desc:
        return desc

    # Try to get from source ideas
    if ideas:
        formulas = []
        for idea in ideas[:3]:
            formula = idea.get("reward_formula", "")
            if formula:
                formulas.append(formula)
        if formulas:
            return "\n".join(formulas)

    return "(no formula)"


def extract_source_methods(ideas: list[dict] | None = None) -> list[str]:
    """Extract source method IDs from ideas."""
    if not ideas:
        return []
    methods = []
    for idea in ideas:
        mid = idea.get("method_id", "")
        if mid and mid not in methods:
            methods.append(mid)
    return methods
