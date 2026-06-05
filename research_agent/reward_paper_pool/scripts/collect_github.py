#!/usr/bin/env python3
"""Collect GitHub repositories related to RL reward design."""

from __future__ import annotations

import argparse
import base64
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import requests

from pool_common import extract_arxiv_ids, keyword_hits, load_dotenv, load_taxonomy, pool_path, write_jsonl


DEFAULT_QUERIES = [
    "reward shaping reinforcement learning",
    "potential based reward shaping",
    "Eureka reward generation",
    "LLM reward reinforcement learning",
    "residual reinforcement learning robot",
    "safe reinforcement learning reward",
    "curriculum reinforcement learning reward",
]

REWARD_PATH_HINTS = ("reward.py", "rewards", "envs", "tasks", "reward")
README_SIGNALS = ("reward", "shaping", "reinforcement learning", "paper", "arxiv", "citation", "bibtex")


class GitHubRewardClient:
    def __init__(self) -> None:
        load_dotenv()
        self.base_url = "https://api.github.com"
        self.token = os.environ.get("GITHUB_TOKEN", "") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "")
        self.headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"
        self.min_interval = 1.0 if self.token else 5.0

    def get(self, endpoint: str, params: Dict[str, Any] | None = None) -> Tuple[int, Any]:
        url = endpoint if endpoint.startswith("http") else f"{self.base_url}{endpoint}"
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=30)
        except requests.RequestException:
            return 0, None
        if resp.status_code == 200:
            return 200, resp.json()
        return resp.status_code, None


def search_repos(client: GitHubRewardClient, query: str, per_page: int = 30) -> List[Dict[str, Any]]:
    code, data = client.get(
        "/search/repositories",
        {"q": f'{query} in:name,description,readme', "sort": "stars", "order": "desc", "per_page": per_page},
    )
    if code != 200 or not data:
        return []
    return data.get("items", [])


def read_readme(client: GitHubRewardClient, full_name: str) -> str:
    code, data = client.get(f"/repos/{full_name}/readme")
    if code != 200 or not data:
        return ""
    encoded = data.get("content", "")
    try:
        return base64.b64decode(encoded).decode("utf-8", errors="replace")
    except Exception:
        return ""


def list_reward_paths(client: GitHubRewardClient, full_name: str) -> List[str]:
    code, data = client.get(f"/repos/{full_name}/contents")
    if code != 200 or not isinstance(data, list):
        return []
    paths = []
    for entry in data:
        name = (entry.get("name") or "").lower()
        path = entry.get("path") or name
        if any(hint in name for hint in REWARD_PATH_HINTS):
            paths.append(path)
    return paths[:20]


def infer_categories(repo: Dict[str, Any], readme: str, taxonomy: Dict[str, Any]) -> List[str]:
    text = " ".join([
        repo.get("full_name", ""),
        repo.get("description") or "",
        " ".join(repo.get("topics", []) or []),
        readme[:5000],
    ])
    scored = []
    for category, meta in taxonomy["categories"].items():
        hits = keyword_hits(text, meta.get("keywords", [])) + keyword_hits(text, meta.get("feature_signals", []))
        if hits:
            scored.append((category, len(hits)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [category for category, _ in scored[:3]]


def repo_quality_score(repo: Dict[str, Any], readme: str, reward_files: Iterable[str]) -> int:
    score = 0
    stars = int(repo.get("stargazers_count") or 0)
    if stars >= 5:
        score += 2
    text = ((repo.get("description") or "") + " " + readme[:5000]).lower()
    score += len(set(keyword_hits(text, README_SIGNALS)))
    if reward_files:
        score += 3
    if extract_arxiv_ids(readme):
        score += 3
    return score


def format_repo(repo: Dict[str, Any], readme: str, reward_files: List[str], categories: List[str]) -> Dict[str, Any]:
    full_name = repo.get("full_name", "")
    return {
        "repo": full_name,
        "url": repo.get("html_url") or f"https://github.com/{full_name}",
        "stars": int(repo.get("stargazers_count") or 0),
        "description": repo.get("description") or "",
        "readme": readme[:30000],
        "related_papers": [f"arxiv:{aid}" for aid in extract_arxiv_ids(readme)],
        "categories": categories,
        "has_reward_code": bool(reward_files),
        "reward_files": reward_files,
        "license": (repo.get("license") or {}).get("spdx_id") or "",
        "last_updated": (repo.get("pushed_at") or repo.get("updated_at") or "")[:10],
        "topics": repo.get("topics", []) or [],
        "source": "github",
    }


def run_collect(base_dir: Path | None = None, per_page: int = 30) -> List[Dict[str, Any]]:
    base = pool_path(base_dir)
    taxonomy = load_taxonomy(base)
    client = GitHubRewardClient()
    rows: Dict[str, Dict[str, Any]] = {}
    for query in DEFAULT_QUERIES:
        for repo in search_repos(client, query, per_page=per_page):
            full_name = repo.get("full_name", "")
            if not full_name or full_name in rows:
                continue
            readme = read_readme(client, full_name)
            reward_files = list_reward_paths(client, full_name)
            categories = infer_categories(repo, readme, taxonomy)
            if repo_quality_score(repo, readme, reward_files) < 3:
                continue
            rows[full_name] = format_repo(repo, readme, reward_files, categories)
            time.sleep(client.min_interval)
        time.sleep(client.min_interval)
    output = list(rows.values())
    write_jsonl(base / "raw" / "github_results.jsonl", output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-page", type=int, default=30)
    args = parser.parse_args()
    rows = run_collect(per_page=args.per_page)
    print(f"wrote {len(rows)} github rows")


if __name__ == "__main__":
    main()
