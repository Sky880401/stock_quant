from .base_strategy import BaseStrategy

class ValuationStrategy(BaseStrategy):
    def analyze(self, df, extra_data=None):
        # 防禦性編程：確保有數據
        if df is None or df.empty:
            return {"signal": "HOLD", "reason": "No price data"}
        
        if not extra_data:
            return {"signal": "HOLD", "reason": "No fundamental data provided"}

        # 提取基本面數據 (注意：Yahoo Finance 有時回傳 None)
        pe = extra_data.get("pe_ratio")
        pb = extra_data.get("pb_ratio")

        # 簡單的價值判斷邏輯
        signal = "HOLD"
        reason = f"PE: {pe}, PB: {pb}"

        if pe and pb:
            if pe < 15 and pb < 1.5:
                signal = "BUY"
                reason = f"Undervalued (PE={pe:.2f} < 15, PB={pb:.2f} < 1.5)"
            elif pe > 25 or pb > 4.0:
                signal = "SELL"
                reason = f"Overvalued (PE={pe:.2f} > 25, PB={pb:.2f} > 4.0)"
        else:
            reason = "Insufficient fundamental data (PE/PB missing)"

        return {
            "signal": signal,
            "reason": reason,
            "data": {"pe": pe, "pb": pb}
        }
