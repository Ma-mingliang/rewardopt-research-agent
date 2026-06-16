"""System preflight checks — detect infrastructure issues before training.

v0.8.2: Windows CUDA/pagefile preflight to catch WinError 1455 before
it manifests as a mysterious training crash.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SystemPreflightResult:
    """Result of system preflight checks."""
    passed: bool
    os_name: str = ""
    is_windows: bool = False
    torch_importable: bool = False
    cuda_available: bool = False
    failure_type: str = ""
    error_message: str = ""
    fix_hint: str = ""

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "os_name": self.os_name,
            "is_windows": self.is_windows,
            "torch_importable": self.torch_importable,
            "cuda_available": self.cuda_available,
            "failure_type": self.failure_type,
            "error_message": self.error_message[:200] if self.error_message else "",
            "fix_hint": self.fix_hint,
        }


_WINDOWS_PAGEFILE_HINT = (
    "Windows page file too small to load CUDA DLLs. "
    "Fix: Right-click This PC > Properties > Advanced > Performance Settings > "
    "Advanced > Virtual Memory > Set initial size 16384MB, maximum size 32768MB, then reboot."
)


def run_system_preflight(execution_python: str | None = None) -> SystemPreflightResult:
    """Run system preflight checks before training.

    Args:
        execution_python: Path to the execution Python interpreter.
            If None, uses the current interpreter.

    Returns:
        SystemPreflightResult with check results.
    """
    os_name = platform.system()
    is_windows = os_name == "Windows"

    result = SystemPreflightResult(
        passed=True,
        os_name=os_name,
        is_windows=is_windows,
    )

    # Check torch import in the execution environment
    python_exe = execution_python or sys.executable

    try:
        check_script = (
            "import sys; "
            "try:\n"
            "    import torch\n"
            "    print(f'torch_ok={torch.__version__}')\n"
            "    try:\n"
            "        cuda = torch.cuda.is_available()\n"
            "        print(f'cuda_available={cuda}')\n"
            "    except Exception as e:\n"
            "        print(f'cuda_error={e}')\n"
            "except OSError as e:\n"
            "    if '1455' in str(e) or 'pagefile' in str(e).lower():\n"
            "        print(f'PAGEFILE_ERROR={e}')\n"
            "        sys.exit(1)\n"
            "    else:\n"
            "        print(f'OSERROR={e}')\n"
            "        sys.exit(2)\n"
            "except Exception as e:\n"
            "        print(f'IMPORT_ERROR={e}')\n"
            "        sys.exit(3)\n"
        )

        proc = subprocess.run(
            [python_exe, "-c", check_script],
            capture_output=True,
            text=True,
            timeout=30,
        )

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        if "PAGEFILE_ERROR" in stdout:
            result.passed = False
            result.torch_importable = False
            result.failure_type = "infra_windows_pagefile_too_small"
            # Extract the error message
            for line in stdout.splitlines():
                if line.startswith("PAGEFILE_ERROR="):
                    result.error_message = line[len("PAGEFILE_ERROR="):]
            result.fix_hint = _WINDOWS_PAGEFILE_HINT
            return result

        if proc.returncode != 0:
            # Other import error — not a pagefile issue
            result.torch_importable = False
            if proc.returncode == 2:
                result.failure_type = "torch_import_oserror"
            elif proc.returncode == 3:
                result.failure_type = "torch_import_error"
            else:
                result.failure_type = "torch_import_unknown"
            result.error_message = stderr or stdout
            result.passed = True  # Non-fatal — don't block, just warn
            return result

        # Torch imported successfully
        result.torch_importable = True
        if "cuda_available=True" in stdout:
            result.cuda_available = True
        elif "cuda_available=False" in stdout:
            result.cuda_available = False

        result.passed = True
        return result

    except subprocess.TimeoutExpired:
        result.passed = True  # Non-fatal
        result.torch_importable = False
        result.failure_type = "torch_import_timeout"
        result.error_message = "Torch import timed out after 30s"
        return result

    except FileNotFoundError:
        result.passed = True  # Non-fatal
        result.failure_type = "execution_python_not_found"
        result.error_message = f"Python interpreter not found: {python_exe}"
        return result

    except Exception as e:
        result.passed = True  # Non-fatal
        result.failure_type = "preflight_exception"
        result.error_message = str(e)
        return result
