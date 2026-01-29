from .base_strategy import BaseStrategy

class ValuationStrategy(BaseStrategy):
    def analyze(self, df, extra_data=None):
        if not extra_data:
            return {"signal": "HOLD", "confidence": 0.0, "reason": "無基本面數據", "data": {"PB_Ratio": "N/A"}}
        
        pb_ratio = extra_data.get("priceToBook")

        # 檢查 PB 是否存在且為數字
        if pb_ratio is None or not isinstance(pb_ratio, (int, float)):
            return {
                "signal": "HOLD", 
                "confidence": 0.0, 
                "reason": "無法取得 PB Ratio", 
                "data": {"PB_Ratio": "N/A"}
            }

        signal = "HOLD"
        reason = f"股價淨值比合理 ({pb_ratio:.2f})"
        confidence = 0.5

        if pb_ratio < 1.0:
            signal = "BUY"
            reason = f"價值低估 (PB {pb_ratio:.2f} < 1.0)"
            confidence = 0.9
        elif pb_ratio > 1.5:
            signal = "SELL"
            reason = f"估值過高 (PB {pb_ratio:.2f} > 1.5)"
            confidence = 0.7

        return {
            "signal": signal,
            "confidence": confidence,
            "reason": reason,
            "data": {"PB_Ratio": float(pb_ratio)}
        }