# Reward LangGraph v0.6.1 — Real LLM Credential Preflight

**Date:** 2026-06-15
**Branch:** `reward-langgraph-v0.6-real-run-validation`
**Commit:** pending

---

## v0.6 为什么没有完成真实 LLM 验证

v0.6 的真实 LLM run 中，`MIMO_API_KEY` 在 shell 环境中存在但为空（length=0）。`conda run` 不加载 `.env` 文件，`run_optimizer.py` 也没有 `.env` 加载逻辑。系统检测到空 key 后静默回退到 mock 模式，导致 LLM 调用次数为 0。

---

## v0.6.1 做了什么

### 1. 轻量 .env loader

在 `research_agent/core/config.py` 中添加 `load_dotenv()` 函数：

- 默认查找 `[cwd/.env, repo_root/.env]`
- 只读取 `KEY=VALUE` 格式，跳过注释和空行
- **shell 非空值优先级高于 .env**
- shell 中存在但为空的变量 → .env 非空值可以覆盖
- 不引入新依赖（纯 stdlib）

### 2. Credential preflight

在 `run_optimizer.py` 的 `main()` 中，config 加载后、optimizer 执行前：

- 调用 `load_dotenv()` 加载 .env
- 当 `mock_llm=False` 时，检查 `MIMO_API_KEY` 是否非空
- 如果为空 → 快速失败，输出清晰错误消息
- 如果非空 → 打印 `key_present=True key_source=dotenv/shell_env key_length=N`

### 3. 移除静默 fallback

`executor.py` 中原来的行为：key 为空时自动切换到 mock 模式。
改为：key 为空时抛出 `RuntimeError`，不再静默降级。

---

## .env 加载策略

| 场景 | 行为 |
|------|------|
| shell `MIMO_API_KEY` 非空 | 使用 shell 值，不覆盖 |
| shell `MIMO_API_KEY` 为空，.env 非空 | 使用 .env 值 |
| shell 缺失，.env 非空 | 使用 .env 值 |
| shell 为空，.env 缺失 | mock_llm=False → 快速失败 |
| mock_llm=True | 不要求 key |

---

## API Key 泄露检查

- [x] `events.jsonl` 不包含完整 API key
- [x] `summary.json` 不包含完整 API key
- [x] stdout 只打印 `key_present`, `key_source`, `key_length`
- [x] executor 只打印 `MIMO_API_KEY=tp-s48jt...`（前 8 字符）

---

## 真实 LLM Run 结果

### 命令

```bash
conda run -n langgraph python run_optimizer.py \
  --project D:/research-agent/HRRL2 \
  --optimizer reward_langgraph \
  --max-iterations 1 --batch-size 1 \
  --execution-python E:/Anaconda/envs/RL2/python.exe \
  --reward-method-pool D:/research-agent/.research-agent/test_method_pool/method_pool.jsonl \
  --reward-method-top-k 3 \
  --staged-eval --max-static-repair-attempts 3 --max-runtime-repair-attempts 2 \
  --no-short-train
```

### Preflight 输出

```
[CREDENTIAL] key_present=True key_source=dotenv key_length=51
```

### Run 结果

| Item | Value |
|------|-------|
| run_id | `20260615_145102_reward_langgraph_bad594` |
| mock_llm | false |
| staged_eval_enabled | true |
| method_pool_total | 5 |
| candidate_id | `reward_langgraph_c001` |
| LLM 调用 | 3 次（3 retries，全部 401 Unauthorized） |
| 候选生成 | false（LLM 调用失败） |
| patch | n/a |
| validation | n/a |
| smoke_train | n/a |
| failure_type | `LLMCallError: 401 Unauthorized` |
| rejection_reason | n/a |
| duration_ms | 24281 |
| baseline_hash | `5ffc1e934e1f8908` (unchanged) |
| events.jsonl | `D:/research-agent/HRRL2/.research-agent/runs/20260615_145102_reward_langgraph_bad594/events.jsonl` |
| summary.json | `D:/research-agent/HRRL2/.research-agent/runs/20260615_145102_reward_langgraph_bad594/summary.json` |

### 关键发现

1. **Credential preflight 工作正常** — .env 加载成功，key 检测通过
2. **LLM 调用确实发起了** — `propose_node` 开始执行，实际向 MiMo gateway 发送了请求
3. **API key 过期/无效** — MiMo gateway 返回 `401 Unauthorized`
4. **系统正确失败** — 3 次重试后抛出 `LLMCallError`，没有静默回退
5. **baseline hash 未变** — 训练代码未被触及

---

## 结果分类

**E. real_llm_call_failed**

API key 存在但被服务器拒绝（401 Unauthorized）。Credential preflight 正确检测到 key 存在，LLM 调用确实发起了，但 key 已过期或无效。

---

## 测试结果

```
test_credential_preflight.py: 8 passed
Full suite:                  258 passed, 1 pre-existing failure
```

---

## 是否建议继续 v0.7

**是，但需要先解决 API key 问题：**

1. **API key 需要更新** — `.env` 中的 `MIMO_API_KEY` 已过期。用户需要提供新的有效 key。
2. **Credential preflight 已就绪** — 新的 .env 加载和 preflight 机制已实现，下次运行时会自动加载 .env。
3. **完整闭环验证待完成** — 需要有效 API key 才能验证 propose→validate→smoke_train→full_eval 完整流程。

### v0.7 建议

1. 更新 `.env` 中的 `MIMO_API_KEY` 为有效 key
2. 重新执行真实 LLM 最小 run
3. 观察 candidate 是否生成非空 patch
4. 验证 staged eval 完整流程（static validation → smoke train → short train）
5. 考虑添加 token/cost tracking
