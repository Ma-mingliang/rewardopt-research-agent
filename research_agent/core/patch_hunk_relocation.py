"""Patch hunk relocation for line-number drift repair.

When LLM-generated diffs have incorrect line numbers, this module
attempts to relocate hunks using anchor-based matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HunkRelocationResult:
    """Result of hunk relocation attempt."""
    success: bool
    relocated_diff: str = ""
    original_diff: str = ""
    hunks_relocated: int = 0
    hunks_failed: int = 0
    reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "relocated_diff": self.relocated_diff[:500] if self.relocated_diff else "",
            "hunks_relocated": self.hunks_relocated,
            "hunks_failed": self.hunks_failed,
            "reason": self.reason,
            "diagnostics": self.diagnostics,
        }


def relocate_hunks(
    diff: str,
    target_content: str,
    context_lines: int = 3,
) -> HunkRelocationResult:
    """Relocate diff hunks using anchor-based matching.

    When line numbers in a diff don't match the target file, this function
    tries to find the correct location by matching context lines (anchors).

    Args:
        diff: The unified diff to relocate.
        target_content: Current content of the target file.
        context_lines: Number of context lines to use as anchors.

    Returns:
        HunkRelocationResult with relocated diff if successful.
    """
    if not diff or not target_content:
        return HunkRelocationResult(
            success=False,
            original_diff=diff,
            reason="Empty diff or target content",
        )

    target_lines = target_content.splitlines()
    diff_lines = diff.splitlines()

    # Parse diff into hunks
    hunks = _parse_hunks(diff_lines)
    if not hunks:
        return HunkRelocationResult(
            success=False,
            original_diff=diff,
            reason="No hunks found in diff",
        )

    # Relocate each hunk
    relocated_hunks = []
    hunks_relocated = 0
    hunks_failed = 0

    for hunk in hunks:
        result = _relocate_single_hunk(hunk, target_lines, context_lines)
        if result["success"]:
            relocated_hunks.append(result["relocated_hunk"])
            hunks_relocated += 1
        else:
            # Keep original hunk if relocation fails
            relocated_hunks.append(hunk["raw"])
            hunks_failed += 1

    # Reconstruct diff
    relocated_diff = _reconstruct_diff(diff_lines, relocated_hunks, hunks)

    return HunkRelocationResult(
        success=hunks_failed == 0,
        relocated_diff=relocated_diff,
        original_diff=diff,
        hunks_relocated=hunks_relocated,
        hunks_failed=hunks_failed,
        reason="All hunks relocated" if hunks_failed == 0 else f"{hunks_failed} hunks failed",
        diagnostics={
            "total_hunks": len(hunks),
            "target_lines": len(target_lines),
        },
    )


def _parse_hunks(diff_lines: list[str], context_lines: int = 3) -> list[dict[str, Any]]:
    """Parse diff into individual hunks."""
    hunks = []
    current_hunk = None
    hunk_lines = []

    for line in diff_lines:
        if line.startswith("@@"):
            # Save previous hunk
            if current_hunk:
                current_hunk["raw"] = "\n".join(hunk_lines)
                hunks.append(current_hunk)

            # Parse hunk header
            match = re.search(r"@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@", line)
            if match:
                current_hunk = {
                    "old_start": int(match.group(1)),
                    "old_count": int(match.group(2)) if match.group(2) else 1,
                    "new_start": int(match.group(3)),
                    "new_count": int(match.group(4)) if match.group(4) else 1,
                    "header": line,
                    "context_before": [],
                    "added_lines": [],
                    "removed_lines": [],
                    "context_after": [],
                }
                hunk_lines = [line]
        elif current_hunk:
            hunk_lines.append(line)
            if line.startswith("+") and not line.startswith("+++"):
                current_hunk["added_lines"].append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                current_hunk["removed_lines"].append(line[1:])
            elif line.startswith(" "):
                context = line[1:]
                if len(current_hunk["context_before"]) < context_lines:
                    current_hunk["context_before"].append(context)
                current_hunk["context_after"].append(context)
            elif line.startswith("\\"):
                pass  # No newline at end of file

    # Save last hunk
    if current_hunk:
        current_hunk["raw"] = "\n".join(hunk_lines)
        hunks.append(current_hunk)

    return hunks


def _relocate_single_hunk(
    hunk: dict[str, Any],
    target_lines: list[str],
    context_lines: int,
) -> dict[str, Any]:
    """Relocate a single hunk using anchor matching."""
    # Try to find location using context lines
    anchors = hunk["context_before"][:context_lines]
    if not anchors:
        # Use removed lines as anchors
        anchors = hunk["removed_lines"][:context_lines]

    if not anchors:
        return {"success": False, "relocated_hunk": hunk["raw"]}

    # Search for anchor sequence in target
    best_match = _find_anchor_sequence(target_lines, anchors)

    if best_match is None:
        return {"success": False, "relocated_hunk": hunk["raw"]}

    # Calculate new line numbers
    new_start = best_match - len(hunk["context_before"]) + 1
    if new_start < 1:
        new_start = 1

    # Reconstruct hunk with new line numbers
    new_header = f"@@ -{new_start},{hunk['old_count']} +{new_start},{hunk['new_count']} @@"
    new_hunk_lines = [new_header]

    # Add context before
    for line in hunk["context_before"]:
        new_hunk_lines.append(f" {line}")

    # Add removed lines
    for line in hunk["removed_lines"]:
        new_hunk_lines.append(f"-{line}")

    # Add added lines
    for line in hunk["added_lines"]:
        new_hunk_lines.append(f"+{line}")

    # Add context after
    for line in hunk["context_after"]:
        new_hunk_lines.append(f" {line}")

    return {
        "success": True,
        "relocated_hunk": "\n".join(new_hunk_lines),
        "new_start": new_start,
    }


def _find_anchor_sequence(target_lines: list[str], anchors: list[str]) -> int | None:
    """Find the best matching location for anchor sequence in target."""
    if not anchors:
        return None

    best_score = 0
    best_position = None

    for i in range(len(target_lines)):
        score = 0
        for j, anchor in enumerate(anchors):
            if i + j >= len(target_lines):
                break
            if _lines_match(target_lines[i + j], anchor):
                score += 1

        if score > best_score:
            best_score = score
            best_position = i + len(anchors) - 1

    # Require at least 50% match
    if best_score >= len(anchors) * 0.5:
        return best_position

    return None


def _lines_match(line1: str, line2: str) -> bool:
    """Check if two lines match (ignoring whitespace)."""
    return line1.strip() == line2.strip()


def _reconstruct_diff(
    diff_lines: list[str],
    relocated_hunks: list[str],
    original_hunks: list[dict[str, Any]],
) -> str:
    """Reconstruct diff with relocated hunks."""
    result = []
    hunk_index = 0
    in_hunk = False

    for line in diff_lines:
        if line.startswith("@@"):
            if hunk_index < len(relocated_hunks):
                result.append(relocated_hunks[hunk_index])
                hunk_index += 1
            in_hunk = True
        elif not in_hunk:
            result.append(line)
        elif line.startswith("+++") or line.startswith("---"):
            result.append(line)
            in_hunk = False

    return "\n".join(result)


def detect_line_number_drift(
    diff: str,
    target_content: str,
    tolerance: int = 5,
) -> dict[str, Any]:
    """Detect line number drift in a diff.

    Args:
        diff: The unified diff to check.
        target_content: Current content of the target file.
        tolerance: Allowed line number deviation.

    Returns:
        Dictionary with drift detection results.
    """
    if not diff or not target_content:
        return {"drift_detected": False, "reason": "Empty diff or target"}

    target_lines = target_content.splitlines()
    diff_lines = diff.splitlines()

    drift_detected = False
    drift_details = []

    for line in diff_lines:
        if line.startswith("@@"):
            match = re.search(r"@@ -(\d+)", line)
            if match:
                expected_line = int(match.group(1))
                # Check if line number is reasonable
                if expected_line > len(target_lines) + tolerance:
                    drift_detected = True
                    drift_details.append({
                        "hunk_header": line,
                        "expected_line": expected_line,
                        "target_lines": len(target_lines),
                        "drift": expected_line - len(target_lines),
                    })

    return {
        "drift_detected": drift_detected,
        "drift_count": len(drift_details),
        "details": drift_details,
    }
