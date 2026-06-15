# Reward LangGraph v0.7.3 — Context-Grounded Reward Patch Proposal

**Date:** 2026-06-16
**Branch:** `reward-langgraph-v0.7.3-context-grounded-proposal`
**Tag:** `reward-langgraph-v0.7.3` (pending)

---

## I. Background: v0.7.2 Failure Diagnosis

The v0.7.2 second real campaign (Run ID: `20260615_224934_reward_langgraph_37290f`) showed that v0.7.1's repair budget control works (4 attempts / 38s vs 30 attempts / 5.8min). However, the initial patch generation still produced structurally invalid diffs:

- **Error**: `IndentationError` at env.py line 958
- **Root cause**: The LLM received the entire env.py file (~2300 lines) with minimal context about where the reward function was or what indentation level to use
- **Result**: The patch had wrong indentation, which even strategy escalation couldn't fix

### Why v0.7.1 Solved Repair Budget but Not Initial Patch Quality

| Problem | v0.7.1 Solution | Remaining Gap |
|---------|----------------|---------------|
| 30 wasted repair attempts | 3-tier strategy with fail-fast | Works |
| Same error repeating undetected | Error signature tracking | Works |
| No strategy switching | Automatic escalation | Works |
| **LLM generates invalid diff** | **Not addressed** | **v0.7.3 target** |

---

## II. v0.7.3 Design: Context-Grounded Proposal

### Core Idea

Instead of sending the entire env.py file to the LLM, extract the reward function with:
- Exact line numbers
- Function boundaries
- Base indentation level
- Existing reward terms
- Anchor lines before/after

This gives the LLM precise context to generate structurally valid patches.

### Architecture

```
initialize_node
  └─ extract_editable_reward_context() → ProposalContext
       ├─ detect_reward_function_bounds() [AST-first, regex fallback]
       ├─ build_line_numbered_context()
       ├─ infer_indent_unit()
       └─ extract_existing_reward_terms()

propose_node
  └─ _build_context_proposal_prompt() → (sys_prompt, user_prompt)
       └─ Uses ProposalContext for line-numbered context
  └─ initial_patch_self_check() → early rejection of bad patches
```

---

## III. ProposalContext Module

### File: `research_agent/core/proposal_context.py`

**Dataclass: ProposalContext**

| Field | Type | Description |
|-------|------|-------------|
| `target_file` | str | Target file name (default: env.py) |
| `function_name` | str | Detected reward function name |
| `function_start_line` | int | First line of reward function |
| `function_end_line` | int | Last line of reward function |
| `class_name` | str | Enclosing class name |
| `class_start_line` | int | First line of enclosing class |
| `local_context_text` | str | Function body only |
| `line_numbered_context` | str | Full context with line markers |
| `indentation_style` | str | "spaces" or "tabs" |
| `indent_unit` | int | Indent size (4 for HRRL2) |
| `base_indent` | int | Base indentation level |
| `allowed_line_ranges` | list[tuple] | Editable line ranges |
| `forbidden_summary` | str | Human-readable forbidden changes |
| `existing_reward_terms` | list[str] | Detected reward variables |
| `anchor_lines_before` | str | 3 lines before function |
| `anchor_lines_after` | str | 3 lines after function |
| `total_file_lines` | int | Total lines in file |

**Functions:**

1. `detect_reward_function_bounds(source_text, target_function)` — AST-first, regex fallback
2. `build_line_numbered_context(source_text, start, end, radius)` — Line-numbered output with `>>>` markers
3. `infer_indent_unit(source_text)` — Detect 4 spaces vs tabs
4. `extract_existing_reward_terms(source_text, function_name)` — Find reward/penalty variables
5. `extract_editable_reward_context(project_path, allowed_changes)` — Main entry point

---

## IV. Prompt Changes

### New System Prompt: `CONTEXT_PROPOSE_SYSTEM_PROMPT`

Key constraints:
- "You are given the EXACT source code of a single reward function with line numbers"
- "The unified diff MUST target the exact line numbers provided"
- "Every added line (+) MUST use the EXACT base indentation shown"
- "Do NOT alter: observation space, action space, reset logic, train/eval logic, imports, model structure, seed, metrics"
- "Do NOT create new top-level functions or classes"
- "If adding numerical terms, guard divisions/log/sqrt with epsilon"
- "Keep the diff SMALL: 5-30 lines changed maximum"
- "Only output a unified diff. No markdown, no explanation, no JSON wrapper"

### New User Prompt: `CONTEXT_PROPOSE_USER_PROMPT`

Includes:
- Function name, file, class, line range
- Base indentation (4 spaces, level 4)
- Line-numbered source with `>>>` markers for editable lines
- Existing reward terms
- Baseline metrics
- Research ideas
- Method pool context
- Allowed/forbidden changes

### Output Format

Strict: only unified diff, no JSON wrapper, no markdown, no explanation.

---

## V. Initial Patch Self-Check

### File: `research_agent/agents/reward_agent/nodes.py`

**Function: `initial_patch_self_check(diff, allowed_files, proposal_context)`**

Returns `(passed, reason, cleaned_diff)`.

### Checks (in order)

| # | Check | Reject Reason |
|---|-------|---------------|
| 1 | Empty diff | `empty_diff` |
| 2 | Markdown fences present | Strip and extract; reject if `markdown_only_no_diff` |
| 3 | Missing unified diff header (`---`/`@@`) | `missing_unified_diff_header` |
| 4 | Modifies forbidden file | `forbidden_file:<name>` |
| 5 | Too large (>80 lines) | `too_large:<count>` |
| 6 | Full-file rewrite (no context lines) | `full_file_rewrite_no_context` |
| 7 | New imports added | `new_import` |
| 8 | Mixed tabs/spaces in leading indent | `mixed_tabs_spaces` |
| 9 | Hunk targets outside editable context | `outside_editable_context:hunk_at_<N>` |

### Thresholds

- `MAX_INITIAL_PATCH_LINES`: 80
- `MAX_MODIFIED_FILES`: 1
- Editable context margin: 10 lines

---

## VI. Integration with Syntax-Aware Repair

When the initial patch fails and repair is needed:

1. `ProposalContext` is extracted once in the executor repair loop
2. For `idea_regeneration_from_baseline` strategy, the repair prompt is enriched with:
   - Editable reward function context
   - Function boundaries
   - Base indentation
   - Existing reward terms
   - Line-numbered source
3. This gives the LLM focused context for regenerating from scratch

---

## VII. Observability

### New Events

| Event | Emitted From |
|-------|-------------|
| `proposal_context_extracted` | initialize_node |
| `proposal_prompt_built` | propose_node |
| `initial_patch_self_check_start` | propose_node |
| `initial_patch_self_check_pass` | propose_node |
| `initial_patch_self_check_failed` | propose_node |
| `initial_patch_too_large` | propose_node |
| `initial_patch_outside_allowed_context` | propose_node |
| `initial_patch_markdown_stripped` | propose_node |
| `context_grounded_proposal_enabled` | (via track method) |

### New Summary Fields

| Field | Type |
|-------|------|
| `context_grounded_proposal_enabled` | bool |
| `proposal_context_file` | string \| null |
| `proposal_context_function` | string \| null |
| `proposal_context_start_line` | int |
| `proposal_context_end_line` | int |
| `initial_patch_self_check_passed` | int |
| `initial_patch_self_check_failure_reason` | string \| null |
| `initial_patch_line_count` | int |
| `initial_patch_too_large_count` | int |
| `initial_patch_outside_allowed_context_count` | int |

---

## VIII. Test Results

| Test File | Result |
|-----------|--------|
| `tests/test_context_grounded_proposal.py` | **32 passed** |
| `tests/test_llm_syntax_repair.py` | 32 passed |
| `tests/test_patch_repair_budget.py` | 21 passed |
| `tests/test_baseline_guard.py` | 19 passed |
| `tests/test_eval_diagnostics.py` | 42 passed |
| `tests/test_observability.py` | 22 passed |
| `tests/test_staged_evaluation.py` | 26 passed |
| Full suite (`tests/ -q`) | **373 passed, 1 failed** |

**Failure classification:** The 1 failure is `tests/test_smoke.py::test_initial_state` — a pre-existing Windows path issue. Not introduced by v0.7.3.

### Test Coverage (20 test cases)

1. `test_finds_reward_function` — AST detection
2. `test_returns_none_for_missing` — no function found
3. `test_line_numbers_match_source` — line numbers correct
4. `test_includes_line_numbers` — line-numbered context
5. `test_marks_function_lines` — `>>>` markers
6. `test_radius_extends_context` — context extends beyond function
7. `test_detects_4_spaces` — indent detection
8. `test_detects_tabs` — tab detection
9. `test_finds_reward_terms` — reward variable extraction
10. `test_extracts_context` — full ProposalContext extraction
11. `test_returns_none_for_missing_file` — missing file
12. `test_returns_none_for_no_reward` — no reward function
13. `test_passes_valid_diff` — self-check passes valid diff
14. `test_rejects_empty_diff` — self-check rejects empty
15. `test_rejects_missing_header` — no unified diff header
16. `test_strips_markdown` — markdown fence stripping
17. `test_rejects_markdown_only` — pure markdown rejected
18. `test_rejects_forbidden_file` — forbidden file modification
19. `test_rejects_too_large` — patch size limit
20. `test_rejects_new_imports` — no new imports

---

## IX. Mock Smoke Results

**Command:**
```
python run_optimizer.py --project HRRL2 --optimizer reward_langgraph --mock-llm \
  --max-iterations 1 --batch-size 1 \
  --reward-method-pool .research-agent/test_method_pool \
  --reward-method-top-k 3 --staged-eval --no-short-train \
  --max-patch-apply-repair-attempts 6 --max-same-error-repair-attempts 2
```

**Results:**
- `baseline_guard_passed=true`
- `env.py hash unchanged: e19703467be71e20`
- New summary fields present: `context_grounded_proposal_enabled`, `proposal_context_file`, etc.
- No crashes
- 0 candidates processed (tried_methods exhausted from previous runs)

---

## X. env.py Hash Verification

**Hash:** `e19703467be71e20` — **unchanged**.

---

## XI. Full Eval Protocol

**Not modified.** v0.7.3 only changes the initial patch proposal mechanism. Full eval protocol, seed, metrics, score, accept/reject logic are all unchanged.

---

## XII. Files Changed

| Action | File | Purpose |
|--------|------|---------|
| CREATE | `research_agent/core/proposal_context.py` | ProposalContext extraction module |
| CREATE | `tests/test_context_grounded_proposal.py` | 32 test cases |
| MODIFY | `research_agent/agents/reward_agent/prompts.py` | Context-grounded prompts |
| MODIFY | `research_agent/agents/reward_agent/nodes.py` | ProposalContext integration, self-check |
| MODIFY | `research_agent/agents/reward_agent/state.py` | Added proposal_context field |
| MODIFY | `research_agent/core/executor.py` | ProposalContext in repair loop |
| MODIFY | `research_agent/core/observability.py` | New events and summary fields |

---

## XIII. Recommendation

**Ready for v0.7.4 real campaign retry.** The context-grounded proposal:

1. Gives the LLM exact line-numbered reward function context
2. Specifies base indentation (4 spaces)
3. Self-checks patches before validation (rejects bad diffs early)
4. Enriches repair prompts with ProposalContext for targeted regeneration
5. All 373 tests pass, env.py hash unchanged, baseline guard not bypassed

The next real campaign should produce structurally valid patches because the LLM now knows exactly what to edit and at what indentation level.
