"""
Market Pulse Bot  —  v15 (FIXED)
AI-powered crypto intelligence platform for Nigerian traders.

FIXES APPLIED:
- Added missing functions: show_p2p_alert_new, prompt_p2p_alert_value
- Fixed function name typos: register_referral → record_referral
- Fixed show_coin_search_prompt → show_coin_search
- Fixed handle_p2p_alert_value → handle_p2p_alert_target
- Removed duplicate build_summary_post
- Added database connection context managers
- Added proper error handling for all DB operations
- Added database indexes for performance
- Added /help command handler
- Added admin alert management
- Added user appeal system
- Added portfolio export to CSV
- Enhanced performance with connection pooling
"""

import requests
import time
import sqlite3
import json
import io
import os
import xml.etree.ElementTree as _ET
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Optional, Dict, List, Tuple, Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ── ENV FILE LOADER ───────────────────────────────────────────────────────────
def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
_load_env()

# ── API KEYS ──────────────────────────────────────────────────────────────────
BOT_TOKEN         = os.environ.get("BOT_TOKEN",         "")
DEEPSEEK_KEY      = os.environ.get("DEEPSEEK_KEY",      "")
MISTRAL_KEY       = os.environ.get("MISTRAL_KEY",       "")
QWEN_KEY          = os.environ.get("QWEN_KEY",          "")
CRYPTOCOMPARE_KEY = os.environ.get("CRYPTOCOMPARE_KEY", "")
ADMIN_CODE        = os.environ.get("ADMIN_CODE",        "")

# ── ADMIN CONFIG ──────────────────────────────────────────────────────────────
ADMIN_IDS = {8212124930}

# ── CHANNEL CONFIG ────────────────────────────────────────────────────────────
CHANNEL_ID      = "-1004495003791"
CHANNEL_ENABLED = True
WAT_OFFSET      = 1

SCHEDULE = {
    "morning_hour_wat":        7,
    "midday_hour_wat":         12,
    "evening_hour_wat":        21,
    "p2p_morning_hour":        10,
    "p2p_evening_hour":        18,
    "gainers_hour_wat":        14,
    "trade_setup_hour_wat":    8,
    "whale_check_seconds":     1800,
    "breakout_check_seconds":  600,
    "funding_check_seconds":   3600,
    "liquidation_check_seconds":3600,
    "arbitrage_check_seconds": 7200,
    "news_interval_seconds":   21600,
    "opportunity_seconds":     21600,
    "bigmove_pct":             3.0,
    "whale_pct":               3.0,
    "funding_extreme_pct":     0.05,
    "liquidation_min_usd_m":   10,
    "arbitrage_min_pct":       0.3,
    "admin_digest_hour_wat":   8,
    "weekly_edge_hour_wat":    18,
    "weekly_auto_post_hour":   21,
}

# ── COINS ─────────────────────────────────────────────────────────────────────
COINS = {
    "BTC":    ("XBTUSD",   "bitcoin"),
    "ETH":    ("ETHUSD",   "ethereum"),
    "SOL":    ("SOLUSD",   "solana"),
    "BNB":    ("BNBUSD",   "binancecoin"),
    "XRP":    ("XRPUSD",   "ripple"),
    "DOGE":   ("DOGEUSD",  "dogecoin"),
    "ADA":    ("ADAUSD",   "cardano"),
    "TRX":    ("TRXUSD",   "tron"),
    "AVAX":   ("AVAXUSD",  "avalanche-2"),
    "LINK":   ("LINKUSD",  "chainlink"),
    "DOT":    ("DOTUSD",   "polkadot"),
    "POL":    ("POLUSD",   "matic-network"),
    "LTC":    ("LTCUSD",   "litecoin"),
    "UNI":    ("UNIUSD",   "uniswap"),
    "ATOM":   ("ATOMUSD",  "cosmos"),
    "NEAR":   ("NEARUSD",  "near"),
    "ICP":    ("ICPUSD",   "internet-computer"),
    "SHIB":   (None,       "shiba-inu"),
    "APT":    (None,       "aptos"),
    "ARB":    (None,       "arbitrum"),
    "OP":     (None,       "optimism"),
    "SUI":    (None,       "sui"),
    "INJ":    (None,       "injective-protocol"),
    "FET":    (None,       "fetch-ai"),
    "FIL":    ("FILUSD",   "filecoin"),
    "RENDER": (None,       "render-token"),
    "WLD":    (None,       "worldcoin-wld"),
    "USDT":   ("USDTUSD",  "tether"),
    "USDC":   ("USDCUSD",  "usd-coin"),
}

def kraken_pair(coin): return COINS[coin][0]
def coin_key(coin):    return COINS[coin][1]

# ── P2P CONFIG ────────────────────────────────────────────────────────────────
P2P_CRYPTOS = ["USDT", "BTC", "ETH", "BNB", "USDC", "SOL", "XRP"]

P2P_FIATS = {
    "NGN": ("Nigerian Naira",     "₦"),
    "GHS": ("Ghanaian Cedi",      "GHc"),
    "KES": ("Kenyan Shilling",    "KSh"),
    "ZAR": ("South African Rand", "R"),
    "UGX": ("Ugandan Shilling",   "USh"),
    "TZS": ("Tanzanian Shilling", "TSh"),
    "EGP": ("Egyptian Pound",     "E£"),
    "MAD": ("Moroccan Dirham",    "MAD"),
    "XOF": ("West African CFA",   "CFA"),
    "USD": ("US Dollar",          "$"),
    "GBP": ("British Pound",      "£"),
    "EUR": ("Euro",               "€"),
    "AED": ("UAE Dirham",         "AED"),
    "CNY": ("Chinese Yuan",       "¥"),
    "INR": ("Indian Rupee",       "₹"),
}

# ── CHART TIMEFRAMES ──────────────────────────────────────────────────────────
TIMEFRAMES = {
    "1H":  (1,    12,  "hm"),
    "6H":  (6,    36,  "hm"),
    "1D":  (24,   48,  "hm"),
    "3D":  (72,   36,  "dhm"),
    "1W":  (168,  42,  "dhm"),
    "1M":  (720,  30,  "date"),
    "3M":  (2160, 30,  "date"),
    "1Y":  (8760, 52,  "date"),
}

CHART_MAX_POINTS      = 1500
CHART_FALLBACK_POINTS = 200
DB_PATH               = "marketpulse.db"

# ── DATABASE CONTEXT MANAGER ──────────────────────────────────────────────────
@contextmanager
def get_db_connection():
    """Context manager for database connections - ensures proper cleanup."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

@contextmanager
def get_db_cursor():
    """Context manager for database cursors with automatic commit/rollback."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

# ── FORMATTING ────────────────────────────────────────────────────────────────
def format_price(v):
    if v >= 1:       return "$%.2f" % v
    elif v >= 0.01:  return "$%.4f" % v
    elif v >= 0.0001:return "$%.6f" % v
    else:            return "$%.8f" % v

def format_change(pct):
    if pct is None: return "N/A"
    sign = "+" if pct >= 0 else ""
    return "%s%.2f%%" % (sign, pct)

# ── CHART RENDERER ────────────────────────────────────────────────────────────
def render_chart_png(coin, timeframe, ts_fmt, rows):
    """Render a price history line chart as PNG bytes."""
    try:
        prices = [float(p) for p, _ in rows]
        times  = [datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") for _, ts in rows]

        chg = (prices[-1] - prices[0]) / prices[0] * 100 if prices[0] else 0
        up = chg >= 0
        line_color = "#26a69a" if up else "#ef5350"
        bg_color   = "#0d1117"
        grid_color = "#21262d"
        text_color = "#8b949e"

        plt.style.use("dark_background")
        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(bg_color)

        ax.plot(times, prices, color=line_color, linewidth=1.8, zorder=3)
        ax.fill_between(times, prices, min(prices), color=line_color, alpha=0.12, zorder=2)

        ax.grid(True, color=grid_color, linewidth=0.6, zorder=1)
        for spine in ax.spines.values():
            spine.set_color(grid_color)
        ax.tick_params(colors=text_color, labelsize=9)

        if ts_fmt == "hm":
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        elif ts_fmt == "dhm":
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d %H:%M"))
        else:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        fig.autofmt_xdate(rotation=30)

        ax.yaxis.set_major_formatter(plt.FuncFormatter(
            lambda v, _: format_price(v) if isinstance(v, (int, float)) else ""))

        sign = "+" if chg >= 0 else ""
        ax.set_title("%s — %s    %s%.2f%%" % (coin, timeframe, sign, chg),
                     color="white", fontsize=13, fontweight="bold", loc="left", pad=14)

        span = times[-1] - times[0]
        pad  = span * 0.08 if span.total_seconds() > 0 else timedelta(minutes=5)
        ax.set_xlim(times[0], times[-1] + pad)
        ax.annotate(format_price(prices[-1]), xy=(times[-1], prices[-1]),
                    xytext=(8, 0), textcoords="offset points",
                    color=line_color, fontsize=10, fontweight="bold", va="center")

        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception as e:
        print("[CHART ERROR] %s" % e)
        plt.close("all")
        return None

# ── HTTP HELPERS ──────────────────────────────────────────────────────────────
def request_json(method, url, params=None, json_data=None, timeout=10,
                 retries=3, backoff=1.5):
    last_exc = None
    for attempt in range(retries):
        try:
            if method == "GET":
                r = requests.get(url, params=params, timeout=timeout)
            else:
                r = requests.post(url, json=json_data, timeout=timeout)
            if r.status_code == 429:
                wait = 30 * (attempt + 1)
                source = url.split("/")[2]
                print("[RATE LIMIT] %s — waiting %ds before retry" % (source, wait))
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    print("[RETRY FAILED] %s %s -> %s" % (method, url, last_exc))
    return None

# ── DATABASE INITIALIZATION ──────────────────────────────────────────────────
def init_db():
    """Initialize database with all tables and indexes."""
    with get_db_connection() as conn:
        c = conn.cursor()
        
        # Drop tables with mismatched schema
        schema = {
            "history":            {"id", "coin", "price", "timestamp"},
            "alerts":             {"id", "chat", "coin", "condition", "target", "active", "label"},
            "user_states":        {"chat", "state", "data", "updated_at"},
            "users":              {"chat", "username", "first_name", "first_seen", "last_seen"},
            "watchlists":         {"id", "chat", "coin"},
            "portfolio":          {"id", "chat", "coin", "amount", "buy_price", "added_at"},
            "events":             {"id", "chat", "action", "timestamp"},
            "p2p_alerts":         {"id", "chat", "crypto", "fiat", "condition", "target", "active"},
            "referrals":          {"id", "referrer_chat", "referred_chat", "joined_at"},
            "portfolio_snapshots":{"id", "chat", "value_usd", "timestamp"},
            "analytics":          {"id", "chat", "feature", "timestamp", "day"},
            "community_p2p":      {"id", "chat", "crypto", "fiat", "buy_rate", "sell_rate",
                                   "exchange", "timestamp", "weight", "status",
                                   "confirmations", "spot_rate", "expires_at"},
            "rate_confirmations": {"id", "rate_id", "chat", "timestamp"},
            "pro_users":          {"id", "chat", "granted_at", "granted_by", "active"},
            "weekly_data":        {"id", "week_start", "data_json", "published", "created_at"},
            "rate_submissions":   {"chat", "submissions_today", "strikes_today",
                                   "blocked_until", "last_submission", "total_verified",
                                   "trust_level", "p2p_used", "onboarded", "last_prompted"},
            "ai_cache":           {"id", "question", "answer", "timestamp"},
            "callback_limits":    {"chat", "count", "window_start", "blocked_until"},
            "appeals":            {"id", "chat", "reason", "status", "created_at", "resolved_at"},
        }
        
        for table, expected in schema.items():
            c.execute("PRAGMA table_info(%s)" % table)
            existing = {row[1] for row in c.fetchall()}
            if existing and not expected.issubset(existing):
                print("Migrating %s..." % table)
                c.execute("DROP TABLE %s" % table)
                conn.commit()

        # Create all tables
        c.executescript("""
        CREATE TABLE IF NOT EXISTS history (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            coin      TEXT NOT NULL,
            price     REAL NOT NULL,
            timestamp TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat      TEXT NOT NULL,
            coin      TEXT NOT NULL,
            condition TEXT NOT NULL,
            target    REAL NOT NULL,
            active    INTEGER DEFAULT 1,
            label     TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS user_states (
            chat       TEXT PRIMARY KEY,
            state      TEXT,
            data       TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS users (
            chat       TEXT PRIMARY KEY,
            username   TEXT,
            first_name TEXT,
            first_seen TEXT,
            last_seen  TEXT
        );
        CREATE TABLE IF NOT EXISTS watchlists (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            chat TEXT NOT NULL,
            coin TEXT NOT NULL,
            UNIQUE(chat, coin)
        );
        CREATE TABLE IF NOT EXISTS portfolio (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat      TEXT NOT NULL,
            coin      TEXT NOT NULL,
            amount    REAL NOT NULL,
            buy_price REAL NOT NULL,
            added_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat      TEXT NOT NULL,
            action    TEXT NOT NULL,
            timestamp TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS p2p_alerts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat      TEXT NOT NULL,
            crypto    TEXT NOT NULL,
            fiat      TEXT NOT NULL,
            condition TEXT NOT NULL,
            target    REAL NOT NULL,
            active    INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS referrals (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_chat TEXT NOT NULL,
            referred_chat TEXT NOT NULL,
            joined_at     TEXT NOT NULL,
            UNIQUE(referred_chat)
        );
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat      TEXT NOT NULL,
            value_usd REAL NOT NULL,
            timestamp TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS analytics (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat      TEXT NOT NULL,
            feature   TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            day       TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS community_p2p (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            chat         TEXT NOT NULL,
            crypto       TEXT NOT NULL,
            fiat         TEXT NOT NULL,
            buy_rate     REAL NOT NULL,
            sell_rate    REAL NOT NULL,
            exchange     TEXT NOT NULL,
            timestamp    TEXT NOT NULL,
            weight       INTEGER DEFAULT 1,
            status       TEXT DEFAULT 'pending',
            confirmations INTEGER DEFAULT 0,
            spot_rate    REAL,
            expires_at   TEXT
        );
        CREATE TABLE IF NOT EXISTS rate_confirmations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            rate_id    INTEGER NOT NULL,
            chat       TEXT NOT NULL,
            timestamp  TEXT NOT NULL,
            UNIQUE(rate_id, chat)
        );
        CREATE TABLE IF NOT EXISTS pro_users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            chat       TEXT NOT NULL UNIQUE,
            granted_at TEXT NOT NULL,
            granted_by TEXT NOT NULL,
            active     INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS weekly_data (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            data_json  TEXT NOT NULL,
            published  INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rate_submissions (
            chat              TEXT PRIMARY KEY,
            submissions_today INTEGER DEFAULT 0,
            strikes_today     INTEGER DEFAULT 0,
            blocked_until     TEXT,
            last_submission   TEXT,
            total_verified    INTEGER DEFAULT 0,
            trust_level       INTEGER DEFAULT 1,
            p2p_used          INTEGER DEFAULT 0,
            onboarded         INTEGER DEFAULT 0,
            last_prompted     TEXT
        );
        CREATE TABLE IF NOT EXISTS ai_cache (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            question  TEXT NOT NULL,
            answer    TEXT NOT NULL,
            timestamp TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS callback_limits (
            chat       TEXT PRIMARY KEY,
            count      INTEGER DEFAULT 0,
            window_start TEXT NOT NULL,
            blocked_until TEXT
        );
        CREATE TABLE IF NOT EXISTS appeals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat        TEXT NOT NULL,
            reason      TEXT NOT NULL,
            status      TEXT DEFAULT 'pending',
            created_at  TEXT NOT NULL,
            resolved_at TEXT
        );
        """)
        
        # Add missing columns safely
        safe_alters = [
            "ALTER TABLE alerts ADD COLUMN label TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN message_count INTEGER DEFAULT 0",
            "ALTER TABLE referrals ADD COLUMN counted INTEGER DEFAULT 0",
        ]
        for stmt in safe_alters:
            try:
                c.execute(stmt)
                conn.commit()
            except Exception:
                pass
        
        # Create indexes for performance
        c.executescript("""
        CREATE INDEX IF NOT EXISTS idx_history_coin_timestamp ON history(coin, timestamp);
        CREATE INDEX IF NOT EXISTS idx_community_p2p_crypto_fiat_status ON community_p2p(crypto, fiat, status);
        CREATE INDEX IF NOT EXISTS idx_community_p2p_timestamp ON community_p2p(timestamp);
        CREATE INDEX IF NOT EXISTS idx_alerts_chat_active ON alerts(chat, active);
        CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen);
        CREATE INDEX IF NOT EXISTS idx_analytics_chat_day ON analytics(chat, day);
        CREATE INDEX IF NOT EXISTS idx_portfolio_chat ON portfolio(chat);
        CREATE INDEX IF NOT EXISTS idx_watchlists_chat ON watchlists(chat);
        """)
        
        conn.commit()
    print("Database ready with indexes")

def track(chat_id, feature):
    """Track user feature usage."""
    try:
        with get_db_cursor() as c:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            day = datetime.now().strftime("%Y-%m-%d")
            c.execute("INSERT INTO analytics (chat, feature, timestamp, day) VALUES (?,?,?,?)",
                      (str(chat_id), feature, now, day))
    except Exception as e:
        print("[TRACK ERROR] %s" % e)

# ── PRO SYSTEM ────────────────────────────────────────────────────────────────
def is_pro(chat_id):
    """Check if user has active Pro subscription."""
    if chat_id in ADMIN_IDS:
        return True
    try:
        with get_db_cursor() as c:
            c.execute("SELECT active FROM pro_users WHERE chat=? AND active=1", (str(chat_id),))
            row = c.fetchone()
            return bool(row)
    except Exception:
        return False

def grant_pro(chat_id, granted_by):
    with get_db_cursor() as c:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT OR REPLACE INTO pro_users (chat, granted_at, granted_by, active) "
                  "VALUES (?,?,?,1)", (str(chat_id), now, str(granted_by)))

def revoke_pro(chat_id):
    with get_db_cursor() as c:
        c.execute("UPDATE pro_users SET active=0 WHERE chat=?", (str(chat_id),))

def pro_gate(chat_id, message_id, feature_name):
    """Show Pro upgrade prompt."""
    if is_pro(chat_id):
        return True
    edit(chat_id, message_id,
         "⭐ <b>Market Pulse Pro</b>\n\n"
         "<b>%s</b> is a Pro feature.\n\n"
         "Upgrade to Pro and get:\n"
         "• Real community P2P rates\n"
         "• Unlimited Ask AI\n"
         "• Instant price alerts\n"
         "• VIP channel access\n"
         "• Portfolio AI analysis\n"
         "• Arbitrage opportunities\n\n"
         "Type /upgrade for pricing and payment details." % feature_name,
         [[{"text": "💎 Upgrade to Pro", "callback_data": "upgrade"},
           {"text": "⬅ Back",           "callback_data": "main_menu"}]])
    return False

# ── ADMIN COMMAND VERIFICATION ────────────────────────────────────────────────
def verify_admin(chat_id, code):
    """Returns True only if chat_id is admin AND code matches ADMIN_CODE."""
    if chat_id not in ADMIN_IDS:
        return False
    if not ADMIN_CODE:
        return True
    return code.strip() == ADMIN_CODE.strip()

# ── COMMUNITY P2P — FULL ANTI-MANIPULATION SYSTEM ────────────────────────────
WHALE_EXCLUDED      = {"USDT", "USDC"}
P2P_MAX_DEVIATION   = 0.20
P2P_CONSENSUS_PCT   = 0.15
P2P_CONSENSUS_NEED  = 2
P2P_PENDING_HOURS   = 2
P2P_VALIDITY_HOURS  = 4
P2P_MAX_PER_HOUR    = 1
P2P_STRIKE_LIMIT    = 3
P2P_BLOCK_HOURS     = 24
FREE_ALERT_LIMIT     = 3
PRO_ALERT_LIMIT      = 20
FREE_WATCHLIST_LIMIT = 10
PRO_WATCHLIST_LIMIT  = 30
FREE_PORTFOLIO_LIMIT = 10
PRO_PORTFOLIO_LIMIT  = 30
FREE_SEARCH_PER_HOUR = 5
AI_CACHE_MINUTES     = 60

def get_user_trust(chat_id):
    """Get user trust level and block status."""
    if chat_id in ADMIN_IDS:
        return {"trust": 10, "blocked": False, "strikes": 0, "verified": 999,
                "last_submission": None, "submissions_today": 0}
    try:
        with get_db_cursor() as c:
            c.execute("SELECT trust_level, strikes_today, blocked_until, total_verified, "
                      "last_submission, submissions_today FROM rate_submissions WHERE chat=?",
                      (str(chat_id),))
            row = c.fetchone()
            if not row:
                return {"trust": 1, "blocked": False, "strikes": 0, "verified": 0,
                        "last_submission": None, "submissions_today": 0}
            trust, strikes, blocked_until, verified, last_sub, subs_today = row
            now = datetime.now()
            is_blocked = bool(blocked_until and datetime.strptime(
                blocked_until, "%Y-%m-%d %H:%M:%S") > now)
            return {"trust": trust or 1, "blocked": is_blocked,
                    "strikes": strikes or 0, "verified": verified or 0,
                    "last_submission": last_sub, "submissions_today": subs_today or 0}
    except Exception as e:
        print("[GET_USER_TRUST ERROR] %s" % e)
        return {"trust": 1, "blocked": False, "strikes": 0, "verified": 0,
                "last_submission": None, "submissions_today": 0}

def update_trust_level(chat_id, verified_count):
    """Update user trust level based on verified submissions."""
    if chat_id in ADMIN_IDS:
        return 10
    trust = 3 if verified_count >= 20 else (2 if verified_count >= 5 else 1)
    with get_db_cursor() as c:
        c.execute("INSERT INTO rate_submissions (chat, trust_level, total_verified) "
                  "VALUES (?,?,?) ON CONFLICT(chat) DO UPDATE SET trust_level=?, total_verified=?",
                  (str(chat_id), trust, verified_count, trust, verified_count))
    return trust

def record_submission_attempt(chat_id, success):
    """Record a P2P rate submission attempt (success or failure)."""
    if chat_id in ADMIN_IDS:
        return
    try:
        with get_db_cursor() as c:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("SELECT strikes_today, submissions_today FROM rate_submissions WHERE chat=?",
                      (str(chat_id),))
            row = c.fetchone()
            strikes = (row[0] or 0) if row else 0
            subs = (row[1] or 0) if row else 0
            if not success:
                strikes += 1
                blocked_until = None
                if strikes >= P2P_STRIKE_LIMIT:
                    blocked_until = (datetime.now() + timedelta(hours=P2P_BLOCK_HOURS)
                                   ).strftime("%Y-%m-%d %H:%M:%S")
                c.execute("INSERT INTO rate_submissions (chat, strikes_today, submissions_today, "
                          "blocked_until, last_submission) VALUES (?,?,?,?,?) ON CONFLICT(chat) "
                          "DO UPDATE SET strikes_today=?, submissions_today=?, "
                          "blocked_until=?, last_submission=?",
                          (str(chat_id), strikes, subs, blocked_until, now,
                           strikes, subs, blocked_until, now))
            else:
                subs += 1
                c.execute("INSERT INTO rate_submissions (chat, submissions_today, last_submission) "
                          "VALUES (?,?,?) ON CONFLICT(chat) DO UPDATE SET "
                          "submissions_today=?, last_submission=?",
                          (str(chat_id), subs, now, subs, now))
    except Exception as e:
        print("[RECORD_SUBMISSION_ATTEMPT ERROR] %s" % e)

def validate_p2p_rate(crypto, fiat, buy_rate, sell_rate):
    """Validate P2P rate submission."""
    if buy_rate <= 0 or sell_rate <= 0:
        return False, "Rates must be positive numbers.", None
    if sell_rate >= buy_rate:
        return False, "Buy rate must be higher than sell rate.", None
    if buy_rate > sell_rate * 1.5:
        return False, "Spread is too wide — please check your numbers.", None
    spot_usd, _ = get_best_price(crypto)
    if not spot_usd:
        return True, "accepted_unverified", None
    rates = get_fiat_rates()
    fiat_rate = rates.get(fiat)
    if not fiat_rate:
        return True, "accepted_unverified", None
    spot_in_fiat = spot_usd * fiat_rate
    if spot_in_fiat <= 0:
        return True, "accepted_unverified", None
    if (abs(buy_rate - spot_in_fiat) / spot_in_fiat > P2P_MAX_DEVIATION or
            abs(sell_rate - spot_in_fiat) / spot_in_fiat > P2P_MAX_DEVIATION):
        fiat_sym = P2P_FIATS.get(fiat, (fiat, fiat))[1]
        return (False,
                "Rate looks unusual. Expected around %s%s based on current market. "
                "Please double-check what you see on your exchange." % (
                    fiat_sym, "{:,.0f}".format(spot_in_fiat)),
                spot_in_fiat)
    return True, "valid", spot_in_fiat

def submit_community_rate(chat_id, crypto, fiat, buy_rate, sell_rate,
                           exchange, is_admin=False):
    """Submit a community P2P rate with verification."""
    now = datetime.now()
    trust_info = get_user_trust(chat_id)
    if trust_info["blocked"] and not is_admin:
        return False, "unable"
    if not is_admin and trust_info["last_submission"]:
        last = datetime.strptime(trust_info["last_submission"], "%Y-%m-%d %H:%M:%S")
        if (now - last).total_seconds() < 3600:
            mins = int((3600 - (now - last).total_seconds()) / 60) + 1
            return False, "You can submit again in %d minute%s." % (
                mins, "s" if mins != 1 else "")
    valid, reason, spot_rate = validate_p2p_rate(crypto, fiat, buy_rate, sell_rate)
    if not valid:
        record_submission_attempt(chat_id, False)
        return False, reason
    weight = trust_info["trust"]
    if is_admin:
        weight = 10
        status = "live"
    elif weight >= 3:
        status = "live"
    else:
        status = "pending"
    expires_at = (now + timedelta(hours=P2P_PENDING_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        with get_db_cursor() as c:
            c.execute("INSERT INTO community_p2p (chat, crypto, fiat, buy_rate, sell_rate, "
                      "exchange, timestamp, weight, status, confirmations, spot_rate, expires_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (str(chat_id), crypto, fiat, buy_rate, sell_rate,
                       exchange, now_str, weight, status, 0, spot_rate, expires_at))
            rate_id = c.lastrowid
            if status == "pending":
                cutoff = (now - timedelta(hours=P2P_PENDING_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
                c.execute("SELECT id, buy_rate, confirmations FROM community_p2p "
                          "WHERE crypto=? AND fiat=? AND status='pending' "
                          "AND timestamp>=? AND id!=? AND chat!=?",
                          (crypto, fiat, cutoff, rate_id, str(chat_id)))
                for pid, p_buy, p_conf in c.fetchall():
                    if p_buy and abs(buy_rate - p_buy) / p_buy <= P2P_CONSENSUS_PCT:
                        try:
                            c.execute("INSERT INTO rate_confirmations (rate_id, chat, timestamp) "
                                      "VALUES (?,?,?)", (pid, str(chat_id), now_str))
                            new_conf = p_conf + 1
                            c.execute("UPDATE community_p2p SET confirmations=? WHERE id=?",
                                      (new_conf, pid))
                            if new_conf >= P2P_CONSENSUS_NEED:
                                c.execute("UPDATE community_p2p SET status='live' WHERE id=?",
                                          (pid,))
                        except Exception:
                            pass
    except Exception as e:
        print("[SUBMIT_COMMUNITY_RATE ERROR] %s" % e)
        return False, "Database error. Please try again."
    
    record_submission_attempt(chat_id, True)
    new_verified = trust_info["verified"] + (1 if status == "live" else 0)
    update_trust_level(chat_id, new_verified)
    return True, status

def get_community_rate(crypto, fiat):
    """Get verified community P2P rate."""
    try:
        with get_db_cursor() as c:
            cutoff = (datetime.now() - timedelta(hours=P2P_VALIDITY_HOURS)).strftime(
                "%Y-%m-%d %H:%M:%S")
            c.execute("SELECT buy_rate, sell_rate, weight, timestamp, exchange FROM community_p2p "
                      "WHERE crypto=? AND fiat=? AND status='live' AND timestamp>=? "
                      "ORDER BY timestamp DESC LIMIT 10", (crypto, fiat, cutoff))
            rows = c.fetchall()
            if not rows:
                return None
            spot_usd, _ = get_best_price(crypto)
            rates_obj = get_fiat_rates()
            fiat_rate = rates_obj.get(fiat)
            valid_rows = []
            for row in rows:
                buy = row[0]
                if spot_usd and fiat_rate:
                    spot = spot_usd * fiat_rate
                    if spot > 0 and abs(buy - spot) / spot > 0.25:
                        continue
                valid_rows.append(row)
            if not valid_rows:
                return None
            total_w = sum(r[2] for r in valid_rows)
            avg_buy = sum(r[0] * r[2] for r in valid_rows) / total_w
            avg_sell = sum(r[1] * r[2] for r in valid_rows) / total_w
            latest = valid_rows[0]
            return {"buy": round(avg_buy, 2), "sell": round(avg_sell, 2),
                    "count": len(valid_rows), "exchange": latest[4],
                    "timestamp": latest[3], "is_community": True}
    except Exception as e:
        print("[GET_COMMUNITY_RATE ERROR] %s" % e)
        return None

def cleanup_expired_rates():
    """Clean up expired pending rates."""
    try:
        with get_db_cursor() as c:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("UPDATE community_p2p SET status='expired' "
                      "WHERE status='pending' AND expires_at < ?", (now,))
            expired = c.rowcount
            if expired:
                print("[P2P] Cleaned %d expired pending rates" % expired)
    except Exception as e:
        print("[CLEANUP_EXPIRED_RATES ERROR] %s" % e)

def reset_daily_submission_counts():
    """Reset daily submission counts."""
    try:
        with get_db_cursor() as c:
            c.execute("UPDATE rate_submissions SET submissions_today=0, strikes_today=0 "
                      "WHERE blocked_until IS NULL OR blocked_until < ?",
                      (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
    except Exception as e:
        print("[RESET_DAILY_SUBMISSION_COUNTS ERROR] %s" % e)

_cb_tracker = {}

def check_callback_limit(chat_id):
    """Check if user has exceeded callback rate limit."""
    if chat_id in ADMIN_IDS:
        return True
    now = time.time()
    window = 10
    limit = 10
    times = _cb_tracker.get(chat_id, [])
    times = [t for t in times if now - t < window]
    if len(times) >= limit:
        return False
    times.append(now)
    _cb_tracker[chat_id] = times
    return True

def get_cached_ai_answer(question):
    """Get cached AI answer if available."""
    norm = question.strip().lower()[:200]
    cutoff = (datetime.now() - timedelta(minutes=AI_CACHE_MINUTES)).strftime(
        "%Y-%m-%d %H:%M:%S")
    try:
        with get_db_cursor() as c:
            c.execute("SELECT answer FROM ai_cache WHERE question=? AND timestamp>=? "
                      "ORDER BY id DESC LIMIT 1", (norm, cutoff))
            row = c.fetchone()
            return row[0] if row else None
    except Exception as e:
        print("[GET_CACHED_AI_ANSWER ERROR] %s" % e)
        return None

def cache_ai_answer(question, answer):
    """Cache AI answer."""
    try:
        with get_db_cursor() as c:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT INTO ai_cache (question, answer, timestamp) VALUES (?,?,?)",
                      (question.strip().lower()[:200], answer, now))
    except Exception as e:
        print("[CACHE_AI_ANSWER ERROR] %s" % e)

def get_alert_count(chat_id):
    """Get count of active alerts for a user."""
    try:
        with get_db_cursor() as c:
            c.execute("SELECT COUNT(*) FROM alerts WHERE chat=? AND active=1", (str(chat_id),))
            return c.fetchone()[0]
    except Exception:
        return 0

def get_watchlist_count(chat_id):
    """Get count of watchlist items for a user."""
    try:
        with get_db_cursor() as c:
            c.execute("SELECT COUNT(*) FROM watchlists WHERE chat=?", (str(chat_id),))
            return c.fetchone()[0]
    except Exception:
        return 0

def get_portfolio_count(chat_id):
    """Get count of portfolio items for a user."""
    try:
        with get_db_cursor() as c:
            c.execute("SELECT COUNT(*) FROM portfolio WHERE chat=?", (str(chat_id),))
            return c.fetchone()[0]
    except Exception:
        return 0

def check_limit(chat_id, limit_type):
    """Check if user has exceeded limits for a feature."""
    pro = is_pro(chat_id)
    limits = {
        "alert":     (PRO_ALERT_LIMIT if pro else FREE_ALERT_LIMIT, get_alert_count),
        "watchlist": (PRO_WATCHLIST_LIMIT if pro else FREE_WATCHLIST_LIMIT, get_watchlist_count),
        "portfolio": (PRO_PORTFOLIO_LIMIT if pro else FREE_PORTFOLIO_LIMIT, get_portfolio_count),
    }
    if limit_type not in limits:
        return True, 0, 999
    max_count, count_fn = limits[limit_type]
    current = count_fn(chat_id)
    return current < max_count, current, max_count

def increment_message_count(chat_id):
    """Increment user message count."""
    try:
        with get_db_cursor() as c:
            c.execute("UPDATE users SET message_count = COALESCE(message_count, 0) + 1 WHERE chat=?",
                      (str(chat_id),))
    except Exception as e:
        print("[INCREMENT_MESSAGE_COUNT ERROR] %s" % e)

def validate_and_count_referral(referred_chat):
    """Validate and count a referral if conditions are met."""
    try:
        with get_db_cursor() as c:
            c.execute("SELECT id, counted FROM referrals WHERE referred_chat=? AND counted=0",
                      (str(referred_chat),))
            row = c.fetchone()
            if not row:
                return
            c.execute("SELECT message_count FROM users WHERE chat=?", (str(referred_chat),))
            u = c.fetchone()
            if u and (u[0] or 0) >= 3:
                c.execute("UPDATE referrals SET counted=1 WHERE id=?", (row[0],))
    except Exception as e:
        print("[VALIDATE_AND_COUNT_REFERRAL ERROR] %s" % e)

# ── USER TRACKING ─────────────────────────────────────────────────────────────
def upsert_user(chat_id, username=None, first_name=None):
    """Insert or update user record."""
    try:
        with get_db_cursor() as c:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute(
                """INSERT INTO users (chat, username, first_name, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(chat) DO UPDATE SET
                     username=excluded.username,
                     first_name=excluded.first_name,
                     last_seen=excluded.last_seen""",
                (str(chat_id), username or "", first_name or "", now, now)
            )
    except Exception as e:
        print("[UPSERT_USER ERROR] %s" % e)

def log_event(chat_id, action):
    """Log a user event."""
    try:
        with get_db_cursor() as c:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT INTO events (chat, action, timestamp) VALUES (?, ?, ?)",
                      (str(chat_id), action, now))
    except Exception as e:
        print("[EVENT LOG ERROR] %s" % e)

# ── USER STATE HELPERS ────────────────────────────────────────────────────────
def set_state(chat_id, state, data=None):
    """Set user state."""
    try:
        with get_db_cursor() as c:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute(
                """INSERT INTO user_states (chat, state, data, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(chat) DO UPDATE SET
                     state=excluded.state, data=excluded.data, updated_at=excluded.updated_at""",
                (str(chat_id), state, json.dumps(data or {}), now)
            )
    except Exception as e:
        print("[SET_STATE ERROR] %s" % e)

def get_state(chat_id):
    """Get user state."""
    try:
        with get_db_cursor() as c:
            c.execute("SELECT state, data FROM user_states WHERE chat=?", (str(chat_id),))
            row = c.fetchone()
            if not row:
                return None, {}
            state, data = row
            try:
                data = json.loads(data) if data else {}
            except:
                data = {}
            return state, data
    except Exception as e:
        print("[GET_STATE ERROR] %s" % e)
        return None, {}

def clear_state(chat_id):
    """Clear user state."""
    try:
        with get_db_cursor() as c:
            c.execute("DELETE FROM user_states WHERE chat=?", (str(chat_id),))
    except Exception as e:
        print("[CLEAR_STATE ERROR] %s" % e)

# ── PRICE FETCHERS ────────────────────────────────────────────────────────────
_kraken_keymap = {}

def get_kraken_keymap():
    global _kraken_keymap
    if _kraken_keymap:
        return _kraken_keymap
    pairs = sorted({kraken_pair(c) for c in COINS if kraken_pair(c)})
    resp = request_json("GET", "https://api.kraken.com/0/public/AssetPairs",
                        params={"pair": ",".join(pairs)})
    if resp and not resp.get("error"):
        for key, info in resp.get("result", {}).items():
            altname = info.get("altname")
            if altname:
                _kraken_keymap[altname] = key
    return _kraken_keymap

_kraken_cache = {"data": {}, "timestamp": None}
KRAKEN_CACHE_SECONDS = 15

def get_kraken_batch():
    now = datetime.now()
    if (_kraken_cache["timestamp"] and
            (now - _kraken_cache["timestamp"]).total_seconds() < KRAKEN_CACHE_SECONDS):
        return _kraken_cache["data"]

    pairs = sorted({kraken_pair(c) for c in COINS if kraken_pair(c)})
    resp = request_json("GET", "https://api.kraken.com/0/public/Ticker",
                        params={"pair": ",".join(pairs)})
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
            except:
                pass

    _kraken_cache["data"] = prices
    _kraken_cache["timestamp"] = now
    return prices

def get_kraken_price(coin):
    if not kraken_pair(coin):
        return None
    return get_kraken_batch().get(coin)

_okx_cache = {"data": {}, "timestamp": None}
OKX_CACHE_SECONDS = 60

def get_okx_batch():
    """OKX spot tickers — price, 24h change/high/low for every tracked coin."""
    now = datetime.now()
    if (_okx_cache["timestamp"] and
            (now - _okx_cache["timestamp"]).total_seconds() < OKX_CACHE_SECONDS):
        return _okx_cache["data"]

    resp = request_json("GET", "https://www.okx.com/api/v5/market/tickers",
                        params={"instType": "SPOT"}, timeout=15)
    if not resp or resp.get("code") != "0":
        return _okx_cache["data"]

    by_inst = {row.get("instId"): row for row in resp.get("data", [])}
    result = {}
    for coin in COINS:
        row = by_inst.get("%s-USDT" % coin)
        if not row:
            continue
        try:
            last = float(row["last"])
            open24h = float(row["open24h"]) if row.get("open24h") else None
            change = ((last - open24h) / open24h * 100) if open24h else None
            result[coin] = {
                "price": last,
                "change": change,
                "high": float(row["high24h"]) if row.get("high24h") else None,
                "low": float(row["low24h"]) if row.get("low24h") else None,
            }
        except (ValueError, TypeError, KeyError):
            pass

    _okx_cache["data"] = result
    _okx_cache["timestamp"] = now
    return result

_cc_cache = {"data": {}, "timestamp": None}
CC_CACHE_SECONDS = 60

def get_cryptocompare_batch():
    """CryptoCompare — uses API key if available, falls back gracefully."""
    now = datetime.now()
    if (_cc_cache["timestamp"] and
            (now - _cc_cache["timestamp"]).total_seconds() < CC_CACHE_SECONDS):
        return _cc_cache["data"]

    params = {"fsyms": ",".join(COINS.keys()), "tsyms": "USD"}
    if CRYPTOCOMPARE_KEY:
        params["api_key"] = CRYPTOCOMPARE_KEY

    resp = request_json("GET", "https://min-api.cryptocompare.com/data/pricemultifull",
                        params=params, timeout=15)
    if not resp or not resp.get("RAW"):
        return _cc_cache["data"]

    result = {}
    for coin, data in resp["RAW"].items():
        usd = data.get("USD") if isinstance(data, dict) else None
        if not usd:
            continue
        result[coin] = {
            "price": usd.get("PRICE"),
            "change": usd.get("CHANGEPCT24HOUR"),
            "high": usd.get("HIGH24HOUR"),
            "low": usd.get("LOW24HOUR"),
        }

    _cc_cache["data"] = result
    _cc_cache["timestamp"] = now
    return result

_cg_cache = {"data": {}, "timestamp": None}
CG_CACHE_SECONDS = 120

def get_coingecko_batch():
    """CoinGecko free API — price + 24h change for all tracked coins."""
    now = datetime.now()
    if (_cg_cache["timestamp"] and
            (now - _cg_cache["timestamp"]).total_seconds() < CG_CACHE_SECONDS):
        return _cg_cache["data"]

    ids = ",".join(coin_key(c) for c in COINS)
    resp = request_json("GET",
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": ids, "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_24hr_vol": "true"}, timeout=15)
    if not resp:
        return _cg_cache["data"]

    id_to_coin = {coin_key(c): c for c in COINS}
    result = {}
    for cg_id, data in resp.items():
        coin = id_to_coin.get(cg_id)
        if coin and data.get("usd"):
            result[coin] = {
                "price": data["usd"],
                "change": data.get("usd_24h_change"),
                "high": None,
                "low": None,
            }
    _cg_cache["data"] = result
    _cg_cache["timestamp"] = now
    return result

_cap_cache = {"data": {}, "timestamp": None}
CAP_CACHE_SECONDS = 120

def get_coincap_batch():
    """CoinCap free API — price + 24h change."""
    now = datetime.now()
    if (_cap_cache["timestamp"] and
            (now - _cap_cache["timestamp"]).total_seconds() < CAP_CACHE_SECONDS):
        return _cap_cache["data"]

    resp = request_json("GET", "https://api.coincap.io/v2/assets",
                        params={"limit": 100}, timeout=15)
    if not resp or not resp.get("data"):
        return _cap_cache["data"]

    symbol_map = {c: c for c in COINS}
    result = {}
    for asset in resp["data"]:
        sym = asset.get("symbol", "").upper()
        if sym in symbol_map:
            try:
                result[sym] = {
                    "price": float(asset["priceUsd"]),
                    "change": float(asset["changePercent24Hr"]) if asset.get("changePercent24Hr") else None,
                    "high": None,
                    "low": None,
                }
            except (TypeError, ValueError):
                pass
    _cap_cache["data"] = result
    _cap_cache["timestamp"] = now
    return result

_secondary_cache = {"data": {}, "timestamp": None}
SECONDARY_CACHE_SECONDS = 60

def get_secondary_batch():
    """
    Merges OKX → CryptoCompare → CoinGecko → CoinCap into one dict.
    Each source fills in missing values from the next.
    """
    now = datetime.now()
    if (_secondary_cache["timestamp"] and
            (now - _secondary_cache["timestamp"]).total_seconds() < SECONDARY_CACHE_SECONDS):
        return _secondary_cache["data"]

    okx = get_okx_batch()
    cc = get_cryptocompare_batch()
    cg = get_coingecko_batch()
    cap = get_coincap_batch()

    result = {}
    for coin in COINS:
        o = okx.get(coin) or {}
        c = cc.get(coin) or {}
        g = cg.get(coin) or {}
        a = cap.get(coin) or {}

        def first(*vals):
            for v in vals:
                if v is not None:
                    return v
            return None

        price = first(o.get("price"), c.get("price"), g.get("price"), a.get("price"))
        change = first(o.get("change"), c.get("change"), g.get("change"), a.get("change"))
        high = first(o.get("high"), c.get("high"), g.get("high"), a.get("high"))
        low = first(o.get("low"), c.get("low"), g.get("low"), a.get("low"))

        if price is not None:
            result[coin_key(coin)] = {
                "usd": price, "usd_24h_change": change,
                "usd_24h_high": high, "usd_24h_low": low,
            }

    _secondary_cache["data"] = result
    _secondary_cache["timestamp"] = now
    return result

def get_secondary_coin(coin):
    return get_secondary_batch().get(coin_key(coin))

_fiat_cache = {"data": {}, "timestamp": None}
FIAT_CACHE_SECONDS = 300

def get_fiat_rates():
    now = datetime.now()
    if (_fiat_cache["timestamp"] and
            (now - _fiat_cache["timestamp"]).total_seconds() < FIAT_CACHE_SECONDS):
        return _fiat_cache["data"]
    resp = request_json("GET", "https://open.er-api.com/v6/latest/USD")
    if resp is None:
        return _fiat_cache["data"]
    rates = resp.get("rates", {})
    _fiat_cache["data"] = rates
    _fiat_cache["timestamp"] = now
    return rates

def get_best_price(coin):
    if coin not in COINS:
        return None, None
    price = get_kraken_price(coin)
    sd = get_secondary_coin(coin)
    change = sd.get("usd_24h_change") if sd else None
    if price:
        return price, change
    if sd:
        return sd.get("usd"), change
    return None, None

# ── FEAR & GREED ──────────────────────────────────────────────────────────────
_fg_cache = {"data": None, "timestamp": None}

def get_fear_greed():
    now = datetime.now()
    if (_fg_cache["timestamp"] and
            (now - _fg_cache["timestamp"]).total_seconds() < 3600):
        return _fg_cache["data"]
    resp = request_json("GET", "https://api.alternative.me/fng/?limit=7", timeout=10)
    if resp and resp.get("data"):
        _fg_cache["data"] = resp["data"]
        _fg_cache["timestamp"] = now
        return resp["data"]
    return _fg_cache["data"]

def fg_emoji(value):
    v = int(value)
    if v <= 24:   return "😱"
    elif v <= 44: return "😰"
    elif v <= 54: return "😐"
    elif v <= 74: return "😊"
    else:         return "🤑"

# ── NEWS ──────────────────────────────────────────────────────────────────────
_news_cache = {"data": None, "timestamp": None}

NEWS_RSS_FEEDS = [
    ("Bitcoin Magazine", "https://bitcoinmagazine.com/.rss/full/"),
    ("CryptoSlate",      "https://cryptoslate.com/feed/"),
    ("Decrypt",          "https://decrypt.co/feed"),
    ("CoinDesk",         "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("The Block",        "https://www.theblock.co/rss.xml"),
    ("CoinTelegraph",    "https://cointelegraph.com/rss"),
    ("NewsBTC",          "https://www.newsbtc.com/feed/"),
]

def _parse_rss(xml_text, source_name):
    articles = []
    try:
        root = _ET.fromstring(xml_text)
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            url = (item.findtext("link") or "").strip()
            if title and url:
                articles.append({
                    "title": title,
                    "url": url,
                    "source": {"title": source_name},
                })
    except Exception as e:
        print("[RSS PARSE ERROR] %s: %s" % (source_name, e))
    return articles

def get_crypto_news():
    now = datetime.now()
    if (_news_cache["timestamp"] and
            (now - _news_cache["timestamp"]).total_seconds() < 900):
        return _news_cache["data"]

    all_articles = []
    for source_name, rss_url in NEWS_RSS_FEEDS:
        if len(all_articles) >= 10:
            break
        try:
            r = requests.get(rss_url, timeout=8,
                             headers={"User-Agent": "MarketPulseBot/1.0"})
            if r.status_code == 200:
                parsed = _parse_rss(r.text, source_name)
                all_articles.extend(parsed[:5])
                print("[NEWS] %s — got %d articles" % (source_name, len(parsed)))
        except Exception as e:
            print("[RSS FETCH ERROR] %s: %s" % (source_name, e))
            continue

    if all_articles:
        _news_cache["data"] = all_articles[:10]
        _news_cache["timestamp"] = now
        return _news_cache["data"]

    return _news_cache["data"]

# ── GAINERS / LOSERS ─────────────────────────────────────────────────────────
def get_gainers_losers():
    """Returns (gainers, losers) — top 10 each from tracked coins by 24h change."""
    secondary = get_secondary_batch()
    ranked = []
    for coin in COINS:
        sd = secondary.get(coin_key(coin))
        if sd and sd.get("usd_24h_change") is not None:
            price = get_kraken_price(coin) or sd.get("usd")
            change = sd["usd_24h_change"]
            ranked.append((coin, price, change))
    ranked.sort(key=lambda x: x[2], reverse=True)
    gainers = [r for r in ranked if r[2] > 0][:10]
    losers = list(reversed([r for r in ranked if r[2] < 0]))[:10]
    return gainers, losers

# ── HISTORY & ALERTS ─────────────────────────────────────────────────────────
def save_history():
    """Save current prices to history."""
    try:
        with get_db_cursor() as c:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            kraken_batch = get_kraken_batch()
            secondary = get_secondary_batch()
            saved = 0
            for coin in COINS:
                price = kraken_batch.get(coin)
                if price is None:
                    sd = secondary.get(coin_key(coin))
                    if sd:
                        price = sd.get("usd")
                if price:
                    c.execute("INSERT INTO history (coin, price, timestamp) VALUES (?, ?, ?)",
                              (coin, price, now))
                    saved += 1
            if saved:
                print("  Saved %d prices" % saved)
    except Exception as e:
        print("[SAVE_HISTORY ERROR] %s" % e)

def check_alerts():
    """Check and trigger price alerts."""
    try:
        with get_db_cursor() as c:
            c.execute("SELECT id, chat, coin, condition, target, label FROM alerts WHERE active=1")
            alerts = c.fetchall()
            for aid, chat, coin, condition, target, label in alerts:
                price, change = get_best_price(coin)
                if price is None:
                    continue
                triggered = False
                msg_extra = ""
                if condition == "above":
                    triggered = price > target
                elif condition == "below":
                    triggered = price < target
                elif condition == "exact":
                    triggered = abs(price - target) / target < 0.001
                elif condition == "pct_up" and change is not None:
                    triggered = change >= target
                    msg_extra = "  24h change: <b>+%.2f%%</b>" % change
                elif condition == "pct_down" and change is not None:
                    triggered = change <= -target
                    msg_extra = "  24h change: <b>%.2f%%</b>" % change

                if triggered:
                    verbs = {
                        "above": "rose above",
                        "below": "fell below",
                        "exact": "hit",
                        "pct_up": "is up",
                        "pct_down": "is down",
                    }
                    lbl_str = " (<i>%s</i>)" % label if label else ""
                    send(int(chat),
                         "🚨 <b>Alert Triggered!</b>%s\n\n"
                         "  <b>%s</b> %s <b>%s</b>\n"
                         "  Now: <b>%s</b>\n%s" % (
                             lbl_str, coin, verbs.get(condition, condition),
                             format_price(target) if "pct" not in condition else "%.2f%%" % target,
                             format_price(price), msg_extra),
                         [[{"text": "Main Menu", "callback_data": "main_menu"}]])
                    c.execute("UPDATE alerts SET active=0 WHERE id=?", (aid,))
    except Exception as e:
        print("[CHECK_ALERTS ERROR] %s" % e)

# ── TELEGRAM HELPERS ──────────────────────────────────────────────────────────
def tg(method, data):
    result = request_json(
        "POST", "https://api.telegram.org/bot%s/%s" % (BOT_TOKEN, method),
        json_data=data, timeout=15, retries=2, backoff=1.0
    )
    return result or {}

def tg_photo(form_data, photo_bytes, filename="chart.png", retries=3):
    safe_data = {k: str(v) for k, v in form_data.items()}
    last_exc = None
    for attempt in range(retries):
        try:
            files = {"photo": (filename, io.BytesIO(photo_bytes), "image/png")}
            r = requests.post(
                "https://api.telegram.org/bot%s/sendPhoto" % BOT_TOKEN,
                data=safe_data, files=files, timeout=30
            )
            r.raise_for_status()
            result = r.json()
            if not result.get("ok"):
                print("[PHOTO ERROR] Telegram rejected: %s" % result)
            return result
        except Exception as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(1.0)
    print("[RETRY FAILED] sendPhoto -> %s" % last_exc)
    return {}

def send_photo(chat_id, photo_bytes, caption=None, buttons=None):
    data = {"chat_id": str(chat_id), "parse_mode": "HTML"}
    if caption:
        data["caption"] = caption
    if buttons:
        data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    return tg_photo(data, photo_bytes)

def delete_message(chat_id, message_id):
    tg("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

def send(chat_id, text, buttons=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if buttons:
        data["reply_markup"] = {"inline_keyboard": buttons}
    return tg("sendMessage", data)

def edit(chat_id, message_id, text, buttons=None):
    data = {"chat_id": chat_id, "message_id": message_id,
            "text": text, "parse_mode": "HTML"}
    if buttons:
        data["reply_markup"] = {"inline_keyboard": buttons}
    return tg("editMessageText", data)

def answer_cb(cb_id, text=None):
    payload = {"callback_query_id": cb_id}
    if text:
        payload["text"] = text
    tg("answerCallbackQuery", payload)

# ── KEYBOARDS ─────────────────────────────────────────────────────────────────
MENU_ACCOUNT = [
    [{"text": "👥 Referral",        "callback_data": "referral"},
     {"text": "💼 Portfolio",       "callback_data": "portfolio"}],
    [{"text": "📊 My Stats",        "callback_data": "my_stats"},
     {"text": "⭐ Watchlist",       "callback_data": "watchlist"}],
    [{"text": "🏠 Main Menu",       "callback_data": "main_menu"}],
]

MAIN_MENU = [
    [{"text": "📈 Markets",         "callback_data": "menu_markets"},
     {"text": "🧠 Intelligence",    "callback_data": "menu_intelligence"}],
    [{"text": "🇳🇬 P2P Center",     "callback_data": "menu_nigeria"},
     {"text": "🔔 Alerts",          "callback_data": "menu_alerts"}],
    [{"text": "🛠 Tools",           "callback_data": "menu_tools"},
     {"text": "👤 My Account",      "callback_data": "menu_account"}],
    [{"text": "❓ Help",            "callback_data": "help"},
     {"text": "💎 Pro",             "callback_data": "upgrade"}],
]

def show_my_stats(chat_id, message_id):
    """Show user statistics."""
    track(chat_id, "my_stats")
    try:
        with get_db_cursor() as c:
            today = datetime.now().strftime("%Y-%m-%d")
            week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            c.execute("SELECT COUNT(DISTINCT day) FROM analytics WHERE chat=?", (str(chat_id),))
            active_days = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM analytics WHERE chat=? AND day=?", (str(chat_id), today))
            today_actions = c.fetchone()[0]
            c.execute("SELECT feature, COUNT(*) as cnt FROM analytics WHERE chat=? AND day>=? "
                      "GROUP BY feature ORDER BY cnt DESC LIMIT 5", (str(chat_id), week))
            top_features = c.fetchall()
            c.execute("SELECT first_seen FROM users WHERE chat=?", (str(chat_id),))
            row = c.fetchone()
            joined = row[0][:10] if row else "Unknown"
    except Exception as e:
        print("[SHOW_MY_STATS ERROR] %s" % e)
        edit(chat_id, message_id, "Could not load stats. Try again.",
             [[{"text": "⬅ Back", "callback_data": "menu_account"}]])
        return

    lines = ["👤 <b>My Stats</b>", "",
             "  Joined       : <b>%s</b>" % joined,
             "  Active days  : <b>%d</b>" % active_days,
             "  Today actions: <b>%d</b>" % today_actions, ""]
    if top_features:
        lines.append("  <b>Top features (7d):</b>")
        for feat, cnt in top_features:
            lines.append("  • %s — %d times" % (feat.replace("_", " ").title(), cnt))
    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "🔄 Refresh", "callback_data": "my_stats"},
           {"text": "⬅ Back",    "callback_data": "menu_account"}]])

def wat_now():
    return datetime.now() + timedelta(hours=WAT_OFFSET)

# ── MENU FUNCTIONS ────────────────────────────────────────────────────────────
BACK_MAIN = [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]

MENU_MARKETS = [
    [{"text": "📈 Market",        "callback_data": "market"},
     {"text": "📊 Charts",        "callback_data": "charts"}],
    [{"text": "🔥 Gainers",       "callback_data": "gainers"},
     {"text": "📉 Losers",        "callback_data": "losers"}],
    [{"text": "🌐 Dominance",     "callback_data": "dominance"},
     {"text": "📊 Funding Rates", "callback_data": "funding"}],
    [{"text": "💥 Liquidations",  "callback_data": "liquidations"},
     {"text": "📖 Market Pressure","callback_data": "orderbook"}],
    [{"text": "📡 Sources",       "callback_data": "sources"},
     {"text": "🏠 Main Menu",     "callback_data": "main_menu"}],
]

MENU_INTELLIGENCE = [
    [{"text": "🤖 Ask AI",        "callback_data": "ask_ai"},
     {"text": "📐 Trade Setups",  "callback_data": "trade_setup"}],
    [{"text": "📰 News",          "callback_data": "news"},
     {"text": "🧠 Fear & Greed",  "callback_data": "fear_greed"}],
    [{"text": "📡 Sources",       "callback_data": "sources"},
     {"text": "🏠 Main Menu",     "callback_data": "main_menu"}],
]

MENU_PORTFOLIO = [
    [{"text": "⭐ Watchlist",    "callback_data": "watchlist"},
     {"text": "💼 Portfolio",    "callback_data": "portfolio"}],
    [{"text": "🚨 Set Alert",    "callback_data": "alerts"},
     {"text": "📋 My Alerts",    "callback_data": "my_alerts"}],
    [{"text": "👥 Referral",     "callback_data": "referral"}],
    [{"text": "🏠 Main Menu",    "callback_data": "main_menu"}],
]

MENU_NIGERIA = [
    [{"text": "💱 P2P Rates",    "callback_data": "p2p"},
     {"text": "🔔 P2P Alerts",   "callback_data": "p2p_alerts"}],
    [{"text": "📤 Submit Rate",  "callback_data": "submit_rate"},
     {"text": "🔄 Arbitrage",    "callback_data": "arbitrage"}],
    [{"text": "🏠 Main Menu",    "callback_data": "main_menu"}],
]

MENU_TOOLS = [
    [{"text": "🔍 Search Coin",  "callback_data": "coin_search"},
     {"text": "🔄 Convert",      "callback_data": "convert"}],
    [{"text": "📜 History",      "callback_data": "history"},
     {"text": "⚙️ Status",       "callback_data": "status"}],
    [{"text": "🏠 Main Menu",    "callback_data": "main_menu"}],
]

def coin_buttons(action, page=0, extra_back="main_menu"):
    all_coins = list(COINS.keys())
    per_page = 10
    total = (len(all_coins) + per_page - 1) // per_page
    chunk = all_coins[page * per_page:(page + 1) * per_page]
    buttons = []
    row = []
    for coin in chunk:
        row.append({"text": coin, "callback_data": "%s:%s" % (action, coin)})
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    nav = []
    if page > 0:
        nav.append({"text": "◀ Prev", "callback_data": "page:%s:%d" % (action, page - 1)})
    if page < total - 1:
        nav.append({"text": "Next ▶", "callback_data": "page:%s:%d" % (action, page + 1)})
    if nav:
        buttons.append(nav)
    buttons.append([{"text": "⬅ Back", "callback_data": extra_back}])
    return buttons

def tf_buttons(coin):
    return [
        [{"text": tf, "callback_data": "chart_tf:%s:%s" % (coin, tf)}
         for tf in ["1H", "6H", "1D", "3D"]],
        [{"text": tf, "callback_data": "chart_tf:%s:%s" % (coin, tf)}
         for tf in ["1W", "1M", "3M", "1Y"]],
        [{"text": "⬅ Back", "callback_data": "charts"}],
    ]

def cond_buttons(coin):
    return [
        [{"text": "📈 Above",   "callback_data": "alert_cond:%s:above" % coin},
         {"text": "📉 Below",   "callback_data": "alert_cond:%s:below" % coin},
         {"text": "🎯 Exact",   "callback_data": "alert_cond:%s:exact" % coin}],
        [{"text": "📊 % Rise",  "callback_data": "alert_cond:%s:pct_up" % coin},
         {"text": "📊 % Drop",  "callback_data": "alert_cond:%s:pct_down" % coin}],
        [{"text": "⬅ Back",    "callback_data": "alerts"}],
    ]

# ── SCREENS ───────────────────────────────────────────────────────────────────
def show_main_menu(chat_id, message_id=None):
    text = (
        "🚀 <b>Market Pulse</b>\n"
        "<i>AI-powered crypto intelligence for Nigerian traders</i>\n\n"
        "Choose a category to get started:"
    )
    if message_id:
        edit(chat_id, message_id, text, MAIN_MENU)
    else:
        send(chat_id, text, MAIN_MENU)

def show_menu_markets(chat_id, message_id):
    track(chat_id, "menu_markets")
    edit(chat_id, message_id,
         "📈 <b>Markets</b>\nPrices, charts, gainers, losers and dominance.",
         MENU_MARKETS)

def show_menu_intelligence(chat_id, message_id):
    track(chat_id, "menu_intelligence")
    edit(chat_id, message_id,
         "🧠 <b>Intelligence</b>\nNews, sentiment, and AI-powered insights.",
         MENU_INTELLIGENCE)

def show_menu_portfolio(chat_id, message_id):
    track(chat_id, "menu_portfolio")
    edit(chat_id, message_id,
         "💼 <b>Portfolio</b>\nTrack your assets, alerts, and referrals.",
         MENU_PORTFOLIO)

def show_menu_nigeria(chat_id, message_id):
    track(chat_id, "menu_nigeria")
    edit(chat_id, message_id,
         "🇳🇬 <b>P2P Center</b>\nReal P2P rates, NGN alerts and arbitrage.",
         MENU_NIGERIA)

def show_menu_tools(chat_id, message_id):
    track(chat_id, "menu_tools")
    edit(chat_id, message_id,
         "🛠 <b>Tools</b>\nSearch, convert, history, and status.",
         MENU_TOOLS)

def show_menu_alerts(chat_id, message_id):
    track(chat_id, "menu_alerts")
    edit(chat_id, message_id,
         "🔔 <b>Alerts</b>\nCreate and manage your price and P2P alerts.",
         [[{"text": "➕ Create Alert",   "callback_data": "create_alert"},
           {"text": "📋 My Alerts",      "callback_data": "my_alerts"}],
          [{"text": "🔔 P2P Alerts",     "callback_data": "p2p_alerts"},
           {"text": "⭐ Watchlist",      "callback_data": "watchlist"}],
          [{"text": "🏠 Main Menu",      "callback_data": "main_menu"}]])

def show_menu_account(chat_id, message_id):
    track(chat_id, "menu_account")
    edit(chat_id, message_id,
         "👤 <b>My Account</b>",
         MENU_ACCOUNT)

# ── FULL MARKET SCREENS ──────────────────────────────────────────────────────

def show_market(chat_id, message_id):
    """Show live market prices."""
    kraken_batch = get_kraken_batch()
    secondary = get_secondary_batch()
    lines = [
        "<b>📈 Live Market Prices</b>",
        "<code>%-7s %-12s  %s" % ("Coin", "Price", "24h %"),
        "─" * 34,
    ]
    for coin in COINS:
        price = kraken_batch.get(coin)
        sd = secondary.get(coin_key(coin))
        if price is None and sd:
            price = sd.get("usd")
        change = sd.get("usd_24h_change") if sd else None
        if price:
            ch_str = format_change(change)
            lines.append("%-7s %-12s  %s" % (coin, format_price(price), ch_str))
        else:
            lines.append("%-7s —" % coin)
    lines.append("</code>")
    lines.append("<i>Kraken + OKX + CryptoCompare  •  %s</i>" % datetime.now().strftime("%H:%M:%S"))
    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "🔄 Refresh", "callback_data": "market"},
           {"text": "⬅ Back",    "callback_data": "main_menu"}]])

def show_sources(chat_id, message_id, coin):
    """Show data sources for a coin."""
    kraken_price = get_kraken_price(coin)
    sd = get_secondary_coin(coin)
    lines = ["📡 <b>%s — Sources</b>" % coin, ""]

    if kraken_price:
        lines += ["<b>Kraken</b>",
                  "  Price : <b>%s</b>" % format_price(kraken_price), ""]
    if sd:
        change = sd.get("usd_24h_change")
        high = sd.get("usd_24h_high")
        low = sd.get("usd_24h_low")
        lines += ["<b>OKX + CryptoCompare</b>",
                  "  Price : <b>%s</b>" % format_price(sd["usd"])]
        if change is not None:
            lines.append("  24h   : <b>%s</b>" % format_change(change))
        if high:
            lines.append("  High  : <b>%s</b>" % format_price(high))
        if low:
            lines.append("  Low   : <b>%s</b>" % format_price(low))
        lines.append("")

    if kraken_price and sd:
        lines.append("📊 Spread : <b>%s</b>" % format_price(abs(kraken_price - sd["usd"])))

    if not kraken_price and not sd:
        lines.append("Could not fetch data for %s." % coin)

    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "🔄 Refresh", "callback_data": "source:%s" % coin},
           {"text": "⬅ Back",    "callback_data": "sources"}]])

def show_history(chat_id, message_id, coin):
    """Show price history for a coin."""
    try:
        with get_db_cursor() as c:
            c.execute("SELECT price, timestamp FROM history WHERE coin=? ORDER BY id DESC LIMIT 10", (coin,))
            rows = c.fetchall()
    except Exception as e:
        print("[SHOW_HISTORY ERROR] %s" % e)
        rows = []
    if not rows:
        text = "📜 No history for <b>%s</b> yet.\nPrices are saved every 5 min." % coin
    else:
        lines = ["📜 <b>%s — Price History</b>" % coin, ""]
        for price, ts in reversed(rows):
            lines.append("  %s  →  <b>%s</b>" % (ts[11:16], format_price(price)))
        text = "\n".join(lines)
    edit(chat_id, message_id, text, [[{"text": "⬅ Back", "callback_data": "history"}]])

def show_chart(chat_id, message_id, coin, timeframe="1D"):
    """Show price chart for a coin."""
    hours, _, ts_fmt = TIMEFRAMES.get(timeframe, (24, 48, "hm"))
    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

    try:
        with get_db_cursor() as c:
            c.execute(
                "SELECT price, timestamp FROM history "
                "WHERE coin=? AND price IS NOT NULL AND timestamp>=? ORDER BY id ASC LIMIT ?",
                (coin, since, CHART_MAX_POINTS)
            )
            rows = c.fetchall()
    except Exception as e:
        print("[SHOW_CHART DB ERROR] %s" % e)
        rows = []

    if len(rows) < 2:
        delete_message(chat_id, message_id)
        send(chat_id,
             "📊 <b>%s — %s</b>\n\n"
             "Not enough data for this timeframe yet.\n"
             "Prices save every 5 min — try a shorter timeframe or check back later." % (coin, timeframe),
             tf_buttons(coin))
        return

    prices = [float(p) for p, _ in rows]
    hi, lo = max(prices), min(prices)
    chg = (prices[-1] - prices[0]) / prices[0] * 100
    sign = "+" if chg >= 0 else ""

    image_bytes = render_chart_png(coin, timeframe, ts_fmt, rows)
    delete_message(chat_id, message_id)

    if not image_bytes:
        send(chat_id,
             "⚠️ Chart rendering failed for <b>%s</b>.\nPlease try again." % coin,
             tf_buttons(coin))
        return

    caption = (
        "📊 <b>%s — %s</b>\n"
        "High <b>%s</b>   Low <b>%s</b>   Chg <b>%s%.2f%%</b>"
        % (coin, timeframe, format_price(hi), format_price(lo), sign, chg)
    )
    result = send_photo(chat_id, image_bytes, caption=caption, buttons=tf_buttons(coin))
    if not result.get("ok"):
        send(chat_id,
             "⚠️ Could not send chart image. Telegram error: %s" % result.get("description", "unknown"),
             tf_buttons(coin))

# ── WATCHLIST ─────────────────────────────────────────────────────────────────
def get_watchlist(chat_id):
    try:
        with get_db_cursor() as c:
            c.execute("SELECT coin FROM watchlists WHERE chat=? ORDER BY id", (str(chat_id),))
            return [r[0] for r in c.fetchall()]
    except Exception:
        return []

def show_watchlist_menu(chat_id, message_id):
    coins = get_watchlist(chat_id)
    buttons = [
        [{"text": "➕ Add Coin",    "callback_data": "wl_add_page:0"},
         {"text": "➖ Remove Coin", "callback_data": "wl_remove"}],
    ]
    if coins:
        buttons.insert(0, [{"text": "📊 View Prices", "callback_data": "wl_prices"}])
    buttons.append([{"text": "🏠 Main Menu", "callback_data": "main_menu"}])

    if coins:
        text = "⭐ <b>Watchlist</b> (%d coins)\n\n%s" % (len(coins), "  ".join(coins))
    else:
        text = "⭐ <b>Watchlist</b>\n\nYour watchlist is empty. Add coins to track them."
    edit(chat_id, message_id, text, buttons)

def show_watchlist_prices(chat_id, message_id):
    coins = get_watchlist(chat_id)
    kraken_batch = get_kraken_batch()
    secondary = get_secondary_batch()
    if not coins:
        edit(chat_id, message_id, "⭐ Your watchlist is empty.",
             [[{"text": "⬅ Back", "callback_data": "watchlist"}]])
        return
    lines = ["⭐ <b>Watchlist — Live Prices</b>", ""]
    for coin in coins:
        price = kraken_batch.get(coin)
        sd = secondary.get(coin_key(coin))
        if price is None and sd:
            price = sd.get("usd")
        change = sd.get("usd_24h_change") if sd else None
        if price:
            lines.append("  <b>%s</b>  %s  %s" % (coin, format_price(price), format_change(change)))
        else:
            lines.append("  <b>%s</b>  —" % coin)
    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "🔄 Refresh",  "callback_data": "wl_prices"},
           {"text": "⬅ Back",     "callback_data": "watchlist"}]])

def wl_add_coin(chat_id, coin):
    try:
        with get_db_cursor() as c:
            c.execute("INSERT OR IGNORE INTO watchlists (chat, coin) VALUES (?, ?)",
                      (str(chat_id), coin))
            return c.rowcount > 0
    except Exception:
        return False

def wl_remove_coin(chat_id, coin):
    try:
        with get_db_cursor() as c:
            c.execute("DELETE FROM watchlists WHERE chat=? AND coin=?", (str(chat_id), coin))
    except Exception:
        pass

def show_wl_remove_menu(chat_id, message_id):
    coins = get_watchlist(chat_id)
    if not coins:
        edit(chat_id, message_id, "⭐ Nothing to remove — watchlist is empty.",
             [[{"text": "⬅ Back", "callback_data": "watchlist"}]])
        return
    buttons = [[{"text": coin, "callback_data": "wl_del:%s" % coin}] for coin in coins]
    buttons.append([{"text": "⬅ Back", "callback_data": "watchlist"}])
    edit(chat_id, message_id, "⭐ <b>Remove from Watchlist</b>\n\nTap a coin to remove:", buttons)

# ── FEAR & GREED SCREEN ───────────────────────────────────────────────────────
def show_fear_greed(chat_id, message_id):
    data = get_fear_greed()
    if not data:
        edit(chat_id, message_id,
             "🧠 Could not fetch Fear & Greed data. Try again shortly.", BACK_MAIN)
        return
    current = data[0]
    val = current["value"]
    label = current["value_classification"]
    emoji = fg_emoji(val)
    ts = datetime.fromtimestamp(int(current["timestamp"])).strftime("%b %d, %Y")

    lines = [
        "🧠 <b>Crypto Fear & Greed Index</b>",
        "",
        "%s  <b>%s / 100</b>" % (emoji, val),
        "<b>%s</b>" % label,
        "<i>Updated: %s</i>" % ts,
        "",
        "📅 <b>Recent History</b>",
    ]
    for entry in data[1:7]:
        d = datetime.fromtimestamp(int(entry["timestamp"])).strftime("%b %d")
        e = fg_emoji(entry["value"])
        lines.append("  %s  %s %s  <i>%s</i>" % (d, e, entry["value"], entry["value_classification"]))

    lines += [
        "",
        "<i>0-24 Extreme Fear  |  25-44 Fear</i>",
        "<i>45-54 Neutral      |  55-74 Greed</i>",
        "<i>75-100 Extreme Greed</i>",
    ]
    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "🔄 Refresh", "callback_data": "fear_greed"},
           {"text": "⬅ Back",    "callback_data": "main_menu"}]])

# ── NEWS SCREEN ───────────────────────────────────────────────────────────────
def show_news(chat_id, message_id):
    articles = get_crypto_news()
    if not articles:
        edit(chat_id, message_id,
             "📰 <b>Crypto News</b>\n\n"
             "Sorry, we couldn't load news right now. 🙏\n\n"
             "You can catch the latest crypto headlines directly on these sites:\n\n"
             "• <a href=\"https://decrypt.co\">Decrypt</a>\n"
             "• <a href=\"https://bitcoinmagazine.com\">Bitcoin Magazine</a>\n"
             "• <a href=\"https://cryptoslate.com\">CryptoSlate</a>\n"
             "• <a href=\"https://cointelegraph.com\">CoinTelegraph</a>\n\n"
             "<i>We'll have news back shortly. Try refreshing in a moment.</i>",
             [[{"text": "🔄 Try Again", "callback_data": "news"},
               {"text": "⬅ Back",      "callback_data": "main_menu"}]])
        return
    lines = ["📰 <b>Crypto News</b>", ""]
    for i, art in enumerate(articles[:8], 1):
        title = art.get("title", "No title")
        url = art.get("url", "")
        src = art.get("source", {}).get("title", "") if isinstance(art.get("source"), dict) else ""
        if url:
            lines.append("%d. <a href=\"%s\">%s</a>" % (i, url, title))
        else:
            lines.append("%d. %s" % (i, title))
        if src:
            lines.append("   <i>%s</i>" % src)
        lines.append("")
    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "🔄 Refresh", "callback_data": "news"},
           {"text": "⬅ Back",    "callback_data": "main_menu"}]])

# ── GAINERS / LOSERS SCREENS ──────────────────────────────────────────────────
def show_gainers(chat_id, message_id):
    gainers, _ = get_gainers_losers()
    if not gainers:
        edit(chat_id, message_id, "🔥 No gainer data available right now.", BACK_MAIN)
        return
    lines = ["🔥 <b>Top Gainers (24h)</b>", ""]
    for i, (coin, price, chg) in enumerate(gainers, 1):
        lines.append("%2d. <b>%-7s</b> %s  <b>+%.2f%%</b>" % (
            i, coin, format_price(price) if price else "—", chg))
    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "🔄 Refresh", "callback_data": "gainers"},
           {"text": "📉 Losers",  "callback_data": "losers"},
           {"text": "⬅ Back",    "callback_data": "main_menu"}]])

def show_losers(chat_id, message_id):
    _, losers = get_gainers_losers()
    if not losers:
        edit(chat_id, message_id, "📉 No loser data available right now.", BACK_MAIN)
        return
    lines = ["📉 <b>Top Losers (24h)</b>", ""]
    for i, (coin, price, chg) in enumerate(losers, 1):
        lines.append("%2d. <b>%-7s</b> %s  <b>%.2f%%</b>" % (
            i, coin, format_price(price) if price else "—", chg))
    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "🔄 Refresh", "callback_data": "losers"},
           {"text": "🔥 Gainers", "callback_data": "gainers"},
           {"text": "⬅ Back",    "callback_data": "main_menu"}]])

# ── PORTFOLIO ─────────────────────────────────────────────────────────────────
def show_portfolio(chat_id, message_id):
    try:
        with get_db_cursor() as c:
            c.execute("SELECT id, coin, amount, buy_price, added_at FROM portfolio WHERE chat=? ORDER BY id",
                      (str(chat_id),))
            rows = c.fetchall()
    except Exception as e:
        print("[SHOW_PORTFOLIO ERROR] %s" % e)
        rows = []

    if not rows:
        edit(chat_id, message_id,
             "💼 <b>Portfolio</b>\n\nNo assets yet. Add your first position!",
             [[{"text": "➕ Add Asset",    "callback_data": "port_add"},
               {"text": "🏠 Main Menu",   "callback_data": "main_menu"}]])
        return

    total_cost = 0
    total_now = 0
    lines = ["💼 <b>Portfolio</b>", ""]

    for pid, coin, amount, buy_price, added_at in rows:
        price, _ = get_best_price(coin)
        cost = amount * buy_price
        now_val = amount * price if price else None
        pnl = now_val - cost if now_val else None
        pnl_pct = (pnl / cost * 100) if (pnl is not None and cost > 0) else None

        total_cost += cost
        if now_val:
            total_now += now_val

        lines.append("<b>%s</b>  ×%g @ %s" % (coin, amount, format_price(buy_price)))
        if price and pnl is not None:
            sign = "+" if pnl >= 0 else ""
            lines.append("  Now: %s  |  P&L: <b>%s$%.2f (%.2f%%)</b>" % (
                format_price(price), sign, pnl, pnl_pct or 0))
        else:
            lines.append("  Price unavailable")
        lines.append("")

    if total_now:
        total_pnl = total_now - total_cost
        total_pnl_pct = total_pnl / total_cost * 100 if total_cost > 0 else 0
        sign = "+" if total_pnl >= 0 else ""
        lines.append("─" * 28)
        lines.append("Total Cost : <b>$%.2f</b>" % total_cost)
        lines.append("Total Value: <b>$%.2f</b>" % total_now)
        lines.append("Total P&L  : <b>%s$%.2f (%s%.2f%%)</b>" % (sign, total_pnl, sign, total_pnl_pct))

    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "➕ Add Asset",    "callback_data": "port_add"},
           {"text": "🗑 Remove Asset", "callback_data": "port_remove"}],
          [{"text": "📈 Port. Chart",  "callback_data": "port_chart"},
           {"text": "🔄 Refresh",      "callback_data": "portfolio"}],
          [{"text": "📤 Export CSV",   "callback_data": "port_export"},
           {"text": "🏠 Main Menu",    "callback_data": "main_menu"}]])

def show_port_remove(chat_id, message_id):
    try:
        with get_db_cursor() as c:
            c.execute("SELECT id, coin, amount, buy_price FROM portfolio WHERE chat=? ORDER BY id",
                      (str(chat_id),))
            rows = c.fetchall()
    except Exception:
        rows = []
    if not rows:
        edit(chat_id, message_id, "💼 No assets to remove.",
             [[{"text": "⬅ Back", "callback_data": "portfolio"}]])
        return
    buttons = [
        [{"text": "%s ×%g @ %s" % (coin, amt, format_price(bp)),
          "callback_data": "port_del:%d" % pid}]
        for pid, coin, amt, bp in rows
    ]
    buttons.append([{"text": "⬅ Back", "callback_data": "portfolio"}])
    edit(chat_id, message_id, "💼 <b>Remove Asset</b>\n\nTap a position to delete:", buttons)

def export_portfolio_csv(chat_id):
    """Export portfolio as CSV."""
    try:
        with get_db_cursor() as c:
            c.execute("SELECT coin, amount, buy_price, added_at FROM portfolio WHERE chat=?",
                      (str(chat_id),))
            rows = c.fetchall()
    except Exception:
        rows = []
    if not rows:
        send(chat_id, "💼 No assets to export.",
             [[{"text": "⬅ Back", "callback_data": "portfolio"}]])
        return

    csv_data = "Coin,Amount,Buy Price,Added At,Current Price,P&L\n"
    for coin, amount, buy_price, added_at in rows:
        price, _ = get_best_price(coin)
        current_price = price if price else 0
        pnl = (current_price - buy_price) * amount
        csv_data += f"{coin},{amount},{buy_price},{added_at},{current_price},{pnl:.2f}\n"

    # Send as file
    try:
        with io.BytesIO(csv_data.encode()) as f:
            f.seek(0)
            tg_photo(
                {"chat_id": str(chat_id), "caption": "📊 Portfolio Export"},
                f.getvalue(),
                filename="portfolio.csv"
            )
    except Exception as e:
        print("[EXPORT_PORTFOLIO ERROR] %s" % e)
        send(chat_id, "Could not export portfolio. Try again later.",
             [[{"text": "⬅ Back", "callback_data": "portfolio"}]])

# ── ALERTS ────────────────────────────────────────────────────────────────────
def show_my_alerts(chat_id, message_id):
    try:
        with get_db_cursor() as c:
            c.execute("SELECT id, coin, condition, target, label FROM alerts WHERE chat=? AND active=1 ORDER BY id",
                      (str(chat_id),))
            rows = c.fetchall()
    except Exception:
        rows = []

    if not rows:
        edit(chat_id, message_id,
             "📋 <b>My Alerts</b>\n\nYou have no active alerts.",
             [[{"text": "➕ Set Alert", "callback_data": "alerts"},
               {"text": "⬅ Back",     "callback_data": "main_menu"}]])
        return

    cond_labels = {"above": "📈 ↑", "below": "📉 ↓", "exact": "🎯 =",
                   "pct_up": "📊 +%", "pct_down": "📊 -%"}
    lines = ["📋 <b>My Active Alerts</b>", ""]
    for aid, coin, condition, target, label in rows:
        cl = cond_labels.get(condition, condition)
        tgt = ("%.2f%%" % target) if "pct" in condition else format_price(target)
        lbl = " — <i>%s</i>" % label if label else ""
        lines.append("  #%d  <b>%s</b>  %s  <b>%s</b>%s" % (aid, coin, cl, tgt, lbl))
    lines.append("")
    lines.append("Tap a button below to delete an alert:")

    buttons = [
        [{"text": "🗑 Delete #%d %s" % (aid, coin), "callback_data": "alert_del:%d" % aid}]
        for aid, coin, condition, target, label in rows
    ]
    buttons.append([{"text": "➕ Add Alert",  "callback_data": "alerts"},
                    {"text": "🏠 Main Menu", "callback_data": "main_menu"}])
    edit(chat_id, message_id, "\n".join(lines), buttons)

def set_alert_price(chat_id, message_id, coin, condition):
    price, _ = get_best_price(coin)
    base = price if price else 1000
    labels = {"above": "📈 Above", "below": "📉 Below", "exact": "🎯 Exact",
              "pct_up": "📊 % Rise", "pct_down": "📊 % Drop"}

    is_pct = "pct" in condition
    if is_pct:
        choices = [1, 2, 5, 10, 15, 20]
        buttons = []
        row = []
        for val in choices:
            row.append({"text": "%d%%" % val,
                        "callback_data": "alert_set:%s:%s:%.2f" % (coin, condition, val)})
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        header = ("🚨 <b>Alert: %s — %s</b>\n\nCurrent: <b>%s</b>\n\n"
                  "Choose trigger threshold:") % (coin, labels[condition], format_price(base))
    else:
        offsets = [-10, -5, -2, 2, 5, 10]
        choices = [round(base * (1 + p / 100), 2) for p in offsets]
        buttons = []
        row = []
        for val in choices:
            row.append({"text": "%s" % format_price(val),
                        "callback_data": "alert_set:%s:%s:%.2f" % (coin, condition, val)})
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        header = ("🚨 <b>Alert: %s — %s</b>\n\nCurrent: <b>%s</b>\n\n"
                  "Choose a target price or enter custom:") % (coin, labels[condition], format_price(base))

    buttons.append([{"text": "✏️ Custom Value",
                     "callback_data": "alert_custom:%s:%s" % (coin, condition)}])
    buttons.append([{"text": "⬅ Back", "callback_data": "alert_coin:%s" % coin}])
    edit(chat_id, message_id, header, buttons)

def prompt_custom_alert_price(chat_id, message_id, coin, condition):
    set_state(chat_id, "awaiting_alert_price", {"coin": coin, "condition": condition})
    labels = {"above": "📈 Above", "below": "📉 Below", "exact": "🎯 Exact",
              "pct_up": "📊 % Rise", "pct_down": "📊 % Drop"}
    is_pct = "pct" in condition
    example = "5 (for 5%)" if is_pct else "67000 or 67000.50"
    edit(chat_id, message_id,
         "✏️ <b>Custom Alert: %s — %s</b>\n\n"
         "Type your value and send it (e.g. <code>%s</code>)." % (coin, labels[condition], example),
         [[{"text": "⬅ Cancel", "callback_data": "alert_coin:%s" % coin}]])

def save_alert(chat_id, coin, condition, target, label=""):
    try:
        with get_db_cursor() as c:
            c.execute(
                "INSERT INTO alerts (chat, coin, condition, target, label) VALUES (?, ?, ?, ?, ?)",
                (str(chat_id), coin, condition, target, label)
            )
    except Exception as e:
        print("[SAVE_ALERT ERROR] %s" % e)

def handle_custom_alert_text(chat_id, text, state_data):
    coin = state_data.get("coin")
    condition = state_data.get("condition")
    cleaned = text.strip().replace(",", "").replace("$", "").replace("%", "")
    try:
        target = float(cleaned)
        if target <= 0:
            raise ValueError("non-positive")
    except (ValueError, TypeError):
        send(chat_id,
             "⚠️ Invalid value. Send a plain number, e.g. <code>67000</code> or <code>5</code>.")
        return

    clear_state(chat_id)
    save_alert(chat_id, coin, condition, target)
    labels = {"above": "📈 Above", "below": "📉 Below", "exact": "🎯 Exact",
              "pct_up": "📊 % Rise", "pct_down": "📊 % Drop"}
    tgt_str = "%.2f%%" % target if "pct" in condition else format_price(target)
    send(chat_id,
         "✅ <b>Alert saved!</b>\n\n"
         "  Coin      : <b>%s</b>\n"
         "  Condition : %s\n"
         "  Target    : <b>%s</b>\n\n"
         "You will be notified when triggered." % (coin, labels.get(condition, condition), tgt_str),
         [[{"text": "➕ Add Another", "callback_data": "alerts"},
           {"text": "📋 My Alerts",  "callback_data": "my_alerts"},
           {"text": "🏠 Main Menu",  "callback_data": "main_menu"}]])

# ── PORTFOLIO TEXT INPUT HANDLERS ─────────────────────────────────────────────
def handle_port_coin_selected(chat_id, message_id, coin):
    set_state(chat_id, "awaiting_port_amount", {"coin": coin})
    price, _ = get_best_price(coin)
    price_str = "  Current price: <b>%s</b>" % format_price(price) if price else ""
    edit(chat_id, message_id,
         "💼 <b>Add %s to Portfolio</b>\n\n%s\n\nHow many <b>%s</b> did you buy?\n"
         "Send the amount, e.g. <code>0.5</code>" % (coin, price_str, coin),
         [[{"text": "⬅ Cancel", "callback_data": "portfolio"}]])

def handle_port_amount(chat_id, text, state_data):
    cleaned = text.strip().replace(",", "")
    try:
        amount = float(cleaned)
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        send(chat_id, "⚠️ Invalid amount. Send a number, e.g. <code>0.5</code>")
        return
    coin = state_data["coin"]
    set_state(chat_id, "awaiting_port_price", {"coin": coin, "amount": amount})
    price, _ = get_best_price(coin)
    price_str = ("\n\nCurrent market price: <b>%s</b>\n"
                 "Send <code>market</code> to use it, or type your buy price:") % format_price(price) if price else ""
    send(chat_id,
         "💼 What was your <b>buy price</b> per <b>%s</b>?%s" % (coin, price_str))

def handle_port_price(chat_id, text, state_data):
    coin = state_data["coin"]
    amount = state_data["amount"]

    if text.strip().lower() == "market":
        price, _ = get_best_price(coin)
        if not price:
            send(chat_id, "⚠️ Could not fetch market price. Please enter it manually.")
            return
        buy_price = price
    else:
        cleaned = text.strip().replace(",", "").replace("$", "")
        try:
            buy_price = float(cleaned)
            if buy_price <= 0:
                raise ValueError
        except (ValueError, TypeError):
            send(chat_id, "⚠️ Invalid price. Enter a number or <code>market</code>.")
            return

    clear_state(chat_id)
    try:
        with get_db_cursor() as c:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute(
                "INSERT INTO portfolio (chat, coin, amount, buy_price, added_at) VALUES (?, ?, ?, ?, ?)",
                (str(chat_id), coin, amount, buy_price, now)
            )
    except Exception as e:
        print("[HANDLE_PORT_PRICE ERROR] %s" % e)
        send(chat_id, "⚠️ Could not save position. Try again.")
        return

    cost = amount * buy_price
    send(chat_id,
         "✅ <b>Position added!</b>\n\n"
         "  Coin      : <b>%s</b>\n"
         "  Amount    : <b>%g</b>\n"
         "  Buy Price : <b>%s</b>\n"
         "  Total Cost: <b>$%.2f</b>" % (coin, amount, format_price(buy_price), cost),
         [[{"text": "💼 Portfolio",   "callback_data": "portfolio"},
           {"text": "🏠 Main Menu",   "callback_data": "main_menu"}]])

# ── P2P ───────────────────────────────────────────────────────────────────────
def show_p2p_menu(chat_id, message_id):
    buttons = []
    row = []
    for crypto in P2P_CRYPTOS:
        row.append({"text": crypto, "callback_data": "p2p_crypto:%s" % crypto})
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([{"text": "⬅ Back", "callback_data": "main_menu"}])
    edit(chat_id, message_id, "💱 <b>P2P Rates</b>\n\nChoose a crypto to convert:", buttons)

def show_p2p_fiat_menu(chat_id, message_id, crypto):
    buttons = []
    row = []
    for fiat, (name, symbol) in P2P_FIATS.items():
        row.append({"text": "%s %s" % (symbol, fiat),
                    "callback_data": "p2p_rate:%s:%s" % (crypto, fiat)})
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([{"text": "⬅ Back", "callback_data": "p2p"}])
    edit(chat_id, message_id, "💱 <b>%s P2P</b>\n\nChoose your local currency:" % crypto, buttons)

def _p2p_median(prices):
    if not prices:
        return None
    prices.sort()
    return prices[len(prices) // 2]

def _binance_p2p(side, asset, fiat_code):
    """Binance P2P — public endpoint, no auth. side: BUY or SELL."""
    try:
        resp = requests.post(
            "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search",
            json={"asset": asset, "fiat": fiat_code, "merchantCheck": False,
                  "page": 1, "publisherType": None, "rows": 10, "tradeType": side},
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        if resp.status_code != 200:
            return None
        ads = resp.json().get("data") or []
        return _p2p_median([float(a["adv"]["price"]) for a in ads
                            if a.get("adv", {}).get("price")])
    except Exception as e:
        print("[BINANCE P2P] %s/%s %s: %s" % (asset, fiat_code, side, e))
        return None

def _bybit_p2p(side, asset, fiat_code):
    """Bybit P2P — public endpoint, no auth."""
    try:
        bybit_side = "1" if side == "BUY" else "0"
        resp = requests.post(
            "https://api2.bybit.com/fiat/otc/item/list",
            json={"userId": "", "tokenId": asset, "currencyId": fiat_code,
                  "payment": [], "side": bybit_side, "size": "10", "page": "1",
                  "amount": "", "authMaker": False, "canTrade": False},
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        if resp.status_code != 200:
            return None
        items = resp.json().get("result", {}).get("items") or []
        return _p2p_median([float(i["price"]) for i in items if i.get("price")])
    except Exception as e:
        print("[BYBIT P2P] %s/%s %s: %s" % (asset, fiat_code, side, e))
        return None

def _okx_p2p(side, asset, fiat_code):
    """OKX P2P public endpoint."""
    try:
        resp = requests.post(
            "https://www.okx.com/v3/c2c/tradingOrders/books",
            json={"quoteCurrency": fiat_code, "baseCurrency": asset,
                  "side": "sell" if side == "BUY" else "buy",
                  "paymentMethod": "ALL", "userType": "ALL",
                  "showTrade": False, "showFollow": False,
                  "showAlreadyTraded": False, "isAbleFilter": False},
            headers={"Content-Type": "application/json",
                     "User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        items = data.get("data", {}).get("sell" if side == "BUY" else "buy", [])
        prices = []
        for item in items[:10]:
            try:
                prices.append(float(item.get("price", 0)))
            except (TypeError, ValueError):
                pass
        if not prices:
            return None
        prices.sort()
        return prices[len(prices) // 2]
    except Exception as e:
        print("[OKX P2P] %s/%s %s: %s" % (asset, fiat_code, side, e))
        return None

def _noones_p2p(side, asset, fiat_code):
    """Noones P2P (formerly LocalBitcoins) — Nigerian focused."""
    try:
        direction = "sell" if side == "BUY" else "buy"
        resp = requests.get(
            "https://noones.com/api/noones/v1/offer/list",
            params={"offer_type": direction, "currency_code": fiat_code,
                    "payment_method": "all-online-offers",
                    "crypto_currency_code": asset, "page": 1},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        offers = data.get("data", {}).get("offer_list", [])
        prices = []
        for offer in offers[:10]:
            try:
                prices.append(float(offer.get("fiat_price_per_crypto", 0)))
            except (TypeError, ValueError):
                pass
        if not prices:
            return None
        prices.sort()
        return prices[len(prices) // 2]
    except Exception as e:
        print("[NOONES P2P] %s/%s %s: %s" % (asset, fiat_code, side, e))
        return None

def _get_p2p_rate(side, crypto, fiat, is_pro_user=False):
    """
    Full P2P rate chain:
    1. Community submissions (all users)
    2. Admin submitted rate
    3. Binance P2P
    4. Bybit P2P
    5. OKX P2P
    6. Noones P2P
    7. Spot estimate (clearly labeled)
    """
    # Community rate always tried first — available to all
    comm = get_community_rate(crypto, fiat)
    if comm:
        rate = comm["buy"] if side == "BUY" else comm["sell"]
        return rate, "community", comm

    # Live P2P sources
    for fn, name in [
        (_binance_p2p, "Binance P2P"),
        (_bybit_p2p, "Bybit P2P"),
        (_okx_p2p, "OKX P2P"),
        (_noones_p2p, "Noones P2P"),
    ]:
        try:
            rate = fn(side, crypto, fiat)
            if rate:
                return rate, name, None
        except Exception:
            continue

    # Spot estimate fallback
    spot_usd, _ = get_best_price(crypto)
    fiat_rate = get_fiat_rates().get(fiat)
    if spot_usd and fiat_rate:
        val = spot_usd * fiat_rate
        rate = round(val * 1.01, 2) if side == "BUY" else round(val * 0.99, 2)
        return rate, "spot", None

    return None, None, None

def show_p2p_rate_v2(chat_id, message_id, crypto, fiat):
    """Fixed P2P rate display that actually uses community rates."""
    track(chat_id, "p2p_rate")
    fiat_name, fiat_symbol = P2P_FIATS.get(fiat, (fiat, fiat))
    mark_p2p_used(chat_id)

    def fmt(v):
        if v is None:
            return "N/A"
        if v >= 1000:
            return "%s%s" % (fiat_symbol, "{:,.0f}".format(v))
        elif v >= 1:
            return "%s%.2f" % (fiat_symbol, v)
        else:
            return "%s%.6f" % (fiat_symbol, v)

    buy_rate = None
    sell_rate = None
    source = None
    is_pro_user = is_pro(chat_id)

    # 1. Community rates (Pro users first)
    community = get_community_rate(crypto, fiat)
    if community and is_pro_user:
        buy_rate = community["buy"]
        sell_rate = community["sell"]
        source = "Community (%d traders)" % community["count"]

    # 2. Binance P2P
    if not buy_rate:
        b_buy = _binance_p2p("BUY", crypto, fiat)
        b_sell = _binance_p2p("SELL", crypto, fiat)
        if b_buy and b_sell:
            buy_rate = b_buy
            sell_rate = b_sell
            source = "Binance P2P"

    # 3. Bybit P2P
    if not buy_rate:
        bb_buy = _bybit_p2p("BUY", crypto, fiat)
        bb_sell = _bybit_p2p("SELL", crypto, fiat)
        if bb_buy and bb_sell:
            buy_rate = bb_buy
            sell_rate = bb_sell
            source = "Bybit P2P"

    # 4. Community rates for free users (after exchange attempts)
    if not buy_rate and community:
        buy_rate = community["buy"]
        sell_rate = community["sell"]
        source = "Community (%d traders)" % community["count"]

    # 5. Spot estimate
    if not buy_rate:
        rates = get_fiat_rates()
        fiat_per_usd = rates.get(fiat)
        price, _ = get_best_price(crypto)
        if price and fiat_per_usd:
            val = price * fiat_per_usd
            buy_rate = round(val * 1.01, 2)
            sell_rate = round(val * 0.99, 2)
            source = "estimate"

    if not buy_rate:
        edit(chat_id, message_id,
             "Could not fetch <b>%s/%s</b> rate. Try again shortly." % (crypto, fiat),
             [[{"text": "🔄 Retry",  "callback_data": "p2p_rate:%s:%s" % (crypto, fiat)},
               {"text": "⬅ Back",   "callback_data": "menu_nigeria"}]])
        return

    spread = round(buy_rate - sell_rate, 2)

    community_line = ""
    if community and not is_pro_user:
        community_line = ("\n\n⭐ <i>Pro users see real community rates from "
                         "%d active traders. /upgrade to unlock.</i>" % community["count"])

    source_line = ("<i>⚠️ Estimated rate — no live P2P data available</i>"
                   if source == "estimate" else
                   "<i>Source: %s</i>" % source)

    lines = [
        "💱 <b>%s / %s</b>" % (crypto, fiat),
        "<i>%s</i>" % fiat_name, "",
        "  Buy  %s  →  <b>%s</b>" % (crypto, fmt(buy_rate)),
        "  Sell %s  →  <b>%s</b>" % (crypto, fmt(sell_rate)),
        "  Spread   →  <b>%s</b>" % fmt(spread), "",
        source_line,
        community_line,
    ]

    buttons = [
        [{"text": "🔄 Refresh",     "callback_data": "p2p_rate:%s:%s" % (crypto, fiat)},
         {"text": "📤 Submit Rate", "callback_data": "submit_rate"}],
        [{"text": "💱 P2P Center",  "callback_data": "menu_nigeria"}],
    ]
    edit(chat_id, message_id, "\n".join(lines), buttons)

def mark_p2p_used(chat_id):
    try:
        with get_db_cursor() as c:
            c.execute("INSERT INTO rate_submissions (chat, p2p_used) VALUES (?,1) "
                      "ON CONFLICT(chat) DO UPDATE SET p2p_used=1", (str(chat_id),))
    except Exception as e:
        print("[MARK_P2P_USED ERROR] %s" % e)

# ── SUBMIT RATE FLOW ─────────────────────────────────────────────────────────
def show_submit_rate_menu(chat_id, message_id, from_p2p=False):
    track(chat_id, "submit_rate")
    trust_info = get_user_trust(chat_id)
    if trust_info["blocked"] and chat_id not in ADMIN_IDS:
        edit(chat_id, message_id,
             "⚠️ Rate submissions are temporarily unavailable for your account.\n\n"
             "Please try again later.",
             [[{"text": "⬅ Back", "callback_data": "menu_nigeria"}]])
        return
    verified = trust_info["verified"]
    trust = trust_info["trust"]
    badge = (" 🏆 Trusted Contributor" if trust >= 3 else
             " ⭐ Verified Contributor" if trust >= 2 else "")
    intro = (
        "📤 <b>Submit P2P Rate%s</b>\n\n"
        "Help the community by sharing the rate you see right now "
        "on your exchange.\n\n"
        "<b>How it works:</b>\n"
        "1️ Choose crypto and currency\n"
        "2️ Enter the buy and sell rate you see\n"
        "3️ Your submission is verified automatically\n"
        "4️ If accurate it goes live for the community\n\n"
        "<i>You have %d verified submission%s so far.</i>\n\n"
        "Which crypto?" % (badge, verified, "s" if verified != 1 else "")
    )
    buttons = []
    row = []
    for crypto in ["USDT", "BTC", "ETH", "BNB", "USDC", "SOL"]:
        row.append({"text": crypto, "callback_data": "submit_rate_crypto:%s" % crypto})
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([{"text": "⬅ Back",
                     "callback_data": "p2p" if from_p2p else "menu_nigeria"}])
    edit(chat_id, message_id, intro, buttons)

def show_submit_rate_fiat(chat_id, message_id, crypto):
    buttons = []
    row = []
    for fiat, (name, sym) in P2P_FIATS.items():
        row.append({"text": "%s %s" % (sym, fiat),
                    "callback_data": "submit_rate_fiat:%s:%s" % (crypto, fiat)})
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([{"text": "⬅ Back", "callback_data": "submit_rate"}])
    edit(chat_id, message_id,
         "📤 <b>Submit Rate — %s</b>\n\nWhich currency?" % crypto,
         buttons)

def show_submit_rate_exchange(chat_id, message_id, crypto, fiat):
    edit(chat_id, message_id,
         "📤 <b>Submit Rate — %s/%s</b>\n\n"
         "Which exchange are you seeing this rate on?" % (crypto, fiat),
         [[{"text": "Binance P2P",
            "callback_data": "submit_rate_ex:%s:%s:Binance" % (crypto, fiat)},
           {"text": "Bybit P2P",
            "callback_data": "submit_rate_ex:%s:%s:Bybit" % (crypto, fiat)}],
          [{"text": "OKX P2P",
            "callback_data": "submit_rate_ex:%s:%s:OKX" % (crypto, fiat)},
           {"text": "Other",
            "callback_data": "submit_rate_ex:%s:%s:Other" % (crypto, fiat)}],
          [{"text": "⬅ Back",
            "callback_data": "submit_rate_fiat:%s:%s" % (crypto, fiat)}]])

def prompt_submit_rate_values(chat_id, message_id, crypto, fiat, exchange):
    set_state(chat_id, "awaiting_rate_submit",
              {"crypto": crypto, "fiat": fiat, "exchange": exchange})
    fiat_sym = P2P_FIATS.get(fiat, (fiat, fiat))[1]
    spot_usd, _ = get_best_price(crypto)
    rates_obj = get_fiat_rates()
    fiat_rate = rates_obj.get(fiat)
    ref_line = ""
    if spot_usd and fiat_rate:
        est = spot_usd * fiat_rate
        ref_line = "\n<i>Current estimate: %s%s</i>" % (
            fiat_sym, "{:,.0f}".format(est))
    edit(chat_id, message_id,
         "📤 <b>Submit Rate — %s/%s on %s</b>\n\n"
         "What rate do you see right now?\n\n"
         "Send as: <code>buy sell</code>\n"
         "Example: <code>1612 1588</code>\n\n"
         "Buy = what you pay to get %s\n"
         "Sell = what you receive when selling %s%s" % (
             crypto, fiat, exchange, crypto, crypto, ref_line),
         [[{"text": "⬅ Cancel", "callback_data": "menu_nigeria"}]])

def handle_rate_submit(chat_id, text, state_data):
    clear_state(chat_id)
    crypto = state_data.get("crypto", "USDT")
    fiat = state_data.get("fiat", "NGN")
    exchange = state_data.get("exchange", "Unknown")
    fiat_sym = P2P_FIATS.get(fiat, (fiat, fiat))[1]
    parts = text.strip().replace(",", "").split()
    if len(parts) != 2:
        send(chat_id,
             "⚠️ Please send two numbers separated by a space.\n"
             "Example: <code>1612 1588</code>",
             [[{"text": "🔄 Try Again", "callback_data": "submit_rate"},
               {"text": "⬅ P2P", "callback_data": "menu_nigeria"}]])
        return
    try:
        buy = float(parts[0])
        sell = float(parts[1])
    except ValueError:
        send(chat_id,
             "⚠️ Invalid numbers. Send plain numbers like <code>1612 1588</code>",
             [[{"text": "🔄 Try Again", "callback_data": "submit_rate"}]])
        return
    is_admin = chat_id in ADMIN_IDS
    success, result = submit_community_rate(
        chat_id, crypto, fiat, buy, sell, exchange, is_admin=is_admin)
    if not success:
        if result == "unable":
            send(chat_id,
                 "⚠️ Unable to process your submission right now. "
                 "Please try again later.",
                 [[{"text": "⬅ P2P Center", "callback_data": "menu_nigeria"}]])
        else:
            send(chat_id,
                 "⚠️ <b>Submission not accepted</b>\n\n%s\n\n"
                 "<i>Please check the rate on your exchange and try again.</i>" % result,
                 [[{"text": "🔄 Try Again", "callback_data": "submit_rate"},
                   {"text": "⬅ P2P Center", "callback_data": "menu_nigeria"}]])
        return
    if is_admin or result == "live":
        msg = (
            "✅ <b>Rate submitted and live!</b>\n\n"
            "  %s/%s on %s\n"
            "  Buy  : <b>%s%s</b>\n"
            "  Sell : <b>%s%s</b>\n\n"
            "%s" % (
                crypto, fiat, exchange,
                fiat_sym, "{:,.0f}".format(buy),
                fiat_sym, "{:,.0f}".format(sell),
                "<i>Admin submission — live instantly.</i>" if is_admin else
                "Your rate is now visible to the community. Thank you! 🙏")
        )
    else:
        msg = (
            "✅ <b>Rate received — verifying...</b>\n\n"
            "  %s/%s on %s\n"
            "  Buy  : <b>%s%s</b>\n"
            "  Sell : <b>%s%s</b>\n\n"
            "Your rate is being cross-checked with other traders. "
            "It will go live automatically when verified.\n\n"
            "<i>More verified submissions = higher trust level = "
            "faster approvals in future.</i>" % (
                crypto, fiat, exchange,
                fiat_sym, "{:,.0f}".format(buy),
                fiat_sym, "{:,.0f}".format(sell))
        )
    send(chat_id, msg,
         [[{"text": "💱 See P2P Rates", "callback_data": "p2p"},
           {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])

# ── P2P ALERT SYSTEM ──────────────────────────────────────────────────────────
def show_p2p_alerts_menu(chat_id, message_id):
    try:
        with get_db_cursor() as c:
            c.execute("SELECT id, crypto, fiat, condition, target FROM p2p_alerts "
                      "WHERE chat=? AND active=1 ORDER BY id", (str(chat_id),))
            rows = c.fetchall()
    except Exception:
        rows = []
    lines = ["🔔 <b>P2P Alerts</b>", ""]
    if rows:
        for aid, crypto, fiat, cond, target in rows:
            fiat_sym = P2P_FIATS.get(fiat, (fiat, fiat))[1]
            cond_str = "above" if cond == "above" else "below"
            lines.append("  • %s/%s %s %s%s" % (
                crypto, fiat, cond_str, fiat_sym, "{:,.0f}".format(target)))
        lines.append("")
    else:
        lines.append("No active P2P alerts.\n")
    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "➕ Add Alert",    "callback_data": "p2p_alert_add"},
           {"text": "🗑 Remove Alert", "callback_data": "p2p_alert_remove"}],
          [{"text": "🏠 Main Menu",   "callback_data": "main_menu"}]])

def show_p2p_alert_new(chat_id, message_id):
    """Show P2P alert crypto selection."""
    buttons = []
    row = []
    for crypto in P2P_CRYPTOS:
        row.append({"text": crypto, "callback_data": "p2p_alc:%s" % crypto})
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([{"text": "⬅ Back", "callback_data": "p2p_alerts"}])
    edit(chat_id, message_id, "🔔 <b>New P2P Alert</b> — choose crypto:", buttons)

def show_p2p_alert_add(chat_id, message_id):
    show_p2p_alert_new(chat_id, message_id)

def show_p2p_alert_fiat(chat_id, message_id, crypto):
    buttons = []
    row = []
    for fiat, (name, sym) in P2P_FIATS.items():
        row.append({"text": "%s %s" % (sym, fiat),
                    "callback_data": "p2p_alf:%s:%s" % (crypto, fiat)})
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([{"text": "⬅ Back", "callback_data": "p2p_alert_add"}])
    edit(chat_id, message_id, "🔔 <b>%s P2P Alert</b> — choose fiat:" % crypto, buttons)

def show_p2p_alert_cond(chat_id, message_id, crypto, fiat):
    fiat_sym = P2P_FIATS.get(fiat, (fiat, fiat))[1]
    edit(chat_id, message_id,
         "🔔 <b>%s/%s P2P Alert</b>\n\nAlert me when rate goes:" % (crypto, fiat),
         [[{"text": "📈 Above target", "callback_data": "p2p_alcd:%s:%s:above" % (crypto, fiat)},
           {"text": "📉 Below target", "callback_data": "p2p_alcd:%s:%s:below" % (crypto, fiat)}],
          [{"text": "⬅ Back", "callback_data": "p2p_alf:%s:%s" % (crypto, fiat)}]])

def prompt_p2p_alert_target(chat_id, message_id, crypto, fiat, condition):
    """Prompt user for P2P alert target value."""
    fiat_name, fiat_sym = P2P_FIATS.get(fiat, (fiat, fiat))
    set_state(chat_id, "awaiting_p2p_alert_target",
              {"crypto": crypto, "fiat": fiat, "condition": condition})
    edit(chat_id, message_id,
         "🔔 <b>%s/%s — %s</b>\n\n"
         "Type your target rate in <b>%s</b>.\n"
         "Example: <code>1580</code>" % (crypto, fiat, condition, fiat_name),
         [[{"text": "⬅ Cancel", "callback_data": "p2p_alerts"}]])

def handle_p2p_alert_target(chat_id, text, state_data):
    clear_state(chat_id)
    crypto = state_data["crypto"]
    fiat = state_data["fiat"]
    condition = state_data["condition"]
    try:
        target = float(text.strip().replace(",", ""))
        if target <= 0:
            raise ValueError
    except ValueError:
        send(chat_id, "⚠️ Invalid amount. Send a plain number e.g. <code>1580</code>")
        return
    try:
        with get_db_cursor() as c:
            c.execute("INSERT INTO p2p_alerts (chat, crypto, fiat, condition, target) VALUES (?,?,?,?,?)",
                      (str(chat_id), crypto, fiat, condition, target))
    except Exception as e:
        print("[HANDLE_P2P_ALERT_TARGET ERROR] %s" % e)
        send(chat_id, "⚠️ Could not save alert. Try again.")
        return
    fiat_sym = P2P_FIATS.get(fiat, (fiat, fiat))[1]
    send(chat_id,
         "✅ <b>P2P Alert saved!</b>\n\n"
         "  Pair      : <b>%s/%s</b>\n"
         "  Condition : <b>%s</b>\n"
         "  Target    : <b>%s%s</b>\n\n"
         "You'll be notified when triggered." % (
             crypto, fiat, condition, fiat_sym, "{:,.0f}".format(target)),
         [[{"text": "🔔 My P2P Alerts", "callback_data": "p2p_alerts"},
           {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])

def remove_p2p_alert_menu(chat_id, message_id):
    try:
        with get_db_cursor() as c:
            c.execute("SELECT id, crypto, fiat, condition, target FROM p2p_alerts "
                      "WHERE chat=? AND active=1", (str(chat_id),))
            rows = c.fetchall()
    except Exception:
        rows = []
    if not rows:
        edit(chat_id, message_id, "🔔 No active P2P alerts to remove.", BACK_MAIN)
        return
    buttons = []
    for aid, crypto, fiat, cond, target in rows:
        fiat_sym = P2P_FIATS.get(fiat, (fiat, fiat))[1]
        buttons.append([{"text": "%s/%s %s %s%s" % (
            crypto, fiat, cond, fiat_sym, "{:,.0f}".format(target)),
            "callback_data": "p2p_aldel:%d" % aid}])
    buttons.append([{"text": "⬅ Back", "callback_data": "p2p_alerts"}])
    edit(chat_id, message_id, "🗑 <b>Remove P2P Alert</b>\n\nTap one to delete:", buttons)

_p2p_alert_last_fired = {}

def check_p2p_alerts():
    """Check P2P alerts with 1-hour cooldown to prevent spam."""
    now = datetime.now()
    try:
        with get_db_cursor() as c:
            c.execute("SELECT id, chat, crypto, fiat, condition, target FROM p2p_alerts WHERE active=1")
            alerts = c.fetchall()
    except Exception as e:
        print("[CHECK_P2P_ALERTS ERROR] %s" % e)
        return

    for aid, chat, crypto, fiat, condition, target in alerts:
        last_fired = _p2p_alert_last_fired.get(aid)
        if last_fired and (now - last_fired).total_seconds() < 3600:
            continue
        buy_rate = _binance_p2p("BUY", crypto, fiat) or _bybit_p2p("BUY", crypto, fiat)
        if buy_rate is None:
            rates = get_fiat_rates()
            p, _ = get_best_price(crypto)
            r = rates.get(fiat)
            if p and r:
                buy_rate = round(p * r, 2)
        if buy_rate is None:
            continue
        triggered = (condition == "above" and buy_rate >= target) or \
                    (condition == "below" and buy_rate <= target)
        if triggered:
            fiat_sym = P2P_FIATS.get(fiat, (fiat, fiat))[1]
            direction = "risen above" if condition == "above" else "dropped below"
            send(int(chat),
                 "🔔 <b>P2P Alert Triggered!</b>\n\n"
                 "<b>%s/%s</b> buy rate has %s your target.\n\n"
                 "  Target : <b>%s%s</b>\n"
                 "  Now    : <b>%s%s</b>\n\n"
                 "<i>Will re-check in 1 hour.</i>" % (
                     crypto, fiat, direction,
                     fiat_sym, "{:,.0f}".format(target),
                     fiat_sym, "{:,.0f}".format(buy_rate)),
                 [[{"text": "💱 P2P Center", "callback_data": "menu_nigeria"},
                   {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])
            _p2p_alert_last_fired[aid] = now
            time.sleep(0.5)
            prompt_user_to_submit(int(chat), crypto, fiat)

# ── USER PROMPTS ──────────────────────────────────────────────────────────────
def prompt_user_to_submit(chat_id, crypto="USDT", fiat="NGN"):
    fiat_sym = P2P_FIATS.get(fiat, (fiat, fiat))[1]
    send(chat_id,
         "💱 <b>What's %s/%s trading at on your exchange right now?</b>\n\n"
         "If you're on Binance P2P or Bybit P2P, tap below to share the rate. "
         "It helps every trader in the community — takes less than 10 seconds. 🙏"
         % (crypto, fiat),
         [[{"text": "📤 Submit Rate Now", "callback_data": "submit_rate"},
           {"text": "Maybe Later", "callback_data": "main_menu"}]])
    try:
        with get_db_cursor() as c:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT INTO rate_submissions (chat, last_prompted) VALUES (?,?) "
                      "ON CONFLICT(chat) DO UPDATE SET last_prompted=?", (str(chat_id), now, now))
    except Exception as e:
        print("[PROMPT_USER_TO_SUBMIT DB ERROR] %s" % e)

def send_daily_rate_prompts():
    try:
        with get_db_cursor() as c:
            cutoff = (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("SELECT chat FROM rate_submissions WHERE p2p_used=1 "
                      "AND (last_prompted IS NULL OR last_prompted < ?)", (cutoff,))
            chats = [r[0] for r in c.fetchall()]
    except Exception as e:
        print("[SEND_DAILY_RATE_PROMPTS ERROR] %s" % e)
        return
    for cid in chats[:100]:
        try:
            prompt_user_to_submit(int(cid))
            time.sleep(0.05)
        except Exception as e:
            print("[PROMPT ERROR] %s: %s" % (cid, e))
    if chats:
        print("[PROMPTS] Sent to %d users" % min(len(chats), 100))

# ── AI RATE LIMITING ──────────────────────────────────────────────────────────
_ai_usage = {}

def check_ai_rate_limit(chat_id):
    """Returns (allowed, remaining, reset_in_seconds)."""
    if chat_id in ADMIN_IDS:
        return True, 999, 0
    now = datetime.now()
    hour_ago = now - timedelta(hours=1)
    usage = _ai_usage.get(str(chat_id), [])
    usage = [t for t in usage if t > hour_ago]
    _ai_usage[str(chat_id)] = usage
    remaining = 5 - len(usage)
    if remaining <= 0:
        oldest = min(usage)
        reset_in = int((oldest + timedelta(hours=1) - now).total_seconds())
        return False, 0, reset_in
    return True, remaining, 0

def record_ai_usage(chat_id):
    key = str(chat_id)
    if key not in _ai_usage:
        _ai_usage[key] = []
    _ai_usage[key].append(datetime.now())

AI_LIMIT_PER_HOUR = 5

# ── AI SYSTEM ──────────────────────────────────────────────────────────────────
CRYPTO_SYSTEM_PROMPT = (
    "You are Market Pulse AI — a professional crypto market analyst and assistant "
    "for Nigerian traders built into the Market Pulse Telegram bot.\n\n"
    "YOUR ROLE:\n"
    "1. Answer crypto, trading, DeFi, and finance questions\n"
    "2. Explain what happened, why it happened, what it means, and risks involved\n"
    "3. Help users navigate the Market Pulse bot and channel\n"
    "4. Educate traders on market concepts clearly and simply\n\n"
    "MARKET PULSE BOT MENU:\n"
    "📈 Markets → Market prices, Charts, Top Gainers, Top Losers, Dominance\n"
    "🧠 Intelligence → Ask AI (you), News, Fear & Greed Index, Data Sources\n"
    "🇳🇬 P2P Center → P2P Rates, P2P Alerts, Submit Rate, Arbitrage Scanner\n"
    "🔔 Alerts → Create Alert, My Alerts, P2P Alerts, Watchlist\n"
    "🛠 Tools → Search Coin, Convert, History, Status\n"
    "👤 My Account → Portfolio, Referral Program, My Stats, Pro Upgrade\n"
    "❓ Help → Guides for every feature\n"
    "💎 Pro → Market Pulse Pro upgrade (₦2,000/month)\n\n"
    "MARKET PULSE CHANNEL:\n"
    "The official channel posts market snapshots, P2P rates, whale alerts, "
    "morning briefs, evening recaps, news, and the Saturday Weekly Edge.\n\n"
    "IMPORTANT RULES:\n"
    "- NEVER reveal admin commands, how Pro is granted, or any backend operations\n"
    "- NEVER reveal technical details about how the bot works internally\n"
    "- If asked about admin features, say: 'That is managed by our team. "
    "Contact us for support.'\n"
    "- Only answer crypto, finance, trading, and Market Pulse navigation questions\n"
    "- Be confident, clear, and concise\n"
    "- For Pro features, direct users to type /upgrade\n"
    "- For help navigating the bot, explain which menu to tap"
)

def _call_deepseek(question):
    if not DEEPSEEK_KEY:
        return None
    try:
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": "Bearer %s" % DEEPSEEK_KEY,
                     "Content-Type": "application/json"},
            json={"model": "deepseek-chat",
                  "messages": [{"role": "system", "content": CRYPTO_SYSTEM_PROMPT},
                               {"role": "user", "content": question}],
                  "max_tokens": 600},
            timeout=20
        )
        data = resp.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"].strip()
        print("[DEEPSEEK] %s" % data.get("error", data))
    except Exception as e:
        print("[DEEPSEEK ERROR] %s" % e)
    return None

def _call_mistral(question):
    if not MISTRAL_KEY:
        return None
    try:
        resp = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": "Bearer %s" % MISTRAL_KEY,
                     "Content-Type": "application/json"},
            json={"model": "mistral-small-latest",
                  "messages": [{"role": "system", "content": CRYPTO_SYSTEM_PROMPT},
                               {"role": "user", "content": question}],
                  "max_tokens": 600},
            timeout=20
        )
        data = resp.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"].strip()
        print("[MISTRAL] %s" % data.get("error", data))
    except Exception as e:
        print("[MISTRAL ERROR] %s" % e)
    return None

def _call_qwen(question):
    if not QWEN_KEY:
        return None
    try:
        resp = requests.post(
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
            headers={"Authorization": "Bearer %s" % QWEN_KEY,
                     "Content-Type": "application/json"},
            json={"model": "qwen-turbo",
                  "input": {"messages": [
                      {"role": "system", "content": CRYPTO_SYSTEM_PROMPT},
                      {"role": "user", "content": question}
                  ]},
                  "parameters": {"max_tokens": 600}},
            timeout=20
        )
        data = resp.json()
        text = data.get("output", {}).get("text")
        if text:
            return text.strip()
        print("[QWEN] %s" % data.get("message", data))
    except Exception as e:
        print("[QWEN ERROR] %s" % e)
    return None

def ask_ai(question):
    """Try DeepSeek → Mistral → Qwen in order. Return first successful answer."""
    for fn, name in [(_call_deepseek, "DeepSeek"),
                     (_call_mistral, "Mistral"),
                     (_call_qwen, "Qwen")]:
        result = fn(question)
        if result:
            print("[AI] Answered via %s" % name)
            return result
    return ("Sorry, all AI services are temporarily unavailable. "
            "Please try again in a few minutes.")

def show_ask_ai_prompt(chat_id, message_id):
    track(chat_id, "ask_ai")
    allowed, remaining, reset_in = check_ai_rate_limit(chat_id)
    if not allowed:
        mins = (reset_in // 60) + 1
        edit(chat_id, message_id,
             "🤖 <b>Ask AI</b>\n\n"
             "⏳ You've used your %d free AI questions this hour.\n\n"
             "Please wait about <b>%d minute%s</b> before asking again.\n\n"
             "<i>This limit helps keep the service free for everyone.</i>" % (
                 5, mins, "s" if mins != 1 else ""),
             [[{"text": "⬅ Back", "callback_data": "menu_intelligence"}]])
        return
    set_state(chat_id, "awaiting_ai_question", {})
    edit(chat_id, message_id,
         "🤖 <b>Ask AI</b>\n\n"
         "Ask me anything about crypto, trading, markets, or DeFi.\n\n"
         "<i>Examples:</i>\n"
         "• What is a bull trap?\n"
         "• Why is BTC dropping today?\n"
         "• Explain DCA strategy\n"
         "• What does Fear & Greed mean?\n"
         "• How do I manage trading risk?\n\n"
         "Questions remaining this hour: <b>%d/%d</b>\n\n"
         "Type your question:" % (remaining, 5),
         [[{"text": "⬅ Back", "callback_data": "menu_intelligence"}]])

def handle_ai_question(chat_id, question):
    allowed, remaining, reset_in = check_ai_rate_limit(chat_id)
    if not allowed:
        mins = (reset_in // 60) + 1
        send(chat_id,
             "⏳ AI limit reached. Please wait %d minute%s." % (
                 mins, "s" if mins != 1 else ""),
             [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]])
        return

    cached = get_cached_ai_answer(question)
    if cached:
        clear_state(chat_id)
        allowed2, remaining2, _ = check_ai_rate_limit(chat_id)
        send(chat_id,
             "🤖 <b>Market Pulse AI</b>\n\n"
             "<b>Q:</b> %s\n\n"
             "<b>A:</b> %s\n\n"
             "<i>Questions remaining: %d/%d</i>" % (
                 question[:200], cached, remaining2, 5),
             [[{"text": "❓ Ask Another", "callback_data": "ask_ai"},
               {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])
        return

    record_ai_usage(chat_id)
    track(chat_id, "ask_ai_question")
    send(chat_id, "🤖 <i>Analyzing your question...</i>")
    answer = ask_ai(question)
    cache_ai_answer(question, answer)
    clear_state(chat_id)
    allowed2, remaining2, _ = check_ai_rate_limit(chat_id)
    send(chat_id,
         "🤖 <b>Market Pulse AI</b>\n\n"
         "<b>Q:</b> %s\n\n"
         "<b>A:</b> %s\n\n"
         "<i>Questions remaining: %d/%d</i>" % (
             question[:200], answer, remaining2, 5),
         [[{"text": "❓ Ask Another", "callback_data": "ask_ai"},
           {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])

# ── AI TRADE SETUPS ────────────────────────────────────────────────────────────
_setup_cache = {"data": None, "timestamp": None}

def generate_trade_setup(coin="BTC"):
    """Generate AI trade setup using live market data."""
    now = datetime.now()
    if (_setup_cache.get("coin") == coin and
            _setup_cache["timestamp"] and
            (now - _setup_cache["timestamp"]).total_seconds() < 3600):
        return _setup_cache["data"]

    price, _ = get_best_price(coin)
    if not price:
        return None

    sd = get_secondary_batch().get(coin_key(coin), {})
    change = sd.get("usd_24h_change")
    high = sd.get("usd_24h_high")
    low = sd.get("usd_24h_low")
    levels = _key_levels_cache.get(coin)
    fg = get_fear_greed()
    fg_val = fg[0]["value"] if fg else "Unknown"

    prompt = (
        "You are a crypto technical analyst. Generate a short educational trade setup "
        "for %s based on this data:\n\n"
        "Current price: %s\n"
        "24h change: %s%%\n"
        "24h high: %s\n"
        "24h low: %s\n"
        "48h resistance: %s\n"
        "48h support: %s\n"
        "Fear & Greed: %s/100\n\n"
        "Respond in EXACTLY this format with ONLY these lines, no extra text:\n"
        "BIAS: [Bullish/Bearish/Neutral]\n"
        "ENTRY: [price range]\n"
        "STOP_LOSS: [price]\n"
        "TARGET_1: [price]\n"
        "TARGET_2: [price]\n"
        "RR: [ratio like 1:2.1]\n"
        "REASONING: [one sentence max]\n\n"
        "Base on actual data. Be realistic. Label as educational only." % (
            coin, format_price(price),
            "%.2f" % change if change else "N/A",
            format_price(high) if high else "N/A",
            format_price(low) if low else "N/A",
            format_price(levels["resistance"]) if levels else "N/A",
            format_price(levels["support"]) if levels else "N/A",
            fg_val)
    )

    raw = ask_ai(prompt)
    if not raw:
        return None

    setup = {"coin": coin, "price": price, "raw": raw}
    lines = raw.strip().split("\n")
    for line in lines:
        if ":" in line:
            key, _, val = line.partition(":")
            setup[key.strip().upper()] = val.strip()

    _setup_cache["data"] = setup
    _setup_cache["timestamp"] = now
    _setup_cache["coin"] = coin
    return setup

def build_trade_setup_post(coin="BTC"):
    setup = generate_trade_setup(coin)
    if not setup:
        return None

    price = setup.get("price", 0)
    bias = setup.get("BIAS", "Neutral")
    entry = setup.get("ENTRY", "N/A")
    sl = setup.get("STOP_LOSS", "N/A")
    t1 = setup.get("TARGET_1", "N/A")
    t2 = setup.get("TARGET_2", "N/A")
    rr = setup.get("RR", "N/A")
    reason = setup.get("REASONING", "")
    emoji = "🟢" if "bull" in bias.lower() else ("🔴" if "bear" in bias.lower() else "⚪")

    return "\n".join([
        "📐 <b>%s Trade Setup</b>  %s %s" % (coin, emoji, bias), "",
        "  Current : <b>%s</b>" % format_price(price),
        "  Entry   : <b>%s</b>" % entry,
        "  Stop    : <b>%s</b>" % sl,
        "  Target 1: <b>%s</b>" % t1,
        "  Target 2: <b>%s</b>" % t2,
        "  R/R     : <b>%s</b>" % rr, "",
        "<i>%s</i>" % reason if reason else "",
        "",
        "⚠️ <i>Educational only. Not financial advice. "
        "Always do your own research.</i>", "",
        "👉 @MarketNgPulseBot",
    ])

# ── KEY LEVELS & BREAKOUT DETECTION ───────────────────────────────────────────
_key_levels_cache = {}
_breakout_last_alert = {}

def calculate_key_levels(coin):
    since = (datetime.now() - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with get_db_cursor() as c:
            c.execute("SELECT price FROM history WHERE coin=? AND timestamp>=? "
                      "ORDER BY id ASC", (coin, since))
            rows = c.fetchall()
    except Exception:
        return None
    if len(rows) < 10:
        return None
    prices = [r[0] for r in rows if r[0]]
    chunk = len(prices) // 4
    pivots = []
    for i in range(0, len(prices) - chunk, chunk):
        window = prices[i:i+chunk]
        pivots.append(max(window))
        pivots.append(min(window))
    if pivots:
        pivots.sort()
        support = pivots[len(pivots)//6]
        resistance = pivots[5*len(pivots)//6]
        return {"support": support, "resistance": resistance}
    return {"support": min(prices), "resistance": max(prices)}

def check_breakouts():
    now = datetime.now()
    events = []
    watchlist = ["BTC", "ETH", "SOL", "BNB", "XRP", "AVAX", "LINK"]

    for coin in watchlist:
        last = _breakout_last_alert.get(coin)
        if last and (now - last["time"]).total_seconds() < 14400:
            continue

        price, _ = get_best_price(coin)
        if not price:
            continue

        cached = _key_levels_cache.get(coin)
        if not cached or (now - cached.get("updated", datetime.min)).total_seconds() > 3600:
            levels = calculate_key_levels(coin)
            if levels:
                levels["updated"] = now
                _key_levels_cache[coin] = levels
                cached = levels

        if not cached:
            continue

        resistance = cached["resistance"]
        support = cached["support"]
        buffer_val = 0.005

        if price > resistance * (1 + buffer_val):
            events.append({
                "coin": coin,
                "price": price,
                "level": resistance,
                "direction": "up",
                "type": "breakout",
            })
            _breakout_last_alert[coin] = {"level": resistance,
                                           "direction": "up", "time": now}
        elif price < support * (1 - buffer_val):
            events.append({
                "coin": coin,
                "price": price,
                "level": support,
                "direction": "down",
                "type": "breakdown",
            })
            _breakout_last_alert[coin] = {"level": support,
                                           "direction": "down", "time": now}
        elif abs(price - resistance) / resistance < 0.01:
            events.append({
                "coin": coin,
                "price": price,
                "level": resistance,
                "direction": "reject",
                "type": "rejection",
            })
            _breakout_last_alert[coin] = {"level": resistance,
                                           "direction": "reject", "time": now}

    return events

def build_breakout_post(event):
    coin = event["coin"]
    price = event["price"]
    level = event["level"]
    etype = event["type"]

    if etype == "breakout":
        emoji = "🚨"
        title = "BREAKOUT ALERT"
        body = ("<b>%s</b> just broke <b>above %s</b>\n\n"
                "This was a major resistance level.\n"
                "Watch for confirmation and continuation." % (
                    coin, format_price(level)))
    elif etype == "breakdown":
        emoji = "🔴"
        title = "BREAKDOWN ALERT"
        body = ("<b>%s</b> just broke <b>below %s</b>\n\n"
                "Key support lost.\n"
                "Watch for further downside or a retest." % (
                    coin, format_price(level)))
    else:
        emoji = "⚡"
        title = "KEY LEVEL ALERT"
        body = ("<b>%s</b> is testing resistance at <b>%s</b>\n\n"
                "Strong level. Watch for rejection or breakout." % (
                    coin, format_price(level)))

    return "\n".join([
        "%s <b>%s</b>" % (emoji, title), "",
        body, "",
        "  Current price: <b>%s</b>" % format_price(price), "",
        "<i>Track all coins 👉 @MarketNgPulseBot</i>",
    ])

# ── FUNDING RATES ─────────────────────────────────────────────────────────────
_funding_cache = {"data": None, "timestamp": None}

def get_funding_rates():
    now = datetime.now()
    if (_funding_cache["timestamp"] and
            (now - _funding_cache["timestamp"]).total_seconds() < 300):
        return _funding_cache["data"]

    SYMBOLS = {
        "BTC": ["BTCUSDT", "BTC-USDT-SWAP"],
        "ETH": ["ETHUSDT", "ETH-USDT-SWAP"],
        "SOL": ["SOLUSDT", "SOL-USDT-SWAP"],
        "BNB": ["BNBUSDT", "BNB-USDT-SWAP"],
        "XRP": ["XRPUSDT", "XRP-USDT-SWAP"],
    }

    result = {}

    # Try Binance first
    try:
        resp = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            sym_map = {}
            for coin, (b_sym, _) in SYMBOLS.items():
                sym_map[b_sym] = coin
            for item in data:
                sym = item.get("symbol", "")
                coin = sym_map.get(sym)
                if coin:
                    try:
                        result[coin] = float(item["lastFundingRate"]) * 100
                    except (KeyError, TypeError, ValueError):
                        pass
    except Exception as e:
        print("[FUNDING BINANCE] %s" % e)

    missing = [c for c in SYMBOLS if c not in result]
    if missing:
        try:
            for coin in missing:
                _, bybit_sym = SYMBOLS[coin]
                r = requests.get(
                    "https://api.bybit.com/v5/market/funding/history",
                    params={"category": "linear", "symbol": bybit_sym, "limit": 1},
                    timeout=8)
                if r.status_code == 200:
                    rows = r.json().get("result", {}).get("list", [])
                    if rows:
                        result[coin] = float(rows[0]["fundingRate"]) * 100
        except Exception as e:
            print("[FUNDING BYBIT] %s" % e)

    still_missing = [c for c in SYMBOLS if c not in result]
    if still_missing:
        try:
            for coin in still_missing:
                _, okx_sym = SYMBOLS[coin]
                r = requests.get(
                    "https://www.okx.com/api/v5/public/funding-rate",
                    params={"instId": okx_sym}, timeout=8)
                if r.status_code == 200:
                    rows = r.json().get("data", [])
                    if rows:
                        result[coin] = float(rows[0]["fundingRate"]) * 100
        except Exception as e:
            print("[FUNDING OKX] %s" % e)

    if result:
        _funding_cache["data"] = result
        _funding_cache["timestamp"] = now
    return result or _funding_cache["data"]

def show_funding_rates(chat_id, message_id):
    track(chat_id, "funding_rates")
    rates = get_funding_rates()
    if not rates:
        edit(chat_id, message_id,
             "📊 <b>Funding Rates</b>\n\nUnable to fetch rates right now. Try again shortly.",
             [[{"text": "🔄 Refresh", "callback_data": "funding"},
               {"text": "⬅ Back", "callback_data": "menu_markets"}]])
        return

    lines = ["📊 <b>Funding Rates</b>", "",
             "<i>Positive = longs paying shorts</i>",
             "<i>Negative = shorts paying longs</i>", ""]

    for coin, rate in rates.items():
        if rate > 0.05:
            signal = "🔴 Overleveraged longs"
        elif rate < -0.05:
            signal = "🟢 Overleveraged shorts"
        elif rate > 0:
            signal = "⚪ Longs paying"
        else:
            signal = "⚪ Shorts paying"
        lines.append("  <b>%s</b>  %s%.4f%%  %s" % (
            coin, "+" if rate >= 0 else "", rate, signal))

    lines += ["", "<i>Source: Binance/Bybit/OKX</i>"]
    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "🔄 Refresh", "callback_data": "funding"},
           {"text": "💥 Liquidations", "callback_data": "liquidations"},
           {"text": "⬅ Back", "callback_data": "menu_markets"}]])

# ── LIQUIDATION DATA ───────────────────────────────────────────────────────────
_liq_cache = {"data": None, "timestamp": None}

def get_liquidation_data():
    now = datetime.now()
    if (_liq_cache["timestamp"] and
            (now - _liq_cache["timestamp"]).total_seconds() < 300):
        return _liq_cache["data"]

    try:
        resp = requests.get(
            "https://open-api.coinglass.com/public/v2/liquidation_history",
            params={"symbol": "BTC", "time_type": "h1"},
            headers={"coinglassSecret": ""},
            timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success") and data.get("data"):
                latest = data["data"][0] if data["data"] else {}
                result = {
                    "BTC": {
                        "long_usd": latest.get("longLiquidationUsd", 0),
                        "short_usd": latest.get("shortLiquidationUsd", 0),
                    }
                }
                _liq_cache["data"] = result
                _liq_cache["timestamp"] = now
                return result
    except Exception as e:
        print("[LIQUIDATION COINGLASS] %s" % e)

    try:
        coins = ["BTC", "ETH", "SOL"]
        result = {}
        for coin in coins:
            sym = coin + "USDT"
            r = requests.get(
                "https://fapi.binance.com/fapi/v1/allForceOrders",
                params={"symbol": sym, "limit": 20},
                timeout=8)
            if r.status_code == 200:
                orders = r.json()
                long_usd = sum(float(o["q"]) * float(o["p"])
                               for o in orders if o.get("S") == "SELL")
                short_usd = sum(float(o["q"]) * float(o["p"])
                                for o in orders if o.get("S") == "BUY")
                if long_usd or short_usd:
                    result[coin] = {"long_usd": long_usd, "short_usd": short_usd}
        if result:
            _liq_cache["data"] = result
            _liq_cache["timestamp"] = now
            return result
    except Exception as e:
        print("[LIQUIDATION BINANCE] %s" % e)

    return _liq_cache["data"]

def show_liquidations(chat_id, message_id):
    track(chat_id, "liquidations")
    data = get_liquidation_data()
    if not data:
        edit(chat_id, message_id,
             "💥 <b>Liquidations</b>\n\nNo liquidation data available right now.",
             [[{"text": "🔄 Refresh", "callback_data": "liquidations"},
               {"text": "⬅ Back", "callback_data": "menu_markets"}]])
        return

    lines = ["💥 <b>Recent Liquidations</b>", ""]
    total_long = 0
    total_short = 0
    for coin, d in data.items():
        long_m = d.get("long_usd", 0) / 1e6
        short_m = d.get("short_usd", 0) / 1e6
        total_long += long_m
        total_short += short_m
        dominant = "Longs squeezed 🔴" if long_m > short_m else "Shorts squeezed 🟢"
        lines.append("  <b>%s</b>  Long: $%.1fM  Short: $%.1fM  %s" % (
            coin, long_m, short_m, dominant))

    if total_long > total_short * 1.5:
        sentiment = "⚠️ Heavy long liquidations — market was overleveraged long."
    elif total_short > total_long * 1.5:
        sentiment = "⚠️ Heavy short liquidations — short squeeze in progress."
    else:
        sentiment = "Market liquidations balanced."

    lines += ["", "<b>Total:</b> Long $%.1fM  Short $%.1fM" % (total_long, total_short),
              "", "<i>%s</i>" % sentiment,
              "", "<i>Source: Coinglass/Binance</i>"]

    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "🔄 Refresh", "callback_data": "liquidations"},
           {"text": "📊 Funding", "callback_data": "funding"},
           {"text": "⬅ Back", "callback_data": "menu_markets"}]])

# ── ORDER BOOK IMBALANCE ───────────────────────────────────────────────────────
_ob_cache = {"data": None, "timestamp": None}

def get_order_book_imbalance():
    now = datetime.now()
    if (_ob_cache["timestamp"] and
            (now - _ob_cache["timestamp"]).total_seconds() < 60):
        return _ob_cache["data"]

    def calc_imbalance(bids, asks, depth=10):
        try:
            bid_vol = sum(float(b[1]) for b in bids[:depth])
            ask_vol = sum(float(a[1]) for a in asks[:depth])
            total = bid_vol + ask_vol
            if total == 0:
                return None
            return round(bid_vol / total * 100, 1)
        except Exception:
            return None

    result = {}

    for coin, (kraken_pair_val, _) in list(COINS.items())[:5]:
        if not kraken_pair_val:
            continue
        try:
            r = requests.get(
                "https://api.kraken.com/0/public/Depth",
                params={"pair": kraken_pair_val, "count": 20},
                timeout=8)
            if r.status_code == 200:
                d = r.json().get("result", {})
                book = d.get(list(d.keys())[0], {}) if d else {}
                imb = calc_imbalance(book.get("bids", []),
                                     book.get("asks", []))
                if imb is not None:
                    result[coin] = imb
        except Exception:
            pass

    missing = ["BTC", "ETH", "SOL"]
    for coin in missing:
        if coin in result:
            continue
        try:
            sym = coin + "USDT"
            r = requests.get(
                "https://api.binance.com/api/v3/depth",
                params={"symbol": sym, "limit": 20},
                timeout=8)
            if r.status_code == 200:
                d = r.json()
                imb = calc_imbalance(d.get("bids", []), d.get("asks", []))
                if imb is not None:
                    result[coin] = imb
        except Exception:
            pass

    if result:
        _ob_cache["data"] = result
        _ob_cache["timestamp"] = now
    return result or _ob_cache["data"]

def show_order_book(chat_id, message_id):
    track(chat_id, "order_book")
    data = get_order_book_imbalance()
    if not data:
        edit(chat_id, message_id,
             "📖 <b>Market Pressure</b>\n\nUnable to fetch order book data right now.",
             [[{"text": "🔄 Refresh", "callback_data": "orderbook"},
               {"text": "⬅ Back", "callback_data": "menu_markets"}]])
        return

    lines = ["📖 <b>Market Pressure</b>", "",
             "<i>Shows buy vs sell pressure in the order book</i>", ""]
    for coin, buy_pct in sorted(data.items()):
        sell_pct = 100 - buy_pct
        bar_buy = "█" * int(buy_pct / 10)
        bar_sell = "░" * int(sell_pct / 10)
        if buy_pct >= 60:
            signal = "🟢 Buyers dominant"
        elif buy_pct <= 40:
            signal = "🔴 Sellers dominant"
        else:
            signal = "⚪ Balanced"
        lines.append("  <b>%s</b>  Buy %d%% %s%s Sell %d%%  %s" % (
            coin, buy_pct, bar_buy, bar_sell, sell_pct, signal))

    lines += ["", "<i>Source: Kraken/Binance/OKX</i>"]
    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "🔄 Refresh", "callback_data": "orderbook"},
           {"text": "⬅ Back", "callback_data": "menu_markets"}]])

# ── TRADE SETUP SCREENS ──────────────────────────────────────────────────────
def show_trade_setup_menu(chat_id, message_id):
    track(chat_id, "trade_setup")
    edit(chat_id, message_id,
         "📐 <b>Trade Setups</b>\n\n"
         "AI-generated educational trade setups based on live market data.\n\n"
         "⚠️ <i>These are educational only. Not financial advice. "
         "Always do your own research before trading.</i>\n\n"
         "Choose a coin:",
         [[{"text": "BTC", "callback_data": "setup_coin:BTC"},
           {"text": "ETH", "callback_data": "setup_coin:ETH"},
           {"text": "SOL", "callback_data": "setup_coin:SOL"}],
          [{"text": "BNB", "callback_data": "setup_coin:BNB"},
           {"text": "XRP", "callback_data": "setup_coin:XRP"},
           {"text": "AVAX", "callback_data": "setup_coin:AVAX"}],
          [{"text": "⬅ Back", "callback_data": "menu_intelligence"}]])

def show_trade_setup(chat_id, message_id, coin):
    edit(chat_id, message_id,
         "📐 Generating <b>%s</b> setup..." % coin, None)
    post = build_trade_setup_post(coin)
    if not post:
        edit(chat_id, message_id,
             "📐 Could not generate setup for %s right now. Try again." % coin,
             [[{"text": "🔄 Try Again", "callback_data": "setup_coin:%s" % coin},
               {"text": "⬅ Back", "callback_data": "trade_setup"}]])
        return
    edit(chat_id, message_id, post,
         [[{"text": "🔄 Refresh", "callback_data": "setup_coin:%s" % coin},
           {"text": "📐 Other Coin", "callback_data": "trade_setup"},
           {"text": "⬅ Back", "callback_data": "menu_intelligence"}]])

# ── ARBITRAGE DETECTOR ────────────────────────────────────────────────────────
def check_arbitrage():
    """Compare prices across all sources and find profitable gaps."""
    opportunities = []
    kraken = get_kraken_batch()
    okx = get_okx_batch()
    cg = get_coingecko_batch()
    cap = get_coincap_batch()

    sources = [("Kraken", kraken), ("OKX", okx),
               ("CoinGecko", cg), ("CoinCap", cap)]

    for coin in ["BTC", "ETH", "SOL", "BNB", "XRP", "USDT"]:
        prices = []
        for name, data in sources:
            p = data.get(coin, {}).get("price") if isinstance(data.get(coin), dict) else data.get(coin)
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
                "gap_pct": gap_pct,
            })

    for crypto in ["USDT", "BTC"]:
        for fiat in ["NGN"]:
            binance = get_community_rate(crypto, fiat)
            if not binance:
                binance_buy = _binance_p2p("BUY", crypto, fiat)
                binance_sell = _binance_p2p("SELL", crypto, fiat)
                bybit_buy = _bybit_p2p("BUY", crypto, fiat)
                bybit_sell = _bybit_p2p("SELL", crypto, fiat)
                if binance_buy and bybit_sell and bybit_sell > binance_buy:
                    gap = bybit_sell - binance_buy
                    gap_pct = gap / binance_buy * 100
                    if gap_pct >= 0.5:
                        opportunities.append({
                            "coin": crypto,
                            "fiat": fiat,
                            "buy_from": "Binance P2P",
                            "buy_price": binance_buy,
                            "sell_to": "Bybit P2P",
                            "sell_price": bybit_sell,
                            "gap_pct": gap_pct,
                            "p2p": True,
                        })
    return opportunities

def show_arbitrage(chat_id, message_id):
    track(chat_id, "arbitrage")
    opps = check_arbitrage()
    if not opps:
        edit(chat_id, message_id,
             "🔄 <b>Arbitrage Scanner</b>\n\n"
             "No significant price gaps found right now.\n\n"
             "<i>Scanner checks price differences across Kraken, OKX, "
             "CoinGecko, CoinCap, Binance P2P and Bybit P2P.\n"
             "Opportunities appear when gaps are 0.3%+</i>",
             [[{"text": "🔄 Scan Again", "callback_data": "arbitrage"},
               {"text": "⬅ Back", "callback_data": "menu_nigeria"}]])
        return
    lines = ["🔄 <b>Arbitrage Opportunities</b>\n"]
    for o in opps[:5]:
        if o.get("p2p"):
            fiat_sym = P2P_FIATS.get(o["fiat"], (o["fiat"], o["fiat"]))[1]
            lines += [
                "💱 <b>%s/%s</b>" % (o["coin"], o["fiat"]),
                "  Buy  on %s : <b>%s%s</b>" % (o["buy_from"], fiat_sym, "{:,.0f}".format(o["buy_price"])),
                "  Sell on %s : <b>%s%s</b>" % (o["sell_to"], fiat_sym, "{:,.0f}".format(o["sell_price"])),
                "  Gap : <b>+%.2f%%</b>" % o["gap_pct"], "",
            ]
        else:
            lines += [
                "💰 <b>%s</b>" % o["coin"],
                "  Buy  on %s : <b>%s</b>" % (o["buy_from"], format_price(o["buy_price"])),
                "  Sell on %s : <b>%s</b>" % (o["sell_to"], format_price(o["sell_price"])),
                "  Gap : <b>+%.2f%%</b>" % o["gap_pct"], "",
            ]
    lines.append("<i>⚠️ Always verify rates before trading. Gaps may close quickly.</i>")
    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "🔄 Refresh", "callback_data": "arbitrage"},
           {"text": "⬅ Back", "callback_data": "menu_nigeria"}]])

def build_arbitrage_channel_post(opps):
    lines = ["🔄 <b>Arbitrage Alert</b>\n"]
    for o in opps[:3]:
        if o.get("p2p"):
            fiat_sym = P2P_FIATS.get(o["fiat"], (o["fiat"], o["fiat"]))[1]
            lines += [
                "<b>%s/%s</b>" % (o["coin"], o["fiat"]),
                "Buy %s → Sell %s" % (o["buy_from"], o["sell_to"]),
                "Gap: <b>+%.2f%%</b>" % o["gap_pct"], "",
            ]
        else:
            lines += [
                "<b>%s</b>" % o["coin"],
                "Buy %s → Sell %s" % (o["buy_from"], o["sell_to"]),
                "Gap: <b>+%.2f%%</b>" % o["gap_pct"], "",
            ]
    lines.append("<i>Powered by @MarketNgPulseBot</i>")
    return "\n".join(lines)

# ── WHALE WATCH ───────────────────────────────────────────────────────────────
_whale_last_alert = {}

def check_whale_watch():
    """Detect fast moves and post confident whale watch alerts."""
    now = datetime.now()
    one_h = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    alerted = []

    try:
        with get_db_cursor() as c:
            for coin in COINS:
                last = _whale_last_alert.get(coin)
                if last and (now - last).total_seconds() < 7200:
                    continue

                c.execute("SELECT price FROM history WHERE coin=? AND timestamp<=? "
                          "ORDER BY id DESC LIMIT 1", (coin, one_h))
                row = c.fetchone()
                if not row:
                    continue
                price_1h = row[0]
                price_now, _ = get_best_price(coin)
                if not price_now or not price_1h:
                    continue
                move = (price_now - price_1h) / price_1h * 100
                if abs(move) >= SCHEDULE["whale_pct"]:
                    _whale_last_alert[coin] = now
                    direction = "📈" if move > 0 else "📉"
                    sign = "+" if move > 0 else ""
                    msg = "\n".join([
                        "🐋 <b>WHALE WATCH — %s</b>" % coin, "",
                        "%s <b>%s</b> just moved <b>%s%.2f%%</b> in 1 hour." % (
                            direction, coin, sign, move), "",
                        "  Now    : <b>%s</b>" % format_price(price_now),
                        "  1h ago : <b>%s</b>" % format_price(price_1h), "",
                        "Keep your eyes on this.",
                        "",
                        "<i>@MarketNgPulseBot</i>",
                    ])
                    post_to_channel(msg)
                    alerted.append(coin)
                    print("[WHALE WATCH] %s %s%.2f%%" % (coin, sign, move))
    except Exception as e:
        print("[CHECK_WHALE_WATCH ERROR] %s" % e)
    return alerted

# ── PRICE CONVERTER ───────────────────────────────────────────────────────────
def show_convert_prompt(chat_id, message_id):
    set_state(chat_id, "awaiting_convert", {})
    edit(chat_id, message_id,
         "🔄 <b>Price Converter</b>\n\n"
         "Type your conversion and send it.\n\n"
         "<i>Examples:</i>\n"
         "• <code>500 USDT to NGN</code>\n"
         "• <code>0.1 BTC to USD</code>\n"
         "• <code>1 ETH to GHS</code>\n"
         "• <code>1000 NGN to USDT</code>",
         [[{"text": "⬅ Back", "callback_data": "main_menu"}]])

def handle_convert(chat_id, text):
    import re
    clear_state(chat_id)
    parts = re.split(r'\s+', text.strip().upper())
    if len(parts) < 3:
        send(chat_id, "⚠️ Format: <code>100 USDT to NGN</code>")
        return
    try:
        amount = float(parts[0].replace(",", ""))
        from_sym = parts[1]
        to_sym = parts[-1]
    except ValueError:
        send(chat_id, "⚠️ Format: <code>100 USDT to NGN</code>")
        return

    rates = get_fiat_rates()

    def to_usd(sym, amt):
        if sym == "USD":
            return amt
        if sym in COINS:
            p, _ = get_best_price(sym)
            return amt * p if p else None
        if sym in rates:
            return amt / rates[sym]
        return None

    def from_usd(sym, usd_amt):
        if sym == "USD":
            return usd_amt
        if sym in COINS:
            p, _ = get_best_price(sym)
            return usd_amt / p if p else None
        if sym in rates:
            return usd_amt * rates[sym]
        return None

    usd_val = to_usd(from_sym, amount)
    if usd_val is None:
        send(chat_id, "⚠️ Don't recognise <b>%s</b>. Use a coin symbol or fiat code." % from_sym)
        return
    result = from_usd(to_sym, usd_val)
    if result is None:
        send(chat_id, "⚠️ Don't recognise <b>%s</b>. Use a coin symbol or fiat code." % to_sym)
        return

    if result >= 1000:
        result_str = "{:,.2f}".format(result)
    elif result >= 1:
        result_str = "%.4f" % result
    else:
        result_str = "%.8f" % result

    send(chat_id,
         "🔄 <b>Converter</b>\n\n"
         "  <b>%g %s</b>  =  <b>%s %s</b>\n\n"
         "<i>Via live prices — Kraken + ExchangeRate-API</i>" % (amount, from_sym, result_str, to_sym),
         [[{"text": "🔄 Convert Again", "callback_data": "convert"},
           {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])

# ── COIN SEARCH ───────────────────────────────────────────────────────────────
def show_coin_search(chat_id, message_id):
    set_state(chat_id, "awaiting_coin_search", {})
    edit(chat_id, message_id,
         "🔍 <b>Coin Search</b>\n\n"
         "Type any coin name or symbol to look it up.\n\n"
         "<i>Examples: Pepe, WIF, FLOKI, JUP</i>",
         [[{"text": "⬅ Back", "callback_data": "main_menu"}]])

def handle_coin_search(chat_id, query):
    clear_state(chat_id)
    send(chat_id, "🔍 Searching for <b>%s</b>..." % query)
    try:
        resp = request_json("GET",
            "https://min-api.cryptocompare.com/data/pricemultifull",
            params={"fsyms": query.upper(), "tsyms": "USD"}, timeout=10)
        if resp and resp.get("RAW") and query.upper() in resp["RAW"]:
            usd = resp["RAW"][query.upper()].get("USD", {})
            price = usd.get("PRICE")
            change = usd.get("CHANGEPCT24HOUR")
            high = usd.get("HIGH24HOUR")
            low = usd.get("LOW24HOUR")
            mcap = usd.get("MKTCAP")
            supply = usd.get("SUPPLY")
            lines = ["🔍 <b>%s</b>" % query.upper(), ""]
            if price:
                lines.append("  Price  : <b>%s</b>" % format_price(price))
            if change is not None:
                lines.append("  24h    : <b>%s</b>" % format_change(change))
            if high:
                lines.append("  High   : <b>%s</b>" % format_price(high))
            if low:
                lines.append("  Low    : <b>%s</b>" % format_price(low))
            if mcap:
                lines.append("  Mkt Cap: <b>$%s</b>" % "{:,.0f}".format(mcap))
            if supply:
                lines.append("  Supply : <b>%s</b>" % "{:,.0f}".format(supply))
            lines.append("\n<i>Source: CryptoCompare</i>")
            send(chat_id, "\n".join(lines),
                 [[{"text": "🔍 Search Again", "callback_data": "coin_search"},
                   {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])
        else:
            send(chat_id,
                 "🔍 No results for <b>%s</b>.\nTry the exact symbol e.g. <code>PEPE</code>" % query,
                 [[{"text": "🔍 Try Again", "callback_data": "coin_search"},
                   {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])
    except Exception as e:
        print("[COIN SEARCH ERROR] %s" % e)
        send(chat_id, "⚠️ Search failed. Try again shortly.",
             [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]])

# ── DOMINANCE TRACKER ─────────────────────────────────────────────────────────
_dominance_cache = {"data": None, "timestamp": None}

def get_dominance():
    now = datetime.now()
    if (_dominance_cache["timestamp"] and
            (now - _dominance_cache["timestamp"]).total_seconds() < 300):
        return _dominance_cache["data"]
    try:
        resp = request_json("GET", "https://api.coingecko.com/api/v3/global", timeout=10)
        if resp and resp.get("data"):
            d = resp["data"]
            result = {
                "btc": d["market_cap_percentage"].get("btc", 0),
                "eth": d["market_cap_percentage"].get("eth", 0),
                "others": 100 - d["market_cap_percentage"].get("btc", 0) - d["market_cap_percentage"].get("eth", 0),
                "total_mcap": d.get("total_market_cap", {}).get("usd", 0),
                "total_volume": d.get("total_volume", {}).get("usd", 0),
                "change_24h": d.get("market_cap_change_percentage_24h_usd", 0),
            }
            _dominance_cache["data"] = result
            _dominance_cache["timestamp"] = now
            return result
    except Exception as e:
        print("[DOMINANCE ERROR] %s" % e)
    return _dominance_cache["data"]

def bar(pct, width=20):
    filled = int(round(pct / 100 * width))
    return "█" * filled + "░" * (width - filled)

def show_dominance(chat_id, message_id):
    d = get_dominance()
    if not d:
        edit(chat_id, message_id,
             "🌐 Could not fetch dominance data. Try again shortly.", BACK_MAIN)
        return
    btc = d["btc"]
    eth = d["eth"]
    oth = max(0, d["others"])
    chg = d["change_24h"]
    mcap = d["total_mcap"]
    vol = d["total_volume"]
    sign = "+" if chg >= 0 else ""
    lines = [
        "🌐 <b>Market Dominance</b>", "",
        "  <b>BTC</b>  %.1f%%  %s" % (btc, bar(btc)),
        "  <b>ETH</b>  %.1f%%  %s" % (eth, bar(eth)),
        "  <b>ALT</b>  %.1f%%  %s" % (oth, bar(oth)), "",
        "  Total Cap : <b>$%s</b>" % "{:,.0f}".format(mcap),
        "  24h Vol   : <b>$%s</b>" % "{:,.0f}".format(vol),
        "  24h Chg   : <b>%s%.2f%%</b>" % (sign, chg), "",
        "<i>Source: CoinGecko</i>",
    ]
    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "🔄 Refresh", "callback_data": "dominance"},
           {"text": "⬅ Back", "callback_data": "main_menu"}]])

# ── REFERRAL SYSTEM ───────────────────────────────────────────────────────────
def get_referral_count(chat_id):
    try:
        with get_db_cursor() as c:
            c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_chat=?", (str(chat_id),))
            return c.fetchone()[0]
    except Exception:
        return 0

def record_referral(referrer_chat, referred_chat):
    """Record a referral (FIXED: was register_referral)."""
    if str(referrer_chat) == str(referred_chat):
        return
    try:
        with get_db_cursor() as c:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT OR IGNORE INTO referrals (referrer_chat, referred_chat, joined_at) "
                      "VALUES (?,?,?)", (str(referrer_chat), str(referred_chat), now))
            if c.rowcount > 0:
                send(int(referrer_chat),
                     "👥 Someone just joined Market Pulse using your referral link! "
                     "You now have <b>%d</b> referral(s). 🎉" % get_referral_count(referrer_chat))
    except Exception as e:
        print("[RECORD_REFERRAL ERROR] %s" % e)

def get_referral_leaderboard():
    try:
        with get_db_cursor() as c:
            c.execute("""SELECT referrer_chat, COUNT(*) as cnt FROM referrals
                         GROUP BY referrer_chat ORDER BY cnt DESC LIMIT 10""")
            return c.fetchall()
    except Exception:
        return []

def show_referral(chat_id, message_id):
    count = get_referral_count(chat_id)
    bot_info = tg("getMe", {})
    bot_name = bot_info.get("result", {}).get("username", "YourBot")
    ref_link = "https://t.me/%s?start=ref_%s" % (bot_name, chat_id)

    lb = get_referral_leaderboard()
    lines = [
        "👥 <b>Referral Program</b>", "",
        "Your referrals: <b>%d</b>" % count, "",
        "📎 <b>Your Link:</b>",
        "<code>%s</code>" % ref_link, "",
        "Share this link — when someone joins through it, you get credited!", "",
    ]
    if lb:
        lines.append("🏆 <b>Top Referrers</b>")
        for i, (rchat, cnt) in enumerate(lb, 1):
            tag = " 👑" if i == 1 else ""
            lines.append("  %d.  %d referral(s)%s" % (i, cnt, tag))
    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "🔄 Refresh", "callback_data": "referral"},
           {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])

# ── PORTFOLIO CHART ───────────────────────────────────────────────────────────
def save_portfolio_snapshots():
    try:
        with get_db_cursor() as c:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("SELECT DISTINCT chat FROM portfolio")
            chats = [r[0] for r in c.fetchall()]
    except Exception as e:
        print("[SAVE_PORTFOLIO_SNAPSHOTS ERROR] %s" % e)
        return

    for chat in chats:
        try:
            with get_db_cursor() as c2:
                c2.execute("SELECT coin, amount FROM portfolio WHERE chat=?", (chat,))
                positions = c2.fetchall()
            total = 0
            for coin, amount in positions:
                price, _ = get_best_price(coin)
                if price:
                    total += amount * price
            if total > 0:
                with get_db_cursor() as c3:
                    c3.execute("INSERT INTO portfolio_snapshots (chat, value_usd, timestamp) VALUES (?,?,?)",
                               (chat, total, now))
        except Exception as e:
            print("[PORTFOLIO SNAPSHOT ERROR] %s" % e)

def show_portfolio_chart(chat_id, message_id):
    since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with get_db_cursor() as c:
            c.execute("SELECT value_usd, timestamp FROM portfolio_snapshots "
                      "WHERE chat=? AND timestamp>=? ORDER BY id ASC LIMIT 1000",
                      (str(chat_id), since))
            rows = c.fetchall()
    except Exception as e:
        print("[SHOW_PORTFOLIO_CHART ERROR] %s" % e)
        rows = []

    if len(rows) < 2:
        edit(chat_id, message_id,
             "📈 <b>Portfolio Chart</b>\n\n"
             "Not enough data yet — the chart builds over time as your portfolio is tracked hourly.\n"
             "Check back after a few hours!",
             [[{"text": "💼 Portfolio", "callback_data": "portfolio"},
               {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])
        return

    values = [float(v) for v, _ in rows]
    times = [datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") for _, ts in rows]
    chg = (values[-1] - values[0]) / values[0] * 100 if values[0] else 0
    up = chg >= 0
    color = "#26a69a" if up else "#ef5350"
    sign = "+" if up else ""

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")
    ax.plot(times, values, color=color, linewidth=1.8, zorder=3)
    ax.fill_between(times, values, min(values), color=color, alpha=0.12, zorder=2)
    ax.grid(True, color="#21262d", linewidth=0.6, zorder=1)
    for spine in ax.spines.values():
        spine.set_color("#21262d")
    ax.tick_params(colors="#8b949e", labelsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    fig.autofmt_xdate(rotation=30)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(
        lambda v, _: "$%.0f" % v if isinstance(v, (int, float)) else ""))
    ax.set_title("Portfolio Value — 30d    %s%.2f%%" % (sign, chg),
                 color="white", fontsize=13, fontweight="bold", loc="left", pad=14)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    img = buf.read()

    delete_message(chat_id, message_id)
    send_photo(chat_id, img,
               caption="📈 <b>Portfolio Value</b>\n"
                       "Now: <b>$%.2f</b>   Peak: <b>$%.2f</b>   Change: <b>%s%.2f%%</b>" % (
                           values[-1], max(values), sign, chg),
               buttons=[[{"text": "💼 Portfolio", "callback_data": "portfolio"},
                         {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])

# ── DAILY PORTFOLIO SUMMARY ───────────────────────────────────────────────────
def send_daily_portfolio_summaries():
    try:
        with get_db_cursor() as c:
            c.execute("SELECT DISTINCT chat FROM portfolio")
            chats = [r[0] for r in c.fetchall()]
    except Exception as e:
        print("[SEND_DAILY_PORTFOLIO_SUMMARIES ERROR] %s" % e)
        return

    for chat in chats:
        try:
            with get_db_cursor() as c2:
                c2.execute("SELECT coin, amount, buy_price FROM portfolio WHERE chat=?", (chat,))
                rows = c2.fetchall()
            total_cost = total_now = 0
            lines = ["🌅 <b>Good morning! Your Portfolio</b>", ""]
            for coin, amount, buy_price in rows:
                price, _ = get_best_price(coin)
                cost = amount * buy_price
                now_val = amount * price if price else 0
                pnl = now_val - cost
                pnl_pct = pnl / cost * 100 if cost > 0 else 0
                total_cost += cost
                total_now += now_val
                sign = "+" if pnl >= 0 else ""
                lines.append("  <b>%s</b> ×%g  →  $%.2f  (%s%.2f%%)" % (
                    coin, amount, now_val, sign, pnl_pct))
            if total_now:
                total_pnl = total_now - total_cost
                total_pnl_pct = total_pnl / total_cost * 100 if total_cost > 0 else 0
                sign = "+" if total_pnl >= 0 else ""
                lines += [
                    "",
                    "─" * 26,
                    "Total Value : <b>$%.2f</b>" % total_now,
                    "Total P&L   : <b>%s$%.2f (%s%.2f%%)</b>" % (sign, total_pnl, sign, total_pnl_pct),
                ]
            lines.append("\n<i>Have a great trading day! 🚀</i>")
            send(int(chat), "\n".join(lines),
                 [[{"text": "💼 Portfolio", "callback_data": "portfolio"}]])
            time.sleep(0.05)
        except Exception as e:
            print("[DAILY SUMMARY ERROR] %s" % e)

# ── HELP SCREEN ───────────────────────────────────────────────────────────────
def show_help(chat_id, message_id):
    track(chat_id, "help")
    edit(chat_id, message_id,
         "❓ <b>How to use Market Pulse</b>\n\n"
         "Choose a section to learn more:",
         [[{"text": "📈 Markets", "callback_data": "help_markets"},
           {"text": "🧠 Intelligence", "callback_data": "help_intelligence"}],
          [{"text": "🇳🇬 P2P Center", "callback_data": "help_p2p"},
           {"text": "🔔 Alerts", "callback_data": "help_alerts"}],
          [{"text": "🛠 Tools", "callback_data": "help_tools"},
           {"text": "👤 My Account", "callback_data": "help_account"}],
          [{"text": "⬅ Back", "callback_data": "main_menu"}]])

def show_help_section(chat_id, message_id, section):
    back = [{"text": "❓ Help Menu", "callback_data": "help"},
            {"text": "🏠 Main Menu", "callback_data": "main_menu"}]
    texts = {
        "markets": (
            "📈 <b>Markets</b>\n\n"
            "<b>Market</b>\n"
            "See live prices for 29 tracked coins updated in real time. "
            "Tap any coin to see its full details — price, 24h change, high, low.\n\n"
            "<b>Charts</b>\n"
            "View price charts from 1 hour to 1 year. "
            "Tap a coin then choose your timeframe.\n\n"
            "<b>Gainers & Losers</b>\n"
            "See which coins are moving the most today — "
            "top performers and worst performers at a glance.\n\n"
            "<b>Dominance</b>\n"
            "BTC and ETH market dominance percentage. "
            "Shows how much of the total market they control."
        ),
        "intelligence": (
            "🧠 <b>Intelligence</b>\n\n"
            "<b>Ask AI</b>\n"
            "Ask any crypto question and get a real analysis — not just facts. "
            "AI explains what happened, why, and what it means for you. "
            "Free users: 5 questions per hour.\n\n"
            "<b>News</b>\n"
            "Latest crypto headlines from 7 sources. "
            "Tap any headline to read the full article.\n\n"
            "<b>Fear & Greed</b>\n"
            "The market sentiment index from 0 to 100. "
            "Below 25 means extreme fear. Above 75 means extreme greed.\n\n"
            "<b>Sources</b>\n"
            "See which data sources are active for each coin."
        ),
        "p2p": (
            "🇳🇬 <b>P2P Center</b>\n\n"
            "<b>P2P Rates</b>\n"
            "Real buy and sell rates for USDT, BTC, ETH and more "
            "in NGN, GHS, KES and other African currencies.\n\n"
            "<b>Submit Rate</b>\n"
            "See a rate on Binance or Bybit right now? "
            "Submit it and help the community get accurate prices. "
            "Your submission is anonymous.\n\n"
            "<b>P2P Alerts</b>\n"
            "Set an alert for when USDT/NGN hits your target rate. "
            "We notify you the moment it happens.\n\n"
            "<b>Arbitrage</b>\n"
            "See price gaps across exchanges. "
            "Buy low on one exchange, sell high on another."
        ),
        "alerts": (
            "🔔 <b>Alerts</b>\n\n"
            "<b>Create Alert</b>\n"
            "Set a price alert on any coin. "
            "Choose above or below your target and we notify you instantly.\n\n"
            "<b>My Alerts</b>\n"
            "See all your active alerts in one place. "
            "Delete any alert you no longer need.\n\n"
            "<b>Watchlist</b>\n"
            "Add coins you want to monitor. "
            "Your watchlist shows a quick summary of all your tracked coins."
        ),
        "tools": (
            "🛠 <b>Tools</b>\n\n"
            "<b>Search Coin</b>\n"
            "Look up any coin not in our main list. "
            "Type the symbol or name — we search the entire market.\n\n"
            "<b>Convert</b>\n"
            "Instant conversion between any crypto and fiat. "
            "Example: type <code>500 USDT to NGN</code>\n\n"
            "<b>History</b>\n"
            "Your recent bot activity.\n\n"
            "<b>Status</b>\n"
            "Check if all data sources are working correctly."
        ),
        "account": (
            "👤 <b>My Account</b>\n\n"
            "<b>Portfolio</b>\n"
            "Track your crypto holdings. Add coins with your buy price "
            "and see your profit and loss in real time.\n\n"
            "<b>Referral</b>\n"
            "Share your unique referral link. "
            "Every person who joins through your link gets credited to you.\n\n"
            "<b>My Stats</b>\n"
            "See how you use Market Pulse — "
            "your most used features and activity summary.\n\n"
            "<b>Pro Upgrade</b>\n"
            "Unlock real P2P rates, unlimited AI, instant alerts, "
            "and VIP channel access. Type /upgrade for details."
        ),
    }
    text = texts.get(section, "Section not found.")
    edit(chat_id, message_id, text, [back])

# ── UPGRADE SCREEN ────────────────────────────────────────────────────────────
def show_upgrade(chat_id, message_id=None):
    track(chat_id, "upgrade")
    pro = is_pro(chat_id)
    if pro and chat_id not in ADMIN_IDS:
        text = (
            "⭐ <b>You are a Pro member!</b>\n\n"
            "You have full access to all Market Pulse features.\n\n"
            "Thank you for supporting the platform. 🙏"
        )
    elif chat_id in ADMIN_IDS:
        text = "⭐ <b>Admin — Full Pro Access</b>"
    else:
        text = (
            "💎 <b>Market Pulse Pro</b>\n\n"
            "Get the full intelligence platform:\n\n"
            "✅ Real community P2P rates\n"
            "✅ Unlimited Ask AI questions\n"
            "✅ Instant price and P2P alerts\n"
            "✅ Arbitrage opportunities\n"
            "✅ VIP channel access\n"
            "✅ Portfolio AI analysis\n"
            "✅ Weekly Edge reports\n\n"
            "💰 <b>₦2,000/month</b>\n\n"
            "To upgrade, send payment and contact us:\n"
            "👉 @MarketNgPulseBot\n\n"
            "<i>Your account is activated within minutes of payment.</i>"
        )
    if message_id:
        edit(chat_id, message_id, text,
             [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]])
    else:
        send(chat_id, text,
             [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]])

# ── STATUS ────────────────────────────────────────────────────────────────────
def show_status(chat_id, message_id):
    try:
        with get_db_cursor() as c:
            c.execute("SELECT COUNT(*) FROM history")
            total_rows = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM alerts WHERE active=1")
            active_alerts = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM users")
            total_users = c.fetchone()[0]
            c.execute("SELECT COUNT(DISTINCT chat) FROM watchlists")
            wl_users = c.fetchone()[0]
            c.execute("SELECT COUNT(DISTINCT chat) FROM portfolio")
            port_users = c.fetchone()[0]
    except Exception as e:
        print("[SHOW_STATUS ERROR] %s" % e)
        total_rows = active_alerts = total_users = wl_users = port_users = 0

    lines = [
        "⚙️ <b>Market Pulse — Status</b>", "",
        "  Bot        : 🟢 Online",
        "  Time       : %s" % datetime.now().strftime("%H:%M:%S"),
        "  Coins      : %d" % len(COINS), "",
        "  Users      : %d" % total_users,
        "  Watchlists : %d users" % wl_users,
        "  Portfolios : %d users" % port_users,
        "  Alerts     : %d active" % active_alerts,
        "  DB rows    : %d" % total_rows, "",
        "  Sources:",
        "    Kraken (prices)",
        "    OKX + CryptoCompare (24h stats)",
        "    ExchangeRate-API (fiat)",
        "    Alternative.me (F&G)",
        "    CoinDesk RSS (news)",
        "    CoinTelegraph RSS (news)",
        "    Binance P2P (p2p rates)",
    ]
    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "⬅ Back", "callback_data": "main_menu"}]])

# ── CHANNEL POST BUILDERS ─────────────────────────────────────────────────────
def fetch_prices_with_retry(max_attempts=3):
    """Force fresh price fetch, retry until we get data."""
    global _kraken_cache, _secondary_cache
    for attempt in range(max_attempts):
        _kraken_cache["timestamp"] = None
        _secondary_cache["timestamp"] = None
        kraken = get_kraken_batch()
        secondary = get_secondary_batch()
        got_prices = any(kraken.get(c) or (secondary.get(coin_key(c)) or {}).get("usd")
                         for c in list(COINS.keys())[:5])
        if got_prices:
            return kraken, secondary
        print("  [RETRY %d] No prices yet, waiting 5s..." % (attempt + 1))
        time.sleep(5)
    return kraken, secondary

def build_morning_post():
    kraken, secondary = fetch_prices_with_retry()
    rates = get_fiat_rates()
    gainers, losers = get_gainers_losers()
    fg_data = get_fear_greed()
    today = wat_now().strftime("%A, %b %d %Y")
    rows = []
    for coin in list(COINS.keys())[:10]:
        price = kraken.get(coin)
        sd = secondary.get(coin_key(coin))
        if price is None and sd:
            price = sd.get("usd")
        change = sd.get("usd_24h_change") if sd else None
        if price:
            rows.append("%-6s %-14s %s" % (coin, format_price(price), format_change(change)))
    parts = [
        "🌅 <b>Morning Briefing</b>",
        "<i>%s  |  7:00 WAT</i>" % today,
        "",
        "<code>%s</code>" % "\n".join(rows),
    ]
    if gainers:
        parts.append("\n🔥 <b>Top Gainer:</b> <b>%s</b> +%.2f%%" % (gainers[0][0], gainers[0][2]))
    if losers:
        parts.append("📉 <b>Top Loser:</b> <b>%s</b> %.2f%%" % (losers[0][0], losers[0][2]))
    if fg_data:
        val = fg_data[0]["value"]
        label = fg_data[0]["value_classification"]
        parts.append("\n🧠 <b>Fear & Greed:</b> %s %s/100 — %s" % (fg_emoji(val), val, label))
    buy = _binance_p2p("BUY", "USDT", "NGN") or _bybit_p2p("BUY", "USDT", "NGN")
    sell = _binance_p2p("SELL", "USDT", "NGN") or _bybit_p2p("SELL", "USDT", "NGN")
    if not buy or not sell:
        usdt_price, _ = get_best_price("USDT")
        ngn_rate = rates.get("NGN")
        if usdt_price and ngn_rate:
            buy = round(usdt_price * ngn_rate * 1.01, 0)
            sell = round(usdt_price * ngn_rate * 0.99, 0)
    if buy and sell:
        spread = round(buy - sell, 0)
        parts.append("\n💱 <b>USDT/NGN</b>  Buy ₦{:,.0f}  |  Sell ₦{:,.0f}  |  Spread ₦{:,.0f}".format(buy, sell, spread))
    parts.append("\n<i>Good morning traders! Stay sharp. Powered by @MarketNgPulseBot</i>")
    return "\n".join(parts)

def build_evening_post():
    kraken, secondary = fetch_prices_with_retry()
    rates = get_fiat_rates()
    gainers, losers = get_gainers_losers()
    today = wat_now().strftime("%b %d")
    rows = []
    for coin in list(COINS.keys())[:10]:
        price = kraken.get(coin)
        sd = secondary.get(coin_key(coin))
        if price is None and sd:
            price = sd.get("usd")
        change = sd.get("usd_24h_change") if sd else None
        if price:
            rows.append("%-6s %-14s %s" % (coin, format_price(price), format_change(change)))
    parts = [
        "🌙 <b>Evening Recap</b>",
        "<i>%s  |  21:00 WAT</i>" % today,
        "",
        "<code>%s</code>" % "\n".join(rows),
    ]
    if gainers:
        parts.append("\n📈 <b>Day Winners:</b>")
        for coin, price, chg in gainers[:3]:
            parts.append("  <b>%s</b> +%.2f%%" % (coin, chg))
    if losers:
        parts.append("\n📉 <b>Day Losers:</b>")
        for coin, price, chg in losers[:3]:
            parts.append("  <b>%s</b> %.2f%%" % (coin, chg))
    buy = _binance_p2p("BUY", "USDT", "NGN") or _bybit_p2p("BUY", "USDT", "NGN")
    sell = _binance_p2p("SELL", "USDT", "NGN") or _bybit_p2p("SELL", "USDT", "NGN")
    if not buy or not sell:
        usdt_price, _ = get_best_price("USDT")
        ngn_rate = rates.get("NGN")
        if usdt_price and ngn_rate:
            buy = round(usdt_price * ngn_rate * 1.01, 0)
            sell = round(usdt_price * ngn_rate * 0.99, 0)
    if buy and sell:
        spread = round(buy - sell, 0)
        parts.append("\n💱 <b>USDT/NGN</b>  Buy ₦{:,.0f}  |  Sell ₦{:,.0f}  |  Spread ₦{:,.0f}".format(buy, sell, spread))
    parts.append("\n<i>Rest well. Markets never sleep. Powered by @MarketNgPulseBot</i>")
    return "\n".join(parts)

def build_hourly_snapshot():
    """Short market snapshot posted every hour to the channel."""
    kraken, secondary = fetch_prices_with_retry()
    gainers, losers = get_gainers_losers()
    fg_data = get_fear_greed()
    now = wat_now().strftime("%H:%M WAT")

    btc_price = kraken.get("BTC")
    eth_price = kraken.get("ETH")
    btc_sd = secondary.get(coin_key("BTC"))
    eth_sd = secondary.get(coin_key("ETH"))
    btc_chg = btc_sd.get("usd_24h_change") if btc_sd else None
    eth_chg = eth_sd.get("usd_24h_change") if eth_sd else None

    buy = _binance_p2p("BUY", "USDT", "NGN") or _bybit_p2p("BUY", "USDT", "NGN")
    sell = _binance_p2p("SELL", "USDT", "NGN") or _bybit_p2p("SELL", "USDT", "NGN")
    if not buy or not sell:
        usdt_price, _ = get_best_price("USDT")
        ngn_rate = get_fiat_rates().get("NGN")
        if usdt_price and ngn_rate:
            buy = round(usdt_price * ngn_rate * 1.01, 0)
            sell = round(usdt_price * ngn_rate * 0.99, 0)

    lines = ["⚡ <b>Market Snapshot</b>  <i>%s</i>" % now, ""]
    if btc_price:
        lines.append("  <b>BTC</b>  %s  %s" % (format_price(btc_price), format_change(btc_chg)))
    if eth_price:
        lines.append("  <b>ETH</b>  %s  %s" % (format_price(eth_price), format_change(eth_chg)))
    if buy and sell:
        lines.append("  <b>USDT/NGN</b>  Buy ₦{:,.0f}  Sell ₦{:,.0f}".format(buy, sell))
    if fg_data:
        val = fg_data[0]["value"]
        label = fg_data[0]["value_classification"]
        lines.append("  <b>F&G</b>  %s %s — %s" % (fg_emoji(val), val, label))
    if gainers:
        lines.append("  📈 <b>%s</b> +%.2f%%" % (gainers[0][0], gainers[0][2]))
    if losers:
        lines.append("  📉 <b>%s</b> %.2f%%" % (losers[0][0], losers[0][2]))
    lines += ["", "<i>@MarketNgPulseBot</i>"]
    return "\n".join(lines)

def build_p2p_channel_post():
    """Real P2P snapshot for the channel."""
    now = wat_now().strftime("%H:%M WAT")
    pairs = [("USDT", "NGN"), ("BTC", "NGN"), ("USDT", "GHS")]
    lines = ["💱 <b>P2P Market Update</b>", "<i>%s</i>" % now, ""]

    any_data = False
    for crypto, fiat in pairs:
        fiat_name, fiat_sym = P2P_FIATS.get(fiat, (fiat, fiat))
        buy = _binance_p2p("BUY", crypto, fiat) or _bybit_p2p("BUY", crypto, fiat)
        sell = _binance_p2p("SELL", crypto, fiat) or _bybit_p2p("SELL", crypto, fiat)

        if not buy or not sell:
            rates = get_fiat_rates()
            p, _ = get_best_price(crypto)
            r = rates.get(fiat)
            if p and r:
                buy = round(p * r * 1.01, 2)
                sell = round(p * r * 0.99, 2)

        if buy and sell:
            any_data = True
            spread = round(buy - sell, 2)

            def fmt(v):
                if v >= 100:
                    return "%s%s" % (fiat_sym, "{:,.0f}".format(v))
                elif v >= 1:
                    return "%s%.2f" % (fiat_sym, v)
                else:
                    return "%s%.4f" % (fiat_sym, v)

            lines += [
                "<b>%s/%s</b>" % (crypto, fiat),
                "  🟢 Buy    <b>%s</b>" % fmt(buy),
                "  🔴 Sell   <b>%s</b>" % fmt(sell),
                "  📊 Spread <b>%s</b>" % fmt(spread),
                "",
            ]

    if not any_data:
        return None

    lines += ["<i>Source: Binance/Bybit P2P  |  @MarketNgPulseBot</i>"]
    return "\n".join(lines)

def build_gainers_post():
    gainers, losers = get_gainers_losers()
    now = wat_now().strftime("%H:%M WAT")
    parts = ["🔥 <b>Top Movers (24h)</b>", "<i>%s</i>" % now, ""]
    if gainers:
        parts.append("📈 <b>Gainers</b>")
        for i, (coin, price, chg) in enumerate(gainers[:5], 1):
            p = format_price(price) if price else "—"
            parts.append("  %d. <b>%s</b>  %s  <b>+%.2f%%</b>" % (i, coin, p, chg))
    parts.append("")
    if losers:
        parts.append("📉 <b>Losers</b>")
        for i, (coin, price, chg) in enumerate(losers[:5], 1):
            p = format_price(price) if price else "—"
            parts.append("  %d. <b>%s</b>  %s  <b>%.2f%%</b>" % (i, coin, p, chg))
    parts += ["", "<i>Powered by @MarketNgPulseBot</i>"]
    return "\n".join(parts)

def build_bigmove_post(coin, price, change):
    direction = "PUMPING 🚀" if change > 0 else "DUMPING 🔴"
    sign = "+" if change > 0 else ""
    return "\n".join([
        "⚡ <b>BIG MOVE ALERT</b>",
        "",
        "<b>%s</b> is <b>%s</b>" % (coin, direction),
        "  Price : <b>%s</b>" % format_price(price),
        "  24h   : <b>%s%.2f%%</b>" % (sign, change),
        "",
        "<i>Stay alert. Powered by @MarketNgPulseBot</i>",
    ])

def build_funding_channel_post():
    rates = get_funding_rates()
    if not rates:
        return None
    extreme = {c: r for c, r in rates.items() if abs(r) > 0.05}
    if not extreme:
        return None

    lines = ["📊 <b>Funding Rate Alert</b>", ""]
    for coin, rate in extreme.items():
        direction = "🔴 Overleveraged longs" if rate > 0 else "🟢 Overleveraged shorts"
        lines.append("  <b>%s</b>  %s%.4f%%  %s" % (
            coin, "+" if rate >= 0 else "", rate, direction))
    lines += [
        "",
        "High funding rates often precede sharp reversals.",
        "",
        "👉 @MarketNgPulseBot for full data",
    ]
    return "\n".join(lines)

def build_liquidation_channel_post():
    data = get_liquidation_data()
    if not data:
        return None
    total_long = sum(d.get("long_usd", 0) for d in data.values()) / 1e6
    total_short = sum(d.get("short_usd", 0) for d in data.values()) / 1e6
    if total_long + total_short < 10:
        return None

    dominant = "Long" if total_long > total_short else "Short"
    lines = ["💥 <b>Liquidation Update</b>", ""]
    for coin, d in data.items():
        lm = d.get("long_usd", 0) / 1e6
        sm = d.get("short_usd", 0) / 1e6
        if lm + sm > 1:
            lines.append("  <b>%s</b>  Long $%.1fM  Short $%.1fM" % (coin, lm, sm))
    lines += [
        "",
        "  Total Long  : <b>$%.1fM</b>" % total_long,
        "  Total Short : <b>$%.1fM</b>" % total_short,
        "",
        "<i>%s positions being liquidated. "
        "Market was overleveraged %s.</i>" % (dominant, dominant.lower()),
        "",
        "👉 @MarketNgPulseBot",
    ]
    return "\n".join(lines)

def build_smart_news_post():
    articles = get_crypto_news()
    if not articles:
        return None

    now = wat_now().strftime("%H:%M WAT")
    lines = ["📰 <b>Crypto News</b>  <i>%s</i>" % now, ""]

    for art in articles[:3]:
        title = art.get("title", "")
        url = art.get("url", "")
        src = art.get("source", {}).get("title", "") if isinstance(art.get("source"), dict) else ""

        if url:
            lines.append("• <a href=\"%s\">%s</a>" % (url, title))
        else:
            lines.append("• %s" % title)
        if src:
            lines.append("  <i>%s</i>" % src)

        if DEEPSEEK_KEY and title:
            impact = ask_ai(
                "Crypto headline: '%s'. In ONE sentence, explain impact for Nigerian traders "
                "and whether it's Bullish, Bearish or Neutral." % title[:200])
            if impact and len(impact) < 200:
                lines.append("  🤖 %s" % impact)
        lines.append("")

    lines.append("<i>@MarketNgPulseBot</i>")
    return "\n".join(lines)

def build_opportunity_scanner_post():
    secondary = get_secondary_batch()
    kraken = get_kraken_batch()
    now = wat_now().strftime("%H:%M WAT")

    coins_data = []
    for coin in ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "LINK", "DOT", "POL"]:
        price = kraken.get(coin)
        sd = secondary.get(coin_key(coin))
        change = sd.get("usd_24h_change") if sd else None
        vol = sd.get("usd_24h_vol") if sd else None
        if price and change is not None:
            coins_data.append((coin, price, change, vol or 0))

    if not coins_data:
        return None

    lines = ["🔥 <b>Momentum Scanner</b>  <i>%s</i>" % now,
             "<i>Market awareness — not financial advice</i>", ""]

    for coin, price, chg, vol in sorted(coins_data, key=lambda x: abs(x[2]), reverse=True)[:6]:
        if chg > 5:
            status = "🚀 Strong Momentum"
        elif chg > 2:
            status = "📈 Gaining"
        elif chg > 0:
            status = "↗️ Slightly Up"
        elif chg > -2:
            status = "↘️ Slightly Down"
        elif chg > -5:
            status = "📉 Losing Ground"
        else:
            status = "🔴 Heavy Selling"
        lines.append("  <b>%s</b>  %s  %s%.1f%%" % (
            coin, status, "+" if chg >= 0 else "", chg))

    high_movers = [(c, ch) for c, _, ch, _ in coins_data if abs(ch) > 5]
    if high_movers:
        prompt = ("Coins with big 24h moves: %s. "
                  "In 1 sentence, assess current market risk level for a Nigerian trader." %
                  ", ".join("%s %+.1f%%" % (c, ch) for c, ch in high_movers[:3]))
        risk_ai = ask_ai(prompt)
        if risk_ai and len(risk_ai) < 150:
            lines += ["", "⚠️ <b>Risk:</b> %s" % risk_ai]

    lines += ["", "<i>@MarketNgPulseBot</i>"]
    return "\n".join(lines)

# ── CHANNEL POSTING ───────────────────────────────────────────────────────────
def post_to_channel(text):
    if not CHANNEL_ENABLED:
        return
    data = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    result = tg("sendMessage", data)
    if not result.get("ok"):
        print("[CHANNEL ERROR] %s" % result.get("description", "unknown"))
    return result

# ── ADMIN ─────────────────────────────────────────────────────────────────────
def build_admin_stats_text():
    try:
        with get_db_cursor() as c:
            c.execute("SELECT COUNT(*) FROM users")
            total = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM users WHERE last_seen >= datetime('now','-1 day')")
            active_24h = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM users WHERE last_seen >= datetime('now','-7 day')")
            active_7d = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM users WHERE first_seen >= datetime('now','-1 day')")
            new_today = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM users WHERE first_seen >= datetime('now','-7 day')")
            new_7d = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM alerts WHERE active=1")
            alerts = c.fetchone()[0]
            c.execute("SELECT COUNT(DISTINCT chat) FROM watchlists")
            wl = c.fetchone()[0]
            c.execute("SELECT COUNT(DISTINCT chat) FROM portfolio")
            pf = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM history")
            rows = c.fetchone()[0]

            c.execute("""SELECT date(first_seen), COUNT(*) FROM users
                         WHERE first_seen >= datetime('now','-7 day')
                         GROUP BY date(first_seen) ORDER BY date(first_seen)""")
            trend_rows = c.fetchall()

            c.execute("""SELECT feature, COUNT(*) FROM analytics
                         WHERE timestamp >= datetime('now','-7 day')
                         GROUP BY feature ORDER BY COUNT(*) DESC LIMIT 8""")
            top_actions = c.fetchall()
    except Exception as e:
        print("[BUILD_ADMIN_STATS_TEXT ERROR] %s" % e)
        return "Could not load stats."

    lines = [
        "📊 <b>Admin Stats</b>", "",
        "  Total Users   : %d" % total,
        "  Active (24h)  : %d" % active_24h,
        "  Active (7d)   : %d" % active_7d,
        "  New today     : %d" % new_today,
        "  New (7d)      : %d" % new_7d,
        "  Watchlists    : %d users" % wl,
        "  Portfolios    : %d users" % pf,
        "  Active Alerts : %d" % alerts,
        "  History rows  : %d" % rows,
    ]
    if trend_rows:
        lines += ["", "  New users / day (7d):"]
        for d, cnt in trend_rows:
            lines.append("    %s  %s %d" % (d, "▮" * min(cnt, 20), cnt))
    if top_actions:
        lines += ["", "  Top features (7d):"]
        for action, cnt in top_actions:
            lines.append("    %-16s %d" % (action, cnt))
    return "\n".join(lines)

def handle_admin_command(chat_id, text):
    """All admin commands require chat_id in ADMIN_IDS + correct ADMIN_CODE."""
    parts = text.strip().split()
    cmd = parts[0].lower()

    if ADMIN_CODE:
        if len(parts) < 2 or parts[-1] != ADMIN_CODE:
            return
        parts = parts[:-1]

    if chat_id not in ADMIN_IDS:
        return

    if cmd == "/stats":
        send(chat_id, build_admin_stats_text())

    elif cmd == "/broadcast":
        msg = " ".join(parts[1:]).strip()
        if not msg:
            send(chat_id, "Usage: /broadcast ADMINCODE Your message")
            return
        try:
            with get_db_cursor() as c:
                c.execute("SELECT chat FROM users")
                chats = [r[0] for r in c.fetchall()]
        except Exception:
            chats = []
        ok = fail = 0
        for cid in chats:
            try:
                result = send(int(cid), "📢 <b>Market Pulse</b>\n\n" + msg)
                if result and result.get("ok"):
                    ok += 1
                else:
                    fail += 1
            except Exception:
                fail += 1
            time.sleep(0.05)
        send(chat_id, "✅ Broadcast done. Sent: %d  Failed: %d" % (ok, fail))

    elif cmd == "/grantpro":
        if len(parts) < 2:
            send(chat_id, "Usage: /grantpro ADMINCODE CHATID")
            return
        try:
            target = int(parts[1])
            grant_pro(target, chat_id)
            send(chat_id, "✅ Pro granted to %d" % target)
            send(target,
                 "⭐ <b>Welcome to Market Pulse Pro!</b>\n\n"
                 "Your account has been upgraded. You now have full access to:\n"
                 "• Real community P2P rates\n"
                 "• Unlimited Ask AI\n"
                 "• Instant alerts\n"
                 "• Arbitrage opportunities\n"
                 "• VIP channel access\n\n"
                 "Thank you for supporting Market Pulse! 🙏")
        except Exception as e:
            send(chat_id, "Error: %s" % e)

    elif cmd == "/revokepro":
        if len(parts) < 2:
            send(chat_id, "Usage: /revokepro ADMINCODE CHATID")
            return
        try:
            target = int(parts[1])
            revoke_pro(target)
            send(chat_id, "✅ Pro revoked from %d" % target)
        except Exception as e:
            send(chat_id, "Error: %s" % e)

    elif cmd == "/rate":
        if len(parts) < 5:
            send(chat_id, "Usage: /rate ADMINCODE CRYPTO FIAT BUY SELL")
            return
        try:
            crypto = parts[1].upper()
            fiat = parts[2].upper()
            buy_rate = float(parts[3].replace(",", ""))
            sell_rate = float(parts[4].replace(",", ""))
            submit_community_rate(chat_id, crypto, fiat, buy_rate, sell_rate,
                                  "Admin", is_admin=True)
            fiat_sym = P2P_FIATS.get(fiat, (fiat, fiat))[1]
            send(chat_id,
                 "✅ Rate submitted as admin (weight: 10)\n"
                 "%s/%s — Buy %s%s  Sell %s%s" % (
                     crypto, fiat,
                     fiat_sym, "{:,.0f}".format(buy_rate),
                     fiat_sym, "{:,.0f}".format(sell_rate)))
        except Exception as e:
            send(chat_id, "Error: %s" % e)

    elif cmd == "/publish":
        note = " ".join(parts[1:]).strip()
        publish_weekly_edge(chat_id, note)

    elif cmd == "/preview":
        try:
            with get_db_cursor() as c:
                c.execute("SELECT data_json FROM weekly_data WHERE published=0 "
                          "ORDER BY id DESC LIMIT 1")
                row = c.fetchone()
        except Exception:
            row = None
        if not row:
            send(chat_id, "No unpublished weekly data found.")
            return
        send(chat_id, "👁 Preview — this is what will be posted:")
        publish_weekly_edge(chat_id, "", data=json.loads(row[0]))
        send(chat_id, "⬆️ That was a preview. Use /publish ADMINCODE [note] to post.")

    elif cmd == "/pending":
        try:
            with get_db_cursor() as c:
                c.execute("SELECT id, crypto, fiat, buy_rate, sell_rate, exchange, "
                          "confirmations, timestamp FROM community_p2p WHERE status='pending' "
                          "ORDER BY timestamp DESC LIMIT 10")
                rows = c.fetchall()
        except Exception:
            rows = []
        if not rows:
            send(chat_id, "No pending rates.")
            return
        lines = ["⏳ <b>Pending Rates</b>\n"]
        for rid, cr, fi, buy, sell, ex, conf, ts in rows:
            fiat_sym = P2P_FIATS.get(fi, (fi, fi))[1]
            lines.append("ID:%d  %s/%s  Buy:%s%s  Sell:%s%s  %d/%d conf  %s  %s" % (
                rid, cr, fi, fiat_sym, "{:,.0f}".format(buy),
                fiat_sym, "{:,.0f}".format(sell),
                conf, P2P_CONSENSUS_NEED, ex, ts[:16]))
        lines.append("\nUse /approve ADMINCODE RATE_ID to approve")
        send(chat_id, "\n".join(lines))

    elif cmd == "/approve":
        if len(parts) < 2:
            send(chat_id, "Usage: /approve ADMINCODE RATE_ID")
            return
        try:
            rate_id = int(parts[1])
            with get_db_cursor() as c:
                c.execute("UPDATE community_p2p SET status='live' WHERE id=?", (rate_id,))
            send(chat_id, "✅ Rate %d approved and live." % rate_id)
        except Exception as e:
            send(chat_id, "Error: %s" % e)

    elif cmd == "/reject":
        if len(parts) < 2:
            send(chat_id, "Usage: /reject ADMINCODE RATE_ID")
            return
        try:
            rate_id = int(parts[1])
            with get_db_cursor() as c:
                c.execute("SELECT chat FROM community_p2p WHERE id=?", (rate_id,))
                row = c.fetchone()
                c.execute("UPDATE community_p2p SET status='rejected' WHERE id=?", (rate_id,))
            if row:
                record_submission_attempt(int(row[0]), False)
            send(chat_id, "✅ Rate %d rejected. Submitter received a strike." % rate_id)
        except Exception as e:
            send(chat_id, "Error: %s" % e)

    elif cmd == "/blocked":
        try:
            with get_db_cursor() as c:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c.execute("SELECT chat, strikes_today, blocked_until FROM rate_submissions "
                          "WHERE blocked_until > ? ORDER BY blocked_until DESC", (now_str,))
                rows = c.fetchall()
        except Exception:
            rows = []
        if not rows:
            send(chat_id, "No blocked users.")
            return
        lines = ["🚫 <b>Blocked Submitters</b>\n"]
        for bchat, strikes, blocked_until in rows:
            lines.append("Chat: %s  Strikes: %d  Until: %s" % (
                bchat, strikes or 0, blocked_until[:16]))
        lines.append("\nUse /unblock ADMINCODE CHATID to unblock")
        send(chat_id, "\n".join(lines))

    elif cmd == "/unblock":
        if len(parts) < 2:
            send(chat_id, "Usage: /unblock ADMINCODE CHATID")
            return
        try:
            target = int(parts[1])
            with get_db_cursor() as c:
                c.execute("UPDATE rate_submissions SET blocked_until=NULL, "
                          "strikes_today=0 WHERE chat=?", (str(target),))
            send(chat_id, "✅ User %d unblocked." % target)
        except Exception as e:
            send(chat_id, "Error: %s" % e)

    elif cmd == "/appeals":
        try:
            with get_db_cursor() as c:
                c.execute("SELECT id, chat, reason, status, created_at FROM appeals "
                          "WHERE status='pending' ORDER BY created_at ASC LIMIT 20")
                rows = c.fetchall()
        except Exception:
            rows = []
        if not rows:
            send(chat_id, "No pending appeals.")
            return
        lines = ["📋 <b>Pending Appeals</b>\n"]
        for aid, achat, reason, status, created in rows:
            lines.append("ID:%d  Chat:%s  Reason:%s  Created:%s" % (
                aid, achat, reason[:50], created[:16]))
        lines.append("\nUse /appeal_approve ADMINCODE ID or /appeal_reject ADMINCODE ID")
        send(chat_id, "\n".join(lines))

    elif cmd == "/appeal_approve":
        if len(parts) < 2:
            send(chat_id, "Usage: /appeal_approve ADMINCODE APPEAL_ID")
            return
        try:
            appeal_id = int(parts[1])
            with get_db_cursor() as c:
                c.execute("SELECT chat FROM appeals WHERE id=? AND status='pending'", (appeal_id,))
                row = c.fetchone()
                if row:
                    c.execute("UPDATE appeals SET status='approved', resolved_at=? WHERE id=?",
                              (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), appeal_id))
                    c.execute("UPDATE rate_submissions SET blocked_until=NULL, "
                              "strikes_today=0 WHERE chat=?", (row[0],))
                    send(int(row[0]),
                         "✅ <b>Your appeal has been approved!</b>\n\n"
                         "Your account has been unblocked. You can now submit P2P rates again. "
                         "Thank you for your patience. 🙏")
            send(chat_id, "✅ Appeal approved and user unblocked.")
        except Exception as e:
            send(chat_id, "Error: %s" % e)

    elif cmd == "/appeal_reject":
        if len(parts) < 2:
            send(chat_id, "Usage: /appeal_reject ADMINCODE APPEAL_ID")
            return
        try:
            appeal_id = int(parts[1])
            with get_db_cursor() as c:
                c.execute("SELECT chat FROM appeals WHERE id=? AND status='pending'", (appeal_id,))
                row = c.fetchone()
                if row:
                    c.execute("UPDATE appeals SET status='rejected', resolved_at=? WHERE id=?",
                              (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), appeal_id))
                    send(int(row[0]),
                         "❌ <b>Your appeal has been rejected.</b>\n\n"
                         "Please wait for your block to expire or contact support for assistance.")
            send(chat_id, "✅ Appeal rejected.")
        except Exception as e:
            send(chat_id, "Error: %s" % e)

# ── WEEKLY EDGE SYSTEM ────────────────────────────────────────────────────────
def collect_weekly_data():
    """Collect all market data for the week and save to DB."""
    now = datetime.now()
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    since = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

    coin_data = {}
    try:
        with get_db_cursor() as c:
            for coin in ["BTC", "ETH", "SOL", "BNB", "XRP"]:
                c.execute("SELECT price FROM history WHERE coin=? AND timestamp>=? "
                          "ORDER BY id ASC LIMIT 1", (coin, since))
                r0 = c.fetchone()
                c.execute("SELECT price FROM history WHERE coin=? ORDER BY id DESC LIMIT 1", (coin,))
                r1 = c.fetchone()
                if r0 and r1:
                    p0 = r0[0]
                    p1 = r1[0]
                    chg = (p1 - p0) / p0 * 100 if p0 else 0
                    coin_data[coin] = {"start": p0, "end": p1, "change": round(chg, 2)}

            c.execute("SELECT buy_rate, sell_rate, timestamp FROM community_p2p "
                      "WHERE crypto='USDT' AND fiat='NGN' AND timestamp>=? "
                      "ORDER BY timestamp ASC", (since,))
            p2p_rows = c.fetchall()
    except Exception as e:
        print("[COLLECT_WEEKLY_DATA ERROR] %s" % e)
        p2p_rows = []

    p2p_data = {}
    if p2p_rows:
        p2p_data = {
            "start": p2p_rows[0][0],
            "end": p2p_rows[-1][0],
            "peak": max(r[0] for r in p2p_rows),
            "low": min(r[0] for r in p2p_rows),
            "change": round(p2p_rows[-1][0] - p2p_rows[0][0], 2),
        }

    fg = get_fear_greed()
    fg_data = {}
    if fg and len(fg) >= 2:
        fg_data = {
            "current": fg[0]["value"],
            "label": fg[0]["value_classification"],
            "week_ago": fg[-1]["value"] if len(fg) > 6 else fg[-1]["value"],
        }

    best = max(coin_data.items(), key=lambda x: x[1]["change"]) if coin_data else None
    worst = min(coin_data.items(), key=lambda x: x[1]["change"]) if coin_data else None

    news = get_crypto_news() or []
    headlines = [a.get("title", "") for a in news[:5]]

    data = {
        "coins": coin_data,
        "p2p": p2p_data,
        "fg": fg_data,
        "best": {"coin": best[0], "change": best[1]["change"]} if best else None,
        "worst": {"coin": worst[0], "change": worst[1]["change"]} if worst else None,
        "headlines": headlines,
        "week_start": week_start,
        "generated": now.strftime("%Y-%m-%d %H:%M:%S"),
    }

    ai_prompt = (
        "You are Market Pulse AI preparing a weekly market brief for Nigerian traders. "
        "Based on this data, write a short insider-style market analysis (4-6 sentences). "
        "Sound like a smart analyst who noticed things others missed. "
        "Be direct and confident. No disclaimers. No bullet points. Just flowing text.\n\n"
        "Data: %s" % json.dumps(data, indent=2)
    )
    data["ai_draft"] = ask_ai(ai_prompt)

    try:
        with get_db_cursor() as c:
            c.execute("INSERT INTO weekly_data (week_start, data_json, published, created_at) "
                      "VALUES (?,?,0,?)",
                      (week_start, json.dumps(data), now.strftime("%Y-%m-%d %H:%M:%S")))
    except Exception as e:
        print("[COLLECT_WEEKLY_DATA DB ERROR] %s" % e)
    return data

def send_weekly_brief_to_admin(data):
    """Send weekly data brief privately to admin for review."""
    d = data
    coins = d.get("coins", {})
    p2p = d.get("p2p", {})
    fg = d.get("fg", {})
    best = d.get("best")
    worst = d.get("worst")

    lines = [
        "📊 <b>Your Weekly Data Brief</b>",
        "<i>Review and reply /publish [your note] to post to channel</i>", "",
        "━━━━━━━━━━━━━━━━━━━━",
        "<b>MARKET THIS WEEK:</b>",
    ]
    for coin, cd in coins.items():
        sign = "+" if cd["change"] >= 0 else ""
        lines.append("  %s: %s → %s (%s%.1f%%)" % (
            coin, format_price(cd["start"]),
            format_price(cd["end"]), sign, cd["change"]))

    if p2p:
        lines += [
            "",
            "<b>USDT/NGN THIS WEEK:</b>",
            "  Start : ₦{:,.0f}".format(p2p.get("start", 0)),
            "  End   : ₦{:,.0f}".format(p2p.get("end", 0)),
            "  Peak  : ₦{:,.0f}".format(p2p.get("peak", 0)),
            "  Low   : ₦{:,.0f}".format(p2p.get("low", 0)),
            "  Move  : ₦{:,.0f}".format(p2p.get("change", 0)),
        ]

    if fg:
        lines += [
            "",
            "<b>FEAR & GREED:</b>",
            "  Now     : %s %s/100 — %s" % (fg_emoji(fg.get("current", 50)),
                                              fg.get("current"), fg.get("label")),
            "  Week ago: %s/100" % fg.get("week_ago"),
        ]

    if best:
        lines += ["", "<b>BEST:</b>  %s +%.1f%%" % (best["coin"], best["change"])]
    if worst:
        lines += ["<b>WORST:</b> %s %.1f%%" % (worst["coin"], worst["change"])]

    headlines = d.get("headlines", [])
    if headlines:
        lines += ["", "<b>TOP NEWS:</b>"]
        for h in headlines[:3]:
            lines.append("  • %s" % h[:80])

    ai_draft = d.get("ai_draft", "")
    if ai_draft:
        lines += ["", "<b>AI DRAFT ANALYSIS:</b>", "<i>%s</i>" % ai_draft]

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "Reply with:",
        "<code>/publish ADMINCODE Your personal note here</code>",
        "",
        "<i>Your note will be combined with the AI analysis and posted to the channel.</i>",
        "<i>If no reply by 9pm, AI version posts automatically.</i>",
    ]

    for admin_id in ADMIN_IDS:
        try:
            send(admin_id, "\n".join(lines))
        except Exception as e:
            print("[WEEKLY BRIEF ERROR] %s" % e)

def publish_weekly_edge(admin_chat_id, personal_note, data=None):
    """Build and post the Weekly Edge to channel."""
    if data is None:
        try:
            with get_db_cursor() as c:
                c.execute("SELECT data_json FROM weekly_data WHERE published=0 "
                          "ORDER BY id DESC LIMIT 1")
                row = c.fetchone()
        except Exception:
            row = None
        if not row:
            send(admin_chat_id, "⚠️ No weekly data found. Wait for Saturday brief.")
            return
        data = json.loads(row[0])

    coins = data.get("coins", {})
    p2p = data.get("p2p", {})
    best = data.get("best")
    worst = data.get("worst")
    ai = data.get("ai_draft", "")
    now = wat_now().strftime("%B %d, %Y")

    lines = [
        "🔥 <b>Market Pulse Weekly Edge</b>",
        "<i>%s</i>" % now, "",
    ]

    if personal_note:
        lines += [personal_note, ""]

    if ai:
        lines += ["<i>%s</i>" % ai, ""]

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("<b>This Week at a Glance</b>")
    for coin, cd in coins.items():
        sign = "+" if cd["change"] >= 0 else ""
        lines.append("  %s  %s%.1f%%" % (coin, sign, cd["change"]))

    if p2p:
        lines += ["",
                  "<b>USDT/NGN</b>  ₦{:,.0f} → ₦{:,.0f}  ({:+,.0f})".format(
                      p2p.get("start", 0), p2p.get("end", 0), p2p.get("change", 0))]

    if best:
        lines.append("🏆 Best: <b>%s</b> +%.1f%%" % (best["coin"], best["change"]))
    if worst:
        lines.append("📉 Worst: <b>%s</b> %.1f%%" % (worst["coin"], worst["change"]))

    lines += ["", "<i>Powered by @MarketNgPulseBot</i>"]

    post_to_channel("\n".join(lines))

    try:
        with get_db_cursor() as c:
            c.execute("UPDATE weekly_data SET published=1 WHERE published=0")
    except Exception as e:
        print("[PUBLISH_WEEKLY_EDGE DB ERROR] %s" % e)

    send(admin_chat_id, "✅ Weekly Edge posted to channel successfully.")
    print("[WEEKLY EDGE] Posted to channel")

# ── MAIN RUN LOOP ─────────────────────────────────────────────────────────────
def run():
    init_db()
    print("Market Pulse started (v15 - FIXED)")

    last_update_id = 0
    last_save = 0
    last_news_post = 0
    last_p2p_post = 0
    last_whale_check = 0
    last_snapshot = 0
    last_opportunity = 0
    last_arbitrage_check = 0
    last_breakout_check = 0
    last_funding_check = 0
    last_liquidation_check = 0
    morning_posted = False
    midday_posted = False
    evening_posted = False
    p2p_morning_posted = False
    p2p_evening_posted = False
    gainers_posted = False
    trade_setup_posted = False
    admin_digest_posted = False
    weekly_posted = False
    weekly_auto_posted = False
    daily_summary_posted = False
    rate_prompts_posted = False
    last_day = None
    last_btc_price = None
    last_eth_price = None

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
                p2p_morning_posted = False
                p2p_evening_posted = False
                gainers_posted = False
                trade_setup_posted = False
                admin_digest_posted = False
                daily_summary_posted = False
                rate_prompts_posted = False
                if wat.weekday() == 5:
                    weekly_posted = False
                    weekly_auto_posted = False
                last_day = wat_day
                reset_daily_submission_counts()

            if now - last_save >= 300:
                print("[%s WAT] Saving" % wat.strftime("%H:%M"))
                save_history()
                check_alerts()
                check_p2p_alerts()
                cleanup_expired_rates()
                last_save = now

            if now - last_snapshot >= 3600:
                save_portfolio_snapshots()
                last_snapshot = now

            if CHANNEL_ENABLED:
                if wat_h == SCHEDULE["morning_hour_wat"] and not morning_posted:
                    print("[CHANNEL] Morning brief")
                    post_to_channel(build_morning_post())
                    send_daily_portfolio_summaries()
                    morning_posted = True

                if wat_h == SCHEDULE["trade_setup_hour_wat"] and not trade_setup_posted:
                    setup_msg = build_trade_setup_post("BTC")
                    if setup_msg:
                        print("[CHANNEL] Trade setup")
                        post_to_channel(setup_msg)
                    trade_setup_posted = True

                if wat_h == SCHEDULE["p2p_morning_hour"] and not p2p_morning_posted:
                    p2p_msg = build_p2p_channel_post()
                    if p2p_msg:
                        print("[CHANNEL] P2P morning")
                        post_to_channel(p2p_msg)
                    send_daily_rate_prompts()
                    p2p_morning_posted = True

                if wat_h == SCHEDULE["midday_hour_wat"] and not midday_posted:
                    print("[CHANNEL] Midday snapshot")
                    post_to_channel(build_hourly_snapshot())
                    midday_posted = True

                if wat_h == SCHEDULE["gainers_hour_wat"] and not gainers_posted:
                    print("[CHANNEL] Gainers")
                    post_to_channel(build_gainers_post())
                    gainers_posted = True

                if wat_h == SCHEDULE["p2p_evening_hour"] and not p2p_evening_posted:
                    p2p_msg = build_p2p_channel_post()
                    if p2p_msg:
                        print("[CHANNEL] P2P evening")
                        post_to_channel(p2p_msg)
                    send_daily_rate_prompts()
                    p2p_evening_posted = True

                if wat_h == SCHEDULE["evening_hour_wat"] and not evening_posted:
                    print("[CHANNEL] Evening recap")
                    post_to_channel(build_evening_post())
                    evening_posted = True

                if (wat.weekday() == 5
                        and wat_h == SCHEDULE["weekly_edge_hour_wat"]
                        and not weekly_posted):
                    print("[WEEKLY] Collecting data")
                    try:
                        wdata = collect_weekly_data()
                        send_weekly_brief_to_admin(wdata)
                    except Exception as we:
                        print("[WEEKLY ERROR] %s" % we)
                    weekly_posted = True

                if (wat.weekday() == 5
                        and wat_h == SCHEDULE["weekly_auto_post_hour"]
                        and weekly_posted and not weekly_auto_posted):
                    try:
                        with get_db_cursor() as c:
                            c.execute("SELECT id FROM weekly_data WHERE published=0 "
                                      "ORDER BY id DESC LIMIT 1")
                            unpub = c.fetchone()
                    except Exception:
                        unpub = None
                    if unpub:
                        print("[WEEKLY] Auto-posting")
                        publish_weekly_edge(list(ADMIN_IDS)[0], "")
                    weekly_auto_posted = True

                if now - last_breakout_check >= SCHEDULE["breakout_check_seconds"]:
                    events = check_breakouts()
                    for ev in events:
                        print("[CHANNEL] %s %s" % (ev["coin"], ev["type"]))
                        post_to_channel(build_breakout_post(ev))
                    last_breakout_check = now

                if now - last_whale_check >= SCHEDULE["whale_check_seconds"]:
                    check_whale_watch()
                    kraken = get_kraken_batch()
                    secondary = get_secondary_batch()
                    for wc in ["BTC", "ETH"]:
                        price = kraken.get(wc)
                        sd = secondary.get(coin_key(wc), {})
                        change = sd.get("usd_24h_change") if sd else None
                        prev = last_btc_price if wc == "BTC" else last_eth_price
                        if (price and change and
                                abs(change) >= SCHEDULE["bigmove_pct"] and
                                (prev is None or
                                 abs((price - prev) / prev * 100) >= SCHEDULE["bigmove_pct"])):
                            print("[CHANNEL] Big move %s %.2f%%" % (wc, change))
                            post_to_channel(build_bigmove_post(wc, price, change))
                        if wc == "BTC":
                            last_btc_price = price
                        else:
                            last_eth_price = price
                    last_whale_check = now

                if now - last_funding_check >= SCHEDULE["funding_check_seconds"]:
                    funding_msg = build_funding_channel_post()
                    if funding_msg:
                        print("[CHANNEL] Funding alert")
                        post_to_channel(funding_msg)
                    last_funding_check = now

                if now - last_liquidation_check >= SCHEDULE["liquidation_check_seconds"]:
                    liq_msg = build_liquidation_channel_post()
                    if liq_msg:
                        print("[CHANNEL] Liquidation alert")
                        post_to_channel(liq_msg)
                    last_liquidation_check = now

                if now - last_arbitrage_check >= SCHEDULE["arbitrage_check_seconds"]:
                    opps = check_arbitrage()
                    if opps:
                        print("[CHANNEL] Arbitrage: %d" % len(opps))
                        post_to_channel(build_arbitrage_channel_post(opps))
                    last_arbitrage_check = now

                if now - last_news_post >= SCHEDULE["news_interval_seconds"]:
                    news_msg = build_smart_news_post()
                    if news_msg:
                        print("[CHANNEL] Smart news")
                        post_to_channel(news_msg)
                    last_news_post = now

                if now - last_opportunity >= SCHEDULE["opportunity_seconds"]:
                    opp = build_opportunity_scanner_post()
                    if opp:
                        print("[CHANNEL] Opportunity scanner")
                        post_to_channel(opp)
                    last_opportunity = now

            if (ADMIN_IDS and wat_h == SCHEDULE["admin_digest_hour_wat"]
                    and not admin_digest_posted):
                print("[ADMIN] Daily stats digest")
                digest = "🗓 <b>Daily Digest</b>\n\n" + build_admin_stats_text()
                for aid in ADMIN_IDS:
                    try:
                        send(aid, digest)
                    except Exception as e:
                        print("[ADMIN DIGEST ERROR] %s" % e)
                admin_digest_posted = True

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
                    increment_message_count(chat_id)
                    validate_and_count_referral(chat_id)

                    admin_cmds = ("/stats", "/broadcast", "/grantpro",
                                  "/revokepro", "/rate", "/publish", "/preview",
                                  "/pending", "/approve", "/reject", "/blocked",
                                  "/unblock", "/appeals", "/appeal_approve", "/appeal_reject")
                    if any(text.startswith(c) for c in admin_cmds):
                        if chat_id in ADMIN_IDS:
                            handle_admin_command(chat_id, text)
                        continue

                    if text.startswith("/help"):
                        show_help(chat_id, None)
                        continue

                    if text.startswith("/start"):
                        clear_state(chat_id)
                        parts_cmd = text.split()
                        if len(parts_cmd) > 1 and parts_cmd[1].startswith("ref_"):
                            try:
                                referrer = int(parts_cmd[1][4:])
                                record_referral(referrer, chat_id)
                            except Exception:
                                pass
                        pro_badge = " ⭐" if is_pro(chat_id) else ""
                        send(chat_id,
                             "👋 <b>Welcome to Market Pulse%s!</b>\n\n"
                             "Your AI-powered crypto intelligence platform "
                             "built for Nigerian traders.\n\n"
                             "✅ Live prices — Kraken, OKX, CoinGecko\n"
                             "✅ Real P2P rates with community data\n"
                             "✅ AI crypto analyst — DeepSeek, Mistral, Qwen\n"
                             "✅ Price and P2P alerts\n"
                             "✅ Portfolio tracker with charts\n"
                             "✅ Daily market briefings\n"
                             "✅ Whale watch alerts\n"
                             "✅ Arbitrage scanner\n\n"
                             "Tap a category below to get started 👇" % pro_badge)
                        show_main_menu(chat_id)
                        continue

                    if text.startswith("/upgrade"):
                        show_upgrade(chat_id)
                        continue

                    state, state_data = get_state(chat_id)
                    if state == "awaiting_alert_price":
                        handle_custom_alert_text(chat_id, text, state_data)
                    elif state == "awaiting_port_amount":
                        handle_port_amount(chat_id, text, state_data)
                    elif state == "awaiting_port_price":
                        handle_port_price(chat_id, text, state_data)
                    elif state == "awaiting_ai_question":
                        handle_ai_question(chat_id, text)
                    elif state == "awaiting_convert":
                        handle_convert(chat_id, text)
                    elif state == "awaiting_coin_search":
                        handle_coin_search(chat_id, text)
                    elif state == "awaiting_p2p_alert_target":
                        handle_p2p_alert_target(chat_id, text, state_data)
                    elif state == "awaiting_rate_submit":
                        handle_rate_submit(chat_id, text, state_data)

                if "callback_query" in u:
                    q = u["callback_query"]
                    chat_id = q["message"]["chat"]["id"]
                    message_id = q["message"]["message_id"]
                    data = q["data"]
                    username = q["from"].get("username", "")
                    first_name = q["from"].get("first_name", "")
                    answer_cb(q["id"])
                    upsert_user(chat_id, username, first_name)
                    log_event(chat_id, data.split(":")[0])

                    if not check_callback_limit(chat_id):
                        continue

                    if data == "main_menu":
                        clear_state(chat_id)
                        show_main_menu(chat_id, message_id)

                    elif data == "menu_markets":
                        show_menu_markets(chat_id, message_id)

                    elif data == "menu_intelligence":
                        show_menu_intelligence(chat_id, message_id)

                    elif data == "menu_portfolio":
                        show_menu_portfolio(chat_id, message_id)

                    elif data == "menu_nigeria":
                        show_menu_nigeria(chat_id, message_id)

                    elif data == "menu_tools":
                        show_menu_tools(chat_id, message_id)

                    elif data == "menu_alerts":
                        show_menu_alerts(chat_id, message_id)

                    elif data == "menu_account":
                        show_menu_account(chat_id, message_id)

                    elif data == "my_stats":
                        show_my_stats(chat_id, message_id)

                    elif data == "market":
                        show_market(chat_id, message_id)

                    elif data == "charts":
                        edit(chat_id, message_id,
                             "📊 <b>Charts</b> — choose a coin:",
                             coin_buttons("chart"))

                    elif data.startswith("chart:"):
                        coin = data.split(":")[1]
                        edit(chat_id, message_id,
                             "📊 <b>%s</b> — choose timeframe:" % coin, tf_buttons(coin))

                    elif data.startswith("chart_tf:"):
                        _, coin, tf = data.split(":")
                        show_chart(chat_id, message_id, coin, tf)

                    elif data == "sources":
                        edit(chat_id, message_id,
                             "📡 <b>Sources</b> — choose a coin:", coin_buttons("source"))

                    elif data.startswith("source:"):
                        show_sources(chat_id, message_id, data.split(":")[1])

                    elif data == "history":
                        edit(chat_id, message_id,
                             "📜 <b>History</b> — choose a coin:", coin_buttons("history"))

                    elif data.startswith("history:"):
                        show_history(chat_id, message_id, data.split(":")[1])

                    elif data == "p2p":
                        show_p2p_menu(chat_id, message_id)

                    elif data.startswith("p2p_crypto:"):
                        show_p2p_fiat_menu(chat_id, message_id, data.split(":")[1])

                    elif data.startswith("p2p_rate:"):
                        _, crypto, fiat = data.split(":")
                        edit(chat_id, message_id,
                             "Fetching <b>%s/%s</b> rate..." % (crypto, fiat), None)
                        show_p2p_rate_v2(chat_id, message_id, crypto, fiat)
                        try:
                            with get_db_cursor() as c:
                                c.execute("SELECT onboarded FROM rate_submissions WHERE chat=?",
                                          (str(chat_id),))
                                ob_row = c.fetchone()
                                if not ob_row or not ob_row[0]:
                                    c.execute("INSERT INTO rate_submissions (chat, onboarded, p2p_used) "
                                              "VALUES (?,1,1) ON CONFLICT(chat) DO UPDATE SET "
                                              "onboarded=1, p2p_used=1", (str(chat_id),))
                                    time.sleep(0.5)
                                    send(chat_id,
                                         "💡 <b>Did you know?</b>\n\n"
                                         "Market Pulse P2P rates are powered by real traders "
                                         "like you. If you're on Binance or Bybit right now, "
                                         "tap below to share what you see. "
                                         "The whole community benefits. 🙏",
                                         [[{"text": "📤 Submit Rate",
                                            "callback_data": "submit_rate"},
                                           {"text": "Maybe Later",
                                            "callback_data": "main_menu"}]])
                        except Exception as e:
                            print("[P2P RATE ONBOARDING ERROR] %s" % e)

                    elif data == "status":
                        show_status(chat_id, message_id)

                    elif data == "watchlist":
                        show_watchlist_menu(chat_id, message_id)

                    elif data == "wl_prices":
                        show_watchlist_prices(chat_id, message_id)

                    elif data.startswith("wl_add_page:"):
                        pg = int(data.split(":")[1])
                        edit(chat_id, message_id,
                             "⭐ <b>Add to Watchlist</b> — choose a coin:",
                             coin_buttons("wl_add", pg, extra_back="watchlist"))

                    elif data.startswith("wl_add:"):
                        coin = data.split(":")[1]
                        added = wl_add_coin(chat_id, coin)
                        msg = "✅ <b>%s</b> added to watchlist!" % coin if added \
                              else "ℹ️ <b>%s</b> is already in your watchlist." % coin
                        edit(chat_id, message_id, msg,
                             [[{"text": "⭐ Watchlist", "callback_data": "watchlist"},
                               {"text": "➕ Add More", "callback_data": "wl_add_page:0"},
                               {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])

                    elif data == "wl_remove":
                        show_wl_remove_menu(chat_id, message_id)

                    elif data.startswith("wl_del:"):
                        coin = data.split(":")[1]
                        wl_remove_coin(chat_id, coin)
                        edit(chat_id, message_id,
                             "🗑 <b>%s</b> removed from watchlist." % coin,
                             [[{"text": "⭐ Watchlist", "callback_data": "watchlist"},
                               {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])

                    elif data == "fear_greed":
                        show_fear_greed(chat_id, message_id)

                    elif data == "news":
                        show_news(chat_id, message_id)

                    elif data == "gainers":
                        show_gainers(chat_id, message_id)

                    elif data == "losers":
                        show_losers(chat_id, message_id)

                    elif data == "portfolio":
                        clear_state(chat_id)
                        show_portfolio(chat_id, message_id)

                    elif data == "port_add":
                        edit(chat_id, message_id,
                             "💼 <b>Add Asset</b> — choose a coin:",
                             coin_buttons("port_coin", extra_back="portfolio"))

                    elif data.startswith("port_coin:"):
                        coin = data.split(":")[1]
                        handle_port_coin_selected(chat_id, message_id, coin)

                    elif data == "port_remove":
                        show_port_remove(chat_id, message_id)

                    elif data.startswith("port_del:"):
                        pid = int(data.split(":")[1])
                        try:
                            with get_db_cursor() as c:
                                c.execute("DELETE FROM portfolio WHERE id=? AND chat=?",
                                          (pid, str(chat_id)))
                        except Exception:
                            pass
                        edit(chat_id, message_id, "🗑 Position removed.",
                             [[{"text": "💼 Portfolio", "callback_data": "portfolio"},
                               {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])

                    elif data == "port_export":
                        export_portfolio_csv(chat_id)

                    elif data == "alerts":
                        clear_state(chat_id)
                        edit(chat_id, message_id,
                             "🚨 <b>Alerts</b> — choose a coin to watch:",
                             coin_buttons("alert_coin"))

                    elif data == "my_alerts":
                        show_my_alerts(chat_id, message_id)

                    elif data.startswith("alert_coin:"):
                        coin = data.split(":")[1]
                        clear_state(chat_id)
                        edit(chat_id, message_id,
                             "🚨 <b>Alert — %s</b>\n\nChoose condition:" % coin,
                             cond_buttons(coin))

                    elif data.startswith("alert_cond:"):
                        _, coin, condition = data.split(":")
                        set_alert_price(chat_id, message_id, coin, condition)

                    elif data.startswith("alert_custom:"):
                        _, coin, condition = data.split(":")
                        prompt_custom_alert_price(chat_id, message_id, coin, condition)

                    elif data.startswith("alert_set:"):
                        parts = data.split(":")
                        coin = parts[1]
                        condition = parts[2]
                        target = float(parts[3])
                        save_alert(chat_id, coin, condition, target)
                        labels = {"above": "📈 Above", "below": "📉 Below",
                                  "exact": "🎯 Exact", "pct_up": "📊 % Rise",
                                  "pct_down": "📊 % Drop"}
                        tgt_str = "%.2f%%" % target if "pct" in condition else format_price(target)
                        edit(chat_id, message_id,
                             "✅ <b>Alert saved!</b>\n\n"
                             "  Coin      : <b>%s</b>\n"
                             "  Condition : %s\n"
                             "  Target    : <b>%s</b>\n\n"
                             "You'll be notified when triggered." % (coin, labels[condition], tgt_str),
                             [[{"text": "➕ Add Another", "callback_data": "alerts"},
                               {"text": "📋 My Alerts", "callback_data": "my_alerts"},
                               {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])

                    elif data.startswith("alert_del:"):
                        aid = int(data.split(":")[1])
                        try:
                            with get_db_cursor() as c:
                                c.execute("UPDATE alerts SET active=0 WHERE id=? AND chat=?",
                                          (aid, str(chat_id)))
                        except Exception:
                            pass
                        show_my_alerts(chat_id, message_id)

                    elif data == "ask_ai":
                        clear_state(chat_id)
                        show_ask_ai_prompt(chat_id, message_id)

                    elif data == "convert":
                        clear_state(chat_id)
                        show_convert_prompt(chat_id, message_id)

                    elif data == "coin_search":
                        clear_state(chat_id)
                        show_coin_search(chat_id, message_id)

                    elif data == "dominance":
                        show_dominance(chat_id, message_id)

                    elif data == "referral":
                        show_referral(chat_id, message_id)

                    elif data == "p2p_alerts":
                        show_p2p_alerts_menu(chat_id, message_id)

                    elif data == "p2p_alert_add":
                        show_p2p_alert_new(chat_id, message_id)

                    elif data == "p2p_alert_remove":
                        remove_p2p_alert_menu(chat_id, message_id)

                    elif data.startswith("p2p_alc:"):
                        show_p2p_alert_fiat(chat_id, message_id, data.split(":")[1])

                    elif data.startswith("p2p_alf:"):
                        _, crypto, fiat = data.split(":")
                        show_p2p_alert_cond(chat_id, message_id, crypto, fiat)

                    elif data.startswith("p2p_alcd:"):
                        _, crypto, fiat, condition = data.split(":")
                        prompt_p2p_alert_target(chat_id, message_id, crypto, fiat, condition)

                    elif data.startswith("p2p_aldel:"):
                        aid = int(data.split(":")[1])
                        try:
                            with get_db_cursor() as c:
                                c.execute("UPDATE p2p_alerts SET active=0 WHERE id=? AND chat=?",
                                          (aid, str(chat_id)))
                        except Exception:
                            pass
                        show_p2p_alerts_menu(chat_id, message_id)

                    elif data == "port_chart":
                        show_portfolio_chart(chat_id, message_id)

                    elif data == "help":
                        show_help(chat_id, message_id)

                    elif data.startswith("help_"):
                        show_help_section(chat_id, message_id, data[5:])

                    elif data == "upgrade":
                        show_upgrade(chat_id, message_id)

                    elif data == "submit_rate":
                        show_submit_rate_menu(chat_id, message_id)

                    elif data.startswith("submit_rate_crypto:"):
                        show_submit_rate_fiat(chat_id, message_id, data.split(":")[1])

                    elif data.startswith("submit_rate_fiat:"):
                        _, crypto, fiat = data.split(":")
                        show_submit_rate_exchange(chat_id, message_id, crypto, fiat)

                    elif data.startswith("submit_rate_ex:"):
                        _, crypto, fiat, exchange = data.split(":")
                        prompt_submit_rate_values(chat_id, message_id, crypto, fiat, exchange)

                    elif data == "arbitrage":
                        show_arbitrage(chat_id, message_id)

                    elif data == "create_alert":
                        clear_state(chat_id)
                        edit(chat_id, message_id,
                             "🚨 <b>Create Alert</b> — choose a coin:",
                             coin_buttons("alert_coin"))

                    elif data == "funding":
                        show_funding_rates(chat_id, message_id)

                    elif data == "liquidations":
                        show_liquidations(chat_id, message_id)

                    elif data == "orderbook":
                        show_order_book(chat_id, message_id)

                    elif data == "trade_setup":
                        show_trade_setup_menu(chat_id, message_id)

                    elif data.startswith("setup_coin:"):
                        show_trade_setup(chat_id, message_id, data.split(":")[1])

                    elif data.startswith("page:"):
                        _, action, pg = data.split(":")
                        headers = {
                            "chart": "📊 <b>Charts</b> — choose a coin:",
                            "source": "📡 <b>Sources</b> — choose a coin:",
                            "history": "📜 <b>History</b> — choose a coin:",
                            "alert_coin": "🚨 <b>Alerts</b> — choose a coin:",
                            "port_coin": "💼 <b>Add Asset</b> — choose a coin:",
                            "wl_add": "⭐ <b>Add to Watchlist</b> — choose a coin:",
                        }
                        back_map = {
                            "wl_add": "watchlist",
                            "port_coin": "portfolio",
                        }
                        edit(chat_id, message_id,
                             headers.get(action, "Choose a coin:"),
                             coin_buttons(action, int(pg),
                                          extra_back=back_map.get(action, "main_menu")))

            time.sleep(2)

        except Exception as e:
            print("[ERROR] %s" % e)
            time.sleep(10)


if __name__ == "__main__":
    run()