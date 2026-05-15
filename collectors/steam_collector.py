"""
collectors/steam_collector.py
==============================
Collects game data from the SteamSpy public API (no API key required).

Endpoints used:
  - ?request=genre&genre=Casual       (top 100)
  - ?request=genre&genre=RPG          (top 100)
  - ?request=genre&genre=Strategy     (top 100)
  - ?request=top100in2weeks           (trending now)
  - ?request=top100forever            (legacy exclusion reference)

Output: storage/raw/YYYY-MM-DD/steam_raw.json
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

STEAMSPY_BASE = "https://steamspy.com/api.php"
REQUEST_TIMEOUT = 30  # seconds

GENRE_ENDPOINTS: list[str] = ["Casual", "RPG", "Strategy"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _parse_tags(tags_raw: Any) -> dict[str, int]:
    """SteamSpy tags field is {tag_name: vote_count}. Normalise safely."""
    if isinstance(tags_raw, dict):
        result: dict[str, int] = {}
        for k, v in tags_raw.items():
            try:
                result[str(k)] = int(v)
            except (TypeError, ValueError):
                pass
        return result
    return {}


def _serialize_app(app_id: str, data: dict) -> dict:
    return {
        "appid": app_id,
        "name": data.get("name"),
        "developer": data.get("developer"),
        "genre": data.get("genre"),
        "tags": _parse_tags(data.get("tags", {})),
        "positive": data.get("positive", 0),
        "negative": data.get("negative", 0),
        "average_forever": data.get("average_forever", 0),
        "owners": data.get("owners"),
        "price": data.get("price"),
    }


def _fetch_endpoint(params: dict) -> dict:
    """
    Call SteamSpy API with given params. Returns the JSON dict.
    Retries once on transient errors.
    """
    for attempt in range(2):
        try:
            resp = requests.get(
                STEAMSPY_BASE, params=params, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning(
                "SteamSpy request failed (attempt %d): %s", attempt + 1, exc
            )
            if attempt == 0:
                time.sleep(5)
    return {}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def collect(today: date | None = None) -> dict:
    """
    Collect Steam game data from SteamSpy.

    Returns a summary dict; writes raw JSON to storage.
    """
    today = today or date.today()
    date_str = today.isoformat()

    raw_dir = Path(config.RAW_DIR) / date_str
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / "steam_raw.json"

    logger.info("[steam] Starting SteamSpy collection for %s", date_str)

    genre_apps: dict[str, list[dict]] = {}
    trending: list[dict] = []
    legacy_ids: list[str] = []

    # ── Genre endpoints ───────────────────────────────────────────────────
    for genre in GENRE_ENDPOINTS:
        logger.info("[steam] Fetching genre: %s", genre)
        raw = _fetch_endpoint({"request": "genre", "genre": genre})
        apps = [_serialize_app(aid, d) for aid, d in raw.items()]
        genre_apps[genre] = apps
        logger.info("[steam] %s: %d apps", genre, len(apps))
        time.sleep(2)

    # ── Trending this week ────────────────────────────────────────────────
    logger.info("[steam] Fetching top100in2weeks")
    raw = _fetch_endpoint({"request": "top100in2weeks"})
    trending = [_serialize_app(aid, d) for aid, d in raw.items()]
    logger.info("[steam] top100in2weeks: %d apps", len(trending))
    time.sleep(2)

    # ── Legacy reference (top100forever) ─────────────────────────────────
    logger.info("[steam] Fetching top100forever (legacy reference)")
    raw = _fetch_endpoint({"request": "top100forever"})
    legacy_ids = list(raw.keys())
    logger.info("[steam] top100forever: %d app ids", len(legacy_ids))

    # ── Aggregate all tags for trend detection ────────────────────────────
    all_apps: list[dict] = []
    seen_ids: set[str] = set()
    for apps in genre_apps.values():
        for a in apps:
            if a["appid"] not in seen_ids:
                all_apps.append(a)
                seen_ids.add(a["appid"])
    for a in trending:
        if a["appid"] not in seen_ids:
            all_apps.append(a)
            seen_ids.add(a["appid"])

    # Aggregate tag vote counts across all apps
    tag_totals: dict[str, int] = {}
    for a in all_apps:
        for tag, votes in a.get("tags", {}).items():
            tag_totals[tag] = tag_totals.get(tag, 0) + votes

    top_tags = sorted(tag_totals.items(), key=lambda x: x[1], reverse=True)[:50]

    payload = {
        "date": date_str,
        "genre_apps": genre_apps,
        "trending": trending,
        "legacy_ids": legacy_ids,
        "all_apps": all_apps,
        "top_tags": top_tags,
        "total_unique_apps": len(all_apps),
    }

    _atomic_write(out_path, payload)
    logger.info(
        "[steam] Done. %d unique apps, %d tags written to %s",
        len(all_apps),
        len(top_tags),
        out_path,
    )
    return {
        "source": "steam",
        "apps_collected": len(all_apps),
        "top_tags_count": len(top_tags),
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import config as _cfg
    # Quick test: only 1 genre endpoint
    result = collect()
    print(result)
