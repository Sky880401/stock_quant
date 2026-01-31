import json
import os
from datetime import datetime, timezone

QUOTA_FILE = "data/user_quota.json"

# [修改] 定義三種額度
DEFAULT_LIMIT = 5    # 免費
BETA_LIMIT = 50      # BETA 測試員
PREMIUM_LIMIT = 100  # VIP 付費

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

# [修改] 改用 tier 來判斷額度
def check_quota_status(user_id, tier='free'):
    data = load_quota()
    user_str = str(user_id)
    used = data["users"].get(user_str, 0)
    
    # 判斷額度上限
    if tier == 'premium':
        limit = PREMIUM_LIMIT
    elif tier == 'beta':
        limit = BETA_LIMIT
    else:
        limit = DEFAULT_LIMIT
        
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
