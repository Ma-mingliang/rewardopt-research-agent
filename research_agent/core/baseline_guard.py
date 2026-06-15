"""Baseline guard: prevent silent baseline migration.

Ensures env.py and baseline_env.py match the accepted operational baseline hash
before the optimizer candidate loop begins. Follows the (ok, Diagnostic) pattern
from eval_diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from research_agent.core.eval_diagnostics import hash_file


class BaselineDriftType(str, Enum):
    """Classification of baseline drift conditions."""

    NONE = "none"
    ENV_VS_MANIFEST = "env_vs_manifest"
    ARTIFACT_VS_ENV = "artifact_vs_env"
    ARTIFACT_MISSING = "artifact_missing"
    MANIFEST_MISSING = "manifest_missing"
    AUTO_PUSH_CONFLICT = "auto_push_conflict"


@dataclass
class BaselineGuardResult:
    """Structured result from baseline guard check."""

    ok: bool = True
    drift_type: BaselineDriftType = BaselineDriftType.NONE
    env_hash: str = ""
    artifact_hash: str = ""
    manifest_hash: str = ""
    error_message: str = ""
    diagnostic_summary: str = ""
    auto_push_detected: bool = False
    allow_migration: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for k, v in self.__dict__.items():
            if isinstance(v, Enum):
                d[k] = v.value
            else:
                d[k] = v
        return d


@dataclass
class BaselineManifest:
    """Parsed baseline manifest YAML."""

    accepted_operational_baseline_hash: str = ""
    historical_baseline_hash: str = ""
    project: str = ""
    file: str = "env.py"
    accepted_since: str = ""
    classification: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


def load_baseline_manifest(path: str | Path) -> BaselineManifest:
    """Load baseline manifest from YAML file.

    Raises FileNotFoundError if path does not exist.
    Raises ValueError if required fields are missing or empty.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Baseline manifest not found: {p}")

    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Baseline manifest is not a valid YAML dict: {p}")

    accepted_hash = data.get("accepted_operational_baseline_hash", "")
    if not accepted_hash or not str(accepted_hash).strip():
        raise ValueError(
            "Baseline manifest missing required field: accepted_operational_baseline_hash"
        )

    metrics_raw = data.get("metrics", {})
    metrics = {k: float(v) for k, v in metrics_raw.items()} if isinstance(metrics_raw, dict) else {}

    policy_raw = data.get("policy", {})
    policy = dict(policy_raw) if isinstance(policy_raw, dict) else {}

    return BaselineManifest(
        accepted_operational_baseline_hash=str(accepted_hash).strip(),
        historical_baseline_hash=str(data.get("historical_baseline_hash", "")),
        project=str(data.get("project", "")),
        file=str(data.get("file", "env.py")),
        accepted_since=str(data.get("accepted_since", "")),
        classification=str(data.get("classification", "")),
        metrics=metrics,
        policy=policy,
        notes=str(data.get("notes", "")),
    )


def compute_file_hash(path: str | Path) -> str:
    """Compute file hash using SHA256 truncated to 16 hex chars.

    Returns empty string if file does not exist.
    """
    return hash_file(path)


def check_baseline_consistency(
    project_path: str | Path,
    manifest: BaselineManifest,
    allow_migration: bool = False,
) -> BaselineGuardResult:
    """Check env.py and baseline_env.py against the accepted baseline hash.

    Returns BaselineGuardResult with ok=True only if all checks pass.
    The caller should set result.auto_push_detected after this call if needed.
    """
    pp = Path(project_path)
    env_path = pp / manifest.file
    artifact_path = pp / ".research-agent" / "artifacts" / f"baseline_{manifest.file}"
    manifest_hash = manifest.accepted_operational_baseline_hash

    result = BaselineGuardResult(
        manifest_hash=manifest_hash,
        allow_migration=allow_migration,
    )

    # CHECK A: env.py exists
    if not env_path.exists():
        result.ok = False
        result.drift_type = BaselineDriftType.ENV_VS_MANIFEST
        result.error_message = f"{manifest.file} not found: {env_path}"
        result.diagnostic_summary = f"{manifest.file} does not exist at project path"
        return result

    result.env_hash = compute_file_hash(env_path)

    # CHECK B: env.py hash vs manifest hash
    env_vs_manifest_ok = result.env_hash == manifest_hash

    # CHECK C: baseline_env.py vs env.py
    artifact_exists = artifact_path.exists()
    if artifact_exists:
        result.artifact_hash = compute_file_hash(artifact_path)
    artifact_vs_env_ok = True
    if artifact_exists:
        artifact_vs_env_ok = result.artifact_hash == result.env_hash

    # Determine if any drift detected
    drift_detected = not env_vs_manifest_ok or not artifact_vs_env_ok or not artifact_exists

    if not drift_detected:
        result.ok = True
        result.drift_type = BaselineDriftType.NONE
        result.diagnostic_summary = "Baseline guard passed"
        return result

    # Drift detected -- classify
    if not env_vs_manifest_ok:
        result.ok = False
        result.drift_type = BaselineDriftType.ENV_VS_MANIFEST
        result.error_message = (
            f"env.py hash mismatch: current={result.env_hash}, "
            f"accepted={manifest_hash}"
        )
        result.diagnostic_summary = (
            f"env.py hash ({result.env_hash}) does not match "
            f"accepted operational baseline ({manifest_hash})"
        )
        result.details = {
            "current_env_hash": result.env_hash,
            "accepted_operational_baseline_hash": manifest_hash,
            "historical_baseline_hash": manifest.historical_baseline_hash,
            "diff_hint": f"Compare current env.py with accepted baseline to identify changes",
            "fix_hint": (
                "Either restore env.py to match the accepted baseline, "
                "or update the baseline manifest after manual audit. "
                "Use --accept-baseline-migration to override."
            ),
        }
    elif not artifact_exists:
        result.ok = False
        result.drift_type = BaselineDriftType.ARTIFACT_MISSING
        result.error_message = f"baseline_{manifest.file} not found: {artifact_path}"
        result.diagnostic_summary = (
            f"Artifact baseline_{manifest.file} does not exist. "
            f"Run baseline phase first to create it."
        )
    elif not artifact_vs_env_ok:
        result.ok = False
        result.drift_type = BaselineDriftType.ARTIFACT_VS_ENV
        result.error_message = (
            f"baseline_{manifest.file} differs from {manifest.file}: "
            f"artifact={result.artifact_hash}, env={result.env_hash}"
        )
        result.diagnostic_summary = (
            f"Artifact baseline_{manifest.file} ({result.artifact_hash}) "
            f"diverges from active {manifest.file} ({result.env_hash})"
        )

    # CHECK D: allow_migration override
    if allow_migration and result.drift_type in (
        BaselineDriftType.ENV_VS_MANIFEST,
        BaselineDriftType.ARTIFACT_VS_ENV,
        BaselineDriftType.ARTIFACT_MISSING,
    ):
        result.ok = True
        result.drift_type = BaselineDriftType.NONE
        result.diagnostic_summary = (
            f"Baseline drift detected but allowed by --accept-baseline-migration. "
            f"Original drift: {result.error_message}"
        )
        return result

    return result


def build_baseline_drift_error(result: BaselineGuardResult) -> str:
    """Format a human-readable error message for a baseline drift result."""
    lines = [
        "[BASELINE GUARD FAILED]",
        f"Drift type: {result.drift_type.value}",
        f"Current env.py hash: {result.env_hash or 'N/A'}",
        f"Accepted baseline hash: {result.manifest_hash or 'N/A'}",
    ]

    if result.artifact_hash:
        lines.append(f"Artifact baseline_env.py hash: {result.artifact_hash}")

    if result.error_message:
        lines.append(f"Error: {result.error_message}")

    if result.details:
        if "historical_baseline_hash" in result.details:
            lines.append(f"Historical baseline hash: {result.details['historical_baseline_hash']}")
        if "diff_hint" in result.details:
            lines.append(f"Hint: {result.details['diff_hint']}")
        if "fix_hint" in result.details:
            lines.append(f"Fix: {result.details['fix_hint']}")

    if result.auto_push_detected:
        lines.append(
            "WARNING: auto_push=true detected. "
            "Auto-push baseline migration is disabled by default. "
            "Use --accept-baseline-migration only after manual baseline audit."
        )

    return "\n".join(lines)
