# Mobile Game Market Intelligence

A fully automated, free-to-run pipeline that runs daily via GitHub Actions,
collects mobile game market data from multiple public sources, detects
emerging trends and underserved niches using deterministic code, then uses
Gemini 1.5 Flash to write a human-readable briefing posted to Discord.

**Code finds patterns. AI explains patterns.**

---

## Architecture

```
Collectors          Processors             Analyzers
───────────         ──────────             ─────────
google_play    -->  freshness         -->  trend_scorer
reddit         -->  normalizer        -->  niche_detector  --> Trends Pass 2
steam          -->  theme_extractor   -->  complaint_parser
trends (P1)                           -->  history_diff

AI                  Reports               Delivery
──                  ───────               ────────
synthesizer    -->  builder           -->  discord_webhook
```

---

## Setup (one-time, ~10 minutes)

### 1. Fork / clone this repo

```bash
git clone https://github.com/YOUR_USERNAME/niche-discover.git
cd niche-discover
```

### 2. Create a Reddit app

1. Go to [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps)
2. Click **Create another app...**
3. Choose type: **script**
4. Redirect URI: `http://localhost:8080`
5. Note the **client ID** (shown under the app name) and **client secret**

### 3. Get a Gemini API key (free tier)

1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Sign in with a Google account
3. Click **Get API key** → Create API key
4. Copy the key

### 4. Create a Discord webhook

1. Open a Discord server you control
2. **Server Settings** → **Integrations** → **Webhooks** → **New Webhook**
3. Choose a channel, give it a name, copy the webhook URL

### 5. Add GitHub Secrets

In your forked repository:
**Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret name            | Value                        |
|------------------------|------------------------------|
| `REDDIT_CLIENT_ID`     | From step 2                  |
| `REDDIT_CLIENT_SECRET` | From step 2                  |
| `REDDIT_USER_AGENT`    | e.g. `GameIntelBot/1.0`      |
| `GEMINI_API_KEY`       | From step 3                  |
| `DISCORD_WEBHOOK_URL`  | From step 4                  |

### 6. Enable GitHub Actions

Go to the **Actions** tab in your repo and enable workflows if prompted.

### 7. Trigger a first run manually

**Actions** → **Daily Market Intelligence Run** → **Run workflow**

This verifies everything works before the scheduled daily run begins.

---

## Schedule

The pipeline runs at **7:00 AM UTC** every day via cron.

You can also trigger it manually from the Actions tab at any time.

---

## What it produces

### Discord message (summary)
- Market overview (2 sentences from AI)
- Top 3 underserved niches (with Trends direction)
- Trending genres
- Google Trends breakout queries
- Top complaint / top praise
- New releases to watch

### Markdown report (attached file)
Full tables for:
- All trending apps with scores
- All niches with evidence
- Emerging themes
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
| Reddit | PRAW read-only API | Free |
| Steam | SteamSpy public API (no key) | Free |
| Google Trends | `pytrends` (unofficial) | Free |
| AI Briefing | Gemini 1.5 Flash (free tier) | Free |

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

## Running locally (for development)

```bash
pip install -r requirements.txt

# Set required env vars (PowerShell example)
$env:REDDIT_CLIENT_ID     = "your_id"
$env:REDDIT_CLIENT_SECRET = "your_secret"
$env:REDDIT_USER_AGENT    = "GameIntelBot/1.0"
$env:GEMINI_API_KEY       = "your_key"
$env:DISCORD_WEBHOOK_URL  = "your_webhook_url"

python main.py
```

Each module also has a standalone `if __name__ == "__main__"` test block
for isolated testing (see the Implementation Order in the spec).

---

## Hard constraints (by design)

- No paid APIs or services
- No local server required
- Zero manual steps after setup
- AI only receives pre-extracted evidence -- it cannot hallucinate data
- All file writes are atomic (`.tmp` then rename)
- One collector failing never stops the pipeline
