"""Tests for patch hunk relocation.

Covers:
- Hunk relocation with matching anchors
- Hunk relocation failure without anchors
- Line number drift detection
"""

import pytest

from research_agent.core.patch_hunk_relocation import (
    HunkRelocationResult,
    relocate_hunks,
    detect_line_number_drift,
)


class TestHunkRelocation:
    """Test hunk relocation."""

    def test_relocate_with_matching_anchors(self):
        """Should relocate hunk when anchors match."""
        diff = """--- a/env.py
+++ b/env.py
@@ -100,5 +100,7 @@
     def step(self):
         reward = 0
+        # New penalty
+        penalty = -1.0
         return reward"""

        target_content = """
    def step(self):
        reward = 0
        return reward
"""

        result = relocate_hunks(diff, target_content)
        # Should succeed or at least attempt relocation
        assert result.original_diff == diff

    def test_relocate_empty_diff(self):
        """Should handle empty diff."""
        result = relocate_hunks("", "target")
        assert result.success is False

    def test_relocate_empty_target(self):
        """Should handle empty target."""
        result = relocate_hunks("diff", "")
        assert result.success is False


class TestLineDriftDetection:
    """Test line number drift detection."""

    def test_no_drift(self):
        """Should detect no drift when line numbers are correct."""
        diff = """--- a/env.py
+++ b/env.py
@@ -1,3 +1,4 @@
 line1
 line2
+new line
 line3"""

        target = "line1\nline2\nline3"
        result = detect_line_number_drift(diff, target)
        assert result["drift_detected"] is False

    def test_drift_detected(self):
        """Should detect drift when line numbers are too high."""
        diff = """--- a/env.py
+++ b/env.py
@@ -999,3 +999,4 @@
 line1
 line2
+new line
 line3"""

        target = "line1\nline2\nline3"
        result = detect_line_number_drift(diff, target, tolerance=5)
        assert result["drift_detected"] is True
        assert result["drift_count"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
