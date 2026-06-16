# Reward LangGraph v0.8 — Proposal Quality and Candidate Diversity Report

**Date:** 2026-06-16
**Branch:** `reward-langgraph-v0.8-proposal-quality`
**Baseline:** v0.7.4 (`reward-langgraph-v0.7.4-real-campaign-retry`)
**Approach:** Offline-only (no real LLM campaign)

---

## I. v0.7.4 Candidate Analysis

Both v0.7.4 candidates were **rejected** with identical composite score **-0.0726**.

### Score Breakdown

| Metric | Weight | Direction | Baseline | Candidate | Normalized | Weighted |
|--------|--------|-----------|----------|-----------|------------|----------|
| completion_rate | 0.4 | higher | 1.0 | 0.0 | -1.0 | -0.4 |
| reward | 0.4 | higher | 983.26 | 984.576 | +0.001335 | +0.000534 |
| lateral_error | 0.2 | lower | 0.0041 | 0.0056 | -0.365854 | -0.073171 |

**Composite = (-0.4 + 0.000534 - 0.073171) / 1.0 = -0.072637**

### Candidate Diffs

Both candidates produced **identical patches**:

```diff
--- a/env.py
+++ b/env.py
@@ -997,2 +997,3 @@
         return reward
+
     def reset(self, seed=None, options=None):
```

This is a **cosmetic-only change** — adding a blank line after `return reward`. No reward term was added, modified, or removed.

### Root Causes

1. **LLM defaulted to cosmetic change**: Despite receiving research method context (safety penalty, energy penalty ideas), the LLM chose the safest possible edit — a blank line insertion.
2. **No diversity enforcement**: Candidates 1 and 2 used different source methods (`PPO_Safety` vs `PPO_Energy`) but produced identical patches. No mechanism detected or prevented this.
3. **Method selection had no fallback**: When a category had fewer untried methods than `batch_size`, the system stopped rather than falling through to the next category.
4. **No diagnostic tracking**: No visibility into patch similarity, method overlap, or candidate diversity metrics.

---

## II. Changes Implemented

### A. Candidate Diversity Diagnostics

**File:** `research_agent/core/executor.py`

New functions:
- `_compute_patch_similarity(diff_a, diff_b) -> float`: Jaccard similarity of added/removed lines between two unified diffs. Returns 0.0-1.0.
- `_check_candidate_diversity(observer, candidate, candidate_ideas, previous_results, candidate_id)`: Compares current candidate against all previous results. Emits events for duplicates (>=0.95 similarity) and low diversity (>=0.8 similarity). Tracks method overlap.

Integration point: called after `candidate_created` event in the iteration loop.

### B. Observability Tracking

**File:** `research_agent/core/observability.py`

New tracking fields:
- `candidate_diversity_enabled` (bool)
- `candidate_pair_similarity_max` (float)
- `duplicate_patch_count` (int)
- `duplicate_method_count` (int)
- `low_diversity_candidate_count` (int)
- `method_selection_fallback_count` (int)

New method: `track_candidate_diversity(current_diff, current_method_ids, similarity_score, is_duplicate_patch, is_duplicate_method, is_low_diversity)`

New events emitted:
- `candidate_duplicate_detected`: similarity >= 0.95
- `candidate_low_diversity`: similarity >= 0.8 but < 0.95
- `candidate_diversity_checked`: every candidate, with full diagnostic data

### C. Cross-Category Method Fallback

**File:** `research_agent/core/paper_sampler.py`

Changed `get_next_batch()` return type from `list[dict]` to `tuple[list[dict], bool]`.

When the current category has fewer untried methods than `batch_size`:
1. Take all available from current category
2. Fill remaining slots from next priority categories
3. Return `did_fallback=True` if any methods came from non-primary categories

**Callers updated:** `run_optimizer.py`, `research_agent/interfaces/cli.py`

### D. Diversity Context in Proposals

**File:** `research_agent/agents/reward_agent/nodes.py`

`_build_context_proposal_prompt()` now builds a `diversity_context` string:
- Lists previously tried method IDs
- Shows count of previous patches
- Previews last 2 patch diffs (first 200 chars each)

**File:** `research_agent/agents/reward_agent/prompts.py`

Added `{diversity_context}` placeholder to `CONTEXT_PROPOSE_USER_PROMPT`.

Added CRITICAL DIVERSITY RULES section:
- No cosmetic changes (blank lines, whitespace, comments)
- Must add/modify/remove a REWARD TERM or REWARD COMPUTATION
- If same method used before, must change reward term STRUCTURE (not just coefficients)
- Prefer adding new reward terms over modifying existing ones

### E. State Plumbing

**File:** `research_agent/agents/reward_agent/state.py`

New fields: `previous_candidate_diffs: list[str]`, `previous_method_ids: list[str]`

**File:** `research_agent/agents/reward_agent/optimizer.py`

New parameters to `propose_candidate()`: `previous_candidate_diffs`, `previous_method_ids`. Passed through to graph initial state.

---

## III. File Summary

| File | Action | Lines Changed |
|------|--------|---------------|
| `research_agent/core/executor.py` | Modified | +85 (similarity + diversity check + fallback integration) |
| `research_agent/core/observability.py` | Modified | +35 (diversity tracking fields + summary) |
| `research_agent/core/paper_sampler.py` | Modified | +30 (cross-category fallback) |
| `research_agent/agents/reward_agent/nodes.py` | Modified | +15 (diversity context building) |
| `research_agent/agents/reward_agent/prompts.py` | Modified | +12 (diversity rules + placeholder) |
| `research_agent/agents/reward_agent/state.py` | Modified | +3 (diversity fields) |
| `research_agent/agents/reward_agent/optimizer.py` | Modified | +5 (diversity params) |
| `run_optimizer.py` | Modified | +1 (tuple unpacking) |
| `research_agent/interfaces/cli.py` | Modified | +1 (tuple unpacking) |
| `tests/test_candidate_diversity.py` | Created | 307 lines, 20 test cases |

---

## IV. Patch Similarity Algorithm

**Algorithm:** Jaccard similarity of changed lines.

```python
def _compute_patch_similarity(diff_a, diff_b):
    # Extract all + and - lines (excluding --- / +++ headers)
    changes_a = {line.strip()[1:].strip() for line in diff_a if line starts with +/-}
    changes_b = {line.strip()[1:].strip() for line in diff_b if line starts with +/-}
    # Jaccard = |intersection| / |union|
    return len(changes_a & changes_b) / len(changes_a | changes_b)
```

**Thresholds:**
- `>= 0.95`: Duplicate (emits `candidate_duplicate_detected`)
- `>= 0.80`: Low diversity (emits `candidate_low_diversity`)
- `< 0.80`: Acceptable diversity

**Edge cases:**
- Both empty: returns 0.0 (no changes to compare)
- One empty: returns 0.0
- Identical diffs: returns 1.0

---

## V. Observability Events and Summary Fields

### New Events

| Event | Trigger | Key Fields |
|-------|---------|------------|
| `candidate_duplicate_detected` | similarity >= 0.95 | candidate_id, similarity, reason |
| `candidate_low_diversity` | 0.8 <= similarity < 0.95 | candidate_id, similarity |
| `candidate_diversity_checked` | Every candidate | similarity, is_duplicate_patch, is_duplicate_method, is_low_diversity, current_method_ids |

### New Summary Fields

| Field | Type | Description |
|-------|------|-------------|
| `candidate_diversity_enabled` | bool | Always true in v0.8 |
| `candidate_pair_similarity_max` | float | Highest similarity observed |
| `duplicate_patch_count` | int | Patches with similarity >= 0.95 |
| `duplicate_method_count` | int | Candidates reusing same method |
| `low_diversity_candidate_count` | int | Candidates with 0.8 <= similarity < 0.95 |
| `method_selection_fallback_count` | int | Batches filled from non-primary categories |

---

## VI. Method Selection Fallback

Before v0.8: `get_next_batch(batch_size=2)` on category `A_potential` with 1 untried method returned only 1 method.

After v0.8: returns 2 methods (1 from `A_potential` + 1 from next category `B_safety`), with `did_fallback=True`.

Priority order follows taxonomy `priority` field (S > A > B > ...).

---

## VII. Prompt Diversity Instructions

Added to `CONTEXT_PROPOSE_USER_PROMPT`:

```
## Diversity Context
{diversity_context}

## Instructions
...
CRITICAL DIVERSITY RULES:
- Do NOT propose cosmetic changes (blank lines, whitespace, comments).
- Your change MUST add, modify, or remove a REWARD TERM or REWARD COMPUTATION.
- If previous candidates used the same method, you MUST change the reward term STRUCTURE, not just coefficients.
- Prefer adding new reward terms over modifying existing ones.
- The change must be substantively different from any previous candidate listed above.
```

The `{diversity_context}` is dynamically built with:
- List of previously tried method IDs
- Count of previous patches
- Preview of last 2 patch diffs (first 200 chars)

---

## VIII. Test Results

### Candidate Diversity Tests (20 tests)

```
tests/test_candidate_diversity.py::TestComputePatchSimilarity::test_identical_diffs PASSED
tests/test_candidate_diversity.py::TestComputePatchSimilarity::test_different_diffs PASSED
tests/test_candidate_diversity.py::TestComputePatchSimilarity::test_empty_diffs PASSED
tests/test_candidate_diversity.py::TestComputePatchSimilarity::test_cosmetic_vs_substantive PASSED
tests/test_candidate_diversity.py::TestComputePatchSimilarity::test_no_changes PASSED
tests/test_candidate_diversity.py::TestCheckCandidateDiversity::test_duplicate_detected PASSED
tests/test_candidate_diversity.py::TestCheckCandidateDiversity::test_low_diversity_detected PASSED
tests/test_candidate_diversity.py::TestCheckCandidateDiversity::test_diverse_candidates_no_event PASSED
tests/test_candidate_diversity.py::TestCheckCandidateDiversity::test_method_overlap_detected PASSED
tests/test_candidate_diversity.py::TestCheckCandidateDiversity::test_observer_summary_fields PASSED
tests/test_candidate_diversity.py::TestCheckCandidateDiversity::test_summary_includes_diversity_fields PASSED
tests/test_candidate_diversity.py::TestMethodSelectionFallback::test_batch_fills_from_next_category PASSED
tests/test_candidate_diversity.py::TestMethodSelectionFallback::test_no_fallback_when_sufficient PASSED
tests/test_candidate_diversity.py::TestMethodSelectionFallback::test_all_tried_returns_empty PASSED
tests/test_candidate_diversity.py::TestMethodSelectionFallback::test_no_duplicate_ids_in_batch PASSED
tests/test_candidate_diversity.py::TestPromptDiversityContext::test_context_prompt_includes_diversity PASSED
tests/test_candidate_diversity.py::TestPromptDiversityContext::test_system_prompt_no_markdown PASSED
tests/test_candidate_diversity.py::TestEnvHashUnchanged::test_env_hash_unchanged PASSED
tests/test_candidate_diversity.py::TestBaselineGuardNotBypassed::test_baseline_guard_not_disabled PASSED
tests/test_candidate_diversity.py::TestFullEvalProtocolUnchanged::test_eval_protocol_not_modified PASSED

20 passed in 16.67s
```

### Full Suite

```
393 passed, 1 failed (pre-existing Windows path issue in test_smoke.py)
1 warning (LangChain deprecation)
Duration: 2min 53s
```

### Baseline Integrity

- `test_baseline_guard.py`: 19/19 passed
- `test_context_grounded_proposal.py`: 32/32 passed
- `test_eval_diagnostics.py`: env hash = `e19703467be71e20` (unchanged)

---

## IX. What v0.8 Does NOT Change

1. Score formula (composite = weighted sum, threshold = 0.0)
2. Full eval fair protocol (same seeds, same objectives)
3. Baseline guard (still active, not bypassed)
4. HRRL2/env.py baseline (hash `e19703467be71e20` unchanged)
5. Candidate accept/reject logic (diversity is diagnostic-only, does not affect acceptance)

---

## X. Expected Impact on Next Campaign

With v0.8 diversity enforcement:
1. The LLM will see explicit instructions to avoid cosmetic changes and produce reward term modifications
2. If candidate N reuses a method from candidate N-1, the diversity context will force structural differences
3. Cross-category fallback ensures the method pool is fully utilized before exhaustion
4. Observability will report patch similarity, enabling post-campaign analysis of proposal quality

The diversity diagnostics are **advisory only** — they emit events and track metrics but do not block candidate creation. This allows the system to gather data before considering hard enforcement in a future version.
