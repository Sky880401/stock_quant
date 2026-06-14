import json
import os
from datetime import datetime, timezone

QUOTA_FILE = "data/user_quota.json"

# [修改] 定義三種額度
DEFAULT_LIMIT = 5    # 免費
BETA_LIMIT = 50      # BETA 測試員
PREMIUM_LIMIT = 100  # VIP 付費

def _empty(today):
    return {"date": today, "users": {}, "limits": {}, "bonus": {}}


def load_quota():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not os.path.exists(QUOTA_FILE):
        return _empty(today)
    try:
        with open(QUOTA_FILE, "r") as f:
            data = json.load(f)
        # 每天重置 used 計數，但保留 limits（每日上限）與 bonus（一次性加值，用完才歸零）
        if data.get("date") != today:
            return {"date": today, "users": {},
                    "limits": data.get("limits", {}), "bonus": data.get("bonus", {})}
        data.setdefault("limits", {})
        data.setdefault("bonus", {})
        return data
    except Exception:
        return _empty(today)


def _base_limit(data, user_str, tier):
    """該用戶的每日上限（自訂 limits 優先，否則依 tier）。"""
    if user_str in data.get("limits", {}):
        return data["limits"][user_str]
    if tier == 'premium':
        return PREMIUM_LIMIT
    if tier == 'beta':
        return BETA_LIMIT
    return DEFAULT_LIMIT

def save_quota(data):
    os.makedirs(os.path.dirname(QUOTA_FILE), exist_ok=True)
    # 原子寫：先寫暫存檔再 os.replace，避免寫到一半被中斷導致 user_quota.json 損毀，
    # 進而被 load_quota 的 except 當成重置 → 全站額度/加值一次蒸發。
    tmp = QUOTA_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=4)
    os.replace(tmp, QUOTA_FILE)

def check_quota_status(user_id, tier='free'):
    """
    檢查用戶今日額度狀態。剩餘 = 今日未用的每日額度 + 一次性 bonus。
    返回: (是否有剩餘額度, 剩餘次數, 每日上限)
    """
    data = load_quota()
    user_str = str(user_id)
    used = data["users"].get(user_str, 0)
    limit = _base_limit(data, user_str, tier)
    bonus = data.get("bonus", {}).get(user_str, 0)
    remaining = max(0, limit - used) + bonus
    return remaining > 0, remaining, limit

def deduct_quota(user_id, tier='free'):
    """扣一次額度：先扣每日額度，每日額度用完才扣一次性 bonus。"""
    data = load_quota()
    user_str = str(user_id)
    used = data["users"].get(user_str, 0)
    limit = _base_limit(data, user_str, tier)
    if used < limit:
        data["users"][user_str] = used + 1
    else:
        cur = data.setdefault("bonus", {}).get(user_str, 0)
        data["bonus"][user_str] = max(0, cur - 1)
    save_quota(data)
    return used + 1

def add_bonus(user_id, amount):
    """一次性加值：給用戶額外 amount 次查詢（用完才歸零、跨日保留，不動每日上限）。
    返回: 用戶目前的 bonus 餘額。
    """
    data = load_quota()
    user_str = str(user_id)
    cur = data.setdefault("bonus", {}).get(user_str, 0)
    new_bonus = max(0, cur + amount)
    data["bonus"][user_str] = new_bonus
    save_quota(data)
    return new_bonus

def admin_add_quota(user_id, amount, base_limit=DEFAULT_LIMIT):
    """（保留）永久調高每日上限。一次性加值請用 add_bonus。
    base_limit: 用戶身分組的基礎上限 (free/beta/premium)，
    避免送額度給高階會員時反而以 DEFAULT_LIMIT 起算降低其上限（audit 修正）。
    """
    data = load_quota()
    user_str = str(user_id)
    data.setdefault("limits", {})
    new_limit = data["limits"].get(user_str, base_limit) + amount
    data["limits"][user_str] = new_limit
    save_quota(data)
    return new_limit
