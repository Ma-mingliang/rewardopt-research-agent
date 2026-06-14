# Reward LangGraph v0.3 — Full Eval Diagnostics Report

**Date:** 2026-06-15
**Branch:** `reward-langgraph-v0.3-full-eval-diagnostics`
**Commit:** (pending)

---

## Summary

Added structured full eval diagnostics: failure classification, preflight checks, repro command generation, stdout/stderr capture, and env hash recording. Every full eval failure now carries a `failure_type`, `diagnostic_summary`, and `repro_command`.

---

## v0.3 Goals

1. Classify full eval failures into specific types (not just `failed: true`)
2. Save full eval stdout/stderr to files
3. Generate reproducible commands
4. Record env.py hashes for train/eval consistency diagnosis
5. Add preflight checks to skip wasted eval runs
6. Backward compatible — old `metrics` and `failed` fields preserved

---

## New Files (2)

| File | Purpose |
|------|---------|
| `research_agent/core/eval_diagnostics.py` | EvalFailureType enum, EvalDiagnostic dataclass, classify_eval_failure, build_repro_command, hash_file, tail_text, run_eval_preflight |
| `tests/test_eval_diagnostics.py` | 42 tests covering classification, preflight, repro command, hash, backward compat |

## Modified Files (4)

| File | Change |
|------|--------|
| `research_agent/execution/experiment_runner.py` | RunResult gains `diagnostics` field; run_eval/run_full_eval accept observer/candidate_id; stdout/stderr saved to files; _build_diagnostic, _summarize_failure helpers |
| `research_agent/core/observability.py` | track_full_eval method; full_eval_total/failed/failure_types/eval_timeout/model_missing/metrics_parse_failed counters; summary.json includes all new fields |
| `research_agent/core/executor.py` | Preflight before full eval; full_eval_result includes failure_type, failure_stage, diagnostics, repro_command, env hashes; observer passed to run_full_eval |
| `tests/test_langgraph_reward_agent.py` | 3 new tests for full eval diagnostics backward compat |
| `tests/test_observability.py` | 10 new tests for track_full_eval and full eval event emission |

---

## EvalFailureType Enum

| Type | Meaning |
|------|---------|
| `none` | No failure |
| `eval_script_crashed` | evaluate.py returned non-zero with traceback |
| `eval_timeout` | evaluate.py timed out |
| `model_missing` | Model file does not exist |
| `model_load_failed` | Model exists but cannot be loaded |
| `env_import_failed` | env.py has syntax/import errors |
| `metrics_file_missing` | evaluate.py did not create metrics output |
| `metrics_parse_failed` | Metrics parser threw exception |
| `metrics_empty` | returncode=0 but no parseable metrics |
| `required_metrics_missing` | Metrics parsed but missing required keys |
| `subprocess_failed` | Non-zero returncode, no traceback |
| `execution_python_missing` | Python executable does not exist |
| `output_dir_not_writable` | Cannot write to output directory |
| `unknown` | No classification matched |

---

## Preflight Checks

Before running full eval, `run_eval_preflight` checks:

1. execution_python exists
2. project_path exists
3. env.py compiles (py_compile)
4. model_path exists (if known)
5. output directory is writable

If preflight fails, full eval is skipped and diagnostic is returned immediately.

---

## full_eval_result Structure (v0.3)

```json
{
  "metrics": {},
  "failed": true,
  "seeds": [0, 1, 2],
  "failure_type": "metrics_empty",
  "failure_stage": "metrics_parse",
  "returncode": 0,
  "stdout_path": ".../candidate_c001_eval_stdout.txt",
  "stderr_path": ".../candidate_c001_eval_stderr.txt",
  "stdout_tail": "...",
  "stderr_tail": "",
  "resolved_command": "E:/Anaconda/envs/RL2/python.exe evaluate.py --seed 0",
  "repro_command": "cd /d D:/research-agent/HRRL2 && E:/Anaconda/envs/RL2/python.exe evaluate.py --seed 0",
  "model_path": ".../best_model.zip",
  "model_exists": true,
  "eval_env_hash": "5ffc1e934e1f8908",
  "baseline_env_hash": "5ffc1e934e1f8908",
  "diagnostic_summary": "evaluate.py completed (returncode=0) but no parseable metrics were found in stdout",
  "diagnostics": {
    "candidate_id": "reward_c001",
    "stage": "eval",
    "failure_type": "metrics_empty",
    "failed": true,
    "returncode": 0,
    "command": "python evaluate.py --seed {seed}",
    "resolved_command": "E:/Anaconda/envs/RL2/python.exe evaluate.py --seed 0",
    "repro_command": "cd /d D:/research-agent/HRRL2 && E:/Anaconda/envs/RL2/python.exe evaluate.py --seed 0",
    "execution_python": "E:/Anaconda/envs/RL2/python.exe",
    "cwd": "D:/research-agent/HRRL2",
    "duration_ms": 1234,
    "stdout_path": "...",
    "stderr_path": "...",
    "stdout_tail": "...",
    "stderr_tail": "",
    "metrics_keys": [],
    "metrics_empty": true,
    "metrics_parser_ok": true,
    "metrics_parser_error": "",
    "env_path": "D:/research-agent/HRRL2/env.py",
    "env_hash": "5ffc1e934e1f8908",
    "error_message": "",
    "diagnostic_summary": "..."
  }
}
```

Backward compatible: `metrics` and `failed` fields always present. New fields are additive.

---

## summary.json New Fields

```json
{
  "full_eval_total": 3,
  "full_eval_failed": 2,
  "full_eval_failure_types": {
    "metrics_empty": 1,
    "eval_script_crashed": 1
  },
  "eval_timeout_count": 0,
  "model_missing_count": 0,
  "metrics_parse_failed_count": 1,
  "last_failed_eval_repro_command": "cd /d D:/project && python evaluate.py",
  "last_failed_eval_stdout_path": ".../candidate_c001_eval_stdout.txt",
  "last_failed_eval_stderr_path": ".../candidate_c001_eval_stderr.txt"
}
```

---

## events.jsonl New Events

| Event | When | Key Fields |
|-------|------|------------|
| `full_eval_preflight_start` | Before preflight | candidate_id |
| `full_eval_preflight_end` | After preflight | candidate_id, preflight_ok, failure_type |
| `full_eval_failed` | Preflight or eval failure | candidate_id, failure_stage, failure_type |
| `metrics_parse_end` | After metrics parsing | candidate_id, metrics_parser_ok, metrics_keys, metrics_empty |
| `metrics_empty` | When metrics empty | candidate_id, stdout_path, stderr_path |

---

## Test Results

```
110 passed in 29.00s (test_eval_diagnostics + test_observability + test_langgraph_reward_agent)
170 passed, 1 pre-existing failure (full suite — test_smoke.py Windows path issue)
```

| Suite | Tests | Status |
|-------|-------|--------|
| test_eval_diagnostics.py | 42 | All pass |
| test_observability.py | 25 | All pass |
| test_langgraph_reward_agent.py | 46 | All pass |
| Other tests | 57 | All pass |
| test_smoke.py::test_initial_state | 1 | Pre-existing Windows path failure |

---

## Mock Smoke Test

```
conda run -n langgraph python run_optimizer.py \
  --project D:/research-agent/HRRL2 \
  --optimizer reward_langgraph \
  --mock-llm --max-iterations 1 --batch-size 1 \
  --execution-python E:/Anaconda/envs/RL2/python.exe
```

| Check | Result |
|-------|--------|
| run_id | `20260615_005848_reward_langgraph_e7d6bb` |
| summary.json v0.3 fields | All present (full_eval_total=0, etc.) |
| Baseline hash after run | `5ffc1e934e1f8908` (unchanged) |

No full eval triggered in mock mode (expected — mock empty patch rejected before training).

---

## Full Eval Fairness Protocol

- [x] No changes to scoring logic
- [x] No changes to seed selection
- [x] No changes to accept/reject logic
- [x] No changes to baseline restoration
- [x] Diagnostics are purely additive observation
- [x] BaseOptimizer.full_eval_candidate still inherited unchanged

---

## Known Limitations

1. **Real full eval diagnostics not triggered** — mock mode rejects candidates before training, so full eval diagnostic paths are only covered by unit tests and fixtures.
2. **model_load_check not implemented** — model_path existence is checked, but actual model loading test is not implemented (project-specific).
3. **Metrics parser project-specific** — `parse_metrics` relies on regex config; diagnostics report when parser returns empty, but cannot diagnose why regex didn't match without project-specific knowledge.

---

## Next Steps (v0.4 suggestions)

1. Candidate-level diagnostic dashboard (aggregate all diagnostics per candidate)
2. Model load check for supported frameworks (stable-baselines3, torch)
3. Metrics regex effectiveness logging (which patterns matched/missed)
4. Train/eval env hash diff reporting
5. Diagnostic-informed candidate retry (auto-retry on transient failures)
