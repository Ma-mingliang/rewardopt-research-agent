# 快速开始：使用 HRRL2 运行你的第一个基本测试

本指南以 HRRL2（自行车控制项目）为目标项目，帮助你验证 research-agent reward 优化平台是否正常工作。

---

## 项目概览

**research-agent** 是一个基于 LLM 的自动化研究代码优化平台。当前主要能力是 **reward 函数优化**：通过 LLM 生成 reward patch，经过语义门控、语法修复、候选排序后保存为可训练的候选。

**HRRL2** 是平台的目标项目，一个基于 PyBullet 的自行车平衡与路径跟踪 RL 环境。优化目标是 `HRRL2/env.py` 中的 `__calculate_reward` 方法。

---

## HRRL2 项目获取与配置

HRRL2 是一个独立的 Git 仓库，被 research-agent 通过 `.gitignore` 排除在外。你需要单独克隆它。

### GitHub 地址

| 项目 | 地址 |
|------|------|
| HRRL2 主仓库 | `https://github.com/Ma-mingliang/HRRL2-test.git` |
| HRRL2 测试副本 | `https://github.com/Ma-mingliang/HRRL2-test-test.git` |

### 分支说明

| 分支 | 用途 |
|------|------|
| `v0-baseline` | **v0 基线分支（推荐）**，包含初始 HRRL2 代码，未经优化器修改 |
| `optimizer-run` | 优化器运行历史分支（含 accepted/rejected 候选） |
| `optimizer-run-v2` | 优化器运行历史分支 v2（含更多 accepted/rejected 候选） |

**重要**: 使用 `v0-baseline` 分支作为基线（https://github.com/Ma-mingliang/HRRL2-test/tree/v0-baseline）。`main`、`optimizer-run` 和 `optimizer-run-v2` 分支已被优化器修改过，不是干净的基线。

### 获取 HRRL2

```bash
# 方式 1: 克隆到 research-agent 目录下（推荐）
cd research-agent
git clone https://github.com/Ma-mingliang/HRRL2-test.git HRRL2
cd HRRL2
git checkout v0-baseline
cd ..

# 方式 2: 如果 HRRL2 目录已存在但为空
cd HRRL2
git status  # 确认是否有内容
# 如无内容，重新克隆
```

### 确认 HRRL2 状态

```bash
# 确认关键文件存在
ls HRRL2/env.py
ls HRRL2/LQR.py
ls HRRL2/stanley.py
ls HRRL2/3D/

# 确认 env.py baseline hash（必须为 e19703467be71e20）
python -c "import hashlib; print(hashlib.sha256(open('HRRL2/env.py','rb').read()).hexdigest()[:16])"

# 确认当前分支（应为 v0-baseline）
cd HRRL2 && git branch --show-current && cd ..
```

### 安装 HRRL2 依赖

HRRL2 需要额外的 RL 依赖，不在 research-agent 的 `pyproject.toml` 中：

```bash
pip install gymnasium torch stable_baselines3 pybullet pybullet_data numpy pandas
```

### 验证 HRRL2 可用

```bash
cd HRRL2
python verify_full_logic_smoke.py
python verify_single_turn_assets.py
cd ..
```

### HRRL2 关键文件

| 文件 | 用途 |
|------|------|
| `env.py` | 环境定义，含 `__calculate_reward` 方法（优化目标） |
| `LQR.py` | Part 1: LQR 平衡控制训练入口 |
| `stanley.py` | Part 3: Stanley 路径跟踪训练入口 |
| `3D/` | 路径 mesh、地形、车辆 URDF 资源 |
| `model/` | 训练输出目录 |
| `verify_full_logic_smoke.py` | 主线烟雾测试 |
| `verify_single_turn_assets.py` | 路径资源加载检查 |
| `README.md` | HRRL2 使用文档 |

### HRRL2 在 optimizer 中的角色

research-agent 优化器通过以下方式使用 HRRL2：

1. **读取** `HRRL2/env.py` 中的 `__calculate_reward` 方法作为优化目标
2. **生成** reward patch（diff 格式）
3. **应用** patch 到 env.py（临时修改）
4. **训练** HRRL2（通过 `LQR.py` 或 `stanley.py`）
5. **评估** 训练结果
6. **回滚** patch（`git checkout -- env.py`）

当前 v0.8.9 只执行步骤 1-3（proposal-only），不训练。

---

## 前置条件

| 条件 | 说明 |
|------|------|
| Python | >= 3.11 |
| Git | 任意版本 |
| Conda（推荐） | 或使用 venv |
| LLM API Key | 仅路径 B/C 需要；路径 A 不需要 |
| HRRL2 项目 | 需要单独克隆（见上文） |
| Execution Python | 路径 C 需要安装了 torch/gymnasium 的 Python（如 `E:/Anaconda/envs/RL2/python.exe`） |

---

## 路径 A：Mock-LLM 冒烟测试（无需 API Key）

最快的验证方式。使用 mock LLM，不调用真实 API，不训练，不 eval。

```bash
# 1. 克隆并安装
git clone https://github.com/Ma-mingliang/rewardopt-research-agent.git
cd rewardopt-research-agent
conda create -n ra python=3.11 -y
conda activate ra
pip install -e ".[dev,langgraph]"

# 2. 验证 CLI
research-agent --help

# 3. 运行 mock-LLM optimizer（无需 API key，无需 HRRL2）
python run_optimizer.py \
  --project test_accept \
  --optimizer reward_langgraph \
  --mock-llm \
  --max-iterations 1 \
  --batch-size 1

# 4. 运行单元测试
python -m pytest tests/ -q
```

**预期结果：**
- CLI 输出帮助信息
- optimizer 运行完成（mock 模式，无实际 LLM 调用）
- 测试通过（可能有 1 个 pre-existing Windows path failure，可忽略）

---

## 路径 B：真实 LLM Proposal-Only 测试（需要 API Key，使用 HRRL2）

验证 LLM 连接和 semantic patch generation。使用 HRRL2 作为目标项目，但不训练。

### 步骤

```bash
# 1. 配置 API key
cp .env.example .env
# 编辑 .env，填入 MIMO_API_KEY

# 2. 确认 HRRL2 存在
ls HRRL2/env.py

# 3. 确认 env.py hash（必须为 e19703467be71e20）
conda run -n ra python -c "import hashlib; print(hashlib.sha256(open('HRRL2/env.py','rb').read()).hexdigest()[:16])"

# 4. 运行 proposal-only campaign（不训练，不 eval）
python run_optimizer.py \
  --project HRRL2 \
  --optimizer reward_langgraph \
  --max-iterations 3 \
  --batch-size 1 \
  --proposal-only \
  --reward-method-pool docs/getting-started/method_pool_sample.jsonl \
  --reward-method-top-k 3 \
  --max-semantic-regeneration-attempts 2 \
  --baseline-manifest docs/baselines/hrrl2_operational_baseline.yaml

# 5. 查看结果
ls HRRL2/.research-agent/runs/
# 找到最新 run 目录
cat HRRL2/.research-agent/runs/<最新run_id>/summary.json | python -m json.tool
```

**预期结果：**
- LLM 被调用，生成 reward patch 候选
- semantic gate 检查每个 patch（cosmetic patches 被拒绝）
- `summary.json` 包含 `semantic_gate_passed_count`, `template_diversity_score` 等
- `candidate_bank.jsonl` 包含 validation-ready patches
- `train_called=false`, `full_eval_called=false`
- env.py hash 未改变

---

## 路径 C：完整 Diversity Campaign + 候选 Handoff（需要 API Key + Execution Python）

复现 v0.8.8 的完整流程：DiversityScheduler 调度 → 多类别候选生成 → 候选排序 → handoff 导出。

### 前置条件

```bash
# 确认 execution python（安装了 torch/gymnasium/stable_baselines3/pybullet 的 Python）
# Windows 示例:
EXEC_PYTHON="E:/Anaconda/envs/RL2/python.exe"
# Linux 示例:
# EXEC_PYTHON="/usr/bin/python3"

# 确认 env.py hash
conda run -n ra python -c "import hashlib; print(hashlib.sha256(open('HRRL2/env.py','rb').read()).hexdigest()[:16])"
# 预期: e19703467be71e20
```

### 运行

```bash
# 1. 配置 API key（如未配置）
cp .env.example .env
# 编辑 .env，填入 MIMO_API_KEY

# 2. 运行 proposal-only diversity campaign
python run_optimizer.py \
  --project HRRL2 \
  --optimizer reward_langgraph \
  --max-iterations 5 \
  --batch-size 1 \
  --execution-python "$EXEC_PYTHON" \
  --reward-method-pool docs/getting-started/method_pool_sample.jsonl \
  --reward-method-top-k 3 \
  --staged-eval \
  --proposal-only \
  --max-semantic-regeneration-attempts 2 \
  --baseline-manifest docs/baselines/hrrl2_operational_baseline.yaml

# 3. 查看结果
RUN_DIR=$(ls -td HRRL2/.research-agent/runs/*/ | head -1)
echo "Run: $RUN_DIR"
cat "${RUN_DIR}summary.json" | python -m json.tool

# 4. 查看候选库
cat "${RUN_DIR}candidate_bank.jsonl | python -m json.tool
```

**预期结果：**
- `template_diversity_score` 接近 1.0（多类别覆盖）
- `candidates_total` >= 3
- `semantic_gate_passed_count` >= 3
- `candidate_bank.jsonl` 包含来自不同 category 的 patches
- `train_called=false`, `full_eval_called=false`
- env.py hash 未改变（`e19703467be71e20`）

### 应用候选 patch 验证（可选）

```bash
# 查看已有候选
cat docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/top_candidates_summary.md

# 应用 top 1 candidate（仅验证 patch 可用，不训练）
cd HRRL2
git apply ../docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/candidate_patches/test_control_energy_005.diff
conda run -n ra python -c "compile(open('env.py','r',encoding='utf-8-sig').read(), 'env.py', 'exec'); print('compile OK')"
git checkout -- env.py
cd ..
```

---

## v0.1–v0.8.9 版本演进历史

### v0.1–v0.5: 基础设施阶段

| 版本 | Tag | Commit | 核心内容 |
|------|-----|--------|---------|
| v0.1 | `reward-langgraph-v0.1` | `83abf0e` | 初始 reward optimizer 框架，LangGraph StateGraph |
| v0.2 | `reward-langgraph-v0.2` | `7567b7a` | 可观测性（events.jsonl, summary.json） |
| v0.3 | `reward-langgraph-v0.3` | `eb22334` | Full eval 诊断（eval timeout, model missing 检测） |
| v0.4 | `reward-langgraph-v0.4` | `99f31a9` | 方法池集成（method_pool.jsonl, MethodSelector） |
| v0.4.1 | `reward-langgraph-v0.4.1` | `0e51cd9` | 方法池测试夹具 |
| v0.5 | `reward-langgraph-v0.5` | `20c9075` | 修复优先 staged eval 流水线 |

### v0.6: 基线守卫阶段

| 版本 | Tag | Commit | 核心内容 |
|------|-----|--------|---------|
| v0.6 | `reward-langgraph-v0.6` | `c8a83c4` | 首次真实 LLM 运行验证 |
| v0.6.1 | `reward-langgraph-v0.6.1` | `3722ba9` | 真实 LLM 重试，发现 auto_push 静默迁移基线 |
| v0.6.2 | `reward-langgraph-v0.6.2` | `aec4271` | model_path_mismatch 诊断 |
| v0.6.2.1 | `reward-langgraph-v0.6.2.1` | `6415863` | 基线审计 |
| v0.6.2.2 | `reward-langgraph-v0.6.2.2` | `279dfd4` | 接受新基线 hash `e19703467be71e20` |
| v0.6.3 | `reward-langgraph-v0.6.3` | `5c8f152` | 基线迁移守卫（baseline_guard.py） |

### v0.7: LLM 语法修复阶段

| 版本 | Tag | Commit | 核心内容 |
|------|-----|--------|---------|
| v0.7.1 | `reward-langgraph-v0.7.1` | `355fa54` | 语法感知 LLM patch repair |
| v0.7.2 | `reward-langgraph-v0.7.2` | `e4cb167` | 第二次真实 campaign（格式修复） |
| v0.7.3 | `reward-langgraph-v0.7.3` | `b5ffeed` | Context-grounded reward patch proposal |
| v0.7.4 | `reward-langgraph-v0.7.4` | `2bf010e` | 真实 campaign 重试 |

### v0.8: 语义门控与候选多样性阶段

| 版本 | Tag | Commit | 核心内容 |
|------|-----|--------|---------|
| v0.8 | `reward-langgraph-v0.8` | `82a90b6` | 候选多样性诊断、cross-category fallback |
| v0.8.1 | `reward-langgraph-v0.8.1` | `5a27b79` | 真实 campaign（cosmetic patches 失败） |
| v0.8.2 | `reward-langgraph-v0.8.2` | `0416ae0` | Hard semantic patch gate + system preflight |
| v0.8.3 | `reward-langgraph-v0.8.3` | `48fafde` | Proposal-only 模式，semantic gate 端到端验证 |
| v0.8.4 | `reward-langgraph-v0.8.4` | `2972a9f` | Method-grounded semantic patch + syntax-safe regen |
| v0.8.5 | `reward-langgraph-v0.8.5` | `da7003d` | Semantic candidate bank（candidate_bank.jsonl） |
| v0.8.6 | `reward-langgraph-v0.8.6` | `4727bbf` | Candidate bank ranking + template diversity |
| v0.8.7 | `reward-langgraph-v0.8.7` | `241d22d` | DiversityScheduler + _mark_batch/exclude_ids 修复 |
| v0.8.8 | `reward-langgraph-v0.8.8` | `13093aa` | 真实 diversity campaign，3 candidates，diversity=1.0 |
| v0.8.9 | `reward-langgraph-v0.8.9` | `203f50c` | Candidate handoff artifacts 导出 |

**总计**: 26 个 tag，覆盖 v0.1 到 v0.8.9。

---

## 关键 Git 信息

| 项目 | 值 |
|------|-----|
| 仓库地址 | `https://github.com/Ma-mingliang/rewardopt-research-agent` |
| 主分支 | `main` |
| 当前最终分支 | `reward-langgraph-v0.8.9-candidate-bank-handoff` |
| 最终 tag | `reward-langgraph-v0.8.9` (commit `203f50c`) |
| HRRL2 env.py baseline hash | `e19703467be71e20` |
| baseline manifest | `docs/baselines/hrrl2_operational_baseline.yaml` |

---

## 关键文件索引

### 平台核心

| 文件 | 用途 |
|------|------|
| `README.md` | 完整安装和使用文档 |
| `pyproject.toml` | Python 依赖定义 |
| `environment.yml` | Conda 环境定义 |
| `.env.example` | API key 模板 |
| `configs/default.yaml` | 全局默认配置 |
| `run_optimizer.py` | 独立优化器 CLI 入口 |

### HRRL2 目标项目

| 文件 | 用途 |
|------|------|
| `HRRL2/env.py` | 环境定义（含 `__calculate_reward` 方法，优化目标） |
| `HRRL2/LQR.py` | Part 1: LQR 平衡控制训练入口 |
| `HRRL2/stanley.py` | Part 3: Stanley 路径跟踪训练入口 |
| `HRRL2/README.md` | HRRL2 使用文档 |
| `docs/baselines/hrrl2_operational_baseline.yaml` | 基线 hash manifest |

### v0.8.9 候选 Handoff

| 文件 | 用途 |
|------|------|
| `docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/README.md` | 使用说明 |
| `docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/top_candidates_summary.md` | 候选排序表 |
| `docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/candidate_metadata.json` | 机器可读元数据 |
| `docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/future_training_commands.md` | 训练命令模板（未执行） |
| `docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/candidate_patches/*.diff` | 3 个候选 patch |

### 交接与文档

| 文件 | 用途 |
|------|------|
| `docs/handovers/reward_langgraph_v0_8_9_handover.md` | 项目交接文档（完整技术细节） |
| `docs/getting-started/quickstart.md` | 本文件 |
| `docs/getting-started/method_pool_sample.jsonl` | 方法池样本（5 个方法，4 个类别） |
| `docs/reports/` | v0.1–v0.8.9 版本演进报告（26 个文件） |

### 代码模块

| 文件 | 用途 |
|------|------|
| `research_agent/core/semantic_patch_gate.py` | 语义门控（拒绝 cosmetic patches） |
| `research_agent/core/proposal_context.py` | 上下文提取（reward function bounds） |
| `research_agent/core/candidate_bank.py` | 候选库 + 排序 + 多样性分析 |
| `research_agent/core/baseline_guard.py` | 基线守卫（防止 env.py 被篡改） |
| `research_agent/core/system_preflight.py` | 系统预检（Windows pagefile） |
| `research_agent/core/executor.py` | 执行器（主循环，proposal-only 路径） |
| `research_agent/core/patch_repair.py` | 语法感知 patch repair |
| `research_agent/agents/reward_agent/optimizer.py` | LangGraph reward optimizer |
| `research_agent/agents/reward_agent/prompts.py` | LLM prompts（proposal, regeneration, fix） |
| `research_agent/agents/reward_agent/nodes.py` | LangGraph 图节点 |
| `research_agent/reward_methods/diversity_scheduler.py` | DiversityScheduler |
| `research_agent/reward_methods/selector.py` | MethodSelector |
| `research_agent/reward_methods/schema.py` | RewardMethodRecord |

---

## 方法池样本说明

`docs/getting-started/method_pool_sample.jsonl` 包含 5 个 reward shaping 方法：

| method_id | category | method_name | confidence |
|-----------|----------|-------------|------------|
| test_pbrs_001 | A_potential_based_reward | Potential-Based Reward Shaping (PBRS) | high |
| test_sparse_to_dense_002 | D_adaptive_dynamic_reward | Sparse-to-Dense Reward Shaping | medium |
| test_curriculum_003 | C_curriculum_subgoal_reward | Curriculum Reward Shaping | medium |
| test_risk_penalty_004 | B_safety_constraint_reward | Risk-Aware Penalty | high |
| test_control_energy_005 | D_adaptive_dynamic_reward | Control Energy Penalty | medium |

覆盖 4 个 reward 类别（A/B/C/D），用于测试 DiversityScheduler 的多类别调度。

---

## 常见问题

### 没有 API Key 怎么办？

使用路径 A（mock-LLM）。`--mock-llm` 标志跳过所有 LLM 调用，只验证代码路径。

### 测试失败怎么办？

```bash
# 查看详细输出
python -m pytest tests/ -v --tb=long

# 只运行特定测试
python -m pytest tests/test_semantic_patch_gate.py -v
python -m pytest tests/test_candidate_bank.py -v
python -m pytest tests/test_template_diversity_scheduler.py -v
```

### WinError 1455（页面文件太小）

这是 Windows CUDA 训练的已知问题。Proposal-only 模式不受影响。如需训练，增大页面文件到 32GB 或使用 CPU 模式。

### env.py hash 不匹配

```bash
conda run -n ra python -c "import hashlib; print(hashlib.sha256(open('HRRL2/env.py','rb').read()).hexdigest()[:16])"
# 预期: e19703467be71e20
# 如不匹配，恢复: cd HRRL2 && git checkout -- env.py
```

### HRRL2 依赖安装

HRRL2 需要额外的 RL 依赖，不在 research-agent 的 pyproject.toml 中：

```bash
pip install gymnasium torch stable_baselines3 pybullet pybullet_data numpy pandas
```

---

## 相关文档

- [完整 README](../../README.md) — 安装、配置、CLI 参考
- [HRRL2 README](../../HRRL2/README.md) — HRRL2 项目使用文档
- [项目交接文档](../handovers/reward_langgraph_v0_8_9_handover.md) — v0.8 系列完整技术细节
- [候选 handoff](../artifacts/reward_langgraph_v0_8_9_candidate_handoff/README.md) — 候选 patches 使用说明
- [版本报告](../reports/) — v0.1–v0.8.9 演进记录（26 个文件）
