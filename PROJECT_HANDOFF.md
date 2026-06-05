# Project Handoff: Research Optimization Agent Platform

## 1. 当前项目状态

本工作区目前主要产物是方案文档，不是已实现代码。

- 原始方案：`newplan.md`
- 当前可执行重构方案：`newplan.executable.md`

`newplan.md` 是早期单一 Reward Agent 方案，保留作为历史参考。后续实现应以 `newplan.executable.md` 为准。

当前最新定位已经从：

```text
Reward Research Agent
```

升级为：

```text
Research Optimization Agent Platform
```

核心变化是：reward 优化不再是整个系统，而只是平台下的一个 optimizer。

---

## 2. 系统定位

系统分为两层：

```text
前站主 Agent
+
后端科研优化执行平台
```

前站主 Agent 包括：

- Claude Code
- Hermes
- Codex
- OpenClaw

后端平台是：

```text
research-agent
```

用户不会直接细控 `research-agent` 的每条命令。用户会先告诉 Claude Code / Hermes / Codex 项目目标、约束、预算和关注指标，再由前站主 Agent 调用 `research-agent`。

`research-agent` 的职责是：

1. 理解项目。
2. 分类科研任务。
3. 选择优化策略。
4. 生成实验计划。
5. 收集、分类、选择相关论文。
6. 执行训练与评估。
7. 记录结果。
8. 更新知识库。
9. 跑满预算后生成报告。

---

## 3. V1 目标

V1 不追求一次性实现所有科研优化能力。V1 只实现：

```text
core platform
reward optimizer
residual_control optimizer
paper evidence pipeline
budget-run experiment scheduler
machine-readable state/report interface
```

V1 只预留接口，不自动实现：

```text
HPO
curriculum learning
observation/action space modification
algorithm replacement
network architecture search
```

这些任务可以被识别和建议，但不能在 V1 中自动 patch。

---

## 4. 目标架构

推荐源码结构：

```text
research_agent/
  core/
    project_understanding.py
    task_classifier.py
    strategy_selector.py
    experiment_planner.py
    executor.py
    result_analyzer.py
    knowledge_base.py
    report_writer.py
    state.py
    config.py
    exceptions.py
    output.py
    cache.py
    git_guard.py

  optimizers/
    reward/
    residual_control/
    hpo/
    curriculum/
    observation/
    action_space/

  literature/
    arxiv_searcher.py
    paper_reader.py
    paper_classifier.py
    paper_selector.py

  interfaces/
    cli.py
    json_protocol.py
    front_agent_contract.py

  execution/
    experiment_runner.py
    metric_parser.py
```

目标 CLI：

```bash
research-agent init --project <path>
research-agent understand --project <path>
research-agent classify-task
research-agent select-strategy
research-agent plan-experiments
research-agent search-papers
research-agent classify-papers
research-agent select-papers
research-agent extract-ideas
research-agent run-plan
research-agent run --phase <phase-id>
research-agent compare
research-agent status --json
research-agent resume
research-agent report --json
```

---

## 5. HRRL 项目重点适配

本平台的第一个重点适配目标是 HRRL / 残差控制类项目。

对于类似：

```text
Dynamic LQR + LQR Residual + Dynamic Stanley + Stanley Residual
```

平台应识别为：

```text
controller_residual_optimization
+ reward_optimization
+ safety_constraint_optimization
```

控制层权限：

| 层级 | 角色 | 权限 |
|------|------|------|
| Dynamic LQR | 基础平衡控制器 | 只读，不改 |
| LQR Residual RL | 平衡残差补偿 | 可优化 reward |
| Dynamic Stanley | 基础路径跟踪控制器 | 只读，不改 |
| Stanley Residual RL | 路径跟踪残差补偿 | 可优化 reward |

推荐策略：

1. LQR residual reward optimization。
2. Stanley residual reward optimization。
3. Safety-aware tracking penalty。
4. Residual magnitude penalty。
5. Potential-based tracking reward。

禁止自动修改：

- LQR 控制律。
- Stanley 控制律。
- PPO/SAC/TD3 算法主体。
- 网络结构。
- optimizer / loss / replay buffer。

---

## 6. Reward Optimizer 继承规则

Reward optimizer 是平台插件，不是平台本体。

它需要保留以下机制：

- objective / improve score
- primary / secondary / diagnostic metrics
- selected paper evidence Top-K
- reward-only patch guard
- candidate lifecycle
- immutable baseline
- candidate ledger
- degraded artifact cleanup
- current best local commit only
- no automatic GitHub push

Reward-only 定义：

```text
只能修改已定位 reward 函数内部，用于计算 scalar reward 的表达式、权重、reward term、penalty term、normalization 或组合逻辑。
```

禁止修改：

```text
observation/state space
action space
environment dynamics
termination/done/truncated
training algorithm
network architecture
optimizer/loss/scheduler
metric definition
```

---

## 7. 论文证据管线

论文不是随意灵感来源，而是确定性 evidence pipeline。

流程：

```text
search-papers
  -> classify-papers
  -> select-papers
  -> extract-ideas
```

每篇论文需要分类，例如：

```text
reward shaping
penalty and constraint design
robotics locomotion reward
control energy and smoothness
reward hacking and specification gaming
residual control
path tracking control
```

选择 Top-K 时必须使用确定性相关性分数：

```text
relevance_score =
  0.35 * objective_match
+ 0.25 * metric_match
+ 0.15 * state_action_match
+ 0.15 * implementation_feasibility
+ 0.10 * recency_or_influence
```

candidate proposal 只能引用 selected papers，不能临时从未选中的论文里挑依据。

---

## 8. 前站主 Agent Contract

前站主 Agent 必须在 `plan-experiments` 或 `run-plan` 前写入：

```text
objective
constraints
budget
metrics
forbidden_changes
```

没有这些内容时，`research-agent` 必须拒绝继续，并输出 JSON next action。

错误输出示例：

```json
{
  "ok": false,
  "error_code": "OBJECTIVE_MISSING",
  "message": "Objective is required before planning experiments.",
  "next_action": "Ask the front agent to write objective, metrics, constraints and budget."
}
```

`status --json` 至少返回：

```text
phase
active_experiment
budget_usage
current_best
blocking_issue
```

---

## 9. 实现优先级

建议实现顺序：

1. CLI + config + state + JSON protocol。
2. Project Understanding Layer。
3. Task Classifier。
4. Strategy Selector。
5. Experiment Planner。
6. Execution Layer。
7. Paper Evidence Pipeline。
8. Reward Optimizer。
9. Residual Control Optimizer。
10. Result Analyzer + Knowledge Base + Report。
11. Resume / cleanup / git guard。

不要一开始就写 reward patch 生成。必须先把平台前几步跑通：

```text
understand -> classify-task -> select-strategy -> plan-experiments
```

---

## 10. 验收重点

平台验收：

- `understand` 输出项目类型、控制结构、训练入口候选、可优化对象、禁止修改对象。
- `classify-task` 输出 task types、confidence、recommended strategies。
- `select-strategy` 基于 task classification 选择 optimizer。
- `plan-experiments` 输出 baseline、phase、训练命令、指标、预算。
- `status --json` 和 `report --json` 可被前站 Agent 稳定读取。
- `resume` 可从中断状态恢复。

HRRL 验收：

- 识别 Dynamic LQR + LQR Residual + Dynamic Stanley + Stanley Residual。
- 分类为 controller_residual_optimization + reward_optimization + safety_constraint_optimization。
- patch guard 拒绝修改 LQR / Stanley 控制律。
- 实验计划包含 baseline、LQR residual reward、Stanley residual reward、safety-aware tracking、joint validation。

Reward optimizer 验收：

- selected papers 必须先分类、打分、Top-K 确定性选择。
- candidate 必须引用 selected papers。
- improve score 使用 objective 权重。
- baseline 不清理、不覆盖。
- degraded candidate 清理重资产但保留 ledger。
- budget 跑满后生成 final report。

---

## 11. 当前注意事项

- `newplan.executable.md` 是最新正式方案。
- `newplan.md` 是历史原始方案，不应作为实现依据。
- 当前仓库中还没有真正实现 `research-agent` 代码。
- 当前两个 Markdown 文件都是未跟踪状态，尚未提交。
- 后续实现前建议先创建独立分支或 worktree。

---

## 12. 一句话交接

请不要实现单一 Reward Agent。请实现一个可被 Claude Code / Hermes / Codex 调用的 `Research Optimization Agent Platform`，先理解项目和分类科研任务，再选择 optimizer；V1 重点实现平台骨架、reward optimizer 和 residual_control optimizer，HRRL 是首个重点适配项目。

