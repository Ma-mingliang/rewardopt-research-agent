from __future__ import annotations

import sys
from pathlib import Path

import requests


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "research_agent" / "reward_paper_pool" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import collect_github  # noqa: E402


def test_github_client_returns_empty_response_on_network_error(monkeypatch):
    def fake_get(*args, **kwargs):
        raise requests.exceptions.SSLError("simulated ssl eof")

    monkeypatch.setattr(collect_github.requests, "get", fake_get)

    client = collect_github.GitHubRewardClient()
    code, data = client.get("/repos/example/project/readme")

    assert code == 0
    assert data is None
