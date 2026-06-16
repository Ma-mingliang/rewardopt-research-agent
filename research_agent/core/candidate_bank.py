"""Candidate bank loading, ranking, and diversity analysis (v0.8.6)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CandidateRecord:
    """A single candidate bank record."""

    candidate_id: str
    iteration: int
    method_ids: list[str]
    method_categories: list[str]
    selected_template: str
    diff_hash: str
    diff_preview: str
    reward_terms_added: list[str]
    reward_terms_modified: list[str]
    semantic_gate_decision: str
    syntax_valid: bool
    validation_passed: bool
    proposal_source: str
    rejection_reason: str
    duplicate_similarity_max: float
    train_called: bool
    full_eval_called: bool


@dataclass
class RankedCandidate:
    """A candidate with ranking scores."""

    record: CandidateRecord
    rank: int = 0
    semantic_rank_score: float = 0.0
    diversity_score: float = 0.0
    complexity_penalty: float = 0.0
    proposal_source_penalty: float = 0.0
    template_novelty_bonus: float = 0.0


@dataclass
class DiversityAnalysis:
    """Diversity analysis across the candidate bank."""

    total_candidates: int = 0
    unique_templates: int = 0
    unique_diff_hashes: int = 0
    unique_proposal_sources: int = 0
    template_distribution: dict[str, int] = field(default_factory=dict)
    source_distribution: dict[str, int] = field(default_factory=dict)
    reward_term_frequency: dict[str, int] = field(default_factory=dict)
    diversity_score: float = 0.0
    low_diversity: bool = False


def load_candidate_bank(path: Path) -> list[CandidateRecord]:
    """Load candidate bank from JSONL file."""
    records: list[CandidateRecord] = []
    if not path.exists():
        return records
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            records.append(CandidateRecord(
                candidate_id=data.get("candidate_id", ""),
                iteration=data.get("iteration", 0),
                method_ids=data.get("method_ids", []),
                method_categories=data.get("method_categories", []),
                selected_template=data.get("selected_template", ""),
                diff_hash=data.get("diff_hash", ""),
                diff_preview=data.get("diff_preview", ""),
                reward_terms_added=data.get("reward_terms_added", []),
                reward_terms_modified=data.get("reward_terms_modified", []),
                semantic_gate_decision=data.get("semantic_gate_decision", ""),
                syntax_valid=data.get("syntax_valid", False),
                validation_passed=data.get("validation_passed", False),
                proposal_source=data.get("proposal_source", ""),
                rejection_reason=data.get("rejection_reason", ""),
                duplicate_similarity_max=data.get("duplicate_similarity_max", 0.0),
                train_called=data.get("train_called", False),
                full_eval_called=data.get("full_eval_called", False),
            ))
    return records


def compute_reward_term_complexity(terms_added: list[str], terms_modified: list[str]) -> float:
    """Compute complexity penalty for reward terms.

    Returns a value in [0, 1]. Higher means more complex (heavier penalty).
    """
    all_terms = terms_added + terms_modified
    if not all_terms:
        return 1.0

    total_lines = sum(len(t.split("\n")) for t in all_terms)
    # Normalize: 1-3 lines = low complexity, 10+ = high
    line_penalty = min(total_lines / 15.0, 1.0)

    # Conditional branches add complexity
    branch_count = sum(1 for t in all_terms if "if " in t or "else:" in t or "elif " in t)
    branch_penalty = min(branch_count / 4.0, 1.0)

    return round(0.6 * line_penalty + 0.4 * branch_penalty, 4)


def compute_proposal_source_penalty(source: str) -> float:
    """Compute penalty based on proposal source.

    Lower penalty is better. Template-fallback is least preferred.
    """
    penalties = {
        "primary": 0.0,
        "semantic_regeneration": 0.05,
        "syntax_repair": 0.1,
        "template_fallback": 0.2,
    }
    return penalties.get(source, 0.15)


def compute_semantic_rank_score(
    record: CandidateRecord,
    template_counts: dict[str, int],
    max_template_count: int,
) -> float:
    """Compute a composite rank score for a candidate.

    Higher score is better. Range [0, 1].
    """
    # Base score from validation
    if not record.validation_passed:
        return 0.0

    base = 0.5

    # Reward term richness: more terms = higher score
    term_count = len(record.reward_terms_added) + len(record.reward_terms_modified)
    term_bonus = min(term_count / 6.0, 0.2)

    # Complexity penalty
    complexity = compute_reward_term_complexity(
        record.reward_terms_added, record.reward_terms_modified,
    )
    complexity_penalty = complexity * 0.15

    # Proposal source penalty
    source_penalty = compute_proposal_source_penalty(record.proposal_source)

    # Template novelty: prefer templates used less frequently
    template_count = template_counts.get(record.selected_template, 0)
    if max_template_count > 0:
        template_novelty = (1.0 - template_count / max_template_count) * 0.15
    else:
        template_novelty = 0.0

    score = base + term_bonus - complexity_penalty - source_penalty + template_novelty
    return round(max(0.0, min(1.0, score)), 4)


def compute_diversity_score(records: list[CandidateRecord]) -> DiversityAnalysis:
    """Compute diversity analysis across all candidates."""
    analysis = DiversityAnalysis(total_candidates=len(records))

    if not records:
        return analysis

    templates: dict[str, int] = {}
    sources: dict[str, int] = {}
    terms: dict[str, int] = {}
    hashes: set[str] = set()

    for r in records:
        templates[r.selected_template] = templates.get(r.selected_template, 0) + 1
        sources[r.proposal_source] = sources.get(r.proposal_source, 0) + 1
        hashes.add(r.diff_hash)
        for term in r.reward_terms_added:
            # Extract variable name from assignment
            stripped = term.strip()
            if "=" in stripped and not stripped.startswith("#") and not stripped.startswith("if"):
                var_name = stripped.split("=")[0].strip()
                if var_name and not var_name.startswith(" ") and var_name.isidentifier():
                    terms[var_name] = terms.get(var_name, 0) + 1

    analysis.unique_templates = len(templates)
    analysis.unique_diff_hashes = len(hashes)
    analysis.unique_proposal_sources = len(sources)
    analysis.template_distribution = templates
    analysis.source_distribution = sources
    analysis.reward_term_frequency = terms

    # Diversity score: ratio of unique items to total
    if analysis.total_candidates > 0:
        hash_ratio = len(hashes) / analysis.total_candidates
        template_ratio = len(templates) / min(analysis.total_candidates, 4)  # cap at 4 templates
        analysis.diversity_score = round(0.6 * hash_ratio + 0.4 * min(template_ratio, 1.0), 4)

    # Low diversity: fewer unique templates than half the candidates
    analysis.low_diversity = len(templates) < max(2, analysis.total_candidates // 2)

    return analysis


def rank_candidates(records: list[CandidateRecord]) -> list[RankedCandidate]:
    """Rank candidates by composite score.

    Returns list sorted by rank (best first).
    """
    if not records:
        return []

    # Compute template frequency
    template_counts: dict[str, int] = {}
    for r in records:
        template_counts[r.selected_template] = template_counts.get(r.selected_template, 0) + 1
    max_template_count = max(template_counts.values()) if template_counts else 1

    ranked: list[RankedCandidate] = []
    for r in records:
        rc = RankedCandidate(record=r)
        rc.semantic_rank_score = compute_semantic_rank_score(
            r, template_counts, max_template_count,
        )
        rc.complexity_penalty = compute_reward_term_complexity(
            r.reward_terms_added, r.reward_terms_modified,
        )
        rc.proposal_source_penalty = compute_proposal_source_penalty(r.proposal_source)
        template_count = template_counts.get(r.selected_template, 0)
        if max_template_count > 0:
            rc.template_novelty_bonus = round(
                (1.0 - template_count / max_template_count) * 0.15, 4,
            )
        ranked.append(rc)

    # Sort by semantic_rank_score descending, then by iteration ascending
    ranked.sort(key=lambda x: (-x.semantic_rank_score, x.record.iteration))

    for i, rc in enumerate(ranked):
        rc.rank = i + 1

    return ranked


def write_ranked_bank(path: Path, ranked: list[RankedCandidate]) -> None:
    """Write ranked candidates to JSONL file."""
    with open(path, "w", encoding="utf-8") as f:
        for rc in ranked:
            record_dict = {
                "rank": rc.rank,
                "candidate_id": rc.record.candidate_id,
                "iteration": rc.record.iteration,
                "semantic_rank_score": rc.semantic_rank_score,
                "diversity_score": rc.diversity_score,
                "complexity_penalty": rc.complexity_penalty,
                "proposal_source_penalty": rc.proposal_source_penalty,
                "template_novelty_bonus": rc.template_novelty_bonus,
                "proposal_source": rc.record.proposal_source,
                "selected_template": rc.record.selected_template,
                "diff_hash": rc.record.diff_hash,
                "reward_terms_added": rc.record.reward_terms_added,
                "reward_terms_modified": rc.record.reward_terms_modified,
                "syntax_valid": rc.record.syntax_valid,
                "validation_passed": rc.record.validation_passed,
                "semantic_gate_decision": rc.record.semantic_gate_decision,
            }
            f.write(json.dumps(record_dict, ensure_ascii=False) + "\n")


def write_diversity_summary(path: Path, analysis: DiversityAnalysis, ranked: list[RankedCandidate]) -> None:
    """Write diversity summary to markdown file."""
    lines: list[str] = []
    lines.append("# Candidate Bank Diversity Summary\n")
    lines.append(f"**Total candidates**: {analysis.total_candidates}\n")
    lines.append(f"**Unique templates**: {analysis.unique_templates}\n")
    lines.append(f"**Unique diff hashes**: {analysis.unique_diff_hashes}\n")
    lines.append(f"**Unique proposal sources**: {analysis.unique_proposal_sources}\n")
    lines.append(f"**Overall diversity score**: {analysis.diversity_score}\n")
    lines.append(f"**Low diversity**: {'Yes' if analysis.low_diversity else 'No'}\n")

    lines.append("\n## Template Distribution\n")
    lines.append("| Template | Count |")
    lines.append("|----------|-------|")
    for tpl, count in sorted(analysis.template_distribution.items(), key=lambda x: -x[1]):
        lines.append(f"| {tpl} | {count} |")

    lines.append("\n## Source Distribution\n")
    lines.append("| Source | Count |")
    lines.append("|--------|-------|")
    for src, count in sorted(analysis.source_distribution.items(), key=lambda x: -x[1]):
        lines.append(f"| {src} | {count} |")

    lines.append("\n## Reward Term Frequency\n")
    lines.append("| Term | Frequency |")
    lines.append("|------|-----------|")
    for term, count in sorted(analysis.reward_term_frequency.items(), key=lambda x: -x[1]):
        lines.append(f"| {term} | {count} |")

    lines.append("\n## Ranked Candidates\n")
    lines.append("| Rank | Candidate | Iteration | Score | Source | Template | Terms |")
    lines.append("|------|-----------|-----------|-------|--------|----------|-------|")
    for rc in ranked:
        terms_str = ", ".join(rc.record.reward_terms_added[:3])
        if len(rc.record.reward_terms_added) > 3:
            terms_str += "..."
        lines.append(
            f"| {rc.rank} | {rc.record.candidate_id} | {rc.record.iteration} "
            f"| {rc.semantic_rank_score:.4f} | {rc.record.proposal_source} "
            f"| {rc.record.selected_template[:30]} | {terms_str} |"
        )

    lines.append("\n## Recommendation\n")
    if ranked:
        best = ranked[0]
        lines.append(f"**Top candidate**: {best.record.candidate_id} (iteration {best.record.iteration})\n")
        lines.append(f"- Score: {best.semantic_rank_score:.4f}\n")
        lines.append(f"- Source: {best.record.proposal_source}\n")
        lines.append(f"- Terms: {', '.join(best.record.reward_terms_added)}\n")
    if analysis.low_diversity:
        lines.append("\n**Warning**: Low template diversity detected. Consider expanding the template pool.\n")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
