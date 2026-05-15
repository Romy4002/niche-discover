"""
collectors/google_play.py
=========================
Collects mobile game data from Google Play using the google-play-scraper library.

Two collection passes:
  1. Chart discovery  -- top 50 "new" and "top" results per category
  2. App details      -- full metadata for each discovered appId

Output: storage/raw/YYYY-MM-DD/google_play_raw.json
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date
from pathlib import Path
from typing import Any

from google_play_scraper import app as gps_app
from google_play_scraper import search
from google_play_scraper.exceptions import NotFoundError

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: Any) -> None:
    """Write JSON atomically via a .tmp file then rename."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _parse_installs(raw: str | None) -> int:
    """Convert Play Store install string like '1,000,000+' to int."""
    if not raw:
        return 0
    cleaned = raw.replace(",", "").replace("+", "").replace(" ", "")
    try:
        return int(cleaned)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------

def _search_category(category: str, n: int = 50) -> list[str]:
    """
    Return up to n appIds for a given category string via search.
    google-play-scraper has no native category-chart endpoint, so we
    use broad keyword searches per category which approximate chart data.
    """
    app_ids: list[str] = []
    try:
        results = search(
            category,
            n_hits=n,
            country="us",
            lang="en",
        )
        for r in results:
            if isinstance(r, dict) and r.get("appId"):
                app_ids.append(r["appId"])
    except Exception as exc:
        logger.warning("Search failed for category '%s': %s", category, exc)
    return app_ids


def _fetch_app_details(app_id: str) -> dict | None:
    """Fetch full app details for a single appId. Returns None on failure."""
    try:
        detail = gps_app(app_id, country="us", lang="en")
        return {
            "appId": detail.get("appId"),
            "title": detail.get("title"),
            "genre": detail.get("genre"),
            "score": detail.get("score"),
            "ratings": detail.get("ratings"),
            "installs": detail.get("installs"),
            "installs_int": _parse_installs(detail.get("installs")),
            "description": (detail.get("description") or "")[:500],
            "released": str(detail.get("released") or ""),
            "updated": str(detail.get("updated") or ""),
            "developer": detail.get("developer"),
            "developerId": detail.get("developerId"),
            "price": detail.get("price"),
            "free": detail.get("free"),
            "contentRating": detail.get("contentRating"),
            "url": detail.get("url"),
        }
    except NotFoundError:
        logger.debug("App not found: %s", app_id)
        return None
    except Exception as exc:
        logger.warning("Failed to fetch details for %s: %s", app_id, exc)
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def collect(today: date | None = None) -> dict:
    """
    Run the full Google Play collection pass.

    Returns a summary dict with counts; writes raw JSON to storage.
    """
    today = today or date.today()
    date_str = today.isoformat()

    raw_dir = Path(config.RAW_DIR) / date_str
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / "google_play_raw.json"

    logger.info("[google_play] Starting collection for %s", date_str)

    # ── Pass 1: discover appIds across all categories ──────────────────────
    seen: set[str] = set()
    chart_membership: dict[str, list[str]] = {}  # appId -> list of categories

    for category in config.GOOGLE_PLAY_CATEGORIES:
        logger.info("[google_play] Searching category: %s", category)
        ids = _search_category(category, n=config.GOOGLE_PLAY_RESULTS_PER_CATEGORY)
        for aid in ids:
            chart_membership.setdefault(aid, []).append(category)
            seen.add(aid)
        time.sleep(0.5)  # gentle pacing

    logger.info("[google_play] Discovered %d unique appIds", len(seen))

    # ── Pass 2: fetch full details ─────────────────────────────────────────
    apps: list[dict] = []
    for i, app_id in enumerate(seen):
        detail = _fetch_app_details(app_id)
        if detail:
            detail["chart_categories"] = chart_membership.get(app_id, [])
            detail["chart_count"] = len(chart_membership.get(app_id, []))
            apps.append(detail)
        if (i + 1) % 25 == 0:
            logger.info("[google_play] Fetched %d/%d app details", i + 1, len(seen))
            time.sleep(1)

    payload = {
        "date": date_str,
        "total_discovered": len(seen),
        "total_fetched": len(apps),
        "apps": apps,
    }

    _atomic_write(out_path, payload)
    logger.info(
        "[google_play] Done. %d apps written to %s", len(apps), out_path
    )
    return {"source": "google_play", "apps_collected": len(apps)}


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Quick test: 1 category, 10 results
    import config as _cfg
    _cfg.GOOGLE_PLAY_CATEGORIES = ["puzzle"]
    _cfg.GOOGLE_PLAY_RESULTS_PER_CATEGORY = 10
    result = collect()
    print(result)
