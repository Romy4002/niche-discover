"""
main.py
========
Pipeline orchestrator. Runs all modules in the specified order.
Each collector is wrapped in try/except -- one failure never stops the pipeline.
If ALL collectors fail, the pipeline aborts with a clear error message.

Run order:
  1. Create storage directories
  2. Collectors:  google_play -> reddit -> steam -> trends (Pass 1)
  3. Processors:  freshness -> normalizer -> theme_extractor
  4. Analyzers:   trend_scorer (prelim) -> niche_detector (runs trends Pass 2)
                  -> complaint_parser -> history_diff
  5. Re-score:    trend_scorer (final, with trends data)
  6. AI:          synthesizer
  7. Reports:     builder
  8. Delivery:    discord_webhook
  9. Summary log
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import config

# Configure logging early
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.now(tz=timezone.utc).strftime("%H:%M:%S")


def _step(name: str) -> None:
    logger.info("=" * 60)
    logger.info("STEP: %s  [%s]", name, _ts())
    logger.info("=" * 60)


def _ensure_dirs(date_str: str) -> None:
    """Create all required storage directories."""
    dirs = [
        Path(config.RAW_DIR) / date_str,
        Path(config.PROCESSED_DIR) / date_str,
        Path(config.REPORTS_DIR),
        Path(config.MASTER_DIR),
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    logger.info("Storage directories created for %s", date_str)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run() -> None:
    pipeline_start = time.time()
    today = date.today()
    date_str = today.isoformat()

    logger.info("Mobile Game Market Intelligence Pipeline")
    logger.info("Date: %s", date_str)
    logger.info("=" * 60)

    # Metadata accumulator
    meta: dict = {
        "date": date_str,
        "play_collected": 0,
        "play_fresh": 0,
        "play_legacy": 0,
        "reddit_posts": 0,
        "steam_apps": 0,
        "niches_validated": 0,
    }

    # ── Step 1: Storage directories ───────────────────────────────────────
    _step("1. Create storage directories")
    _ensure_dirs(date_str)

    # ── Step 2: Collectors ────────────────────────────────────────────────
    _step("2a. Google Play collector")
    gp_ok = False
    try:
        from collectors import google_play
        r = google_play.collect(today)
        meta["play_collected"] = r.get("apps_collected", 0)
        gp_ok = True
        logger.info("Google Play: %d apps", meta["play_collected"])
    except Exception as exc:
        logger.warning("Google Play collector FAILED: %s", exc)

    _step("2b. Reddit collector")
    reddit_ok = False
    try:
        from collectors import reddit_collector
        r = reddit_collector.collect(today)
        meta["reddit_posts"] = r.get("posts_collected", 0)
        reddit_ok = True
        logger.info("Reddit: %d posts", meta["reddit_posts"])
    except Exception as exc:
        logger.warning("Reddit collector FAILED: %s", exc)

    _step("2c. Steam collector")
    steam_ok = False
    try:
        from collectors import steam_collector
        r = steam_collector.collect(today)
        meta["steam_apps"] = r.get("apps_collected", 0)
        steam_ok = True
        logger.info("Steam: %d apps", meta["steam_apps"])
    except Exception as exc:
        logger.warning("Steam collector FAILED: %s", exc)

    _step("2d. Google Trends (Pass 1 -- breakout queries)")
    trends_ok = False
    try:
        from collectors import trends_collector
        trends_collector.collect_breakout(today)
        trends_ok = True
        logger.info("Trends Pass 1: breakout queries collected")
    except Exception as exc:
        logger.warning("Trends collector (Pass 1) FAILED: %s", exc)

    # Abort if ALL collectors failed
    if not any([gp_ok, reddit_ok, steam_ok]):
        logger.error(
            "ABORT: All data collectors failed. Cannot produce intelligence report."
        )
        sys.exit(1)

    # ── Step 3: Processors ────────────────────────────────────────────────
    _step("3a. Freshness classifier")
    try:
        from processors import freshness
        r = freshness.process(today)
        meta["play_fresh"] = r.get("fresh", 0)
        meta["play_legacy"] = r.get("legacy", 0)
        logger.info("Freshness: %d fresh, %d legacy", meta["play_fresh"], meta["play_legacy"])
    except Exception as exc:
        logger.warning("Freshness processor FAILED: %s", exc)

    _step("3b. Normalizer")
    try:
        from processors import normalizer
        normalizer.process(today)
    except Exception as exc:
        logger.warning("Normalizer FAILED: %s", exc)

    _step("3c. Theme extractor")
    try:
        from processors import theme_extractor
        theme_extractor.process(today)
    except Exception as exc:
        logger.warning("Theme extractor FAILED: %s", exc)

    # ── Step 4: Analyzers ─────────────────────────────────────────────────
    _step("4a. Trend scorer (preliminary -- no trends data yet)")
    try:
        from analyzers import trend_scorer
        trend_scorer.process(today)
    except Exception as exc:
        logger.warning("Trend scorer (prelim) FAILED: %s", exc)

    _step("4b. Niche detector (runs Trends Pass 2 internally)")
    try:
        from analyzers import niche_detector
        r = niche_detector.process(today)
        meta["niches_validated"] = r.get("niches_found", 0)
        logger.info("Niches: %d found", meta["niches_validated"])
    except Exception as exc:
        logger.warning("Niche detector FAILED: %s", exc)

    _step("4c. Complaint parser")
    try:
        from analyzers import complaint_parser
        complaint_parser.process(today)
    except Exception as exc:
        logger.warning("Complaint parser FAILED: %s", exc)

    _step("4d. History diff")
    try:
        from analyzers import history_diff
        history_diff.process(today)
    except Exception as exc:
        logger.warning("History diff FAILED: %s", exc)

    # ── Step 5: Re-score with Trends data ─────────────────────────────────
    _step("5. Trend scorer (final -- with trends validation data)")
    try:
        from analyzers import trend_scorer
        trend_scorer.process(today)
    except Exception as exc:
        logger.warning("Trend scorer (final) FAILED: %s", exc)

    # ── Step 6: AI synthesis ──────────────────────────────────────────────
    _step("6. AI synthesizer")
    try:
        from ai import synthesizer
        synthesizer.synthesize(today)
    except Exception as exc:
        logger.warning("AI synthesizer FAILED: %s", exc)

    # ── Step 7: Build reports ─────────────────────────────────────────────
    _step("7. Report builder")
    report_path = None
    discord_msg = ""
    try:
        from reports import builder
        report_path, discord_msg = builder.build(today, meta)
        logger.info("Report written: %s", report_path)
    except Exception as exc:
        logger.warning("Report builder FAILED: %s", exc)

    # ── Step 8: Discord delivery ──────────────────────────────────────────
    _step("8. Discord delivery")
    if report_path and discord_msg:
        try:
            from delivery import discord_webhook
            ok = discord_webhook.deliver(discord_msg, report_path)
            if ok:
                logger.info("Discord delivery: SUCCESS")
            else:
                logger.warning("Discord delivery: PARTIAL FAILURE (check logs)")
        except Exception as exc:
            logger.warning("Discord delivery FAILED: %s", exc)
    else:
        logger.warning("Discord delivery SKIPPED -- no report or message available")

    # ── Step 9: Summary ───────────────────────────────────────────────────
    elapsed = round(time.time() - pipeline_start, 1)
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE  [%s]", _ts())
    logger.info("=" * 60)
    logger.info("Sources collected:")
    logger.info("  Google Play : %d apps (%d fresh, %d legacy excluded)",
                meta["play_collected"], meta["play_fresh"], meta["play_legacy"])
    logger.info("  Reddit      : %d posts from %d subreddits",
                meta["reddit_posts"], len(config.REDDIT_SUBREDDITS))
    logger.info("  Steam       : %d apps analyzed", meta["steam_apps"])
    logger.info("Niches found  : %d", meta["niches_validated"])
    logger.info("Total runtime : %.1fs", elapsed)
    logger.info("=" * 60)


if __name__ == "__main__":
    run()
