"""
shopify_harvester.py — Shopify site discovery + health scan.

Public API:
    scan_file(src_path, dst_path, proxy, min_price, max_price, workers, on_progress)
    harvest_from_seeds(seeds, keyword, dst_path, proxy, min_price, max_price, workers, on_progress)
    load_keywords()
    load_seeds(path="seeds.txt")

Both scan_file and harvest_from_seeds return a 4-tuple:
    (live, dead, over, errors)  — lists of URLs
"""
from __future__ import annotations

import os
import re
import json
import random
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

_HERE = Path(__file__).parent
_KEYWORDS_FILE = _HERE / "keywords.txt"
_SEEDS_FILE = _HERE / "seeds.txt"

_DIRECTORY = [
    "https://shop.app/api/search?query={q}&limit=250",
]

_DEFAULT_KEYWORDS = [
    "coffee", "tea", "candle", "soap", "skincare", "beauty",
    "fashion", "clothing", "jewelry", "accessories", "home", "kitchen",
    "toys", "pets", "fitness", "sports", "outdoor", "books", "snacks",
    "wine", "supplements", "boutique", "vintage", "handmade", "wellness",
]


def load_keywords() -> list:
    try:
        if _KEYWORDS_FILE.is_file():
            lines = [
                ln.strip() for ln in _KEYWORDS_FILE.read_text(encoding="utf-8").splitlines()
            ]
            lines = [ln for ln in lines if ln and not ln.startswith("#")]
            if lines:
                return lines
    except Exception:
        pass
    return list(_DEFAULT_KEYWORDS)


def load_seeds(path: str = None) -> list:
    p = Path(path) if path else _SEEDS_FILE
    try:
        if p.is_file():
            return [
                ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
    except Exception:
        pass
    return []


def _normalize(raw) -> str:
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


def _probe(domain: str, proxy_url: str,
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
        "headers": {"User-Agent": random.choice(_UA_POOL),
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


# ══════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════════
def scan_file(
    src_path: str,
    dst_path: str,
    proxy: str,
    min_price: float,
    max_price: float,
    workers: int = 30,
    on_progress=None,
) -> tuple:
    raw = _read_lines(src_path)
    domains = []
    seen = set()
    for r in raw:
        d = _normalize(r)
        if d and d not in seen:
            seen.add(d)
            domains.append(d)

    live, dead, over, errors = [], [], [], []
    total = len(domains)
    if total == 0:
        return live, dead, over, errors

    done = [0]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_probe, d, proxy, min_price, max_price): d for d in domains}
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

    _write_lines(dst_path, live)
    return live, dead, over, errors


def harvest_from_seeds(
    seeds: list,
    keyword: str,
    dst_path: str,
    proxy: str,
    min_price: float,
    max_price: float,
    workers: int = 30,
    on_progress=None,
) -> tuple:
    candidates = []
    seen = set()

    for s in seeds:
        d = _normalize(s)
        if d and d not in seen:
            seen.add(d)
            candidates.append(d)

    kws = [keyword] if keyword else []
    kws.extend(load_keywords())
    kws = [re.sub(r"[^a-z0-9\-]", "", k.lower()) for k in kws if k]
    kws = [k for k in kws if k]

    for kw in kws[:5]:
        try:
            url = _DIRECTORY[0].format(q=urllib.parse.quote(kw))
            r = httpx.get(url, timeout=12, follow_redirects=True,
                          headers={"User-Agent": random.choice(_UA_POOL)})
            if r.status_code == 200:
                try:
                    data = r.json()
                    for entry in data.get("results", []) if isinstance(data, dict) else []:
                        for key in ("domain", "shop_domain", "url"):
                            v = entry.get(key) if isinstance(entry, dict) else None
                            if v:
                                d = _normalize(v)
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
            slug = f"{kw}{suf}"
            d = f"{slug}.myshopify.com"
            if d not in seen:
                seen.add(d)
                candidates.append(d)

    live, dead, over, errors = [], [], [], []
    total = len(candidates)
    if total == 0:
        return live, dead, over, errors

    done = [0]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_probe, d, proxy, min_price, max_price): d for d in candidates}
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

    existing = _read_lines(dst_path)
    existing_set = {_normalize(u) for u in existing if u}
    appended = 0
    for u in live:
        d = _normalize(u)
        if d and d not in existing_set:
            existing.append(u)
            existing_set.add(d)
            appended += 1
    if appended:
        _write_lines(dst_path, existing)

    return live, dead, over, errors
