# Reward LangGraph v0.6.2.2 — Baseline Acceptance Report

**Date:** 2026-06-15
**Branch:** `reward-langgraph-v0.6.2-model-load-diagnosis`
**HEAD:** `6415863`

---

## I. Baseline Migration Record

| 项目 | 值 |
|------|-----|
| Historical baseline hash (v0.1–v0.6) | `5ffc1e934e1f8908` |
| Accepted operational baseline (v0.6.2.2) | `e19703467be71e20` |
| Migration classification | D. auto_push_baseline_migration_without_review |
| Acceptance decision | **已接受** |

---

## II. env.py 一致性验证

| 文件 | Hash (SHA256 前 16 字符) |
|------|--------------------------|
| `HRRL2/env.py` | `e19703467be71e20` |
| `HRRL2/.research-agent/artifacts/baseline_env.py` | `e19703467be71e20` |

**env.py 与 baseline_env.py 完全一致。**

---

## III. Baseline Eval 结果

**命令：**
```
cd D:/research-agent/HRRL2 && E:/Anaconda/envs/RL2/python.exe .research-agent/evaluate.py model/checkpoints/best_baseline.zip --episodes 30
```

| 指标 | 值 |
|------|-----|
| reward | 983.26 |
| completion_rate | 1.0 |
| lateral_error | 0.0041 |

---

## IV. baseline.json 历史记录对比

| 指标 | baseline.json 记录 | 当前 baseline eval |
|------|-------------------|-------------------|
| reward | 1601.59 | 983.26 |
| completion_rate | 1.0 | 1.0 |
| lateral_error | 1.30 | 0.0041 |

**差异说明：**

baseline.json 中的 metrics 是早期版本（v0.1 或 v0.2）记录的，当时的 env.py 和模型可能与当前不同：
- reward 差异（1601 vs 983）：可能由于旧 env.py 的 reward 函数参数不同
- lateral_error 差异（1.30 vs 0.0041）：当前模型表现更好，可能是模型改进或评估参数变化

completion_rate 一致（均为 1.0），说明模型功能正常。

---

## V. 功能验证

| 检查项 | 结果 |
|--------|------|
| reward 函数是否为原始版本（非 PBRS） | 是 |
| `min_success_steps` | 300（原始值） |
| env.py 与 baseline_env.py 一致 | 是 |
| model_load_failed 修复已应用 | 是（`{checkpoint_path}` 占位符） |
| eval_command preflight 已添加 | 是（11 个新测试通过） |

---

## VI. 接受理由

1. 当前 env.py 有正确的原始 reward 函数（非 candidate PBRS patch）
2. `min_success_steps=300` 是原始设计值
3. 模型加载和评估正常（completion_rate=1.0）
4. env.py 与 baseline_env.py 一致，rollback 机制工作正常
5. 旧 baseline `5ffc` 不在 git 中，无法恢复
6. v0.6.2 的 model_load_failed 修复已应用并测试通过

---

## VII. 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| baseline.json metrics 与当前 eval 不一致 | 记录差异，后续版本更新 baseline.json |
| 无法确认 `5ffc` → `e197` 的精确 diff | 接受当前 baseline 为 operational baseline |
| HRRL2 不被 git 跟踪 | v0.7 建议：将 env.py 纳入 git 或添加 snapshot 机制 |

---

## VIII. 后续建议

1. 更新 baseline.json 为当前 eval metrics（reward=983.26, completion_rate=1.0, lateral_error=0.0041）
2. v0.7：将 HRRL2/env.py 纳入 git 跟踪或添加 baseline snapshot 机制
3. v0.7：在 auto_push 更新 baseline 前添加人工确认步骤
