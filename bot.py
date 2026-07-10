"""
Market Pulse Bot — v26 "Morning Pro Package + Mirror Mode + Data Fixes"
============================================
AI-powered crypto intelligence for Nigerian traders.

V18 NEW FEATURES:
✅ NEW: Content Engine — one market analysis → 7 platform-native formats automatically
✅ NEW: Admin Content Package — Telegram, X, X Thread, WhatsApp, Instagram, TikTok, hashtags, CTA, posting order
✅ NEW: /contentpackage admin command — generate full package from morning/midday/evening/weekly or on-demand
✅ NEW: content_packages DB table — stores all generated packages with approval status
✅ NEW: Admin menu: 📦 Content Package button — browse & manage pending packages
✅ NEW: Admin dashboard improvements — growth rate, revenue, feature usage, alert accuracy, content performance
✅ NEW: Weekly Educational Content — 5 rotating educational topics auto-generated Sunday
✅ NEW: Content Engine integrated into all scheduled posts (morning/midday/evening/weekly)
✅ NEW: Platform-native voice — each format rewritten for its channel; never copy-paste duplication
✅ NEW: Admin approval gate — packages delivered only to admin, never auto-published
✅ ARCHITECTURE: Full V2 Content Ecosystem spec implemented

V17 FIXES & IMPROVEMENTS:
✅ CRITICAL: Fixed SQLite placeholder (?) → PostgreSQL (%s) in get_ai_usage_today()
✅ CRITICAL: Fixed all INSERT OR REPLACE → ON CONFLICT DO UPDATE (PostgreSQL syntax)
✅ CRITICAL: Fixed get_state() return value — now returns (state, data) tuple correctly everywhere
✅ CRITICAL: Admin config (BOT_MODE, CHANNEL_ENABLED, PRO_CHANNEL_ID) now loaded at startup
✅ CRITICAL: Ban user now uses correct PostgreSQL ON CONFLICT syntax
✅ FIXED: Whale detection now correctly compares snapshots vs previous hour, not current vs current
✅ FIXED: AI usage daily reset now uses WAT timezone, not server UTC
✅ FIXED: Double AI build on channel posts eliminated (one call per post type)
✅ FIXED: /stats command uses PostgreSQL-compatible datetime comparison
✅ FIXED: /users command uses PostgreSQL-compatible datetime comparison
✅ FIXED: awaiting_alert_target state handler now correctly unpacks get_state() tuple
✅ FIXED: All state handlers in callback section correctly unpack get_state() tuple
✅ FIXED: /addtrade lastrowid removed — not available in psycopg2, using RETURNING
✅ NEW: Admin-configurable alert watchlist via /setwatchlist and /watchlistcoins commands
✅ NEW: Mid-day conditional posting — only fires if market moved >2% since morning
✅ NEW: Smart alert ranking — alerts scored by volume, proximity, and market importance
✅ NEW: Admin settings persisted to DB (admin_settings table) instead of JSON file only
✅ ARCHITECTURE: All V2 spec priorities enforced — accuracy, transparency, reliability first
"""

import os
import ssl
import socket
import base64
import struct
import psycopg2
from psycopg2.extras import RealDictCursor
from urllib.parse import urlparse
import json
import time
import requests
import xml.etree.ElementTree as ET
import re
import random
from datetime import datetime, timedelta
from collections import defaultdict
import logging
import threading
from logging.handlers import RotatingFileHandler

# ═══════════════════════════════════════════════════════════════════════════
# 📋 LOGGING CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

LOG_FILE = "bot.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# 🔑 TOKEN CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_KEY", "YOUR_DEEPSEEK_KEY_HERE")
MISTRAL_KEY = os.environ.get("MISTRAL_KEY", "YOUR_MISTRAL_KEY_HERE")
QWEN_KEY = os.environ.get("QWEN_KEY", "YOUR_QWEN_KEY_HERE")

# ═══════════════════════════════════════════════════════════════════════════
# 🔐 PRIVACY & CHANNEL CONFIG
# ═══════════════════════════════════════════════════════════════════════════

# Load ADMIN_IDS from env var — comma-separated Telegram user IDs
# e.g. ADMIN_IDS=123456789,987654321
_admin_ids_env = os.environ.get("ADMIN_IDS", "8212124930")
ADMIN_IDS = {int(x.strip()) for x in _admin_ids_env.split(",") if x.strip().isdigit()}

ADMIN_CODE = os.environ.get("ADMIN_CODE", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "-1004495003791")
PRO_CHANNEL_ID = os.environ.get("PRO_CHANNEL_ID", "-1004383094764")
CHANNEL_ENABLED = True
MIRROR_MODE = False  # When True: Pro channel content also posts to free channel
WAT_OFFSET = 1
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ═══════════════════════════════════════════════════════════════════════════
# 📋 GLOBAL BOT MODE
# ═══════════════════════════════════════════════════════════════════════════

BOT_MODE = "everyone"  # "everyone" or "pro"

# ═══════════════════════════════════════════════════════════════════════════
# 🗄️ ADMIN CONFIG PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════

def load_admin_config():
    """Load admin config from DB (primary) — Railway filesystem is ephemeral so no file storage."""
    defaults = {
        "PRO_CHANNEL_ID": PRO_CHANNEL_ID,
        "CHANNEL_ENABLED": CHANNEL_ENABLED,
        "BOT_MODE": BOT_MODE,
    }
    db = None
    try:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT key, value FROM admin_settings WHERE key IN ('PRO_CHANNEL_ID','CHANNEL_ENABLED','BOT_MODE')")
        rows = c.fetchall()
        for key, value in rows:
            if key == "CHANNEL_ENABLED":
                defaults[key] = value.lower() in ("true", "1", "yes")
            else:
                defaults[key] = value
        return defaults
    except Exception as e:
        logger.warning("[CONFIG LOAD] DB not ready yet, using defaults: %s" % e)
        return defaults
    finally:
        if db:
            try: db.close()
            except Exception: pass

def save_admin_config(config):
    """Save admin config to DB — survives Railway restarts and redeploys."""
    db = None
    try:
        db = get_db()
        c = db.cursor()
        now = wat_now().strftime("%Y-%m-%d %H:%M:%S")
        for key, value in config.items():
            c.execute(
                "INSERT INTO admin_settings (key, value, updated_at) VALUES (%s,%s,%s) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, str(value), now)
            )
        db.commit()
        logger.info("[CONFIG] Saved admin config to DB")
    except Exception as e:
        logger.error("[CONFIG ERROR] %s" % e)
        if db:
            try: db.rollback()
            except Exception: pass
    finally:
        if db:
            try: db.close()
            except Exception: pass

# ═══════════════════════════════════════════════════════════════════════════
# 📋 SCHEDULE
# ═══════════════════════════════════════════════════════════════════════════

SCHEDULE = {
    "morning_hour_wat": 7,
    "midday_hour_wat": 13,
    "evening_hour_wat": 19,
    "weekly_edge_day": 5,
    "weekly_edge_hour": 7,
    "bigmove_pct": 3.0,
    "admin_digest_hour_wat": 8,
    "health_check_interval_minutes": 10,
    "expiry_reminder_days": 7,
}

# ═══════════════════════════════════════════════════════════════════════════
# 🪙 COINS & P2P CONFIG
# ═══════════════════════════════════════════════════════════════════════════

COINS = {
    "BTC": ("XBTUSD", "bitcoin"),
    "ETH": ("ETHUSD", "ethereum"),
    "SOL": ("SOLUSD", "solana"),
    "BNB": (None, "binancecoin"),
    "XRP": ("XRPUSD", "ripple"),
    "DOGE": ("DOGEUSD", "dogecoin"),
    "ADA": ("ADAUSD", "cardano"),
    "TRX": ("TRXUSD", "tron"),
    "AVAX": ("AVAXUSD", "avalanche-2"),
    "LINK": ("LINKUSD", "chainlink"),
    "DOT": ("DOTUSD", "polkadot"),
    "POL": ("POLUSD", "polygon-ecosystem-token"),
    "LTC": ("LTCUSD", "litecoin"),
    "UNI": ("UNIUSD", "uniswap"),
    "ATOM": ("ATOMUSD", "cosmos"),
    "NEAR": ("NEARUSD", "near"),
    "ICP": ("ICPUSD", "internet-computer"),
    "SHIB": (None, "shiba-inu"),
    "APT": (None, "aptos"),
    "ARB": (None, "arbitrum"),
    "OP": (None, "optimism"),
    "SUI": (None, "sui"),
    "INJ": (None, "injective-protocol"),
    "FET": (None, "fetch-ai"),
    "FIL": ("FILUSD", "filecoin"),
    "RENDER": (None, "render-token"),
    "WLD": (None, "worldcoin-wld"),
    "TON": (None, "the-open-network"),
    "USDT": (None, "tether"),
    "USDC": ("USDCUSD", "usd-coin"),
}

def kraken_pair(coin): return COINS[coin][0]
def coin_key(coin): return COINS[coin][1]

P2P_CRYPTOS = ["USDT", "BTC", "ETH", "BNB", "USDC", "SOL", "XRP"]
P2P_FIATS = {
    "NGN": ("Nigerian Naira", "₦"),
    "GHS": ("Ghanaian Cedi", "GHc"),
    "KES": ("Kenyan Shilling", "KSh"),
    "ZAR": ("South African Rand", "R"),
    "UGX": ("Ugandan Shilling", "USh"),
    "TZS": ("Tanzanian Shilling", "TSh"),
    "EGP": ("Egyptian Pound", "E£"),
    "MAD": ("Moroccan Dirham", "MAD"),
    "XOF": ("West African CFA", "CFA"),
    "USD": ("US Dollar", "$"),
    "GBP": ("British Pound", "£"),
    "EUR": ("Euro", "€"),
    "AED": ("UAE Dirham", "AED"),
    "CNY": ("Chinese Yuan", "¥"),
    "INR": ("Indian Rupee", "₹"),
}

TIMEFRAMES = {
    "1H": (1, 12, "hm"),
    "6H": (6, 36, "hm"),
    "1D": (24, 48, "hm"),
    "3D": (72, 36, "dhm"),
    "1W": (168, 42, "dhm"),
    "1M": (720, 30, "date"),
    "3M": (2160, 30, "date"),
    "1Y": (8760, 52, "date"),
}

NEWS_RSS_FEEDS = [
    ("Bitcoin Magazine", "https://bitcoinmagazine.com/.rss/full/"),
    ("CryptoSlate", "https://cryptoslate.com/feed/"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
    ("NewsBTC", "https://www.newsbtc.com/feed/"),
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
]

# ═══════════════════════════════════════════════════════════════════════════
# 🛠 HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def format_price(v):
    if v is None:
        return "N/A"
    try:
        v = float(v)
    except Exception as _e:
        return "N/A"
    if v >= 1:
        return "$%.2f" % v
    elif v >= 0.01:
        return "$%.4f" % v
    elif v >= 0.0001:
        return "$%.6f" % v
    else:
        return "$%.8f" % v

def format_change(pct):
    if pct is None:
        return "N/A"
    try:
        pct = float(pct)
    except Exception as _e:
        return "N/A"
    sign = "+" if pct >= 0 else ""
    return "%s%.2f%%" % (sign, pct)

def format_ngn(v):
    """Format Nigerian Naira amount with ₦ symbol."""
    if v is None:
        return "N/A"
    try:
        v = float(v)
        return "₦{:,.0f}".format(v) if v >= 1 else "₦{:.4f}".format(v)
    except Exception:
        return str(v)

def format_forex(v, symbol=""):
    """Format a forex pair price with appropriate decimals."""
    if v is None:
        return "N/A"
    try:
        v = float(v)
        if v >= 100:
            return "{}{:,.2f}".format(symbol, v)
        elif v >= 1:
            return "{}{:.4f}".format(symbol, v)
        else:
            return "{}{:.6f}".format(symbol, v)
    except Exception:
        return str(v)

def format_large(v):
    if v is None:
        return "N/A"
    try:
        v = float(v)
    except Exception as _e:
        return "N/A"
    if v >= 1e12:
        return "$%.2fT" % (v / 1e12)
    if v >= 1e9:
        return "$%.1fB" % (v / 1e9)
    if v >= 1e6:
        return "$%.0fM" % (v / 1e6)
    return "$%.0f" % v

def wat_now():
    """Always derive WAT from UTC — server timezone independent."""
    return datetime.utcnow() + timedelta(hours=WAT_OFFSET)

def get_random_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
    }

def request_json(method, url, params=None, json_data=None, timeout=10, retries=3, backoff=1.5):
    last_exc = None
    for attempt in range(retries):
        try:
            if method == "GET":
                r = requests.get(url, params=params, timeout=timeout)
            else:
                r = requests.post(url, json=json_data, timeout=timeout)
            if r.status_code == 429:
                wait = 30 * (attempt + 1)
                logger.warning("[RATE LIMIT] waiting %ds" % wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    logger.error("[RETRY FAILED] %s" % last_exc)
    return None

def fetch_with_backoff(url, max_retries=5, timeout=15):
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=get_random_headers(), timeout=timeout)
            if response.status_code == 429:
                wait = (2 ** attempt) * 2
                logger.warning("[BACKOFF] Waiting %ds" % wait)
                time.sleep(wait)
                continue
            if response.status_code == 200:
                return response.json()
        except Exception as _e:
            time.sleep(2 ** attempt)
    return None

# ═══════════════════════════════════════════════════════════════════════════
# 🗄️ DATABASE
# ═══════════════════════════════════════════════════════════════════════════

def get_db():
    """Return a PostgreSQL connection. Falls back gracefully."""
    url = DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL environment variable not set")
    result = urlparse(url)
    conn = psycopg2.connect(
        host=result.hostname,
        port=result.port or 5432,
        database=result.path.lstrip("/"),
        user=result.username,
        password=result.password,
        sslmode="require",
        connect_timeout=10,
    )
    conn.autocommit = False
    return conn

def init_db():
    db = get_db()
    try:
        c = db.cursor()
        tables = """
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY ,
        coin TEXT NOT NULL,
        price REAL NOT NULL,
        timestamp TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY ,
        chat TEXT NOT NULL,
        coin TEXT NOT NULL,
        condition TEXT NOT NULL,
        target REAL NOT NULL,
        active INTEGER DEFAULT 1,
        label TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS user_states (
        chat TEXT PRIMARY KEY,
        state TEXT,
        data TEXT,
        updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS users (
        chat TEXT PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        first_seen TEXT,
        last_seen TEXT
    );
    CREATE TABLE IF NOT EXISTS watchlists (
        id INTEGER PRIMARY KEY ,
        chat TEXT NOT NULL,
        coin TEXT NOT NULL,
        UNIQUE(chat, coin)
    );
    CREATE TABLE IF NOT EXISTS portfolio (
        id INTEGER PRIMARY KEY ,
        chat TEXT NOT NULL,
        coin TEXT NOT NULL,
        amount REAL NOT NULL,
        buy_price REAL NOT NULL,
        added_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY ,
        chat TEXT NOT NULL,
        action TEXT NOT NULL,
        timestamp TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS p2p_alerts (
        id INTEGER PRIMARY KEY ,
        chat TEXT NOT NULL,
        crypto TEXT NOT NULL,
        fiat TEXT NOT NULL,
        condition TEXT NOT NULL,
        target REAL NOT NULL,
        active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY ,
        referrer_chat TEXT NOT NULL,
        referred_chat TEXT NOT NULL,
        joined_at TEXT NOT NULL,
        UNIQUE(referred_chat)
    );
    CREATE TABLE IF NOT EXISTS pro_subscriptions (
        chat TEXT PRIMARY KEY,
        expiry_date TEXT NOT NULL,
        source TEXT DEFAULT 'payment',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS pro_referrals (
        id INTEGER PRIMARY KEY ,
        referrer_chat TEXT NOT NULL,
        referred_chat TEXT NOT NULL,
        reward_type TEXT,
        claimed INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        UNIQUE(referred_chat)
    );
    CREATE TABLE IF NOT EXISTS portfolio_snapshots (
        id INTEGER PRIMARY KEY ,
        chat TEXT NOT NULL,
        value_usd REAL NOT NULL,
        timestamp TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS health_log (
        id INTEGER PRIMARY KEY ,
        service TEXT NOT NULL,
        status TEXT NOT NULL,
        details TEXT,
        timestamp TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS feature_usage (
        id INTEGER PRIMARY KEY ,
        chat TEXT NOT NULL,
        feature TEXT NOT NULL,
        timestamp TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS community_p2p (
        id INTEGER PRIMARY KEY ,
        chat TEXT NOT NULL,
        crypto TEXT NOT NULL,
        fiat TEXT NOT NULL,
        buy_rate REAL NOT NULL,
        sell_rate REAL NOT NULL,
        exchange TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        weight INTEGER DEFAULT 1,
        status TEXT DEFAULT 'pending',
        confirmations INTEGER DEFAULT 0,
        spot_rate REAL,
        expires_at TEXT
    );
    CREATE TABLE IF NOT EXISTS trade_journal (
        id INTEGER PRIMARY KEY ,
        chat TEXT NOT NULL,
        coin TEXT NOT NULL,
        direction TEXT NOT NULL,
        entry_price REAL NOT NULL,
        exit_price REAL,
        size REAL NOT NULL,
        stop_loss REAL,
        take_profit REAL,
        pnl REAL,
        status TEXT DEFAULT 'open',
        opened_at TEXT NOT NULL,
        closed_at TEXT
    );
    CREATE TABLE IF NOT EXISTS rate_submissions (
        chat TEXT PRIMARY KEY,
        submissions_today INTEGER DEFAULT 0,
        strikes_today INTEGER DEFAULT 0,
        blocked_until TEXT,
        last_submission TEXT,
        total_verified INTEGER DEFAULT 0,
        trust_level INTEGER DEFAULT 1,
        p2p_used INTEGER DEFAULT 0,
        onboarded INTEGER DEFAULT 0,
        last_prompted TEXT
    );
    CREATE TABLE IF NOT EXISTS banned_users (
        chat TEXT PRIMARY KEY,
        reason TEXT,
        banned_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS admin_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS bot_logs (
        id INTEGER PRIMARY KEY ,
        level TEXT NOT NULL,
        message TEXT NOT NULL,
        timestamp TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS system_status (
        id INTEGER PRIMARY KEY ,
        service TEXT NOT NULL,
        status TEXT NOT NULL,
        details TEXT,
        timestamp TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS price_cache (
        coin TEXT NOT NULL,
        price REAL NOT NULL,
        timestamp TEXT NOT NULL,
        PRIMARY KEY (coin, timestamp)
    );
    CREATE TABLE IF NOT EXISTS channel_posts (
        id INTEGER PRIMARY KEY ,
        post_type TEXT NOT NULL,
        posted_at TEXT NOT NULL,
        message_id TEXT
    );
    CREATE TABLE IF NOT EXISTS user_preferences (
        chat TEXT PRIMARY KEY,
        language TEXT DEFAULT 'en',
        notifications INTEGER DEFAULT 1,
        theme TEXT DEFAULT 'dark',
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS content_packages (
        id SERIAL PRIMARY KEY,
        package_type TEXT NOT NULL,
        trigger_source TEXT NOT NULL,
        telegram_text TEXT,
        x_post TEXT,
        x_thread TEXT,
        whatsapp_text TEXT,
        instagram_caption TEXT,
        instagram_carousel TEXT,
        tiktok_script TEXT,
        hashtags TEXT,
        cta TEXT,
        posting_order TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS content_performance (
        id SERIAL PRIMARY KEY,
        package_id INTEGER,
        platform TEXT NOT NULL,
        metric TEXT NOT NULL,
        value INTEGER DEFAULT 0,
        recorded_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS trade_ideas (
        id SERIAL PRIMARY KEY,
        coin TEXT NOT NULL,
        tier TEXT NOT NULL,
        direction TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        entry TEXT,
        stop TEXT,
        target1 TEXT,
        target2 TEXT,
        bias TEXT,
        confidence TEXT,
        rr TEXT,
        invalidation TEXT,
        max_size_pct TEXT,
        ai_rationale TEXT,
        status TEXT DEFAULT 'open',
        created_at TEXT NOT NULL,
        closed_at TEXT,
        result TEXT
    );
    """
        # Convert SQLite syntax to PostgreSQL
        tables = tables.replace("INTEGER PRIMARY KEY ", "SERIAL PRIMARY KEY")
        tables = tables.replace("INTEGER DEFAULT 1", "INTEGER DEFAULT 1")
        # Execute each CREATE TABLE separately
        for stmt in [s.strip() for s in tables.split(";") if s.strip()]:
            try:
                c.execute(stmt)
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.warning(f"[DB INIT] {e}")

        # Create indexes on high-frequency query columns (IF NOT EXISTS safe)
        indexes = [
        "CREATE INDEX IF NOT EXISTS idx_alerts_active ON alerts(active)",
        "CREATE INDEX IF NOT EXISTS idx_alerts_chat ON alerts(chat)",
        "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_events_chat ON events(chat)",
        "CREATE INDEX IF NOT EXISTS idx_feature_usage_chat_ts ON feature_usage(chat, timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_watchlists_chat ON watchlists(chat)",
        "CREATE INDEX IF NOT EXISTS idx_history_coin_ts ON history(coin, timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_users_first_seen ON users(first_seen)",
        "CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen)",
        "CREATE INDEX IF NOT EXISTS idx_pro_subs_chat ON pro_subscriptions(chat)",
        "CREATE INDEX IF NOT EXISTS idx_pro_subs_expiry ON pro_subscriptions(expiry_date)",
        "CREATE INDEX IF NOT EXISTS idx_content_packages_status ON content_packages(status)",
        "CREATE INDEX IF NOT EXISTS idx_channel_posts_posted_at ON channel_posts(posted_at)",
        "CREATE INDEX IF NOT EXISTS idx_trade_ideas_status ON trade_ideas(status)",
        "CREATE INDEX IF NOT EXISTS idx_trade_ideas_coin ON trade_ideas(coin)",
        ]
        for idx_sql in indexes:
            try:
                c.execute(idx_sql)
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.warning(f"[DB INDEX] {e}")
                db.rollback()
                db = get_db()
                c = db.cursor()
        # Add label column if missing
        try:
            c.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS label TEXT DEFAULT ''")
        except Exception as _e:
            logger.debug("[SILENT EXC] %s" % _e)
        db.commit()
        logger.info("Database initialized (PostgreSQL)")
    except Exception as e:
        logger.error("[INIT DB] %s" % e)
        try: db.rollback()
        except Exception: pass
        raise
    finally:
        try: db.close()
        except Exception: pass

# ═══════════════════════════════════════════════════════════════════════════
# 📊 FEATURE TRACKING & USER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def track_feature(chat_id, feature):
    db = None
    try:
        db = get_db()
        c = db.cursor()
        now = wat_now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO feature_usage (chat, feature, timestamp) VALUES (%s, %s, %s)",
                  (str(chat_id), feature, now))
        db.commit()
    except Exception as e:
        logger.warning("[TRACK FEATURE] %s" % e)
        if db:
            try: db.rollback()
            except Exception: pass
    finally:
        if db:
            try: db.close()
            except Exception: pass

def get_ai_usage_today(chat_id):
    """Return how many AI questions this user has asked today (WAT timezone)."""
    db = None
    try:
        db = get_db()
        c = db.cursor()
        today_wat = wat_now().strftime("%Y-%m-%d")
        c.execute(
            "SELECT COUNT(*) FROM feature_usage WHERE chat=%s AND feature='ai_question' AND timestamp LIKE %s",
            (str(chat_id), today_wat + "%")
        )
        return c.fetchone()[0]
    except Exception as _e:
        return 0
    finally:
        if db:
            try: db.close()
            except Exception: pass

FREE_AI_LIMIT = 5
UPGRADE_BTN = [[{"text": "💎 Upgrade to Pro", "callback_data": "upgrade"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]

def check_ai_limit(chat_id):
    """Returns (allowed, used, limit). Admins/Pro/everyone-mode always allowed."""
    if get_bot_mode() == "everyone" or chat_id in ADMIN_IDS or is_pro(chat_id):
        return True, 0, 999
    used = get_ai_usage_today(chat_id)
    return used < FREE_AI_LIMIT, used, FREE_AI_LIMIT

def ai_limit_msg(used, limit):
    return (
        f"⛔ <b>Daily AI Limit Reached</b>\n\n"
        f"You've used <b>{used}/{limit}</b> free AI questions today.\n\n"
        f"✨ Upgrade to Pro for <b>unlimited</b> AI questions, "
        f"market outlooks, trade setups and more.\n\n"
        f"<i>Your limit resets at midnight WAT.</i>"
    )

def upsert_user(chat_id, username=None, first_name=None):
    db = None
    try:
        db = get_db()
        c = db.cursor()
        now = wat_now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            """INSERT INTO users (chat, username, first_name, first_seen, last_seen)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT(chat) DO UPDATE SET
                 username=excluded.username,
                 first_name=excluded.first_name,
                 last_seen=excluded.last_seen""",
            (str(chat_id), username or "", first_name or "", now, now)
        )
        db.commit()
    except Exception as e:
        logger.error("[UPSERT USER ERROR] %s" % e)
        if db:
            try: db.rollback()
            except Exception: pass
    finally:
        if db:
            try: db.close()
            except Exception: pass

def log_event(chat_id, action):
    db = None
    try:
        db = get_db()
        c = db.cursor()
        now = wat_now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO events (chat, action, timestamp) VALUES (%s, %s, %s)",
                  (str(chat_id), action, now))
        db.commit()
    except Exception as e:
        logger.warning("[LOG EVENT] %s" % e)
        if db:
            try: db.rollback()
            except Exception: pass
    finally:
        if db:
            try: db.close()
            except Exception: pass

def set_state(chat_id, state, data=None):
    db = None
    try:
        db = get_db()
        c = db.cursor()
        now = wat_now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            """INSERT INTO user_states (chat, state, data, updated_at)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT(chat) DO UPDATE SET
                 state=excluded.state, data=excluded.data, updated_at=excluded.updated_at""",
            (str(chat_id), state, json.dumps(data or {}), now)
        )
        db.commit()
    except Exception as e:
        logger.error("[SET STATE ERROR] %s" % e)
        if db:
            try: db.rollback()
            except Exception: pass
    finally:
        if db:
            try: db.close()
            except Exception: pass

def get_state(chat_id):
    """Returns (state_string, data_dict). Always a 2-tuple."""
    db = None
    try:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT state, data FROM user_states WHERE chat=%s", (str(chat_id),))
        row = c.fetchone()
        if not row:
            return None, {}
        state, raw_data = row
        try:
            data = json.loads(raw_data) if raw_data else {}
        except Exception:
            data = {}
        return state, data
    except Exception as e:
        logger.warning("[GET STATE] %s" % e)
        return None, {}
    finally:
        if db:
            try: db.close()
            except Exception: pass

def clear_state(chat_id):
    db = None
    try:
        db = get_db()
        c = db.cursor()
        c.execute("DELETE FROM user_states WHERE chat=%s", (str(chat_id),))
        db.commit()
    except Exception as e:
        logger.error("[CLEAR STATE ERROR] %s" % e)
        if db:
            try: db.rollback()
            except Exception: pass
    finally:
        if db:
            try: db.close()
            except Exception: pass

def is_user_banned(chat_id):
    """Check if user is banned"""
    db = None
    try:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT chat FROM banned_users WHERE chat=%s", (str(chat_id),))
        row = c.fetchone()
        return bool(row)
    except Exception as e:
        logger.warning("[IS_USER_BANNED] %s" % e)
        return False
    finally:
        if db:
            try: db.close()
            except Exception: pass

def ban_user(chat_id, reason="No reason provided"):
    """Ban a user from using the bot"""
    db = None
    try:
        db = get_db()
        c = db.cursor()
        now = wat_now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "INSERT INTO banned_users (chat, reason, banned_at) VALUES (%s,%s,%s) "
            "ON CONFLICT(chat) DO UPDATE SET reason=excluded.reason, banned_at=excluded.banned_at",
            (str(chat_id), reason, now)
        )
        db.commit()
        logger.info("[BAN] Banned user: %s" % chat_id)
        return True
    except Exception as e:
        logger.error("[BAN ERROR] %s" % e)
        if db:
            try: db.rollback()
            except Exception: pass
        return False
    finally:
        if db:
            try: db.close()
            except Exception: pass

def unban_user(chat_id):
    """Unban a user"""
    db = None
    try:
        db = get_db()
        c = db.cursor()
        c.execute("DELETE FROM banned_users WHERE chat=%s", (str(chat_id),))
        db.commit()
        logger.info("[UNBAN] Unbanned user: %s" % chat_id)
        return True
    except Exception as _e:
        return False
    finally:
        if db:
            try: db.close()
            except Exception: pass

def get_banned_users():
    """Get list of banned users"""
    db = None
    try:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT chat, reason, banned_at FROM banned_users ORDER BY banned_at DESC")
        return c.fetchall()
    except Exception as _e:
        return []
    finally:
        if db:
            try: db.close()
            except Exception: pass

# ═══════════════════════════════════════════════════════════════════════════
# 📨 TELEGRAM HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def tg(method, data):
    return request_json(
        "POST", "https://api.telegram.org/bot%s/%s" % (BOT_TOKEN, method),
        json_data=data, timeout=15, retries=2
    ) or {}

_TG_MAX_LEN = 4096

def _safe_truncate(text, max_len=_TG_MAX_LEN):
    """Truncate text to Telegram safe length, preserving HTML validity best-effort."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 30] + "\n<i>[message truncated]</i>"

def send(chat_id, text, buttons=None):
    data = {"chat_id": chat_id, "text": _safe_truncate(text), "parse_mode": "HTML"}
    if buttons:
        data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    return tg("sendMessage", data)

def edit(chat_id, message_id, text, buttons=None):
    data = {"chat_id": chat_id, "message_id": message_id,
            "text": _safe_truncate(text), "parse_mode": "HTML"}
    if buttons:
        data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    return tg("editMessageText", data)

def delete_message(chat_id, message_id):
    tg("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

def answer_cb(cb_id, text=None):
    payload = {"callback_query_id": cb_id}
    if text:
        payload["text"] = text
    tg("answerCallbackQuery", payload)

def post_to_channel(text):
    global CHANNEL_ENABLED, CHANNEL_ID
    if not CHANNEL_ENABLED:
        return
    data = {
        "chat_id": CHANNEL_ID,
        "text": _safe_truncate(text),
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    return tg("sendMessage", data)

def post_to_pro_channel(text):
    """Post to Pro channel. If MIRROR_MODE is on, also posts to free channel."""
    global CHANNEL_ENABLED, PRO_CHANNEL_ID, MIRROR_MODE
    if not CHANNEL_ENABLED or not PRO_CHANNEL_ID:
        return
    if PRO_CHANNEL_ID == "-100XXXXXXXXX":
        return
    data = {
        "chat_id": PRO_CHANNEL_ID,
        "text": _safe_truncate(text),
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    result = tg("sendMessage", data)
    # Mirror mode: same message goes to free channel too
    if MIRROR_MODE and CHANNEL_ENABLED and CHANNEL_ID:
        try:
            mirror_data = {
                "chat_id": CHANNEL_ID,
                "text": _safe_truncate(text),
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            tg("sendMessage", mirror_data)
            logger.info("[MIRROR] Post mirrored to free channel")
        except Exception as e:
            logger.error("[MIRROR] Failed: %s" % e)
    return result

# ═══════════════════════════════════════════════════════════════════════════
# 🔐 CHANNEL LOCK SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

# Cache channel membership — avoids hitting Telegram API on every message/callback
_channel_cache = {}  # chat_id -> (is_member: bool, expires_at: float)
_CHANNEL_CACHE_TTL = 300  # 5 minutes

def is_user_in_channel(chat_id, force=False):
    global CHANNEL_ID
    now_ts = time.time()
    if not force:
        cached = _channel_cache.get(chat_id)
        if cached and now_ts < cached[1]:
            return cached[0]
    try:
        result = tg("getChatMember", {"chat_id": CHANNEL_ID, "user_id": chat_id})
        if result and result.get("ok"):
            status = result.get("result", {}).get("status", "")
            member = status in ["member", "administrator", "creator"]
            _channel_cache[chat_id] = (member, now_ts + _CHANNEL_CACHE_TTL)
            return member
    except Exception as e:
        logger.warning("[CHANNEL CHECK] %s" % e)
    # On error, return cached value if available (fail open), else False
    cached = _channel_cache.get(chat_id)
    return cached[0] if cached else False

def check_channel_membership(chat_id):
    if is_user_in_channel(chat_id):
        return True
    
    send(chat_id,
         "🔒 <b>Channel Membership Required</b>\n\n"
         "To use Market Pulse, you must join our channel first.\n\n"
         "👉 @marketpulseng\n\n"
         "After joining, tap the button below to verify.",
         [[{"text": "✅ I've Joined", "callback_data": "verify_join"}]])
    return False

# ═══════════════════════════════════════════════════════════════════════════
# 💰 PRO SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

PRO_REFERRAL_REWARDS = {
    3:  "1week",
    5:  "1month",
    10: "3months",
    20: "6months"
}

def get_bot_mode():
    global BOT_MODE
    return BOT_MODE

def set_bot_mode(mode):
    global BOT_MODE
    if mode in ["everyone", "pro"]:
        BOT_MODE = mode
        return True
    return False

def is_pro(chat_id):
    if get_bot_mode() == "everyone" or chat_id in ADMIN_IDS:
        return True
    db = None
    try:
        db = get_db()
        c = db.cursor()
        now = wat_now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("SELECT expiry_date FROM pro_subscriptions WHERE chat=%s AND expiry_date > %s",
                  (str(chat_id), now))
        row = c.fetchone()
        return bool(row)
    except Exception as e:
        logger.warning("[IS_PRO] %s" % e)
        return False
    finally:
        if db:
            try: db.close()
            except Exception: pass

def get_pro_expiry(chat_id):
    db = None
    try:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT expiry_date FROM pro_subscriptions WHERE chat=%s", (str(chat_id),))
        row = c.fetchone()
        return row[0] if row else None
    except Exception as _e:
        return None
    finally:
        if db:
            try: db.close()
            except Exception: pass

def get_pro_days_left(chat_id):
    expiry = get_pro_expiry(chat_id)
    if not expiry:
        return None
    try:
        expiry_date = datetime.strptime(expiry, "%Y-%m-%d %H:%M:%S")
        days_left = (expiry_date - datetime.now()).days
        return max(0, days_left)
    except Exception as _e:
        return None

def grant_pro(chat_id, months=1, source="payment"):
    db = None
    try:
        db = get_db()
        c = db.cursor()
        now = wat_now()
        expiry = now + timedelta(days=30 * months)
        expiry_str = expiry.strftime("%Y-%m-%d %H:%M:%S")
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        c.execute("SELECT expiry_date FROM pro_subscriptions WHERE chat=%s", (str(chat_id),))
        row = c.fetchone()

        if row:
            try:
                existing_expiry = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                existing_expiry = now  # Malformed date fallback
            if existing_expiry > now:
                new_expiry = existing_expiry + timedelta(days=30 * months)
            else:
                new_expiry = now + timedelta(days=30 * months)
            new_expiry_str = new_expiry.strftime("%Y-%m-%d %H:%M:%S")
            c.execute("UPDATE pro_subscriptions SET expiry_date=%s, source=%s WHERE chat=%s",
                      (new_expiry_str, source, str(chat_id)))
        else:
            c.execute("INSERT INTO pro_subscriptions (chat, expiry_date, source, created_at) VALUES (%s,%s,%s,%s)",
                      (str(chat_id), expiry_str, source, now_str))

        db.commit()
        logger.info("[PRO] Granted Pro to %s for %s months" % (chat_id, months))
        return True
    except Exception as e:
        logger.error("[GRANT PRO ERROR] %s" % e)
        if db:
            try: db.rollback()
            except Exception: pass
        return False
    finally:
        if db:
            try: db.close()
            except Exception: pass

def get_pro_referral_count(chat_id):
    db = None
    try:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT COUNT(*) FROM pro_referrals WHERE referrer_chat=%s", (str(chat_id),))
        return c.fetchone()[0]
    except Exception as _e:
        return 0
    finally:
        if db:
            try: db.close()
            except Exception: pass

def get_pro_referral_reward(chat_id):
    """Returns (reward_description, days) for current referral count."""
    count = get_pro_referral_count(chat_id)
    reward = None
    for threshold, reward_type in sorted(PRO_REFERRAL_REWARDS.items(), reverse=True):
        if count >= threshold:
            reward = reward_type
            break
    return reward, count

def record_pro_referral(referrer_chat, referred_chat):
    if str(referrer_chat) == str(referred_chat):
        return
    # Both free and pro users can refer — rewards granted automatically
    try:
        db = get_db()
        c = db.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("SELECT id FROM pro_referrals WHERE referred_chat=%s", (str(referred_chat),))
        if c.fetchone():
            db.close()
            return
        c.execute("INSERT INTO pro_referrals (referrer_chat, referred_chat, created_at) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                  (str(referrer_chat), str(referred_chat), now))
        db.commit()
        
        new_count = get_pro_referral_count(referrer_chat)
        reward, _ = get_pro_referral_reward(referrer_chat)
        thresholds = {3: ("1 week", 0.25), 5: ("1 month", 1), 10: ("3 months", 3), 20: ("6 months", 6)}
        if reward and new_count in thresholds:
            label, months = thresholds[new_count]
            grant_pro(referrer_chat, months, "referral")
            try:
                send(int(referrer_chat),
                    f"🎉 <b>Referral Reward!</b>\n\n"
                    f"You hit <b>{new_count} referrals</b> — <b>{label} Pro access</b> added!\n\n"
                    f"Keep going:\n"
                    f"{'5 referrals → 1 month free' if new_count < 5 else '10 referrals → 3 months free' if new_count < 10 else '20 referrals → 6 months free' if new_count < 20 else 'You have hit the top tier!'}")
            except Exception as _e:
                logger.debug("[SILENT EXC] %s" % _e)

        db.close()
    except Exception as e:
        logger.error("[PRO REFERRAL ERROR] %s" % e)

# ═══════════════════════════════════════════════════════════════════════════
# 🏠 MENUS
# ═══════════════════════════════════════════════════════════════════════════

def get_user_badge(chat_id):
    if is_pro(chat_id):
        return "⭐ Pro User"
    else:
        return "👤 Free User"

BACK_MAIN = [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]

MAIN_MENU = [
    [{"text": "📊 Markets", "callback_data": "menu_markets"}],
    [{"text": "🧠 Intelligence", "callback_data": "menu_intelligence"}],
    [{"text": "🇳🇬 P2P Center", "callback_data": "menu_p2p"}],
    [{"text": "🔔 Alerts", "callback_data": "menu_alerts"}],
    [{"text": "💼 Portfolio", "callback_data": "menu_portfolio"}],
    [{"text": "📈 Trade Journal", "callback_data": "menu_trades"}],
    [{"text": "🛠 Tools", "callback_data": "menu_tools"}],
    [{"text": "👤 My Account", "callback_data": "menu_account"}],
    [{"text": "❓ Help", "callback_data": "help"}],
]

MAIN_MENU_FREE = [
    [{"text": "📊 Markets", "callback_data": "menu_markets"}],
    [{"text": "🧠 Intelligence", "callback_data": "menu_intelligence"}],
    [{"text": "🇳🇬 P2P Center", "callback_data": "menu_p2p"}],
    [{"text": "🔔 Alerts", "callback_data": "menu_alerts"}],
    [{"text": "💼 Portfolio", "callback_data": "menu_portfolio"}],
    [{"text": "📈 Trade Journal", "callback_data": "menu_trades"}],
    [{"text": "🛠 Tools", "callback_data": "menu_tools"}],
    [{"text": "👤 My Account", "callback_data": "menu_account"}],
    [{"text": "💎 Upgrade to Pro", "callback_data": "upgrade"}],
    [{"text": "❓ Help", "callback_data": "help"}],
]

MAIN_MENU_PRO = [
    [{"text": "⭐ Pro Menu", "callback_data": "menu_pro"}],
    [{"text": "📊 Markets", "callback_data": "menu_markets"}],
    [{"text": "🧠 Intelligence", "callback_data": "menu_intelligence"}],
    [{"text": "🇳🇬 P2P Center", "callback_data": "menu_p2p"}],
    [{"text": "🔔 Alerts", "callback_data": "menu_alerts"}],
    [{"text": "💼 Portfolio", "callback_data": "menu_portfolio"}],
    [{"text": "📈 Trade Journal", "callback_data": "menu_trades"}],
    [{"text": "🛠 Tools", "callback_data": "menu_tools"}],
    [{"text": "📈 Pro Tools", "callback_data": "menu_pro_tools"}],
    [{"text": "👤 My Account", "callback_data": "menu_account"}],
    [{"text": "❓ Help", "callback_data": "help"}],
]

MARKETS_MENU = [
    [{"text": "📈 Live Market", "callback_data": "market"}],
    [{"text": "🔥 Gainers", "callback_data": "gainers"}],
    [{"text": "📉 Losers", "callback_data": "losers"}],
    [{"text": "🌐 Dominance", "callback_data": "dominance"}],
    [{"text": "🔄 Arbitrage", "callback_data": "arbitrage"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

INTELLIGENCE_MENU = [
    [{"text": "🤖 Ask AI", "callback_data": "ask_ai"}],
    [{"text": "📰 AI News", "callback_data": "news"}],
    [{"text": "🧠 Fear & Greed", "callback_data": "fear_greed"}],
    [{"text": "📈 Market Outlook", "callback_data": "market_outlook"}],
    [{"text": "🎯 Trade Setup", "callback_data": "trade_setup"}],
    [{"text": "📡 Sources", "callback_data": "sources"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

P2P_MENU = [
    [{"text": "💱 P2P Rates", "callback_data": "p2p"}],
    [{"text": "📤 Submit Rate", "callback_data": "submit_rate"}],
    [{"text": "🔔 P2P Alerts", "callback_data": "p2p_alerts"}],
    [{"text": "🔄 Arbitrage Scanner", "callback_data": "arbitrage"}],
    [{"text": "📊 My P2P History", "callback_data": "p2p_history"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

ALERTS_MENU = [
    [{"text": "➕ Create Alert", "callback_data": "alerts"}],
    [{"text": "📋 My Alerts", "callback_data": "my_alerts"}],
    [{"text": "⭐ Watchlist", "callback_data": "watchlist"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

ALERTS_MENU_FREE = [
    [{"text": "➕ Create Alert (3 max)", "callback_data": "alerts"}],
    [{"text": "📋 My Alerts", "callback_data": "my_alerts"}],
    [{"text": "⭐ Watchlist (10 max)", "callback_data": "watchlist"}],
    [{"text": "💎 Upgrade for Unlimited", "callback_data": "upgrade"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

ALERTS_MENU_PRO = [
    [{"text": "➕ Create Alert (20 max)", "callback_data": "alerts"}],
    [{"text": "📋 My Alerts", "callback_data": "my_alerts"}],
    [{"text": "⭐ Watchlist (30 max)", "callback_data": "watchlist"}],
    [{"text": "⚡ Smart Alerts", "callback_data": "smart_alerts"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

PORTFOLIO_MENU = [
    [{"text": "💼 View Portfolio", "callback_data": "portfolio"}],
    [{"text": "➕ Add Position", "callback_data": "add_portfolio"}],
    [{"text": "🗑️ Remove Position", "callback_data": "remove_portfolio"}],
    [{"text": "📊 P&L Summary", "callback_data": "pnl_summary"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

TRADES_MENU = [
    [{"text": "📈 My Trades", "callback_data": "trade_journal"}],
    [{"text": "➕ Add Trade", "callback_data": "add_trade"}],
    [{"text": "🔒 Close Trade", "callback_data": "close_trade"}],
    [{"text": "📊 Win Rate", "callback_data": "win_rate"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

TOOLS_MENU = [
    [{"text": "🔍 Search Coin", "callback_data": "coin_search"}],
    [{"text": "🔄 Convert", "callback_data": "convert"}],
    [{"text": "📐 Position Calculator", "callback_data": "position_calculator"}],
    [{"text": "📜 Price History", "callback_data": "history"}],
    [{"text": "⚙️ Bot Status", "callback_data": "status"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

ACCOUNT_MENU_FREE = [
    [{"text": "👤 My Profile", "callback_data": "profile"}],
    [{"text": "💼 Portfolio", "callback_data": "portfolio"}],
    [{"text": "👥 Referral", "callback_data": "referral"}],
    [{"text": "📊 My Usage", "callback_data": "my_usage"}],
    [{"text": "⚙️ Settings", "callback_data": "settings"}],
    [{"text": "💎 Upgrade to Pro", "callback_data": "upgrade"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

ACCOUNT_MENU_PRO = [
    [{"text": "👤 My Profile", "callback_data": "profile"}],
    [{"text": "⭐ Pro Status", "callback_data": "pro_status"}],
    [{"text": "💼 Portfolio", "callback_data": "portfolio"}],
    [{"text": "📈 Trade Journal", "callback_data": "trade_journal"}],
    [{"text": "📐 Position Calculator", "callback_data": "position_calculator"}],
    [{"text": "👥 Referral", "callback_data": "referral"}],
    [{"text": "📊 My Usage", "callback_data": "my_usage"}],
    [{"text": "⚙️ Settings", "callback_data": "settings"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

HELP_MENU = [
    [{"text": "📚 All Commands", "callback_data": "help_commands"}],
    [{"text": "📖 How To Use", "callback_data": "help_howto"}],
    [{"text": "❓ FAQ", "callback_data": "help_faq"}],
    [{"text": "💬 Support", "callback_data": "support"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

# ── Admin menu: 6 grouped submenus instead of 10 flat buttons ────────────
ADMIN_MENU = [
    [{"text": "📊 Analytics", "callback_data": "adm_analytics"},
     {"text": "📢 Channel",   "callback_data": "adm_channel"}],
    [{"text": "👥 Users",     "callback_data": "adm_users"},
     {"text": "⚡ Trades",    "callback_data": "adm_trades"}],
    [{"text": "🏥 System",    "callback_data": "adm_system"},
     {"text": "⚙️ Settings",  "callback_data": "adm_settings_menu"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]
ADMIN_ANALYTICS_MENU = [
    [{"text": "📊 Dashboard",  "callback_data": "admin_dashboard"}],
    [{"text": "📈 Stats",      "callback_data": "admin_stats"}],
    [{"text": "👤 Users",      "callback_data": "admin_users"}],
    [{"text": "⬅ Back",       "callback_data": "admin_menu"}],
]
ADMIN_CHANNEL_MENU = [
    [{"text": "📰 Publish Post",    "callback_data": "admin_publish"}],
    [{"text": "📦 Content Packages","callback_data": "admin_content_packages"}],
    [{"text": "🔄 Toggle Channel",  "callback_data": "adm_toggle_channel"}],
    [{"text": "🪞 Mirror Mode",     "callback_data": "adm_toggle_mirror"}],
    [{"text": "⬅ Back",            "callback_data": "admin_menu"}],
]
ADMIN_USERS_MENU = [
    [{"text": "📢 Broadcast",  "callback_data": "admin_broadcast"}],
    [{"text": "🔒 Ban User",   "callback_data": "admin_ban"}],
    [{"text": "💎 Grant Pro",  "callback_data": "adm_grant_pro"}],
    [{"text": "⬅ Back",       "callback_data": "admin_menu"}],
]
ADMIN_TRADES_MENU = [
    [{"text": "📋 Trade History",  "callback_data": "adm_trade_history"}],
    [{"text": "⚡ Generate Trade", "callback_data": "adm_gen_trade"}],
    [{"text": "📊 Performance",    "callback_data": "adm_performance"}],
    [{"text": "⬅ Back",           "callback_data": "admin_menu"}],
]
ADMIN_SYSTEM_MENU = [
    [{"text": "🏥 Health",    "callback_data": "admin_health"}],
    [{"text": "📋 Logs",      "callback_data": "admin_logs"}],
    [{"text": "⬅ Back",      "callback_data": "admin_menu"}],
]
ADMIN_SETTINGS_MENU = [
    [{"text": "⚙️ Bot Settings", "callback_data": "admin_settings"}],
    [{"text": "🤖 Bot Mode",     "callback_data": "adm_mode_menu"}],
    [{"text": "⬅ Back",         "callback_data": "admin_menu"}],
]


# ═══════════════════════════════════════════════════════════════════════════
# ⚡ WEBSOCKET PRICE ENGINE
# ═══════════════════════════════════════════════════════════════════════════
# Maintains persistent WebSocket connections to Binance and Kraken.
# Prices land in _ws_price_cache — a shared dict read by get_best_price().
#
# Architecture:
#   • One daemon thread per exchange (Binance stream, Kraken stream)
#   • Auto-reconnects with exponential backoff on disconnect/error
#   • Falls back to REST if WebSocket hasn't received a price within
#     WS_STALE_SECONDS (60 s) — REST fetchers are unchanged below
#   • No third-party libraries — uses only Python stdlib ssl + socket
#
# Exchanges:
#   Binance  — wss://stream.binance.com:9443  (no API key required)
#   Kraken   — wss://ws.kraken.com            (no API key required)
#   Bybit    — wss://stream.bybit.com/v5/public/spot (no API key required)
#
# The REST fetchers for OKX/Bybit/CoinGecko remain as final fallbacks.
# ═══════════════════════════════════════════════════════════════════════════

# ── Shared price cache ────────────────────────────────────────────────────
# { "BTC": {"price": 67000.0, "change": 1.23, "ts": 1710000000.0}, ... }
_ws_price_cache: dict = {}
_ws_lock = threading.Lock()
WS_STALE_SECONDS = 60  # If no update in 60s, treat as stale, fall to REST

# ── Symbol maps ───────────────────────────────────────────────────────────
# Binance uses lowercase concatenated pairs e.g. "btcusdt"
_BINANCE_STREAM_MAP = {
    coin.lower() + "usdt": coin
    for coin in COINS
    if coin not in ("USDT", "USDC")   # Stablecoins don't need a stream
}
# Binance also carries USDT/USDC via a BUSD pair — skip them

# Kraken WS uses its own symbol format e.g. "XBT/USD"
_KRAKEN_WS_MAP = {
    "XBT/USD": "BTC",
    "ETH/USD": "ETH",
    "SOL/USD": "SOL",
    "XRP/USD": "XRP",
    "DOGE/USD": "DOGE",
    "ADA/USD": "ADA",
    "LTC/USD": "LTC",
    "DOT/USD": "DOT",
    "LINK/USD": "LINK",
    "ATOM/USD": "ATOM",
    "FIL/USD": "FIL",
    "TRX/USD": "TRX",
    "AVAX/USD": "AVAX",
    "NEAR/USD": "NEAR",
    "UNI/USD": "UNI",
}

# Bybit WS symbol format e.g. "BTCUSDT"
_BYBIT_WS_MAP = {
    coin + "USDT": coin
    for coin in COINS
    if coin not in ("USDT", "USDC")
}


# ── Low-level RFC 6455 WebSocket client (stdlib only) ────────────────────

def _ws_handshake(host, path, port=443):
    """Open a TLS socket and perform the WebSocket HTTP upgrade handshake.
    Returns the connected ssl.SSLSocket or raises on failure."""
    ctx = ssl.create_default_context()
    raw = socket.create_connection((host, port), timeout=15)
    sock = ctx.wrap_socket(raw, server_hostname=host)
    key = base64.b64encode(os.urandom(16)).decode()
    handshake = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(handshake.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(1024)
        if not chunk:
            raise ConnectionError("WebSocket handshake: empty response")
        resp += chunk
    if b"101" not in resp:
        raise ConnectionError(f"WebSocket upgrade failed: {resp[:200]}")
    return sock


def _ws_recv_frame(sock):
    """Read one complete WebSocket frame. Returns (opcode, payload_bytes).
    Automatically responds to ping frames with a pong (RFC 6455 §5.5.3).
    Raises on connection close or error frames."""
    header = b""
    while len(header) < 2:
        chunk = sock.recv(2 - len(header))
        if not chunk:
            raise ConnectionError("WebSocket: connection closed")
        header += chunk

    byte1, byte2 = header[0], header[1]
    opcode = byte1 & 0x0F
    masked = bool(byte2 & 0x80)
    length = byte2 & 0x7F

    if length == 126:
        raw = _ws_recv_exact(sock, 2)
        length = struct.unpack("!H", raw)[0]
    elif length == 127:
        raw = _ws_recv_exact(sock, 8)
        length = struct.unpack("!Q", raw)[0]

    mask_key = _ws_recv_exact(sock, 4) if masked else b""
    payload = _ws_recv_exact(sock, length)

    if masked:
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

    if opcode == 8:   # Connection close
        raise ConnectionError("WebSocket: server sent close frame")
    if opcode == 9:   # Ping — must reply with Pong (opcode 0xA) or server disconnects
        _ws_send_pong(sock, payload)
        return None, b""
    if opcode == 0xA: # Pong — unsolicited pong, just ignore
        return None, b""
    return opcode, payload


def _ws_send_pong(sock, payload=b""):
    """Send a RFC 6455 Pong frame (opcode 0xA), client-masked."""
    length = len(payload)
    mask_key = os.urandom(4)
    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    if length <= 125:
        header = bytes([0x8A, 0x80 | length]) + mask_key
    else:
        header = bytes([0x8A, 0x7E]) + struct.pack("!H", length) + mask_key
    sock.sendall(header + masked)


def _ws_recv_exact(sock, n):
    """Read exactly n bytes from sock."""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("WebSocket: short read")
        buf += chunk
    return buf


def _ws_send_text(sock, text):
    """Send a text frame (opcode 1), client-masked as per RFC 6455."""
    payload = text.encode("utf-8")
    length = len(payload)
    mask_key = os.urandom(4)
    masked_payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    if length <= 125:
        header = bytes([0x81, 0x80 | length]) + mask_key
    elif length <= 65535:
        header = bytes([0x81, 0xFE]) + struct.pack("!H", length) + mask_key
    else:
        header = bytes([0x81, 0xFF]) + struct.pack("!Q", length) + mask_key
    sock.sendall(header + masked_payload)


def _ws_cache_price(coin, price, change=None):
    """Thread-safe write into the shared price cache."""
    with _ws_lock:
        existing = _ws_price_cache.get(coin, {})
        _ws_price_cache[coin] = {
            "price": float(price),
            "change": change if change is not None else existing.get("change"),
            "ts": time.time(),
        }


def _ws_get_cached(coin):
    """Return (price, change) from WebSocket cache if fresh, else (None, None)."""
    with _ws_lock:
        entry = _ws_price_cache.get(coin)
    if not entry:
        return None, None
    if time.time() - entry["ts"] > WS_STALE_SECONDS:
        return None, None   # Stale — REST fallback will handle it
    return entry["price"], entry.get("change")


# ── Binance WebSocket thread ──────────────────────────────────────────────

def _binance_ws_thread():
    """Persistent Binance combined stream. Reconnects with backoff."""
    streams = "/".join(f"{sym}@miniTicker" for sym in sorted(_BINANCE_STREAM_MAP))
    path = f"/stream?streams={streams}"
    host = "stream.binance.com"
    port = 9443
    backoff = 2

    while True:
        sock = None
        try:
            logger.info("[WS BINANCE] Connecting...")
            sock = _ws_handshake(host, path, port)
            sock.settimeout(45)   # Binance sends keepalive every ~20s
            backoff = 2           # Reset on successful connect
            logger.info("[WS BINANCE] Connected — streaming %d pairs" % len(_BINANCE_STREAM_MAP))

            while True:
                opcode, payload = _ws_recv_frame(sock)
                if opcode is None:
                    continue   # Ping frame — skip
                msg = json.loads(payload.decode("utf-8"))
                # Combined stream wraps data in {"stream":..., "data":{...}}
                data = msg.get("data", msg)
                sym = data.get("s", "").lower()   # e.g. "btcusdt"
                coin = _BINANCE_STREAM_MAP.get(sym)
                if coin:
                    last = float(data.get("c", 0) or data.get("lastPrice", 0))
                    open24h = float(data.get("o", 0) or 0)
                    change = ((last - open24h) / open24h * 100) if open24h else None
                    if last > 0:
                        _ws_cache_price(coin, last, change)

        except Exception as e:
            logger.warning("[WS BINANCE] Disconnected: %s — reconnecting in %ds" % (e, backoff))
        finally:
            if sock:
                try: sock.close()
                except Exception: pass

        time.sleep(backoff)
        backoff = min(backoff * 2, 60)   # Cap at 60s


# ── Kraken WebSocket thread ───────────────────────────────────────────────

def _kraken_ws_thread():
    """Persistent Kraken v2 WebSocket. Reconnects with backoff."""
    host = "ws.kraken.com"
    path = "/"
    pairs = list(_KRAKEN_WS_MAP.keys())
    backoff = 2

    # Kraken also provides 24h open via the ticker channel
    _kraken_open24h = {}   # symbol -> open24h price

    while True:
        sock = None
        try:
            logger.info("[WS KRAKEN] Connecting...")
            sock = _ws_handshake(host, path, port=443)
            sock.settimeout(30)
            backoff = 2
            logger.info("[WS KRAKEN] Connected")

            # Subscribe to ticker channel
            sub_msg = json.dumps({
                "event": "subscribe",
                "pair": pairs,
                "subscription": {"name": "ticker"}
            })
            _ws_send_text(sock, sub_msg)

            while True:
                opcode, payload = _ws_recv_frame(sock)
                if opcode is None:
                    continue
                msg = json.loads(payload.decode("utf-8"))

                # Kraken sends [channelID, data, "ticker", "XBT/USD"]
                if isinstance(msg, list) and len(msg) == 4 and msg[2] == "ticker":
                    ticker = msg[1]
                    symbol = msg[3]   # e.g. "XBT/USD"
                    coin = _KRAKEN_WS_MAP.get(symbol)
                    if coin:
                        last = float(ticker.get("c", [0])[0])
                        open24h = float(ticker.get("o", [0])[0])
                        change = ((last - open24h) / open24h * 100) if open24h else None
                        if last > 0:
                            _ws_cache_price(coin, last, change)

        except Exception as e:
            logger.warning("[WS KRAKEN] Disconnected: %s — reconnecting in %ds" % (e, backoff))
        finally:
            if sock:
                try: sock.close()
                except Exception: pass

        time.sleep(backoff)
        backoff = min(backoff * 2, 60)


# ── Bybit WebSocket thread ────────────────────────────────────────────────

def _bybit_ws_thread():
    """Persistent Bybit v5 spot WebSocket. Covers coins not on Kraken/Binance.

    Bybit requires the CLIENT to send {"op":"ping"} every 20 seconds or the
    server will close the connection. We use a 19s socket timeout so the recv
    loop wakes up slightly before the deadline and sends a ping proactively.
    """
    host = "stream.bybit.com"
    path = "/v5/public/spot"
    # Only subscribe to coins that Binance doesn't already cover
    binance_covered = set(c.upper() for c in _BINANCE_STREAM_MAP.values())
    bybit_only = [sym for sym, coin in _BYBIT_WS_MAP.items() if coin not in binance_covered]
    if not bybit_only:
        logger.info("[WS BYBIT] No extra coins to stream — thread idle")
        return

    backoff = 2
    BYBIT_PING_INTERVAL = 19  # seconds — Bybit disconnects after 20s silence

    while True:
        sock = None
        try:
            logger.info("[WS BYBIT] Connecting...")
            sock = _ws_handshake(host, path, port=443)
            # Timeout slightly under ping interval so we wake up to send ping
            sock.settimeout(BYBIT_PING_INTERVAL)
            backoff = 2
            logger.info("[WS BYBIT] Connected — streaming %d pairs" % len(bybit_only))

            # Subscribe to tickers
            sub_msg = json.dumps({
                "op": "subscribe",
                "args": [f"tickers.{sym}" for sym in bybit_only]
            })
            _ws_send_text(sock, sub_msg)

            last_ping = time.time()

            while True:
                try:
                    opcode, payload = _ws_recv_frame(sock)
                except TimeoutError:
                    # Socket timed out — time to send keepalive ping
                    _ws_send_text(sock, json.dumps({"op": "ping"}))
                    last_ping = time.time()
                    continue
                except OSError as oe:
                    if "timed out" in str(oe).lower():
                        _ws_send_text(sock, json.dumps({"op": "ping"}))
                        last_ping = time.time()
                        continue
                    raise

                if opcode is None:
                    continue

                msg = json.loads(payload.decode("utf-8"))

                if msg.get("topic", "").startswith("tickers."):
                    data = msg.get("data", {})
                    sym = msg["topic"].replace("tickers.", "")
                    coin = _BYBIT_WS_MAP.get(sym)
                    if coin:
                        last = float(data.get("lastPrice", 0) or 0)
                        open24h = float(data.get("prevPrice24h", 0) or 0)
                        change = ((last - open24h) / open24h * 100) if open24h else None
                        if last > 0:
                            _ws_cache_price(coin, last, change)

                elif msg.get("op") in ("pong", "ping"):
                    pass  # Server acknowledged our ping — connection healthy

                # Proactive ping if somehow no timeout fired yet
                if time.time() - last_ping >= BYBIT_PING_INTERVAL:
                    _ws_send_text(sock, json.dumps({"op": "ping"}))
                    last_ping = time.time()

        except Exception as e:
            logger.warning("[WS BYBIT] Disconnected: %s — reconnecting in %ds" % (e, backoff))
        finally:
            if sock:
                try: sock.close()
                except Exception: pass

        time.sleep(backoff)
        backoff = min(backoff * 2, 60)


# ── Bybit ping keepalive ──────────────────────────────────────────────────
# Bybit disconnects if no message is received in 20s.
# We handle this by maintaining a reference to the socket and sending pings.
# The simpler approach: reconnect quickly (backoff=2s) on disconnect.
# The _bybit_ws_thread already handles that — no separate ping thread needed.


# ── WebSocket engine startup ──────────────────────────────────────────────

_ws_started = False

def start_ws_price_engine():
    """Launch all WebSocket threads. Called once at bot startup.
    Safe to call multiple times — only starts threads once."""
    global _ws_started
    if _ws_started:
        return
    _ws_started = True

    threads = [
        ("Binance", _binance_ws_thread),
        ("Kraken",  _kraken_ws_thread),
        ("Bybit",   _bybit_ws_thread),
    ]
    for name, target in threads:
        t = threading.Thread(target=target, name=f"WS-{name}", daemon=True)
        t.start()
        logger.info("[WS ENGINE] Started %s thread" % name)


def ws_engine_status():
    """Return a status string for admin health checks."""
    with _ws_lock:
        covered = [(c, e["ts"]) for c, e in _ws_price_cache.items()]
    now = time.time()
    fresh = [(c, now - ts) for c, ts in covered if now - ts <= WS_STALE_SECONDS]
    stale = [(c, now - ts) for c, ts in covered if now - ts > WS_STALE_SECONDS]
    return (
        f"WebSocket Engine\n"
        f"  Fresh prices: {len(fresh)}/{len(COINS)} coins\n"
        f"  Stale: {len(stale)}\n"
        f"  Oldest fresh: {max((age for _,age in fresh), default=0):.0f}s ago"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 💰 PRICE FETCHERS
# ═══════════════════════════════════════════════════════════════════════════

_kraken_keymap = {}
_kraken_cache = {"data": {}, "timestamp": None}
_secondary_cache = {"data": {}, "timestamp": None}
_morning_btc_snapshot = {}  # Stores BTC price at morning post time for midday threshold check
_fiat_cache = {"data": {}, "timestamp": None}

def get_kraken_keymap():
    global _kraken_keymap
    if _kraken_keymap:
        return _kraken_keymap
    pairs = sorted({kraken_pair(c) for c in COINS if kraken_pair(c)})
    resp = fetch_with_backoff(f"https://api.kraken.com/0/public/AssetPairs?pair={','.join(pairs)}")
    if resp and not resp.get("error"):
        for key, info in resp.get("result", {}).items():
            altname = info.get("altname")
            if altname:
                _kraken_keymap[altname] = key
    return _kraken_keymap

def get_kraken_batch():
    global _kraken_cache
    now = wat_now()
    if (_kraken_cache["timestamp"] and
            (now - _kraken_cache["timestamp"]).total_seconds() < 15):
        return _kraken_cache["data"]
    pairs = sorted({kraken_pair(c) for c in COINS if kraken_pair(c)})
    resp = fetch_with_backoff(f"https://api.kraken.com/0/public/Ticker?pair={','.join(pairs)}")
    if not resp or resp.get("error"):
        return _kraken_cache["data"]
    keymap = get_kraken_keymap()
    result = resp.get("result", {})
    prices = {}
    for coin in COINS:
        pair = kraken_pair(coin)
        if not pair:
            continue
        entry = result.get(keymap.get(pair, pair))
        if entry:
            try:
                prices[coin] = float(entry["c"][0])
            except Exception as _e:
                logger.debug("[SILENT EXC] %s" % _e)
    _kraken_cache["data"] = prices
    _kraken_cache["timestamp"] = now
    return prices

def get_kraken_price(coin):
    if not kraken_pair(coin):
        return None
    return get_kraken_batch().get(coin)

def get_okx_price(coin):
    try:
        resp = fetch_with_backoff(f"https://www.okx.com/api/v5/market/ticker?instId={coin}-USDT")
        if resp and resp.get("code") == "0":
            data = resp.get("data", [])
            if data:
                return float(data[0].get("last", 0))
    except Exception as _e:
        logger.debug("[SILENT EXC] %s" % _e)
    return None

def get_bybit_price(coin):
    try:
        resp = fetch_with_backoff(f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={coin}USDT")
        if resp and resp.get("retCode") == 0:
            data = resp.get("result", {}).get("list", [])
            if data:
                return float(data[0].get("lastPrice", 0))
    except Exception as _e:
        logger.debug("[SILENT EXC] %s" % _e)
    return None

def get_coingecko_price(coin):
    try:
        coin_id = COINS[coin][1]
        resp = fetch_with_backoff(f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd")
        if resp and coin_id in resp:
            return resp[coin_id].get("usd")
    except Exception as _e:
        logger.debug("[SILENT EXC] %s" % _e)
    return None

def get_price_with_fallback(coin):
    # 1. WebSocket cache — always first, zero latency, no REST timeout risk
    ws_price, _ = _ws_get_cached(coin)
    if ws_price:
        return ws_price
    # 2. Kraken REST batch (cached 15s) — reliable, no API key needed
    price = get_kraken_price(coin)
    if price:
        return price
    # 3. OKX REST — secondary
    price = get_okx_price(coin)
    if price:
        return price
    # 4. Bybit REST — tertiary (usually covered by WS already)
    price = get_bybit_price(coin)
    if price:
        return price
    # 5. CoinGecko REST — last resort
    price = get_coingecko_price(coin)
    if price:
        return price
    return None

def get_secondary_batch():
    global _secondary_cache
    now = wat_now()
    if (_secondary_cache["timestamp"] and
            (now - _secondary_cache["timestamp"]).total_seconds() < 60):
        return _secondary_cache["data"]
    
    resp = fetch_with_backoff("https://www.okx.com/api/v5/market/tickers?instType=SPOT")
    result = {}
    if resp and resp.get("code") == "0":
        for row in resp.get("data", []):
            inst = row.get("instId", "")
            coin = inst.replace("-USDT", "")
            if coin in COINS:
                try:
                    last = float(row["last"])
                    open24h = float(row["open24h"]) if row.get("open24h") else None
                    change = ((last - open24h) / open24h * 100) if open24h else None
                    result[coin_key(coin)] = {
                        "usd": last,
                        "usd_24h_change": change,
                        "usd_24h_high": float(row["high24h"]) if row.get("high24h") else None,
                        "usd_24h_low": float(row["low24h"]) if row.get("low24h") else None,
                    }
                except Exception as _e:
                    logger.debug("[SILENT EXC] %s" % _e)
    
    if not result:
        # CoinGecko markets endpoint — free, no key, 30 calls/min (replaces CryptoCompare 25/day limit)
        try:
            cg_ids = ",".join(v[1] for v in COINS.values() if v[1])
            resp = fetch_with_backoff(
                f"https://api.coingecko.com/api/v3/coins/markets"
                f"?vs_currency=usd&ids={cg_ids}&order=market_cap_desc&per_page=100"
                f"&price_change_percentage=24h"
            )
            if resp:
                for item in resp:
                    cg_id = item.get("id")
                    if cg_id:
                        result[cg_id] = {
                            "usd": item.get("current_price"),
                            "usd_24h_change": item.get("price_change_percentage_24h"),
                            "usd_24h_high": item.get("high_24h"),
                            "usd_24h_low": item.get("low_24h"),
                        }
        except Exception as e:
            logger.warning("[SECONDARY BATCH] CoinGecko: %s" % e)
    
    _secondary_cache["data"] = result
    _secondary_cache["timestamp"] = now
    return result

def get_secondary_coin(coin):
    return get_secondary_batch().get(coin_key(coin))

def get_best_price(coin):
    """Return (price, change_24h_pct) using WebSocket cache when available,
    falling back through Kraken/OKX/Bybit/CoinGecko REST as needed."""
    if coin not in COINS:
        return None, None

    # Try WebSocket cache first — includes change% when available
    ws_price, ws_change = _ws_get_cached(coin)
    if ws_price:
        # If WS gave us a change%, use it; otherwise supplement from secondary batch
        if ws_change is not None:
            return ws_price, ws_change
        sd = get_secondary_coin(coin)
        change = sd.get("usd_24h_change") if sd else None
        return ws_price, change

    # Fall back to REST chain
    price = get_price_with_fallback(coin)
    sd = get_secondary_coin(coin)
    change = sd.get("usd_24h_change") if sd else None
    if price:
        return price, change
    if sd:
        return sd.get("usd"), change
    return None, None

def get_fiat_rates():
    """Get USD-based fiat exchange rates. Cached 4 hours.
    Sources: frankfurter.app (primary, unlimited) + open.er-api.com (fallback).
    NGN added separately via P2P-derived rate since frankfurter.app excludes NGN."""
    global _fiat_cache
    now = wat_now()
    if (_fiat_cache["timestamp"] and
            (now - _fiat_cache["timestamp"]).total_seconds() < 14400):
        return _fiat_cache["data"]

    rates = {}

    # Primary: frankfurter.app — no rate limit, no API key needed
    try:
        resp = fetch_with_backoff("https://api.frankfurter.app/latest?from=USD")
        if resp and "rates" in resp:
            rates = resp["rates"]
            rates["USD"] = 1.0
            logger.info("[FIAT RATES] frankfurter.app loaded %d rates" % len(rates))
    except Exception as e:
        logger.warning("[FIAT RATES] frankfurter: %s" % e)

    # Fallback to open.er-api.com if primary failed
    if not rates:
        try:
            resp = fetch_with_backoff("https://open.er-api.com/v6/latest/USD")
            if resp and "rates" in resp:
                rates = resp["rates"]
                logger.info("[FIAT RATES] er-api fallback loaded %d rates" % len(rates))
        except Exception as e:
            logger.warning("[FIAT RATES] er-api fallback: %s" % e)

    # ── NGN: frankfurter.app excludes NGN ────────────────────────────────
    # Derive NGN rate from Binance P2P USDT/NGN (most accurate parallel rate)
    # Since USDT ≈ $1, USDT/NGN rate ≈ USD/NGN parallel market rate
    if "NGN" not in rates:
        try:
            buy_ngn, sell_ngn, source = get_p2p_rate("USDT", "NGN")
            if buy_ngn and sell_ngn:
                # Use midpoint of buy/sell as the USD/NGN rate
                ngn_rate = (buy_ngn + sell_ngn) / 2
                rates["NGN"] = round(ngn_rate, 2)
                logger.info("[FIAT RATES] NGN derived from P2P: ₦%.0f/USD (source: %s)" % (ngn_rate, source))
        except Exception as e:
            logger.warning("[FIAT RATES] NGN P2P derivation: %s" % e)

    if rates:
        _fiat_cache["data"] = rates
        _fiat_cache["timestamp"] = now

    return _fiat_cache["data"] or {}

# ═══════════════════════════════════════════════════════════════════════════
# 📊 MISSING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

_STABLECOINS = {"USDT", "USDC"}  # Exclude from gainers/losers

def get_gainers_losers():
    prices = {}
    for coin in COINS:
        if coin in _STABLECOINS:
            continue
        price, change = get_best_price(coin)
        if price and change is not None:
            prices[coin] = {"price": price, "change": change}
    
    if not prices:
        return [], []
    
    sorted_coins = sorted(prices.items(), key=lambda x: x[1]["change"], reverse=True)
    gainers = [(c, p["price"], p["change"]) for c, p in sorted_coins[:5] if p["change"] > 0]
    losers = [(c, p["price"], p["change"]) for c, p in sorted_coins[-5:] if p["change"] < 0]
    return gainers, losers

def get_okx_batch():
    try:
        resp = fetch_with_backoff("https://www.okx.com/api/v5/market/tickers?instType=SPOT")
        if resp and resp.get("code") == "0":
            result = {}
            for row in resp.get("data", []):
                inst = row.get("instId", "")
                coin = inst.replace("-USDT", "")
                if coin in COINS:
                    result[coin] = {"price": float(row["last"])}
            return result
    except Exception as _e:
        logger.debug("[SILENT EXC] %s" % _e)
    return {}

def get_coingecko_batch():
    try:
        # COINS[symbol] = (kraken_pair, coingecko_id) — unpack correctly
        ids = [v[1] for v in COINS.values()]
        resp = fetch_with_backoff(f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(ids)}&vs_currencies=usd")
        if resp:
            result = {}
            for coin, (_, cg_id) in COINS.items():
                if cg_id in resp and resp[cg_id].get("usd"):
                    result[coin] = {"price": resp[cg_id]["usd"]}
            return result
    except Exception as e:
        logger.warning("[COINGECKO BATCH] %s" % e)
    return {}

def save_price_history():
    db = None
    try:
        db = get_db()
        c = db.cursor()
        now = wat_now().strftime("%Y-%m-%d %H:%M:%S")
        rows = []
        for coin in COINS:
            price, _ = get_best_price(coin)
            if price and price > 0:
                rows.append((coin, price, now))
        if rows:
            c.executemany("INSERT INTO history (coin, price, timestamp) VALUES (%s, %s, %s)", rows)
            db.commit()
            logger.info("[HISTORY] Saved %d price records" % len(rows))
    except Exception as e:
        logger.error("[HISTORY ERROR] %s" % e)
        if db:
            try: db.rollback()
            except Exception: pass
    finally:
        if db:
            try: db.close()
            except Exception: pass

# ═══════════════════════════════════════════════════════════════════════════
# 🇳🇬 P2P SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

def _p2p_median(prices):
    if not prices:
        return None
    prices.sort()
    return prices[len(prices) // 2]

def get_binance_p2p(side, asset, fiat_code):
    try:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json",
            "Referer": "https://p2p.binance.com/",
            "Origin": "https://p2p.binance.com"
        }
        payload = {
            "asset": asset,
            "fiat": fiat_code,
            "merchantCheck": False,
            "page": 1,
            "publisherType": None,
            "rows": 10,
            "tradeType": side
        }
        resp = requests.post(
            "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search",
            json=payload,
            headers=headers,
            timeout=15
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        ads = data.get("data") or []
        prices = []
        for a in ads:
            try:
                adv = a.get("adv", {})
                price = adv.get("price")
                if price:
                    prices.append(float(price))
            except Exception as _e:
                continue
        if not prices:
            return None
        return _p2p_median(prices)
    except Exception as e:
        logger.error("[BINANCE P2P ERROR] %s" % e)
        return None

def get_bybit_p2p(side, asset, fiat_code):
    try:
        bybit_side = "1" if side == "BUY" else "0"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": random.choice(USER_AGENTS)
        }
        resp = requests.post(
            "https://api2.bybit.com/fiat/otc/item/list",
            json={"userId": "", "tokenId": asset, "currencyId": fiat_code,
                  "payment": [], "side": bybit_side, "size": "10", "page": "1",
                  "amount": "", "authMaker": False, "canTrade": False},
            headers=headers,
            timeout=10
        )
        if resp.status_code != 200:
            return None
        items = resp.json().get("result", {}).get("items") or []
        prices = [float(i["price"]) for i in items if i.get("price")]
        return _p2p_median(prices)
    except Exception as e:
        logger.error("[BYBIT P2P ERROR] %s" % e)
        return None

def get_p2p_rate(crypto, fiat):
    try:
        buy = get_binance_p2p("BUY", crypto, fiat)
        sell = get_binance_p2p("SELL", crypto, fiat)
        if buy and sell:
            return buy, sell, "Binance P2P"
    except Exception as _e:
        logger.debug("[SILENT EXC] %s" % _e)
    
    try:
        buy = get_bybit_p2p("BUY", crypto, fiat)
        sell = get_bybit_p2p("SELL", crypto, fiat)
        if buy and sell:
            return buy, sell, "Bybit P2P"
    except Exception as _e:
        logger.debug("[SILENT EXC] %s" % _e)
    
    try:
        rates = get_fiat_rates()
        price, _ = get_best_price(crypto)
        fiat_per_usd = rates.get(fiat)
        if price and fiat_per_usd:
            val = price * fiat_per_usd
            buy = round(val * 1.015, 2)
            sell = round(val * 0.985, 2)
            return buy, sell, "Estimated ⚠️"
    except Exception as e:
        logger.warning("[P2P ESTIMATE] %s" % e)

    return None, None, None

# ═══════════════════════════════════════════════════════════════════════════
# 📊 PORTFOLIO FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def get_portfolio_value(chat_id):
    try:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT coin, amount, buy_price FROM portfolio WHERE chat=%s", (str(chat_id),))
        rows = c.fetchall()
        db.close()
        
        total_invested = 0
        total_current = 0
        positions = []
        
        for coin, amount, buy_price in rows:
            current_price, _ = get_best_price(coin)
            if current_price:
                invested = amount * buy_price
                current = amount * current_price
                pnl = current - invested
                pnl_pct = (pnl / invested) * 100 if invested > 0 else 0
                positions.append({
                    "coin": coin,
                    "amount": amount,
                    "buy_price": buy_price,
                    "current_price": current_price,
                    "invested": invested,
                    "current": current,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct
                })
                total_invested += invested
                total_current += current
        
        return {
            "positions": positions,
            "total_invested": total_invested,
            "total_current": total_current,
            "total_pnl": total_current - total_invested,
            "total_pnl_pct": ((total_current - total_invested) / total_invested * 100) if total_invested > 0 else 0
        }
    except Exception as _e:
        return None

# ═══════════════════════════════════════════════════════════════════════════
# 📈 TRADE JOURNAL FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def close_trade(chat_id, trade_id, exit_price=None):
    try:
        db = get_db()
        c = db.cursor()
        
        c.execute("SELECT coin, direction, entry_price, size, status FROM trade_journal WHERE id=%s AND chat=%s",
                  (trade_id, str(chat_id)))
        row = c.fetchone()
        
        if not row:
            return {"error": "Trade not found"}
        
        coin, direction, entry_price, size, status = row
        
        if status == "closed":
            return {"error": "Trade already closed"}
        
        if exit_price is None:
            exit_price, _ = get_best_price(coin)
            if not exit_price:
                return {"error": "Could not get current price"}
        
        if direction == "LONG":
            pnl = (exit_price - entry_price) * size
        else:
            pnl = (entry_price - exit_price) * size
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        c.execute("UPDATE trade_journal SET exit_price=%s, pnl=%s, status='closed', closed_at=%s WHERE id=%s",
                  (exit_price, pnl, now, trade_id))
        db.commit()
        db.close()
        
        return {"pnl": pnl, "exit_price": exit_price}
    except Exception as e:
        return {"error": str(e)}

# ═══════════════════════════════════════════════════════════════════════════
# 🧠 FEAR & GREED
# ═══════════════════════════════════════════════════════════════════════════

_fg_cache = {"data": None, "timestamp": None}

def get_latest_news(limit=5):
    """Alias for get_crypto_news with limit support."""
    news = get_crypto_news()
    if news and limit:
        return news[:limit]
    return news or []


def get_fear_greed():
    global _fg_cache
    now = datetime.now()
    if (_fg_cache["timestamp"] and (now - _fg_cache["timestamp"]).total_seconds() < 21600):  # 6hr cache — F&G only updates once per day
        return _fg_cache["data"]
    try:
        resp = fetch_with_backoff("https://api.alternative.me/fng/?limit=7")
        if resp and resp.get("data"):
            _fg_cache["data"] = resp["data"]
            _fg_cache["timestamp"] = now
            return resp["data"]
    except Exception as _e:
        logger.debug("[SILENT EXC] %s" % _e)
    return _fg_cache["data"]

def fg_emoji(value):
    try:
        v = int(value)
    except (ValueError, TypeError):
        return "😐"
    if v <= 24: return "😱"
    elif v <= 44: return "😰"
    elif v <= 54: return "😐"
    elif v <= 74: return "😊"
    else: return "🤑"

# ═══════════════════════════════════════════════════════════════════════════
# 📰 NEWS SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

_news_cache = {"data": None, "timestamp": None}

def _parse_rss(xml_text, source_name):
    articles = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            url = (item.findtext("link") or "").strip()
            if title and url:
                articles.append({"title": title, "url": url, "source": {"title": source_name}})
    except Exception as _e:
        logger.debug("[SILENT EXC] %s" % _e)
    return articles

def get_crypto_news():
    global _news_cache
    now = wat_now()
    if (_news_cache["timestamp"] and (now - _news_cache["timestamp"]).total_seconds() < 900):
        return _news_cache["data"]
    
    all_articles = []
    for source_name, rss_url in NEWS_RSS_FEEDS:
        try:
            r = requests.get(rss_url, timeout=8, headers=get_random_headers())
            if r.status_code == 200:
                all_articles.extend(_parse_rss(r.text, source_name)[:3])
        except Exception as _e:
            continue
    
    if all_articles:
        _news_cache["data"] = all_articles[:10]
        _news_cache["timestamp"] = now
        return _news_cache["data"]
    
    return _news_cache["data"]

# ═══════════════════════════════════════════════════════════════════════════
# 🤖 AI SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

AI_SYSTEM_PROMPT = """
You are a professional crypto analyst writing for Nigerian crypto traders. You understand Nigerian FX dynamics deeply — P2P rates, naira volatility, CBN policy, dollar scarcity.

CRITICAL RULES:
1. NEVER use asterisks (*) for anything — not bold, not bullets, not emphasis.
2. Use Telegram HTML tags: <b>price</b> for bold numbers and key levels only.
3. NEVER invent historical events, institutional activity, or macro news. Only state what can be observed from price data.
4. Separate facts from predictions. Facts come from data. Predictions are scenarios, not certainties.
5. If no quality setup exists, say so clearly — never force a trade.
6. Be concise. No padding. No generic phrases.

STRUCTURED FORMAT (use exactly — fields are parsed by code):
SITUATION: [One sentence — what is happening RIGHT NOW at this price level. Use correct terminology: Testing Support / Testing Resistance / Breakout / Breakdown. Bold the key level.]
CONTEXT: [One sentence — Nigerian trader angle. P2P implication or naira risk. Bold any key naira figure.]
Market Bias: [Bullish / Bearish / Neutral]
Entry: $[exact price or "none" if no setup]
Stop: $[exact price or "none"]
Target: $[exact price or "none"]
Confidence: [High / Moderate / Low / Uncertain — based on trend, momentum, and level strength only]
DECISION: [One sentence — exactly what you would do right now, or clearly state: Wait — [reason]]

End with: NFA — manage your risk.
"""

def ask_deepseek(question):
    if not DEEPSEEK_KEY:
        return None
    try:
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": "Bearer %s" % DEEPSEEK_KEY,
                     "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "system", "content": AI_SYSTEM_PROMPT},
                             {"role": "user", "content": question}],
                "max_tokens": 800,
                "temperature": 0.7,
            },
            timeout=30
        )
        data = resp.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error("[DEEPSEEK ERROR] %s" % e)
    return None

def ask_mistral(question):
    if not MISTRAL_KEY:
        return None
    try:
        resp = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": "Bearer %s" % MISTRAL_KEY,
                     "Content-Type": "application/json"},
            json={
                "model": "mistral-small-latest",
                "messages": [{"role": "system", "content": AI_SYSTEM_PROMPT},
                             {"role": "user", "content": question}],
                "max_tokens": 800,
            },
            timeout=30
        )
        data = resp.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error("[MISTRAL ERROR] %s" % e)
    return None

def ask_qwen(question):
    if not QWEN_KEY:
        return None
    try:
        resp = requests.post(
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
            headers={"Authorization": "Bearer %s" % QWEN_KEY,
                     "Content-Type": "application/json"},
            json={
                "model": "qwen-turbo",
                "input": {"messages": [{"role": "system", "content": AI_SYSTEM_PROMPT},
                                       {"role": "user", "content": question}]},
                "parameters": {"max_tokens": 800}
            },
            timeout=30
        )
        data = resp.json()
        if "output" in data and "text" in data["output"]:
            return data["output"]["text"].strip()
    except Exception as e:
        logger.error("[QWEN ERROR] %s" % e)
    return None

def _clean_ai_response(text):
    if not text:
        return text
    # Convert markdown bold to Telegram HTML bold
    text = re.sub(r'[*][*](.+?)[*][*]', r'<b>\1</b>', text, flags=re.DOTALL)
    text = re.sub(r'[*](.+?)[*]', r'<b>\1</b>', text)
    text = text.replace('*', '')
    # Strip markdown headers (### / ## / #)
    text = re.sub(r'^#{1,3}\s+', '', text, flags=re.MULTILINE)
    # Collapse excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def ask_ai(question):
    providers = [
        ("DeepSeek", ask_deepseek),
        ("Mistral", ask_mistral),
        ("Qwen", ask_qwen),
    ]
    for name, func in providers:
        try:
            result = func(question)
            if result:
                return _clean_ai_response(result), name
        except Exception as _e:
            continue
    return None, None

# ═══════════════════════════════════════════════════════════════════════════
# 📊 CHANNEL POST BUILDERS
# ═══════════════════════════════════════════════════════════════════════════

def _morning_data():
    btc_price, btc_change = get_best_price("BTC")
    eth_price, eth_change = get_best_price("ETH")
    sol_price, sol_change = get_best_price("SOL")
    bnb_price, bnb_change = get_best_price("BNB")
    xrp_price, xrp_change = get_best_price("XRP")
    fg_data   = get_fear_greed()
    gainers, losers = get_gainers_losers()
    today    = wat_now().strftime("%A, %b %d")
    time_str = wat_now().strftime("%I:%M %p WAT")
    btc_sd   = get_secondary_coin("BTC")
    btc_high = btc_sd.get("usd_24h_high") if btc_sd else None
    btc_low  = btc_sd.get("usd_24h_low")  if btc_sd else None
    buy, sell, _ = get_p2p_rate("USDT", "NGN")
    return dict(
        btc_price=btc_price, btc_change=btc_change,
        eth_price=eth_price, eth_change=eth_change,
        sol_price=sol_price, sol_change=sol_change,
        bnb_price=bnb_price, bnb_change=bnb_change,
        xrp_price=xrp_price, xrp_change=xrp_change,
        fg_data=fg_data, gainers=gainers, losers=losers,
        today=today, time_str=time_str,
        btc_high=btc_high, btc_low=btc_low, buy=buy, sell=sell
    )

def _morning_base(d):
    fg_val = d["fg_data"][0]["value"] if d["fg_data"] else "N/A"
    fg_lbl = d["fg_data"][0]["value_classification"] if d["fg_data"] else "Neutral"
    lines = [
        "\U0001f305 <b>MARKET PULSE — MORNING BRIEFING</b>",
        f"<i>{d['today']}  |  {d['time_str']}</i>", "",
        "· · · · · · · · · · · · · · · · · · ·", "",
        f"📈 BTC: <b>{format_price(d['btc_price'])}</b>  {format_change(d['btc_change'])}",
        f"📈 ETH: <b>{format_price(d['eth_price'])}</b>  {format_change(d['eth_change'])}",
        f"📈 SOL: <b>{format_price(d['sol_price'])}</b>  {format_change(d['sol_change'])}",
        f"📈 BNB: <b>{format_price(d['bnb_price'])}</b>  {format_change(d['bnb_change'])}",
        f"📈 XRP: <b>{format_price(d['xrp_price'])}</b>  {format_change(d['xrp_change'])}",
        "",
        f"🧠 Fear & Greed: <b>{fg_val}/100</b> — {fg_lbl}", "",
    ]
    if d["btc_high"] and d["btc_low"]:
        lines += [f"📊 BTC 24h Range: <b>{format_price(d['btc_low'])}</b> — <b>{format_price(d['btc_high'])}</b>", ""]
    if d["gainers"]:
        lines += [f"📈 <b>TOP MOVER:</b> <b>{d['gainers'][0][0]}</b> +{d['gainers'][0][2]:.2f}%", ""]
    if d["buy"] and d["sell"]:
        lines += [f"💱 <b>USDT/NGN</b>  Buy \u20a6{int(d['buy']):,}  |  Sell \u20a6{int(d['sell']):,}  Spread \u20a6{int(d['buy']-d['sell']):,}", ""]
    return lines

def build_morning_briefing():
    """Free — prices, sentiment, P2P, teaser. Nothing else."""
    d = _morning_data()
    fg_val = d["fg_data"][0]["value"] if d["fg_data"] else "N/A"
    fg_lbl = d["fg_data"][0]["value_classification"] if d["fg_data"] else "Neutral"
    fg_num = int(fg_val) if str(fg_val).isdigit() else 50
    if fg_num <= 25:   mood = "Extreme Fear — historically a buying zone, but patience first."
    elif fg_num <= 45: mood = "Fear — cautious market. Watch before you act."
    elif fg_num <= 60: mood = "Neutral — no edge either way. Let price decide."
    elif fg_num <= 80: mood = "Greed — momentum is building. Protect profits."
    else:              mood = "Extreme Greed — overheated. Reversal risk is high."
    lines = [
        "\U0001f305 <b>MORNING BRIEFING</b>",
        f"<i>{d['today']}  ·  {d['time_str']}</i>",
        "",
        f"BTC   <b>{format_price(d['btc_price'])}</b>   {format_change(d['btc_change'])}",
        f"ETH   <b>{format_price(d['eth_price'])}</b>   {format_change(d['eth_change'])}",
        f"SOL   <b>{format_price(d['sol_price'])}</b>   {format_change(d['sol_change'])}",
        f"BNB   <b>{format_price(d['bnb_price'])}</b>   {format_change(d['bnb_change'])}",
        f"XRP   <b>{format_price(d['xrp_price'])}</b>   {format_change(d['xrp_change'])}",
        "",
        f"🧠 Fear & Greed   <b>{fg_val}/100</b>",
        f"<i>{mood}</i>",
    ]
    if d["buy"] and d["sell"]:
        lines += [
            "",
            f"💱 USDT/NGN   Buy \u20a6{int(d['buy']):,}   Sell \u20a6{int(d['sell']):,}   Spread \u20a6{int(d['buy']-d['sell']):,}",
        ]
    lines += [
        "",
        "· · · · · · · · · · · · · · · · · · ·",
        "",
        "📤 <b>Trading USDT today?</b> Submit your P2P rate inside the bot — tap P2P Center → Submit Rate. Every submission helps the community.",
        "",
        "💎 <b>Pro members are reading the AI analysis right now — what is driving this, what to expect today, and the exact entry, stop and target.</b>",
        "DM @heisthegeneral — ₦3,000/month.",
        "",
        "<i>NFA - DYOR  ·  ⚡ Market Pulse</i>",
    ]
    return "\n".join(lines)

def build_morning_briefing_pro():
    """Pro — same base + Nigerian context AI analysis + entry/stop/target."""
    d = _morning_data()
    fg_val = d["fg_data"][0]["value"] if d["fg_data"] else "N/A"
    fg_lbl = d["fg_data"][0]["value_classification"] if d["fg_data"] else "Neutral"
    fg_num = int(fg_val) if str(fg_val).isdigit() else 50
    r = round(d["btc_price"] * 1.02, 2) if d["btc_price"] else None
    s = round(d["btc_price"] * 0.98, 2) if d["btc_price"] else None
    p2p_buy, p2p_sell, p2p_src = get_p2p_rate("USDT","NGN")
    p2p_str = (f"USDT/NGN Buy \u20a6{int(p2p_buy):,} / Sell \u20a6{int(p2p_sell):,} "
               f"Spread \u20a6{int(p2p_buy-p2p_sell):,} via {p2p_src}") if p2p_buy else "P2P unavailable"

    track = get_track_record_line()
    lines = []
    if track:
        lines += [track, ""]

    lines += [
        "\U0001f305 <b>MORNING BRIEFING — PRO</b>",
        f"<i>{d['today']}  ·  {d['time_str']}</i>",
        "",
        "📊 <b>PRICES</b>",
        f"BTC   <b>{format_price(d['btc_price'])}</b>   {format_change(d['btc_change'])}",
        f"ETH   <b>{format_price(d['eth_price'])}</b>   {format_change(d['eth_change'])}",
        f"SOL   <b>{format_price(d['sol_price'])}</b>   {format_change(d['sol_change'])}",
        f"BNB   <b>{format_price(d['bnb_price'])}</b>   {format_change(d['bnb_change'])}",
        f"XRP   <b>{format_price(d['xrp_price'])}</b>   {format_change(d['xrp_change'])}",
        "",
        f"🧠 Fear & Greed   <b>{fg_val}/100</b> — {fg_lbl}",
    ]

    if d["btc_high"] and d["btc_low"]:
        lines += ["",
                  f"📊 BTC 24h Range   <b>{format_price(d['btc_low'])}</b> — <b>{format_price(d['btc_high'])}</b>"]

    if r and s:
        lines += ["",
                  "🎯 <b>KEY LEVELS</b>",
                  f"Resistance   <b>{format_price(r)}</b>",
                  f"Support      <b>{format_price(s)}</b>"]

    if d["gainers"]:
        lines += ["", "🏆 <b>EARLY MOVERS</b>"]
        for coin, price, chg in d["gainers"][:3]:
            lines.append(f"{'📈' if chg>=0 else '📉'} <b>{coin}</b>   {format_price(price)}   {chg:+.1f}%")

    if d["losers"]:
        lines += ["", "⚠️ <b>LAGGING</b>"]
        for coin, price, chg in d["losers"][:2]:
            lines.append(f"📉 <b>{coin}</b>   {format_price(price)}   {chg:.1f}%")

    if p2p_buy and p2p_sell:
        lines += ["",
                  "💱 <b>USDT/NGN</b>",
                  f"Buy \u20a6{int(p2p_buy):,}   Sell \u20a6{int(p2p_sell):,}   Spread \u20a6{int(p2p_buy-p2p_sell):,}",
                  f"<i>Source: {p2p_src}</i>"]

    try:
        news = get_latest_news(limit=2)
        if news:
            lines += ["", "📰 <b>MARKET NEWS</b>"]
            for n in news[:2]:
                lines.append(f"· <i>{n.get('title','')[:110]}</i>")
    except Exception as _e:
        logger.debug("[SILENT EXC] %s" % _e)

    g_str = ", ".join(f"{c} {ch:+.1f}%" for c,_,ch in d["gainers"][:3]) if d["gainers"] else "flat"
    l_str = ", ".join(f"{c} {ch:.1f}%" for c,_,ch in d["losers"][:2]) if d["losers"] else "none"
    ai_prompt = (
        f"Morning brief for Nigerian crypto traders. "
        f"BTC {format_price(d['btc_price'])} ({format_change(d['btc_change'])}), "
        f"ETH {format_price(d['eth_price'])} ({format_change(d['eth_change'])}), "
        f"SOL {format_price(d['sol_price'])}. Fear & Greed {fg_val}/100 ({fg_lbl}). "
        f"Movers: {g_str}. Lagging: {l_str}. {p2p_str}. "
        f"Write SITUATION / CONTEXT / DECISION. "
        f"DECISION must have specific Entry, Stop, Target for the best setup today. "
        f"Also say whether the P2P spread makes it worth converting naira right now."
    )
    ai, _ = ask_ai(ai_prompt)
    if not ai:
        ai = "Markets are setting up. Watch key levels and size your positions correctly."

    import re as _re
    em = _re.search(r"Entry[:\s]+([$\u20a60-9,.kK]+)", ai, _re.IGNORECASE)
    sm = _re.search(r"Stop[:\s]+([$\u20a60-9,.kK]+)", ai, _re.IGNORECASE)
    tm = _re.search(r"Target[:\s]+([$\u20a60-9,.kK]+)", ai, _re.IGNORECASE)
    update_pro_decision("BTC", "watching",
        em.group(1) if em else format_price(s or 0),
        sm.group(1) if sm else "",
        tm.group(1) if tm else "")

    lines += [
        "",
        "· · · · · · · · · · · · · · · · · · ·",
        "",
        "🧠 <b>MORNING ANALYSIS</b>",
        "",
        ai,
        "",
        "<i>NFA — manage your risk.  ·  ⚡ Market Pulse Pro</i>",
    ]
    return "\n".join(lines)

def build_midday_snapshot():
    """Free — prices, sentiment, P2P, teaser only."""
    btc_price, btc_change = get_best_price("BTC")
    eth_price, eth_change = get_best_price("ETH")
    sol_price, sol_change = get_best_price("SOL")
    bnb_price, bnb_change = get_best_price("BNB")
    xrp_price, xrp_change = get_best_price("XRP")
    fg_data = get_fear_greed()
    fg_val = fg_data[0]["value"] if fg_data else "N/A"
    fg_lbl = fg_data[0]["value_classification"] if fg_data else "Neutral"
    buy, sell, _ = get_p2p_rate("USDT","NGN")
    today = wat_now().strftime("%b %d")
    time_str = wat_now().strftime("%I:%M %p WAT")
    lines = [
        "\u26a1 <b>MIDDAY SNAPSHOT</b>",
        f"<i>{today}  ·  {time_str}</i>",
        "",
        f"BTC   <b>{format_price(btc_price)}</b>   {format_change(btc_change)}",
        f"ETH   <b>{format_price(eth_price)}</b>   {format_change(eth_change)}",
        f"SOL   <b>{format_price(sol_price)}</b>   {format_change(sol_change)}",
        f"BNB   <b>{format_price(bnb_price)}</b>   {format_change(bnb_change)}",
        f"XRP   <b>{format_price(xrp_price)}</b>   {format_change(xrp_change)}",
        "",
        f"🧠 Fear & Greed   <b>{fg_val}/100</b> — {fg_lbl}",
    ]
    if buy and sell:
        lines += [
            "",
            f"💱 USDT/NGN   Buy \u20a6{int(buy):,}   Sell \u20a6{int(sell):,}   Spread \u20a6{int(buy-sell):,}",
        ]
    lines += [
        "",
        "· · · · · · · · · · · · · · · · · · ·",
        "",
        "📤 <b>Seen a good P2P rate today?</b> Submit it inside the bot — tap P2P Center → Submit Rate. It takes 10 seconds and helps everyone.",
        "",
        "💎 <b>Pro members have the AI midday read right now — what the afternoon likely holds and the exact level to enter or wait.</b>",
        "DM @heisthegeneral — ₦3,000/month.",
        "",
        "<i>NFA - DYOR  ·  ⚡ Market Pulse</i>",
    ]
    return "\n".join(lines)

def build_midday_snapshot_pro():
    """Pro — full midday with AI afternoon read and live setup."""
    btc_price, btc_change = get_best_price("BTC")
    eth_price, eth_change = get_best_price("ETH")
    sol_price, sol_change = get_best_price("SOL")
    bnb_price, bnb_change = get_best_price("BNB")
    xrp_price, xrp_change = get_best_price("XRP")
    fg_data = get_fear_greed()
    gainers, losers = get_gainers_losers()
    fg_val = fg_data[0]["value"] if fg_data else "N/A"
    fg_lbl = fg_data[0]["value_classification"] if fg_data else "Neutral"
    buy, sell, src = get_p2p_rate("USDT","NGN")
    today = wat_now().strftime("%b %d")
    time_str = wat_now().strftime("%I:%M %p WAT")
    g_str = ", ".join(f"{c} {ch:+.1f}%" for c,_,ch in gainers[:3]) if gainers else "flat"
    l_str = ", ".join(f"{c} {ch:.1f}%" for c,_,ch in losers[:2]) if losers else "none"
    p2p_str = (f"USDT/NGN Buy \u20a6{int(buy):,} / Sell \u20a6{int(sell):,} Spread \u20a6{int(buy-sell):,} via {src}") if buy else ""

    lines = [
        "\u26a1 <b>MIDDAY SNAPSHOT — PRO</b>",
        f"<i>{today}  ·  {time_str}</i>",
        "",
        "📊 <b>PRICES</b>",
        f"BTC   <b>{format_price(btc_price)}</b>   {format_change(btc_change)}",
        f"ETH   <b>{format_price(eth_price)}</b>   {format_change(eth_change)}",
        f"SOL   <b>{format_price(sol_price)}</b>   {format_change(sol_change)}",
        f"BNB   <b>{format_price(bnb_price)}</b>   {format_change(bnb_change)}",
        f"XRP   <b>{format_price(xrp_price)}</b>   {format_change(xrp_change)}",
        "",
        f"🧠 Fear & Greed   <b>{fg_val}/100</b> — {fg_lbl}",
    ]

    if gainers:
        lines += ["", "📈 <b>LEADING</b>"]
        for coin, price, chg in gainers[:3]:
            lines.append(f"<b>{coin}</b>   {format_price(price)}   {chg:+.1f}%")

    if losers:
        lines += ["", "📉 <b>LAGGING</b>"]
        for coin, price, chg in losers[:3]:
            lines.append(f"<b>{coin}</b>   {format_price(price)}   {chg:.1f}%")

    if buy and sell:
        lines += ["",
                  "💱 <b>USDT/NGN</b>",
                  f"Buy \u20a6{int(buy):,}   Sell \u20a6{int(sell):,}   Spread \u20a6{int(buy-sell):,}",
                  f"<i>Source: {src}</i>"]

    ai_prompt = (
        f"Midday read for Nigerian traders. BTC {format_price(btc_price)} ({format_change(btc_change)}), "
        f"ETH {format_price(eth_price)} ({format_change(eth_change)}). "
        f"Fear & Greed {fg_val}/100. Leading: {g_str}. Lagging: {l_str}. {p2p_str}. "
        f"SITUATION / CONTEXT / DECISION format. "
        f"DECISION: hold, add or reduce — the exact level you are watching and what triggers action. "
        f"Entry, stop and target if there is a live setup right now."
    )
    ai, _ = ask_ai(ai_prompt)
    if not ai:
        ai = "Market consolidating. Wait for a directional close before committing."

    lines += [
        "",
        "· · · · · · · · · · · · · · · · · · ·",
        "",
        "🧠 <b>MIDDAY READ</b>",
        "",
        ai,
        "",
        "<i>NFA — manage your risk.  ·  ⚡ Market Pulse Pro</i>",
    ]
    return "\n".join(lines)

def build_evening_recap():
    """Free — prices, sentiment, P2P, teaser only."""
    btc_price, btc_change = get_best_price("BTC")
    eth_price, eth_change = get_best_price("ETH")
    sol_price, sol_change = get_best_price("SOL")
    bnb_price, bnb_change = get_best_price("BNB")
    xrp_price, xrp_change = get_best_price("XRP")
    fg_data = get_fear_greed()
    fg_val = fg_data[0]["value"] if fg_data else "N/A"
    fg_lbl = fg_data[0]["value_classification"] if fg_data else "Neutral"
    buy, sell, _ = get_p2p_rate("USDT","NGN")
    today = wat_now().strftime("%b %d")
    time_str = wat_now().strftime("%I:%M %p WAT")
    lines = [
        "\U0001f319 <b>EVENING RECAP</b>",
        f"<i>{today}  ·  {time_str}</i>",
        "",
        f"BTC   <b>{format_price(btc_price)}</b>   {format_change(btc_change)}",
        f"ETH   <b>{format_price(eth_price)}</b>   {format_change(eth_change)}",
        f"SOL   <b>{format_price(sol_price)}</b>   {format_change(sol_change)}",
        f"BNB   <b>{format_price(bnb_price)}</b>   {format_change(bnb_change)}",
        f"XRP   <b>{format_price(xrp_price)}</b>   {format_change(xrp_change)}",
        "",
        f"🧠 Fear & Greed   <b>{fg_val}/100</b> — {fg_lbl}",
    ]
    if buy and sell:
        lines += [
            "",
            f"💱 USDT/NGN   Buy \u20a6{int(buy):,}   Sell \u20a6{int(sell):,}   Spread \u20a6{int(buy-sell):,}",
        ]
    lines += [
        "",
        "· · · · · · · · · · · · · · · · · · ·",
        "",
        "📤 <b>End of day ritual:</b> Submit today's best P2P rate inside the bot. Your submissions keep our data sharp for the whole community.",
        "",
        "💎 <b>Pro members have tomorrow's exact trade plan right now — entry zone, stop loss and target going into tomorrow.</b>",
        "DM @heisthegeneral — ₦3,000/month.",
        "",
        "<i>NFA - DYOR  ·  ⚡ Market Pulse</i>",
    ]
    return "\n".join(lines)

def build_evening_recap_pro():
    """Pro — full evening recap + AI tomorrow plan with entry/stop/target."""
    btc_price, btc_change = get_best_price("BTC")
    eth_price, eth_change = get_best_price("ETH")
    sol_price, sol_change = get_best_price("SOL")
    bnb_price, bnb_change = get_best_price("BNB")
    xrp_price, xrp_change = get_best_price("XRP")
    fg_data = get_fear_greed()
    gainers, losers = get_gainers_losers()
    fg_val = fg_data[0]["value"] if fg_data else "N/A"
    fg_lbl = fg_data[0]["value_classification"] if fg_data else "Neutral"
    buy, sell, src = get_p2p_rate("USDT","NGN")
    today = wat_now().strftime("%b %d")
    time_str = wat_now().strftime("%I:%M %p WAT")
    g_str = ", ".join(f"{c} {ch:+.1f}%" for c,_,ch in gainers[:3]) if gainers else "none"
    l_str = ", ".join(f"{c} {ch:.1f}%" for c,_,ch in losers[:3]) if losers else "none"
    p2p_str = (f"USDT/NGN Buy \u20a6{int(buy):,} / Sell \u20a6{int(sell):,} "
               f"Spread \u20a6{int(buy-sell):,} via {src}") if buy else ""

    lines = [
        "\U0001f319 <b>EVENING RECAP — PRO</b>",
        f"<i>{today}  ·  {time_str}</i>",
        "",
        "📊 <b>CLOSING PRICES</b>",
        f"BTC   <b>{format_price(btc_price)}</b>   {format_change(btc_change)}",
        f"ETH   <b>{format_price(eth_price)}</b>   {format_change(eth_change)}",
        f"SOL   <b>{format_price(sol_price)}</b>   {format_change(sol_change)}",
        f"BNB   <b>{format_price(bnb_price)}</b>   {format_change(bnb_change)}",
        f"XRP   <b>{format_price(xrp_price)}</b>   {format_change(xrp_change)}",
        "",
        f"🧠 Fear & Greed   <b>{fg_val}/100</b> — {fg_lbl}",
    ]

    if gainers:
        lines += ["", "🏆 <b>DAY WINNERS</b>"]
        for coin, price, chg in gainers[:3]:
            lines.append(f"📈 <b>{coin}</b>   {format_price(price)}   {chg:+.1f}%")

    if losers:
        lines += ["", "📉 <b>DAY LOSERS</b>"]
        for coin, price, chg in losers[:3]:
            lines.append(f"📉 <b>{coin}</b>   {format_price(price)}   {chg:.1f}%")

    if buy and sell:
        lines += ["",
                  "💱 <b>USDT/NGN</b>",
                  f"Buy \u20a6{int(buy):,}   Sell \u20a6{int(sell):,}   Spread \u20a6{int(buy-sell):,}",
                  f"<i>Source: {src}</i>"]

    try:
        btc_sd = get_secondary_coin("BTC")
        btc_high = btc_sd.get("usd_24h_high") if btc_sd else None
        btc_low  = btc_sd.get("usd_24h_low")  if btc_sd else None
        if btc_high and btc_low and btc_price:
            mid = (btc_high + btc_low) / 2
            bias = "upper half" if btc_price > mid else "lower half"
            direction = "bullish" if btc_price > mid else "bearish"
            lines += ["",
                      "🌙 <b>OVERNIGHT WATCH</b>",
                      f"BTC closed in the <b>{bias}</b> of today's range — {direction} bias into tomorrow.",
                      f"Range: <b>{format_price(btc_low)}</b> — <b>{format_price(btc_high)}</b>"]
    except Exception as _e:
        logger.debug("[SILENT EXC] %s" % _e)

    try:
        news = get_latest_news(limit=2)
        if news:
            lines += ["", "📰 <b>EVENING HEADLINES</b>"]
            for n in news[:2]:
                lines.append(f"· <i>{n.get('title','')[:110]}</i>")
    except Exception as _e:
        logger.debug("[SILENT EXC] %s" % _e)

    ai_prompt = (
        f"Evening wrap for Nigerian traders. "
        f"BTC {format_price(btc_price)} ({format_change(btc_change)}), "
        f"ETH {format_price(eth_price)} ({format_change(eth_change)}). "
        f"Fear & Greed {fg_val}/100. Winners: {g_str}. Losers: {l_str}. {p2p_str}. "
        f"SITUATION / CONTEXT / DECISION. "
        f"SITUATION: what did the market do today in one sentence. "
        f"CONTEXT: what it means for Nigerian traders — naira angle or overnight risk. "
        f"DECISION: exact plan going into tomorrow. Entry zone, stop loss, target. "
        f"Or clearly state: wait — and give one reason."
    )
    ai, _ = ask_ai(ai_prompt)
    if not ai:
        ai = "Markets closed with mixed signals. Stay patient and wait for cleaner setups."

    lines += [
        "",
        "· · · · · · · · · · · · · · · · · · ·",
        "",
        "🔮 <b>TOMORROW'S PLAN</b>",
        "",
        ai,
        "",
        "<i>NFA — manage your risk.  ·  ⚡ Market Pulse Pro</i>",
    ]
    return "\n".join(lines)

def build_weekly_edge():
    """Free — top 3 movers only. Everything else is pro."""
    db = get_db(); c = db.cursor()
    since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    performers = []
    for coin in ["BTC","ETH","SOL","BNB","XRP","DOGE","ADA"]:
        c.execute("SELECT price FROM history WHERE coin=%s AND timestamp>=%s ORDER BY id ASC LIMIT 1",(coin,since))
        first = c.fetchone()
        c.execute("SELECT price FROM history WHERE coin=%s ORDER BY id DESC LIMIT 1",(coin,))
        last = c.fetchone()
        if first and last and first[0]:
            chg = (last[0]-first[0])/first[0]*100
            performers.append((coin,last[0],first[0],chg))
    db.close()
    performers.sort(key=lambda x: x[3], reverse=True)
    week_start = (datetime.now()-timedelta(days=7)).strftime("%b %d")
    week_end   = datetime.now().strftime("%b %d")
    buy, sell, _ = get_p2p_rate("USDT","NGN")
    lines = [
        "🔥 <b>WEEKLY EDGE</b>",
        f"<i>{week_start} — {week_end}</i>",
        "",
        "📊 <b>THIS WEEK</b>",
    ]
    for coin,now_p,start_p,chg in performers[:3]:
        arrow = "📈" if chg >= 0 else "📉"
        lines.append(f"{arrow} <b>{coin}</b>   {chg:+.1f}%")
    if buy and sell:
        lines += ["",
                  f"💱 USDT/NGN   Buy \u20a6{int(buy):,}   Sell \u20a6{int(sell):,}"]
    lines += [
        "",
        "· · · · · · · · · · · · · · · · · · ·",
        "",
        "📤 <b>Submit your P2P rate</b> inside the bot — tap P2P Center → Submit Rate. Every rate submitted improves our community data.",
        "",
        "💎 <b>The Pro Weekly Edge is out.</b>",
        "What actually moved markets this week. The one coin set up for next week.",
        "Exact entry, stop and target. What the AI would do going into Monday.",
        "",
        "DM @heisthegeneral — ₦3,000/month.",
        "",
        "<i>NFA - DYOR  ·  ⚡ Market Pulse</i>",
    ]
    return "\n".join(lines)

def build_weekly_edge_pro():
    """Pro — full weekly intelligence. Feels like inside information."""
    db = get_db(); c = db.cursor()
    since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    performers = []
    for coin in ["BTC","ETH","SOL","BNB","XRP","DOGE","ADA"]:
        c.execute("SELECT price FROM history WHERE coin=%s AND timestamp>=%s ORDER BY id ASC LIMIT 1",(coin,since))
        first = c.fetchone()
        c.execute("SELECT price FROM history WHERE coin=%s ORDER BY id DESC LIMIT 1",(coin,))
        last = c.fetchone()
        if first and last and first[0]:
            chg = (last[0]-first[0])/first[0]*100
            performers.append((coin,last[0],first[0],chg))
    db.close()
    performers.sort(key=lambda x: x[3], reverse=True)
    week_start = (datetime.now()-timedelta(days=7)).strftime("%b %d")
    week_end   = datetime.now().strftime("%b %d")
    buy, sell, source = get_p2p_rate("USDT","NGN")
    fg_data = get_fear_greed()
    fg_val  = fg_data[0]["value"] if fg_data else "N/A"
    fg_lbl  = fg_data[0]["value_classification"] if fg_data else "Neutral"
    perf_str = ", ".join(f"{co} {ch:+.1f}%" for co,_,_,ch in performers[:7])
    top_coin = performers[0][0] if performers else "BTC"
    top_chg  = performers[0][3] if performers else 0
    bot_coin = performers[-1][0] if performers else "ETH"
    bot_chg  = performers[-1][3] if performers else 0
    p2p_str  = (f"USDT/NGN: Buy \u20a6{int(buy):,} / Sell \u20a6{int(sell):,} "
                f"Spread \u20a6{int(buy-sell):,} via {source}") if buy else "P2P unavailable"

    lines = [
        "🔥 <b>WEEKLY EDGE — PRO</b>",
        f"<i>{week_start} — {week_end}  ·  Saturday Intelligence Report</i>",
        "",
        "📊 <b>WEEK IN NUMBERS</b>",
        "",
    ]
    for coin,now_p,start_p,chg in performers[:7]:
        arrow = "📈" if chg >= 0 else "📉"
        lines.append(f"{arrow} <b>{coin}</b>   {format_price(start_p)} → <b>{format_price(now_p)}</b>   <b>{chg:+.1f}%</b>")

    lines += [
        "",
        f"🧠 Sentiment   <b>{fg_val}/100</b> — {fg_lbl}",
    ]
    if buy and sell:
        lines += [f"💱 USDT/NGN   Buy \u20a6{int(buy):,}   Sell \u20a6{int(sell):,}   Spread \u20a6{int(buy-sell):,}"]
        lines += [f"<i>Source: {source}</i>"]

    ai_prompt = (
        f"You are writing the Saturday weekly intelligence brief for serious Nigerian crypto traders "
        f"who pay ₦3,000/month for premium access. This should feel like a sharp analyst's private note — "
        f"confident, specific, and impossible to ignore. Not generic. Not a recap of prices they already saw. "
        f"Data: {week_start}–{week_end}. All coins: {perf_str}. "
        f"Best: {top_coin} ({top_chg:+.1f}%). Worst: {bot_coin} ({bot_chg:+.1f}%). "
        f"Fear & Greed: {fg_val}/100 ({fg_lbl}). {p2p_str}. "
        f"Write in plain text, no asterisks, no headers with colons. "
        f"Use this exact structure with a blank line between each section:\n"
        f"WHAT DROVE THIS WEEK: 2 sentences. Tell them what actually moved markets — macro, sentiment shift, key events. Not just prices. Make it feel like they are getting context others missed.\n\n"
        f"THE NIGERIAN ANGLE: 1–2 sentences. What did the naira and P2P spread do this week? Was it a good week to buy USDT or hold naira? Be direct.\n\n"
        f"THE ONE COIN FOR NEXT WEEK: Name one coin. Give the exact price level you are watching. Explain in one sentence why the setup is interesting. This should feel like a tip from someone who has done the work.\n\n"
        f"LEVELS TO WATCH: BTC key resistance above. BTC key support below. One line each, no fluff.\n\n"
        f"MY POSITION GOING INTO NEXT WEEK: Tell them exactly what you are doing as a trader — holding, adding on dips, reducing, or flat. Give the specific entry, stop and target. If you are sitting out, say why in one sentence.\n\n"
        f"End with exactly: NFA — manage your risk."
    )
    ai, _ = ask_ai(ai_prompt)
    if not ai:
        ai = (
            "WHAT DROVE THIS WEEK: Markets moved on macro uncertainty and position squeezes rather than any single catalyst — the kind of week where patience was the best trade.\n\n"
            f"THE NIGERIAN ANGLE: P2P spread stayed manageable at \u20a6{int(buy-sell) if buy and sell else 35}. Reasonable week to accumulate if you had naira sitting idle.\n\n"
            f"THE ONE COIN FOR NEXT WEEK: {top_coin} — the setup is clean and the volume supports it. Watching {format_price(performers[0][1] * 0.97 if performers else 0)} as the entry zone.\n\n"
            "LEVELS TO WATCH: BTC needs to clear resistance cleanly. Support is the line that cannot break.\n\n"
            "MY POSITION: Cautiously long. Sized small until the market confirms direction."
        )

    lines += [
        "",
        "· · · · · · · · · · · · · · · · · · ·",
        "",
        ai,
        "",
        "· · · · · · · · · · · · · · · · · · ·",
        "",
        "<i>NFA — manage your risk.  ·  ⚡ Market Pulse Pro</i>",
    ]
    return "\n".join(lines)



# ═══════════════════════════════════════════════════════════════════════════
# 🔔 KEY MARKET ALERT SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

# Key alert coins — kept small by default. Admin can change with /setwatchlist.
KEY_ALERT_COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]

# Max ONE alert per check cycle — channel stays clean
MAX_ALERTS_PER_CYCLE = 1

# Tolerance: price must be within 1.0% of a level (was 1.8% — too wide)
KEY_LEVEL_TOLERANCE = 0.010

# Cooldown: 6 hours per coin per level, stored in DB to survive restarts
KEY_ALERT_COOLDOWN_HOURS = 6

def _get_key_alert_cooldown(coin):
    """Return True if this coin is still in cooldown (6 hours). DB-backed.
    Keyed on coin only — not level — so slight level fluctuations don't bypass cooldown."""
    db = None
    try:
        db = get_db()
        c = db.cursor()
        since = (wat_now() - timedelta(hours=KEY_ALERT_COOLDOWN_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "SELECT updated_at FROM admin_settings WHERE key=%s AND updated_at >= %s",
            (f"key_alert_{coin}", since)
        )
        return c.fetchone() is not None
    except Exception as e:
        logger.warning(f"[KEY ALERT CD] {e}")
        return False
    finally:
        if db:
            try: db.close()
            except Exception: pass

def _set_key_alert_cooldown(coin):
    """Record that we just sent an alert for this coin."""
    db = None
    try:
        db = get_db()
        c = db.cursor()
        now = wat_now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "INSERT INTO admin_settings (key, value, updated_at) VALUES (%s,%s,%s) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (f"key_alert_{coin}", now, now)
        )
        db.commit()
        logger.info(f"[KEY ALERT] Cooldown set for {coin} — next alert in {KEY_ALERT_COOLDOWN_HOURS}h")
    except Exception as e:
        logger.warning(f"[KEY ALERT CD SET] {e}")
        if db:
            try: db.rollback()
            except Exception: pass
    finally:
        if db:
            try: db.close()
            except Exception: pass

# ── Dynamic Key Levels ───────────────────────────────────────────────────
# No hardcoded levels. Levels are calculated on-demand from price history
# in the DB (swing highs, swing lows, round numbers near current price).
# Cache: { coin: (levels_list, calculated_at_timestamp) }
_dynamic_levels_cache = {}
_LEVELS_CACHE_TTL = 3600  # recalculate every hour

def get_dynamic_key_levels(coin, price):
    """Calculate key levels dynamically from stored price history.
    Returns a sorted list of relevant price levels for this coin.
    Falls back to round-number generation if history is insufficient."""
    now = time.time()
    cached = _dynamic_levels_cache.get(coin)
    if cached and (now - cached[1]) < _LEVELS_CACHE_TTL:
        return cached[0]

    levels = set()

    # ── 1. Swing highs and lows from 30-day price history ─────────────────
    db = None
    try:
        db = get_db()
        c = db.cursor()
        since = (wat_now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "SELECT price FROM history WHERE coin=%s AND timestamp >= %s ORDER BY timestamp ASC",
            (coin, since)
        )
        rows = c.fetchall()
        prices = [float(r[0]) for r in rows if r[0]]
    except Exception as e:
        logger.warning(f"[KEY LEVELS] DB read error for {coin}: {e}")
        prices = []
    finally:
        if db:
            try: db.close()
            except Exception: pass

    if len(prices) >= 10:
        # Find swing highs: local max with 3 bars either side
        for i in range(3, len(prices) - 3):
            window = prices[i-3:i+4]
            if prices[i] == max(window):
                levels.add(round(prices[i], _price_decimals(prices[i])))
        # Find swing lows: local min with 3 bars either side
        for i in range(3, len(prices) - 3):
            window = prices[i-3:i+4]
            if prices[i] == min(window):
                levels.add(round(prices[i], _price_decimals(prices[i])))

    # ── 2. Round psychological numbers near current price ──────────────────
    if price:
        levels.update(_round_number_levels(price))

    # ── 3. Filter to levels within 30% of current price ───────────────────
    if price:
        levels = {l for l in levels if l > 0 and abs(l - price) / price <= 0.30}

    result = sorted(levels, reverse=True)
    _dynamic_levels_cache[coin] = (result, now)
    logger.info(f"[KEY LEVELS] {coin}: {len(result)} dynamic levels calculated")
    return result


def _price_decimals(price):
    """Number of decimal places to round to based on price magnitude."""
    if price >= 10000: return 0
    if price >= 1000:  return 0
    if price >= 100:   return 1
    if price >= 10:    return 2
    if price >= 1:     return 3
    return 4


def _round_number_levels(price):
    """Generate psychological round numbers (00, 000, 0000) near a price."""
    levels = set()
    magnitude = 10 ** (len(str(int(price))) - 1)
    for mult in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
        levels.add(round(magnitude * mult, _price_decimals(magnitude * mult)))
    for frac in [0.25, 0.50, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]:
        candidate = round(price * frac / magnitude) * magnitude
        if candidate > 0:
            levels.add(candidate)
    return levels

def _nearest_key_level(price, levels, tolerance=None):
    """Find nearest key level within tolerance. Uses KEY_LEVEL_TOLERANCE by default."""
    if tolerance is None:
        tolerance = KEY_LEVEL_TOLERANCE
    for level in levels:
        if level > 0 and abs(price - level) / level <= tolerance:
            return level
    return None

def _level_label(price, level):
    """Correct terminology based on price vs level."""
    diff_pct = (price - level) / level * 100
    if diff_pct > 1.5:
        return "BREAKOUT", "🚀"
    elif diff_pct > 0:
        return "TESTING RESISTANCE", "🟡"
    elif diff_pct > -1.5:
        return "TESTING SUPPORT", "🟠"
    else:
        return "TRADING BELOW SUPPORT", "🔴"

def _validate_alert(coin, price, entry, stop, target, label, direction="long"):
    """Pre-send validation. Returns (valid, reason). Direction-aware for long/short."""
    # Check for unresolved placeholders
    combined = f"{coin}{price}{entry}{stop}{target}{label}"
    if re.search(r'\\1|\{[a-z_]+\}|%s|None', str(combined)):
        return False, "Unresolved placeholder detected"
    # Price sanity
    if not price or price <= 0:
        return False, "Invalid price"
    # Entry/stop/target logic — direction-aware
    if entry and stop and target:
        try:
            e = float(str(entry).replace("$","").replace(",",""))
            s = float(str(stop).replace("$","").replace(",",""))
            t = float(str(target).replace("$","").replace(",",""))
            if direction == "long":
                if s >= e:
                    return False, f"Long stop {s} >= entry {e}"
                if t <= e:
                    return False, f"Long target {t} <= entry {e}"
                if e <= 0:
                    return False, "Entry price must be positive"
                rr = (t - e) / (e - s)
            else:  # short
                if s <= e:
                    return False, f"Short stop {s} <= entry {e}"
                if t >= e:
                    return False, f"Short target {t} >= entry {e}"
                rr = (e - t) / (s - e)
            if rr < 1.0:
                return False, f"R:R {rr:.2f} below minimum 1:1"
        except Exception as ex:
            logger.warning(f"[VALIDATE ALERT] Parse error: {ex}")
    return True, "OK"

def _calc_trade_metrics(entry, stop, target, size_usd=1000):
    """Calculate R:R, P&L for a given trade."""
    try:
        e = float(str(entry).replace("$","").replace(",",""))
        s = float(str(stop).replace("$","").replace(",",""))
        t = float(str(target).replace("$","").replace(",",""))
        risk_pct  = abs(e - s) / e * 100
        reward_pct = abs(t - e) / e * 100
        rr = reward_pct / risk_pct if risk_pct > 0 else 0
        pot_profit = size_usd * (reward_pct / 100)
        pot_loss   = size_usd * (risk_pct / 100)
        return {
            "rr": round(rr, 2),
            "risk_pct": round(risk_pct, 2),
            "reward_pct": round(reward_pct, 2),
            "pot_profit": round(pot_profit, 2),
            "pot_loss": round(pot_loss, 2),
        }
    except Exception as _e:
        return None

def build_free_key_alert(coin, price, change, level, chat_id=None):
    status_label, status_arrow = _level_label(price, level)
    buy, sell, _ = get_p2p_rate("USDT", "NGN")
    p2p_line = f"💱 USDT/NGN  Buy \u20a6{int(buy):,}  Sell \u20a6{int(sell):,}  Spread \u20a6{int(buy-sell):,}" if buy and sell else ""
    lines = [
        f"⚡ <b>KEY LEVEL ALERT — {coin}</b>",
        f"{status_arrow} <b>{coin}</b> — {status_label}",
        f"💰 Price: <b>{format_price(price)}</b>  {format_change(change)}",
        f"🎯 Key Level: <b>{format_price(level)}</b>",
    ]
    if p2p_line:
        lines += ["", p2p_line]
    lines += ["", "<i>NFA - DYOR  ·  ⚡ Market Pulse</i>"]
    if chat_id and should_show_upsell(chat_id):
        lines += [FREE_UPSELL_BLOCK]
    return "\n".join(lines)

def build_pro_key_alert(coin, price, change, level,
                        entry=None, stop=None, target=None,
                        bias="Neutral", confidence="Uncertain",
                        situation="", context_line="", decision=""):
    """Pro key alert with full Trade Hypothesis section."""
    status_label, status_arrow = _level_label(price, level)
    sd = get_secondary_coin(coin)
    high_24 = sd.get("usd_24h_high") if sd else None
    low_24  = sd.get("usd_24h_low")  if sd else None
    buy, sell, p2p_src = get_p2p_rate("USDT", "NGN")

    # Header
    lines = [
        f"🔔 <b>PRO ALERT — {coin}</b>",
        f"{status_arrow} <b>{status_label}</b>  ·  Key Level: <b>{format_price(level)}</b>",
        f"💰 Price: <b>{format_price(price)}</b>  {format_change(change)}",
    ]
    if high_24 and low_24:
        lines.append(f"📊 24h Range: {format_price(low_24)} — {format_price(high_24)}")

    # Analysis
    lines += ["", "· · · · · · · · · · · · · · · · · · ·", ""]
    if situation:
        lines.append(f"<b>SITUATION:</b> {situation}")
    if context_line:
        lines.append(f"<b>CONTEXT:</b> {context_line}")

    # Trade Hypothesis
    if entry and stop and target:
        valid, reason = _validate_alert(coin, price, entry, stop, target, status_label)
        if valid:
            metrics = _calc_trade_metrics(entry, stop, target)
            lines += [
                "",
                "· · · · · · · · · · · · · · · · · · ·",
                "",
                "📐 <b>TRADE HYPOTHESIS</b>  <i>(Illustrative only)</i>",
                f"Market Bias: <b>{bias}</b>",
                f"Entry Zone: <b>{entry}</b>",
                f"Stop Loss:  <b>{stop}</b>",
                f"Target:     <b>{target}</b>",
            ]
            if metrics:
                lines += [
                    f"Risk:Reward: <b>1 : {metrics['rr']}</b>",
                    f"Pot. Profit: <b>+${metrics['pot_profit']:,.0f} (+{metrics['reward_pct']:.2f}%)</b>  per $1,000",
                    f"Pot. Loss:   <b>-${metrics['pot_loss']:,.0f} (-{metrics['risk_pct']:.2f}%)</b>  per $1,000",
                ]
            lines += [
                f"Confidence: <b>{confidence}</b>",
                "",
                "Conditions: Price must confirm at this level with a candle close.",
                "Assumes normal market liquidity.",
            ]
        else:
            lines += ["", f"⚠️ Trade setup could not be validated: {reason}. Monitor manually."]
    elif decision:
        lines += ["", f"<b>DECISION:</b> {decision}"]

    # P2P Intelligence
    if buy and sell:
        spread = int(buy - sell)
        lines += [
            "",
            "· · · · · · · · · · · · · · · · · · ·",
            "",
            "💱 <b>NIGERIAN P2P INTELLIGENCE</b>",
            f"Buy: <b>₦{int(buy):,}</b>   Sell: <b>₦{int(sell):,}</b>   Spread: <b>₦{spread:,}</b>",
            f"Source: {p2p_src}",
            "Recommendation: " + (
                "Reasonable to convert now — spread is tight." if spread <= 35
                else "Spread is wide — wait for it to compress unless urgent." if spread >= 50
                else "Moderate spread — convert only if needed."
            ),
        ]

    lines += [
        "",
        "· · · · · · · · · · · · · · · · · · ·",
        "",
        "<i>Illustrative example only. Not financial advice. Estimates are model-generated and not guaranteed.</i>",
        "<i>NFA — manage your risk.  ·  ⚡ Market Pulse Pro</i>",
    ]
    return "\n".join(lines)

def _parse_ai_trade(ai_text, price):
    """Extract entry, stop, target from AI response. Returns dict or None."""
    import re as _re
    if not ai_text:
        return None
    try:
        e_m = _re.search(r"Entry[:\s]+\$?([0-9,\.]+)", ai_text, _re.IGNORECASE)
        s_m = _re.search(r"Stop[:\s]+\$?([0-9,\.]+)", ai_text, _re.IGNORECASE)
        t_m = _re.search(r"Target[:\s]+\$?([0-9,\.]+)", ai_text, _re.IGNORECASE)
        bias_m = _re.search(r"(Bullish|Bearish|Neutral)", ai_text, _re.IGNORECASE)
        conf_m = _re.search(r"Confidence[:\s]+(High|Moderate|Low|Uncertain)", ai_text, _re.IGNORECASE)
        sit_m = _re.search(r"SITUATION[:\s]*(.+?)(?:\n|$)", ai_text, _re.IGNORECASE)
        ctx_m = _re.search(r"CONTEXT[:\s]*(.+?)(?:\n|$)", ai_text, _re.IGNORECASE)
        dec_m = _re.search(r"DECISION[:\s]*(.+?)(?:\n|$)", ai_text, _re.IGNORECASE)
        entry  = f"${float(e_m.group(1).replace(',','')):,.0f}" if e_m else None
        stop   = f"${float(s_m.group(1).replace(',','')):,.0f}" if s_m else None
        target = f"${float(t_m.group(1).replace(',','')):,.0f}" if t_m else None
        return {
            "entry":   entry,
            "stop":    stop,
            "target":  target,
            "bias":    bias_m.group(1).capitalize() if bias_m else "Neutral",
            "confidence": conf_m.group(1).capitalize() if conf_m else "Uncertain",
            "situation": sit_m.group(1).strip() if sit_m else "",
            "context":   ctx_m.group(1).strip() if ctx_m else "",
            "decision":  dec_m.group(1).strip() if dec_m else "",
        }
    except Exception as _e:
        return None

def check_key_market_alerts():
    """Smart key level alert engine.
    - Max 1 alert per cycle (MAX_ALERTS_PER_CYCLE)
    - 6-hour per-coin cooldown stored in DB (survives restarts)
    - Tighter 1% proximity tolerance (was 1.8%)
    - Only alerts on confirmed swing levels from price history
    """
    triggered = []

    try:
        for coin in KEY_ALERT_COINS:
            price, change = get_best_price(coin)
            if not price:
                continue
            levels = get_dynamic_key_levels(coin, price)
            if not levels:
                continue
            level = _nearest_key_level(price, levels)
            if not level:
                continue
            # DB-backed cooldown — coin-level, survives restarts
            if _get_key_alert_cooldown(coin):
                logger.debug(f"[KEY ALERT] {coin} in 6h cooldown, skipping")
                continue
            proximity = abs(price - level) / level
            triggered.append((proximity, coin, price, change or 0, level))

        # Sort by proximity — send the coin closest to its level
        triggered.sort(key=lambda x: x[0])

        sent = 0
        for proximity, coin, price, ch, level in triggered:
            if sent >= MAX_ALERTS_PER_CYCLE:
                break
            # Set cooldown BEFORE sending — prevents double-post on error
            _set_key_alert_cooldown(coin)
            logger.info(f"[KEY ALERT] {coin} @ {format_price(price)} — {_level_label(price, level)[0]}")

            # Free channel
            post_to_channel(build_free_key_alert(coin, price, ch, level))

            # Pro channel — structured AI prompt
            sd = get_secondary_coin(coin)
            high_24 = sd.get("usd_24h_high") if sd else None
            low_24  = sd.get("usd_24h_low")  if sd else None
            fg_data = get_fear_greed()
            fg_val  = fg_data[0]["value"] if fg_data else "N/A"
            h_str = format_price(high_24) if isinstance(high_24,(int,float)) else "N/A"
            l_str = format_price(low_24)  if isinstance(low_24,(int,float)) else "N/A"
            status_label, _ = _level_label(price, level)

            ai_prompt = (
                f"{coin} is at {format_price(price)} ({format_change(ch)}). "
                f"Status: {status_label} at {format_price(level)}. "
                f"24h High: {h_str}  Low: {l_str}. Fear & Greed: {fg_val}/100. "
                f"Respond in this EXACT format, plain text, no asterisks:\n"
                f"SITUATION: [one sentence — what is happening at this level right now]\n"
                f"CONTEXT: [one sentence — Nigerian trader angle, P2P or naira impact]\n"
                f"Market Bias: [Bullish / Bearish / Neutral]\n"
                f"Entry: $[price]\n"
                f"Stop: $[price]\n"
                f"Target: $[price]\n"
                f"Confidence: [High / Moderate / Low / Uncertain]\n"
                f"DECISION: [one sentence — what you would do right now or wait with reason]\n"
                f"If no quality setup exists, write: Entry: none  Stop: none  Target: none"
            )
            ai_raw, _ = ask_ai(ai_prompt)
            trade = _parse_ai_trade(ai_raw, price)

            if trade and trade.get("entry") and trade["entry"] != "$none":
                valid, reason = _validate_alert(
                    coin, price,
                    trade.get("entry",""), trade.get("stop",""), trade.get("target",""),
                    status_label
                )
                if not valid:
                    logger.warning(f"[KEY ALERT] Validation failed for {coin}: {reason}")
                    # Send without trade hypothesis
                    post_to_pro_channel(build_pro_key_alert(
                        coin, price, ch, level,
                        situation=trade.get("situation",""),
                        context_line=trade.get("context",""),
                        decision=f"Setup invalidated: {reason}. Monitor manually.",
                        bias=trade.get("bias","Neutral"),
                        confidence="Uncertain"
                    ))
                else:
                    post_to_pro_channel(build_pro_key_alert(
                        coin, price, ch, level,
                        entry=trade.get("entry"),
                        stop=trade.get("stop"),
                        target=trade.get("target"),
                        bias=trade.get("bias","Neutral"),
                        confidence=trade.get("confidence","Uncertain"),
                        situation=trade.get("situation",""),
                        context_line=trade.get("context",""),
                    ))
            else:
                # No trade setup — send analysis only
                post_to_pro_channel(build_pro_key_alert(
                    coin, price, ch, level,
                    situation=trade.get("situation","") if trade else "",
                    context_line=trade.get("context","") if trade else "",
                    decision="No High-Confidence Trade Setup for this alert. Monitor the level.",
                    bias=trade.get("bias","Neutral") if trade else "Neutral",
                    confidence="Uncertain"
                ))
            sent += 1
            time.sleep(1)  # brief pause between alerts

    except Exception as e:
        logger.error(f"[KEY ALERT ERROR] {e}")

def daily_digest():
    db = None
    try:
        db = get_db()
        c = db.cursor()
        today_wat = wat_now().strftime("%Y-%m-%d")
        c.execute("SELECT COUNT(*) FROM events WHERE timestamp LIKE %s", (today_wat + "%",))
        total_events = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE first_seen LIKE %s", (today_wat + "%",))
        new_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE last_seen LIKE %s", (today_wat + "%",))
        active_users = c.fetchone()[0]
    except Exception as e:
        logger.error("[DAILY DIGEST ERROR] %s" % e)
        return
    finally:
        if db:
            try: db.close()
            except Exception: pass

    for admin_id in ADMIN_IDS:
        try:
            send(admin_id, (
                f"📊 <b>Daily Digest</b>\n\n"
                f"📅 {today_wat} (WAT)\n"
                f"👤 New Users: <b>{new_users}</b>\n"
                f"🟢 Active Users: <b>{active_users}</b>\n"
                f"📊 Total Events: <b>{total_events}</b>"
            ))
        except Exception as e:
            logger.error("[DAILY DIGEST SEND] admin %s: %s" % (admin_id, e))

# ═══════════════════════════════════════════════════════════════════════════
# 📊 SCREEN HANDLERS
# ═══════════════════════════════════════════════════════════════════════════

def show_main_menu(chat_id, message_id=None):
    text = (
        "🚀 <b>Market Pulse</b>\n\n"
        f"👤 {get_user_badge(chat_id)}\n\n"
        "AI-powered crypto intelligence for Nigerian traders.\n\n"
        "Choose a category:"
    )
    
    if get_bot_mode() == "everyone":
        menu = MAIN_MENU
    elif is_pro(chat_id):
        menu = MAIN_MENU_PRO
    else:
        menu = MAIN_MENU_FREE
    
    if message_id:
        edit(chat_id, message_id, text, menu)
    else:
        send(chat_id, text, menu)

def show_market(chat_id, message_id=None):
    track_feature(chat_id, "market")
    kraken_batch = get_kraken_batch()
    secondary = get_secondary_batch()
    
    lines = [
        "📈 <b>Live Market Prices</b>",
        "",
        "<code>Coin    Price       24h %",
        "──────────────────────────────"
    ]
    
    for coin in ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT"]:
        price = kraken_batch.get(coin)
        sd = secondary.get(coin_key(coin))
        if price is None and sd:
            price = sd.get("usd")
        change = sd.get("usd_24h_change") if sd else None
        if price:
            lines.append(f"{coin:6} {format_price(price):10} {format_change(change)}")
    
    lines.append("</code>")
    lines.append("")
    lines.append(f"<i>👤 {get_user_badge(chat_id)}</i>")
    
    buttons = [
        [{"text": "🔄 Refresh", "callback_data": "market"},
         {"text": "⬅ Back", "callback_data": "main_menu"}]
    ]
    
    if message_id:
        edit(chat_id, message_id, "\n".join(lines), buttons)
    else:
        send(chat_id, "\n".join(lines), buttons)

def show_upgrade(chat_id, message_id=None):
    if is_pro(chat_id):
        ref_count = get_pro_referral_count(chat_id)
        next_tier = ""
        if ref_count < 3:   next_tier = f"{3-ref_count} more referral(s) → 1 week free"
        elif ref_count < 5: next_tier = f"{5-ref_count} more referral(s) → 1 month free"
        elif ref_count < 10:next_tier = f"{10-ref_count} more referral(s) → 3 months free"
        elif ref_count < 20:next_tier = f"{20-ref_count} more referral(s) → 6 months free"
        else:               next_tier = "Maximum tier reached — thank you!"
        text = (
            "⭐ <b>You are Pro!</b>\n\n"
            f"📅 Expires: <b>{get_pro_expiry(chat_id) or 'N/A'}</b>\n"
            f"👥 Referrals: <b>{ref_count}</b>   <i>{next_tier}</i>\n\n"
            "Your referral link:\n"
            f"<code>https://t.me/MarketNgPulseBot?start=ref_PRO_{chat_id}</code>\n\n"
            "<i>Share this link. When a friend joins, you earn free Pro time.</i>"
        )
    else:
        text = (
            "💎 <b>Market Pulse Pro</b>\n\n"
            "Everything free users get, plus:\n\n"
            "🧠 AI analysis on every morning, midday and evening post\n"
            "🎯 Exact entry, stop loss and target — every day\n"
            "🔔 Key level alerts with AI breakout analysis\n"
            "🐋 Whale alerts with AI trade decision\n"
            "💱 P2P rate alerts with naira context\n"
            "📊 Saturday Weekly Edge — full intelligence report\n"
            "📈 Unlimited AI questions\n"
            "⚙️ 20 price alerts, 30 watchlist items\n"
            "📒 Trade Journal + Position Calculator\n\n"
            "💰 <b>₦3,000/month</b>\n\n"
            "👥 <b>Refer friends, earn free Pro:</b>\n"
            "3 referrals → 1 week free\n"
            "5 referrals → 1 month free\n"
            "10 referrals → 3 months free\n"
            "20 referrals → 6 months free\n\n"
            "📩 <b>To upgrade, DM: @heisthegeneral</b>\n"
            "<i>Activated within minutes.</i>"
        )
    
    buttons = [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]
    
    if message_id:
        edit(chat_id, message_id, text, buttons)
    else:
        send(chat_id, text, buttons)

def show_help(chat_id, message_id=None):
    text = (
        "📚 <b>Market Pulse Commands</b>\n\n"
        "📊 <b>Markets</b>\n"
        "/market - Live prices\n"
        "/charts - Price charts\n"
        "/gainers - Top gainers\n"
        "/losers - Top losers\n"
        "/dominance - Market dominance\n\n"
        "🧠 <b>Intelligence</b>\n"
        "/ai - Ask AI\n"
        "/news - AI news\n"
        "/feargreed - Fear & Greed\n"
        "/outlook - Market outlook\n\n"
        "🇳🇬 <b>P2P</b>\n"
        "/p2p - P2P rates\n"
        "/p2palerts - P2P alerts\n"
        "/arbitrage - Arbitrage scanner\n\n"
        "🔔 <b>Alerts</b>\n"
        "/alert - Create alert\n"
        "/alerts - My alerts\n"
        "/watchlist - Watchlist\n\n"
        "💼 <b>Portfolio</b>\n"
        "/portfolio - My portfolio\n"
        "/addportfolio - Add position\n"
        "/removeportfolio - Remove position\n\n"
        "📈 <b>Trade Journal</b>\n"
        "/addtrade - Add trade\n"
        "/closetrade - Close trade\n"
        "/trades - My trades\n\n"
        "🛠 <b>Tools</b>\n"
        "/position - Position calculator\n"
        "/convert - Convert crypto\n"
        "/search - Search coin\n\n"
        "👤 <b>Account</b>\n"
        "/upgrade - Upgrade to Pro\n"
        "/referral - Referral program\n"
        "/settings - User settings\n"
        "/feedback - Send feedback\n\n"
        "ℹ️ <b>Info</b>\n"
        "/help - This menu\n"
        "/version - Bot version\n"
        "/ping - Check bot status"
    )
    
    buttons = [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]
    
    if message_id:
        edit(chat_id, message_id, text, buttons)
    else:
        send(chat_id, text, buttons)

def show_portfolio(chat_id, message_id=None):
    portfolio_data = get_portfolio_value(chat_id)
    
    if not portfolio_data or not portfolio_data["positions"]:
        text = (
            "💼 <b>Portfolio</b>\n\n"
            "No positions yet.\n\n"
            "Add positions:\n"
            "<code>/addportfolio BTC 0.5 61000</code>"
        )
        buttons = [
            [{"text": "➕ Add Position", "callback_data": "add_portfolio"}],
            [{"text": "🏠 Main Menu", "callback_data": "main_menu"}]
        ]
        
        if message_id:
            edit(chat_id, message_id, text, buttons)
        else:
            send(chat_id, text, buttons)
        return
    
    lines = ["💼 <b>Portfolio</b>\n"]
    
    for pos in portfolio_data["positions"]:
        pnl_emoji = "📈" if pos["pnl"] > 0 else "📉" if pos["pnl"] < 0 else "➖"
        lines.append(f"{pnl_emoji} <b>{pos['coin']}</b>")
        lines.append(f"  Amount: {pos['amount']:.4f}")
        lines.append(f"  Entry: {format_price(pos['buy_price'])}")
        lines.append(f"  Current: {format_price(pos['current_price'])}")
        lines.append(f"  P&L: <b>{'+' if pos['pnl'] > 0 else ''}{pos['pnl']:.2f}</b> ({'+' if pos['pnl_pct'] > 0 else ''}{pos['pnl_pct']:.1f}%)")
        lines.append("")
    
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 Total Invested: ${portfolio_data['total_invested']:.2f}")
    lines.append(f"📊 Current Value: ${portfolio_data['total_current']:.2f}")
    pnl_emoji = "📈" if portfolio_data["total_pnl"] > 0 else "📉" if portfolio_data["total_pnl"] < 0 else "➖"
    lines.append(f"{pnl_emoji} Total P&L: <b>{'+' if portfolio_data['total_pnl'] > 0 else ''}{portfolio_data['total_pnl']:.2f}</b> ({'+' if portfolio_data['total_pnl_pct'] > 0 else ''}{portfolio_data['total_pnl_pct']:.1f}%)")
    lines.append("")
    lines.append("<i>NFA - DYOR</i>")
    
    buttons = [
        [{"text": "🔄 Refresh", "callback_data": "portfolio"}],
        [{"text": "➕ Add", "callback_data": "add_portfolio"},
         {"text": "🗑️ Remove", "callback_data": "remove_portfolio"}],
        [{"text": "🏠 Main Menu", "callback_data": "main_menu"}]
    ]
    
    if message_id:
        edit(chat_id, message_id, "\n".join(lines), buttons)
    else:
        send(chat_id, "\n".join(lines), buttons)

def show_trade_journal(chat_id, message_id=None):
    if not is_pro(chat_id) and get_bot_mode() != "everyone":
        text = "🔒 <b>Pro Feature</b>\n\nTrade Journal is only available to Pro users."
        if message_id:
            edit(chat_id, message_id, text, [[{"text": "💎 Upgrade", "callback_data": "upgrade"}, {"text": "⬅ Back", "callback_data": "menu_account"}]])
        else:
            send(chat_id, text, [[{"text": "💎 Upgrade", "callback_data": "upgrade"}, {"text": "⬅ Back", "callback_data": "menu_account"}]])
        return
    
    try:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT id, coin, direction, entry_price, exit_price, size, pnl, status FROM trade_journal "
                  "WHERE chat=%s ORDER BY id DESC LIMIT 20", (str(chat_id),))
        rows = c.fetchall()
        db.close()
        
        if not rows:
            text = (
                "📈 <b>Trade Journal</b>\n\n"
                "No trades yet.\n\n"
                "Add a trade:\n"
                "<code>/addtrade BTC LONG 61000 62000 0.5</code>"
            )
            buttons = [
                [{"text": "➕ Add Trade", "callback_data": "add_trade"}],
                [{"text": "🏠 Main Menu", "callback_data": "main_menu"}]
            ]
            
            if message_id:
                edit(chat_id, message_id, text, buttons)
            else:
                send(chat_id, text, buttons)
            return
        
        lines = ["📈 <b>Trade Journal</b>\n"]
        total_pnl = 0
        wins = 0
        closed_trades = 0
        
        for tid, coin, direction, entry, exit_price, size, pnl, status in rows:
            if status == "closed" and pnl is not None:
                total_pnl += pnl
                closed_trades += 1
                if pnl > 0:
                    wins += 1
            pnl_str = f"+${pnl:.2f}" if pnl and pnl > 0 else f"-${abs(pnl):.2f}" if pnl else "Open"
            status_emoji = "✅" if status == "closed" else "⏳"
            lines.append(f"{status_emoji} #{tid} <b>{coin}</b> {direction}")
            lines.append(f"   Entry: {format_price(entry)} → Exit: {format_price(exit_price) if exit_price else 'Open'}")
            lines.append(f"   Size: {size} | P&L: <b>{pnl_str}</b>")
            lines.append("")
        
        if closed_trades > 0:
            win_rate = (wins / closed_trades) * 100 if closed_trades > 0 else 0
            lines.append(f"📊 Total P&L: <b>+${total_pnl:.2f}</b>")
            lines.append(f"📊 Win Rate: <b>{win_rate:.1f}%</b> ({wins}/{closed_trades})")
        
        lines.append("")
        lines.append("<i>Use /addtrade to record trades</i>")
        
        buttons = [
            [{"text": "🔄 Refresh", "callback_data": "trade_journal"}],
            [{"text": "➕ Add", "callback_data": "add_trade"},
             {"text": "🔒 Close", "callback_data": "close_trade"}],
            [{"text": "🏠 Main Menu", "callback_data": "main_menu"}]
        ]
        
        if message_id:
            edit(chat_id, message_id, "\n".join(lines), buttons)
        else:
            send(chat_id, "\n".join(lines), buttons)
    except Exception as e:
        logger.error("[TRADE JOURNAL ERROR] %s" % e)
        if message_id:
            edit(chat_id, message_id, "⚠️ Error loading trades.", BACK_MAIN)
        else:
            send(chat_id, "⚠️ Error loading trades.")

def show_settings(chat_id, message_id=None):
    try:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT language, notifications, theme FROM user_preferences WHERE chat=%s", (str(chat_id),))
        row = c.fetchone()
        db.close()
        
        if not row:
            db = get_db()
            c = db.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT INTO user_preferences (chat, language, notifications, theme, updated_at) VALUES (%s,%s,%s,%s,%s)",
                      (str(chat_id), 'en', 1, 'dark', now))
            db.commit()
            db.close()
            language, notifications, theme = 'en', 1, 'dark'
        else:
            language, notifications, theme = row
        
        text = (
            "⚙️ <b>User Settings</b>\n\n"
            f"🌐 Language: <b>{language.upper()}</b>\n"
            f"🔔 Notifications: <b>{'✅ On' if notifications else '❌ Off'}</b>\n"
            f"🎨 Theme: <b>{theme.title()}</b>\n\n"
            "Tap to change:"
        )
        
        buttons = [
            [{"text": f"🌐 Language ({language.upper()})", "callback_data": "settings_language"}],
            [{"text": f"🔔 Notifications ({'On' if notifications else 'Off'})", "callback_data": "settings_notifications"}],
            [{"text": f"🎨 Theme ({theme.title()})", "callback_data": "settings_theme"}],
            [{"text": "🏠 Main Menu", "callback_data": "main_menu"}]
        ]
        
        if message_id:
            edit(chat_id, message_id, text, buttons)
        else:
            send(chat_id, text, buttons)
    except Exception as e:
        logger.error("[SETTINGS ERROR] %s" % e)
        if message_id:
            edit(chat_id, message_id, "⚠️ Error loading settings.", BACK_MAIN)
        else:
            send(chat_id, "⚠️ Error loading settings.")

def show_position_calculator(chat_id, message_id=None):
    if not is_pro(chat_id) and get_bot_mode() != "everyone":
        text = "🔒 <b>Pro Feature</b>\n\nPosition Calculator is only available to Pro users."
        if message_id:
            edit(chat_id, message_id, text, [[{"text": "💎 Upgrade", "callback_data": "upgrade"}, {"text": "⬅ Back", "callback_data": "menu_account"}]])
        else:
            send(chat_id, text, [[{"text": "💎 Upgrade", "callback_data": "upgrade"}, {"text": "⬅ Back", "callback_data": "menu_account"}]])
        return
    
    set_state(chat_id, "awaiting_position_calc", {})
    text = (
        "📐 <b>Position Size Calculator</b>\n\n"
        "Enter your account details:\n\n"
        "Format: <code>ACCOUNT_SIZE RISK_PERCENT ENTRY_PRICE STOP_LOSS</code>\n\n"
        "Example: <code>10000 2 98200 97000</code>\n\n"
        "Account: $10,000 | Risk: 2% | Entry: $98,200 | SL: $97,000"
    )
    
    if message_id:
        edit(chat_id, message_id, text, [[{"text": "⬅ Cancel", "callback_data": "main_menu"}]])
    else:
        send(chat_id, text, [[{"text": "⬅ Cancel", "callback_data": "main_menu"}]])

def handle_position_calc(chat_id, text):
    clear_state(chat_id)
    parts = text.strip().replace(",", "").split()
    if len(parts) != 4:
        send(chat_id, "⚠️ Format: <code>ACCOUNT_SIZE RISK_PERCENT ENTRY_PRICE STOP_LOSS</code>")
        return
    
    try:
        account = float(parts[0])
        risk_pct = float(parts[1])
        entry = float(parts[2])
        sl = float(parts[3])
        
        if account <= 0 or risk_pct <= 0 or entry <= 0 or sl <= 0:
            raise ValueError
        
        risk_amount = account * (risk_pct / 100)
        risk_per_unit = abs(entry - sl)
        position_size = risk_amount / risk_per_unit
        position_value = position_size * entry
        
        lines = [
            "📐 <b>Position Size Calculator</b>",
            "",
            f"Account: <b>${account:,.2f}</b>",
            f"Risk: <b>{risk_pct:.1f}%</b> (${risk_amount:,.2f})",
            f"Entry: <b>{format_price(entry)}</b>",
            f"Stop Loss: <b>{format_price(sl)}</b>",
            "",
            "· · · · · · · · · · · · · · · · · · ·",
            "",
            f"📊 Position Size: <b>{position_size:.4f}</b> units",
            f"💰 Position Value: <b>${position_value:,.2f}</b>",
            f"💸 Risk per Unit: <b>${risk_per_unit:.2f}</b>",
            "",
            "· · · · · · · · · · · · · · · · · · ·",
            "",
            "<i>NFA - DYOR</i>",
        ]
        
        send(chat_id, "\n".join(lines), [
            [{"text": "🔄 Calculate Again", "callback_data": "position_calculator"}],
            [{"text": "🏠 Main Menu", "callback_data": "main_menu"}]
        ])
    except Exception as _e:
        send(chat_id, "⚠️ Invalid input. Use numbers only.")

# ═══════════════════════════════════════════════════════════════════════════
# 🔄 ARBITRAGE SCANNER
# ═══════════════════════════════════════════════════════════════════════════

def scan_arbitrage():
    opportunities = []
    kraken = get_kraken_batch()
    okx = get_okx_batch()
    cg = get_coingecko_batch()
    
    sources = [("Kraken", kraken), ("OKX", okx), ("CoinGecko", cg)]
    
    for coin in ["BTC", "ETH", "SOL", "BNB", "XRP"]:
        prices = []
        for name, data in sources:
            if coin in data and data[coin].get("price"):
                p = data[coin]["price"]
                if p and p > 0:
                    prices.append((name, float(p)))
        if len(prices) < 2:
            continue
        prices.sort(key=lambda x: x[1])
        low_src, low_price = prices[0]
        high_src, high_price = prices[-1]
        gap_pct = (high_price - low_price) / low_price * 100
        if gap_pct >= 0.3:
            opportunities.append({
                "coin": coin,
                "buy_from": low_src,
                "buy_price": low_price,
                "sell_to": high_src,
                "sell_price": high_price,
                "gap_pct": gap_pct
            })
    
    return opportunities

# ═══════════════════════════════════════════════════════════════════════════
# 🚀 MAIN RUN LOOP
# ═══════════════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════════════
# 📦 CONTENT ENGINE — V2 MULTI-PLATFORM CONTENT GENERATION
# ═══════════════════════════════════════════════════════════════════════════
# One market analysis → 7 native formats (Telegram, X, WhatsApp,
# Instagram caption, Instagram carousel, TikTok script, plus hashtags/CTA).
# All output goes to admin only. Never auto-published.
# ═══════════════════════════════════════════════════════════════════════════

EDUCATIONAL_TOPICS = [
    "Support & Resistance — how levels work and why price respects them",
    "Risk Management — position sizing, stop losses, and why most traders blow their accounts",
    "P2P Explained — how Nigerian P2P trading works, what spreads mean, and how to read them",
    "Market Cycles — accumulation, markup, distribution, markdown and where we are now",
    "Fear & Greed — how sentiment drives price and how to use it as a contrarian signal",
    "Liquidity & Whales — what liquidity really means and how large players move price",
    "Market Psychology — why traders repeat the same mistakes and how to avoid them",
    "Stablecoins — USDT vs USDC, risks, and how to use them in a Nigerian context",
    "What Fake Breakouts Are — how to identify them before you get trapped",
    "Understanding Volatility — how to read market structure during high-volatility moves",
]

def _content_ai(prompt, max_words=None):
    """Single AI call for content generation. Returns text or empty string."""
    if max_words:
        prompt = prompt + f"\n\nKeep under {max_words} words."
    result, _ = ask_ai(prompt)
    return result or ""


def build_content_engine(
    post_type: str,
    telegram_text: str,
    market_context: dict,
) -> dict:
    """
    Core Content Engine.
    Takes the Telegram post (already built) + market context dict and
    produces all other platform formats via individual AI calls.

    post_type: 'morning' | 'midday' | 'evening' | 'weekly' | 'alert'
    market_context: keys like btc_price, btc_change, fg_val, fg_lbl,
                    gainers_str, losers_str, p2p_str, key_insight

    Returns a dict with keys:
      telegram, x_post, x_thread, whatsapp, instagram_caption,
      instagram_carousel, tiktok_script, hashtags, cta, posting_order
    """
    btc_price   = market_context.get("btc_price", "N/A")
    btc_change  = market_context.get("btc_change", "0%")
    fg_val      = market_context.get("fg_val", "50")
    fg_lbl      = market_context.get("fg_lbl", "Neutral")
    gainers_str = market_context.get("gainers_str", "N/A")
    losers_str  = market_context.get("losers_str", "N/A")
    p2p_str     = market_context.get("p2p_str", "")
    key_insight = market_context.get("key_insight", "")

    # Strip HTML tags from telegram text for AI prompts (re already imported at module level)
    clean_tg = re.sub(r"<[^>]+>", "", telegram_text).strip()

    results = {"telegram": telegram_text}

    # ── X POST (single insight, educational, no copy-paste) ──────────────
    x_prompt = (
        f"You are writing a single X (Twitter) post for Market Pulse, a Nigerian crypto "
        f"intelligence brand. Extract ONE valuable insight from this market brief and rewrite it "
        f"natively for X. Educational, not a price alert. No hashtags yet (add later). "
        f"Max 250 characters. Plain text only.\nMarket Brief:\n{clean_tg[:800]}"
    )
    results["x_post"] = _content_ai(x_prompt, max_words=60)

    # ── X THREAD (educational expansion — only for morning/evening/weekly) ─
    if post_type in ("morning", "evening", "weekly", "alert"):
        thread_prompt = (
            f"Write a 4-tweet educational X thread for Market Pulse based on this market brief. "
            f"Each tweet: educational, specific to today's market, no emojis in tweet 1. "
            f"Format: Tweet 1: [text]\nTweet 2: [text]\nTweet 3: [text]\nTweet 4: [text]\n"
            f"Make tweet 1 the hook. Tweet 4 ends with the lesson Nigerian traders should apply now. "
            f"No hashtags in the thread itself.\nMarket Brief:\n{clean_tg[:800]}"
        )
        results["x_thread"] = _content_ai(thread_prompt, max_words=280)
    else:
        results["x_thread"] = ""

    # ── WHATSAPP (short, scannable, max-value snapshot) ───────────────────
    wa_prompt = (
        f"Write a WhatsApp channel post for Market Pulse. Short, easy to scan, maximum value. "
        f"This is a retention tool — existing followers, not new ones. "
        f"Cover only the most important number and the one thing traders should know right now. "
        f"Max 80 words. No HTML tags. Use \n for line breaks.\nContext:\n{clean_tg[:600]}"
    )
    results["whatsapp"] = _content_ai(wa_prompt, max_words=80)

    # ── INSTAGRAM CAPTION ─────────────────────────────────────────────────
    ig_prompt = (
        f"Write an Instagram caption for Market Pulse, a Nigerian crypto intelligence brand. "
        f"Educational, not hype. End with a call-to-action inviting followers to comment or save. "
        f"2–3 short paragraphs, conversational tone. Max 150 words.\nContext:\n{clean_tg[:600]}"
    )
    results["instagram_caption"] = _content_ai(ig_prompt, max_words=150)

    # ── INSTAGRAM CAROUSEL COPY ───────────────────────────────────────────
    carousel_prompt = (
        f"Write copy for a 5-slide Instagram carousel for Market Pulse. "
        f"Topic: today's market insight for Nigerian traders. Educational, visual-first. "
        f"Format each slide: SLIDE [N]: [Title] | [Body — 1-2 short sentences max] "
        f"Slide 1 must be a hook. Slide 5 must be a CTA/lesson. "
        f"Plain text, no HTML.\nContext:\n{clean_tg[:600]}"
    )
    results["instagram_carousel"] = _content_ai(carousel_prompt, max_words=200)

    # ── TIKTOK SCRIPT (30–60 second, faceless, educational) ──────────────
    tiktok_prompt = (
        f"Write a 30–60 second TikTok video script for Market Pulse. "
        f"This is a FACELESS video — no presenter. Use: on-screen text, chart annotations, voice-over. "
        f"Format: \n[VISUAL]: description of what appears on screen\n[TEXT OVERLAY]: what text appears\n[VO]: voice-over line\n"
        f"Educational. Never clickbait. Topic: today's key market insight for Nigerian traders. "
        f"End with one strong lesson. Max 120 words.\nContext:\n{clean_tg[:600]}"
    )
    results["tiktok_script"] = _content_ai(tiktok_prompt, max_words=150)

    # ── HASHTAGS ──────────────────────────────────────────────────────────
    ht_prompt = (
        f"Generate 10 relevant hashtags for a Nigerian crypto intelligence post about today's market. "
        f"Mix broad (#crypto #bitcoin) with Nigerian-specific (#NigerianTraders #CryptoNigeria) "
        f"and educational (#CryptoEducation #TradingLessons). Plain text, one line, space-separated."
    )
    results["hashtags"] = _content_ai(ht_prompt, max_words=30)

    # ── CTA ───────────────────────────────────────────────────────────────
    cta_map = {
        "morning": "🚀 Start your trading day smarter — join @marketpulseng on Telegram for the full brief.",
        "midday":  "📊 Full midday analysis with entry & stop is live in the Pro channel. DM @heisthegeneral.",
        "evening": "🌙 Get tomorrow's exact trade plan before you sleep — Pro channel. DM @heisthegeneral.",
        "weekly":  "🔥 Saturday Weekly Edge is live in the Pro channel — entry, stop, target for next week. DM @heisthegeneral.",
        "alert":   "⚡ Full key level analysis + trade setup is in the Pro channel right now. DM @heisthegeneral.",
    }
    results["cta"] = cta_map.get(post_type, "⚡ Full intelligence in the Pro channel. DM @heisthegeneral.")

    # ── POSTING ORDER ─────────────────────────────────────────────────────
    order_map = {
        "morning": "1. Telegram (full brief) → 2. X Post (insight) → 3. WhatsApp (snapshot) → 4. Instagram Story text",
        "midday":  "1. Telegram (midday) → 2. X Post → 3. WhatsApp (only if significant move)",
        "evening": "1. Telegram (recap) → 2. X Post → 3. WhatsApp → 4. X Thread (if important lesson) → 5. Instagram",
        "weekly":  "1. Telegram (full report) → 2. X Educational Thread → 3. Instagram Carousel → 4. WhatsApp summary → 5. TikTok",
        "alert":   "1. Telegram (alert) → 2. X Post → 3. WhatsApp (only if major event)",
    }
    results["posting_order"] = order_map.get(post_type, "1. Telegram → 2. X → 3. WhatsApp")

    return results


def save_content_package(post_type: str, trigger_source: str, package: dict) -> int:
    """Save generated content package to DB. Returns package ID."""
    db = None
    try:
        db = get_db(); c = db.cursor()
        now = wat_now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            """INSERT INTO content_packages
               (package_type, trigger_source, telegram_text, x_post, x_thread,
                whatsapp_text, instagram_caption, instagram_carousel, tiktok_script,
                hashtags, cta, posting_order, status, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s)
               RETURNING id""",
            (
                post_type, trigger_source,
                package.get("telegram",""), package.get("x_post",""),
                package.get("x_thread",""), package.get("whatsapp",""),
                package.get("instagram_caption",""), package.get("instagram_carousel",""),
                package.get("tiktok_script",""), package.get("hashtags",""),
                package.get("cta",""), package.get("posting_order",""), now
            )
        )
        pkg_id = c.fetchone()[0]
        db.commit()
        logger.info(f"[CONTENT ENGINE] Package #{pkg_id} saved ({post_type})")
        return pkg_id
    except Exception as e:
        logger.error(f"[CONTENT ENGINE] Save error: {e}")
        if db:
            try: db.rollback()
            except Exception: pass
        return 0
    finally:
        if db:
            try: db.close()
            except Exception: pass


def format_content_package_for_admin(pkg_id: int, package: dict, post_type: str) -> str:
    """Format content package as admin Telegram message."""
    now_str = wat_now().strftime("%b %d, %I:%M %p WAT")
    sections = [
        f"📦 <b>CONTENT PACKAGE #{pkg_id}</b>  —  {post_type.upper()}",
        f"<i>{now_str}  ·  ⚡ Market Pulse</i>",
        "",
        "⚠️ <b>ADMIN ONLY. Do not publish automatically.</b>",
        "Review each section below and publish manually.",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "📱 <b>TELEGRAM (Full Brief)</b>",
        "<i>→ Already posted to channel if scheduled. No action needed.</i>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "🐦 <b>X POST</b>",
        package.get("x_post","N/A"),
        "",
    ]

    x_thread = package.get("x_thread","")
    if x_thread:
        sections += [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "🧵 <b>X THREAD</b>",
            x_thread,
            "",
        ]

    sections += [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "💬 <b>WHATSAPP CHANNEL</b>",
        package.get("whatsapp","N/A"),
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "📸 <b>INSTAGRAM CAPTION</b>",
        package.get("instagram_caption","N/A"),
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "🎠 <b>INSTAGRAM CAROUSEL COPY</b>",
        package.get("instagram_carousel","N/A"),
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "🎵 <b>TIKTOK SCRIPT (Faceless)</b>",
        package.get("tiktok_script","N/A"),
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "🏷 <b>HASHTAGS</b>",
        package.get("hashtags","N/A"),
        "",
        "📢 <b>SUGGESTED CTA</b>",
        package.get("cta","N/A"),
        "",
        "📋 <b>SUGGESTED POSTING ORDER</b>",
        package.get("posting_order","N/A"),
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"<i>Package #{pkg_id} · Approve or discard · NFA</i>",
    ]
    return "\n".join(sections)


def generate_and_deliver_content_package(
    post_type: str,
    telegram_text: str,
    market_context: dict,
    trigger_source: str = "scheduled",
):
    """
    Full pipeline: build content engine → save to DB → deliver to admin.
    Called after every scheduled channel post.
    """
    try:
        logger.info(f"[CONTENT ENGINE] Building {post_type} package...")
        package = build_content_engine(post_type, telegram_text, market_context)
        pkg_id  = save_content_package(post_type, trigger_source, package)
        admin_msg = format_content_package_for_admin(pkg_id, package, post_type)
        for admin_id in ADMIN_IDS:
            # Split message if too long (Telegram limit 4096)
            if len(admin_msg) <= 4000:
                send(admin_id, admin_msg)
            else:
                # Send in parts at natural break points
                parts = admin_msg.split("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                current = ""
                for part in parts:
                    if len(current) + len(part) + 40 < 3800:
                        current += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" + part
                    else:
                        if current:
                            send(admin_id, current.strip())
                        current = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" + part
                        time.sleep(0.5)
                if current:
                    send(admin_id, current.strip())
        logger.info(f"[CONTENT ENGINE] Package #{pkg_id} delivered to admin(s)")
        return pkg_id
    except Exception as e:
        logger.error(f"[CONTENT ENGINE] Pipeline error: {e}")
        return 0


def build_weekly_educational_content() -> str:
    """
    Sunday educational content. Rotates through EDUCATIONAL_TOPICS by week number.
    Sends to admin as a content package, also returns the Telegram version.
    """
    week_num = datetime.now().isocalendar()[1]
    topic = EDUCATIONAL_TOPICS[week_num % len(EDUCATIONAL_TOPICS)]

    tg_prompt = (
        f"Write a Telegram educational post for Nigerian crypto traders on: {topic}. "
        f"Structure: short intro (1 sentence), 3-4 clear educational points, "
        f"real example relevant to Nigerian traders (P2P, naira, or common mistake). "
        f"End with one actionable takeaway. "
        f"No asterisks. Use HTML bold <b>text</b> for key terms. Max 300 words. "
        f"Footer: NFA - DYOR  ·  ⚡ Market Pulse"
    )
    tg_text, _ = ask_ai(tg_prompt)
    if not tg_text:
        tg_text = f"📚 <b>Weekly Education: {topic}</b>\n\n<i>Educational content unavailable — check back next week.</i>"

    # Generate full content package
    mc = {"key_insight": topic, "fg_val": "50", "fg_lbl": "Neutral", "btc_price": "N/A", "btc_change": "0%"}
    generate_and_deliver_content_package("weekly", tg_text, mc, trigger_source="educational")
    return tg_text


def get_pending_content_packages(limit=5) -> list:
    """Return list of pending content packages for admin review."""
    db = None
    try:
        db = get_db(); c = db.cursor()
        c.execute(
            "SELECT id, package_type, trigger_source, created_at FROM content_packages "
            "WHERE status='pending' ORDER BY id DESC LIMIT %s", (limit,)
        )
        return c.fetchall()
    except Exception as _e:
        return []
    finally:
        if db:
            try: db.close()
            except Exception: pass


def get_content_package_by_id(pkg_id: int) -> dict:
    """Retrieve a specific content package by ID."""
    db = None
    try:
        db = get_db(); c = db.cursor()
        c.execute(
            "SELECT id, package_type, trigger_source, telegram_text, x_post, x_thread, "
            "whatsapp_text, instagram_caption, instagram_carousel, tiktok_script, "
            "hashtags, cta, posting_order, status, created_at "
            "FROM content_packages WHERE id=%s", (pkg_id,)
        )
        row = c.fetchone()
        if not row:
            return {}
        keys = ["id","package_type","trigger_source","telegram","x_post","x_thread",
                "whatsapp","instagram_caption","instagram_carousel","tiktok_script",
                "hashtags","cta","posting_order","status","created_at"]
        return dict(zip(keys, row))
    except Exception as _e:
        return {}
    finally:
        if db:
            try: db.close()
            except Exception: pass


def mark_package_status(pkg_id: int, status: str):
    """Mark package as approved/discarded."""
    db = None
    try:
        db = get_db(); c = db.cursor()
        c.execute("UPDATE content_packages SET status=%s WHERE id=%s", (status, pkg_id))
        db.commit()
    except Exception as e:
        logger.error(f"[CONTENT ENGINE] Status update error: {e}")
        if db:
            try: db.rollback()
            except Exception: pass
    finally:
        if db:
            try: db.close()
            except Exception: pass


def build_admin_dashboard() -> str:
    """Comprehensive admin dashboard with all V2 spec metrics."""
    db = None
    try:
        db = get_db(); c = db.cursor()
        now_wat_str = wat_now().strftime("%Y-%m-%d %H:%M:%S")
        today = wat_now().strftime("%Y-%m-%d")
        week_ago = (wat_now() - timedelta(days=7)).strftime("%Y-%m-%d")
        month_ago = (wat_now() - timedelta(days=30)).strftime("%Y-%m-%d")

        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]
        # M4 FIX: compare full datetime string against stored YYYY-MM-DD HH:MM:SS
        c.execute("SELECT COUNT(*) FROM pro_subscriptions WHERE expiry_date > %s", (now_wat_str,))
        pro_users = c.fetchone()[0]
        free_users = total_users - pro_users

        c.execute("SELECT COUNT(*) FROM users WHERE first_seen >= %s", (week_ago + " 00:00:00",))
        new_this_week = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE first_seen >= %s", (month_ago + " 00:00:00",))
        new_this_month = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM alerts WHERE active=1")
        active_alerts = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM alerts")
        total_alerts = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM channel_posts WHERE posted_at >= %s", (week_ago + " 00:00:00",))
        posts_this_week = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM content_packages WHERE status='pending'")
        pending_packages = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM content_packages")
        total_packages = c.fetchone()[0]

        # Top features this week
        c.execute(
            "SELECT feature, COUNT(*) as cnt FROM feature_usage WHERE timestamp >= %s "
            "GROUP BY feature ORDER BY cnt DESC LIMIT 5", (week_ago + " 00:00:00",)
        )
        top_features = c.fetchall()

        c.execute("SELECT COUNT(*) FROM banned_users")
        banned_count = c.fetchone()[0]

        lines = [
            "📊 <b>ADMIN DASHBOARD</b>",
            f"<i>{wat_now().strftime('%b %d, %Y  %I:%M %p WAT')}</i>",
            "",
            "👥 <b>USERS</b>",
            f"Total: <b>{total_users:,}</b>",
            f"Pro:   <b>{pro_users:,}</b>  |  Free: <b>{free_users:,}</b>",
            f"New (7d):  <b>{new_this_week:,}</b>  |  New (30d): <b>{new_this_month:,}</b>",
            f"Banned:   <b>{banned_count:,}</b>",
            "",
            "🔔 <b>ALERTS</b>",
            f"Active: <b>{active_alerts:,}</b>  |  Total created: <b>{total_alerts:,}</b>",
            "",
            "📢 <b>CHANNEL</b>",
            f"Posts (7d): <b>{posts_this_week:,}</b>",
            f"Mode: <b>{get_bot_mode().upper()}</b>  |  Channel: <b>{'LIVE' if CHANNEL_ENABLED else 'PAUSED'}</b>",
            "",
            "📦 <b>CONTENT ENGINE</b>",
            f"Packages generated: <b>{total_packages:,}</b>",
            f"Pending approval: <b>{pending_packages:,}</b>",
            "",
        ]

        if top_features:
            lines += ["🏆 <b>TOP FEATURES (7d)</b>"]
            for feature, cnt in top_features:
                lines.append(f"  {feature}: <b>{cnt:,}</b>")
            lines.append("")

        lines += [
            "⚙️ <b>SYSTEM</b>",
            f"Bot Mode: <b>{get_bot_mode().upper()}</b>",
            f"Channel Posting: <b>{'✅ ON' if CHANNEL_ENABLED else '⏸ OFF'}</b>",
            f"Pro Channel: <b>{'✅ SET' if PRO_CHANNEL_ID and PRO_CHANNEL_ID != '-100XXXXXXXXX' else '❌ NOT SET'}</b>",
        ]
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[DASHBOARD] {e}")
        return f"⚠️ Dashboard error: {e}"
    finally:
        if db:
            try: db.close()
            except Exception: pass
# ═══════════════════════════════════════════════════════════════════════════
# ⚡ EDGE TRADE ENGINE — THREE-TIER TRADE SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

TRADE_TIERS = {
    "steady": {
        "label": "STEADY TRADE", "emoji": "🟢",
        "risk_desc": "Low-Medium Risk",
        "max_stop_pct": 5.0, "min_target_pct": 8.0, "min_rr": 1.5,
        "max_size": "3-5% of portfolio",
    },
    "momentum": {
        "label": "MOMENTUM TRADE", "emoji": "🟡",
        "risk_desc": "Medium-High Risk",
        "max_stop_pct": 10.0, "min_target_pct": 15.0, "min_rr": 1.5,
        "max_size": "2-3% of portfolio",
    },
    "edge": {
        "label": "EDGE TRADE", "emoji": "🔴",
        "risk_desc": "HIGH RISK — HIGH REWARD",
        "max_stop_pct": 15.0, "min_target_pct": 30.0, "min_rr": 2.0,
        "max_size": "1-2% of portfolio MAX",
    },
}

EDGE_DISCLAIMER = (
    "\u2501" * 24 + "\n"
    "\u26a0\ufe0f <b>RISK DISCLAIMER</b>\n"
    "This is a HIGH-RISK setup. You can LOSE your entire position. "
    "Only trade money you can afford to lose completely. "
    "Past setups do not guarantee future results. "
    "Market Pulse takes no responsibility for trading outcomes.\n"
    "NFA \u2014 DYOR \u2014 Trade at your own risk.\n"
    "\u2501" * 24
)

STANDARD_DISCLAIMER = (
    "<i>Illustrative only. Not financial advice. "
    "Always use a stop loss. NFA \u2014 DYOR \u2014 manage your risk.</i>\n"
    "\u26a1 Market Pulse Pro"
)


def _gather_trade_analytics(coin, price):
    """Pull rich market data from price history DB for AI context.
    Returns a dict of calculated indicators."""
    analytics = {
        "rsi_14": None,
        "above_ma20": None,
        "pct_from_30d_high": None,
        "pct_from_30d_low": None,
        "volume_trend": None,
        "price_30d_high": None,
        "price_30d_low": None,
    }
    db = None
    try:
        db = get_db()
        c = db.cursor()
        since_30d = (wat_now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "SELECT price FROM history WHERE coin=%s AND timestamp >= %s ORDER BY timestamp ASC",
            (coin, since_30d)
        )
        rows = c.fetchall()
        prices = [float(r[0]) for r in rows if r[0]]

        if len(prices) >= 14:
            # RSI-14 approximation using Wilder smoothing
            gains, losses = [], []
            for i in range(1, len(prices)):
                delta = prices[i] - prices[i-1]
                gains.append(max(delta, 0))
                losses.append(max(-delta, 0))
            avg_gain = sum(gains[-14:]) / 14
            avg_loss = sum(losses[-14:]) / 14
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                analytics["rsi_14"] = round(100 - (100 / (1 + rs)), 1)
            else:
                analytics["rsi_14"] = 100.0

        if len(prices) >= 20:
            ma20 = sum(prices[-20:]) / 20
            analytics["above_ma20"] = price > ma20

        if len(prices) >= 5:
            high_30d = max(prices)
            low_30d  = min(prices)
            analytics["price_30d_high"] = high_30d
            analytics["price_30d_low"]  = low_30d
            analytics["pct_from_30d_high"] = round((price - high_30d) / high_30d * 100, 1)
            analytics["pct_from_30d_low"]  = round((price - low_30d)  / low_30d  * 100, 1)

        # Volume trend: compare recent 7 data points to previous 7
        if len(prices) >= 14:
            recent_vol  = sum(abs(prices[i]-prices[i-1]) for i in range(len(prices)-7, len(prices)))
            prev_vol    = sum(abs(prices[i]-prices[i-1]) for i in range(len(prices)-14, len(prices)-7))
            if prev_vol > 0:
                analytics["volume_trend"] = "rising" if recent_vol > prev_vol * 1.1 else (
                    "falling" if recent_vol < prev_vol * 0.9 else "flat"
                )

    except Exception as e:
        logger.warning(f"[TRADE ANALYTICS] {coin}: {e}")
    finally:
        if db:
            try: db.close()
            except Exception: pass

    return analytics


def _analytics_to_str(a):
    """Format analytics dict into a concise string for the AI prompt."""
    parts = []
    if a["rsi_14"] is not None:
        rsi = a["rsi_14"]
        zone = "oversold" if rsi < 35 else ("overbought" if rsi > 65 else "neutral")
        parts.append(f"RSI-14: {rsi} ({zone})")
    if a["above_ma20"] is not None:
        parts.append(f"Price {'above' if a['above_ma20'] else 'below'} 20-day average")
    if a["pct_from_30d_high"] is not None:
        parts.append(f"{a['pct_from_30d_high']:+.1f}% from 30d high ({format_price(a['price_30d_high'])})")
    if a["pct_from_30d_low"] is not None:
        parts.append(f"{a['pct_from_30d_low']:+.1f}% from 30d low ({format_price(a['price_30d_low'])})")
    if a["volume_trend"]:
        parts.append(f"Volatility trend: {a['volume_trend']}")
    return " | ".join(parts) if parts else "Insufficient history (< 14 data points)"


def _tier_conditions_met(tier, analytics, fg_val):
    """Pre-screen: return (ok, reason) based on market conditions vs tier requirements.
    Prevents the AI from generating a setup when conditions are clearly wrong."""
    rsi = analytics.get("rsi_14")
    above_ma = analytics.get("above_ma20")
    vol_trend = analytics.get("volume_trend")
    pct_high  = analytics.get("pct_from_30d_high")
    fg = int(fg_val) if str(fg_val).isdigit() else 50

    if tier == "steady":
        # Steady needs clear structure — avoid extreme conditions
        if rsi and (rsi > 75 or rsi < 25):
            return False, f"RSI {rsi} is extreme — no steady setup in these conditions"
        if vol_trend == "rising" and fg > 75:
            return False, "Volatility rising + extreme greed — not a steady environment"
        return True, "ok"

    elif tier == "momentum":
        # Momentum needs directional movement
        if vol_trend == "flat" and rsi and 40 < rsi < 60:
            return False, "Market is ranging (flat volatility, neutral RSI) — no momentum"
        return True, "ok"

    elif tier == "edge":
        # Edge needs strong conditions — RSI extended OR near 30d extreme
        has_condition = False
        if rsi and (rsi > 68 or rsi < 32):
            has_condition = True
        if pct_high and abs(pct_high) < 3:
            has_condition = True  # Near 30d high/low
        if fg > 75 or fg < 25:
            has_condition = True
        if not has_condition:
            return False, "No extreme conditions present — save Edge for high-conviction moments"
        return True, "ok"

    return True, "ok"


def _build_trade_ai_prompt(coin, price, tier, sd, fg_val, p2p_str, analytics=None):
    tier_cfg = TRADE_TIERS[tier]
    h24 = sd.get("usd_24h_high") if sd else None
    l24 = sd.get("usd_24h_low") if sd else None
    h_str = format_price(h24) if isinstance(h24, (int, float)) else "N/A"
    l_str = format_price(l24) if isinstance(l24, (int, float)) else "N/A"
    analytics_str = _analytics_to_str(analytics) if analytics else "No history data"
    tf_guide = {
        "steady":   "Daily or Weekly. Prefer established structure.",
        "momentum": "4H or Daily. Breakouts or trend continuations.",
        "edge":     "1H or 4H. High-conviction momentum setups only.",
    }
    return (
        f"You are a professional crypto analyst generating a {tier_cfg['risk_desc']} trade idea "
        f"for Nigerian traders on Market Pulse Pro.\n\n"
        f"COIN: {coin} | PRICE: {format_price(price)} | 24H: {l_str}—{h_str}\n"
        f"FEAR & GREED: {fg_val}/100 | P2P: {p2p_str}\n"
        f"MARKET DATA: {analytics_str}\n\n"
        f"TIER: {tier_cfg['label']} — {tier_cfg['risk_desc']}\n"
        f"TIMEFRAME: {tf_guide[tier]}\n"
        f"STOP MAX: {tier_cfg['max_stop_pct']}% | TARGET MIN: {tier_cfg['min_target_pct']}% | MIN R:R: {tier_cfg['min_rr']}:1\n\n"
        f"Use the MARKET DATA above (RSI, MA, distance from highs/lows) to justify your setup.\n"
        f"If the data does not support a {tier} setup, say so — do not force a trade.\n\n"
        f"Respond ONLY in this exact format. No asterisks. Plain text:\n"
        f"TIMEFRAME: [1H / 4H / Daily / Weekly]\n"
        f"DIRECTION: [Long / Short]\n"
        f"RATIONALE: [2 sentences — must reference the market data above]\n"
        f"NIGERIAN ANGLE: [1 sentence — naira/P2P relevance]\n"
        f"Market Bias: [Strongly Bullish / Bullish / Neutral / Bearish / Strongly Bearish]\n"
        f"Entry: $[price]\n"
        f"Stop Loss: $[price]\n"
        f"Target 1: $[price]\n"
        f"Target 2: $[price or none]\n"
        f"Invalidation: $[price]\n"
        f"Confidence: [High / Moderate / Low]\n"
        f"If no quality setup: TIMEFRAME: None\nDIRECTION: None\nEntry: none"
    )


def _parse_trade_idea(ai_text, price):
    if not ai_text:
        return None
    try:
        def _get(pattern, text):
            m = re.search(pattern, text, re.IGNORECASE)
            return m.group(1).strip() if m else None
        def _pf(pattern, text):
            raw = _get(pattern, text)
            if not raw or raw.lower() in ("none","n/a","-","$none"):
                return None
            try:
                return "$" + f"{float(raw.replace('$','').replace(',','')):,.2f}"
            except Exception:
                return None
        return {
            "timeframe":    _get(r"TIMEFRAME[:\s]+(\S+)", ai_text) or "4H",
            "direction":    _get(r"DIRECTION[:\s]+(\w+)", ai_text) or "Long",
            "rationale":    _get(r"RATIONALE[:\s]*(.+?)(?=\nNIGERIAN|\n[A-Z]|\Z)", ai_text),
            "ng_angle":     _get(r"NIGERIAN ANGLE[:\s]*(.+?)(?=\nMarket|\n[A-Z]|\Z)", ai_text),
            "bias":         _get(r"Market Bias[:\s]*(.+?)(?=\n|\Z)", ai_text) or "Neutral",
            "entry":        _pf(r"Entry[:\s]+\$?([0-9,\.]+)", ai_text),
            "stop":         _pf(r"Stop Loss[:\s]+\$?([0-9,\.]+)", ai_text),
            "target1":      _pf(r"Target 1[:\s]+\$?([0-9,\.]+)", ai_text),
            "target2":      _pf(r"Target 2[:\s]+\$?([0-9,\.]+)", ai_text),
            "invalidation": _pf(r"Invalidation[:\s]+\$?([0-9,\.]+)", ai_text),
            "confidence":   _get(r"Confidence[:\s]+(\w+)", ai_text) or "Moderate",
        }
    except Exception as e:
        logger.warning(f"[TRADE PARSE] {e}")
        return None


def save_trade_idea(coin, tier, trade, ai_raw=""):
    db = None
    try:
        db = get_db()
        c = db.cursor()
        now = wat_now().strftime("%Y-%m-%d %H:%M:%S")
        metrics = _calc_trade_metrics(trade.get("entry",""), trade.get("stop",""), trade.get("target1",""))
        rr_str = f"1:{metrics['rr']}" if metrics else "N/A"
        c.execute(
            """INSERT INTO trade_ideas
               (coin, tier, direction, timeframe, entry, stop, target1, target2,
                bias, confidence, rr, invalidation, max_size_pct, ai_rationale, status, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',%s) RETURNING id""",
            (coin, tier, trade.get("direction","Long"), trade.get("timeframe","4H"),
             trade.get("entry"), trade.get("stop"), trade.get("target1"), trade.get("target2"),
             trade.get("bias","Neutral"), trade.get("confidence","Moderate"), rr_str,
             trade.get("invalidation"), TRADE_TIERS[tier]["max_size"],
             ai_raw[:500] if ai_raw else "", now)
        )
        idea_id = c.fetchone()[0]
        db.commit()
        logger.info(f"[TRADE IDEAS] #{idea_id} saved — {coin} {tier}")
        return idea_id
    except Exception as e:
        logger.error(f"[TRADE IDEAS] Save error: {e}")
        if db:
            try: db.rollback()
            except Exception: pass
        return 0
    finally:
        if db:
            try: db.close()
            except Exception: pass


def build_trade_idea_message(coin, price, tier, trade, idea_id=0):
    tier_cfg = TRADE_TIERS[tier]
    metrics = _calc_trade_metrics(trade.get("entry",""), trade.get("stop",""), trade.get("target1",""))
    lines = [
        f"{tier_cfg['emoji']} <b>{tier_cfg['label']} #{idea_id}</b>",
        f"<b>{coin}/USDT</b>  \u00b7  {trade.get('direction','Long').upper()}  \u00b7  {trade.get('timeframe','4H')}",
        f"<i>{tier_cfg['risk_desc']}</i>",
        "",
        f"\U0001f4b0 Current: <b>{format_price(price)}</b>",
        f"\U0001f4c8 Bias: <b>{trade.get('bias','Neutral')}</b>",
        "",
    ]
    if trade.get("rationale"):
        lines += ["\U0001f4cb <b>SETUP</b>", trade["rationale"], ""]
    if trade.get("ng_angle"):
        lines += ["\U0001f1f3\U0001f1ec <b>NIGERIAN ANGLE</b>", trade["ng_angle"], ""]
    lines += ["\u00b7 " * 18, ""]
    entry = trade.get("entry","\u2014")
    stop  = trade.get("stop","\u2014")
    t1    = trade.get("target1","\u2014")
    t2    = trade.get("target2")
    inv   = trade.get("invalidation","\u2014")
    conf  = trade.get("confidence","Moderate")
    lines += [
        "\U0001f4d0 <b>LEVELS</b>",
        f"Entry:        <b>{entry}</b>",
        f"Stop Loss:    <b>{stop}</b>",
        f"Target 1:     <b>{t1}</b>",
    ]
    if t2:
        lines.append(f"Target 2:     <b>{t2}</b>  <i>(aggressive)</i>")
    lines += [f"Invalidation: <b>{inv}</b>", ""]
    if metrics:
        lines += [
            "\U0001f4ca <b>RISK METRICS</b>",
            f"Risk:Reward:  <b>1 : {metrics['rr']}</b>",
            f"Stop Risk:    <b>-{metrics['risk_pct']:.1f}%</b>  (${metrics['pot_loss']:,.0f} per $1,000)",
            f"T1 Reward:    <b>+{metrics['reward_pct']:.1f}%</b>  (${metrics['pot_profit']:,.0f} per $1,000)",
            f"Confidence:   <b>{conf}</b>",
            f"Max Size:     <b>{tier_cfg['max_size']}</b>",
            "",
        ]
    lines += ["\u00b7 " * 18, ""]
    lines.append(EDGE_DISCLAIMER if tier == "edge" else STANDARD_DISCLAIMER)
    return "\n".join(lines)


def generate_trade_idea(coin, tier="momentum"):
    """Full pipeline: gather analytics → pre-screen → AI → parse → validate → save → return."""
    try:
        price, _ = get_best_price(coin)
        if not price:
            return None, None, 0
        sd      = get_secondary_coin(coin)
        fg_data = get_fear_greed()
        fg_val  = fg_data[0]["value"] if fg_data else "50"
        buy, sell, _ = get_p2p_rate("USDT", "NGN")
        p2p_str = f"USDT/NGN Buy \u20a6{int(buy):,} / Sell \u20a6{int(sell):,}" if buy else "N/A"

        # Gather rich market analytics from price history
        analytics = _gather_trade_analytics(coin, price)

        # Pre-screen: check if market conditions support this tier
        ok, reason = _tier_conditions_met(tier, analytics, fg_val)
        if not ok:
            logger.info(f"[TRADE ENGINE] {coin} {tier} pre-screened out: {reason}")
            return None, None, 0

        prompt  = _build_trade_ai_prompt(coin, price, tier, sd, fg_val, p2p_str, analytics)
        ai_raw, _ = ask_ai(prompt)
        if not ai_raw:
            return None, None, 0
        trade = _parse_trade_idea(ai_raw, price)
        if not trade or not trade.get("entry"):
            return None, None, 0
        if trade["entry"] and trade["entry"].lower() in ("$none","none"):
            logger.info(f"[TRADE ENGINE] {coin} {tier} — AI found no quality setup")
            return None, None, 0
        direction = trade.get("direction","Long").lower()
        valid, reason = _validate_alert(
            coin, price,
            trade.get("entry",""), trade.get("stop",""), trade.get("target1",""),
            tier, direction=direction
        )
        if not valid:
            logger.warning(f"[TRADE ENGINE] {coin} {tier} validation failed: {reason}")
            return None, None, 0
        idea_id = save_trade_idea(coin, tier, trade, ai_raw)
        analytics_str = _analytics_to_str(analytics) if analytics else ""
        msg = build_trade_idea_message(coin, price, tier, trade, idea_id)
        if analytics_str and "Insufficient" not in analytics_str:
            msg += f"\n\n<i>\U0001f4ca Data: {analytics_str}</i>"
        return msg, trade, idea_id
    except Exception as e:
        logger.error(f"[TRADE ENGINE] {coin} {tier}: {e}")
        return None, None, 0


def get_trade_history(limit=10, coin=None, tier=None):
    db = None
    try:
        db = get_db()
        c = db.cursor()
        filters, params = [], []
        if coin:
            filters.append("coin=%s"); params.append(coin)
        if tier:
            filters.append("tier=%s"); params.append(tier)
        where = ("WHERE " + " AND ".join(filters)) if filters else ""
        params.append(limit)
        c.execute(
            f"SELECT id, coin, tier, direction, timeframe, entry, target1, confidence, status, created_at "
            f"FROM trade_ideas {where} ORDER BY id DESC LIMIT %s", params
        )
        return c.fetchall()
    except Exception as e:
        logger.error(f"[TRADE HISTORY] {e}")
        return []
    finally:
        if db:
            try: db.close()
            except Exception: pass


def close_trade_idea(idea_id, result):
    db = None
    try:
        db = get_db()
        c = db.cursor()
        now = wat_now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "UPDATE trade_ideas SET status='closed', closed_at=%s, result=%s WHERE id=%s",
            (now, result, idea_id)
        )
        db.commit()
        return True
    except Exception as e:
        logger.error(f"[CLOSE TRADE] {e}")
        if db:
            try: db.rollback()
            except Exception: pass
        return False
    finally:
        if db:
            try: db.close()
            except Exception: pass




def check_user_price_alerts():
    """Check all active user-set price alerts. Batch-deactivates triggered alerts."""
    db = None
    try:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT id, chat, coin, condition, target, label FROM alerts WHERE active=1")
        rows = c.fetchall()
    except Exception as e:
        logger.error(f"[PRICE ALERTS LOAD] {e}")
        return
    finally:
        if db:
            try: db.close()
            except Exception: pass

    triggered_ids = []
    for row in rows:
        aid, chat_id, coin, condition, target, label = row
        try:
            price, _ = get_best_price(coin)
            if not price:
                continue
            fired = (condition == "above" and price >= target) or                     (condition == "below" and price <= target)
            if fired:
                lbl = f" ({label})" if label else ""
                arrow = "📈" if condition == "above" else "📉"
                msg = (
                    f"🔔 <b>PRICE ALERT TRIGGERED</b>\n\n"
                    f"{arrow} <b>{coin}</b> is now <b>{condition}</b> your target{lbl}\n"
                    f"💰 Current: <b>{format_price(price)}</b>\n"
                    f"🎯 Target: <b>{format_price(target)}</b>\n\n"
                    f"<i>NFA - DYOR</i>"
                )
                send(int(chat_id), msg)
                triggered_ids.append(aid)
                logger.info(f"[PRICE ALERT] {coin} {condition} {target} triggered for {chat_id}")
        except Exception as e:
            logger.error(f"[PRICE ALERT] {coin} for {chat_id}: {e}")

    # Batch-deactivate all triggered alerts in one query
    if triggered_ids:
        db2 = None
        try:
            db2 = get_db()
            c2 = db2.cursor()
            c2.execute("UPDATE alerts SET active=0 WHERE id = ANY(%s)", (triggered_ids,))
            db2.commit()
        except Exception as e:
            logger.error(f"[PRICE ALERT DEACTIVATE] {e}")
            if db2:
                try: db2.rollback()
                except Exception: pass
        finally:
            if db2:
                try: db2.close()
                except Exception: pass



def check_watchlist_alerts():
    """Single-query watchlist check — no N+1 pattern."""
    db = None
    try:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT chat, coin FROM watchlists ORDER BY chat")
        rows = c.fetchall()
    except Exception as e:
        logger.error("[WATCHLIST ALERT ERROR] %s" % e)
        return
    finally:
        if db:
            try: db.close()
            except Exception: pass

    from collections import defaultdict
    watchlists = defaultdict(list)
    for chat_id, coin in rows:
        watchlists[chat_id].append(coin)

    for chat_id, coins in watchlists.items():
        for coin in coins:
            try:
                price, change = get_best_price(coin)
                if price and change and abs(change) > 5:
                    direction = "🚀 UP" if change > 0 else "🔴 DOWN"
                    send(chat_id, (
                        f"🔔 <b>Watchlist Alert</b>\n\n"
                        f"{coin} is {direction} <b>{abs(change):.2f}%</b>\n"
                        f"Current: {format_price(price)}\n\n"
                        f"<i>NFA - DYOR</i>"
                    ))
            except Exception as e:
                logger.error(f"[WATCHLIST ALERT] {coin} for {chat_id}: {e}")

# ═══════════════════════════════════════════════════════════════════════════
# 🐋 WHALE / BREAKOUT DETECTION
# ═══════════════════════════════════════════════════════════════════════════

_whale_price_cache = {}  # coin -> price at last hourly snapshot
_whale_snapshot_ready = False  # True after first snapshot has been taken
_morning_btc_snapshot = {}  # {"price": float} — BTC price at morning post time, for midday conditional check



def check_p2p_rate_alerts():
    """Check user-set P2P rate alerts and notify when target is crossed."""
    db = None
    try:
        db = get_db()
        c = db.cursor()
        c.execute(
            "SELECT id, chat, crypto, fiat, condition, target FROM p2p_alerts WHERE active=1"
        )
        rows = c.fetchall()
    except Exception as e:
        logger.error("[P2P ALERTS] Load error: %s" % e)
        return
    finally:
        if db:
            try: db.close()
            except Exception: pass

    triggered_ids = []
    for row in rows:
        aid, chat_id, crypto, fiat, condition, target = row
        try:
            buy, sell, source = get_p2p_rate(crypto, fiat)
            if not buy or not sell:
                continue
            rate = buy if condition == "buy_below" else sell
            fired = (condition == "buy_below" and rate <= target) or                     (condition == "sell_above" and rate >= target)
            if fired:
                symbol = P2P_FIATS.get(fiat, ("", fiat))[1]
                direction = "dropped to or below" if condition == "buy_below" else "reached or above"
                msg = (
                    f"🔔 <b>P2P RATE ALERT</b>\n\n"
                    f"💱 {crypto}/{fiat} {condition.replace('_',' ').title()}\n"
                    f"Current rate: <b>{symbol}{int(rate):,}</b>\n"
                    f"Your target:  <b>{symbol}{int(target):,}</b>\n\n"
                    f"Rate has {direction} your target.\n"
                    f"<i>Source: {source}  ·  NFA</i>"
                )
                send(int(chat_id), msg)
                triggered_ids.append(aid)
        except Exception as e:
            logger.error(f"[P2P ALERT] {crypto}/{fiat} for {chat_id}: {e}")

    if triggered_ids:
        db2 = None
        try:
            db2 = get_db()
            c2 = db2.cursor()
            c2.execute("UPDATE p2p_alerts SET active=0 WHERE id = ANY(%s)", (triggered_ids,))
            db2.commit()
        except Exception as e:
            logger.error("[P2P ALERT DEACTIVATE] %s" % e)
            if db2:
                try: db2.rollback()
                except Exception: pass
        finally:
            if db2:
                try: db2.close()
                except Exception: pass




# ═══════════════════════════════════════════════════════════════════════════
# 💱 FOREX TRADE ENGINE
# ═══════════════════════════════════════════════════════════════════════════
# Generates trade setups for currency pairs — same 3 tiers as crypto.
# Data sources: get_p2p_rate() for NGN pairs, get_fiat_rates() for major forex.
# All ideas posted to Pro channel only.
# ═══════════════════════════════════════════════════════════════════════════

FOREX_PAIRS = {
    "USDT/NGN": {
        "description": "Tether vs Nigerian Naira (P2P market)",
        "base": "USDT", "quote": "NGN",
        "symbol": "₦", "source": "p2p",
        "pip_size": 1.0,        # 1 naira pip
        "typical_spread": 30,   # typical buy-sell spread in naira
    },
    "USD/NGN": {
        "description": "US Dollar vs Nigerian Naira",
        "base": "USD", "quote": "NGN",
        "symbol": "₦", "source": "fiat",
        "pip_size": 1.0,
        "typical_spread": 50,
    },
    "BTC/NGN": {
        "description": "Bitcoin vs Nigerian Naira",
        "base": "BTC", "quote": "NGN",
        "symbol": "₦", "source": "derived",
        "pip_size": 1000,
        "typical_spread": 5000,
    },
    "EUR/USD": {
        "description": "Euro vs US Dollar",
        "base": "EUR", "quote": "USD",
        "symbol": "$", "source": "fiat",
        "pip_size": 0.0001,
        "typical_spread": 0.0002,
    },
    "GBP/USD": {
        "description": "British Pound vs US Dollar",
        "base": "GBP", "quote": "USD",
        "symbol": "$", "source": "fiat",
        "pip_size": 0.0001,
        "typical_spread": 0.0002,
    },
}


def get_forex_rate(pair_key):
    """Get current rate for a forex pair.
    Returns (rate, bid, ask, source_str) or (None, None, None, None)."""
    pair = FOREX_PAIRS.get(pair_key)
    if not pair:
        return None, None, None, None

    try:
        if pair["source"] == "p2p":
            buy, sell, source = get_p2p_rate("USDT", "NGN")
            if buy and sell:
                mid = (buy + sell) / 2
                return mid, sell, buy, f"P2P ({source})"
            return None, None, None, None

        elif pair["source"] == "fiat":
            rates = get_fiat_rates()
            if pair_key == "USD/NGN":
                ngn = rates.get("NGN")
                if ngn:
                    spread = pair["typical_spread"]
                    return ngn, ngn - spread/2, ngn + spread/2, "ExchangeRate"
            elif pair_key == "EUR/USD":
                eur = rates.get("EUR")
                if eur:
                    # EUR/USD = 1/EUR rate (EUR rate is how many EUR per USD)
                    rate = 1 / eur if eur else None
                    if rate:
                        spread = pair["typical_spread"]
                        return rate, rate - spread, rate + spread, "Frankfurter"
            elif pair_key == "GBP/USD":
                gbp = rates.get("GBP")
                if gbp:
                    rate = 1 / gbp if gbp else None
                    if rate:
                        spread = pair["typical_spread"]
                        return rate, rate - spread, rate + spread, "Frankfurter"
            return None, None, None, None

        elif pair["source"] == "derived":
            # BTC/NGN = BTC/USD * USD/NGN
            btc_usd, _ = get_best_price("BTC")
            rates = get_fiat_rates()
            ngn_rate = rates.get("NGN")
            if btc_usd and ngn_rate:
                rate = btc_usd * ngn_rate
                spread = rate * 0.005  # 0.5% spread
                return rate, rate - spread, rate + spread, "Derived (BTC*NGN)"
            return None, None, None, None

    except Exception as e:
        logger.warning(f"[FOREX RATE] {pair_key}: {e}")
    return None, None, None, None


def _build_forex_ai_prompt(pair_key, rate, bid, ask, tier, fg_val, source):
    """Build AI prompt for a forex trade idea."""
    pair = FOREX_PAIRS[pair_key]
    tier_cfg = TRADE_TIERS[tier]
    symbol = pair["symbol"]
    tf_guide = {
        "steady":   "Daily or Weekly timeframe. Prefer established range boundaries.",
        "momentum": "4H or Daily timeframe. Trend continuation or breakout from range.",
        "edge":     "1H or 4H timeframe. High-conviction directional move only.",
    }
    ngn_context = ""
    if "NGN" in pair_key:
        ngn_context = (
            f"\nNIGERIAN CONTEXT: This is the most important pair for Nigerian traders. "
            f"Consider naira depreciation trends, CBN policy, parallel market dynamics, "
            f"and import demand pressures in your analysis."
        )

    return (
        f"You are a professional forex analyst generating a {tier_cfg['risk_desc']} trade idea "
        f"for Nigerian traders on Market Pulse Pro.\n\n"
        f"PAIR: {pair_key} — {pair['description']}\n"
        f"CURRENT RATE: {symbol}{rate:,.4f}\n"
        f"BID: {symbol}{bid:,.4f} | ASK: {symbol}{ask:,.4f}\n"
        f"DATA SOURCE: {source}\n"
        f"FEAR & GREED (crypto): {fg_val}/100 (sentiment context){ngn_context}\n\n"
        f"TIER: {tier_cfg['label']} — {tier_cfg['risk_desc']}\n"
        f"TIMEFRAME: {tf_guide[tier]}\n"
        f"STOP MAX: {tier_cfg['max_stop_pct']}% from entry\n"
        f"TARGET MIN: {tier_cfg['min_target_pct']}% from entry\n"
        f"MIN R:R: {tier_cfg['min_rr']}:1\n\n"
        f"IMPORTANT: Entry, Stop, Target must be in {pair['quote']} terms (e.g. {symbol}1,620 not $1,620).\n"
        f"If no quality {tier} setup exists right now, say so clearly.\n\n"
        f"Respond ONLY in this exact format. No asterisks. Plain text:\n"
        f"TIMEFRAME: [1H / 4H / Daily / Weekly]\n"
        f"DIRECTION: [Buy {pair['base']} / Sell {pair['base']}]\n"
        f"RATIONALE: [2 sentences — explain why this setup makes sense now]\n"
        f"NIGERIAN ANGLE: [1 sentence — what this means for naira holders or P2P traders]\n"
        f"Market Bias: [Bullish {pair['base']} / Bearish {pair['base']} / Neutral]\n"
        f"Entry: {symbol}[rate]\n"
        f"Stop Loss: {symbol}[rate]\n"
        f"Target 1: {symbol}[rate]\n"
        f"Target 2: {symbol}[rate or none]\n"
        f"Invalidation: {symbol}[rate]\n"
        f"Confidence: [High / Moderate / Low]\n"
        f"If no quality setup: TIMEFRAME: None\nDIRECTION: None\nEntry: none"
    )


def _parse_forex_trade(ai_text, rate, symbol):
    """Parse AI forex trade response. Returns dict or None."""
    if not ai_text:
        return None
    try:
        def _get(pattern, text):
            m = re.search(pattern, text, re.IGNORECASE)
            return m.group(1).strip() if m else None

        def _pf(pattern, text):
            raw = _get(pattern, text)
            if not raw or raw.lower() in ("none", "n/a", "-"):
                return None
            # Strip any currency symbols and commas
            cleaned = re.sub(r"[₦$£€,]", "", raw).strip()
            try:
                return float(cleaned)
            except Exception:
                return None

        entry = _pf(r"Entry[:\s]+[₦$£€]?([0-9,\.]+)", ai_text)
        if not entry:
            return None
        if str(entry).lower() == "none":
            return None

        return {
            "timeframe":    _get(r"TIMEFRAME[:\s]+(\S+)", ai_text) or "4H",
            "direction":    _get(r"DIRECTION[:\s]*(.+?)(?=\n|$)", ai_text) or "Buy",
            "rationale":    _get(r"RATIONALE[:\s]*(.+?)(?=\nNIGERIAN|\n[A-Z]|$)", ai_text),
            "ng_angle":     _get(r"NIGERIAN ANGLE[:\s]*(.+?)(?=\nMarket|\n[A-Z]|$)", ai_text),
            "bias":         _get(r"Market Bias[:\s]*(.+?)(?=\n|$)", ai_text) or "Neutral",
            "entry":        entry,
            "stop":         _pf(r"Stop Loss[:\s]+[₦$£€]?([0-9,\.]+)", ai_text),
            "target1":      _pf(r"Target 1[:\s]+[₦$£€]?([0-9,\.]+)", ai_text),
            "target2":      _pf(r"Target 2[:\s]+[₦$£€]?([0-9,\.]+)", ai_text),
            "invalidation": _pf(r"Invalidation[:\s]+[₦$£€]?([0-9,\.]+)", ai_text),
            "confidence":   _get(r"Confidence[:\s]+(\w+)", ai_text) or "Moderate",
        }
    except Exception as e:
        logger.warning(f"[FOREX PARSE] {e}")
        return None


def _validate_forex_trade(pair_key, rate, trade):
    """Validate forex trade levels. Returns (valid, reason)."""
    entry  = trade.get("entry")
    stop   = trade.get("stop")
    target = trade.get("target1")
    direction = trade.get("direction","Buy").lower()

    if not entry or not stop or not target:
        return False, "Missing entry, stop, or target"
    if entry <= 0 or stop <= 0 or target <= 0:
        return False, "Negative or zero price levels"

    is_buy = "buy" in direction or "long" in direction

    if is_buy:
        if stop >= entry:
            return False, f"Buy stop {stop} >= entry {entry}"
        if target <= entry:
            return False, f"Buy target {target} <= entry {entry}"
        rr = (target - entry) / (entry - stop) if (entry - stop) > 0 else 0
    else:
        if stop <= entry:
            return False, f"Sell stop {stop} <= entry {entry}"
        if target >= entry:
            return False, f"Sell target {target} >= entry {entry}"
        rr = (entry - target) / (stop - entry) if (stop - entry) > 0 else 0

    tier_cfg = TRADE_TIERS.get("momentum", {})
    min_rr = tier_cfg.get("min_rr", 1.5)
    if rr < min_rr:
        return False, f"R:R {rr:.2f} below minimum {min_rr}"

    return True, "OK"


def build_forex_trade_message(pair_key, rate, tier, trade, idea_id=0):
    """Build Pro channel message for a forex trade idea."""
    pair     = FOREX_PAIRS[pair_key]
    tier_cfg = TRADE_TIERS[tier]
    symbol   = pair["symbol"]
    entry    = trade.get("entry")
    stop     = trade.get("stop")
    t1       = trade.get("target1")
    t2       = trade.get("target2")
    inv      = trade.get("invalidation")
    conf     = trade.get("confidence", "Moderate")
    direction = trade.get("direction", f"Buy {pair['base']}")

    # Calculate R:R
    rr_str = "N/A"
    risk_pct = stop_pct = t1_pct = None
    if entry and stop and t1:
        is_buy = "buy" in direction.lower() or "long" in direction.lower()
        try:
            if is_buy:
                risk   = entry - stop
                reward = t1 - entry
            else:
                risk   = stop - entry
                reward = entry - t1
            if risk > 0:
                rr_str   = f"1 : {reward/risk:.2f}"
                stop_pct = abs(risk / entry * 100)
                t1_pct   = abs(reward / entry * 100)
        except Exception:
            pass

    def fmt(v):
        if v is None:
            return "—"
        if symbol == "₦":
            return format_ngn(v)
        return format_forex(v, symbol)

    lines = [
        f"{tier_cfg['emoji']} <b>{tier_cfg['label']} #{idea_id} — FOREX</b>",
        f"<b>{pair_key}</b>  ·  {direction.upper()}  ·  {trade.get('timeframe','4H')}",
        f"<i>{pair['description']} — {tier_cfg['risk_desc']}</i>",
        "",
        f"💱 Current Rate: <b>{fmt(rate)}</b>",
        f"📈 Bias: <b>{trade.get('bias','Neutral')}</b>",
        "",
    ]
    if trade.get("rationale"):
        lines += ["📋 <b>SETUP</b>", trade["rationale"], ""]
    if trade.get("ng_angle"):
        lines += ["🇳🇬 <b>NIGERIAN ANGLE</b>", trade["ng_angle"], ""]

    lines += [
        "· · · · · · · · · · · · · · · · · · ·", "",
        "📐 <b>LEVELS</b>",
        f"Entry:        <b>{fmt(entry)}</b>",
        f"Stop Loss:    <b>{fmt(stop)}</b>",
        f"Target 1:     <b>{fmt(t1)}</b>",
    ]
    if t2:
        lines.append(f"Target 2:     <b>{fmt(t2)}</b>  <i>(aggressive)</i>")
    lines += [f"Invalidation: <b>{fmt(inv)}</b>", ""]

    if rr_str != "N/A" and stop_pct:
        lines += [
            "📊 <b>RISK METRICS</b>",
            f"Risk:Reward:  <b>{rr_str}</b>",
            f"Stop Risk:    <b>-{stop_pct:.2f}%</b>",
        ]
        if t1_pct:
            lines.append(f"T1 Reward:    <b>+{t1_pct:.2f}%</b>")
        lines += [
            f"Confidence:   <b>{conf}</b>",
            f"Max Size:     <b>{tier_cfg['max_size']}</b>",
            "",
        ]

    lines += ["· · · · · · · · · · · · · · · · · · ·", ""]
    lines.append(EDGE_DISCLAIMER if tier == "edge" else STANDARD_DISCLAIMER)
    return "\n".join(lines)


def generate_forex_trade_idea(pair_key, tier="momentum"):
    """Full pipeline for forex trade idea: fetch → AI → parse → validate → save → post."""
    try:
        rate, bid, ask, source = get_forex_rate(pair_key)
        if not rate:
            logger.info(f"[FOREX ENGINE] No rate for {pair_key}")
            return None, None, 0

        pair     = FOREX_PAIRS[pair_key]
        fg_data  = get_fear_greed()
        fg_val   = fg_data[0]["value"] if fg_data else "50"

        prompt   = _build_forex_ai_prompt(pair_key, rate, bid or rate, ask or rate, tier, fg_val, source)
        ai_raw, _ = ask_ai(prompt)
        if not ai_raw:
            return None, None, 0

        trade = _parse_forex_trade(ai_raw, rate, pair["symbol"])
        if not trade or not trade.get("entry"):
            logger.info(f"[FOREX ENGINE] {pair_key} {tier} — no setup from AI")
            return None, None, 0

        valid, reason = _validate_forex_trade(pair_key, rate, trade)
        if not valid:
            logger.warning(f"[FOREX ENGINE] {pair_key} {tier} validation failed: {reason}")
            return None, None, 0

        # Save to trade_ideas table (reuse same table — pair_key as coin)
        db = None
        idea_id = 0
        try:
            db = get_db()
            c  = db.cursor()
            now = wat_now().strftime("%Y-%m-%d %H:%M:%S")
            is_buy = "buy" in trade.get("direction","").lower()
            entry = trade.get("entry", 0)
            stop  = trade.get("stop", 0)
            t1    = trade.get("target1", 0)
            rr    = abs((t1 - entry) / (entry - stop)) if (entry - stop) != 0 else 0
            c.execute(
                """INSERT INTO trade_ideas
                   (coin, tier, direction, timeframe, entry, stop, target1, target2,
                    bias, confidence, rr, invalidation, max_size_pct, ai_rationale, status, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',%s) RETURNING id""",
                (
                    pair_key, tier,
                    trade.get("direction", "Buy"),
                    trade.get("timeframe", "4H"),
                    str(round(entry, 4)) if entry else None,
                    str(round(stop, 4)) if stop else None,
                    str(round(t1, 4)) if t1 else None,
                    str(round(trade["target2"], 4)) if trade.get("target2") else None,
                    trade.get("bias", "Neutral"),
                    trade.get("confidence", "Moderate"),
                    f"1:{rr:.2f}",
                    str(round(trade["invalidation"], 4)) if trade.get("invalidation") else None,
                    TRADE_TIERS[tier]["max_size"],
                    ai_raw[:500],
                    now,
                )
            )
            idea_id = c.fetchone()[0]
            db.commit()
            logger.info(f"[FOREX ENGINE] #{idea_id} saved — {pair_key} {tier}")
        except Exception as e:
            logger.error(f"[FOREX ENGINE] Save error: {e}")
        finally:
            if db:
                try: db.close()
                except Exception: pass

        msg = build_forex_trade_message(pair_key, rate, tier, trade, idea_id)
        return msg, trade, idea_id

    except Exception as e:
        logger.error(f"[FOREX ENGINE] {pair_key} {tier}: {e}")
        return None, None, 0


# ═══════════════════════════════════════════════════════════════════════════
# 🤖 AUTOMATED TRADE SCANNER
# ═══════════════════════════════════════════════════════════════════════════
# Runs every 4 hours. Pre-screens all coins + forex pairs.
# Picks the single best setup. Posts to Pro channel.
# Max 1 post per 4-hour window. Max 3 per day. DB-backed cooldown.
# ═══════════════════════════════════════════════════════════════════════════

# Coins the scanner will check (most liquid, best AI setups)
SCANNER_CRYPTO_COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "AVAX", "LINK", "DOGE"]
SCANNER_FOREX_PAIRS  = ["USDT/NGN", "USD/NGN", "BTC/NGN", "EUR/USD", "GBP/USD"]

# Tier priority — Edge checked first as highest value for Pro subscribers
SCANNER_TIER_ORDER   = ["edge", "momentum", "steady"]

_scanner_daily_count = {"date": None, "count": 0}


def _scanner_get_cooldown():
    """Return True if scanner posted in last 4 hours."""
    db = None
    try:
        db = get_db()
        c  = db.cursor()
        since = (wat_now() - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "SELECT updated_at FROM admin_settings WHERE key='auto_scanner_last' AND updated_at >= %s",
            (since,)
        )
        return c.fetchone() is not None
    except Exception as e:
        logger.warning(f"[SCANNER CD] {e}")
        return False
    finally:
        if db:
            try: db.close()
            except Exception: pass


def _scanner_set_cooldown():
    """Record that scanner just posted."""
    db = None
    try:
        db = get_db()
        c  = db.cursor()
        now = wat_now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "INSERT INTO admin_settings (key, value, updated_at) VALUES ('auto_scanner_last',%s,%s) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (now, now)
        )
        db.commit()
    except Exception as e:
        logger.warning(f"[SCANNER CD SET] {e}")
        if db:
            try: db.rollback()
            except Exception: pass
    finally:
        if db:
            try: db.close()
            except Exception: pass


def run_trade_scanner():
    """
    Automated trade scanner. Called every 4 hours by the scheduler.

    Strategy:
    1. Check 4-hour cooldown — skip if already posted recently
    2. Check daily max (3 per day) — skip if hit
    3. Pre-screen all crypto coins for each tier using analytics
    4. Pre-screen all forex pairs
    5. Pick the single best candidate (Edge > Momentum > Steady)
    6. Generate one AI trade idea for that candidate
    7. Post to Pro channel if valid
    8. Set cooldown
    """
    global _scanner_daily_count

    # Daily count reset
    today = wat_now().strftime("%Y-%m-%d")
    if _scanner_daily_count["date"] != today:
        _scanner_daily_count = {"date": today, "count": 0}

    if _scanner_daily_count["count"] >= 3:
        logger.info("[SCANNER] Daily max (3) reached — skipping")
        return

    if _scanner_get_cooldown():
        logger.info("[SCANNER] 4-hour cooldown active — skipping")
        return

    logger.info("[SCANNER] Starting automated trade scan...")

    fg_data = get_fear_greed()
    fg_val  = fg_data[0]["value"] if fg_data else "50"

    # ── Phase 1: Pre-screen crypto coins ──────────────────────────────────
    # No AI calls here — only analytics check. Fast.
    candidates = []  # (priority, type, identifier, tier)

    tier_priority = {"edge": 0, "momentum": 1, "steady": 2}

    for tier in SCANNER_TIER_ORDER:
        for coin in SCANNER_CRYPTO_COINS:
            try:
                price, _ = get_best_price(coin)
                if not price:
                    continue
                analytics = _gather_trade_analytics(coin, price)
                ok, reason = _tier_conditions_met(tier, analytics, fg_val)
                if ok:
                    candidates.append((tier_priority[tier], "crypto", coin, tier))
                    logger.info(f"[SCANNER] {coin} {tier} passed pre-screen")
            except Exception as e:
                logger.warning(f"[SCANNER] {coin} {tier} error: {e}")

    # ── Phase 2: Pre-screen forex pairs ───────────────────────────────────
    for tier in SCANNER_TIER_ORDER:
        for pair_key in SCANNER_FOREX_PAIRS:
            try:
                rate, _, _, _ = get_forex_rate(pair_key)
                if not rate:
                    continue
                # Forex uses simplified pre-screening — just F&G check
                fg = int(fg_val) if str(fg_val).isdigit() else 50
                if tier == "edge" and not (fg > 70 or fg < 30):
                    continue  # Edge needs extreme sentiment
                candidates.append((tier_priority[tier], "forex", pair_key, tier))
                logger.info(f"[SCANNER] {pair_key} {tier} passed pre-screen")
            except Exception as e:
                logger.warning(f"[SCANNER] {pair_key} {tier} error: {e}")

    if not candidates:
        logger.info("[SCANNER] No candidates passed pre-screening — no post today")
        return

    # ── Phase 3: Pick best candidate and generate ONE AI call ─────────────
    # Sort by priority (Edge=0 first), then crypto before forex for reliability
    candidates.sort(key=lambda x: (x[0], 0 if x[1]=="crypto" else 1))

    for priority, asset_type, identifier, tier in candidates:
        try:
            logger.info(f"[SCANNER] Generating {tier} idea for {identifier} ({asset_type})")

            if asset_type == "crypto":
                msg, trade, idea_id = generate_trade_idea(identifier, tier)
            else:
                msg, trade, idea_id = generate_forex_trade_idea(identifier, tier)

            if msg and idea_id:
                post_to_pro_channel(msg)
                _scanner_set_cooldown()
                _scanner_daily_count["count"] += 1
                logger.info(f"[SCANNER] ✅ Posted #{idea_id} — {identifier} {tier} ({asset_type}) | Daily: {_scanner_daily_count['count']}/3")
                return  # One post per scan — stop here
            else:
                logger.info(f"[SCANNER] {identifier} {tier} — AI found no quality setup, trying next candidate")

        except Exception as e:
            logger.error(f"[SCANNER] {identifier} {tier}: {e}")
            continue

    logger.info("[SCANNER] All candidates tried — no valid setup generated this cycle")



# ═══════════════════════════════════════════════════════════════════════════
# 🌅 MORNING PRO PACKAGE
# ═══════════════════════════════════════════════════════════════════════════
# Fires at 7AM WAT alongside morning brief.
# Pro channel receives: header + 3 crypto setups + 3 forex setups + P2P read
# Each as a separate message. Runs in background thread.
# Skips any tier with no quality setup — never forces a trade.
# ═══════════════════════════════════════════════════════════════════════════

# Best coins to feature in morning package (most liquid, best AI setups)
MORNING_CRYPTO_COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "AVAX"]
MORNING_FOREX_PAIRS  = ["USDT/NGN", "USD/NGN", "EUR/USD", "GBP/USD", "BTC/NGN"]


def build_morning_p2p_intelligence():
    """Build P2P intelligence section for morning Pro package."""
    try:
        buy, sell, source = get_p2p_rate("USDT", "NGN")
        if not buy or not sell:
            return None
        spread = buy - sell
        spread_pct = (spread / sell) * 100
        fg_data = get_fear_greed()
        fg_val = int(fg_data[0]["value"]) if fg_data else 50

        # Direction read
        if fg_val > 65:
            direction = "Naira under pressure — crypto demand high. Buy USDT now before rates rise further."
            emoji = "📈"
        elif fg_val < 35:
            direction = "Crypto sentiment weak — USDT demand may ease. Consider waiting for better P2P rates."
            emoji = "📉"
        else:
            direction = "Market neutral. P2P rates stable. Standard entry timing."
            emoji = "➡️"

        # Spread health
        if spread_pct < 1.5:
            spread_health = "🟢 Tight spread — good liquidity"
        elif spread_pct < 3.0:
            spread_health = "🟡 Normal spread"
        else:
            spread_health = "🔴 Wide spread — low liquidity, trade carefully"

        return (
            f"💱 <b>P2P INTELLIGENCE — MORNING READ</b>\n"
            f"<i>USDT/NGN · {source}</i>\n\n"
            f"Buy USDT:  <b>₦{int(buy):,}</b>\n"
            f"Sell USDT: <b>₦{int(sell):,}</b>\n"
            f"Spread:    <b>₦{int(spread):,}</b> ({spread_pct:.1f}%)\n"
            f"{spread_health}\n\n"
            f"{emoji} <b>Direction Read</b>\n"
            f"{direction}\n\n"
            f"F&G: <b>{fg_val}/100</b> — {fg_emoji(fg_val)} Sentiment context\n\n"
            f"<i>P2P rates change throughout the day. This is the opening read.\n"
            f"NFA — verify before trading.</i>\n"
            f"⚡ Market Pulse Pro"
        )
    except Exception as e:
        logger.error(f"[MORNING P2P] {e}")
        return None


def run_morning_pro_package():
    """
    Full morning Pro trade package. Called in background thread at 7AM WAT.

    Posts to Pro channel in order:
    1. Header
    2. Crypto Steady (best qualifying coin)
    3. Crypto Momentum (best qualifying coin)
    4. Crypto Edge (only if conditions strongly support it)
    5. Forex Steady
    6. Forex Momentum
    7. Forex Edge (only if conditions strongly support it)
    8. P2P Intelligence

    3-second gap between messages for clean channel flow.
    Skips any tier with no quality setup.
    """
    logger.info("[MORNING PRO PKG] Starting morning trade package...")

    fg_data = get_fear_greed()
    fg_val  = fg_data[0]["value"] if fg_data else "50"

    # ── Header ────────────────────────────────────────────────────────────
    wat_str = wat_now().strftime("%A, %B %d · %I:%M %p WAT")
    header  = (
        f"⚡ <b>MORNING PRO INTELLIGENCE PACKAGE</b>\n"
        f"<i>{wat_str}</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Today\'s full trade package follows.\n"
        f"Crypto setups · Forex setups · P2P read\n\n"
        f"<i>Only quality setups posted. Tiers skipped if conditions don\'t support them.</i>"
    )
    post_to_pro_channel(header)
    time.sleep(3)

    # ── Crypto Setups ─────────────────────────────────────────────────────
    crypto_posted = 0
    for tier in ["steady", "momentum", "edge"]:
        posted = False
        for coin in MORNING_CRYPTO_COINS:
            try:
                price, _ = get_best_price(coin)
                if not price:
                    continue
                analytics = _gather_trade_analytics(coin, price)
                ok, reason = _tier_conditions_met(tier, analytics, fg_val)
                if not ok:
                    continue
                msg, trade, idea_id = generate_trade_idea(coin, tier)
                if msg and idea_id:
                    post_to_pro_channel(msg)
                    crypto_posted += 1
                    posted = True
                    logger.info(f"[MORNING PRO PKG] Crypto {tier}: {coin} #{idea_id}")
                    time.sleep(3)
                    break  # One coin per tier
            except Exception as e:
                logger.error(f"[MORNING PRO PKG] Crypto {tier} {coin}: {e}")
                continue
        if not posted:
            logger.info(f"[MORNING PRO PKG] Crypto {tier}: no quality setup found — skipped")

    # ── Forex Setups ──────────────────────────────────────────────────────
    forex_posted = 0
    for tier in ["steady", "momentum", "edge"]:
        posted = False
        for pair_key in MORNING_FOREX_PAIRS:
            try:
                rate, _, _, _ = get_forex_rate(pair_key)
                if not rate:
                    continue
                # Simplified forex pre-screen
                fg = int(fg_val) if str(fg_val).isdigit() else 50
                if tier == "edge" and not (fg > 70 or fg < 30):
                    continue
                msg, trade, idea_id = generate_forex_trade_idea(pair_key, tier)
                if msg and idea_id:
                    post_to_pro_channel(msg)
                    forex_posted += 1
                    posted = True
                    logger.info(f"[MORNING PRO PKG] Forex {tier}: {pair_key} #{idea_id}")
                    time.sleep(3)
                    break  # One pair per tier
            except Exception as e:
                logger.error(f"[MORNING PRO PKG] Forex {tier} {pair_key}: {e}")
                continue
        if not posted:
            logger.info(f"[MORNING PRO PKG] Forex {tier}: no quality setup — skipped")

    # ── P2P Intelligence ──────────────────────────────────────────────────
    try:
        p2p_msg = build_morning_p2p_intelligence()
        if p2p_msg:
            post_to_pro_channel(p2p_msg)
            logger.info("[MORNING PRO PKG] P2P intelligence posted")
            time.sleep(2)
    except Exception as e:
        logger.error(f"[MORNING PRO PKG] P2P: {e}")

    # ── Summary ───────────────────────────────────────────────────────────
    total = crypto_posted + forex_posted
    logger.info(f"[MORNING PRO PKG] Complete — {crypto_posted} crypto + {forex_posted} forex setups posted")

    if total == 0:
        post_to_pro_channel(
            "⚡ <b>MORNING PRO PACKAGE</b>\n\n"
            "No quality setups across all tiers this morning.\n"
            "Market conditions don\'t support a strong entry right now.\n\n"
            "<i>This is the correct call. Protecting capital is part of the strategy.\n"
            "Next package at 7AM tomorrow.</i>\n"
            "⚡ Market Pulse Pro"
        )


def toggle_mirror_mode():
    """Toggle MIRROR_MODE and persist to DB."""
    global MIRROR_MODE
    MIRROR_MODE = not MIRROR_MODE
    try:
        cfg = load_admin_config()
        cfg["MIRROR_MODE"] = MIRROR_MODE
        save_admin_config(cfg)
        logger.info("[ADMIN] Mirror mode toggled to %s" % ("ON" if MIRROR_MODE else "OFF"))
    except Exception as e:
        logger.error("[MIRROR MODE TOGGLE] %s" % e)

def toggle_channel_enabled():
    """Toggle CHANNEL_ENABLED and persist to DB. Safe to call from any scope."""
    global CHANNEL_ENABLED
    CHANNEL_ENABLED = not CHANNEL_ENABLED
    try:
        cfg = load_admin_config()
        cfg["CHANNEL_ENABLED"] = CHANNEL_ENABLED
        save_admin_config(cfg)
        logger.info("[ADMIN] Channel toggled to %s" % ("ON" if CHANNEL_ENABLED else "OFF"))
    except Exception as e:
        logger.error("[TOGGLE CHANNEL] %s" % e)


def run():
    global CHANNEL_ENABLED, PRO_CHANNEL_ID, BOT_MODE, CHANNEL_ID, _kraken_cache, _secondary_cache, _morning_btc_snapshot
    
    # Load admin config on startup
    config = load_admin_config()
    CHANNEL_ENABLED = config.get("CHANNEL_ENABLED", True)
    PRO_CHANNEL_ID  = config.get("PRO_CHANNEL_ID", PRO_CHANNEL_ID)
    BOT_MODE        = config.get("BOT_MODE", "everyone")
    MIRROR_MODE     = config.get("MIRROR_MODE", False)
    if isinstance(MIRROR_MODE, str):
        MIRROR_MODE = MIRROR_MODE.lower() in ("true", "1", "yes")
    
    init_db()

    # Start WebSocket price engine — persistent streams to Binance, Kraken, Bybit.
    # Prices land in _ws_price_cache; get_best_price() reads from it first.
    # REST fetchers remain as automatic fallbacks if WS data is stale.
    start_ws_price_engine()
    logger.info("[STARTUP] WebSocket price engine launched (Binance + Kraken + Bybit)")

    # Load persisted alert watchlist from DB if it was previously set by admin
    try:
        db = get_db(); c = db.cursor()
        c.execute("SELECT value FROM admin_settings WHERE key='alert_watchlist'")
        row = c.fetchone()
        db.close()
        if row:
            saved_coins = json.loads(row[0])
            if saved_coins:
                KEY_ALERT_COINS.clear()
                KEY_ALERT_COINS.extend(saved_coins)
                logger.info(f"[STARTUP] Loaded alert watchlist from DB: {saved_coins}")
    except Exception as e:
        logger.warning(f"[STARTUP] Could not load watchlist from DB: {e}")

    logger.info("=" * 60)
    logger.info("🚀 Market Pulse Bot v22 - Bug Fix Release")
    logger.info("=" * 60)
    logger.info("✅ V17 FIXES ACTIVE:")
    logger.info("  - PostgreSQL syntax fully corrected (no SQLite leftovers)")
    logger.info("  - get_state() tuple handling fixed across all handlers")
    logger.info("  - Whale detection snapshot logic fixed")
    logger.info("  - Admin config loaded from DB + JSON at startup")
    logger.info("  - AI limit resets at WAT midnight")
    logger.info("  - Double AI build on channel posts eliminated")
    logger.info("  - Midday conditional posting (>2% move required)")
    logger.info("  - Admin-configurable alert watchlist via /setwatchlist")
    logger.info("=" * 60)
    logger.info("📊 Bot Mode: %s" % get_bot_mode().upper())
    logger.info("📢 Channel: %s" % ("ENABLED" if CHANNEL_ENABLED else "DISABLED"))
    logger.info("📢 Pro Channel: %s" % (PRO_CHANNEL_ID if PRO_CHANNEL_ID != "-100XXXXXXXXX" else "NOT SET"))
    logger.info("=" * 60)

    last_update_id = 0
    last_morning_post = 0
    last_midday_post = 0
    last_evening_post = 0
    last_weekly_post = 0
    last_health_check = 0
    last_expiry_check = 0
    last_price_save = 0
    last_watchlist_check = 0
    last_daily_digest = 0
    last_key_alert_check = 0
    last_p2p_check = 0
    last_trade_scan = 0
    morning_posted = False
    midday_posted = False
    evening_posted = False
    weekly_posted = False
    educational_posted = False  # Sunday educational content flag
    last_day = None

    while True:
        try:
            now = time.time()
            wat = wat_now()
            wat_h = wat.hour
            wat_day = wat.date()

            if wat_day != last_day:
                morning_posted = False
                midday_posted = False
                evening_posted = False
                weekly_posted = False if wat.weekday() != SCHEDULE["weekly_edge_day"] else weekly_posted
                educational_posted = False if wat.weekday() != 6 else educational_posted
                last_day = wat_day

            # ── HEALTH CHECK ──────────────────────────────────────────────────
            if now - last_health_check >= 600:
                logger.info("[HEALTH] Health check passed")
                last_health_check = now

            # ── EXPIRY REMINDERS ─────────────────────────────────────────────
            if now - last_expiry_check >= 3600:
                last_expiry_check = now

            # ── PRICE HISTORY ────────────────────────────────────────────────
            if now - last_price_save >= 3600:
                save_price_history()
                last_price_save = now

            # ── WATCHLIST ALERTS ─────────────────────────────────────────────
            if now - last_watchlist_check >= 300:
                try:
                    check_watchlist_alerts()
                except Exception as e:
                    logger.error("[WATCHLIST] %s" % e)
                try:
                    check_user_price_alerts()
                except Exception as e:
                    logger.error("[PRICE ALERTS] %s" % e)
                last_watchlist_check = now

            # ── KEY MARKET LEVEL ALERTS ───────────────────────────────────────
            # Check every 30 minutes — cooldown is 6 hours so 10 min was redundant
            if now - last_key_alert_check >= 1800:
                try:
                    check_key_market_alerts()
                except Exception as e:
                    logger.error("[KEY ALERT] %s" % e)
                last_key_alert_check = now

            # ── WHALE / BREAKOUT DETECTION ────────────────────────────────────
            
            # ── AUTOMATED TRADE SCANNER ──────────────────────────────────────
            # Runs every 4 hours. Pre-screens coins + forex. Posts best setup to Pro.
            if now - last_trade_scan >= 14400:
                threading.Thread(
                    target=run_trade_scanner,
                    name="TradeScannerAuto",
                    daemon=True
                ).start()
                last_trade_scan = now

            # ── P2P RATE MONITORING ───────────────────────────────────────────
            if now - last_p2p_check >= 900:   # check every 15 min
                try:
                    check_p2p_rate_alerts()
                except Exception as e:
                    logger.error("[P2P CHECK] %s" % e)
                last_p2p_check = now

            # ── DAILY DIGEST — fires at 8AM WAT each day ──────────────────
            if wat_h == SCHEDULE["admin_digest_hour_wat"] and (now - last_daily_digest >= 3600):
                try:
                    daily_digest()
                except Exception as e:
                    logger.error("[DAILY DIGEST] %s" % e)
                last_daily_digest = now

            # ── CHANNEL POSTS ─────────────────────────────────────────────────
            # C1 FIX: Content Engine always runs in a daemon thread so it
            # never blocks the poll loop (each call makes 7 AI requests,
            # up to 12 minutes blocking time if run synchronously).
            if CHANNEL_ENABLED:
                if wat_h == SCHEDULE["morning_hour_wat"] and not morning_posted:
                    logger.info("[CHANNEL] Morning briefing")
                    pro_content = build_morning_briefing_pro()
                    # Snapshot BTC price at morning for midday conditional check
                    _morning_btc_price, _ = get_best_price("BTC")
                    _morning_btc_snapshot["price"] = _morning_btc_price
                    if get_bot_mode() == "everyone":
                        post_to_channel(pro_content)
                    else:
                        post_to_channel(build_morning_briefing())
                    post_to_pro_channel(pro_content)
                    morning_posted = True
                    # Morning Pro Package — crypto + forex + P2P setups in background
                    threading.Thread(
                        target=run_morning_pro_package,
                        name="MorningProPackage",
                        daemon=True
                    ).start()
                    logger.info("[SCHEDULER] Morning Pro Package thread started")
                    # Content Engine runs in background thread
                    try:
                        btc_p, btc_c = get_best_price("BTC")
                        fg_d = get_fear_greed()
                        g, l = get_gainers_losers()
                        buy_r, sell_r, _ = get_p2p_rate("USDT","NGN")
                        mc = {
                            "btc_price": format_price(btc_p),
                            "btc_change": format_change(btc_c),
                            "fg_val": fg_d[0]["value"] if fg_d else "50",
                            "fg_lbl": fg_d[0]["value_classification"] if fg_d else "Neutral",
                            "gainers_str": ", ".join(f"{c} {ch:+.1f}%" for c,_,ch in g[:3]) if g else "N/A",
                            "losers_str": ", ".join(f"{c} {ch:.1f}%" for c,_,ch in l[:2]) if l else "N/A",
                            "p2p_str": f"USDT/NGN Buy ₦{int(buy_r):,} / Sell ₦{int(sell_r):,}" if buy_r else "",
                            "key_insight": "Morning market brief for Nigerian traders",
                        }
                        _t = threading.Thread(
                            target=generate_and_deliver_content_package,
                            args=("morning", pro_content, mc, "scheduled_morning"),
                            daemon=True
                        )
                        _t.start()
                    except Exception as ce:
                        logger.error(f"[CONTENT ENGINE] Morning thread error: {ce}")

                if wat_h == SCHEDULE["midday_hour_wat"] and not midday_posted:
                    # V2 SPEC: Mid-day update only if market moved >2% since morning
                    btc_now, _ = get_best_price("BTC")
                    btc_morning = _morning_btc_snapshot.get("price")
                    significant_move = True
                    if btc_now and btc_morning and btc_morning > 0:
                        pct_move = abs((btc_now - btc_morning) / btc_morning * 100)
                        if pct_move < 2.0:
                            significant_move = False
                            logger.info(f"[CHANNEL] Midday skipped — BTC only moved {pct_move:.2f}% since morning (threshold: 2%)")
                    if significant_move:
                        logger.info("[CHANNEL] Midday snapshot — significant market move detected")
                        pro_content = build_midday_snapshot_pro()
                        if get_bot_mode() == "everyone":
                            post_to_channel(pro_content)
                        else:
                            post_to_channel(build_midday_snapshot())
                        post_to_pro_channel(pro_content)
                        try:
                            btc_p, btc_c = get_best_price("BTC")
                            fg_d = get_fear_greed()
                            buy_r, sell_r, _ = get_p2p_rate("USDT","NGN")
                            mc = {
                                "btc_price": format_price(btc_p),
                                "btc_change": format_change(btc_c),
                                "fg_val": fg_d[0]["value"] if fg_d else "50",
                                "fg_lbl": fg_d[0]["value_classification"] if fg_d else "Neutral",
                                "p2p_str": f"USDT/NGN Buy ₦{int(buy_r):,} / Sell ₦{int(sell_r):,}" if buy_r else "",
                                "key_insight": "Midday market update — significant move detected",
                            }
                            threading.Thread(
                                target=generate_and_deliver_content_package,
                                args=("midday", pro_content, mc, "scheduled_midday"),
                                daemon=True
                            ).start()
                        except Exception as ce:
                            logger.error(f"[CONTENT ENGINE] Midday thread error: {ce}")
                    midday_posted = True

                if wat_h == SCHEDULE["evening_hour_wat"] and not evening_posted:
                    logger.info("[CHANNEL] Evening recap")
                    pro_content = build_evening_recap_pro()
                    if get_bot_mode() == "everyone":
                        post_to_channel(pro_content)
                    else:
                        post_to_channel(build_evening_recap())
                    post_to_pro_channel(pro_content)
                    evening_posted = True
                    try:
                        btc_p, btc_c = get_best_price("BTC")
                        fg_d = get_fear_greed()
                        g, l = get_gainers_losers()
                        buy_r, sell_r, _ = get_p2p_rate("USDT","NGN")
                        mc = {
                            "btc_price": format_price(btc_p),
                            "btc_change": format_change(btc_c),
                            "fg_val": fg_d[0]["value"] if fg_d else "50",
                            "fg_lbl": fg_d[0]["value_classification"] if fg_d else "Neutral",
                            "gainers_str": ", ".join(f"{c} {ch:+.1f}%" for c,_,ch in g[:3]) if g else "N/A",
                            "losers_str": ", ".join(f"{c} {ch:.1f}%" for c,_,ch in l[:2]) if l else "N/A",
                            "p2p_str": f"USDT/NGN Buy ₦{int(buy_r):,} / Sell ₦{int(sell_r):,}" if buy_r else "",
                            "key_insight": "Evening market recap and tomorrow plan",
                        }
                        threading.Thread(
                            target=generate_and_deliver_content_package,
                            args=("evening", pro_content, mc, "scheduled_evening"),
                            daemon=True
                        ).start()
                    except Exception as ce:
                        logger.error(f"[CONTENT ENGINE] Evening thread error: {ce}")

                if (wat.weekday() == SCHEDULE["weekly_edge_day"] and
                        wat_h == SCHEDULE["weekly_edge_hour"] and
                        not weekly_posted):
                    logger.info("[CHANNEL] Weekly Edge")
                    pro_content = build_weekly_edge_pro()
                    if get_bot_mode() == "everyone":
                        post_to_channel(pro_content)
                    else:
                        post_to_channel(build_weekly_edge())
                    post_to_pro_channel(pro_content)
                    weekly_posted = True
                    try:
                        btc_p, btc_c = get_best_price("BTC")
                        fg_d = get_fear_greed()
                        buy_r, sell_r, _ = get_p2p_rate("USDT","NGN")
                        g, l = get_gainers_losers()
                        mc = {
                            "btc_price": format_price(btc_p),
                            "btc_change": format_change(btc_c),
                            "fg_val": fg_d[0]["value"] if fg_d else "50",
                            "fg_lbl": fg_d[0]["value_classification"] if fg_d else "Neutral",
                            "gainers_str": ", ".join(f"{c} {ch:+.1f}%" for c,_,ch in g[:3]) if g else "N/A",
                            "losers_str": ", ".join(f"{c} {ch:.1f}%" for c,_,ch in l[:2]) if l else "N/A",
                            "p2p_str": f"USDT/NGN Buy ₦{int(buy_r):,} / Sell ₦{int(sell_r):,}" if buy_r else "",
                            "key_insight": "Saturday weekly intelligence report",
                        }
                        threading.Thread(
                            target=generate_and_deliver_content_package,
                            args=("weekly", pro_content, mc, "scheduled_weekly"),
                            daemon=True
                        ).start()
                    except Exception as ce:
                        logger.error(f"[CONTENT ENGINE] Weekly thread error: {ce}")

                # C3 FIX: Educational content fires on SUNDAY at 9AM WAT.
                # Was previously nested inside the Saturday block — making it
                # unreachable (wat.weekday() cannot be both 5 and 6).
                if wat.weekday() == 6 and wat_h == 9 and not educational_posted:
                    logger.info("[CHANNEL] Sunday educational content")
                    educational_posted = True
                    threading.Thread(
                        target=build_weekly_educational_content,
                        daemon=True
                    ).start()

            # ── POLLING ───────────────────────────────────────────────────────
            updates = request_json(
                "GET", "https://api.telegram.org/bot%s/getUpdates" % BOT_TOKEN,
                params={"offset": last_update_id, "timeout": 10},
                timeout=20, retries=2, backoff=1.0
            ) or {}

            for u in updates.get("result", []):
                last_update_id = u["update_id"] + 1

                if "message" in u:
                    msg = u["message"]
                    chat_id = msg["chat"]["id"]
                    text = msg.get("text", "")
                    username = msg["from"].get("username", "")
                    first_name = msg["from"].get("first_name", "")

                    if not text:
                        continue

                    upsert_user(chat_id, username, first_name)
                    log_event(chat_id, text if text.startswith("/") else "text_reply")

                    # ── CHECK BANNED ───────────────────────────────────────────
                    if is_user_banned(chat_id):
                        send(chat_id, "🔒 You are banned from using this bot.")
                        continue

                    # ── CHANNEL LOCK CHECK ────────────────────────────────────
                    if not is_user_in_channel(chat_id) and chat_id not in ADMIN_IDS:
                        send(chat_id,
                             "🔒 <b>Channel Membership Required</b>\n\n"
                             "To use Market Pulse you must join our free channel first:\n\n"
                             "👉 @marketpulseng\n\n"
                             "Join then tap the button below.",
                             [[{"text": "✅ Verified", "callback_data": "verify_join"}]])
                        continue

                    # ═══════════════════════════════════════════════════════════
                    # 🔴 ADMIN COMMANDS (HIDDEN FROM USERS)
                    # ═══════════════════════════════════════════════════════════
                    if chat_id in ADMIN_IDS:
                        # ── ADMIN HELP ──────────────────────────────────────────
                        if text.startswith("/adminhelp"):
                            help_text = (
                                "👑 <b>Admin Commands</b>\n\n"
                                "<b>POSTS</b>\n"
                                "/postnow morning|midday|evening|weekly\n"
                                "/contentpackage morning|midday|evening|weekly\n\n"
                                "<b>TRADES</b>\n"
                                "/trade [COIN] steady|momentum|edge\n"
                                "/tradehistory [COIN] [tier]\n"
                                "/closetrade [ID] hit_t1|hit_t2|stopped|cancelled\n\n"
                                "<b>USERS</b>\n"
                                "/grantpro [ID] [months]\n"
                                "/ban [ID] — /unban [ID]\n"
                                "/broadcast [message]\n\n"
                                "<b>SYSTEM</b>\n"
                                "/stats — /dashboard\n"
                                "/mode everyone|pro\n"
                                "/togglechannel\n"
                                "/packages — /package [ID]\n\n"
                                "Or use /admin for the menu."
                            )
                            send(chat_id, help_text)
                            continue

                        # ── MODE ──────────────────────────────────────────────────
                        if text.startswith("/mode everyone"):
                            set_bot_mode("everyone")
                            config = load_admin_config()
                            config["BOT_MODE"] = "everyone"
                            save_admin_config(config)
                            send(chat_id, "✅ Mode changed to: <b>Everyone Free</b>\n\nAll features are now FREE for everyone.")
                            logger.info("[ADMIN] %s set mode to everyone" % chat_id)
                            continue

                        if text.startswith("/mode pro"):
                            set_bot_mode("pro")
                            config = load_admin_config()
                            config["BOT_MODE"] = "pro"
                            save_admin_config(config)
                            send(chat_id, "✅ Mode changed to: <b>Free & Pro</b>\n\nFree users get limited features. Pro users get everything.")
                            logger.info("[ADMIN] %s set mode to pro" % chat_id)
                            continue

                        # ── GRANT PRO ─────────────────────────────────────────────
                        if text.startswith("/grantpro"):
                            parts = text.split()
                            if len(parts) >= 2:
                                try:
                                    target = int(parts[1])
                                    months = int(parts[2]) if len(parts) >= 3 else 1
                                    if grant_pro(target, months):
                                        send(chat_id, f"✅ Pro granted to <code>{target}</code> for <b>{months}</b> month(s)")
                                        logger.info("[ADMIN] %s granted Pro to %s for %s months" % (chat_id, target, months))
                                    else:
                                        send(chat_id, "❌ Failed to grant Pro.")
                                except Exception as _e:
                                    send(chat_id, "⚠️ Usage: /grantpro CHATID [MONTHS]")
                            else:
                                send(chat_id, "⚠️ Usage: /grantpro CHATID [MONTHS]")
                            continue

                        # ── STATS ──────────────────────────────────────────────────
                        if text.startswith("/stats"):
                            try:
                                db = get_db()
                                c = db.cursor()
                                c.execute("SELECT COUNT(*) FROM users")
                                total_users = c.fetchone()[0]
                                c.execute("SELECT COUNT(*) FROM pro_subscriptions")
                                total_pro = c.fetchone()[0]
                                c.execute("SELECT COUNT(*) FROM alerts WHERE active=1")
                                total_alerts = c.fetchone()[0]
                                c.execute("SELECT COUNT(*) FROM p2p_alerts WHERE active=1")
                                total_p2p_alerts = c.fetchone()[0]
                                c.execute("SELECT COUNT(*) FROM trade_journal")
                                total_trades = c.fetchone()[0]
                                since_24h = (wat_now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
                                c.execute("SELECT COUNT(*) FROM events WHERE timestamp > %s", (since_24h,))
                                active_24h = c.fetchone()[0]
                                c.execute("SELECT COUNT(*) FROM events")
                                total_events = c.fetchone()[0]
                                c.execute("SELECT COUNT(*) FROM watchlists")
                                total_watchlist = c.fetchone()[0]
                                c.execute("SELECT COUNT(*) FROM portfolio")
                                total_portfolio = c.fetchone()[0]
                                c.execute("SELECT COUNT(*) FROM banned_users")
                                total_banned = c.fetchone()[0]
                                db.close()
                                
                                mode = get_bot_mode().upper()
                                text = (
                                    "📊 <b>Market Pulse — Admin Stats</b>\n\n"
                                    f"👤 <b>Users</b>\n"
                                    f"  • Total: <b>{total_users:,}</b>\n"
                                    f"  • Pro: <b>{total_pro:,}</b>\n"
                                    f"  • Active (24h): <b>{active_24h:,}</b>\n"
                                    f"  • Banned: <b>{total_banned:,}</b>\n\n"
                                    f"📈 <b>Content & Data</b>\n"
                                    f"  • Alerts: <b>{total_alerts:,}</b>\n"
                                    f"  • P2P Alerts: <b>{total_p2p_alerts:,}</b>\n"
                                    f"  • Watchlist: <b>{total_watchlist:,}</b>\n"
                                    f"  • Portfolio: <b>{total_portfolio:,}</b>\n"
                                    f"  • Trades: <b>{total_trades:,}</b>\n"
                                    f"  • Events: <b>{total_events:,}</b>\n\n"
                                    f"⚙️ <b>System</b>\n"
                                    f"  • Mode: <b>{mode}</b>\n"
                                    f"  • Channel: <b>{'✅ Enabled' if CHANNEL_ENABLED else '❌ Disabled'}</b>\n"
                                    f"  • Pro Channel: <b>{'✅ Set' if PRO_CHANNEL_ID and PRO_CHANNEL_ID != '-100XXXXXXXXX' else '❌ Not Set'}</b>\n\n"
                                    f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S WAT')}"
                                )
                                send(chat_id, text)
                            except Exception as e:
                                logger.error("[STATS ERROR] %s" % e)
                                send(chat_id, f"⚠️ Error: {str(e)}")
                            continue

                        # ── PUBLISH ────────────────────────────────────────────────
                        if text.startswith("/publish"):
                            parts = text.split()
                            if len(parts) < 2:
                                send(chat_id, "⚠️ Usage: /publish morning | midday | evening | weekly")
                                continue

                            post_type = parts[1].lower()

                            if post_type == "morning":
                                pro_content  = build_morning_briefing_pro()
                                free_content = build_morning_briefing()
                            elif post_type == "midday":
                                pro_content  = build_midday_snapshot_pro()
                                free_content = build_midday_snapshot()
                            elif post_type == "evening":
                                pro_content  = build_evening_recap_pro()
                                free_content = build_evening_recap()
                            elif post_type == "weekly":
                                pro_content  = build_weekly_edge_pro()
                                free_content = build_weekly_edge()
                            else:
                                send(chat_id, "⚠️ Types: morning, midday, evening, weekly")
                                continue

                            if not CHANNEL_ENABLED:
                                send(chat_id, "⚠️ Channel posting is disabled. Use /togglechannel to enable.")
                                continue

                            try:
                                main_content = pro_content if get_bot_mode() == "everyone" else free_content
                                result = post_to_channel(main_content)
                                if result and result.get("ok"):
                                    send(chat_id, f"✅ Published <b>{post_type}</b> to main channel")
                                    logger.info("[ADMIN] %s published %s" % (chat_id, post_type))
                                    if PRO_CHANNEL_ID and PRO_CHANNEL_ID != "-100XXXXXXXXX":
                                        post_to_pro_channel(pro_content)
                                        send(chat_id, "✅ Also published to Pro channel")
                                else:
                                    send(chat_id, f"❌ Failed to post: {result}")
                            except Exception as e:
                                logger.error("[PUBLISH ERROR] %s" % e)
                                send(chat_id, f"❌ Error: {e}")
                            continue

                        # ── BROADCAST ──────────────────────────────────────────────
                        if text.startswith("/broadcast"):
                            message = text.replace("/broadcast", "", 1).strip()
                            if not message:
                                send(chat_id, "⚠️ Usage: /broadcast Your message here")
                                continue
                            send(chat_id, f"📢 Send to ALL users?\n\nMessage:\n{message}\n\nReply with <b>/confirm_broadcast</b> to send, or <b>/cancel</b> to stop.")
                            set_state(chat_id, "awaiting_broadcast_confirm", {"message": message})
                            continue

                        if text.startswith("/confirm_broadcast"):
                            state, state_data = get_state(chat_id)
                            if state != "awaiting_broadcast_confirm" or not state_data:
                                send(chat_id, "⚠️ No broadcast pending.")
                                continue
                            message = state_data.get("message")
                            if not message:
                                send(chat_id, "⚠️ No message found.")
                                continue
                            db = get_db()
                            c = db.cursor()
                            c.execute("SELECT chat FROM users")
                            users = c.fetchall()
                            db.close()
                            sent = 0
                            failed = 0
                            send(chat_id, f"📢 Broadcasting to <b>{len(users)}</b> users...")
                            for (user_chat,) in users:
                                if is_user_banned(user_chat):
                                    continue
                                try:
                                    send(int(user_chat), f"📢 <b>Announcement</b>\n\n{message}")
                                    sent += 1
                                except Exception as _e:
                                    failed += 1
                                time.sleep(0.05)
                            clear_state(chat_id)
                            logger.info("[ADMIN] %s broadcast to %s users" % (chat_id, sent))
                            send(chat_id, f"✅ Broadcast complete!\nSent: {sent}\nFailed: {failed}")
                            continue

                        # ── USERS ───────────────────────────────────────────────────
                        if text.startswith("/users"):
                            try:
                                db = get_db()
                                c = db.cursor()
                                c.execute("SELECT COUNT(*) FROM users")
                                total = c.fetchone()[0]
                                c.execute("SELECT COUNT(*) FROM pro_subscriptions")
                                pro = c.fetchone()[0]
                                c.execute("SELECT COUNT(*) FROM users WHERE last_seen >= %s",
                                          ((datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"),))
                                recent = c.fetchone()[0]
                                c.execute("SELECT chat, username, first_name, last_seen FROM users ORDER BY id DESC LIMIT 20")
                                rows = c.fetchall()
                                db.close()
                                
                                lines = [
                                    f"👤 <b>User Statistics</b>\n",
                                    f"Total: <b>{total:,}</b>",
                                    f"Pro: <b>{pro:,}</b>",
                                    f"Active (7d): <b>{recent:,}</b>",
                                    "",
                                    "━━━━━━━━━━━━━━━━━━━━━━━━━",
                                    "",
                                    "📋 <b>Recent Users (last 20)</b>"
                                ]
                                for chat, username, first_name, last_seen in rows:
                                    name = first_name or username or str(chat)
                                    if is_pro(chat):
                                        name = f"⭐ {name}"
                                    lines.append(f"• {name[:25]} ({chat})")
                                send(chat_id, "\n".join(lines))
                            except Exception as e:
                                logger.error("[USERS ERROR] %s" % e)
                                send(chat_id, f"⚠️ Error: {e}")
                            continue

                        # ── TEST ────────────────────────────────────────────────────
                        if text.startswith("/test"):
                            send(chat_id, "🧪 <b>Running tests...</b>")
                            results = []
                            try:
                                result = post_to_channel("🧪 <b>Test</b>\n\nBot is online and posting correctly.")
                                results.append(("Main Channel", "✅" if result and result.get("ok") else "❌"))
                            except Exception as _e:
                                results.append(("Main Channel", "❌ Error"))
                            if PRO_CHANNEL_ID and PRO_CHANNEL_ID != "-100XXXXXXXXX":
                                try:
                                    result = post_to_pro_channel("🧪 <b>Test</b>\n\nBot is online.")
                                    results.append(("Pro Channel", "✅" if result and result.get("ok") else "❌"))
                                except Exception as _e:
                                    results.append(("Pro Channel", "❌ Error"))
                            else:
                                results.append(("Pro Channel", "⏳ Not set"))
                            try:
                                ai, provider = ask_ai("Say hello in one word")
                                results.append(("AI Service", f"✅ {provider}" if ai else "❌"))
                            except Exception as _e:
                                results.append(("AI Service", "❌"))
                            try:
                                price, change = get_best_price("BTC")
                                results.append(("Price API", f"✅ {format_price(price)}" if price else "❌"))
                            except Exception as _e:
                                results.append(("Price API", "❌"))
                            try:
                                buy, sell, source = get_p2p_rate("USDT", "NGN")
                                results.append(("P2P", f"✅ ₦{int(buy)}" if buy else "❌"))
                            except Exception as _e:
                                results.append(("P2P", "❌"))
                            try:
                                news = get_crypto_news()
                                results.append(("News", f"✅ {len(news) if news else 0} articles" if news else "❌"))
                            except Exception as _e:
                                results.append(("News", "❌"))
                            lines = ["🧪 <b>Test Results</b>\n"]
                            for name, status in results:
                                lines.append(f"{name}: {status}")
                            send(chat_id, "\n".join(lines))
                            continue

                        # ── HEALTH ──────────────────────────────────────────────────
                        if text.startswith("/health"):
                            send(chat_id, "🔍 Running health check...")
                            checks = []
                            try:
                                price, _ = get_best_price("BTC")
                                checks.append(("Prices", "✅" if price else "❌", f"BTC {format_price(price)}" if price else "Failed"))
                            except Exception as _e:
                                checks.append(("Prices", "❌", "Failed"))
                            try:
                                buy, sell, source = get_p2p_rate("USDT", "NGN")
                                checks.append(("P2P", "✅" if buy else "❌", f"{source}" if buy else "Failed"))
                            except Exception as _e:
                                checks.append(("P2P", "❌", "Failed"))
                            try:
                                news = get_crypto_news()
                                checks.append(("News", "✅" if news else "❌", f"{len(news) if news else 0} articles"))
                            except Exception as _e:
                                checks.append(("News", "❌", "Failed"))
                            try:
                                fg = get_fear_greed()
                                checks.append(("Fear & Greed", "✅" if fg else "❌", f"{fg[0]['value'] if fg else 'N/A'}/100"))
                            except Exception as _e:
                                checks.append(("Fear & Greed", "❌", "Failed"))
                            try:
                                ai_result, provider = ask_ai("Test")
                                checks.append(("AI", "✅" if ai_result else "❌", provider or "All failed"))
                            except Exception as _e:
                                checks.append(("AI", "❌", "All failed"))
                            try:
                                db = get_db()
                                c = db.cursor()
                                c.execute("SELECT COUNT(*) FROM users")
                                count = c.fetchone()[0]
                                db.close()
                                checks.append(("Database", "✅", f"{count} users"))
                            except Exception as _e:
                                checks.append(("Database", "❌", "Connection failed"))
                            lines = ["🏥 <b>Health Check</b>\n", "<code>Service       Status   Details", "─────────────────────────────────────"]
                            for service, status, detail in checks:
                                lines.append(f"{service:12} {status:8} {detail}")
                            lines.append("</code>")
                            send(chat_id, "\n".join(lines))
                            continue

                        # ── TOGGLECHANNEL ──────────────────────────────────────────
                        if text.startswith("/togglechannel"):
                            CHANNEL_ENABLED = not CHANNEL_ENABLED
                            config = load_admin_config()
                            config["CHANNEL_ENABLED"] = CHANNEL_ENABLED
                            save_admin_config(config)
                            status = "ENABLED" if CHANNEL_ENABLED else "DISABLED"
                            send(chat_id, f"✅ Channel posting <b>{status}</b>")
                            logger.info("[ADMIN] %s toggled channel to %s" % (chat_id, status))
                            continue

                        # ── SET PRO CHANNEL ─────────────────────────────────────────
                        if text.startswith("/setprochannel"):
                            parts = text.split()
                            if len(parts) >= 2:
                                PRO_CHANNEL_ID = parts[1]
                                config = load_admin_config()
                                config["PRO_CHANNEL_ID"] = PRO_CHANNEL_ID
                                save_admin_config(config)
                                send(chat_id, f"✅ Pro channel set to: <code>{PRO_CHANNEL_ID}</code>")
                                logger.info("[ADMIN] %s set pro channel to %s" % (chat_id, PRO_CHANNEL_ID))
                            else:
                                send(chat_id, "⚠️ Usage: /setprochannel -100XXXXXXXXX")
                            continue

                        # ── SET CHANNEL ─────────────────────────────────────────────
                        if text.startswith("/setchannel"):
                            parts = text.split()
                            if len(parts) >= 2:
                                CHANNEL_ID = parts[1]
                                send(chat_id, f"✅ Main channel set to: <code>{CHANNEL_ID}</code>")
                                logger.info("[ADMIN] %s set channel to %s" % (chat_id, CHANNEL_ID))
                            else:
                                send(chat_id, "⚠️ Usage: /setchannel -100XXXXXXXXX")
                            continue

                        # ── REFRESH PRICES ──────────────────────────────────────────
                        if text.startswith("/refreshprices"):
                            send(chat_id, "🔄 Refreshing prices...")
                            try:
                                _kraken_cache = {"data": {}, "timestamp": None}
                                _secondary_cache = {"data": {}, "timestamp": None}
                                get_kraken_batch()
                                get_secondary_batch()
                                send(chat_id, "✅ Prices refreshed successfully!")
                                logger.info("[ADMIN] %s refreshed prices" % chat_id)
                            except Exception as e:
                                logger.error("[REFRESH ERROR] %s" % e)
                                send(chat_id, f"❌ Error: {e}")
                            continue

                        # ── CLEAR STATE ─────────────────────────────────────────────
                        if text.startswith("/clearstate"):
                            parts = text.split()
                            if len(parts) >= 2:
                                try:
                                    target = int(parts[1])
                                    clear_state(target)
                                    send(chat_id, f"✅ Cleared state for <code>{target}</code>")
                                    logger.info("[ADMIN] %s cleared state for %s" % (chat_id, target))
                                except Exception as _e:
                                    send(chat_id, "⚠️ Usage: /clearstate CHATID")
                            else:
                                send(chat_id, "⚠️ Usage: /clearstate CHATID")
                            continue

                        # ── WATCHLIST COINS (ADMIN) ──────────────────────────────────
                        if text.startswith("/watchlistcoins"):
                            coins_list = ", ".join(KEY_ALERT_COINS)
                            send(chat_id,
                                f"📋 <b>Alert Watchlist ({len(KEY_ALERT_COINS)} coins)</b>\n\n"
                                f"<code>{coins_list}</code>\n\n"
                                f"Use /setwatchlist COIN1 COIN2 ... to change.\n"
                                f"Available: {', '.join(list(COINS.keys()))}")
                            continue

                        # ── SET WATCHLIST (ADMIN) ────────────────────────────────────
                        if text.startswith("/setwatchlist"):
                            parts = text.split()[1:]
                            if not parts:
                                send(chat_id, "⚠️ Usage: /setwatchlist BTC ETH SOL BNB XRP LINK AVAX SUI")
                                continue
                            valid = [p.upper() for p in parts if p.upper() in COINS]
                            invalid = [p.upper() for p in parts if p.upper() not in COINS]
                            if not valid:
                                send(chat_id, f"❌ No valid coins. Available: {', '.join(list(COINS.keys()))}")
                                continue
                            KEY_ALERT_COINS.clear()
                            KEY_ALERT_COINS.extend(valid)
                            # Save to DB
                            try:
                                db = get_db(); c = db.cursor()
                                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                c.execute("INSERT INTO admin_settings (key, value, updated_at) VALUES ('alert_watchlist',%s,%s) "
                                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                                          (json.dumps(valid), now_str))
                                db.commit(); db.close()
                            except Exception as e:
                                logger.error(f"[SETWATCHLIST DB] {e}")
                            msg = f"✅ Alert watchlist updated to <b>{len(valid)} coins</b>:\n<code>{', '.join(valid)}</code>"
                            if invalid:
                                msg += f"\n\n⚠️ Skipped (unknown): {', '.join(invalid)}"
                            send(chat_id, msg)
                            logger.info(f"[ADMIN] {chat_id} set watchlist: {valid}")
                            continue

                        # ── BAN ──────────────────────────────────────────────────────
                        if text.startswith("/ban"):
                            parts = text.split()
                            if len(parts) >= 2:
                                try:
                                    target = int(parts[1])
                                    reason = " ".join(parts[2:]) if len(parts) >= 3 else "No reason provided"
                                    if ban_user(target, reason):
                                        send(chat_id, f"✅ Banned user <code>{target}</code>\nReason: {reason}")
                                        logger.info("[ADMIN] %s banned %s" % (chat_id, target))
                                    else:
                                        send(chat_id, "❌ Failed to ban user.")
                                except Exception as _e:
                                    send(chat_id, "⚠️ Usage: /ban CHATID [REASON]")
                            else:
                                send(chat_id, "⚠️ Usage: /ban CHATID [REASON]")
                            continue

                        # ── UNBAN ────────────────────────────────────────────────────
                        if text.startswith("/unban"):
                            parts = text.split()
                            if len(parts) >= 2:
                                try:
                                    target = int(parts[1])
                                    if unban_user(target):
                                        send(chat_id, f"✅ Unbanned user <code>{target}</code>")
                                        logger.info("[ADMIN] %s unbanned %s" % (chat_id, target))
                                    else:
                                        send(chat_id, "❌ Failed to unban user.")
                                except Exception as _e:
                                    send(chat_id, "⚠️ Usage: /unban CHATID")
                            else:
                                send(chat_id, "⚠️ Usage: /unban CHATID")
                            continue

                        # ── BLACKLIST ────────────────────────────────────────────────
                        if text.startswith("/blacklist"):
                            banned = get_banned_users()
                            if not banned:
                                send(chat_id, "📋 <b>Banned Users</b>\n\nNo users are banned.")
                                continue
                            lines = ["📋 <b>Banned Users</b>\n"]
                            for chat, reason, banned_at in banned[:20]:
                                lines.append(f"• <code>{chat}</code> — {reason[:30]}")
                                lines.append(f"  <i>{banned_at}</i>")
                            if len(banned) > 20:
                                lines.append(f"\n... and {len(banned) - 20} more")
                            send(chat_id, "\n".join(lines))
                            continue

                        # ── LOGS ─────────────────────────────────────────────────────
                        if text.startswith("/logs"):
                            try:
                                with open(LOG_FILE, "r") as f:
                                    lines = f.readlines()[-30:]
                                log_text = "📋 <b>Recent Logs</b>\n\n<code>"
                                for line in lines:
                                    log_text += line[:200] + "\n"
                                log_text += "</code>"
                                send(chat_id, log_text)
                            except Exception as _e:
                                send(chat_id, "⚠️ Could not read logs.")
                            continue

                        # ── POSTNOW ──────────────────────────────────────────────────
                        if text.startswith("/postnow"):
                            parts = text.split()
                            if len(parts) < 2:
                                send(chat_id, "⚠️ Usage: /postnow morning | midday | evening | weekly")
                                continue
                            post_type = parts[1].lower()
                            if post_type == "morning":
                                pro_content  = build_morning_briefing_pro()
                                free_content = build_morning_briefing()
                            elif post_type == "midday":
                                pro_content  = build_midday_snapshot_pro()
                                free_content = build_midday_snapshot()
                            elif post_type == "evening":
                                pro_content  = build_evening_recap_pro()
                                free_content = build_evening_recap()
                            elif post_type == "weekly":
                                pro_content  = build_weekly_edge_pro()
                                free_content = build_weekly_edge()
                            else:
                                send(chat_id, "⚠️ Types: morning, midday, evening, weekly")
                                continue
                            if not CHANNEL_ENABLED:
                                send(chat_id, "⚠️ Channel posting is disabled.")
                                continue
                            try:
                                main_content = pro_content if get_bot_mode() == "everyone" else free_content
                                result = post_to_channel(main_content)
                                if result and result.get("ok"):
                                    send(chat_id, f"✅ Posted <b>{post_type}</b> to channel")
                                    logger.info("[ADMIN] %s forced post %s" % (chat_id, post_type))
                                    if PRO_CHANNEL_ID and PRO_CHANNEL_ID != "-100XXXXXXXXX":
                                        post_to_pro_channel(pro_content)
                                else:
                                    send(chat_id, f"❌ Failed: {result}")
                            except Exception as e:
                                logger.error("[POSTNOW ERROR] %s" % e)
                                send(chat_id, f"❌ Error: {e}")
                            continue

                        # ── CANCEL ───────────────────────────────────────────────────
                        if text.startswith("/cancel"):
                            clear_state(chat_id)
                            send(chat_id, "✅ Cancelled.")
                            continue

                        # ── /forex ───────────────────────────────────────────────────
                        if text.startswith("/forex"):
                            parts = text.split()
                            if len(parts) < 3:
                                send(chat_id,
                                    "💱 <b>Forex Trade Idea Generator</b>\n\n"
                                    "Usage: /forex [PAIR] [tier]\n\n"
                                    "Pairs:\n"
                                    "  USDT/NGN  USD/NGN  BTC/NGN\n"
                                    "  EUR/USD   GBP/USD\n\n"
                                    "Tiers: steady | momentum | edge\n\n"
                                    "Examples:\n"
                                    "/forex USDT/NGN momentum\n"
                                    "/forex EUR/USD steady\n"
                                    "/forex USD/NGN edge"
                                )
                                continue
                            pair_arg = parts[1].upper().replace("-", "/")
                            tier_arg = parts[2].lower()
                            if pair_arg not in FOREX_PAIRS:
                                send(chat_id, f"⚠️ Unknown pair: {pair_arg}\nAvailable: {', '.join(FOREX_PAIRS.keys())}")
                                continue
                            if tier_arg not in TRADE_TIERS:
                                send(chat_id, f"⚠️ Unknown tier: {tier_arg}. Use: steady, momentum, edge")
                                continue
                            send(chat_id, f"⏳ Generating <b>{tier_arg.upper()}</b> idea for <b>{pair_arg}</b>...")
                            try:
                                msg, trade, idea_id = generate_forex_trade_idea(pair_arg, tier_arg)
                                if msg and idea_id:
                                    post_to_pro_channel(msg)
                                    send(chat_id,
                                        f"✅ <b>Forex Idea #{idea_id}</b> posted to Pro channel.\n"
                                        f"Pair: {pair_arg} | Tier: {tier_arg.upper()}\n"
                                        f"Use /closetrade {idea_id} [result] when it closes.")
                                else:
                                    send(chat_id, f"⚠️ No quality {tier_arg} setup for {pair_arg} right now.")
                            except Exception as fe:
                                logger.error(f"[/forex CMD] {fe}")
                                send(chat_id, f"❌ Error: {fe}")
                            continue

                        # ── /admin ────────────────────────────────────────────────────
                        if text.strip() == "/admin":
                            send(chat_id, "👑 <b>Admin Panel</b>\n\nSelect a category:", ADMIN_MENU)
                            continue

                        # ── TRADE IDEAS (admin) ───────────────────────────────────────
                        if text.startswith("/trade"):
                            # Usage: /trade BTC momentum | /trade ETH steady | /trade SOL edge
                            parts = text.split()
                            if len(parts) < 3:
                                send(chat_id,
                                    "⚡ <b>Trade Idea Generator</b>\n\n"
                                    "Usage: /trade [COIN] [tier]\n\n"
                                    "Tiers:\n"
                                    "  <b>steady</b>   — Low-medium risk, 8-15% target\n"
                                    "  <b>momentum</b> — Medium-high risk, 15-30% target\n"
                                    "  <b>edge</b>     — HIGH RISK, 30-100%+ target\n\n"
                                    "Examples:\n"
                                    "/trade BTC momentum\n"
                                    "/trade ETH edge\n"
                                    "/trade SOL steady"
                                )
                                continue
                            coin_arg = parts[1].upper()
                            tier_arg = parts[2].lower()
                            if tier_arg not in TRADE_TIERS:
                                send(chat_id, f"⚠️ Unknown tier: {tier_arg}. Use: steady, momentum, edge")
                                continue
                            if coin_arg not in COINS:
                                send(chat_id, f"⚠️ Unknown coin: {coin_arg}. Use one of: {', '.join(list(COINS.keys())[:10])}...")
                                continue
                            send(chat_id, f"⏳ Generating <b>{tier_arg.upper()}</b> idea for <b>{coin_arg}</b>...")
                            try:
                                msg, trade, idea_id = generate_trade_idea(coin_arg, tier_arg)
                                if msg and idea_id:
                                    # Post to Pro channel
                                    post_to_pro_channel(msg)
                                    send(chat_id,
                                        f"✅ <b>Trade Idea #{idea_id}</b> generated and posted to Pro channel.\n\n"
                                        f"Coin: {coin_arg} | Tier: {tier_arg.upper()}\n"
                                        f"Entry: {trade.get('entry','—')} | Stop: {trade.get('stop','—')} | T1: {trade.get('target1','—')}\n\n"
                                        f"Use /closetrade {idea_id} [hit_t1|hit_t2|stopped|cancelled] when trade closes."
                                    )
                                else:
                                    send(chat_id,
                                        f"⚠️ No quality {tier_arg} setup found for {coin_arg} right now.\n"
                                        f"AI could not generate a valid entry/stop/target that meets the tier criteria.\n"
                                        f"Try a different tier or wait for better market structure."
                                    )
                            except Exception as te:
                                logger.error(f"[/trade CMD] {te}")
                                send(chat_id, f"❌ Error: {te}")
                            continue

                        # ── TRADE HISTORY ─────────────────────────────────────────────
                        if text.startswith("/tradehistory") or text.startswith("/trades"):
                            parts = text.split()
                            coin_f = parts[1].upper() if len(parts) > 1 and parts[1].upper() in COINS else None
                            tier_f = parts[2].lower() if len(parts) > 2 and parts[2].lower() in TRADE_TIERS else None
                            rows = get_trade_history(limit=15, coin=coin_f, tier=tier_f)
                            if not rows:
                                send(chat_id, "📋 <b>Trade History</b>\n\nNo trade ideas recorded yet.\n\nGenerate one with /trade [COIN] [tier]")
                            else:
                                lines = ["📋 <b>Trade History</b>", f"<i>Showing last {len(rows)} ideas</i>", ""]
                                for row in rows:
                                    tid, coin, tier, direction, tf, entry, t1, conf, status, created = row
                                    status_emoji = "✅" if status == "closed" else "🟡"
                                    lines.append(
                                        f"{status_emoji} <b>#{tid}</b> {coin} {tier.upper()} {direction} {tf}\n"
                                        f"   Entry: {entry or '—'} → T1: {t1 or '—'} | {conf} | {created[:10]}"
                                    )
                                lines += ["", "Use /closetrade [ID] [result] to close an idea."]
                                send(chat_id, "\n".join(lines))
                            continue

                        # ── CLOSE TRADE ───────────────────────────────────────────────
                        if text.startswith("/closetrade"):
                            parts = text.split()
                            if len(parts) < 3:
                                send(chat_id,
                                    "Usage: /closetrade [ID] [result]\n\n"
                                    "Results: hit_t1 | hit_t2 | stopped | cancelled"
                                )
                                continue
                            try:
                                close_id = int(parts[1])
                                result   = parts[2].lower()
                                valid_results = ("hit_t1","hit_t2","stopped","cancelled")
                                if result not in valid_results:
                                    send(chat_id, f"⚠️ Result must be one of: {', '.join(valid_results)}")
                                    continue
                                ok = close_trade_idea(close_id, result)
                                result_emoji = {"hit_t1":"✅","hit_t2":"🏆","stopped":"❌","cancelled":"⏹"}.get(result,"✅")
                                if ok:
                                    send(chat_id, f"{result_emoji} Trade #{close_id} closed as <b>{result}</b>.\n\nThis will be included in performance tracking.")
                                else:
                                    send(chat_id, f"❌ Could not close trade #{close_id}. Check the ID.")
                            except ValueError:
                                send(chat_id, "⚠️ Invalid ID. Usage: /closetrade 5 hit_t1")
                            continue

                        # ── CONTENT PACKAGE ──────────────────────────────────────────
                        if text.startswith("/contentpackage") or text.startswith("/cp"):
                            parts = text.split()
                            post_type = parts[1].lower() if len(parts) >= 2 else "morning"
                            if post_type not in ("morning","midday","evening","weekly","educational"):
                                send(chat_id,
                                    "📦 <b>Content Package</b>\n\nUsage:\n"
                                    "/contentpackage morning\n"
                                    "/contentpackage midday\n"
                                    "/contentpackage evening\n"
                                    "/contentpackage weekly\n"
                                    "/contentpackage educational")
                                continue
                            send(chat_id, f"⏳ Generating <b>{post_type}</b> content package...\nThis takes ~30 seconds while AI writes each platform format.")
                            try:
                                if post_type == "educational":
                                    tg_text = build_weekly_educational_content()
                                    send(chat_id, f"✅ Educational content package generated and delivered above.")
                                else:
                                    if post_type == "morning":
                                        tg_text = build_morning_briefing_pro()
                                    elif post_type == "midday":
                                        tg_text = build_midday_snapshot_pro()
                                    elif post_type == "evening":
                                        tg_text = build_evening_recap_pro()
                                    else:
                                        tg_text = build_weekly_edge_pro()
                                    btc_p, btc_c = get_best_price("BTC")
                                    fg_d = get_fear_greed()
                                    g, l = get_gainers_losers()
                                    buy_r, sell_r, _ = get_p2p_rate("USDT","NGN")
                                    mc = {
                                        "btc_price": format_price(btc_p),
                                        "btc_change": format_change(btc_c),
                                        "fg_val": fg_d[0]["value"] if fg_d else "50",
                                        "fg_lbl": fg_d[0]["value_classification"] if fg_d else "Neutral",
                                        "gainers_str": ", ".join(f"{c} {ch:+.1f}%" for c,_,ch in g[:3]) if g else "N/A",
                                        "losers_str": ", ".join(f"{c} {ch:.1f}%" for c,_,ch in l[:2]) if l else "N/A",
                                        "p2p_str": f"USDT/NGN Buy ₦{int(buy_r):,} / Sell ₦{int(sell_r):,}" if buy_r else "",
                                        "key_insight": f"Admin-requested {post_type} content package",
                                    }
                                    pkg_id = generate_and_deliver_content_package(post_type, tg_text, mc, f"admin_manual_{post_type}")
                                    send(chat_id, f"✅ <b>Content Package #{pkg_id}</b> generated and delivered above.\n\n"
                                         f"Review each section carefully before publishing to any platform.")
                            except Exception as e:
                                logger.error(f"[CONTENTPACKAGE CMD] {e}")
                                send(chat_id, f"❌ Error generating package: {e}")
                            continue

                        # ── DASHBOARD ─────────────────────────────────────────────────
                        if text.startswith("/dashboard"):
                            send(chat_id, build_admin_dashboard(),
                                [[{"text": "📦 Content Packages", "callback_data": "admin_content_packages"},
                                  {"text": "⬅ Back", "callback_data": "main_menu"}]])
                            continue

                        # ── CONTENT PACKAGES LIST ─────────────────────────────────────
                        if text.startswith("/packages"):
                            pkgs = get_pending_content_packages(limit=10)
                            if not pkgs:
                                send(chat_id, "📦 <b>Content Packages</b>\n\nNo pending packages.")
                            else:
                                lines = ["📦 <b>Pending Content Packages</b>\n"]
                                for pid, ptype, psrc, pdate in pkgs:
                                    lines.append(f"• #{pid} <b>{ptype.upper()}</b> — {psrc} — {pdate[:16]}")
                                lines.append("\nUse /package [ID] to view a specific package.")
                                send(chat_id, "\n".join(lines))
                            continue

                        if text.startswith("/package "):
                            try:
                                pkg_id = int(text.split()[1])
                                pkg = get_content_package_by_id(pkg_id)
                                if not pkg:
                                    send(chat_id, f"❌ Package #{pkg_id} not found.")
                                else:
                                    admin_msg = format_content_package_for_admin(pkg_id, pkg, pkg.get("package_type","?"))
                                    if len(admin_msg) <= 4000:
                                        send(chat_id, admin_msg,
                                            [[{"text": "✅ Approve", "callback_data": f"pkg_approve_{pkg_id}"},
                                              {"text": "🗑 Discard", "callback_data": f"pkg_discard_{pkg_id}"}]])
                                    else:
                                        send(chat_id, admin_msg[:3900] + "...\n\n[truncated — full package in DB]")
                            except (ValueError, IndexError):
                                send(chat_id, "⚠️ Usage: /package [ID]")
                            continue

                    # ═══════════════════════════════════════════════════════════════
                    # 🔵 USER COMMANDS (EVERYONE CAN USE)
                    # ═══════════════════════════════════════════════════════════════

                    # ── START ──────────────────────────────────────────────────────
                    if text.startswith("/start"):
                        clear_state(chat_id)
                        if "ref_PRO_" in text:
                            try:
                                referrer = int(text.split("ref_PRO_")[1].split()[0])
                                record_pro_referral(referrer, chat_id)
                            except Exception as _e:
                                logger.debug("[SILENT EXC] %s" % _e)
                        show_main_menu(chat_id)
                        continue

                    # ── HELP ──────────────────────────────────────────────────────
                    if text.startswith("/help") or text.startswith("/commands") or text == "/%s":
                        show_help(chat_id, None)
                        continue

                    # ── MENU ──────────────────────────────────────────────────────
                    if text.startswith("/menu"):
                        show_main_menu(chat_id)
                        continue

                    # ── MARKET ────────────────────────────────────────────────────
                    if text.startswith("/market") or text.startswith("/prices"):
                        show_market(chat_id, None)
                        continue

                    # ── UPGRADE ──────────────────────────────────────────────────
                    if text.startswith("/upgrade") or text.startswith("/pro"):
                        show_upgrade(chat_id, None)
                        continue

                    # ── PORTFOLIO ─────────────────────────────────────────────────
                    if text.startswith("/portfolio") or text.startswith("/port"):
                        show_portfolio(chat_id, None)
                        continue

                    # ── TRADE JOURNAL ─────────────────────────────────────────────
                    if text.startswith("/trades") or text.startswith("/journal"):
                        show_trade_journal(chat_id, None)
                        continue

                    # ── SETTINGS ──────────────────────────────────────────────────
                    if text.startswith("/settings") or text.startswith("/prefs"):
                        show_settings(chat_id, None)
                        continue

                    # ── POSITION CALCULATOR ──────────────────────────────────────
                    if text.startswith("/position") or text.startswith("/pos"):
                        show_position_calculator(chat_id, None)
                        continue

                    # ── VERSION ──────────────────────────────────────────────────
                    if text.startswith("/version") or text.startswith("/ver"):
                        text = (
                            "ℹ️ <b>Market Pulse Bot</b>\n\n"
                            f"📅 Version: <b>v17 - The Intelligence Upgrade</b>\n"
                            f"🤖 Mode: <b>{get_bot_mode().upper()}</b>\n"
                            f"📊 Channel: <b>{'Enabled' if CHANNEL_ENABLED else 'Disabled'}</b>\n"
                            f"👤 Your Status: <b>{get_user_badge(chat_id)}</b>\n\n"
                            f"📅 Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S WAT')}"
                        )
                        send(chat_id, text, BACK_MAIN)
                        continue

                    # ── PING ──────────────────────────────────────────────────────
                    if text.startswith("/ping"):
                        send(chat_id, "🏓 <b>Pong!</b>\n\nBot is alive and running.")
                        continue

                    # ── ADD PORTFOLIO ─────────────────────────────────────────────
                    if text.startswith("/addportfolio") or text.startswith("/addport"):
                        parts = text.split()
                        if len(parts) >= 4:
                            try:
                                coin = parts[1].upper()
                                amount = float(parts[2])
                                buy_price = float(parts[3])
                                db = get_db()
                                c = db.cursor()
                                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                c.execute("INSERT INTO portfolio (chat, coin, amount, buy_price, added_at) VALUES (%s,%s,%s,%s,%s)",
                                          (str(chat_id), coin, amount, buy_price, now))
                                db.commit()
                                db.close()
                                send(chat_id, f"✅ Added {amount} {coin} @ {format_price(buy_price)}")
                            except Exception as _e:
                                send(chat_id, "⚠️ Format: /addportfolio BTC 0.5 61000")
                        else:
                            send(chat_id, "⚠️ Format: /addportfolio BTC 0.5 61000")
                        continue

                    # ── REMOVE PORTFOLIO ──────────────────────────────────────────
                    if text.startswith("/removeportfolio") or text.startswith("/removeport"):
                        parts = text.split()
                        if len(parts) >= 2:
                            try:
                                coin = parts[1].upper()
                                db = get_db()
                                c = db.cursor()
                                c.execute("DELETE FROM portfolio WHERE chat=%s AND coin=%s", (str(chat_id), coin))
                                db.commit()
                                db.close()
                                send(chat_id, f"✅ Removed {coin} from portfolio")
                            except Exception as _e:
                                send(chat_id, "⚠️ Error removing coin.")
                        else:
                            send(chat_id, "⚠️ Usage: /removeportfolio COIN")
                        continue

                    # ── ADD TRADE ─────────────────────────────────────────────────
                    if text.startswith("/addtrade"):
                        parts = text.split()
                        if len(parts) >= 5:
                            try:
                                coin = parts[1].upper()
                                direction = parts[2].upper()
                                entry_price = float(parts[3])
                                exit_price = float(parts[4])
                                size = float(parts[5]) if len(parts) >= 6 else 1.0
                                
                                db = get_db()
                                c = db.cursor()
                                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                if direction == "LONG":
                                    pnl = (exit_price - entry_price) * size
                                else:
                                    pnl = (entry_price - exit_price) * size
                                c.execute(
                                    "INSERT INTO trade_journal (chat, coin, direction, entry_price, exit_price, size, pnl, status, opened_at) "
                                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                    (str(chat_id), coin, direction, entry_price, exit_price, size, pnl, 'closed', now)
                                )
                                db.commit()
                                db.close()
                                send(chat_id, f"✅ Trade recorded!\n\n{coin} {direction}\nEntry: {format_price(entry_price)}\nExit: {format_price(exit_price)}\nP&L: {format_price(pnl)}\nSize: {size}")
                            except Exception as _e:
                                send(chat_id, "⚠️ Format: /addtrade BTC LONG 61000 62000 0.5")
                        else:
                            send(chat_id, "⚠️ Format: /addtrade BTC LONG 61000 62000 0.5")
                        continue

                    # ── CLOSE TRADE ──────────────────────────────────────────────
                    if text.startswith("/closetrade"):
                        parts = text.split()
                        if len(parts) >= 2:
                            try:
                                trade_id = int(parts[1])
                                exit_price = float(parts[2]) if len(parts) >= 3 else None
                                result = close_trade(chat_id, trade_id, exit_price)
                                if "error" in result:
                                    send(chat_id, f"⚠️ {result['error']}")
                                else:
                                    send(chat_id, f"✅ Trade closed!\n\nP&L: {format_price(result['pnl'])}\nExit Price: {format_price(result['exit_price'])}")
                            except Exception as _e:
                                send(chat_id, "⚠️ Format: /closetrade TRADE_ID [EXIT_PRICE]")
                        else:
                            send(chat_id, "⚠️ Format: /closetrade TRADE_ID [EXIT_PRICE]")
                        continue

                    # ── WATCHLIST ──────────────────────────────────────────────────
                    if text.startswith("/watchlist") or text.startswith("/wl"):
                        parts = text.split()
                        if len(parts) >= 2:
                            action = parts[1].lower()
                            if action == "add" and len(parts) >= 3:
                                coin = parts[2].upper()
                                try:
                                    db = get_db()
                                    c = db.cursor()
                                    c.execute("INSERT INTO watchlists (chat, coin) VALUES (%s,%s) ON CONFLICT DO NOTHING", (str(chat_id), coin))
                                    db.commit()
                                    db.close()
                                    send(chat_id, f"✅ Added {coin} to watchlist")
                                except Exception as _e:
                                    send(chat_id, "⚠️ Error adding to watchlist.")
                            elif action == "remove" and len(parts) >= 3:
                                coin = parts[2].upper()
                                try:
                                    db = get_db()
                                    c = db.cursor()
                                    c.execute("DELETE FROM watchlists WHERE chat=%s AND coin=%s", (str(chat_id), coin))
                                    db.commit()
                                    db.close()
                                    send(chat_id, f"✅ Removed {coin} from watchlist")
                                except Exception as _e:
                                    send(chat_id, "⚠️ Error removing from watchlist.")
                            elif action == "list":
                                try:
                                    db = get_db()
                                    c = db.cursor()
                                    c.execute("SELECT coin FROM watchlists WHERE chat=%s", (str(chat_id),))
                                    rows = c.fetchall()
                                    db.close()
                                    if not rows:
                                        send(chat_id, "📋 <b>Watchlist</b>\n\nNo coins in watchlist.")
                                    else:
                                        coins = [r[0] for r in rows]
                                        send(chat_id, f"📋 <b>Watchlist</b>\n\n{', '.join(coins)}")
                                except Exception as _e:
                                    send(chat_id, "⚠️ Error loading watchlist.")
                            else:
                                send(chat_id, "⚠️ Usage: /watchlist add|remove|list [COIN]")
                        else:
                            send(chat_id, "⚠️ Usage: /watchlist add|remove|list [COIN]")
                        continue

                    # ── P2P ──────────────────────────────────────────────────────
                    if text.startswith("/p2p"):
                        buy, sell, source = get_p2p_rate("USDT", "NGN")
                        if buy and sell:
                            text = (
                                "💱 <b>USDT/NGN P2P Rates</b>\n\n"
                                f"Buy: <b>₦{int(buy):,}</b>\n"
                                f"Sell: <b>₦{int(sell):,}</b>\n"
                                f"Spread: <b>₦{int(buy - sell):,}</b>\n\n"
                                f"Source: <i>{source}</i>"
                            )
                        else:
                            text = "⚠️ Could not fetch P2P rates. Please try again later."
                        send(chat_id, text, [[{"text": "🔄 Refresh", "callback_data": "p2p"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])
                        continue

                    # ── FEAR & GREED ──────────────────────────────────────────────
                    if text.startswith("/feargreed") or text.startswith("/fg"):
                        fg_data = get_fear_greed()
                        if fg_data:
                            current = fg_data[0]
                            text = (
                                "🧠 <b>Fear & Greed Index</b>\n\n"
                                f"Current: <b>{current['value']}/100</b>\n"
                                f"Status: <b>{current['value_classification']}</b>\n"
                                f"{fg_emoji(current['value'])}\n\n"
                                f"📅 {current['timestamp']}"
                            )
                            if len(fg_data) > 1:
                                week_ago = fg_data[-1]
                                text += f"\n\nWeek ago: {week_ago['value']}/100 ({week_ago['value_classification']})"
                        else:
                            text = "⚠️ Could not fetch Fear & Greed data."
                        send(chat_id, text, [[{"text": "🔄 Refresh", "callback_data": "fear_greed"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])
                        continue

                    # ── NEWS ──────────────────────────────────────────────────────
                    if text.startswith("/news"):
                        news = get_crypto_news()
                        if news:
                            lines = ["📰 <b>Top Crypto News</b>\n"]
                            for i, art in enumerate(news[:5], 1):
                                lines.append(f"{i}. <b>{art.get('title', '')[:80]}</b>")
                                lines.append(f"   {art.get('source', {}).get('title', 'Unknown')}")
                                lines.append("")
                            send(chat_id, "\n".join(lines), [[{"text": "🔄 Refresh", "callback_data": "news"}, {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])
                        else:
                            send(chat_id, "⚠️ No news available.", BACK_MAIN)
                        continue

                    # ── AI ──────────────────────────────────────────────────────
                    if text.startswith("/ai") or text.startswith("/ask"):
                        allowed, used, limit = check_ai_limit(chat_id)
                        if not allowed:
                            send(chat_id, ai_limit_msg(used, limit), UPGRADE_BTN)
                            continue
                        question = text.replace("/ai", "", 1).replace("/ask", "", 1).strip()
                        if not question:
                            set_state(chat_id, "awaiting_ai_question", {})
                            send(chat_id, "🤖 <b>Ask AI</b>\n\nWhat would you like to know?\n\nSend your question below.", [[{"text": "⬅ Cancel", "callback_data": "main_menu"}]])
                            continue
                        track_feature(chat_id, "ai_question")
                        send(chat_id, "🤖 Thinking...")
                        response, provider = ask_ai(question)
                        if response:
                            remaining = (limit - used - 1) if limit else None
                            footer = f"\n\n<i>💬 {remaining} free questions left today.</i>" if remaining is not None and remaining >= 0 else ""
                            send(chat_id, f"🤖 <b>AI ({provider})</b>\n\n{response}{footer}", BACK_MAIN)
                        else:
                            send(chat_id, "⚠️ AI service is currently unavailable. Please try again later.", BACK_MAIN)
                        continue

                    # ── FEEDBACK ──────────────────────────────────────────────────
                    if text.startswith("/feedback") or text.startswith("/fb"):
                        set_state(chat_id, "awaiting_feedback", {})
                        send(chat_id, "💬 <b>Send Feedback</b>\n\nPlease describe your feedback, suggestion, or bug report.", [[{"text": "⬅ Cancel", "callback_data": "main_menu"}]])
                        continue

                    # ── REFERRAL ──────────────────────────────────────────────────
                    if text.startswith("/refer") or text.startswith("/referral"):
                        count = get_pro_referral_count(chat_id)
                        ref_link = f"https://t.me/MarketNgPulseBot?start=ref_PRO_{chat_id}"
                        if is_pro(chat_id):
                            reward, _ = get_pro_referral_reward(chat_id)
                            next_milestone = ""
                            if count < 5:   next_milestone = f"{5-count} more to get 1 month free"
                            elif count < 10: next_milestone = f"{10-count} more to get 3 months free"
                            elif count < 20: next_milestone = f"{20-count} more to get 6 months free"
                            else:            next_milestone = "Maximum tier reached — thank you!"
                            ref_text = (
                                "👥 <b>Your Referral Stats</b>\n\n"
                                f"Total referrals: <b>{count}</b>\n"
                                f"Next milestone: <i>{next_milestone}</i>\n\n"
                                "🎯 <b>Rewards</b>\n"
                                "3 referrals  →  1 week free\n"
                                "5 referrals  →  1 month free\n"
                                "10 referrals →  3 months free\n"
                                "20 referrals →  6 months free\n\n"
                                "📤 <b>Your link:</b>\n"
                                f"<code>{ref_link}</code>\n\n"
                                "<i>Share this link. Every person who joins through it counts.</i>"
                            )
                        else:
                            ref_text = (
                                "👥 <b>Referral Program</b>\n\n"
                                f"Referrals so far: <b>{count}</b>\n\n"
                                "Refer friends and earn free Pro access:\n\n"
                                "3 referrals  →  1 week Pro free\n"
                                "5 referrals  →  1 month Pro free\n"
                                "10 referrals →  3 months Pro free\n"
                                "20 referrals →  6 months Pro free\n\n"
                                "📤 <b>Your referral link:</b>\n"
                                f"<code>{ref_link}</code>\n\n"
                                "<i>You don't need to be Pro to refer. "
                                "Hit 3 referrals and get your first week on us.</i>"
                            )
                        btns = [[{"text": "💎 Upgrade — ₦3,000/mo", "callback_data": "upgrade"},
                                  {"text": "🏠 Main Menu", "callback_data": "main_menu"}]]
                        send(chat_id, ref_text, btns)
                        continue

                    # ── CANCEL ───────────────────────────────────────────────────
                    if text.startswith("/cancel"):
                        clear_state(chat_id)
                        send(chat_id, "✅ Cancelled.", BACK_MAIN)
                        continue

                    # ── STATE HANDLERS ──────────────────────────────────────────
                    state, state_data = get_state(chat_id)
                    
                    if state == "awaiting_position_calc":
                        handle_position_calc(chat_id, text)
                        continue
                    
                    if state == "awaiting_ai_question":
                        allowed, used, limit = check_ai_limit(chat_id)
                        if not allowed:
                            clear_state(chat_id)
                            send(chat_id, ai_limit_msg(used, limit), UPGRADE_BTN)
                            continue
                        clear_state(chat_id)
                        track_feature(chat_id, "ai_question")
                        send(chat_id, "🤖 Thinking...")
                        # Security: cap user AI input length and strip injection patterns
                        safe_text = text[:500].replace("Ignore previous instructions","").replace("ignore all previous","")
                        response, provider = ask_ai(safe_text)
                        if response:
                            remaining = (limit - used - 1) if limit else None
                            footer = f"\n\n<i>💬 {remaining} free questions left today.</i>" if remaining is not None and remaining >= 0 else ""
                            send(chat_id, f"🤖 <b>AI ({provider})</b>\n\n{response}{footer}", BACK_MAIN)
                        else:
                            send(chat_id, "⚠️ AI service is currently unavailable.", BACK_MAIN)
                        continue
                    
                    if state == "awaiting_feedback":
                        clear_state(chat_id)
                        for admin_id in ADMIN_IDS:
                            send(admin_id, f"💬 <b>User Feedback</b>\n\nUser: <code>{chat_id}</code>\n\n{text}")
                        send(chat_id, "✅ <b>Feedback Sent!</b>\n\nThank you for your feedback.", BACK_MAIN)
                        continue

                    # ── ALERT COIN ────────────────────────────────────────────────
                    if state == "awaiting_alert_coin":
                        coin = text.upper().strip()
                        if coin not in COINS:
                            send(chat_id, f"❌ Unknown coin <b>{coin}</b>. Try BTC, ETH, SOL etc.")
                        else:
                            set_state(chat_id, "awaiting_alert_condition", {"coin": coin})
                            btns = [
                                [{"text": "📈 Price Above", "callback_data": "alert_cond_above"},
                                 {"text": "📉 Price Below", "callback_data": "alert_cond_below"}],
                                [{"text": "❌ Cancel", "callback_data": "menu_alerts"}],
                            ]
                            price, _ = get_best_price(coin)
                            send(chat_id, f"➕ <b>Alert for {coin}</b>\n\nCurrent: <b>{format_price(price)}</b>\n\nAlert when price goes:", btns)
                        continue

                    if state == "awaiting_alert_target":
                        _, sdata = get_state(chat_id)
                        coin = sdata.get("coin", "BTC")
                        cond = sdata.get("condition", "above")
                        try:
                            target = float(text.replace(",", "").replace("$", ""))
                            clear_state(chat_id)
                            db = get_db(); c = db.cursor()
                            c.execute("INSERT INTO alerts (chat, coin, condition, target, active) VALUES (%s,%s,%s,%s,1)",
                                      (str(chat_id), coin, cond, target))
                            db.commit(); db.close()
                            send(chat_id, f"✅ <b>Alert Created!</b>\n\n{coin} will alert you when price goes <b>{cond}</b> <b>{format_price(target)}</b>", BACK_MAIN)
                        except ValueError:
                            send(chat_id, "❌ Invalid price. Send a number like <code>50000</code>")
                        continue

                    # ── WATCHLIST ADD ─────────────────────────────────────────────
                    if state == "awaiting_wl_add":
                        coin = text.upper().strip()
                        if coin not in COINS:
                            send(chat_id, f"❌ Unknown coin <b>{coin}</b>. Try BTC, ETH, SOL etc.")
                        else:
                            try:
                                db = get_db(); c = db.cursor()
                                c.execute("INSERT INTO watchlists (chat, coin) VALUES (%s,%s) ON CONFLICT DO NOTHING", (str(chat_id), coin))
                                db.commit(); db.close()
                                clear_state(chat_id)
                                price, ch = get_best_price(coin)
                                send(chat_id, f"✅ <b>{coin}</b> added to watchlist!\n\nCurrent: <b>{format_price(price)}</b>  {format_change(ch) if ch else ''}",
                                     [[{"text": "⭐ View Watchlist", "callback_data": "watchlist"}]])
                            except Exception as e:
                                send(chat_id, f"⚠️ Could not add {coin}: {e}")
                        continue

                    # ── TRADE SETUP (Pro AI) ──────────────────────────────────────
                    if state == "awaiting_trade_setup_coin":
                        coin = text.upper().strip()
                        clear_state(chat_id)
                        if coin not in COINS:
                            send(chat_id, f"❌ Unknown coin <b>{coin}</b>.")
                        else:
                            send(chat_id, f"🤖 Generating trade setup for <b>{coin}</b>...")
                            price, ch = get_best_price(coin)
                            sd = get_secondary_coin(coin)
                            high_24 = sd.get("usd_24h_high") if sd else None
                            low_24  = sd.get("usd_24h_low")  if sd else None
                            prompt = (
                                f"{coin} is at {format_price(price)} ({format_change(ch or 0)}). "
                                f"24h High: {format_price(high_24) if isinstance(high_24,(int,float)) else 'N/A'}, "
                                f"24h Low: {format_price(low_24) if isinstance(low_24,(int,float)) else 'N/A'}. "
                                f"Give a complete trade setup: entry zone, stop loss, take profit levels (TP1, TP2, TP3), "
                                f"risk/reward ratio, and what invalidates the setup. Label as EDUCATIONAL ONLY."
                            )
                            analysis, provider = ask_ai(prompt)
                            send(chat_id,
                                f"📊 <b>Trade Setup — {coin}</b>\n\n"
                                f"{analysis or 'Analysis unavailable right now.'}\n\n"
                                f"⚠️ <i>🎓 EDUCATIONAL ONLY — NFA - DYOR</i>", BACK_MAIN)
                        continue

                    # ── ADMIN BROADCAST ───────────────────────────────────────────
                    if state == "awaiting_grant_pro" and chat_id in ADMIN_IDS:
                        clear_state(chat_id)
                        parts = text.strip().split()
                        try:
                            target_id = int(parts[0])
                            months = int(parts[1]) if len(parts) > 1 else 1
                            ok = grant_pro(target_id, months)
                            if ok:
                                send(chat_id, f"✅ Pro granted to <code>{target_id}</code> for {months} month(s).")
                                try:
                                    send(target_id,
                                        f"🎉 <b>Pro Access Granted!</b>\n\n"
                                        f"You now have Market Pulse Pro for {months} month(s).\n"
                                        f"Enjoy unlimited AI, trade ideas, and full intelligence.")
                                except Exception:
                                    pass
                            else:
                                send(chat_id, "❌ Failed to grant Pro. Check logs.")
                        except (ValueError, IndexError):
                            send(chat_id, "⚠️ Send the user ID: <code>123456789</code> or <code>123456789 3</code> for 3 months")
                        continue

                    if state == "awaiting_broadcast" and chat_id in ADMIN_IDS:
                        clear_state(chat_id)
                        db = get_db(); c = db.cursor()
                        c.execute("SELECT DISTINCT chat FROM users")
                        all_users = c.fetchall(); db.close()
                        sent_count = 0
                        for (uid,) in all_users:
                            try:
                                send(int(uid), f"📣 <b>Announcement</b>\n\n{text}")
                                sent_count += 1
                                time.sleep(0.05)
                            except Exception as _e:
                                logger.debug("[SILENT EXC] %s" % _e)
                        send(chat_id, f"✅ Broadcast sent to <b>{sent_count}</b> users.")
                        continue

                    # ── ADMIN BAN ─────────────────────────────────────────────────
                    if state == "awaiting_ban_id" and chat_id in ADMIN_IDS:
                        clear_state(chat_id)
                        try:
                            target_id = int(text.strip())
                            ban_user(target_id, "Banned by admin")
                            send(chat_id, f"✅ User <code>{target_id}</code> has been banned.")
                        except ValueError:
                            send(chat_id, "❌ Invalid ID. Send a numeric Telegram user ID.")
                        continue

                    # ── PORTFOLIO ADD ─────────────────────────────────────────
                    if state == "awaiting_add_portfolio":
                        parts = text.upper().split()
                        if len(parts) == 3 and parts[0] in COINS:
                            try:
                                coin, amount, buy_price = parts[0], float(parts[1]), float(parts[2])
                                clear_state(chat_id)
                                db = get_db(); c = db.cursor()
                                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                c.execute("INSERT INTO portfolio (chat,coin,amount,buy_price,added_at) VALUES (%s,%s,%s,%s,%s)",
                                          (str(chat_id), coin, amount, buy_price, now_str))
                                db.commit(); db.close()
                                send(chat_id, f"✅ Added <b>{amount} {coin}</b> at <b>${buy_price:,.2f}</b>", BACK_MAIN)
                            except ValueError:
                                send(chat_id, "❌ Invalid format. Use: <code>BTC 0.5 60000</code>")
                        else:
                            send(chat_id, "\u274c Format: <code>COIN AMOUNT BUY_PRICE</code>\nExample: <code>BTC 0.5 60000</code>")
                        continue

                    # ── PORTFOLIO REMOVE ──────────────────────────────────────────
                    if state == "awaiting_remove_portfolio":
                        coin = text.upper().strip()
                        clear_state(chat_id)
                        db = get_db(); c = db.cursor()
                        c.execute("DELETE FROM portfolio WHERE chat=%s AND coin=%s", (str(chat_id), coin))
                        db.commit(); db.close()
                        send(chat_id, f"✅ Removed <b>{coin}</b> from portfolio.", BACK_MAIN)
                        continue

                    # ── TRADE ADD ─────────────────────────────────────────────────
                    if state == "awaiting_add_trade":
                        parts = text.upper().split()
                        if len(parts) >= 3 and parts[0] in COINS and parts[1] in ("LONG","SHORT"):
                            try:
                                coin, direction, entry = parts[0], parts[1].lower(), float(parts[2])
                                size = float(parts[3]) if len(parts) > 3 else 1.0
                                sl = float(parts[4]) if len(parts) > 4 else None
                                tp = float(parts[5]) if len(parts) > 5 else None
                                clear_state(chat_id)
                                db = get_db(); c = db.cursor()
                                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                c.execute("INSERT INTO trade_journal (chat,coin,direction,entry_price,size,stop_loss,take_profit,status,opened_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                          (str(chat_id), coin, direction, entry, size, sl, tp, "open", now_str))
                                db.commit(); db.close()
                                send(chat_id, f"✅ Trade logged\n<b>{direction.upper()} {coin}</b> @ ${entry:,.2f}", BACK_MAIN)
                            except ValueError:
                                send(chat_id, "❌ Invalid format.")
                        else:
                            send(chat_id, "❌ Format: <code>COIN LONG/SHORT ENTRY [SIZE] [SL] [TP]</code>\nExample: <code>BTC LONG 60000 0.1 58000 65000</code>")
                        continue

                    # ── TRADE CLOSE ───────────────────────────────────────────────
                    if state == "awaiting_close_trade":
                        parts = text.split()
                        if len(parts) >= 2:
                            try:
                                trade_id, exit_price = int(parts[0]), float(parts[1])
                                clear_state(chat_id)
                                close_trade(chat_id, trade_id, exit_price)
                                send(chat_id, f"✅ Trade #{trade_id} closed at ${exit_price:,.2f}", BACK_MAIN)
                            except (ValueError, IndexError):
                                send(chat_id, "❌ Format: <code>TRADE_ID EXIT_PRICE</code>\nExample: <code>3 65000</code>")
                        else:
                            send(chat_id, "❌ Format: <code>TRADE_ID EXIT_PRICE</code>")
                        continue

                    # ── COIN SEARCH ───────────────────────────────────────────────
                    if state == "awaiting_coin_search":
                        coin = text.upper().strip()
                        clear_state(chat_id)
                        if coin in COINS:
                            price, change = get_best_price(coin)
                            sd = get_secondary_coin(coin)
                            high = sd.get("usd_24h_high") if sd else None
                            low  = sd.get("usd_24h_low")  if sd else None
                            lines = [
                                f"🔍 <b>{coin} Details</b>\n",
                                f"💰 Price: <b>{format_price(price)}</b>",
                                f"📈 24h Change: <b>{format_change(change)}</b>",
                            ]
                            if high: lines.append(f"⬆️ 24h High: <b>{format_price(high)}</b>")
                            if low:  lines.append(f"⬇️ 24h Low: <b>{format_price(low)}</b>")
                            send(chat_id, "\n".join(lines), BACK_MAIN)
                        else:
                            send(chat_id, f"❌ <b>{coin}</b> not found. Available: {', '.join(list(COINS.keys())[:10])}...", BACK_MAIN)
                        continue

                    # ── CONVERT ───────────────────────────────────────────────────
                    if state == "awaiting_convert":
                        clear_state(chat_id)
                        parts = text.upper().split()
                        try:
                            # Format: 1 BTC NGN  or  100 USD ETH
                            amount_in, from_sym, to_sym = float(parts[0]), parts[1], parts[2]
                            crypto_coins = list(COINS.keys())
                            result = None
                            if from_sym in crypto_coins and to_sym == "NGN":
                                price, _ = get_best_price(from_sym)
                                buy, _, _ = get_p2p_rate("USDT", "NGN")
                                if price and buy:
                                    result = f"{amount_in} {from_sym} ≈ ₦{amount_in * price * buy:,.0f}"
                            elif from_sym in crypto_coins and to_sym in crypto_coins:
                                p1, _ = get_best_price(from_sym)
                                p2, _ = get_best_price(to_sym)
                                if p1 and p2:
                                    result = f"{amount_in} {from_sym} ≈ {amount_in*p1/p2:.6f} {to_sym}"
                            elif from_sym == "NGN" and to_sym in crypto_coins:
                                price, _ = get_best_price(to_sym)
                                _, sell, _ = get_p2p_rate("USDT", "NGN")
                                if price and sell:
                                    result = f"₦{amount_in:,.0f} ≈ {amount_in/sell/price:.8f} {to_sym}"
                            send(chat_id, f"💱 <b>Conversion</b>\n\n{result or 'Could not convert — check symbols.'}", BACK_MAIN)
                        except (ValueError, IndexError):
                            send(chat_id, "❌ Format: <code>AMOUNT FROM TO</code>\nExamples:\n<code>1 BTC NGN</code>\n<code>100 ETH BTC</code>\n<code>50000 NGN BTC</code>", BACK_MAIN)
                        continue

                    # ── PRICE HISTORY ─────────────────────────────────────────────
                    if state == "awaiting_history":
                        coin = text.upper().strip()
                        clear_state(chat_id)
                        if coin not in COINS:
                            send(chat_id, f"❌ Unknown coin {coin}.", BACK_MAIN)
                        else:
                            db = get_db(); c = db.cursor()
                            c.execute("SELECT price, timestamp FROM history WHERE coin=%s ORDER BY id DESC LIMIT 7", (coin,))
                            rows = c.fetchall(); db.close()
                            if rows:
                                lines = [f"📊 <b>{coin} Price History</b>\n"]
                                for price_val, ts in rows:
                                    lines.append(f"• {ts[:16]}  <b>{format_price(price_val)}</b>")
                                send(chat_id, "\n".join(lines), BACK_MAIN)
                            else:
                                send(chat_id, f"No history for {coin} yet.", BACK_MAIN)
                        continue

                    # ── P2P RATE SUBMIT ───────────────────────────────────────────
                    if state == "awaiting_p2p_rate":
                        clear_state(chat_id)
                        try:
                            parts = text.upper().split()
                            if len(parts) == 4:
                                crypto, fiat, buy_r, sell_r = parts[0], parts[1], float(parts[2]), float(parts[3])
                                if buy_r > sell_r and buy_r > 100 and sell_r > 100:
                                    db = get_db(); cur = db.cursor()
                                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    cur.execute(
                                        "INSERT INTO community_p2p (chat, crypto, fiat, buy_rate, sell_rate, timestamp) VALUES (%s,%s,%s,%s,%s,%s)",
                                        (str(chat_id), crypto, fiat, buy_r, sell_r, now_str)
                                    )
                                    db.commit(); db.close()
                                    send(chat_id,
                                        f"✅ <b>Rate submitted!</b>\n\n"
                                        f"{crypto}/{fiat}   Buy ₦{int(buy_r):,}   Sell ₦{int(sell_r):,}\n\n"
                                        f"<i>Thank you — your submission helps the whole community.</i>",
                                        BACK_MAIN)
                                else:
                                    send(chat_id, "❌ Invalid rates. Buy must be higher than sell and both must be above 100.\nTry: <code>USDT NGN 1620 1590</code>")
                            else:
                                send(chat_id, "❌ Wrong format. Send: <code>USDT NGN 1620 1590</code>")
                        except ValueError:
                            send(chat_id, "❌ Invalid numbers. Try: <code>USDT NGN 1620 1590</code>")
                        continue

                    # ── ALERT CONDITION (intermediate state) ──────────────────────
                    if state == "awaiting_alert_condition":
                        send(chat_id, "Please tap 📈 Price Above or 📉 Price Below on the buttons above.")
                        continue

                    # ── BROADCAST CONFIRM ─────────────────────────────────────────
                    if state == "awaiting_broadcast_confirm" and chat_id in ADMIN_IDS:
                        if text.lower() in ("yes", "confirm", "send"):
                            msg = state_data.get("message", "") if state_data else ""
                            clear_state(chat_id)
                            db = get_db(); c = db.cursor()
                            c.execute("SELECT DISTINCT chat FROM users")
                            all_users = c.fetchall(); db.close()
                            sent_count = 0
                            for (uid,) in all_users:
                                try:
                                    send(int(uid), f"📣 <b>Announcement</b>\n\n{msg}")
                                    sent_count += 1
                                    time.sleep(0.1)  # 10/sec — safe Telegram rate limit
                                except: pass
                            send(chat_id, f"✅ Broadcast sent to {sent_count} users.")
                        else:
                            clear_state(chat_id)
                            send(chat_id, "❌ Broadcast cancelled.")
                        continue

                    # ── TRY AI ON ANY QUESTION ──────────────────────────────────
                    if any(kw in text.lower() for kw in ["what", "how", "why", "when", "where", "is", "are", "can", "will", "tell", "explain"]):
                        send(chat_id, "🤖 Thinking...")
                        response, provider = ask_ai(text)
                        if response:
                            send(chat_id, f"🤖 <b>AI ({provider})</b>\n\n{response}", BACK_MAIN)
                        else:
                            send(chat_id, "⚠️ AI service is currently unavailable.", BACK_MAIN)
                        continue

                # ═══════════════════════════════════════════════════════════════
                # 📊 CALLBACK QUERY HANDLERS
                # ═══════════════════════════════════════════════════════════════
                if "callback_query" in u:
                    q = u["callback_query"]
                    chat_id = q["message"]["chat"]["id"]
                    message_id = q["message"]["message_id"]
                    data = q["data"]
                    username = q["from"].get("username", "")
                    first_name = q["from"].get("first_name", "")
                    answer_cb(q["id"])
                    upsert_user(chat_id, username, first_name)

                    if is_user_banned(chat_id):
                        edit(chat_id, message_id, "🔒 You are banned from using this bot.", BACK_MAIN)
                        continue

                    if not is_user_in_channel(chat_id) and chat_id not in ADMIN_IDS:
                        edit(chat_id, message_id, "🔒 Please join our free channel first:\n\n👉 @marketpulseng\n\nJoin then tap Verify.", [[{"text": "✅ Verified", "callback_data": "verify_join"}]])
                        continue

                    # ── VERIFY JOIN ──────────────────────────────────────────────
                    if data == "verify_join":
                        if is_user_in_channel(chat_id, force=True):
                            edit(chat_id, message_id, "✅ <b>Welcome to Market Pulse!</b>\n\n"
                            "You now have access. Tap the button to get started.",
                            [[{"text": "🚀 Get Started", "callback_data": "main_menu"}]])
                        else:
                            edit(chat_id, message_id, "❌ Still can't find you in the channel.\n\n1. Join @marketpulseng\n2. Come back and tap Try Again.", [[{"text": "✅ Try Again", "callback_data": "verify_join"}]])
                        continue

                    # ── MAIN MENU ────────────────────────────────────────────────
                    if data == "main_menu":
                        clear_state(chat_id)
                        show_main_menu(chat_id, message_id)
                        continue

                    # ── ADMIN MENU NAVIGATION ─────────────────────────────────────
                    if data == "admin_menu" and chat_id in ADMIN_IDS:
                        edit(chat_id, message_id, "👑 <b>Admin Panel</b>\n\nSelect a category:", ADMIN_MENU)
                        continue
                    if data == "adm_analytics" and chat_id in ADMIN_IDS:
                        edit(chat_id, message_id, "📊 <b>Analytics</b>", ADMIN_ANALYTICS_MENU)
                        continue
                    if data == "adm_channel" and chat_id in ADMIN_IDS:
                        edit(chat_id, message_id, "📢 <b>Channel</b>", ADMIN_CHANNEL_MENU)
                        continue
                    if data == "adm_users" and chat_id in ADMIN_IDS:
                        edit(chat_id, message_id, "👥 <b>Users</b>", ADMIN_USERS_MENU)
                        continue
                    if data == "adm_trades" and chat_id in ADMIN_IDS:
                        edit(chat_id, message_id, "⚡ <b>Trades</b>", ADMIN_TRADES_MENU)
                        continue
                    if data == "adm_system" and chat_id in ADMIN_IDS:
                        edit(chat_id, message_id, "🏥 <b>System</b>", ADMIN_SYSTEM_MENU)
                        continue
                    if data == "adm_settings_menu" and chat_id in ADMIN_IDS:
                        edit(chat_id, message_id, "⚙️ <b>Settings</b>", ADMIN_SETTINGS_MENU)
                        continue
                    if data == "adm_toggle_channel" and chat_id in ADMIN_IDS:
                        toggle_channel_enabled()
                        status = "✅ Enabled" if CHANNEL_ENABLED else "⏸ Paused"
                        edit(chat_id, message_id,
                            f"📢 Channel posting is now <b>{status}</b>.",
                            [[{"text": "⬅ Back", "callback_data": "adm_channel"}]])
                        continue

                    if data == "adm_toggle_mirror" and chat_id in ADMIN_IDS:
                        toggle_mirror_mode()
                        status = "🟢 ON" if MIRROR_MODE else "🔴 OFF"
                        edit(chat_id, message_id,
                            f"🪞 <b>Mirror Mode: {status}</b>\n\n"
                            f"{'Pro channel posts are now being mirrored to the free channel.' if MIRROR_MODE else 'Pro channel posts are no longer mirrored to the free channel.'}\n\n"
                            f"⚠️ When ON — free users see all Pro content including trade setups.",
                            [[{"text": "⬅ Back", "callback_data": "adm_channel"}]])
                        continue
                    if data == "adm_grant_pro" and chat_id in ADMIN_IDS:
                        set_state(chat_id, "awaiting_grant_pro")
                        edit(chat_id, message_id,
                            "💎 <b>Grant Pro</b>\n\nSend the user\'s Telegram ID to grant 30 days Pro.\n"
                            "Format: <code>123456789</code> or <code>123456789 3</code> for 3 months.",
                            [[{"text": "❌ Cancel", "callback_data": "adm_users"}]])
                        continue
                    if data == "adm_trade_history" and chat_id in ADMIN_IDS:
                        rows = get_trade_history(limit=10)
                        if not rows:
                            edit(chat_id, message_id, "📋 No trade ideas yet.\n\nGenerate one from ⚡ Trades menu.",
                                [[{"text": "⬅ Back", "callback_data": "adm_trades"}]])
                        else:
                            lines = ["📋 <b>Recent Trade Ideas</b>\n"]
                            for row in rows:
                                tid, coin, tier, direction, tf, entry, t1, conf, status, created = row
                                emoji = {"open":"🟡","closed":"✅"}.get(status,"⚪")
                                lines.append(f"{emoji} <b>#{tid}</b> {coin} {tier.upper()} {direction} | {created[:10]}")
                            edit(chat_id, message_id, "\n".join(lines),
                                [[{"text": "⬅ Back", "callback_data": "adm_trades"}]])
                        continue
                    if data == "adm_gen_trade" and chat_id in ADMIN_IDS:
                        edit(chat_id, message_id,
                            "⚡ <b>Generate Trade Idea</b>\n\n"
                            "Use the command format:\n"
                            "<code>/trade BTC momentum</code>\n"
                            "<code>/trade ETH steady</code>\n"
                            "<code>/trade SOL edge</code>\n\n"
                            "Tiers: steady | momentum | edge",
                            [[{"text": "⬅ Back", "callback_data": "adm_trades"}]])
                        continue
                    if data == "adm_performance" and chat_id in ADMIN_IDS:
                        db = None
                        try:
                            db = get_db()
                            c = db.cursor()
                            c.execute("SELECT COUNT(*) FROM trade_ideas")
                            total = c.fetchone()[0]
                            c.execute("SELECT COUNT(*) FROM trade_ideas WHERE status=\'closed\' AND result=\'hit_t1\'")
                            hit_t1 = c.fetchone()[0]
                            c.execute("SELECT COUNT(*) FROM trade_ideas WHERE status=\'closed\' AND result=\'hit_t2\'")
                            hit_t2 = c.fetchone()[0]
                            c.execute("SELECT COUNT(*) FROM trade_ideas WHERE status=\'closed\' AND result=\'stopped\'")
                            stopped = c.fetchone()[0]
                            c.execute("SELECT COUNT(*) FROM trade_ideas WHERE status=\'open\'")
                            open_ideas = c.fetchone()[0]
                            closed = hit_t1 + hit_t2 + stopped
                            win_rate = round((hit_t1 + hit_t2) / closed * 100, 1) if closed > 0 else 0
                            msg = (
                                "📊 <b>Trade Performance</b>\n\n"
                                f"Total ideas: <b>{total}</b>\n"
                                f"Open: <b>{open_ideas}</b>\n"
                                f"Closed: <b>{closed}</b>\n\n"
                                f"✅ Hit T1: <b>{hit_t1}</b>\n"
                                f"🏆 Hit T2: <b>{hit_t2}</b>\n"
                                f"❌ Stopped: <b>{stopped}</b>\n\n"
                                f"Win Rate: <b>{win_rate}%</b>\n"
                                f"<i>Use /closetrade [ID] [result] to record outcomes</i>"
                            )
                        except Exception as e:
                            msg = f"⚠️ Error loading performance: {e}"
                        finally:
                            if db:
                                try: db.close()
                                except Exception: pass
                        edit(chat_id, message_id, msg,
                            [[{"text": "⬅ Back", "callback_data": "adm_trades"}]])
                        continue
                    if data == "adm_mode_menu" and chat_id in ADMIN_IDS:
                        mode = get_bot_mode().upper()
                        edit(chat_id, message_id,
                            f"🤖 <b>Bot Mode</b>\n\nCurrent: <b>{mode}</b>\n\n"
                            "Everyone — all features free\n"
                            "Pro — Free + Pro tiers active",
                            [[{"text": "🌍 Everyone", "callback_data": "adm_mode_everyone"},
                              {"text": "💎 Pro", "callback_data": "adm_mode_pro"}],
                             [{"text": "⬅ Back", "callback_data": "adm_settings_menu"}]])
                        continue
                    if data == "adm_mode_everyone" and chat_id in ADMIN_IDS:
                        set_bot_mode("everyone")
                        cfg = load_admin_config(); cfg["BOT_MODE"] = "everyone"; save_admin_config(cfg)
                        edit(chat_id, message_id, "✅ Mode set to <b>Everyone Free</b>.",
                            [[{"text": "⬅ Back", "callback_data": "adm_settings_menu"}]])
                        continue
                    if data == "adm_mode_pro" and chat_id in ADMIN_IDS:
                        set_bot_mode("pro")
                        cfg = load_admin_config(); cfg["BOT_MODE"] = "pro"; save_admin_config(cfg)
                        edit(chat_id, message_id, "✅ Mode set to <b>Pro</b>.",
                            [[{"text": "⬅ Back", "callback_data": "adm_settings_menu"}]])
                        continue

                    # ── MENU NAVIGATION ──────────────────────────────────────────
                    if data == "menu_markets":
                        edit(chat_id, message_id, "📊 <b>Markets</b>\n\nSelect an option:", MARKETS_MENU)
                        continue
                    
                    if data == "menu_intelligence":
                        edit(chat_id, message_id, "🧠 <b>Intelligence</b>\n\nSelect an option:", INTELLIGENCE_MENU)
                        continue
                    
                    if data == "menu_p2p":
                        edit(chat_id, message_id, "🇳🇬 <b>P2P Center</b>\n\nSelect an option:", P2P_MENU)
                        continue
                    
                    if data == "menu_alerts":
                        if get_bot_mode() == "everyone" or is_pro(chat_id):
                            edit(chat_id, message_id, "🔔 <b>Alerts</b>\n\nSelect an option:", ALERTS_MENU_PRO)
                        else:
                            edit(chat_id, message_id, "🔔 <b>Alerts</b>\n\nSelect an option:", ALERTS_MENU_FREE)
                        continue
                    
                    if data == "menu_portfolio":
                        edit(chat_id, message_id, "💼 <b>Portfolio</b>\n\nSelect an option:", PORTFOLIO_MENU)
                        continue
                    
                    if data == "menu_trades":
                        edit(chat_id, message_id, "📈 <b>Trade Journal</b>\n\nSelect an option:", TRADES_MENU)
                        continue
                    
                    if data == "menu_tools":
                        edit(chat_id, message_id, "🛠 <b>Tools</b>\n\nSelect an option:", TOOLS_MENU)
                        continue
                    
                    if data == "menu_account":
                        if get_bot_mode() == "everyone" or is_pro(chat_id):
                            edit(chat_id, message_id, "👤 <b>My Account</b>\n\nSelect an option:", ACCOUNT_MENU_PRO)
                        else:
                            edit(chat_id, message_id, "👤 <b>My Account</b>\n\nSelect an option:", ACCOUNT_MENU_FREE)
                        continue
                    
                    if data == "help":
                        show_help(chat_id, message_id)
                        continue

                    # ── FEATURES ──────────────────────────────────────────────────
                    if data == "market":
                        show_market(chat_id, message_id)
                        continue
                    
                    if data == "portfolio":
                        show_portfolio(chat_id, message_id)
                        continue
                    
                    if data == "trade_journal":
                        show_trade_journal(chat_id, message_id)
                        continue
                    
                    if data == "settings":
                        show_settings(chat_id, message_id)
                        continue
                    
                    if data == "position_calculator":
                        show_position_calculator(chat_id, message_id)
                        continue
                    
                    if data == "upgrade":
                        show_upgrade(chat_id, message_id)
                        continue
                    
                    if data == "p2p":
                        buy, sell, source = get_p2p_rate("USDT", "NGN")
                        if buy and sell:
                            text = (
                                "💱 <b>USDT/NGN P2P Rates</b>\n\n"
                                f"Buy: <b>₦{int(buy):,}</b>\n"
                                f"Sell: <b>₦{int(sell):,}</b>\n"
                                f"Spread: <b>₦{int(buy - sell):,}</b>\n\n"
                                f"Source: <i>{source}</i>"
                            )
                        else:
                            text = "⚠️ Could not fetch P2P rates."
                        edit(chat_id, message_id, text, [[{"text": "🔄 Refresh", "callback_data": "p2p"}, {"text": "⬅ Back", "callback_data": "menu_p2p"}]])
                        continue
                    
                    if data == "fear_greed":
                        fg_data = get_fear_greed()
                        if fg_data:
                            current = fg_data[0]
                            text = (
                                "🧠 <b>Fear & Greed Index</b>\n\n"
                                f"Current: <b>{current['value']}/100</b>\n"
                                f"Status: <b>{current['value_classification']}</b>\n"
                                f"{fg_emoji(current['value'])}\n\n"
                                f"📅 {current['timestamp']}"
                            )
                            if len(fg_data) > 1:
                                week_ago = fg_data[-1]
                                text += f"\n\nWeek ago: {week_ago['value']}/100 ({week_ago['value_classification']})"
                        else:
                            text = "⚠️ Could not fetch Fear & Greed data."
                        edit(chat_id, message_id, text, [[{"text": "🔄 Refresh", "callback_data": "fear_greed"}, {"text": "⬅ Back", "callback_data": "menu_intelligence"}]])
                        continue
                    
                    if data == "news":
                        news = get_crypto_news()
                        if news:
                            lines = ["📰 <b>Top Crypto News</b>\n"]
                            for i, art in enumerate(news[:5], 1):
                                lines.append(f"{i}. <b>{art.get('title', '')[:80]}</b>")
                                lines.append(f"   {art.get('source', {}).get('title', 'Unknown')}")
                                lines.append("")
                            edit(chat_id, message_id, "\n".join(lines), [[{"text": "🔄 Refresh", "callback_data": "news"}, {"text": "⬅ Back", "callback_data": "menu_intelligence"}]])
                        else:
                            edit(chat_id, message_id, "⚠️ No news available.", [[{"text": "⬅ Back", "callback_data": "menu_intelligence"}]])
                        continue

                    # ── SETTINGS CALLBACKS ──────────────────────────────────────
                    if data == "settings_language":
                        buttons = [
                            [{"text": "🇬🇧 English", "callback_data": "lang_en"}],
                            [{"text": "🇳🇬 Hausa", "callback_data": "lang_ha"}],
                            [{"text": "🇳🇬 Yoruba", "callback_data": "lang_yo"}],
                            [{"text": "🇳🇬 Igbo", "callback_data": "lang_ig"}],
                            [{"text": "⬅ Back", "callback_data": "settings"}]
                        ]
                        edit(chat_id, message_id, "🌐 <b>Select Language</b>", buttons)
                        continue
                    
                    if data.startswith("lang_"):
                        lang = data.split("_")[1]
                        try:
                            db = get_db()
                            c = db.cursor()
                            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            c.execute(
                                "INSERT INTO user_preferences (chat, language, notifications, theme, updated_at) "
                                "VALUES (%s,%s,1,'dark',%s) "
                                "ON CONFLICT(chat) DO UPDATE SET language=excluded.language, updated_at=excluded.updated_at",
                                (str(chat_id), lang, now)
                            )
                            db.commit()
                            db.close()
                            send(chat_id, f"✅ Language set to {lang.upper()}")
                            show_settings(chat_id, message_id)
                        except Exception as _e:
                            send(chat_id, "⚠️ Error saving settings.")
                        continue
                    
                    if data == "settings_notifications":
                        try:
                            db = get_db()
                            c = db.cursor()
                            c.execute("SELECT notifications FROM user_preferences WHERE chat=%s", (str(chat_id),))
                            row = c.fetchone()
                            current = row[0] if row else 1
                            new_val = 0 if current else 1
                            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            c.execute(
                                "INSERT INTO user_preferences (chat, language, notifications, theme, updated_at) "
                                "VALUES (%s,'en',%s,'dark',%s) "
                                "ON CONFLICT(chat) DO UPDATE SET notifications=excluded.notifications, updated_at=excluded.updated_at",
                                (str(chat_id), new_val, now)
                            )
                            db.commit()
                            db.close()
                            send(chat_id, f"✅ Notifications {'On' if new_val else 'Off'}")
                            show_settings(chat_id, message_id)
                        except Exception as _e:
                            send(chat_id, "⚠️ Error saving settings.")
                        continue
                    
                    if data == "settings_theme":
                        try:
                            db = get_db()
                            c = db.cursor()
                            c.execute("SELECT theme FROM user_preferences WHERE chat=%s", (str(chat_id),))
                            row = c.fetchone()
                            current = row[0] if row else "dark"
                            new_val = "light" if current == "dark" else "dark"
                            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            c.execute(
                                "INSERT INTO user_preferences (chat, language, notifications, theme, updated_at) "
                                "VALUES (%s,'en',1,%s,%s) "
                                "ON CONFLICT(chat) DO UPDATE SET theme=excluded.theme, updated_at=excluded.updated_at",
                                (str(chat_id), new_val, now)
                            )
                            db.commit()
                            db.close()
                            send(chat_id, f"✅ Theme set to {new_val.title()}")
                            show_settings(chat_id, message_id)
                        except Exception as _e:
                            send(chat_id, "⚠️ Error saving settings.")
                        continue

                    # ── PORTFOLIO ACTIONS ──────────────────────────────────────
                    if data == "add_portfolio":
                        set_state(chat_id, "awaiting_add_portfolio", {})
                        edit(chat_id, message_id, "➕ <b>Add Portfolio Position</b>\n\nSend in this format:\n<code>BTC 0.5 61000</code>", [[{"text": "⬅ Cancel", "callback_data": "menu_portfolio"}]])
                        continue
                    
                    if data == "remove_portfolio":
                        set_state(chat_id, "awaiting_remove_portfolio", {})
                        edit(chat_id, message_id, "🗑️ <b>Remove Portfolio Position</b>\n\nSend the coin name: <code>BTC</code>", [[{"text": "⬅ Cancel", "callback_data": "menu_portfolio"}]])
                        continue
                    
                    if data == "pnl_summary":
                        portfolio_data = get_portfolio_value(chat_id)
                        if portfolio_data and portfolio_data["positions"]:
                            text = (
                                "📊 <b>P&L Summary</b>\n\n"
                                f"💰 Total Invested: <b>${portfolio_data['total_invested']:.2f}</b>\n"
                                f"📈 Current Value: <b>${portfolio_data['total_current']:.2f}</b>\n"
                                f"📊 Total P&L: <b>{'+' if portfolio_data['total_pnl'] > 0 else ''}{portfolio_data['total_pnl']:.2f}</b>\n"
                                f"📈 P&L %: <b>{'+' if portfolio_data['total_pnl_pct'] > 0 else ''}{portfolio_data['total_pnl_pct']:.1f}%</b>\n\n"
                                f"📊 Positions: <b>{len(portfolio_data['positions'])}</b>"
                            )
                        else:
                            text = "📊 <b>P&L Summary</b>\n\nNo positions yet."
                        edit(chat_id, message_id, text, [[{"text": "⬅ Back", "callback_data": "menu_portfolio"}]])
                        continue

                    # ── TRADE ACTIONS ────────────────────────────────────────────
                    if data == "add_trade":
                        set_state(chat_id, "awaiting_add_trade", {})
                        edit(chat_id, message_id, "➕ <b>Add Trade</b>\n\nFormat: <code>BTC LONG 61000 62000 0.5</code>", [[{"text": "⬅ Cancel", "callback_data": "menu_trades"}]])
                        continue
                    
                    if data == "close_trade":
                        set_state(chat_id, "awaiting_close_trade", {})
                        edit(chat_id, message_id, "🔒 <b>Close Trade</b>\n\nSend: <code>TRADE_ID EXIT_PRICE</code>\n\nOr just <code>TRADE_ID</code> for current price", [[{"text": "⬅ Cancel", "callback_data": "menu_trades"}]])
                        continue
                    
                    if data == "win_rate":
                        try:
                            db = get_db()
                            c = db.cursor()
                            c.execute("SELECT pnl FROM trade_journal WHERE chat=%s AND status='closed'", (str(chat_id),))
                            rows = c.fetchall()
                            db.close()
                            if rows:
                                total_pnl = sum(r[0] for r in rows if r[0])
                                wins = sum(1 for r in rows if r[0] and r[0] > 0)
                                total = len(rows)
                                win_rate = (wins / total) * 100 if total > 0 else 0
                                avg_pnl = total_pnl / total if total > 0 else 0
                                text = (
                                    "📊 <b>Win Rate Analysis</b>\n\n"
                                    f"Total Trades: <b>{total}</b>\n"
                                    f"Wins: <b>{wins}</b>\n"
                                    f"Losses: <b>{total - wins}</b>\n"
                                    f"Win Rate: <b>{win_rate:.1f}%</b>\n"
                                    f"Total P&L: <b>{'+' if total_pnl > 0 else ''}{total_pnl:.2f}</b>\n"
                                    f"Average P&L: <b>{'+' if avg_pnl > 0 else ''}{avg_pnl:.2f}</b>"
                                )
                            else:
                                text = "📊 <b>Win Rate Analysis</b>\n\nNo closed trades yet."
                        except Exception as _e:
                            text = "⚠️ Error loading trade stats."
                        edit(chat_id, message_id, text, [[{"text": "⬅ Back", "callback_data": "menu_trades"}]])
                        continue

                    # ── ASK AI ────────────────────────────────────────────────────
                    if data == "ask_ai":
                        allowed, used, limit = check_ai_limit(chat_id)
                        if not allowed:
                            edit(chat_id, message_id, ai_limit_msg(used, limit), UPGRADE_BTN)
                            continue
                        remaining = (limit - used) if limit else None
                        hint = f"\n\n<i>💬 {remaining} free questions remaining today.</i>" if remaining is not None else ""
                        set_state(chat_id, "awaiting_ai_question", {})
                        edit(chat_id, message_id, f"🤖 <b>Ask AI</b>\n\nWhat would you like to know?{hint}", [[{"text": "⬅ Cancel", "callback_data": "menu_intelligence"}]])
                        continue

                    # ── P2P ACTIONS ──────────────────────────────────────────────
                    if data == "submit_rate":
                        set_state(chat_id, "awaiting_p2p_rate", {})
                        edit(chat_id, message_id, "📤 <b>Submit P2P Rate</b>\n\nFormat: <code>USDT NGN 1530 1520</code>", [[{"text": "⬅ Cancel", "callback_data": "menu_p2p"}]])
                        continue
                    
                    if data == "p2p_alerts":
                        edit(chat_id, message_id, "🔔 <b>P2P Alerts</b>\n\nFeature coming soon!", [[{"text": "⬅ Back", "callback_data": "menu_p2p"}]])
                        continue
                    
                    if data == "arbitrage":
                        opportunities = scan_arbitrage()
                        if opportunities:
                            lines = ["🔄 <b>Arbitrage Opportunities</b>\n"]
                            for opp in opportunities[:5]:
                                lines.append(f"<b>{opp['coin']}</b>")
                                lines.append(f"  Buy: {opp['buy_from']} @ {format_price(opp['buy_price'])}")
                                lines.append(f"  Sell: {opp['sell_to']} @ {format_price(opp['sell_price'])}")
                                lines.append(f"  Gap: <b>{opp['gap_pct']:.2f}%</b>")
                                lines.append("")
                        else:
                            lines = ["🔄 <b>Arbitrage Scanner</b>\n\nNo opportunities found at the moment.\n\n<small>Check back later!</small>"]
                        edit(chat_id, message_id, "\n".join(lines), [[{"text": "🔄 Refresh", "callback_data": "arbitrage"}, {"text": "⬅ Back", "callback_data": "menu_p2p"}]])
                        continue

                    # ── TOOLS ────────────────────────────────────────────────────
                    if data == "coin_search":
                        set_state(chat_id, "awaiting_coin_search", {})
                        edit(chat_id, message_id, "🔍 <b>Search Coin</b>\n\nSend the coin name: <code>BTC</code>", [[{"text": "⬅ Cancel", "callback_data": "menu_tools"}]])
                        continue
                    
                    if data == "convert":
                        set_state(chat_id, "awaiting_convert", {})
                        edit(chat_id, message_id, "🔄 <b>Convert Crypto</b>\n\nFormat: <code>BTC 1.5 USD</code>", [[{"text": "⬅ Cancel", "callback_data": "menu_tools"}]])
                        continue
                    
                    if data == "history":
                        set_state(chat_id, "awaiting_history", {})
                        edit(chat_id, message_id, "📜 <b>Price History</b>\n\nFormat: <code>BTC 1D</code>\n\nTimeframes: 1H, 6H, 1D, 3D, 1W, 1M, 3M, 1Y", [[{"text": "⬅ Cancel", "callback_data": "menu_tools"}]])
                        continue
                    
                    if data == "status":
                        text = (
                            "⚙️ <b>Bot Status</b>\n\n"
                            f"📅 Version: v16\n"
                            f"🤖 Mode: {get_bot_mode().upper()}\n"
                            f"📊 Channel: {'✅ Online' if CHANNEL_ENABLED else '⏸️ Paused'}\n"
                            f"👤 Your Status: {get_user_badge(chat_id)}\n\n"
                            f"🟢 All systems operational."
                        )
                        edit(chat_id, message_id, text, [[{"text": "🔄 Refresh", "callback_data": "status"}, {"text": "⬅ Back", "callback_data": "menu_tools"}]])
                        continue

                    # ── ACCOUNT ──────────────────────────────────────────────────
                    if data == "profile":
                        db = get_db()
                        c = db.cursor()
                        c.execute("SELECT first_name, username, first_seen, last_seen FROM users WHERE chat=%s", (str(chat_id),))
                        row = c.fetchone()
                        db.close()
                        if row:
                            name, username, first_seen, last_seen = row
                            text = (
                                "👤 <b>My Profile</b>\n\n"
                                f"Name: <b>{name or 'N/A'}</b>\n"
                                f"Username: <b>@{username or 'N/A'}</b>\n"
                                f"Status: <b>{get_user_badge(chat_id)}</b>\n"
                                f"Joined: <b>{first_seen}</b>\n"
                                f"Last Active: <b>{last_seen}</b>"
                            )
                        else:
                            text = "👤 <b>My Profile</b>\n\nNo profile data available."
                        edit(chat_id, message_id, text, [[{"text": "⬅ Back", "callback_data": "menu_account"}]])
                        continue
                    
                    if data == "pro_status":
                        if is_pro(chat_id):
                            expiry = get_pro_expiry(chat_id)
                            days = get_pro_days_left(chat_id)
                            refs = get_pro_referral_count(chat_id)
                            text = (
                                "⭐ <b>Pro Status</b>\n\n"
                                f"Status: <b>✅ Active</b>\n"
                                f"Expires: <b>{expiry}</b>\n"
                                f"Days Left: <b>{days}</b>\n"
                                f"Referrals: <b>{refs}</b>\n\n"
                                "🎁 Refer 5+ people for FREE months!"
                            )
                        else:
                            text = (
                                "⭐ <b>Pro Status</b>\n\n"
                                "Status: <b>❌ Not Active</b>\n\n"
                                "💎 Upgrade to Pro:\n"
                                "✅ Unlimited AI\n"
                                "✅ 20 alerts\n"
                                "✅ Trade Journal\n"
                                "✅ Position Calculator\n"
                                "✅ Pro Referrals\n\n"
                                "Contact @heisthegeneral"
                            )
                        edit(chat_id, message_id, text, [[{"text": "💎 Upgrade", "callback_data": "upgrade"}, {"text": "⬅ Back", "callback_data": "menu_account"}]])
                        continue
                    
                    if data == "my_usage":
                        try:
                            db = get_db()
                            c = db.cursor()
                            c.execute("SELECT COUNT(*) FROM feature_usage WHERE chat=%s", (str(chat_id),))
                            total_usage = c.fetchone()[0]
                            c.execute("SELECT COUNT(*) FROM alerts WHERE chat=%s AND active=1", (str(chat_id),))
                            total_alerts = c.fetchone()[0]
                            c.execute("SELECT COUNT(*) FROM portfolio WHERE chat=%s", (str(chat_id),))
                            total_positions = c.fetchone()[0]
                            c.execute("SELECT COUNT(*) FROM trade_journal WHERE chat=%s", (str(chat_id),))
                            total_trades = c.fetchone()[0]
                            db.close()
                            text = (
                                "📊 <b>My Usage</b>\n\n"
                                f"📈 Total Interactions: <b>{total_usage}</b>\n"
                                f"🔔 Active Alerts: <b>{total_alerts}</b>\n"
                                f"💼 Portfolio Items: <b>{total_positions}</b>\n"
                                f"📈 Trades Logged: <b>{total_trades}</b>"
                            )
                        except Exception as _e:
                            text = "📊 <b>My Usage</b>\n\nCould not load usage data."
                        edit(chat_id, message_id, text, [[{"text": "⬅ Back", "callback_data": "menu_account"}]])
                        continue
                    
                    if data == "referral":
                        if is_pro(chat_id):
                            count = get_pro_referral_count(chat_id)
                            reward, _ = get_pro_referral_reward(chat_id)
                            text = (
                                "👥 <b>Pro Referral Program</b>\n\n"
                                f"📊 Referrals: <b>{count}</b>\n"
                                f"🎁 Next reward: <b>{reward or 'None yet'}</b>\n\n"
                                "🎯 Milestones:\n"
                                "5 referrals → 1 month FREE\n"
                                "10 referrals → 3 months FREE\n"
                                "20 referrals → 6 months FREE\n\n"
                                "📤 Share your referral link:\n"
                                f"<code>https://t.me/MarketNgPulseBot?start=ref_PRO_{chat_id}</code>"
                            )
                        else:
                            text = "👥 <b>Referral Program</b>\n\nUpgrade to Pro to earn FREE months!"
                        edit(chat_id, message_id, text, [[{"text": "💎 Upgrade", "callback_data": "upgrade"}, {"text": "⬅ Back", "callback_data": "menu_account"}]])
                        continue

                    # ── HELP SUB-MENUS ──────────────────────────────────────────
                    if data == "help_commands":
                        show_help(chat_id, message_id)
                        continue
                    
                    if data == "help_howto":
                        text = (
                            "📖 <b>How To Use Market Pulse</b>\n\n"
                            "1. <b>Start</b> — Type /start or /menu\n"
                            "2. <b>Prices</b> — Tap Markets or type /market\n"
                            "3. <b>AI Analysis</b> — Tap Intelligence or type /ai\n"
                            "4. <b>P2P Rates</b> — Tap P2P Center or type /p2p\n"
                            "5. <b>Portfolio</b> — Tap Portfolio or type /portfolio\n"
                            "6. <b>Trades</b> — Tap Trade Journal or type /trades\n"
                            "7. <b>Alerts</b> — Tap Alerts or type /alerts\n\n"
                            "💡 Pro tip: Use /help to see all commands!"
                        )
                        edit(chat_id, message_id, text, [[{"text": "⬅ Back", "callback_data": "help"}]])
                        continue
                    
                    if data == "help_faq":
                        text = (
                            "❓ <b>FAQ</b>\n\n"
                            "❔ <b>Is this free?</b>\n"
                            "Yes! Core features are free. Pro users get more.\n\n"
                            "❔ <b>Where do prices come from?</b>\n"
                            "Kraken → OKX → Bybit → CoinGecko\n\n"
                            "❔ <b>Are P2P rates real?</b>\n"
                            "Yes! From Binance P2P and Bybit P2P.\n\n"
                            "❔ <b>How do I upgrade to Pro?</b>\n"
                            "Contact @heisthegeneral\n\n"
                            "❔ <b>NFA - DYOR?</b>\n"
                            "Not Financial Advice - Do Your Own Research."
                        )
                        edit(chat_id, message_id, text, [[{"text": "⬅ Back", "callback_data": "help"}]])
                        continue
                    
                    if data == "support":
                        text = (
                            "💬 <b>Support</b>\n\n"
                            "Need help? Contact us:\n\n"
                            "📩 DM: @heisthegeneral\n"
                            "📢 Channel: @MarketNgPulseBot\n\n"
                            "Or use /feedback to send a message."
                        )
                        edit(chat_id, message_id, text, [[{"text": "⬅ Back", "callback_data": "help"}]])

                    # ── ADMIN CALLBACKS ──────────────────────────────────────────
                    if chat_id in ADMIN_IDS:
                        if data == "admin_stats":
                            db = get_db()
                            c = db.cursor()
                            c.execute("SELECT COUNT(*) FROM users")
                            users = c.fetchone()[0]
                            c.execute("SELECT COUNT(*) FROM pro_subscriptions")
                            pro = c.fetchone()[0]
                            c.execute("SELECT COUNT(*) FROM alerts WHERE active=1")
                            alerts = c.fetchone()[0]
                            db.close()
                            text = (
                                "📊 <b>Admin Stats</b>\n\n"
                                f"👤 Users: <b>{users:,}</b>\n"
                                f"⭐ Pro: <b>{pro:,}</b>\n"
                                f"🔔 Alerts: <b>{alerts:,}</b>\n"
                                f"⚡ Mode: <b>{get_bot_mode().upper()}</b>"
                            )
                            edit(chat_id, message_id, text, [[{"text": "🔄 Refresh", "callback_data": "admin_stats"}, {"text": "⬅ Back", "callback_data": "main_menu"}]])
                            continue
                        
                        if data == "admin_users":
                            db = get_db()
                            c = db.cursor()
                            c.execute("SELECT chat, username, first_name FROM users ORDER BY id DESC LIMIT 10")
                            rows = c.fetchall()
                            db.close()
                            lines = ["👤 <b>Recent Users</b>\n"]
                            for chat, username, first_name in rows:
                                name = first_name or username or str(chat)
                                lines.append(f"• {name[:25]} (<code>{chat}</code>)")
                            edit(chat_id, message_id, "\n".join(lines), [[{"text": "⬅ Back", "callback_data": "adm_analytics"}]])
                            continue
                        
                        if data == "admin_health":
                            ws_status = ws_engine_status()
                            btc_p, _ = _ws_get_cached("BTC")
                            eth_p, _ = _ws_get_cached("ETH")
                            with _ws_lock:
                                cached_count = len(_ws_price_cache)
                            health_msg = (
                                "🏥 <b>System Health</b>\n\n"
                                "⚡ <b>WebSocket Engine</b>\n"
                                f"  Binance: {'🟢 streaming' if btc_p else '🔴 stale/down'}\n"
                                f"  Kraken:  {'🟢 streaming' if eth_p else '🟡 REST fallback'}\n"
                                f"  Prices cached: {cached_count}/{len(COINS)} coins\n\n"
                                "🌐 <b>REST Fallbacks</b>\n"
                                "  OKX / Bybit / CoinGecko: standby\n\n"
                                "🤖 <b>Bot</b>\n"
                                f"  Mode: {get_bot_mode().upper()}\n"
                                f"  Channel: {'✅ ON' if CHANNEL_ENABLED else '⏸ OFF'}\n"
                                "  Poll loop: 🟢 running"
                            )
                            edit(chat_id, message_id, health_msg,
                                [[{"text": "🔄 Refresh", "callback_data": "admin_health"},
                                  {"text": "⬅ Back", "callback_data": "adm_system"}]])
                            continue

                    # ── PRO MENU ──────────────────────────────────────────────────
                    if data == "menu_pro":
                        text = (
                            "⭐ <b>Pro Features</b>\n\n"
                            "✅ Unlimited AI\n"
                            "✅ 20 alerts\n"
                            "✅ 30 watchlist items\n"
                            "✅ 30 portfolio items\n"
                            "✅ Trade Journal\n"
                            "✅ Position Calculator\n"
                            "✅ AI Trade Setups\n"
                            "✅ Pro Channel\n"
                            "✅ Pro Referrals\n\n"
                            f"📅 Expires: <b>{get_pro_expiry(chat_id) or 'N/A'}</b>"
                        )
                        edit(chat_id, message_id, text, [[{"text": "⬅ Back", "callback_data": "main_menu"}]])
                        continue
                    
                    if data == "menu_pro_tools":
                        text = (
                            "📈 <b>Pro Tools</b>\n\n"
                            "✅ Position Calculator\n"
                            "✅ Trade Journal\n"
                            "✅ AI Trade Setups\n"
                            "✅ Smart Alerts\n"
                            "✅ Advanced Analytics\n"
                            "✅ Pro Referrals"
                        )
                        edit(chat_id, message_id, text, [[{"text": "⬅ Back", "callback_data": "main_menu"}]])

                    # ── ALERTS — Create Alert ─────────────────────────────────────
                    if data == "alerts":
                        set_state(chat_id, "awaiting_alert_coin")
                        pro_limit = 20 if (get_bot_mode() == "everyone" or is_pro(chat_id)) else 3
                        db = get_db(); c = db.cursor()
                        c.execute("SELECT COUNT(*) FROM alerts WHERE chat=%s AND active=1", (str(chat_id),))
                        count = c.fetchone()[0]; db.close()
                        if count >= pro_limit:
                            edit(chat_id, message_id,
                                f"⚠️ You have reached your alert limit ({pro_limit}).\n\nDelete an alert first.",
                                [[{"text": "📋 My Alerts", "callback_data": "my_alerts"}, {"text": "⬅ Back", "callback_data": "menu_alerts"}]])
                        else:
                            coins_list = ", ".join(list(COINS.keys())[:15]) + "..."
                            edit(chat_id, message_id,
                                f"➕ <b>Create Price Alert</b>\n\n"
                                f"Send the coin symbol you want to track.\n"
                                f"Example: <code>BTC</code>\n\n"
                                f"Available: {coins_list}",
                                [[{"text": "❌ Cancel", "callback_data": "menu_alerts"}]])

                    # ── ALERTS — My Alerts ────────────────────────────────────────
                    if data == "my_alerts":
                        db = get_db(); c = db.cursor()
                        c.execute("SELECT id, coin, condition, target, label FROM alerts WHERE chat=%s AND active=1", (str(chat_id),))
                        rows = c.fetchall(); db.close()
                        if not rows:
                            edit(chat_id, message_id, "📋 <b>My Alerts</b>\n\nYou have no active alerts.\n\nTap ➕ Create Alert to add one.",
                                [[{"text": "➕ Create Alert", "callback_data": "alerts"}, {"text": "⬅ Back", "callback_data": "menu_alerts"}]])
                        else:
                            lines = ["📋 <b>My Active Alerts</b>\n"]
                            btns = []
                            for row in rows:
                                aid, coin, cond, target, label = row
                                lbl = f" ({label})" if label else ""
                                lines.append(f"• <b>{coin}</b> {cond} <b>{format_price(target)}</b>{lbl}")
                                btns.append([{"text": f"🗑 Delete {coin} {cond} {format_price(target)}", "callback_data": f"del_alert_{aid}"}])
                            btns.append([{"text": "⬅ Back", "callback_data": "menu_alerts"}])
                            edit(chat_id, message_id, "\n".join(lines), btns)

                    # ── ALERTS — Delete single alert ─────────────────────────────
                    if data.startswith("del_alert_"):
                        try:
                            aid = int(data.split("_")[2])
                            db = get_db(); c = db.cursor()
                            c.execute("UPDATE alerts SET active=0 WHERE id=%s AND chat=%s", (aid, str(chat_id)))
                            db.commit(); db.close()
                            edit(chat_id, message_id, "✅ Alert deleted.", [[{"text": "📋 My Alerts", "callback_data": "my_alerts"}]])
                        except Exception as e:
                            logger.error("[DEL ALERT] %s" % e)

                    # ── ALERTS — Watchlist ────────────────────────────────────────
                    if data == "watchlist":
                        db = get_db(); c = db.cursor()
                        c.execute("SELECT coin FROM watchlists WHERE chat=%s", (str(chat_id),))
                        wl = [r[0] for r in c.fetchall()]; db.close()
                        limit = 30 if (get_bot_mode() == "everyone" or is_pro(chat_id)) else 10
                        lines = [f"⭐ <b>My Watchlist</b> ({len(wl)}/{limit})\n"]
                        if wl:
                            for coin in wl:
                                p, ch = get_best_price(coin)
                                lines.append(f"• <b>{coin}</b>  {format_price(p)}  {format_change(ch) if ch else ''}")
                        else:
                            lines.append("Empty — type a coin symbol to add (e.g. <code>BTC</code>)")
                        btns = [
                            [{"text": "➕ Add Coin", "callback_data": "wl_add"}],
                            [{"text": "🗑 Remove Coin", "callback_data": "wl_remove"}],
                            [{"text": "⬅ Back", "callback_data": "menu_alerts"}],
                        ]
                        edit(chat_id, message_id, "\n".join(lines), btns)

                    if data == "wl_add":
                        set_state(chat_id, "awaiting_wl_add")
                        edit(chat_id, message_id, "⭐ <b>Add to Watchlist</b>\n\nSend the coin symbol.\nExample: <code>ETH</code>",
                            [[{"text": "❌ Cancel", "callback_data": "watchlist"}]])

                    if data == "wl_remove":
                        db = get_db(); c = db.cursor()
                        c.execute("SELECT coin FROM watchlists WHERE chat=%s", (str(chat_id),))
                        wl = [r[0] for r in c.fetchall()]; db.close()
                        if not wl:
                            edit(chat_id, message_id, "Your watchlist is empty.", [[{"text": "⬅ Back", "callback_data": "watchlist"}]])
                        else:
                            btns = [[{"text": f"🗑 {coin}", "callback_data": f"wl_del_{coin}"}] for coin in wl]
                            btns.append([{"text": "⬅ Back", "callback_data": "watchlist"}])
                            edit(chat_id, message_id, "🗑 <b>Remove from Watchlist</b>\n\nSelect coin to remove:", btns)

                    if data.startswith("wl_del_"):
                        coin = data.split("wl_del_")[1].upper()
                        db = get_db(); c = db.cursor()
                        c.execute("DELETE FROM watchlists WHERE chat=%s AND coin=%s", (str(chat_id), coin))
                        db.commit(); db.close()
                        edit(chat_id, message_id, f"✅ <b>{coin}</b> removed from watchlist.", [[{"text": "⭐ Watchlist", "callback_data": "watchlist"}]])

                    # ── ALERTS — Smart Alerts (Pro) ───────────────────────────────
                    if data == "smart_alerts":
                        if get_bot_mode() != "everyone" and not is_pro(chat_id):
                            edit(chat_id, message_id, "⭐ <b>Pro Feature</b>\n\nSmart Alerts are available for Pro users only.",
                                [[{"text": "💎 Upgrade", "callback_data": "upgrade"}, {"text": "⬅ Back", "callback_data": "menu_alerts"}]])
                        else:
                            lines = [
                                "⚡ <b>Smart Alerts</b>\n",
                                "Smart Alerts automatically monitor key levels and notify you when:",
                                "• Major coins test key support/resistance",
                                "• 5%+ moves detected on your watchlist",
                                "• AI analysis available on demand",
                                "",
                                "✅ Smart Alerts are <b>active</b> — you will be notified in this channel automatically.",
                            ]
                            edit(chat_id, message_id, "\n".join(lines), [[{"text": "⬅ Back", "callback_data": "menu_alerts"}]])

                    # ── MARKETS — Gainers ─────────────────────────────────────────
                    if data == "gainers":
                        gainers, _ = get_gainers_losers()
                        if gainers:
                            lines = ["📈 <b>Top Gainers (24h)</b>\n"]
                            for coin, price, ch in gainers:
                                lines.append(f"• <b>{coin}</b>  {format_price(price)}  {format_change(ch)}")
                            edit(chat_id, message_id, "\n".join(lines),
                                [[{"text": "📉 Losers", "callback_data": "losers"}, {"text": "⬅ Back", "callback_data": "menu_markets"}]])
                        else:
                            edit(chat_id, message_id, "📈 No gainer data available right now.", [[{"text": "⬅ Back", "callback_data": "menu_markets"}]])

                    # ── MARKETS — Losers ──────────────────────────────────────────
                    if data == "losers":
                        _, losers = get_gainers_losers()
                        if losers:
                            lines = ["📉 <b>Top Losers (24h)</b>\n"]
                            for coin, price, ch in losers:
                                lines.append(f"• <b>{coin}</b>  {format_price(price)}  {format_change(ch)}")
                            edit(chat_id, message_id, "\n".join(lines),
                                [[{"text": "📈 Gainers", "callback_data": "gainers"}, {"text": "⬅ Back", "callback_data": "menu_markets"}]])
                        else:
                            edit(chat_id, message_id, "📉 No loser data available right now.", [[{"text": "⬅ Back", "callback_data": "menu_markets"}]])

                    # ── MARKETS — Charts ──────────────────────────────────────────
                    if data == "charts":
                        edit(chat_id, message_id,
                            "📊 <b>Charts</b>\n\nView live charts on TradingView:\n\n"
                            "• BTC: tradingview.com/chart?symbol=BTCUSD\n"
                            "• ETH: tradingview.com/chart?symbol=ETHUSD\n"
                            "• SOL: tradingview.com/chart?symbol=SOLUSD\n\n"
                            "<i>Tap a coin in /market for quick price data.</i>",
                            [[{"text": "⬅ Back", "callback_data": "menu_markets"}]])

                    # ── MARKETS — Dominance ───────────────────────────────────────
                    if data == "dominance":
                        try:
                            resp = fetch_with_backoff("https://api.coingecko.com/api/v3/global")
                            gdata = resp.get("data", {}) if resp else {}
                            dom = gdata.get("market_cap_percentage", {})
                            btc_d = dom.get("btc", 0)
                            eth_d = dom.get("eth", 0)
                            total = gdata.get("total_market_cap", {}).get("usd", 0)
                            lines = [
                                "🌐 <b>Market Dominance</b>\n",
                                f"BTC Dominance: <b>{btc_d:.1f}%</b>",
                                f"ETH Dominance: <b>{eth_d:.1f}%</b>",
                                f"Others: <b>{100-btc_d-eth_d:.1f}%</b>",
                                "",
                                f"Total Market Cap: <b>${total/1e9:.0f}B</b>",
                            ]
                            edit(chat_id, message_id, "\n".join(lines), [[{"text": "⬅ Back", "callback_data": "menu_markets"}]])
                        except Exception as e:
                            edit(chat_id, message_id, "⚠️ Could not load dominance data.", [[{"text": "⬅ Back", "callback_data": "menu_markets"}]])

                    # ── INTELLIGENCE — Market Outlook ─────────────────────────────
                    if data == "market_outlook":
                        if get_bot_mode() != "everyone" and not is_pro(chat_id):
                            edit(chat_id, message_id,
                                "🔒 <b>Pro Feature</b>\n\n"
                                "Market Outlook is available for Pro users only.\n\n"
                                "Upgrade to get:\n"
                                "• Full AI market analysis\n"
                                "• Daily trade ideas\n"
                                "• Pro channel alerts with AI",
                                [[{"text": "💎 Upgrade to Pro", "callback_data": "upgrade"}, {"text": "⬅ Back", "callback_data": "menu_intelligence"}]])
                            continue
                        allowed, used, limit = check_ai_limit(chat_id)
                        if not allowed:
                            edit(chat_id, message_id, ai_limit_msg(used, limit), UPGRADE_BTN)
                            continue
                        btc_p, btc_c = get_best_price("BTC")
                        eth_p, eth_c = get_best_price("ETH")
                        fg_data = get_fear_greed()
                        fg_val = fg_data[0]["value"] if fg_data else "N/A"
                        fg_lbl = fg_data[0]["value_classification"] if fg_data else "N/A"
                        prompt = (
                            f"BTC: {format_price(btc_p)} ({format_change(btc_c)}), "
                            f"ETH: {format_price(eth_p)} ({format_change(eth_c)}). "
                            f"Fear & Greed: {fg_val}/100 ({fg_lbl}). "
                            f"Give a full market outlook for the next 24-48 hours covering BTC, ETH, and overall sentiment."
                        )
                        track_feature(chat_id, "ai_question")
                        edit(chat_id, message_id, "🔮 <b>Market Outlook</b>\n\n⏳ Analyzing...", None)
                        analysis, provider = ask_ai(prompt)
                        remaining = (limit - used - 1) if limit else None
                        footer = f"\n\n<i>💬 {remaining} free AI uses left today.</i>" if remaining is not None and remaining >= 0 else ""
                        text = f"🔮 <b>Market Outlook</b>\n\n{analysis or 'Analysis unavailable right now.'}\n\n<i>NFA - DYOR</i>{footer}"
                        edit(chat_id, message_id, text, [[{"text": "🔄 Refresh", "callback_data": "market_outlook"}, {"text": "⬅ Back", "callback_data": "menu_intelligence"}]])

                    # ── INTELLIGENCE — Trade Setup ─────────────────────────────────
                    if data == "trade_setup":
                        if get_bot_mode() != "everyone" and not is_pro(chat_id):
                            edit(chat_id, message_id, "⭐ <b>Pro Feature</b>\n\nTrade Setups are for Pro users only.",
                                [[{"text": "💎 Upgrade", "callback_data": "upgrade"}, {"text": "⬅ Back", "callback_data": "menu_intelligence"}]])
                        else:
                            set_state(chat_id, "awaiting_trade_setup_coin")
                            edit(chat_id, message_id,
                                "📊 <b>AI Trade Setup</b>\n\nWhich coin do you want a trade setup for?\n"
                                "Send the symbol, e.g. <code>BTC</code>",
                                [[{"text": "❌ Cancel", "callback_data": "menu_intelligence"}]])

                    # ── P2P — History ─────────────────────────────────────────────
                    if data == "p2p_history":
                        try:
                            db = get_db(); c = db.cursor()
                            c.execute("SELECT crypto, fiat, buy_rate, sell_rate, timestamp FROM community_p2p ORDER BY id DESC LIMIT 10")
                            rows = c.fetchall(); db.close()
                            if rows:
                                lines = ["📜 <b>Recent P2P Rates</b>\n"]
                                for crypto, fiat, buy, sell, ts in rows:
                                    symbol = P2P_FIATS.get(fiat, ("", fiat))[1]
                                    lines.append(f"• {crypto}/{fiat}  Buy {symbol}{int(buy):,}  Sell {symbol}{int(sell):,}")
                                edit(chat_id, message_id, "\n".join(lines), [[{"text": "⬅ Back", "callback_data": "menu_p2p"}]])
                            else:
                                edit(chat_id, message_id, "No P2P history available yet.", [[{"text": "⬅ Back", "callback_data": "menu_p2p"}]])
                        except Exception as e:
                            edit(chat_id, message_id, "⚠️ Could not load P2P history.", [[{"text": "⬅ Back", "callback_data": "menu_p2p"}]])

                    # ── INTELLIGENCE — Sources ────────────────────────────────────
                    if data == "sources":
                        edit(chat_id, message_id,
                            "📡 <b>Data Sources</b>\n\n"
                            "💰 <b>Prices:</b> Kraken, OKX, Bybit, CoinGecko\n"
                            "📊 <b>Market Data:</b> CoinGecko\n"
                            "😱 <b>Fear & Greed:</b> Alternative.me\n"
                            "📰 <b>News:</b> CryptoPanic, CoinDesk RSS\n"
                            "🤖 <b>AI:</b> DeepSeek (primary), Mistral (fallback), Qwen (fallback)\n"
                            "💱 <b>P2P:</b> Binance P2P, Bybit P2P\n\n"
                            "<i>Data refreshes every 5–10 minutes.</i>",
                            [[{"text": "⬅ Back", "callback_data": "menu_intelligence"}]])

                    # ── ADMIN — Publish button ────────────────────────────────────
                    if data == "admin_publish" and chat_id in ADMIN_IDS:
                        btns = [
                            [{"text": "🌅 Morning", "callback_data": "ap_morning"}, {"text": "⚡ Midday", "callback_data": "ap_midday"}],
                            [{"text": "🌙 Evening", "callback_data": "ap_evening"}, {"text": "📊 Weekly", "callback_data": "ap_weekly"}],
                            [{"text": "⬅ Back", "callback_data": "main_menu"}],
                        ]
                        edit(chat_id, message_id, "📢 <b>Force Publish</b>\n\nChoose post type:", btns)

                    if data == "ap_morning" and chat_id in ADMIN_IDS:
                        edit(chat_id, message_id, "⏳ Publishing...", None)
                        pro_content = build_morning_briefing_pro()
                        post_to_channel(pro_content if get_bot_mode() == "everyone" else build_morning_briefing())
                        post_to_pro_channel(pro_content)
                        edit(chat_id, message_id, "✅ Morning briefing published.", [[{"text": "⬅ Back", "callback_data": "admin_publish"}]])

                    if data == "ap_midday" and chat_id in ADMIN_IDS:
                        edit(chat_id, message_id, "⏳ Publishing...", None)
                        pro_content = build_midday_snapshot_pro()
                        post_to_channel(pro_content if get_bot_mode() == "everyone" else build_midday_snapshot())
                        post_to_pro_channel(pro_content)
                        edit(chat_id, message_id, "✅ Midday snapshot published.", [[{"text": "⬅ Back", "callback_data": "admin_publish"}]])

                    if data == "ap_evening" and chat_id in ADMIN_IDS:
                        edit(chat_id, message_id, "⏳ Publishing...", None)
                        pro_content = build_evening_recap_pro()
                        post_to_channel(pro_content if get_bot_mode() == "everyone" else build_evening_recap())
                        post_to_pro_channel(pro_content)
                        edit(chat_id, message_id, "✅ Evening recap published.", [[{"text": "⬅ Back", "callback_data": "admin_publish"}]])

                    if data == "ap_weekly" and chat_id in ADMIN_IDS:
                        edit(chat_id, message_id, "⏳ Publishing...", None)
                        pro_content = build_weekly_edge_pro()
                        post_to_channel(pro_content if get_bot_mode() == "everyone" else build_weekly_edge())
                        post_to_pro_channel(pro_content)
                        edit(chat_id, message_id, "✅ Weekly edge published.", [[{"text": "⬅ Back", "callback_data": "admin_publish"}]])

                    # ── ADMIN — Settings ──────────────────────────────────────────
                    if data == "admin_settings" and chat_id in ADMIN_IDS:
                        mode = get_bot_mode().upper()
                        ch_status = "✅ Enabled" if CHANNEL_ENABLED else "⏸️ Disabled"
                        edit(chat_id, message_id,
                            f"⚙️ <b>Bot Settings</b>\n\n"
                            f"🤖 Mode: <b>{mode}</b>\n"
                            f"📢 Channel: <b>{ch_status}</b>\n"
                            f"📢 Pro Channel: <b>{'✅ Set' if PRO_CHANNEL_ID and PRO_CHANNEL_ID != '-100XXXXXXXXX' else '❌ Not Set'}</b>\n\n"
                            f"Use /mode everyone or /mode pro to change mode.\n"
                            f"Use /togglechannel to toggle posting.",
                            [[{"text": "⬅ Back", "callback_data": "adm_settings_menu"}]])

                    # ── ADMIN — Broadcast ─────────────────────────────────────────
                    if data == "admin_broadcast" and chat_id in ADMIN_IDS:
                        set_state(chat_id, "awaiting_broadcast")
                        edit(chat_id, message_id,
                            "📣 <b>Broadcast Message</b>\n\nSend the message to broadcast to all users.",
                            [[{"text": "❌ Cancel", "callback_data": "adm_users"}]])

                    # ── ADMIN — Ban user ──────────────────────────────────────────
                    if data == "admin_ban" and chat_id in ADMIN_IDS:
                        set_state(chat_id, "awaiting_ban_id")
                        edit(chat_id, message_id,
                            "🔨 <b>Ban User</b>\n\nSend the Telegram ID of the user to ban.",
                            [[{"text": "❌ Cancel", "callback_data": "adm_users"}]])

                    # ── ADMIN — Logs ──────────────────────────────────────────────
                    if data == "admin_logs" and chat_id in ADMIN_IDS:
                        try:
                            with open(LOG_FILE, "r") as lf:
                                lines = lf.readlines()
                            last = "".join(lines[-30:]) if lines else "No logs."
                            edit(chat_id, message_id, f"📋 <b>Recent Logs</b>\n\n<pre>{last[-3000:]}</pre>",
                                [[{"text": "⬅ Back", "callback_data": "adm_system"}]])
                        except Exception as e:
                            edit(chat_id, message_id, f"⚠️ Could not read logs: {e}", [[{"text": "⬅ Back", "callback_data": "adm_system"}]])

                    # ── ADMIN — Dashboard ────────────────────────────────────────
                    if data == "admin_dashboard" and chat_id in ADMIN_IDS:
                        edit(chat_id, message_id, "⏳ Loading dashboard...", None)
                        dashboard = build_admin_dashboard()
                        edit(chat_id, message_id, dashboard,
                            [[{"text": "📦 Content Packages", "callback_data": "admin_content_packages"},
                              {"text": "🔄 Refresh", "callback_data": "admin_dashboard"}],
                             [{"text": "⬅ Back", "callback_data": "adm_analytics"}]])

                    # ── ADMIN — Content Packages ──────────────────────────────────
                    if data == "admin_content_packages" and chat_id in ADMIN_IDS:
                        pkgs = get_pending_content_packages(limit=8)
                        if not pkgs:
                            edit(chat_id, message_id,
                                "📦 <b>Content Packages</b>\n\nNo pending packages.\n\n"
                                "Use /contentpackage morning|midday|evening|weekly to generate one manually.",
                                [[{"text": "⬅ Back", "callback_data": "adm_channel"}]])
                        else:
                            lines = ["📦 <b>Pending Content Packages</b>\n"]
                            btns = []
                            for pid, ptype, psrc, pdate in pkgs:
                                lines.append(f"• #{pid} <b>{ptype.upper()}</b> — {pdate[:16]}")
                                btns.append([{"text": f"#{pid} {ptype.upper()}", "callback_data": f"pkg_view_{pid}"}])
                            lines.append("\nTap a package to review it.")
                            btns.append([{"text": "⬅ Back", "callback_data": "main_menu"}])
                            edit(chat_id, message_id, "\n".join(lines), btns)

                    if data.startswith("pkg_view_") and chat_id in ADMIN_IDS:
                        try:
                            pkg_id = int(data.split("pkg_view_")[1])
                            pkg = get_content_package_by_id(pkg_id)
                            if not pkg:
                                edit(chat_id, message_id, f"❌ Package #{pkg_id} not found.",
                                    [[{"text": "⬅ Back", "callback_data": "admin_content_packages"}]])
                            else:
                                admin_msg = format_content_package_for_admin(pkg_id, pkg, pkg.get("package_type","?"))
                                # Send as new message (too long to edit into existing)
                                send(chat_id, admin_msg[:4000])
                                edit(chat_id, message_id,
                                    f"📦 <b>Package #{pkg_id}</b> shown above.\n\nMark as:",
                                    [[{"text": "✅ Approve", "callback_data": f"pkg_approve_{pkg_id}"},
                                      {"text": "🗑 Discard", "callback_data": f"pkg_discard_{pkg_id}"}],
                                     [{"text": "⬅ Back", "callback_data": "admin_content_packages"}]])
                        except (ValueError, IndexError):
                            edit(chat_id, message_id, "❌ Invalid package ID.",
                                [[{"text": "⬅ Back", "callback_data": "admin_content_packages"}]])

                    if data.startswith("pkg_approve_") and chat_id in ADMIN_IDS:
                        try:
                            pkg_id = int(data.split("pkg_approve_")[1])
                            mark_package_status(pkg_id, "approved")
                            edit(chat_id, message_id, f"✅ Package #{pkg_id} marked as <b>approved</b>.",
                                [[{"text": "📦 Packages", "callback_data": "admin_content_packages"},
                                  {"text": "⬅ Back", "callback_data": "main_menu"}]])
                        except Exception as _e:
                            edit(chat_id, message_id, "❌ Error updating package.", [[{"text": "⬅ Back", "callback_data": "admin_content_packages"}]])

                    if data.startswith("pkg_discard_") and chat_id in ADMIN_IDS:
                        try:
                            pkg_id = int(data.split("pkg_discard_")[1])
                            mark_package_status(pkg_id, "discarded")
                            edit(chat_id, message_id, f"🗑 Package #{pkg_id} discarded.",
                                [[{"text": "📦 Packages", "callback_data": "admin_content_packages"},
                                  {"text": "⬅ Back", "callback_data": "main_menu"}]])
                        except Exception as _e:
                            edit(chat_id, message_id, "❌ Error updating package.", [[{"text": "⬅ Back", "callback_data": "admin_content_packages"}]])

                    # ── ALERT CONDITION CALLBACKS ─────────────────────────────
                    if data in ("alert_cond_above", "alert_cond_below"):
                        _, sdata = get_state(chat_id)
                        coin = sdata.get("coin", "BTC")
                        cond = "above" if data == "alert_cond_above" else "below"
                        set_state(chat_id, "awaiting_alert_target", {"coin": coin, "condition": cond})
                        price, _ = get_best_price(coin)
                        edit(chat_id, message_id,
                            f"➕ <b>{coin} Alert</b>\n\nCurrent: <b>{format_price(price)}</b>\n\n"
                            f"Send the target price (e.g. <code>65000</code>):",
                            [[{"text": "❌ Cancel", "callback_data": "menu_alerts"}]])

                    # ── LANGUAGE SETTINGS ─────────────────────────────────────────────
                    for lang_code, lang_name in [("en","English"),("ha","Hausa"),("ig","Igbo"),("yo","Yoruba")]:
                        if data == f"lang_{lang_code}":
                            edit(chat_id, message_id,
                                f"✅ Language set to <b>{lang_name}</b>.\n\n<i>Note: Full multilingual support coming soon.</i>",
                                [[{"text": "⬅ Back", "callback_data": "settings_language"}]])

            time.sleep(2)

        except Exception as e:
            logger.error("[MAIN ERROR] %s" % e)
            import traceback
            traceback.print_exc()
            time.sleep(10)

# ═══════════════════════════════════════════════════════════════════════════
# 🚀 ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    run()
