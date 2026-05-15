"""
reports/builder.py
===================
Assembles two outputs from all processed data:

1. Full markdown report:  storage/reports/YYYY-MM-DD_report.md
2. Discord plain-text:    returned as a string (max 1800 chars)

The markdown report is the attachment; the plain-text is the message body.
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

    # â”€â”€ AI Briefing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    briefing_path = proc_dir / "ai_briefing.txt"
    briefing = briefing_path.read_text(encoding="utf-8") if briefing_path.exists() else "[AI briefing not available]"
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(briefing)
    lines.append("")

    # â”€â”€ Trending Apps â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Underserved Niches â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Google Trends Breakout Queries â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Emerging Themes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Player Complaints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Player Praises â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    lines.append("## Player Praises")
    lines.append("")
    top_praises = (complaint_data or {}).get("top_praises", [])
    if top_praises:
        for phrase, count, _ in top_praises[:8]:
            lines.append(f"- **{phrase}** ({count}x)")
    else:
        lines.append("_No praise data._")
    lines.append("")

    # â”€â”€ Steam Mechanic Signals â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Newly Detected Apps â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Trend Velocity â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Run Metadata â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
# Discord message builder
# ---------------------------------------------------------------------------

def build_discord_message(
    date_str: str,
    proc_dir: Path,
    raw_dir: Path,
) -> str:
    """
    Build a concise Discord message (max 1800 chars) from processed data.
    """
    parts: list[str] = []
    parts.append(f"**Mobile Game Intel -- {date_str}**")
    parts.append("")

    # Market overview: extract clean prose sentences from briefing (skip markdown headers)
    briefing_path = proc_dir / "ai_briefing.txt"
    if briefing_path.exists():
        full = briefing_path.read_text(encoding="utf-8")
        prose_lines = [
            l.strip().lstrip("*#> ").strip()
            for l in full.splitlines()
            if l.strip()
            and not l.startswith("[")          # skip fallback notes
            and not l.startswith("#")          # skip markdown headers
            and not l.startswith("**1.")       # skip section headers like **1. Market Overview**
            and not l.startswith("**2.")
            and len(l.strip()) > 40            # skip very short lines
        ]
        overview = " ".join(prose_lines[:2])[:300]
        parts.append(overview)
        parts.append("")

    # Top niches
    niche_data = _load_json(proc_dir / "niches.json")
    top_niches = (niche_data or {}).get("top_niches", [])[:3]
    if top_niches:
        parts.append("**Top Niches Today**")
        for n in top_niches:
            direction = _safe(n.get("trends_direction"))
            parts.append(
                f"- {n.get('niche_topic')} ({direction}) -- "
                f"{n.get('niche_score', 0):.1f} score"
            )
        parts.append("")

    # Trending genres
    trend_data = _load_json(proc_dir / "trend_scores.json")
    candidates = (trend_data or {}).get("trending_candidates", [])[:10]
    genres_seen: list[str] = []
    for c in candidates:
        g = c.get("genre")
        if g and g not in genres_seen:
            genres_seen.append(g)
        if len(genres_seen) == 3:
            break
    if genres_seen:
        parts.append("**Trending Genres**")
        parts.append(", ".join(genres_seen))
        parts.append("")

    # Google Trends breakout
    breakout_data = _load_json(raw_dir / "trends_breakout.json")
    breakout_queries = (breakout_data or {}).get("breakout_queries", [])[:3]
    if breakout_queries:
        parts.append("**Google Trends Breakout**")
        parts.append(", ".join(breakout_queries))
        parts.append("")

    # Player signal
    complaint_data = _load_json(proc_dir / "complaints.json")
    top_complaints = (complaint_data or {}).get("top_complaints", [])
    top_praises = (complaint_data or {}).get("top_praises", [])
    if top_complaints or top_praises:
        parts.append("**Player Signal**")
        if top_complaints:
            phrase, count, _ = top_complaints[0]
            parts.append(f"Top complaint: {phrase} ({count}x)")
        if top_praises:
            phrase, count, _ = top_praises[0]
            parts.append(f"Top praise: {phrase} ({count}x)")
        parts.append("")

    # New releases to watch
    diff_data = _load_json(proc_dir / "history_diff.json")
    newly = (diff_data or {}).get("newly_detected_apps", [])[:3]
    if newly:
        parts.append("**New Releases to Watch**")
        for app in newly:
            app_id = app.get("appId") or app.get("id") or ""
            play_url = (
                f"https://play.google.com/store/apps/details?id={app_id}"
                if app_id else ""
            )
            link = f" (<{play_url}>)" if play_url else ""
            parts.append(
                f"- **{_safe(app.get('title'))}**{link}\n"
                f"  {_safe(app.get('genre'))} · {_safe(app.get('freshness_label'))}"
            )
        parts.append("")

    parts.append("_(Full report attached)_")

    message = "\n".join(parts)
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
    print("Discord preview:\n", msg[:400])


