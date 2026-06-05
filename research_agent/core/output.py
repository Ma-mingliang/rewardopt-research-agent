"""JSON protocol output helpers for front agent communication."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def ok_response(data: dict[str, Any]) -> dict:
    """Wrap data in a success envelope."""
    return {"ok": True, "timestamp": _now_iso(), **data}


def error_response(error_code: str, message: str, next_action: str = "") -> dict:
    """Wrap error in a standard error envelope."""
    resp = {
        "ok": False,
        "error_code": error_code,
        "message": message,
        "timestamp": _now_iso(),
    }
    if next_action:
        resp["next_action"] = next_action
    return resp


def write_json_report(path: Path, data: dict) -> None:
    """Write a JSON report file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def write_markdown_report(path: Path, content: str) -> None:
    """Write a Markdown report file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def print_json(data: dict, file=None) -> None:
    """Print JSON to stdout."""
    json.dump(data, file or sys.stdout, indent=2, ensure_ascii=False)
    print(file=file or sys.stdout)


def append_jsonl(path: Path, data: dict) -> None:
    """Append a JSON line to a .jsonl file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        f.write("\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
