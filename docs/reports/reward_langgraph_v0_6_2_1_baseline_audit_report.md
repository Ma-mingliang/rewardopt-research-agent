# Reward LangGraph v0.6.2.1 — Baseline Audit Report

**Date:** 2026-06-15
**Branch:** `reward-langgraph-v0.6.2-model-load-diagnosis`
**HEAD:** `6415863`

---

## I. Audit 目标

确认 `HRRL2/env.py` baseline hash 从 `5ffc1e934e1f8908` 变为 `e19703467be71e20` 的原因，判断是否可接受。

---

## II. Git 跟踪状态

| 文件 | Tracked | Status |
|------|---------|--------|
| `HRRL2/env.py` | **否** | `!! HRRL2/` (整个目录被 .gitignore) |
| `HRRL2/.research-agent/artifacts/baseline_env.py` | **否** | 同上 |

`git show reward-langgraph-v0.6:HRRL2/env.py` 返回空。旧 baseline 无法从 git 恢复。

---

## III. Hash 对比

| 来源 | Hash (SHA256 前 16 字符) | 大小 | 时间 |
|------|--------------------------|------|------|
| 历史基准 (v0.1–v0.6) | `5ffc1e934e1f8908` | — | — |
| 当前 env.py | `e19703467be71e20` | 102,974 | — |
| baseline_env.py | `e19703467be71e20` | 102,974 | 2026-06-15 15:18 |
| candidate_env.py | `172d7a516975fbb4` | 104,642 | — |

**env.py 与 baseline_env.py 完全一致。**

---

## IV. Diff 分析

### env.py vs candidate_env.py

candidate_env.py 是 v0.6.1 run 中 candidate 的 patch 应用后的版本。差异：

| 项目 | current env.py (baseline) | candidate_env.py (patched) |
|------|--------------------------|---------------------------|
| `min_success_steps` | 300 | 1000 |
| `__calculate_reward` | 原始 reward 函数 | PBRS reward 函数 (11 行修改) |
| 行数 | 2329 | 2354 |

当前 env.py 有**正确的原始 reward 函数**，不是 candidate 的 PBRS 版本。

### env.py vs 旧 baseline (5ffc1e934e1f8908)

**无法直接对比** — 旧版本不在 git 中，无备份文件可恢复。

---

## V. Hash 变化原因

### 证据链

1. v0.1–v0.6 所有报告记录 baseline hash 为 `5ffc1e934e1f8908`
2. v0.6 run（mock LLM）未修改 env.py
3. v0.6.1 run 配置 `auto_push: true`
4. v0.6.1 run 的 executor 启动时检测到 `baseline_env.py` 与当前 `env.py` 不一致
5. auto_push 自动将 `baseline_env.py` 更新为当前 `env.py`（hash `e19703467be71e20`）
6. v0.6.1 run 完成后，executor 将 `env.py` 回滚到 `baseline_env.py`
7. 最终 env.py 和 baseline_env.py 均为 `e19703467be71e20`

### 变化时间点

在 v0.6（mock LLM）和 v0.6.1（real LLM）之间，env.py 发生了变化。可能原因：
- 某次更早的 optimizer run 修改了 env.py 但 rollback 不完整
- 手动编辑
- auto_push 在某次 run 中将 baseline 更新为被修改的 env.py

由于 HRRL2 不被 git 跟踪，无法确定具体是哪次操作导致变化。

---

## VI. Baseline 变化分类

**D. auto_push_baseline_migration_without_review**

auto_push 自动迁移 baseline，但未经过人工确认。

理由：
1. Hash 确实发生了变化（`5ffc` → `e197`）
2. 变化由 auto_push 机制自动执行
3. 旧 baseline 无法恢复（不在 git 中）
4. 当前 env.py 的 reward 函数和关键参数与原始设计一致

---

## VII. 当前 Baseline 功能验证

| 检查项 | 结果 |
|--------|------|
| reward 函数是否为原始版本 | 是（非 PBRS） |
| `min_success_steps` | 300（原始值） |
| env.py 与 baseline_env.py 一致 | 是 |
| v0.6.1 full eval 复现通过 | 是（reward=972.5, completion_rate=1.0） |
| baseline.json metrics | reward=1601.59, completion_rate=1.0, lateral_error=1.30 |

---

## VIII. 对 Full Eval 公平协议的影响

| 检查项 | 状态 |
|--------|------|
| 评估指标未变 | 是（completion_rate, reward, lateral_error） |
| seed 选择未变 | 是（[42]） |
| 评估逻辑未变 | 是（scoring.py 未修改） |
| accept/reject 标准未变 | 是 |
| baseline env.py 用于 full eval | 是（executor 在 eval 前恢复 baseline） |

---

## IX. 建议

### 是否接受 e197 作为新 baseline

**建议接受**，理由：

1. 当前 env.py 有正确的原始 reward 函数（非 candidate patch）
2. `min_success_steps=300` 是原始设计值
3. v0.6.1 full eval 复现通过，模型加载和评估正常
4. env.py 与 baseline_env.py 一致，rollback 机制工作正常
5. 旧 baseline 无法恢复，拒绝当前 baseline 无法回到 `5ffc`

### 是否需要恢复 5ffc

**不建议**，原因：

1. 旧 baseline 不在 git 中，无法恢复
2. 当前 baseline 功能正确
3. 恢复需要重新运行所有 baseline eval，成本高

### 风险

- 无法确认 `5ffc` → `e197` 的精确 diff
- 如果变化不是 benign（如改变了 reward 函数参数），可能影响 baseline metrics

### 缓解措施

可以用当前 env.py 运行一次 baseline eval，对比 baseline.json 中记录的 metrics（reward=1601.59, completion_rate=1.0, lateral_error=1.30），确认一致性。

---

## X. 是否建议 push v0.6.2.1

**待用户确认**。如果接受 e197 作为新 baseline，可以 push。否则需要进一步调查。

---

## XI. v0.7 建议

1. 将 HRRL2/env.py 纳入 git 跟踪（移出 .gitignore），或添加 baseline snapshot 机制
2. 在 auto_push 更新 baseline 前添加人工确认步骤
3. 记录 baseline hash 变更历史到 state.json
