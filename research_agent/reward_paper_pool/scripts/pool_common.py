#!/usr/bin/env python3
"""Shared utilities for Reward Function Paper Pool V1."""

from __future__ import annotations

import hashlib
import json
import os
import re
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
ARXIV_ID_RE = re.compile(r"(?:arxiv:|arxiv\.org/(?:abs|pdf)/)?(\d{4}\.\d{4,5})(?:v\d+)?", re.I)


HRLL_LAYERS = ["lqr_residual", "stanley_residual", "balance_control", "path_tracking", "safety_gate"]


def load_dotenv() -> None:
    for path in (Path.home() / ".hermes" / ".env", REPO_ROOT / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def pool_path(base_dir: Optional[Path] = None) -> Path:
    return Path(base_dir) if base_dir is not None else ROOT


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)


def load_taxonomy(base_dir: Optional[Path] = None) -> Dict[str, Any]:
    base = pool_path(base_dir)
    path = base / "taxonomy.yaml"
    if not path.exists():
        path = ROOT / "taxonomy.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_title(title: str) -> str:
    text = (title or "").lower().replace("-", " ")
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def title_hash(title: str) -> str:
    return hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()[:12]


def canonical_arxiv_id(value: str) -> str:
    match = ARXIV_ID_RE.search(value or "")
    return match.group(1) if match else ""


def paper_key(row: Dict[str, Any]) -> str:
    arxiv_id = canonical_arxiv_id(row.get("arxiv_id", "") or row.get("paper_id", "") or row.get("url", ""))
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    return f"title:{title_hash(row.get('title', ''))}"


def extract_arxiv_ids(text: str) -> List[str]:
    seen = []
    for match in ARXIV_ID_RE.finditer(text or ""):
        arxiv_id = match.group(1)
        if arxiv_id not in seen:
            seen.append(arxiv_id)
    return seen


def parse_year(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    text = str(value or "")
    match = re.search(r"(19|20)\d{2}", text)
    return int(match.group(0)) if match else None


def keyword_hits(text: str, keywords: Iterable[str]) -> List[str]:
    hay = (text or "").lower().replace("-", " ")
    hits = []
    for keyword in keywords:
        kw = str(keyword or "").lower()
        if not kw:
            continue
        forms = {kw, kw.replace("-", " ")}
        if any(form in hay for form in forms):
            hits.append(keyword)
    return hits


def classify_text(text: str, taxonomy: Dict[str, Any]) -> Dict[str, int]:
    scores: Dict[str, int] = {}
    for category, meta in taxonomy.get("categories", {}).items():
        kw_hits = keyword_hits(text, meta.get("keywords", []))
        sig_hits = keyword_hits(text, meta.get("feature_signals", []))
        if kw_hits or sig_hits:
            scores[category] = len(kw_hits) * 2 + len(sig_hits)
    return scores


def empty_hrll_relevance() -> Dict[str, float]:
    return {layer: 0.0 for layer in HRLL_LAYERS}


def infer_hrll_relevance(text: str, categories: Iterable[str]) -> Dict[str, float]:
    lower = (text or "").lower()
    cats = set(categories or [])
    result = empty_hrll_relevance()
    if "F_residual_aware_reward" in cats or "residual" in lower:
        result["lqr_residual"] = 0.9 if "lqr" in lower else 0.75
        result["stanley_residual"] = 0.85 if "tracking" in lower or "path" in lower else 0.65
    if "tracking" in lower or "path" in lower or "navigation" in lower:
        result["path_tracking"] = max(result["path_tracking"], 0.75)
        result["stanley_residual"] = max(result["stanley_residual"], 0.6)
    if "balance" in lower or "fall" in lower:
        result["balance_control"] = 0.75
    if "B_safety_constraint_reward" in cats or "safety" in lower or "barrier" in lower:
        result["safety_gate"] = 0.85
    return result


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 3] + "..."
