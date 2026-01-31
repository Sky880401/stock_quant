import json
import os
from datetime import datetime, timezone

QUOTA_FILE = "data/user_quota.json"

# [修改這裡] 設定額度
DEFAULT_LIMIT = 10    # <--- 免費仔每日額度 (在此修改)
PREMIUM_LIMIT = 100  # <--- VIP 每日額度

def load_quota():
    if not os.path.exists(QUOTA_FILE):
        return {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "users": {}}
    try:
        with open(QUOTA_FILE, "r") as f:
            data = json.load(f)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if data.get("date") != today:
                return {"date": today, "users": {}}
            return data
    except:
        return {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "users": {}}

def save_quota(data):
    os.makedirs(os.path.dirname(QUOTA_FILE), exist_ok=True)
    with open(QUOTA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def check_quota_status(user_id, is_premium=False):
    data = load_quota()
    user_str = str(user_id)
    used = data["users"].get(user_str, 0)
    limit = PREMIUM_LIMIT if is_premium else DEFAULT_LIMIT
    return used < limit, limit - used, limit

def deduct_quota(user_id):
    data = load_quota()
    user_str = str(user_id)
    used = data["users"].get(user_str, 0)
    data["users"][user_str] = used + 1
    save_quota(data)
    return used + 1

def admin_add_quota(user_id, amount):
    data = load_quota()
    user_str = str(user_id)
    used = data["users"].get(user_str, 0)
    data["users"][user_str] = max(0, used - amount)
    save_quota(data)
    return data["users"][user_str]
