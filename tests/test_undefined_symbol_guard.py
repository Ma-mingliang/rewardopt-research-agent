"""Tests for undefined symbol guard and missing helper repair.

Regression tests for v0.8.10 repair-first strategy.
"""

import pytest
from pathlib import Path

from research_agent.core.undefined_symbol_guard import (
    UndefinedSymbolDecision,
    check_undefined_symbols,
)
from research_agent.core.repair_classifier import (
    IssueType,
    RepairIssue,
    RepairStrategy,
    classify_error,
    detect_undefined_helpers_in_patch,
)
from research_agent.core.missing_helper_repair import (
    MissingHelperRepairResult,
    repair_missing_helper,
)


class TestUndefinedSymbolGuard:
    """Test undefined symbol guard detection."""

    def test_detects_self_compute_potential_reward(self):
        """Test detection of self._compute_potential_reward() call."""
        patch_diff = """--- a/env.py
+++ b/env.py
@@ -500,7 +500,7 @@
         # Stage 3: Path tracking with residual correction
         if self.current_stage == 3:
             # Base reward from Stanley controller
-            reward = self._compute_stage3_reward()
+            reward = self._compute_stage3_reward() + self._compute_potential_reward()

             # Apply residual correction from TD3
             if self.residual_correction_enabled:"""

        available_methods = ["_compute_stage3_reward", "_compute_lqr_reward"]

        result = check_undefined_symbols(
            patch_diff=patch_diff,
            class_source="class Path_tracking_stage3:\n    def _compute_stage3_reward(self): pass",
            candidate_id="residual_control_c001",
        )

        assert not result.passed
        assert "_compute_potential_reward" in result.missing_helper_methods
        assert len(result.repair_issues) > 0
        assert result.repair_issues[0].issue_type == IssueType.UNDEFINED_HELPER_METHOD

    def test_detects_compute_potential_reward_without_self(self):
        """Test detection of _compute_potential_reward() call without self."""
        patch_diff = """--- a/env.py
+++ b/env.py
@@ -500,7 +500,7 @@
         if self.current_stage == 3:
             reward = self._compute_stage3_reward()
+            potential = _compute_potential_reward()
             return reward"""

        result = check_undefined_symbols(
            patch_diff=patch_diff,
            class_source="class Env:\n    def _compute_stage3_reward(self): pass",
            candidate_id="test_c001",
        )

        assert not result.passed
        assert "_compute_potential_reward" in result.missing_helper_methods

    def test_passes_when_all_symbols_defined(self):
        """Test that guard passes when all symbols are defined."""
        patch_diff = """--- a/env.py
+++ b/env.py
@@ -500,7 +500,7 @@
         if self.current_stage == 3:
             reward = self._compute_stage3_reward()
+            reward += self._compute_bonus()
             return reward"""

        result = check_undefined_symbols(
            patch_diff=patch_diff,
            class_source="class Env:\n    def _compute_stage3_reward(self): pass\n    def _compute_bonus(self): pass",
            candidate_id="test_c002",
        )

        assert result.passed
        assert len(result.missing_helper_methods) == 0

    def test_ignores_builtins(self):
        """Test that builtins are not flagged as undefined."""
        patch_diff = """--- a/env.py
+++ b/env.py
@@ -500,7 +500,7 @@
         if self.current_stage == 3:
             reward = self._compute_stage3_reward()
+            reward += abs(error)
             return reward"""

        result = check_undefined_symbols(
            patch_diff=patch_diff,
            class_source="class Env:\n    def _compute_stage3_reward(self): pass",
            candidate_id="test_c003",
        )

        assert result.passed
        assert "abs" not in result.missing_helper_methods


class TestRepairClassifier:
    """Test error classification."""

    def test_classifies_undefined_helper_method(self):
        """Test classification of undefined helper method error."""
        issue = classify_error(
            candidate_id="test_c001",
            error_type="NameError",
            error_message="name '_compute_potential_reward' is not defined",
            traceback_tail="  File 'env.py', line 501\n    reward = self._compute_potential_reward()",
        )

        assert issue.issue_type == IssueType.UNDEFINED_HELPER_METHOD
        assert issue.recommended_strategy == RepairStrategy.MISSING_HELPER_REPAIR
        assert issue.repairable
        assert "_compute_potential_reward" in issue.failing_symbol

    def test_classifies_syntax_error(self):
        """Test classification of syntax error."""
        issue = classify_error(
            candidate_id="test_c002",
            error_type="SyntaxError",
            error_message="invalid syntax (env.py, line 501)",
            failing_line=501,
        )

        assert issue.issue_type == IssueType.SYNTAX_ERROR
        assert issue.recommended_strategy == RepairStrategy.SYNTAX_AWARE_REPAIR
        assert issue.repairable

    def test_classifies_indentation_error(self):
        """Test classification of indentation error."""
        issue = classify_error(
            candidate_id="test_c003",
            error_type="IndentationError",
            error_message="unexpected indent (env.py, line 502)",
            failing_line=502,
        )

        assert issue.issue_type == IssueType.INDENTATION_ERROR
        assert issue.recommended_strategy == RepairStrategy.SYNTAX_AWARE_REPAIR

    def test_detects_undefined_helpers_in_patch(self):
        """Test detection of undefined helpers in patch."""
        patch_diff = """+            reward = self._compute_stage3_reward() + self._compute_potential_reward()
+            penalty = self._calculate_penalty(error)"""

        available_methods = ["_compute_stage3_reward"]

        undefined = detect_undefined_helpers_in_patch(
            patch_diff=patch_diff,
            available_methods=available_methods,
        )

        assert "_compute_potential_reward" in undefined
        assert "_calculate_penalty" in undefined
        assert "_compute_stage3_reward" not in undefined


class TestMissingHelperRepair:
    """Test missing helper repair strategy."""

    def test_inline_conversion_for_potential_reward(self):
        """Test inline conversion for potential-based reward."""
        patch_diff = """--- a/env.py
+++ b/env.py
@@ -500,7 +500,7 @@
         if self.current_stage == 3:
             reward = self._compute_stage3_reward()
-            reward += 0
+            reward += self._compute_potential_reward()
             return reward"""

        available_variables = ["current_error", "lateral_error", "reward"]

        result = repair_missing_helper(
            patch_diff=patch_diff,
            undefined_symbol="_compute_potential_reward",
            available_variables=available_variables,
            candidate_id="residual_control_c001",
        )

        assert result.success
        assert result.repair_strategy == "inline_conversion"
        assert "_compute_potential_reward" not in result.repaired_diff
        assert "current_error" in result.repaired_diff or "lateral_error" in result.repaired_diff

    def test_helper_definition_when_inline_not_possible(self):
        """Test helper definition when inline conversion is not possible."""
        patch_diff = """--- a/env.py
+++ b/env.py
@@ -500,7 +500,7 @@
         if self.current_stage == 3:
             reward = self._compute_stage3_reward()
-            reward += 0
+            reward += self._compute_special_metric()
             return reward"""

        available_variables = []  # No available variables
        class_source = """class Path_tracking_stage3:
    def __init__(self):
        pass

    def _compute_stage3_reward(self):
        return 0.0
"""

        result = repair_missing_helper(
            patch_diff=patch_diff,
            undefined_symbol="_compute_special_metric",
            available_variables=available_variables,
            class_source=class_source,
            candidate_id="test_c001",
        )

        # Should succeed with helper definition
        assert result.success
        assert result.repair_strategy == "helper_definition"
        assert "def _compute_special_metric" in result.repaired_diff

    def test_fails_when_cannot_repair(self):
        """Test failure when repair is not possible."""
        # Empty patch - nothing to repair
        patch_diff = ""

        result = repair_missing_helper(
            patch_diff=patch_diff,
            undefined_symbol="_compute_impossible",
            available_variables=[],
            candidate_id="test_c002",
        )

        assert not result.success
        assert "failed" in result.reason.lower()


class TestResidualControlC001Regression:
    """Regression tests for residual_control_c001 case."""

    def test_classifies_as_undefined_helper_method(self):
        """Test that residual_control_c001 is classified as undefined_helper_method."""
        error_message = "name '_compute_potential_reward' is not defined"
        traceback_tail = """  File "D:\\rewardopt-research-agent\\HRRL2\\env.py", line 501
    reward = self._compute_stage3_reward() + self._compute_potential_reward()
NameError: name '_compute_potential_reward' is not defined"""

        issue = classify_error(
            candidate_id="residual_control_c001",
            error_type="NameError",
            error_message=error_message,
            traceback_tail=traceback_tail,
            failing_line=501,
        )

        assert issue.issue_type == IssueType.UNDEFINED_HELPER_METHOD
        assert issue.recommended_strategy == RepairStrategy.MISSING_HELPER_REPAIR
        assert issue.failing_symbol == "_compute_potential_reward"
        assert issue.repairable

    def test_triggers_missing_helper_repair_not_generic(self):
        """Test that undefined helper triggers missing_helper_repair, not generic repair."""
        error_message = "name '_compute_potential_reward' is not defined"

        issue = classify_error(
            candidate_id="residual_control_c001",
            error_type="NameError",
            error_message=error_message,
        )

        # Should NOT be generic patch_repair_exhausted
        assert issue.issue_type != IssueType.COMPILE_ERROR
        assert issue.recommended_strategy == RepairStrategy.MISSING_HELPER_REPAIR
        assert issue.recommended_strategy != RepairStrategy.SYNTAX_AWARE_REPAIR

    def test_can_repair_with_inline_conversion(self):
        """Test that residual_control_c001 can be repaired with inline conversion."""
        patch_diff = """--- a/env.py
+++ b/env.py
@@ -500,7 +500,7 @@
         # Stage 3: Path tracking with residual correction
         if self.current_stage == 3:
             # Base reward from Stanley controller
-            reward = self._compute_stage3_reward()
+            reward = self._compute_stage3_reward() + self._compute_potential_reward()

             # Apply residual correction from TD3
             if self.residual_correction_enabled:"""

        available_variables = ["current_error", "lateral_error", "reward", "angular_velocity"]

        result = repair_missing_helper(
            patch_diff=patch_diff,
            undefined_symbol="_compute_potential_reward",
            available_variables=available_variables,
            candidate_id="residual_control_c001",
        )

        assert result.success
        assert result.repair_strategy == "inline_conversion"
        # Verify the helper call is removed
        assert "_compute_potential_reward" not in result.repaired_diff
        # Verify inline expression uses available variables
        assert any(var in result.repaired_diff for var in available_variables)


class TestProposalOnlyMode:
    """Test that proposal-only mode does not train."""

    def test_proposal_only_does_not_train(self):
        """Test that proposal-only mode skips training."""
        # This is a conceptual test - actual implementation would need mock
        # The key is that proposal-only mode should not call train_command
        pass

    def test_full_eval_not_called_in_proposal_only(self):
        """Test that full eval is not called in proposal-only mode."""
        # This is a conceptual test - actual implementation would need mock
        # The key is that proposal-only mode should not call eval_command
        pass


class TestBaselineProtection:
    """Test that baseline is not modified."""

    def test_env_py_hash_unchanged(self):
        """Test that env.py hash is not changed by repair operations."""
        # This is a conceptual test - actual implementation would check file hash
        # The key is that repair operations work on temp copies, not the real file
        pass

    def test_repair_uses_temp_copy(self):
        """Test that repair operations use temp copy of env.py."""
        # This is a conceptual test - actual implementation would verify temp file usage
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
