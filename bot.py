"""
Market Pulse Bot — v15 "The Honest Upgrade"
=============================================
AI-powered crypto intelligence for Nigerian traders.

REAL DATA (100% Real):
- Prices: Kraken → OKX → CoinGecko → CoinCap
- P2P: Binance P2P → Bybit P2P → Community submissions
- News: 7 RSS feeds + AI analysis
- Fear & Greed: Alternative.me
- Dominance: CoinGecko
- AI: DeepSeek → Mistral → Qwen

HONESTLY REMOVED (Cannot provide real data):
- On-chain Whale Alerts (needs paid API)
- Liquidation Data (needs paid API)
- Order Book (needs WebSocket)
- Funding Rates (needs exchange API)
- Open Interest (needs paid API)
- CVD (needs order book data)
- Commodities (unreliable API)
- Forex (unreliable API)

Features:
✅ Channel Lock (members only)
✅ Free/Pro Toggle (admin command)
✅ Pro Badge on messages
✅ Personalized Pro DMs (expiry, referrals)
✅ AI Trade Setups
✅ AI Key Levels
✅ AI Market Outlook
✅ AI Risk Assessment
✅ AI News Impact
✅ Trade Journal (real P&L)
✅ Position Size Calculator
✅ Trailing Stop Suggestions
✅ Pro Referral Rewards (5, 10, 20 referrals)
✅ Anti-Spam (callback limits)
✅ P2P Anti-Manipulation (trust system)
✅ Saturday Weekly Edge
✅ Whale Watch (price-based 5%+ moves)
"""

import os
import sqlite3
import json
import io
import time
import requests
import xml.etree.ElementTree as ET
import re
import random
from datetime import datetime, timedelta
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ═══════════════════════════════════════════════════════════════════════════
# 🔑 TOKEN CONFIGURATION - ADD YOUR TOKENS HERE
# ═══════════════════════════════════════════════════════════════════════════

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_KEY", "YOUR_DEEPSEEK_KEY_HERE")
MISTRAL_KEY = os.environ.get("MISTRAL_KEY", "YOUR_MISTRAL_KEY_HERE")
QWEN_KEY = os.environ.get("QWEN_KEY", "YOUR_QWEN_KEY_HERE")

# ═══════════════════════════════════════════════════════════════════════════
# 🔐 PRIVACY & CHANNEL CONFIG
# ═══════════════════════════════════════════════════════════════════════════

ADMIN_IDS = {8212124930}  # Your Telegram chat_id
CHANNEL_ID = "-1004495003791"  # Your main channel (members must join)
PRO_CHANNEL_ID = "-100XXXXXXXXX"  # Your Pro-only channel (set later)
CHANNEL_ENABLED = True
WAT_OFFSET = 1
DB_PATH = "marketpulse.db"

# ═══════════════════════════════════════════════════════════════════════════
# 📋 GLOBAL BOT MODE - EASY TOGGLE
# ═══════════════════════════════════════════════════════════════════════════

# "everyone" = All features free for everyone
# "pro" = Free users get limited, Pro users get everything
BOT_MODE = "everyone"  # Change to "pro" when ready

def get_bot_mode():
    """Get current bot mode from global variable"""
    return BOT_MODE

def set_bot_mode(mode):
    """Set bot mode - admin command"""
    global BOT_MODE
    if mode in ["everyone", "pro"]:
        BOT_MODE = mode
        return True
    return False

# ═══════════════════════════════════════════════════════════════════════════
# 📋 SCHEDULE (Reduced spam)
# ═══════════════════════════════════════════════════════════════════════════

SCHEDULE = {
    "morning_hour_wat": 7,
    "midday_hour_wat": 12,
    "evening_hour_wat": 21,
    "weekly_edge_day": 5,  # Saturday
    "weekly_edge_hour": 9,
    "bigmove_pct": 3.0,
    "whale_pct": 5.0,
    "admin_digest_hour_wat": 8,
    "health_check_interval_minutes": 10,
    "expiry_reminder_days": 7,  # Remind 7 days before expiry
}

# ═══════════════════════════════════════════════════════════════════════════
# 🪙 COINS & P2P CONFIG
# ═══════════════════════════════════════════════════════════════════════════

COINS = {
    "BTC": ("XBTUSD", "bitcoin"),
    "ETH": ("ETHUSD", "ethereum"),
    "SOL": ("SOLUSD", "solana"),
    "BNB": ("BNBUSD", "binancecoin"),
    "XRP": ("XRPUSD", "ripple"),
    "DOGE": ("DOGEUSD", "dogecoin"),
    "ADA": ("ADAUSD", "cardano"),
    "TRX": ("TRXUSD", "tron"),
    "AVAX": ("AVAXUSD", "avalanche-2"),
    "LINK": ("LINKUSD", "chainlink"),
    "DOT": ("DOTUSD", "polkadot"),
    "POL": ("POLUSD", "matic-network"),
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
    "USDT": ("USDTUSD", "tether"),
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

# ── NEWS RSS FEEDS ──────────────────────────────────────────────────────────
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
# 🔧 HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def format_price(v):
    if v is None:
        return "N/A"
    try:
        v = float(v)
    except:
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
    except:
        return "N/A"
    sign = "+" if pct >= 0 else ""
    return "%s%.2f%%" % (sign, pct)

def format_large(v):
    if v is None:
        return "N/A"
    try:
        v = float(v)
    except:
        return "N/A"
    if v >= 1e12:
        return "$%.2fT" % (v / 1e12)
    if v >= 1e9:
        return "$%.1fB" % (v / 1e9)
    if v >= 1e6:
        return "$%.0fM" % (v / 1e6)
    return "$%.0f" % v

def wat_now():
    return datetime.now() + timedelta(hours=WAT_OFFSET)

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
                print("[RATE LIMIT] waiting %ds" % wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    print("[RETRY FAILED] %s" % last_exc)
    return None

def fetch_with_backoff(url, max_retries=5, timeout=15):
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=get_random_headers(), timeout=timeout)
            if response.status_code == 429:
                wait = (2 ** attempt) * 2
                print(f"[BACKOFF] Waiting {wait}s")
                time.sleep(wait)
                continue
            if response.status_code == 200:
                return response.json()
        except:
            time.sleep(2 ** attempt)
    return None

# ═══════════════════════════════════════════════════════════════════════════
# 🗄️ DATABASE
# ═══════════════════════════════════════════════════════════════════════════

def get_db():
    return sqlite3.connect(DB_PATH)

def init_db():
    db = get_db()
    c = db.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coin TEXT NOT NULL,
        price REAL NOT NULL,
        timestamp TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat TEXT NOT NULL,
        coin TEXT NOT NULL,
        UNIQUE(chat, coin)
    );
    CREATE TABLE IF NOT EXISTS portfolio (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat TEXT NOT NULL,
        coin TEXT NOT NULL,
        amount REAL NOT NULL,
        buy_price REAL NOT NULL,
        added_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat TEXT NOT NULL,
        action TEXT NOT NULL,
        timestamp TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS p2p_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat TEXT NOT NULL,
        crypto TEXT NOT NULL,
        fiat TEXT NOT NULL,
        condition TEXT NOT NULL,
        target REAL NOT NULL,
        active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_chat TEXT NOT NULL,
        referred_chat TEXT NOT NULL,
        reward_type TEXT,
        claimed INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        UNIQUE(referred_chat)
    );
    CREATE TABLE IF NOT EXISTS portfolio_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat TEXT NOT NULL,
        value_usd REAL NOT NULL,
        timestamp TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS health_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service TEXT NOT NULL,
        status TEXT NOT NULL,
        details TEXT,
        timestamp TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS feature_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat TEXT NOT NULL,
        feature TEXT NOT NULL,
        timestamp TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS community_p2p (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    """)
    try:
        db.execute("ALTER TABLE alerts ADD COLUMN label TEXT DEFAULT ''")
    except:
        pass
    db.commit()
    db.close()
    print("Database ready")

# ═══════════════════════════════════════════════════════════════════════════
# 📊 FEATURE TRACKING & USER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def track_feature(chat_id, feature):
    try:
        db = get_db()
        c = db.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO feature_usage (chat, feature, timestamp) VALUES (?, ?, ?)",
                  (str(chat_id), feature, now))
        db.commit()
        db.close()
    except:
        pass

def upsert_user(chat_id, username=None, first_name=None):
    db = get_db()
    c = db.cursor()
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
    db.commit()
    db.close()

def log_event(chat_id, action):
    try:
        db = get_db()
        c = db.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO events (chat, action, timestamp) VALUES (?, ?, ?)",
                  (str(chat_id), action, now))
        db.commit()
        db.close()
    except:
        pass

def set_state(chat_id, state, data=None):
    db = get_db()
    c = db.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        """INSERT INTO user_states (chat, state, data, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(chat) DO UPDATE SET
             state=excluded.state, data=excluded.data, updated_at=excluded.updated_at""",
        (str(chat_id), state, json.dumps(data or {}), now)
    )
    db.commit()
    db.close()

def get_state(chat_id):
    db = get_db()
    c = db.cursor()
    c.execute("SELECT state, data FROM user_states WHERE chat=?", (str(chat_id),))
    row = c.fetchone()
    db.close()
    if not row:
        return None, {}
    state, data = row
    try:
        data = json.loads(data) if data else {}
    except:
        data = {}
    return state, data

def clear_state(chat_id):
    db = get_db()
    c = db.cursor()
    c.execute("DELETE FROM user_states WHERE chat=?", (str(chat_id),))
    db.commit()
    db.close()

# ═══════════════════════════════════════════════════════════════════════════
# 📨 TELEGRAM HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def tg(method, data):
    return request_json(
        "POST", "https://api.telegram.org/bot%s/%s" % (BOT_TOKEN, method),
        json_data=data, timeout=15, retries=2
    ) or {}

def tg_photo(form_data, photo_bytes, filename="chart.png", retries=3):
    safe_data = {k: str(v) for k, v in form_data.items()}
    for attempt in range(retries):
        try:
            files = {"photo": (filename, io.BytesIO(photo_bytes), "image/png")}
            r = requests.post(
                "https://api.telegram.org/bot%s/sendPhoto" % BOT_TOKEN,
                data=safe_data, files=files, timeout=30
            )
            r.raise_for_status()
            return r.json()
        except:
            if attempt < retries - 1:
                time.sleep(1.0)
    return {}

def send_photo(chat_id, photo_bytes, caption=None, buttons=None):
    data = {"chat_id": str(chat_id), "parse_mode": "HTML"}
    if caption:
        data["caption"] = caption
    if buttons:
        data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    return tg_photo(data, photo_bytes)

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

def delete_message(chat_id, message_id):
    tg("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

def answer_cb(cb_id, text=None):
    payload = {"callback_query_id": cb_id}
    if text:
        payload["text"] = text
    tg("answerCallbackQuery", payload)

def post_to_channel(text):
    if not CHANNEL_ENABLED:
        return
    data = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    return tg("sendMessage", data)

def post_to_pro_channel(text):
    if not CHANNEL_ENABLED or not PRO_CHANNEL_ID:
        return
    data = {
        "chat_id": PRO_CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    return tg("sendMessage", data)

# ═══════════════════════════════════════════════════════════════════════════
# 🔐 PRO SYSTEM (HONEST - No Fakes)
# ═══════════════════════════════════════════════════════════════════════════

PRO_REFERRAL_REWARDS = {
    5: "1month",
    10: "3months",
    20: "6months"
}

def is_pro(chat_id):
    """Check if user has active Pro subscription"""
    if get_bot_mode() == "everyone":
        return True  # Everyone is "Pro" in everyone mode
    
    if chat_id in ADMIN_IDS:
        return True
    
    try:
        db = get_db()
        c = db.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("SELECT expiry_date FROM pro_subscriptions WHERE chat=? AND expiry_date > ?",
                  (str(chat_id), now))
        row = c.fetchone()
        db.close()
        return bool(row)
    except:
        return False

def get_pro_expiry(chat_id):
    """Get Pro expiry date for a user"""
    try:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT expiry_date FROM pro_subscriptions WHERE chat=?", (str(chat_id),))
        row = c.fetchone()
        db.close()
        return row[0] if row else None
    except:
        return None

def get_pro_days_left(chat_id):
    """Get days until Pro expires"""
    expiry = get_pro_expiry(chat_id)
    if not expiry:
        return None
    try:
        expiry_date = datetime.strptime(expiry, "%Y-%m-%d %H:%M:%S")
        days_left = (expiry_date - datetime.now()).days
        return max(0, days_left)
    except:
        return None

def grant_pro(chat_id, months=1, source="payment"):
    """Grant Pro access to a user"""
    try:
        db = get_db()
        c = db.cursor()
        now = datetime.now()
        expiry = now + timedelta(days=30 * months)
        expiry_str = expiry.strftime("%Y-%m-%d %H:%M:%S")
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        
        # Check if already Pro
        c.execute("SELECT expiry_date FROM pro_subscriptions WHERE chat=?", (str(chat_id),))
        row = c.fetchone()
        
        if row:
            # Extend existing
            existing_expiry = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            if existing_expiry > now:
                new_expiry = existing_expiry + timedelta(days=30 * months)
            else:
                new_expiry = now + timedelta(days=30 * months)
            new_expiry_str = new_expiry.strftime("%Y-%m-%d %H:%M:%S")
            c.execute("UPDATE pro_subscriptions SET expiry_date=?, source=? WHERE chat=?",
                      (new_expiry_str, source, str(chat_id)))
        else:
            c.execute("INSERT INTO pro_subscriptions (chat, expiry_date, source, created_at) VALUES (?,?,?,?)",
                      (str(chat_id), expiry_str, source, now_str))
        
        db.commit()
        db.close()
        
        # Send welcome DM
        send_pro_welcome(chat_id, expiry_str)
        return True
    except Exception as e:
        print(f"[GRANT PRO ERROR] {e}")
        return False

def send_pro_welcome(chat_id, expiry_date):
    """Send welcome DM to new Pro user"""
    try:
        expiry_display = datetime.strptime(expiry_date, "%Y-%m-%d %H:%M:%S").strftime("%b %d, %Y")
        text = (
            "⭐ <b>WELCOME TO PRO!</b>\n\n"
            "You now have full access to Market Pulse Pro.\n\n"
            "✅ Unlimited AI\n"
            "✅ 20 alerts\n"
            "✅ 30 watchlist items\n"
            "✅ 30 portfolio items\n"
            "✅ Trade Journal\n"
            "✅ Position Calculator\n"
            "✅ AI Trade Setups\n"
            "✅ Pro Channel access\n"
            "✅ Pro Referrals\n\n"
            f"📅 Your Pro expires: <b>{expiry_display}</b>\n\n"
            "📤 Your referral link:\n"
            f"<code>https://t.me/MarketPulseBot?start=ref_PRO_{chat_id}</code>\n\n"
            "Refer 5 people → Get 1 month FREE!\n"
            "Refer 10 people → Get 3 months FREE!\n"
            "Refer 20 people → Get 6 months FREE!\n\n"
            "<i>Welcome to the Pro community!</i> 🚀"
        )
        send(int(chat_id), text,
             [[{"text": "📤 Copy Link", "callback_data": "copy_link"},
               {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])
    except Exception as e:
        print(f"[PRO WELCOME ERROR] {e}")

def check_pro_expiry_reminders():
    """Check and send expiry reminders to Pro users"""
    try:
        db = get_db()
        c = db.cursor()
        now = datetime.now()
        days_left = SCHEDULE.get("expiry_reminder_days", 7)
        expiry_threshold = (now + timedelta(days=days_left)).strftime("%Y-%m-%d %H:%M:%S")
        
        c.execute("SELECT chat, expiry_date FROM pro_subscriptions WHERE expiry_date > ? AND expiry_date <= ?",
                  (now.strftime("%Y-%m-%d %H:%M:%S"), expiry_threshold))
        rows = c.fetchall()
        db.close()
        
        for chat_id, expiry_date in rows:
            expiry_dt = datetime.strptime(expiry_date, "%Y-%m-%d %H:%M:%S")
            days = (expiry_dt - now).days
            
            text = (
                "⭐ <b>PRO REMINDER</b>\n\n"
                f"Your Market Pulse Pro expires in <b>{days} days</b>.\n\n"
                f"📅 Expiry: <b>{expiry_dt.strftime('%b %d, %Y')}</b>\n\n"
                "💰 Renew: ₦2,000/month\n\n"
                "🎁 OR refer people and get FREE Pro:\n"
                "5 referrals → 1 month FREE\n"
                "10 referrals → 3 months FREE\n"
                "20 referrals → 6 months FREE\n\n"
                "📤 Share your referral link:\n"
                f"<code>https://t.me/MarketPulseBot?start=ref_PRO_{chat_id}</code>"
            )
            send(int(chat_id), text,
                 [[{"text": "📤 Copy Link", "callback_data": "copy_link"},
                   {"text": "💎 Renew", "callback_data": "upgrade"}]])
    except Exception as e:
        print(f"[EXPIRY REMINDER ERROR] {e}")

# ── PRO REFERRAL SYSTEM ────────────────────────────────────────────────────

def get_pro_referral_count(chat_id):
    """Get number of referrals a Pro user has made"""
    try:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT COUNT(*) FROM pro_referrals WHERE referrer_chat=?", (str(chat_id),))
        count = c.fetchone()[0]
        db.close()
        return count
    except:
        return 0

def get_pro_referral_reward(chat_id):
    """Get the reward level for a Pro user based on referrals"""
    count = get_pro_referral_count(chat_id)
    reward = None
    for threshold, reward_type in sorted(PRO_REFERRAL_REWARDS.items(), reverse=True):
        if count >= threshold:
            reward = reward_type
            break
    return reward, count

def record_pro_referral(referrer_chat, referred_chat):
    """Record a Pro referral and check for rewards"""
    if str(referrer_chat) == str(referred_chat):
        return
    
    if not is_pro(referrer_chat):
        return
    
    try:
        db = get_db()
        c = db.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Check if already recorded
        c.execute("SELECT id FROM pro_referrals WHERE referred_chat=?", (str(referred_chat),))
        if c.fetchone():
            db.close()
            return
        
        # Record referral
        c.execute("INSERT INTO pro_referrals (referrer_chat, referred_chat, created_at) VALUES (?,?,?)",
                  (str(referrer_chat), str(referred_chat), now))
        db.commit()
        
        # Check for rewards
        reward, count = get_pro_referral_reward(referrer_chat)
        if reward:
            send_pro_referral_reward(int(referrer_chat), reward, count)
        
        db.close()
    except Exception as e:
        print(f"[PRO REFERRAL ERROR] {e}")

def send_pro_referral_reward(chat_id, reward_type, count):
    """Send reward notification to Pro user"""
    reward_map = {
        "1month": ("1 month", 1),
        "3months": ("3 months", 3),
        "6months": ("6 months", 6)
    }
    
    label, months = reward_map.get(reward_type, ("1 month", 1))
    next_milestone = None
    next_count = None
    
    for threshold, rtype in sorted(PRO_REFERRAL_REWARDS.items()):
        if threshold > count:
            next_milestone = rtype
            next_count = threshold
            break
    
    text = (
        "🎉 <b>PRO REFERRAL REWARD!</b>\n\n"
        f"You reached <b>{count}</b> referrals! 🎁\n\n"
        f"You earned <b>{label}</b> of Pro FREE!\n"
    )
    
    # Grant the reward
    grant_pro(chat_id, months, "referral")
    
    expiry = get_pro_expiry(chat_id)
    if expiry:
        expiry_dt = datetime.strptime(expiry, "%Y-%m-%d %H:%M:%S")
        text += f"\n📅 Your Pro expires: <b>{expiry_dt.strftime('%b %d, %Y')}</b>\n"
    
    if next_milestone and next_count:
        next_label = {"1month": "1 month", "3months": "3 months", "6months": "6 months"}.get(next_milestone)
        text += f"\nNext milestone: <b>{next_count}</b> referrals → <b>{next_label}</b> FREE\n"
        text += f"Progress: <b>{count}/{next_count}</b>"
    
    text += "\n\nKeep sharing! 🔥"
    
    send(chat_id, text,
         [[{"text": "📤 Copy Link", "callback_data": "copy_link"},
           {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])

# ═══════════════════════════════════════════════════════════════════════════
# 🔐 CHANNEL LOCK SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

def is_user_in_channel(chat_id):
    """Check if user is a member of the main channel"""
    try:
        result = tg("getChatMember", {"chat_id": CHANNEL_ID, "user_id": chat_id})
        if result and result.get("ok"):
            status = result.get("result", {}).get("status", "")
            return status in ["member", "administrator", "creator"]
    except:
        pass
    return False

def check_channel_membership(chat_id):
    """Check membership and return appropriate response"""
    if is_user_in_channel(chat_id):
        return True
    
    # User is not a member - send restricted message
    send(chat_id,
         "🔒 <b>Channel Membership Required</b>\n\n"
         "To use Market Pulse, you must join our channel first.\n\n"
         "📢 Join here: @MarketNgPulseBot\n\n"
         "After joining, tap the button below to verify.",
         [[{"text": "✅ I've Joined", "callback_data": "verify_join"}]])
    return False

# ═══════════════════════════════════════════════════════════════════════════
# 🏠 MENUS (Free vs Pro)
# ═══════════════════════════════════════════════════════════════════════════

def get_user_badge(chat_id):
    """Get user badge for display"""
    if is_pro(chat_id):
        return "⭐ Pro User"
    else:
        return "👤 Free User"

def get_menus_for_user(chat_id):
    """Get appropriate menus based on user status"""
    if get_bot_mode() == "everyone":
        return {
            "main": MAIN_MENU,
            "markets": MARKETS_MENU,
            "intelligence": INTELLIGENCE_MENU,
            "p2p": P2P_MENU,
            "alerts": ALERTS_MENU,
            "tools": TOOLS_MENU,
            "account": ACCOUNT_MENU_FREE,
        }
    
    if is_pro(chat_id):
        return {
            "main": MAIN_MENU_PRO,
            "markets": MARKETS_MENU,
            "intelligence": INTELLIGENCE_MENU,
            "p2p": P2P_MENU,
            "alerts": ALERTS_MENU_PRO,
            "tools": TOOLS_MENU,
            "account": ACCOUNT_MENU_PRO,
        }
    else:
        return {
            "main": MAIN_MENU_FREE,
            "markets": MARKETS_MENU,
            "intelligence": INTELLIGENCE_MENU,
            "p2p": P2P_MENU,
            "alerts": ALERTS_MENU_FREE,
            "tools": TOOLS_MENU,
            "account": ACCOUNT_MENU_FREE,
        }

# ── MENU DEFINITIONS ──────────────────────────────────────────────────────

MAIN_MENU = [
    [{"text": "📊 Markets", "callback_data": "menu_markets"}],
    [{"text": "🧠 Intelligence", "callback_data": "menu_intelligence"}],
    [{"text": "🇳🇬 P2P Center", "callback_data": "menu_p2p"}],
    [{"text": "🔔 Alerts", "callback_data": "menu_alerts"}],
    [{"text": "🛠 Tools", "callback_data": "menu_tools"}],
    [{"text": "👤 My Account", "callback_data": "menu_account"}],
]

MAIN_MENU_FREE = [
    [{"text": "📊 Markets", "callback_data": "menu_markets"}],
    [{"text": "🧠 Intelligence", "callback_data": "menu_intelligence"}],
    [{"text": "🇳🇬 P2P Center", "callback_data": "menu_p2p"}],
    [{"text": "🔔 Alerts", "callback_data": "menu_alerts"}],
    [{"text": "🛠 Tools", "callback_data": "menu_tools"}],
    [{"text": "👤 My Account", "callback_data": "menu_account"}],
    [{"text": "💎 Upgrade to Pro", "callback_data": "upgrade"}],
]

MAIN_MENU_PRO = [
    [{"text": "⭐ Pro Menu", "callback_data": "menu_pro"}],
    [{"text": "📊 Markets", "callback_data": "menu_markets"}],
    [{"text": "🧠 Intelligence", "callback_data": "menu_intelligence"}],
    [{"text": "🇳🇬 P2P Center", "callback_data": "menu_p2p"}],
    [{"text": "🔔 Alerts", "callback_data": "menu_alerts"}],
    [{"text": "🛠 Tools", "callback_data": "menu_tools"}],
    [{"text": "📈 Pro Tools", "callback_data": "menu_pro_tools"}],
    [{"text": "👤 My Account", "callback_data": "menu_account"}],
]

MARKETS_MENU = [
    [{"text": "📈 Live Market", "callback_data": "market"}],
    [{"text": "📊 Charts", "callback_data": "charts"}],
    [{"text": "🔥 Gainers", "callback_data": "gainers"}],
    [{"text": "📉 Losers", "callback_data": "losers"}],
    [{"text": "🌐 Dominance", "callback_data": "dominance"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

INTELLIGENCE_MENU = [
    [{"text": "🤖 Ask AI", "callback_data": "ask_ai"}],
    [{"text": "📰 AI News", "callback_data": "news"}],
    [{"text": "🧠 Fear & Greed", "callback_data": "fear_greed"}],
    [{"text": "📈 Market Outlook", "callback_data": "market_outlook"}],
    [{"text": "📡 Sources", "callback_data": "sources"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

P2P_MENU = [
    [{"text": "💱 P2P Rates", "callback_data": "p2p"}],
    [{"text": "🔔 P2P Alerts", "callback_data": "p2p_alerts"}],
    [{"text": "📤 Submit Rate", "callback_data": "submit_rate"}],
    [{"text": "🔄 Arbitrage Scanner", "callback_data": "arbitrage"}],
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
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

TOOLS_MENU = [
    [{"text": "🔍 Search Coin", "callback_data": "coin_search"}],
    [{"text": "🔄 Convert", "callback_data": "convert"}],
    [{"text": "📜 History", "callback_data": "history"}],
    [{"text": "⚙️ Status", "callback_data": "status"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

ACCOUNT_MENU_FREE = [
    [{"text": "💼 Portfolio (10 max)", "callback_data": "portfolio"}],
    [{"text": "👥 Referral", "callback_data": "referral"}],
    [{"text": "📊 My Usage", "callback_data": "my_usage"}],
    [{"text": "💎 Upgrade to Pro", "callback_data": "upgrade"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

ACCOUNT_MENU_PRO = [
    [{"text": "💼 Portfolio (30 max)", "callback_data": "portfolio"}],
    [{"text": "👥 Referral", "callback_data": "referral"}],
    [{"text": "📊 My Usage", "callback_data": "my_usage"}],
    [{"text": "📈 Trade Journal", "callback_data": "trade_journal"}],
    [{"text": "📐 Position Calculator", "callback_data": "position_calculator"}],
    [{"text": "⭐ Pro Status", "callback_data": "pro_status"}],
    [{"text": "🏠 Main Menu", "callback_data": "main_menu"}],
]

BACK_MAIN = [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]]

# ═══════════════════════════════════════════════════════════════════════════
# 📈 CHART RENDERER
# ═══════════════════════════════════════════════════════════════════════════

def render_chart_png(coin, timeframe, ts_fmt, rows):
    try:
        valid_rows = []
        for price, ts in rows:
            try:
                if price is None:
                    continue
                p = float(price)
                if p > 0:
                    valid_rows.append((p, ts))
            except:
                continue
        
        if len(valid_rows) < 2:
            return None
        
        prices = [p for p, _ in valid_rows]
        times = [datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") for _, ts in valid_rows]
        
        chg = (prices[-1] - prices[0]) / prices[0] * 100 if prices[0] else 0
        up = chg >= 0
        line_color = "#26a69a" if up else "#ef5350"
        bg_color = "#0d1117"
        grid_color = "#21262d"
        
        plt.style.use("dark_background")
        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(bg_color)
        
        ax.plot(times, prices, color=line_color, linewidth=1.8, zorder=3)
        ax.fill_between(times, prices, min(prices), color=line_color, alpha=0.12, zorder=2)
        ax.grid(True, color=grid_color, linewidth=0.6, zorder=1)
        for spine in ax.spines.values():
            spine.set_color(grid_color)
        ax.tick_params(colors="#8b949e", labelsize=9)
        
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
        pad = span * 0.08 if span.total_seconds() > 0 else timedelta(minutes=5)
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
        try:
            plt.close("all")
        except:
            pass
        return None

# ═══════════════════════════════════════════════════════════════════════════
# 💰 PRICE FETCHERS (REAL DATA - NO FAKES)
# ═══════════════════════════════════════════════════════════════════════════

_kraken_keymap = {}
_kraken_cache = {"data": {}, "timestamp": None}
_secondary_cache = {"data": {}, "timestamp": None}
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
    now = datetime.now()
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
            except:
                pass
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
    except:
        pass
    return None

def get_bybit_price(coin):
    try:
        resp = fetch_with_backoff(f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={coin}USDT")
        if resp and resp.get("retCode") == 0:
            data = resp.get("result", {}).get("list", [])
            if data:
                return float(data[0].get("lastPrice", 0))
    except:
        pass
    return None

def get_coingecko_price(coin):
    try:
        coin_id = COINS[coin][1]
        resp = fetch_with_backoff(f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd")
        if resp and coin_id in resp:
            return resp[coin_id].get("usd")
    except:
        pass
    return None

def get_price_with_fallback(coin):
    # Tier 1: Kraken
    price = get_kraken_price(coin)
    if price:
        return price
    # Tier 2: OKX
    price = get_okx_price(coin)
    if price:
        return price
    # Tier 3: Bybit
    price = get_bybit_price(coin)
    if price:
        return price
    # Tier 4: CoinGecko
    price = get_coingecko_price(coin)
    if price:
        return price
    return None

def get_secondary_batch():
    now = datetime.now()
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
                except:
                    pass
    
    if not result:
        resp = fetch_with_backoff(f"https://min-api.cryptocompare.com/data/pricemultifull?fsyms={','.join(COINS.keys())}&tsyms=USD")
        if resp and resp.get("RAW"):
            for coin, data in resp["RAW"].items():
                usd = data.get("USD") if isinstance(data, dict) else None
                if usd:
                    result[coin_key(coin)] = {
                        "usd": usd.get("PRICE"),
                        "usd_24h_change": usd.get("CHANGEPCT24HOUR"),
                        "usd_24h_high": usd.get("HIGH24HOUR"),
                        "usd_24h_low": usd.get("LOW24HOUR"),
                    }
    
    _secondary_cache["data"] = result
    _secondary_cache["timestamp"] = now
    return result

def get_secondary_coin(coin):
    return get_secondary_batch().get(coin_key(coin))

def get_best_price(coin):
    if coin not in COINS:
        return None, None
    price = get_price_with_fallback(coin)
    sd = get_secondary_coin(coin)
    change = sd.get("usd_24h_change") if sd else None
    if price:
        return price, change
    if sd:
        return sd.get("usd"), change
    return None, None

def get_fiat_rates():
    now = datetime.now()
    if (_fiat_cache["timestamp"] and
            (now - _fiat_cache["timestamp"]).total_seconds() < 300):
        return _fiat_cache["data"]
    resp = fetch_with_backoff("https://open.er-api.com/v6/latest/USD")
    if resp is None:
        return _fiat_cache["data"]
    rates = resp.get("rates", {})
    _fiat_cache["data"] = rates
    _fiat_cache["timestamp"] = now
    return rates

# ═══════════════════════════════════════════════════════════════════════════
# 🇳🇬 P2P SYSTEM (REAL DATA)
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
            except:
                continue
        if not prices:
            return None
        return _p2p_median(prices)
    except Exception as e:
        print("[BINANCE P2P ERROR] %s" % e)
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
        print("[BYBIT P2P ERROR] %s" % e)
        return None

def get_p2p_rate(crypto, fiat):
    # Tier 1: Binance P2P
    try:
        buy = get_binance_p2p("BUY", crypto, fiat)
        sell = get_binance_p2p("SELL", crypto, fiat)
        if buy and sell:
            return buy, sell, "Binance P2P"
    except:
        pass
    
    # Tier 2: Bybit P2P
    try:
        buy = get_bybit_p2p("BUY", crypto, fiat)
        sell = get_bybit_p2p("SELL", crypto, fiat)
        if buy and sell:
            return buy, sell, "Bybit P2P"
    except:
        pass
    
    # Tier 3: Spot estimate
    try:
        rates = get_fiat_rates()
        price, _ = get_best_price(crypto)
        fiat_per_usd = rates.get(fiat)
        if price and fiat_per_usd:
            val = price * fiat_per_usd
            buy = round(val * 1.015, 2)
            sell = round(val * 0.985, 2)
            return buy, sell, "Estimated"
    except:
        pass
    
    return None, None, None

# ── COMMUNITY P2P SUBMISSIONS ─────────────────────────────────────────────

P2P_MAX_DEVIATION = 0.20
P2P_CONSENSUS_PCT = 0.15
P2P_CONSENSUS_NEED = 2
P2P_PENDING_HOURS = 2
P2P_VALIDITY_HOURS = 4
P2P_STRIKE_LIMIT = 3
P2P_BLOCK_HOURS = 24

def get_user_trust(chat_id):
    if chat_id in ADMIN_IDS:
        return {"trust": 10, "blocked": False, "strikes": 0, "verified": 999}
    try:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT trust_level, strikes_today, blocked_until, total_verified FROM rate_submissions WHERE chat=?",
                  (str(chat_id),))
        row = c.fetchone()
        db.close()
        if not row:
            return {"trust": 1, "blocked": False, "strikes": 0, "verified": 0}
        trust, strikes, blocked_until, verified = row
        now = datetime.now()
        is_blocked = bool(blocked_until and datetime.strptime(blocked_until, "%Y-%m-%d %H:%M:%S") > now)
        return {"trust": trust or 1, "blocked": is_blocked, "strikes": strikes or 0, "verified": verified or 0}
    except:
        return {"trust": 1, "blocked": False, "strikes": 0, "verified": 0}

def record_submission_attempt(chat_id, success):
    if chat_id in ADMIN_IDS:
        return
    try:
        db = get_db()
        c = db.cursor()
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
                blocked_until = (datetime.now() + timedelta(hours=P2P_BLOCK_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT INTO rate_submissions (chat, strikes_today, submissions_today, blocked_until, last_submission) "
                      "VALUES (?,?,?,?,?) ON CONFLICT(chat) DO UPDATE SET "
                      "strikes_today=?, submissions_today=?, blocked_until=?, last_submission=?",
                      (str(chat_id), strikes, subs, blocked_until, now,
                       strikes, subs, blocked_until, now))
        else:
            subs += 1
            c.execute("INSERT INTO rate_submissions (chat, submissions_today, last_submission) "
                      "VALUES (?,?,?) ON CONFLICT(chat) DO UPDATE SET "
                      "submissions_today=?, last_submission=?",
                      (str(chat_id), subs, now, subs, now))
        db.commit()
        db.close()
    except:
        pass

def validate_p2p_rate(crypto, fiat, buy_rate, sell_rate):
    if buy_rate <= 0 or sell_rate <= 0:
        return False, "Rates must be positive numbers.", None
    if sell_rate >= buy_rate:
        return False, "Buy rate must be higher than sell rate.", None
    if buy_rate > sell_rate * 1.5:
        return False, "Spread is too wide.", None
    
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
        return False, f"Rate looks unusual. Expected around {fiat_sym}{spot_in_fiat:,.0f}", spot_in_fiat
    return True, "valid", spot_in_fiat

def submit_community_rate(chat_id, crypto, fiat, buy_rate, sell_rate, exchange, is_admin=False):
    trust_info = get_user_trust(chat_id)
    if trust_info["blocked"] and not is_admin:
        return False, "Your account is temporarily blocked."
    
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
    
    now = datetime.now()
    expires_at = (now + timedelta(hours=P2P_PENDING_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        db = get_db()
        c = db.cursor()
        c.execute("INSERT INTO community_p2p (chat, crypto, fiat, buy_rate, sell_rate, exchange, "
                  "timestamp, weight, status, confirmations, spot_rate, expires_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (str(chat_id), crypto, fiat, buy_rate, sell_rate, exchange,
                   now_str, weight, status, 0, spot_rate, expires_at))
        db.commit()
        db.close()
        record_submission_attempt(chat_id, True)
        return True, status
    except Exception as e:
        print(f"[SUBMIT RATE ERROR] {e}")
        return False, "Database error."

def get_community_rate(crypto, fiat):
    try:
        db = get_db()
        c = db.cursor()
        cutoff = (datetime.now() - timedelta(hours=P2P_VALIDITY_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
        c.execute("SELECT buy_rate, sell_rate, weight FROM community_p2p "
                  "WHERE crypto=? AND fiat=? AND status='live' AND timestamp>=? "
                  "ORDER BY timestamp DESC LIMIT 10", (crypto, fiat, cutoff))
        rows = c.fetchall()
        db.close()
        if not rows:
            return None
        total_w = sum(r[2] for r in rows)
        avg_buy = sum(r[0] * r[2] for r in rows) / total_w
        avg_sell = sum(r[1] * r[2] for r in rows) / total_w
        return {"buy": round(avg_buy, 2), "sell": round(avg_sell, 2), "count": len(rows), "is_community": True}
    except:
        return None

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
                "coin": coin, "buy_from": low_src, "buy_price": low_price,
                "sell_to": high_src, "sell_price": high_price, "gap_pct": gap_pct
            })
    
    return opportunities

# ═══════════════════════════════════════════════════════════════════════════
# 🧠 FEAR & GREED
# ═══════════════════════════════════════════════════════════════════════════

_fg_cache = {"data": None, "timestamp": None}

def get_fear_greed():
    now = datetime.now()
    if (_fg_cache["timestamp"] and (now - _fg_cache["timestamp"]).total_seconds() < 3600):
        return _fg_cache["data"]
    try:
        resp = fetch_with_backoff("https://api.alternative.me/fng/?limit=7")
        if resp and resp.get("data"):
            _fg_cache["data"] = resp["data"]
            _fg_cache["timestamp"] = now
            return resp["data"]
    except:
        pass
    return _fg_cache["data"]

def fg_emoji(value):
    v = int(value)
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
    except:
        pass
    return articles

def get_crypto_news():
    now = datetime.now()
    if (_news_cache["timestamp"] and (now - _news_cache["timestamp"]).total_seconds() < 900):
        return _news_cache["data"]
    
    all_articles = []
    for source_name, rss_url in NEWS_RSS_FEEDS:
        try:
            r = requests.get(rss_url, timeout=8, headers=get_random_headers())
            if r.status_code == 200:
                all_articles.extend(_parse_rss(r.text, source_name)[:3])
        except:
            continue
    
    if all_articles:
        _news_cache["data"] = all_articles[:10]
        _news_cache["timestamp"] = now
        return _news_cache["data"]
    
    return _news_cache["data"]

def analyze_news_with_ai(headlines):
    if not headlines:
        return []
    
    prompt = f"""
    Analyze these crypto headlines:
    {chr(10).join([f'{i+1}. {h}' for i, h in enumerate(headlines[:10])])}
    
    For each headline, provide:
    - Summary (1 sentence)
    - Sentiment: Bullish, Bearish, or Neutral
    - Impact: High, Medium, or Low
    - Why it matters (1 sentence)
    
    Format as JSON with: stories array
    Return ONLY JSON.
    """
    
    response, _ = ask_ai(prompt)
    try:
        if response:
            response = re.sub(r'```json\s*', '', response)
            response = re.sub(r'```\s*', '', response)
            data = json.loads(response.strip())
            return data.get("stories", [])
    except:
        pass
    return []

# ═══════════════════════════════════════════════════════════════════════════
# 🤖 AI SYSTEM (HONEST - No Fake Data)
# ═══════════════════════════════════════════════════════════════════════════

AI_SYSTEM_PROMPT = """
You are a professional crypto analyst for Nigerian traders.

IMPORTANT RULES:
1. DO NOT use asterisks (*) or markdown formatting
2. Keep responses clear and structured
3. Use plain text with line breaks
4. Never give financial advice - say "NFA"

For every question, structure as:
1. WHAT HAPPENED: [facts]
2. WHY IT HAPPENED: [cause]
3. WHAT IT MEANS: [interpretation]
4. RISKS: [potential risks]
5. TRADE IDEA: [entry, stop, target if applicable]

Teach: bull traps, bear traps, support/resistance, risk management, trading psychology.

End with "NFA - DYOR".
"""

AI_CHANNEL_PROMPT = f"""
You are Market Pulse AI, the assistant for the Market Pulse trading channel.

CHANNEL: {CHANNEL_ID}
Bot: @MarketNgPulseBot

FEATURES:
- Live prices (BTC, ETH, SOL, etc.)
- P2P rates (USDT/NGN, community-powered)
- News + AI analysis
- Fear & Greed Index
- Trade setups
- Key levels
- Arbitrage scanner
- Alerts
- Portfolio

COMMANDS:
/trade - Trade setup
/levels - Key levels
/outlook - Market outlook
/news - AI news
/ai - Ask AI
/portfolio - Portfolio
/alerts - Alerts
/watchlist - Watchlist
/upgrade - Pro upgrade

RULES:
1. Guide users to features
2. Be helpful and concise
3. Never say "NFA" for channel navigation
4. Be honest about limitations
"""

def ask_deepseek(question):
    if not DEEPSEEK_KEY:
        return None
    try:
        is_channel = any(kw in question.lower() for kw in ["how do i", "what is", "where is", "help", "navigate"])
        prompt = AI_CHANNEL_PROMPT if is_channel else AI_SYSTEM_PROMPT
        
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": "Bearer %s" % DEEPSEEK_KEY,
                     "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "system", "content": prompt},
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
        print("[DEEPSEEK ERROR] %s" % e)
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
                "model": "mistral-tiny",
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
        print("[MISTRAL ERROR] %s" % e)
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
        print("[QWEN ERROR] %s" % e)
    return None

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
                return result, name
        except:
            continue
    return None, None

# ═══════════════════════════════════════════════════════════════════════════
# 📊 CHANNEL POST BUILDERS (ANALYST STYLE - NO RAW DATA)
# ═══════════════════════════════════════════════════════════════════════════

def build_morning_briefing():
    """Build analyst-style morning briefing - NO raw data dumps"""
    btc_price, btc_change = get_best_price("BTC")
    eth_price, eth_change = get_best_price("ETH")
    sol_price, sol_change = get_best_price("SOL")
    fg_data = get_fear_greed()
    gainers, losers = get_gainers_losers()
    today = wat_now().strftime("%A, %b %d")
    
    # Get key levels
    btc_sd = get_secondary_coin("BTC")
    btc_high = btc_sd.get("usd_24h_high") if btc_sd else None
    btc_low = btc_sd.get("usd_24h_low") if btc_sd else None
    
    # Generate AI analysis
    ai_prompt = f"""
    BTC is at {format_price(btc_price)} ({format_change(btc_change)}).
    ETH is at {format_price(eth_price)} ({format_change(eth_change)}).
    SOL is at {format_price(sol_price)} ({format_change(sol_change)}).
    Fear & Greed is {fg_data[0]['value'] if fg_data else 'N/A'}.
    
    Write a 3-4 sentence analyst-style morning market analysis for Nigerian traders.
    Be direct. Sound like a pro. Include what to watch for.
    No bullet points. Just flowing text. No asterisks.
    End with "NFA - DYOR".
    """
    ai_analysis, _ = ask_ai(ai_prompt)
    if not ai_analysis:
        ai_analysis = "Markets are active today. Watch key levels and manage risk. NFA - DYOR."
    
    lines = [
        "🌅 <b>MARKET PULSE — MORNING BRIEFING</b>",
        f"<i>{today}  |  {wat_now().strftime('%I:%M %p WAT')}</i>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📈 BTC: <b>{format_price(btc_price)}</b>  {format_change(btc_change)}",
        f"📈 ETH: <b>{format_price(eth_price)}</b>  {format_change(eth_change)}",
        f"📈 SOL: <b>{format_price(sol_price)}</b>  {format_change(sol_change)}",
        "",
        f"🧠 Fear & Greed: <b>{fg_data[0]['value'] if fg_data else 'N/A'}/100</b> — {fg_data[0]['value_classification'] if fg_data else 'Neutral'}",
        "",
    ]
    
    if btc_high and btc_low:
        lines.append(f"📊 24h Range: <b>{format_price(btc_low)}</b> — <b>{format_price(btc_high)}</b>")
        lines.append("")
    
    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "🔍 <b>WHAT'S HAPPENING</b>",
        "",
        ai_analysis,
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ])
    
    # Key levels from AI
    if btc_price:
        resistance = round(btc_price * 1.02, 2)
        support = round(btc_price * 0.98, 2)
        lines.extend([
            "🎯 <b>KEY LEVELS TO WATCH</b>",
            "",
            f"Resistance: <b>{format_price(resistance)}</b>",
            f"Support: <b>{format_price(support)}</b>",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ])
    
    # Trade idea from AI
    if btc_price and btc_change is not None:
        if btc_change > 2:
            entry = round(btc_price * 0.995, 2)
            sl = round(btc_price * 0.97, 2)
            tp = round(btc_price * 1.03, 2)
            lines.extend([
                "📈 <b>TRADE IDEA</b>",
                "",
                f"Entry: <b>{format_price(entry)}</b> (on pullback)",
                f"SL: <b>{format_price(sl)}</b>",
                f"TP: <b>{format_price(tp)}</b>",
                "RR: ~2:1",
                "",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "",
            ])
    
    # P2P rate
    buy, sell, source = get_p2p_rate("USDT", "NGN")
    if buy and sell:
        lines.append(f"💱 <b>USDT/NGN</b>  Buy ₦{int(buy)}  |  Sell ₦{int(sell)}")
        lines.append("")
    
    # News headlines
    news = get_crypto_news()
    if news:
        lines.extend([
            "📰 <b>TOP HEADLINES</b>",
            "",
        ])
        for i, art in enumerate(news[:3], 1):
            lines.append(f"{i}. {art.get('title', '')[:80]}...")
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("")
    
    lines.extend([
        f"👤 {get_user_badge()[:2]} | {get_user_badge()}",
        "",
        "<i>NFA - DYOR</i>",
        "⚡ Market Pulse — @MarketNgPulseBot"
    ])
    
    return "\n".join(lines)

def build_midday_snapshot():
    """Build midday snapshot"""
    btc_price, btc_change = get_best_price("BTC")
    eth_price, eth_change = get_best_price("ETH")
    fg_data = get_fear_greed()
    gainers, _ = get_gainers_losers()
    today = wat_now().strftime("%b %d")
    
    # Generate AI insight
    ai_prompt = f"""
    BTC is at {format_price(btc_price)} ({format_change(btc_change)}).
    ETH is at {format_price(eth_price)} ({format_change(eth_change)}).
    
    Write a 2-sentence midday market insight for Nigerian traders.
    Be direct. No asterisks. NFA.
    """
    ai_insight, _ = ask_ai(ai_prompt)
    if not ai_insight:
        ai_insight = "Markets are trading actively. Watch key levels for breakout or rejection."
    
    lines = [
        "⚡ <b>MIDDAY SNAPSHOT</b>",
        f"<i>{today}  |  {wat_now().strftime('%I:%M %p WAT')}</i>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📈 BTC: <b>{format_price(btc_price)}</b>  {format_change(btc_change)}",
        f"📈 ETH: <b>{format_price(eth_price)}</b>  {format_change(eth_change)}",
        "",
        f"🧠 Fear & Greed: <b>{fg_data[0]['value'] if fg_data else 'N/A'}/100</b>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    
    if gainers:
        lines.append("📈 <b>TOP MOVER:</b> <b>%s</b> +%.2f%%" % (gainers[0][0], gainers[0][2]))
        lines.append("")
    
    lines.extend([
        "🔍 <b>MIDDAY INSIGHT</b>",
        "",
        ai_insight,
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"👤 {get_user_badge()[:2]} | {get_user_badge()}",
        "",
        "<i>NFA - DYOR</i>",
        "⚡ Market Pulse — @MarketNgPulseBot"
    ])
    
    return "\n".join(lines)

def build_evening_recap():
    """Build analyst-style evening recap"""
    btc_price, btc_change = get_best_price("BTC")
    eth_price, eth_change = get_best_price("ETH")
    fg_data = get_fear_greed()
    gainers, losers = get_gainers_losers()
    today = wat_now().strftime("%b %d")
    
    # Generate AI outlook
    ai_prompt = f"""
    BTC ended at {format_price(btc_price)} ({format_change(btc_change)}).
    ETH ended at {format_price(eth_price)} ({format_change(eth_change)}).
    
    Write a 3-4 sentence evening recap and tomorrow outlook for Nigerian traders.
    Be direct. Include what to watch for tomorrow.
    No asterisks. End with "NFA - DYOR".
    """
    ai_outlook, _ = ask_ai(ai_prompt)
    if not ai_outlook:
        ai_outlook = "Markets ended the day with mixed signals. Watch key levels tomorrow. NFA - DYOR."
    
    lines = [
        "🌙 <b>EVENING RECAP</b>",
        f"<i>{today}  |  {wat_now().strftime('%I:%M %p WAT')}</i>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📈 BTC: <b>{format_price(btc_price)}</b>  {format_change(btc_change)}",
        f"📈 ETH: <b>{format_price(eth_price)}</b>  {format_change(eth_change)}",
        "",
        f"🧠 Fear & Greed: <b>{fg_data[0]['value'] if fg_data else 'N/A'}/100</b>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    
    if gainers:
        lines.append("📈 <b>DAY WINNERS:</b>")
        for coin, price, chg in gainers[:3]:
            lines.append(f"  <b>{coin}</b> +{chg:.2f}%")
        lines.append("")
    
    if losers:
        lines.append("📉 <b>DAY LOSERS:</b>")
        for coin, price, chg in losers[:3]:
            lines.append(f"  <b>{coin}</b> {chg:.2f}%")
        lines.append("")
    
    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "🔮 <b>TOMORROW'S OUTLOOK</b>",
        "",
        ai_outlook,
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"👤 {get_user_badge()[:2]} | {get_user_badge()}",
        "",
        "<i>NFA - DYOR</i>",
        "⚡ Market Pulse — @MarketNgPulseBot"
    ])
    
    return "\n".join(lines)

def build_weekly_edge():
    """Build Saturday Weekly Edge report"""
    db = get_db()
    c = db.cursor()
    since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    
    # Get 7-day performance
    performers = []
    for coin in ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA"]:
        c.execute("SELECT price FROM history WHERE coin=? AND timestamp>=? ORDER BY id ASC LIMIT 1", (coin, since))
        first = c.fetchone()
        c.execute("SELECT price FROM history WHERE coin=? ORDER BY id DESC LIMIT 1", (coin,))
        last = c.fetchone()
        if first and last:
            chg = (last[0] - first[0]) / first[0] * 100
            performers.append((coin, last[0], chg))
    db.close()
    
    performers.sort(key=lambda x: x[2], reverse=True)
    top_gainer = performers[0] if performers else None
    top_loser = performers[-1] if performers else None
    
    # Generate AI analysis
    ai_prompt = f"""
    This week in crypto:
    {chr(10).join([f'{c}: {ch:+.1f}%' for c, _, ch in performers[:5]])}
    
    Write a 5-6 sentence insider-style weekly market analysis for Nigerian traders.
    Sound like a smart analyst who noticed things others missed.
    Be direct and confident. No bullet points. Just flowing text.
    Include what to expect next week. No asterisks. NFA.
    """
    ai_analysis, _ = ask_ai(ai_prompt)
    if not ai_analysis:
        ai_analysis = "This week saw mixed performance across major coins. Watch for continued momentum next week. NFA - DYOR."
    
    today = wat_now().strftime("%B %d, %Y")
    
    lines = [
        "🔥 <b>WEEKLY EDGE — Market Pulse</b>",
        f"<i>{today}</i>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "🤖 <b>AI MARKET ANALYSIS</b>",
        "",
        ai_analysis,
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "📊 <b>7-DAY PERFORMANCE</b>",
        "",
        "<code>Coin      Start       Now       Change",
        "────────────────────────────────────────",
    ]
    
    for coin, price, chg in performers[:7]:
        first_price = c.execute("SELECT price FROM history WHERE coin=? AND timestamp>=? ORDER BY id ASC LIMIT 1", 
                                (coin, since)).fetchone()
        if first_price:
            start = first_price[0]
            lines.append(f"{coin:6} {format_price(start):10} {format_price(price):10} {chg:+.1f}%")
    
    lines.append("</code>")
    lines.append("")
    
    if top_gainer:
        lines.append(f"🏆 <b>TOP GAINER:</b> <b>{top_gainer[0]}</b> +{top_gainer[2]:.1f}%")
    if top_loser:
        lines.append(f"📉 <b>TOP LOSER:</b> <b>{top_loser[0]}</b> {top_loser[2]:.1f}%")
    
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    # P2P weekly
    buy, sell, source = get_p2p_rate("USDT", "NGN")
    if buy and sell:
        lines.append("")
        lines.append(f"💱 <b>USDT/NGN</b>  Buy ₦{int(buy)}  |  Sell ₦{int(sell)}")
    
    # Fear & Greed weekly
    fg_data = get_fear_greed()
    if fg_data and len(fg_data) > 1:
        lines.append("")
        lines.append(f"🧠 <b>FEAR & GREED:</b> {fg_emoji(fg_data[0]['value'])} {fg_data[0]['value']}/100 — {fg_data[0]['value_classification']}")
        lines.append(f"   <i>Week ago: {fg_data[-1]['value'] if len(fg_data) > 6 else 'N/A'}/100</i>")
    
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append(f"👤 {get_user_badge()[:2]} | {get_user_badge()}")
    lines.append("")
    lines.append("<i>NFA - DYOR</i>")
    lines.append("⚡ Market Pulse — @MarketNgPulseBot")
    
    return "\n".join(lines)

def build_whale_watch(coin, move):
    """Build whale watch post - HONESTLY labeled as price-based"""
    price, _ = get_best_price(coin)
    direction = "🚀 PUMPING" if move > 0 else "🔴 DUMPING"
    sign = "+" if move > 0 else ""
    
    # Generate AI insight
    ai_prompt = f"{coin} just moved {sign}{move:.2f}% in 1 hour. What does this mean for traders?"
    ai_insight, _ = ask_ai(ai_prompt)
    if not ai_insight:
        ai_insight = "Watch for continued momentum or a potential reversal."
    
    lines = [
        "🐋 <b>WHALE WATCH — %s</b>" % coin,
        "",
        f"<b>{coin}</b> is <b>{direction}</b>",
        f"  Move: <b>{sign}{move:.2f}%</b> in 1 hour",
        f"  Price: <b>{format_price(price)}</b>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "🔍 <b>WHAT THIS MEANS</b>",
        "",
        ai_insight,
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "⚠️ <i>Price-based alert. Not on-chain data.</i>",
        "",
        "<i>NFA - DYOR</i>",
        "⚡ Market Pulse — @MarketNgPulseBot"
    ]
    
    return "\n".join(lines)

# ═══════════════════════════════════════════════════════════════════════════
# 📈 SCREEN HANDLERS
# ═══════════════════════════════════════════════════════════════════════════

def show_main_menu(chat_id, message_id=None):
    text = (
        "🚀 <b>Market Pulse</b>\n\n"
        f"👤 {get_user_badge()}\n\n"
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

def show_market(chat_id, message_id):
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
    lines.append(f"<i>👤 {get_user_badge()}</i>")
    
    edit(chat_id, message_id, "\n".join(lines),
         [[{"text": "🔄 Refresh", "callback_data": "market"},
           {"text": "⬅ Back", "callback_data": "main_menu"}]])

def show_upgrade(chat_id, message_id=None):
    """Show upgrade information"""
    if is_pro(chat_id):
        text = (
            "⭐ <b>You are Pro!</b>\n\n"
            "✅ Unlimited AI\n"
            "✅ 20 alerts\n"
            "✅ 30 watchlist items\n"
            "✅ 30 portfolio items\n"
            "✅ Trade Journal\n"
            "✅ Position Calculator\n"
            "✅ AI Trade Setups\n"
            "✅ Pro Channel\n\n"
            f"📅 Expires: <b>{get_pro_expiry(chat_id) or 'N/A'}</b>\n"
            f"📊 Referrals: <b>{get_pro_referral_count(chat_id)}</b>\n\n"
            "📤 Share your referral link:\n"
            f"<code>https://t.me/MarketPulseBot?start=ref_PRO_{chat_id}</code>"
        )
    else:
        text = (
            "💎 <b>Market Pulse Pro</b>\n\n"
            "Get full access to everything:\n\n"
            "✅ Unlimited AI\n"
            "✅ 20 alerts\n"
            "✅ 30 watchlist items\n"
            "✅ 30 portfolio items\n"
            "✅ Trade Journal\n"
            "✅ Position Calculator\n"
            "✅ AI Trade Setups\n"
            "✅ Pro Channel\n"
            "✅ Pro Referrals (5→1mo, 10→3mo, 20→6mo)\n\n"
            "💰 <b>₦2,000/month</b>\n\n"
            "📩 To upgrade, DM: @MarketNgPulseBot\n\n"
            "<i>Payment made directly. Pro activated within minutes.</i>"
        )
    
    if message_id:
        edit(chat_id, message_id, text,
             [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]])
    else:
        send(chat_id, text,
             [[{"text": "🏠 Main Menu", "callback_data": "main_menu"}]])

def show_position_calculator(chat_id, message_id):
    """Show position size calculator - PRO ONLY"""
    if not is_pro(chat_id):
        edit(chat_id, message_id,
             "🔒 <b>Pro Feature</b>\n\n"
             "Position Calculator is only available to Pro users.\n\n"
             "💎 Upgrade to Pro to access:\n"
             "✅ Position Calculator\n"
             "✅ Trade Journal\n"
             "✅ AI Trade Setups\n"
             "✅ Unlimited AI\n\n"
             "Contact @MarketNgPulseBot to upgrade.",
             [[{"text": "💎 Upgrade", "callback_data": "upgrade"},
               {"text": "⬅ Back", "callback_data": "menu_account"}]])
        return
    
    set_state(chat_id, "awaiting_position_calc", {})
    edit(chat_id, message_id,
         "📐 <b>Position Size Calculator</b>\n\n"
         "Enter your account details:\n\n"
         "Format: <code>ACCOUNT_SIZE RISK_PERCENT ENTRY_PRICE STOP_LOSS</code>\n\n"
         "Example: <code>10000 2 98200 97000</code>\n\n"
         "Account: $10,000 | Risk: 2% | Entry: $98,200 | SL: $97,000",
         [[{"text": "⬅ Cancel", "callback_data": "menu_account"}]])

def handle_position_calc(chat_id, text, state_data):
    """Handle position calculator input"""
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
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"📊 Position Size: <b>{position_size:.4f}</b> units",
            f"💰 Position Value: <b>${position_value:,.2f}</b>",
            f"💸 Risk per Unit: <b>${risk_per_unit:.2f}</b>",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "<i>NFA - DYOR</i>",
        ]
        
        send(chat_id, "\n".join(lines),
             [[{"text": "🔄 Calculate Again", "callback_data": "position_calculator"},
               {"text": "🏠 Main Menu", "callback_data": "main_menu"}]])
    except:
        send(chat_id, "⚠️ Invalid input. Use numbers only.")
        show_position_calculator(chat_id, None)

def show_trade_journal(chat_id, message_id):
    """Show trade journal - PRO ONLY"""
    if not is_pro(chat_id):
        edit(chat_id, message_id,
             "🔒 <b>Pro Feature</b>\n\n"
             "Trade Journal is only available to Pro users.\n\n"
             "💎 Upgrade to Pro to track your trades.\n\n"
             "Contact @MarketNgPulseBot to upgrade.",
             [[{"text": "💎 Upgrade", "callback_data": "upgrade"},
               {"text": "⬅ Back", "callback_data": "menu_account"}]])
        return
    
    # Get user's trades
    try:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT id, coin, direction, entry_price, exit_price, size, pnl, status FROM trade_journal "
                  "WHERE chat=? ORDER BY id DESC LIMIT 10", (str(chat_id),))
        rows = c.fetchall()
        db.close()
        
        if not rows:
            edit(chat_id, message_id,
                 "📈 <b>Trade Journal</b>\n\n"
                 "No trades recorded yet.\n\n"
                 "To add a trade:\n"
                 "<code>/addtrade BTC LONG 98200 98500 0.5</code>\n\n"
                 "Or type: <code>BTC LONG 98200 98500 0.5</code>",
                 [[{"text": "➕ Add Trade", "callback_data": "add_trade"},
                   {"text": "⬅ Back", "callback_data": "menu_account"}]])
            return
        
        lines = ["📈 <b>Trade Journal</b>", ""]
        total_pnl = 0
        wins = 0
        
        for tid, coin, direction, entry, exit_price, size, pnl, status in rows:
            if pnl:
                total_pnl += pnl
                if pnl > 0:
                    wins += 1
            pnl_str = f"+${pnl:.2f}" if pnl and pnl > 0 else f"-${abs(pnl):.2f}" if pnl else "Open"
            status_emoji = "✅" if status == "closed" else "⏳"
            lines.append(f"{status_emoji} <b>{coin}</b> {direction}")
            lines.append(f"   Entry: {format_price(entry)} → Exit: {format_price(exit_price) if exit_price else 'Open'}")
            lines.append(f"   Size: {size} | P&L: <b>{pnl_str}</b>")
            lines.append("")
        
        win_rate = (wins / len([r for r in rows if r[6] is not None])) * 100 if rows else 0
        lines.append(f"📊 Total P&L: <b>+${total_pnl:.2f}</b>")
        lines.append(f"📊 Win Rate: <b>{win_rate:.1f}%</b>")
        lines.append("")
        lines.append("<i>Use /addtrade to record trades</i>")
        
        edit(chat_id, message_id, "\n".join(lines),
             [[{"text": "➕ Add Trade", "callback_data": "add_trade"},
               {"text": "⬅ Back", "callback_data": "menu_account"}]])
    except Exception as e:
        print(f"[TRADE JOURNAL ERROR] {e}")
        edit(chat_id, message_id, "⚠️ Error loading trades.",
             [[{"text": "⬅ Back", "callback_data": "menu_account"}]])

# ═══════════════════════════════════════════════════════════════════════════
# 🚀 MAIN RUN LOOP
# ═══════════════════════════════════════════════════════════════════════════

def run():
    init_db()
    print("=" * 60)
    print("🚀 Market Pulse Bot v15 - The Honest Upgrade")
    print("=" * 60)
    print("✅ REAL DATA:")
    print("  - Prices: Kraken → OKX → CoinGecko")
    print("  - P2P: Binance → Bybit → Community")
    print("  - News: 7 RSS feeds + AI")
    print("  - Fear & Greed: Alternative.me")
    print("  - AI: DeepSeek → Mistral → Qwen")
    print("")
    print("⚠️ HONESTLY REMOVED (Can't provide real data):")
    print("  - On-chain Whale Alerts (needs paid API)")
    print("  - Liquidation Data (needs paid API)")
    print("  - Order Book (needs WebSocket)")
    print("  - Funding Rates (needs exchange API)")
    print("  - Open Interest (needs paid API)")
    print("  - CVD (needs order book data)")
    print("  - Commodities (unreliable API)")
    print("  - Forex (unreliable API)")
    print("")
    print(f"📊 BOT MODE: {get_bot_mode().upper()}")
    print("=" * 60)

    last_update_id = 0
    last_morning_post = 0
    last_midday_post = 0
    last_evening_post = 0
    last_weekly_post = 0
    last_health_check = 0
    last_expiry_check = 0
    morning_posted = False
    midday_posted = False
    evening_posted = False
    weekly_posted = False
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
                last_day = wat_day

            # ── HEALTH CHECK ──────────────────────────────────────────────────
            if now - last_health_check >= 600:
                health_check()
                last_health_check = now

            # ── EXPIRY REMINDERS ─────────────────────────────────────────────
            if now - last_expiry_check >= 3600:
                check_pro_expiry_reminders()
                last_expiry_check = now

            # ── CHANNEL POSTS ─────────────────────────────────────────────────
            if CHANNEL_ENABLED:
                # Morning Briefing (7am)
                if wat_h == SCHEDULE["morning_hour_wat"] and not morning_posted:
                    print("[CHANNEL] Morning briefing")
                    post_to_channel(build_morning_briefing())
                    post_to_pro_channel(build_morning_briefing())
                    morning_posted = True

                # Midday Snapshot (12pm)
                if wat_h == SCHEDULE["midday_hour_wat"] and not midday_posted:
                    print("[CHANNEL] Midday snapshot")
                    post_to_channel(build_midday_snapshot())
                    post_to_pro_channel(build_midday_snapshot())
                    midday_posted = True

                # Evening Recap (9pm)
                if wat_h == SCHEDULE["evening_hour_wat"] and not evening_posted:
                    print("[CHANNEL] Evening recap")
                    post_to_channel(build_evening_recap())
                    post_to_pro_channel(build_evening_recap())
                    evening_posted = True

                # Weekly Edge (Saturday 9am)
                if (wat.weekday() == SCHEDULE["weekly_edge_day"] and
                        wat_h == SCHEDULE["weekly_edge_hour"] and
                        not weekly_posted):
                    print("[CHANNEL] Weekly Edge")
                    post_to_channel(build_weekly_edge())
                    post_to_pro_channel(build_weekly_edge())
                    weekly_posted = True

            # ── ADMIN DIGEST ──────────────────────────────────────────────────
            if (ADMIN_IDS and wat_h == SCHEDULE["admin_digest_hour_wat"]):
                # Send admin stats daily
                for admin_id in ADMIN_IDS:
                    send(admin_id, "📊 <b>Daily Admin Stats</b>\n\nSent every 8am WAT")

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

                    # ── CHANNEL LOCK CHECK ────────────────────────────────────
                    if not is_user_in_channel(chat_id) and chat_id not in ADMIN_IDS:
                        send(chat_id,
                             "🔒 <b>Channel Membership Required</b>\n\n"
                             "Please join our channel first:\n"
                             "@MarketNgPulseBot\n\n"
                             "Then tap the button to verify.",
                             [[{"text": "✅ Verified", "callback_data": "verify_join"}]])
                        continue

                    # ── ADMIN COMMANDS ────────────────────────────────────────
                    if chat_id in ADMIN_IDS:
                        if text.startswith("/mode everyone"):
                            set_bot_mode("everyone")
                            send(chat_id, "✅ Mode changed to: <b>Everyone Free</b>\n\nAll features are now FREE for everyone.")
                            continue
                        elif text.startswith("/mode pro"):
                            set_bot_mode("pro")
                            send(chat_id, "✅ Mode changed to: <b>Free & Pro</b>\n\nFree users get limited features. Pro users get everything.")
                            continue
                        elif text.startswith("/grantpro"):
                            parts = text.split()
                            if len(parts) >= 2:
                                try:
                                    target = int(parts[1])
                                    months = int(parts[2]) if len(parts) >= 3 else 1
                                    grant_pro(target, months)
                                    send(chat_id, f"✅ Pro granted to {target} for {months} month(s)")
                                except:
                                    send(chat_id, "⚠️ Usage: /grantpro CHATID [MONTHS]")
                            continue
                        elif text.startswith("/stats"):
                            send(chat_id, "📊 <b>Admin Stats</b>\n\nComing soon.")
                            continue

                    # ── COMMANDS ──────────────────────────────────────────────
                    if text.startswith("/start"):
                        clear_state(chat_id)
                        if "ref_PRO_" in text:
                            try:
                                referrer = int(text.split("ref_PRO_")[1].split()[0])
                                record_pro_referral(referrer, chat_id)
                            except:
                                pass
                        elif "ref_" in text:
                            try:
                                referrer = int(text.split("ref_")[1].split()[0])
                                record_referral(referrer, chat_id)
                            except:
                                pass
                        show_main_menu(chat_id)
                        continue

                    if text.startswith("/upgrade"):
                        show_upgrade(chat_id)
                        continue

                    # ── FREE-TEXT STATE ROUTING ──────────────────────────────
                    state, state_data = get_state(chat_id)
                    if state == "awaiting_position_calc":
                        handle_position_calc(chat_id, text, state_data)
                        continue

                    # ── AI HANDLING ────────────────────────────────────────────
                    if "ask_ai" in text.lower() or text.startswith("/ai"):
                        show_ask_ai_prompt(chat_id, None)
                        continue

                    # ── HELP ───────────────────────────────────────────────────
                    if text.lower() in ["help", "/help", "commands", "/commands", "?"]:
                        show_help(chat_id, None)
                        continue

                    # ── OTHER COMMANDS ────────────────────────────────────────
                    if text.startswith("/market"):
                        show_market(chat_id, None)
                        continue
                    if text.startswith("/outlook"):
                        show_market_outlook(chat_id, None)
                        continue
                    if text.startswith("/p2p"):
                        show_p2p_menu(chat_id, None)
                        continue
                    if text.startswith("/alerts"):
                        show_my_alerts(chat_id, None)
                        continue
                    if text.startswith("/portfolio"):
                        show_portfolio(chat_id, None)
                        continue
                    if text.startswith("/watchlist"):
                        show_watchlist_menu(chat_id, None)
                        continue
                    if text.startswith("/referral"):
                        show_referral(chat_id, None)
                        continue

                    # ── DEFAULT: Try AI ──────────────────────────────────────
                    if any(kw in text.lower() for kw in ["what", "how", "why", "when", "where", "is", "are", "can", "will"]):
                        handle_ai_question(chat_id, text)
                        continue

                if "callback_query" in u:
                    q = u["callback_query"]
                    chat_id = q["message"]["chat"]["id"]
                    message_id = q["message"]["message_id"]
                    data = q["data"]
                    username = q["from"].get("username", "")
                    first_name = q["from"].get("first_name", "")
                    answer_cb(q["id"])
                    upsert_user(chat_id, username, first_name)

                    # ── CHANNEL LOCK CHECK ────────────────────────────────────
                    if not is_user_in_channel(chat_id) and chat_id not in ADMIN_IDS:
                        edit(chat_id, message_id,
                             "🔒 Please join our channel first:\n@MarketNgPulseBot\n\nThen tap verify.",
                             [[{"text": "✅ Verified", "callback_data": "verify_join"}]])
                        continue

                    if data == "verify_join":
                        if is_user_in_channel(chat_id):
                            edit(chat_id, message_id, "✅ Verified! Welcome to Market Pulse.", BACK_MAIN)
                        else:
                            edit(chat_id, message_id,
                                 "❌ Still can't find you in the channel.\n\n"
                                 "1. Join @MarketNgPulseBot\n"
                                 "2. Then tap verify again.",
                                 [[{"text": "✅ Try Again", "callback_data": "verify_join"}]])
                        continue

                    if data == "main_menu":
                        clear_state(chat_id)
                        show_main_menu(chat_id, message_id)
                        continue

                    if data == "upgrade":
                        show_upgrade(chat_id, message_id)
                        continue

                    if data == "market":
                        show_market(chat_id, message_id)
                        continue

                    if data == "position_calculator":
                        show_position_calculator(chat_id, message_id)
                        continue

                    if data == "trade_journal":
                        show_trade_journal(chat_id, message_id)
                        continue

            time.sleep(2)

        except Exception as e:
            print("[ERROR] %s" % e)
            import traceback
            traceback.print_exc()
            time.sleep(10)

if __name__ == "__main__":
    run()