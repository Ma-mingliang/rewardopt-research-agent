"""Tests for the baseline_guard module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from research_agent.core.baseline_guard import (
    BaselineDriftType,
    BaselineGuardResult,
    BaselineManifest,
    build_baseline_drift_error,
    check_baseline_consistency,
    compute_file_hash,
    load_baseline_manifest,
)
from research_agent.core.eval_diagnostics import hash_file


class TestLoadBaselineManifest:
    def test_load_valid(self, tmp_path: Path):
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(
            yaml.dump({
                "accepted_operational_baseline_hash": "abc123",
                "project": "TestProject",
                "file": "env.py",
                "metrics": {"reward": 100.0},
            }),
            encoding="utf-8",
        )
        m = load_baseline_manifest(manifest_path)
        assert m.accepted_operational_baseline_hash == "abc123"
        assert m.project == "TestProject"
        assert m.file == "env.py"
        assert m.metrics == {"reward": 100.0}

    def test_load_missing_file(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_baseline_manifest(tmp_path / "nonexistent.yaml")

    def test_load_empty_hash(self, tmp_path: Path):
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(
            yaml.dump({"accepted_operational_baseline_hash": ""}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="accepted_operational_baseline_hash"):
            load_baseline_manifest(manifest_path)

    def test_load_whitespace_hash(self, tmp_path: Path):
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(
            yaml.dump({"accepted_operational_baseline_hash": "   "}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="accepted_operational_baseline_hash"):
            load_baseline_manifest(manifest_path)


class TestComputeFileHash:
    def test_hash_matches(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("print('hello')", encoding="utf-8")
        assert compute_file_hash(f) == hash_file(f)
        assert len(compute_file_hash(f)) == 16

    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert compute_file_hash(tmp_path / "nonexistent.py") == ""


class TestCheckBaselineConsistency:
    def _make_manifest(self, accepted_hash: str) -> BaselineManifest:
        return BaselineManifest(
            accepted_operational_baseline_hash=accepted_hash,
            project="TestProject",
            file="env.py",
        )

    def _setup_project(self, tmp_path: Path, env_content: str, artifact_content: str | None = None):
        project_path = tmp_path / "project"
        project_path.mkdir()
        env_path = project_path / "env.py"
        env_path.write_text(env_content, encoding="utf-8")
        if artifact_content is not None:
            artifacts_dir = project_path / ".research-agent" / "artifacts"
            artifacts_dir.mkdir(parents=True)
            (artifacts_dir / "baseline_env.py").write_text(artifact_content, encoding="utf-8")
        return project_path

    def test_pass_all_match(self, tmp_path: Path):
        content = "def reward(): return 1"
        project_path = self._setup_project(tmp_path, content, content)
        env_hash = hash_file(project_path / "env.py")
        manifest = self._make_manifest(env_hash)

        result = check_baseline_consistency(project_path, manifest)
        assert result.ok is True
        assert result.drift_type == BaselineDriftType.NONE
        assert result.env_hash == env_hash
        assert "passed" in result.diagnostic_summary.lower()

    def test_fail_env_vs_manifest(self, tmp_path: Path):
        content = "def reward(): return 1"
        project_path = self._setup_project(tmp_path, content, content)
        manifest = self._make_manifest("0000000000000000")

        result = check_baseline_consistency(project_path, manifest)
        assert result.ok is False
        assert result.drift_type == BaselineDriftType.ENV_VS_MANIFEST
        assert result.env_hash != "0000000000000000"
        assert "fix_hint" in result.details

    def test_fail_artifact_vs_env(self, tmp_path: Path):
        env_content = "def reward(): return 1"
        artifact_content = "def reward(): return 2"
        project_path = self._setup_project(tmp_path, env_content, artifact_content)
        env_hash = hash_file(project_path / "env.py")
        manifest = self._make_manifest(env_hash)

        result = check_baseline_consistency(project_path, manifest)
        assert result.ok is False
        assert result.drift_type == BaselineDriftType.ARTIFACT_VS_ENV
        assert result.artifact_hash != result.env_hash

    def test_fail_artifact_missing(self, tmp_path: Path):
        content = "def reward(): return 1"
        project_path = self._setup_project(tmp_path, content, artifact_content=None)
        env_hash = hash_file(project_path / "env.py")
        manifest = self._make_manifest(env_hash)

        result = check_baseline_consistency(project_path, manifest)
        assert result.ok is False
        assert result.drift_type == BaselineDriftType.ARTIFACT_MISSING

    def test_allow_migration_overrides(self, tmp_path: Path):
        content = "def reward(): return 1"
        project_path = self._setup_project(tmp_path, content, content)
        manifest = self._make_manifest("0000000000000000")

        result = check_baseline_consistency(project_path, manifest, allow_migration=True)
        assert result.ok is True
        assert result.drift_type == BaselineDriftType.NONE
        assert "allowed" in result.diagnostic_summary.lower()

    def test_allow_migration_overrides_artifact_mismatch(self, tmp_path: Path):
        env_content = "def reward(): return 1"
        artifact_content = "def reward(): return 2"
        project_path = self._setup_project(tmp_path, env_content, artifact_content)
        env_hash = hash_file(project_path / "env.py")
        manifest = self._make_manifest(env_hash)

        result = check_baseline_consistency(project_path, manifest, allow_migration=True)
        assert result.ok is True

    def test_env_missing(self, tmp_path: Path):
        project_path = tmp_path / "project"
        project_path.mkdir()
        manifest = self._make_manifest("abc123")

        result = check_baseline_consistency(project_path, manifest)
        assert result.ok is False
        assert result.drift_type == BaselineDriftType.ENV_VS_MANIFEST
        assert "not found" in result.error_message


class TestAutoPushConflict:
    def test_auto_push_conflict_flag(self, tmp_path: Path):
        """When auto_push=True and drift detected, result should indicate conflict."""
        content = "def reward(): return 1"
        project_path = tmp_path / "project"
        project_path.mkdir()
        (project_path / "env.py").write_text(content, encoding="utf-8")
        artifacts_dir = project_path / ".research-agent" / "artifacts"
        artifacts_dir.mkdir(parents=True)
        (artifacts_dir / "baseline_env.py").write_text(content, encoding="utf-8")

        env_hash = hash_file(project_path / "env.py")
        manifest = BaselineManifest(
            accepted_operational_baseline_hash="0000000000000000",
        )

        result = check_baseline_consistency(project_path, manifest)
        assert result.ok is False
        assert result.drift_type == BaselineDriftType.ENV_VS_MANIFEST

        # Simulate caller setting auto_push_detected
        result.auto_push_detected = True
        error_msg = build_baseline_drift_error(result)
        assert "auto_push" in error_msg.lower()


class TestBuildBaselineDriftError:
    def test_format_includes_all_fields(self):
        result = BaselineGuardResult(
            ok=False,
            drift_type=BaselineDriftType.ENV_VS_MANIFEST,
            env_hash="aaaa",
            manifest_hash="bbbb",
            artifact_hash="cccc",
            error_message="test error",
            details={
                "historical_baseline_hash": "dddd",
                "diff_hint": "compare files",
                "fix_hint": "restore env.py",
            },
        )
        msg = build_baseline_drift_error(result)
        assert "BASELINE GUARD FAILED" in msg
        assert "aaaa" in msg
        assert "bbbb" in msg
        assert "cccc" in msg
        assert "dddd" in msg
        assert "restore env.py" in msg

    def test_auto_push_warning(self):
        result = BaselineGuardResult(
            ok=False,
            drift_type=BaselineDriftType.ENV_VS_MANIFEST,
            auto_push_detected=True,
        )
        msg = build_baseline_drift_error(result)
        assert "auto_push" in msg.lower()
        assert "--accept-baseline-migration" in msg


class TestBaselineGuardResultToDict:
    def test_to_dict_serializes_enums(self):
        result = BaselineGuardResult(
            ok=False,
            drift_type=BaselineDriftType.ARTIFACT_VS_ENV,
        )
        d = result.to_dict()
        assert d["drift_type"] == "artifact_vs_env"
        assert d["ok"] is False
        assert isinstance(d, dict)
        # Should be JSON-serializable
        json.dumps(d)


class TestObserverIntegration:
    def test_observer_events(self, tmp_path: Path):
        from research_agent.core.observability import RunObserver

        run_dir = tmp_path / "runs"
        observer = RunObserver(
            run_log_dir=str(run_dir),
            optimizer="test",
            project_path=str(tmp_path),
        )

        observer.emit("baseline_guard_start", manifest_path="test.yaml")
        observer.emit("baseline_guard_pass", env_hash="abc123")
        observer.track_baseline_guard(passed=True, manifest_path="test.yaml")
        observer.close()

        # Verify events.jsonl
        events_path = observer.run_dir / "events.jsonl"
        assert events_path.exists()
        lines = events_path.read_text(encoding="utf-8").strip().split("\n")
        event_types = [json.loads(line)["event_type"] for line in lines]
        assert "baseline_guard_start" in event_types
        assert "baseline_guard_pass" in event_types

        # Verify summary.json
        summary_path = observer.run_dir / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["baseline_guard_run"] is True
        assert summary["baseline_guard_passed"] is True
        assert summary["baseline_guard_failed"] is False
        assert summary["baseline_guard_manifest_path"] == "test.yaml"

    def test_observer_guard_failed(self, tmp_path: Path):
        from research_agent.core.observability import RunObserver

        run_dir = tmp_path / "runs"
        observer = RunObserver(
            run_log_dir=str(run_dir),
            optimizer="test",
            project_path=str(tmp_path),
        )

        observer.emit("baseline_guard_failed", drift_type="env_vs_manifest")
        observer.track_baseline_guard(
            passed=False,
            drift_type="env_vs_manifest",
            manifest_path="test.yaml",
        )
        observer.close()

        summary_path = observer.run_dir / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["baseline_guard_run"] is True
        assert summary["baseline_guard_passed"] is False
        assert summary["baseline_guard_failed"] is True
        assert summary["baseline_guard_drift_type"] == "env_vs_manifest"
