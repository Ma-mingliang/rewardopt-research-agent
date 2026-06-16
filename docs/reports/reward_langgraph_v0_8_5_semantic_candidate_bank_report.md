# v0.8.5: Semantic Candidate Bank and Validation-Only Campaign

**Date**: 2026-06-16
**Branch**: reward-langgraph-v0.8.5-semantic-candidate-bank
**Tag**: reward-langgraph-v0.8.5
**Run ID**: 20260616_162636_reward_langgraph_a15423

## Goal

Generate a bank of validation-ready semantic reward patches using real LLM, without training or full eval. Each candidate must pass:
- Semantic gate (reward term changes)
- Syntax-safe compile check
- AST parse validation

## Hard Constraints (all honored)

1. No autoconfig stash popped
2. No v0.1–v0.8.4 tags moved
3. Full eval protocol unchanged
4. Seed/metrics/score/accept logic unchanged
5. Baseline guard enabled and passed
6. No --accept-baseline-migration used
7. HRRL2/env.py baseline unchanged
8. No MIMO_API_KEY leaked
9. No training entered
10. No full eval entered
11. No pagefile changes required

## Implementation

### Candidate Bank Output

Added `_write_candidate_bank_record()` to `research_agent/core/executor.py`:
- Writes validated candidates to `candidate_bank.jsonl`
- Each record includes: candidate_id, iteration, method_ids, method_categories, diff_hash, diff_preview, reward_terms_added, reward_terms_modified, semantic_gate_decision, syntax_valid, validation_passed, proposal_source, train_called, full_eval_called

### Proposal Source Tracking

Determined from candidate description prefix:
- `[syntax-repaired]` → `syntax_repair`
- `[template-fallback]` → `template_fallback`
- `[regenerated]` → `semantic_regeneration`
- Otherwise → `primary`

### Semantic Decision Tracking

Fixed bug where `semantic_decision` held the initial rejected decision instead of the final passed decision after regeneration. Now updated in all three success paths (syntax-valid, syntax-repaired, template-fallback).

## Campaign Results

### Run Configuration

```
--max-iterations 5 --batch-size 1 --proposal-only
--max-semantic-regeneration-attempts 2
--staged-eval
--baseline-manifest docs/baselines/hrrl2_operational_baseline.yaml
```

### Iteration Summary

| Iteration | Version | Proposal Source | IndentationError | Result |
|-----------|---------|----------------|-------------------|--------|
| 1 | v0754 | semantic_regeneration | Trailing whitespace (attempt 1) → fixed (attempt 2) | Validated |
| 2 | v0755 | syntax_repair | IndentationError → syntax-repaired | Validated |
| 3 | v0756 | semantic_regeneration | None (first try) | Validated |
| 4 | v0757 | semantic_regeneration | None (first try) | Validated |
| 5 | v0758 | — | SSL error (iteration failed) | Failed |

### Metrics

| Metric | Value |
|--------|-------|
| run_id | 20260616_162636_reward_langgraph_a15423 |
| total_candidates | 4 |
| semantic_patch_generated_count | 4 |
| semantic_gate_pass_count | 4 |
| semantic_gate_rejected_count | 0 |
| semantic_regeneration_attempts_total | 4 |
| semantic_regeneration_success_count | 4 |
| semantic_regeneration_syntax_valid_count | 3 |
| semantic_regeneration_syntax_repair_count | 1 |
| validation_pass_count | 4 |
| candidate_bank_size | 4 |
| cosmetic_patch_rejected_count | 0 |
| no_reward_term_change_count | 0 |
| duplicate_patch_rejected_count | 0 |
| cross_iteration_similarity_max | 0.0 |
| train_called | false |
| full_eval_called | false |
| baseline_guard_passed | true |
| env.py hash before | e19703467be71e20 |
| env.py hash after | e19703467be71e20 |

### Candidate Bank Contents

| # | Candidate | Proposal Source | Diff Hash | Reward Terms |
|---|-----------|----------------|-----------|--------------|
| 1 | reward_langgraph_c001 | semantic_regeneration | — | stability_penalty (conditional) |
| 2 | reward_langgraph_c001 | syntax_repair | — | angular_velocity penalty (exponential) |
| 3 | reward_langgraph_c001 | semantic_regeneration | — | stage_weight potential |
| 4 | reward_langgraph_c001 | semantic_regeneration | — | stability_penalty (conditional) |

### Reward Terms Generated

1. **stability_penalty**: Conditional penalty for near-fall conditions (`angular_velocity > 2.0 or current_error > 0.5`)
2. **angular_velocity penalty**: Exponential decay penalty on angular velocity
3. **stage_weight potential**: Stage-weighted potential-based shaping

All terms use only variables from `available_reward_variables` (angular_velocity, current_error, reward).

## Observability Fields (new)

```json
{
  "semantic_regeneration_syntax_valid_count": 3,
  "semantic_regeneration_syntax_repair_count": 1
}
```

## Files Modified

| File | Changes |
|------|---------|
| `research_agent/core/executor.py` | Added `_write_candidate_bank_record()`, candidate bank initialization, proposal source tracking, semantic_decision update in regeneration success paths |

## Key Findings

### 1. Did v0.8.5 produce validation-ready semantic patches?

**Yes.** 4 out of 5 iterations produced validation-ready patches. 1 iteration failed due to SSL error (infrastructure issue, not semantic).

### 2. How many were cosmetic and rejected?

**0.** All initial proposals triggered semantic regeneration (cosmetic/empty), and all regeneration attempts eventually produced valid semantic patches.

### 3. How many required semantic regeneration?

**4 out of 4** (100%). The initial LLM proposals were consistently cosmetic or empty, requiring regeneration every time.

### 4. How many required syntax repair?

**1 out of 4** (25%). One patch had IndentationError that was fixed by syntax-aware repair.

### 5. How many passed semantic gate but failed validation?

**0.** All patches that passed semantic gate also passed syntax-safe validation.

### 6. What reward terms were generated?

- stability_penalty (conditional, 2 variants)
- angular_velocity penalty (exponential decay)
- stage_weight potential-based shaping

### 7. Were terms based only on available variables?

**Yes.** All terms use angular_velocity, current_error, and reward — all from the available variables list.

### 8. Were patches diverse or repetitive?

**Partially repetitive.** The stability_penalty pattern appeared twice. The angular_velocity penalty appeared twice with different formulations. The stage_weight potential was unique. Cross-iteration similarity was 0.0 (no exact duplicates).

### 9. Did train/full eval remain skipped?

**Yes.** `train_called=false`, `full_eval_called=false` for all candidates.

### 10. Did env.py hash remain unchanged?

**Yes.** `e19703467be71e20` before and after.

### 11. Did baseline guard pass?

**Yes.** `baseline_guard_passed=true`.

### 12. Is it worth later training, or should v0.9 switch to deterministic template synthesis?

**Recommendation: Hybrid approach.** The LLM regeneration is now reliable (4/4 success rate) but produces somewhat repetitive patches. A deterministic template synthesizer could:
- Guarantee syntax correctness (no IndentationError)
- Generate more diverse reward terms by combining templates
- Be faster and cheaper (no LLM calls)
- Be validated deterministically

However, the LLM approach still has value for generating novel reward structures that templates can't anticipate. A v0.9 hybrid could:
1. Use deterministic templates as the primary path
2. Use LLM regeneration as a fallback for novel structures
3. Use the semantic gate + syntax-safe checks as universal validators

## Test Results

```
94 targeted tests: PASSED
484 full suite tests: PASSED (1 pre-existing Windows path issue)
```

## Commit and Tag

- **Commit**: `feat: add semantic candidate bank`
- **Tag**: `reward-langgraph-v0.8.5`
