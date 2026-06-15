# Reward LangGraph v0.4 — Reward Method Pool Integration

**Date:** 2026-06-15
**Branch:** `reward-langgraph-v0.4-method-pool`

---

## Summary

Formalized the reward method pool integration: schema, loader, selector, formatter, and LLM prompt injection. Candidates now receive structured method context from the 142-method pool (8 taxonomy categories) when proposing reward modifications.

---

## v0.4 Goals

1. Formal `RewardMethodRecord` frozen dataclass mapping method_pool.jsonl fields
2. JSONL loader with validation and error tolerance
3. Category-based selector with confidence sorting, dedup, and top-k limiting
4. Rich formatter for LLM prompt injection
5. Integrate method pool into LangGraph reward agent via `{method_context}` prompt variable
6. CLI options `--reward-method-pool` and `--reward-method-top-k`
7. Observability tracking for method pool usage
8. Backward compatible — no method pool = existing behavior

---

## New Files (5)

| File | Purpose |
|------|---------|
| `research_agent/reward_methods/__init__.py` | Package exports |
| `research_agent/reward_methods/schema.py` | `RewardMethodRecord` frozen dataclass |
| `research_agent/reward_methods/loader.py` | `load_method_pool()` — JSONL loader with validation |
| `research_agent/reward_methods/selector.py` | `MethodSelector` — category filter, confidence sort, dedup, top-k |
| `research_agent/reward_methods/formatter.py` | `format_method_context()`, `format_method_brief()`, `build_source_meta_from_records()` |

## Modified Files (8)

| File | Change |
|------|--------|
| `research_agent/core/config.py` | Added `method_pool_path: str` and `method_top_k: int` to `OptimizerConfig` |
| `research_agent/agents/reward_agent/state.py` | Added `method_pool_context: str` and `method_pool_ids: list[str]` to `RewardAgentState` |
| `research_agent/agents/reward_agent/prompts.py` | Added `{method_context}` variable to `PROPOSE_USER_PROMPT` |
| `research_agent/agents/reward_agent/nodes.py` | `propose_node` reads `method_pool_context` from state, passes to prompt |
| `research_agent/agents/reward_agent/optimizer.py` | `propose_candidate()` accepts `method_pool` param, uses selector+formatter |
| `research_agent/core/executor.py` | Loads method pool in `_execute_optimizer_phase`, passes to optimizer; `_init_sampler` accepts pool path |
| `run_optimizer.py` | Added `--reward-method-pool` and `--reward-method-top-k` CLI options |
| `research_agent/core/observability.py` | Added `track_method_pool_usage()`, summary fields |

---

## Method Pool Schema

```python
@dataclass(frozen=True)
class RewardMethodRecord:
    method_id: str
    category: str                       # e.g., "A_potential_based_reward"
    method_name: str
    core_idea: str
    reward_formula: str
    implementation_template: str
    applicable_layers: tuple[str, ...]
    applicable_metrics: tuple[str, ...]
    risks: tuple[str, ...]
    confidence: str                     # "high" | "medium" | "low"
    source_papers: tuple[str, ...]
```

- Frozen dataclass (immutable)
- `from_dict()` tolerant of missing/extra fields
- `tuple` for list fields (hashable, immutable)

---

## Loader Behavior

`load_method_pool(pool_path: Path) -> list[RewardMethodRecord]`

- Reads JSONL line-by-line
- Skips blank lines, JSON parse errors, records with empty `method_id`
- Logs warnings for missing critical fields
- Returns empty list if file does not exist (not an error)
- Loads 142 methods from the real pool with all 8 categories

---

## Selector Rules

`MethodSelector.select(categories, top_k, exclude_ids)`

1. Filter to specified categories (or all if None)
2. Exclude already-tried method IDs
3. Sort by confidence (high > medium > low), then category
4. Deduplicate by `method_id` (keep first occurrence)
5. Return top_k results

---

## Formatter / Prompt Injection

### format_method_context (rich)

```
[A_potential_based_reward] Potential-Based Reward Shaping (confidence: high)
  Core idea: Use potential differences as shaping term.
  Formula: gamma * Phi(s_next) - Phi(s)
  Implementation: tracking_improvement = abs(e_t) - abs(e_t1); reward += k_phi * tracking_improvement
  Applicable layers: stanley_residual, path_tracking
  Applicable metrics: tracking_error, heading_error
  Risks: reward hacking if proxy metrics dominate task success
```

### format_method_brief (compact)

```
  [A] Potential-Based Reward Shaping: gamma * Phi(s') - Phi(s) | layers: stanley_residual, path_tracking
```

### Prompt injection

`PROPOSE_USER_PROMPT` now includes:

```
Method pool context (reference methods from literature):
{method_context}
```

The `{method_context}` variable is populated by `format_method_context()` when a method pool is provided, or empty string when not.

---

## source_meta Example

```json
{
  "source_method_ids": ["a_potential_based_reward_openreview_hqwhxvzcmj", "b_safety_penalty_xyz"],
  "source_categories": ["A_potential_based_reward", "B_safety_constraint_reward"],
  "source_papers": ["openreview:HqWHxvZCMJ", "openreview:xyz"],
  "method_pool_method_ids": ["test_pbrs_001", "test_risk_penalty_004"],
  "method_pool_categories": ["A_potential_based_reward", "B_safety_constraint_reward"]
}
```

---

## events.jsonl Example

```json
{"timestamp": "...", "run_id": "...", "event_type": "method_pool_loaded", "total_methods": 142, "categories": ["A_potential_based_reward", "B_safety_constraint_reward", ...], "pool_path": ".../method_pool.jsonl"}
```

---

## summary.json Example

```json
{
  "method_pool_total": 142,
  "method_pool_selected": 3,
  "method_pool_categories_used": ["A_potential_based_reward", "B_safety_constraint_reward", "D_adaptive_dynamic_reward"]
}
```

---

## CLI Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--reward-method-pool` | `click.Path()` | None | Path to method_pool.jsonl for rich context injection |
| `--reward-method-top-k` | `int` | 5 | Number of methods to inject as context |

Priority chain: CLI > config > default.

---

## Test Results

```
compileall: All modules compile
test_reward_method_pool.py:     28 passed
test_langgraph_reward_agent.py: 46 passed (1 pre-existing warning)
test_observability.py:          22 passed
Full suite:                    179 passed, 1 warning
```

| Suite | Tests | Status |
|-------|-------|--------|
| test_reward_method_pool.py | 28 | All pass |
| test_langgraph_reward_agent.py | 46 | All pass |
| test_observability.py | 22 | All pass |
| test_eval_diagnostics.py | 42 | All pass |
| test_dual_env_smoke.py | 8 | All pass |
| test_patch_and_optimizers.py | 27 | All pass |
| Other tests | 6 | All pass |

### Warning

```
LangChainPendingDeprecationWarning: The default value of `allowed_objects` will change in a future version.
```

Pre-existing from langgraph library. Non-blocking.

---

## Method Pool Mock Smoke Test

```
conda run -n langgraph python run_optimizer.py \
  --project D:/research-agent/HRRL2 \
  --optimizer reward_langgraph \
  --mock-llm --max-iterations 1 --batch-size 1 \
  --execution-python E:/Anaconda/envs/RL2/python.exe \
  --reward-method-pool D:/research-agent/.research-agent/test_method_pool/method_pool.jsonl \
  --reward-method-top-k 3
```

| Check | Result |
|-------|--------|
| run_id | `20260615_113623_reward_langgraph_2fcfab` |
| CLI options parsed | Yes |
| No real LLM calls | Correct (mock mode) |
| Mock empty patch rejected | Expected (sampler exhausted) |
| summary.json method_pool_* fields | Present (zero defaults — optimizer phase not entered) |
| Baseline hash | `5ffc1e934e1f8908` (unchanged) |

**Note:** The optimizer phase was never entered because the PaperSampler reported all methods as already tried (the HRRL2 project has been used in prior mock runs). This is expected behavior — the method pool integration only activates when candidates are actually proposed inside `_execute_optimizer_phase`.

---

## Baseline Hash

```
5ffc1e934e1f8908
```

Unchanged from v0.1 through v0.4.

---

## Full Eval Fairness Protocol

- [x] No changes to scoring logic
- [x] No changes to seed selection
- [x] No changes to accept/reject logic
- [x] No changes to baseline restoration
- [x] Method pool is purely additive context for LLM proposals
- [x] BaseOptimizer.full_eval_candidate still inherited unchanged

---

## Known Limitations

1. **Mock smoke test doesn't exercise method pool path** — The HRRL2 project's sampler has exhausted all methods from prior runs, so `_execute_optimizer_phase` is never entered. The method pool loading and injection are only covered by unit tests.
2. **`--reward-method-pool` expects file path** — The CLI option expects the full path to `method_pool.jsonl`, not a directory. Users must include the filename.
3. **Method pool loaded per-phase, not per-candidate** — The method pool is loaded once at the start of `_execute_optimizer_phase` and the same set is passed to all candidates in that phase. Dynamic pool changes during a run are not supported.
4. **No prompt token budget management** — `format_method_context()` includes all fields. If `top_k` is large, the prompt could exceed the LLM context window. The `format_method_brief()` compact formatter is available but not used by default.

---

## Next Steps (v0.5 suggestions)

1. Candidate-level method pool tracking (which methods were injected per candidate)
2. Dynamic method pool refresh between candidates
3. Prompt token budget management (auto-switch to brief format when context is tight)
4. Method effectiveness logging (which methods led to accepted candidates)
5. Per-category method selection strategies (not just confidence-based)
