"""
analyzers/complaint_parser.py
==============================
Scans Reddit posts and comments for recurring complaint and praise phrases.
Groups results by theme: monetization | gameplay | technical | content.

Output: storage/processed/YYYY-MM-DD/complaints.json
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        logger.warning("[complaint_parser] File not found: %s", path)
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _scan_text(text: str, phrases: dict[str, str]) -> dict[str, int]:
    """
    Count occurrences of each phrase in text (case-insensitive).
    Returns {phrase: count}.
    """
    text_lower = text.lower()
    counts: dict[str, int] = {}
    for phrase in phrases:
        count = text_lower.count(phrase)
        if count > 0:
            counts[phrase] = count
    return counts


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process(today: date | None = None) -> dict:
    """
    Scan all Reddit posts + comments for complaint and praise signals.

    Returns the analysis dict; writes complaints.json to storage.
    """
    today = today or date.today()
    date_str = today.isoformat()

    raw_dir = Path(config.RAW_DIR) / date_str
    proc_dir = Path(config.PROCESSED_DIR) / date_str
    proc_dir.mkdir(parents=True, exist_ok=True)

    reddit_data = _load_json(raw_dir / "reddit_raw.json")
    if not reddit_data:
        logger.error("[complaint_parser] No Reddit data available")
        empty = {
            "date": date_str,
            "top_complaints": [],
            "top_praises": [],
            "monetization_sentiment": 0.0,
            "content_sentiment": 0.0,
        }
        _atomic_write(proc_dir / "complaints.json", empty)
        return empty

    # ── Aggregate all text ────────────────────────────────────────────────
    all_text_chunks: list[str] = []
    for post in reddit_data.get("posts", []):
        all_text_chunks.append((post.get("title") or ""))
        all_text_chunks.append((post.get("selftext") or ""))
        for comment in post.get("comments", []):
            all_text_chunks.append((comment.get("body") or ""))

    full_text = " ".join(all_text_chunks)
    logger.info(
        "[complaint_parser] Scanning %d chars across %d posts",
        len(full_text),
        len(reddit_data.get("posts", [])),
    )

    # ── Count complaints ──────────────────────────────────────────────────
    complaint_totals: dict[str, int] = {}
    for phrase in config.COMPLAINT_PHRASES:
        count = full_text.lower().count(phrase)
        if count > 0:
            complaint_totals[phrase] = count

    # ── Count praises ─────────────────────────────────────────────────────
    praise_totals: dict[str, int] = {}
    for phrase in config.PRAISE_PHRASES:
        count = full_text.lower().count(phrase)
        if count > 0:
            praise_totals[phrase] = count

    # ── Build sorted output lists ─────────────────────────────────────────
    top_complaints = sorted(
        [
            (phrase, count, config.COMPLAINT_PHRASES[phrase])
            for phrase, count in complaint_totals.items()
        ],
        key=lambda x: -x[1],
    )

    top_praises = sorted(
        [
            (phrase, count, config.PRAISE_PHRASES[phrase])
            for phrase, count in praise_totals.items()
        ],
        key=lambda x: -x[1],
    )

    # ── Sentiment scores by category ──────────────────────────────────────
    def _category_sentiment(
        complaints: list[tuple], praises: list[tuple], category: str
    ) -> float:
        """Returns -1 to +1 sentiment for a category."""
        neg = sum(c for _, c, cat in complaints if cat == category)
        pos = sum(c for _, c, cat in praises if cat == category)
        total = neg + pos
        if total == 0:
            return 0.0
        return round((pos - neg) / total, 4)

    monetization_sentiment = _category_sentiment(top_complaints, top_praises, "monetization")
    content_sentiment = _category_sentiment(top_complaints, top_praises, "content")

    result = {
        "date": date_str,
        "top_complaints": top_complaints[:20],  # serialise as list of [phrase, count, theme]
        "top_praises": top_praises[:10],
        "monetization_sentiment": monetization_sentiment,
        "content_sentiment": content_sentiment,
    }

    _atomic_write(proc_dir / "complaints.json", result)
    logger.info(
        "[complaint_parser] Done. %d complaints, %d praises. Monetization sentiment: %.2f",
        len(top_complaints),
        len(top_praises),
        monetization_sentiment,
    )
    return {
        "complaints_found": len(top_complaints),
        "praises_found": len(top_praises),
        "monetization_sentiment": monetization_sentiment,
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = process()
    print(result)
