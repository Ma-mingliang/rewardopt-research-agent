# Reward LangGraph v0.5 — Repair-first RL-aware Staged Evaluation

**Date:** 2026-06-15
**Branch:** `reward-langgraph-v0.5-repair-staged-eval`

---

## Summary

Added a repair-first staged evaluation pipeline that screens candidates through progressive stages (static validation → smoke train → short train → full eval) before committing to expensive full evaluation. Code errors enter repair loops before rejection. Smoke training screens for crashes only, not performance. Short train uses uncertainty-aware RL screening that never rejects based on early episode instability. The full eval protocol is completely unchanged.

---

## v0.5 Goals

1. Progressive staged evaluation pipeline with 7 stages
2. Error classification: infra errors vs code errors vs timeout vs crash
3. Code errors enter repair loops before rejection (static + runtime repair)
4. Smoke train: crash-only screening with capped steps (no performance filter)
5. Short train: uncertainty-aware screening, never single-seed hard reject
6. Medium train: multi-seed confirmation with CV-based variance check
7. Full eval: unchanged protocol
8. `staged_evaluation.enabled` defaults to `false` — zero regression risk
9. CLI options for staged eval control
10. Observability events and summary counters for all stages

---

## New Files (5)

| File | Purpose |
|------|---------|
| `research_agent/evaluation/__init__.py` | Package exports |
| `research_agent/evaluation/stages.py` | `StageName`, `StageDecision`, `FailureClass`, `StageResult`, `CandidateStagedResult` |
| `research_agent/evaluation/repair.py` | `classify_failure()`, `is_infra_error()`, `run_smoke_train()` |
| `research_agent/evaluation/policy.py` | `ScreeningPolicy`, `evaluate_short_train()`, `evaluate_medium_train()` |
| `research_agent/evaluation/orchestrator.py` | `should_use_staged_eval()`, `get_staged_config()` |

## Modified Files (4)

| File | Change |
|------|--------|
| `research_agent/core/config.py` | Added `StagedEvaluationConfig` class + field in `AgentConfig` |
| `research_agent/core/executor.py` | 3 injection points in `_execute_optimizer_phase` (~80 lines conditional) |
| `research_agent/core/observability.py` | New counters + `track_staged_*` methods + summary keys |
| `run_optimizer.py` | `--staged-eval`, `--max-static-repair-attempts`, `--max-runtime-repair-attempts`, `--short-train/--no-short-train` |

## Modified Files (1 config)

| File | Change |
|------|--------|
| `configs/default.yaml` | Added `staged_evaluation:` section |

## New Test Files (2)

| File | Tests |
|------|-------|
| `tests/test_staged_evaluation.py` | 26 tests: enums, serialization, classify_failure, is_infra_error, config defaults, orchestrator |
| `tests/test_repair_policy.py` | 20 tests: CV calculation, short_train decisions, medium_train decisions, screening policy |

---

## Staged Evaluation Pipeline

```
proposal → [static_validation] → [static_repair_loop] → [smoke_train] → [runtime_repair_loop] → [short_train] → [medium_train] → full_eval
                                                              ↑                                                    ↑
                                                     crash-only screening                              uncertainty-aware screening
                                                     (no performance filter)                           (no single-seed hard reject)
```

All stages are gated by `if use_staged:` — when `enabled=False`, the conditional blocks are skipped and the flow is identical to pre-v0.5 behavior.

---

## Data Structures

### StageName (7 stages)

```python
class StageName(str, Enum):
    STATIC_VALIDATION = "static_validation"
    STATIC_REPAIR = "static_repair"
    SMOKE_TRAIN = "smoke_train"
    RUNTIME_REPAIR = "runtime_repair"
    SHORT_TRAIN = "short_train"
    MEDIUM_TRAIN = "medium_train"
    FULL_EVAL = "full_eval"
```

### StageDecision (11 decisions)

```python
class StageDecision(str, Enum):
    PASS = "pass"
    REPAIR = "repair"
    PROMOTE = "promote"
    DEFER = "defer"
    NEEDS_MORE_SEEDS = "needs_more_seeds"
    REJECT_CATASTROPHIC = "reject_catastrophic"
    REJECT_VALIDATION_FAILED = "reject_validation_failed"
    REJECT_RUNTIME_FAILED = "reject_runtime_failed"
    REJECT_POLICY_VIOLATION = "reject_policy_violation"
    REJECT_REPAIR_EXHAUSTED = "reject_repair_exhausted"
    INFRA_FAILED = "infra_failed"
```

### FailureClass (8 classes)

```python
class FailureClass(str, Enum):
    STATIC_SYNTAX = "static_syntax"
    STATIC_DIFF = "static_diff"
    RUNTIME_CODE = "runtime_code"
    RUNTIME_INFRA = "runtime_infra"
    RUNTIME_TIMEOUT = "runtime_timeout"
    TRAIN_CRASH = "train_crash"
    EVAL_FAILED = "eval_failed"
    UNKNOWN = "unknown"
```

### StageResult and CandidateStagedResult

Both dataclasses have `to_dict()` for JSON serialization. `StageResult` captures per-stage outcome; `CandidateStagedResult` aggregates the full candidate journey through stages.

---

## Error Classification Rules

### Infra errors (repairable=False)

- `CUDA out of memory`, `torch.cuda.OutOfMemoryError`
- `No module named`, `ModuleNotFoundError`
- `FileNotFoundError`, `PermissionError`
- `python: command not found`, `DLL load failed`

### Code errors (repairable=True)

- `AttributeError`, `TypeError`, `ValueError`, `KeyError`, `IndexError`, `NameError`
- `ZeroDivisionError`
- References to `__calculate_reward`, `reward`

### Timeout

- `timeout`, `timed out` → `RUNTIME_TIMEOUT`

### Generic crash

- `traceback` → `TRAIN_CRASH`

---

## Smoke Train Definition

`run_smoke_train()` runs training with `max_steps = min(500, config.execution.max_steps // 20)`.

| Outcome | Decision |
|---------|----------|
| Training completes (returncode=0) | `PASS` |
| Infra error detected | `INFRA_FAILED` (or `REJECT_CATASTROPHIC` if `reject_on_infra_failure`) |
| Code error detected | `REPAIR` |
| Timeout | `RUNTIME_TIMEOUT` |

**Does NOT evaluate performance** — poor metrics are not a rejection reason.

---

## Short Train Screening Policy

`evaluate_short_train(metrics_by_seed, baseline_metrics, policy) -> StageDecision`

| Condition | Decision |
|-----------|----------|
| All seeds crash/empty | `REJECT_CATASTROPHIC` |
| All seeds have zero reward | `REJECT_CATASTROPHIC` |
| At least one seed succeeds with non-zero metrics | `PROMOTE` |

**Never rejects** based on a single seed's poor reward, tracking_error, or fall_rate. RL early episodes are inherently unstable.

---

## Medium Train Screening Policy

`evaluate_medium_train(metrics_by_seed, baseline_metrics, policy) -> StageDecision`

| Condition | Decision |
|-----------|----------|
| All seeds crash/empty | `REJECT_CATASTROPHIC` |
| Too few seeds (< min_seeds_for_decision) | `NEEDS_MORE_SEEDS` |
| High variance (CV > threshold) | `NEEDS_MORE_SEEDS` |
| Otherwise | `PROMOTE` |

---

## Config

### StagedEvaluationConfig

```python
class StagedEvaluationConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = False
    max_static_repair_attempts: int = 3
    max_runtime_repair_attempts: int = 2
    smoke_train_enabled: bool = True
    short_train_enabled: bool = False
    medium_train_enabled: bool = False
    reject_on_infra_failure: bool = False
    uncertainty_policy: str = "conservative"
```

### default.yaml

```yaml
staged_evaluation:
  enabled: false
  max_static_repair_attempts: 3
  max_runtime_repair_attempts: 2
  smoke_train_enabled: true
  short_train_enabled: false
  medium_train_enabled: false
  reject_on_infra_failure: false
  uncertainty_policy: conservative
```

---

## CLI Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--staged-eval` | flag | False | Enable staged evaluation pipeline |
| `--max-static-repair-attempts` | int | 3 | Max static repair attempts |
| `--max-runtime-repair-attempts` | int | 2 | Max runtime repair attempts |
| `--short-train/--no-short-train` | bool | None | Enable/disable short train screening |

Priority chain: CLI > config > default.

---

## Executor Integration

Three injection points inside `_execute_optimizer_phase`, all gated by `if use_staged:`.

### Setup (after optimizer init)

```python
use_staged = should_use_staged_eval(config)
staged_cfg = get_staged_config(config) if use_staged else {}
```

### Injection Point 1: After compilation auto-fix, before training loop

Smoke train stage with `run_smoke_train()`. Rejects on infra failure if configured.

### Injection Point 2: Training failure handling

Classifies error with `classify_failure()` before `_fix_training_error()`. Skips LLM repair for infra errors.

### Injection Point 3: Before full eval

Short train screening with `evaluate_short_train()`. Promotes/rejects/defers based on training metrics.

---

## Observability

### New events (via `observer.emit()`)

- `staged_eval_start`, `staged_eval_end`
- `staged_smoke_train_start`, `staged_smoke_train_end`
- `staged_runtime_repair_start`, `staged_runtime_repair_end`
- `staged_short_train_start`, `staged_short_train_end`
- `staged_candidate_final_decision`

### New summary counters

- `staged_eval_enabled`
- `staged_total_stages_run`
- `staged_static_repairs`, `staged_runtime_repairs`
- `staged_smoke_rejected`, `staged_infra_failures`
- `staged_short_train_promoted`, `staged_short_train_deferred`

---

## Test Results

```
compileall: All modules compile
test_staged_evaluation.py:      26 passed
test_repair_policy.py:          20 passed
test_langgraph_reward_agent.py: 46 passed
test_observability.py:          22 passed
test_reward_method_pool.py:     28 passed
test_eval_diagnostics.py:       42 passed
Full suite:                    250 passed, 1 pre-existing failure
```

| Suite | Tests | Status |
|-------|-------|--------|
| test_staged_evaluation.py | 26 | All pass |
| test_repair_policy.py | 20 | All pass |
| test_langgraph_reward_agent.py | 46 | All pass |
| test_observability.py | 22 | All pass |
| test_reward_method_pool.py | 28 | All pass |
| test_eval_diagnostics.py | 42 | All pass |
| test_dual_env_smoke.py | 8 | All pass |
| test_patch_and_optimizers.py | 27 | All pass |
| Other tests | 31 | All pass (1 pre-existing Windows path issue in test_smoke.py) |

---

## Mock Smoke Test

```
conda run -n langgraph python run_optimizer.py \
  --project D:/research-agent/HRRL2 \
  --optimizer reward_langgraph \
  --mock-llm --max-iterations 1 --batch-size 1 \
  --execution-python E:/Anaconda/envs/RL2/python.exe \
  --staged-eval --no-short-train
```

| Check | Result |
|-------|--------|
| run_id | `20260615_124133_reward_langgraph_de1936` |
| CLI options parsed | Yes |
| No real LLM calls | Correct (mock mode) |
| summary.json staged_eval fields | Present (zero defaults — optimizer phase not entered) |
| Baseline hash | `5ffc1e934e1f8908` (unchanged) |

**Note:** The optimizer phase was never entered because the PaperSampler reported all methods as already tried (HRRL2 has 214 entries from prior runs). This is expected — the staged evaluation only activates when candidates are actually proposed inside `_execute_optimizer_phase`.

---

## Baseline Hash

```
5ffc1e934e1f8908
```

Unchanged from v0.1 through v0.5.

---

## Full Eval Fairness Protocol

- [x] No changes to scoring logic (`scoring.py` untouched)
- [x] No changes to seed selection (`full_eval_seeds` untouched)
- [x] No changes to accept/reject logic in `make_accept_decision`
- [x] No changes to baseline restoration
- [x] Staged evaluation is purely additive — early filtering before full eval
- [x] `full_eval_candidate` on BaseOptimizer unchanged

---

## Known Limitations

1. **Optimizer phase not entered in mock smoke test** — HRRL2's tried_methods.jsonl has 214 entries, so PaperSampler reports all methods as tried. The staged eval injection points are inside `_execute_optimizer_phase` and were never reached. Same limitation as v0.4.
2. **Smoke train calls `run_train()`** — requires `execution/experiment_runner.py` to be importable. If the runner has project-specific dependencies, smoke train may fail with import errors (classified as infra error).
3. **Short train disabled by default** — `short_train_enabled: false` in default config. Must be explicitly enabled via CLI (`--short-train`) or config.
4. **No medium train implementation** — `evaluate_medium_train()` is implemented in `policy.py` but no executor injection point exists yet. The medium train stage is defined but not wired into the pipeline.

---

## Next Steps (v0.6 suggestions)

1. Wire medium train stage into executor injection point 3
2. Candidate-level staged result tracking (which stages each candidate passed)
3. Adaptive smoke train step count based on project complexity
4. Staged evaluation dashboard in run summary
5. Repair effectiveness logging (which repairs succeeded, which patterns are hardest)
