from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "research_agent" / "reward_paper_pool" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import normalize_papers  # noqa: E402
from pool_common import read_jsonl, write_jsonl  # noqa: E402


def test_normalize_skips_rows_without_required_paper_fields(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "taxonomy.yaml").write_text(
        """
categories:
  A_potential_based_reward:
    title: Potential-based reward shaping
    min_papers: 1
    keywords:
      - reward shaping
    feature_signals:
      - potential
""".lstrip(),
        encoding="utf-8",
    )
    write_jsonl(
        tmp_path / "raw" / "openreview_results.jsonl",
        [
            {
                "paper_id": "openreview:missing-abstract",
                "title": "Reward Shaping Placeholder",
                "abstract": "",
                "url": "https://openreview.net/forum?id=missing-abstract",
                "source": "openreview",
                "categories": ["A_potential_based_reward"],
            },
            {
                "paper_id": "openreview:valid",
                "title": "Reward Shaping With Evidence",
                "abstract": "A paper about potential reward shaping.",
                "url": "https://openreview.net/forum?id=valid",
                "source": "openreview",
                "categories": ["A_potential_based_reward"],
            },
        ],
    )
    write_jsonl(tmp_path / "raw" / "arxiv_results.jsonl", [{"source": "arxiv", "status": "partial_failure"}])
    write_jsonl(tmp_path / "raw" / "github_results.jsonl", [])

    normalize_papers.run_normalize(base_dir=tmp_path)

    rows = read_jsonl(tmp_path / "paper_pool.jsonl")
    assert [row["paper_id"] for row in rows] == ["openreview:valid"]
