# Reward LangGraph v0.7 — First Campaign Failure Report

**Date:** 2026-06-15
**Branch:** `reward-langgraph-v0.7-small-real-campaign`
**Run ID:** `20260615_213208_reward_langgraph_b59f51`

---

## I. Campaign Configuration

| Parameter | Value |
|-----------|-------|
| Optimizer | reward_langgraph |
| Mock LLM | false (real LLM) |
| Max iterations | 1 |
| Batch size | 3 |
| Execution Python | E:/Anaconda/envs/RL2/python.exe |
| Staged eval | enabled |
| Short train | disabled |
| Baseline manifest | docs/baselines/hrrl2_operational_baseline.yaml |
| Method pool | .research-agent/test_method_pool |
| Method top-k | 3 |

---

## II. Preflight Results

| Check | Result |
|-------|--------|
| Credential preflight | key_present=true, key_source=dotenv, key_length=51 |
| Baseline guard | **PASSED** (env_hash=e19703467be71e20) |
| Method pool loaded | 5 methods, 4 categories |
| env.py hash | **unchanged** (e19703467be71e20) |
| Working tree | clean |

---

## III. Candidate Details

### v0724 — reward_langgraph_c001

| Field | Value |
|-------|-------|
| Candidate ID | reward_langgraph_c001 |
| Method | test_risk_penalty_004 (B_safety_constraint_reward) |
| Category | B_safety_constraint_reward |
| Status | **REJECTED** |
| Rejection reason | Patch apply failed after 30 repair attempts |
| Reward formula | Added asymmetric safety penalty that scales exponentially with proximity to safety boundaries |
| Diff lines | 24 |
| LLM calls (propose) | 1 |
| LLM calls (repair) | 30 |
| Total LLM calls | 31 |
| Metrics before | reward=930.85, completion_rate=1.0, lateral_error=0.0041 |
| Train reached | **no** |
| Eval reached | **no** |

---

## IV. Failure Analysis

### Root Cause

The LLM generated a unified diff with an `IndentationError` at `env.py` line 983-984. The error message:

```
IndentationError: expected an indented block after 'if' statement on line 983 (env.py, line 984)
```

The patch repair loop attempted 30 times to fix this error via LLM repair, but each attempt produced a diff with the same error. The loop exhausted all 30 attempts without ever producing a compilable patch.

### Why 30 Attempts Failed

1. **No error signature tracking**: The repair loop did not detect that the same `IndentationError` at the same location was repeating.
2. **No strategy switching**: The same repair approach was applied 30 times without attempting alternative strategies (e.g., local hunk regeneration, idea regeneration from baseline).
3. **Insufficient context**: The repair prompt may not have included enough local code context (baseline + patched) around the error location for the LLM to understand the structural problem.
4. **Wasted API calls**: 30 LLM calls were consumed for a fundamentally broken patch, ~5.8 minutes of wall clock time.

### Timeline

| Time (UTC) | Event |
|------------|-------|
| 13:32:08 | Run started |
| 13:32:08 | Baseline guard passed |
| 13:32:09 | Method pool loaded (5 methods) |
| 13:32:10 | Candidate c001 initialized |
| 13:32:27 | LLM proposed diff (24 lines, 1 LLM call) |
| 13:32:29 | Validation passed (AST check) |
| 13:32:29 | Patch apply failed (IndentationError) |
| 13:32:29 – 13:37:54 | 30 repair attempts, all failed |
| 13:37:54 | Candidate rejected |
| 13:37:56 | Run completed |

---

## V. System Protection Verification

| Protection | Status |
|------------|--------|
| Baseline guard | Passed before iteration |
| env.py hash | Unchanged (e19703467be71e20) |
| Patch applied in temp copy | Yes (never touched real env.py) |
| Full eval protocol | Not affected |
| Seed / metrics / score logic | Not affected |
| Accept/reject logic | Not affected |
| Observability events | Recorded correctly |

---

## VI. Observability Data

### events.jsonl

- `run_start` — 13:32:08
- `baseline_guard_start` — 13:32:08
- `baseline_guard_pass` — 13:32:08 (env_hash=e19703467be71e20)
- `optimizer_override` — 13:32:08 (reward -> reward_langgraph)
- `iteration_start` — 13:32:08
- `staged_eval_start` — 13:32:08
- `method_pool_loaded` — 13:32:09 (5 methods, 4 categories)
- `node_start/initialize_node` — 13:32:10
- `node_start/propose_node` — 13:32:10
- `node_end/propose_node` — 13:32:27 (diff_lines=24)
- `node_start/validate_node` — 13:32:27
- `node_end/validate_node` — 13:32:29 (validation_ok=true)
- `node_start/return_candidate_node` — 13:32:29
- `candidate_created` — 13:32:29
- `iteration_end` — 13:37:54 (candidates_evaluated=0)
- `run_end` — 13:37:56

### summary.json

- `baseline_guard_run`: true
- `baseline_guard_passed`: true
- `staged_eval_enabled`: true
- `method_pool_total`: 5
- `candidates_total`: 0 (rejected before counting)
- `duration_ms`: 347967

---

## VII. Conclusion

The v0.7 system protection chain is effective:

1. Baseline guard correctly blocks silent migration.
2. env.py is never directly modified.
3. Patch apply happens in temp copy.
4. Observability records all events.

However, the **LLM patch repair mechanism is inefficient**:

1. 30 attempts for a single IndentationError is wasteful.
2. No error signature detection for repeated failures.
3. No strategy switching when the same repair approach fails.
4. No fail-fast on repeated identical errors.

---

## VIII. Next Steps

**v0.7.1: LLM Syntax-Aware Patch Repair**

1. Implement error signature tracking (`make_error_signature`).
2. Implement 3-tier repair strategy: `direct_diff_repair` -> `local_hunk_regeneration` -> `idea_regeneration_from_baseline`.
3. Reduce default repair attempts from 30 to 6.
4. Add repeated-error fail-fast (max 2 same-signature attempts before strategy switch).
5. Enrich repair prompt with baseline context, patched context, line numbers, and allowed changes.
6. Add observability for repair strategies and error signatures.
7. Add CLI flags for repair budget configuration.

This is **not** a modification of the validation/eval protocol. It only changes the LLM patch repair mechanism to be smarter and more efficient.
