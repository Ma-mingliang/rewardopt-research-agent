# Reward LangGraph v0.8.1 — Diversity-Aware Real Campaign Report

**Date:** 2026-06-16
**Branch:** `reward-langgraph-v0.8.1-diversity-real-campaign`
**Run ID:** `20260616_090125_reward_langgraph_22eb6f`
**Duration:** 84.6s (1min 25s)
**Outcome:** INFRA FAILURE + COSMETIC PATCHES — diversity prompt insufficient

---

## I. v0.8.1 Goal

Validate whether v0.8's diversity diagnostics, cross-category fallback, and prompt diversity rules produce substantively different reward term modifications in a real LLM campaign with 3 candidates.

---

## II. v0.8 Changes Summary

| Change | File | Purpose |
|--------|------|---------|
| Patch similarity (Jaccard) | `executor.py` | Detect duplicate/low-diversity patches |
| Diversity events | `executor.py` | `candidate_duplicate_detected`, `candidate_low_diversity`, `candidate_diversity_checked` |
| Observability tracking | `observability.py` | 6 new summary fields |
| Cross-category fallback | `paper_sampler.py` | Fill batch from next category when exhausted |
| Diversity context injection | `nodes.py`, `prompts.py` | Previous method IDs + patch previews in prompt |
| CRITICAL DIVERSITY RULES | `prompts.py` | No cosmetic changes, must modify reward terms |
| State plumbing | `state.py`, `optimizer.py` | Pass previous diffs/method IDs through graph |

---

## III. Campaign Command

```bash
conda run -n langgraph python D:/research-agent/run_optimizer.py \
  --project D:/research-agent/HRRL2 \
  --optimizer reward_langgraph \
  --max-iterations 3 \
  --batch-size 1 \
  --execution-python E:/Anaconda/envs/RL2/python.exe \
  --reward-method-pool D:/research-agent/.research-agent/test_method_pool \
  --reward-method-top-k 3 \
  --staged-eval \
  --max-static-repair-attempts 3 \
  --max-runtime-repair-attempts 2 \
  --max-patch-apply-repair-attempts 6 \
  --max-same-error-repair-attempts 2 \
  --no-short-train \
  --baseline-manifest D:/research-agent/docs/baselines/hrrl2_operational_baseline.yaml
```

No `--mock-llm`, no `--accept-baseline-migration`.

---

## IV. Run Summary

| Field | Value |
|-------|-------|
| run_id | `20260616_090125_reward_langgraph_22eb6f` |
| total_candidates | 2 |
| candidates_ready | 0 |
| candidates_rejected | 2 |
| rejection_reasons | `train_failed: 2` |
| iterations_completed | 2 (of 3 planned) |
| stop_reason | All methods exhausted |

---

## V. Candidate Table

| # | candidate_id | method_ids | patch summary | reward terms modified | patch lines | similarity | validation | train/eval | score | rejection |
|---|-------------|-----------|---------------|----------------------|-------------|------------|------------|------------|-------|-----------|
| 1 | v0733 | test_curriculum_003, test_sparse_to_dense_002 | Blank line after `return reward` | NONE | 1 (+1 blank) | 0.0 (first) | pass (after fix) | FAIL (WinError 1455) | N/A | train_failed |
| 2 | v0734 | test_control_energy_005 | Blank line after `return reward` | NONE | 1 (+1 blank) | 0.0 (first in iter 2) | pass (after fix) | FAIL (WinError 1455) | N/A | train_failed |

Both candidates are **identical to v0.7.4** — cosmetic blank line insertion, no reward term modification.

---

## VI. Diversity Metrics

| Metric | Value |
|--------|-------|
| candidate_diversity_enabled | true |
| candidate_pair_similarity_max | 0.0 |
| duplicate_patch_count | 0 |
| duplicate_method_count | 0 |
| low_diversity_candidate_count | 0 |
| method_selection_fallback_count | 1 |

**Note:** similarity_max=0.0 and duplicate_count=0 because each iteration only had 1 candidate (batch_size=1), so there was no previous candidate within the same iteration to compare against. The diversity check compares against `previous_results` which is empty per-iteration. The two candidates ARE identical but were in separate iterations.

---

## VII. Comparison with v0.7.4

| Aspect | v0.7.4 | v0.8.1 | Improved? |
|--------|--------|--------|-----------|
| Identical diffs across candidates | YES (both blank line) | YES (both blank line) | NO |
| Cosmetic-only patch | YES | YES | NO |
| Substantive reward term change | NO | NO | NO |
| Diversity prompt present | NO | YES | YES (but ineffective) |
| Diversity diagnostics | NO | YES (events emitted) | YES |
| Cross-category fallback | NO | YES (1 fallback) | YES |
| Training completed | YES (both ran full eval) | NO (WinError 1455) | WORSE |

---

## VIII. LLM Behavior Analysis

### Iteration 1 (candidate v0733)
1. `propose_node` called with context_grounded=true, function `__calculate_reward`
2. LLM returned **empty diff** (no diff extracted)
3. `validate_node` failed: "No diff to validate"
4. `llm_fix_node` called — LLM produced blank line patch (6 lines)
5. `validate_node` passed after fix
6. Diversity check: similarity=0.0 (no previous candidates)
7. Patch applied, smoke_train started
8. **Training crashed**: `OSError: [WinError 1455] 页面文件太小` loading `cufft64_11.dll`

### Iteration 2 (candidate v0734)
1. Same flow — LLM returned empty diff initially
2. `llm_fix_node` produced identical blank line patch
3. Diversity check: similarity=0.0 (iteration boundary reset)
4. **Same training crash**

### Root Cause: Empty Initial Proposals
Both iterations: LLM returned empty diff on first attempt, then `llm_fix_node` generated the simplest possible patch (blank line). The diversity rules in the prompt were ignored because:
1. The initial proposal was empty (LLM didn't produce a diff at all)
2. The fix node uses a different prompt (`FIX_PROMPT`) that doesn't include diversity rules
3. The fix node's goal is "fix the syntax error" — it defaults to minimal changes

---

## IX. Infrastructure Failure

**Error:** `OSError: [WinError 1455] 页面文件太小，无法完成操作`
**DLL:** `E:\Anaconda\envs\RL2\lib\site-packages\torch\lib\cufft64_11.dll`
**Cause:** Windows page file too small to load CUDA libraries
**Impact:** Both candidates failed at smoke_train, never reached full eval
**Classification:** `train_crash` (infrastructure, not code)

This is a system resource issue. The RL2 conda environment's CUDA/torch cannot load due to memory pressure. This did NOT occur in v0.7.4 (which ran successfully), suggesting system state changed between runs.

---

## X. Baseline Comparison

| Metric | Baseline | v0.8.1 Candidates |
|--------|----------|-------------------|
| reward | 983.26 | N/A (training failed) |
| completion_rate | 1.0 | N/A |
| lateral_error | 0.0041 | N/A |

No candidate completed training, so no metrics comparison is possible.

---

## XI. Observability

| Field | Value |
|-------|-------|
| baseline_guard_run | true |
| baseline_guard_passed | true |
| env_hash_before | e19703467be71e20 |
| env_hash_after | e19703467be71e20 |
| total_llm_calls | 4 (2 propose + 2 fix) |
| context_grounded_proposal_enabled | false (summary field) |
| initial_patch_self_check_passed | 0 |
| syntax_repair_success_count | 2 |
| staged_static_repairs | 2 |
| staged_runtime_repairs | 2 |

**Note:** `context_grounded_proposal_enabled=false` in summary despite events showing `context_grounded=true`. This is a summary field tracking issue — the events confirm context-grounded mode was active.

---

## XII. Key Findings

### Finding 1: Diversity Prompt Is Insufficient
The CRITICAL DIVERSITY RULES in `CONTEXT_PROPOSE_USER_PROMPT` had zero effect. Both candidates produced identical cosmetic patches. The LLM:
- Returned empty diffs on first attempt
- Relied on `llm_fix_node` which uses a simpler prompt without diversity rules
- Defaulted to the safest possible edit (blank line insertion)

### Finding 2: Empty Proposals Bypass Diversity Enforcement
When the LLM returns an empty diff, the system routes to `llm_fix_node`. The fix node's prompt (`FIX_PROMPT`) does NOT include diversity context or diversity rules. This creates a bypass: diversity enforcement only works if the LLM produces a non-empty initial proposal.

### Finding 3: Infrastructure Masked Candidate Quality
WinError 1455 prevented any training, so we cannot assess whether the cosmetic patches would have been rejected by metrics (as in v0.7.4 where score=-0.0726). The infrastructure failure needs to be resolved before meaningful diversity testing.

### Finding 4: Method Pool Exhaustion
Only 5 methods across 4 categories. With batch_size=1 and 3 iterations planned, the pool was exhausted after 2 iterations. The cross-category fallback worked (1 fallback recorded) but couldn't prevent exhaustion.

---

## XIII. Verdict

**v0.8.1 outcome: diversity prompt insufficient**

The diversity diagnostics infrastructure works correctly (events emitted, metrics tracked, fallback triggered). But the prompt-level diversity enforcement is ineffective because:
1. LLM returns empty diffs, routing to fix node without diversity rules
2. Fix node defaults to cosmetic changes
3. No semantic gate blocks cosmetic patches before training

---

## XIV. Recommended Next Steps

### v0.8.2: Hard Candidate Semantic Gate
Block cosmetic/empty patches BEFORE training:
1. **Cosmetic-only reject**: If patch only adds/removes blank lines, whitespace, or comments → reject before train
2. **No-reward-term-change reject**: If patch doesn't add/modify/remove a reward term → reject before train
3. **Duplicate patch reject**: If similarity >= 0.95 with any previous candidate → reject before train
4. **Same structure reject**: If reward term structure repeated with only coefficient changes → reject/defer
5. **Require semantic reward term delta**: Enforce that at least one `+` line contains a reward computation

This requires changes in `executor.py` after `candidate_created` event, before the training step.

### v0.9: Multi-Seed Confirmation (if v0.8.2 produces valid patches)
- Run accepted candidates across multiple seeds
- Uncertainty-aware policy for short_train
- Candidate ranking by stability/tracking tradeoff
