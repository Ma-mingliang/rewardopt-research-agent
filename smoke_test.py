"""Smoke test for all 12 CLI commands - clean version."""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

PYTHON = "E:/Anaconda/python.exe"
PROJECT = "D:/research-agent/test_accept"
MODULE = "research_agent.interfaces.cli"
STATE_PATH = Path(PROJECT) / ".research-agent" / "state.json"
CONFIG_PATH = Path(PROJECT) / ".research-agent" / "config.yaml"


def read_phase() -> str:
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f).get("phase", "?")


def run_cmd(args: list[str], timeout: int = 300) -> dict:
    cmd = [PYTHON, "-m", MODULE] + args
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=PROJECT)
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
            "so": stdout[:40].replace("\n", " "),
            "se": stderr[:40].replace("\n", " ") if stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "cmd": " ".join(args), "code": -1, "t": timeout,
            "json": False, "ok": None, "phase": read_phase(),
            "so": "TIMEOUT", "se": "TIMEOUT",
        }


def setup_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("metrics", {})["primary"] = [{"name": "reward", "direction": "maximize"}]
    cfg["metrics"]["metric_regex"] = {"reward": r"reward\s*=\s*([\d.]+)", "loss": r"loss\s*=\s*([\d.]+)"}
    cfg.setdefault("objective", {}).update({"name": "maximize_reward", "description": "Maximize reward", "focus": ["reward shaping"]})
    cfg.setdefault("execution", {}).update({
        "train_command": f'{PYTHON} -c "print(\'train seed={{seed}}\')"',
        "eval_command": f'{PYTHON} -c "import math; s={{seed}}; print(f\'reward = {{0.5+0.1*math.sin(s):.4f}}\'); print(f\'loss = {{0.1+0.01*s:.4f}}\')"',
        "timeout_seconds_per_seed": 30,
    })
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    obj = Path(PROJECT) / ".research-agent" / "reports" / "front_agent_objective.json"
    obj.write_text(json.dumps({"name": "maximize_reward", "description": "Maximize reward", "focus": ["reward shaping"]}), encoding="utf-8")
    # Mark objective written in state
    with open(STATE_PATH, encoding="utf-8") as f:
        state = json.load(f)
    state["front_agent"]["objective_written"] = True
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def write_mock_papers():
    p = Path(PROJECT) / ".research-agent" / "logs" / "arxiv_papers.jsonl"
    papers = [
        {"paper_id": "arxiv:2401.00001", "title": "Reward Shaping for Continuous Control",
         "abstract": "Novel reward shaping approach for continuous control.", "authors": ["A"], "published": "2024-01-15", "categories": ["cs.LG"]},
        {"paper_id": "arxiv:2401.00002", "title": "Safe RL with Constraints",
         "abstract": "Safety constraints in reinforcement learning.", "authors": ["B"], "published": "2024-02-20", "categories": ["cs.RO"]},
    ]
    with open(p, "w", encoding="utf-8") as f:
        for paper in papers:
            f.write(json.dumps(paper) + "\n")


def write_selected_papers():
    p = Path(PROJECT) / ".research-agent" / "logs" / "selected_reward_evidence.jsonl"
    papers = [
        {"paper_id": "arxiv:2401.00001", "title": "Reward Shaping for Continuous Control",
         "abstract": "Novel reward shaping approach.", "categories": ["reward shaping"], "relevance_score": 0.85},
    ]
    with open(p, "w", encoding="utf-8") as f:
        for paper in papers:
            f.write(json.dumps(paper) + "\n")


def force_phase(phase: str):
    """Force state phase without touching other fields."""
    with open(STATE_PATH, encoding="utf-8") as f:
        state = json.load(f)
    state["phase"] = phase
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def main():
    R: list[dict] = []

    # Clean start
    ra_dir = Path(PROJECT) / ".research-agent"
    if ra_dir.exists():
        shutil.rmtree(ra_dir)
    Path(PROJECT).mkdir(parents=True, exist_ok=True)
    (Path(PROJECT) / "main.py").write_text(
        'import math\ndef train(seed=42): return {"reward": 0.5+0.1*math.sin(seed)}\n'
        'def evaluate(seed=42):\n    r=train(seed); print(f"reward = {r[\'reward\']:.4f}"); print(f"loss = {0.1+0.01*seed:.4f}"); return r\n',
        encoding="utf-8",
    )

    # 1. init — creates phase=initialized
    R.append(run_cmd(["init", "--project", PROJECT]))
    setup_config()

    # 2. understand — advances to phase=understood
    R.append(run_cmd(["understand", "--project", PROJECT, "--json"], timeout=120))

    # 3. classify-task — advances to phase=classified
    R.append(run_cmd(["classify-task", "--json"], timeout=120))

    # 4. select-strategy — advances to phase=strategy_selected
    R.append(run_cmd(["select-strategy", "--json"]))

    # 5. plan-experiments — advances to phase=planned
    R.append(run_cmd(["plan-experiments", "--json"]))

    # 6. search-papers — should advance to phase=literature_searched
    # arxiv API may be slow/rate-limited, use 90s timeout
    R.append(run_cmd(["search-papers", "--json"], timeout=90))
    # If search-papers didn't find papers (arxiv rate limit), inject mock data
    papers_file = Path(PROJECT) / ".research-agent" / "logs" / "arxiv_papers.jsonl"
    n_papers = len(papers_file.read_text().strip().splitlines()) if papers_file.exists() else 0
    if n_papers == 0:
        write_mock_papers()
        if read_phase() == "planned":
            force_phase("literature_searched")
            with open(STATE_PATH, encoding="utf-8") as f:
                state = json.load(f)
            state["literature"]["arxiv_papers"] = "logs/arxiv_papers.jsonl"
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)

    # 7. classify-papers — advances to phase=literature_classified
    R.append(run_cmd(["classify-papers", "--json"], timeout=120))

    # 8. select-papers — advances to phase=literature_selected
    # LLM may be slow, use 180s timeout
    R.append(run_cmd(["select-papers", "--json"], timeout=180))
    # If select-papers didn't advance (timeout or no papers), force mock data
    if read_phase() == "literature_classified":
        write_selected_papers()
        force_phase("literature_selected")
        with open(STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
        state["literature"]["selected_evidence"] = "logs/selected_reward_evidence.jsonl"
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    # 9. extract-ideas — advances to phase=ideas_extracted
    R.append(run_cmd(["extract-ideas", "--json"], timeout=120))

    # 10. run-plan — advances through running_plan to completed
    R.append(run_cmd(["run-plan", "--json"], timeout=120))

    # 11. run --phase — reset to ideas_extracted, then run baseline
    force_phase("ideas_extracted")
    R.append(run_cmd(["run", "--phase", "baseline", "--json"], timeout=120))

    # 12. status
    R.append(run_cmd(["status", "--json"]))

    # === TABLE ===
    print("\n" + "=" * 140)
    print("CLI SMOKE TEST — ALL 12 COMMANDS")
    print("=" * 140)
    print(f"{'#':<3} {'Command':<30} {'Code':<6} {'Time':<8} {'JSON':<6} {'ok':<6} {'Phase':<22} {'stdout':<32} {'stderr':<32}")
    print("-" * 140)

    passed = failed = 0
    for i, r in enumerate(R, 1):
        p = r["code"] == 0 and r["json"]
        if p: passed += 1
        else: failed += 1
        mark = "PASS" if p else "FAIL"
        so = r["so"][:30]
        se = r["se"][:30]
        print(f"{i:<3} {r['cmd']:<30} {r['code']:<6} {r['t']:<8} {str(r['json']):<6} {str(r['ok']):<6} {r['phase']:<22} {so:<32} {se:<32}")

    print("-" * 140)
    print(f"TOTAL: {len(R)} | PASSED: {passed} | FAILED: {failed}")
    print("=" * 140)

    # CHECK 1: --json mode
    print("\n[CHECK 1] --json mode (stdout = pure JSON):")
    jf = 0
    for r in R:
        if "--json" in r["cmd"]:
            ok = r["json"]
            if not ok: jf += 1
            print(f"  {'PASS' if ok else 'FAIL'} {r['cmd']}")
    print(f"  Failures: {jf}")

    # CHECK 2: stderr on success
    print("\n[CHECK 2] stderr (no tracebacks on success):")
    tb_count = 0
    for r in R:
        if r["code"] == 0 and "Traceback" in r.get("se", ""):
            print(f"  WARN: {r['cmd']} has traceback in stderr")
            tb_count += 1
    if tb_count == 0:
        print("  All clean")

    # CHECK 3: classify-task timing
    ct = next((r for r in R if "classify-task" in r["cmd"]), None)
    if ct:
        print(f"\n[CHECK 3] classify-task: {ct['t']}s {'PASS (< 60s)' if ct['t'] < 60 else 'FAIL - LIKELY HANG'}")

    # CHECK 4: no silent failures
    print("\n[CHECK 4] Silent failures (exit 0 but ok=false):")
    sf = 0
    for r in R:
        if r["code"] == 0 and r["ok"] is False:
            print(f"  WARN: {r['cmd']}")
            sf += 1
    if sf == 0:
        print("  None")

    # CHECK 5: phase progression
    print("\n[CHECK 5] Phase progression:")
    phases_seen = [r["phase"] for r in R]
    print(f"  Phases: {' -> '.join(phases_seen)}")

    all_ok = failed == 0 and jf == 0
    print(f"\n{'='*140}")
    print(f"FINAL: {'ALL PASS' if all_ok else f'{failed} FAIL, {jf} JSON-FAIL'}")
    print(f"{'='*140}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
