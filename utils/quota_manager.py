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
        return {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "users": {},
            "limits": {}  # 新增：存儲用戶自訂額度
        }
    try:
        with open(QUOTA_FILE, "r") as f:
            data = json.load(f)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            # 每天重置used計數，但保留limits
            if data.get("date") != today:
                return {
                    "date": today,
                    "users": {},
                    "limits": data.get("limits", {})  # 保留用戶的自訂額度
                }
            # 確保limits字段存在
            if "limits" not in data:
                data["limits"] = {}
            return data
    except:
        return {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "users": {},
            "limits": {}
        }

def save_quota(data):
    os.makedirs(os.path.dirname(QUOTA_FILE), exist_ok=True)
    with open(QUOTA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def check_quota_status(user_id, tier='free'):
    """
    檢查用戶今日額度狀態
    返回: (是否有剩餘額度, 剩餘次數, 上限)
    """
    data = load_quota()
    user_str = str(user_id)
    used = data["users"].get(user_str, 0)
    
    # 優先檢查用戶自訂額度（來自!gift命令）
    if user_str in data.get("limits", {}):
        limit = data["limits"][user_str]
    # 否則根據tier判斷
    elif tier == 'premium':
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
    """
    管理員增加用戶額度
    邏輯：增加用戶的上限額度（不是減少已用次數）
    返回: 用戶新的總額度上限
    """
    data = load_quota()
    user_str = str(user_id)
    
    # 初始化limits字典
    if "limits" not in data:
        data["limits"] = {}
    
    # 獲取用戶當前的基礎上限（如果有自訂額度則使用，否則使用默認值）
    current_limit = data["limits"].get(user_str, DEFAULT_LIMIT)
    
    # 增加額度
    new_limit = current_limit + amount
    data["limits"][user_str] = new_limit
    
    save_quota(data)
    return new_limit
