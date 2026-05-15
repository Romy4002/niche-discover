"""
collectors/steam_collector.py
==============================
Collects game data from the SteamSpy public API (no API key required).

Tag strategy:
  - top100in2weeks gives us trending app IDs (no tags in bulk)
  - We fetch individual appdetails for up to TAG_SAMPLE_SIZE apps to get tags
  - This gives reliable mechanic/tag signal without excessive API calls

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
REQUEST_TIMEOUT = 30
GENRE_ENDPOINTS: list[str] = ["Casual", "RPG", "Strategy", "Action", "Indie"]

# Fetch appdetails for this many trending apps to build the tag signal
TAG_SAMPLE_SIZE = 80


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _parse_tags(tags_raw: Any) -> dict[str, int]:
    if isinstance(tags_raw, dict):
        result: dict[str, int] = {}
        for k, v in tags_raw.items():
            try:
                result[str(k)] = int(v)
            except (TypeError, ValueError):
                pass
        return result
    return {}


def _fetch_endpoint(params: dict, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            resp = requests.get(STEAMSPY_BASE, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            wait = 5 * (attempt + 1)
            logger.warning("SteamSpy request failed (attempt %d): %s", attempt + 1, exc)
            if attempt < retries - 1:
                time.sleep(wait)
    return {}


def _fetch_app_tags(appid: str) -> dict[str, int]:
    """Fetch full appdetails for a single app to get its tags."""
    data = _fetch_endpoint({"request": "appdetails", "appid": appid})
    return _parse_tags(data.get("tags", {}))


def _serialize_app(app_id: str, data: dict) -> dict:
    return {
        "appid": str(app_id),
        "name": data.get("name"),
        "developer": data.get("developer"),
        "genre": data.get("genre"),
        "tags": _parse_tags(data.get("tags", {})),
        "positive": data.get("positive", 0),
        "negative": data.get("negative", 0),
        "average_forever": data.get("average_forever", 0),
        "average_2weeks": data.get("average_2weeks", 0),
        "owners": data.get("owners"),
        "price": data.get("price"),
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def collect(today: date | None = None) -> dict:
    today = today or date.today()
    date_str = today.isoformat()

    raw_dir = Path(config.RAW_DIR) / date_str
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / "steam_raw.json"

    logger.info("[steam] Starting SteamSpy collection for %s", date_str)

    genre_apps: dict[str, list[dict]] = {}
    trending_ids: list[str] = []
    legacy_ids: list[str] = []

    # -- Genre endpoints (gives us app names + owner counts, no tags in bulk) --
    for genre in GENRE_ENDPOINTS:
        logger.info("[steam] Fetching genre: %s", genre)
        raw = _fetch_endpoint({"request": "genre", "genre": genre})
        apps = [_serialize_app(aid, d) for aid, d in raw.items()]
        genre_apps[genre] = apps
        logger.info("[steam] %s: %d apps", genre, len(apps))
        time.sleep(2)

    # -- Trending this week (IDs + basic info, no tags) --------------------
    logger.info("[steam] Fetching top100in2weeks")
    raw = _fetch_endpoint({"request": "top100in2weeks"})
    trending_raw = {aid: d for aid, d in raw.items()}
    trending_ids = list(trending_raw.keys())
    logger.info("[steam] top100in2weeks: %d apps", len(trending_ids))
    time.sleep(2)

    # -- Legacy reference --------------------------------------------------
    logger.info("[steam] Fetching top100forever (legacy reference)")
    raw = _fetch_endpoint({"request": "top100forever"})
    legacy_ids = list(raw.keys())
    logger.info("[steam] top100forever: %d app ids", len(legacy_ids))
    time.sleep(2)

    # -- Fetch individual appdetails for top trending to get TAGS ----------
    logger.info("[steam] Fetching appdetails for top %d trending apps (for tags)", TAG_SAMPLE_SIZE)
    tag_totals: dict[str, int] = {}
    detailed_apps: list[dict] = []

    for i, appid in enumerate(trending_ids[:TAG_SAMPLE_SIZE]):
        app_data = _fetch_endpoint({"request": "appdetails", "appid": appid})
        if app_data:
            app = _serialize_app(appid, app_data)
            detailed_apps.append(app)
            for tag, votes in app["tags"].items():
                tag_totals[tag] = tag_totals.get(tag, 0) + votes
        if (i + 1) % 10 == 0:
            logger.info("[steam] Fetched %d/%d appdetails", i + 1, min(len(trending_ids), TAG_SAMPLE_SIZE))
        time.sleep(1.2)  # SteamSpy rate limit: ~1 req/sec

    logger.info("[steam] Tag aggregation: %d unique tags from %d apps", len(tag_totals), len(detailed_apps))

    # -- Aggregate all app IDs for normalizer -------------------------------
    all_app_ids: set[str] = set()
    all_apps_basic: list[dict] = []
    seen: set[str] = set()

    for apps in genre_apps.values():
        for a in apps:
            if a["appid"] not in seen:
                all_apps_basic.append(a)
                seen.add(a["appid"])
    for a in detailed_apps:
        if a["appid"] not in seen:
            all_apps_basic.append(a)
            seen.add(a["appid"])
    for appid, d in trending_raw.items():
        if appid not in seen:
            all_apps_basic.append(_serialize_app(appid, d))
            seen.add(appid)

    top_tags = sorted(tag_totals.items(), key=lambda x: -x[1])[:50]

    payload = {
        "date": date_str,
        "genre_apps": {g: [a["appid"] for a in apps] for g, apps in genre_apps.items()},  # just IDs to save space
        "trending": detailed_apps,
        "legacy_ids": legacy_ids,
        "all_apps": all_apps_basic,
        "top_tags": top_tags,
        "total_unique_apps": len(seen),
    }

    _atomic_write(out_path, payload)
    logger.info(
        "[steam] Done. %d unique apps, %d top tags written to %s",
        len(seen), len(top_tags), out_path,
    )
    return {
        "source": "steam",
        "apps_collected": len(seen),
        "top_tags_count": len(top_tags),
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = collect()
    print(result)
