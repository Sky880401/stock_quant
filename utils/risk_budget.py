"""
風險預算管理系統
- 日回撤限制 (Daily Max Drawdown)
- 週回撤限制 (Weekly Max Drawdown)
- 風險預算追蹤 (Risk Budget Tracking)
"""
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

RISK_LOG = "data/risk_log.json"

class RiskBudgetManager:
    def __init__(self, 
                 daily_max_drawdown=0.02,      # 2% 日回撤
                 weekly_max_drawdown=0.08,     # 8% 週回撤
                 max_consecutive_losses=3):    # 最多連續3次虧損
        self.daily_max_dd = daily_max_drawdown
        self.weekly_max_dd = weekly_max_drawdown
        self.max_consecutive_losses = max_consecutive_losses
        self.load_history()
    
    def load_history(self):
        """載入歷史交易記錄"""
        if os.path.exists(RISK_LOG):
            with open(RISK_LOG, 'r') as f:
                self.history = json.load(f)
        else:
            self.history = {
                "daily_pnl": [],
                "weekly_pnl": [],
                "consecutive_losses": 0,
                "last_trade_date": None
            }
    
    def save_history(self):
        """保存風險記錄"""
        os.makedirs(os.path.dirname(RISK_LOG), exist_ok=True)
        with open(RISK_LOG, 'w') as f:
            json.dump(self.history, f, indent=2)
    
    def record_trade_pnl(self, pnl, trade_date=None):
        """
        記錄交易損益
        pnl: 損益百分比 (例如 0.01 = +1%, -0.02 = -2%)
        """
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y-%m-%d")
        
        # 清理過期記錄
        self._cleanup_old_records()
        
        # 記錄日PnL
        self.history["daily_pnl"].append({"date": trade_date, "pnl": pnl})
        
        # 更新連續虧損計數
        if pnl < 0:
            self.history["consecutive_losses"] += 1
        else:
            self.history["consecutive_losses"] = 0
        
        self.save_history()
    
    def can_trade_today(self, initial_equity=100000):
        """檢查是否可以交易 - 今日是否超過回撤限制"""
        today = datetime.now().strftime("%Y-%m-%d")
        today_pnl = sum(t["pnl"] for t in self.history["daily_pnl"] if t["date"] == today)
        
        current_drawdown = abs(today_pnl) if today_pnl < 0 else 0
        
        if current_drawdown > self.daily_max_dd:
            return False, f"Today's drawdown {current_drawdown:.2%} exceeds limit {self.daily_max_dd:.2%}"
        
        return True, "OK"
    
    def can_trade_weekly(self, initial_equity=100000):
        """檢查是否可以交易 - 本週是否超過回撤限制"""
        today = datetime.now()
        week_start = today - timedelta(days=today.weekday())
        week_start_str = week_start.strftime("%Y-%m-%d")
        
        weekly_pnl = sum(t["pnl"] for t in self.history["daily_pnl"] 
                        if t["date"] >= week_start_str)
        
        current_drawdown = abs(weekly_pnl) if weekly_pnl < 0 else 0
        
        if current_drawdown > self.weekly_max_dd:
            return False, f"Weekly drawdown {current_drawdown:.2%} exceeds limit {self.weekly_max_dd:.2%}"
        
        return True, "OK"
    
    def check_consecutive_losses(self):
        """檢查是否觸發連續虧損限制"""
        if self.history["consecutive_losses"] >= self.max_consecutive_losses:
            return False, f"Hit max consecutive losses ({self.max_consecutive_losses})"
        
        return True, "OK"
    
    def get_trading_status(self):
        """取得完整交易狀態"""
        daily_ok, daily_msg = self.can_trade_today()
        weekly_ok, weekly_msg = self.can_trade_weekly()
        loss_ok, loss_msg = self.check_consecutive_losses()
        
        can_trade = daily_ok and weekly_ok and loss_ok
        
        return {
            "can_trade": can_trade,
            "daily_status": daily_msg,
            "weekly_status": weekly_msg,
            "loss_status": loss_msg,
            "consecutive_losses": self.history["consecutive_losses"]
        }
    
    def _cleanup_old_records(self, days_to_keep=30):
        """清理30天以前的記錄"""
        cutoff = (datetime.now() - timedelta(days=days_to_keep)).strftime("%Y-%m-%d")
        self.history["daily_pnl"] = [t for t in self.history["daily_pnl"] if t["date"] >= cutoff]


# 全局實例
_risk_manager = None

def get_risk_manager():
    """獲取全局風險管理器實例"""
    global _risk_manager
    if _risk_manager is None:
        _risk_manager = RiskBudgetManager()
    return _risk_manager

def check_trading_allowed(user_id: str = "default"):
    """主函數：檢查是否允許交易"""
    manager = get_risk_manager()
    status = manager.get_trading_status()
    
    if not status["can_trade"]:
        reasons = []
        if status["daily_status"] != "OK":
            reasons.append(status["daily_status"])
        if status["weekly_status"] != "OK":
            reasons.append(status["weekly_status"])
        if status["loss_status"] != "OK":
            reasons.append(status["loss_status"])
        
        return False, " | ".join(reasons)
    
    return True, "All checks passed"

if __name__ == "__main__":
    # 測試
    manager = RiskBudgetManager()
    print("Trading Status:", manager.get_trading_status())
    
    # 模擬記錄損益
    manager.record_trade_pnl(-0.01)  # -1%
    manager.record_trade_pnl(-0.015) # -1.5%
    print("After 2 losses:", manager.get_trading_status())
