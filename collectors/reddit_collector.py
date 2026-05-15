"""
collectors/reddit_collector.py
================================
Collects posts from mobile-gaming subreddits using Reddit's public
JSON API (no authentication required, no PRAW needed).

Endpoint pattern:
  GET https://www.reddit.com/r/{subreddit}/{sort}.json?limit=50

No Reddit app / API key required. This uses the same data
Reddit exposes on its website, just in JSON format.

Output: storage/raw/YYYY-MM-DD/reddit_raw.json
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

REDDIT_BASE = "https://www.reddit.com"
REQUEST_TIMEOUT = 20
# Reddit requires a descriptive User-Agent for public JSON access
USER_AGENT = "GameIntelBot/1.0 (market intelligence pipeline; non-commercial)"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _fetch_posts(subreddit: str, sort: str = "hot", limit: int = 50) -> list[dict]:
    """
    Fetch posts from a subreddit using the public .json endpoint.
    Returns a list of serialized post dicts.
    """
    url = f"{REDDIT_BASE}/r/{subreddit}/{sort}.json"
    params = {"limit": limit, "raw_json": 1}
    headers = {"User-Agent": USER_AGENT}

    for attempt in range(3):
        try:
            resp = requests.get(
                url, params=params, headers=headers, timeout=REQUEST_TIMEOUT
            )
            if resp.status_code == 429:
                wait = 10 * (attempt + 1)
                logger.warning(
                    "[reddit] 429 rate limit on %s/%s -- waiting %ds", subreddit, sort, wait
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            children = data.get("data", {}).get("children", [])
            posts = []
            for child in children:
                p = child.get("data", {})
                posts.append({
                    "id": p.get("id", ""),
                    "title": p.get("title", ""),
                    "selftext": (p.get("selftext") or "")[: config.REDDIT_SELFTEXT_MAX_CHARS],
                    "score": p.get("score", 0),
                    "num_comments": p.get("num_comments", 0),
                    "created_utc": datetime.fromtimestamp(
                        p.get("created_utc", 0), tz=timezone.utc
                    ).isoformat(),
                    "url": p.get("url", ""),
                    "subreddit": p.get("subreddit", subreddit),
                    "flair": p.get("link_flair_text"),
                    "comments": [],  # top-level comments fetched separately
                })
            return posts
        except requests.HTTPError as exc:
            logger.warning(
                "[reddit] HTTP error fetching %s/%s (attempt %d): %s",
                subreddit, sort, attempt + 1, exc
            )
            time.sleep(3)
        except Exception as exc:
            logger.warning(
                "[reddit] Error fetching %s/%s (attempt %d): %s",
                subreddit, sort, attempt + 1, exc
            )
            time.sleep(3)
    return []


def _fetch_comments(subreddit: str, post_id: str, limit: int = 20) -> list[dict]:
    """Fetch top-level comments for a post with many comments."""
    url = f"{REDDIT_BASE}/r/{subreddit}/comments/{post_id}.json"
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if len(data) < 2:
            return []
        comment_listing = data[1].get("data", {}).get("children", [])
        comments = []
        for child in comment_listing[:limit]:
            c = child.get("data", {})
            if child.get("kind") == "t1":  # t1 = comment
                comments.append({
                    "id": c.get("id", ""),
                    "body": (c.get("body") or "")[:300],
                    "score": c.get("score", 0),
                })
        return comments
    except Exception as exc:
        logger.debug("[reddit] Comments fetch failed for %s: %s", post_id, exc)
        return []


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def collect(today: date | None = None) -> dict:
    """
    Collect posts from all configured subreddits using the public JSON API.
    No authentication required.

    Returns a summary dict; writes raw JSON to storage.
    """
    today = today or date.today()
    date_str = today.isoformat()

    raw_dir = Path(config.RAW_DIR) / date_str
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / "reddit_raw.json"

    logger.info("[reddit] Starting collection (public JSON API) for %s", date_str)

    all_posts: list[dict] = []
    seen_ids: set[str] = set()
    subreddit_counts: dict[str, int] = {}

    for sub_name in config.REDDIT_SUBREDDITS:
        sub_posts: dict[str, dict] = {}
        try:
            # Hot posts
            hot = _fetch_posts(sub_name, sort="hot", limit=config.REDDIT_POSTS_PER_SUB)
            for p in hot:
                sub_posts[p["id"]] = p
            time.sleep(1)  # gentle pacing between requests

            # New posts
            new = _fetch_posts(sub_name, sort="new", limit=config.REDDIT_POSTS_PER_SUB)
            for p in new:
                if p["id"] not in sub_posts:
                    sub_posts[p["id"]] = p
            time.sleep(1)

            # Fetch comments for high-engagement posts
            for post in list(sub_posts.values()):
                if post["num_comments"] > config.REDDIT_COMMENT_THRESHOLD:
                    comments = _fetch_comments(sub_name, post["id"])
                    post["comments"] = comments
                    time.sleep(0.5)

            count = len(sub_posts)
            subreddit_counts[sub_name] = count
            logger.info("[reddit] %s: %d posts", sub_name, count)

            for pid, post in sub_posts.items():
                if pid not in seen_ids:
                    all_posts.append(post)
                    seen_ids.add(pid)

        except Exception as exc:
            logger.warning("[reddit] Skipping %s due to error: %s", sub_name, exc)
            subreddit_counts[sub_name] = 0

        time.sleep(2)  # be respectful between subreddits

    payload = {
        "date": date_str,
        "total_posts": len(all_posts),
        "subreddit_counts": subreddit_counts,
        "posts": all_posts,
        "auth_method": "public_json_api",
    }

    _atomic_write(out_path, payload)
    logger.info(
        "[reddit] Done. %d posts across %d subreddits written to %s",
        len(all_posts),
        len(config.REDDIT_SUBREDDITS),
        out_path,
    )
    return {
        "source": "reddit",
        "posts_collected": len(all_posts),
        "subreddits": len(config.REDDIT_SUBREDDITS),
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import config as _cfg
    _cfg.REDDIT_SUBREDDITS = ["AndroidGaming"]
    _cfg.REDDIT_POSTS_PER_SUB = 10
    result = collect()
    print(result)
