# reward_langgraph v0.1 Smoke Report

Date: 2026-06-14

## Summary

Verified dual-environment LangGraph reward optimizer (`reward_langgraph`) as v0.1 stable baseline.
All project code execution (compile, AST check, train, eval) uses `execution_python`, never the agent's own Python.

## Test Environment

| Item | Value |
|------|-------|
| agent_python | `E:\Anaconda\envs\langgraph\python.exe` (Python 3.11.15, langgraph 0.6.11) |
| execution_python | `E:\Anaconda\envs\RL2\python.exe` |
| project | `D:/research-agent/HRRL2` |

## Minimal Real Run

### Command

```
python run_optimizer.py --project D:/research-agent/HRRL2 --mock-llm --max-iterations 1 --batch-size 1 --execution-python E:/Anaconda/envs/RL2/python.exe
```

### Dual-Environment Confirmation (from log)

| Item | Value |
|------|-------|
| agent_python | `E:\Anaconda\envs\langgraph\python.exe` |
| execution_python | `E:\Anaconda\envs\RL2\python.exe` |
| fallback_used | `False` |
| optimizer | `reward_langgraph` |
| project_path | `D:\research-agent\HRRL2` |

### Candidate

| Item | Value |
|------|-------|
| candidate_id | `reward_langgraph_c001` |
| status | `REJECTED` |
| rejection reason | `empty patch rejected before training` |
| mode | mock-llm (no real LLM calls) |

### Train/Eval Command (from log)

```
E:/Anaconda/envs/RL2/python.exe .research-agent/train.py {seed}
```

Confirmed: `{python}` resolved to RL2 execution Python, not langgraph agent Python.

### Full Eval

Not run -- empty patch rejected before training (correct behavior: mock mode produces no-op candidate).

### Baseline SHA256

| | Hash |
|---|---|
| Before | `5ffc1e934e1f8908d0c093bc121c15cd2db6cf54d140958176583c205a442e6a` |
| After | `5ffc1e934e1f8908d0c093bc121c15cd2db6cf54d140958176583c205a442e6a` |
| Match | **YES** |

## Unit Test Results

| Suite | Result |
|-------|--------|
| reward_langgraph dedicated (36 tests) | 36/36 passed |
| dual-env smoke (8 tests) | 8/8 passed |
| regression (54 tests) | 54/54 passed |
| **Total** | **98/98 passed** |

### Key Tests Verified

1. Graph compilation and caching
2. State defaults (no KeyError)
3. Routing: validation_ok, max_attempts, indent error, normal error, total_llm_calls
4. ExecutionEnv resolve from CLI, config, fallback
5. Invalid execution_python fails fast (FileNotFoundError)
6. Patch validation isolation (baseline hash unchanged)
7. Temp-only patching (temp dir cleaned up)
8. train/eval command resolution ({python} -> execution_python)
9. run_eval/run_full_eval forward python_executable
10. Registry: reward_langgraph registered, reward backward compat
11. Full eval protocol unchanged (inherited from BaseOptimizer)

## Architecture

```
LangGraph StateGraph:
  START -> initialize -> propose -> validate -> {should_continue_or_return}
      |-> "return" -> return_candidate -> END
      |-> "try_auto_indent" -> auto_indent -> validate
      |-> "llm_fix" -> llm_fix -> validate

Dual-Environment:
  Agent Python (langgraph env): LLM calls, state graph orchestration
  Execution Python (RL2 env): compile, AST check, train, eval, validate_patch
```

## Files Created/Modified

### New Files (12)
- `research_agent/core/execution_env.py` -- Dual-environment abstraction
- `research_agent/optimizers/reward/reward_patch_utils.py` -- Shared stateless utils
- `research_agent/agents/__init__.py`
- `research_agent/agents/reward_agent/__init__.py`
- `research_agent/agents/reward_agent/state.py` -- RewardAgentState TypedDict
- `research_agent/agents/reward_agent/prompts.py` -- Prompt strings
- `research_agent/agents/reward_agent/tools.py` -- Stateless tools (validate_patch)
- `research_agent/agents/reward_agent/nodes.py` -- Graph node functions
- `research_agent/agents/reward_agent/edges.py` -- Conditional routing
- `research_agent/agents/reward_agent/graph.py` -- StateGraph builder
- `research_agent/agents/reward_agent/optimizer.py` -- LangGraphRewardOptimizer
- `tests/test_langgraph_reward_agent.py` -- 36 dedicated tests

### Modified Files (7)
- `pyproject.toml` -- Added `[project.optional-dependencies] langgraph`
- `research_agent/core/config.py` -- Added `python_executable` to ExecutionConfig
- `research_agent/optimizers/__init__.py` -- Registered `"reward_langgraph"`
- `research_agent/optimizers/base.py` -- Added `execution_python` to BaseOptimizer
- `research_agent/core/executor.py` -- Threads `execution_python` through all calls
- `research_agent/execution/experiment_runner.py` -- Added `python_executable` param, resolves `{python}`
- `run_optimizer.py` -- Added `--execution-python` CLI option
