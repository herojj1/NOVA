"""
CardCheckout API — Server Entry Point
======================================
FastAPI server that exposes the Shopify card-checking engine as an HTTP API.

Endpoints
---------
GET  /health
GET  /check?card=NUM|MM|YYYY|CVV&url=SHOP_URL&proxy=...
POST /check  (JSON body)

Response includes a `captcha` flag. When true, the caller should rotate to
another site rather than treating the card as dead.
"""

import os
import asyncio
import concurrent.futures
import functools
import logging
import threading as _threading
import time
from typing import Optional, Tuple

from fastapi import FastAPI, Query
from pydantic import BaseModel

from checkout_engine import (
    run_checkout_public,
    normalize_proxy,
    parse_card_entry,
)

# ── Logging ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cardcheckout.api")

# ── Configuration ──────────────────────────────────────────────────────
THREAD_WORKERS = int(os.environ.get("CHECKER_THREADS", "200"))
MAX_RETRIES    = int(os.environ.get("CHECKER_RETRIES", "1"))

_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=THREAD_WORKERS,
    thread_name_prefix="chk",
)

_active_checks      = 0
_active_checks_lock = _threading.Lock()


def _inc_active():
    global _active_checks
    with _active_checks_lock:
        _active_checks += 1


def _dec_active():
    global _active_checks
    with _active_checks_lock:
        _active_checks -= 1


app = FastAPI(
    title="CardCheckout API",
    version="3.0.0",
    description=(
        "Shopify card-check API. Captcha-aware: when a site returns a "
        "captcha challenge, `captcha` is true and the caller is expected "
        "to rotate to another site."
    ),
    docs_url=None,
    redoc_url=None,
)


# ── Request / Response models ──────────────────────────────────────────

class CheckRequest(BaseModel):
    card:     Optional[str] = None
    shop_url: Optional[str] = None
    proxy:    Optional[str] = None
    low:      bool          = True


class CheckResponse(BaseModel):
    Response:    str  = "ERROR"
    CC:          str  = ""
    Price:       str  = ""
    Gate:        str  = "Shopify"
    Site:        str  = ""
    Charged:     str  = "False"
    status_code: str  = ""
    error:       str  = ""
    retryable:   bool = False
    captcha:     bool = False
    receipt_url: str  = ""


# ── Helpers ────────────────────────────────────────────────────────────

def _validate_proxy(raw: str) -> Tuple[Optional[str], Optional[CheckResponse]]:
    if not raw or not raw.strip():
        return None, CheckResponse(
            Response="ERROR",
            status_code="PROXY_REQUIRED",
            error="proxy is required — e.g. http://user:pass@1.2.3.4:8080",
        )
    try:
        return normalize_proxy(raw), None
    except Exception as exc:
        return None, CheckResponse(
            Response="ERROR",
            status_code="PROXY_INVALID",
            error=f"Invalid proxy format: {exc}",
        )


def _validate_card(raw: str) -> Tuple[Optional[str], Optional[CheckResponse]]:
    import datetime as _dt
    if not raw or not raw.strip():
        return None, CheckResponse(
            Response="ERROR",
            status_code="CARD_REQUIRED",
            error="card is required — format: number|mm|yyyy|cvv",
        )
    try:
        _num, _month, _year, _cvv = parse_card_entry(raw)
    except Exception as exc:
        return None, CheckResponse(
            Response="ERROR",
            status_code="CARD_INVALID",
            error=f"invalid card format: {exc}",
        )
    now = _dt.datetime.utcnow()
    if _year < now.year or (_year == now.year and _month < now.month):
        return None, CheckResponse(
            Response="ERROR",
            status_code="CARD_EXPIRED",
            error=f"card expired: {_month:02d}/{_year}",
        )
    return raw.strip(), None


def _validate_url(raw: str) -> Tuple[Optional[str], Optional[CheckResponse]]:
    import urllib.parse as _up
    if not raw or not raw.strip():
        return None, CheckResponse(
            Response="ERROR",
            status_code="URL_REQUIRED",
            error="shop url is required — e.g. https://store.myshopify.com",
        )
    url = raw.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = _up.urlparse(url)
        hostname = parsed.hostname or ""
        if not hostname or "." not in hostname or " " in hostname:
            raise ValueError(hostname)
    except Exception:
        return None, CheckResponse(
            Response="ERROR",
            status_code="URL_INVALID",
            error=f"invalid shop url: {raw!r}",
        )
    return url, None


def _build_response(res: dict, shop_url: str = "") -> CheckResponse:
    status_name = (res.get("status") or "Error").upper()
    if status_name == "DEAD":
        status_name = "DECLINED"
    return CheckResponse(
        Response    = status_name,
        CC          = res.get("card") or "",
        Price       = res.get("price") or "",
        Gate        = "Shopify",
        Site        = shop_url or res.get("site") or "",
        Charged     = "True" if status_name == "CHARGED" else "False",
        status_code = res.get("status_code") or "",
        error       = str(res.get("message") or res.get("error") or ""),
        retryable   = bool(res.get("retryable")),
        captcha     = bool(res.get("captcha")),
        receipt_url = res.get("receipt_url") or "",
    )


async def _run_check(shop_url: str, card: str, proxy_url: str,
                     low: bool) -> CheckResponse:
    loop     = asyncio.get_event_loop()
    attempts = 1 + MAX_RETRIES
    last: Optional[CheckResponse] = None

    for attempt in range(1, attempts + 1):
        t0 = time.perf_counter()
        _inc_active()
        try:
            fn  = functools.partial(run_checkout_public, shop_url, card, proxy_url, low)
            res = await loop.run_in_executor(_pool, fn)
        except Exception as exc:
            logger.warning("attempt %d/%d unhandled: %s", attempt, attempts, exc)
            last = CheckResponse(Response="ERROR", error=str(exc), retryable=True)
            continue
        finally:
            _dec_active()

        resp = _build_response(res, shop_url)
        logger.info(
            "attempt %d/%d | status=%-8s code=%-24s captcha=%s elapsed=%.1fs",
            attempt, attempts, resp.Response, resp.status_code or "-",
            resp.captcha, time.perf_counter() - t0,
        )
        if resp.Response in ("CHARGED", "APPROVED", "3DS"):
            logger.info(
                "HIT | status=%s | amount=%s | site=%s | receipt=%s",
                resp.Response, resp.Price, shop_url, resp.receipt_url,
            )
        if resp.captcha:
            return resp
        if not resp.retryable or attempt == attempts:
            return resp
        last = resp
    return last


# ── Routes ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
async def health():
    with _active_checks_lock:
        active = _active_checks
    return {
        "ok":             True,
        "threads":        THREAD_WORKERS,
        "retries":        MAX_RETRIES,
        "active_checks":  active,
        "engine_version": "3.0.0",
        "captcha_aware":  True,
    }


@app.get("/check", response_model=CheckResponse, tags=["check"])
async def check_get(
    card:  str = Query(..., description="Card string: number|mm|yyyy|cvv"),
    url:   str = Query(..., description="Shopify store URL"),
    proxy: str = Query(..., description="Proxy: http://user:pass@host:port"),
    low:   str = Query(default="true", description="true = prefer products under $5"),
):
    card_val, err = _validate_card(card)
    if err:
        err.CC = card
        return err
    url_val, err = _validate_url(url)
    if err:
        err.CC = card
        err.Site = url
        return err
    proxy_val, err = _validate_proxy(proxy)
    if err:
        err.CC = card
        err.Site = url_val
        return err
    low_mode = low.strip().lower() in ("1", "true", "yes")
    return await _run_check(url_val, card_val, proxy_val, low_mode)


@app.post("/check", response_model=CheckResponse, tags=["check"])
async def check_post(req: CheckRequest):
    raw_card = req.card or ""
    raw_url  = req.shop_url or ""
    card_val, err = _validate_card(raw_card)
    if err:
        err.CC = raw_card
        return err
    url_val, err = _validate_url(raw_url)
    if err:
        err.CC   = raw_card
        err.Site = raw_url
        return err
    proxy_val, err = _validate_proxy(req.proxy or "")
    if err:
        err.CC   = raw_card
        err.Site = url_val
        return err
    return await _run_check(url_val, card_val, proxy_val, req.low)


# ── Standalone runner ──────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    logger.info("CardCheckout API — port=%d threads=%d retries=%d",
                port, THREAD_WORKERS, MAX_RETRIES)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
