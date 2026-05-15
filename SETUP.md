# GitHub Setup Guide

Follow these steps exactly. Takes about 10 minutes total.

---

## Step 1 — Get Your API Keys

### Gemini API Key (free, 1 min)
1. Go to https://aistudio.google.com/app/apikey
2. Click **Create API key** → **Create API key in new project**
3. Copy the key (starts with `AIza...`)

### Discord Webhook URL (2 min)
1. Open Discord → go to a server you own (or create one)
2. Click the server name → **Server Settings**
3. Left sidebar → **Integrations** → **Webhooks**
4. Click **New Webhook** → choose a channel → give it a name
5. Click **Copy Webhook URL**

### Reddit (OPTIONAL — no account needed)
Reddit data is collected via the public JSON API with no credentials.
Just set the user agent string shown in Step 4.

---

## Step 2 — Create the GitHub Repository

1. Go to https://github.com/new
2. Fill in:
   - **Repository name**: `niche-discover`
   - **Visibility**: Public ← important (free Actions minutes are unlimited for public repos)
   - **DO NOT** check "Add a README file"
   - **DO NOT** add .gitignore or license
3. Click **Create repository**
4. Leave the page open — you will need the repo URL

---

## Step 3 — Push the Code

Open PowerShell in the `niche-discover` folder and run these commands
one at a time (replace `YOUR_USERNAME` with your GitHub username):

```powershell
git add -A
git commit -m "feat: initial pipeline"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/niche-discover.git
git push -u origin main
```

If asked to log in, use your GitHub username and a **Personal Access Token**
(not your password). Create one at:
https://github.com/settings/tokens/new
- Expiry: 90 days
- Scope: check **repo**
- Click Generate → copy the token → paste it as the password

---

## Step 4 — Add GitHub Secrets

Secrets are encrypted. GitHub Actions reads them as environment variables at runtime.
**Never put secrets in your code or commit them.**

1. Go to your repo on GitHub
2. Click **Settings** (top tab, not your profile settings)
3. Left sidebar → **Secrets and variables** → **Actions**
4. Click **New repository secret** for each row below:

| Secret Name | Value |
|---|---|
| `GEMINI_API_KEY` | Your key from Step 1 |
| `DISCORD_WEBHOOK_URL` | Your webhook URL from Step 1 |

Add them **one at a time**. The name must match exactly — GitHub secrets are case-sensitive.

---

## Step 5 — Enable GitHub Actions

1. Click the **Actions** tab in your repo
2. If you see a yellow warning banner saying workflows are disabled, click:
   **"I understand my workflows, go ahead and enable them"**
3. You should now see **Daily Market Intelligence Run** in the left sidebar

---

## Step 6 — Run It Manually (First Test)

Before waiting for the daily 7 AM UTC schedule, trigger a manual run:

1. **Actions** tab → click **Daily Market Intelligence Run** in the left sidebar
2. Click the **Run workflow** button (top right, next to the branch dropdown)
3. Select branch: `main`
4. Click the green **Run workflow** button

The run will start within ~30 seconds. Click into it to see live logs.
It takes about 8–10 minutes to complete.

---

## Step 7 — Verify It Worked

After the run finishes (all steps green):

✅ Check your Discord channel — you should see:
   - A summary message with trending genres, niches, and new releases
   - A `report.md` file attached with the full intelligence report

✅ Check your repo — a new commit should appear:
   - Message: `chore: update master history [skip ci]`
   - This updates `storage/master/app_history.json` with today's data

✅ Click **Artifacts** on the completed run page to download the full report

---

## Daily Schedule

The pipeline runs automatically at **7:00 AM UTC** every day.

| UTC | India (IST) | US Eastern | US Pacific |
|-----|------------|------------|------------|
| 7:00 AM | 12:30 PM | 3:00 AM | 12:00 AM |

To change the time, edit `.github/workflows/daily_run.yml` line 5:
```yaml
- cron: "0 7 * * *"   # format: minute hour * * *
```

---

## Troubleshooting

**Run fails at "Google Play collector"**
- Temporary network error — re-run manually. Google Play has occasional blocks.

**Run fails at "Reddit collector"**
- Reddit rate-limited the GitHub Actions IP. Wait 10 minutes and re-run.

**Gemini returns 404 or 429**
- 404 → wrong model name. The `config.py` uses `gemini-2.5-flash-lite` which works on free tier.
- 429 → rate limit hit. Free tier allows ~1500 requests/day. You are only using 1 per run.

**Discord shows no message**
- Check the `DISCORD_WEBHOOK_URL` secret — paste it fresh (no trailing spaces).
- Make sure the webhook was not deleted from Discord settings.

**"update master history" commit never appears**
- The pipeline needs write permission. Go to:
  Settings → Actions → General → scroll to "Workflow permissions"
  → select **Read and write permissions** → Save

---

## Free Tier Summary

| Service | Limit | Our usage |
|---------|-------|-----------|
| GitHub Actions (public repo) | Unlimited | ~10 min/day |
| Gemini 2.5 Flash Lite | 1500 req/day | 1 req/run |
| Reddit public JSON API | No auth limit | ~400 req/run |
| SteamSpy | No stated limit | ~10 req/run |
| Google Trends (pytrends) | Rate-limited per IP | ~3 req/run |
| Discord Webhooks | No stated limit | 2 req/run |

**Total cost: $0**

