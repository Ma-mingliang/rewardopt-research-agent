# v0.8.8: Diversity-Aware Semantic Candidate Bank Refresh

**Date**: 2026-06-17
**Branch**: reward-langgraph-v0.8.8-diverse-candidate-bank-refresh
**Tag**: reward-langgraph-v0.8.8

## v0.8.7 Summary

v0.8.7 added a `DiversityScheduler` that re-ranks the method pool to favor under-represented categories and excludes already-tried methods. It also fixed two bugs: the proposal-only path missing `_mark_batch()` and template tracking only checking the first idea. Template diversity score improved from 0.0 to 1.0 in unit tests.

## Goal

Run a real proposal-only diversity campaign using the v0.8.7 DiversityScheduler to generate a refreshed candidate bank with diverse, validation-ready semantic reward candidates. Confirm candidates cover multiple templates/categories. Keep `train_called=false` and `full_eval_called=false`.

## Command

```
conda run -n langgraph python D:/research-agent/run_optimizer.py ^
--project D:/research-agent/HRRL2 ^
--optimizer reward_langgraph ^
--max-iterations 5 ^
--batch-size 1 ^
--execution-python E:/Anaconda/envs/RL2/python.exe ^
--reward-method-pool D:/research-agent/.research-agent/test_method_pool ^
--reward-method-top-k 3 ^
--staged-eval ^
--proposal-only ^
--max-semantic-regeneration-attempts 2 ^
--baseline-manifest D:/research-agent/docs/baselines/hrrl2_operational_baseline.yaml
```

## Run Results

| Metric | Value |
|--------|-------|
| run_id | 20260617_123033_reward_langgraph_8bac43 |
| total_candidates | 3 |
| candidates_proposal_only_validated | 3 |
| semantic_gate_passed_count | 3 |
| semantic_gate_rejected_count | 0 |
| template_diversity_score | 1.0 |
| template_low_diversity | false |
| unique_template_count | 3 |
| unique_category_count | 3 |
| train_called | false |
| full_eval_called | false |
| baseline_guard_passed | true |
| env.py hash | e19703467be71e20 (unchanged) |

## Template Distribution

| Template | Category | Count |
|----------|----------|-------|
| test_pbrs_001 | A_potential_based_reward | 1 |
| test_curriculum_003 | C_curriculum_subgoal_reward | 1 |
| test_control_energy_005 | D_adaptive_dynamic_reward | 1 |

## Category Distribution

| Category | Count |
|----------|-------|
| A_potential_based_reward | 1 |
| C_curriculum_subgoal_reward | 1 |
| D_adaptive_dynamic_reward | 1 |

Note: B_safety_constraint_reward was used in iteration 1 (cross-category fallback) but the candidate's primary template was from category A.

## Candidate Quality Audit

| # | Candidate | Template | Category | Source | Reward Terms | Syntax | Validation | Score | Recommendation |
|---|-----------|----------|----------|--------|-------------|--------|------------|-------|----------------|
| 1 | reward_langgraph_c001 | test_control_energy_005 | D_adaptive_dynamic | semantic_regeneration | control_energy penalty (quadratic) | valid | passed | 0.626 | keep_for_future_training |
| 2 | reward_langgraph_c001 | test_pbrs_001 | A_potential_based | semantic_regeneration | risk_penalty (angular_velocity + error thresholds) | valid | passed | 0.605 | keep_for_future_training |
| 3 | reward_langgraph_c001 | test_curriculum_003 | C_curriculum_subgoal | semantic_regeneration | stability_penalty (near-fall conditions) | valid | passed | 0.605 | keep_for_future_training |

## Ranked Candidate Bank

| Rank | Score | Template | Source | Complexity | Terms |
|------|-------|----------|--------|------------|-------|
| 1 | 0.626 | test_control_energy_005 | semantic_regeneration | 0.16 | control_energy penalty |
| 2 | 0.605 | test_pbrs_001 | semantic_regeneration | 0.30 | risk_penalty |
| 3 | 0.605 | test_curriculum_003 | semantic_regeneration | 0.30 | stability_penalty |

## Semantic/Validation Statistics

| Stat | Value |
|------|-------|
| semantic_patch_generated_count | 3 |
| semantic_gate_pass_count | 3 |
| semantic_gate_rejected_count | 0 |
| semantic_regeneration_attempts_total | 4 (2 candidates needed regeneration) |
| semantic_regeneration_success_count | 3 |
| syntax_fail_then_repair_count | 1 (iteration 3: IndentationError repaired) |
| ssl_error_count | 1 (iteration 2: SSL EOF) |
| validation_pass_count | 3 |

## Iteration Log

| Iteration | Methods | Candidate | Status | Notes |
|-----------|---------|-----------|--------|-------|
| 1 | test_pbrs_001, test_risk_penalty_004 | v0771 | validated | syntax-valid on attempt 1 |
| 2 | test_curriculum_003, test_sparse_to_dense_002 | v0772 | failed | syntax fail + SSL error |
| 3 | test_curriculum_003, test_sparse_to_dense_002 | v0773 | validated | syntax fail on attempt 1, repaired on attempt 2 |
| 4 | test_control_energy_005 | v0774 | validated | syntax-valid on attempt 1 |

## Key Findings

### 1. Did diversity improve in a real LLM campaign?

**Yes.** The v0.8.7 DiversityScheduler successfully drove the sampler through different categories. 3 unique templates from 3 different categories were selected, compared to v0.8.5's single template across all 4 candidates.

### 2. Are candidates semantic and validation-ready?

**Yes.** All 3 candidates passed the semantic gate, are syntax-valid, and contain meaningful reward terms (risk_penalty, stability_penalty, control_energy). No cosmetic patches.

### 3. Was the method pool the limiting factor?

**Yes.** The test pool has only 5 methods across 4 categories. With batch_size=2 and cross-category fallback, the pool was exhausted after 4 iterations (3 validated candidates). A larger pool would yield more candidates.

### 4. Top candidate analysis

Rank 1 (`test_control_energy_005`, score 0.626): Control energy penalty with quadratic cost on action magnitude. Lower complexity (0.16) than the other candidates (0.30). Simple, focused reward term.

## Recommendation

**Keep top 1-2 candidates for future training** when resource constraints are addressed. The control_energy and risk_penalty candidates are clean, low-complexity reward terms that could improve driving behavior.

For v0.8.9: Expand to the default pool (142 methods, 8 categories) to test diversity at scale.

## Test Results

```
56 key tests: PASSED
```

## Files Generated

| File | Purpose |
|------|---------|
| `HRRL2/.research-agent/candidate_bank.jsonl` | 3 validation-ready candidates |
| `HRRL2/.research-agent/candidate_bank_ranked.jsonl` | Ranked candidates with scores |
| `HRRL2/.research-agent/candidate_bank_summary.md` | Diversity summary |
| `docs/reports/reward_langgraph_v0_8_8_diverse_candidate_bank_refresh_report.md` | This report |

## Commit and Tag

- **Commit**: `docs: add v0.8.8 diverse candidate bank refresh report`
- **Tag**: `reward-langgraph-v0.8.8`
