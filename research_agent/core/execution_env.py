"""Dual-environment abstraction: agent Python vs execution Python.

LangGraph orchestration runs in the agent environment.
All project code execution (train, eval, compile, smoke test) runs
in the execution environment specified by execution_python.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ExecutionEnv:
    """Resolved execution environment for project code."""
    python_executable: str
    project_path: Path
    work_dir: Path
    timeout_seconds: int = 600
    env_vars: dict[str, str] = field(default_factory=dict)
    cwd: Path | None = None


@dataclass
class ExecutionResult:
    """Structured result from subprocess execution."""
    returncode: int
    stdout: str
    stderr: str


def resolve_execution_env(
    config: Any = None,
    cli_execution_python: str | None = None,
    project_path: Path | None = None,
    work_dir: Path | None = None,
) -> ExecutionEnv:
    """Resolve the execution environment with priority: CLI > config > sys.executable.

    Args:
        config: AgentConfig with execution.python_executable.
        cli_execution_python: CLI --execution-python argument.
        project_path: Project root path.
        work_dir: .research-agent work directory.

    Returns:
        Resolved ExecutionEnv.
    """
    agent_python = sys.executable
    fallback = False

    # Priority 1: CLI argument
    python_exec = cli_execution_python

    # Priority 2: Config
    if not python_exec and config is not None:
        exec_config = getattr(config, "execution", None)
        if exec_config is not None:
            python_exec = getattr(exec_config, "python_executable", "") or None

    # Priority 3: Fallback to current Python
    if not python_exec:
        python_exec = agent_python
        fallback = True

    # Resolve to absolute path
    python_path = Path(python_exec)
    if not python_path.is_absolute():
        # Try to find on PATH
        import shutil
        found = shutil.which(python_exec)
        if found:
            python_exec = found
        else:
            python_exec = str(python_path.resolve())
    else:
        python_exec = str(python_path)

    # Validate that explicitly specified execution_python exists
    if not fallback and not Path(python_exec).exists():
        raise FileNotFoundError(
            f"execution_python not found: {python_exec}. "
            f"Cannot fall back to agent Python — dual-environment isolation requires a valid execution Python."
        )

    # Log resolution
    print(f"[ExecutionEnv] agent_python={agent_python}", flush=True)
    print(f"[ExecutionEnv] execution_python={python_exec}", flush=True)
    print(f"[ExecutionEnv] fallback_used={fallback}", flush=True)
    if project_path:
        print(f"[ExecutionEnv] project_path={project_path}", flush=True)

    timeout = 600
    if config is not None:
        exec_config = getattr(config, "execution", None)
        if exec_config is not None:
            timeout = getattr(exec_config, "timeout_seconds_per_seed", 600)

    return ExecutionEnv(
        python_executable=python_exec,
        project_path=project_path or Path.cwd(),
        work_dir=work_dir or Path.cwd(),
        timeout_seconds=timeout,
    )


def run_in_execution_env(
    env: ExecutionEnv,
    script_code: str,
    args: list[str] | None = None,
) -> ExecutionResult:
    """Run Python script code in the execution environment via subprocess.

    Args:
        env: Execution environment.
        script_code: Python code to run with -c flag.
        args: Additional arguments.

    Returns:
        ExecutionResult with returncode, stdout, stderr.
    """
    cmd = [env.python_executable, "-c", script_code]
    if args:
        cmd.extend(args)

    cwd = str(env.cwd or env.project_path)

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=env.timeout_seconds,
            env={**os.environ, **env.env_vars} if env.env_vars else None,
        )
        return ExecutionResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    except subprocess.TimeoutExpired:
        return ExecutionResult(returncode=-1, stdout="", stderr="execution timed out")
    except FileNotFoundError:
        return ExecutionResult(
            returncode=-1,
            stdout="",
            stderr=f"Python not found: {env.python_executable}",
        )
    except Exception as e:
        return ExecutionResult(returncode=-1, stdout="", stderr=str(e))


def run_python_compile(env: ExecutionEnv, file_path: Path) -> tuple[bool, str]:
    """Check if a Python file compiles using the execution environment's Python.

    NEVER uses in-process compile() — always uses subprocess with execution_python.

    Args:
        env: Execution environment.
        file_path: Path to the Python file to compile.

    Returns:
        (True, "") if compiles, (False, error_message) if not.
    """
    result = run_in_execution_env(
        env,
        f"import py_compile; py_compile.compile(r'{file_path}', doraise=True)",
    )
    if result.returncode == 0:
        return True, ""
    error = result.stderr.strip() or "compilation failed"
    return False, error


def run_ast_check(env: ExecutionEnv, file_path: Path) -> tuple[bool, str]:
    """Check if a Python file parses as valid AST using execution Python.

    Args:
        env: Execution environment.
        file_path: Path to the Python file.

    Returns:
        (True, "") if valid, (False, error_message) if not.
    """
    result = run_in_execution_env(
        env,
        f"import ast; ast.parse(open(r'{file_path}', encoding='utf-8-sig').read())",
    )
    if result.returncode == 0:
        return True, ""
    error = result.stderr.strip() or "AST parse failed"
    return False, error


def resolve_command(command_template: str, env: ExecutionEnv) -> str:
    """Resolve {python} placeholder in a command template.

    If the template contains {python}, replace it with env.python_executable.
    Otherwise, if the command starts with 'python' or 'python3', prepend the
    execution python.

    Args:
        command_template: Command string, e.g. "python train.py --seed {seed}".
        env: Execution environment.

    Returns:
        Resolved command string.
    """
    if "{python}" in command_template:
        return command_template.replace("{python}", env.python_executable)

    # If command starts with bare 'python' or 'python3', replace with execution python
    stripped = command_template.strip()
    for prefix in ("python3 ", "python "):
        if stripped.startswith(prefix):
            return env.python_executable + stripped[len(prefix) - 1:]
    if stripped == "python" or stripped == "python3":
        return env.python_executable

    return command_template
