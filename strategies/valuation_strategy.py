from .base_strategy import BaseStrategy
from .schema import StrategyResult

class ValuationStrategy(BaseStrategy):
    def analyze(self, df, extra_data=None):
        if not extra_data:
            return StrategyResult("UNKNOWN", 0.0, "No fundamental data", risk_penalty=0.3)

        ticker = extra_data.get("ticker", "UNKNOWN")
        pe = extra_data.get("pe_ratio")
        pb = extra_data.get("pb_ratio")

        # [關鍵優化] 數據缺失不再是 HOLD，而是 UNKNOWN + 扣分
        if pe is None and pb is None:
            return StrategyResult(
                signal="UNKNOWN",
                confidence=0.0,
                reason="Missing PE/PB Data",
                risk_penalty=0.25, # 資料缺失扣分
                assumptions=["High uncertainty due to missing data"]
            )

        # 產業閾值 (簡化版)
        thresholds = {"pe_buy": 15, "pe_sell": 25, "pb_buy": 1.5, "pb_sell": 4.0}
        
        # ... (這裡省略中間的產業判斷邏輯，保持原樣即可) ...
        # 為了演示方便，我們直接用簡單邏輯，您可以用之前 v2.1 的完整邏輯覆蓋這裡
        
        score = 0
        if pe and pe < 15: score += 1
        if pe and pe > 25: score -= 1
        if pb and pb < 1.5: score += 1
        if pb and pb > 4.0: score -= 1

        signal = "HOLD"
        risk_penalty = 0.0
        
        if score >= 1: signal = "BUY"
        elif score <= -1: signal = "SELL"
        
        return StrategyResult(
            signal=signal,
            confidence=0.7,
            reason=f"Score: {score}",
            risk_penalty=0.0, # 數據完整，無扣分
            raw_data={"pe": pe, "pb": pb}
        )
