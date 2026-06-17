# Reward LangGraph v0.6 — Real-run Validation and Closed-loop Diagnostics

**Date:** 2026-06-15
**Branch:** `reward-langgraph-v0.6-real-run-validation`
**Commit:** `20c9075` (feat: add repair-first staged evaluation pipeline)

---

## v0.6 目标

不继续堆新功能，而是用真实 LLM 小规模验证 reward_langgraph v0.1–v0.5 的完整闭环。重点观察真实 candidate 是否能生成非空 patch、是否能通过 validation、是否触发 repair loop、是否能进入 smoke train、如果失败是否能给出明确 diagnostics。

---

## Mock Baseline Run

| Item | Value |
|------|-------|
| run_id | `20260615_140649_reward_langgraph_13bcad` |
| mock_llm | true |
| staged_eval_enabled | true |
| method_pool_total | 5 |
| method_pool_categories_used | A_potential_based_reward, B_safety_constraint_reward, C_curriculum_subgoal_reward, D_adaptive_dynamic_reward |
| candidates_total | 1 |
| candidate_id | `reward_langgraph_c001` |
| has_diff | false |
| rejection_reason | empty_patch |
| staged_total_stages_run | 0 |
| duration_ms | 2561 |
| baseline_hash | `5ffc1e934e1f8908` (unchanged) |

**Events confirmed:** `staged_eval_start`, `method_pool_loaded`, `propose_candidate`, `candidate_created`, `candidate_rejected`, `iteration_end`, `run_end`

---

## Real LLM Run

### Command

```bash
conda run -n langgraph python run_optimizer.py \
  --project D:/research-agent/HRRL2 \
  --optimizer reward_langgraph \
  --max-iterations 1 \
  --batch-size 1 \
  --execution-python E:/Anaconda/envs/RL2/python.exe \
  --reward-method-pool D:/research-agent/.research-agent/test_method_pool/method_pool.jsonl \
  --reward-method-top-k 3 \
  --staged-eval \
  --max-static-repair-attempts 3 \
  --max-runtime-repair-attempts 2 \
  --no-short-train
```

Note: `--mock-llm` was NOT passed. The system was configured for real LLM.

### Results

| Item | Value |
|------|-------|
| run_id | `20260615_140929_reward_langgraph_5691da` |
| events.jsonl | `D:/research-agent/HRRL2/.research-agent/runs/20260615_140929_reward_langgraph_5691da/events.jsonl` |
| summary.json | `D:/research-agent/HRRL2/.research-agent/runs/20260615_140929_reward_langgraph_5691da/summary.json` |
| agent_python | `E:\Anaconda\envs\langgraph\python.exe` |
| execution_python | `E:/Anaconda/envs/RL2/python.exe` |
| fallback_used | false |
| optimizer | reward_langgraph |
| method_pool_enabled | true (5 methods, 4 categories) |
| method_pool_selected_ids | none (candidate rejected before selection) |
| staged_eval_enabled | true |
| candidate_id | `reward_langgraph_c001` |
| candidate_generated | true (noop/mock fallback) |
| patch_empty | true |
| patch_lines | 0 |
| validation_passed | n/a (rejected before validation) |
| static_repair_triggered | false |
| static_repair_attempts | 0 |
| smoke_train_triggered | false |
| runtime_repair_triggered | false |
| runtime_repair_attempts | 0 |
| short_train_closed | true (disabled via --no-short-train) |
| full_eval_triggered | false |
| failure_type | n/a |
| rejection_reason | empty_patch |
| diagnostics | n/a (rejected before training) |
| llm_calls_total | 0 |
| duration_ms | 2483 |
| token/cost_estimate | 0 tokens, $0.00 |

---

## Key Finding: MIMO_API_KEY Not Available

The real LLM run printed:
```
[WARNING] MIMO_API_KEY not set. LLM calls will fail.
[OK] Using mock-llm mode
```

**Root cause:** `MIMO_API_KEY` is set in the shell but is **empty** (length=0). The `.env` file at `D:/research-agent/.env` contains the actual key, but `run_optimizer.py` does not load `.env` files — it reads `os.environ.get("MIMO_API_KEY", "")` directly.

**Impact:** The system correctly detected the empty API key and fell back to mock mode, generating a no-op candidate with empty patch. No real LLM calls were made.

**Resolution:** Before a real LLM run, the user must either:
1. `export MIMO_API_KEY=<your_api_key>` in the shell before running
2. Or add `python-dotenv` loading to `run_optimizer.py`

This is documented as a known limitation, not a code bug — the system handled it gracefully.

---

## Result Classification

**E. real_llm_call_failed**

The LLM could not be called because `MIMO_API_KEY` is empty in the environment. The system correctly fell back to mock mode. No real candidate was generated.

---

## Baseline Hash

| Checkpoint | Hash |
|------------|------|
| Before runs | `5ffc1e934e1f8908d0c093bc121c15cd2db6cf54d140958176583c205a442e6a` |
| After runs | `5ffc1e934e1f8908d0c093bc121c15cd2db6cf54d140958176583c205a442e6a` |
| Match | ✓ |

---

## Full Eval Fairness Protocol

- [x] No changes to scoring logic
- [x] No changes to seed selection
- [x] No changes to accept/reject logic
- [x] No changes to baseline restoration
- [x] No changes to baseline hash
- [x] Full eval was never triggered (candidate rejected before training)

---

## Test Results

```
test_langgraph_reward_agent.py: 46 passed
test_observability.py:          22 passed
test_eval_diagnostics.py:       42 passed
test_staged_evaluation.py:      26 passed
test_repair_policy.py:          20 passed
Total:                         156 passed, 1 warning
```

No code changes were made in v0.6 — only report generation.

---

## 发现的问题

1. **MIMO_API_KEY 不可用** — `conda run` 环境中 `MIMO_API_KEY` 为空。`.env` 文件存在但未被加载。系统正确回退到 mock 模式。
2. **tried_methods.jsonl 需要手动清空** — HRRL2 的 tried_methods.jsonl 有 214 条记录，PaperSampler 报告所有方法已尝试。需要临时清空才能进入 optimizer phase。
3. **staged_eval stages 未被触发** — 因为 candidate 在到达 staged eval 阶段之前就被拒绝了（empty patch）。真实 LLM 生成非空 patch 后才能验证 staged eval 完整流程。

---

## 是否建议继续 v0.6.1 修复

**否** — 当前问题不需要代码修复：
- MIMO_API_KEY 需要用户在运行前设置（环境配置问题，非代码 bug）
- tried_methods.jsonl 的清空是已知的测试限制（同 v0.4）
- staged eval 未触发是因为没有真实 candidate（需要真实 LLM）

---

## v0.7 建议

1. **真实 LLM 验证** — 设置 MIMO_API_KEY 后重新运行，验证完整 propose→validate→smoke_train→full_eval 闭环
2. **dotenv 支持** — 在 run_optimizer.py 中添加 `python-dotenv` 自动加载 `.env` 文件
3. **自动 tried_methods 管理** — 考虑 PaperSampler 支持 "force re-try" 模式，避免手动清空
4. **staged eval 集成测试** — 用 fixture mock LLM 返回非空 patch，验证 staged eval 完整流程
5. **Token/cost tracking** — 在 LLM client 中添加 token 计数和成本估算
