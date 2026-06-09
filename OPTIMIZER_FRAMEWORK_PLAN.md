# 优化器框架重构计划 V2

> 修复了 V1 的 6 个关键问题，详见底部"设计问题与修复"。

## 目标

将 HRRL2 中已验证的功能抽象为优化器框架的核心能力，使任何新项目只需在 `init` 阶段完成配置，即可使用完整的优化流程。

---

## 核心设计原则

1. **项目无关**：优化器框架不包含任何项目特定代码
2. **约定优于配置**：通过 RA_CHECKPOINT_DIR 等约定减少配置
3. **模板 + 填充**：init 阶段框架提供模板，agent 填充项目参数（不从零生成）
4. **公平评估**：所有 candidate 都用 baseline 的原始 reward 评估，确保可比性
5. **加权决策**：accept/reject 基于综合加权分数，不是单指标阈值
6. **原子操作**：任何步骤失败都能安全回滚到一致状态

---

## 阶段 1：init 阶段

### 1.1 生成 .research-agent/train.py

**方式**：框架提供模板 `research_agent/templates/train_template.py`，agent 填充以下参数：

| 参数 | 说明 | 示例 |
|------|------|------|
| `PROJECT_ROOT` | 项目根目录 | `Path(__file__).parent.parent` |
| `IMPORT_ENV` | 导入环境模块的代码 | `import env as env_module` |
| `CREATE_ENV` | 创建环境实例的代码 | `env_module.Attitude_control_stage1(render=False)` |
| `CREATE_MODEL` | 创建模型的代码 | `TD3("MlpPolicy", ...)` |
| `TRAIN_MODEL` | 训练模型的代码 | `model.learn(total_timesteps=timesteps)` |
| `SAVE_BEST` | 保存 best model 的逻辑 | BestModelCallback 或自定义 |
| `TIMESTEPS` | 默认训练步数 | `20000` |

**输出**：`.research-agent/train.py`

**约定**：
```
环境变量 RA_CHECKPOINT_DIR 由优化器框架设置
best model 必须保存到 {RA_CHECKPOINT_DIR}/best_model.zip
训练过程中只保存 best model（基于 N 回合平均奖励，回合变化时计算）
CLI: python .research-agent/train.py <seed> [--checkpoint-dir DIR]
```

### 1.2 生成 .research-agent/evaluate.py

**方式**：框架提供模板 `research_agent/templates/evaluate_template.py`，agent 填充：

| 参数 | 说明 |
|------|------|
| `IMPORT_ENV` | 导入环境模块 |
| `CREATE_ENV` | 创建环境实例 |
| `LOAD_MODEL` | 加载模型的代码 |
| `EPISODE_METRICS` | 每回合收集的指标逻辑 |
| `SUCCESS_CRITERIA` | 判断回合成功的条件 |

**输出**：`.research-agent/evaluate.py`

**输出格式**（stdout，必须严格遵循）：
```
[METRICS]
{"completion_rate": 0.95, "reward": 850.3, "lateral_error": 3.2}

completion_rate = 0.9500
reward = 850.3000
lateral_error = 3.2000
```

**指标要求**：
- 必须包含 `completion_rate`（成功率，硬性要求）
- 其他指标由 agent 根据项目特点确定
- 每个指标必须有 `direction`（maximize/minimize）和 `weight`

### 1.3 生成评判标准

**输出**：写入 `config.yaml` 的 `evaluation` 部分

```yaml
evaluation:
  test_episodes: 30                    # 公平评估回合数
  checkpoint_dir: model/checkpoints
  modifiable_files:                    # ★ 新增：声明可修改文件范围
    - env.py
    - reward.py
  metrics:
    - name: completion_rate
      direction: maximize
      weight: 0.4
      hard_min: 0.3                    # 低于此值直接拒绝
    - name: reward
      direction: maximize
      weight: 0.4
    - name: lateral_error
      direction: minimize
      weight: 0.2
      hard_max: 50.0
  composite_threshold: 0.0            # 综合分 > 0 才接受
  llm_weight: 0.2                     # LLM 动态评判占比（0 = 禁用）
  no_improvement_patience: 5          # 连续 N 轮无提升则停止
```

### 1.4 文档生成

**输出**：写入 `.research-agent/README.md`

内容：
- 优化器工作流程说明
- train.py 和 evaluate.py 的接口约定
- RA_CHECKPOINT_DIR 约定（使用前必须阅读）
- 指标和权重说明
- modifiable_files 的作用
- 如何自定义

---

## 阶段 2：Baseline

### 2.1 流程

```
1. 训练
   - 设置 RA_CHECKPOINT_DIR = {project}/model/checkpoints
   - 对每个 seed 调用 train_command
   - checkpoint 保存在 RA_CHECKPOINT_DIR/best_model.zip

2. 归档
   - 复制 best_model.zip → best_baseline.zip

3. 公平评估
   - 恢复 baseline 状态（确保 env.py 未被修改）
   - 调用 evaluate.py best_baseline.zip --episodes 30
   - 得到 baseline_fair = {completion_rate, reward, lateral_error, ...}

4. 保存基准
   - baseline_fair 写入 state.json
   - baseline env.py 复制到 .research-agent/artifacts/baseline_env.py
   - baseline_metrics 写入 artifacts/baseline_metrics.json
```

### 2.2 输出

```json
{
  "phase_id": "baseline",
  "status": "completed",
  "metrics": {"completion_rate": {"mean": 1.0, "std": 0.0, ...}},
  "fair_eval": {"completion_rate": 0.95, "reward": 850.3, "lateral_error": 3.2},
  "checkpoint": "model/checkpoints/best_baseline.zip"
}
```

---

## 阶段 3：Optimizer 核心循环

### 3.1 单个 Candidate 流程

```
对于每个 candidate（最多 max_candidates 轮）：

1. 获取方法
   batch = PaperSampler.get_next_batch(batch_size=2)

2. 提出 candidate
   candidate = optimizer.propose_candidate(phase, baseline_fair, batch)
   生成 patch_diff（修改 modifiable_files 中的文件）

3. 应用 patch
   patch_manager.apply_and_validate(candidate)
   ★ 失败 → 记录错误，continue 到下一个 candidate

4. 训练（用修改后的 env.py）
   设置 RA_CHECKPOINT_DIR = {project}/model/checkpoints/{version_id}
   调用 train_command
   ★ 失败 → rollback env.py（git checkout -- .），记录错误，continue

5. 公平评估 ★ 核心 ★
   5a. git stash（保存当前修改后的完整状态）
   5b. 恢复 baseline env.py（从 artifacts/baseline_env.py 复制）
   5c. 调用 evaluate.py {version_id}/best_model.zip --episodes 30
       → 得到 fair_metrics
   5d. git stash pop（恢复修改后的状态）
       ★ 如果 stash pop 冲突 → 手动恢复 modifiable_files

6. 综合评分 ★ 核心 ★
   composite = Σ(weight_i × score_i)

   score_i 的计算（修复了除零问题）：
   - maximize: candidate_val / max(baseline_val, epsilon) - 1
   - minimize: 1 - candidate_val / max(baseline_val, epsilon)

   其中 epsilon = 1e-6（防止除零）

7. Hard 阈值检查 ★ 核心 ★
   对每个指标检查 hard_min / hard_max：
   - 任何指标超 hard 阈值 → 直接拒绝，不看综合分

8. LLM 动态评判（20% 权重，可选）★ 核心 ★
   如果 llm_weight > 0 且 API 可用：
   - 输入：baseline 表现、candidate 表现、composite 分数、项目目标
   - Prompt："基于以下表现，给出 0-1 的评分和理由"
   - 输出：llm_score ∈ [0, 1] + reason
   - 如果 API 不可用：llm_score = 0.5（中性）

9. 最终决策
   final_score = (1 - llm_weight) × composite + llm_weight × llm_score

   if 任何 hard 阈值被突破:
       REJECT
   elif final_score > composite_threshold:
       ACCEPT
   else:
       REJECT

10. 后处理
    Accepted:
    - 归档 checkpoint → {version_id}_best.zip + current_best.zip
    - git snapshot
    - 更新 state.current_best
    - 记录 accepted 到 tried_methods.jsonl

    Rejected:
    - git checkout -- .（回滚 modifiable_files）
    - checkpoint 保留（不删除）
    - 记录 rejected 到 tried_methods.jsonl
```

### 3.2 关键修复：公平评估的 env.py 恢复

```
问题：candidate 的 patch 基于当前 env.py 生成。
     如果先恢复 baseline env.py 再 re-apply patch，patch 上下文可能不匹配。

解决方案：git stash

步骤：
1. 训练完成后，当前 env.py = 修改后的版本（reward_B）
2. git stash → 保存 reward_B 的完整状态
3. 从 artifacts/ 复制 baseline env.py → 当前 env.py = reward_A
4. evaluate.py 用 reward_A 评估 checkpoint → fair_metrics
5. git stash pop → 恢复 env.py = reward_B
6. 继续后续流程（accept/reject/rollback）

优势：
- 不需要 re-apply patch
- stash pop 恢复的是训练时的精确状态
- 如果 stash pop 失败，可以从 artifacts/ 重新恢复
```

### 3.3 版本化管理

```
{project}/model/checkpoints/
├── best_model.zip          ← 当前训练中的 best（每次训练覆盖）
├── best_baseline.zip       ← baseline 归档（只读）
├── v0001/
│   └── best_model.zip      ← v0001 的 checkpoint
├── v0001_best.zip          ← v0001 accepted 后归档
├── v0002/
│   └── best_model.zip
└── current_best.zip        ← 最新 accepted 的 checkpoint
```

---

## 阶段 4：收敛与终止

### 4.1 终止条件（满足任一即停）

```
1. PaperSampler 返回空（所有方法已尝试）
2. candidates_proposed >= max_candidates
3. full_evals_run >= max_full_evals
4. wall_clock_seconds >= wall_clock_hours * 3600
5. 连续 no_improvement_patience 轮无提升 ★ 新增 ★
```

### 4.2 最终验证

```
优化完成后：
1. 用 current_best.zip 跑 30 回合公平评估
2. 与 baseline_fair 对比，生成对比报告
3. 生成 reports/optimization_report.json
```

---

## 阶段 5：实验日志与报告

### 5.1 日志文件

| 文件 | 内容 | 格式 |
|------|------|------|
| CHANGELOG.md | 每个 candidate 的详细记录 | Markdown |
| tried_methods.jsonl | 方法级 + 版本级记录 | JSONL |
| candidates.jsonl | candidate 完整信息 | JSONL |
| experiments.jsonl | 阶段级实验记录 | JSONL |
| llm_calls.jsonl | LLM 调用记录（含评判理由） | JSONL |

### 5.2 最终报告

```
reports/optimization_report.json:
{
  "baseline": {"fair_eval": {...}, "checkpoint": "..."},
  "candidates": [
    {"version_id": "v0001", "fair_eval": {...}, "composite": 0.12, "accepted": true, ...},
    {"version_id": "v0002", "fair_eval": {...}, "composite": -0.03, "accepted": false, ...}
  ],
  "best": {"version_id": "v0001", "fair_eval": {...}, "checkpoint": "..."},
  "improvement": {"reward": "+15.2%", "completion_rate": "+5%", "lateral_error": "-8%"},
  "resource_usage": {...},
  "methods_tried": 12,
  "methods_total": 45
}
```

---

## 阶段 6：Paper Pool 迭代

### 6.1 PaperSampler 增强

```
现有功能：
- 从 method_pool.jsonl 按批次选取方法
- 记录已使用方法
- 避免重复

需要增强：
- 支持按 category 优先级排序
- 支持跳过低置信度方法
- 支持方法组合（2 个互补方法）
```

### 6.2 方法标记

```
每个方法尝试后标记状态：
- accepted: 已接受，效果提升
- rejected: 已拒绝，无提升
- error: 应用/训练失败
- noop: 生成空 patch

标记信息写入 tried_methods.jsonl
```

---

## 文件结构总览

```
.research-agent/
├── config.yaml              ← 项目配置（含 evaluation 部分）
├── state.json               ← 运行状态
├── train.py                 ← ★ init 时从模板填充生成
├── evaluate.py              ← ★ init 时从模板填充生成
├── README.md                ← ★ init 时生成的文档
├── artifacts/
│   ├── baseline_env.py      ← baseline 时保存
│   ├── baseline_metrics.json
│   └── eval_result.json
├── logs/
│   ├── tried_methods.jsonl
│   ├── candidates.jsonl
│   ├── experiments.jsonl
│   └── llm_calls.jsonl
├── reports/
│   ├── experiment_plan.json
│   ├── execution_report.json
│   └── optimization_report.json
└── CHANGELOG.md

research_agent/templates/         ← ★ 框架模板（新增）
├── train_template.py
├── evaluate_template.py
└── README_template.md
```

---

## 实施顺序

| 序号 | 任务 | 依赖 | 估计工作量 |
|------|------|------|-----------|
| **1** | 创建 train_template.py 模板 | 无 | 中 |
| **2** | 创建 evaluate_template.py 模板 | 无 | 中 |
| **3** | 定义 config.yaml 的 evaluation schema | 无 | 小 |
| **4** | 增强 init 命令：从模板填充生成 train.py/evaluate.py | 1,2,3 | 中 |
| **5** | 增强 init 命令：生成 README.md | 1,2 | 小 |
| **6** | 实现综合加权评分算法（修复除零） | 3 | 小 |
| **7** | 实现 git stash 方式的公平评估流程 | 4 | 中 |
| **8** | 重构 baseline 流程 | 6,7 | 中 |
| **9** | 重构 optimizer 核心循环 | 8 | 大 |
| **10** | 实现 LLM 动态评判（20% 权重） | 9 | 中 |
| **11** | 实现版本化 checkpoint 管理 | 9 | 小 |
| **12** | 实现收敛条件检测（含 patience） | 9 | 小 |
| **13** | 增强 PaperSampler | 无 | 中 |
| **14** | 增强实验日志和最终报告 | 9 | 中 |
| **15** | 端到端测试（用 HRRL2 验证） | 1-14 | 中 |
| **16** | 文档完善 + 使用前告知机制 | 1-15 | 小 |

---

## 设计问题与修复（V1 → V2）

### 问题 1：env.py 恢复逻辑有致命缺陷 ★ 关键 ★

**V1 方案**：恢复 baseline env.py → 评估 → re-apply patch

**问题**：candidate 的 patch 基于当前 env.py 生成。如果之前有 accepted candidate 修改了 env.py，baseline env.py 与 patch 的上下文不匹配，re-apply 会失败。

**V2 修复**：用 `git stash` 保存训练时的精确状态，评估后 `git stash pop` 恢复。不需要 re-apply patch。

### 问题 2：综合分归一化有除零风险 ★ 关键 ★

**V1 方案**：`(candidate - baseline) / |baseline|`

**问题**：baseline = 0 时崩溃（如 completion_rate 初始为 0）。

**V2 修复**：`candidate / max(baseline, epsilon) - 1`，epsilon = 1e-6。

### 问题 3：LLM 20% 权重组合方式不清楚

**V1 方案**："LLM 判断占 20%"，但没说 LLM 输出什么。

**V2 修复**：
- LLM 输出 0-1 连续分 + 理由
- Prompt 明确："基于以下表现，给出 0-1 的评分和理由"
- API 不可用时 llm_score = 0.5（中性，不影响决策）

### 问题 4：init 生成 train.py 的可行性存疑

**V1 方案**：agent 从零生成 train.py

**问题**：不同项目训练框架差异巨大，从零生成质量不可控。

**V2 修复**：框架提供模板，agent 只填充项目特定参数。模板处理通用逻辑（BestModelCallback、checkpoint 保存、CLI 解析）。

### 问题 5：训练失败时无清理策略

**V1 方案**：无

**V2 修复**：每步都有 try/except：
- 训练失败 → git checkout -- . + 记录错误 + continue
- stash pop 失败 → 从 artifacts/ 手动恢复 + 警告

### 问题 6：缺少可修改文件范围定义

**V1 方案**：无

**V2 修复**：config.yaml 声明 `modifiable_files` 列表。PatchManager 只允许修改这些文件。回滚时只恢复这些文件。

---

## 扩展计划（后续）

1. 多目标优化（Pareto 前沿）
2. 并行 candidate 评估
3. 自动超参数调优（HPO optimizer）
4. 可视化仪表板
5. 方法组合策略（互补方法自动配对）
