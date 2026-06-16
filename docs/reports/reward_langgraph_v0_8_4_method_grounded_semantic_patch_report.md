# v0.8.4: Method-Grounded Semantic Reward Patch Generation

**Date**: 2026-06-16
**Branch**: reward-langgraph-v0.8.4
**Tag**: reward-langgraph-v0.8.4

## Goal

Improve the quality of LLM-generated reward patches by:
1. Providing few-shot examples of valid reward patches
2. Extracting available reward variables from the target function
3. Improving prompts with anti-cosmetic rules and semantic checklists
4. Implementing semantic regeneration when the gate rejects a patch

## Problem Analysis (v0.8.3)

All 3 candidates in the v0.8.3 campaign produced identical cosmetic blank-line patches:
- The LLM returns empty diff initially
- Routes to fix path
- Generates simplest "fix" (blank line addition)
- Semantic gate correctly rejects, but no retry mechanism exists

**Root cause**: Prompt lacks few-shot examples; LLM doesn't understand "reward term modification".

## Implementation

### 1. Few-Shot Reward Patch Examples

Created `docs/examples/reward_patch_few_shots.yaml` with 4 examples:
- **pbrs_potential_shaping**: PBRS potential-based reward shaping
- **tracking_error_penalty**: Squared tracking error penalty
- **control_energy_penalty**: Action energy regularization
- **stability_fall_penalty**: Angular velocity stability penalty

Each example includes:
- Method category and intent
- Available variables used
- Before/after code snippets
- Unified diff
- Why it's semantic (not cosmetic)
- Forbidden cosmetic patterns
- Required changed terms

### 2. ProposalContext Enhancement

Added to `research_agent/core/proposal_context.py`:
- `available_reward_variables` field: Extracts parameters, local assignments, and common RL variables
- `existing_reward_expression_lines` field: Extracts lines with reward accumulation patterns
- `extract_available_reward_variables()` function
- `extract_reward_expression_lines()` function

### 3. Prompt Improvements

Updated `research_agent/agents/reward_agent/prompts.py`:
- `CONTEXT_PROPOSE_USER_PROMPT`: Added available_reward_variables, existing_reward_expression_lines, few_shot_examples, MANDATORY SEMANTIC DELTA CHECKLIST, VALID PATCH CONTRACT
- `SEMANTIC_FIX_PROMPT`: Added available_reward_variables, existing_reward_expression_lines, few_shot_examples, MANDATORY RULES
- Added `SEMANTIC_REGENERATION_SYSTEM_PROMPT` and `SEMANTIC_REGENERATION_PROMPT`
- Added `load_few_shot_examples()` function with YAML loading and fallback

### 4. Semantic Regeneration Node

Added to `research_agent/core/executor.py`:
- `_attempt_semantic_regeneration()`: Calls LLM with SEMANTIC_REGENERATION_PROMPT when gate rejects
- `_extract_diff_from_response()`: Extracts unified diff from LLM response text
- Regeneration logic: Tries up to `max_semantic_regeneration_attempts` times before rejecting
- Extracts `proposal_context` and `method_context` from optimizer's graph state

### 5. Observability

Added to `research_agent/core/observability.py`:
- `track_semantic_regeneration()` method
- Counters: `_semantic_regeneration_attempts`, `_semantic_regeneration_successes`, `_semantic_regeneration_failures`
- Summary fields: `semantic_regeneration_attempts`, `semantic_regeneration_successes`, `semantic_regeneration_failures`

### 6. CLI Flag

Added to `run_optimizer.py`:
- `--max-semantic-regeneration-attempts` (default: 2)
- Passed through to `_execute_optimizer_phase`

## Test Results

### Unit Tests (32 tests)

```
tests/test_semantic_regeneration.py::TestExtractDiffFromResponse (7 tests) PASSED
tests/test_semantic_regeneration.py::TestAttemptSemanticRegeneration (6 tests) PASSED
tests/test_semantic_regeneration.py::TestRegenerationObservability (3 tests) PASSED
tests/test_reward_patch_few_shots.py::TestLoadFewShotExamples (8 tests) PASSED
tests/test_reward_patch_few_shots.py::TestFewShotExampleContent (8 tests) PASSED
```

### Full Test Suite

```
469 passed, 1 failed (pre-existing Windows path issue in test_smoke.py)
```

### Mock Smoke Test

```
--mock-llm --max-iterations 1 --batch-size 1 --proposal-only --max-semantic-regeneration-attempts 2
Result: candidate rejected as empty_patch (expected in mock mode)
Summary: semantic_regeneration_attempts=0, baseline_guard_passed=true
```

### Real Proposal-Only Campaign

```
--max-iterations 1 --batch-size 3 --proposal-only --max-semantic-regeneration-attempts 2 --optimizer reward_langgraph

Candidate 1 (v0741):
- Initial patch: cosmetic (blank line addition)
- Semantic gate: REJECTED (cosmetic_patch_rejected)
- Regeneration attempt 1: empty_response → failed
- Regeneration attempt 2: empty_response → failed
- Final: REJECTED after 2 regeneration attempts

Summary:
- semantic_gate_rejected_count: 1
- cosmetic_patch_rejected_count: 1
- semantic_regeneration_attempts: 1 (overall outcome tracking)
- semantic_regeneration_failures: 1
- baseline_guard_passed: true
```

## Observability Fields

### Summary JSON (new fields)

```json
{
  "semantic_regeneration_attempts": 1,
  "semantic_regeneration_successes": 0,
  "semantic_regeneration_failures": 1
}
```

### Events JSONL (new event types)

- `semantic_regeneration_start`: When regeneration begins
- `semantic_regeneration_attempt`: Each regeneration attempt
- `semantic_regeneration_success`: When regeneration produces valid patch
- `semantic_regeneration_attempt_failed`: When single attempt fails
- `semantic_regeneration_failed`: When all attempts exhausted

## Files Modified

| File | Changes |
|------|---------|
| `research_agent/core/executor.py` | Added `_attempt_semantic_regeneration()`, `_extract_diff_from_response()`, regeneration logic |
| `research_agent/core/observability.py` | Added `track_semantic_regeneration()`, counters, summary fields |
| `research_agent/core/proposal_context.py` | Added `available_reward_variables`, `existing_reward_expression_lines` fields and extractors |
| `research_agent/agents/reward_agent/prompts.py` | Updated prompts with few-shot examples, anti-cosmetic rules, regeneration prompts |
| `research_agent/agents/reward_agent/nodes.py` | Updated to pass new context fields to prompts |
| `run_optimizer.py` | Added `--max-semantic-regeneration-attempts` CLI flag |

## Files Created

| File | Purpose |
|------|---------|
| `docs/examples/reward_patch_few_shots.yaml` | 4 few-shot examples of valid reward patches |
| `tests/test_semantic_regeneration.py` | 16 tests for regeneration logic |
| `tests/test_reward_patch_few_shots.py` | 16 tests for few-shot examples |
| `docs/reports/reward_langgraph_v0_8_4_method_grounded_semantic_patch_report.md` | This report |

## Key Design Decisions

1. **Few-shot examples in YAML**: Easy to maintain and extend; loaded at runtime with fallback
2. **Available variables extraction**: AST-based extraction of parameters, local assignments, and common RL vars
3. **Regeneration before rejection**: When gate rejects, try regenerating up to N times before final rejection
4. **Extract context from optimizer state**: `proposal_context` and `method_context` extracted from LangGraph state
5. **Observability tracking**: Track overall regeneration outcome (success/failure) separately from individual attempts

## Next Steps

1. Run longer campaign (10+ candidates) to evaluate patch quality improvement
2. Analyze regeneration success rate across different rejection reasons
3. Consider adding more few-shot examples for different reward patterns
4. Monitor for new failure modes (e.g., regeneration producing invalid diffs)
