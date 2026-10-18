"""
shopify_api_engine.py — API-less adapter.

Bridges checkout_engine.py (curl_cffi Shopify checkout) + site_fetcher.py
(site pool + background harvester) to the bot's original import surface:

    run_shopify_check(site, card, proxy_str=None, variant_id=None) -> dict
    is_proxy_alive(proxy_url, timeout=6.0) -> bool
    parse_proxy(raw) -> dict | None
    ledger_stats() -> dict
    ledger_clear() -> None

No uvicorn. No FastAPI. No HTTP hop. Pure in-process.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

from checkout_engine import (
    CheckStatus,
    CheckResult,
    normalize_proxy as _engine_normalize_proxy,
    run_checkout_for_card,
)
import site_fetcher

log = logging.getLogger("shopify_api_engine")


# ── proxy parsing (kept for bot compat) ──────────────────────────────
_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*)://(.*)$")


def _is_port(v: str) -> bool:
    return v.isdigit() and 1 <= int(v) <= 65535


def parse_proxy(raw: Optional[str]) -> Optional[dict]:
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
    return {
        "url": _engine_normalize_proxy(raw),
        "scheme": scheme,
        "host": host,
        "port": int(port),
        "user": user,
        "pass": password,
    }


# ── result conversion ────────────────────────────────────────────────
_STATUS_MAP = {
    CheckStatus.CHARGED:  "Charged",
    CheckStatus.APPROVED: "Approved",
    CheckStatus.DECLINED: "Dead",
    CheckStatus.ERROR:    "Error",
}


def _to_bot_dict(res: CheckResult) -> dict:
    price_str = "-"
    price_val = 0.0
    try:
        if res.amount:
            pv = float(str(res.amount).replace("$", "").strip())
            if pv > 0:
                price_str = f"${pv:.2f}"
                price_val = pv
    except (ValueError, TypeError):
        pass

    status = _STATUS_MAP.get(res.status, "Error")
    message = res.status_code or res.error or "UNKNOWN"
    message = re.sub(r"^step\d+:\s*", "", message).strip() or "UNKNOWN"

    return {
        "status":       status,
        "message":      message[:150],
        "card":         res.card,
        "gateway":      "Shopify Payments",
        "price":        price_str,
        "price_value":  price_val,
        "site":         res.shop_url,
        "status_code":  res.status_code or "UNKNOWN",
        "retryable":    bool(res.retryable),
        "elapsed":      round(float(res.elapsed or 0.0), 2),
    }


# ── public API ───────────────────────────────────────────────────────
def run_shopify_check(
    site: str,
    card: str,
    proxy_str: Optional[str] = None,
    variant_id: Optional[str] = None,
) -> dict:
    """Sync wrapper around checkout_engine.run_checkout_for_card."""
    t0 = time.time()
    site_clean = (site or "").strip()
    if not site_clean.startswith(("http://", "https://")):
        site_clean = "https://" + site_clean
    site_clean = site_clean.rstrip("/")

    proxy_url = ""
    if proxy_str:
        try:
            proxy_url = _engine_normalize_proxy(proxy_str)
        except Exception:
            proxy_url = ""

    try:
        res = run_checkout_for_card(
            site_clean,
            card,
            proxy_url=proxy_url,
            timeout_seconds=90.0,
        )
    except Exception as exc:
        log.warning("engine exception for %s: %s", site_clean, exc)
        return {
            "status":       "Error",
            "message":      f"engine: {str(exc)[:120]}",
            "card":         card,
            "gateway":      "Shopify Payments",
            "price":        "-",
            "price_value":  0.0,
            "site":         site_clean,
            "status_code":  "ENGINE_EXCEPTION",
            "retryable":    True,
            "elapsed":      round(time.time() - t0, 2),
        }

    try:
        if res.status in (CheckStatus.CHARGED, CheckStatus.APPROVED):
            site_fetcher.report_success(site_clean)
        elif res.status_code == "CAPTCHA_REQUIRED":
            site_fetcher.report_captcha(site_clean)
        elif res.status_code in ("PAYMENTS_METHOD", "SITE_INCOMPATIBLE"):
            site_fetcher.report_payment_blocked(site_clean)
        elif res.status == CheckStatus.ERROR and res.retryable:
            site_fetcher.report_failure(site_clean, weight=1)
    except Exception:
        pass

    return _to_bot_dict(res)


def is_proxy_alive(proxy_url: str, timeout: float = 6.0) -> bool:
    if not proxy_url:
        return False
    try:
        from curl_cffi import requests as _req
        r = _req.get(
            "https://api.ipify.org?format=json",
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=timeout,
            impersonate="chrome131",
            verify=False,
        )
        return r.status_code == 200
    except Exception:
        return False


def ledger_stats() -> dict:
    try:
        return {"cached": site_fetcher.pool_size()}
    except Exception:
        return {"cached": 0}


def ledger_clear() -> None:
    try:
        site_fetcher.clear_captcha(None)
    except Exception:
        pass