"""
ai/synthesizer.py
==================
Builds a structured evidence packet from all processed data and sends it
to Gemini 2.5 Flash Lite to generate a 600-word human-readable briefing.

The AI ONLY receives pre-extracted evidence. It cannot access any
external data or APIs.

Fallback: if Gemini API call fails, returns a structured-data summary
without AI narration (pipeline continues normally).

Output: storage/processed/YYYY-MM-DD/ai_briefing.txt
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types as genai_types

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


def _safe_str(v: Any, default: str = "n/a") -> str:
    return str(v) if v is not None else default


# ---------------------------------------------------------------------------
# Evidence packet builder
# ---------------------------------------------------------------------------

def _build_evidence_packet(date_str: str, proc_dir: Path, raw_dir: Path) -> str:
    """
    Assemble the structured evidence string that is sent to Gemini.
    All data comes from pre-computed JSON files.
    """
    lines: list[str] = []
    lines.append(f"=== MOBILE GAME MARKET INTELLIGENCE -- {date_str} ===")
    lines.append("")

    # -- Trending Apps -------------------------------------------------------
    lines.append("## TRENDING APPS (top 10 by trend_score)")
    trend_data = _load_json(proc_dir / "trend_scores.json")
    candidates = (trend_data or {}).get("trending_candidates", [])[:10]
    if candidates:
        lines.append(
            "| Rank | Title | Genre | Trend Score | Freshness | Trends Direction |"
        )
        lines.append("|------|-------|-------|-------------|-----------|-----------------|")
        for i, app in enumerate(candidates, 1):
            lines.append(
                f"| {i} | {_safe_str(app.get('title'))} "
                f"| {_safe_str(app.get('genre'))} "
                f"| {_safe_str(app.get('trend_score'))} "
                f"| {_safe_str(app.get('freshness_label'))} "
                f"| {_safe_str(app.get('trends_direction'))} |"
            )
    else:
        lines.append("No trending apps data available.")
    lines.append("")

    # -- Underserved Niches --------------------------------------------------
    lines.append("## UNDERSERVED NICHES (top 5 by final rank)")
    niche_data = _load_json(proc_dir / "niches.json")
    top_niches = (niche_data or {}).get("top_niches", [])[:5]
    if top_niches:
        lines.append(
            "| Niche Topic | Reddit Mentions | Matching Apps | Niche Score | "
            "Trends Direction | Explicit Demand |"
        )
        lines.append(
            "|-------------|-----------------|---------------|-------------|"
            "-----------------|-----------------|"
        )
        for n in top_niches:
            lines.append(
                f"| {_safe_str(n.get('niche_topic'))} "
                f"| {_safe_str(n.get('mention_count'))} "
                f"| {_safe_str(n.get('matching_app_count'))} "
                f"| {_safe_str(n.get('niche_score'))} "
                f"| {_safe_str(n.get('trends_direction'))} "
                f"| {_safe_str(n.get('explicit_demand_signals'))} |"
            )
    else:
        lines.append("No niche data available.")
    lines.append("")

    # -- Google Trends Breakout Queries --------------------------------------
    lines.append("## GOOGLE TRENDS BREAKOUT QUERIES (rising this week)")
    breakout_data = _load_json(raw_dir / "trends_breakout.json")
    breakout_queries = (breakout_data or {}).get("breakout_queries", [])
    if breakout_queries:
        for q in breakout_queries[:15]:
            lines.append(f"- {q}")
    else:
        lines.append("No breakout queries data available.")
    lines.append("")

    # -- Emerging Themes -----------------------------------------------------
    lines.append("## EMERGING THEMES (new this week)")
    diff_data = _load_json(proc_dir / "history_diff.json")
    emerging = (diff_data or {}).get("emerging_themes", [])[:10]
    theme_data = _load_json(proc_dir / "themes.json")
    candidate_themes = (theme_data or {}).get("candidate_themes", [])[:5]
    if emerging:
        for t in emerging:
            lines.append(f"- {t.get('theme')} (score: {t.get('score_today', 0):.4f})")
    elif candidate_themes:
        for label, phrases in candidate_themes:
            lines.append(f"- {label}: {', '.join(phrases)}")
    else:
        lines.append("No emerging themes data.")
    lines.append("")

    # -- Player Complaints ---------------------------------------------------
    lines.append("## PLAYER COMPLAINTS (top 10 by frequency)")
    complaint_data = _load_json(proc_dir / "complaints.json")
    top_complaints = (complaint_data or {}).get("top_complaints", [])[:10]
    if top_complaints:
        lines.append("| Complaint | Count | Category |")
        lines.append("|-----------|-------|----------|")
        for phrase, count, category in top_complaints:
            lines.append(f"| {phrase} | {count} | {category} |")
    else:
        lines.append("No complaint data available.")
    lines.append("")

    # -- Player Praises ------------------------------------------------------
    lines.append("## PLAYER PRAISES (top 5)")
    top_praises = (complaint_data or {}).get("top_praises", [])[:5]
    if top_praises:
        for phrase, count, _ in top_praises:
            lines.append(f"- {phrase} ({count}x)")
    else:
        lines.append("No praise data available.")
    lines.append("")

    # -- Newly Detected Apps -------------------------------------------------
    lines.append("## NEWLY DETECTED APPS TODAY")
    newly = (diff_data or {}).get("newly_detected_apps", [])[:10]
    if newly:
        lines.append("| Title | Genre | Freshness | Description |")
        lines.append("|-------|-------|-----------|-------------|")
        for app in newly:
            desc = str(app.get("description") or "")[:60]
            lines.append(
                f"| {_safe_str(app.get('title'))} "
                f"| {_safe_str(app.get('genre'))} "
                f"| {_safe_str(app.get('freshness_label'))} "
                f"| {desc} |"
            )
    else:
        lines.append("No newly detected apps.")
    lines.append("")

    # -- Steam Mechanic Trends -----------------------------------------------
    lines.append("## STEAM MECHANIC TRENDS (top tags this week)")
    steam_data = _load_json(raw_dir / "steam_raw.json")
    top_tags = (steam_data or {}).get("top_tags", [])[:15]
    if top_tags:
        lines.append("| Tag | Vote Count |")
        lines.append("|-----|------------|")
        for tag, votes in top_tags:
            lines.append(f"| {tag} | {votes} |")
    else:
        lines.append("No Steam tag data available.")
    lines.append("")

    # -- Trend Velocity ------------------------------------------------------
    lines.append("## TREND VELOCITY (accelerating from last 7 days)")
    accelerating = (diff_data or {}).get("accelerating_apps", [])[:10]
    if accelerating:
        lines.append("| App Title | Score 7d Ago | Score Today | Delta |")
        lines.append("|-----------|-------------|-------------|-------|")
        for app in accelerating:
            lines.append(
                f"| {_safe_str(app.get('title'))} "
                f"| {_safe_str(app.get('score_7d_ago'))} "
                f"| {_safe_str(app.get('trend_score'))} "
                f"| +{_safe_str(app.get('trend_velocity'))} |"
            )
    else:
        lines.append("No accelerating apps detected (first run or stable week).")
    lines.append("")

    lines.append("=== END OF EVIDENCE ===")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------------

_INSTRUCTION = """
You are a mobile game market analyst. Based ONLY on the evidence above -- \
do not add information not present in the data -- write a market intelligence \
briefing with these sections:

1. Market Overview (2-3 sentences)
2. Trending Genres & Mechanics (what the data shows)
3. Underserved Niches (concrete opportunities with evidence; prioritize niches \
confirmed by both Reddit demand AND rising Google Trends signal)
4. Player Sentiment (complaints and praises summary)
5. Notable New Releases (brief)
6. Strategic Observations (cross-source patterns only)
7. One-Line Conclusion

Write in clear, professional language. Be specific.
Do not invent trends not present in the data.
Max 600 words.
"""


def synthesize(today: date | None = None) -> str:
    """
    Build evidence packet and call Gemini to write the briefing.
    Falls back to a plain evidence-only note on API failure.

    Returns the briefing text; writes ai_briefing.txt to storage.
    """
    today = today or date.today()
    date_str = today.isoformat()

    proc_dir = Path(config.PROCESSED_DIR) / date_str
    raw_dir = Path(config.RAW_DIR) / date_str
    proc_dir.mkdir(parents=True, exist_ok=True)
    out_path = proc_dir / "ai_briefing.txt"

    evidence = _build_evidence_packet(date_str, proc_dir, raw_dir)
    prompt = evidence + "\n\n" + _INSTRUCTION

    # -- Configure Gemini ----------------------------------------------------
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("[synthesizer] GEMINI_API_KEY not set -- using fallback")
        fallback = f"[AI synthesis unavailable -- GEMINI_API_KEY not set]\n\n{evidence}"
        _atomic_write(out_path, fallback)
        return fallback

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=config.AI_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                max_output_tokens=config.AI_MAX_OUTPUT_TOKENS,
                temperature=0.3,
            ),
        )
        briefing = response.text
        logger.info("[synthesizer] Gemini response received (%d chars)", len(briefing))
    except Exception as exc:
        logger.warning("[synthesizer] Gemini API call failed: %s", exc)
        briefing = (
            f"[AI synthesis unavailable -- API error: {exc}]\n\n"
            "The following structured data was collected but could not be narrated:\n\n"
            + evidence
        )

    _atomic_write(out_path, briefing)
    logger.info("[synthesizer] Briefing written to %s", out_path)
    return briefing


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = synthesize()
    print(result[:500])

