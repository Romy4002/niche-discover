"""
collectors/reddit_collector.py
================================
Collects posts from mobile-gaming subreddits using Reddit's public
JSON API — no authentication required.

Strategy (tried in order per subreddit):
  1. www.reddit.com with full browser headers + cookie pre-fetch
  2. old.reddit.com JSON endpoint (less aggressive bot detection)
  3. Reddit RSS feed (XML fallback, works even when JSON is blocked)

Output: storage/raw/YYYY-MM-DD/reddit_raw.json
"""

from __future__ import annotations

import json
import logging
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

# Realistic browser headers — Reddit checks these on datacenter IPs
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

REQUEST_TIMEOUT = 20


# ---------------------------------------------------------------------------
# Session builder — pre-fetches cookies from Reddit homepage
# ---------------------------------------------------------------------------

def _build_session() -> requests.Session:
    """Return a session pre-loaded with Reddit cookies."""
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    try:
        session.get("https://www.reddit.com/", timeout=10)
        time.sleep(0.5)
    except Exception:
        pass
    return session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _parse_post(p: dict, subreddit: str) -> dict:
    return {
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
        "comments": [],
    }


# ---------------------------------------------------------------------------
# Strategy 1: www.reddit.com JSON
# ---------------------------------------------------------------------------

def _fetch_json(
    session: requests.Session, subreddit: str, sort: str, limit: int
) -> list[dict]:
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.json"
    for attempt in range(2):
        try:
            resp = session.get(
                url, params={"limit": limit, "raw_json": 1}, timeout=REQUEST_TIMEOUT
            )
            if resp.status_code == 403:
                logger.debug("[reddit] www 403 on %s/%s", subreddit, sort)
                return []
            if resp.status_code == 429:
                time.sleep(15 * (attempt + 1))
                continue
            resp.raise_for_status()
            children = resp.json().get("data", {}).get("children", [])
            return [_parse_post(c["data"], subreddit) for c in children]
        except Exception as exc:
            logger.debug("[reddit] www error %s/%s: %s", subreddit, sort, exc)
            time.sleep(3)
    return []


# ---------------------------------------------------------------------------
# Strategy 2: old.reddit.com JSON
# ---------------------------------------------------------------------------

def _fetch_old_json(
    session: requests.Session, subreddit: str, sort: str, limit: int
) -> list[dict]:
    url = f"https://old.reddit.com/r/{subreddit}/{sort}.json"
    headers = {**BROWSER_HEADERS, "Host": "old.reddit.com"}
    for attempt in range(2):
        try:
            resp = session.get(
                url,
                params={"limit": limit, "raw_json": 1},
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code in (403, 429):
                if resp.status_code == 429:
                    time.sleep(15)
                return []
            resp.raise_for_status()
            children = resp.json().get("data", {}).get("children", [])
            return [_parse_post(c["data"], subreddit) for c in children]
        except Exception as exc:
            logger.debug("[reddit] old error %s/%s: %s", subreddit, sort, exc)
            time.sleep(3)
    return []


# ---------------------------------------------------------------------------
# Strategy 3: RSS feed (XML) — works even when JSON endpoints are blocked
# ---------------------------------------------------------------------------

_RSS_NS = "http://www.w3.org/2005/Atom"


def _fetch_rss(subreddit: str, sort: str, limit: int) -> list[dict]:
    """Parse Reddit RSS feed as last resort."""
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.rss"
    headers = {
        "User-Agent": BROWSER_HEADERS["User-Agent"],
        "Accept": "application/rss+xml, application/xml, text/xml",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)

        posts = []
        # Atom feed: entries are <entry> elements
        entries = root.findall(f"{{{_RSS_NS}}}entry")
        for entry in entries[:limit]:
            title_el = entry.find(f"{{{_RSS_NS}}}title")
            link_el = entry.find(f"{{{_RSS_NS}}}link")
            content_el = entry.find(f"{{{_RSS_NS}}}content")
            updated_el = entry.find(f"{{{_RSS_NS}}}updated")
            id_el = entry.find(f"{{{_RSS_NS}}}id")

            raw_id = (id_el.text or "") if id_el is not None else ""
            # ID is like "t3_XXXXX" — extract post id
            post_id = raw_id.split("_")[-1] if "_" in raw_id else raw_id[-6:]

            posts.append({
                "id": post_id,
                "title": title_el.text if title_el is not None else "",
                "selftext": (content_el.text or "")[:config.REDDIT_SELFTEXT_MAX_CHARS]
                if content_el is not None else "",
                "score": 0,
                "num_comments": 0,
                "created_utc": updated_el.text if updated_el is not None else "",
                "url": link_el.get("href", "") if link_el is not None else "",
                "subreddit": subreddit,
                "flair": None,
                "comments": [],
            })
        return posts
    except Exception as exc:
        logger.debug("[reddit] RSS error %s/%s: %s", subreddit, sort, exc)
        return []


# ---------------------------------------------------------------------------
# Fetch with fallback chain: www → old → RSS
# ---------------------------------------------------------------------------

def _fetch_with_fallback(
    session: requests.Session, subreddit: str, sort: str, limit: int
) -> tuple[list[dict], str]:
    """
    Try www JSON → old JSON → RSS feed.
    Returns (posts, source_used).
    """
    posts = _fetch_json(session, subreddit, sort, limit)
    if posts:
        return posts, "www_json"

    time.sleep(1)
    posts = _fetch_old_json(session, subreddit, sort, limit)
    if posts:
        return posts, "old_json"

    time.sleep(1)
    posts = _fetch_rss(subreddit, sort, limit)
    if posts:
        return posts, "rss"

    return [], "none"


# ---------------------------------------------------------------------------
# Comment fetcher
# ---------------------------------------------------------------------------

def _fetch_comments(
    session: requests.Session, subreddit: str, post_id: str
) -> list[dict]:
    url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json"
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return []
        data = resp.json()
        if len(data) < 2:
            return []
        children = data[1].get("data", {}).get("children", [])
        return [
            {"id": c["data"].get("id", ""), "body": (c["data"].get("body") or "")[:300], "score": c["data"].get("score", 0)}
            for c in children[:20]
            if c.get("kind") == "t1"
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def collect(today: date | None = None) -> dict:
    today = today or date.today()
    date_str = today.isoformat()

    raw_dir = Path(config.RAW_DIR) / date_str
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / "reddit_raw.json"

    logger.info("[reddit] Starting collection (public JSON API) for %s", date_str)

    session = _build_session()
    all_posts: list[dict] = []
    seen_ids: set[str] = set()
    subreddit_counts: dict[str, int] = {}
    sources_used: dict[str, str] = {}

    for sub_name in config.REDDIT_SUBREDDITS:
        sub_posts: dict[str, dict] = {}
        sub_source = "none"
        try:
            hot, src = _fetch_with_fallback(session, sub_name, "hot", config.REDDIT_POSTS_PER_SUB)
            for p in hot:
                sub_posts[p["id"]] = p
            if src != "none":
                sub_source = src
            time.sleep(1.5)

            new_posts, src2 = _fetch_with_fallback(session, sub_name, "new", config.REDDIT_POSTS_PER_SUB)
            for p in new_posts:
                if p["id"] not in sub_posts:
                    sub_posts[p["id"]] = p
            if src2 != "none" and sub_source == "none":
                sub_source = src2
            time.sleep(1.5)

            # Comments for high-engagement posts (only when not on RSS — no IDs)
            if sub_source in ("www_json", "old_json"):
                for post in list(sub_posts.values()):
                    if post["num_comments"] > config.REDDIT_COMMENT_THRESHOLD:
                        post["comments"] = _fetch_comments(session, sub_name, post["id"])
                        time.sleep(0.5)

            sources_used[sub_name] = sub_source
            subreddit_counts[sub_name] = len(sub_posts)
            logger.info("[reddit] %s: %d posts (via %s)", sub_name, len(sub_posts), sub_source)

            for pid, post in sub_posts.items():
                if pid not in seen_ids:
                    all_posts.append(post)
                    seen_ids.add(pid)

        except Exception as exc:
            logger.warning("[reddit] Skipping %s: %s", sub_name, exc)
            subreddit_counts[sub_name] = 0
            sources_used[sub_name] = "error"

        time.sleep(2)

    payload = {
        "date": date_str,
        "total_posts": len(all_posts),
        "subreddit_counts": subreddit_counts,
        "sources_used": sources_used,
        "posts": all_posts,
    }
    _atomic_write(out_path, payload)
    logger.info(
        "[reddit] Done. %d posts across %d subreddits written to %s",
        len(all_posts), len(config.REDDIT_SUBREDDITS), out_path,
    )
    return {"source": "reddit", "posts_collected": len(all_posts), "subreddits": len(config.REDDIT_SUBREDDITS)}


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
