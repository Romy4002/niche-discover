"""
analyzers/history_diff.py
==========================
Compares today's signals against a rolling 30-day master history
to detect newly emerging apps and accelerating themes.

Master files (created if missing, git-tracked):
  storage/master/app_history.json
  storage/master/theme_history.json

Format:
  app_history.json:
    {appId: {date: str, score: float, title: str, ...}}
  theme_history.json:
    {theme: [{date: str, score: float}, ...]}   # up to 30 entries

Output: storage/processed/YYYY-MM-DD/history_diff.json
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
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


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("[history_diff] Failed to load %s: %s", path, exc)
        return default


def _cutoff_date(today: date) -> str:
    return (today - timedelta(days=config.HISTORY_WINDOW_DAYS)).isoformat()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process(today: date | None = None) -> dict:
    """
    Diff today's trend_scores and themes against master history.
    Update master history with today's data (rolling 30-day window).

    Returns diff summary dict; writes history_diff.json to storage.
    """
    today = today or date.today()
    date_str = today.isoformat()
    cutoff = _cutoff_date(today)

    master_dir = Path(config.MASTER_DIR)
    master_dir.mkdir(parents=True, exist_ok=True)
    proc_dir = Path(config.PROCESSED_DIR) / date_str
    proc_dir.mkdir(parents=True, exist_ok=True)

    app_hist_path = master_dir / "app_history.json"
    theme_hist_path = master_dir / "theme_history.json"

    # ── Load master histories ──────────────────────────────────────────────
    # app_history: {appId: {date, score, title}}
    app_history: dict[str, dict] = _load_json(app_hist_path, default={})
    # theme_history: {theme: [{date, score}]}
    theme_history: dict[str, list[dict]] = _load_json(theme_hist_path, default={})

    # ── Load today's data ──────────────────────────────────────────────────
    trend_data = _load_json(proc_dir / "trend_scores.json")
    today_candidates: list[dict] = (trend_data or {}).get("trending_candidates", [])

    theme_data = _load_json(proc_dir / "themes.json")
    today_bigrams: list[tuple] = (theme_data or {}).get("top_bigrams", [])

    # ── Diff apps ──────────────────────────────────────────────────────────
    newly_detected: list[dict] = []
    accelerating_apps: list[dict] = []
    recurring_apps: list[dict] = []

    for app in today_candidates:
        app_id = app.get("appId") or app.get("id") or app.get("title", "")
        score_today = float(app.get("trend_score") or 0)

        if app_id in app_history:
            prev = app_history[app_id]
            score_7d_ago = float(prev.get("score", 0))
            velocity = round(score_today - score_7d_ago, 4)
            entry = {
                **app,
                "status": "recurring",
                "score_7d_ago": score_7d_ago,
                "trend_velocity": velocity,
            }
            recurring_apps.append(entry)
            if velocity > 0:
                accelerating_apps.append(entry)
        else:
            entry = {**app, "status": "newly_detected", "score_7d_ago": 0, "trend_velocity": score_today}
            newly_detected.append(entry)

        # Update history
        app_history[app_id] = {
            "date": date_str,
            "score": score_today,
            "title": app.get("title"),
            "genre": app.get("genre"),
        }

    # ── Diff themes ────────────────────────────────────────────────────────
    emerging_themes: list[dict] = []
    recurring_themes: list[dict] = []

    for phrase, score in today_bigrams:
        past_entries = theme_history.get(phrase, [])
        # Only look at entries within the last 7 days
        recent_dates = {e["date"] for e in past_entries}
        seven_days_ago = (today - timedelta(days=7)).isoformat()
        appeared_recently = any(d >= seven_days_ago for d in recent_dates)

        if appeared_recently:
            # Compute frequency change
            old_score = next(
                (e["score"] for e in reversed(past_entries) if e["date"] >= seven_days_ago),
                0.0,
            )
            freq_change = round(((score - old_score) / (old_score + 1e-6)) * 100, 1)
            recurring_themes.append({
                "theme": phrase,
                "score_today": score,
                "score_prev": old_score,
                "frequency_change_pct": freq_change,
            })
        else:
            emerging_themes.append({"theme": phrase, "score_today": score})

        # Update theme history
        if phrase not in theme_history:
            theme_history[phrase] = []
        theme_history[phrase].append({"date": date_str, "score": score})

    # ── Purge old entries from master histories ────────────────────────────
    # Apps: remove entries older than HISTORY_WINDOW_DAYS
    app_history = {
        aid: data
        for aid, data in app_history.items()
        if data.get("date", "") >= cutoff
    }
    # Themes: prune old date entries
    for theme in list(theme_history.keys()):
        theme_history[theme] = [
            e for e in theme_history[theme] if e.get("date", "") >= cutoff
        ]
        if not theme_history[theme]:
            del theme_history[theme]

    # ── Write master histories ─────────────────────────────────────────────
    _atomic_write(app_hist_path, app_history)
    _atomic_write(theme_hist_path, theme_history)

    # ── Write diff output ──────────────────────────────────────────────────
    result = {
        "date": date_str,
        "newly_detected_apps": newly_detected,
        "accelerating_apps": accelerating_apps,
        "recurring_apps": recurring_apps,
        "emerging_themes": emerging_themes,
        "recurring_themes": recurring_themes,
    }
    _atomic_write(proc_dir / "history_diff.json", result)

    logger.info(
        "[history_diff] Done. New: %d, Accelerating: %d, Emerging themes: %d",
        len(newly_detected),
        len(accelerating_apps),
        len(emerging_themes),
    )
    return {
        "newly_detected": len(newly_detected),
        "accelerating": len(accelerating_apps),
        "emerging_themes": len(emerging_themes),
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = process()
    print(result)
