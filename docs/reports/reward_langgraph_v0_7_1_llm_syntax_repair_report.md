# Reward LangGraph v0.7.1 — LLM Syntax-Aware Patch Repair

**Date:** 2026-06-15
**Branch:** `reward-langgraph-v0.7.1-llm-syntax-repair`
**Tag:** `reward-langgraph-v0.7.1`

---

## I. Background: v0.7 First Campaign Failure

The v0.7 real campaign (Run ID: `20260615_213208_reward_langgraph_b59f51`) failed because:

1. LLM generated a patch with `IndentationError` at env.py line 983-984.
2. The repair loop tried 30 times with the same simple prompt.
3. Each attempt produced the same error — no error signature tracking, no strategy switching.
4. 30 LLM API calls were wasted on a fundamentally broken patch.

**Root cause**: The repair mechanism was naive — it sent the same prompt 30 times without detecting repeated failures or escalating to better strategies.

---

## II. Why 30 Attempts Was a Problem

| Issue | Impact |
|-------|--------|
| No error signature tracking | Same error repeated 30 times undetected |
| No strategy switching | Same repair approach applied 30 times |
| Minimal context in prompt | LLM couldn't understand the structural problem |
| No temp copy validation | Repaired diffs not validated before accepting |
| Hardcoded limit | No way to configure via CLI or config |

---

## III. Why LLM Repair Is Still Necessary

IndentationError in LLM-generated patches cannot be fixed by simple heuristics because:

1. The error is in the *diff*, not in the original file.
2. The diff may have correct *intent* but wrong *structure*.
3. The LLM needs to understand the surrounding code context to fix indentation.
4. Pattern-based fixes (like `auto_fix_indentation`) can handle simple cases but fail on structural issues (broken if/else/try blocks).

---

## IV. New Syntax-Aware Repair Mechanism

### Module: `research_agent/core/patch_repair.py`

**Data structures:**
- `PatchRepairError`: Structured error with type, file, line number, message, traceback, diff, baseline context, patched context
- `PatchRepairResult`: Result of repair attempt with strategy, diagnostics
- `RepairStrategy` (enum): `direct_diff_repair`, `local_hunk_regeneration`, `idea_regeneration_from_baseline`
- `RepairAttemptTracker`: Tracks attempts, error signatures, strategy state

**Key functions:**
- `make_error_signature(error_type, file, line, message)` → normalized signature string
- `extract_error_line(message)` → line number (handles `line N` and `file:N:` formats)
- `extract_error_type(message)` → exception type
- `extract_local_context(file, line, radius)` → code around error with line markers
- `build_syntax_repair_prompt(error, strategy, ...)` → system + user prompt
- `parse_repair_response(text)` → extracted diff from LLM response
- `validate_repaired_diff_on_temp_copy(project, diff, ...)` → (ok, errors) via temp directory

---

## V. Three Repair Strategies

### Strategy 1: `direct_diff_repair`
- Input: failed diff + error + context
- Instruction: Fix the diff so it applies and compiles
- Use case: header errors, line count errors, small indentation fixes

### Strategy 2: `local_hunk_regeneration`
- Triggered when: same error signature appears 2+ times
- Instruction: Regenerate ONLY the hunk around the error line from baseline context
- Use case: repeated IndentationError, broken if/else/try blocks

### Strategy 3: `idea_regeneration_from_baseline`
- Triggered when: local_hunk_regeneration also fails
- Instruction: Generate a NEW minimal patch from scratch using baseline code + reward idea
- Use case: fundamentally broken diff structure, unfixable patches

---

## VI. Repair Budget (Default Values)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_patch_apply_repair_attempts` | **6** | Total repair attempts (was 30) |
| `max_same_error_repair_attempts` | **2** | Same error before strategy switch |
| `max_strategy_attempts.direct_diff_repair` | 2 | Max attempts for strategy 1 |
| `max_strategy_attempts.local_hunk_regeneration` | 2 | Max attempts for strategy 2 |
| `max_strategy_attempts.idea_regeneration_from_baseline` | 2 | Max attempts for strategy 3 |
| `fail_fast_on_repeated_error` | true | Enable repeated-error detection |

### CLI Flags

```
--max-patch-apply-repair-attempts INT
--max-same-error-repair-attempts INT
```

---

## VII. Repeated-Error Fail-Fast

```
Attempt 1: IndentationError|env.py|983|expected indented block → strategy: direct_diff_repair
Attempt 2: IndentationError|env.py|983|expected indented block → same error! switch strategy
Strategy switch: direct_diff_repair → local_hunk_regeneration
Attempt 3: IndentationError|env.py|983|expected indented block → strategy: local_hunk_regeneration
Attempt 4: IndentationError|env.py|983|expected indented block → same error! switch strategy
Strategy switch: local_hunk_regeneration → idea_regeneration_from_baseline
Attempt 5: (new diff generated from scratch)
Attempt 6: (if still failing) → patch_repair_exhausted
```

Total: 6 attempts max, not 30.

---

## VIII. Prompt Context Design

The repair prompt now includes:

1. Error type, file, line number, message
2. Traceback tail (last 20 lines)
3. Failed unified diff
4. Baseline code around error (40-60 lines)
5. Patched code around error (40-60 lines)
6. Allowed changes
7. Reward idea / rationale
8. Method pool context (if available)
9. Strategy-specific instructions
10. Constraints (no full rewrite, no new imports, minimal diff)

---

## IX. Observability

### New events.jsonl event types

| Event | Fields |
|-------|--------|
| `patch_repair_start` | candidate_id, max_attempts, max_same_error |
| `patch_repair_attempt` | candidate_id, strategy, attempt, error_signature, error_type, error_line |
| `patch_repair_strategy_switch` | candidate_id, old_strategy, new_strategy, error_signature, same_error_count |
| `patch_repair_success` | candidate_id, total_attempts, strategy_history |
| `patch_repair_exhausted` | candidate_id, total_attempts, diagnostics |
| `repeated_patch_repair_error` | candidate_id, last_error_signature, error_counts |

### New summary.json fields

| Field | Type |
|-------|------|
| `patch_repair_attempts_total` | int |
| `patch_repair_exhausted_count` | int |
| `repeated_patch_repair_error_count` | int |
| `syntax_repair_success_count` | int |
| `max_patch_apply_repair_attempts` | int |
| `max_same_error_repair_attempts` | int |
| `repair_strategy_counts` | dict |
| `last_patch_repair_error_signature` | string \| null |

---

## X. Test Results

| Test File | Result |
|-----------|--------|
| `tests/test_llm_syntax_repair.py` | **32 passed** |
| `tests/test_patch_repair_budget.py` | **21 passed** |
| `tests/test_baseline_guard.py` | 19 passed |
| `tests/test_eval_diagnostics.py` | 42 passed |
| `tests/test_observability.py` | 22 passed |
| `tests/test_staged_evaluation.py` | 26 passed |
| **New tests total** | **53 passed** |
| Full suite (`tests/ -q`) | **341 passed, 1 failed** |

**Failure classification:** The 1 failure is `tests/test_smoke.py::test_initial_state` — a pre-existing Windows path issue (`D:\project` vs `/project`). This failure exists on the `main` branch before v0.7.1. No evidence v0.7.1 introduced or worsened this failure.

---

## XI. Mock Smoke Results

**Command:**
```
python run_optimizer.py --project HRRL2 --optimizer reward_langgraph --mock-llm \
  --max-iterations 1 --batch-size 1 \
  --reward-method-pool .research-agent/test_method_pool \
  --reward-method-top-k 3 --staged-eval --no-short-train \
  --max-patch-apply-repair-attempts 6 --max-same-error-repair-attempts 2
```

**Results:**
- `baseline_guard_passed=true`
- `staged_eval_enabled=true`
- `method_pool_enabled=true`
- `execution_python=E:/Anaconda/envs/RL2/python.exe`
- `env.py hash unchanged: e19703467be71e20`
- `max_patch_apply_repair_attempts=6` (from CLI)
- `max_same_error_repair_attempts=2` (from CLI)
- Summary has all new patch_repair fields

---

## XII. env.py Hash Verification

**Hash:** `e19703467be71e20` — **unchanged**.

---

## XIII. Full Eval Protocol

**Not modified.** v0.7.1 only changes the LLM patch repair mechanism. Full eval protocol, seed, metrics, score, accept/reject logic are all unchanged.

---

## XIV. Recommendation

**Ready to continue v0.7 second round campaign.** The new repair mechanism:

1. Reduces max attempts from 30 to 6.
2. Detects repeated errors and switches strategies.
3. Provides rich context to the LLM for better repairs.
4. Validates repaired diffs on temp copies before accepting.
5. Records detailed diagnostics for each repair attempt.
