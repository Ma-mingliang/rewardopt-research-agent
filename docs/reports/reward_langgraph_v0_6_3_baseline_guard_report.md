# Reward LangGraph v0.6.3 — Baseline Migration Guard Report

**Date:** 2026-06-15
**Branch:** `reward-langgraph-v0.6.3-baseline-guard`
**Tag:** `reward-langgraph-v0.6.3`

---

## I. v0.6.3 目标

禁止 silent baseline migration。以后如果 `env.py` / `baseline_env.py` / accepted baseline hash 发生变化，默认 fail fast。只有显式传入 `--accept-baseline-migration` 参数时，才允许接受新的 operational baseline。

---

## II. v0.6.2.2 Baseline Migration 背景

| 项目 | 值 |
|------|-----|
| Historical baseline hash (v0.1–v0.6) | `5ffc1e934e1f8908` |
| Accepted operational baseline (v0.6.2.2) | `e19703467be71e20` |
| Migration classification | D. auto_push_baseline_migration_without_review |
| Root cause | `auto_push: true` in config silently overwrote `baseline_env.py` |

---

## III. Baseline Manifest 设计

新增 tracked manifest: `docs/baselines/hrrl2_operational_baseline.yaml`

```yaml
project: HRRL2
file: env.py
accepted_operational_baseline_hash: "e19703467be71e20"
historical_baseline_hash: "5ffc1e934e1f8908"
accepted_since: "reward-langgraph-v0.6.2.2"
classification: "auto_push_baseline_migration_without_review"
baseline_eval_metrics:
  reward: 983.26
  completion_rate: 1.0
  lateral_error: 0.0041
policy:
  allow_silent_baseline_migration: false
  require_explicit_acceptance: true
```

由于 `HRRL2/` 整体被 `.gitignore`，不能依赖 git 跟踪 `env.py`。此 manifest 只记录 hash、说明和指标，不提交 `env.py` 全文或 secret。

---

## IV. Baseline Guard 检查规则

新增模块: `research_agent/core/baseline_guard.py`

| 检查 | 条件 | 结果 |
|------|------|------|
| CHECK A | `env.py` 不存在 | fail fast, `ENV_VS_MANIFEST` |
| CHECK B | `env.py` hash ≠ manifest hash | fail fast, `ENV_VS_MANIFEST` |
| CHECK C | `baseline_env.py` ≠ `env.py` | fail fast, `ARTIFACT_VS_ENV` |
| CHECK C' | `baseline_env.py` 不存在 | fail fast, `ARTIFACT_MISSING` |
| CHECK D | auto_push + drift + no allow | fail fast, `AUTO_PUSH_CONFLICT` |
| Override | `--accept-baseline-migration` | 允许继续，但记录 `baseline_migration_allowed` |

关键设计:
- Guard 是纯函数模块，不修改任何文件
- `allow_migration=True` 只允许继续运行，不自动写入 manifest
- 遵循 `eval_diagnostics.py` 的 `(ok, Diagnostic)` 返回模式

---

## V. Auto-Push 防护策略

| 场旳 | 行为 |
|------|------|
| `auto_push=true` + drift + no `--accept` | **fail fast** |
| `auto_push=true` + drift + `--accept` | allow with warning |
| `auto_push=false` + drift + no `--accept` | **fail fast** |
| `auto_push=false` + no drift | pass |

原 `executor.py` lines 1121-1148 的 auto_push baseline sync 已移除，替换为注释:
```python
# v0.6.3+: Baseline guard runs in run_optimizer.py before iteration loop.
# Auto-push baseline sync removed to prevent silent migration.
```

---

## VI. CLI 参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--baseline-manifest PATH` | `docs/baselines/hrrl2_operational_baseline.yaml` | Baseline manifest 路径 |
| `--accept-baseline-migration` | `false` | 允许 baseline drift 时继续运行 |

---

## VII. Observability

### events.jsonl 新增事件

| event_type | 字段 |
|------------|------|
| `baseline_guard_start` | manifest_path, manifest_hash, auto_push, allow_migration |
| `baseline_guard_pass` | env_hash, manifest_hash |
| `baseline_guard_failed` | drift_type, env_hash, manifest_hash, auto_push, allow_migration |
| `baseline_drift_detected` | drift_type, env_hash, artifact_hash, manifest_hash |
| `baseline_guard_manifest_missing` | manifest_path |

### summary.json 新增字段

| 字段 | 类型 |
|------|------|
| `baseline_guard_run` | bool |
| `baseline_guard_passed` | bool |
| `baseline_guard_failed` | bool |
| `baseline_guard_drift_type` | string \| null |
| `baseline_guard_manifest_path` | string \| null |

---

## VIII. 正向 Mock Smoke 结果

**命令:**
```
python run_optimizer.py --project HRRL2 --optimizer reward_langgraph --mock-llm --max-iterations 1 --batch-size 1 --staged-eval --no-short-train
```

**结果:**
- `[BASELINE GUARD] Passed. env_hash=e19703467be71e20`
- `baseline_guard_passed=true`
- `current_env_hash=e19703467be71e20`
- `accepted_operational_baseline_hash=e19703467be71e20`
- Run ID: `20260615_210522_reward_langgraph_4cf050`

**events.jsonl 示例:**
```json
{"event_type": "baseline_guard_start", "manifest_hash": "e19703467be71e20", "auto_push": true, "allow_migration": false}
{"event_type": "baseline_guard_pass", "env_hash": "e19703467be71e20", "manifest_hash": "e19703467be71e20"}
```

**summary.json 示例:**
```json
{
  "baseline_guard_run": true,
  "baseline_guard_passed": true,
  "baseline_guard_failed": false,
  "baseline_guard_drift_type": null,
  "baseline_guard_manifest_path": "docs/baselines/hrrl2_operational_baseline.yaml"
}
```

---

## IX. 负向 Smoke 结果

构造临时副本，修改 `env.py` 一行注释，使 hash 变化。

**结果:**
- Original hash: `e19703467be71e20`
- Modified hash: `121e696a1ecdbe8e`
- `Guard ok: False`
- `Drift type: env_vs_manifest`
- `Error: env.py hash mismatch: current=121e696a1ecdbe8e, accepted=e19703467be71e20`
- `Fix hint: Either restore env.py to match the accepted baseline, or update the baseline manifest after manual audit. Use --accept-baseline-migration to override.`
- Real `HRRL2/env.py` hash unchanged: `e19703467be71e20`
- 临时目录已清理

---

## X. 测试结果

| 测试文件 | 结果 |
|----------|------|
| `tests/test_baseline_guard.py` | 19 passed |
| `tests/test_eval_diagnostics.py` | 42 passed |
| `tests/test_observability.py` | 22 passed |
| Full suite (`tests/ -q`) | 288 passed, 1 failed (pre-existing Windows path issue) |

---

## XI. Full Eval 协议

Full eval 协议保持不变。Baseline guard 在 optimizer iteration loop 之前运行，不影响 baseline phase 或 full eval 的执行逻辑。

---

## XII. 是否修改 env.py

**否。** `HRRL2/env.py` 未被修改。Hash 验证: `e19703467be71e20`。

---

## XIII. v0.7 建议

1. 将 baseline manifest 集成到 `experiment_plan.json` 中，作为 phase-level metadata
2. 增加 baseline manifest 的 git hook pre-commit 校验
3. 支持多-project baseline manifest (当前硬编码 HRRL2)
4. 增加 baseline hash 的自动定期校验 (cron/scheduled task)
