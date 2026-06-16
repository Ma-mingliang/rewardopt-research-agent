"""Semantic patch gate — reject cosmetic/no-reward-term patches before training.

v0.8.2: Hard semantic gate that blocks patches lacking substantive reward
term modifications. Does NOT affect full eval protocol or accept/reject logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class RejectionReason(str, Enum):
    COSMETIC_PATCH = "cosmetic_patch_rejected"
    NO_REWARD_TERM_CHANGE = "no_reward_term_change"
    DUPLICATE_PATCH = "duplicate_patch_rejected"
    OUTSIDE_REWARD_CONTEXT = "patch_outside_reward_context"
    SEMANTIC_GATE_FAILED = "semantic_gate_failed"


@dataclass
class SemanticPatchDecision:
    """Result of semantic patch analysis."""
    passed: bool
    reason: str = ""
    semantic_change_detected: bool = False
    cosmetic_only: bool = False
    blank_line_only: bool = False
    whitespace_only: bool = False
    comment_only: bool = False
    reward_terms_changed: bool = False
    reward_terms_added: list[str] = field(default_factory=list)
    reward_terms_removed: list[str] = field(default_factory=list)
    coefficient_only_change: bool = False
    modified_files: list[str] = field(default_factory=list)
    changed_line_count: int = 0
    diagnostics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "semantic_change_detected": self.semantic_change_detected,
            "cosmetic_only": self.cosmetic_only,
            "blank_line_only": self.blank_line_only,
            "whitespace_only": self.whitespace_only,
            "comment_only": self.comment_only,
            "reward_terms_changed": self.reward_terms_changed,
            "reward_terms_added": self.reward_terms_added,
            "reward_terms_removed": self.reward_terms_removed,
            "coefficient_only_change": self.coefficient_only_change,
            "modified_files": self.modified_files,
            "changed_line_count": self.changed_line_count,
        }


# Patterns that indicate reward term computation
_REWARD_TERM_PATTERNS = [
    r'\breward\s*[\+\-\*]?=',
    r'\breward\s*\+',
    r'\breward\s*-',
    r'\bpotential\b',
    r'\bshaping\b',
    r'\bpenalty\b',
    r'penalty\s*[\+\-\*]?=',
    r'=\s*-.*penalty',
    r'\bbonus\b',
    r'\btracking_reward\b',
    r'\blateral_error\b',
    r'\bheading_error\b',
    r'\bangular_velocity\b',
    r'\bcompletion_reward\b',
    r'\bsafety\b.*\bpenalty\b',
    r'\benergy\b.*\bpenalty\b',
    r'\bcurriculum\b',
    r'\bgamma\b.*\bphi\b',
    r'\balpha\b.*\berror\b',
    r'\brho\b.*\bconstraint\b',
]

# Patterns that are purely cosmetic
_BLANK_LINE_RE = re.compile(r'^\s*$')
_WHITESPACE_ONLY_RE = re.compile(r'^\s+$')
_COMMENT_ONLY_RE = re.compile(r'^\s*#')


def _is_blank_or_whitespace(line: str) -> bool:
    return bool(_BLANK_LINE_RE.match(line) or _WHITESPACE_ONLY_RE.match(line))


def _is_comment(line: str) -> bool:
    return bool(_COMMENT_ONLY_RE.match(line))


def _is_reward_term(line: str) -> bool:
    for pat in _REWARD_TERM_PATTERNS:
        if re.search(pat, line, re.IGNORECASE):
            return True
    return False


def _extract_changed_lines(diff_text: str) -> tuple[list[str], list[str]]:
    """Extract added and removed lines from a unified diff."""
    added = []
    removed = []
    for line in diff_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("+++") or stripped.startswith("---"):
            continue
        if stripped.startswith("+"):
            added.append(stripped[1:].strip())
        elif stripped.startswith("-"):
            removed.append(stripped[1:].strip())
    return added, removed


def _extract_modified_files(diff_text: str) -> list[str]:
    """Extract file paths from diff headers."""
    files = []
    for line in diff_text.splitlines():
        if line.startswith("--- a/") or line.startswith("+++ b/"):
            path = line.split("/", 1)[-1] if "/" in line else line.split()[-1]
            if path not in files:
                files.append(path)
    return files


def _is_coefficient_only_change(added: list[str], removed: list[str]) -> bool:
    """Check if changes are only numeric coefficient tweaks."""
    if not added or not removed:
        return False
    if len(added) != len(removed):
        return False
    # Normalize: replace numbers with placeholder
    num_re = re.compile(r'-?\d+\.?\d*')
    for a, r in zip(added, removed):
        a_norm = num_re.sub('NUM', a)
        r_norm = num_re.sub('NUM', r)
        if a_norm != r_norm:
            return False
    return True


def analyze_patch_semantics(
    diff_text: str,
    reward_function_lines: tuple[int, int] | None = None,
    previous_diffs: list[str] | None = None,
    similarity_threshold: float = 0.95,
) -> SemanticPatchDecision:
    """Analyze a patch for semantic reward term changes.

    Args:
        diff_text: Unified diff text.
        reward_function_lines: (start, end) line numbers of reward function.
        previous_diffs: List of previous candidate diffs for duplicate detection.
        similarity_threshold: Jaccard threshold for duplicate detection.

    Returns:
        SemanticPatchDecision with analysis results.
    """
    if not diff_text or not diff_text.strip():
        return SemanticPatchDecision(
            passed=False,
            reason="empty_diff",
            cosmetic_only=True,
        )

    added, removed = _extract_changed_lines(diff_text)
    modified_files = _extract_modified_files(diff_text)

    # No changed lines at all
    if not added and not removed:
        return SemanticPatchDecision(
            passed=False,
            reason=RejectionReason.COSMETIC_PATCH.value,
            cosmetic_only=True,
            blank_line_only=True,
            modified_files=modified_files,
        )

    # Check if ALL changed lines are blank/whitespace
    all_blank = all(_is_blank_or_whitespace(l) for l in added + removed)
    if all_blank:
        return SemanticPatchDecision(
            passed=False,
            reason=RejectionReason.COSMETIC_PATCH.value,
            cosmetic_only=True,
            blank_line_only=True,
            modified_files=modified_files,
            changed_line_count=len(added) + len(removed),
        )

    # Check if ALL changed lines are comments
    all_comments = all(_is_comment(l) or _is_blank_or_whitespace(l) for l in added + removed)
    if all_comments:
        return SemanticPatchDecision(
            passed=False,
            reason=RejectionReason.COSMETIC_PATCH.value,
            cosmetic_only=True,
            comment_only=True,
            modified_files=modified_files,
            changed_line_count=len(added) + len(removed),
        )

    # Check for reward term changes
    reward_added = [l for l in added if _is_reward_term(l)]
    reward_removed = [l for l in removed if _is_reward_term(l)]
    reward_changed = bool(reward_added or reward_removed)

    # Check if changes are coefficient-only
    coeff_only = _is_coefficient_only_change(added, removed)

    # Check for duplicate patch
    is_duplicate = False
    max_similarity = 0.0
    if previous_diffs:
        for prev_diff in previous_diffs:
            sim = _compute_jaccard(diff_text, prev_diff)
            if sim > max_similarity:
                max_similarity = sim
            if sim >= similarity_threshold:
                is_duplicate = True
                break

    # Decision logic
    if is_duplicate:
        return SemanticPatchDecision(
            passed=False,
            reason=RejectionReason.DUPLICATE_PATCH.value,
            semantic_change_detected=reward_changed,
            reward_terms_changed=reward_changed,
            reward_terms_added=reward_added,
            reward_terms_removed=reward_removed,
            coefficient_only_change=coeff_only,
            modified_files=modified_files,
            changed_line_count=len(added) + len(removed),
            diagnostics={"max_similarity": round(max_similarity, 4)},
        )

    if not reward_changed:
        return SemanticPatchDecision(
            passed=False,
            reason=RejectionReason.NO_REWARD_TERM_CHANGE.value,
            semantic_change_detected=False,
            cosmetic_only=False,
            reward_terms_changed=False,
            modified_files=modified_files,
            changed_line_count=len(added) + len(removed),
        )

    # Passed — has reward term changes
    return SemanticPatchDecision(
        passed=True,
        reason="semantic_reward_change_detected",
        semantic_change_detected=True,
        reward_terms_changed=True,
        reward_terms_added=reward_added,
        reward_terms_removed=reward_removed,
        coefficient_only_change=coeff_only,
        modified_files=modified_files,
        changed_line_count=len(added) + len(removed),
        diagnostics={"max_similarity": round(max_similarity, 4)} if previous_diffs else {},
    )


def _compute_jaccard(diff_a: str, diff_b: str) -> float:
    """Jaccard similarity of changed lines between two diffs."""
    def _changes(diff: str) -> set[str]:
        s = set()
        for line in diff.splitlines():
            stripped = line.strip()
            if stripped.startswith("+") and not stripped.startswith("+++"):
                s.add(stripped[1:].strip())
            elif stripped.startswith("-") and not stripped.startswith("---"):
                s.add(stripped[1:].strip())
        return s

    a = _changes(diff_a)
    b = _changes(diff_b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
