"""
analyzers/niche_detector.py
============================
Detects underserved niches: topics with strong Reddit discussion
but low corresponding Google Play supply.

Algorithm:
  1. Extract game-related topics from Reddit (mention_count > 3)
  2. Inject Trends breakout queries (confirmed rising terms)
  3. niche_score = mention_count / (matching_app_count + 1)
  4. Flag as "underserved" when score > 2.0 AND app_count < 10
  5. Detect explicit demand phrases (+2 bonus)
  6. Call trends Pass 2 on top 10 candidates
  7. Sort: trends direction primary, niche_score secondary

Output: storage/processed/YYYY-MM-DD/niches.json
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import config
from collectors import trends_collector

logger = logging.getLogger(__name__)

# Direction sort order (lower index = higher priority)
_DIRECTION_ORDER = {"rising": 0, "new_signal": 1, "stable": 2, "declining": 3, "no_data": 4, "error": 5}

# Terms that are Reddit/internet meta-language, not game niches
_NICHE_STOPWORDS: frozenset[str] = frozenset([
    # Reddit meta
    "would", "could", "should", "anyone", "someone", "people", "want", "need",
    "think", "know", "feel", "really", "still", "just", "also", "even",
    "much", "many", "some", "time", "way", "thing", "things", "lot",
    "look", "like", "got", "get", "make", "made", "back", "actually",
    # Publishing meta-terms
    "reviews", "review", "sales", "releases", "release", "roundup",
    "round", "featuring", "feature", "weekly", "daily", "monthly",
    "thread", "discussion", "question", "questions", "recommend",
    "recommendations", "looking", "request", "requests",
    # Platform names (not mobile game niches)
    "switch", "switcharcade", "nintendo", "playstation", "xbox",
    "steam", "pc", "console", "windows", "apple",
    # Generic qualifiers
    "indie", "port", "ports", "remake", "remaster", "sequel",
    "update", "patch", "beta", "alpha", "early", "access",
    # Filler words TF-IDF stopwords miss in this context
    "year", "day", "week", "month", "ago", "old", "has", "was",
    "did", "does", "its", "the", "for", "and", "with", "from",
])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _load_json(path: Path) -> dict | list | None:
    if not path.exists():
        logger.warning("[niche_detector] File not found: %s", path)
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Topic extraction from Reddit
# ---------------------------------------------------------------------------

# Extracts noun-like tokens: 1-3 word phrases, alpha only, 3+ chars each
_WORD_RE = re.compile(r"\b[a-z]{3,}\b")


def _extract_topics_from_reddit(posts: list[dict]) -> dict[str, dict]:
    """
    Extract candidate topic terms from Reddit posts.

    Returns {topic: {"mention_count": int, "supporting_posts": [str],
                     "explicit_demand_signals": int}}
    """
    topic_data: dict[str, dict] = {}

    for post in posts:
        title = (post.get("title") or "").lower()
        selftext = (post.get("selftext") or "").lower()
        combined = f"{title} {selftext}"

        # Check explicit demand phrases
        demand_found = 0
        for phrase in config.NICHE_EXPLICIT_DEMAND_PHRASES:
            if phrase in combined:
                demand_found += 1

        # Extract unigram and bigram topics from the title only
        # (selftext is noisier; titles are more signal-dense)
        words = _WORD_RE.findall(title)

        # Unigrams (skip common words already handled by stopwords in TF-IDF)
        for word in words:
            if word in config.TFIDF_CUSTOM_STOPWORDS or word in _NICHE_STOPWORDS:
                continue
            if len(word) < 4:  # skip very short words ("tha", "rip", etc.)
                continue
            if word not in topic_data:
                topic_data[word] = {
                    "mention_count": 0,
                    "supporting_posts": [],
                    "explicit_demand_signals": 0,
                }
            topic_data[word]["mention_count"] += 1
            if len(topic_data[word]["supporting_posts"]) < 3:
                topic_data[word]["supporting_posts"].append(post.get("title", ""))
            if demand_found:
                topic_data[word]["explicit_demand_signals"] += demand_found

        # Bigrams
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            if (words[i] in config.TFIDF_CUSTOM_STOPWORDS or words[i+1] in config.TFIDF_CUSTOM_STOPWORDS
                    or words[i] in _NICHE_STOPWORDS or words[i+1] in _NICHE_STOPWORDS):
                continue
            if bigram not in topic_data:
                topic_data[bigram] = {
                    "mention_count": 0,
                    "supporting_posts": [],
                    "explicit_demand_signals": 0,
                }
            topic_data[bigram]["mention_count"] += 1
            if len(topic_data[bigram]["supporting_posts"]) < 3:
                topic_data[bigram]["supporting_posts"].append(post.get("title", ""))
            if demand_found:
                topic_data[bigram]["explicit_demand_signals"] += demand_found

    return topic_data


# ---------------------------------------------------------------------------
# App supply counter
# ---------------------------------------------------------------------------

def _count_matching_apps(topic: str, all_apps: list[dict]) -> int:
    """
    Count Google Play apps whose title, genre, or description
    mentions the topic term.
    """
    topic_lower = topic.lower()
    count = 0
    for app in all_apps:
        searchable = " ".join([
            (app.get("title") or "").lower(),
            (app.get("genre") or "").lower(),
            (app.get("description") or "")[:200].lower(),
        ])
        if topic_lower in searchable:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process(today: date | None = None) -> dict:
    """
    Detect underserved niches and validate top candidates via Trends.

    Returns summary dict; writes niches.json to storage.
    """
    today = today or date.today()
    date_str = today.isoformat()

    raw_dir = Path(config.RAW_DIR) / date_str
    proc_dir = Path(config.PROCESSED_DIR) / date_str
    proc_dir.mkdir(parents=True, exist_ok=True)

    # ── Load Reddit posts ─────────────────────────────────────────────────
    reddit_data = _load_json(raw_dir / "reddit_raw.json")
    posts: list[dict] = (reddit_data or {}).get("posts", [])
    logger.info("[niche_detector] Processing %d Reddit posts", len(posts))

    # ── Load all Google Play apps (full corpus, not just fresh) ───────────
    play_data = _load_json(raw_dir / "google_play_raw.json")
    all_play_apps: list[dict] = (play_data or {}).get("apps", [])

    # ── Extract Reddit topics ─────────────────────────────────────────────
    topic_data = _extract_topics_from_reddit(posts)

    # ── Inject Trends breakout queries ────────────────────────────────────
    breakout_path = raw_dir / "trends_breakout.json"
    if breakout_path.exists():
        breakout_data = _load_json(breakout_path)
        for query in (breakout_data or {}).get("breakout_queries", []):
            q = query.lower().strip()
            if q not in topic_data:
                topic_data[q] = {
                    "mention_count": 0,
                    "supporting_posts": [],
                    "explicit_demand_signals": 0,
                }
            # Give breakout queries a minimum mention boost
            topic_data[q]["mention_count"] = max(topic_data[q]["mention_count"], config.NICHE_MIN_MENTIONS)
        logger.info("[niche_detector] Injected Trends breakout queries")

    # ── Score niches ──────────────────────────────────────────────────────
    niches: list[dict] = []
    for topic, data in topic_data.items():
        mention_count = data["mention_count"]
        if mention_count < config.NICHE_MIN_MENTIONS:
            continue

        app_count = _count_matching_apps(topic, all_play_apps)
        demand = data["explicit_demand_signals"]

        niche_score = mention_count / (app_count + 1)
        if demand > 0:
            niche_score += config.NICHE_EXPLICIT_DEMAND_BONUS * demand

        if niche_score < config.NICHE_SCORE_THRESHOLD and app_count >= config.NICHE_MAX_SUPPLY:
            continue

        niches.append({
            "niche_topic": topic,
            "mention_count": mention_count,
            "matching_app_count": app_count,
            "niche_score": round(niche_score, 4),
            "explicit_demand_signals": demand,
            "trends_direction": None,
            "trends_peak": None,
            "supporting_posts": data["supporting_posts"][:3],
        })

    # Sort by niche_score to get top candidates before Trends
    niches.sort(key=lambda x: x["niche_score"], reverse=True)
    top_candidates = niches[: config.NICHE_TOP_N]

    # ── Validate top candidates via Trends Pass 2 ─────────────────────────
    if top_candidates:
        candidate_terms = [n["niche_topic"] for n in top_candidates]
        logger.info(
            "[niche_detector] Running Trends Pass 2 on %d candidates", len(candidate_terms)
        )
        try:
            tv = trends_collector.get_trend_validation(candidate_terms, today=today)
            for niche in top_candidates:
                term = niche["niche_topic"]
                if term in tv:
                    niche["trends_direction"] = tv[term].get("direction")
                    niche["trends_peak"] = tv[term].get("peak")
        except Exception as exc:
            logger.warning("[niche_detector] Trends validation failed: %s", exc)

    # ── Final sort: direction primary, score secondary ────────────────────
    def _sort_key(n: dict) -> tuple[int, float]:
        direction = n.get("trends_direction") or "no_data"
        return (_DIRECTION_ORDER.get(direction, 99), -n["niche_score"])

    top_candidates.sort(key=_sort_key)

    payload = {
        "date": date_str,
        "total_topics_analyzed": len(topic_data),
        "niches_qualified": len(niches),
        "top_niches": top_candidates,
    }
    _atomic_write(proc_dir / "niches.json", payload)

    logger.info(
        "[niche_detector] Done. %d topics -> %d niches -> top %d",
        len(topic_data),
        len(niches),
        len(top_candidates),
    )
    return {
        "total_topics": len(topic_data),
        "niches_found": len(niches),
        "top_niches": len(top_candidates),
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = process()
    print(result)
