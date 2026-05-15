"""
collectors/reddit_collector.py
================================
Collects posts from mobile-gaming subreddits using Reddit's public API.

Fallback chain per subreddit (GitHub Actions AWS IPs often get 403):
  1. www.reddit.com JSON with full browser headers + cookie pre-fetch
  2. old.reddit.com JSON
  3. Reddit RSS/Atom feed (XML)
  4. Supplementary: TouchArcade RSS + iTunes App Store RSS (always works)

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
}
REQUEST_TIMEOUT = 20

# Supplementary RSS sources that are never blocked (no auth, no IP restrictions)
SUPPLEMENTARY_FEEDS = [
    # TouchArcade - confirmed working (rich mobile game news)
    ("https://toucharcade.com/category/news/feed/", "toucharcade"),
    # Game Developer - industry/mechanic trends
    ("https://www.gamedeveloper.com/rss.xml", "gamedeveloper"),
]


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


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    try:
        session.get("https://www.reddit.com/", timeout=8)
        time.sleep(0.5)
    except Exception:
        pass
    return session


# ---------------------------------------------------------------------------
# Strategy 1: www.reddit.com JSON
# ---------------------------------------------------------------------------

def _fetch_json(session: requests.Session, subreddit: str, sort: str, limit: int) -> list[dict]:
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.json"
    for attempt in range(2):
        try:
            resp = session.get(url, params={"limit": limit, "raw_json": 1}, timeout=REQUEST_TIMEOUT)
            if resp.status_code in (403, 429):
                if resp.status_code == 429:
                    time.sleep(15)
                return []
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

def _fetch_old_json(session: requests.Session, subreddit: str, sort: str, limit: int) -> list[dict]:
    url = f"https://old.reddit.com/r/{subreddit}/{sort}.json"
    for attempt in range(2):
        try:
            resp = session.get(url, params={"limit": limit, "raw_json": 1},
                               headers={**BROWSER_HEADERS, "Host": "old.reddit.com"},
                               timeout=REQUEST_TIMEOUT)
            if resp.status_code in (403, 429):
                return []
            resp.raise_for_status()
            children = resp.json().get("data", {}).get("children", [])
            return [_parse_post(c["data"], subreddit) for c in children]
        except Exception as exc:
            logger.debug("[reddit] old error %s/%s: %s", subreddit, sort, exc)
            time.sleep(3)
    return []


# ---------------------------------------------------------------------------
# Strategy 3: Reddit RSS (Atom feed)
# ---------------------------------------------------------------------------

_ATOM_NS = "http://www.w3.org/2005/Atom"

def _fetch_rss(subreddit: str, sort: str, limit: int) -> list[dict]:
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.rss"
    try:
        resp = requests.get(url, headers={"User-Agent": BROWSER_HEADERS["User-Agent"],
                                          "Accept": "application/rss+xml, text/xml"},
                            timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        posts = []
        for entry in root.findall(f"{{{_ATOM_NS}}}entry")[:limit]:
            title_el = entry.find(f"{{{_ATOM_NS}}}title")
            link_el  = entry.find(f"{{{_ATOM_NS}}}link")
            content_el = entry.find(f"{{{_ATOM_NS}}}content")
            id_el    = entry.find(f"{{{_ATOM_NS}}}id")
            raw_id   = (id_el.text or "") if id_el is not None else ""
            post_id  = raw_id.split("_")[-1] if "_" in raw_id else raw_id[-6:]
            posts.append({
                "id": post_id,
                "title": (title_el.text or "") if title_el is not None else "",
                "selftext": (content_el.text or "")[:config.REDDIT_SELFTEXT_MAX_CHARS] if content_el is not None else "",
                "score": 0, "num_comments": 0, "created_utc": "", "flair": None, "comments": [],
                "url": link_el.get("href", "") if link_el is not None else "",
                "subreddit": subreddit,
            })
        return posts
    except Exception as exc:
        logger.debug("[reddit] RSS error %s/%s: %s", subreddit, sort, exc)
        return []


# ---------------------------------------------------------------------------
# Strategy 4: Supplementary RSS feeds (TouchArcade etc.) — never blocked
# ---------------------------------------------------------------------------

def _fetch_supplementary_feeds() -> list[dict]:
    """
    Parse gaming news RSS feeds that work from any IP.
    Converts articles into post-like dicts so downstream processors work unchanged.
    """
    posts: list[dict] = []
    for feed_url, source_name in SUPPLEMENTARY_FEEDS:
        try:
            resp = requests.get(feed_url,
                                headers={"User-Agent": BROWSER_HEADERS["User-Agent"]},
                                timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                logger.debug("[reddit] Feed %s returned %d", source_name, resp.status_code)
                continue

            root = ET.fromstring(resp.content)
            # Handle both RSS 2.0 and Atom
            items = root.findall(".//item") or root.findall(f".//{{{_ATOM_NS}}}entry")
            count = 0
            for item in items[:40]:
                # Use "is not None" - NOT "or" - because ET elements are falsy when empty
                _t = item.find("title");   title_el = _t if _t is not None else item.find(f"{{{_ATOM_NS}}}title")
                _d = item.find("description"); _d = _d if _d is not None else item.find("summary")
                desc_el = _d if _d is not None else item.find(f"{{{_ATOM_NS}}}content")
                _l = item.find("link");    link_el = _l if _l is not None else item.find(f"{{{_ATOM_NS}}}link")
                title = (title_el.text or "").strip() if title_el is not None else ""
                desc  = (desc_el.text or "").strip()[:config.REDDIT_SELFTEXT_MAX_CHARS] if desc_el is not None else ""
                link  = ((link_el.text or "") if link_el is not None else "") or (link_el.get("href","") if link_el is not None else "")
                if title:
                    posts.append({
                        "id": f"{source_name}_{count}",
                        "title": title,
                        "selftext": desc,
                        "score": 10,
                        "num_comments": 0,
                        "created_utc": "",
                        "url": link,
                        "subreddit": source_name,
                        "flair": None,
                        "comments": [],
                    })
                    count += 1
            logger.info("[reddit] %s: %d articles", source_name, count)
        except Exception as exc:
            logger.warning("[reddit] Feed %s failed: %s", source_name, exc)
        time.sleep(1)
    return posts


# ---------------------------------------------------------------------------
# Fallback chain: www → old → RSS
# ---------------------------------------------------------------------------

def _fetch_with_fallback(session: requests.Session, subreddit: str, sort: str, limit: int) -> tuple[list[dict], str]:
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
    return [], "blocked"


def _fetch_comments(session: requests.Session, subreddit: str, post_id: str) -> list[dict]:
    url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json"
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return []
        data = resp.json()
        if len(data) < 2:
            return []
        return [
            {"id": c["data"].get("id", ""), "body": (c["data"].get("body") or "")[:300], "score": c["data"].get("score", 0)}
            for c in data[1].get("data", {}).get("children", [])[:20]
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

    logger.info("[reddit] Starting collection for %s", date_str)

    session = _build_session()
    all_posts: list[dict] = []
    seen_ids: set[str] = set()
    subreddit_counts: dict[str, int] = {}
    sources_used: dict[str, str] = {}
    reddit_blocked = True

    for sub_name in config.REDDIT_SUBREDDITS:
        sub_posts: dict[str, dict] = {}
        sub_source = "none"
        try:
            hot, src = _fetch_with_fallback(session, sub_name, "hot", config.REDDIT_POSTS_PER_SUB)
            for p in hot:
                sub_posts[p["id"]] = p
            if src != "blocked":
                sub_source = src
                reddit_blocked = False
            time.sleep(1.5)

            new_posts, src2 = _fetch_with_fallback(session, sub_name, "new", config.REDDIT_POSTS_PER_SUB)
            for p in new_posts:
                if p["id"] not in sub_posts:
                    sub_posts[p["id"]] = p
            if src2 != "blocked" and sub_source == "none":
                sub_source = src2
            time.sleep(1.5)

            if sub_source in ("www_json", "old_json"):
                for post in list(sub_posts.values()):
                    if post["num_comments"] > config.REDDIT_COMMENT_THRESHOLD:
                        post["comments"] = _fetch_comments(session, sub_name, post["id"])
                        time.sleep(0.5)

            sources_used[sub_name] = sub_source or "blocked"
            subreddit_counts[sub_name] = len(sub_posts)
            logger.info("[reddit] %s: %d posts (via %s)", sub_name, len(sub_posts), sub_source or "blocked")

            for pid, post in sub_posts.items():
                if pid not in seen_ids:
                    all_posts.append(post)
                    seen_ids.add(pid)

        except Exception as exc:
            logger.warning("[reddit] Skipping %s: %s", sub_name, exc)
            sources_used[sub_name] = "error"
        time.sleep(2)

    # -- Supplementary feeds (always collected — works from any IP) --------
    logger.info("[reddit] Collecting supplementary gaming feeds")
    supplementary = _fetch_supplementary_feeds()
    for post in supplementary:
        if post["id"] not in seen_ids:
            all_posts.append(post)
            seen_ids.add(post["id"])

    if reddit_blocked:
        logger.warning(
            "[reddit] All subreddits blocked (datacenter IP). "
            "Using %d supplementary feed articles only.", len(supplementary)
        )

    payload = {
        "date": date_str,
        "total_posts": len(all_posts),
        "reddit_posts": len(all_posts) - len(supplementary),
        "supplementary_posts": len(supplementary),
        "subreddit_counts": subreddit_counts,
        "sources_used": sources_used,
        "reddit_blocked": reddit_blocked,
        "posts": all_posts,
    }
    _atomic_write(out_path, payload)
    logger.info(
        "[reddit] Done. %d posts (%d reddit + %d supplementary)",
        len(all_posts), len(all_posts) - len(supplementary), len(supplementary)
    )
    return {"source": "reddit", "posts_collected": len(all_posts), "subreddits": len(config.REDDIT_SUBREDDITS)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import config as _cfg
    _cfg.REDDIT_SUBREDDITS = ["AndroidGaming"]
    _cfg.REDDIT_POSTS_PER_SUB = 10
    result = collect()
    print(result)



