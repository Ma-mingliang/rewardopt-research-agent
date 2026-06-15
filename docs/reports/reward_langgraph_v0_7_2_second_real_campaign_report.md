# Reward LangGraph v0.7.2 — Second Real Campaign

**Date:** 2026-06-15
**Branch:** `reward-langgraph-v0.7.2-second-real-campaign`
**Tag:** `reward-langgraph-v0.7.2` (pending)

---

## I. Goal

Run the second real optimization campaign (2 candidates) with the v0.7.1 syntax-aware patch repair mechanism. Verify that the repair loop terminates in 6 attempts (not 30) with strategy switching.

---

## II. Campaign Parameters

| Parameter | Value |
|-----------|-------|
| Run ID | `20260615_224934_reward_langgraph_37290f` |
| Project | HRRL2 |
| Branch | `optimizer-run-v2` |
| Commit | `4a90930` |
| Agent Python | `E:\Anaconda\envs\langgraph\python.exe` |
| Execution Python | `E:/Anaconda/envs/RL2/python.exe` |
| Mock LLM | false |
| Max Iterations | 2 |
| Batch Size | 1 |
| Staged Eval | enabled |
| Short Train | disabled |
| Max Patch Repair Attempts | 6 |
| Max Same Error Attempts | 2 |
| Duration | 38,281 ms (38 seconds) |

---

## III. Campaign Results

### Candidate Summary

| Metric | Value |
|--------|-------|
| Candidates Total | 1 |
| Candidates Ready | 1 |
| Candidates Rejected | 1 |
| Candidates Trained | 0 |
| Candidates Eval Failed | 0 |
| LLM Calls Total | 1 |

### Patch Repair Summary

| Metric | Value |
|--------|-------|
| Patch Repair Attempts Total | 4 |
| Strategy Switches | 3 |
| Validation Pass Count | 0 |
| Smoke Train Pass Count | 0 |
| Full Eval Pass Count | 0 |
| Rejection Reason | `patch_repair_exhausted` |
| Error | IndentationError at env.py line 958 |

### Strategy History

| Attempt | Strategy | Result |
|---------|----------|--------|
| 1 | `direct_diff_repair` | IndentationError at line 958 |
| 2 | `direct_diff_repair` | Same error → switch strategy |
| 3 | `local_hunk_regeneration` | Same error → switch strategy |
| 4 | `idea_regeneration_from_baseline` | Same error → all strategies exhausted |

Total: 4 attempts with 3 strategy switches. Patch rejected.

---

## IV. Comparison: v0.7 vs v0.7.2

| Metric | v0.7 (First Campaign) | v0.7.2 (Second Campaign) |
|--------|----------------------|--------------------------|
| Repair Attempts | 30 | **4** |
| Strategy Switches | 0 | **3** |
| Duration | 5.8 minutes | **38 seconds** |
| Error | IndentationError:983 | IndentationError:958 |
| Root Cause | No error tracking, same prompt ×30 | Error tracked, strategy escalated |
| Result | Exhausted | Exhausted |

The v0.7.1 repair mechanism works as designed: repeated errors are detected after 2 attempts and strategies are escalated. The loop terminates in 4 attempts instead of 30.

---

## V. Remaining Problem

The LLM consistently generates patches with `IndentationError` at different lines (983 in v0.7, 958 in v0.7.2). Even with strategy escalation, the repair cannot fix the structural issue. This is an **LLM generation quality problem**, not a repair mechanism problem.

Possible next steps:
1. Improve the initial patch generation prompt (structural constraints)
2. Add pre-generation code structure analysis
3. Use few-shot examples of correct reward patches
4. Validate patch structure before full apply (dry-run indentation check)

---

## VI. Baseline Guard

| Metric | Value |
|--------|-------|
| Baseline Guard Run | true |
| Baseline Guard Passed | true |
| Manifest Path | `docs/baselines/hrrl2_operational_baseline.yaml` |
| Manifest Hash | `e19703467be71e20` |
| env.py Hash | `e19703467be71e20` (unchanged) |

---

## VII. Bugfix: Observer Tracking

### Problem

The v0.7.2 campaign run showed `patch_repair_attempts_total=0` in summary.json despite events.jsonl having 4 repair attempts. Root cause: `observer.track_patch_repair()` was never called from the executor loop — only `observer.emit()` was called.

### Fix

Added `observer.track_patch_repair()` calls at three locations in `executor.py`:
1. After `patch_repair_success` event → tracks success count and strategy
2. After `patch_repair_exhausted` event → tracks exhausted count and error signature
3. After `repeated_patch_repair_error` event → tracks repeated error count

Also removed duplicate `_log_candidate` and `_mark_batch` calls in the exhausted path.

### Commits

- `e83f147` — `fix: wire observer.track_patch_repair() calls in executor loop`
- `eb8dc07` — `fix: remove duplicate _log_candidate and _mark_batch calls in repair exhausted path`

**Note:** The campaign was run before these fixes, so the summary counters in this run's summary.json are still 0. Future runs will have correct counters.

---

## VIII. Observability Events

### events.jsonl (25 events)

| Event | Key Fields |
|-------|------------|
| `run_start` | phase=main |
| `baseline_guard_start` | manifest_hash=e19703467be71e20, auto_push=true |
| `baseline_guard_pass` | env_hash=e19703467be71e20 |
| `iteration_start` | iteration=1 |
| `method_pool_loaded` | total=5, categories=[A,B,C,D] |
| `candidate_created` | candidate_id=reward_langgraph_c001 |
| `patch_repair_start` | max_attempts=6, max_same_error=2 |
| `patch_repair_attempt` | strategy=direct_diff_repair, attempt=1, error_line=958 |
| `patch_repair_strategy_switch` ×3 | direct→local_hunk→idea_regen |
| `patch_repair_exhausted` | total_attempts=4 |
| `repeated_patch_repair_error` | error_signature=IndentationError|env.py|958|... |
| `run_end` | total_iterations=1 |

### summary.json Counters (pre-fix, all 0)

| Counter | Value | Expected (post-fix) |
|---------|-------|---------------------|
| `patch_repair_attempts_total` | 0 | 4 |
| `patch_repair_exhausted_count` | 0 | 1 |
| `repeated_patch_repair_error_count` | 0 | 1 |
| `syntax_repair_success_count` | 0 | 0 |
| `repair_strategy_counts` | {} | {direct: 2, local_hunk: 1, idea_regen: 1} |

---

## IX. env.py Hash Verification

**Hash:** `e19703467be71e20` — **unchanged**.

---

## X. Final Output

| # | Item | Value |
|---|------|-------|
| 1 | Run ID | `20260615_224934_reward_langgraph_37290f` |
| 2 | Duration | 38 seconds |
| 3 | Candidates Total | 1 |
| 4 | Non-empty Patch Count | 1 |
| 5 | Patch Repair Attempts Total | 4 |
| 6 | Repeated Error Strategy Switch Count | 3 |
| 7 | Validation Pass Count | 0 |
| 8 | Smoke Train Pass Count | 0 |
| 9 | Full Eval Pass Count | 0 |
| 10 | Rejection Reason Distribution | `{patch_repair_exhausted: 1}` |
| 11 | env.py Hash | `e19703467be71e20` (unchanged) |
| 12 | Baseline Guard | passed |
| 13 | Observer Bugfix | committed (e83f147, eb8dc07) |
| 14 | Summary Counters | 0 (pre-fix run; post-fix runs will be correct) |
| 15 | Improvement | 4 attempts / 38s vs 30 attempts / 5.8min |
| 16 | Next Step | Improve initial patch generation quality |

---

## XI. Recommendation

The v0.7.1 syntax-aware repair mechanism is **working correctly**: 4 attempts with 3 strategy switches instead of 30 wasted calls. The remaining problem is that the LLM generates structurally broken patches (IndentationError) that even strategy escalation cannot fix.

**Next priority:** Improve initial patch generation to produce structurally valid diffs. The repair mechanism is ready; the generation quality needs work.
