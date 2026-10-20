"""
database.py — MongoDB persistence for NOVA v9.3.

Sync pymongo client. Every bot.py data-accessor routes here.
Silent-fail on any Mongo error so the bot never crashes on a DB blip.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Optional

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

log = logging.getLogger("database")

# ══════════════════════════════════════════════════════════════════════
#  CONFIG  (env overrides; defaults are the user's Atlas cluster)
# ══════════════════════════════════════════════════════════════════════
MONGO_URL = os.environ.get(
    "MONGO_URL",
    "mongodb+srv://Hero:jasin12345@cluster0.9wykfhr.mongodb.net/?appName=Cluster0",
)
MONGO_DB = os.environ.get("MONGO_DB", "nova")

_client: Optional[MongoClient] = None
_db: Optional[Database] = None
_init_lock = threading.Lock()


def get_db() -> Optional[Database]:
    """Lazy-connect Mongo once. Returns None on failure."""
    global _client, _db
    if _db is not None:
        return _db
    with _init_lock:
        if _db is not None:
            return _db
        try:
            _client = MongoClient(
                MONGO_URL,
                serverSelectionTimeoutMS=8000,
                connectTimeoutMS=8000,
                socketTimeoutMS=15000,
                maxPoolSize=30,
                minPoolSize=2,
                retryWrites=True,
                retryReads=True,
            )
            _client.admin.command("ping")
            _db = _client[MONGO_DB]
            _ensure_indexes(_db)
            log.info("Mongo connected: %s / %s", MONGO_DB, MONGO_URL.split("@")[-1])
            return _db
        except Exception as e:
            log.warning("Mongo connect failed: %s", e)
            return None


def _ensure_indexes(db: Database) -> None:
    try:
        db.users.create_index("plan_expiry")
        db.keys.create_index("expiry")
        db.referrals.create_index("code", sparse=True)
        db.referral_codes.create_index("user_id")
        db.checks.create_index([("user_id", 1), ("ts", -1)])
        try:
            db.checks.create_index("ts", expireAfterSeconds=60 * 60 * 24 * 14)
        except Exception:
            pass
        db.rank.create_index("charged")
    except Exception as e:
        log.warning("indexes: %s", e)


def _c(coll: str) -> Optional[Collection]:
    db = get_db()
    return db[coll] if db is not None else None


def boot() -> bool:
    """Call once at startup. Returns True if connected."""
    return get_db() is not None


# ══════════════════════════════════════════════════════════════════════
#  PREMIUM / PLANS
# ══════════════════════════════════════════════════════════════════════
def is_premium(user_id: int) -> bool:
    c = _c("users")
    if c is None:
        return False
    try:
        doc = c.find_one({"_id": user_id}, {"plan_expiry": 1})
    except Exception:
        return False
    if not doc:
        return False
    exp = doc.get("plan_expiry")
    if exp is None:
        return False
    try:
        if isinstance(exp, str):
            exp = datetime.fromisoformat(exp)
        if exp.tzinfo is not None:
            exp = exp.replace(tzinfo=None)
        return datetime.utcnow() < exp
    except Exception:
        return False


def get_cc_limit(user_id: int) -> int:
    c = _c("users")
    if c is None:
        return 0
    try:
        doc = c.find_one({"_id": user_id}, {"cc_limit": 1, "plan_expiry": 1})
    except Exception:
        return 0
    if not doc:
        return 0
    exp = doc.get("plan_expiry")
    if exp is None:
        return 0
    try:
        if isinstance(exp, str):
            exp = datetime.fromisoformat(exp)
        if exp.tzinfo is not None:
            exp = exp.replace(tzinfo=None)
        if datetime.utcnow() >= exp:
            return 0
    except Exception:
        return 0
    return int(doc.get("cc_limit", 0) or 0)


def add_premium(user_id: int, hours: int, cc_limit: int) -> None:
    c = _c("users")
    if c is None:
        return
    from datetime import timedelta
    now = datetime.utcnow()
    try:
        doc = c.find_one({"_id": user_id})
        base = now
        if doc:
            exp = doc.get("plan_expiry")
            if exp:
                try:
                    if isinstance(exp, str):
                        exp = datetime.fromisoformat(exp)
                    if exp.tzinfo is not None:
                        exp = exp.replace(tzinfo=None)
                    if exp > now:
                        base = exp
                except Exception:
                    pass
        new_exp = base + timedelta(hours=hours)
        cur_cc = int(doc.get("cc_limit", 0) if doc else 0)
        c.update_one(
            {"_id": user_id},
            {"$set": {
                "plan_expiry": new_exp.isoformat(),
                "cc_limit": max(cur_cc, cc_limit),
                "updated_at": now.isoformat(),
            }},
            upsert=True,
        )
    except Exception as e:
        log.warning("add_premium: %s", e)


def remove_premium(user_id: int) -> None:
    c = _c("users")
    if c is None:
        return
    try:
        c.update_one(
            {"_id": user_id},
            {"$unset": {"plan_expiry": "", "cc_limit": ""},
             "$set": {"updated_at": datetime.utcnow().isoformat()}},
        )
    except Exception as e:
        log.warning("remove_premium: %s", e)


def list_premium(limit: int = 5000) -> list[dict]:
    c = _c("users")
    if c is None:
        return []
    try:
        return list(c.find({"plan_expiry": {"$ne": None}}).limit(limit))
    except Exception:
        return []


def purge_expired() -> int:
    """Delete expired premium rows. Called hourly by bot cleanup loop."""
    c = _c("users")
    if c is None:
        return 0
    try:
        now_iso = datetime.utcnow().isoformat()
        r = c.update_many(
            {"plan_expiry": {"$ne": None, "$lt": now_iso}},
            {"$unset": {"plan_expiry": "", "cc_limit": ""}},
        )
        return r.modified_count
    except Exception:
        return 0


# ══════════════════════════════════════════════════════════════════════
#  PROXIES
# ══════════════════════════════════════════════════════════════════════
def load_user_proxies(user_id: int) -> list[str]:
    c = _c("proxies")
    if c is None:
        return []
    try:
        doc = c.find_one({"_id": user_id}, {"urls": 1})
        return list(doc.get("urls", [])) if doc else []
    except Exception:
        return []


def save_user_proxies(user_id: int, proxies: list[str]) -> None:
    c = _c("proxies")
    if c is None:
        return
    try:
        c.update_one(
            {"_id": user_id},
            {"$set": {"urls": list(proxies),
                      "updated_at": datetime.utcnow()}},
            upsert=True,
        )
    except Exception as e:
        log.warning("save_user_proxies: %s", e)


# ══════════════════════════════════════════════════════════════════════
#  KEYS
# ══════════════════════════════════════════════════════════════════════
def load_key(key: str) -> Optional[dict]:
    c = _c("keys")
    if c is None:
        return None
    try:
        return c.find_one({"_id": key})
    except Exception:
        return None


def save_key(key: str, data: dict) -> None:
    c = _c("keys")
    if c is None:
        return
    try:
        doc = dict(data)
        doc["_id"] = key
        c.replace_one({"_id": key}, doc, upsert=True)
    except Exception as e:
        log.warning("save_key: %s", e)


def delete_key(key: str) -> bool:
    c = _c("keys")
    if c is None:
        return False
    try:
        r = c.delete_one({"_id": key})
        return r.deleted_count > 0
    except Exception:
        return False


def list_keys(limit: int = 5000) -> list[dict]:
    c = _c("keys")
    if c is None:
        return []
    try:
        return list(c.find().limit(limit))
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════
#  RANK
# ══════════════════════════════════════════════════════════════════════
def increment_charged(user_id: int) -> None:
    c = _c("rank")
    if c is None:
        return
    try:
        c.update_one({"_id": user_id}, {"$inc": {"charged": 1}}, upsert=True)
    except Exception as e:
        log.warning("increment_charged: %s", e)


def get_charged_count(user_id: int) -> int:
    c = _c("rank")
    if c is None:
        return 0
    try:
        doc = c.find_one({"_id": user_id})
        return int(doc.get("charged", 0)) if doc else 0
    except Exception:
        return 0


def rank_all() -> list[tuple[int, int]]:
    c = _c("rank")
    if c is None:
        return []
    try:
        return [(d["_id"], int(d.get("charged", 0)))
                for d in c.find().sort("charged", -1).limit(10000)]
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════
#  SETTINGS
# ══════════════════════════════════════════════════════════════════════
_DEFAULT_SETTINGS = {
    "_id": "global",
    "maintenance": False,
    "threshold": 7.00,
    "min_price": 0.01,
}


def load_settings() -> dict:
    c = _c("settings")
    if c is None:
        return dict(_DEFAULT_SETTINGS)
    try:
        doc = c.find_one({"_id": "global"})
        if not doc:
            c.insert_one(dict(_DEFAULT_SETTINGS))
            return dict(_DEFAULT_SETTINGS)
        return doc
    except Exception:
        return dict(_DEFAULT_SETTINGS)


def save_settings(data: dict) -> None:
    c = _c("settings")
    if c is None:
        return
    try:
        doc = dict(data)
        doc["_id"] = "global"
        c.replace_one({"_id": "global"}, doc, upsert=True)
    except Exception as e:
        log.warning("save_settings: %s", e)


# ══════════════════════════════════════════════════════════════════════
#  REFERRALS
# ══════════════════════════════════════════════════════════════════════
def get_referral_user(user_id: int) -> Optional[dict]:
    c = _c("referrals")
    if c is None:
        return None
    try:
        return c.find_one({"_id": user_id})
    except Exception:
        return None


def save_referral_user(user_id: int, data: dict) -> None:
    c = _c("referrals")
    if c is None:
        return
    try:
        doc = dict(data)
        doc["_id"] = user_id
        c.replace_one({"_id": user_id}, doc, upsert=True)
    except Exception as e:
        log.warning("save_referral_user: %s", e)


def find_referral_by_code(code: str) -> Optional[int]:
    c = _c("referral_codes")
    if c is None:
        return None
    try:
        doc = c.find_one({"_id": (code or "").upper()})
        return int(doc["user_id"]) if doc else None
    except Exception:
        return None


def save_referral_code(code: str, user_id: int) -> None:
    c = _c("referral_codes")
    if c is None:
        return
    try:
        c.update_one({"_id": (code or "").upper()},
                     {"$set": {"user_id": user_id}},
                     upsert=True)
    except Exception as e:
        log.warning("save_referral_code: %s", e)


def list_referral_users(limit: int = 5000) -> list[dict]:
    c = _c("referrals")
    if c is None:
        return []
    try:
        return list(c.find().limit(limit))
    except Exception:
        return []


def list_referral_codes(limit: int = 5000) -> list[dict]:
    c = _c("referral_codes")
    if c is None:
        return []
    try:
        return list(c.find().limit(limit))
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════
#  STREAKS
# ══════════════════════════════════════════════════════════════════════
def get_streak(user_id: int) -> Optional[dict]:
    c = _c("streaks")
    if c is None:
        return None
    try:
        return c.find_one({"_id": user_id})
    except Exception:
        return None


def save_streak(user_id: int, data: dict) -> None:
    c = _c("streaks")
    if c is None:
        return
    try:
        doc = dict(data)
        doc["_id"] = user_id
        c.replace_one({"_id": user_id}, doc, upsert=True)
    except Exception as e:
        log.warning("save_streak: %s", e)


# ══════════════════════════════════════════════════════════════════════
#  CHECK HISTORY
# ══════════════════════════════════════════════════════════════════════
def log_check(user_id: int, card_last4: str, status: str,
              gateway: str = "Shopify", site: str = "",
              message: str = "", price: str = "") -> None:
    c = _c("checks")
    if c is None:
        return
    try:
        c.insert_one({
            "user_id": user_id,
            "card_last4": card_last4,
            "status": status,
            "gateway": gateway,
            "site": site,
            "message": (message or "")[:200],
            "price": price,
            "ts": datetime.utcnow(),
        })
    except Exception:
        pass


def history(user_id: int, limit: int = 15) -> list[dict]:
    c = _c("checks")
    if c is None:
        return []
    try:
        return list(c.find({"user_id": user_id}).sort("ts", -1).limit(limit))
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════
#  STATS
# ══════════════════════════════════════════════════════════════════════
def stats() -> dict:
    db = get_db()
    if db is None:
        return {}
    try:
        return {
            "users_total":     db.users.count_documents({}),
            "users_premium":   db.users.count_documents({"plan_expiry": {"$ne": None}}),
            "keys_total":      db.keys.count_documents({}),
            "proxies_users":   db.proxies.count_documents({}),
            "referrals_total": db.referrals.count_documents({}),
            "checks_total":    db.checks.count_documents({}),
        }
    except Exception:
        return {}
