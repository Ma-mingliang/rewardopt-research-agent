"""Load method pool from JSONL."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from research_agent.reward_methods.schema import RewardMethodRecord

logger = logging.getLogger(__name__)


def load_method_pool(pool_path: Path) -> list[RewardMethodRecord]:
    """Load method_pool.jsonl into a list of RewardMethodRecord.

    Skips blank lines and JSON parse errors.
    Returns empty list if file does not exist.
    """
    if not pool_path.exists():
        logger.warning("Method pool file not found: %s", pool_path)
        return []

    records: list[RewardMethodRecord] = []
    with open(pool_path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping invalid JSON at line %d in %s", lineno, pool_path)
                continue
            if not d.get("method_id"):
                logger.warning("Skipping record with empty method_id at line %d", lineno)
                continue
            records.append(RewardMethodRecord.from_dict(d))

    logger.info("Loaded %d methods from %s", len(records), pool_path)
    return records
