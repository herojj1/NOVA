"""
shopify_harvester.py — Compat shim.

Bridges old bot.py imports to site_fetcher. Delete once bot.py is v9.1.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

import site_fetcher as _sf

log = logging.getLogger("shopify_harvester")

_HERE = Path(__file__).parent
_KEYWORDS_FILE = _HERE / "keywords.txt"
_SEEDS_FILE    = _HERE / "seeds.txt"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def load_keywords() -> list:
    try:
        if _KEYWORDS_FILE.is_file():
            lines = [
                ln.strip() for ln in
                _KEYWORDS_FILE.read_text(encoding="utf-8").splitlines()
            ]
            lines = [ln for ln in lines if ln and not ln.startswith("#")]
            if lines:
                return lines
    except Exception:
        pass
    return _sf._DEFAULT_KEYWORDS[:]


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


def _normalize(raw: Any) -> str:
    if not raw:
        return ""
    s = str(raw).strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = s.rstrip("/").split("/")[0].split("?")[0]
    if s.startswith("www."):
        s = s[4:]
    if not s or "." not in s:
        return ""
    if not re.match(
        r"^[a-z0-9]([a-z0-9\-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)+$",
        s,
    ):
        return ""
    return s


def _read_lines(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except Exception:
        return []


def _write_lines(path: str, lines: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln + "\n")


def _probe(domain, proxy_url, min_price, max_price, timeout=10.0):
    if not domain:
        return {"url": "", "ok": False, "reason": "empty", "price": 0.0}
    url = f"https://{domain}"
    probe_url = f"{url}/products.json?limit=50"
    kw = {"timeout": timeout, "follow_redirects": False,
          "headers": {"User-Agent": _UA, "Accept": "application/json"}}
    if proxy_url:
        kw["proxy"] = proxy_url
    try:
        r = httpx.get(probe_url, **kw)
        if r.status_code != 200:
            return {"url": url, "ok": False,
                    "reason": f"HTTP {r.status_code}", "price": 0.0}
        if '"products"' not in (r.text or ""):
            return {"url": url, "ok": False,
                    "reason": "not shopify", "price": 0.0}
        data = r.json()
        prods = data.get("products") or []
        if not prods:
            return {"url": url, "ok": False,
                    "reason": "no products", "price": 0.0}
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
            return {"url": url, "ok": False,
                    "reason": "all OOS", "price": 0.0}
        if cheapest > max_price:
            return {"url": url, "ok": False,
                    "reason": f"over ${max_price}", "price": cheapest}
        if cheapest < min_price:
            return {"url": url, "ok": False,
                    "reason": f"under ${min_price}", "price": cheapest}
        return {"url": url, "ok": True,
                "reason": f"${cheapest:.2f}", "price": cheapest}
    except httpx.TimeoutException:
        return {"url": url, "ok": False, "reason": "timeout", "price": 0.0}
    except httpx.ProxyError as e:
        return {"url": url, "ok": False,
                "reason": f"proxy: {str(e)[:40]}", "price": 0.0}
    except Exception as e:
        return {"url": url, "ok": False,
                "reason": str(e)[:60], "price": 0.0}


def _probe_batch(domains, proxy, min_price, max_price, workers, on_progress):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    live, dead, over, errors = [], [], [], []
    total = len(domains)
    if total == 0:
        return live, dead, over, errors
    done = [0]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_probe, d, proxy, min_price, max_price): d
                for d in domains}
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
    return live, dead, over, errors


def scan_file(src_path, dst_path, proxy, min_price, max_price,
              workers=30, on_progress=None):
    raw = _read_lines(src_path)
    domains, seen = [], set()
    for r in raw:
        d = _normalize(r)
        if d and d not in seen:
            seen.add(d)
            domains.append(d)
    live, dead, over, errors = _probe_batch(
        domains, proxy, min_price, max_price, workers, on_progress
    )
    _write_lines(dst_path, live)
    try:
        for u in live:
            _sf.report_success(u)
        for u in dead:
            _sf.report_failure(u, weight=1)
    except Exception:
        pass
    return live, dead, over, errors


def harvest_from_seeds(seeds, keyword, dst_path, proxy,
                       min_price, max_price, workers=30, on_progress=None):
    candidates, seen = [], set()
    for s in seeds:
        d = _normalize(s)
        if d and d not in seen:
            seen.add(d)
            candidates.append(d)
    suffixes = ["", "shop", "store", "co", "official", "us", "uk", "india"]
    kws = [keyword] if keyword else []
    kws.extend(load_keywords())
    kws = [re.sub(r"[^a-z0-9\-]", "", k.lower()) for k in kws if k]
    kws = [k for k in kws if k]
    for kw in kws[:20]:
        if len(candidates) >= 500:
            break
        for suf in suffixes:
            slug = f"{kw}{suf}"
            d = f"{slug}.myshopify.com"
            if d not in seen:
                seen.add(d)
                candidates.append(d)
    live, dead, over, errors = _probe_batch(
        candidates, proxy, min_price, max_price, workers, on_progress
    )
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
    try:
        for u in live:
            _sf.report_success(u)
    except Exception:
        pass
    return live, dead, over, errors
