"""
processors/freshness.py
========================
Classifies every Google Play app as fresh or legacy using a composite
signal system -- NOT a simple date check.

Each app accumulates legacy_signals (int). When signals >= threshold,
the app is excluded from trend analysis regardless of its release date.

Output:
  storage/processed/YYYY-MM-DD/fresh_candidates.json
  storage/processed/YYYY-MM-DD/legacy_excluded.json
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dateutil import parser as dateutil_parser

import config

logger = logging.getLogger(__name__)

FRESH_LABELS = frozenset(
    ["new_release", "new_release_with_traction", "recent_release", "establishing"]
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _parse_date(raw: str | None) -> date | None:
    """Parse a variety of date string formats into a date object."""
    if not raw:
        return None
    try:
        return dateutil_parser.parse(str(raw)).date()
    except Exception:
        return None


def _parse_installs(raw: str | int | None) -> int:
    """Convert install string like '1,000,000+' or int to int."""
    if isinstance(raw, int):
        return raw
    if not raw:
        return 0
    cleaned = str(raw).replace(",", "").replace("+", "").replace(" ", "")
    try:
        return int(cleaned)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Hard-override checks
# ---------------------------------------------------------------------------

_LEGACY_TITLE_RE = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in config.KNOWN_LEGACY_TITLE_PATTERNS
]


def _is_legacy_publisher(app_id: str) -> bool:
    """Return True if the appId prefix matches a known legacy publisher."""
    app_id_lower = (app_id or "").lower()
    return any(app_id_lower.startswith(pub) for pub in config.KNOWN_LEGACY_PUBLISHERS)


def _is_legacy_title(title: str) -> bool:
    """Return True if the title matches a known legacy title pattern."""
    t = (title or "").lower()
    return any(rx.search(t) for rx in _LEGACY_TITLE_RE)


# ---------------------------------------------------------------------------
# Per-app classifier
# ---------------------------------------------------------------------------

def classify_app(app: dict, today: date) -> dict:
    """
    Classify a single app dict. Adds freshness fields in-place.

    Fields added:
      freshness_label   : str
      freshness_score   : float
      legacy_signals    : int
      legacy_reasons    : list[str]
      released_days     : int | None
      ratings_count     : int
    """
    app_id: str = app.get("appId") or app.get("appid") or ""
    title: str = app.get("title") or ""
    ratings: int = int(app.get("ratings") or 0)
    installs: int = _parse_installs(app.get("installs") or app.get("installs_int"))

    # ── Step 1: Hard overrides ─────────────────────────────────────────────
    if _is_legacy_publisher(app_id):
        app.update({
            "freshness_label": "legacy",
            "freshness_score": 0.0,
            "legacy_signals": 99,
            "legacy_reasons": ["hard_override"],
            "released_days": None,
            "ratings_count": ratings,
        })
        return app

    if _is_legacy_title(title):
        app.update({
            "freshness_label": "legacy",
            "freshness_score": 0.0,
            "legacy_signals": 99,
            "legacy_reasons": ["hard_override_title"],
            "released_days": None,
            "ratings_count": ratings,
        })
        return app

    released_date = _parse_date(app.get("released"))
    if released_date is None:
        app.update({
            "freshness_label": "legacy",
            "freshness_score": 0.0,
            "legacy_signals": 99,
            "legacy_reasons": ["no_release_date"],
            "released_days": None,
            "ratings_count": ratings,
        })
        return app

    released_days: int = (today - released_date).days

    updated_date = _parse_date(app.get("updated"))
    lifespan_days: int = (
        (updated_date - released_date).days
        if updated_date and updated_date > released_date
        else released_days
    )

    # ── Step 2: Compute soft legacy signals ────────────────────────────────
    legacy_signals: int = 0
    legacy_reasons: list[str] = []

    # Signal A -- Old release date
    if released_days > config.LEGACY_AGE_DAYS_STRONG:
        legacy_signals += 3
        legacy_reasons.append(f"old_release:{released_days}d")
    elif released_days > config.LEGACY_AGE_DAYS_MODERATE:
        legacy_signals += 1
        legacy_reasons.append(f"aging:{released_days}d")

    # Signal B -- High rating count
    if ratings > config.LEGACY_RATINGS_HIGH:
        legacy_signals += 3
        legacy_reasons.append(f"high_ratings:{ratings}")
    elif ratings > config.LEGACY_RATINGS_MID:
        legacy_signals += 1
        legacy_reasons.append(f"mature_ratings:{ratings}")

    # Signal C -- Massive install base
    if installs > config.LEGACY_INSTALLS_MASSIVE:
        legacy_signals += 2
        legacy_reasons.append(f"massive_installs:{installs}")

    # Signal D -- Suspected re-upload
    if lifespan_days > config.LEGACY_AGE_DAYS_STRONG and released_days <= config.LEGACY_AGE_DAYS_MODERATE:
        legacy_signals += 2
        legacy_reasons.append("suspected_reupload")

    # ── Step 3: Threshold classification ──────────────────────────────────
    if legacy_signals >= config.LEGACY_SIGNAL_THRESHOLD:
        app.update({
            "freshness_label": "legacy",
            "freshness_score": 0.0,
            "legacy_signals": legacy_signals,
            "legacy_reasons": legacy_reasons,
            "released_days": released_days,
            "ratings_count": ratings,
        })
        return app

    if released_days <= config.FRESHNESS_NEW_DAYS:
        label, score = "new_release", 1.0
    elif released_days <= config.FRESHNESS_RECENT_DAYS:
        label, score = "recent_release", 0.7
    elif released_days <= config.FRESHNESS_ESTABLISHING:
        label, score = "establishing", 0.4
    else:
        label, score = "established", 0.2

    # ── Step 4: Traction bonus ─────────────────────────────────────────────
    if label == "new_release" and ratings > 1000:
        label = "new_release_with_traction"
        score = min(score + 0.2, 1.0)

    app.update({
        "freshness_label": label,
        "freshness_score": score,
        "legacy_signals": legacy_signals,
        "legacy_reasons": legacy_reasons,
        "released_days": released_days,
        "ratings_count": ratings,
    })
    return app


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process(today: date | None = None) -> dict:
    """
    Load google_play_raw.json, classify every app, split into fresh / legacy.

    Returns a summary dict; writes two JSON files to storage.
    """
    today = today or date.today()
    date_str = today.isoformat()

    raw_path = Path(config.RAW_DIR) / date_str / "google_play_raw.json"
    processed_dir = Path(config.PROCESSED_DIR) / date_str
    processed_dir.mkdir(parents=True, exist_ok=True)

    if not raw_path.exists():
        logger.error("[freshness] Raw file not found: %s", raw_path)
        return {"fresh": 0, "legacy": 0}

    with raw_path.open(encoding="utf-8") as f:
        raw = json.load(f)

    apps: list[dict] = raw.get("apps", [])
    logger.info("[freshness] Classifying %d apps", len(apps))

    fresh: list[dict] = []
    legacy: list[dict] = []

    for app in apps:
        classified = classify_app(app, today)
        if classified.get("freshness_label") in FRESH_LABELS:
            fresh.append(classified)
        else:
            legacy.append(classified)

    _atomic_write(processed_dir / "fresh_candidates.json", {
        "date": date_str,
        "count": len(fresh),
        "apps": fresh,
    })
    _atomic_write(processed_dir / "legacy_excluded.json", {
        "date": date_str,
        "count": len(legacy),
        "apps": legacy,
    })

    logger.info(
        "[freshness] Done. Fresh: %d, Legacy: %d", len(fresh), len(legacy)
    )
    return {"fresh": len(fresh), "legacy": len(legacy)}


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = process()
    print(result)
