# Reward Paper Pool V1 Handoff

## 当前状态

本目录是 Reward Function Paper Pool / Method Pool V1 的独立知识库资产目录，位置：

```text
D:\research-agent\research_agent\reward_paper_pool
```

当前已完成：

- 8 类 reward method taxonomy 已写入 `taxonomy.yaml`
- arXiv / GitHub / OpenReview 采集脚本已放入 `scripts/`
- 论文标准化、分类、方法提取、报告生成、质量验证脚本已放入 `scripts/`
- `raw/`、`category_reports/`、`paper_pool.jsonl`、`method_pool.jsonl`、`github_pool.jsonl`、`validation_report.md` 已生成
- 当前池子尚未正式联网采集，三个 pool 文件为空
- `validation_report.md` 当前 hard checks 为 `NO`，这是预期状态，不是脚本错误

不要为了让验证通过而手写或虚构论文。正式填池必须运行采集链路，且每篇论文必须有可访问 URL 或 arXiv / OpenReview / GitHub 来源。

## 目录结构

```text
reward_paper_pool/
  taxonomy.yaml
  paper_pool.jsonl
  method_pool.jsonl
  github_pool.jsonl
  validation_report.md
  missing_categories.md
  raw/
    arxiv_results.jsonl
    github_results.jsonl
    openreview_results.jsonl
  category_reports/
    A_potential_based_reward.md
    B_safety_constraint_reward.md
    C_curriculum_subgoal_reward.md
    D_adaptive_dynamic_reward.md
    E_hierarchical_reward.md
    F_residual_aware_reward.md
    G_llm_reward_generation.md
    H_learned_preference_reward.md
  scripts/
    collect_arxiv.py
    collect_github.py
    collect_openreview.py
    normalize_papers.py
    classify_papers.py
    extract_methods.py
    build_reports.py
    validate_pool.py
    pool_common.py
```

## 分类体系

`taxonomy.yaml` 定义了 8 个固定大类，每类目标至少 10 篇论文：

- `A_potential_based_reward`
- `B_safety_constraint_reward`
- `C_curriculum_subgoal_reward`
- `D_adaptive_dynamic_reward`
- `E_hierarchical_reward`
- `F_residual_aware_reward`
- `G_llm_reward_generation`
- `H_learned_preference_reward`

这些 key 是下游 Research Optimization Agent 的稳定接口，不要随意改名。

## 运行前准备

建议在 `D:\research-agent\research_agent` 作为工作目录运行。

依赖：

```powershell
pip install arxiv requests pyyaml python-dotenv rapidfuzz
```

可选环境变量：

```powershell
$env:GITHUB_TOKEN="..."
$env:AGENT_PIPELINE_API_KEY="..."
$env:AGENT_PIPELINE_BASE_URL="..."
$env:AGENT_PIPELINE_MODEL="..."
```

说明：

- `GITHUB_TOKEN` 可选；没有 token 时 GitHub collector 会低频运行，但更容易遇到 rate limit
- LLM 只用于 `extract_methods.py` 的方法提取增强
- 没有 LLM 时可以用 `--no-llm`，脚本会使用规则模板生成低风险方法草案

## 正式填池顺序

从 `D:\research-agent\research_agent` 执行：

```powershell
python reward_paper_pool\scripts\collect_arxiv.py
python reward_paper_pool\scripts\collect_openreview.py
python reward_paper_pool\scripts\collect_github.py
python reward_paper_pool\scripts\normalize_papers.py
python reward_paper_pool\scripts\classify_papers.py
python reward_paper_pool\scripts\extract_methods.py
python reward_paper_pool\scripts\build_reports.py
python reward_paper_pool\scripts\validate_pool.py
```

如果没有配置 LLM：

```powershell
python reward_paper_pool\scripts\extract_methods.py --no-llm
```

## 关键行为

- `collect_arxiv.py`
  - 使用 arXiv API
  - 每个关键词默认拉取 `max_results=30`
  - 请求之间至少间隔 3 秒
  - 输出 `raw/arxiv_results.jsonl`
  - 按 arXiv ID 优先去重，没有 ID 时用规范化标题 hash 去重

- `collect_openreview.py`
  - 使用 OpenReview API 搜索
  - API 失败时允许部分失败，不应阻断整个池子
  - 输出 `raw/openreview_results.jsonl`

- `collect_github.py`
  - 使用 GitHub REST API 搜索仓库
  - 只读取 repo metadata、README、浅层 contents
  - 不下载大文件
  - 检测 `reward.py`、`rewards/`、`envs/`、`tasks/` 等 reward code 线索
  - 输出 `raw/github_results.jsonl`

- `normalize_papers.py`
  - 合并 arXiv / OpenReview / GitHub 信息
  - 关联 README 中出现的 arXiv ID
  - 输出 `paper_pool.jsonl` 和 `github_pool.jsonl`

- `classify_papers.py`
  - 规则优先分类
  - 如果类别不足 10 篇，会输出 `missing_categories.md`
  - 不会硬编论文补数

- `extract_methods.py`
  - V1 只使用 title / abstract / README 级证据
  - 来自 abstract-only 的方法不能标 `high` confidence
  - 每个 method 必须有 `implementation_template`

- `validate_pool.py`
  - 输出 `validation_report.md`
  - hard checks 未通过时保留失败状态，不要手动改报告

## 验收标准

正式填池后，`validation_report.md` 应满足：

- 8 个大类全部存在
- 每类至少 10 篇论文
- 总论文数至少 80
- GitHub 项目至少 10 个
- 至少 5 个 GitHub repo 成功关联论文
- `method_pool` 至少 30 个方法
- 每个方法都有 `implementation_template`
- 每类至少 3 个 method template
- 至少 10 个方法适用于 HRRL / residual control
- 至少 5 个方法适用于 `lqr_residual`
- 至少 5 个方法适用于 `stanley_residual`
- 至少 5 个方法适用于 `safety_gate`
- 重复论文比例不超过 5%

## 当前已知未完成项

当前 pool 文件为空：

- `paper_pool.jsonl`
- `method_pool.jsonl`
- `github_pool.jsonl`

因此当前 `validation_report.md` 中这些 hard checks 会失败：

- 每类论文数不足
- 总论文数不足
- GitHub repo 数不足
- method 数不足
- HRRL / residual / safety gate 方法覆盖不足

下一位接手者的首要任务是运行正式采集链路，然后根据 `missing_categories.md` 扩展不足类别的关键词。

## 调试建议

如果某类长期不足 10 篇：

1. 查看 `missing_categories.md`
2. 在 `taxonomy.yaml` 对应 category 增加更宽的关键词
3. 重新运行对应 collector
4. 再运行 normalize / classify / extract / build / validate

如果 GitHub 关联不足：

1. 确认 `GITHUB_TOKEN` 是否可用
2. 查看 `raw/github_results.jsonl`
3. 检查 README 是否包含 arXiv ID、paper、citation、bibtex 等线索
4. 必要时增加 GitHub 搜索 query

如果 method 数不足：

1. 确认 `paper_pool.jsonl` 每类已有足够论文
2. 使用 LLM 环境变量运行 `extract_methods.py`
3. 没有 LLM 时运行 `--no-llm`，但需要后续人工审查 confidence 和模板质量

## 注意事项

- smoke test 不要真实调用完整文献链路
- 不要让 run-plan 每次重新查论文
- `paper_pool` 是低频更新资产，建议每周或每月更新
- `method_pool` 是 Agent 核心知识库，需要长期保存
- 不要虚构论文、GitHub repo、PDF URL 或 method 来源
- `validation_report.md` 是事实报告，不是目标状态文档
