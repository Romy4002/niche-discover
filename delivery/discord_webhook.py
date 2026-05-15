"""
delivery/discord_webhook.py
============================
Sends the intelligence report to a Discord webhook as:
  1. A plain-text message (the summary)
  2. A markdown file attachment (the full report)

Requires environment variable: DISCORD_WEBHOOK_URL
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30  # seconds


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def deliver(message: str, report_path: Path) -> bool:
    """
    Post the Discord message and attach the markdown report.

    Returns True if both requests succeeded, False otherwise.
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        logger.error("[discord] DISCORD_WEBHOOK_URL not set -- skipping delivery")
        return False

    success = True

    # ── Request 1: post plain-text message ────────────────────────────────
    try:
        resp = requests.post(
            webhook_url,
            json={"content": message},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        logger.info(
            "[discord] Message posted successfully (HTTP %d)", resp.status_code
        )
    except requests.HTTPError as exc:
        logger.error(
            "[discord] Message post failed (HTTP %d): %s",
            exc.response.status_code if exc.response else 0,
            exc,
        )
        success = False
    except requests.RequestException as exc:
        logger.error("[discord] Message post error: %s", exc)
        success = False

    time.sleep(1)

    # ── Request 2: post markdown file as attachment ───────────────────────
    if report_path.exists():
        try:
            with report_path.open("rb") as f:
                resp = requests.post(
                    webhook_url,
                    files={"file": ("report.md", f, "text/markdown")},
                    timeout=REQUEST_TIMEOUT,
                )
            resp.raise_for_status()
            logger.info(
                "[discord] Report file attached successfully (HTTP %d)", resp.status_code
            )
        except requests.HTTPError as exc:
            logger.error(
                "[discord] File attach failed (HTTP %d): %s",
                exc.response.status_code if exc.response else 0,
                exc,
            )
            success = False
        except requests.RequestException as exc:
            logger.error("[discord] File attach error: %s", exc)
            success = False
    else:
        logger.error("[discord] Report file not found: %s", report_path)
        success = False

    return success


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from pathlib import Path
    from datetime import date

    date_str = date.today().isoformat()
    test_path = Path(f"storage/reports/{date_str}_report.md")
    test_msg = f"**Test delivery -- {date_str}**\nThis is a test ping from the pipeline."

    ok = deliver(test_msg, test_path)
    print("Delivery success:", ok)
