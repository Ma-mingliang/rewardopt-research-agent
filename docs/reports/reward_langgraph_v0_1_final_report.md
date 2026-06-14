# reward_langgraph v0.1 Final Report

Date: 2026-06-14
Commit: `83abf0e`
Tag: `reward-langgraph-v0.1`
Status: **COMPLETE — all tests passed, baseline integrity verified**

---

## 1. Summary

v0.1 将 `RewardOptimizer.propose_candidate()` 循环重构为 LangGraph `StateGraph` 代理，实现严格的双环境架构：

- **LangGraph 环境** (`E:\Anaconda\envs\langgraph\python.exe`)：仅负责代理编排、状态图、LLM 调用、节点路由
- **执行 Python 环境** (`E:\Anaconda\envs\RL2\python.exe`)：所有 train/eval/compile/smoke test/patch validation 在此运行

v0.1 已完成并通过全部测试。

---

## 2. 核心验收结果

| 验证项 | 结果 |
|--------|------|
| agent_python | `E:\Anaconda\envs\langgraph\python.exe` |
| execution_python | `E:\Anaconda\envs\RL2\python.exe` |
| fallback_used | `False` |
| optimizer | `reward_langgraph` |
| pytest 专用测试 (36 tests) | 36/36 passed |
| pytest 双环境 smoke (8 tests) | 8/8 passed |
| pytest 回归测试 (54 tests) | 54/54 passed |
| **pytest 总计** | **98/98 passed** |
| mock smoke test | 通过（empty patch 在训练前被正确拒绝） |
| HRRL2/env.py SHA256 前后一致 | **YES** (`5ffc1e93...442e6a`) |
| `full_eval_candidate` 是否被覆盖 | **否** — 继承自 `BaseOptimizer`，协议未改变 |
| dual-env 日志确认 | agent_python / execution_python / fallback_used 均正确输出 |

---

## 3. 架构

```
LangGraph StateGraph:
  START -> initialize -> propose -> validate -> {should_continue_or_return}
      |-> "return" -> return_candidate -> END
      |-> "try_auto_indent" -> auto_indent -> validate
      |-> "llm_fix" -> llm_fix -> validate

双环境隔离：
  Agent Python (langgraph env):   LLM 调用、状态图编排
  Execution Python (RL2 env):     compile、AST check、train、eval、validate_patch
```

---

## 4. 文件清单

### 4.1 新增文件（14 个）

| # | 文件 | 用途 |
|---|------|------|
| 1 | `research_agent/core/execution_env.py` | 双环境抽象：ExecutionEnv、resolve_execution_env、run_python_compile、resolve_command |
| 2 | `research_agent/optimizers/reward/reward_patch_utils.py` | 8 个无状态工具函数，从 RewardOptimizer 提取 |
| 3 | `research_agent/agents/__init__.py` | 空包 |
| 4 | `research_agent/agents/reward_agent/__init__.py` | 空包 |
| 5 | `research_agent/agents/reward_agent/state.py` | RewardAgentState TypedDict |
| 6 | `research_agent/agents/reward_agent/prompts.py` | 提示词：PROPOSE / FIX / EMPTY_DIFF_RETRY |
| 7 | `research_agent/agents/reward_agent/tools.py` | 无状态工具：validate_patch（temp-dir 隔离）、read_reward_code |
| 8 | `research_agent/agents/reward_agent/nodes.py` | 6 个图节点函数 |
| 9 | `research_agent/agents/reward_agent/edges.py` | 条件路由：should_continue_or_return |
| 10 | `research_agent/agents/reward_agent/graph.py` | build_reward_proposal_graph()，带 @lru_cache |
| 11 | `research_agent/agents/reward_agent/optimizer.py` | LangGraphRewardOptimizer（继承 BaseOptimizer） |
| 12 | `tests/test_langgraph_reward_agent.py` | 36 个专用测试 |
| 13 | `tests/test_dual_env_smoke.py` | 8 个双环境 smoke 测试 |
| 14 | `docs/reports/reward_langgraph_v0_1_smoke_report.md` | smoke test 报告 |

### 4.2 修改文件（7 个）

| # | 文件 | 修改内容 |
|---|------|----------|
| 1 | `pyproject.toml` | 新增 `[project.optional-dependencies] langgraph` |
| 2 | `research_agent/core/config.py` | ExecutionConfig 新增 `python_executable: str = ""` |
| 3 | `research_agent/optimizers/__init__.py` | 注册 `"reward_langgraph"` |
| 4 | `research_agent/optimizers/base.py` | BaseOptimizer 新增 `execution_python` 参数，`full_eval_candidate` 透传 |
| 5 | `research_agent/core/executor.py` | `_execute_optimizer_phase` 透传 `execution_python` 到 optimizer 和 train/eval |
| 6 | `research_agent/execution/experiment_runner.py` | `run_train`/`run_eval`/`run_full_eval`/`_run_subprocess` 新增 `python_executable` 参数，解析 `{python}` 占位符 |
| 7 | `research_agent/optimizers/reward/optimizer.py` | 7 个私有方法替换为 `reward_patch_utils` 导入，零行为变更 |

---

## 5. 验证记录

### 5.1 单元测试

```
tests/test_langgraph_reward_agent.py    36 passed
tests/test_dual_env_smoke.py             8 passed
tests/test_patch_and_optimizers.py      54 passed
---------------------------
Total                                   98/98 passed
```

### 5.2 关键测试覆盖

1. Graph 编译和缓存
2. State 默认值（无 KeyError）
3. 路由：validation_ok / max_attempts / indent error / normal error / total_llm_calls
4. ExecutionEnv 从 CLI、config、fallback 三种路径解析
5. 无效 execution_python 快速失败（FileNotFoundError）
6. Patch 隔离验证（baseline hash 不变）
7. Temp-only patching（temp dir 清理）
8. train/eval 命令解析（`{python}` -> execution_python）
9. `run_eval`/`run_full_eval` 透传 `python_executable`
10. 注册表：reward_langgraph 已注册，reward 向后兼容
11. full_eval_candidate 协议未变（继承自 BaseOptimizer）

### 5.3 Mock Smoke Test

```
Command: python run_optimizer.py --project D:/research-agent/HRRL2 --mock-llm --max-iterations 1 --batch-size 1 --execution-python E:/Anaconda/envs/RL2/python.exe

Result:
  candidate_id = reward_langgraph_c001
  status = REJECTED
  rejection reason = empty patch rejected before training
  mode = mock-llm（无真实 LLM 调用）
  train/eval command = E:/Anaconda/envs/RL2/python.exe .research-agent/train.py {seed}
```

### 5.4 Baseline SHA256

| 时机 | Hash |
|------|------|
| 运行前 | `5ffc1e934e1f8908d0c093bc121c15cd2db6cf54d140958176583c205a442e6a` |
| 运行后 | `5ffc1e934e1f8908d0c093bc121c15cd2db6cf54d140958176583c205a442e6a` |
| 一致 | **YES** |

---

## 6. v0.1 限制（已知）

| # | 限制 | 说明 |
|---|------|------|
| 1 | Mock run 仅验证工程链路 | `--mock-llm` 模式不调用真实 LLM，未验证真实优化能力 |
| 2 | Empty patch 被拒绝是正确行为 | mock 模式不生成实际 diff，propose 返回空 patch，在训练前被 reject |
| 3 | CLI 无 `--optimizer` 参数 | 当前 `run_optimizer.py` 没有 `--optimizer` 命令行选项 |
| 4 | Optimizer 由 experiment_plan.json 决定 | 选择哪个 optimizer 运行取决于 `experiment_plan.json` 中的 phase config，不能通过 CLI 覆盖 |
| 5 | 真实 full_eval 未验证 | 未在真实 LLM + 真实 train/eval 流程下运行 reward_langgraph |
| 6 | PaperSampler 耗尽 | HRRL2 项目有 214 个已尝试方法，smoke test 前需临时清空 `tried_methods.jsonl` |

如需使用 `reward_langgraph`，需要：
- 临时修改 `experiment_plan.json` 中对应 phase 的 optimizer 为 `"reward_langgraph"`，或
- 等后续版本增加 `--optimizer` CLI override

---

## 7. 后续版本规划

### v0.2

- **`--optimizer` CLI override**：在 `run_optimizer.py` 增加 `--optimizer` 参数，允许命令行覆盖 experiment_plan.json 中的 optimizer 选择
- **结构化运行日志**：每个 LangGraph node 输出结构化日志（candidate_id、attempt、total_llm_calls、validation_error、patch_status）
- **Run summary JSON**：每次运行保存 run summary 到 `work_dir/logs/run_summary_{timestamp}.json`
- **拒绝阶段记录**：明确记录 candidate 被拒绝的阶段：`empty_diff` / `validation_failed` / `train_failed` / `eval_failed` / `metrics_empty`

### v0.3

- **真实 full_eval 诊断**：专门诊断 `full_eval_result` 中 `metrics={}` + `failed=true` 的根因
- **失败信息持久化**：`full_eval_result` 为空时，保存 stdout/stderr 和失败原因到日志
- **不修改 full eval 协议**：仅增加诊断信息，不改变评估逻辑

### v0.4

- **接入 reward paper/method pool**：对接 `PaperSampler` 和 `reward_papers.jsonl`，使用论文驱动的方法选择
- **真实 LLM 优化验证**：在真实 LLM 模式下完成至少 1 次完整 propose → validate → train → eval 流程

---

## 8. 验证命令（参考）

```bash
# 环境准备
conda activate langgraph
pip install -e ".[langgraph]"

# 导入检查
python -c "import langgraph; print(langgraph.__version__)"

# 单元测试
python -m pytest tests/test_langgraph_reward_agent.py -v

# 回归测试
python -m pytest tests/ -v

# Mock smoke test（需先确保 experiment_plan.json 中 optimizer 为 reward_langgraph）
python run_optimizer.py \
  --project D:/research-agent/HRRL2 \
  --mock-llm \
  --max-iterations 1 \
  --batch-size 1 \
  --execution-python E:/Anaconda/envs/RL2/python.exe

# 验证 baseline 不变
# 运行前后对比 HRRL2/env.py SHA256
```

注意：当前 CLI 没有 `--optimizer` 参数。optimizer 选择由 `experiment_plan.json` 的 phase config 决定。
