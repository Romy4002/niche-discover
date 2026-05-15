"""
config.py -- Central configuration for the mobile game market intelligence pipeline.
All thresholds, lists, and constants live here.
Secrets (API keys, tokens) are loaded from environment variables at runtime -- never here.
"""

# --- Google Play --------------------------------------------------------------

GOOGLE_PLAY_CATEGORIES: list[str] = [
    "action", "puzzle", "strategy", "rpg", "simulation",
    "casual", "adventure", "arcade", "sports", "card",
]
GOOGLE_PLAY_RESULTS_PER_CATEGORY: int = 50

# --- Freshness thresholds (days) ---------------------------------------------

FRESHNESS_NEW_DAYS: int = 30
FRESHNESS_RECENT_DAYS: int = 90
FRESHNESS_ESTABLISHING: int = 180

# --- Legacy scoring ----------------------------------------------------------

LEGACY_SIGNAL_THRESHOLD: int = 3
LEGACY_RATINGS_HIGH: int = 500_000
LEGACY_RATINGS_MID: int = 100_000
LEGACY_INSTALLS_MASSIVE: int = 50_000_000
LEGACY_AGE_DAYS_STRONG: int = 365
LEGACY_AGE_DAYS_MODERATE: int = 180

KNOWN_LEGACY_PUBLISHERS: list[str] = [
    "com.supercell", "com.king", "com.gameloft", "com.ea.",
    "com.zynga", "com.kabam", "com.glu", "com.jam.",
    "com.miniclip", "com.outfit7", "com.imangi", "com.kiloo",
    "com.halfbrick", "com.rovio", "com.playtika",
]

KNOWN_LEGACY_TITLE_PATTERNS: list[str] = [
    r"roblox", r"free fire", r"pubg", r"clash (of|royale)",
    r"candy crush", r"subway surfers", r"temple run",
    r"pokemon go", r"brawl stars", r"hay day", r"boom beach",
    r"mobile legends", r"honor of kings",
]

# --- Reddit ------------------------------------------------------------------

REDDIT_SUBREDDITS: list[str] = [
    "AndroidGaming", "iosgaming", "indiegaming",
    "gamedev", "patientgamers", "SteamDeals", "MobileGaming",
]
REDDIT_POSTS_PER_SUB: int = 50
REDDIT_COMMENT_THRESHOLD: int = 50
REDDIT_MAX_COMMENTS: int = 20
REDDIT_SELFTEXT_MAX_CHARS: int = 500

# --- Google Trends -----------------------------------------------------------

TRENDS_BATCH_SIZE: int = 5
TRENDS_SLEEP_BETWEEN: int = 5          # seconds between batches (reduce 400s)
TRENDS_RETRY_SLEEP: int = 60
TRENDS_TIMEFRAME_VALIDATE: str = "today 3-m"   # "now X-m" is not valid in pytrends
TRENDS_TIMEFRAME_BREAKOUT: str = "now 7-d"
TRENDS_BREAKOUT_SEED: str = "mobile games"
TRENDS_BREAKOUT_TOP_N: int = 15
TRENDS_RISING_THRESHOLD: float = 1.2
TRENDS_DECLINING_THRESHOLD: float = 0.8

# --- Niche detection ---------------------------------------------------------

NICHE_MIN_MENTIONS: int = 3
NICHE_MAX_SUPPLY: int = 10
NICHE_SCORE_THRESHOLD: float = 2.0
NICHE_EXPLICIT_DEMAND_BONUS: float = 2.0
NICHE_TOP_N: int = 10

NICHE_EXPLICIT_DEMAND_PHRASES: list[str] = [
    "i wish there was a game that",
    "no good mobile version",
    "needs a mobile port",
    "surprisingly no mobile game",
    "someone should make",
]

# --- Trend scoring -----------------------------------------------------------

TREND_TOP_N: int = 20
TREND_REDDIT_POINTS_PER_MENTION: int = 3
TREND_REDDIT_CAP: int = 15
TREND_STEAM_MECHANIC_BONUS: int = 4
TREND_EARLY_TRACTION_BONUS: int = 2
TREND_MULTI_CHART_BONUS: int = 2
TREND_RISING_BONUS: int = 5
TREND_NEW_SIGNAL_BONUS: int = 3
TREND_DECLINING_PENALTY: int = -4
TREND_TRACTION_MIN_RATINGS: int = 500
TREND_TRACTION_MAX_DAYS: int = 180

# --- History / diff ----------------------------------------------------------

HISTORY_WINDOW_DAYS: int = 30

# --- Complaint / praise phrases ----------------------------------------------

COMPLAINT_PHRASES: dict[str, str] = {
    "hate": "gameplay", "broken": "technical",
    "pay to win": "monetization", "p2w": "monetization",
    "too expensive": "monetization", "boring": "gameplay",
    "repetitive": "gameplay", "no content": "content",
    "abandoned": "content", "dead game": "content",
    "energy system": "monetization", "ads": "monetization",
    "too many ads": "monetization", "crashes": "technical",
    "unplayable": "technical", "rigged": "gameplay",
    "unfair": "gameplay", "pay wall": "monetization",
    "predatory": "monetization", "no endgame": "content",
    "nothing to do": "content", "pay or wait": "monetization",
}

PRAISE_PHRASES: dict[str, str] = {
    "addicted": "gameplay", "gem": "gameplay",
    "hidden gem": "gameplay", "underrated": "gameplay",
    "amazing": "gameplay", "love this": "gameplay",
    "best mobile": "gameplay", "recommend": "gameplay",
    "solid": "gameplay", "finally a game": "gameplay",
    "scratches that itch": "gameplay", "no ads": "monetization",
    "fair monetization": "monetization", "great value": "monetization",
    "worth buying": "monetization",
}

# --- TF-IDF theme extraction -------------------------------------------------

TFIDF_CUSTOM_STOPWORDS: list[str] = [
    "game", "games", "play", "playing", "played", "mobile",
    "android", "ios", "free", "download", "update", "new",
    "best", "top", "good", "great", "love", "like", "app",
    "version", "season", "event", "limited", "bundle",
]

TFIDF_TOP_UNIGRAMS: int = 50
TFIDF_TOP_BIGRAMS: int = 30

# --- AI ----------------------------------------------------------------------

AI_MODEL: str = "gemini-2.5-flash-lite"
AI_MAX_OUTPUT_TOKENS: int = 1000

# --- Discord -----------------------------------------------------------------

DISCORD_MAX_MESSAGE_CHARS: int = 1800

# --- Storage paths -----------------------------------------------------------

STORAGE_ROOT: str = "storage"
RAW_DIR: str = "storage/raw"
PROCESSED_DIR: str = "storage/processed"
REPORTS_DIR: str = "storage/reports"
MASTER_DIR: str = "storage/master"
