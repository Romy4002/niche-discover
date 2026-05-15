"""
processors/normalizer.py
=========================
Normalises data from all three sources (Google Play, Reddit, Steam)
into a unified schema for downstream analyzers.

unified_record = {
  "source"           : "google_play" | "reddit" | "steam",
  "id"               : str,
  "title"            : str,
  "description"      : str  (max 300 chars),
  "genre_tags"       : [str],
  "mechanic_tags"    : [str],
  "sentiment_score"  : float,  # 0-1, higher = more positive
  "engagement_signal": float,  # normalized installs/ratings/upvotes
  "date_signal"      : str,    # ISO date
  "freshness_label"  : str,
  "raw_ref"          : str,
}

Output: storage/processed/YYYY-MM-DD/unified_records.json
"""

from __future__ import annotations

import json
import logging
import re
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


def _norm_float(value: float, maximum: float) -> float:
    """Normalize a value to [0, 1] given an expected maximum."""
    if maximum <= 0:
        return 0.0
    return min(float(value) / maximum, 1.0)


# ---------------------------------------------------------------------------
# Google Play normalizer
# ---------------------------------------------------------------------------

def _normalize_play_app(app: dict) -> dict:
    score = float(app.get("score") or 0.0)
    sentiment = score / 5.0  # 0-5 star to 0-1

    ratings = int(app.get("ratings") or 0)
    engagement = _norm_float(ratings, 1_000_000)

    genre = app.get("genre") or ""
    genre_tags = [genre] if genre else []

    desc = (app.get("description") or "")[:300]

    released = app.get("released") or ""
    date_signal = str(released)[:10] if released else ""

    return {
        "source": "google_play",
        "id": app.get("appId", ""),
        "title": app.get("title", ""),
        "description": desc,
        "genre_tags": genre_tags,
        "mechanic_tags": [],  # populated by theme_extractor downstream
        "sentiment_score": round(sentiment, 4),
        "engagement_signal": round(engagement, 4),
        "date_signal": date_signal,
        "freshness_label": app.get("freshness_label", "unknown"),
        "raw_ref": f"google_play:{app.get('appId', '')}",
    }


# ---------------------------------------------------------------------------
# Reddit normalizer
# ---------------------------------------------------------------------------

# Matches "Game Title" or Game Title (2-4 capitalised words)
_QUOTED_RE = re.compile(r'"([^"]{3,60})"')
_CAPS_PHRASE_RE = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b')


def _extract_game_titles_from_reddit(
    post: dict, play_titles: set[str]
) -> list[str]:
    """
    Heuristically extract game titles mentioned in a Reddit post.
    Strategy:
      1. Quoted phrases in title/selftext
      2. Flair label (often a game name)
      3. Capitalised 2-4 word phrases that also appear in the Play Store list
    """
    text = (post.get("title") or "") + " " + (post.get("selftext") or "")
    found: list[str] = []

    # Quoted titles
    for m in _QUOTED_RE.finditer(text):
        found.append(m.group(1).strip())

    # Flair
    flair = post.get("flair")
    if flair and len(flair) > 2:
        found.append(flair)

    # Capitalised phrases cross-referenced with Play Store titles
    for m in _CAPS_PHRASE_RE.finditer(text):
        phrase = m.group(1)
        if phrase.lower() in play_titles:
            found.append(phrase)

    return list(dict.fromkeys(found))  # deduplicate preserving order


def _normalize_reddit_post(post: dict, play_titles: set[str]) -> dict:
    score = int(post.get("score") or 0)
    num_comments = int(post.get("num_comments") or 0)
    engagement = _norm_float(score + num_comments * 2, 5000)

    mentions = _extract_game_titles_from_reddit(post, play_titles)
    genre_tags = [post.get("flair")] if post.get("flair") else []
    genre_tags = [g for g in genre_tags if g]

    desc = ((post.get("title") or "") + " " + (post.get("selftext") or ""))[:300]
    date_signal = (post.get("created_utc") or "")[:10]

    return {
        "source": "reddit",
        "id": post.get("id", ""),
        "title": post.get("title", ""),
        "description": desc,
        "genre_tags": genre_tags,
        "mechanic_tags": [],
        "sentiment_score": 0.5,  # neutral baseline; complaint_parser refines
        "engagement_signal": round(engagement, 4),
        "date_signal": date_signal,
        "freshness_label": "n/a",
        "raw_ref": f"reddit:{post.get('subreddit', '')}:{post.get('id', '')}",
        "_mentioned_titles": mentions,  # internal use by niche_detector
    }


# ---------------------------------------------------------------------------
# Steam normalizer
# ---------------------------------------------------------------------------

def _normalize_steam_app(app: dict) -> dict:
    pos = int(app.get("positive") or 0)
    neg = int(app.get("negative") or 0)
    total = pos + neg
    sentiment = (pos / total) if total > 0 else 0.5

    engagement = _norm_float(
        app.get("average_forever") or 0, 10_000
    )

    tags = list((app.get("tags") or {}).keys())
    genre = app.get("genre") or ""
    genre_tags = [genre] if genre else []

    return {
        "source": "steam",
        "id": str(app.get("appid", "")),
        "title": app.get("name", ""),
        "description": "",
        "genre_tags": genre_tags,
        "mechanic_tags": tags[:20],  # top 20 tags as mechanic signals
        "sentiment_score": round(sentiment, 4),
        "engagement_signal": round(engagement, 4),
        "date_signal": "",
        "freshness_label": "n/a",
        "raw_ref": f"steam:{app.get('appid', '')}",
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process(today: date | None = None) -> dict:
    """
    Load raw data from all three sources, normalize into unified records.

    Returns summary dict; writes unified_records.json to storage.
    """
    today = today or date.today()
    date_str = today.isoformat()

    raw_dir = Path(config.RAW_DIR) / date_str
    proc_dir = Path(config.PROCESSED_DIR) / date_str
    proc_dir.mkdir(parents=True, exist_ok=True)

    unified: list[dict] = []

    # ── Google Play (use fresh_candidates only) ────────────────────────────
    fresh_path = proc_dir / "fresh_candidates.json"
    play_titles: set[str] = set()
    if fresh_path.exists():
        with fresh_path.open(encoding="utf-8") as f:
            fresh_data = json.load(f)
        apps = fresh_data.get("apps", [])
        for app in apps:
            unified.append(_normalize_play_app(app))
            t = (app.get("title") or "").lower()
            if t:
                play_titles.add(t)
        logger.info("[normalizer] Google Play: %d fresh apps normalized", len(apps))
    else:
        logger.warning("[normalizer] fresh_candidates.json not found — skipping Play data")

    # ── Reddit ────────────────────────────────────────────────────────────
    reddit_path = raw_dir / "reddit_raw.json"
    if reddit_path.exists():
        with reddit_path.open(encoding="utf-8") as f:
            reddit_data = json.load(f)
        posts = reddit_data.get("posts", [])
        for post in posts:
            unified.append(_normalize_reddit_post(post, play_titles))
        logger.info("[normalizer] Reddit: %d posts normalized", len(posts))
    else:
        logger.warning("[normalizer] reddit_raw.json not found — skipping Reddit data")

    # ── Steam ─────────────────────────────────────────────────────────────
    steam_path = raw_dir / "steam_raw.json"
    if steam_path.exists():
        with steam_path.open(encoding="utf-8") as f:
            steam_data = json.load(f)
        all_apps = steam_data.get("all_apps", [])
        for app in all_apps:
            unified.append(_normalize_steam_app(app))
        logger.info("[normalizer] Steam: %d apps normalized", len(all_apps))
    else:
        logger.warning("[normalizer] steam_raw.json not found — skipping Steam data")

    _atomic_write(proc_dir / "unified_records.json", {
        "date": date_str,
        "total": len(unified),
        "records": unified,
    })

    logger.info("[normalizer] Done. %d unified records written", len(unified))
    return {
        "total_unified": len(unified),
        "play_titles_indexed": len(play_titles),
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = process()
    print(result)
