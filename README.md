# Research Optimization Agent Platform

基于 LLM 的自动化研究代码优化平台。通过论文引导的方法和复合评分机制，迭代式地生成、评估和筛选候选补丁。

**版本:** 1.1 (非累积版本) | **Python:** >=3.11 | **平台:** 跨平台 (Windows/Linux/macOS)

---

## 目录

- [快速开始](#快速开始)
- [系统架构](#系统架构)
- [安装](#安装)
- [配置说明](#配置说明)
- [使用方法](#使用方法)
- [迁移到其他电脑](#迁移到其他电脑)
- [项目结构](#项目结构)
- [常见问题](#常见问题)

---

## 快速开始

```bash
# 1. 克隆仓库
git clone <repo-url> research-agent
cd research-agent

# 2. 创建 Python 环境 (>=3.11)
conda create -n ra python=3.11 -y
conda activate ra

# 3. 安装
pip install -e ".[dev]"

# 4. 配置 API 密钥
cp .env.example .env
# 编辑 .env，填入实际的 API key

# 5. 初始化目标项目
research-agent init --project /path/to/your/project

# 6. 运行
research-agent understand --project /path/to/your/project
```

---

## 系统架构

```
                    +-----------------+
                    |   CLI (Click)   |
                    +--------+--------+
                             |
                    +--------v--------+
                    |   Executor      |  编排引擎 & 状态机
                    +--------+--------+
                             |
           +-----------------+-----------------+
           |                 |                 |
  +--------v------+  +-------v-------+  +------v--------+
  |  LLM Client   |  |  Optimizers   |  |  Literature   |
  | (OpenAI 兼容)  |  |  (6 个插件)   |  |  文献管线     |
  +---------------+  +-------+-------+  +---------------+
                             |
                    +--------v--------+
                    | Experiment Runner|  子进程执行 train/eval
                    +--------+--------+
                             |
                    +--------v--------+
                    | Scoring & Patch  |  复合评分，接受/拒绝决策
                    +-----------------+
```

**核心循环:** LLM 提出奖励函数候选 -> 通过 train/eval 评分 -> 最优候选被采纳 -> 文献信息指导下一轮提案。

---

## 安装

### 前置条件

- Python >= 3.11
- Git
- 可用的 OpenAI 兼容 LLM API（默认: MiMo v2.5 Pro）
- （可选）Conda 或 venv 用于环境隔离

### 安装步骤

```bash
# 方式 A: Conda
conda create -n ra python=3.11 -y
conda activate ra

# 方式 B: venv
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# 以可编辑模式安装，包含开发依赖
pip install -e ".[dev]"

# 验证安装
research-agent --help
```

### 依赖列表

| 包名 | 用途 |
|------|------|
| pydantic >= 2.0 | 配置校验、数据模型 |
| pyyaml >= 6.0 | YAML 配置加载 |
| click >= 8.0 | CLI 框架 |
| httpx >= 0.27 | LLM API 的 HTTP 客户端 |
| pytest >= 8.0 | 测试 (开发) |
| pytest-cov >= 5.0 | 覆盖率 (开发) |

---

## 配置说明

配置分为 4 层，优先级从高到低：项目级配置 > 全局默认配置 > 环境变量 > 代码内默认值。

### 1. API 密钥 (.env)

从模板复制并填入密钥：

```bash
cp .env.example .env
```

```env
MIMO_API_KEY=你的实际API密钥

# 可选: 覆盖默认 LLM 端点
# MIMO_BASE_URL=https://your-endpoint.com/v1
```

`.env` 文件已在 `.gitignore` 中，不会被提交。

### 2. 全局默认配置 (configs/default.yaml)

`configs/default.yaml` 是主配置文件，控制所有默认行为：

| 配置节 | 用途 | 迁移时需要修改的 |
|--------|------|------------------|
| `llm` | LLM 提供商、模型、端点 | 如使用不同 API，更新 `base_url` |
| `evaluation` | 指标、权重、阈值 | 按目标项目自定义 |
| `execution` | 训练/评估命令、随机种子 | 通过 `init` 按项目设置 |
| `literature` | 论文搜索设置 | 通常无需修改 |
| `budget` | 时间限制 | 按项目调整 |

### 3. 项目级配置

运行 `research-agent init --project <PATH>` 后，会在 `<PATH>/.research-agent/config.yaml` 创建项目专属配置，覆盖全局默认值。

**每个项目必须设置的关键字段：**

```yaml
# .research-agent/config.yaml
execution:
  train_command: "python .research-agent/train.py {seed}"
  eval_command: "python .research-agent/evaluate.py {seed}"
  max_steps: 20000

evaluation:
  metrics:
    - name: your_metric
      direction: maximize
      weight: 0.5
    - name: another_metric
      direction: minimize
      weight: 0.5
```

命令中的 `{seed}` 占位符会在运行时被替换为 `full_eval_seeds` 中的种子值。

### 4. 切换 LLM 端点

默认使用: `https://token-plan-sgp.xiaomimimo.com/v1`，模型 `mimo-v2.5-pro`。

切换到其他 OpenAI 兼容 API：

```yaml
# 在 configs/default.yaml 或 .research-agent/config.yaml 中
llm:
  provider: openai_compatible
  model: your-model-name
  base_url: "https://your-api-endpoint.com/v1"
  api_key_env: "YOUR_API_KEY_ENV_VAR"
```

然后在 `.env` 中设置对应的环境变量。

---

## 使用方法

### CLI 命令

所有命令通过 `research-agent` 入口调用：

```bash
# 项目初始化
research-agent init --project /path/to/project

# 分析流水线（按顺序执行）
research-agent understand --project /path/to/project
research-agent classify-task
research-agent select-strategy
research-agent plan-experiments

# 文献流水线
research-agent search-papers --topic "reward shaping"
research-agent classify-papers
research-agent select-papers --top-k 5
research-agent extract-ideas

# 优化执行
research-agent run-plan                    # 执行完整计划
research-agent run-iteration               # 执行单次迭代
research-agent run --phase <phase_name>    # 执行单个阶段
research-agent propose-candidate --optimizer reward  # 提出单个候选

# 监控
research-agent status
research-agent generate-report

# 维护
research-agent resume                      # 恢复中断的运行
research-agent cleanup                     # 清理临时文件
research-agent cleanup --full              # 完全清理
research-agent git-snapshot --message "msg"
```

### 独立优化器

```bash
python run_optimizer.py --project /path/to/project --max-iterations 10
```

参数：
- `--project PATH` - 目标项目目录
- `--max-iterations N` - 最大优化迭代次数
- `--batch-size N` - 每轮候选数（默认: 3）
- `--mock-llm` - 使用模拟 LLM 进行测试

### 冒烟测试

```bash
python smoke_test.py
```

使用 `test_accept/` 作为测试项目，端到端运行全部 12 个 CLI 命令。需要先安装本包。

---

## 迁移到其他电脑

### 随仓库迁移的内容（git 管理）

- 全部源代码 (`research_agent/`)
- 默认配置 (`configs/default.yaml`)
- 论文池数据 (`research_agent/reward_paper_pool/`)
- 模板文件 (`research_agent/templates/`)
- 测试文件 (`tests/`, `smoke_test.py`)
- `pyproject.toml`, `.gitignore`, `.env.example`

### 不随仓库迁移的内容（gitignore 或本地）

| 项目 | 位置 | 处理方式 |
|------|------|----------|
| API 密钥 | `.env` | 从 `.env.example` 创建 |
| Python 环境 | `.venv/` 或 conda 环境 | 用 `pip install -e ".[dev]"` 重建 |
| 项目状态 | `<project>/.research-agent/` | 通过 `init` + 运行重新生成 |
| 测试夹具 | `test_accept/`, `test_project/` | 通过冒烟测试重新生成 |
| IDE 设置 | `.vscode/`, `.idea/` | 按偏好重新配置 |

### 迁移清单

```bash
# 在新机器上执行：

# 1. 克隆仓库
git clone <repo-url> research-agent
cd research-agent

# 2. 创建 Python 环境
conda create -n ra python=3.11 -y && conda activate ra
# 或: python -m venv .venv && source .venv/bin/activate

# 3. 安装
pip install -e ".[dev]"

# 4. 配置 API 密钥
cp .env.example .env
# 编辑 .env 填入你的 API key

# 5. （可选）如不使用默认 LLM 端点，更新配置
# 编辑 configs/default.yaml -> llm.base_url

# 6. （可选）如迁移 HRRL2 项目，更新硬编码路径
# 编辑 HRRL2/.research-agent/config.yaml：
#   - train_command / eval_command: 替换 Python 路径
#   - project.path: 更新为新目录路径

# 7. （可选）更新冒烟测试路径
# 编辑 smoke_test.py 第 28-29 行：
#   PYTHON = "/你的/python/路径"
#   PROJECT = "/你的/test_accept/路径"

# 8. 验证
research-agent --help
python smoke_test.py
```

### 需要手动更新的硬编码路径

以下文件包含环境相关的硬编码路径，迁移时必须修改：

| 文件 | 行号 | 内容 | 替换为 |
|------|------|------|--------|
| `smoke_test.py` | 28-29 | `PYTHON`, `PROJECT` | 你的 Python 路径和 test_accept 路径 |
| `HRRL2/.research-agent/config.yaml` | 3-4 | `train_command`, `eval_command` | 你的 Python 解释器路径 |
| `HRRL2/.research-agent/config.yaml` | 45 | `project.path` | HRRL2 目录的新路径 |
| `.claude/settings.local.json` | - | Bash 权限 | 如使用 Claude Code 则更新 Python 路径 |

---

## 项目结构

```
research-agent/
├── configs/
│   └── default.yaml              # 全局默认配置
├── research_agent/               # 主 Python 包
│   ├── core/                     # 配置、状态机、LLM 客户端、评分
│   ├── execution/                # 子进程 train/eval 执行器
│   ├── interfaces/               # CLI、JSON 协议、前置代理合约
│   ├── literature/               # arXiv 搜索、论文分类与阅读
│   ├── optimizers/               # 6 个优化器插件（reward, HPO 等）
│   ├── templates/                # 生成的 train/evaluate 脚本模板
│   └── reward_paper_pool/        # 118 篇论文、142 个方法、8 个类别
├── tests/                        # 单元测试
├── HRRL2/                        # 示例目标项目（自行车控制）
├── run_optimizer.py              # 独立优化器脚本
├── smoke_test.py                 # 端到端冒烟测试
├── pyproject.toml                # 包定义与依赖
├── .env.example                  # API 密钥模板
└── .gitignore
```

### 优化器插件

| 插件 | 状态 | 用途 |
|------|------|------|
| `reward` | 活跃 | LLM 驱动的奖励函数优化 |
| `residual_control` | 活跃 | 残差控制策略优化 |
| `hpo` | 占位 | 超参数优化 |
| `curriculum` | 占位 | 课程学习优化 |
| `observation` | 占位 | 观测空间优化 |
| `action_space` | 占位 | 动作空间优化 |

### 状态机阶段

```
initialized -> understood -> classified -> strategy_selected -> planned
-> literature_searched -> literature_classified -> literature_selected
-> ideas_extracted -> running_plan -> completed / budget_exhausted / interrupted / error
```

---

## 常见问题

### "MIMO_API_KEY not found"

确保项目根目录下存在 `.env` 文件，且包含 `MIMO_API_KEY=<你的密钥>`。

### "Module not found: research_agent"

在项目根目录执行 `pip install -e .`。

### LLM 请求超时

在配置中增大 `llm.timeout_seconds`（默认 120 秒）。同时检查 `llm.max_retries` 设置。

### 文件锁错误（Windows）

系统使用文件锁进行并发控制。如果残留锁文件：

```bash
research-agent status --clear-stale-lock
```

### 冒烟测试失败

检查：
1. 包已安装: `pip install -e ".[dev]"`
2. `smoke_test.py` 第 28-29 行的路径与你的环境匹配
3. `test_accept/` 目录存在（如不存在执行 `research-agent init --project test_accept`）

### 训练/评估命令找不到

更新项目 `.research-agent/config.yaml` 中的 `train_command` 和 `eval_command`，使用正确的 Python 解释器路径。
