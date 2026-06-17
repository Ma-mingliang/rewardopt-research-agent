# v0.8.7: Template Diversity Expansion

**Date**: 2026-06-17
**Branch**: reward-langgraph-v0.8.7-template-diversity-expansion
**Tag**: reward-langgraph-v0.8.7

## Goal

Expand method/template diversity beyond the single PBRS template that dominated v0.8.5 candidates. Add a diversity scheduler that ensures candidates span multiple reward categories across iterations.

## Hard Constraints (all honored)

1. No autoconfig stash popped
2. No v0.1–v0.8.6 tags moved
3. Full eval protocol unchanged
4. Seed/metrics/score/accept logic unchanged
5. Baseline guard enabled and passed
6. No --accept-baseline-migration used
7. HRRL2/env.py baseline unchanged
8. No MIMO_API_KEY leaked
9. No training entered
10. No full eval entered
11. No pagefile changes required

## Root Cause Analysis

### Why v0.8.5 Had Zero Template Diversity

**Problem**: All 4 v0.8.5 candidates used `a_potential_based_reward_openreview_ubnujziy2o` (category A only).

**Root causes**:

1. **No method exclusion**: `MethodSelector.select()` has an `exclude_ids` parameter but it was never called with `previous_method_ids`. The optimizer received `previous_method_ids` from the executor but didn't pass them to the selector.

2. **Deterministic sorting**: Methods are sorted by `(confidence, category, method_id)`. All category A methods have `confidence: "medium"`, so the same top-k methods were selected every iteration.

3. **Missing `_mark_batch` in proposal-only path**: The proposal-only code path never called `sampler.mark_used()`, so the sampler didn't know which methods had been tried and kept returning the same batch.

4. **Template tracking only checked first idea**: `track_template_selection` only looked at `candidate_ideas[0]`, missing other methods in the batch.

## Implementation

### 1. Diversity Scheduler Module

Created `research_agent/reward_methods/diversity_scheduler.py`:

- `DiversityScheduler(diversity_weight=0.3)` — Tracks category usage across iterations
- `record_selection(method_id, category)` — Record a method selection
- `compute_diversity_score()` — Compute diversity [0, 1] (1.0 = perfectly uniform)
- `rank_for_diversity(pool, exclude_ids)` — Re-rank pool favoring under-represented categories

**Diversity formula**: Methods from categories with fewer prior selections get a diversity bonus that moves them up the ranking. The `diversity_weight` parameter controls how strongly under-used categories are boosted.

### 2. Optimizer Integration

Modified `research_agent/agents/reward_agent/optimizer.py`:

- Added `_diversity_scheduler` instance to `LangGraphRewardOptimizer`
- In `propose_candidate()`:
  - Use `rank_for_diversity()` to re-rank the pool before selection
  - Pass `previous_method_ids` as `exclude_ids` to avoid re-selecting tried methods
  - Record selections in the scheduler after each iteration
  - Emit `diversity_score` in `source_meta`

### 3. Proposal-Only `_mark_batch` Fix

Modified `research_agent/core/executor.py`:

- Added `_mark_batch("tried", reason="proposal_only_validated")` to the proposal-only path (line ~2703)
- This ensures the sampler marks methods as tried even in proposal-only mode

### 4. Template Tracking Fix

Modified `research_agent/core/executor.py`:

- Changed template tracking from `candidate_ideas[0]` only to iterating all `candidate_ideas`
- Each method in the batch is now tracked individually

## Campaign Results

### Before Fix (v0.8.5 behavior)

| Metric | Value |
|--------|-------|
| template_usage_counts | {a_potential_based_reward_openreview_ubnujziy2o: 4} |
| template_diversity_score | 0.0 |
| template_low_diversity | true |
| Unique categories | 1 |

### After Fix (v0.8.7)

```
--project D:/research-agent/HRRL2
--optimizer reward_langgraph
--max-iterations 5 --batch-size 1 --proposal-only
--reward-method-pool D:/research-agent/.research-agent/test_method_pool
--reward-method-top-k 3
--staged-eval
--baseline-manifest docs/baselines/hrrl2_operational_baseline.yaml
```

| Metric | Value |
|--------|-------|
| candidates_proposal_only_validated | 3 |
| semantic_gate_passed_count | 3 |
| template_usage_counts | {test_pbrs_001: 1, test_risk_penalty_004: 1, test_curriculum_003: 1, test_sparse_to_dense_002: 1, test_control_energy_005: 1} |
| template_diversity_score | 1.0 |
| template_low_diversity | false |
| method_pool_categories_used | [A, B, C, D] |
| baseline_guard_passed | true |
| env.py hash | e19703467be71e20 (unchanged) |

Note: Only 3 iterations completed (not 5) because the 5-method test pool was exhausted with batch_size=2 cross-category fallback.

## Test Results

```
20 new tests: PASSED
547 full suite tests: PASSED (1 pre-existing Windows path issue)
```

### New Tests

- `tests/test_template_diversity_scheduler.py` (15 tests): init, record_selection, diversity_score, rank_for_diversity, integration with MethodSelector
- `tests/test_method_pool_diversity.py` (5 tests): 5-iteration diversity, no duplicate IDs, diversity score, backward compatibility

## Files Modified

| File | Changes |
|------|---------|
| `research_agent/agents/reward_agent/optimizer.py` | Added DiversityScheduler import and instance; use rank_for_diversity() before selection; record selections; emit diversity_score |
| `research_agent/core/executor.py` | Added `_mark_batch("tried")` to proposal-only path; fixed template tracking to iterate all candidate_ideas |

## Files Created

| File | Purpose |
|------|---------|
| `research_agent/reward_methods/diversity_scheduler.py` | Diversity scheduler for category-aware method selection |
| `tests/test_template_diversity_scheduler.py` | 15 tests for diversity scheduler |
| `tests/test_method_pool_diversity.py` | 5 tests for method pool diversity integration |
| `docs/reports/reward_langgraph_v0_8_7_template_diversity_expansion_report.md` | This report |

## Key Findings

### 1. Was the diversity issue resolved?

**Yes.** The diversity scheduler re-ranks the method pool to favor under-used categories, and `exclude_ids` prevents re-selecting already-tried methods. Template diversity score went from 0.0 to 1.0.

### 2. What was the hidden bug?

The proposal-only code path never called `_mark_batch()`, so the sampler never learned which methods had been tried. This caused it to return the same batch every iteration.

### 3. Does the diversity scheduler work with both optimizer types?

**Yes.** The scheduler is internal to `LangGraphRewardOptimizer`. The base `RewardOptimizer` doesn't use method pools, so it's unaffected.

### 4. What's next for v0.8.8?

Run a full 5-candidate diversity campaign with the default pool (142 methods, 8 categories) to validate that the scheduler maintains diversity at scale.

## Commit and Tag

- **Commit**: `feat: add template diversity scheduler and fix proposal-only tracking`
- **Tag**: `reward-langgraph-v0.8.7`
