"""Tests for Windows CUDA/pagefile system preflight (v0.8.2)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from research_agent.core.system_preflight import (
    SystemPreflightResult,
    run_system_preflight,
    _WINDOWS_PAGEFILE_HINT,
)
from research_agent.core.observability import RunObserver


class TestSystemPreflightResult:
    def test_to_dict(self):
        result = SystemPreflightResult(
            passed=True,
            os_name="Windows",
            is_windows=True,
            torch_importable=True,
            cuda_available=True,
        )
        d = result.to_dict()
        assert d["passed"] is True
        assert d["os_name"] == "Windows"
        assert d["torch_importable"] is True

    def test_to_dict_truncates_error(self):
        result = SystemPreflightResult(
            passed=False,
            error_message="x" * 500,
        )
        d = result.to_dict()
        assert len(d["error_message"]) <= 200


class TestRunSystemPreflight:
    def test_returns_result_object(self):
        """Test that preflight returns a SystemPreflightResult."""
        result = run_system_preflight()
        assert isinstance(result, SystemPreflightResult)
        assert result.os_name in ("Windows", "Linux", "Darwin")

    def test_windows_detected(self):
        """Test Windows detection."""
        with patch("research_agent.core.system_preflight.platform") as mock_platform:
            mock_platform.system.return_value = "Windows"
            result = run_system_preflight()
            assert result.is_windows is True

    def test_non_windows(self):
        with patch("research_agent.core.system_preflight.platform") as mock_platform:
            mock_platform.system.return_value = "Linux"
            result = run_system_preflight()
            assert result.is_windows is False


class TestPagefileErrorDetection:
    def test_pagefile_error_sets_failure_type(self):
        """Test that WinError 1455 is caught and classified."""
        mock_proc = MagicMock()
        mock_proc.stdout = "PAGEFILE_ERROR=[WinError 1455] 页面文件太小"
        mock_proc.stderr = ""
        mock_proc.returncode = 1

        with patch("research_agent.core.system_preflight.subprocess.run", return_value=mock_proc):
            result = run_system_preflight(execution_python="python")
            assert result.passed is False
            assert result.failure_type == "infra_windows_pagefile_too_small"
            assert result.torch_importable is False
            assert "16384" in result.fix_hint

    def test_pagefile_error_not_counted_as_candidate_rejection(self):
        """Test that pagefile failure is infra, not candidate."""
        mock_proc = MagicMock()
        mock_proc.stdout = "PAGEFILE_ERROR=[WinError 1455] 页面文件太小"
        mock_proc.stderr = ""
        mock_proc.returncode = 1

        with patch("research_agent.core.system_preflight.subprocess.run", return_value=mock_proc):
            result = run_system_preflight(execution_python="python")
            assert result.passed is False
            assert "infra" in result.failure_type

    def test_fix_hint_contains_pagefile_guidance(self):
        mock_proc = MagicMock()
        mock_proc.stdout = "PAGEFILE_ERROR=[WinError 1455] 页面文件太小"
        mock_proc.stderr = ""
        mock_proc.returncode = 1

        with patch("research_agent.core.system_preflight.subprocess.run", return_value=mock_proc):
            result = run_system_preflight(execution_python="python")
            assert "pagefile" in result.fix_hint.lower() or "page file" in result.fix_hint.lower()
            assert "16384" in result.fix_hint

    def test_torch_success_passes(self):
        mock_proc = MagicMock()
        mock_proc.stdout = "torch_ok=2.0.0\ncuda_available=True"
        mock_proc.stderr = ""
        mock_proc.returncode = 0

        with patch("research_agent.core.system_preflight.subprocess.run", return_value=mock_proc):
            result = run_system_preflight(execution_python="python")
            assert result.passed is True
            assert result.torch_importable is True
            assert result.cuda_available is True


class TestObserverIntegration:
    def test_preflight_pass_event(self, tmp_path: Path):
        observer = RunObserver(tmp_path, "test", tmp_path)
        observer.emit("system_preflight_pass",
                      torch_importable=True,
                      cuda_available=False)
        observer.track_system_preflight(
            passed=True,
            failure_type="",
            torch_importable=True,
        )
        observer.write_summary()

        with open(observer.events_path) as f:
            events = [json.loads(l) for l in f if l.strip()]
        pass_events = [e for e in events if e["event_type"] == "system_preflight_pass"]
        assert len(pass_events) == 1

        with open(observer.summary_path) as f:
            summary = json.load(f)
        assert summary["system_preflight_passed"] is True

    def test_preflight_failed_event(self, tmp_path: Path):
        observer = RunObserver(tmp_path, "test", tmp_path)
        observer.emit("system_preflight_failed",
                      failure_type="infra_windows_pagefile_too_small",
                      error_message="WinError 1455",
                      fix_hint=_WINDOWS_PAGEFILE_HINT)
        observer.track_system_preflight(
            passed=False,
            failure_type="infra_windows_pagefile_too_small",
            torch_importable=False,
        )
        observer.write_summary()

        with open(observer.summary_path) as f:
            summary = json.load(f)
        assert summary["system_preflight_passed"] is False
        assert summary["system_preflight_failure_type"] == "infra_windows_pagefile_too_small"
        assert summary["torch_import_preflight_passed"] is False

    def test_summary_has_preflight_fields(self, tmp_path: Path):
        observer = RunObserver(tmp_path, "test", tmp_path)
        observer.write_summary()
        with open(observer.summary_path) as f:
            summary = json.load(f)
        assert "system_preflight_enabled" in summary
        assert "system_preflight_passed" in summary
        assert "system_preflight_failure_type" in summary
        assert "torch_import_preflight_passed" in summary
