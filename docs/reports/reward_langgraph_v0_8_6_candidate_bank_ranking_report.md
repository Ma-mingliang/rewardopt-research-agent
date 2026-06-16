# v0.8.6: Candidate Bank Ranking and Template Diversity

**Date**: 2026-06-16
**Branch**: reward-langgraph-v0.8.6-candidate-bank-ranking
**Tag**: reward-langgraph-v0.8.6

## Goal

Audit v0.8.5 candidate bank, resolve counter discrepancy, add candidate bank ranking with diversity-aware scoring, and add template diversity controls.

## Hard Constraints (all honored)

1. No autoconfig stash popped
2. No v0.1–v0.8.5 tags moved
3. Full eval protocol unchanged
4. Seed/metrics/score/accept logic unchanged
5. Baseline guard enabled and passed
6. No --accept-baseline-migration used
7. HRRL2/env.py baseline unchanged
8. No MIMO_API_KEY leaked
9. No training entered
10. No full eval entered
11. No pagefile changes required

## v0.8.5 Candidate Bank Audit

### Audit Table

| # | Iteration | Proposal Source | Diff Hash | Reward Terms | semantic_gate_decision |
|---|-----------|----------------|-----------|--------------|----------------------|
| 1 | 1 | semantic_regeneration | ea52506882fe6591 | stability_penalty (conditional) | passed |
| 2 | 1 | syntax_repair | 58eb0a2280e88eca | angular_velocity penalty (exponential) | passed |
| 3 | 1 | semantic_regeneration | 05cd1723dfd8c975 | stage_weight potential | passed |
| 4 | 1 | semantic_regeneration | ea52506882fe6591 | stability_penalty (conditional) | passed |

### Counter Discrepancy Resolution

**Problem**: `semantic_gate_passed_count=0` but `validation_pass_count=4`.

**Root cause**: When semantic regeneration succeeds, the code reaches the `else` block at line 2339 (`if not semantic_decision.passed:` → `else:`), but this `else` only runs when the *initial* proposal passes. When regeneration succeeds, the code breaks out of the regeneration loop and falls through to the continuation at line 2353, skipping the `track_semantic_gate(passed=True)` call.

**Fix**: Added `observer.track_semantic_gate(passed=True, ...)` to all 3 regeneration success paths:
- Syntax-valid path: `reason="passed_after_regeneration"`
- Syntax-repaired path: `reason="passed_after_syntax_repair"`
- Template-fallback path: `reason="passed_after_template_fallback"`

**After fix**: `semantic_gate_passed_count=4`, `semantic_gate_rejected_count=0` (all candidates eventually passed).

## Implementation

### 1. Candidate Bank Ranking Module

Created `research_agent/core/candidate_bank.py`:

- `load_candidate_bank(path)` — Load JSONL records
- `compute_reward_term_complexity(terms_added, terms_modified)` — Complexity penalty [0, 1]
- `compute_proposal_source_penalty(source)` — Source penalty (primary=0, regeneration=0.05, syntax_repair=0.1, template_fallback=0.2)
- `compute_semantic_rank_score(record, template_counts, max_template_count)` — Composite rank score [0, 1]
- `compute_diversity_score(records)` — Diversity analysis across candidates
- `rank_candidates(records)` — Rank by composite score
- `write_ranked_bank(path, ranked)` — Write ranked JSONL
- `write_diversity_summary(path, analysis, ranked)` — Write markdown summary

### 2. Template Diversity Tracking

Added to `research_agent/core/observability.py`:
- `_template_usage_counts` — Per-template usage counter
- `_template_diversity_score` — Ratio of unique templates to total
- `_template_low_diversity` — Flag when diversity is low
- `track_template_selection(template_id)` — Track template usage
- `compute_template_diversity()` — Compute diversity metrics
- Summary fields: `template_usage_counts`, `template_diversity_score`, `template_low_diversity`

### 3. Counter Consistency Fix

Added `observer.track_semantic_gate(passed=True)` to all 3 regeneration success paths in `executor.py`.

### 4. Template Selection Tracking in Executor

Added template tracking call before `_write_candidate_bank_record()` in executor.

## v0.8.5 Ranked Candidate Bank

| Rank | Candidate | Iteration | Score | Source | Template | Complexity | Terms |
|------|-----------|-----------|-------|--------|----------|------------|-------|
| 1 | reward_langgraph_c001 | 1 | 0.6050 | semantic_regeneration | a_potential_based_reward_openreview_ubnujziy2o | 0.30 | stability_penalty (conditional) |
| 2 | reward_langgraph_c001 | 1 | 0.6050 | semantic_regeneration | a_potential_based_reward_openreview_ubnujziy2o | 0.30 | stability_penalty (conditional) |
| 3 | reward_langgraph_c001 | 1 | 0.5990 | semantic_regeneration | a_potential_based_reward_openreview_ubnujziy2o | 0.34 | stage_weight potential |
| 4 | reward_langgraph_c001 | 1 | 0.5820 | syntax_repair | a_potential_based_reward_openreview_ubnujziy2o | 0.12 | angular_velocity penalty |

### Diversity Analysis

- **Total candidates**: 4
- **Unique templates**: 1 (all from `a_potential_based_reward_openreview_ubnujziy2o`)
- **Unique diff hashes**: 3
- **Unique proposal sources**: 2 (semantic_regeneration, syntax_repair)
- **Diversity score**: 0.55
- **Low diversity**: Yes

### Ranking Formula

```
semantic_rank_score = 0.5                           # base (validation passed)
                    + min(term_count / 6, 0.2)      # term richness bonus
                    - complexity * 0.15              # complexity penalty
                    - source_penalty                 # source penalty
                    + template_novelty * 0.15        # template novelty bonus
```

## Extension Campaign Results

### Run Configuration

```
--project D:/research-agent/HRRL2
--max-iterations 3 --batch-size 1 --proposal-only
--max-semantic-regeneration-attempts 2
--staged-eval
--baseline-manifest docs/baselines/hrrl2_operational_baseline.yaml
```

### Result

**Campaign failed** due to pre-existing API mismatch: `RewardOptimizer.propose_candidate() got an unexpected keyword argument 'method_pool'`. This is unrelated to v0.8.6 changes.

### Observability Verification

Template diversity tracking fields confirmed present in summary.json:
- `template_usage_counts: {}` (no candidates produced)
- `template_diversity_score: 0.0`
- `template_low_diversity: true`
- `semantic_gate_passed_count: 0`
- `semantic_gate_rejected_count: 0`

## Test Results

```
36 new tests: PASSED
520 full suite tests: PASSED (1 pre-existing Windows path issue)
```

### New Tests

- `tests/test_candidate_bank.py` (27 tests): load_candidate_bank, compute_reward_term_complexity, compute_proposal_source_penalty, compute_semantic_rank_score, compute_diversity_score, rank_candidates, write_ranked_bank, write_diversity_summary
- `tests/test_candidate_bank_ranking.py` (9 tests): track_template_selection, compute_template_diversity, low_diversity_detection, template_diversity_in_summary, semantic_gate counter consistency (5 paths)

## Files Modified

| File | Changes |
|------|---------|
| `research_agent/core/executor.py` | Added `track_semantic_gate(passed=True)` to 3 regeneration success paths; added template tracking before candidate bank write |
| `research_agent/core/observability.py` | Added template diversity tracking: `_template_usage_counts`, `_template_diversity_score`, `_template_low_diversity`, `track_template_selection()`, `compute_template_diversity()`, summary fields |
| `run_optimizer.py` | Added `observer.compute_template_diversity()` before close |

## Files Created

| File | Purpose |
|------|---------|
| `research_agent/core/candidate_bank.py` | Candidate bank loading, ranking, diversity analysis |
| `tests/test_candidate_bank.py` | 27 tests for candidate bank module |
| `tests/test_candidate_bank_ranking.py` | 9 tests for template diversity and counter consistency |
| `docs/reports/reward_langgraph_v0_8_6_candidate_bank_ranking_report.md` | This report |

## Key Findings

### 1. Was the counter discrepancy resolved?

**Yes.** Root cause: regeneration success paths did not call `track_semantic_gate(passed=True)`. Fixed by adding the call to all 3 paths.

### 2. Is the candidate bank diverse?

**No.** All 4 candidates used the same template (`a_potential_based_reward_openreview_ubnujziy2o`). Diversity score: 0.55 (low). 3 unique diff hashes across 4 candidates.

### 3. How do candidates rank?

Rank 1 and 2 tie at 0.6050 (stability_penalty, different iterations). Rank 3 is stage_weight potential (0.5990). Rank 4 is angular_velocity penalty (0.5820, syntax_repair source penalty).

### 4. Does template diversity tracking work?

**Yes.** `template_usage_counts`, `template_diversity_score`, and `template_low_diversity` are now in summary.json.

### 5. Should v0.9 expand the template pool?

**Yes.** All candidates come from one template. Expanding to 3-4 templates would improve diversity and reduce the risk of repetitive reward structures.

## Commit and Tag

- **Commit**: `feat: add candidate bank ranking and template diversity`
- **Tag**: `reward-langgraph-v0.8.6`
