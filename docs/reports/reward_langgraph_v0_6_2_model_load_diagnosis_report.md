# Reward LangGraph v0.6.2 — Model Load Failure Diagnosis

**Date:** 2026-06-15
**Branch:** `reward-langgraph-v0.6.2-model-load-diagnosis`
**Base:** `reward-langgraph-v0.6-real-run-validation` (3722ba9)

---

## I. v0.6.2 目标

定位并修复 v0.6.1 真实 LLM run 中 full eval 阶段的 `model_load_failed` 错误。

---

## II. v0.6.1 Full Eval 失败背景

v0.6.1 的真实 LLM run 完成了完整 pipeline（LLM → validate → smoke_train → train → eval），但在 full eval 阶段失败：

- run_id: `20260615_152846_reward_langgraph_ade794`
- failure_type: `model_load_failed`
- candidate 被 reject，score=0.0000

---

## III. 证据收集

### run_id
`20260615_152846_reward_langgraph_ade794`

### eval stdout
```
[EVAL] checkpoint=42
[EVAL] episodes=30
[Stage 1 - Pure RL] 初始化环境:
  - 失败惩罚: -10.0
  - 早期失败额外惩罚: -20.0
  - 动作重复: 1
```

### eval stderr
```
Traceback (most recent call last):
  File "D:\research-agent\HRRL2\.research-agent\evaluate.py", line 90, in <module>
    main()
  File "D:\research-agent\HRRL2\.research-agent\evaluate.py", line 79, in main
    metrics = evaluate(args.checkpoint, args.episodes)
  File "D:\research-agent\HRRL2\.research-agent\evaluate.py", line 30, in evaluate
    model = TD3.load(checkpoint_path, env=env)
  ...
FileNotFoundError: [Errno 2] No such file or directory: '42.zip'
```

### 关键事实
- `[EVAL] checkpoint=42` — eval 收到的是 seed 数字，不是模型路径
- `FileNotFoundError: '42.zip'` — SB3 尝试加载 `42.zip`，文件不存在
- 模型实际路径: `model/checkpoints/v0722/best_model.zip` (5.9MB, 存在)

---

## IV. model_load_failed 分类

**B. model_path_mismatch**

训练保存路径和 full eval 读取路径不一致。

- 训练保存到: `model/checkpoints/v0722/best_model.zip`
- eval 尝试加载: `42.zip`（seed 数字，不是模型路径）

---

## V. 根因

HRRL2 的 `config.yaml` 中 `eval_command` 配置为：

```yaml
eval_command: E:/Anaconda/envs/RL2/python.exe .research-agent/evaluate.py {seed}
```

`{seed}` 被替换为种子数字（42），但 `evaluate.py` 期望第一个参数是模型文件路径。

`run_eval()` 函数只支持 `{seed}` 占位符，不支持 `{checkpoint_path}`。即使 `run_full_eval()` 传递了 `checkpoint_dir`，eval 命令模板也无法引用它。

---

## VI. 修复

### 1. `experiment_runner.py` — `run_eval()`

新增 `{checkpoint_path}` 占位符支持：

- 新增 `checkpoint_dir` 参数
- 从 `checkpoint_dir` 或 `extra_env["RA_CHECKPOINT_DIR"]` 解析模型路径
- 替换 `{checkpoint_path}` 为 `checkpoint_dir / "best_model.zip"`
- 将 `model_path` 传递给 `_build_diagnostic()`

### 2. `experiment_runner.py` — `run_full_eval()`

传递 `checkpoint_dir` 到 `run_eval()` 调用。

### 3. `experiment_runner.py` — `_build_diagnostic()`

新增 `model_path` 参数，传递给 `build_repro_command()` 以生成正确的复现命令。

### 4. `eval_diagnostics.py` — `build_repro_command()`

新增 `{checkpoint_path}` 占位符替换。

### 5. `eval_diagnostics.py` — `run_eval_preflight()`

新增 eval_command 占位符验证：当 `evaluate.py` 命令使用 `{seed}` 而非 `{checkpoint_path}` 时，preflight 失败并输出 `fix_hint`。

### 6. `HRRL2/.research-agent/config.yaml`

```yaml
# 修复前
eval_command: E:/Anaconda/envs/RL2/python.exe .research-agent/evaluate.py {seed}
# 修复后
eval_command: E:/Anaconda/envs/RL2/python.exe .research-agent/evaluate.py {checkpoint_path}
```

---

## VII. 修复文件列表

| 文件 | 修改内容 |
|------|---------|
| `research_agent/execution/experiment_runner.py` | `run_eval()` 支持 `{checkpoint_path}`；`run_full_eval()` 传递 `checkpoint_dir`；`_build_diagnostic()` 传递 `model_path` |
| `research_agent/core/eval_diagnostics.py` | `build_repro_command()` 支持 `{checkpoint_path}`；`run_eval_preflight()` 新增占位符验证；`EvalDiagnostic` 新增 `fix_hint` 等字段 |
| `HRRL2/.research-agent/config.yaml` | `eval_command` 从 `{seed}` 改为 `{checkpoint_path}`（在 .gitignore 中，需手动更新） |
| `docs/examples/hrrl2_config_eval_checkpoint_path.yaml` | 新增 tracked 配置示例 |
| `tests/test_eval_command_preflight.py` | 新增 11 个测试 |

---

## VIII. Baseline Hash 澄清

### 当前 env.py hash

- SHA256 (full): `E19703467BE71E20639C13C181DB0C760D53973D2DF7EA967FF5197E3566ACD9`
- Framework hash (SHA256 前 16 字符): `e19703467be71e20`

### 历史基准

v0.1–v0.6 报告中记录的 baseline hash 为 `5ffc1e934e1f8908`。

### 为什么变化

`5ffc1e934e1f8908` → `e19703467be71e20` 的变化发生在 v0.6.1 真实 LLM run 期间：

1. v0.6.1 run 配置 `auto_push: true`
2. Executor 启动时比较 `baseline_env.py` 和当前 `env.py` 的 MD5 hash
3. 检测到不一致时，auto_push 自动将 `baseline_env.py` 更新为当前 `env.py`
4. v0.6.1 run 完成后，executor 将 `env.py` 回滚到 `baseline_env.py`
5. 最终 `env.py` 和 `baseline_env.py` 均为 `e19703467be71e20`

### 当前一致性

- `env.py` hash: `e19703467be71e20`
- `baseline_env.py` hash: `e19703467be71e20`
- 两者一致，无污染

### autoconfig stash

未 pop，仍为 `stash@{0}`。

---

## IX. Config 可复现性保护

### 问题

`HRRL2/.research-agent/config.yaml` 被 `.gitignore` 忽略，关键修复（`{checkpoint_path}`）无法通过 git 跟踪。其他机器可能继续使用旧的 `{seed}` 配置。

### 解决方案 A：eval_command placeholder preflight

在 `run_eval_preflight()` 中新增检查：

- 检测 `evaluate.py` 命令使用 `{seed}` 而非 `{checkpoint_path}`
- preflight 失败，输出清晰错误和 `fix_hint`
- 错误在 full train 之前暴露（preflight 阶段）

preflight 失败输出示例：
```
Invalid eval_command placeholder: evaluate.py needs {checkpoint_path}, not {seed}.
Fix: In your project's .research-agent/config.yaml, change:
  eval_command: ... evaluate.py {seed}
to:
  eval_command: ... evaluate.py {checkpoint_path}
```

### 解决方案 B：tracked config example

新增 `docs/examples/hrrl2_config_eval_checkpoint_path.yaml`，展示正确的 `eval_command` 写法。该文件可被 git 跟踪，作为参考。

---

## X. 复测结果

### compileall
```
Passed (no errors)
```

### 新增 tests
```
test_eval_command_preflight.py: 11 passed
  - TestEvalCommandPreflight: 6 tests (placeholder validation)
  - TestBuildReproCommandCheckpointPath: 3 tests (repro command)
  - TestEvalDiagnosticFields: 2 tests (diagnostic fields)
```

### 相关 existing tests
```
test_eval_diagnostics.py:    18 passed
test_staged_evaluation.py:   12 passed
test_observability.py:       28 passed
```

### Full suite
```
269 passed, 1 pre-existing failure (test_smoke.py::test_initial_state)
```

### Full eval 复现（使用正确模型路径）
```
[EVAL] checkpoint=model/checkpoints/v0722/best_model.zip
[EVAL] episodes=3
reward = 972.4972
completion_rate = 1.0000
lateral_error = 0.0033
```

模型加载成功，评估产出正常 metrics。

---

## XI. Full Eval 协议是否保持不变

是。修复仅涉及 eval 命令的模型路径传递机制，不涉及：
- 评估指标（completion_rate, reward, lateral_error）
- seed 选择（仍为 [42]）
- 评估 episodes（仍为 30）
- 评分逻辑（scoring.py 未修改）
- accept/reject 判断标准

---

## XII. 是否需要 v0.6.3

不需要。根因已定位并修复，复测通过，preflight 保护已添加。

---

## XIII. v0.7 建议

1. 使用修复后的 eval 命令重新验证 v0.6.1 的 candidate（复用已有模型，不需重新训练）
2. 如果 candidate metrics 优于 baseline，验证 accept/reject 流程
3. 考虑添加 model_path 到 summary.json 以便快速诊断
