"""
rz_harvester.py — RazorPay page discovery + health scan.

Public API:
  - scan_file(src_path, dst_path, proxy, workers, on_progress)
              -> (live, dead, errors)
  - harvest_from_seeds(seeds, keyword, dst_path, proxy, workers, on_progress)
              -> (live, dead, errors)
"""
from __future__ import annotations

import os
import re
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

_RZ_SLUG_HINTS = [
    "donate", "donation", "pay", "payment", "paynow", "checkout",
    "fees", "booking", "order", "store", "shop", "buy", "cart",
    "subscription", "subscribe", "register", "ticket", "course",
    "schoolfees", "collegefees", "tuition", "seva", "daan",
    "fund", "temple", "church", "mandir", "trust", "foundation",
    "ngo", "charity", "welfare", "sponsor", "support",
]


def _probe(url: str, proxy: str | None, timeout: float = 10.0) -> dict:
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
        "headers": {"User-Agent": random.choice(_UA_POOL),
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


def _read_lines(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except Exception:
        return []


def _write_lines(path: str, lines: list):
    with open(path, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln + "\n")


def scan_file(src_path: str, dst_path: str, proxy: str | None,
              workers: int = 30, on_progress=None):
    raw = _read_lines(src_path)
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
        futs = {ex.submit(_probe, u, proxy): u for u in urls}
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

    _write_lines(dst_path, live)
    return live, dead, errors


def harvest_from_seeds(seeds: list, keyword: str | None, dst_path: str,
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
        futs = {ex.submit(_probe, u, proxy): u for u in candidates}
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

    existing = _read_lines(dst_path)
    existing_set = {u.strip().rstrip("/") for u in existing if u}
    appended = 0
    for u in live:
        if u not in existing_set:
            existing.append(u)
            existing_set.add(u)
            appended += 1
    if appended:
        _write_lines(dst_path, existing)

    return live, dead, errors
