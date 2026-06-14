"""Full eval diagnostics: failure classification, preflight checks, repro commands.

Provides structured diagnostics for full eval failures so that each failure
can be traced to a specific cause (metrics_empty, eval_script_crashed, etc.)
and reproduced with a single copy-paste command.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class EvalFailureType(str, Enum):
    """Classification of full eval failures."""
    NONE = "none"
    EVAL_SCRIPT_CRASHED = "eval_script_crashed"
    EVAL_TIMEOUT = "eval_timeout"
    MODEL_MISSING = "model_missing"
    MODEL_LOAD_FAILED = "model_load_failed"
    ENV_IMPORT_FAILED = "env_import_failed"
    METRICS_FILE_MISSING = "metrics_file_missing"
    METRICS_PARSE_FAILED = "metrics_parse_failed"
    METRICS_EMPTY = "metrics_empty"
    REQUIRED_METRICS_MISSING = "required_metrics_missing"
    SUBPROCESS_FAILED = "subprocess_failed"
    EXECUTION_PYTHON_MISSING = "execution_python_missing"
    OUTPUT_DIR_NOT_WRITABLE = "output_dir_not_writable"
    UNKNOWN = "unknown"


@dataclass
class EvalDiagnostic:
    """Structured diagnostic record for a single eval run."""
    candidate_id: str = ""
    stage: str = "full_eval"
    failure_type: str = EvalFailureType.NONE
    failed: bool = False
    returncode: int = 0
    command: str = ""
    resolved_command: str = ""
    repro_command: str = ""
    execution_python: str = ""
    cwd: str = ""
    duration_ms: int = 0
    stdout_path: str = ""
    stderr_path: str = ""
    stdout_tail: str = ""
    stderr_tail: str = ""
    metrics_path: str = ""
    metrics_exists: bool = False
    metrics_keys: list[str] = field(default_factory=list)
    metrics_empty: bool = False
    metrics_parser_ok: bool = True
    metrics_parser_error: str = ""
    required_metrics_missing: list[str] = field(default_factory=list)
    model_path: str = ""
    model_exists: bool = False
    model_size_bytes: int = 0
    model_mtime: float = 0.0
    env_path: str = ""
    env_import_ok: bool = True
    env_import_error: str = ""
    baseline_env_hash: str = ""
    eval_env_hash: str = ""
    patched_env_hash: str = ""
    error_message: str = ""
    diagnostic_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        d = {}
        for k, v in self.__dict__.items():
            d[k] = v
        return d


def hash_file(path: str | Path, max_bytes: int = 1024 * 1024) -> str:
    """SHA256 hash of a file, truncated to 16 hex chars. Returns '' if file missing."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return ""
    try:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                h.update(chunk)
                if h.digest_size > max_bytes:
                    break
        return h.hexdigest()[:16]
    except Exception:
        return ""


def tail_text(path: str | Path, max_chars: int = 4000) -> str:
    """Read the last max_chars characters of a text file. Returns '' if missing."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return ""
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            return "..." + content[-max_chars:]
        return content
    except Exception:
        return ""


def build_repro_command(
    execution_python: str,
    eval_command: str,
    cwd: str,
    candidate_id: str = "",
    model_path: str = "",
    seed: int | None = None,
    output_dir: str = "",
) -> str:
    """Build a copy-paste repro command for PowerShell.

    Uses execution_python, not agent_python. Quotes paths with spaces.
    """
    parts = []

    # cd to project dir
    if cwd:
        if " " in cwd:
            parts.append(f'cd /d "{cwd}"')
        else:
            parts.append(f"cd /d {cwd}")

    # Build the eval command
    cmd = eval_command
    if execution_python:
        if "{python}" in cmd:
            cmd = cmd.replace("{python}", execution_python)
        else:
            stripped = cmd.strip()
            for prefix in ("python3 ", "python "):
                if stripped.startswith(prefix):
                    cmd = execution_python + stripped[len(prefix) - 1:]
                    break

    # Inject seed if available and not already in command
    if seed is not None and "{seed}" in cmd:
        cmd = cmd.replace("{seed}", str(seed))

    parts.append(cmd)

    return " && ".join(parts) if parts else cmd


def classify_eval_failure(
    returncode: int,
    timed_out: bool,
    stdout: str,
    stderr: str,
    metrics: dict,
    metrics_parser_ok: bool = True,
    metrics_parser_error: str = "",
    model_exists: bool = True,
    env_import_ok: bool = True,
    env_import_error: str = "",
    execution_python_exists: bool = True,
    output_dir_writable: bool = True,
    required_metrics: list[str] | None = None,
) -> EvalFailureType:
    """Classify the failure type based on available evidence.

    Priority order:
    1. Preflight failures (python missing, env import, model missing, dir not writable)
    2. Timeout
    3. Subprocess crash (returncode != 0)
    4. Metrics file missing / parse failure
    5. Metrics empty
    6. Required metrics missing
    7. Unknown
    """
    # Preflight failures
    if not execution_python_exists:
        return EvalFailureType.EXECUTION_PYTHON_MISSING
    if not env_import_ok:
        return EvalFailureType.ENV_IMPORT_FAILED
    if not model_exists:
        return EvalFailureType.MODEL_MISSING
    if not output_dir_writable:
        return EvalFailureType.OUTPUT_DIR_NOT_WRITABLE

    # Timeout
    if timed_out:
        return EvalFailureType.EVAL_TIMEOUT

    # Subprocess crash
    if returncode != 0:
        error_text = (stderr or "") + (stdout or "")
        lower = error_text.lower()
        if "traceback" in lower or "error" in lower:
            if "model" in lower and ("load" in lower or "open" in lower or "found" in lower):
                return EvalFailureType.MODEL_LOAD_FAILED
            if "import" in lower and ("error" in lower or "module" in lower):
                return EvalFailureType.ENV_IMPORT_FAILED
            return EvalFailureType.EVAL_SCRIPT_CRASHED
        return EvalFailureType.SUBPROCESS_FAILED

    # returncode == 0 but metrics issues
    if not metrics_parser_ok:
        return EvalFailureType.METRICS_PARSE_FAILED

    if not metrics:
        return EvalFailureType.METRICS_EMPTY

    # Check required metrics
    if required_metrics:
        missing = [m for m in required_metrics if m not in metrics or metrics[m] is None]
        if missing:
            return EvalFailureType.REQUIRED_METRICS_MISSING

    return EvalFailureType.NONE


def run_eval_preflight(
    execution_python: str,
    project_path: str | Path,
    eval_command: str,
    env_file: str | Path | None = None,
    model_path: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> tuple[bool, EvalDiagnostic]:
    """Run preflight checks before full eval.

    Returns (ok, diagnostic). If ok is False, full eval should not proceed.
    """
    diag = EvalDiagnostic(stage="preflight")

    # 1. execution_python exists
    if execution_python:
        python_exists = Path(execution_python).exists()
        diag.execution_python = execution_python
        if not python_exists:
            diag.failed = True
            diag.failure_type = EvalFailureType.EXECUTION_PYTHON_MISSING
            diag.error_message = f"execution_python not found: {execution_python}"
            diag.diagnostic_summary = f"Python executable does not exist: {execution_python}"
            return False, diag

    # 2. project_path exists
    pp = Path(project_path)
    if not pp.exists():
        diag.failed = True
        diag.failure_type = EvalFailureType.UNKNOWN
        diag.error_message = f"project_path not found: {project_path}"
        diag.diagnostic_summary = f"Project path does not exist: {project_path}"
        return False, diag

    # 3. env.py import check
    if env_file is None:
        env_file = pp / "env.py"
    env_p = Path(env_file)
    diag.env_path = str(env_p)
    if env_p.exists():
        diag.eval_env_hash = hash_file(env_p)
        if execution_python and Path(execution_python).exists():
            try:
                result = subprocess.run(
                    [execution_python, "-m", "py_compile", str(env_p)],
                    capture_output=True, text=True, timeout=30,
                    cwd=str(pp),
                )
                if result.returncode != 0:
                    diag.env_import_ok = False
                    diag.env_import_error = result.stderr[:500]
                    diag.failed = True
                    diag.failure_type = EvalFailureType.ENV_IMPORT_FAILED
                    diag.error_message = result.stderr[:500]
                    diag.diagnostic_summary = f"env.py compilation failed: {result.stderr[:200]}"
                    return False, diag
            except subprocess.TimeoutExpired:
                diag.env_import_ok = False
                diag.env_import_error = "py_compile timed out"
                diag.failed = True
                diag.failure_type = EvalFailureType.ENV_IMPORT_FAILED
                diag.diagnostic_summary = "env.py compilation timed out"
                return False, diag
            except Exception as e:
                diag.env_import_ok = False
                diag.env_import_error = str(e)[:500]

    # 4. model_path check (if known)
    if model_path:
        mp = Path(model_path)
        diag.model_path = str(mp)
        diag.model_exists = mp.exists()
        if mp.exists():
            try:
                diag.model_size_bytes = mp.stat().st_size
                diag.model_mtime = mp.stat().st_mtime
            except Exception:
                pass
        else:
            diag.failed = True
            diag.failure_type = EvalFailureType.MODEL_MISSING
            diag.error_message = f"Model file not found: {model_path}"
            diag.diagnostic_summary = f"Model does not exist: {model_path}"
            return False, diag

    # 5. output_dir writable
    if output_dir:
        od = Path(output_dir)
        if od.exists():
            writable = os.access(str(od), os.W_OK)
            if not writable:
                diag.failed = True
                diag.failure_type = EvalFailureType.OUTPUT_DIR_NOT_WRITABLE
                diag.error_message = f"Output directory not writable: {output_dir}"
                diag.diagnostic_summary = f"Cannot write to output directory: {output_dir}"
                return False, diag

    # 6. Check execution_python is used in eval_command
    if execution_python and eval_command:
        resolved = eval_command
        if "{python}" in resolved:
            resolved = resolved.replace("{python}", execution_python)
        diag.resolved_command = resolved

    diag.diagnostic_summary = "Preflight passed"
    return True, diag
