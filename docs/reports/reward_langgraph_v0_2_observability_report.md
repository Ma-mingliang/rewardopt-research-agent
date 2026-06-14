# Reward LangGraph v0.2 — Observability Report

**Date:** 2026-06-15
**Branch:** `reward-langgraph-v0.2-observability`
**Commit:** `5ab25f2`

---

## Summary

Added structured observability to the LangGraph reward optimizer: per-node event logging, run summary JSON, CLI optimizer override, and full test coverage.

---

## What Changed

### New Files (2)

| File | Purpose |
|------|---------|
| `research_agent/core/observability.py` | RunObserver class — events.jsonl + summary.json |
| `tests/test_observability.py` | 13 unit tests for RunObserver |

### Modified Files (6)

| File | Change |
|------|--------|
| `run_optimizer.py` | `--optimizer` and `--run-log-dir` CLI options; observer lifecycle |
| `research_agent/core/executor.py` | observer passthrough; candidate/train/eval event logging |
| `research_agent/core/metrics_utils.py` | Added `get_eval_metric_defs()` |
| `research_agent/agents/reward_agent/nodes.py` | All 6 nodes emit node_start/node_end events with duration_ms |
| `research_agent/agents/reward_agent/optimizer.py` | observer injection; passes observer through graph config |
| `tests/test_langgraph_reward_agent.py` | 7 new tests (observability integration + CLI override) |

---

## Test Results

```
56 passed, 1 warning in 24.62s
```

| Suite | Tests | Status |
|-------|-------|--------|
| test_observability.py | 13 | All pass |
| test_langgraph_reward_agent.py | 43 | All pass |

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
| run_id format | `20260615_002920_reward_langgraph_9053eb` |
| events.jsonl generated | Yes (3 events: run_start, optimizer_override, run_end) |
| summary.json generated | Yes |
| optimizer in summary | `reward_langgraph` |
| execution_python | `E:/Anaconda/envs/RL2/python.exe` |
| fallback_used | `false` |
| Baseline hash after run | `5ffc1e934e1f8908` (unchanged) |

---

## Observability Architecture

```
run_optimizer.py
  └─ RunObserver(run_log_dir, optimizer, project_path, ...)
       ├─ emit("run_start", ...)
       ├─ emit("iteration_start", ...)
       ├─ _execute_optimizer_phase(observer=observer)
       │    └─ optimizer.__init__(observer=observer)
       │         └─ graph.invoke(config={"observer": observer})
       │              ├─ initialize_node  → emit("node_start/end")
       │              ├─ propose_node     → emit("node_start/end")
       │              ├─ validate_node    → emit("node_start/end")
       │              ├─ auto_indent_node → emit("node_start/end")
       │              ├─ llm_fix_node     → emit("node_start/end")
       │              └─ return_candidate_node → emit("node_start/end")
       ├─ emit("candidate_created/rejected/train/eval", ...)
       ├─ emit("iteration_end", ...)
       └─ write_summary() → summary.json
```

### Events Emitted

| Event | Source | Key Fields |
|-------|--------|------------|
| `run_start` | run_optimizer.py | optimizer, project_path, mock_llm |
| `optimizer_override` | run_optimizer.py | original, override |
| `iteration_start/end` | run_optimizer.py | iteration, batch_size |
| `candidate_created` | executor | candidate_id, status |
| `candidate_rejected` | executor | rejection_reason |
| `candidate_train_start/end` | executor | candidate_id, duration_ms |
| `candidate_eval_start/end` | executor | candidate_id, duration_ms |
| `node_start/end` | nodes.py | node, candidate_id, attempt, duration_ms |
| `run_end` | run_optimizer.py | total_iterations, total_candidates |

### Summary JSON Fields

- `run_id`, `started_at`, `ended_at`, `duration_ms`
- `optimizer`, `agent_python`, `execution_python`, `fallback_used`
- `mock_llm`, `max_iterations`, `batch_size`
- `candidates_total`, `candidates_ready`, `candidates_rejected`
- `candidates_trained`, `candidates_eval_failed`, `metrics_empty_count`
- `llm_calls_total`, `rejection_reasons`
- `event_log` (always `"events.jsonl"`)

---

## Security

- API keys and secrets redacted to `<redacted>` in all events
- stdout/stderr truncated to 1000 chars + `"...<truncated>"` marker
- No secrets in events.jsonl or summary.json

---

## Prohibitions Honored

- [x] Did not pop stash
- [x] Did not modify reward strategy
- [x] Did not modify full eval protocol
- [x] Did not introduce new LLM provider
- [x] Did not run full real optimization
- [x] Did not mix autoconfig changes
- [x] Did not commit .claude/feishu-mcp-server/qq-mcp-server/
- [x] Did not move reward-langgraph-v0.1 tag
