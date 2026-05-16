"""
reports/builder.py
===================
Assembles two outputs from all processed data:

1. Full markdown report:  storage/reports/YYYY-MM-DD_report.md
2. Discord rich message:  returned as a string (max 1800 chars)

The markdown report is the attachment; the rich message is the body.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe(v: Any, default: str = "n/a") -> str:
    return str(v) if v is not None else default


def _truncate(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return text[: n - 3] + "..."


# ---------------------------------------------------------------------------
# Markdown report builder
# ---------------------------------------------------------------------------

def build_markdown(
    date_str: str,
    proc_dir: Path,
    raw_dir: Path,
    meta: dict,
) -> str:
    """
    Build the full markdown intelligence report from all processed data.
    """
    lines: list[str] = []
    lines.append(f"# Mobile Game Market Intelligence -- {date_str}")
    lines.append("")

    # ── AI Briefing ──────────────────────────────────────────────────────────
    briefing_path = proc_dir / "ai_briefing.txt"
    briefing = briefing_path.read_text(encoding="utf-8") if briefing_path.exists() else "[AI briefing not available]"
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(briefing)
    lines.append("")

    # ── Trending Apps ────────────────────────────────────────────────────────
    lines.append("## Trending Apps")
    lines.append("")
    trend_data = _load_json(proc_dir / "trend_scores.json")
    candidates = (trend_data or {}).get("trending_candidates", [])
    if candidates:
        lines.append(
            "| Rank | Title | Genre | Trend Score | Freshness | Released (days ago) | Trends Direction |"
        )
        lines.append(
            "|------|-------|-------|-------------|-----------|---------------------|-----------------|"
        )
        for i, app in enumerate(candidates, 1):
            lines.append(
                f"| {i} | {_safe(app.get('title'))} "
                f"| {_safe(app.get('genre'))} "
                f"| {_safe(app.get('trend_score'))} "
                f"| {_safe(app.get('freshness_label'))} "
                f"| {_safe(app.get('released_days'))} "
                f"| {_safe(app.get('trends_direction'))} |"
            )
    else:
        lines.append("_No trending apps data._")
    lines.append("")

    # ── Underserved Niches ───────────────────────────────────────────────────
    lines.append("## Underserved Niches")
    lines.append("")
    niche_data = _load_json(proc_dir / "niches.json")
    top_niches = (niche_data or {}).get("top_niches", [])
    if top_niches:
        lines.append(
            "| Niche Topic | Mentions | Apps | Score | Trends Direction | Demand Signals | Supporting Posts |"
        )
        lines.append(
            "|-------------|----------|------|-------|-----------------|----------------|-----------------|"
        )
        for n in top_niches:
            posts = "; ".join(n.get("supporting_posts", [])[:2])
            lines.append(
                f"| {_safe(n.get('niche_topic'))} "
                f"| {_safe(n.get('mention_count'))} "
                f"| {_safe(n.get('matching_app_count'))} "
                f"| {_safe(n.get('niche_score'))} "
                f"| {_safe(n.get('trends_direction'))} "
                f"| {_safe(n.get('explicit_demand_signals'))} "
                f"| {_truncate(posts, 80)} |"
            )
    else:
        lines.append("_No niche data._")
    lines.append("")

    # ── Google Trends Breakout Queries ───────────────────────────────────────
    lines.append("## Google Trends Breakout Queries")
    lines.append("")
    breakout_data = _load_json(raw_dir / "trends_breakout.json")
    breakout_queries = (breakout_data or {}).get("breakout_queries", [])
    if breakout_queries:
        for q in breakout_queries:
            lines.append(f"- {q}")
    else:
        lines.append("_No breakout queries._")
    lines.append("")

    # ── Emerging Themes ──────────────────────────────────────────────────────
    lines.append("## Emerging Themes")
    lines.append("")
    diff_data = _load_json(proc_dir / "history_diff.json")
    emerging = (diff_data or {}).get("emerging_themes", [])
    theme_data = _load_json(proc_dir / "themes.json")
    candidate_themes = (theme_data or {}).get("candidate_themes", [])
    if emerging:
        for t in emerging:
            lines.append(f"- **{t.get('theme')}** (TF-IDF: {t.get('score_today', 0):.4f})")
    elif candidate_themes:
        for label, phrases in candidate_themes[:8]:
            lines.append(f"- **{label}**: {', '.join(phrases)}")
    else:
        lines.append("_No emerging themes._")
    lines.append("")

    # ── Player Complaints ────────────────────────────────────────────────────
    lines.append("## Player Complaints")
    lines.append("")
    complaint_data = _load_json(proc_dir / "complaints.json")
    top_complaints = (complaint_data or {}).get("top_complaints", [])
    if top_complaints:
        lines.append("| Complaint | Count | Category |")
        lines.append("|-----------|-------|----------|")
        for phrase, count, category in top_complaints[:15]:
            lines.append(f"| {phrase} | {count} | {category} |")
    else:
        lines.append("_No complaint data._")
    lines.append("")

    # ── Player Praises ───────────────────────────────────────────────────────
    lines.append("## Player Praises")
    lines.append("")
    top_praises = (complaint_data or {}).get("top_praises", [])
    if top_praises:
        for phrase, count, _ in top_praises[:8]:
            lines.append(f"- **{phrase}** ({count}x)")
    else:
        lines.append("_No praise data._")
    lines.append("")

    # ── Steam Mechanic Signals ───────────────────────────────────────────────
    lines.append("## Steam Mechanic Signals")
    lines.append("")
    steam_data = _load_json(raw_dir / "steam_raw.json")
    top_tags = (steam_data or {}).get("top_tags", [])[:20]
    if top_tags:
        lines.append("| Tag | Vote Count |")
        lines.append("|-----|------------|")
        for tag, votes in top_tags:
            lines.append(f"| {tag} | {votes} |")
    else:
        lines.append("_No Steam tag data._")
    lines.append("")

    # ── Newly Detected Apps ──────────────────────────────────────────────────
    lines.append("## Newly Detected Apps")
    lines.append("")
    newly = (diff_data or {}).get("newly_detected_apps", [])
    if newly:
        lines.append("| Title | Genre | Freshness | Trend Score |")
        lines.append("|-------|-------|-----------|-------------|")
        for app in newly[:15]:
            lines.append(
                f"| {_safe(app.get('title'))} "
                f"| {_safe(app.get('genre'))} "
                f"| {_safe(app.get('freshness_label'))} "
                f"| {_safe(app.get('trend_score'))} |"
            )
    else:
        lines.append("_No newly detected apps (first run or no new entries)._")
    lines.append("")

    # ── Trend Velocity ───────────────────────────────────────────────────────
    lines.append("## Trend Velocity (7-day acceleration)")
    lines.append("")
    accelerating = (diff_data or {}).get("accelerating_apps", [])
    if accelerating:
        lines.append("| App Title | Score 7d Ago | Score Today | Delta |")
        lines.append("|-----------|-------------|-------------|-------|")
        for app in accelerating[:10]:
            lines.append(
                f"| {_safe(app.get('title'))} "
                f"| {_safe(app.get('score_7d_ago'))} "
                f"| {_safe(app.get('trend_score'))} "
                f"| +{_safe(app.get('trend_velocity'))} |"
            )
    else:
        lines.append("_No accelerating apps this week._")
    lines.append("")

    # ── Run Metadata ─────────────────────────────────────────────────────────
    lines.append("## Data Sources & Run Metadata")
    lines.append("")
    lines.append(f"- **Google Play**: {meta.get('play_collected', 0)} apps collected, "
                 f"{meta.get('play_fresh', 0)} fresh, {meta.get('play_legacy', 0)} legacy excluded")
    lines.append(f"- **Reddit**: {meta.get('reddit_posts', 0)} posts from "
                 f"{len(config.REDDIT_SUBREDDITS)} subreddits")
    lines.append(f"- **Steam**: {meta.get('steam_apps', 0)} apps analyzed")
    lines.append(f"- **Google Trends**: {meta.get('niches_validated', 0)} niches validated, "
                 f"{len(breakout_queries)} breakout queries")
    lines.append(f"- **Run timestamp**: {datetime.now(tz=timezone.utc).isoformat()}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Discord message builder — rich formatting
# ---------------------------------------------------------------------------

# Trend direction → emoji
_DIRECTION_EMOJI: dict[str, str] = {
    "rising":     "📈",
    "new_signal": "✨",
    "stable":     "➡️",
    "declining":  "📉",
    "no_data":    "❓",
    "error":      "⚠️",
}

# Freshness label → short emoji label
_FRESH_LABEL: dict[str, str] = {
    "new_release":               "🆕 New",
    "new_release_with_traction": "🚀 Breakout",
    "recent_release":            "🔥 Recent",
    "establishing":              "📱 Growing",
}


def _dir_emoji(direction: str | None) -> str:
    return _DIRECTION_EMOJI.get(direction or "no_data", "❓")


def _score_bar(score: float, max_score: float = 30.0, width: int = 8) -> str:
    """Return a mini progress bar e.g. ████░░░░"""
    filled = round((score / max_score) * width) if max_score else 0
    filled = max(0, min(filled, width))
    return "█" * filled + "░" * (width - filled)


def build_discord_message(
    date_str: str,
    proc_dir: Path,
    raw_dir: Path,
) -> str:
    """
    Build a rich, visually structured Discord message (max 1800 chars).
    """
    lines: list[str] = []

    # ── Header ───────────────────────────────────────────────────────────────
    lines.append(f"## 🎮 Mobile Game Intel  `{date_str}`")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # ── AI overview snippet ───────────────────────────────────────────────────
    briefing_path = proc_dir / "ai_briefing.txt"
    if briefing_path.exists():
        full = briefing_path.read_text(encoding="utf-8")
        prose = [
            l.strip().lstrip("*#> ").strip()
            for l in full.splitlines()
            if l.strip()
            and not l.startswith("[")       # fallback notes
            and not l.startswith("#")       # markdown headers
            and not l.startswith("**1.")    # numbered section headers
            and not l.startswith("**2.")
            and not l.startswith("===")     # evidence section dividers
            and not l.startswith("|")       # table rows
            and not l.startswith("---")     # table separators
            and not l.startswith("- ")      # bullet lists
            and len(l.strip()) > 60         # skip very short lines
        ]
        if prose:
            snippet = " ".join(prose[:2])[:260]
            lines.append(f"> {snippet}")
            lines.append("")

    # ── Top trending apps ─────────────────────────────────────────────────────
    trend_data = _load_json(proc_dir / "trend_scores.json")
    candidates = (trend_data or {}).get("trending_candidates", [])[:5]
    if candidates:
        lines.append("**📊 Top Trending Apps**")
        top_score = float(candidates[0].get("trend_score", 30) or 30)
        for app in candidates:
            score = float(app.get("trend_score", 0) or 0)
            bar = _score_bar(score, max_score=max(top_score, 1.0))
            fresh = _FRESH_LABEL.get(
                app.get("freshness_label") or "", app.get("freshness_label") or ""
            )
            d_emoji = _dir_emoji(app.get("trends_direction"))
            lines.append(
                f"`{bar}` **{_safe(app.get('title'))}**  "
                f"{d_emoji} `{score:.0f}` · {fresh}"
            )
        lines.append("")

    # ── Top niches ────────────────────────────────────────────────────────────
    niche_data = _load_json(proc_dir / "niches.json")
    top_niches = (niche_data or {}).get("top_niches", [])[:4]
    if top_niches:
        lines.append("**🔍 Underserved Niches**")
        for n in top_niches:
            direction = n.get("trends_direction") or "no_data"
            d_emoji = _dir_emoji(direction)
            score = n.get("niche_score", 0)
            mentions = n.get("mention_count", 0)
            topic = str(n.get("niche_topic", "")).title()
            lines.append(
                f"{d_emoji} **{topic}** — score `{score:.0f}` · {mentions} mentions"
            )
        lines.append("")

    # ── Trending genres ───────────────────────────────────────────────────────
    genres_seen: list[str] = []
    for c in (candidates or []):
        g = c.get("genre")
        if g and g not in genres_seen:
            genres_seen.append(g)
        if len(genres_seen) == 3:
            break
    if genres_seen:
        genre_tags = "  ".join(f"`{g}`" for g in genres_seen)
        lines.append(f"**🕹️ Hot Genres:** {genre_tags}")
        lines.append("")

    # ── Player sentiment ──────────────────────────────────────────────────────
    complaint_data = _load_json(proc_dir / "complaints.json")
    top_complaints = (complaint_data or {}).get("top_complaints", [])
    top_praises = (complaint_data or {}).get("top_praises", [])
    sentiment_parts: list[str] = []
    if top_praises:
        phrase, count, _ = top_praises[0]
        sentiment_parts.append(f"😍 **{phrase}** ×{count}")
    if top_complaints:
        phrase, count, _ = top_complaints[0]
        sentiment_parts.append(f"😤 **{phrase}** ×{count}")
    if sentiment_parts:
        lines.append("**💬 Player Pulse:** " + "   ·   ".join(sentiment_parts))
        lines.append("")

    # ── Google Trends breakout ────────────────────────────────────────────────
    breakout_data = _load_json(raw_dir / "trends_breakout.json")
    breakout_queries = (breakout_data or {}).get("breakout_queries", [])[:4]
    if breakout_queries:
        bq_tags = "  ".join(f"`{q}`" for q in breakout_queries)
        lines.append(f"**🔥 Trends Breakout:** {bq_tags}")
        lines.append("")

    # ── New releases ──────────────────────────────────────────────────────────
    diff_data = _load_json(proc_dir / "history_diff.json")
    newly = (diff_data or {}).get("newly_detected_apps", [])[:2]
    if newly:
        lines.append("**🆕 Just Detected**")
        for app in newly:
            app_id = app.get("appId") or app.get("id") or ""
            play_url = (
                f"https://play.google.com/store/apps/details?id={app_id}"
                if app_id else ""
            )
            link = f" → <{play_url}>" if play_url else ""
            genre = _safe(app.get("genre"))
            lines.append(f"▸ **{_safe(app.get('title'))}** · `{genre}`{link}")
        lines.append("")

    # ── Footer ────────────────────────────────────────────────────────────────
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📎 *Full report attached above*")

    message = "\n".join(lines)
    if len(message) > config.DISCORD_MAX_MESSAGE_CHARS:
        message = message[: config.DISCORD_MAX_MESSAGE_CHARS - 3] + "..."
    return message


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build(today: date | None = None, meta: dict | None = None) -> tuple[Path, str]:
    """
    Build the full markdown report and the Discord message.

    Returns (report_path, discord_message).
    """
    today = today or date.today()
    date_str = today.isoformat()
    meta = meta or {}

    proc_dir = Path(config.PROCESSED_DIR) / date_str
    raw_dir = Path(config.RAW_DIR) / date_str
    reports_dir = Path(config.REPORTS_DIR)
    reports_dir.mkdir(parents=True, exist_ok=True)

    report_path = reports_dir / f"{date_str}_report.md"

    logger.info("[builder] Building markdown report for %s", date_str)
    md = build_markdown(date_str, proc_dir, raw_dir, meta)
    _atomic_write(report_path, md)

    logger.info("[builder] Building Discord message")
    discord_msg = build_discord_message(date_str, proc_dir, raw_dir)

    logger.info(
        "[builder] Done. Report: %s (%d chars), Discord: %d chars",
        report_path,
        len(md),
        len(discord_msg),
    )
    return report_path, discord_msg


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    path, msg = build()
    print("Report:", path)
    print("Discord preview:\n", msg)
