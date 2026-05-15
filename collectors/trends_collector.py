"""
collectors/trends_collector.py
================================
Collects Google Trends data using the pytrends library (no API key).

Two passes:
  Pass 1 -- Breakout query discovery (called during collection phase)
  Pass 2 -- Niche term validation    (called by niche_detector.py)

Rate-limit handling:
  - Max 5 terms per batch
  - Sleep TRENDS_SLEEP_BETWEEN seconds between batches
  - On TooManyRequestsError: sleep TRENDS_RETRY_SLEEP seconds, retry once

Output:
  Pass 1: storage/raw/YYYY-MM-DD/trends_breakout.json
  Pass 2: storage/processed/YYYY-MM-DD/trends_validation.json
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any

from pytrends.exceptions import TooManyRequestsError
from pytrends.request import TrendReq

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _build_pytrends() -> TrendReq:
    """Build a TrendReq instance compatible with urllib3 2.x."""
    # urllib3 2.x renamed method_whitelist -> allowed_methods
    # pytrends 4.9.x still passes method_whitelist, so we patch Retry
    import urllib3.util.retry as _retry_mod
    if not hasattr(_retry_mod.Retry, "_patched_for_urllib3v2"):
        _OrigRetry = _retry_mod.Retry.__init__
        def _patched_init(self, *args, **kwargs):
            kwargs.pop("method_whitelist", None)
            _OrigRetry(self, *args, **kwargs)
        _retry_mod.Retry.__init__ = _patched_init
        _retry_mod.Retry._patched_for_urllib3v2 = True
    return TrendReq(hl="en-US", tz=360, timeout=(10, 25), retries=1, backoff_factor=0.5)


def _safe_mean(values: list[float]) -> float:
    """Return mean, or 0.0 for empty list."""
    return mean(values) if values else 0.0


# ---------------------------------------------------------------------------
# Pass 1 -- Breakout query discovery
# ---------------------------------------------------------------------------

def collect_breakout(today: date | None = None) -> list[str]:
    """
    Seed "mobile games" on Google Trends, extract the top N rising
    related queries. Stores results to trends_breakout.json.

    Returns the list of breakout query strings.
    """
    today = today or date.today()
    date_str = today.isoformat()

    raw_dir = Path(config.RAW_DIR) / date_str
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / "trends_breakout.json"

    logger.info("[trends] Pass 1: collecting breakout queries")

    breakout_queries: list[str] = []

    try:
        pt = _build_pytrends()
        pt.build_payload(
            kw_list=[config.TRENDS_BREAKOUT_SEED],
            timeframe=config.TRENDS_TIMEFRAME_BREAKOUT,
            geo="",
        )
        related = pt.related_queries()
        rising_df = related.get(config.TRENDS_BREAKOUT_SEED, {}).get("rising")
        if rising_df is not None and not rising_df.empty:
            queries = rising_df["query"].tolist()[: config.TRENDS_BREAKOUT_TOP_N]
            breakout_queries = [str(q) for q in queries]
            logger.info("[trends] Found %d breakout queries", len(breakout_queries))
        else:
            logger.warning("[trends] No rising queries found in Trends data")
    except TooManyRequestsError:
        logger.warning("[trends] 429 on breakout query — sleeping 60s, retrying")
        time.sleep(config.TRENDS_RETRY_SLEEP)
        try:
            pt = _build_pytrends()
            pt.build_payload(
                kw_list=[config.TRENDS_BREAKOUT_SEED],
                timeframe=config.TRENDS_TIMEFRAME_BREAKOUT,
                geo="",
            )
            related = pt.related_queries()
            rising_df = related.get(config.TRENDS_BREAKOUT_SEED, {}).get("rising")
            if rising_df is not None and not rising_df.empty:
                breakout_queries = rising_df["query"].tolist()[: config.TRENDS_BREAKOUT_TOP_N]
        except Exception as exc:
            logger.warning("[trends] Retry also failed: %s", exc)
    except Exception as exc:
        logger.warning("[trends] Breakout query fetch failed: %s", exc)

    payload = {
        "date": date_str,
        "seed": config.TRENDS_BREAKOUT_SEED,
        "breakout_queries": breakout_queries,
    }
    _atomic_write(out_path, payload)
    logger.info("[trends] Pass 1 done. %d breakout queries", len(breakout_queries))
    return breakout_queries


# ---------------------------------------------------------------------------
# Pass 2 -- Niche term validation
# ---------------------------------------------------------------------------

def _classify_direction(values: list[float]) -> dict:
    """
    Given a time series of weekly interest values (oldest first),
    compute direction: rising / declining / stable / new_signal.
    """
    if len(values) < 8:
        # Not enough data -- pad with zeros at start
        values = [0.0] * (8 - len(values)) + values

    earlier = _safe_mean(values[:4])
    recent = _safe_mean(values[-4:])
    peak = max(values) if values else 0.0

    if earlier == 0:
        direction = "new_signal"
    elif recent > earlier * config.TRENDS_RISING_THRESHOLD:
        direction = "rising"
    elif recent < earlier * config.TRENDS_DECLINING_THRESHOLD:
        direction = "declining"
    else:
        direction = "stable"

    return {
        "direction": direction,
        "peak": peak,
        "recent_avg": recent,
        "earlier_avg": earlier,
    }


def get_trend_validation(
    terms: list[str], today: date | None = None
) -> dict[str, dict]:
    """
    Validate a list of niche terms against Google Trends (Pass 2).

    Called by niche_detector.py with its top-10 candidates.
    Returns {term: {direction, peak, recent_avg, earlier_avg}}.
    Writes output to storage/processed/YYYY-MM-DD/trends_validation.json.
    """
    today = today or date.today()
    date_str = today.isoformat()

    processed_dir = Path(config.PROCESSED_DIR) / date_str
    processed_dir.mkdir(parents=True, exist_ok=True)
    out_path = processed_dir / "trends_validation.json"

    logger.info("[trends] Pass 2: validating %d niche terms", len(terms))

    results: dict[str, dict] = {}

    # Process in batches of TRENDS_BATCH_SIZE
    for batch_start in range(0, len(terms), config.TRENDS_BATCH_SIZE):
        batch = terms[batch_start : batch_start + config.TRENDS_BATCH_SIZE]
        logger.info("[trends] Validating batch: %s", batch)

        for attempt in range(2):
            try:
                pt = _build_pytrends()
                pt.build_payload(
                    kw_list=batch,
                    timeframe=config.TRENDS_TIMEFRAME_VALIDATE,
                    geo="",
                )
                df = pt.interest_over_time()
                if df is not None and not df.empty:
                    for term in batch:
                        if term in df.columns:
                            values = df[term].tolist()
                            classified = _classify_direction(
                                [float(v) for v in values]
                            )
                            results[term] = {"term": term, **classified}
                        else:
                            results[term] = {
                                "term": term,
                                "direction": "no_data",
                                "peak": 0.0,
                                "recent_avg": 0.0,
                                "earlier_avg": 0.0,
                            }
                else:
                    for term in batch:
                        results[term] = {
                            "term": term,
                            "direction": "no_data",
                            "peak": 0.0,
                            "recent_avg": 0.0,
                            "earlier_avg": 0.0,
                        }
                break  # success

            except TooManyRequestsError:
                if attempt == 0:
                    logger.warning(
                        "[trends] 429 on batch %s — sleeping %ds, retrying",
                        batch,
                        config.TRENDS_RETRY_SLEEP,
                    )
                    time.sleep(config.TRENDS_RETRY_SLEEP)
                else:
                    logger.warning("[trends] Retry failed for batch %s — skipping", batch)
                    for term in batch:
                        results[term] = {
                            "term": term,
                            "direction": "no_data",
                            "peak": 0.0,
                            "recent_avg": 0.0,
                            "earlier_avg": 0.0,
                        }
            except Exception as exc:
                logger.warning("[trends] Batch %s failed: %s — skipping", batch, exc)
                for term in batch:
                    results[term] = {
                        "term": term,
                        "direction": "error",
                        "peak": 0.0,
                        "recent_avg": 0.0,
                        "earlier_avg": 0.0,
                    }
                break

        # Sleep between batches to avoid rate limits
        if batch_start + config.TRENDS_BATCH_SIZE < len(terms):
            time.sleep(config.TRENDS_SLEEP_BETWEEN)

    payload = {
        "date": date_str,
        "terms_validated": len(results),
        "results": results,
    }
    _atomic_write(out_path, payload)
    logger.info(
        "[trends] Pass 2 done. %d terms validated. Written to %s",
        len(results),
        out_path,
    )
    return results


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=== Pass 1: Breakout queries ===")
    queries = collect_breakout()
    print("Breakout queries:", queries[:5])

    if queries:
        print("\n=== Pass 2: Validate first 5 terms ===")
        validation = get_trend_validation(queries[:5])
        for term, data in validation.items():
            print(f"  {term}: {data['direction']}")

