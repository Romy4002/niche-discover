"""
processors/theme_extractor.py
==============================
Extracts recurring themes from Reddit titles + app descriptions
using TF-IDF (scikit-learn).

Outputs:
  - Top 50 unigrams by TF-IDF weight
  - Top 30 bigrams by TF-IDF weight
  - Candidate themes: bigrams grouped by shared root word

Output: storage/processed/YYYY-MM-DD/themes.json
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _build_stopwords() -> frozenset[str]:
    """Merge scikit-learn English stopwords with custom game stopwords."""
    return frozenset(ENGLISH_STOP_WORDS) | frozenset(config.TFIDF_CUSTOM_STOPWORDS)


def _stem_root(word: str) -> str:
    """
    Very lightweight root extractor -- strips common suffixes.
    We avoid heavy NLP deps (spaCy, NLTK) to keep the install minimal.
    """
    suffixes = ["ing", "er", "ed", "ers", "ings", "s", "es"]
    w = word.lower()
    for s in suffixes:
        if w.endswith(s) and len(w) - len(s) >= 4:
            return w[: -len(s)]
    return w


def _group_bigrams_by_root(
    bigrams: list[tuple[str, float]]
) -> list[tuple[str, list[str]]]:
    """
    Group bigrams that share a root word in either position.
    Returns list of (label, [supporting_phrases]).
    """
    groups: dict[str, list[str]] = {}
    for phrase, _ in bigrams:
        words = phrase.split()
        roots = [_stem_root(w) for w in words]
        # Use the first content word root as the group key
        key = roots[0] if roots else phrase
        groups.setdefault(key, []).append(phrase)

    # Only surface groups with 2+ phrases
    themes: list[tuple[str, list[str]]] = [
        (key, phrases)
        for key, phrases in groups.items()
        if len(phrases) >= 2
    ]
    return sorted(themes, key=lambda x: -len(x[1]))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process(today: date | None = None) -> dict:
    """
    Build TF-IDF theme corpus from Reddit posts + fresh app descriptions.

    Returns the theme data dict; writes themes.json to storage.
    """
    today = today or date.today()
    date_str = today.isoformat()

    raw_dir = Path(config.RAW_DIR) / date_str
    proc_dir = Path(config.PROCESSED_DIR) / date_str
    proc_dir.mkdir(parents=True, exist_ok=True)

    corpus: list[str] = []

    # ── Reddit post titles ─────────────────────────────────────────────────
    reddit_path = raw_dir / "reddit_raw.json"
    if reddit_path.exists():
        with reddit_path.open(encoding="utf-8") as f:
            reddit_data = json.load(f)
        for post in reddit_data.get("posts", []):
            title = post.get("title", "")
            selftext = (post.get("selftext") or "")[:200]
            corpus.append(f"{title} {selftext}")
        logger.info("[theme_extractor] Added %d Reddit docs", len(corpus))
    else:
        logger.warning("[theme_extractor] reddit_raw.json not found")

    # ── Fresh app descriptions ─────────────────────────────────────────────
    fresh_path = proc_dir / "fresh_candidates.json"
    if fresh_path.exists():
        with fresh_path.open(encoding="utf-8") as f:
            fresh_data = json.load(f)
        for app in fresh_data.get("apps", []):
            desc = (app.get("description") or "")[:300]
            if desc:
                corpus.append(desc)
        logger.info("[theme_extractor] Added fresh app descriptions; total corpus: %d", len(corpus))
    else:
        logger.warning("[theme_extractor] fresh_candidates.json not found")

    if not corpus:
        logger.error("[theme_extractor] Empty corpus — cannot extract themes")
        empty = {
            "date": date_str,
            "top_unigrams": [],
            "top_bigrams": [],
            "candidate_themes": [],
        }
        _atomic_write(proc_dir / "themes.json", empty)
        return empty

    stopwords = _build_stopwords()

    # ── Unigram TF-IDF ─────────────────────────────────────────────────────
    uni_vec = TfidfVectorizer(
        ngram_range=(1, 1),
        stop_words=list(stopwords),
        max_features=500,
        min_df=2,
        sublinear_tf=True,
    )
    try:
        uni_matrix = uni_vec.fit_transform(corpus)
        uni_scores = zip(
            uni_vec.get_feature_names_out(),
            uni_matrix.mean(axis=0).tolist()[0],
        )
        top_unigrams = sorted(uni_scores, key=lambda x: -x[1])[: config.TFIDF_TOP_UNIGRAMS]
        top_unigrams = [(w, round(s, 6)) for w, s in top_unigrams]
    except Exception as exc:
        logger.warning("[theme_extractor] Unigram TF-IDF failed: %s", exc)
        top_unigrams = []

    # ── Bigram TF-IDF ──────────────────────────────────────────────────────
    bi_vec = TfidfVectorizer(
        ngram_range=(2, 2),
        stop_words=list(stopwords),
        max_features=500,
        min_df=2,
        sublinear_tf=True,
    )
    try:
        bi_matrix = bi_vec.fit_transform(corpus)
        bi_scores = zip(
            bi_vec.get_feature_names_out(),
            bi_matrix.mean(axis=0).tolist()[0],
        )
        top_bigrams = sorted(bi_scores, key=lambda x: -x[1])[: config.TFIDF_TOP_BIGRAMS]
        top_bigrams = [(p, round(s, 6)) for p, s in top_bigrams]
    except Exception as exc:
        logger.warning("[theme_extractor] Bigram TF-IDF failed: %s", exc)
        top_bigrams = []

    # ── Theme grouping ─────────────────────────────────────────────────────
    candidate_themes = _group_bigrams_by_root(top_bigrams)

    result = {
        "date": date_str,
        "corpus_size": len(corpus),
        "top_unigrams": top_unigrams,
        "top_bigrams": top_bigrams,
        "candidate_themes": candidate_themes,
    }

    _atomic_write(proc_dir / "themes.json", result)
    logger.info(
        "[theme_extractor] Done. %d unigrams, %d bigrams, %d themes",
        len(top_unigrams),
        len(top_bigrams),
        len(candidate_themes),
    )
    return result


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = process()
    print("Top unigrams:", result["top_unigrams"][:10])
    print("Candidate themes:", result["candidate_themes"][:5])
