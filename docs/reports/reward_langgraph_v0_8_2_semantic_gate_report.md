# Reward LangGraph v0.8.2 — Hard Semantic Gate Report

**Date:** 2026-06-16
**Branch:** `reward-langgraph-v0.8.2-semantic-gate`
**Baseline:** v0.8.1 (`reward-langgraph-v0.8.1-diversity-real-campaign`)

---

## I. v0.8.1 Failure Background

v0.8.1 real campaign produced 2 candidates, both **identical cosmetic blank-line patches** — the same failure as v0.7.4 and v0.8. Despite CRITICAL DIVERSITY RULES in the prompt, the LLM returned empty diffs on first attempt, routing to `llm_fix_node` which generated cosmetic patches.

**Root causes:**
1. Primary propose returned empty diff
2. Empty diff routed to `llm_fix_node` → `FIX_PROMPT`
3. `FIX_PROMPT` did NOT inherit v0.8's diversity rules
4. Fix path generated cosmetic blank-line patch
5. No semantic validation blocked cosmetic patches before training
6. Cross-iteration duplicate tracking was missing (only within-iteration comparison)
7. Windows pagefile too small (WinError 1455) crashed CUDA DLL loading

---

## II. Changes Implemented

### A. Hard Semantic Patch Gate

**File:** `research_agent/core/semantic_patch_gate.py` (NEW)

`SemanticPatchDecision` dataclass with fields:
- `passed`, `reason`, `semantic_change_detected`, `cosmetic_only`, `blank_line_only`, `whitespace_only`, `comment_only`, `reward_terms_changed`, `reward_terms_added`, `reward_terms_removed`, `coefficient_only_change`, `modified_files`, `changed_line_count`

`analyze_patch_semantics(diff_text, reward_function_lines, previous_diffs, similarity_threshold)` — rejects:
1. Empty diffs
2. Blank-line-only patches
3. Whitespace-only patches
4. Comment-only patches
5. Patches with no reward term changes
6. Duplicate patches (similarity >= 0.95)

Reward term detection uses 18+ regex patterns matching: `reward +=`, `potential`, `penalty`, `bonus`, `tracking_reward`, `lateral_error`, `angular_velocity`, `completion_reward`, `safety_penalty`, `energy_penalty`, `curriculum`, `gamma*phi`, `alpha*error`, `rho*constraint`, etc.

**Integration:** `executor.py` — semantic gate runs after `candidate_created` event, BEFORE training. Cosmetic patches are rejected with `rejection_reason=cosmetic_patch_rejected` or `no_reward_term_change`.

### B. FIX_PROMPT Diversity Propagation

**File:** `research_agent/agents/reward_agent/prompts.py`

New prompts:
- `SEMANTIC_FIX_SYSTEM_PROMPT` — instructs LLM to modify reward terms, prohibits cosmetic changes
- `SEMANTIC_FIX_PROMPT` — includes `{diversity_context}`, `{previous_diff}`, `{existing_reward_terms}`, `{line_numbered_context}`

**File:** `research_agent/agents/reward_agent/nodes.py`

Updated `propose_node` empty diff retry: when primary propose returns empty and ProposalContext is available, uses `SEMANTIC_FIX_PROMPT` instead of repeating the same prompt. This ensures diversity rules reach the fix path.

Added `_build_diversity_context_string()` helper for reuse across prompts.

### C. Cross-Iteration Duplicate Tracking

**File:** `research_agent/core/executor.py`

New `candidate_diff_history: list[dict]` accumulates across all iterations in a run. Each entry records: `candidate_id`, `iteration`, `diff`, `method_ids`, `decision`.

After semantic gate passes, candidate diff is compared against ALL previous iteration diffs. If similarity >= 0.95, emits `cross_iteration_duplicate_detected` event.

**File:** `research_agent/core/observability.py`

New summary fields:
- `cross_iteration_duplicate_patch_count`
- `cross_iteration_similarity_max`

### D. Windows CUDA/Pagefile Preflight

**File:** `research_agent/core/system_preflight.py` (NEW)

`run_system_preflight(execution_python)` — runs BEFORE training loop:
1. Checks OS (Windows detection)
2. Attempts `import torch` in execution environment
3. If WinError 1455 detected → `failure_type=infra_windows_pagefile_too_small`
4. Returns `fix_hint` with pagefile sizing guidance (16384MB initial, 32768MB max)

If preflight fails with pagefile error, the run stops immediately — candidates are NOT blamed for infra failure.

Events: `system_preflight_start`, `system_preflight_pass`, `system_preflight_failed`

### E. Observability

**File:** `research_agent/core/observability.py`

New tracking methods:
- `track_semantic_gate(passed, reason, cosmetic_only, reward_terms_changed)`
- `track_cross_iteration_duplicate(similarity)`
- `track_system_preflight(passed, failure_type, torch_importable)`

New summary fields:
- `semantic_gate_enabled`, `semantic_gate_passed_count`, `semantic_gate_rejected_count`
- `cosmetic_patch_rejected_count`, `no_reward_term_change_count`
- `semantic_gate_rejection_reasons` (dict)
- `cross_iteration_duplicate_patch_count`, `cross_iteration_similarity_max`
- `system_preflight_enabled`, `system_preflight_passed`, `system_preflight_failure_type`
- `torch_import_preflight_passed`

---

## III. File Summary

| File | Action | Lines |
|------|--------|-------|
| `research_agent/core/semantic_patch_gate.py` | CREATE | ~200 |
| `research_agent/core/system_preflight.py` | CREATE | ~120 |
| `research_agent/core/executor.py` | MODIFY | +80 (semantic gate + preflight + cross-iteration) |
| `research_agent/core/observability.py` | MODIFY | +40 (new tracking + summary fields) |
| `research_agent/agents/reward_agent/prompts.py` | MODIFY | +45 (semantic fix prompts) |
| `research_agent/agents/reward_agent/nodes.py` | MODIFY | +30 (semantic retry + diversity builder) |
| `tests/test_semantic_patch_gate.py` | CREATE | ~230 |
| `tests/test_fix_prompt_diversity.py` | CREATE | ~70 |
| `tests/test_system_preflight.py` | CREATE | ~140 |

---

## IV. Test Results

### Targeted Tests (115 tests)

```
test_semantic_patch_gate.py:     24/24 passed
test_fix_prompt_diversity.py:     8/8 passed
test_system_preflight.py:        12/12 passed
test_candidate_diversity.py:     20/20 passed
test_context_grounded_proposal.py: 32/32 passed
test_baseline_guard.py:          19/19 passed
```

### Full Suite

```
437 passed, 1 failed (pre-existing Windows path issue in test_smoke.py)
Duration: 56.83s
```

---

## V. What v0.8.2 Does NOT Change

1. Full eval protocol (same seeds, same objectives, same metrics)
2. Score formula (composite = weighted sum, threshold = 0.0)
3. Accept/reject logic for candidates that pass semantic gate
4. Baseline guard (still active)
5. HRRL2/env.py baseline (hash `e19703467be71e20` unchanged)

---

## VI. Mock Smoke Scenarios

### Scenario A: Cosmetic patch → rejected before train
- Primary propose returns empty → semantic fix prompt → blank-line diff
- Semantic gate: `cosmetic_patch_rejected`
- Train: NOT called
- Result: rejection logged, no training wasted

### Scenario B: Real reward term → passes gate
- Primary propose returns `reward += safety_penalty`
- Semantic gate: `passed` (reward_terms_changed=True)
- Validation: passes
- Result: proceeds to train

### Scenario C: Pagefile error → infra stop
- System preflight detects WinError 1455
- Run stops immediately with `infra_windows_pagefile_too_small`
- Candidates: NOT blamed
- Fix hint: pagefile sizing guidance

---

## VII. Required User Action Before Real Campaign

**Windows pagefile must be increased before running v0.8.3:**

1. Right-click This PC → Properties → Advanced system settings
2. Performance → Settings → Advanced → Virtual Memory
3. Set: Initial size = 16384MB, Maximum size = 32768MB
4. Reboot

Without this, any real campaign will fail at system preflight with `infra_windows_pagefile_too_small`.

---

## VIII. Recommendation

Proceed to **v0.8.3** real campaign AFTER:
1. Windows pagefile increased and rebooted
2. v0.8.2 pushed and verified

If v0.8.3 still produces cosmetic patches despite semantic gate, the issue is in the LLM's ability to generate reward term modifications — consider:
- Stronger prompt engineering
- Few-shot examples in the prompt
- Different LLM model
- Human-in-the-loop candidate review
