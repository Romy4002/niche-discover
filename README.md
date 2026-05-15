# Mobile Game Market Intelligence

A fully automated, free-to-run pipeline that runs daily via GitHub Actions,
collects mobile game market data from multiple public sources, detects
emerging trends and underserved niches using deterministic code, then uses
Gemini 2.5 Flash Lite to write a human-readable briefing posted to Discord.

**Code finds patterns. AI explains patterns.**

---

## Architecture

```
Collectors          Processors             Analyzers
───────────         ──────────             ─────────
google_play    -->  freshness         -->  trend_scorer
reddit/feeds   -->  normalizer        -->  niche_detector  --> Trends Pass 2
steam          -->  theme_extractor   -->  complaint_parser
trends (P1)                           -->  history_diff

AI                  Reports               Delivery
──                  ───────               ────────
synthesizer    -->  builder           -->  discord_webhook
```

Reddit data is collected via the **public JSON API** — no account or API key required.
If Reddit IPs are blocked (e.g. on GitHub Actions), the collector automatically falls back to
TouchArcade RSS and Game Developer RSS feeds.

---

## Setup (one-time, ~10 minutes)

See `SETUP.md` for the full step-by-step guide. Quick summary:

### 1. Get a Gemini API key (free tier)

1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Click **Create API key** → **Create API key in new project**
3. Copy the key (starts with `AIza...`)

### 2. Create a Discord webhook

1. Open a Discord server you control
2. **Server Settings** → **Integrations** → **Webhooks** → **New Webhook**
3. Choose a channel, give it a name, copy the webhook URL

### 3. Add GitHub Secrets

In your repository: **Settings** → **Secrets and variables** → **Actions**

| Secret name           | Value                   |
|-----------------------|-------------------------|
| `GEMINI_API_KEY`      | Your key from step 1    |
| `DISCORD_WEBHOOK_URL` | Your webhook from step 2|

That's it. **No Reddit credentials needed.**

### 4. Enable GitHub Actions

Go to the **Actions** tab and enable workflows if prompted.
Set workflow permissions to **Read and write** under Settings → Actions → General.

### 5. Trigger a first run manually

**Actions** → **Daily Market Intelligence Run** → **Run workflow**

---

## Schedule

The pipeline runs at **3:20 AM UTC** every day (delivers by ~9:00 AM IST).

| UTC     | IST (India) | US Eastern | US Pacific |
|---------|-------------|------------|------------|
| 3:20 AM | 8:50 AM     | 11:20 PM   | 8:20 PM    |

You can also trigger it manually from the Actions tab at any time.

---

## What it produces

### Discord message (summary)
- Market overview (2 sentences from AI briefing)
- Top 3 underserved niches with Trends direction
- Trending genres
- Top complaint / top praise
- New releases to watch with Play Store links

### Markdown report (attached file)
Full tables for:
- All trending apps with scores
- All niches with evidence
- Emerging themes (TF-IDF)
- Player complaints + praises
- Steam mechanic tags
- Newly detected apps
- Trend velocity (7-day acceleration)
- Run metadata

---

## Data Sources

| Source | Method | Cost |
|--------|--------|------|
| Google Play | `google-play-scraper` (Python lib) | Free |
| Reddit | Public JSON API — no auth required | Free |
| TouchArcade | RSS feed (fallback when Reddit is blocked) | Free |
| Game Developer | RSS feed (fallback when Reddit is blocked) | Free |
| Steam | SteamSpy public API (no key needed) | Free |
| Google Trends | `pytrends` (unofficial) | Free |
| AI Briefing | Gemini 2.5 Flash Lite (free tier) | Free |

---

## Storage layout

```
storage/
  raw/YYYY-MM-DD/          -- raw collector output (gitignored)
  processed/YYYY-MM-DD/    -- analyzer output (gitignored)
  reports/                 -- final markdown reports (gitignored)
  master/                  -- rolling 30-day history (git-tracked)
    app_history.json
    theme_history.json
```

Only `storage/master/` is committed to the repo. Everything else is
rebuilt fresh each run and uploaded as a GitHub Actions artifact.

---

## Running locally

```powershell
pip install -r requirements.txt

# Set required env vars
$env:GEMINI_API_KEY      = "your_key"
$env:DISCORD_WEBHOOK_URL = "your_webhook_url"

python main.py
```

Reddit data will be collected automatically — no credentials needed.

---

## Hard constraints (by design)

- No paid APIs or services
- No Reddit account or API credentials required
- No local server required
- Zero manual steps after setup
- AI only receives pre-extracted evidence — it cannot hallucinate data
- All file writes are atomic (`.tmp` then rename)
- One collector failing never stops the pipeline
