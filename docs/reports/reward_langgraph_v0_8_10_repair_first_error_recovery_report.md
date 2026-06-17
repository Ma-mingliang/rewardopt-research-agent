# v0.8.10: Repair-first Undefined Helper and Error-Class-Specific Recovery

**Date**: 2026-06-17  
**Branch**: reward-langgraph-v0.8.9-candidate-bank-handoff  
**Tag**: reward-langgraph-v0.8.10  
**Previous Version**: v0.8.9

---

## 1. Background

After v0.8.9, the optimizer run produced candidate `residual_control_c001` which was rejected with generic `patch_repair_exhausted after 4 attempts`. The root cause was undefined helper method `_compute_potential_reward()` being called in the patch without a corresponding definition.

### Original Failure Report

**Path**: `D:\rewardopt-research-agent\HRRL2\.research-agent\reports\rejection_analysis_report.md`

**Key Issues**:
- Candidate `residual_control_c001` called `self._compute_potential_reward()` which was not defined in `env.py`
- The repair loop attempted 4 generic strategies (direct_diff_repair → local_hunk_regeneration → idea_regeneration_from_baseline) but all failed
- The final rejection reason was generic `patch_repair_exhausted` without specific error classification

---

## 2. Why Old Repair Strategy Failed

### Root Cause Analysis

1. **No Error Classification**: The old repair loop did not classify errors into specific types
2. **Generic Repair Strategies**: All errors were treated the same way (syntax repair)
3. **No Undefined Symbol Detection**: Undefined helper methods were not detected before repair attempts
4. **No Inline Conversion**: The system did not attempt to convert helper calls to inline expressions
5. **Generic Rejection**: `patch_repair_exhausted` was used as a catch-all rejection reason

### Failure Timeline

```
Attempt 1 [direct_diff_repair]: compilation_failed (SyntaxError line 501)
Attempt 2 [direct_diff_repair]: compilation_failed (same error)
Attempt 3 [local_hunk_regeneration]: compilation_failed (same error)
Attempt 4 [idea_regeneration_from_baseline]: compilation_failed (same error)
→ patch_repair_exhausted
```

**Problem**: The system kept trying syntax repair when the real issue was an undefined symbol.

---

## 3. New Error-Class-Specific Repair Pipeline

### Architecture

```
Patch Error
    ↓
Error Classifier (repair_classifier.py)
    ↓
┌─────────────────────────────────────────┐
│  IssueType Classification               │
├─────────────────────────────────────────┤
│  • indentation_error                    │
│  • syntax_error                         │
│  • ast_parse_error                      │
│  • undefined_helper_method  ← NEW       │
│  • unresolved_symbol        ← NEW       │
│  • unavailable_variable                 │
│  • patch_outside_context                │
│  • cosmetic_patch                       │
│  • no_reward_term_change                │
│  • duplicate_patch                      │
│  • validation_error                     │
└─────────────────────────────────────────┘
    ↓
Strategy Mapping
    ↓
┌─────────────────────────────────────────┐
│  RepairStrategy                         │
├─────────────────────────────────────────┤
│  • syntax_aware_repair                  │
│  • missing_helper_repair    ← NEW       │
│  • variable_grounded_regen  ← NEW       │
│  • inline_conversion        ← NEW       │
│  • semantic_regeneration                │
│  • diversity_regeneration               │
│  • local_hunk_regeneration              │
│  • validation_guided_repair             │
└─────────────────────────────────────────┘
```

### New Files

| File | Purpose |
|------|---------|
| `research_agent/core/repair_classifier.py` | Error classification and strategy mapping |
| `research_agent/core/undefined_symbol_guard.py` | Pre-repair undefined symbol detection |
| `research_agent/core/missing_helper_repair.py` | Inline conversion and helper definition repair |
| `tests/test_undefined_symbol_guard.py` | Regression tests |

---

## 4. Undefined Helper Guard

### Detection Logic

```python
# research_agent/core/undefined_symbol_guard.py

def check_undefined_symbols(
    patch_diff: str,
    class_source: str = "",
    module_source: str = "",
    candidate_id: str = "",
    available_reward_variables: list[str] | None = None,
) -> UndefinedSymbolDecision:
    # 1. Extract added lines from diff
    # 2. Find self.method() calls
    # 3. Find function() calls
    # 4. Check against available methods
    # 5. Flag undefined helpers with _compute_*, _calculate_*, _get_*, _reward_* prefixes
    # 6. Ignore builtins and safe names
```

### Detection Results

For `residual_control_c001`:
```json
{
  "passed": false,
  "missing_helper_methods": ["_compute_potential_reward"],
  "reason": "missing_helper_methods: _compute_potential_reward"
}
```

---

## 5. Missing Helper Repair

### Strategy A: Inline Conversion (Priority)

Convert undefined helper call to inline expression using available variables.

**Example**:
```python
# Before (undefined helper)
reward = self._compute_stage3_reward() + self._compute_potential_reward()

# After (inline conversion)
reward = self._compute_stage3_reward() + (-0.5 * abs(current_error))
```

**Rules**:
- Only use variables from `available_reward_variables`
- No new helper methods
- No new imports
- Minimal local diff
- Must pass compile/AST/semantic gate/validation

### Strategy B: Helper Definition Repair

Only when inline conversion is not possible, add complete helper method definition.

**Example**:
```python
# Added to class
def _compute_potential_reward(self):
    """Compute potential-based reward."""
    k_phi = 0.5
    if hasattr(self, 'current_error'):
        return -k_phi * abs(self.current_error)
    return 0.0
```

**Rules**:
- Complete method definition
- Correct indentation
- Parameters match call
- Only use available variables
- Must pass compile/AST/undefined symbol guard/semantic gate/validation

---

## 6. Variable-Grounded Regeneration Fallback

When missing helper repair fails, use variable-grounded regeneration.

**Rules**:
1. Extract available_reward_variables from ProposalContext
2. Choose implementable reward term based on current method/template
3. Do not use non-existent variables
4. Generate new inline reward expression
5. Do not call any new helpers
6. Do not add imports
7. Do not add class methods
8. Run compile/AST/semantic gate/validation

**If still fails**: Reject with specific reason:
- `missing_helper_repair_failed`
- `unavailable_required_variable`

**NOT**: `patch_repair_exhausted`

---

## 7. Prompt Updates

### Updated Prompts

**CONTEXT_PROPOSE_SYSTEM_PROMPT**:
```
- Do NOT call helper methods that are not already defined in the provided context.
- Do NOT invent `_compute_*`, `_calculate_*`, `_get_*`, or `_reward_*` functions.
- Prefer inline reward expressions using available variables.
- If introducing a helper method, include the complete method definition in the same diff.
- A patch calling an undefined helper is invalid.
```

**SEMANTIC_REGENERATION_SYSTEM_PROMPT**:
```
CRITICAL HELPER RULES:
- Do NOT call helper methods that are not already defined in the provided context.
- Do NOT invent `_compute_*`, `_calculate_*`, `_get_*`, or `_reward_*` functions.
- Prefer inline reward expressions using available variables.
- If introducing a helper method, include the complete method definition in the same diff.
- A patch calling an undefined helper is invalid.
- For potential-based reward, use inline potential terms unless an existing potential function is already present.
```

---

## 8. residual_control_c001 Regression Result

### Test Results

```python
# Test: test_classifies_as_undefined_helper_method
assert issue.issue_type == IssueType.UNDEFINED_HELPER_METHOD ✓
assert issue.recommended_strategy == RepairStrategy.MISSING_HELPER_REPAIR ✓
assert issue.failing_symbol == "_compute_potential_reward" ✓
assert issue.repairable ✓

# Test: test_triggers_missing_helper_repair_not_generic
assert issue.issue_type != IssueType.COMPILE_ERROR ✓
assert issue.recommended_strategy == RepairStrategy.MISSING_HELPER_REPAIR ✓
assert issue.recommended_strategy != RepairStrategy.SYNTAX_AWARE_REPAIR ✓

# Test: test_can_repair_with_inline_conversion
assert result.success ✓
assert result.repair_strategy == "inline_conversion" ✓
assert "_compute_potential_reward" not in result.repaired_diff ✓
assert any(var in result.repaired_diff for var in available_variables) ✓
```

### Repair Output

```
residual_control_c001
undefined_helper_method detected
missing_helper_repair applied
inline reward expression generated
compile passed
AST passed
semantic gate passed
validation passed
patch_repair_exhausted avoided ✓
```

---

## 9. Test Results

### Test Suite

```
tests/test_undefined_symbol_guard.py::TestUndefinedSymbolGuard::test_detects_self_compute_potential_reward PASSED
tests/test_undefined_symbol_guard.py::TestUndefinedSymbolGuard::test_detects_compute_potential_reward_without_self PASSED
tests/test_undefined_symbol_guard.py::TestUndefinedSymbolGuard::test_passes_when_all_symbols_defined PASSED
tests/test_undefined_symbol_guard.py::TestUndefinedSymbolGuard::test_ignores_builtins PASSED
tests/test_undefined_symbol_guard.py::TestRepairClassifier::test_classifies_undefined_helper_method PASSED
tests/test_undefined_symbol_guard.py::TestRepairClassifier::test_classifies_syntax_error PASSED
tests/test_undefined_symbol_guard.py::TestRepairClassifier::test_classifies_indentation_error PASSED
tests/test_undefined_symbol_guard.py::TestRepairClassifier::test_detects_undefined_helpers_in_patch PASSED
tests/test_undefined_symbol_guard.py::TestMissingHelperRepair::test_inline_conversion_for_potential_reward PASSED
tests/test_undefined_symbol_guard.py::TestMissingHelperRepair::test_helper_definition_when_inline_not_possible PASSED
tests/test_undefined_symbol_guard.py::TestMissingHelperRepair::test_fails_when_cannot_repair PASSED
tests/test_undefined_symbol_guard.py::TestResidualControlC001Regression::test_classifies_as_undefined_helper_method PASSED
tests/test_undefined_symbol_guard.py::TestResidualControlC001Regression::test_triggers_missing_helper_repair_not_generic PASSED
tests/test_undefined_symbol_guard.py::TestResidualControlC001Regression::test_can_repair_with_inline_conversion PASSED
tests/test_undefined_symbol_guard.py::TestProposalOnlyMode::test_proposal_only_does_not_train PASSED
tests/test_undefined_symbol_guard.py::TestProposalOnlyMode::test_full_eval_not_called_in_proposal_only PASSED
tests/test_undefined_symbol_guard.py::TestBaselineProtection::test_env_py_hash_unchanged PASSED
tests/test_undefined_symbol_guard.py::TestBaselineProtection::test_repair_uses_temp_copy PASSED

======================== 18 passed in 0.09s =========================
```

---

## 10. Key Metrics

| Metric | Value |
|--------|-------|
| **env.py hash** | `a08f66bb363e375cd0e18a4c2bc5df0d` (unchanged) |
| **train_called** | false |
| **full_eval_called** | false |
| **patch_repair_exhausted avoided** | yes |
| **Tests passed** | 18/18 |
| **Working tree** | clean (before commit) |

---

## 11. Error Classification Table

| candidate_id | original_error | root_cause | current_repair_result | required_repair_strategy |
|--------------|----------------|------------|----------------------|--------------------------|
| residual_control_c001 | SyntaxError (compilation_failed) | missing_helper_method / unresolved_symbol | patch_repair_exhausted | missing_helper_repair → inline_conversion |

---

## 12. Acceptance Criteria

| Criteria | Status |
|----------|--------|
| Every error candidate is classified | ✓ |
| Every error candidate enters corresponding repair strategy | ✓ |
| Undefined helper does not enter generic repair loop | ✓ |
| Inline-repairable patches are fixed | ✓ |
| Unfixable patches have specific, explainable reasons | ✓ |
| `patch_repair_exhausted` no longer used for missing helper | ✓ |
| train_called=false | ✓ |
| full_eval_called=false | ✓ |
| env.py hash unchanged | ✓ |

---

## 13. Recommendations

### For Future Development

1. **Extend Inline Patterns**: Add more inline conversion patterns for common reward terms
2. **Improve Helper Detection**: Enhance detection of complex helper patterns
3. **Add More Test Cases**: Cover more edge cases for undefined symbols
4. **Update Method Pool**: Ensure method pool templates use inline expressions

### For Users

1. **Review Repaired Patches**: Always review inline-converted patches before training
2. **Check Available Variables**: Ensure `available_reward_variables` is complete
3. **Test Locally**: Run `proposal-only` mode before full training runs

---

## 14. Conclusion

v0.8.10 successfully implements repair-first strategy for undefined helper methods. The system now:

1. **Classifies errors** into specific types before repair
2. **Detects undefined symbols** before attempting generic repair
3. **Attempts inline conversion** as the first repair strategy
4. **Provides specific rejection reasons** instead of generic `patch_repair_exhausted`
5. **Preserves baseline** (env.py hash unchanged)
6. **Does not train** (proposal-only mode)

The `residual_control_c001` case is now handled correctly with `missing_helper_repair` → `inline_conversion` strategy, avoiding the generic `patch_repair_exhausted` rejection.

---

**Report Generated**: 2026-06-17  
**Version**: v0.8.10  
**Tests**: 18/18 passed  
**Status**: Ready for commit and tag
