# Research Optimization Agent Platform V1.0 可执行方案

> 本文档是 `newplan.md` 的独立重构版。原文件保持不变。
> 新定位：Claude Code / Hermes / Codex / OpenClaw 是前站主 Agent，`research-agent` 是后端科研优化执行平台。

---

## 〇、执行计划声明

本文档是 V1 的唯一正式依据，同时承担**产品规格、接口契约和实施计划**三种角色。实现 Agent 不应再回退到 `newplan.md`，也不应把本文拆成多个互相漂移的方案文件。

实施顺序必须先建立平台骨架和机器可读协议，再进入 optimizer patch 生成：

```text
CLI + config + state + JSON protocol
  -> init
  -> understand
  -> classify-task
  -> select-strategy
  -> plan-experiments
  -> paper evidence pipeline
  -> execution scheduler
  -> reward/residual_control optimizers
  -> report/resume/cleanup/git guard
```

V1 第一验收闭环是：

```text
research-agent init --project <path>
research-agent understand --project <path> --json
research-agent classify-task --json
research-agent select-strategy --json
research-agent plan-experiments --json
```

禁止一开始实现 reward patch 生成。只有当前站 contract、state、JSON 输出、实验计划和安全边界全部稳定后，才能实现 optimizer candidate patch 生命周期。

---

## 一、总目标与定位

构建一个长期挂机式 `Research Optimization Agent Platform`，用于科研代码项目的自动理解、任务分类、策略选择、实验规划、训练执行、结果分析和知识沉淀。

`research-agent` 不再是单一奖励函数优化工具。Reward 优化只是平台下的一个 optimizer。V1 重点实现平台骨架，并首发支持：

- `optimizers/reward`：奖励函数优化。
- `optimizers/residual_control`：残差控制科研优化，面向 HRRL、LQR residual、Stanley residual 等项目。

### 1.1 前站主 Agent 与后端平台分工

```text
Human
  ↓
Claude Code / Hermes / Codex / OpenClaw
  ↓
research-agent
  ↓
project + experiments + reports
```

- Human 不需要直接细控每条 CLI 命令。
- 前站主 Agent 负责理解用户目标、读取项目、整理 objective / constraints / budget / metrics / forbidden changes。
- `research-agent` 负责执行科研优化工作流，并输出 machine-readable state / status / reports。
- `research-agent` 不是主要对话 Agent，而是可被前站 Agent 稳定调用的科研执行后端。

### 1.2 平台核心流程

```text
understand project
  -> classify research task
  -> select strategy
  -> plan experiments
  -> collect/classify/select papers
  -> run plan
  -> analyze result
  -> update knowledge base
  -> continue until budget exhausted or hard stop
  -> report
```

最关键原则：

1. 先理解项目，再选择优化策略。
2. 不预设所有项目都要改 reward。
3. 不因连续失败、无提升或 plateau 提前停止；默认跑满预算。
4. 所有自动修改必须受 optimizer 的权限边界约束。
5. 所有结果必须可恢复、可审计、可由前站 Agent 读取。

### 1.2.1 进程生命周期模型

`research-agent` 不是常驻 daemon，不使用 systemd / tmux / 计划任务。采用**前站 Agent 按需 subprocess 调用**模型：

```text
前站 Agent (Claude Code / Hermes / Codex / OpenClaw)
  │
  │  subprocess 调用 CLI 命令
  │  stdout/stderr 捕获
  │  exit code 判定
  │
  └─> research-agent <command> [--json]
        │
        ├─ 短命令 (init, understand, classify-task, status, report): 同步返回，exit 0/非 0
        │
        └─ 长命令 (run-plan, run --phase): 持续执行，完成后 exit 0/非 0
```

**崩溃恢复职责划分：**

| 场景 | 检测方 | 响应方 | 响应动作 |
|------|--------|--------|---------|
| 命令 exit 0 | 前站 Agent | 前站 Agent | 读取 `status --json`，决定下一步 |
| 命令 exit 非 0 | 前站 Agent | 前站 Agent | 读取 stderr / `status --json`，调用 `resume` |
| 命令超时（超过预期时长 2x） | 前站 Agent | 前站 Agent | 发 SIGTERM，等 30s，发 SIGKILL，调用 `resume` |
| 前站 Agent 本身崩溃 | Human | Human | 手动重新启动前站 Agent，前站 Agent 调用 `resume` |
| 机器重启 | Human | Human | 重启后前站 Agent 调用 `resume` |

**不需要 watchdog。** 前站 Agent 本身就是 watchdog：它发起调用、等待结果、处理异常。`research-agent` 只负责执行一次命令然后退出。

**进程管理约束：**

- 每个 CLI 命令是一个独立进程，执行完毕必须退出。
- `run-plan` 是长命令（可能运行数天），但仍然是单一进程，不是 daemon。
- `run-plan` 内部通过 SIGTERM 信号处理实现 graceful shutdown：收到信号后保存 state、回滚未完成 candidate、退出。
- Windows 上使用 `signal.SIGTERM` / `signal.SIGBREAK` 替代方案（`SetConsoleCtrlHandler`）。
- 前站 Agent 必须记录每次调用的 PID 和启动时间，用于超时检测。

### 1.3 V1 支持识别的科研任务类型

V1 的 task classifier 至少识别以下类型：

```text
reward_optimization
hyperparameter_optimization
curriculum_design
observation_optimization
action_space_optimization
safety_constraint_optimization
controller_residual_optimization
training_stability_optimization
algorithm_selection
paper_driven_experiment_design
```

V1 自动实现：

- core platform。
- reward optimizer。
- residual_control optimizer。
- paper evidence pipeline。
- budget-run experiment scheduler。
- machine-readable state/report interface。

V1 只预留接口，不自动实现：

- HPO。
- curriculum。
- observation/action space modification。
- algorithm replacement。
- network architecture search。

### 1.4 HRRL 项目默认理解

对于类似 `Dynamic LQR + LQR Residual + Dynamic Stanley + Stanley Residual` 的 HRRL 项目，平台应识别为：

```text
controller_residual_optimization
+ reward_optimization
+ safety_constraint_optimization
```

控制层理解：

| 层级 | 角色 | 权限 |
|------|------|------|
| Dynamic LQR | 基础平衡控制器 | 只读，不改 |
| LQR Residual RL | 平衡残差补偿 | 可优化 reward |
| Dynamic Stanley | 基础路径跟踪控制器 | 只读，不改 |
| Stanley Residual RL | 路径跟踪残差补偿 | 可优化 reward |

推荐优先策略：

1. LQR residual reward optimization。
2. Stanley residual reward optimization。
3. safety-aware tracking penalty。
4. residual magnitude penalty。
5. potential-based tracking reward。

暂不建议：

1. 修改 LQR 控制律。
2. 修改 Stanley 控制律。
3. 修改 PPO/SAC/TD3 算法主体。
4. 修改网络结构。

---

## 二、目录结构与路径

必须严格区分三个路径：

| 名称 | 含义 | 示例 |
|------|------|------|
| `agent_root` | `research-agent` 工具源码目录 | 安装包所在目录 |
| `project_root` | 被研究的科研项目目录 | `E:\Code\python\HRRL0` |
| `work_dir` | 目标项目内的平台工作目录 | `<project_root>\.research-agent` |

所有运行时产物必须写入 `work_dir`，不能写入工具源码目录。

### 2.1 工具源码结构

```text
research-agent/
  pyproject.toml
  README.md
  .env.example
  research_agent/
    __init__.py
    core/
      __init__.py
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
      exceptions.py      # 见下方异常类定义
      output.py
      cache.py
      git_guard.py
      llm_client.py      # LLMClient, LLMResponse
    optimizers/
      __init__.py
      reward/
        __init__.py
        reward_locator.py
        reward_proposer.py
        patch_guard.py
        objective.py
        candidate_ledger.py
        cleanup.py
      residual_control/
        __init__.py
        control_stack_scanner.py
        residual_reward_proposer.py
        safety_gate_analyzer.py
        residual_patch_guard.py
      hpo/
        __init__.py
      curriculum/
        __init__.py
      observation/
        __init__.py
      action_space/
        __init__.py
    literature/
      __init__.py
      arxiv_searcher.py
      paper_reader.py
      paper_classifier.py
      paper_selector.py
    interfaces/
      __init__.py
      cli.py
      json_protocol.py
      front_agent_contract.py
    execution/
      __init__.py
      experiment_runner.py
      metric_parser.py      # MetricParser 类，被 Optimizer.run_candidate 调用，实现 metric_regex 解析逻辑
  configs/
    default.yaml
  skills/
    hermes/
      research-agent/
        SKILL.md
  tests/
```

**.env.example 内容：**

```text
# LLM API 配置
MIMO_API_KEY=your_api_key_here

# 可选：覆盖 default.yaml 中的 base_url
# MIMO_BASE_URL=https://token-plan-sgp.xiaomimimo.com/v1

# 可选：arxiv API 配置（默认无需 API key）
# ARXIV_MAX_RESULTS=50

# 可选：磁盘空间警告阈值（字节，默认 1073741824 = 1GB）
# DISK_SPACE_WARN_BYTES=1073741824
```

**skills/hermes/research-agent/SKILL.md 内容：**

````markdown
---
name: research-agent
description: Research optimization agent platform for automated RL project understanding, task classification, experiment planning, and reward optimization.
trigger: When the user mentions research optimization, reward optimization, RL training, experiment planning, or references a research project that needs optimization.
---

# Research Agent Skill

## What it does

`research-agent` is a backend research optimization platform. It:
1. Understands a research project's structure and control stack
2. Classifies research tasks (reward optimization, residual control, HPO, etc.)
3. Selects optimization strategies
4. Plans experiments with phase DAG
5. Searches and classifies arxiv papers for evidence
6. Runs optimization candidates with screening + full evaluation
7. Reports results in machine-readable format

## How to use

### Prerequisites
- Python 3.10+
- `research-agent` installed (`pip install -e .` in the source directory)
- LLM API key set in `.env` or environment variable

### Workflow

```bash
# 1. Initialize project
research-agent init --project /path/to/project

# 2. Write objective (edit .research-agent/front_agent_objective.json)
#    Fill in objective, constraints, budget, metrics

# 3. Understand project
research-agent understand --project /path/to/project --json

# 4. Classify tasks
research-agent classify-task --json

# 5. Select strategy
research-agent select-strategy --json

# 6. Plan experiments
research-agent plan-experiments --json

# 7. Search and select papers
research-agent search-papers --json
research-agent classify-papers --json
research-agent select-papers --json

# 8. Run plan
research-agent run-plan --json

# 9. Get report
research-agent report --json
```

### JSON Protocol

All commands support `--json` flag. Errors return:
```json
{"ok": false, "error_code": "OBJECTIVE_MISSING", "message": "Objective is required before planning experiments.", "next_action": "Ask the front agent to write objective, metrics, constraints and budget."}
```

### Resume after interruption

```bash
research-agent resume --json
```

### Check status during long runs

```bash
research-agent status --json
```
````

### 2.2 目标项目工作目录

`research-agent init --project <project_root>` 创建：

**重复 init 行为：**

| 场景 | 行为 |
|------|------|
| `.research-agent/` 不存在 | 创建完整目录结构和空模板 |
| `.research-agent/` 存在，`state.json` 不存在 | 覆盖目录结构，保留已有文件 |
| `.research-agent/` 存在，`state.json` 存在且 `phase` 为 `initialized` | 覆盖 config.yaml 和空模板，保留 state.json |
| `.research-agent/` 存在，`state.json` 存在且 `phase` 不为 `initialized` | 输出 `{"ok": false, "error_code": "ALREADY_INITIALIZED", "message": "Project already initialized and has progressed. Use 'resume' to continue, or delete .research-agent/ to re-init."}` |

`ALREADY_INITIALIZED` 保护已填充的 `front_agent_objective.json` 和已有进度不被意外覆盖。

**`metric_regex` 优先级：** `front_agent_objective.json` 中的 `metrics.metric_regex` 优先于 `config.yaml` 中的 `metric_regex`。`config.yaml` 仅作为 fallback（当 objective 未定义某 metric 的 regex 时使用 config 中的定义）。合并语义为 per-metric：如果 objective 定义了 metric X 的 regex，使用 objective 的；否则使用 config.yaml 的 metric_regex[X]。两个来源按 metric name 逐项合并，不是整体替换。

**`project_path` 读取规则：** 除 `init` 和 `understand`（显式接收 `--project`）外，所有命令从 `state.json` 的 `project_path` 字段读取项目路径。如果 `state.json` 缺少 `project_path` 或该字段为空，命令以 `{"ok": false, "error_code": "PROJECT_PATH_MISSING", "message": "state.json is missing project_path.", "next_action": "Re-run init --project <path> or repair state.json."}` 退出。

```text
<project_root>/.research-agent/
  config.yaml
  state.json
  lock
  reports/
    front_agent_objective.md
    project_understanding.md
    project_understanding.json
    task_classification.json
    strategy_selection.md
    strategy_selection.json
    experiment_plan.md
    experiment_plan.json
    arxiv_papers.md
    paper_taxonomy.md
    selected_reward_evidence.md
    candidate_ledger.md
    extracted_ideas.md
    knowledge_base.md
    final_report.md
    final_report.json
    # candidate_ledger.md 格式：每个 candidate 一行，表格形式
    # | candidate_id | optimizer | phase_id | status | improve_score | rejection_reason | evidence_refs |
    # 内容与 logs/candidates.jsonl 一致，但以 Markdown 表格呈现供人类阅读。
    # 由 executor 在每次 candidate 状态变更时自动更新（append 或 modify 行）。
    # `report` 命令也会重新生成此文件。
  logs/
    events.jsonl
    experiments.jsonl
    candidates.jsonl
    paper_taxonomy.jsonl
    selected_reward_evidence.jsonl
    extracted_ideas.jsonl
    arxiv_papers.jsonl
    llm_calls.jsonl
  patches/
  cache/
  artifacts/
```

所有 state 中保存的路径都必须相对 `work_dir`，但 `project_path` 必须保存为绝对路径。

**机器可读产物规则：**

- Markdown 报告只供 Human / 前站 Agent 展示阅读，不作为执行输入。
- JSON 报告才是 `research-agent` 内部执行和前站 Agent 读取的稳定协议。
- `executor.py` 只能读取 `state.json` 和 `reports/experiment_plan.json` 执行 phase，不能解析 `experiment_plan.md`。
- `report --json` 必须读取 state/logs 并生成 `reports/final_report.json`，stdout 输出同一个 JSON 对象。
- 任一 `*.json` artifact 写入前必须先通过 `json.dumps` / `json.loads` 往返验证，失败时命令返回 `JSON_ARTIFACT_INVALID`。

**日志文件 schema：**

`logs/events.jsonl`（所有平台事件）：

```jsonl
{"timestamp": "2026-06-05T12:00:00Z", "event": "phase_started", "phase_id": "lqr-residual", "details": {}}
{"timestamp": "2026-06-05T12:05:00Z", "event": "candidate_proposed", "candidate_id": "cand_rew_001", "details": {"optimizer": "reward"}}
{"timestamp": "2026-06-05T12:10:00Z", "event": "candidate_guarded", "candidate_id": "cand_rew_001", "details": {"allowed": true}}
{"timestamp": "2026-06-05T13:00:00Z", "event": "candidate_screening_completed", "candidate_id": "cand_rew_001", "details": {"improve_score": 0.03, "verdict": "promoted"}}
{"timestamp": "2026-06-05T15:00:00Z", "event": "candidate_accepted", "candidate_id": "cand_rew_001", "details": {"improve_score": 0.08}}
{"timestamp": "2026-06-05T15:00:00Z", "event": "current_best_updated", "candidate_id": "cand_rew_001", "details": {"commit_hash": "abc123"}}
{"timestamp": "2026-06-05T18:00:00Z", "event": "budget_check", "details": {"wall_clock_seconds": 21600, "candidates": 5, "full_evals": 2}}
# budget_check 在每个 candidate lifecycle 状态转换时触发（proposed→patch_generated→guarded→screening→promoted→full_eval）
```

event 枚举：`phase_started`, `phase_completed`, `candidate_proposed`, `candidate_patch_generated`, `candidate_guarded`, `candidate_guard_rejected`, `candidate_screening_started`, `candidate_screening_completed`, `candidate_fulleval_started`, `candidate_fulleval_completed`, `candidate_accepted`, `candidate_rejected`, `candidate_needs_more_evidence`, `candidate_archive_inconclusive`, `candidate_needs_revisit`, `current_best_updated`, `budget_check`, `budget_exhausted`, `user_interrupt`, `error`, `resume`, `cleanup`, `literature_search_started`, `literature_search_completed`, `literature_classify_started`, `literature_classify_completed`, `literature_select_started`, `literature_select_completed`, `joint_validation_started`, `joint_validation_completed`, `joint_validation_conflict`.

`logs/experiments.jsonl`（每次训练/评估的详细结果）：

```json
{
  "timestamp": "2026-06-05T12:30:00Z",
  "candidate_id": "cand_rew_001",
  "phase_id": "lqr-residual",
  "stage": "screening",
  "seed": 42,
  "train_command": "python train.py --reward-version cand_rew_001",
  "eval_command": "python eval.py --seed 42",
  "exit_code": 0,
  "duration_seconds": 1800,
  "metrics": {"fall_rate": 0.09, "balance_error": 0.13, "mean_reward": 245.6},
  "log_path": "artifacts/cand_rew_001/screening/seed_42/stdout.log"
}
```

`logs/candidates.jsonl`（candidate 生命周期记录）：

**candidate `status` 枚举（完整列表）：**

`proposed`, `patch_generated`, `guarded`, `screening`, `promoted`, `full_eval`, `accepted`, `rejected`, `needs_more_evidence`, `archive_inconclusive`, `needs_revisit`

```json
{
  "candidate_id": "cand_rew_001",
  "optimizer": "reward",
  "phase_id": "lqr-residual",
  "status": "accepted",
  "created_at": "2026-06-05T12:05:00Z",
  "updated_at": "2026-06-05T15:00:00Z",
  "proposal": {"description": "Increase tracking error penalty weight by 20%", "evidence_refs": ["arxiv:2401.12345"]},
  "patch_path": "patches/cand_rew_001.patch",
  "improve_score": 0.08,
  "rejection_reason": null,
  "reward_hacking_flags": [],
  "metrics_summary": {"fall_rate": {"baseline": 0.15, "candidate": 0.08, "change_pct": -0.467}},
  "git_commit": "abc123"
}
```

`logs/llm_calls.jsonl`：见 3.4 节 LLM 调用层定义。

**日志轮转策略：**

336 小时运行期间，日志文件可能增长到 GB 级。采用以下轮转策略：

| 文件 | 轮转条件 | 轮转方式 | 保留 |
|------|---------|---------|------|
| `logs/events.jsonl` | 文件 > 50MB | 重命名为 `events.jsonl.1`，新建 `events.jsonl` | 最近 3 个轮转文件 |
| `logs/experiments.jsonl` | 文件 > 100MB | 同上 | 最近 3 个 |
| `logs/candidates.jsonl` | 不轮转 | 文件通常很小（每个 candidate 一行） | 全部保留 |
| `logs/extracted_ideas.jsonl` | 不轮转 | 文件很小（最多 20 个 idea），status 字段原地更新（不追加新行） | 全部保留 |
| `logs/arxiv_papers.jsonl` | 不轮转 | 文件很小（论文列表） | 全部保留 |
| `logs/llm_calls.jsonl` | 文件 > 50MB | 同上 | 最近 3 个 |
| `artifacts/*/stdout.log` | candidate 被 cleanup 后 | 随 cleanup 一起删除 | accepted candidate 保留 |

轮转在每次写入前检查。轮转操作本身不获取额外 lock，但只在持有 `.research-agent/lock` 的进程（即 mutating 命令）中执行。`status --json` 等只读命令不写日志，不触发轮转。因此不存在竞态条件。

---

## 三、配置与 Front-Agent Contract

### 3.1 配置优先级

```text
CLI 参数 > <project_root>/.research-agent/config.yaml > research_agent/configs/default.yaml
```

`init` 时把默认配置复制到目标项目的 `.research-agent/config.yaml`。后续命令只读取项目级配置，除非显式传入 `--config`。

### 3.2 前站主 Agent 必填内容

前站主 Agent 通过写入 `.research-agent/front_agent_objective.json` 文件来提交所有必填信息。不使用 CLI 子命令，直接写文件。`research-agent init` 创建该文件的空模板，前站 Agent 填充后，后续命令自动读取。

**硬契约：** `plan-experiments` 和 `run-plan` 之前，`front_agent_objective.json` 必须显式包含 `objective`、`constraints`、`constraints.forbidden_changes`、`budget`、`metrics.primary`，并且每个 primary/safety metric 必须有可用 `metric_regex`。空对象、空数组和空字符串不视为已填写。`default.yaml` 只能补字段内部默认值，不能替代缺失的前站 contract。

**写入方式：**

前站 Agent 直接写入 JSON 文件到 `<project_root>/.research-agent/front_agent_objective.json`。

**文件格式（front_agent_objective.json）：**

```json
{
  "objective": {
    "name": "optimize_lqr_residual_reward",
    "description": "Improve LQR residual RL agent's balance stability and reduce fall rate while maintaining control energy within bounds.",
    "focus": ["fall_rate", "balance_error", "episode_length"]
  },
  "constraints": {
    "forbidden_changes": [
      "algorithm_body",
      "network_architecture",
      "optimizer",
      "loss",
      "replay_buffer",
      "base_controller_law"
    ],
    "require_human_review_for": [
      "observation_space_change",
      "action_space_change",
      "termination_logic_change"
    ]
  },
  "budget": {
    "wall_clock_hours": 336,
    "gpu_hours": null,
    "max_candidates": 50,
    "max_full_evals": 20
  },
  "metrics": {
    "primary": [
      {
        "name": "fall_rate",
        "direction": "lower_is_better",
        "weight": 0.4,
        "min_improvement_pct": 0.01,
        "max_regression_pct": 0.10
      },
      {
        "name": "balance_error",
        "direction": "lower_is_better",
        "weight": 0.35,
        "min_improvement_pct": 0.01,
        "max_regression_pct": 0.10
      },
      {
        "name": "episode_length",
        "direction": "higher_is_better",
        "weight": 0.25,
        "min_improvement_pct": 0.02,
        "max_regression_pct": 0.15
      }
    ],
    "safety": [
      {
        "name": "residual_magnitude",
        "direction": "lower_is_better",
        "weight": 1.0,
        "hard_violation_threshold": 0.50
      },
      {
        "name": "control_energy",
        "direction": "lower_is_better",
        "weight": 0.8,
        "hard_violation_threshold": 0.30
      }
    ],
    "diagnostic": [
      {
        "name": "mean_reward",
        "direction": "higher_is_better"
      },
      {
        "name": "episode_length_std",
        "direction": "lower_is_better"
      }
    ],
    "metric_regex": {
      "fall_rate": {
        "log_file": "stdout",
        "regex": "fall_rate\\s*[=:]\\s*([\\-\\d\\.]+)",
        "group": 1,
        "aggregate": "last"
      }
    }
  }
}
```

**字段约束：**

| 字段 | 类型 | 必填 | 默认值 |
|------|------|------|--------|
| `objective.name` | string | 是 | 无 |
| `objective.description` | string | 是 | 无 |
| `objective.focus` | list[string] | 否 | `[]` |
| `constraints` | object | 是 | 无 |
| `constraints.forbidden_changes` | list[string] | 是 | 无 |
| `constraints.require_human_review_for` | list[string] | 否 | 从 default.yaml 继承 |
| `budget` | object | 是 | 无 |
| `budget.wall_clock_hours` | number | 是 | 无 |
| `budget.max_candidates` | number \| null | 否 | null（无上限） |
| `budget.max_full_evals` | number \| null | 否 | null（无上限） |
| `metrics.primary` | list[MetricSpec] | 是 | 无 |
| `metrics.safety` | list[MetricSpec] | 否 | `[]` |
| `metrics.diagnostic` | list[MetricSpec] | 否 | `[]` |
| `metrics.metric_regex` | object | 是 | 无 |

**以下字段不在 `front_agent_objective.json` 中，从 `config.yaml` 的 `objective` 节读取：**

| 字段 | config.yaml 路径 | 默认值 |
|------|-----------------|--------|
| `primary_score_threshold` | `objective.primary_score_threshold` | 0.05 |
| `hard_primary_regression_policy` | `objective.hard_primary_regression_policy` | "reject" |
| `mean_reward_role` | `objective.mean_reward_role` | "diagnostic_only" |

**MetricSpec 格式：**

```json
{
  "name": "fall_rate",
  "direction": "lower_is_better",
  "weight": 0.4,
  "min_improvement_pct": 0.01,
  "max_regression_pct": 0.10,
  "hard_violation_threshold": 0.50
}
```

- `name`：metric 名称，必须与 `metric_regex` 中的 key 匹配。
- `direction`：`"lower_is_better"` 或 `"higher_is_better"`。
- `weight`：在综合分数中的权重（primary metrics 之间归一化）。
- `min_improvement_pct`：单 metric 最小改善百分比，低于此值不算真正改善（默认 0.01）。
- `max_regression_pct`：单 metric 最大退化百分比，超过则直接 reject（默认 0.10）。
- `hard_violation_threshold`：仅 safety metrics 使用，超过此值为 hard violation。

**Metric regex 硬校验：**

- 每个 `metrics.primary[].name` 必须在合并后的 `metric_regex` 中存在。
- 每个 `metrics.safety[].name` 必须在合并后的 `metric_regex` 中存在。
- diagnostic metric 没有 regex 时只跳过 diagnostic 解析并记录 warning，不阻塞 `plan-experiments`。
- `understand` 输出的 `metric_output_locations[].pattern` 只能作为人工建议，不能自动参与运行时 metric 解析。

**缺失检测：**

| 缺失字段 | error_code | 阻塞命令 |
|----------|-----------|---------|
| `objective` 不存在或为空对象 | `OBJECTIVE_MISSING` | plan-experiments, run-plan |
| `objective.name` 为空字符串 | `OBJECTIVE_MISSING` | plan-experiments, run-plan |
| `objective.description` 为空字符串 | `OBJECTIVE_MISSING` | plan-experiments, run-plan |
| `metrics.primary` 为空列表 | `METRICS_MISSING` | plan-experiments, run-plan |
| primary/safety metric 缺少 regex | `METRIC_REGEX_MISSING` | plan-experiments, run-plan |
| `budget` 不存在或为空对象 | `BUDGET_MISSING` | plan-experiments, run-plan |
| `budget.wall_clock_hours` 缺失或不大于 0 | `BUDGET_MISSING` | plan-experiments, run-plan |
| `constraints` 不存在或为空对象 | `CONSTRAINTS_MISSING` | plan-experiments, run-plan |
| `constraints.forbidden_changes` 缺失或为空列表 | `FORBIDDEN_CHANGES_MISSING` | plan-experiments, run-plan |

`understand` 和 `classify-task` 不需要 objective，可以先执行。

**Objective 写入时机：**

```text
init
  -> 前站 Agent 写入 front_agent_objective.json（至少 objective、constraints、budget、metrics.primary、metric_regex）
  -> understand（不需要 objective）
  -> classify-task（不需要 objective）
  -> 前站 Agent 可补全 front_agent_objective.json（safety/diagnostic metrics、metric_regex、human review rules）
  -> select-strategy（不需要 objective）
  -> plan-experiments（执行完整 hard contract 检查）
  -> search/classify/select papers
  -> run-plan（再次执行完整 hard contract 检查）
```

`plan-experiments` 和 `run-plan` 在执行时读取 `front_agent_objective.json`。如果文件在 init 后从未写入或关键字段为空，返回对应 error_code。

`understand` 的 LLM prompt 不需要 objective.focus。它通过扫描项目文件来理解项目，不依赖用户输入的目标。

`init` 创建的空模板：

```json
{
  "objective": {},
  "constraints": {},
  "budget": {},
  "metrics": {
    "primary": [],
    "safety": [],
    "diagnostic": [],
    "metric_regex": {}
  }
}
```

### 3.3 default.yaml

```yaml
llm:
  provider: openai_compatible
  model: mimo-v2.5-pro
  base_url: "https://token-plan-sgp.xiaomimimo.com/v1"
  api_key_env: "MIMO_API_KEY"
  timeout_seconds: 120
  max_retries: 3
  retry_delay_seconds: 5
  max_tokens: 4096
  qps: 2.0

project:
  path: ""
  python_file_globs: ["**/*.py"]
  ignore_dirs:
    - ".git"
    - ".venv"
    - "venv"
    - "__pycache__"
    - "logs"
    - "runs"
    - "wandb"
    - "checkpoints"
    - "node_modules"

front_agent:
  required: true
  allowed_callers:  # 信息性配置，CLI 无法自动校验调用者身份。用于文档和日志记录。
    - "claude_code"
    - "hermes"
    - "codex"
    - "openclaw"
  require_objective_before_plan: true
  require_json_protocol: true

objective:
  name: ""
  description: ""
  focus: []
  primary_score_threshold: 0.05
  hard_primary_regression_policy: "reject"
  mean_reward_role: "diagnostic_only"

constraints:
  forbidden_changes:
    - "algorithm_body"
    - "network_architecture"
    - "optimizer"
    - "loss"
    - "replay_buffer"
    - "base_controller_law"
  require_human_review_for:
    - "observation_space_change"
    - "action_space_change"
    - "termination_logic_change"
    - "algorithm_selection_change"

budget:
  wall_clock_hours: 336
  gpu_hours: null
  max_candidates: null
  max_full_evals: null
  stop_when_budget_exhausted: true  # true=预算耗尽时停止（默认）；false=超过预算后继续执行并输出警告（用于探索性运行）

joint_validation:
  lqr_degradation_threshold: 0.90
  stanley_degradation_threshold: 0.90
  combined_score_threshold: 0.85

metrics:
  primary: []
  safety: []
  diagnostic: []
  metric_regex: {}
  metric_thresholds:
    default_min_improvement_pct: 0.01
    default_max_regression_pct: 0.10
  safety_weights: {}
  # 格式: {metric_name: weight}
  # 示例: {"residual_magnitude": 1.0, "control_energy": 0.8}
  # 未列出的 safety metric 使用 weight=1.0
  cv_threshold: 0.3
  instability_weight: 0.5
  screening_threshold: 0.0
  # 格式: {metric_name: {"log_file": glob_pattern, "regex": pattern, "group": int, "aggregate": "last"|"max"|"min"|"mean"}}
  # 示例:
  #   mean_reward:
  #     log_file: "stdout"
  #     regex: "ep_rew_mean\\s*[=:]\\s*([\\-\\d\\.]+)"
  #     group: 1
  #     aggregate: "last"
  #   fall_rate:
  #     log_file: "eval/*.json"
  #     regex: "\"fall_rate\"\\s*:\\s*([\\d\\.]+)"
  #     group: 1
  #     aggregate: "last"
  #   tracking_error:
  #     log_file: "logs/metrics.jsonl"
  #     regex: "\"tracking_error\"\\s*:\\s*([\\d\\.]+)"
  #     group: 1
  #     aggregate: "mean"
  # log_file 支持:
  #   - "stdout": 捕获训练命令的 stdout
  #   - "stderr": 捕获训练命令的 stderr
  #   - glob 模式: 匹配 project_root 下的文件（如 "eval/*.json", "logs/*.jsonl"）
  # aggregate:
  #   - "last": 取最后一次匹配的值
  #   - "max": 取所有匹配的最大值
  #   - "min": 取所有匹配的最小值
  #   - "mean": 取所有匹配的平均值

literature:
  enabled: true
  require_before_propose: true
  top_k_selected_papers: 5
  min_relevance_score: 0.60
  max_queries: 10
  max_results_per_query: 20
  max_extracted_ideas: 20
  deterministic_selection: true
  classification_categories:
    - "reward shaping"
    - "penalty and constraint design"
    - "curriculum reward"
    - "robotics locomotion reward"
    - "control energy and smoothness"
    - "reward hacking and specification gaming"
    - "residual control"
    - "path tracking control"

execution:
  train_command: ""
  eval_command: ""
  max_steps: 20000
  screening_seeds: [42]
  full_eval_seeds: [42, 123, 456]
  confirmation_seeds: [789, 101112]
  timeout_seconds_per_seed: 3600

git:
  auto_commit_best: true
  auto_push_best: false
  push_remote: "origin"
  push_branch: null

output:
  json: false
  quiet: false
  log_level: INFO
```

### 3.4 LLM 调用层

所有需要 LLM 的操作（understand、classify-task、propose_candidate、paper scoring、paper classification、extract-ideas）统一通过 `research_agent.core.llm_client` 模块调用。

**LLMClient 接口：**

```python
from dataclasses import dataclass

@dataclass
class LLMResponse:
    content: str              # LLM 返回的原始文本
    parsed: dict | list | None  # 尝试 JSON parse 后的结果（失败为 None）
    tokens_used: int
    model: str
    latency_seconds: float

class LLMClient:
    def __init__(self, config: dict):
        """从 config.yaml 的 llm 节初始化。"""
        raise NotImplementedError

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: str = "json",  # "json" | "text"
        seed: int | None = None,  # 传递给 API 的 seed 参数，用于确定性输出。如果 API 不支持 seed，此参数被忽略。
    ) -> LLMResponse:
        """调用 LLM API。

        行为：
        - 自动重试（max_retries 次，retry_delay_seconds 间隔）。
        - response_format="json" 时，自动 parse content 为 JSON。
        - parse 失败时，retry 并在 prompt 中追加 "Return valid JSON only."。
        - 超过 max_retries 仍失败，抛出 LLMCallError。
        - 每次调用记录到 logs/llm_calls.jsonl。
        """
        raise NotImplementedError
```

**Prompt Template 约定：**

每个使用 LLM 的模块必须定义自己的 prompt template 常量。格式：

```python
# research_agent/core/task_classifier.py

CLASSIFY_SYSTEM_PROMPT = """You are a research task classifier for RL projects.
Given a project understanding report, classify the research tasks.
Return JSON only."""

CLASSIFY_USER_PROMPT = """Project understanding:
{project_understanding}

Available task types: {available_task_types}

Return JSON:
{
  "task_types": ["reward_optimization", "controller_residual_optimization"],
  "confidence": <0-1>,
  "recommended_strategies": ["<strategy1>"],
  "not_recommended": ["<type1>"]
}"""
```

**Token Budget：**

| 操作 | 单次 max_tokens | 预估 input tokens | 预估总 tokens/调用 |
|------|----------------|-------------------|-------------------|
| understand | 4096 | 5000-20000 | 10000-25000 |
| classify-task | 1024 | 500-2000 | 1000-3000 |
| propose_candidate | 4096 | 2000-8000 | 5000-12000 |
| paper scoring (per paper) | 512 | 500-1500 | 800-2000 |
| paper classification (per paper) | 256 | 300-800 | 400-1000 |
| extract-ideas | 4096 | 3000-10000 | 5000-15000 |

**调用频次控制：**

- 默认 QPS 上限：2（可在 config.yaml 的 `llm.qps` 覆盖）。
- 超过 QPS 时 sleep 等待，不报错。
- arxiv API 搜索无 QPS 限制（使用 arxiv Python 库的内置 rate limit）。

**失败与降级：**

| 场景 | 处置 |
|------|------|
| LLM API 超时 | 重试 max_retries 次，然后抛出 `LLMCallError` |
| LLM 返回非法 JSON（response_format="json"） | 重试 max_retries 次，每次追加 "Return valid JSON only."，然后抛出 `LLMCallError` |
| LLM API 完全不可用 | 抛出 `LLMCallError`，命令以 `LLM_SERVICE_UNAVAILABLE` error_code 退出 |
| Token 超限（input 超过模型 context） | 截断 input（保留 system prompt + user prompt 的前 N 字符），记录 warning 到 llm_calls.jsonl |

**降级策略：**

- `classify-task`：如果 LLM 不可用，fallback 到规则引擎（基于 project_understanding 中的关键词匹配）。规则引擎结果的 confidence 上限为 0.6，且在 JSON 输出中附加 `"fallback": "rule_engine"`。
- `understand`：无降级，必须 LLM。失败则命令失败。
- `propose_candidate`：无降级，必须 LLM。失败则 `NO_CANDIDATE_GENERATED`。
- `paper scoring`：如果 LLM 不可用，`objective_match`、`state_action_match`、`implementation_feasibility` 全部设为 0.5（中性值）。总分公式不变，但由于 3 个子分数固定为 0.5，实际排序主要由 `metric_match`（权重 0.25）和 `recency_or_influence`（权重 0.10）决定。此时有效排序公式为 `0.35*0.5 + 0.25*metric_match + 0.15*0.5 + 0.15*0.5 + 0.10*recency = 0.325 + 0.25*metric_match + 0.10*recency`。`metric_match` 和 `recency` 本身不会降级（不依赖 LLM），因此总分范围为 [0.325, 0.675]，始终在 [0, 1] 内，无需额外 clamp。

**llm_calls.jsonl 格式：**

```json
{
  "timestamp": "2026-06-05T12:00:00Z",
  "operation": "classify-task",
  "model": "mimo-v2.5-pro",
  "input_tokens": 1500,
  "output_tokens": 300,
  "total_tokens": 1800,
  "latency_seconds": 3.2,
  "success": true,
  "retries": 0,
  "error": null,
  "response_preview": "{\"task_types\": [\"reward_optimization\"]}"
}
```

### 3.5 配置验证

`research-agent` 在每次命令启动时验证 config（项目级 + 默认值合并后的最终配置）。

**验证方式：**

使用 pydantic `BaseModel` 定义 config schema。验证失败时输出 error JSON 并退出。

```python
from pydantic import BaseModel, Field

from pydantic import ConfigDict

class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    provider: str = "openai_compatible"
    model: str
    base_url: str
    api_key_env: str
    timeout_seconds: int = Field(ge=10, le=600)
    max_retries: int = Field(ge=0, le=10)
    retry_delay_seconds: int = Field(ge=1, le=60)
    max_tokens: int = Field(ge=256, le=32768)
    qps: float = Field(ge=0.1, le=10.0, default=2.0)

class BudgetConfig(BaseModel):
    wall_clock_hours: float = Field(ge=1, le=8760)
    gpu_hours: float | None = None
    max_candidates: int | None = None
    max_full_evals: int | None = None
    stop_when_budget_exhausted: bool = True

# 其他 config 节使用同样的 pydantic BaseModel 方式定义。
```

**验证错误示例：**

```json
{
  "ok": false,
  "error_code": "CONFIG_INVALID",
  "message": "Config validation failed",
  "details": [
    {"field": "llm.timeout_seconds", "error": "ensure this value is less than or equal to 600", "value": 9999},
    {"field": "budget.wall_clock_hours", "error": "ensure this value is greater than or equal to 1", "value": -1}
  ],
  "next_action": "Fix the config values in .research-agent/config.yaml"
}
```

**unknown key 处理：**

- config.yaml 中出现 default.yaml 没有的 key 时，不报错，静默忽略。
- 理由：允许用户添加自定义字段（如 optimizer-specific 配置），不阻塞。

### 3.6 JSON Protocol

所有命令必须支持 `--json`。错误输出格式：

```json
{
  "ok": false,
  "error_code": "OBJECTIVE_MISSING",
  "message": "Objective is required before planning experiments.",
  "next_action": "Ask the front agent to write objective, metrics, constraints and budget."
}
```

`status --json` 必须返回：

```json
{
  "ok": true,
  "phase": "running_plan",
  "active_experiment": "lqr_residual_reward_screening",
  "budget_usage": {
    "wall_clock_seconds": 12345,
    "gpu_seconds": null,
    "candidates": 18,
    "full_evals": 4
  },
  "current_best": {
    "optimizer": "residual_control",
    "candidate_id": "cand_rew_014",
    "commit_hash": "abc123",
    "improve_score": 0.083
  },
  "blocking_issue": null
}
```

`plan-experiments --json` 必须返回并写入 `reports/experiment_plan.json`：

```json
{
  "ok": true,
  "phase": "planned",
  "report_path": "reports/experiment_plan.md",
  "json_path": "reports/experiment_plan.json",
  "plan": {
    "version": 1,
    "project_path": "E:\\Code\\python\\HRRL0",
    "phases": [
      {
        "phase_id": "baseline",
        "dependencies": [],
        "optimizer": null,
        "objective_summary": "Establish immutable baseline metrics before any candidate patch.",
        "allowed_changes": [],
        "forbidden_changes": [{"type": "all_project_files"}],
        "train_command": "python train.py",
        "eval_command": "python eval.py",
        "primary_metrics": ["fall_rate", "balance_error", "episode_length"],
        "safety_metrics": ["residual_magnitude", "control_energy"],
        "budget": {
          "max_candidates": 0,
          "max_full_evals": 0,
          "timeout_seconds": 3600
        },
        "rollback_policy": "none",
        "cleanup_policy": "none",
        "status": "pending"
      }
    ]
  },
  "next_action": "Call 'search-papers --json' before optimizer proposal."
}
```

`report --json` 必须可被前站主 Agent 稳定读取，不能要求解析 Markdown。

**`report` 输出行为：**

| flag | stdout | 文件输出 |
|------|--------|---------|
| 无 flag | `final_report.md` 的内容（人类可读，前站 Agent 应使用 `--json`） | 写入 `reports/final_report.md` 和 `reports/final_report.json` |
| `--json` | `final_report.json` 的内容（stdout） | 同时写入 `reports/final_report.md` 和 `reports/final_report.json` |

> **注意：** 无 flag 时 stdout 输出 Markdown 是为了方便人类直接查看。前站 Agent 必须使用 `--json` 获取 machine-readable 输出。

`report` 是幂等命令，可多次调用，每次都从 state.json 和日志重新生成报告。不获取 lock（只读操作）。

### 3.6.1 Error Code 枚举

所有命令的 JSON 错误输出必须使用以下 error_code。前站 Agent 根据 `next_action` 字段决定下一步。

**平台级错误：**

| error_code | 含义 | next_action |
|-----------|------|------------|
| `WORK_DIR_NOT_FOUND` | `.research-agent/` 不存在 | 调用 `init --project <path>` |
| `STATE_FILE_CORRUPT` | `state.json` 无法解析 | 人工检查 `state.json`，或删除后重新 `init` |
| `LOCK_BUSY` | 另一个命令正在执行 | 等待后重试。如果确认进程已死，调用 `status --clear-stale-lock` 清理 |
| `LOCK_STALE` | lock 文件存在但持有进程已退出 | `status --clear-stale-lock` |
| `CONFIG_INVALID` | `config.yaml` 格式或值错误 | 检查并修复 `config.yaml` |
| `CONFIG_KEY_MISSING` | 缺少必填配置项 | 补充缺失的配置项 |
| `JSON_ARTIFACT_INVALID` | 生成的 JSON artifact 无法被解析 | 检查对应命令的 schema 生成逻辑 |
| `BUDGET_EXHAUSTED` | 预算已耗尽 | 调用 `report --json` 获取结果 |
| `ALREADY_INITIALIZED` | 项目已初始化且有进度 | 调用 `resume` 继续，或删除 `.research-agent/` 后重新 `init` |
| `PROJECT_PATH_MISSING` | `state.json` 中缺少 `project_path` 字段 | 检查 `state.json`，或重新 `init --project <path>` |

**前置依赖错误：**

| error_code | 含义 | next_action |
|-----------|------|------------|
| `OBJECTIVE_MISSING` | objective 未写入 | 前站 Agent 写入 objective、metrics、constraints、budget |
| `CONSTRAINTS_MISSING` | constraints 未写入 | 前站 Agent 写入 constraints |
| `FORBIDDEN_CHANGES_MISSING` | forbidden_changes 未写入 | 前站 Agent 写入 constraints.forbidden_changes |
| `BUDGET_MISSING` | budget 未写入 | 前站 Agent 写入 budget |
| `METRICS_MISSING` | metrics 未写入 | 前站 Agent 写入 metrics |
| `METRIC_REGEX_MISSING` | primary/safety metric 缺少解析 regex | 在 front_agent_objective.json 或 config.yaml 中补充 metrics.metric_regex |
| `PROJECT_UNDERSTANDING_MISSING` | 未执行 understand | 调用 `understand --project <path>` |
| `TASK_CLASSIFICATION_MISSING` | 未执行 classify-task | 调用 `classify-task` |
| `STRATEGY_SELECTION_MISSING` | 未执行 select-strategy | 调用 `select-strategy` |
| `EXPERIMENT_PLAN_MISSING` | 未执行 plan-experiments | 调用 `plan-experiments` |
| `LITERATURE_NOT_SEARCHED` | 未执行 search-papers | 调用 `search-papers` |
| `LITERATURE_NOT_CLASSIFIED` | 未执行 classify-papers | 调用 `classify-papers` |
| `LITERATURE_NOT_SELECTED` | 未执行 select-papers | 调用 `select-papers` |

**执行错误：**

| error_code | 含义 | next_action |
|-----------|------|------------|
| `TRAIN_COMMAND_MISSING` | `execution.train_command` 为空 | 在 config.yaml 中配置 train_command |
| `EVAL_COMMAND_MISSING` | `execution.eval_command` 为空 | 在 config.yaml 中配置 eval_command |
| `PROJECT_NOT_GIT_REPO` | 目标项目不是 Git 仓库 | 在 project_root 初始化 Git 或显式改为只读规划模式 |
| `DIRTY_WORKTREE` | 目标项目存在未提交改动 | 提交、清理，或由前站 Agent 显式选择 stash 后重试 |
| `TRAIN_COMMAND_FAILED` | 训练命令 exit 非 0 | 检查日志，修复训练环境 |
| `EVAL_COMMAND_FAILED` | 评估命令 exit 非 0 | 检查日志，修复评估环境 |
| `TRAIN_TIMEOUT` | 训练超过 timeout_seconds_per_seed | 增大 timeout 或优化训练速度 |
| `LITERATURE_SEARCH_FAILED` | arxiv API 搜索失败（网络不可用或重试耗尽） | 检查网络连接后重试；如果不影响 propose（`require_before_propose=false`），可跳过论文阶段继续 |
| `PATCH_APPLY_FAILED` | git apply 失败 | 检查 patch 文件和项目状态 |
| `PATCH_ROLLBACK_FAILED` | git checkout 回滚失败 | 人工介入恢复工作区 |
| `COMMIT_FAILED` | accepted current best 本地 commit 失败 | 检查 Git 状态并人工介入 |
| `DISK_SPACE_LOW` | 磁盘剩余 < 阈值（默认 1GB） | 清理磁盘空间 |
| `NO_COMPARABLE_CANDIDATES` | 没有 candidate 完成 full_eval | 调用 `run-plan` 或 `run --phase` 生成并评估 candidate |
| `PHASE_NOT_FOUND` | `run --phase <id>` 的 phase_id 不在 experiment_plan 中 | 检查可用 phase：`plan-experiments --json` |
| `METRIC_PARSE_FAILED` | 某个 metric 在所有 seed 中均解析失败（exit_code=-2） | 检查 metric_regex 配置和 eval 输出格式 |
| `PROJECT_STATE_CORRUPT` | 项目关键文件被意外修改 | 人工检查项目状态 |

**Optimizer 错误：**

| error_code | 含义 | next_action |
|-----------|------|------------|
| `GUARD_VIOLATION` | candidate patch 违反权限边界 | optimizer 重新生成 candidate |
| `GUARD_HUMAN_REVIEW_REQUIRED` | patch 修改了需要人工复核的区域 | 前站 Agent 请求人工审批 |
| `NO_CANDIDATE_GENERATED` | optimizer 无法生成新 candidate | 检查 knowledge_base 中的失败假设，或等待新 evidence |
| `PATCH_GENERATION_FAILED` | proposal 无法生成合法 patch | optimizer 重新生成 proposal 或降低 patch 范围 |
| `EVIDENCE_INSUFFICIENT` | selected papers 不足以支撑 proposal | 追加搜索或降低 min_relevance_score |
| `REWARD_HACKING_DETECTED` | 检测到 reward hacking 风险 | reject candidate，记录到 knowledge_base |
| `JOINT_VALIDATION_PATCH_CONFLICT` | Phase 2 和 Phase 3 的 patch 修改了同一文件且无法自动 merge | 人工介入或前站 Agent 决策优先保留哪个 phase 的改动 |
| `PATCH_GUARD_BLOCKED` | 连续 5 个 candidate 被 guard 拒绝（stop_reason = `patch_guard_blocked`） | 检查 optimizer 是否在生成违反约束的 patch，调整 forbidden_changes 或 optimizer 参数 |

**LLM 错误：**

| error_code | 含义 | next_action |
|-----------|------|------------|
| `LLM_SERVICE_UNAVAILABLE` | LLM API 完全不可用（重试耗尽） | 等待 LLM 服务恢复后重试；classify-task 可 fallback 到规则引擎 |
| `LLM_INVALID_RESPONSE` | LLM 返回无法解析的 JSON（重试耗尽） | 等待 LLM 服务恢复后重试 |

**成功响应中的 `next_action`：**

成功时（`ok: true`）也可以包含 `next_action`，指导前站 Agent 下一步：

```json
{
  "ok": true,
  "data": {"phase": "classified"},
  "next_action": "Call 'select-strategy' to choose optimizer."
}
```

### 3.7 通信协议

`research-agent` 与前站 Agent 之间**没有双向通道**。通信完全基于 CLI 调用 + 文件系统，不存在 HTTP callback、WebSocket、stdio pipe。

**通信模型：**

```text
前站 Agent                    research-agent
    │                              │
    │  ── subprocess 调用 ──────>  │  执行命令
    │                              │  写入 state.json / reports / logs
    │  <── stdout (JSON) ────────  │  exit
    │                              │
    │  轮询: status --json ─────>  │  读取 state.json，返回当前状态
    │  <── stdout (JSON) ────────  │  exit
```

**命令执行协议：**

| 命令类型 | 执行方式 | 返回方式 |
|----------|---------|---------|
| 短命令（init, understand, classify-task, select-strategy, plan-experiments, search-papers, classify-papers, select-papers, extract-ideas, compare, status, report, cache clear） | 同步执行，阻塞直到完成 | stdout 输出 JSON（`--json`）或文本；exit 0 = 成功，exit 非 0 = 失败 |
| 长命令（run-plan, run --phase） | 同步执行，阻塞直到完成或被中断 | 同上；前站 Agent 通过超时检测判断是否卡死 |

**前站 Agent 查询中间状态：**

```bash
# 前站 Agent 在长命令执行期间，另起进程查询状态
research-agent status --json
```

`status --json` 是只读操作，不获取 lock，任何时候都可以安全调用。

**`--clear-stale-lock` 行为：**

```bash
research-agent status --clear-stale-lock [--json]
```

1. 读取 lock 文件中的 PID。
2. 检查 PID 是否存活（`os.kill(pid, 0)` 或等效跨平台检测）。
3. 如果 PID 不存活，删除 lock 文件，输出 `{"ok": true, "cleared": true, "stale_pid": <pid>}`。
4. 如果 PID 存活，输出 `{"ok": false, "error_code": "LOCK_BUSY", "message": "Process <pid> is still running"}`。
5. 如果 lock 文件不存在，输出 `{"ok": true, "cleared": false, "message": "No lock file found"}`。

此命令**必须在非 mutating 命令上下文中调用**（即不能在另一个 run-plan 执行期间调用）。前站 Agent 应在确认长命令 subprocess 已退出（收到 exit code）后调用。不要在 subprocess 可能仍在启动时调用 `--clear-stale-lock`。

**前站 Agent 判定命令完成：**

- subprocess 返回 → 命令完成（成功或失败）。
- 前站 Agent 必须设置 subprocess 的 timeout（默认：短命令 300s，长命令 = `budget.wall_clock_hours * 3600 * 2`）。
- 超时 → 前站 Agent 发送 SIGTERM → 等待 30s → SIGKILL → 调用 `resume`。

**跨平台中断处理：**

| 平台 | SIGTERM 等效 | SIGKILL 等效 |
|------|-------------|-------------|
| Unix/Linux/macOS | `signal.SIGTERM` | `signal.SIGKILL` |
| Windows | `process.terminate()`（发送 `CTRL_BREAK_EVENT`） | `process.kill()`（调用 `TerminateProcess`） |

research-agent 内部信号处理：
- Unix：注册 `signal.SIGTERM` 和 `signal.SIGINT` handler，设置 `stop_reason = "user_interrupt"`，完成当前 seed 后优雅退出。
- Windows：注册 `signal.SIGTERM` handler（Python 在 Windows 上支持有限）。如果 handler 不生效，依赖 `state.json` 中的 stop_reason 检测：`resume` 命令检查 `stop_reason` 是否为 `null` 但 `progress.current_candidate` 非空（说明进程被强制终止）。

**前站 Agent 获取新状态的方式：**

前站 Agent 不需要轮询新状态。它发起调用后阻塞等待结果。命令结束后，stdout 就是最新状态。如果需要在命令执行期间查询中间状态，使用 `status --json`。

**状态变更通知：**

`research-agent` 不主动推送通知。所有状态变更通过写入 `state.json` 和 `logs/events.jsonl` 持久化。前站 Agent 通过命令返回值或主动 `status --json` 查询获取。

---

## 四、平台核心命令

使用 `click`，入口为 `research_agent.interfaces.cli:main`。

### 4.1 命令列表

```bash
research-agent init --project <path>
research-agent understand --project <path>
research-agent classify-task
research-agent select-strategy
research-agent plan-experiments
research-agent search-papers [--topic "residual control reward shaping"]  # --topic 追加到自动生成的 query 列表中（不替换），作为额外搜索方向
research-agent classify-papers
research-agent select-papers [--top-k N]  # --top-k 一次性覆盖 config 中的 literature.top_k_selected_papers，不修改 config 或 state
research-agent extract-ideas
research-agent run-plan
research-agent run --phase <phase-id>
research-agent compare [--candidate-id <id>] [--vs baseline|current-best|<candidate-id>]
research-agent status [--json] [--clear-stale-lock]
research-agent resume
research-agent report [--json]
research-agent cache clear
```

### 4.2 命令依赖

```text
init
  -> understand
  -> classify-task
  -> select-strategy
  -> plan-experiments
  -> search-papers
  -> classify-papers
  -> select-papers
  -> extract-ideas
  -> run-plan
  -> compare/report
```

当 `literature.require_before_propose=true` 时，paper pipeline 是 optimizer proposal 的 hard dependency。

### 4.3 extract-ideas

从 selected papers 和 knowledge base 中提取尚未验证的假设和思路。

```bash
research-agent extract-ideas [--json]
```

**依赖：** `select-papers` 完成后可执行。

**功能：**

- 遍历 selected papers 的摘要和分类。
- 结合 knowledge_base 中的 `failed_hypotheses` 和 `open_hypotheses`。
- 提取未尝试过的 reward shaping 思路、penalty 设计、potential shaping 方法。
- 过滤已 rejected 的假设（除非有新 evidence 支持）。
- **数量上限**：最多输出 20 个 idea（可在 config.yaml 的 `literature.max_extracted_ideas` 覆盖）。如果提取结果超过上限，按 feasibility（high > medium > low）和 source_paper 的 relevance_score 降序截断。

**输出：**

```text
reports/extracted_ideas.md
logs/extracted_ideas.jsonl
```

**`logs/extracted_ideas.jsonl` 格式：**

```json
{"timestamp": "2026-06-05T12:00:00Z", "idea_id": "idea_001", "source_paper": "arxiv:2401.12345", "description": "Use potential-based shaping reward for tracking error", "category": "reward shaping", "feasibility": "high", "related_hypotheses": [], "status": "open"}
```

`status` 枚举：`open`（未尝试）、`attempted`（已生成 candidate）、`rejected`（已被 reject）、`accepted`（已被 accept）。

**idea status 转换规则：**

| 转换 | 触发条件 | 说明 |
|------|---------|------|
| open → attempted | optimizer 的 `propose_candidate` 引用了该 idea | candidate 创建时自动标记 |
| attempted → accepted | 引用该 idea 的 candidate 被 accept | candidate 进入 accepted 状态时更新 |
| attempted → rejected | 引用该 idea 的 candidate 被 reject | candidate 进入 rejected 状态时更新 |
| rejected → open | 新 evidence 支持重新尝试 | knowledge_base 更新时，如有新 paper 支持该 idea |

**idea 去重规则：** 如果 `extract-ideas` 产出的 idea 与已有 open idea 匹配（相同 description 或 source_paper），保留已有 idea（不重复添加）。如果新 idea 的 feasibility 更高，更新已有 idea 的 feasibility。

idea status 更新由 `research-agent` 内部自动执行，不暴露独立 CLI 命令。

**JSON 输出格式：**

```json
{
  "ok": true,
  "ideas": [
    {
      "idea_id": "idea_001",
      "source_paper": "arxiv:2401.12345",
      "description": "Use potential-based shaping reward for tracking error",
      "category": "reward shaping",
      "feasibility": "high",
      "related_hypotheses": []
    }
  ],
  "total": 5
}
```

`extract-ideas` 不自动执行任何修改，只输出建议。optimizer 可以在 `propose_candidate` 时参考 extracted ideas。

### 4.4 compare

比较两个 candidate 或 candidate 与 baseline 的 metrics 差异。

```bash
research-agent compare [--candidate-id <id>] [--vs baseline|current-best|<candidate-id>] [--json]
```

**参数：**

- `--candidate-id <id>`：要比较的 candidate ID。默认为 current best。
- `--vs`：比较目标。默认为 `baseline`。
  - `baseline`：与 baseline metrics 比较。
  - `current-best`：与 current best metrics 比较。
  - `<candidate-id>`：与指定 candidate 比较。

**依赖：** 至少有一个 candidate 完成 full_eval。如果没有，返回 `NO_COMPARABLE_CANDIDATES` 错误。

**metric direction 来源：** compare 使用 `front_agent_objective.json` 中的 metric 定义（primary/safety/diagnostic）确定 direction。如果某个 metric 仅出现在一侧（left 或 right），另一侧视为 baseline 值。`direction` 字段（per-metric）重命名为 `assessment`，值为 `"improved"` / `"degraded"` / `"unchanged"`（`|change_pct| < 0.001`），避免与 MetricSpec.direction 混淆。

**JSON 输出格式：**

```json
{
  "ok": true,
  "left": {
    "candidate_id": "cand_rew_014",
    "metrics": {"fall_rate": 0.08, "balance_error": 0.12}
  },
  "right": {
    "candidate_id": "baseline",
    "metrics": {"fall_rate": 0.15, "balance_error": 0.18}
  },
  "comparison": {
    "fall_rate": {"change": -0.07, "change_pct": -0.467, "assessment": "improved"},
    "balance_error": {"change": -0.06, "change_pct": -0.333, "assessment": "improved"}
  },
  "verdict": "improved"
}
```

### 4.5 resume

`resume` 读取 state 并从最近的安全阶段恢复：

- 如果停在 project understanding 后，继续 classify-task。
- 如果停在 experiment phase 中，检查 active experiment 是否完成。
- 如果训练中断，标记 interrupted run，不假装成功。
- 如果 `run --phase`（非 `run-plan`）中断，`resume` 从 `progress.current_phase.phase_id` 重新执行该 phase。
- 如果工作区有未清理 patch，必须回滚到 current best 或进入人工复核。

---

## 五、Project Understanding Layer

命令：

```bash
research-agent understand --project E:\Code\python\HRRL0
```

输出：

```text
reports/project_understanding.md
```

内容必须包括：

- 项目类型候选。
- 控制结构。
- 训练入口候选。
- 评估入口候选。
- 关键配置文件。
- 可优化对象。
- 禁止修改对象。
- 指标输出位置。
- 可能的 optimizer 适配。

**`understand --json` 输出格式：**

```json
{
  "ok": true,
  "project_type": ["residual_rl", "hierarchical_control", "path_tracking"],
  "control_structure": "Dynamic LQR + LQR Residual + Dynamic Stanley + Stanley Residual",
  "train_entry": "train.py",
  "eval_entry": "eval.py",
  "config_files": ["config.yaml", "env_config.json"],
  "optimizable_targets": [
    {"name": "residual_reward", "file": "reward.py", "line_range": [45, 120], "type": "reward_function"},
    {"name": "residual_magnitude_penalty", "file": "reward.py", "line_range": [125, 140], "type": "penalty_term"}
  ],
  "readonly_targets": [
    {"name": "lqr_control_law", "file": "controllers/lqr.py", "reason": "base_controller_law"},
    {"name": "stanley_control_law", "file": "controllers/stanley.py", "reason": "base_controller_law"}
  ],
  "metric_output_locations": [
    {"metric": "fall_rate", "source": "eval stdout", "pattern": "fall_rate\\s*[=:]\\s*([\\-\\d\\.]+)"}
  ],
  "optimizer_affinity": ["reward", "residual_control"],
  "report_path": "reports/project_understanding.md"
}
```

`metric_output_locations[].pattern` 是正则表达式，仅供参考（由 `understand` 的 LLM 推断）。实际 metric 提取使用 `metric_regex`（来自 `front_agent_objective.json` 或 `config.yaml`），不使用此 discovered pattern。

`understand` 必须同时输出 `reports/project_understanding.md`（人类可读）和 `--json` 时的 stdout（机器可读）。两者内容一致，格式不同。

### 5.1 HRRL 理解规则

如果项目中出现以下信号，应提高 residual_control 任务置信度：

- `LQR`、`dynamic_lqr`、`lqr_controller`。
- `Stanley`、`dynamic_stanley`、`stanley_controller`。
- `residual`、`residual_rl`、`residual_policy`。
- path tracking、trajectory tracking、lateral error、heading error。
- safety gate、fall、constraint、stability。

HRRL 理解输出示例：

```text
项目类型：Residual RL / Hierarchical Control / Path Tracking
控制结构：Dynamic LQR + LQR Residual + Dynamic Stanley + Stanley Residual
训练入口：待确认
可优化对象：residual reward、residual magnitude penalty、safety-aware tracking penalty
禁止修改对象：LQR 控制律、Stanley 控制律、算法主体、网络结构
```

---

## 六、Task Classifier

命令：

```bash
research-agent classify-task
```

输出：

```text
reports/task_classification.json
```

示例：

```json
{
  "task_types": [
    "controller_residual_optimization",
    "reward_optimization",
    "safety_constraint_optimization"
  ],
  "confidence": 0.86,
  "recommended_strategies": [
    "residual-aware reward",
    "safety-aware tracking reward",
    "potential-based tracking reward"
  ],
  "not_recommended": [
    "algorithm_body_change",
    "base_controller_law_change",
    "network_architecture_search"
  ]
}
```

分类器可以识别 HPO、curriculum、observation、action space 等任务，但 V1 对这些只输出建议，不自动执行 patch。

**输出行为：**

| flag | stdout | 文件输出 |
|------|--------|---------|
| 无 flag | task_classification.json 的内容（JSON 格式） | 写入 `reports/task_classification.json` |
| `--json` | 同上 | 同上 |

`classify-task` 的 stdout 始终为 JSON 格式（与 `reports/task_classification.json` 内容一致）。

---

## 七、Strategy Selector

命令：

```bash
research-agent select-strategy
```

输出：

```text
reports/strategy_selection.md
```

**输出行为：**

| flag | stdout | 文件输出 |
|------|--------|---------|
| 无 flag | strategy_selection.md 的内容（Markdown 格式） | 写入 `reports/strategy_selection.md` |
| `--json` | strategy_selection 的 JSON 表示（包含 selected_optimizers、reasoning 等结构化字段） | 同时写入 `reports/strategy_selection.md` 和 stdout 的 JSON |

V1 策略选择规则：

- `reward_optimization` 选择 `optimizers/reward`。
- `controller_residual_optimization` 选择 `optimizers/residual_control`。
- `safety_constraint_optimization` 可以由 `reward` 和 `residual_control` 联合处理。
- `algorithm_selection` 只输出建议，不自动改算法。
- `observation_optimization` 和 `action_space_optimization` 进入人工复核。

HRRL 推荐策略：

1. LQR residual reward optimization。
2. Stanley residual reward optimization。
3. Safety-aware tracking penalty。
4. Residual magnitude penalty。
5. Potential-based tracking reward。

---

## 八、Experiment Planner

命令：

```bash
research-agent plan-experiments
```

输出：

```text
reports/experiment_plan.md
reports/experiment_plan.json
```

没有 objective、constraints、constraints.forbidden_changes、budget、metrics.primary 或 primary/safety metric regex 时，`plan-experiments` 必须失败。

`experiment_plan.md` 只供人类阅读；`experiment_plan.json` 是 executor 唯一可读的 phase plan。

HRRL 默认实验计划：

```text
Phase 1: baseline evaluation
Phase 2: optimize LQR residual reward
Phase 3: optimize Stanley residual reward
Phase 4: safety-aware tracking validation
Phase 5: joint validation
Phase 6: final report
```

非 HRRL 项目（如纯 RL 无经典控制器）的默认实验计划：

```text
Phase 1: baseline evaluation
Phase 2: reward optimization（使用 reward optimizer）
Phase 3: validation（验证 accepted candidate 在更多 seed 上的稳定性）
Phase 4: final report
```

非 HRRL 项目的 phase 结构由 `task_classification` 的结果驱动：
- 如果只有 `reward_optimization`：使用上述简化计划。
- 如果有 `controller_residual_optimization` 但无经典控制器信号：降级为纯 reward optimization，记录 warning。
- 如果 `classify-task` 返回的 `task_types` 全部属于 V1 不自动执行的类型（如 `algorithm_selection`、`observation_optimization`）：只输出建议，不生成 optimizer phase，`run-plan` 只生成 final report。

每个 phase 必须定义：

- phase id。
- optimizer。
- 目标。
- 允许修改对象。
- 禁止修改对象。
- 训练命令。
- 评估命令。
- primary metrics。
- safety metrics。
- budget。
- rollback / cleanup policy。
- phase status（初始为 `pending`）。

**`reports/experiment_plan.json` schema：**

```json
{
  "version": 1,
  "generated_at": "2026-06-05T12:00:00Z",
  "project_path": "E:\\Code\\python\\HRRL0",
  "objective_name": "optimize_lqr_residual_reward",
  "global_budget": {
    "wall_clock_hours": 336,
    "gpu_hours": null,
    "max_candidates": 50,
    "max_full_evals": 20
  },
  "phases": [
    {
      "phase_id": "lqr-residual",
      "dependencies": ["baseline"],
      "optimizer": "reward",
      "task_types": ["controller_residual_optimization", "reward_optimization"],
      "objective_summary": "Optimize LQR residual reward without modifying base LQR control law.",
      "allowed_changes": [
        {
          "type": "reward_function",
          "file": "reward.py",
          "line_range": [45, 120],
          "symbol": "compute_lqr_residual_reward"
        }
      ],
      "forbidden_changes": [
        {
          "type": "base_controller_law",
          "file": "controllers/lqr.py",
          "symbol": "DynamicLQR"
        }
      ],
      "train_command": "python train.py",
      "eval_command": "python eval.py",
      "primary_metrics": ["fall_rate", "balance_error", "episode_length"],
      "safety_metrics": ["residual_magnitude", "control_energy"],
      "budget": {
        "max_candidates": 15,
        "max_full_evals": 5,
        "timeout_seconds": 3600
      },
      "rollback_policy": "git_checkout",
      "cleanup_policy": "full",
      "status": "pending"
    }
  ]
}
```

`plan-experiments` 必须在写入前验证：

1. `phases` 按 DAG 拓扑序排列。
2. 每个 `dependencies[]` 都指向已存在 phase。
3. 每个 phase 的 `primary_metrics` / `safety_metrics` 都能在合并后的 `metric_regex` 中找到解析规则。
4. 每个 optimizer phase 至少有一个 `allowed_changes`，且所有 `forbidden_changes` 来自 front-agent contract 或 project understanding。
5. 所有 JSON 字段可被 `json.loads` 解析；否则返回 `JSON_ARTIFACT_INVALID`。

**Phase status 枚举：**

| 值 | 含义 |
|----|------|
| `pending` | 尚未开始 |
| `running` | 正在执行（有 candidate 在 screening 或 full_eval） |
| `completed` | 正常完成（所有 candidate 处理完毕） |
| `skipped` | 被跳过（如预算不足，或前置 phase 失败） |
| `failed` | 执行失败（训练命令持续失败等不可恢复错误） |

**Phase DAG（依赖与并行规则）：**

```text
Phase 1: baseline (无依赖)
    │
    ├──────────────────────┐
    ▼                      ▼
Phase 2: LQR residual    Phase 3: Stanley residual
    │                      │
    ├──────────────────────┘
    ▼
Phase 4: safety-aware tracking validation
    │
    ▼
Phase 5: joint validation
    │
    ▼
Phase 6: final report
```

**并行规则：**

| Phase | 依赖 | 可并行 |
|-------|------|--------|
| Phase 1: baseline | 无 | 不可（必须先完成获取 baseline metrics） |
| Phase 2: LQR residual | Phase 1 | 可与 Phase 3 并行（如果前站 Agent 支持并发调用） |
| Phase 3: Stanley residual | Phase 1 | 可与 Phase 2 并行 |
| Phase 4: safety-aware tracking | Phase 2 + Phase 3 | 不可（依赖两者结果） |
| Phase 5: joint validation | Phase 4 | 不可（依赖 safety 验证） |
| Phase 6: final report | Phase 5 | 不可（依赖全部完成） |

**Phase 失败传播规则：**

| 失败场景 | 后续行为 |
|---------|---------|
| Phase 1 (baseline) 失败 | 所有后续 phase 自动 skipped。stop_reason = `train_command_invalid`。 |
| Phase 2 (LQR residual) 失败 | Phase 3 继续执行（不依赖 Phase 2）。Phase 4 的处理取决于 Phase 3 的结果：如果 Phase 3 成功，Phase 4 降级执行（只验证 Stanley residual，跳过 LQR 验证）；如果 Phase 3 也失败，Phase 4 skipped。 |
| Phase 3 (Stanley residual) 失败 | 同上，Phase 4 只验证 LQR（降级模式）。 |
| Phase 2 和 Phase 3 都失败 | Phase 4、5、6 全部 skipped。 |
| Phase 4 (safety validation) 失败 | Phase 5 (joint validation) skipped。Phase 6 (final report) 仍然执行，但记录 safety validation 未完成。 |
| Phase 5 (joint validation) 失败 | Phase 6 仍然执行，记录 joint validation 失败原因。 |

**非 HRRL 项目（4-phase）失败传播：**

| 失败 Phase | 影响 | 最终行为 |
|-----------|------|---------|
| Phase 1 (baseline) 失败 | Phase 2/3/4 全部跳过 | 直接进入 final report（记录失败原因） |
| Phase 2 (reward optimization) 失败 | Phase 3 (validation) 跳过（无 accepted candidate 可验证） | Phase 4 (final report) 仍执行 |
| Phase 3 (validation) 失败 | 无 | Phase 4 (final report) 仍执行 |

executor 在 phase 失败时：
1. 将 phase status 设为 `failed`。
2. 记录失败原因到 `logs/events.jsonl`。
3. 根据上表决定后续 phase 的状态（`skipped` 或继续）。
4. 不自动重试失败的 phase（除非前站 Agent 显式调用 `run --phase <id>` 重试）。

**并行执行约束：**

- **V1 始终串行执行。** 使用全局 lock 文件（`.research-agent/lock`），任意时刻只有一个 mutating 命令运行。
- Phase 2 和 Phase 3 串行执行，顺序由 `experiment_plan.phases` 列表决定。
- candidate_id 的 optimizer 命名空间（`cand_rew_*`、`cand_res_*`）是前向兼容设计，为未来 V2 并行执行预留，V1 中仅用于区分来源。

**Phase 间数据传递：**

| 产出方 | 消费方 | 传递内容 |
|--------|--------|---------|
| Phase 1 | Phase 2, 3 | baseline metrics（只读） |
| Phase 2 | Phase 4 | accepted LQR residual candidate + metrics |
| Phase 3 | Phase 4 | accepted Stanley residual candidate + metrics |
| Phase 4 | Phase 5 | safety validation result |
| Phase 5 | Phase 6 | joint validation result + all metrics |

**Phase budget 分配：**

每个 phase 的 `budget.max_candidates` 和 `budget.max_full_evals` 是该 phase 的独立上限（sub-budget），不是全局 budget 的分区。全局 budget 是总上限，phase budget 是单 phase 上限。当全局 budget 耗尽时，所有 phase 停止，`phase` 进入 `budget_exhausted`，`stop_reason` 使用具体原因（如 `budget_wall_clock`、`budget_max_candidates`）。当某 phase 的 sub-budget 耗尽时，仅该 phase 停止，其他 phase 可继续。`plan-experiments` 命令验证：所有 phase sub-budget 之和不超过全局 budget（如有上限），否则输出 warning 但不阻塞。

| Phase | max_candidates | max_full_evals | 说明 |
|-------|---------------|---------------|------|
| Phase 1: baseline | 0 | 0 | 只跑 baseline，不生成 candidate。使用 config.yaml 的 `execution.train_command` 和 `execution.eval_command`，seed 使用 `execution.full_eval_seeds`。Phase 1 的 train+eval 不计入 max_full_evals（它是 baseline 建立，不是 optimizer candidate 评估）。max_full_evals=0 表示 Phase 1 不生成 optimizer candidate。 |
| Phase 2: LQR residual | 15 | 5 | 主要优化 phase |
| Phase 3: Stanley residual | 15 | 5 | 主要优化 phase |
| Phase 4: safety tracking | 5 | 2 | 验证性质，不需要大量 candidate |
| Phase 5: joint validation | 0 | 3 | 不生成新 candidate，只验证组合。每次 joint test（apply 组合 patch + 全部 seeds 训练评估）计为 1 full_eval，无论成功或失败（防止无限重试）。max_full_evals=3 允许最多 3 次 joint test。 |
| Phase 6: final report | 0 | 0 | 只生成报告 |

---

## 九、Paper Evidence Pipeline

论文阶段是确定性 evidence pipeline，不是随意灵感池。

### 9.1 搜索

`search-papers` 根据 objective、task classification、selected strategies、metrics 和项目上下文生成 queries。

**Query 生成策略：**

query 来源按优先级排列：

| 来源 | 生成方式 | 示例 |
|------|---------|------|
| objective.focus | 每个 focus 词 + "reward" / "RL" | `"fall rate reward shaping RL"` |
| task_classification.task_types | 类型名拆词 + "paper" | `"residual control reinforcement learning"` |
| strategy_selection.strategies | 策略名直查 | `"safety-aware tracking reward"` |
| metrics.primary | metric 名 + "optimization" | `"tracking error optimization reward"` |
| project context keywords | 从 understand 输出提取关键词 | `"LQR residual Stanley path tracking"` |

**去重规则：**

- 对所有生成的 query 做小写 + 去标点 + 排序。
- 相同词集的 query 只保留一个。
- 最终 query 数量上限：10（可在 config.yaml 的 `literature.max_queries` 覆盖）。

**搜索参数：**

```python
arxiv_search(
    queries=generated_queries,
    max_results_per_query=config.literature.get("max_results_per_query", 20),
    sort_by="relevance",  # "relevance" | "lastUpdatedDate" | "submittedDate"
    sort_order="descending",
)
```

- 去重：不同 query 可能返回相同论文（相同 arxiv ID），合并后去重。
- 总论文数上限：`max_results_per_query * max_queries`（默认 200）。

**搜索失败处理：**

| 场景 | 处置 |
|------|------|
| arxiv API 超时 | 重试 3 次，间隔 5s |
| arxiv API 返回 0 结果 | 记录 warning，继续（不阻塞） |
| 网络不可用 | 输出 `LITERATURE_SEARCH_FAILED` error_code |
| 某些 query 返回 0 结果 | 跳过该 query，不报错 |

输出：

```text
reports/arxiv_papers.md
logs/arxiv_papers.jsonl
```

**`logs/arxiv_papers.jsonl` 格式：**

```json
{"paper_id": "arxiv:2401.12345", "title": "Safety-Aware Reward Shaping for Autonomous Driving", "abstract": "This paper studies reward shaping for safe autonomous control.", "authors": ["Alice", "Bob"], "published": "2024-01-15", "arxiv_url": "https://arxiv.org/abs/2401.12345", "categories": ["cs.AI", "cs.LG"]}
```

### 9.2 分类

`classify-papers` 把论文分到 reward/control/safety 等类别。

**分类方法：LLM + 规则混合。**

| 步骤 | 方法 | 说明 |
|------|------|------|
| 1. 关键词预分类 | 规则引擎 | 论文标题/摘要中出现 `classification_categories` 中的关键词时，预标记类别 |
| 2. LLM 精分类 | LLM | 对每篇论文，prompt LLM 从 `classification_categories` 中选择 1-3 个最匹配的类别 |
| 3. 合并 | 规则 | 取 LLM 输出为主，关键词预分类为补充（如果 LLM 返回空，fallback 到关键词结果） |

**分类 prompt：**

```text
System: You are a paper classifier for RL research. Given paper title and abstract, classify into 1-3 categories.

User:
Title: {title}
Abstract: {abstract}

Categories: {classification_categories}

Return JSON: {"categories": ["<cat1>", "<cat2>"], "confidence": 0-1}
```

**LLM 不可用时的降级：**

纯关键词匹配。在标题和摘要中搜索每个 category 的关键词（取 category 名称的各单词）。匹配数量最多的 category 作为主分类。confidence 上限 0.5。

类别关键词映射（用于降级 fallback）：

| category | 关键词 |
|----------|--------|
| reward shaping | reward, shaping, potential |
| penalty and constraint design | penalty, constraint, safety |
| curriculum reward | curriculum, staged, progressive |
| robotics locomotion reward | locomotion, walking, bipedal, quadruped |
| control energy and smoothness | energy, smoothness, torque |
| reward hacking and specification gaming | hacking, gaming, overoptimization |
| residual control | residual, compensation, augmentation |
| path tracking control | tracking, path, trajectory, lateral |

```text
reward shaping
penalty and constraint design
curriculum reward
robotics locomotion reward
control energy and smoothness
reward hacking and specification gaming
residual control
path tracking control
```

输出：

```text
reports/paper_taxonomy.md
logs/paper_taxonomy.jsonl
```

### 9.3 确定性选择

`select-papers` 计算：

```text
relevance_score =
  0.35 * objective_match
+ 0.25 * metric_match
+ 0.15 * state_action_match
+ 0.15 * implementation_feasibility
+ 0.10 * recency_or_influence
```

**各子分数定义与计算方式：**

| 子分数 | 权重 | 计算方式 | 值域 |
|--------|------|---------|------|
| `objective_match` | 0.35 | LLM 评估论文摘要与 objective 的语义相关度。prompt: "Rate how relevant this paper's contribution is to the research objective on a scale of 0-1." 输出归一化到 [0, 1]。 | [0, 1] |
| `metric_match` | 0.25 | 论文摘要/标题中出现 primary metrics 关键词的数量占比。匹配规则：将 metric name 中的下划线替换为空格后进行大小写不敏感的子串匹配（如 `fall_rate` → 匹配 "fall rate"，`tracking_error` → 匹配 "tracking error"，`episode_length` → 匹配 "episode length"）。`matched_count / total_primary_metrics`，clamped to [0, 1]。 | [0, 1] |
| `state_action_match` | 0.15 | LLM 评估论文实验设置与目标项目的 state/action 空间相似度。prompt: "Rate similarity of the experimental setup (state space, action space, environment) to the target project on a scale of 0-1." | [0, 1] |
| `implementation_feasibility` | 0.15 | LLM 评估论文方法在目标项目中实现的可行性。prompt: "Rate the feasibility of implementing this paper's approach in the target project (considering code complexity, dependencies, and compatibility) on a scale of 0-1." | [0, 1] |
| `recency_or_influence` | 0.10 | `max(0, 1 - (current_year - pub_year) / 10)` 对于已知年份的论文。arxiv API 不提供引用数，因此不使用引用数加成。年份未知时默认 0.5。如果论文在 arxiv 结果中出现多次（不同版本），取最新版本的年份。 | [0, 1] |

**`metric_regex` aggregate 语义：**

- `last`：对于 stdout/stderr，取最后一次匹配的值（输出流中最后出现的匹配行）。对于文件 glob，取最近修改的匹配文件中的值。如果多个文件 mtime 相同（Windows mtime 精度为 2 秒），按文件路径字典序作为 tiebreaker。
- `max`：取所有匹配中的最大值。
- `min`：取所有匹配中的最小值。
- `mean`：取所有匹配的算术平均值。

**确定性保证：**

- LLM 评估的子分数（`objective_match`、`state_action_match`、`implementation_feasibility`）使用 temperature=0 + 固定 seed（如果 API 支持）。确定性主要通过缓存保证：相同输入命中缓存时直接返回，不调用 LLM。如果 API 不支持 seed 参数，相同输入的首次调用可能产生微小差异，但后续调用均命中缓存。
- 每篇论文的子分数缓存到 `cache/paper_scores.json`，后续调用直接读缓存。
- **缓存 key**：`sha256(scoring_schema_version + paper_id + objective_hash + metric_specs_hash + project_context_hash + scoring_year)`。
- `objective_hash` = `sha256(json.dumps({"name": objective.name, "description": objective.description, "focus": sorted(objective.focus)}, sort_keys=True))[:16]`。
- `metric_specs_hash` = `sha256(json.dumps(primary metric name/direction/weight 列表, sort_keys=True))[:16]`。
- `project_context_hash` = `sha256(project_understanding.control_structure + optimizer_affinity + state/action 摘要)[:16]`。
- `scoring_year` 使用当前 UTC 年份，确保 `recency_or_influence` 随年份变化时缓存自动失效。
- **缓存失效**：以上任一 key 组成字段变化即缓存失效。`cache clear` 命令删除 `cache/` 目录下的所有文件（包括 `paper_scores.json` 和其他缓存文件）。
- **缓存格式**：`{"caches": [{"key": "sha256_hex", "paper_id": "arxiv:2401.12345", "scores": {"objective_match": 0.8, "metric_match": 0.6, "state_action_match": 0.7, "implementation_feasibility": 0.9, "recency_or_influence": 0.8}, "cached_at": "ISO8601"}]}`。
- 相同输入（相同 paper list + 相同 objective + 相同 metrics）必须产出相同 Top-K。

选择规则：

1. 过滤低于 `literature.min_relevance_score` 的论文。
2. 按 `relevance_score` 降序。
3. 分数相同按 objective_match、metric_match、年份、paper id 稳定排序。
4. 选出 Top-K。

输出：

```text
reports/selected_reward_evidence.md
logs/selected_reward_evidence.jsonl
```

optimizer proposal 只能引用 selected papers。不能从未选中的论文临时挑依据。

---

## 十、Optimizer 接口

每个 optimizer 必须实现统一接口：

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ProjectContext:
    project_path: Path
    work_dir: Path
    project_understanding: dict
    file_index: dict[str, list[str]]  # {filename: [abs_paths]}


@dataclass
class MetricSpec:
    name: str
    direction: str  # "lower_is_better" | "higher_is_better"
    weight: float = 1.0                      # primary/safety metrics 使用，diagnostic 忽略。默认 1.0（等权重）
    min_improvement_pct: float = 0.01        # primary metrics 使用。如果 front_agent_objective.json 未指定，使用 config.yaml 的 metric_thresholds.default_min_improvement_pct（默认 0.01）
    max_regression_pct: float = 0.10         # primary metrics 使用，超过此值直接 reject
    hard_violation_threshold: float | None = None  # safety metrics only。绝对值阈值：candidate 的 safety metric 值（非 change_pct）超过此值即为 hard violation。例如 residual_magnitude > 0.50，无论 baseline 如何。


@dataclass
class Objective:
    name: str
    description: str
    focus: list[str]
    primary_metrics: list[MetricSpec]   # 从 front_agent_objective.json metrics.primary 读取
    safety_metrics: list[MetricSpec]    # 从 front_agent_objective.json metrics.safety 读取
    diagnostic_metrics: list[MetricSpec]  # 从 front_agent_objective.json metrics.diagnostic 读取
    primary_score_threshold: float  # 从 config.yaml 的 objective.primary_score_threshold 读取（不在 front_agent_objective.json 中）
    hard_primary_regression_policy: str  # "reject" | "warn"，从 config.yaml 读取。"reject"=超过 max_regression_pct 直接 reject；"warn"=记录警告但不自动 reject（仍由总分和 safety_penalty 决定）
    mean_reward_role: str  # "diagnostic_only" | "primary"
    metric_regex: dict  # 优先从 front_agent_objective.json metrics.metric_regex 读取，fallback 到 config.yaml
    cv_threshold: float = 0.3  # 从 config.yaml 的 metrics.cv_threshold 读取
    instability_weight: float = 0.5  # 从 config.yaml 的 metrics.instability_weight 读取
    screening_threshold: float = 0.0  # 从 config.yaml 的 metrics.screening_threshold 读取


@dataclass
class Constraints:
    forbidden_changes: list[str]
    require_human_review_for: list[str]


@dataclass
class Candidate:
    candidate_id: str  # 格式: "cand_{optimizer_prefix}_{seq:03d}", 如 "cand_rew_001"
    optimizer: str
    phase_id: str  # 所属 phase，如 "lqr-residual"
    status: str  # 见 candidate lifecycle
    proposal: dict
    patch_path: Path | None
    screening_result: dict | None
    full_eval_result: dict | None
    improve_score: float | None
    rejection_reason: str | None
    evidence_refs: list[str]  # selected paper IDs
    created_at: str  # ISO 8601
    updated_at: str  # ISO 8601，每次状态变更时更新


# Candidate ID 命名空间规则：
# 格式: cand_{optimizer_prefix}_{seq:03d}
# optimizer_prefix 由各 optimizer 定义：
#   - reward optimizer: "rew" -> cand_rew_001, cand_rew_002, cand_rew_003
#   - residual_control optimizer: "res" -> cand_res_001, cand_res_002, cand_res_003
# 序号在每个 optimizer 命名空间内独立递增，不全局共享。
# 这确保并行 phase（如 Phase 2 和 Phase 3）的 candidate_id 不会冲突。
#
# 存储位置: {work_dir}/logs/candidates.jsonl 中按 candidate_id 索引。
# state.json 的 candidate_queue 和 needs_more_evidence 列表存储 candidate_id 字符串引用。


@dataclass
class GuardResult:
    allowed: bool
    violations: list[str]  # 如 ["修改了 observation_space", "修改了 algorithm_body"]
    warnings: list[str]


@dataclass
class PatchGenerationResult:
    success: bool
    patch_path: Path | None
    error_code: str | None
    message: str | None


@dataclass
class RunResult:
    success: bool
    exit_code: int
    metrics: dict[str, float]  # {metric_name: value}
    log_path: Path
    duration_seconds: float


@dataclass
class AnalyzeResult:
    verdict: str  # "improved" | "degraded" | "inconclusive"
    primary_score: float
    safety_penalty: float
    instability_penalty: float
    candidate_improve_score: float
    improve_score_ci_low: float   # bootstrap 95% CI 下界（1000 次重采样）
    improve_score_ci_high: float  # bootstrap 95% CI 上界
    metric_details: dict[str, dict]  # {metric: {baseline, candidate, change_pct, ci_low, ci_high}}
    notes: str


@dataclass
class CleanupResult:
    removed_files: list[str]
    preserved_files: list[str]
    freed_bytes: int


class Optimizer(Protocol):
    name: str
    supported_task_types: list[str]

    def __init__(
        self,
        project_context: ProjectContext,
        config: dict,
        llm_client: LLMClient,
    ) -> None:
        """构造函数。

        Args:
            project_context: 项目上下文（路径、文件索引、understanding 结果）。
            config: 合并后的完整 config dict。
            llm_client: LLM 调用客户端（所有 optimizer 共享同一实例）。
        """
        raise NotImplementedError

    def inspect(
        self,
        objective: Objective,
        constraints: Constraints,
    ) -> dict:
        """扫描项目，返回 optimizer 识别到的可优化对象和当前状态。

        Returns:
            {
                "optimizable_targets": list[dict],  # [{name, file, line_range, type}]
                "readonly_targets": list[dict],
                "current_reward_structure": dict | None,
                "confidence": float,
            }
        """
        raise NotImplementedError

    def plan_phase(
        self,
        strategy: str,
        context: ProjectContext,
        objective: Objective,
        constraints: Constraints,
    ) -> dict:
        """为当前 optimizer 规划一个实验 phase。

        Returns:
            {
                "phase_id": str,           # 如 "lqr-residual"
                "optimizer": str,
                "objective_summary": str,
                "allowed_changes": list[dict],   # [{"type": str, "file"?: str, "line_range"?: [int,int], "symbol"?: str}]
                "forbidden_changes": list[dict],  # [{"type": str, "file"?: str, "symbol"?: str}]
                "train_command": str,
                "eval_command": str,
                "primary_metrics": list[str],
                "safety_metrics": list[str],
                "budget": {
                    "max_candidates": int,
                    "max_full_evals": int,
                    "timeout_seconds": int,
                },
                "rollback_policy": str,  # "git_checkout"（默认，回滚到 current best commit）| "git_stash"（stash 改动）| "none"（不回滚，用于 joint validation 等场景）
            }
        """
        raise NotImplementedError

    def propose_candidate(
        self,
        phase: dict,
        evidence: list[dict],   # selected papers
        history: list[Candidate],
        knowledge_base: dict,
        extracted_ideas: list[dict] | None = None,  # 从 extract-ideas 输出
    ) -> Candidate:
        """基于 evidence 和 history 生成一个新的 candidate proposal。

        约束：
        - proposal 必须引用 evidence 中的 paper ID。
        - 不得违反 phase["forbidden_changes"]。
        - 不得重复 history 中已 rejected 的假设（除非有新 evidence）。
        - proposal 不是 patch，只是结构化修改意图。此步骤不得修改项目文件。

        Returns:
            Candidate 对象，status 必须为 "proposed"，patch_path 必须为 None。
        """
        raise NotImplementedError

    def generate_patch(
        self,
        candidate: Candidate,
        phase: dict,
        project_state: ProjectContext,
    ) -> PatchGenerationResult:
        """把 proposal 转换成 unified diff patch 文件。

        流程：
        1. 读取 candidate.proposal 中的结构化修改意图。
        2. 只打开 phase["allowed_changes"] 指向的文件和 symbol / line_range。
        3. 生成 unified diff，写入 work_dir/patches/{candidate_id}.patch。
        4. 使用 unidiff 解析 patch；解析失败返回 PATCH_GENERATION_FAILED。
        5. 成功时设置 candidate.patch_path，但不 apply patch。

        Returns:
            PatchGenerationResult。success=False 时命令输出 PATCH_GENERATION_FAILED。
        """
        raise NotImplementedError

    def guard_candidate(
        self,
        candidate: Candidate,
        project_state: ProjectContext,
        constraints: Constraints,
    ) -> GuardResult:
        """检查 candidate patch 是否违反权限边界。

        检查内容：
        - candidate.patch_path 必须存在；缺失时返回 PATCH_GENERATION_FAILED。
        - patch 是否修改了 forbidden_changes 中列出的文件/函数。
        - patch 是否修改了 require_human_review_for 中列出的区域。
        - patch 是否只修改了该 optimizer 允许的区域。

        Returns:
            GuardResult，allowed=True 时 candidate.status 更新为 "guarded"。
        """
        raise NotImplementedError

    def run_candidate(
        self,
        candidate: Candidate,
        train_command: str,
        eval_command: str,
        seeds: list[int],
        timeout_per_seed: int,
    ) -> RunResult:
        """执行 candidate 的训练和评估。

        流程（逐 seed 串行）：
        1. 应用 candidate patch 到工作区。
        2. 对每个 seed：
           a. 执行 train_command（设置 env 变量 SEED=<seed>）。
           b. 等待训练完成或超时（timeout_per_seed）。
           c. 执行 eval_command（设置 env 变量 SEED=<seed>）。
           d. 解析 eval 输出中的 metrics（见下方 metric 解析规则）。
           e. 清理该 seed 的临时 checkpoint（如果 policy 要求）。
        3. 回滚 patch（恢复到 current best commit）。
        4. 聚合所有 seed 的 metrics（mean）。

        为什么不 train_all_then_eval：每个 seed 独立 train+eval 可以尽早发现
        失败的 seed，避免浪费时间训练后续 seed。

        **Metric 解析规则：**

        使用 `objective.metric_regex` 中定义的正则表达式从 eval 输出中提取 metric 值。

        解析流程：
        1. 对每个 metric，读取其 `metric_regex` 配置。
        2. 根据 `log_file` 定位输出：
           - `"stdout"`：使用 eval_command 的 stdout 输出。
           - `"stderr"`：使用 eval_command 的 stderr 输出。
           - glob 模式（如 `"eval/*.json"`）：匹配 project_root 下的文件，读取内容。
        3. 对定位到的内容应用 `regex`，提取 `group` 指定的捕获组。
        4. 如果有多次匹配，根据 `aggregate` 聚合：
           - `"last"`：取最后一次匹配。
           - `"max"`：取所有匹配的最大值。
           - `"min"`：取所有匹配的最小值。
           - `"mean"`：取所有匹配的算术平均。
        5. 转换为 float。如果转换失败，记录 warning 到 experiments.jsonl，该 seed 的该 metric 标记为 None。
        6. 如果某个 metric 在所有 seed 中都解析失败，RunResult.success=False，exit_code=-2。

        **train/eval 命令环境变量：**

        | 变量 | 值 | 说明 |
        |------|------|------|
        | `SEED` | 当前 seed 值 | 随机种子 |
        | `CANDIDATE_ID` | candidate_id | 当前 candidate 标识 |
        | `PHASE_ID` | phase_id | 当前 phase 标识 |
        | `WORK_DIR` | .research-agent 绝对路径 | 工作目录 |
        | `PROJECT_ROOT` | 项目根目录绝对路径 | 项目根目录 |

        Returns:
            RunResult，包含聚合后的 metrics。
        """
        raise NotImplementedError

    def analyze_result(
        self,
        candidate: Candidate,
        baseline_metrics: dict[str, float],
        current_best_metrics: dict[str, float],
        objective: Objective,
    ) -> AnalyzeResult:
        """分析 candidate 结果，判定 verdict。

        判定逻辑见 11.2 节 accepted 条件。

        Returns:
            AnalyzeResult。
        """
        raise NotImplementedError

    def cleanup(
        self,
        candidate: Candidate,
        policy: str,  # "full" | "light" | "none"
    ) -> CleanupResult:
        """清理 candidate 的训练产物。

        policy="full": 清理 checkpoint、wandb、临时权重、大日志。
        policy="light": 只清理 checkpoint 和 wandb。
        policy="none": 不清理。

        必须保留：candidate ledger、patch、proposal summary、metrics summary、rejection reason。

        Returns:
            CleanupResult。
        """
        raise NotImplementedError
```

**exceptions.py 异常类定义：**

```python
class ResearchAgentError(Exception):
    """所有 research-agent 异常的基类。"""
    error_code: str
    message: str
    next_action: str

class LLMCallError(ResearchAgentError):
    """LLM API 调用失败（重试耗尽后抛出）。"""
    error_code = "LLM_SERVICE_UNAVAILABLE"
    def __init__(self, message: str, retries: int, last_error: str):
        self.message = message
        self.retries = retries
        self.last_error = last_error
        self.next_action = "Wait for LLM service to recover, then retry."

class LLMResponseParseError(ResearchAgentError):
    """LLM 返回的 JSON 无法解析（重试耗尽后抛出）。"""
    error_code = "LLM_INVALID_RESPONSE"
    def __init__(self, message: str, raw_response: str):
        self.message = message
        self.raw_response = raw_response
        self.next_action = "Wait for LLM service to recover, then retry."

class GuardViolationError(ResearchAgentError):
    """candidate patch 违反权限边界。"""
    error_code = "GUARD_VIOLATION"
    def __init__(self, violations: list[str]):
        self.violations = violations
        self.message = f"Guard violations: {violations}"
        self.next_action = "Optimizer should regenerate candidate without violating constraints."

class BudgetExhaustedError(ResearchAgentError):
    """预算耗尽。"""
    error_code = "BUDGET_EXHAUSTED"
    def __init__(self, budget_type: str):
        self.message = f"Budget exhausted: {budget_type}"
        self.next_action = "Call 'report --json' to get results."

class PatchApplyError(ResearchAgentError):
    """git apply 失败。"""
    error_code = "PATCH_APPLY_FAILED"
    def __init__(self, patch_path: str, git_error: str):
        self.message = f"Failed to apply patch {patch_path}: {git_error}"
        self.next_action = "Check patch file and project state."

class PatchRollbackError(ResearchAgentError):
    """git rollback 失败。"""
    error_code = "PATCH_ROLLBACK_FAILED"
    def __init__(self, git_error: str):
        self.message = f"Failed to rollback: {git_error}"
        self.next_action = "Manual intervention required to restore workdir."

class StateFileCorruptError(ResearchAgentError):
    """state.json 无法解析。"""
    error_code = "STATE_FILE_CORRUPT"
    def __init__(self, parse_error: str):
        self.message = f"state.json corrupt: {parse_error}"
        self.next_action = "Check state.json, or delete and re-init."

class LiteratureError(ResearchAgentError):
    """文献 pipeline 错误（搜索/分类/选择阶段）。"""
    def __init__(self, error_code: str, message: str, next_action: str):
        self.error_code = error_code
        self.message = message
        self.next_action = next_action

class DependencyMissingError(ResearchAgentError):
    """前置依赖缺失（如 objective、task_classification 等）。"""
    def __init__(self, error_code: str, message: str, next_action: str):
        self.error_code = error_code
        self.message = message
        self.next_action = next_action
```

**candidate lifecycle 状态机：**

```text
proposed
  │
  ▼
patch_generated
  │
  ▼
guarded
  │
  ▼
screening ──(不通过)──> rejected
  │
  ▼
promoted
  │
  ▼
full_eval ──(明确不通过)──> rejected
  │
  ├─(通过)──> accepted
  │
  └─(接近阈值)──> needs_more_evidence
                      │
                      ├─(追加后通过)──> accepted
                      ├─(追加后不通过)──> rejected
                      └─(预算不足)──> archive_inconclusive

accepted ──(joint validation 冲突)──> needs_revisit

needs_revisit ──(冲突解决)──> accepted 或 rejected
  │
  └─(预算不足)──> archive_inconclusive
```

**`accepted` 非终态说明：** `accepted` 不是绝对终态。在 joint validation（Phase 5）阶段，如果已 accepted 的 candidate 组合后互相破坏，executor 会将涉及的 candidate 状态从 `accepted` 回退为 `needs_revisit`。这是唯一允许从 `accepted` 回退的场景，且仅发生在 joint validation 阶段。

**`needs_revisit` 说明：**

- 仅在 joint validation 阶段触发：当 Phase 2 和 Phase 3 的 accepted candidate 组合后互相破坏时，两个 candidate 都标记为 `needs_revisit`。
- `needs_revisit` 不是失败，而是"需要在新的 joint 上下文中重新评估"。
- 重新评估可以由前站 Agent 决策：调整其中一个 candidate 的 patch 后重新 joint validation，或接受退化并记录。
- `needs_revisit` candidate 仍计入 `resource_usage.candidates`。

**状态转换条件汇总：**

| 转换 | 触发条件 | 定量标准 |
|------|---------|---------|
| proposed → patch_generated | generate_patch.success=True | patch 写入 `patches/{candidate_id}.patch` 且可被 unidiff 解析 |
| proposed → rejected | patch 生成失败 | `PATCH_GENERATION_FAILED`，记录 proposal 和失败原因，不 apply |
| patch_generated → guarded | guard_candidate.allowed=True | patch 无 forbidden_changes 违规，无 human_review 未批准 |
| patch_generated → rejected | guard_candidate.allowed=False | `GUARD_VIOLATION` 或 `GUARD_HUMAN_REVIEW_REQUIRED` |
| guarded → screening | executor 调用 run_candidate | 使用 `execution.screening_seeds`（默认 `[42]`） |
| screening → promoted | screening 结果通过 | `improve_screening_score >= screening_threshold`（默认 0.0）且无 safety hard violation |
| screening → rejected | screening 结果不通过 | promotion 条件的否定：即 `improve_screening_score < screening_threshold` 或存在 safety hard violation。promotion 要求所有条件同时满足，任一条件不满足即 rejection。 |

**`improve_screening_score` 计算规则：**

screening 阶段使用 `screening_seeds`（默认 `[42]`，通常只有 1 个 seed）执行。计算逻辑与 `candidate_improve_score`（section 11.2）相同，但有以下差异：

1. **单 seed 时跳过 instability_penalty**：只有 1 个 seed 无法计算 cv（变异系数），因此 `instability_penalty = 0`。
2. **单 seed 时跳过 bootstrap CI**：seed 数 < 3 时跳过 bootstrap 条件（与 full_eval 规则一致）。
3. **公式简化**：`improve_screening_score = primary_score - safety_penalty`。
4. **single seed 计算方式**：screening 使用单个 candidate seed 值直接与 multi-seed baseline mean 计算 `normalized_change_i`。即 `normalized_change_i = (candidate_single_seed_value_i - baseline_mean_i) / abs(baseline_mean_i)`。baseline mean 来自 Phase 1 的 full_eval 结果（3 seeds 的均值）。
5. **screening_threshold=0.0 的设计意图**：screening 仅过滤 safety hard violation 和明显退化的 candidate，不做质量筛选。`screening_threshold=0.0` 意味着只要 candidate 没有 safety 违规且 `primary_score >= 0`（即没有整体退化），就通过 screening 进入 full_eval。质量筛选由 full_eval 的 accepted 条件（6 条）完成。
6. **目的**：screening 是快速过滤，只做粗筛。通过 screening 不代表 candidate 会被接受，只代表值得投入 full_eval 资源。
| promoted → full_eval | executor 调用 run_candidate | 使用 `execution.full_eval_seeds`（默认 `[42, 123, 456]`） |
| full_eval → accepted | 满足全部 accepted 条件 | 见 11.2 节 6 条 |
| full_eval → rejected | 违反硬约束 | 当 `hard_primary_regression_policy="reject"` 时，任何 primary metric 的 `change_pct_i < -max_regression_pct`（考虑 direction），或 safety metric 的 `hard_violation_threshold` 被触发。当 `policy="warn"` 时，仅 safety hard violation 触发 reject。 |
| full_eval → needs_more_evidence | 接近阈值 | `threshold * 0.5 <= candidate_improve_score < threshold`，或 `ci_low <= -0.01`（bootstrap CI 下界明显为负，与 accepted condition #4 使用同一阈值） |
| needs_more_evidence → accepted | 追加 confirmation_seeds 后通过 | 追加后满足 accepted 全部 6 条 |
| needs_more_evidence → rejected | 追加 confirmation_seeds 后不通过 | 追加后违反硬约束 |
| needs_more_evidence → archive_inconclusive | 预算不足 | `len(confirmation_seeds) * timeout_seconds_per_seed` wall-clock 秒 > 剩余 wall_clock 预算，或 confirmation 会超出 phase 的 max_full_evals / max_candidates sub-budget，或超出全局 max_full_evals / max_candidates |
| accepted → needs_revisit | joint validation 冲突 | Phase 5 中，已 accepted 的 candidate 组合后互相破坏时，executor 回退状态 |
| needs_revisit → accepted | 冲突解决后通过 | 调整 patch 后重新 joint validation 满足 accepted 条件 |
| needs_revisit → rejected | 冲突解决后不通过 | 重新评估后违反硬约束或总分不足 |
| needs_revisit → archive_inconclusive | 预算不足 | 重新评估所需 wall-clock 秒 > 剩余 wall_clock 预算 |

**Patch guard 判定规则：**

1. 使用 `unidiff` 解析 candidate patch，得到每个修改文件和 hunk 行范围；解析失败返回 `PATCH_GENERATION_FAILED`。
2. 将 hunk 行范围与 phase 的 `allowed_changes[].file + line_range/symbol` 求交集；没有交集的修改一律拒绝。
3. 将 hunk 行范围与 `forbidden_changes`、`readonly_targets`、`require_human_review_for` 求交集；命中 forbidden/readonly 返回 `GUARD_VIOLATION`，命中 human review 返回 `GUARD_HUMAN_REVIEW_REQUIRED`。
4. Python 文件必须额外用 AST 建立 symbol range（function/class 起止行）。如果 hunk 落在 reward 函数外，即使同文件也拒绝。
5. Reward optimizer 的 guard 只允许修改 reward scalar 计算相关表达式、权重、term、penalty、normalization 或组合逻辑；修改 observation/action/termination/training/network/metric logging 一律拒绝。
6. Residual control optimizer 的 guard 默认拒绝修改 LQR / Stanley / PID / MPC 基础控制律和经典控制器参数更新逻辑，只允许 residual reward、residual magnitude penalty、safety-aware tracking penalty、potential-based tracking reward、residual action smoothness penalty。
7. guard 不调用 LLM 做最终裁决；LLM 可提供候选解释，但允许/拒绝必须由 patch、phase schema、project understanding targets 和 AST/unidiff 规则确定。

**"applied" 状态约束：**

"applied" 不是一个独立 lifecycle 状态，而是指 "candidate patch 已被 git apply 到工作区" 的瞬时状态。约束：

- 正常运行时任意时刻最多只有一个 candidate 处于 applied 状态。joint validation（Phase 5）允许同时 apply 多个 patch（每个 optimizer 一个），因为其目的是验证组合效果。joint validation 完成后恢复单 patch 约束。
- state.json 的 `applied_patches` 列表跟踪当前 applied 的 patch。正常时列表为空或含 1 个元素；Phase 5 时可含多个元素。`run_candidate` apply patch 时追加元素，rollback 时移除对应元素。`resume` 检查此字段：如果非空，说明 crash 时 patch 未回滚，必须逐一回滚再继续。
- `run_candidate` 开始时 apply patch，结束时必须回滚 patch（无论成功或失败）。
- 回滚后工作区必须回到 current best commit。
- 如果 run_candidate 进程崩溃导致 patch 未回滚，`resume` 必须检测并回滚。

---

## 十一、Reward Optimizer

`optimizers/reward` 继承原 reward 专项方案的核心机制，但只作为插件存在。

### 11.1 Reward-only 定义

只能修改已定位 reward 函数内部，用于计算 scalar reward 的表达式、权重、reward term、penalty term、normalization 或组合逻辑。

允许：

- reward 权重。
- reward term / penalty term。
- reward shaping。
- reward normalization。
- alive bonus、fall penalty、tracking penalty、control energy penalty、smoothness penalty。

禁止：

- observation / state space。
- action space。
- environment dynamics。
- termination / done / truncated。
- training algorithm、network、optimizer、loss、scheduler、replay buffer。
- metric 定义或日志输出方式。

### 11.2 Objective 与 Improve Score

前站主 Agent 必须提供：

- primary metrics。
- secondary safety metrics。
- diagnostic metrics。
- 权重。
- min improvement threshold。
- max regression threshold。

`mean_reward` 默认只能是 diagnostic，不能作为主要成功标准。

综合分数：

```text
primary_score =
  Σ(weight_i * normalized_change_i) / Σ(weight_i)
  # 权重按 phase 归一化：每个 phase 的 primary_score 仅使用该 phase 的 primary metrics。
  # Σ(weight_i) 仅对当前 active phase 的 primary metrics 求和。

candidate_improve_score =
  primary_score
  - safety_penalty
  - instability_penalty
```

**primary_score 计算细则：**

```text
对于每个 primary metric i:
  baseline_mean_i = mean(baseline_seeds_i)
  candidate_mean_i = mean(candidate_seeds_i)
  change_pct_i = (candidate_mean_i - baseline_mean_i) / abs(baseline_mean_i)
  # baseline_mean_i 为 0 时，使用绝对差值: change_pct_i = candidate_mean_i - baseline_mean_i

  # 归一化到 [-1, 1]，防止极端值主导
  normalized_change_i = clamp(change_pct_i, -1.0, 1.0)

  # 如果方向与 objective 不一致（如 tracking_error 应该越小越好），取反
  # metric_direction[i] 来自 Objective.primary_metrics[i].direction
  if objective.primary_metrics[i].direction == "lower_is_better":
    normalized_change_i = -normalized_change_i

  # 注意：不在此处 clip。超过 max_regression_pct 的退化由 accepted 条件 #3 单独处理（直接 reject）。
  # primary_score 使用未 clip 的 normalized_change_i，保留真实退化幅度用于排序和报告。

primary_score = Σ(weight_i * normalized_change_i) / Σ(weight_i)
```

**safety_penalty 计算细则：**

```text
safety_penalty = 0

对于每个 safety metric j:
  baseline_mean_j = mean(baseline_seeds_j)
  candidate_mean_j = mean(candidate_seeds_j)
  change_pct_j = (candidate_mean_j - baseline_mean_j) / abs(baseline_mean_j)

  # metric_direction[j] 来自 Objective.safety_metrics[j].direction
  if objective.safety_metrics[j].direction == "lower_is_better":
    # safety metric 越小越好（如 fall_rate、constraint_violation）
    if change_pct_j > 0:  # 恶化
      safety_penalty += change_pct_j * safety_weight_j
  else:
    # safety metric 越大越好（如 stability_score）
    if change_pct_j < 0:  # 恶化
      safety_penalty += abs(change_pct_j) * safety_weight_j

# safety_weight_j 默认 1.0，可在 config.yaml 的 metrics.safety_weights 中覆盖
# safety_penalty 无上限，足以 reject 任何 candidate
```

**instability_penalty 计算细则：**

```text
对于每个 primary metric i:
  cv_i = std(candidate_seeds_i) / abs(mean(candidate_seeds_i))
  # cv = coefficient of variation（变异系数）

instability_penalty = Σ(instability_weight * max(0, cv_i - cv_threshold)) / count(primary_metrics)

# cv_threshold 默认 0.3（30% 变异系数），可在 config.yaml 中覆盖
# instability_weight 默认 0.5
# 含义：如果 candidate 在不同 seed 上表现差异过大（cv > 30%），施加惩罚
```

**accepted 条件详解：**

1. `candidate_improve_score >= objective.primary_score_threshold`。
   - threshold 默认 0.05（即综合改善 5%）。
2. 至少一个 primary metric 达到自己的 `min_improvement_pct`。
   - `min_improvement_pct` 默认 0.01（1%），可在 config.yaml 的 `metrics.metric_thresholds` 中按 metric 覆盖。
   - 含义：不允许所有 metric 都微弱改善（如每个 +0.5%）凑出总分。
3. 没有 primary metric 超过 `max_regression_pct`（safety metrics 由 `hard_violation_threshold` 和 `safety_penalty` 单独处理，不适用此条件）。
   - `max_regression_pct` 默认 0.10（10%），可在 config.yaml 中覆盖。
   - 当 `hard_primary_regression_policy` 为 `"reject"`（默认）时，任何 primary metric 退化超过此阈值直接 reject，不看总分。
   - 当 `hard_primary_regression_policy` 为 `"warn"` 时，记录警告到 `logs/events.jsonl`，但不自动 reject（仍由 `candidate_improve_score` 和其他条件决定）。此模式用于实验性探索。
   - safety metric 的退化由 `hard_violation_threshold` 控制（条件 #6 的 safety hard violation），以及 `safety_penalty` 在总分中扣减。
4. bootstrap CI 不明显反对改善趋势。
   - 对 `candidate_improve_score` 做 bootstrap（1000 次重采样）。
   - 计算 95% CI: `[ci_low, ci_high]`。
   - 条件：`ci_low > -0.01`。
   - 含义：CI 下界不能明显为负。允许 CI 包含 0（不确定），但不允许 CI 的主体在负区间。
   - seed 数 < 3 时跳过此条件（bootstrap 无意义），直接视为通过。
5. 没有 H5 级 reward hacking 风险。
   - H5（多 seed 不一致）未触发。H1-H4 为 warning 级别，不阻塞 acceptance，但必须记入 `reward_hacking_flags` 和 report。
   - 见下方 reward hacking 检测规则。
6. 满足最低 seed 数。
   - screening 阶段：至少 `len(screening_seeds)` 个 seed。
   - full_eval 阶段：至少 `len(full_eval_seeds)` 个 seed。

**reward hacking 检测规则：**

以下任一条件触发 reward hacking 告警：

| # | 检测项 | 规则 | 处置 |
|---|--------|------|------|
| H1 | diagnostic metric 异常飙升 | `mean_reward`（diagnostic）改善 > primary metric 改善的 3 倍 | warning，不自动 reject，记入 report |
| H2 | episode length 异常变化 | `episode_length` 变化 > 50%（无论方向） | warning，不自动 reject，记入 report |
| H3 | safety metric 极端改善 | safety metric 改善 > 50% | warning（可能是 metric 解析错误或环境变化） |
| H4 | reward scale 异常 | candidate 的 reward 数量级与 baseline 差异 > 5x | warning，不自动 reject，记入 report |
| H5 | 多 seed 不一致 | 同一 candidate 的某个 metric 在不同 seed 上符号相反（如 seed_42 改善 +10%，seed_123 退化 -10%） | 标记为 `inconclusive`，进入 `needs_more_evidence` |

reward hacking 不自动 reject（因为可能是真正的改善），但必须：
- 记入 `logs/candidates.jsonl` 的 `reward_hacking_flags` 字段。
- 记入 `final_report.md` 的 "reward hacking / safety risk" 章节。
- 如果 H1-H5 全部触发，升级为 `needs_more_evidence`，追加 confirmation_seeds。

---

## 十二、Residual Control Optimizer

`optimizers/residual_control` 面向"经典控制器 + RL residual"的科研项目。

### 12.1 control_stack_scanner.py

扫描：

- 基础控制器：LQR、Stanley、PID、MPC。
- residual policy / residual reward。
- 控制器输出合成方式。
- safety gate / constraint。
- tracking error、heading error、lateral error、residual magnitude。

### 12.2 权限边界

默认只读：

- LQR 控制律。
- Stanley 控制律。
- 经典控制器参数更新逻辑。
- RL 算法主体。
- 网络结构。

允许优化：

- residual reward。
- residual magnitude penalty。
- safety-aware tracking penalty。
- potential-based tracking reward。
- residual action smoothness penalty。

### 12.3 HRRL phase 策略

LQR residual phase：

- 目标：平衡残差补偿更稳定。
- primary metrics：fall_rate、balance_error、episode_length。
- safety metrics：residual_magnitude、control_energy。

Stanley residual phase：

- 目标：路径跟踪更稳定。
- primary metrics：tracking_error、heading_error、path_success_rate。
- safety metrics：residual_magnitude、control_energy、constraint_violation_rate。

Joint validation：

- 验证 LQR residual 与 Stanley residual 同时启用时没有互相破坏。
- 不允许只看单阶段改善。

**Joint validation 执行逻辑：**

```text
1. 读取 Phase 2 的 accepted candidate（LQR residual best）的 patch。
2. 读取 Phase 3 的 accepted candidate（Stanley residual best）的 patch。
3. 同时 apply 两个 patch 到工作区（如果冲突，手动 merge）。
4. 使用 full_eval_seeds 执行训练 + 评估。
5. 比较 joint result vs Phase 2 standalone vs Phase 3 standalone vs baseline。
```

**Joint validation 通过条件：**

| 条件 | 规则 |
|------|------|
| LQR metrics 不退化 | joint 的 LQR primary metrics（fall_rate, balance_error）不差于 Phase 2 standalone 的 `joint_validation.lqr_degradation_threshold`（默认 0.90，即 90%） |
| Stanley metrics 不退化 | joint 的 Stanley primary metrics（tracking_error, heading_error）不差于 Phase 3 standalone 的 `joint_validation.stanley_degradation_threshold`（默认 0.90） |
| Safety metrics 不违反 | joint 的 safety metrics 不超过 hard_violation_threshold |
| 综合得分合理 | joint 的加权综合分不低于 max(Phase 2 standalone, Phase 3 standalone) 的 `joint_validation.combined_score_threshold`（默认 0.85） |

**Joint validation 失败处置：**

- 如果 LQR metrics 退化：记录到 knowledge_base，标记 "LQR residual 与 Stanley residual 冲突"。
- 如果 Stanley metrics 退化：同上，标记冲突。
- 如果两者都退化：两个 phase 的 accepted candidate 都标记为 `needs_revisit`。
- 如果 joint validation 因 patch merge 冲突无法执行：计为 1 full_eval，记录冲突原因，两个 candidate 标记为 `needs_revisit`。
- 冲突不自动 reject（可能是环境噪声），但必须记入 report 和 knowledge_base。

**Joint validation 的 patch 合并策略：**

1. Phase 2 和 Phase 3 的 patch 修改的文件如果完全不重叠，直接顺序 apply。
2. 如果有重叠文件（如同一个 reward 函数文件），尝试 3-way merge：
   - base = baseline commit
   - ours = Phase 2 patch
   - theirs = Phase 3 patch
3. 如果 merge 冲突，标记为 `JOINT_VALIDATION_PATCH_CONFLICT`，要求人工介入或前站 Agent 决策。

---

## 十三、Execution Layer

`executor.py` 根据 `state.json` 和 `reports/experiment_plan.json` 执行 phase。`experiment_plan.md` 只供人类阅读，不能作为执行输入。

每个 phase 支持：

```bash
research-agent run --phase baseline
research-agent run --phase lqr-residual
research-agent run --phase stanley-residual
research-agent run --phase joint-validation
```

**`run-plan` 与 `run --phase` 的关系：**

| 命令 | 行为 | 适用场景 |
|------|------|---------|
| `run-plan` | 按 experiment_plan.phases 列表顺序自动执行所有 phase，直到预算耗尽或硬停止。单一进程，内部持有 lock。 | 默认用法，前站 Agent 只需调用一次 |
| `run --phase <id>` | 只执行指定的 phase。适合前站 Agent 手动控制 phase 执行顺序、重试失败的 phase、或并行调用多个 phase。 | 高级用法，需要前站 Agent 编排 |

`run-plan` 是推荐用法。`run --phase` 是逃生舱口，用于 `run-plan` 无法覆盖的场景（如手动重试、选择性跳过 phase）。两者互斥——不能在 `run-plan` 执行期间调用 `run --phase`（会竞争 lock）。如果 `run --phase` 在 `run-plan` 持有 lock 时被调用，`run --phase` 立即返回 `LOCK_BUSY` 错误（不阻塞等待）。

**Phase 执行顺序：**

`experiment_plan.phases` 列表必须按 DAG 拓扑序排列（依赖方在后）。executor 按列表顺序遍历 phases，跳过 dependency 未满足的 phase（标记为 `skipped`）。串行执行时，Phase 2 和 Phase 3 按列表顺序依次执行。

**Baseline 与 candidate 执行顺序：**

1. run-plan 启动后先验证 project_root 是 Git 仓库，且 mutating 命令执行前工作区干净；失败分别返回 `PROJECT_NOT_GIT_REPO` 或 `DIRTY_WORKTREE`。
2. Phase 1 baseline 不生成 patch，不修改项目文件；执行 train/eval 后将 baseline commit、baseline metrics、baseline artifact paths 写入 state/logs。
3. optimizer phase 对每个 candidate 执行：`propose_candidate -> generate_patch -> guard_candidate -> run_candidate(screening) -> analyze -> full_eval/needs_more_evidence/reject -> cleanup`。
4. `generate_patch` 只写 `patches/{candidate_id}.patch`，不 apply；`guard_candidate` 只检查 patch。
5. `run_candidate` apply patch 前追加到 `state.applied_patches` 列表，结束后无论成功失败都 rollback 到 current best commit 并从列表移除对应元素。
6. candidate accepted 且优于 current best 时，executor 创建本地 commit，更新 `state.current_best.commit_hash`、`state.current_best.candidate_id`、`state.current_best.improve_score`。
7. commit 失败时返回 `COMMIT_FAILED`，保留 patch 和 artifacts，停止当前 mutating 命令并要求人工介入。
8. rejected / archive_inconclusive candidate 不保留工作区改动，但必须保留 patch、proposal、metrics summary、ledger 和 rejection reason。

硬停止只允许：

- wall-clock / GPU / max candidates / max full evals 预算耗尽。
- 用户中断。
- 训练命令失效。
- 项目状态损坏。
- 磁盘不足。
- patch 安全违规持续阻塞。

不允许把连续失败、无提升、plateau 或 patience 耗尽作为停止原因。

**进度反馈机制：**

`run-plan` 在执行期间持续更新 `state.json` 中的进度信息，前站 Agent 通过 `status --json` 查询。

`state.json` 中增加 `progress` 字段：

```json
{
  "progress": {
    "current_phase": {
      "phase_id": "lqr-residual",
      "status": "running",
      "candidates_completed": 8,
      "candidates_total_budget": 15,
      "current_candidate": {
        "candidate_id": "cand_rew_009",
        "status": "screening",
        "seeds_completed": 1,
        "seeds_total": 1,
        "started_at": "2026-06-05T12:00:00Z",
        "elapsed_seconds": 1800
      }
    },
    "overall": {
      "phases_completed": 2,
      "phases_total": 6,
      "wall_clock_elapsed_seconds": 86400,
      "wall_clock_budget_seconds": 1209600,
      "budget_usage_pct": 7.1,
      "estimated_remaining_seconds": 1123200
    }
  }
}
```

`status --json` 返回时包含 `progress` 字段。前站 Agent 可据此展示进度条或决定是否干预。

**进度更新时机：**

| 事件 | 更新内容 |
|------|---------|
| phase 开始 | `current_phase.phase_id`、`current_phase.status = "running"` |
| candidate 开始 screening | `current_candidate` 全部字段 |
| seed 训练完成 | `current_candidate.seeds_completed += 1` |
| candidate screening 完成 | `candidates_completed += 1`、清空 `current_candidate` |
| candidate full_eval 开始 | `current_candidate` 更新 |
| phase 完成 | `current_phase.status = "completed"`、`overall.phases_completed += 1` |

---

## 十四、Result Analyzer 与 Knowledge Base

### 14.1 Result Analyzer

比较对象：

```text
candidate vs current best
candidate vs baseline
phase-level result
joint-validation result
```

输出：

```text
improved | degraded | inconclusive
```

`inconclusive` 是证据不足，不是失败。close-call candidate 应进入 `needs_more_evidence` 或等待剩余预算追加 seeds。

### 14.2 Knowledge Base

`knowledge_base.py` 维护：

- accepted candidates。
- rejected candidates。
- inconclusive candidates。
- selected papers。
- failed hypotheses。
- remaining open hypotheses。
- phase-level findings。
- project-specific constraints。

输出：

```text
reports/knowledge_base.md
logs/events.jsonl
logs/candidates.jsonl
```

---

## 十五、Git、清理与基线保护

### 15.1 Git

- 每个 accepted current best 必须有本地 commit。
- 默认不 push GitHub。
- 只有 `git.auto_push_best=true` 且前站主 Agent 确认远程策略后才允许 push。
- degraded / rejected / archive_inconclusive 不保留工作区改动，但保留 patch 和 ledger。

**Git safety policy：**

| 场景 | 行为 |
|------|------|
| `project_root` 不是 Git 仓库 | mutating 命令返回 `PROJECT_NOT_GIT_REPO`。`understand`、`classify-task`、`select-strategy` 可继续只读执行。 |
| 工作区有未提交改动 | `run-plan`、`run --phase`、candidate patch 相关命令默认返回 `DIRTY_WORKTREE`。 |
| 前站 Agent 明确选择 stash | executor 创建 `git stash push -u -m "research-agent pre-run stash <timestamp>"`，stash ref 写入 state；执行结束后不自动 pop，报告 next_action。 |
| baseline commit 不存在 | Phase 1 完成后创建 baseline commit；创建失败返回 `COMMIT_FAILED`。 |
| current best commit 不存在 | 使用 baseline commit 作为 rollback target；如果 baseline 也不存在，返回 `PROJECT_STATE_CORRUPT`。 |
| patch apply 后进程崩溃 | `state.applied_patches` 保持非空，`resume` 逐一 rollback 到 rollback target，再继续。 |
| rollback 失败 | 返回 `PATCH_ROLLBACK_FAILED`，停止所有 mutating 命令，要求人工恢复工作区。 |

**state 中必须记录的 Git 字段：**

```json
{
  "git": {
    "project_is_git_repo": true,
    "baseline_commit": "base123",
    "current_best_commit": "abc123",
    "rollback_target_commit": "abc123",
    "pre_run_stash": null,
    "dirty_worktree_policy": "abort"
  }
}
```

### 15.2 Baseline immutable

baseline 是研究锚点：

- baseline metrics 不改。
- baseline logs 不删。
- baseline commit 不动。
- baseline config 保留。
- baseline seed results 保留。

磁盘压力下，只允许压缩 baseline 原始日志，不允许删除或覆盖。

### 15.3 Cleanup

明显差的 candidate 可以清理：

- 训练 checkpoint。
- TensorBoard / wandb 大文件。
- 临时模型权重。
- rollout dump。
- 重复 stdout/stderr 大日志。

必须保留：

- candidate ledger。
- patch 文件。
- proposal 摘要。
- 指标 summary。
- rejected 原因。
- git commit / rollback 信息。

---

## 十六、报告

`report` 输出：

```text
reports/final_report.md
reports/final_report.json
```

**各报告文件格式：**

所有 `.md` 报告使用统一的 Markdown 结构，便于人类阅读。每个报告文件以一级标题开始，包含生成时间戳和版本号。

`reports/front_agent_objective.md`：
- 从 `front_agent_objective.json` 生成的人类可读版本。
- 包含 objective、constraints、budget、metrics 的格式化展示。
- 模板结构：`# Objective` → `## Name / Description / Focus` → `## Metrics`（表格：name/direction/weight/min_improvement/max_regression）→ `## Constraints`（forbidden_changes 列表）→ `## Budget`（表格）。

`reports/project_understanding.md`：
- 项目类型、控制结构、入口文件、可优化/禁止对象的结构化描述。

`reports/strategy_selection.md`：
- 选中的 optimizer 列表及理由。
- 推荐策略和不推荐策略。

`reports/experiment_plan.md`：
- Phase DAG 的文本表示。
- 每个 phase 的目标、metrics、budget、依赖关系。

`reports/knowledge_base.md`：
- accepted/rejected/inconclusive candidates 摘要。
- 已验证/未验证假设列表。
- phase-level findings。

`reports/final_report.md`：
- 完整研究总结，包含所有 13 个必需章节。
- 内容与 `final_report.json` 一致，Markdown 格式。

报告必须包含：

1. 项目理解摘要。
2. 任务分类和置信度。
3. 策略选择。
4. 实验计划。
5. 论文收集、分类、Top-K selected evidence。
6. 各 phase 结果。
7. current best。
8. candidate ledger 摘要。
9. resource usage 和 stop_reason。
10. cleanup 统计。
11. reward hacking / safety risk。
12. 剩余未验证假设。
13. 下一次研究建议。

如果预算跑满但没有发现更优方案，只能写：

```text
在本预算内未发现更优方案
```

不能写"研究失败"，也不能暗示后续 candidate 不可能变好。

**final_report.json 完整 schema：**

```json
{
  "version": 1,
  "generated_at": "2026-06-05T12:00:00Z",
  "project_path": "E:\\Code\\python\\HRRL0",

  "project_understanding": {
    "project_type": ["residual_rl", "hierarchical_control", "path_tracking"],
    "control_structure": "Dynamic LQR + LQR Residual + Dynamic Stanley + Stanley Residual",
    "train_entry": "train.py",
    "eval_entry": "eval.py",
    "optimizable_targets": ["residual_reward", "residual_magnitude_penalty"],
    "readonly_targets": ["lqr_control_law", "stanley_control_law"]
  },

  "task_classification": {
    "task_types": ["controller_residual_optimization", "reward_optimization", "safety_constraint_optimization"],
    "confidence": 0.86,
    "recommended_strategies": ["residual-aware reward", "safety-aware tracking reward"],
    "not_recommended": ["algorithm_body_change", "base_controller_law_change"]
  },

  "strategy_selection": {
    "selected_optimizers": ["residual_control", "reward"],
    "strategy_rationale": "HRRL control stack contains LQR and Stanley residual policies; V1 can optimize residual rewards while keeping base controllers read-only."
  },

  "experiment_plan": {
    "phases": [
      {
        "phase_id": "baseline",
        "optimizer": null,
        "status": "completed"
      },
      {
        "phase_id": "lqr-residual",
        "optimizer": "reward",
        "status": "completed",
        "candidates_generated": 12,
        "candidates_accepted": 2,
        "candidates_rejected": 8,
        "candidates_archive_inconclusive": 2
      }
    ]
  },

  "literature": {
    "total_papers_found": 45,
    "total_papers_classified": 40,
    "top_k_selected": 5,
    "selected_papers": [
      {
        "paper_id": "arxiv:2401.12345",
        "title": "Safety-Aware Reward Shaping for Residual Reinforcement Learning",
        "relevance_score": 0.82,
        "categories": ["residual control", "reward shaping"]
      }
    ]
  },

  "current_best": {
    "candidate_id": "cand_rew_014",
    "optimizer": "reward",
    "phase": "lqr-residual",
    "commit_hash": "abc123",
    "improve_score": 0.083,
    "metrics": {
      "fall_rate": {"baseline": 0.15, "candidate": 0.08, "change_pct": -0.467},
      "tracking_error": {"baseline": 0.32, "candidate": 0.28, "change_pct": -0.125}
    },
    "safety_metrics": {
      "residual_magnitude": {"baseline": 0.05, "candidate": 0.06, "change_pct": 0.2}
    }
  },

  "candidate_ledger": {
    "total": 18,
    "accepted": 2,
    "rejected": 12,
    "inconclusive": 2,
    "needs_more_evidence": 0,
    "needs_revisit": 0,
    "archive_inconclusive": 2,
    "summary": [
      {
        "candidate_id": "cand_rew_001",
        "optimizer": "reward",
        "status": "rejected",
        "improve_score": -0.02,
        "rejection_reason": "safety metric degraded beyond threshold",
        "evidence_refs": ["arxiv:2401.12345"]
      }
    ]
  },

  "resource_usage": {
    "wall_clock_seconds": 259200,
    "gpu_seconds": null,
    "candidates": 18,
    "full_evals": 6,
    "screening_evals": 12
  },

  "stop_reason": "budget_wall_clock",

  "cleanup_stats": {
    "files_removed": 24,
    "bytes_freed": 1073741824,
    "files_preserved": 48
  },

  "reward_hacking_flags": [
    {
      "candidate_id": "cand_rew_005",
      "flags": ["H1", "H2"],
      "details": "mean_reward improved 3x more than primary metric; episode_length changed 60%"
    }
  ],

  "safety_risks": [],

  "open_hypotheses": [
    "potential-based tracking reward for LQR residual (not yet attempted due to budget exhaustion)",
    "curriculum learning for residual magnitude (requires curriculum optimizer, not yet implemented)"
  ],

  "next_steps": [
    "Increase budget to explore remaining hypotheses",
    "Implement curriculum optimizer for residual magnitude scheduling",
    "Test with additional random seeds for inconclusive candidates"
  ]
}
```

---

## 十七、状态管理

状态文件：

```text
<project_root>/.research-agent/state.json
```

核心字段：

```json
{
  "version": 1,
  "project_path": "E:\\Code\\python\\HRRL0",
  "work_dir": ".research-agent",
  "phase": "initialized",
  "front_agent": {
    "caller": "codex",
    "objective_written": false,
    "objective_file": "front_agent_objective.json"
  },
  "project_understanding": {
    "report": "reports/project_understanding.md",
    "json": "reports/project_understanding.json",
    "project_type": []
  },
  "task_classification": {
    "task_types": [],
    "confidence": 0.0,
    "report": "reports/task_classification.json"
  },
  "strategy_selection": {
    "selected_optimizers": [],
    "report": "reports/strategy_selection.md",
    "json": "reports/strategy_selection.json"
  },
  "experiment_plan": {
    "report": "reports/experiment_plan.md",
    "json": "reports/experiment_plan.json",
    "phases": []
  },
  "git": {
    "project_is_git_repo": null,
    "baseline_commit": null,
    "current_best_commit": null,
    "rollback_target_commit": null,
    "pre_run_stash": null,
    "dirty_worktree_policy": "abort"
  },
  "current_best": null,
  "candidate_queue": [],
  "needs_more_evidence": [],
  "literature": {
    "arxiv_papers": null,
    "paper_taxonomy": null,
    "selected_evidence": null,
    "extracted_ideas": null
  },
  "resource_usage": {
    "wall_clock_seconds": 0,
    "gpu_seconds": null,
    "candidates": 0,
    "full_evals": 0,
    "screening_evals": 0
  },
  "stop_reason": null,
  "progress": null,
  "applied_patches": []
}
```

**`applied_patches` 字段语义：** 空列表 `[]` 表示当前无 patch applied。列表元素格式为 `{"candidate_id": "cand_rew_001", "applied_at": "ISO8601"}`。正常运行时列表最多 1 个元素；joint validation（Phase 5）允许同时 apply 多个 patch（每个 optimizer 一个），此时列表可包含多个元素。`run_candidate` 在 `git apply` 成功后追加元素，在 `git checkout` 回滚后移除对应元素。如果进程在设置后 crash（SIGKILL 等），此字段保留 crash 时的列表状态，`resume` 检测到非空列表后逐一回滚 patch 再恢复。

每个 mutating 命令必须获取 `.research-agent/lock`。stale lock 只能由 `status --clear-stale-lock` 或前站主 Agent 明确处理。

**Lock 实现：**

```python
import os
import json
from pathlib import Path

LOCK_PATH = work_dir / "lock"

def acquire_lock(work_dir: Path, timeout_seconds: int = 300) -> dict:
    """获取 lock 文件。使用 file-based lock + PID 检测。

    实现：
    1. 尝试创建 lock 文件，写入 {"pid": os.getpid(), "started_at": ISO8601, "command": "run-plan"}。
    2. 如果 lock 文件已存在：
       a. 读取 lock 中的 PID。
       b. 检查 PID 是否存活。
       c. 如果 PID 不存活，标记为 stale，获取 lock。
       d. 如果 PID 存活，等待 timeout_seconds 后重试。
    3. 获取成功后，写入 lock 文件。

    注意：不使用 fcntl.flock（Windows 不支持）。使用 create-if-not-exists 原子操作。
    Windows: 使用 open(lock_path, 'x', encoding='utf-8') 创建 lock 文件。
    Unix: 使用 os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)。

    PID 存活检查：
    - Unix: os.kill(pid, 0)，如果抛出 ProcessLookupError 则进程不存在。
    - Windows: 使用 ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)，
      如果返回 NULL 则进程不存在。fallback：检查 lock 文件的 started_at 是否超过 staleness 阈值
      （默认为命令预期时长的 2 倍）。
    """
    raise NotImplementedError

def release_lock(work_dir: Path) -> None:
    """释放 lock 文件。删除 lock 文件。"""
    raise NotImplementedError
```

**state.json 原子写入：**

所有对 `state.json` 的写入必须使用 "write-tmp + atomic-rename" 模式，防止写入中途 crash 导致文件损坏：

```python
import json
import os
import tempfile
from pathlib import Path

def write_state_json(work_dir: Path, state: dict) -> None:
    """原子写入 state.json。

    策略：先写 .tmp 并 fsync，然后 os.replace 直接覆盖 state.json。
    os.replace 在 Unix 上是 rename(2) 原子操作；在 Windows 上是 MoveFileEx
    with REPLACE_EXISTING，同样保证目标文件要么是旧内容要么是新内容，不会出现
    中间状态（空文件或部分写入）。

    crash 安全性分析：
    - crash 在 json.dump/fsync 之前：state.json 保持旧内容（完整）。
    - crash 在 os.replace 期间：文件系统保证 state.json 要么是旧版本要么是新版本。
    - 不存在 state.json 丢失的窗口（无需先备份再替换）。

    启动时清理：如果 state.json.tmp 存在，说明上次写入中途 crash，
    直接忽略即可（state.json 仍为旧内容）。
    """
    state_path = work_dir / "state.json"
    tmp_path = work_dir / "state.json.tmp"

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())

    os.replace(str(tmp_path), str(state_path))
```

**`progress.estimated_remaining_seconds` 计算公式：**

`estimated_remaining_seconds = (wall_clock_elapsed_seconds / max(phases_completed, 1)) * (phases_total - phases_completed)`。当 `phases_completed = 0` 时，使用 Phase 1 的预期时长（如果可用），否则为 null。

**`needs_revisit` 重新评估机制：** `run --phase joint-validation` 会重新评估所有处于 `needs_revisit` 状态的 candidate。前站 Agent 可以在调用前调整 candidate 的 patch（通过修改 patches/ 目录），然后重新运行 joint validation。

**`candidate_ledger.md` 生成规则：** 由 executor 在每次 candidate 状态变更时自动更新（追加或修改行）。`report` 命令也会重新生成此文件。

**state.json 损坏恢复：**

如果 `state.json` 无法解析（JSON decode error），命令必须：
1. 检查 `state.json.tmp` 是否存在且可解析（可能是 crash 时的最新写入）。
2. 如果 tmp 可解析，用 tmp 替换 state.json 并继续。
3. 如果 tmp 不存在或也无法解析，输出 error_code `STATE_FILE_CORRUPT`，要求人工干预。完整的 event-sourced recovery 延迟到 V2。

**state.json 语义不一致恢复：**

以下情况视为 `STATE_FILE_CORRUPT`，先尝试从 `state.json.tmp` 恢复；tmp 也不一致时要求人工介入：

- `phase = "completed"` 但 `stop_reason = null`。
- `phase = "budget_exhausted"` 但 `stop_reason` 不是具体预算原因。
- `state.applied_patches` 非空但某个元素的 patch 文件不存在。
- `state.current_best.commit_hash` 存在但 Git 中找不到该 commit。
- `experiment_plan.json` 不存在但 `state.phase` 已达到 `planned` 或之后。
- `experiment_plan.phases[].status` 与 `state.progress.current_phase` 指向不同 active phase。

**中断进程检测机制：**

当 `resume` 发现 `phase = "running_plan"` 且 `stop_reason = null` 时（可能是 SIGKILL 或 crash 导致信号处理器未执行），使用以下检测逻辑：

1. 检查 lock 文件是否存在。如果存在，读取 lock 中的 PID。
2. 检查 PID 是否存活（Unix: `os.kill(pid, 0)`；Windows: `OpenProcess`）。
3. 如果 PID 存活：进程仍在运行，`resume` 输出 `LOCK_BUSY` 错误。
4. 如果 PID 不存活：进程已退出，lock 为 stale。`resume` 清除 stale lock，检查 `applied_patches` 列表，非空则逐一回滚 patch（`git checkout`），然后从 `progress.current_phase` 恢复执行。
5. 如果 lock 文件不存在：说明进程异常退出且 lock 未创建（极罕见）。检查 `applied_patches` 列表并逐一回滚，然后恢复。

**stop_reason 枚举：**

| 值 | 含义 | 触发条件 |
|----|------|---------|
| `null` | 尚未停止 | 运行中 |
| `budget_wall_clock` | wall-clock 预算耗尽 | `resource_usage.wall_clock_seconds >= budget.wall_clock_hours * 3600` |
| `budget_gpu_hours` | GPU 小时预算耗尽 | `resource_usage.gpu_seconds >= budget.gpu_hours * 3600` |
| `budget_max_candidates` | candidate 数量预算耗尽 | `budget.max_candidates` 不为 null 且 `resource_usage.candidates >= budget.max_candidates`。当 `budget.max_candidates` 为 null 时跳过此检查。 |
| `budget_max_full_evals` | full eval 数量预算耗尽 | `budget.max_full_evals` 不为 null 且 `resource_usage.full_evals >= budget.max_full_evals`。当 `budget.max_full_evals` 为 null 时跳过此检查。 |
| `user_interrupt` | 用户中断 | SIGTERM / SIGINT |
| `train_command_invalid` | 训练命令持续失败 | 连续 3 个不同 candidate 的 train_command 均 exit 非 0（不一定是连续 candidate，只需在最近 3 次 train 调用中全部失败）。"错误类型相同" 判定：如果 3 次失败的 exit code 相同（如都是 1 或都是 137），或 stderr 的前 200 字符相同，则判定为系统性错误而非偶发失败。 |
| `project_state_corrupt` | 项目状态损坏 | 关键文件缺失或不可读 |
| `disk_space_low` | 磁盘不足 | 可用空间 < 1GB |
| `patch_guard_blocked` | patch 安全违规持续阻塞 | 连续 5 个 candidate 被 guard 拒绝 |
| `all_phases_completed` | 所有 phase 完成 | experiment_plan 中所有 phase status 为 completed |

**phase 枚举与状态机：**

```text
initialized                     # init 完成
  │
  ▼
understood                      # understand 完成
  │
  ▼
classified                      # classify-task 完成
  │
  ▼
strategy_selected               # select-strategy 完成
  │
  ▼
planned                         # plan-experiments 完成
  │
  ▼
literature_searched             # search-papers 完成
  │
  ▼
literature_classified           # classify-papers 完成
  │
  ▼
literature_selected             # select-papers 完成
  │
  ▼
ideas_extracted                 # extract-ideas 完成（可选阶段，不影响 run-plan 启动）
  │
  ▼
running_plan                    # run-plan 执行中
  │
  ├─ phase 执行中 ────────────> running_plan（state.json 的 phase 字段保持 "running_plan"）
  │                               # 当前 phase 信息在 state.json 的 progress.current_phase 中
  │                               # 如 progress.current_phase.phase_id = "lqr-residual"
  ├─ resume ───────────────────> running_plan（中断后恢复，phase 不变，progress.current_phase 重置后继续）
  │
  ├─ 所有 phase 完成 ────────> completed
  │
  ├─ 预算耗尽 ────────────────> budget_exhausted
  │
  ├─ 用户中断 ────────────────> interrupted
  │
  └─ 严重错误 ────────────────> error
```

**phase 转换规则：**

| 转换 | 触发命令 | 前置条件 |
|------|---------|---------|
| initialized → understood | `understand` | 项目路径有效 |
| understood → classified | `classify-task` | project_understanding 存在 |
| classified → strategy_selected | `select-strategy` | task_classification 存在 |
| strategy_selected → planned | `plan-experiments` | objective + constraints + forbidden_changes + budget + metrics.primary + metric_regex 全部存在 |
| planned → literature_searched | `search-papers` | experiment_plan 存在 |
| literature_searched → literature_classified | `classify-papers` | arxiv_papers 存在 |
| literature_classified → literature_selected | `select-papers` | paper_taxonomy 存在 |
| literature_selected → ideas_extracted | `extract-ideas` | selected_papers 存在（可选阶段） |
| literature_selected → running_plan | `run-plan` | objective + constraints + forbidden_changes + budget + metrics.primary + metric_regex 全部存在（跳过 extract-ideas 时直接进入。状态机图中 ideas_extracted 为可选节点，literature_selected 可直接指向 running_plan） |
| ideas_extracted → running_plan | `run-plan` | objective + constraints + forbidden_changes + budget + metrics.primary + metric_regex 全部存在 |
| running_plan → completed | 自动 | 所有 phase 完成且预算未耗尽。此时 `phase` 字段变为 `completed`，`stop_reason` 变为 `all_phases_completed`。两者是正交字段：`phase` 表示平台状态，`stop_reason` 表示停止原因。约束：当 `phase = "completed"` 时，`stop_reason` 必须非 null。如果 `stop_reason` 为 null 但 `phase` 为 `completed`，`resume` 视为 `STATE_FILE_CORRUPT` 并尝试从 `state.json.bak` 恢复。 |
| running_plan → budget_exhausted | 自动 | 任一 budget 字段达到上限。`phase` 变为 `budget_exhausted`，`stop_reason` 必须为具体预算原因：`budget_wall_clock` / `budget_gpu_hours` / `budget_max_candidates` / `budget_max_full_evals`。 |
| running_plan → interrupted | SIGTERM / SIGINT | 信号处理。`phase` 变为 `interrupted`，`stop_reason` 变为 `user_interrupt`。两者同时设置。 |
| running_plan → error | 自动 | 训练命令失效 / 项目状态损坏 / 磁盘不足 |

**resume 行为与 phase 的关系：**

| 当前 phase | resume 行为 |
|-----------|------------|
| initialized / understood / classified / strategy_selected | 从下一阶段继续 |
| planned / literature_searched / literature_classified / literature_selected / ideas_extracted | 从下一阶段继续 |
| running_plan | 检查 active experiment 状态；如有 applied patch 则回滚；从当前 phase 重新开始。`phase` 始终保持 `running_plan`，内部通过 `progress.current_phase` 跟踪活跃实验 phase。 |
| completed / budget_exhausted | 报告已完成，不重复执行 |
| interrupted | 从 running_plan 恢复 |
| error | 报告错误，要求人工干预或前站 Agent 重新决策 |

---

## 十八、依赖安装

```toml
[project]
name = "research-agent"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = [
    "click>=8.0",
    "rich>=13.0",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "requests>=2.28",
    "gitpython>=3.1",  # git 操作（commit, checkout, apply, diff 生成）
    "unidiff>=0.7",    # patch 文件解析和 guard 检查（解析 .patch 文件的修改范围）
    "arxiv>=2.0",
    "python-dotenv>=1.0",
    "numpy>=1.24",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "pytest-mock>=3.0",
]

[project.scripts]
research-agent = "research_agent.interfaces.cli:main"
```

安装：

```bash
cd <research-agent-source>
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

---

## 十九、验收标准

### 19.1 平台验收

| # | 标准 | 验证方式 |
|---|------|---------|
| 1 | 初始化项目 | `research-agent init --project <path>` 创建 `.research-agent/` |
| 2 | 前站 contract 生效 | objective 缺失时 `plan-experiments` 失败并输出 JSON next_action |
| 3 | project understanding | `understand` 输出项目类型、控制结构、训练入口候选、可优化/禁止对象 |
| 4 | task classification | `classify-task` 输出 task types、confidence、recommended strategies |
| 5 | strategy selection | `select-strategy` 基于 task classification 选择 optimizer |
| 6 | experiment planning | `plan-experiments` 输出 baseline、phase、命令、指标、预算 |
| 7 | machine-readable status | `status --json` 返回 phase、active experiment、budget、current best |
| 8 | report json | `report --json` 可被前站 Agent 读取 |
| 9 | resume | 中断后 `resume` 能从安全阶段恢复 |

### 19.2 HRRL 专项验收

| # | 标准 | 验证方式 |
|---|------|---------|
| 10 | 识别 HRRL 控制结构 | 识别 Dynamic LQR + LQR Residual + Dynamic Stanley + Stanley Residual |
| 11 | 分类 HRRL 任务 | 输出 controller_residual_optimization + reward_optimization + safety_constraint_optimization |
| 12 | LQR 只读 | patch guard 拒绝修改 LQR 控制律 |
| 13 | Stanley 只读 | patch guard 拒绝修改 Stanley 控制律 |
| 14 | residual reward 可优化 | 允许 LQR/Stanley residual reward optimizer candidate |
| 15 | 实验计划合理 | 包含 baseline、LQR residual reward、Stanley residual reward、safety tracking、joint validation |

### 19.3 Reward optimizer 继承验收

| # | 标准 | 验证方式 |
|---|------|---------|
| 16 | 论文确定性选择 | 相同输入下 selected papers Top-K 一致 |
| 17 | candidate 引用论文 | proposal 必须引用 selected papers |
| 18 | `improve_score` 使用 objective | `improve_score` 按 primary weights 和 safety penalty 计算 |
| 19 | reward-only guard | 拒绝 observation/action/termination/algorithm/network 修改 |
| 20 | baseline immutable | cleanup 不删除或覆盖 baseline artifacts |
| 21 | degraded cleanup | 清理重资产但保留 ledger |
| 22 | no auto GitHub push | 默认不 push remote |
| 23 | budget-run | 连续 degraded 不停机，预算耗尽才 report |

### 19.4 测试策略

所有测试都使用 pytest。测试 fixture 统一放在 `tests/fixtures/`，mock HRRL 项目必须包含：

```text
tests/fixtures/hrrl_project/
  train.py
  eval.py
  reward.py
  controllers/lqr.py
  controllers/stanley.py
  config.yaml
```

**必须实现的测试文件与命令：**

| 测试文件 | 覆盖内容 | 命令 | 期望 |
|----------|----------|------|------|
| `tests/test_front_agent_contract.py` | objective/constraints/forbidden_changes/budget/metrics/metric_regex 缺失时的 error_code | `pytest tests/test_front_agent_contract.py -v` | 全部 PASS |
| `tests/test_json_protocol.py` | `status --json`、`report --json`、`plan-experiments --json` 可 `json.loads` | `pytest tests/test_json_protocol.py -v` | 全部 PASS |
| `tests/test_experiment_planner.py` | HRRL phase DAG、`experiment_plan.json` schema、metric regex 校验 | `pytest tests/test_experiment_planner.py -v` | 全部 PASS |
| `tests/test_project_understanding.py` | Dynamic LQR + LQR Residual + Dynamic Stanley + Stanley Residual 识别 | `pytest tests/test_project_understanding.py -v` | 全部 PASS |
| `tests/test_task_classifier.py` | 输出 `task_types`，包含 controller_residual/reward/safety | `pytest tests/test_task_classifier.py -v` | 全部 PASS |
| `tests/test_strategy_selector.py` | reward/residual_control optimizer 选择，V1 不自动执行任务只建议 | `pytest tests/test_strategy_selector.py -v` | 全部 PASS |
| `tests/test_metric_parser.py` | stdout/stderr/glob regex，last/max/min/mean 聚合 | `pytest tests/test_metric_parser.py -v` | 全部 PASS |
| `tests/test_patch_guard.py` | reward-only、LQR/Stanley readonly、human review 区域 | `pytest tests/test_patch_guard.py -v` | 全部 PASS |
| `tests/test_git_guard.py` | 非 git repo、dirty worktree、baseline/current best rollback target | `pytest tests/test_git_guard.py -v` | 全部 PASS |
| `tests/test_paper_selector.py` | Top-K 稳定、objective/context/year 变化导致 cache key 变化 | `pytest tests/test_paper_selector.py -v` | 全部 PASS |
| `tests/test_executor_lifecycle.py` | proposal -> patch_generated -> guarded -> screening -> rollback 状态流 | `pytest tests/test_executor_lifecycle.py -v` | 全部 PASS |
| `tests/test_resume.py` | `applied_patches` 非空时 resume 先 rollback | `pytest tests/test_resume.py -v` | 全部 PASS |

**集成测试：**

```bash
pytest tests/integration/test_cli_platform_flow.py -v
pytest tests/integration/test_hrrl_mock_project.py -v
pytest tests/integration/test_report_status_json.py -v
```

集成测试必须验证：

1. `init -> understand -> classify-task -> select-strategy -> plan-experiments` 第一闭环可运行。
2. `reports/project_understanding.json`、`reports/strategy_selection.json`、`reports/experiment_plan.json` 均存在并可解析。
3. 缺 front-agent contract 时 `plan-experiments` 返回对应 JSON error，不写 partial plan。
4. HRRL mock project 生成 baseline、lqr-residual、stanley-residual、safety-tracking、joint-validation phase。
5. `report --json` 和 `status --json` 包含 `phase`、`active_experiment`、`resource_usage`、`current_best`、`blocking_issue`。

### 19.5 V1 实施任务清单

> **执行规则：** 每个 Task 必须先写测试，再实现最小代码，再运行该 Task 的测试命令。不要跳过第一闭环去写 reward patch 生成。

| Task | 目标 | 修改区域 | 测试文件 | 验收命令 |
|------|------|----------|----------|----------|
| 1 | 项目骨架与 packaging | `pyproject.toml`、`research_agent/__init__.py`、CLI entrypoint | `tests/test_json_protocol.py` | `pytest tests/test_json_protocol.py -v` |
| 2 | config/state/output/json protocol | `core/config.py`、`core/state.py`、`core/output.py`、`interfaces/json_protocol.py` | `tests/test_front_agent_contract.py` | `pytest tests/test_front_agent_contract.py -v` |
| 3 | CLI init/status/report 空实现 | `interfaces/cli.py`、`interfaces/front_agent_contract.py` | `tests/integration/test_report_status_json.py` | `pytest tests/integration/test_report_status_json.py -v` |
| 4 | Project Understanding Layer | `core/project_understanding.py` | `tests/test_project_understanding.py` | `pytest tests/test_project_understanding.py -v` |
| 5 | Task Classifier | `core/task_classifier.py` | `tests/test_task_classifier.py` | `pytest tests/test_task_classifier.py -v` |
| 6 | Strategy Selector | `core/strategy_selector.py` | `tests/test_strategy_selector.py` | `pytest tests/test_strategy_selector.py -v` |
| 7 | Experiment Planner JSON schema | `core/experiment_planner.py` | `tests/test_experiment_planner.py` | `pytest tests/test_experiment_planner.py -v` |
| 8 | Metric Parser | `execution/metric_parser.py` | `tests/test_metric_parser.py` | `pytest tests/test_metric_parser.py -v` |
| 9 | Paper Evidence Pipeline | `literature/arxiv_searcher.py`、`paper_classifier.py`、`paper_selector.py` | `tests/test_paper_selector.py` | `pytest tests/test_paper_selector.py -v` |
| 10 | Git guard + patch guard | `core/git_guard.py`、`optimizers/reward/patch_guard.py`、`optimizers/residual_control/residual_patch_guard.py` | `tests/test_git_guard.py`、`tests/test_patch_guard.py` | `pytest tests/test_git_guard.py tests/test_patch_guard.py -v` |
| 11 | Executor lifecycle + resume | `core/executor.py`、`execution/experiment_runner.py`、`core/cache.py` | `tests/test_executor_lifecycle.py`、`tests/test_resume.py` | `pytest tests/test_executor_lifecycle.py tests/test_resume.py -v` |
| 12 | Report writer + end-to-end platform flow | `core/report_writer.py`、`core/knowledge_base.py`、`core/result_analyzer.py` | integration tests | `pytest tests/integration -v` |

---

## 二十、给实现 Agent 的执行指令

请严格按本文档实现 V1。关键约束：

1. 不要把系统实现成单一奖励函数优化工具。
2. `research-agent` 是后端科研优化执行平台，前站主 Agent 是 Claude Code / Hermes / Codex / OpenClaw。
3. 平台第一步必须 understand project。
4. 第二步必须 classify research task。
5. 第三步必须 select optimization strategy。
6. 第四步必须 plan experiments。
7. Reward optimization 只是 `optimizers/reward`。
8. HRRL 项目必须识别为 residual control optimization + reward optimization + safety constraint optimization。
9. Dynamic LQR 和 Dynamic Stanley 默认只读，不允许自动修改。
10. LQR Residual RL 和 Stanley Residual RL 可进行 reward 优化。
11. 所有命令必须支持 `--json` 或 machine-readable 输出。
12. 没有 objective / constraints / budget / metrics 不允许 `plan-experiments` 或 `run-plan`。
13. 论文必须先收集、分类、确定性选择 Top-K，再作为 candidate 依据。
14. 不允许把连续失败、无提升、plateau 或 patience 耗尽作为停止原因。
15. baseline 不允许清理、覆盖或重算替换。
16. current best 默认只本地 commit，不自动 push GitHub。
17. 验收标准全部通过才算完成。

