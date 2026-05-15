"""
analyzers/trend_scorer.py
==========================
Scores every fresh candidate app using a cross-source corroboration formula.

Score components:
  base                  = freshness_score * 10
  Reddit corroboration  = +3 per mention, cap +15
  Steam mechanic overlap= +4 if mechanic_tags overlap trending Steam tags
  Early traction        = +2 (ratings > 500 AND released_days < 180)
  Multi-chart presence  = +2 (app in 2+ Play Store category charts)
  Trends boost          = +5 rising / +3 new_signal / -4 declining

Top 20 apps by score become trending_candidates.

Output: storage/processed/YYYY-MM-DD/trend_scores.json
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


def _load_json(path: Path) -> dict | list | None:
    if not path.exists():
        logger.warning("[trend_scorer] File not found: %s", path)
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

def _compute_score(
    app: dict,
    reddit_title_counts: dict[str, int],
    steam_trending_tags: set[str],
    trends_validation: dict[str, dict],
) -> float:
    """Compute the trend score for a single app."""

    score = float(app.get("freshness_score", 0.0)) * 10

    # ── Reddit corroboration ──────────────────────────────────────────────
    title_lower = (app.get("title") or "").lower()
    genre_lower = (app.get("genre") or "").lower()
    reddit_hits = reddit_title_counts.get(title_lower, 0) + reddit_title_counts.get(genre_lower, 0)
    reddit_bonus = min(reddit_hits * config.TREND_REDDIT_POINTS_PER_MENTION, config.TREND_REDDIT_CAP)
    score += reddit_bonus

    # ── Steam mechanic overlap ────────────────────────────────────────────
    mechanic_tags = {t.lower() for t in (app.get("mechanic_tags") or [])}
    if mechanic_tags & steam_trending_tags:
        score += config.TREND_STEAM_MECHANIC_BONUS

    # ── Early traction ────────────────────────────────────────────────────
    ratings = int(app.get("ratings_count") or app.get("ratings") or 0)
    released_days = app.get("released_days") or 9999
    if ratings > config.TREND_TRACTION_MIN_RATINGS and released_days < config.TREND_TRACTION_MAX_DAYS:
        score += config.TREND_EARLY_TRACTION_BONUS

    # ── Multi-chart presence ──────────────────────────────────────────────
    chart_count = int(app.get("chart_count") or 0)
    if chart_count >= 2:
        score += config.TREND_MULTI_CHART_BONUS

    # ── Trends boost ──────────────────────────────────────────────────────
    if trends_validation:
        # Look up by title, partial match
        direction = None
        for term, tdata in trends_validation.items():
            if term.lower() in title_lower or title_lower in term.lower():
                direction = tdata.get("direction")
                break
        if direction == "rising":
            score += config.TREND_RISING_BONUS
        elif direction == "new_signal":
            score += config.TREND_NEW_SIGNAL_BONUS
        elif direction == "declining":
            score += config.TREND_DECLINING_PENALTY

    return round(score, 4)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process(today: date | None = None) -> dict:
    """
    Score all fresh candidates and rank the top TREND_TOP_N.

    Designed to be called twice:
      - First pass: before trends validation (trends_validation may be empty)
      - Second pass: after niche_detector has run trends Pass 2

    Returns summary dict; writes trend_scores.json.
    """
    today = today or date.today()
    date_str = today.isoformat()

    proc_dir = Path(config.PROCESSED_DIR) / date_str
    proc_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = Path(config.RAW_DIR) / date_str

    # ── Load fresh candidates ─────────────────────────────────────────────
    fresh_data = _load_json(proc_dir / "fresh_candidates.json")
    apps: list[dict] = (fresh_data or {}).get("apps", [])
    if not apps:
        logger.warning("[trend_scorer] No fresh candidates found")
        result = {"date": date_str, "trending_candidates": []}
        _atomic_write(proc_dir / "trend_scores.json", result)
        return result

    # ── Build Reddit mention counts ───────────────────────────────────────
    reddit_data = _load_json(raw_dir / "reddit_raw.json")
    reddit_title_counts: dict[str, int] = {}
    if reddit_data:
        for post in reddit_data.get("posts", []):
            text = (
                (post.get("title") or "") + " " + (post.get("selftext") or "")
            ).lower()
            # Count each app title/genre mention
            for token in text.split():
                reddit_title_counts[token] = reddit_title_counts.get(token, 0) + 1

    # ── Build Steam trending tag set ──────────────────────────────────────
    steam_data = _load_json(raw_dir / "steam_raw.json")
    steam_trending_tags: set[str] = set()
    if steam_data:
        for tag, _ in (steam_data.get("top_tags") or [])[:30]:
            steam_trending_tags.add(str(tag).lower())

    # ── Load trends validation (may not exist on first pass) ─────────────
    trends_validation: dict[str, dict] = {}
    tv_path = proc_dir / "trends_validation.json"
    if tv_path.exists():
        tv_data = _load_json(tv_path)
        if tv_data:
            trends_validation = tv_data.get("results", {})

    # ── Score every fresh app ─────────────────────────────────────────────
    scored: list[dict] = []
    for app in apps:
        s = _compute_score(app, reddit_title_counts, steam_trending_tags, trends_validation)
        entry = {
            "appId": app.get("appId") or app.get("id"),
            "title": app.get("title"),
            "genre": app.get("genre"),
            "freshness_label": app.get("freshness_label"),
            "freshness_score": app.get("freshness_score"),
            "released_days": app.get("released_days"),
            "ratings_count": app.get("ratings_count") or app.get("ratings"),
            "chart_count": app.get("chart_count", 0),
            "trend_score": s,
            "trends_direction": None,  # filled below if data available
        }
        # Attach trends direction for reporting
        title_lower = (app.get("title") or "").lower()
        for term, tdata in trends_validation.items():
            if term.lower() in title_lower or title_lower in term.lower():
                entry["trends_direction"] = tdata.get("direction")
                break
        scored.append(entry)

    scored.sort(key=lambda x: x["trend_score"], reverse=True)
    trending_candidates = scored[: config.TREND_TOP_N]

    result = {
        "date": date_str,
        "total_scored": len(scored),
        "trending_candidates": trending_candidates,
    }
    _atomic_write(proc_dir / "trend_scores.json", result)

    logger.info(
        "[trend_scorer] Done. Top score: %.1f (%s), total scored: %d",
        trending_candidates[0]["trend_score"] if trending_candidates else 0,
        trending_candidates[0]["title"] if trending_candidates else "n/a",
        len(scored),
    )
    return {
        "total_scored": len(scored),
        "top_score": trending_candidates[0]["trend_score"] if trending_candidates else 0,
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = process()
    print(result)
