from __future__ import annotations

import sys
from pathlib import Path

import requests


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "research_agent" / "reward_paper_pool" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import collect_arxiv  # noqa: E402
from pool_common import read_jsonl  # noqa: E402


def test_arxiv_collector_continues_after_keyword_timeout(tmp_path, monkeypatch):
    (tmp_path / "raw").mkdir()
    (tmp_path / "taxonomy.yaml").write_text(
        """
categories:
  A_potential_based_reward:
    title: Potential-based reward shaping
    min_papers: 1
    keywords:
      - timeout query
      - working query
""".lstrip(),
        encoding="utf-8",
    )

    def fake_collect(category, query, max_results=30, start=0, timeout_seconds=45.0, client=None):
        if query == "timeout query":
            raise requests.ReadTimeout("simulated arxiv timeout")
        return [
            {
                "paper_id": "arxiv:2501.00001",
                "arxiv_id": "2501.00001",
                "title": "Working Reward Paper",
                "categories": [category],
                "matched_keywords": [query],
                "source": "arxiv",
            }
        ]

    monkeypatch.setattr(collect_arxiv, "collect_for_keyword", fake_collect)
    monkeypatch.setattr(collect_arxiv.time, "sleep", lambda _: None)

    rows = collect_arxiv.run_collect(base_dir=tmp_path, max_results=30, sleep_seconds=0)

    assert any(row.get("paper_id") == "arxiv:2501.00001" for row in rows)
    output_rows = read_jsonl(tmp_path / "raw" / "arxiv_results.jsonl")
    failure = next(row for row in output_rows if row.get("status") == "partial_failure")
    assert failure["errors"][0]["query"] == "timeout query"


def test_arxiv_collector_retries_rate_limit_after_retry_after(monkeypatch):
    attempts = 0
    slept = []

    def fake_collect(category, query, max_results=30, start=0, timeout_seconds=45.0, client=None):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            response = requests.Response()
            response.status_code = 429
            response.headers["Retry-After"] = "7"
            raise requests.HTTPError("rate limited", response=response)
        return [{"paper_id": "arxiv:2501.00002", "title": "Recovered"}]

    monkeypatch.setattr(collect_arxiv, "collect_for_keyword", fake_collect)
    monkeypatch.setattr(collect_arxiv.time, "sleep", slept.append)

    rows = collect_arxiv.collect_with_retries(
        "A_potential_based_reward",
        "rate limited",
        max_results=30,
        retries=1,
    )

    assert rows[0]["paper_id"] == "arxiv:2501.00002"
    assert slept == [7.0]


def test_arxiv_api_client_sets_user_agent_and_rate_limits():
    calls = []

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, params=None, timeout=None):
            calls.append((url, params, timeout, dict(self.headers)))
            response = requests.Response()
            response.status_code = 200
            response._content = b"<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'></feed>"
            return response

    times = iter([100.0, 101.0, 103.0])
    slept = []
    client = collect_arxiv.ArxivApiClient(
        delay_seconds=3.0,
        session=FakeSession(),
        now=lambda: next(times),
        sleep=slept.append,
    )

    client.get({"q": "first"}, timeout_seconds=10)
    client.get({"q": "second"}, timeout_seconds=10)

    assert "research-agent" in calls[0][3]["User-Agent"]
    assert slept == [2.0]


def test_arxiv_collector_flushes_partial_results_between_queries(tmp_path, monkeypatch):
    (tmp_path / "raw").mkdir()
    (tmp_path / "taxonomy.yaml").write_text(
        """
categories:
  A_potential_based_reward:
    title: Potential-based reward shaping
    min_papers: 10
    keywords:
      - first query
      - second query
""".lstrip(),
        encoding="utf-8",
    )
    writes = []

    def fake_collect(category, query, max_results=30, start=0, timeout_seconds=45.0, client=None):
        if query == "first query":
            return [
                {
                    "paper_id": "arxiv:2501.00003",
                    "arxiv_id": "2501.00003",
                    "title": "First Query Paper",
                    "categories": [category],
                    "matched_keywords": [query],
                    "source": "arxiv",
                }
            ]
        raise RuntimeError("stop after first")

    def fake_write(path, rows):
        writes.append(list(rows))

    monkeypatch.setattr(collect_arxiv, "collect_for_keyword", fake_collect)
    monkeypatch.setattr(collect_arxiv, "write_jsonl", fake_write)
    monkeypatch.setattr(collect_arxiv.time, "sleep", lambda _: None)

    collect_arxiv.run_collect(base_dir=tmp_path, max_results=30, sleep_seconds=0, retries=0)

    assert any(row.get("paper_id") == "arxiv:2501.00003" for row in writes[0])
