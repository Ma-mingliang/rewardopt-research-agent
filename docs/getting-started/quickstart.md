# 快速开始：运行你的第一个基本测试

本指南帮助你在 10 分钟内验证 research-agent 平台是否正常工作。提供三条路径，从简到繁。

---

## 前置条件

| 条件 | 说明 |
|------|------|
| Python | >= 3.11 |
| Git | 任意版本 |
| Conda（推荐） | 或使用 venv |
| LLM API Key | 仅路径 B/C 需要；路径 A 不需要 |
| HRRL2 项目 | 仅路径 C 需要；路径 A/B 不需要 |

---

## 路径 A：Mock-LLM 冒烟测试（无需 API Key，无需 HRRL2）

最快的验证方式。使用 mock LLM，不调用真实 API，不训练，不 eval。

```bash
# 1. 克隆并安装
git clone <repo-url> research-agent
cd research-agent
conda create -n ra python=3.11 -y
conda activate ra
pip install -e ".[dev,langgraph]"

# 2. 验证 CLI
research-agent --help

# 3. 运行 mock-LLM optimizer（无需 API key）
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

## 路径 B：真实 LLM Proposal-Only 测试（需要 API Key，无需 HRRL2）

验证 LLM 连接和 semantic patch generation 是否工作。

```bash
# 1. 配置 API key
cp .env.example .env
# 编辑 .env，填入 MIMO_API_KEY

# 2. 初始化测试项目（如不存在）
research-agent init --project test_accept

# 3. 运行 proposal-only campaign（不训练，不 eval）
python run_optimizer.py \
  --project test_accept \
  --optimizer reward_langgraph \
  --max-iterations 2 \
  --batch-size 1 \
  --proposal-only \
  --reward-method-pool docs/getting-started/method_pool_sample.jsonl \
  --reward-method-top-k 3 \
  --max-semantic-regeneration-attempts 2

# 4. 查看结果
ls test_accept/.research-agent/runs/
# 找到最新 run 目录，查看 summary.json
```

**预期结果：**
- LLM 被调用，生成 reward patch 候选
- semantic gate 检查每个 patch
- 运行日志在 `test_accept/.research-agent/runs/<run_id>/`
- `summary.json` 包含 `semantic_gate_passed_count` 等字段
- 不训练，不 eval，`train_called=false`

---

## 路径 C：完整 Reward 优化测试（需要 API Key + HRRL2）

验证从候选生成到 handoff 的完整流程。需要 HRRL2 项目已配置。

### 前置条件

```bash
# HRRL2 必须已存在且已初始化
ls HRRL2/env.py  # 确认存在

# 确认 env.py hash
python -c "import hashlib; print(hashlib.sha256(open('HRRL2/env.py','rb').read()).hexdigest()[:16])"
# 预期输出: e19703467be71e20
```

### 运行

```bash
# 1. 配置 API key（如未配置）
cp .env.example .env
# 编辑 .env，填入 MIMO_API_KEY

# 2. 确认 execution python 路径
# Windows 示例: E:/Anaconda/envs/RL2/python.exe
# Linux 示例: /usr/bin/python3

# 3. 运行 proposal-only diversity campaign
python run_optimizer.py \
  --project HRRL2 \
  --optimizer reward_langgraph \
  --max-iterations 5 \
  --batch-size 1 \
  --execution-python <你的execution-python路径> \
  --reward-method-pool docs/getting-started/method_pool_sample.jsonl \
  --reward-method-top-k 3 \
  --staged-eval \
  --proposal-only \
  --max-semantic-regeneration-attempts 2 \
  --baseline-manifest docs/baselines/hrrl2_operational_baseline.yaml

# 4. 查看结果
ls HRRL2/.research-agent/runs/
```

**预期结果：**
- `summary.json` 包含 `template_diversity_score`, `semantic_gate_passed_count` 等
- `candidate_bank.jsonl` 包含 validation-ready patches
- `train_called=false`, `full_eval_called=false`
- env.py hash 未改变

### 应用候选 patch（可选）

```bash
# 查看候选
cat docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/top_candidates_summary.md

# 应用 top 1 candidate（不训练，仅验证 patch 可用）
cd HRRL2
git apply ../docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/candidate_patches/test_control_energy_005.diff
python -c "compile(open('env.py','r',encoding='utf-8-sig').read(), 'env.py', 'exec'); print('compile OK')"
git checkout -- env.py
```

---

## 关键文件说明

| 文件 | 用途 |
|------|------|
| `README.md` | 完整安装和使用文档 |
| `pyproject.toml` | Python 依赖定义 |
| `.env.example` | API key 模板 |
| `configs/default.yaml` | 全局默认配置 |
| `docs/baselines/hrrl2_operational_baseline.yaml` | 基线 hash manifest |
| `docs/getting-started/method_pool_sample.jsonl` | 方法池样本（5 个方法，4 个类别） |
| `docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/` | v0.8.9 候选 patches 和元数据 |
| `docs/handovers/reward_langgraph_v0_8_9_handover.md` | 项目交接文档 |
| `docs/reports/` | v0.1-v0.8.9 版本演进报告 |
| `tests/` | 单元测试（35 个文件） |

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
```

### WinError 1455（页面文件太小）

这是 Windows CUDA 训练的已知问题。Proposal-only 模式不受影响。如需训练，增大页面文件到 32GB 或使用 CPU 模式。

### env.py hash 不匹配

```bash
python -c "import hashlib; print(hashlib.sha256(open('HRRL2/env.py','rb').read()).hexdigest()[:16])"
# 预期: e19703467be71e20
# 如不匹配，恢复: cd HRRL2 && git checkout -- env.py
```

---

## 相关文档

- [完整 README](../../README.md) — 安装、配置、CLI 参考
- [项目交接文档](../handovers/reward_langgraph_v0_8_9_handover.md) — v0.8 系列完整技术细节
- [候选 handoff](../artifacts/reward_langgraph_v0_8_9_candidate_handoff/README.md) — 候选 patches 使用说明
- [版本报告](../reports/) — v0.1-v0.8.9 演进记录
