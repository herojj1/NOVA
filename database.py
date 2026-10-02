# database.py — NOVA Bot
import os
import datetime
from motor.motor_asyncio import AsyncIOMotorClient

# ── MongoDB connection ──
MONGO_URL = os.getenv("MONGO_URL", "mongodb+srv://Hero:jasini12345@cluster0.9wykfhr.mongodb.net/?appName=Cluster0")
DB_NAME   = os.getenv("DB_NAME", "nova_bot")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

# ── Collections ──
users_col        = db["users"]
keys_col         = db["keys"]
proxies_col      = db["proxies"]
sites_col        = db["sites"]
cards_col        = db["cards"]
global_sites_col = db["global_sites"]
joined_col       = db["joined_users"]


# ══════════════════════════════════════════════════════════════════════════
#  INIT
# ══════════════════════════════════════════════════════════════════════════

async def init_db():
    try:
        await users_col.create_index("user_id", unique=True)
        await keys_col.create_index("key", unique=True)
        await proxies_col.create_index([("user_id", 1), ("proxy_url", 1)])
        await sites_col.create_index([("user_id", 1), ("site", 1)])
        await global_sites_col.create_index("site", unique=True)
        await cards_col.create_index("created_at")
        await joined_col.create_index("user_id", unique=True)
        print("✅ NOVA Database initialized successfully!")
    except Exception as e:
        print(f"⚠️ DB init warning: {e}")


# ══════════════════════════════════════════════════════════════════════════
#  USERS
# ══════════════════════════════════════════════════════════════════════════

async def ensure_user(user_id: int):
    existing = await users_col.find_one({"user_id": user_id})
    if not existing:
        await users_col.insert_one({
            "user_id": user_id,
            "plan": "Bronze",
            "expiry": None,
            "banned": False,
            "banned_by": None,
            "total_charged": 0,
            "created_at": datetime.datetime.utcnow(),
        })


async def get_user_plan(user_id: int) -> str:
    user = await users_col.find_one({"user_id": user_id})
    if not user:
        return "Bronze"
    plan = user.get("plan", "Bronze")
    expiry = user.get("expiry")
    if expiry and datetime.datetime.utcnow() > expiry:
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {"plan": "Bronze", "expiry": None}},
        )
        return "Bronze"
    return plan


async def set_user_plan(user_id: int, plan: str, days: int = 0):
    expiry = None
    if days > 0:
        expiry = datetime.datetime.utcnow() + datetime.timedelta(days=days)
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {
            "plan": plan,
            "expiry": expiry,
            "premium_days": days,
            "updated_at": datetime.datetime.utcnow(),
        }},
        upsert=True,
    )


async def is_premium_user(user_id: int) -> bool:
    plan = await get_user_plan(user_id)
    return plan in ["Core", "Elite", "Root", "X"]


async def is_banned_user(user_id: int) -> bool:
    user = await users_col.find_one({"user_id": user_id})
    return user.get("banned", False) if user else False


async def increment_user_charged(user_id: int):
    await users_col.update_one(
        {"user_id": user_id},
        {"$inc": {"total_charged": 1}},
        upsert=True,
    )


# ══════════════════════════════════════════════════════════════════════════
#  JOIN VERIFICATION CACHE
# ══════════════════════════════════════════════════════════════════════════

async def mark_user_joined(user_id: int):
    await joined_col.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "joined_at": datetime.datetime.utcnow()}},
        upsert=True,
    )


async def is_user_marked_joined(user_id: int) -> bool:
    doc = await joined_col.find_one({"user_id": user_id})
    return doc is not None


async def remove_joined_mark(user_id: int):
    await joined_col.delete_one({"user_id": user_id})


# ══════════════════════════════════════════════════════════════════════════
#  PROXIES
# ══════════════════════════════════════════════════════════════════════════

async def add_proxy_db(user_id: int, proxy_data: dict):
    await proxies_col.insert_one({
        "user_id": user_id,
        "ip": proxy_data.get("ip"),
        "port": proxy_data.get("port"),
        "username": proxy_data.get("username"),
        "password": proxy_data.get("password"),
        "proxy_url": proxy_data.get("proxy_url"),
        "proxy_type": proxy_data.get("type", "http"),
        "added_at": datetime.datetime.utcnow(),
    })


async def get_all_user_proxies(user_id: int):
    cursor = proxies_col.find({"user_id": user_id}).sort("added_at", 1)
    return await cursor.to_list(length=200)


async def get_proxy_count(user_id: int) -> int:
    return await proxies_col.count_documents({"user_id": user_id})


async def get_random_proxy(user_id: int):
    import random
    proxies = await get_all_user_proxies(user_id)
    return random.choice(proxies) if proxies else None


async def remove_proxy_by_index(user_id: int, index: int):
    proxies = await get_all_user_proxies(user_id)
    if 0 <= index < len(proxies):
        proxy = proxies[index]
        await proxies_col.delete_one({"_id": proxy["_id"]})
        return proxy
    return None


async def remove_proxy_by_url(user_id: int, proxy_url: str):
    result = await proxies_col.delete_one({"user_id": user_id, "proxy_url": proxy_url})
    return result.deleted_count > 0


async def clear_all_proxies(user_id: int) -> int:
    result = await proxies_col.delete_many({"user_id": user_id})
    return result.deleted_count


# ══════════════════════════════════════════════════════════════════════════
#  SITES
# ══════════════════════════════════════════════════════════════════════════

async def add_site_db(user_id: int, site: str) -> bool:
    existing = await sites_col.find_one({"user_id": user_id, "site": site})
    if existing:
        return False
    await sites_col.insert_one({
        "user_id": user_id,
        "site": site,
        "added_at": datetime.datetime.utcnow(),
    })
    return True


async def get_user_sites(user_id: int):
    cursor = sites_col.find({"user_id": user_id})
    docs = await cursor.to_list(length=50000)
    return [doc["site"] for doc in docs]


async def remove_site_db(user_id: int, site: str) -> bool:
    result = await sites_col.delete_one({"user_id": user_id, "site": site})
    return result.deleted_count > 0


# ══════════════════════════════════════════════════════════════════════════
#  GLOBAL SITES
# ══════════════════════════════════════════════════════════════════════════

async def add_global_site(site: str) -> bool:
    try:
        await global_sites_col.insert_one({
            "site": site,
            "added_at": datetime.datetime.utcnow(),
        })
        return True
    except Exception:
        return False


async def get_global_sites():
    cursor = global_sites_col.find()
    docs = await cursor.to_list(length=10000)
    return [doc["site"] for doc in docs]


async def remove_global_site(site: str) -> bool:
    result = await global_sites_col.delete_one({"site": site})
    return result.deleted_count > 0


# ══════════════════════════════════════════════════════════════════════════
#  CARD HISTORY
# ══════════════════════════════════════════════════════════════════════════

async def save_card_to_db(card: str, status: str, response: str,
                          gateway: str = "", price: str = "-"):
    try:
        await cards_col.insert_one({
            "card": card,
            "status": status,
            "response": response,
            "gateway": gateway,
            "price": price,
            "created_at": datetime.datetime.utcnow(),
        })
    except Exception:
        pass


async def get_total_cards_count() -> int:
    return await cards_col.count_documents({})


async def get_charged_count() -> int:
    return await cards_col.count_documents({"status": "CHARGED"})


async def get_approved_count() -> int:
    return await cards_col.count_documents({"status": "APPROVED"})


# ══════════════════════════════════════════════════════════════════════════
#  STATISTICS
# ══════════════════════════════════════════════════════════════════════════

async def get_total_users() -> int:
    return await users_col.count_documents({})


async def get_premium_count() -> int:
    return await users_col.count_documents({
        "plan": {"$in": ["Core", "Elite", "Root", "X"]}
    })


async def get_all_premium_users():
    cursor = users_col.find({"plan": {"$in": ["Core", "Elite", "Root", "X"]}})
    return await cursor.to_list(length=1000)


async def get_total_sites_count() -> int:
    return await sites_col.count_documents({})


async def get_users_with_sites() -> int:
    pipeline = [{"$group": {"_id": "$user_id"}}]
    result = await sites_col.aggregate(pipeline).to_list(length=10000)
    return len(result)


async def get_sites_per_user():
    pipeline = [
        {"$group": {"_id": "$user_id", "cnt": {"$sum": 1}}},
        {"$project": {"user_id": "$_id", "cnt": 1, "_id": 0}},
    ]
    return await sites_col.aggregate(pipeline).to_list(length=1000)


async def get_all_sites_detail():
    cursor = sites_col.find().sort("user_id", 1)
    return await cursor.to_list(length=10000)
