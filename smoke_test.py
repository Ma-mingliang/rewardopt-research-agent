"""Smoke test for all 12 CLI commands — fast mode with paper pool.

Mode: SMOKE (no real LLM calls, uses pre-collected paper pool)
- init: REAL
- understand / classify-task: mock report injection (LLM-dependent, not pool-related)
- select-strategy: REAL (rule-based)
- plan-experiments: mock injection (controls budget)
- search-papers: REAL with --use-pool (reads from reward_paper_pool)
- classify-papers: REAL (keyword-based, no LLM needed)
- select-papers: REAL (deterministic scoring)
- extract-ideas: REAL with --mock-llm (keyword fallback)
- run-plan: REAL execution (train/eval, optimizer with fallback)
- run --phase baseline: REAL execution
- status: REAL
"""

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

PYTHON = "E:/Anaconda/python.exe"
PROJECT = "D:/research-agent/test_accept"
MODULE = "research_agent.interfaces.cli"
STATE_PATH = Path(PROJECT) / ".research-agent" / "state.json"
CONFIG_PATH = Path(PROJECT) / ".research-agent" / "config.yaml"


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def read_phase() -> str:
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f).get("phase", "?")


def read_state() -> dict:
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def write_state(state: dict):
    tmp = STATE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE_PATH)


def run_cmd(args: list[str], timeout: int = 300) -> dict:
    cmd = [PYTHON, "-m", MODULE] + args
    start = time.monotonic()
    try:
        env = {**os.environ, "MIMO_API_KEY": os.environ.get("MIMO_API_KEY", "")}
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=PROJECT, env=env)
        dur = time.monotonic() - start
        stdout, stderr = proc.stdout.strip(), proc.stderr.strip()
        json_valid, json_data = False, None
        if stdout:
            try:
                json_data = json.loads(stdout)
                json_valid = True
            except json.JSONDecodeError:
                pass
        return {
            "cmd": " ".join(args), "code": proc.returncode, "t": round(dur, 1),
            "json": json_valid, "ok": json_data.get("ok") if json_data else None,
            "phase": read_phase(),
            "so": stdout[:200].replace("\n", " "),
            "se": stderr,  # FULL stderr
            "mock": False,
        }
    except subprocess.TimeoutExpired:
        return {
            "cmd": " ".join(args), "code": -1, "t": timeout,
            "json": False, "ok": None, "phase": read_phase(),
            "so": "TIMEOUT", "se": "TIMEOUT",
            "mock": False,
        }


def mock_result(cmd_label: str, phase: str) -> dict:
    """Record a mock-injected step as passed."""
    return {
        "cmd": cmd_label, "code": 0, "t": 0.0,
        "json": True, "ok": True, "phase": phase,
        "so": "(mock injected)", "se": "",
        "mock": True,
    }


# ──────────────────────────────────────────────
# Thorough cleanup for Windows
# ──────────────────────────────────────────────

def thorough_cleanup():
    """Remove .research-agent with retries for Windows file locking."""
    ra_dir = Path(PROJECT) / ".research-agent"
    if not ra_dir.exists():
        return
    for attempt in range(5):
        try:
            shutil.rmtree(ra_dir)
            return
        except (PermissionError, OSError):
            time.sleep(0.5)
    try:
        shutil.rmtree(ra_dir)
    except Exception as e:
        print(f"WARNING: Could not fully clean {ra_dir}: {e}", file=sys.stderr)


# ──────────────────────────────────────────────
# Mock data injection (for LLM-dependent steps)
# ──────────────────────────────────────────────

def setup_config():
    """Write config.yaml with required fields."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("metrics", {})["primary"] = [{"name": "reward", "direction": "maximize"}]
    cfg["metrics"]["metric_regex"] = {"reward": r"reward\s*=\s*([\d.]+)", "loss": r"loss\s*=\s*([\d.]+)"}
    cfg.setdefault("objective", {}).update({
        "name": "maximize_reward", "description": "Maximize reward", "focus": ["reward shaping"],
    })
    cfg.setdefault("execution", {}).update({
        "train_command": f'{PYTHON} -c "print(\'train seed={{seed}}\')"',
        "eval_command": (
            f'{PYTHON} -c "import math; s={{seed}}; '
            f'print(f\'reward = {{0.5+0.1*math.sin(s):.4f}}\'); '
            f'print(f\'loss = {{0.1+0.01*s:.4f}}\')"'
        ),
        "timeout_seconds_per_seed": 30,
    })
    cfg.setdefault("budget", {}).update({
        "wall_clock_hours": 1,
        "max_candidates": 1,
        "max_full_evals": 2,
    })
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

    # Write objective file
    obj = Path(PROJECT) / ".research-agent" / "reports" / "front_agent_objective.json"
    obj.write_text(json.dumps({
        "name": "maximize_reward",
        "description": "Maximize reward",
        "focus": ["reward shaping"],
    }), encoding="utf-8")

    state = read_state()
    state["front_agent"]["objective_written"] = True
    write_state(state)


def inject_mock_understanding():
    """Write project_understanding.json and advance state to understood."""
    report = {
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project_type": ["simple_rl"],
        "control_structure": "none",
        "train_entry": "main.py",
        "eval_entry": "main.py",
        "config_files": ["config.yaml"],
        "optimizable_targets": [
            {"name": "reward_function", "file": "main.py", "line_range": [1, 5], "type": "reward_function"},
        ],
        "readonly_targets": [],
        "metric_output_locations": [
            {"metric": "reward", "source": "stdout", "pattern": r"reward\s*=\s*([\d.]+)"},
            {"metric": "loss", "source": "stdout", "pattern": r"loss\s*=\s*([\d.]+)"},
        ],
        "optimizer_affinity": ["reward"],
    }
    reports_dir = Path(PROJECT) / ".research-agent" / "reports"
    (reports_dir / "project_understanding.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (reports_dir / "project_understanding.md").write_text("# Project Understanding\n\nMock.\n", encoding="utf-8")
    state = read_state()
    state["phase"] = "understood"
    state["project_understanding"] = {
        "report": "reports/project_understanding.md",
        "json": "reports/project_understanding.json",
        "project_type": ["simple_rl"],
    }
    write_state(state)


def inject_mock_classification():
    """Write task_classification.json and advance state to classified."""
    report = {
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_types": ["reward_optimization"],
        "confidence": 0.8,
        "recommended_strategies": ["reward shaping"],
        "not_recommended": [],
    }
    reports_dir = Path(PROJECT) / ".research-agent" / "reports"
    (reports_dir / "task_classification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    state = read_state()
    state["phase"] = "classified"
    state["task_classification"] = {
        "task_types": ["reward_optimization"],
        "confidence": 0.8,
        "report": "reports/task_classification.json",
    }
    write_state(state)


def inject_experiment_plan():
    """Write experiment_plan.json with max_candidates=1 for fast smoke."""
    reports_dir = Path(PROJECT) / ".research-agent" / "reports"
    plan = {
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "planned",
        "plan": {
            "version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "project_path": PROJECT,
            "objective_name": "maximize_reward",
            "global_budget": {
                "wall_clock_hours": 1, "gpu_hours": 1,
                "max_candidates": 1, "max_full_evals": 2,
            },
            "phases": [
                {
                    "phase_id": "baseline", "dependencies": [], "optimizer": None,
                    "objective_summary": "Establish baseline metrics.",
                    "allowed_changes": [],
                    "forbidden_changes": [{"type": "all_project_files"}],
                    "train_command": f'{PYTHON} -c "print(\'train seed=42\')"',
                    "eval_command": (
                        f'{PYTHON} -c "import math; s=42; '
                        f'print(f\'reward = {{0.5+0.1*math.sin(s):.4f}}\'); '
                        f'print(f\'loss = {{0.1+0.01*s:.4f}}\')"'
                    ),
                    "primary_metrics": ["reward"], "safety_metrics": [],
                    "budget": {"max_candidates": 0, "max_full_evals": 1, "timeout_seconds": 60},
                    "rollback_policy": "git_checkout", "cleanup_policy": "none", "status": "pending",
                },
                {
                    "phase_id": "reward-optimization", "dependencies": ["baseline"],
                    "optimizer": "reward", "task_types": ["reward_optimization"],
                    "allowed_changes": [
                        {"type": "reward_function", "file": "main.py", "line_range": [1, 5], "symbol": "reward"},
                    ],
                    "forbidden_changes": [],
                    "train_command": f'{PYTHON} -c "print(\'train seed=42\')"',
                    "eval_command": (
                        f'{PYTHON} -c "import math; s=42; '
                        f'print(f\'reward = {{0.5+0.1*math.sin(s):.4f}}\'); '
                        f'print(f\'loss = {{0.1+0.01*s:.4f}}\')"'
                    ),
                    "primary_metrics": ["reward"], "safety_metrics": [],
                    "budget": {"max_candidates": 1, "max_full_evals": 1, "timeout_seconds": 120},
                    "rollback_policy": "git_checkout", "cleanup_policy": "none", "status": "pending",
                },
            ],
        },
    }
    (reports_dir / "experiment_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    (reports_dir / "experiment_plan.md").write_text("# Experiment Plan\n\nMock.\n", encoding="utf-8")
    state = read_state()
    state["phase"] = "planned"
    state["experiment_plan"] = {
        "report": "reports/experiment_plan.md",
        "json": "reports/experiment_plan.json",
        "phases": ["baseline", "reward-optimization"],
    }
    write_state(state)


def force_phase(phase: str):
    """Force state phase without touching other fields."""
    state = read_state()
    state["phase"] = phase
    write_state(state)


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    R: list[dict] = []

    # === CLEANUP ===
    thorough_cleanup()
    Path(PROJECT).mkdir(parents=True, exist_ok=True)
    (Path(PROJECT) / "main.py").write_text(
        'import math\n'
        'def train(seed=42): return {"reward": 0.5+0.1*math.sin(seed)}\n'
        'def evaluate(seed=42):\n'
        '    r=train(seed); print(f"reward = {r[\'reward\']:.4f}"); '
        'print(f"loss = {0.1+0.01*seed:.4f}"); return r\n',
        encoding="utf-8",
    )

    # ──────────────────────────────────────────
    # 1. init — REAL
    # ──────────────────────────────────────────
    R.append(run_cmd(["init", "--project", PROJECT]))
    if R[-1]["code"] != 0:
        print("FATAL: init failed"); return 1
    setup_config()

    # ──────────────────────────────────────────
    # 2. understand — MOCK (LLM-dependent)
    # ──────────────────────────────────────────
    inject_mock_understanding()
    R.append(mock_result("understand --json (mock)", "understood"))

    # ──────────────────────────────────────────
    # 3. classify-task — MOCK (LLM-dependent)
    # ──────────────────────────────────────────
    inject_mock_classification()
    R.append(mock_result("classify-task --json (mock)", "classified"))

    # ──────────────────────────────────────────
    # 4. select-strategy — REAL (rule-based)
    # ──────────────────────────────────────────
    R.append(run_cmd(["select-strategy", "--json"]))

    # ──────────────────────────────────────────
    # 5. plan-experiments — MOCK (controls budget)
    # ──────────────────────────────────────────
    inject_experiment_plan()
    R.append(mock_result("plan-experiments --json (mock)", "planned"))

    # ──────────────────────────────────────────
    # 6. search-papers — REAL with --use-pool
    # ──────────────────────────────────────────
    R.append(run_cmd(["search-papers", "--use-pool", "--json"], timeout=30))

    # ──────────────────────────────────────────
    # 7. classify-papers — REAL (keyword-based, no LLM)
    # ──────────────────────────────────────────
    R.append(run_cmd(["classify-papers", "--mock-llm", "--json"], timeout=60))

    # ──────────────────────────────────────────
    # 8. select-papers — REAL (deterministic scoring)
    # ──────────────────────────────────────────
    R.append(run_cmd(["select-papers", "--mock-llm", "--json"], timeout=60))

    # ──────────────────────────────────────────
    # 9. extract-ideas — REAL with --mock-llm
    # ──────────────────────────────────────────
    R.append(run_cmd(["extract-ideas", "--mock-llm", "--json"], timeout=30))

    # ──────────────────────────────────────────
    # 10. run-plan — REAL execution (mock-llm for deterministic no-op candidates)
    # ──────────────────────────────────────────
    R.append(run_cmd(["run-plan", "--mock-llm", "--json"], timeout=300))

    # ──────────────────────────────────────────
    # 11. run --phase baseline — REAL execution
    # ──────────────────────────────────────────
    force_phase("ideas_extracted")
    R.append(run_cmd(["run", "--phase", "baseline", "--json"], timeout=120))

    # ──────────────────────────────────────────
    # 12. status — REAL
    # ──────────────────────────────────────────
    R.append(run_cmd(["status", "--json"]))

    # ══════════════════════════════════════════
    # RESULTS TABLE
    # ══════════════════════════════════════════
    print("\n" + "=" * 140)
    print("CLI SMOKE TEST — ALL 12 COMMANDS (POOL MODE)")
    print("=" * 140)
    print(f"{'#':<3} {'Command':<42} {'Code':<6} {'Time':<8} {'JSON':<6} {'ok':<6} {'Mock':<6} {'Phase':<24} {'stdout':<40}")
    print("-" * 140)

    passed = failed = 0
    for i, r in enumerate(R, 1):
        p = r["code"] == 0 and (r["json"] or r.get("mock"))
        if p:
            passed += 1
        else:
            failed += 1
        mock_flag = "M" if r.get("mock") else "R"
        so = r["so"][:38]
        print(f"{i:<3} {r['cmd']:<42} {r['code']:<6} {r['t']:<8} {str(r['json']):<6} {str(r['ok']):<6} {mock_flag:<6} {r['phase']:<24} {so:<40}")

    print("-" * 140)
    print(f"TOTAL: {len(R)} | PASSED: {passed} | FAILED: {failed}")
    print(f"Mode: POOL (M=mock injected, R=real command)")
    print("=" * 140)

    # ══════════════════════════════════════════
    # CHECKS
    # ══════════════════════════════════════════

    print("\n[CHECK 1] --json mode (real commands only):")
    jf = 0
    for r in R:
        if r.get("mock"):
            continue
        if "--json" in r["cmd"]:
            ok = r["json"]
            if not ok:
                jf += 1
            print(f"  {'PASS' if ok else 'FAIL'} {r['cmd']}")
    print(f"  Failures: {jf}")

    print("\n[CHECK 2] stderr (no tracebacks on success):")
    tb_count = 0
    for r in R:
        if r.get("mock"):
            continue
        if r["code"] == 0 and "Traceback" in r.get("se", ""):
            print(f"  WARN: {r['cmd']} has traceback in stderr")
            tb_count += 1
    if tb_count == 0:
        print("  All clean")

    print("\n[CHECK 3] Failed command details:")
    fail_count = 0
    for r in R:
        if r["code"] != 0:
            fail_count += 1
            print(f"  FAIL: {r['cmd']}")
            print(f"    code={r['code']} time={r['t']}s")
            if r.get("se"):
                for line in r["se"].split("\n")[-5:]:
                    print(f"    stderr: {line}")
            if r.get("so") and r["so"] != "TIMEOUT":
                print(f"    stdout: {r['so'][:200]}")
    if fail_count == 0:
        print("  None")

    print("\n[CHECK 4] Silent failures (exit 0 but ok=false):")
    sf = 0
    for r in R:
        if r.get("mock"):
            continue
        if r["code"] == 0 and r["ok"] is False:
            print(f"  WARN: {r['cmd']}")
            sf += 1
    if sf == 0:
        print("  None")

    print("\n[CHECK 5] Phase progression:")
    phases_seen = [r["phase"] for r in R]
    print(f"  Phases: {' -> '.join(phases_seen)}")

    # ══════════════════════════════════════════
    # FINAL
    # ══════════════════════════════════════════
    all_ok = failed == 0 and jf == 0
    print(f"\n{'='*140}")
    print(f"FINAL: {'ALL PASS' if all_ok else f'{failed} FAIL, {jf} JSON-FAIL'}")
    print(f"{'='*140}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
