# Reward LangGraph v0.8.9 项目交接文档

**生成日期**: 2026-06-17
**最后更新**: 2026-06-17（含论文池下载说明、安全清理、分支修正）
**基于**: 仓库实际代码、reports、run artifacts、candidate handoff artifacts 和 git 状态

---

## 1. 当前最终状态

| 项目 | 值 |
|------|-----|
| 最终分支 | `reward-langgraph-v0.8.9-candidate-bank-handoff` |
| 最终 tag | `reward-langgraph-v0.8.9` |
| 最终 tag commit | `203f50c` |
| 当前分支最新 commit | `0f99930` |
| 是否已 push 到 origin | 分支和 tag 均已 push |
| origin branch 指向 | `0f99930` |
| origin tag 指向 | `203f50c`（`refs/tags/reward-langgraph-v0.8.9`，未移动） |
| older tags 是否 untouched | 是，v0.1 至 v0.8.8 全部保留 |
| working tree | clean |
| HRRL2/env.py hash | `e19703467be71e20`（已从仓库确认） |
| HRRL2 v0 基线分支 | [`v0-baseline`](https://github.com/Ma-mingliang/HRRL2-test/tree/v0-baseline) |
| baseline guard 状态 | `baseline_guard_passed=True`, `baseline_guard_run=True` |
| train_called | false |
| full_eval_called | false |
| 论文池 | 435 PDF + 150 MD，需从 GitHub Releases 下载 |

**说明**: v0.8.9 tag 固定在 `203f50c`，后续 docs commit 推送到同一分支但不移动 tag。

### 最近 docs 提交记录

| Commit | 内容 |
|--------|------|
| `0f99930` | 添加论文池下载说明（quickstart、handover、papers/README.md） |
| `042e4db` | 安全清理：移除 key 前缀、key 长度、泄露的 API key |
| `6e3569e` | 修正 HRRL2 基线分支：`main` → `v0-baseline` |
| `8db331f` | 添加 HRRL2 GitHub 链接、克隆说明、optimizer 角色描述 |
| `458188f` | 添加 HRRL2 GitHub 链接和获取说明 |

---

## 1.1 项目仓库地址

### research-agent 平台

| 项目 | 值 |
|------|-----|
| GitHub 地址 | `https://github.com/Ma-mingliang/rewardopt-research-agent.git` |
| 主分支 | `main` |
| 当前工作分支 | `reward-langgraph-v0.8.9-candidate-bank-handoff` |
| 最终 tag | `reward-langgraph-v0.8.9` (commit `203f50c`) |

### HRRL2 目标项目

| 项目 | 值 |
|------|-----|
| GitHub 地址 | `https://github.com/Ma-mingliang/HRRL2-test.git` |
| 测试副本 | `https://github.com/Ma-mingliang/HRRL2-test-test.git` |
| v0 基线分支 | [`v0-baseline`](https://github.com/Ma-mingliang/HRRL2-test/tree/v0-baseline)（推荐，未经优化器修改的干净基线） |
| 优化器运行分支 | `optimizer-run`, `optimizer-run-v2`（含 accepted/rejected 候选历史） |
| 本地路径 | `research-agent/HRRL2/`（gitignored，需单独克隆） |

### 获取 HRRL2

```bash
# 在 research-agent 根目录下
git clone https://github.com/Ma-mingliang/HRRL2-test.git HRRL2
cd HRRL2
git checkout v0-baseline  # 使用 v0 基线分支
```

**重要**: 使用 `v0-baseline` 分支作为基线（https://github.com/Ma-mingliang/HRRL2-test/tree/v0-baseline）。`main`、`optimizer-run` 和 `optimizer-run-v2` 分支已被优化器修改过，不是干净的基线。

### HRRL2 在 optimizer 中的角色

1. **读取** `HRRL2/env.py` 中的 `__calculate_reward` 方法作为优化目标
2. **生成** reward patch（diff 格式）
3. **应用** patch 到 env.py（临时修改）
4. **训练** HRRL2（通过 `LQR.py` 或 `stanley.py`）
5. **评估** 训练结果
6. **回滚** patch（`git checkout -- env.py`）

当前 v0.8.9 只执行步骤 1-3（proposal-only），不训练。

---

## 2. 项目目标与边界

### reward_langgraph 的目标

- 只优化 reward 函数（`HRRL2/env.py` 中的 `__calculate_reward` 方法）
- 不修改 RL 算法
- 不修改训练协议
- 不修改 full eval 协议
- 不修改 seed / metrics / score / accept 逻辑
- 当前 v0.8 系列目标：生成、筛选、修复、排序和保存 reward candidate patches

### 为什么当前不训练

- Windows 页面文件 / CUDA 资源问题未解决（之前出现过 WinError 1455）
- 用户未处理页面文件配置或切换到 CPU/低资源训练方案
- v0.8 系列只做到 validation-ready candidate handoff
- 不能声称任何候选性能提升（无训练结果）

---

## 3. 关键安全约束

| 约束 | 说明 |
|------|------|
| 不修改 HRRL2/env.py baseline | accepted operational baseline hash = `e19703467be71e20` |
| 不使用 --accept-baseline-migration | 基线迁移必须经过人工审计 |
| 不关闭 baseline guard | `research_agent/core/baseline_guard.py` 始终启用 |
| 不移动已推送的 tag | v0.1 至 v0.8.9 全部固定 |
| 不泄露 MIMO_API_KEY | `.env` 中的 API 密钥，不可提交或打印 |
| 不提交 .env / checkpoint / 大日志 / 私有配置 | `.gitignore` 已配置 |
| campaign 必须显式使用 --optimizer reward_langgraph | 不使用默认 optimizer |
| 不使用 git push --tags | 只推当前分支和指定 tag |
| 不把 CUDA/pagefile infra failure 记作 candidate failure | 这是基础设施问题，不是候选问题 |
| 不把 validation-ready 说成 full-eval-passed | 无训练结果 = 无性能声称 |

**安全清理记录** (2026-06-17): 已从所有跟踪文件中移除 key 前缀（`tp-shkic...`）、key 长度（`key_length=51`）和一个泄露的真实 API key（v0.6 validation report 中的 `tp-s48j...`）。`.env` 文件未被 git 跟踪。

---

## 4. v0.8 系列演进概览

### v0.8.1

- **问题**: v0.8 的 diversity prompt 不足以阻止 cosmetic patches；LLM 返回空 diff 后走 fix path 生成 blank-line patches
- **修复**: 添加 patch similarity (Jaccard)、diversity events、cross-category fallback、diversity context injection、CRITICAL DIVERSITY RULES
- **结果**: 2 candidates，均为 identical cosmetic blank-line patches（失败）
- **训练/full eval**: 否（INFRA FAILURE + COSMETIC PATCHES）
- **tag**: `reward-langgraph-v0.8.1`
- **report**: `docs/reports/reward_langgraph_v0_8_1_diversity_real_campaign_report.md`

### v0.8.2

- **问题**: v0.8.1 cosmetic patches 通过了无语义验证
- **修复**: 创建 `semantic_patch_gate.py`（hard semantic gate）、`system_preflight.py`（Windows pagefile preflight）、fix-path diversity propagation
- **结果**: cosmetic/no-reward-term patches 在训练前被拒绝
- **训练/full eval**: 否
- **tag**: `reward-langgraph-v0.8.2`
- **report**: `docs/reports/reward_langgraph_v0_8_2_semantic_gate_report.md`

### v0.8.3

- **问题**: 需要验证 semantic gate 在真实 LLM campaign 中端到端生效
- **修复**: 添加 `--proposal-only` 模式（propose+validate only，skip training/eval）
- **结果**: proposal-only campaign 运行成功，cosmetic patches 被拒绝
- **训练/full eval**: 否
- **tag**: `reward-langgraph-v0.8.3`
- **run_id**: `20260616_133439_reward_langgraph_7cd8d9`
- **report**: `docs/reports/reward_langgraph_v0_8_3_semantic_gated_proposal_campaign_report.md`

### v0.8.4

- **问题**: LLM 不理解 "reward term modification"，需要 few-shot examples
- **修复**: 创建 `reward_patch_few_shots.yaml`、提取 available reward variables、改进 prompts、实现 semantic regeneration
- **结果**: semantic patch 生成并通过语法安全检查
- **训练/full eval**: 否
- **tag**: `reward-langgraph-v0.8.4`
- **report**: `docs/reports/reward_langgraph_v0_8_4_method_grounded_semantic_patch_report.md`

### v0.8.5

- **问题**: 需要持久化 validation-ready semantic patches
- **修复**: 创建 `candidate_bank.py`、candidate_bank.jsonl、validation-only campaign
- **结果**: 4 candidates 全部 validation-ready，但存在 template 单一问题（全部 category A）
- **训练/full eval**: 否
- **tag**: `reward-langgraph-v0.8.5`
- **run_id**: `20260616_162636_reward_langgraph_a15423`
- **report**: `docs/reports/reward_langgraph_v0_8_5_semantic_candidate_bank_report.md`

### v0.8.6

- **问题**: 候选排序缺失、template 多样性不足
- **修复**: 添加 `rank_candidates()`、`compute_diversity_score()`、method_pool API compatibility fix
- **结果**: 候选可排序，template diversity tracking 可用
- **训练/full eval**: 否
- **tag**: `reward-langgraph-v0.8.6`
- **report**: `docs/reports/reward_langgraph_v0_8_6_candidate_bank_ranking_report.md`

### v0.8.7

- **问题**: v0.8.5 候选全部来自同一 category A，零 template 多样性
- **根因**:
  1. `MethodSelector.select()` 的 `exclude_ids` 参数从未被调用
  2. 确定性排序导致每轮选相同 methods
  3. proposal-only 路径缺少 `_mark_batch("tried")`
  4. template tracking 只检查 `candidate_ideas[0]`
- **修复**: 创建 `diversity_scheduler.py`、修复 `_mark_batch`、修复 `exclude_ids` 传递、修复 template tracking 遍历所有 ideas
- **结果**: template diversity score 从 0.0 提升到 1.0（单元测试）
- **训练/full eval**: 否
- **tag**: `reward-langgraph-v0.8.7`
- **report**: `docs/reports/reward_langgraph_v0_8_7_template_diversity_expansion_report.md`

### v0.8.8

- **问题**: 需要验证 DiversityScheduler 在真实 LLM campaign 中工作
- **修复**: 运行真实 proposal-only diversity campaign
- **结果**:
  - `candidate_bank_size=3`
  - `unique_template_count=3`
  - `unique_category_count=3`
  - `template_diversity_score=1.0`
  - `validation_pass_count=3`
  - `train_called=false`, `full_eval_called=false`
- **训练/full eval**: 否
- **tag**: `reward-langgraph-v0.8.8`
- **run_id**: `20260617_123033_reward_langgraph_8bac43`
- **report**: `docs/reports/reward_langgraph_v0_8_8_diverse_candidate_bank_refresh_report.md`

### v0.8.9

- **问题**: 需要将 v0.8.8 候选打包为可复用的交接工件
- **修复**: 导出 top candidate patches、metadata、future training commands（不执行）
- **结果**: 3 个 patch 导出，全部 compile + AST 通过
- **训练/full eval**: 否
- **tag**: `reward-langgraph-v0.8.9`
- **commit**: `203f50c`
- **report**: `docs/reports/reward_langgraph_v0_8_9_candidate_bank_handoff_report.md`

---

## 5. 当前核心能力和代码位置

### 5.1 Context-grounded proposal

- **代码路径**: `research_agent/core/proposal_context.py`
- **关键类/函数**: `ProposalContext`, `extract_editable_reward_context()`, `detect_reward_function_bounds()`, `build_line_numbered_context()`
- **作用**: 从 `env.py` 提取 reward function 的源码、行号、边界、缩进信息，供 LLM 生成结构有效的 patch
- **输入**: `project_path`, `allowed_changes`, `target_file`, `target_function`
- **输出**: `ProposalContext` dataclass（含 function bounds、line-numbered context、existing reward terms、available variables）
- **注意事项**: 使用 `utf-8-sig` 编码读取 env.py（处理 BOM）

### 5.2 Initial patch self-check

- **代码路径**: `research_agent/agents/reward_agent/nodes.py`
- **关键函数**: propose node 中的 diff 验证逻辑
- **作用**: LLM 返回 diff 后立即检查是否为空、是否在 allowed context 内
- **输入**: LLM 返回的 diff text
- **输出**: 通过/拒绝决策
- **注意事项**: 空 diff 会触发 empty_diff_retry 路径

### 5.3 Semantic patch gate

- **代码路径**: `research_agent/core/semantic_patch_gate.py`
- **关键类/函数**: `SemanticPatchDecision`, `analyze_patch_semantics()`, `_is_reward_term()`, `_compute_jaccard()`
- **作用**: 硬语义门控，拒绝 cosmetic/no-reward-term patches
- **输入**: `diff_text`, `reward_function_lines`, `previous_diffs`, `similarity_threshold`
- **输出**: `SemanticPatchDecision`（passed/rejected + 原因）
- **拒绝类型**: `cosmetic_patch_rejected`, `no_reward_term_change`, `duplicate_patch_rejected`, `patch_outside_reward_context`
- **注意事项**: 使用 Jaccard 相似度检测跨迭代重复 patches

### 5.4 Semantic regeneration

- **代码路径**: `research_agent/core/executor.py` (`_attempt_semantic_regeneration()`), `research_agent/agents/reward_agent/prompts.py` (`SEMANTIC_REGENERATION_PROMPT`, `SEMANTIC_REGENERATION_SYSTEM_PROMPT`)
- **作用**: 当 semantic gate 拒绝 patch 后，使用专门的 regeneration prompt 重新生成
- **输入**: 被拒绝的 candidate、semantic_decision、proposal_context、method_context
- **输出**: 新的 diff string 或 None
- **注意事项**: 最多尝试 `--max-semantic-regeneration-attempts` 次（默认 2）

### 5.5 Syntax-safe regeneration

- **代码路径**: `research_agent/core/executor.py`, `research_agent/agents/reward_agent/prompts.py` (`SEMANTIC_REGENERATION_PROMPT`)
- **作用**: semantic regeneration 生成的 diff 必须通过 compile + AST 检查
- **输入**: regenerated diff
- **输出**: syntax_valid=True/False
- **注意事项**: IndentationError 会被 syntax-aware repair 处理

### 5.6 Syntax-aware repair

- **代码路径**: `research_agent/core/patch_repair.py`
- **关键类/函数**: `RepairStrategy`, `PatchRepairError`, `RepairAttemptTracker`, `build_syntax_repair_prompt()`, `validate_repaired_diff_on_temp_copy()`
- **作用**: 三级修复策略升级：direct_diff_repair → local_hunk_regeneration → idea_regeneration_from_baseline
- **输入**: 失败的 diff、error signature、修复策略
- **输出**: 修复后的 diff 或失败
- **注意事项**: 预算限制（max 6 total attempts, max 2 per error signature）

### 5.7 Template fallback

- **代码路径**: `research_agent/agents/reward_agent/nodes.py`, `research_agent/agents/reward_agent/prompts.py`
- **作用**: 当 semantic regeneration 失败后，使用 template fallback 生成 patch
- **注意事项**: template fallback 的 proposal_source_penalty 更高（0.2）

### 5.8 Cross-iteration duplicate tracking

- **代码路径**: `research_agent/core/semantic_patch_gate.py` (`_compute_jaccard()`)
- **作用**: 使用 Jaccard 相似度比较当前 diff 与之前所有候选 diff，拒绝相似度 > 0.95 的重复 patches
- **输入**: `previous_diffs` 列表
- **输出**: `duplicate_similarity_max` 值

### 5.9 Candidate bank

- **代码路径**: `research_agent/core/candidate_bank.py`
- **关键类/函数**: `CandidateRecord`, `load_candidate_bank()`, `write_ranked_bank()`, `write_diversity_summary()`
- **作用**: JSONL 格式存储 validation-ready semantic patches 及其元数据
- **输入**: candidate data from executor
- **输出**: `candidate_bank.jsonl`, `candidate_bank_ranked.jsonl`, `candidate_bank_summary.md`
- **注意事项**: 每条记录含 candidate_id, diff_hash, reward_terms_added, semantic_gate_decision, syntax_valid, validation_passed 等字段

### 5.10 Candidate bank ranking

- **代码路径**: `research_agent/core/candidate_bank.py`
- **关键函数**: `rank_candidates()`, `compute_semantic_rank_score()`, `compute_reward_term_complexity()`, `compute_proposal_source_penalty()`
- **排序公式**: `base(0.5) + min(term_count/6, 0.2) - complexity*0.15 - source_penalty + template_novelty*0.15`
- **输入**: `CandidateRecord` 列表
- **输出**: `RankedCandidate` 列表（按 score 降序）

### 5.11 DiversityScheduler

- **代码路径**: `research_agent/reward_methods/diversity_scheduler.py`
- **关键类**: `DiversityScheduler`
- **关键方法**: `rank_for_diversity()`, `record_selection()`, `compute_diversity_score()`
- **作用**: 跨迭代追踪 category 使用情况，对使用较少的 category 给予 diversity bonus
- **输入**: method pool, exclude_ids
- **输出**: 按 diversity 排序的 method list
- **diversity score 公式**: `1.0 - sum(|c - max_per_cat|) / (2 * total)`
- **注意事项**: `diversity_weight=0.3` 控制 bonus 强度

### 5.12 Method pool compatibility shim

- **代码路径**: `research_agent/reward_methods/schema.py`, `research_agent/reward_methods/selector.py`
- **关键类**: `RewardMethodRecord`, `MethodSelector`
- **作用**: `RewardMethodRecord.from_dict()` 兼容 JSONL 格式；`MethodSelector.select()` 支持 category filter, confidence sort, dedup, exclude_ids
- **注意事项**: `select()` 的 `exclude_ids` 参数在 v0.8.7 之前从未被调用

### 5.13 Proposal-only mode

- **代码路径**: `run_optimizer.py` (`--proposal-only` flag), `research_agent/core/executor.py` (proposal-only 路径)
- **作用**: 只运行 propose+validate，跳过 training 和 eval
- **关键行为**:
  - `_mark_batch("tried", reason="proposal_only_validated")` 标记已尝试
  - `patch_manager.rollback_patch(candidate)` 回滚 env.py
  - pagefile warnings 作为非阻塞信息事件
- **注意事项**: v0.8.7 修复了 `_mark_batch` 缺失问题

### 5.14 Baseline guard

- **代码路径**: `research_agent/core/baseline_guard.py`
- **关键类/函数**: `BaselineGuardResult`, `BaselineManifest`, `check_baseline_consistency()`, `build_baseline_drift_error()`
- **作用**: 在 optimizer 迭代循环开始前检查 env.py 和 baseline_env.py 是否与 accepted operational baseline hash 一致
- **检查项**:
  - CHECK A: env.py 存在
  - CHECK B: env.py hash vs manifest hash
  - CHECK C: baseline_env.py vs env.py
  - CHECK D: auto_push + drift + no allow_migration → AUTO_PUSH_CONFLICT
- **manifest 路径**: `docs/baselines/hrrl2_operational_baseline.yaml`
- **注意事项**: `--accept-baseline-migration` 可覆盖 B/C 检查，但不自动写入 manifest

### 5.15 Observability

- **代码路径**: `research_agent/core/observability.py`
- **关键类**: `RunObserver`
- **输出文件**: `events.jsonl`（append-only）, `summary.json`（on close）
- **关键字段**: `run_id`, `candidates_total`, `template_diversity_score`, `semantic_gate_passed_count`, `baseline_guard_passed`, `train_called`, `full_eval_called`
- **注意事项**: 无外部依赖，纯 stdlib

### 5.16 System preflight

- **代码路径**: `research_agent/core/system_preflight.py`
- **关键类/函数**: `SystemPreflightResult`, `run_system_preflight()`
- **作用**: 训练前检测 Windows CUDA/pagefile 问题（WinError 1455）
- **行为**: pagefile 太小 → 阻塞训练；其他 import error → 非阻塞警告
- **注意事项**: proposal-only 模式下 preflight 不阻塞

---

## 6. 重要代码模块说明

### 6.1 research_agent/core/semantic_patch_gate.py

- **行数**: 286 行
- **核心函数**: `analyze_patch_semantics(diff_text, reward_function_lines, previous_diffs, similarity_threshold)`
- **输出**: `SemanticPatchDecision` dataclass
- **关键模式**: `_REWARD_TERM_PATTERNS`（20+ 正则匹配 reward/penalty/bonus/potential/shaping 等）
- **拒绝逻辑**: 空 diff → cosmetic; 全 blank/whitespace → cosmetic; 全 comment → cosmetic; 无 reward term 变化 → no_reward_term_change; 重复 → duplicate_patch_rejected

### 6.2 research_agent/core/proposal_context.py

- **行数**: 356 行
- **核心函数**: `extract_editable_reward_context(project_path, allowed_changes, target_file, target_function)`
- **输出**: `ProposalContext` dataclass
- **关键能力**: AST + regex 双重检测 reward function bounds; 提取 existing reward terms, available variables, reward expression lines

### 6.3 research_agent/core/candidate_bank.py

- **行数**: 330 行
- **核心类**: `CandidateRecord` (frozen dataclass), `RankedCandidate`, `DiversityAnalysis`
- **核心函数**: `load_candidate_bank()`, `rank_candidates()`, `compute_diversity_score()`, `write_ranked_bank()`, `write_diversity_summary()`

### 6.4 research_agent/core/system_preflight.py

- **行数**: 155 行
- **核心函数**: `run_system_preflight(execution_python)`
- **输出**: `SystemPreflightResult` dataclass
- **检测**: torch import, CUDA availability, Windows pagefile (WinError 1455)

### 6.5 research_agent/core/observability.py

- **行数**: 较长（未从仓库确认精确行数）
- **核心类**: `RunObserver`
- **关键方法**: `emit()`, `track_candidate()`, `track_template_selection()`, `write_summary()`

### 6.6 research_agent/core/executor.py

- **行数**: 较长（2700+ 行）
- **核心函数**: `_execute_optimizer_phase()`, `_attempt_semantic_regeneration()`
- **关键路径**:
  - proposal-only path (~line 2680-2708)
  - staged eval path (~line 2710+)
  - semantic gate check + regeneration loop
- **v0.8.7 修复**: `_mark_batch("tried")` at line 2703, template tracking iterates all candidate_ideas at lines 2684-2689

### 6.7 research_agent/agents/reward_agent/prompts.py

- **行数**: 较长
- **关键 prompts**:
  - `CONTEXT_PROPOSE_SYSTEM_PROMPT` / `CONTEXT_PROPOSE_USER_PROMPT`: context-grounded proposal
  - `SEMANTIC_REGENERATION_SYSTEM_PROMPT` / `SEMANTIC_REGENERATION_PROMPT`: semantic regeneration
  - `SEMANTIC_FIX_SYSTEM_PROMPT` / `SEMANTIC_FIX_PROMPT`: semantic fix
  - `FIX_SYSTEM_PROMPT` / `FIX_PROMPT`: syntax fix
  - `EMPTY_DIFF_RETRY_PROMPT`: empty diff retry
- **few-shot examples**: `docs/examples/reward_patch_few_shots.yaml`（通过 `load_few_shot_examples()` 加载）

### 6.8 research_agent/agents/reward_agent/nodes.py

- **行数**: 较长
- **关键节点**: propose node, validate node, fix node, semantic regeneration node
- **作用**: LangGraph StateGraph 的节点函数实现

### 6.9 research_agent/reward_methods/

- `diversity_scheduler.py` (85 行): DiversityScheduler
- `selector.py` (66 行): MethodSelector
- `schema.py` (41 行): RewardMethodRecord
- `formatter.py`: format_method_context(), build_source_meta_from_records()
- `loader.py`: 加载 method_pool.jsonl

### 6.10 run_optimizer.py

- **行数**: 较长
- **关键 CLI options**:
  - `--project`, `--optimizer`, `--max-iterations`, `--batch-size`
  - `--execution-python`, `--mock-llm`
  - `--proposal-only`, `--staged-eval`, `--no-short-train`
  - `--reward-method-pool`, `--reward-method-top-k`
  - `--baseline-manifest`, `--accept-baseline-migration`
  - `--max-semantic-regeneration-attempts`

---

## 7. v0.8.9 候选池交接

### Artifact 目录

`docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/`

### 目录结构

```
README.md                    — 使用说明
top_candidates_summary.md    — 候选排序表 + 风险说明
candidate_metadata.json      — 机器可读元数据
future_training_commands.md  — 训练命令模板（未执行）
candidate_patches/
  test_control_energy_005.diff  — Rank 1 patch
  test_pbrs_001.diff            — Rank 2 patch
  test_curriculum_003.diff      — Rank 3 patch
```

### Patch 数量

3 个

### candidate_metadata.json 摘要

- `source_run_id`: `20260617_123033_reward_langgraph_8bac43`
- `env_hash`: `e19703467be71e20`
- `train_called`: false
- `full_eval_called`: false
- `candidates`: 3 条记录，每条含 rank, candidate_id, selected_template, method_ids, reward_terms_added, diff_hash, semantic_rank_score, complexity_penalty, proposal_source, syntax_valid, validation_passed, semantic_gate_decision, diff_file

### top_candidates_summary.md 摘要

候选排序表，包含 rank, candidate, template, category, reward terms, score, complexity, source penalty, syntax, validation, risk note, recommendation 列。

### future_training_commands.md 用途

训练命令模板，包含：
- 前置条件（pagefile, env.py hash, baseline guard）
- Train Top 1 Candidate (control_energy) 命令
- Train Top 2 Candidates 命令
- Run Full Eval After Training 命令
- Optional Multi-Seed Confirmation 命令

**这些命令在 v0.8.9 中未执行。**

### candidate_patches/ 下的 diff 文件

| 文件 | 内容 |
|------|------|
| `test_control_energy_005.diff` | 两处插入：L971 后添加 control_energy 定义，L995 后添加 reward += control_energy |
| `test_pbrs_001.diff` | 一处插入：L995 后添加 risk_penalty 逻辑 |
| `test_curriculum_003.diff` | 一处插入：L995 后添加 stability_penalty 逻辑 |

### Top Candidates 表格

| Rank | Template | Category | Reward Terms | Score | Complexity | Syntax | Validation | Risk Note | Recommendation |
|------|----------|----------|-------------|-------|------------|--------|------------|-----------|----------------|
| 1 | test_control_energy_005 | D_adaptive_dynamic_reward | control_energy penalty (quadratic) | 0.626 | 0.16 | valid | passed | Possible under-actuation, worse tracking | keep_for_future_training |
| 2 | test_pbrs_001 | A_potential_based_reward | risk_penalty (angular_velocity + error) | 0.605 | 0.30 | valid | passed | Potential function may conflict with objective | keep_for_future_training |
| 3 | test_curriculum_003 | C_curriculum_subgoal_reward | stability_penalty (near-fall conditions) | 0.605 | 0.30 | valid | passed | Shaping mismatch or overfitting to stages | keep_for_future_training |

---

## 8. 当前推荐候选

### Top candidate: test_control_energy_005

- **Rank**: 1
- **Category**: D_adaptive_dynamic_reward
- **Score**: 0.626
- **Complexity**: 0.16（最低）
- **Proposal source**: semantic_regeneration
- **Reward term**: `control_energy = -0.01 * target_handle_angle ** 2`
- **含义**: 对 action magnitude（target_handle_angle）增加二次代价
- **潜在收益**: 更平滑动作、降低控制能量
- **潜在风险**: 控制不足（under-actuation）、路径跟踪变差、修正变慢
- **当前状态**: 仅 validation-ready，没有训练结果，不能声称性能提升

### Alternative candidates

- **test_pbrs_001** (Rank 2, score 0.605): Risk penalty for `angular_velocity > 1.5 or current_error > 0.3`，penalty = -3.0
- **test_curriculum_003** (Rank 3, score 0.605): Stability penalty for `angular_velocity > 2.0 or current_error > 0.5`，penalty = -5.0

---

## 9. 真实 run 记录

### v0.8.8 run

| 项目 | 值 |
|------|-----|
| run_id | `20260617_123033_reward_langgraph_8bac43` |
| candidates_total | 3 |
| candidates_proposal_only_validated | 3 |
| candidates_ready | 0 |
| candidates_rejected | 0 |
| template_diversity_score | 1.0 |
| template_low_diversity | False |
| semantic_gate_passed_count | 3 |
| semantic_gate_rejected_count | 0 |
| semantic_regeneration_successes | 3 |
| proposal_only | True |
| baseline_guard_passed | True |
| baseline_guard_run | True |

**template_usage_counts** (来自 summary.json):

| Template | Count |
|----------|-------|
| test_pbrs_001 | 1 |
| test_risk_penalty_004 | 1 |
| test_curriculum_003 | 1 |
| test_sparse_to_dense_002 | 1 |
| test_control_energy_005 | 1 |

**method_pool_categories_used**: A_potential_based_reward, B_safety_constraint_reward, C_curriculum_subgoal_reward, D_adaptive_dynamic_reward

**selected_template_distribution** (候选产出):

| Template | Category | Count |
|----------|----------|-------|
| test_pbrs_001 | A_potential_based_reward | 1 |
| test_curriculum_003 | C_curriculum_subgoal_reward | 1 |
| test_control_energy_005 | D_adaptive_dynamic_reward | 1 |

**selected_category_distribution**:

| Category | Count |
|----------|-------|
| A_potential_based_reward | 1 |
| C_curriculum_subgoal_reward | 1 |
| D_adaptive_dynamic_reward | 1 |

**env.py hash**: `e19703467be71e20`（run 前后一致，已从仓库确认）

### v0.8.9

| 项目 | 值 |
|------|-----|
| commit | `203f50c` |
| artifact path | `docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/` |
| patch count | 3 |
| compile + AST pass | 全部 3 个 patch 通过 |
| train_called | false |
| full_eval_called | false |

---

## 10. 测试状态

根据 reports 记录：

| 版本 | 测试结果 |
|------|---------|
| v0.8.9 | 55 key tests passed |
| v0.8.8 | 56 passed |
| v0.8.7 | 20 new tests (diversity scheduler + method pool diversity) |
| v0.8.6 | 527 passed, 1 pre-existing Windows path failure |
| v0.8.5 | 484 passed, 1 pre-existing Windows path failure |

### v0.8 系列相关测试文件（全部存在于仓库中）

| 测试文件 | 覆盖能力 |
|---------|---------|
| `tests/test_semantic_patch_gate.py` | semantic gate 拒绝 cosmetic/no-reward-term/duplicate patches |
| `tests/test_semantic_regeneration.py` | semantic regeneration 在 gate 拒绝后重新生成 |
| `tests/test_semantic_regeneration_syntax.py` | semantic regeneration 的语法安全检查 |
| `tests/test_candidate_bank.py` | candidate bank 加载、存储、记录格式 |
| `tests/test_candidate_bank_ranking.py` | candidate ranking、diversity analysis、score 计算 |
| `tests/test_template_diversity_scheduler.py` | DiversityScheduler 的 category tracking、diversity score、rank_for_diversity |
| `tests/test_method_pool_diversity.py` | 5-iteration diversity、no duplicate IDs、diversity score |
| `tests/test_method_pool_api_compat.py` | MethodSelector API 兼容性 |
| `tests/test_baseline_guard.py` | baseline guard 加载、hash 检查、drift 检测 |

### Pre-existing Windows path issue

v0.8.5/v0.8.6 报告中记录的 1 pre-existing Windows path failure 不属于 v0.8 回归，是已知的环境问题。

---

## 11. 后续如果要训练，应该怎么做

**当前不训练。** 未来如果资源允许，先训练 top 1 candidate。

### 未来训练前必须确认

1. 页面文件设置为至少 32GB，或使用 CPU-only/低资源训练方案
2. env.py hash 仍为 `e19703467be71e20`
3. baseline guard 通过
4. eval command 使用 `{checkpoint_path}`，不是 `{seed}`
5. 不使用 `--accept-baseline-migration`
6. 不修改 full eval 协议
7. 显式使用 `--optimizer reward_langgraph`

### 训练命令模板

参见 `docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/future_training_commands.md`

**这些命令尚未执行。**

### 推荐训练顺序

1. 先训练 top 1 candidate (test_control_energy_005)
2. 评估结果
3. 如果效果好，再考虑 top 2 (test_pbrs_001)
4. 不要直接扩大到全部候选

---

## 12. 禁止操作清单

| 禁止操作 | 原因 |
|---------|------|
| pop stash | autoconfig stash 不应被弹出 |
| force push tag | 会覆盖已发布的 tag |
| git push --tags | 可能推送不相关的本地 tag |
| 移动已推送的 tag | v0.1 至 v0.8.9 全部固定 |
| 跑 full eval 并改协议 | full eval 协议不可修改 |
| 把 cosmetic patch 放进 train | semantic gate 已拒绝 |
| 把 pagefile/CUDA infra failure 记作 candidate failure | 这是基础设施问题 |
| 提交 secrets | .env, MIMO_API_KEY 等 |
| 修改 baseline env.py | hash 必须保持 `e19703467be71e20` |
| 说 validation-ready candidate 已经性能提升 | 无训练结果 = 无性能声称 |

---

## 13. 给下一位接手者的建议

1. **不要立即启动 v0.9。** v0.8 系列已达成目标：semantic reward patch 生成、语法安全修复、候选排序、template/category 多样性、候选 handoff 工件保存。

2. **先阅读 v0.8.9 handoff artifacts。** `docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/` 包含所有候选 patches 和使用说明。

3. **下载论文池。** 论文 PDF + markitdown MD 文件不在 git 中，需从 GitHub Releases 下载 `reward_paper_pool_papers.zip`（约 814MB），解压到项目根目录。详见附录 C 或 `research_agent/reward_paper_pool/papers/README.md`。

4. **使用正确的 HRRL2 基线分支。** 克隆 HRRL2 后务必 `git checkout v0-baseline`，不要用 `main`。详见 1.1 节。

5. **如果要继续，优先解决资源环境或低资源训练方案。** 当前阻塞因素是 Windows 页面文件 / CUDA 资源问题（WinError 1455）。

6. **如果不训练，v0.8.9 可以作为稳定里程碑归档。** 所有候选 patches 已导出、metadata 已保存、future training commands 已文档化。

7. **如果要扩展 method pool，应先增加真实 reward templates，再做 proposal-only campaign。** 当前 method pool 中的模板来自文献，但数量有限。

8. **如果要训练，只训练 top 1–2 candidates，不要直接扩大。** 从 test_control_energy_005 开始，评估后再决定是否扩展。

9. **如继续做 proposal，不要再只优化 prompt，要先增强 method pool 的真实模板质量。** v0.8.4-v0.8.8 的经验表明，prompt 优化的收益递减，模板质量才是关键。

10. **注意安全。** 仓库中不包含任何真实密钥（已清理），但 `.env` 文件在本地磁盘上。不要将 `.env` 提交到 git，不要在文档中打印密钥值。

---

## 附录 A: v0.8 系列 tag 和 commit 对照

| 版本 | tag | 说明 |
|------|-----|------|
| v0.8 | `reward-langgraph-v0.8` | 初始 diversity 尝试 |
| v0.8.1 | `reward-langgraph-v0.8.1` | diversity real campaign（cosmetic patches） |
| v0.8.2 | `reward-langgraph-v0.8.2` | hard semantic gate |
| v0.8.3 | `reward-langgraph-v0.8.3` | proposal-only campaign |
| v0.8.4 | `reward-langgraph-v0.8.4` | method-grounded semantic patch |
| v0.8.5 | `reward-langgraph-v0.8.5` | semantic candidate bank |
| v0.8.6 | `reward-langgraph-v0.8.6` | candidate bank ranking |
| v0.8.7 | `reward-langgraph-v0.8.7` | DiversityScheduler |
| v0.8.8 | `reward-langgraph-v0.8.8` | diverse candidate bank refresh |
| v0.8.9 | `reward-langgraph-v0.8.9` | candidate handoff artifacts |

## 附录 B: 关键文件路径速查

| 文件 | 用途 |
|------|------|
| `research_agent/core/semantic_patch_gate.py` | 语义门控 |
| `research_agent/core/proposal_context.py` | 上下文提取 |
| `research_agent/core/candidate_bank.py` | 候选库 + 排序 |
| `research_agent/core/system_preflight.py` | 系统预检 |
| `research_agent/core/baseline_guard.py` | 基线守卫 |
| `research_agent/core/observability.py` | 可观测性 |
| `research_agent/core/executor.py` | 执行器（主循环） |
| `research_agent/core/patch_repair.py` | 语法修复 |
| `research_agent/agents/reward_agent/optimizer.py` | LangGraph optimizer |
| `research_agent/agents/reward_agent/prompts.py` | 提示词 |
| `research_agent/agents/reward_agent/nodes.py` | 图节点 |
| `research_agent/reward_methods/diversity_scheduler.py` | 多样性调度 |
| `research_agent/reward_methods/selector.py` | 方法选择 |
| `research_agent/reward_methods/schema.py` | 方法记录 schema |
| `run_optimizer.py` | CLI 入口 |
| `docs/baselines/hrrl2_operational_baseline.yaml` | 基线 manifest |
| `docs/artifacts/reward_langgraph_v0_8_9_candidate_handoff/` | 候选 handoff 工件 |
| `research_agent/reward_paper_pool/` | 论文池（方法模板来源） |
| `research_agent/reward_paper_pool/papers/` | 论文 PDF + MD（需从 GitHub Releases 下载） |

---

## 附录 C: 论文池下载

论文池包含 435 篇 reward shaping 相关论文（PDF）和 150 篇 markitdown 转换的 markdown 文件。文件不在 git 仓库中，需从 GitHub Releases 下载。

**下载地址**: `https://github.com/Ma-mingliang/rewardopt-research-agent/releases`

**文件名**: `reward_paper_pool_papers.zip`（约 814MB）

**解压方法**:
```bash
cd research-agent
unzip reward_paper_pool_papers.zip
```

解压后路径: `research_agent/reward_paper_pool/papers/`

详细说明见 `research_agent/reward_paper_pool/papers/README.md`。
