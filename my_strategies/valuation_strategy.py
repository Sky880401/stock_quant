from .base_strategy import BaseStrategy
import pandas as pd

class ValuationStrategy(BaseStrategy):
    # 👇 關鍵修正：加入 __init__ 來接收參數
    def __init__(self, threshold=0.8):
        self.threshold = threshold

    def analyze(self, df: pd.DataFrame) -> dict:
        # 簡單範例：假設我們用本益比 (PE) 或其他指標
        # 這裡先示範用股價位置判斷 (Price vs 過去一年高點)
        
        if df.empty:
            return {"signal": "HOLD", "confidence": 0}

        highest_price = df['High'].max()
        current_price = df['Close'].iloc[-1]
        
        # 如果目前價格低於最高價的 80% (threshold)，視為便宜
        position = current_price / highest_price
        
        if position < self.threshold:
            return {
                "signal": "BUY",
                "confidence": 70,
                "reason": f"價格處於低檔 (距高點 {(1-position)*100:.1f}%)"
            }
        elif position > 0.95:
            return {
                "signal": "SELL",
                "confidence": 60,
                "reason": "價格接近歷史高點"
            }
        else:
            return {
                "signal": "HOLD",
                "confidence": 50,
                "reason": "估值合理區間"
            }