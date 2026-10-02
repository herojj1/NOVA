# database.py
import os
import datetime
from motor.motor_asyncio import AsyncIOMotorClient

# MongoDB Connection
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "razor_x_bot")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

# Collections
users_col = db["users"]
keys_col = db["keys"]
proxies_col = db["proxies"]
sites_col = db["sites"]
cards_col = db["cards"]
global_sites_col = db["global_sites"]
joined_col = db["joined_users"]


async def init_db():
    """𝗜𝗻𝗶𝘁𝗶𝗮𝗹𝗶𝘇𝗲 𝗱𝗮𝘁𝗮𝗯𝗮𝘀𝗲 𝘄𝗶𝘁𝗵 𝗶𝗻𝗱𝗲𝘅𝗲𝘀"""
    try:
        await users_col.create_index("user_id", unique=True)
        await keys_col.create_index("key", unique=True)
        await proxies_col.create_index([("user_id", 1), ("proxy_url", 1)])
        await sites_col.create_index([("user_id", 1), ("site", 1)])
        await global_sites_col.create_index("site", unique=True)
        await cards_col.create_index("created_at")
        await joined_col.create_index("user_id", unique=True)
        print("✅ 𝗥𝗔𝗭𝗢𝗥 𝗫 𝗗𝗮𝘁𝗮𝗯𝗮𝘀𝗲 𝗶𝗻𝗶𝘁𝗶𝗮𝗹𝗶𝘇𝗲𝗱 𝘀𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆!")
    except Exception as e:
        print(f"⚠️ 𝗗𝗕 𝗶𝗻𝗶𝘁 𝘄𝗮𝗿𝗻𝗶𝗻𝗴: {e}")


# ============ 𝗨𝗦𝗘𝗥 𝗠𝗔𝗡𝗔𝗚𝗘𝗠𝗘𝗡𝗧 ============

async def ensure_user(user_id: int):
    """𝗘𝗻𝘀𝘂𝗿𝗲 𝘂𝘀𝗲𝗿 𝗲𝘅𝗶𝘀𝘁𝘀 𝗶𝗻 𝗗𝗕"""
    existing = await users_col.find_one({"user_id": user_id})
    if not existing:
        await users_col.insert_one({
            "user_id": user_id,
            "plan": "Bronze",
            "expiry": None,
            "banned": False,
            "banned_by": None,
            "created_at": datetime.datetime.utcnow()
        })


async def get_user_plan(user_id: int) -> str:
    """𝗚𝗲𝘁 𝘂𝘀𝗲𝗿'𝘀 𝗰𝘂𝗿𝗿𝗲𝗻𝘁 𝗽𝗹𝗮𝗻"""
    user = await users_col.find_one({"user_id": user_id})
    if not user:
        return "Bronze"

    plan = user.get("plan", "Bronze")
    expiry = user.get("expiry")

    if expiry and datetime.datetime.utcnow() > expiry:
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {"plan": "Bronze", "expiry": None}}
        )
        return "Bronze"

    return plan


async def set_user_plan(user_id: int, plan: str, days: int = 0):
    """𝗦𝗲𝘁 𝘂𝘀𝗲𝗿 𝗽𝗹𝗮𝗻 𝘄𝗶𝘁𝗵 𝗲𝘅𝗽𝗶𝗿𝘆"""
    expiry = None
    if days > 0:
        expiry = datetime.datetime.utcnow() + datetime.timedelta(days=days)

    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {
            "plan": plan,
            "expiry": expiry,
            "premium_days": days,
            "updated_at": datetime.datetime.utcnow()
        }},
        upsert=True
    )


async def is_premium_user(user_id: int) -> bool:
    """𝗖𝗵𝗲𝗰𝗸 𝗶𝗳 𝘂𝘀𝗲𝗿 𝗵𝗮𝘀 𝗽𝗿𝗲𝗺𝗶𝘂𝗺 𝗽𝗹𝗮𝗻"""
    plan = await get_user_plan(user_id)
    return plan in ["Core", "Elite", "Root", "X"]


async def is_banned_user(user_id: int) -> bool:
    """𝗖𝗵𝗲𝗰𝗸 𝗶𝗳 𝘂𝘀𝗲𝗿 𝗶𝘀 𝗯𝗮𝗻𝗻𝗲𝗱"""
    user = await users_col.find_one({"user_id": user_id})
    return user.get("banned", False) if user else False


# ============ 𝗝𝗢𝗜𝗡 𝗩𝗘𝗥𝗜𝗙𝗜𝗖𝗔𝗧𝗜𝗢𝗡 𝗖𝗔𝗖𝗛𝗘 ============

async def mark_user_joined(user_id: int):
    """𝗠𝗮𝗿𝗸 𝗮 𝘂𝘀𝗲𝗿 𝗮𝘀 𝗵𝗮𝘃𝗶𝗻𝗴 𝗷𝗼𝗶𝗻𝗲𝗱 𝗿𝗲𝗾𝘂𝗶𝗿𝗲𝗱 𝗰𝗵𝗮𝘁𝘀"""
    await joined_col.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "joined_at": datetime.datetime.utcnow()}},
        upsert=True
    )


async def is_user_marked_joined(user_id: int) -> bool:
    """𝗖𝗵𝗲𝗰𝗸 𝗶𝗳 𝘂𝘀𝗲𝗿 𝗶𝘀 𝗺𝗮𝗿𝗸𝗲𝗱 𝗮𝘀 𝗷𝗼𝗶𝗻𝗲𝗱"""
    doc = await joined_col.find_one({"user_id": user_id})
    return doc is not None


async def remove_joined_mark(user_id: int):
    """𝗥𝗲𝗺𝗼𝘃𝗲 𝘁𝗵𝗲 𝗷𝗼𝗶𝗻𝗲𝗱 𝗺𝗮𝗿𝗸"""
    await joined_col.delete_one({"user_id": user_id})


# ============ 𝗣𝗥𝗢𝗫𝗬 𝗠𝗔𝗡𝗔𝗚𝗘𝗠𝗘𝗡𝗧 ============

async def add_proxy_db(user_id: int, proxy_data: dict):
    """𝗔𝗱𝗱 𝗽𝗿𝗼𝘅𝘆 𝗳𝗼𝗿 𝘂𝘀𝗲𝗿"""
    proxy_doc = {
        "user_id": user_id,
        "ip": proxy_data.get("ip"),
        "port": proxy_data.get("port"),
        "username": proxy_data.get("username"),
        "password": proxy_data.get("password"),
        "proxy_url": proxy_data.get("proxy_url"),
        "proxy_type": proxy_data.get("type", "http"),
        "added_at": datetime.datetime.utcnow()
    }
    await proxies_col.insert_one(proxy_doc)


async def get_all_user_proxies(user_id: int):
    """𝗚𝗲𝘁 𝗮𝗹𝗹 𝗽𝗿𝗼𝘅𝗶𝗲𝘀 𝗳𝗼𝗿 𝘂𝘀𝗲𝗿"""
    cursor = proxies_col.find({"user_id": user_id}).sort("added_at", 1)
    return await cursor.to_list(length=200)


async def get_proxy_count(user_id: int) -> int:
    """𝗚𝗲𝘁 𝘂𝘀𝗲𝗿'𝘀 𝗽𝗿𝗼𝘅𝘆 𝗰𝗼𝘂𝗻𝘁"""
    return await proxies_col.count_documents({"user_id": user_id})


async def get_random_proxy(user_id: int):
    """𝗚𝗲𝘁 𝗿𝗮𝗻𝗱𝗼𝗺 𝗽𝗿𝗼𝘅𝘆 𝗳𝗼𝗿 𝘂𝘀𝗲𝗿"""
    import random
    proxies = await get_all_user_proxies(user_id)
    if not proxies:
        return None
    return random.choice(proxies)


async def remove_proxy_by_index(user_id: int, index: int):
    """𝗥𝗲𝗺𝗼𝘃𝗲 𝗽𝗿𝗼𝘅𝘆 𝗯𝘆 𝗶𝗻𝗱𝗲𝘅"""
    proxies = await get_all_user_proxies(user_id)
    if 0 <= index < len(proxies):
        proxy = proxies[index]
        await proxies_col.delete_one({"_id": proxy["_id"]})
        return proxy
    return None


async def remove_proxy_by_url(user_id: int, proxy_url: str):
    """𝗥𝗲𝗺𝗼𝘃𝗲 𝗽𝗿𝗼𝘅𝘆 𝗯𝘆 𝗨𝗥𝗟"""
    result = await proxies_col.delete_one({
        "user_id": user_id,
        "proxy_url": proxy_url
    })
    return result.deleted_count > 0


async def clear_all_proxies(user_id: int) -> int:
    """𝗖𝗹𝗲𝗮𝗿 𝗮𝗹𝗹 𝗽𝗿𝗼𝘅𝗶𝗲𝘀 𝗳𝗼𝗿 𝘂𝘀𝗲𝗿"""
    result = await proxies_col.delete_many({"user_id": user_id})
    return result.deleted_count


# ============ 𝗦𝗜𝗧𝗘 𝗠𝗔𝗡𝗔𝗚𝗘𝗠𝗘𝗡𝗧 ============

async def add_site_db(user_id: int, site: str) -> bool:
    """𝗔𝗱𝗱 𝘀𝗶𝘁𝗲 𝗳𝗼𝗿 𝘂𝘀𝗲𝗿"""
    existing = await sites_col.find_one({"user_id": user_id, "site": site})
    if existing:
        return False

    await sites_col.insert_one({
        "user_id": user_id,
        "site": site,
        "added_at": datetime.datetime.utcnow()
    })
    return True


async def get_user_sites(user_id: int):
    """𝗚𝗲𝘁 𝗮𝗹𝗹 𝘀𝗶𝘁𝗲𝘀 𝗳𝗼𝗿 𝘂𝘀𝗲𝗿"""
    cursor = sites_col.find({"user_id": user_id})
    docs = await cursor.to_list(length=50000)
    return [doc["site"] for doc in docs]


async def remove_site_db(user_id: int, site: str) -> bool:
    """𝗥𝗲𝗺𝗼𝘃𝗲 𝘀𝗶𝘁𝗲 𝗳𝗼𝗿 𝘂𝘀𝗲𝗿"""
    result = await sites_col.delete_one({"user_id": user_id, "site": site})
    return result.deleted_count > 0


# ============ 𝗚𝗟𝗢𝗕𝗔𝗟 𝗦𝗜𝗧𝗘𝗦 ============

async def add_global_site(site: str) -> bool:
    """𝗔𝗱𝗱 𝗴𝗹𝗼𝗯𝗮𝗹 𝘀𝗶𝘁𝗲"""
    try:
        await global_sites_col.insert_one({
            "site": site,
            "added_at": datetime.datetime.utcnow()
        })
        return True
    except:
        return False


async def get_global_sites():
    """𝗚𝗲𝘁 𝗮𝗹𝗹 𝗴𝗹𝗼𝗯𝗮𝗹 𝘀𝗶𝘁𝗲𝘀"""
    cursor = global_sites_col.find()
    docs = await cursor.to_list(length=10000)
    return [doc["site"] for doc in docs]


async def remove_global_site(site: str) -> bool:
    """𝗥𝗲𝗺𝗼𝘃𝗲 𝗴𝗹𝗼𝗯𝗮𝗹 𝘀𝗶𝘁𝗲"""
    result = await global_sites_col.delete_one({"site": site})
    return result.deleted_count > 0

# ============ 𝗦𝗧𝗔𝗧𝗜𝗦𝗧𝗜𝗖𝗦 ============

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
        {"$project": {"user_id": "$_id", "cnt": 1, "_id": 0}}
    ]
    return await sites_col.aggregate(pipeline).to_list(length=1000)


async def get_all_sites_detail():
    cursor = sites_col.find().sort("user_id", 1)
    return await cursor.to_list(length=10000)
