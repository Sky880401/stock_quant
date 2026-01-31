import talib
import pandas as pd
import numpy as np
from .base_strategy import BaseStrategy
from .schema import StrategyResult

class MACrossoverStrategy(BaseStrategy):
    def analyze(self, df: pd.DataFrame, extra_data: dict = None) -> StrategyResult:
        # 1. 數據檢查
        if df is None or len(df) < 60:
            return StrategyResult(
                signal="HOLD", 
                confidence=0.0, 
                reason="Insufficient data (Need > 60 bars)"
            )

        # 2. 計算均線
        close_prices = df['Close'].values
        ma5 = talib.SMA(close_prices, timeperiod=5)
        ma20 = talib.SMA(close_prices, timeperiod=20)
        ma60 = talib.SMA(close_prices, timeperiod=60)

        # 取得最新一筆數據
        curr_price = close_prices[-1]
        c_ma5 = ma5[-1]
        c_ma20 = ma20[-1]
        c_ma60 = ma60[-1]

        # 3. 訊號判斷邏輯
        signal = "HOLD"
        confidence = 0.5
        reason = "Neutral Trend"
        score = 0
        assumptions = []

        # 檢查 NaN
        if np.isnan(c_ma60):
            return StrategyResult("HOLD", 0.0, "Calculating MA...")

        # 多頭排列 (Bullish Alignment)
        if c_ma5 > c_ma20 > c_ma60:
            signal = "BUY"
            score = 2.0
            confidence = 0.8
            reason = "Bullish Alignment (MA5 > MA20 > MA60)"
            assumptions.append("Short-term momentum is strong")
            assumptions.append("Long-term trend is up")
        
        # 空頭排列 (Bearish Alignment)
        elif c_ma5 < c_ma20 < c_ma60:
            signal = "SELL"
            score = -2.0
            confidence = 0.8
            reason = "Bearish Alignment (MA5 < MA20 < MA60)"
            assumptions.append("Downward pressure confirmed")
        
        # 黃金交叉 (Golden Cross)
        elif c_ma5 > c_ma20 and ma5[-2] <= ma20[-2]:
            signal = "BUY"
            score = 1.0
            confidence = 0.6
            reason = "Golden Cross (MA5 crossed above MA20)"
        
        # 死亡交叉 (Death Cross)
        elif c_ma5 < c_ma20 and ma5[-2] >= ma20[-2]:
            signal = "SELL"
            score = -1.0
            confidence = 0.6
            reason = "Death Cross (MA5 crossed below MA20)"

        # 4. 回傳標準物件
        return StrategyResult(
            signal=signal,
            confidence=confidence,
            reason=reason,
            scores={"tech_score": score},
            assumptions=assumptions,
            raw_data={
                "price": float(curr_price),
                "ma5": float(c_ma5),
                "ma20": float(c_ma20),
                "ma60": float(c_ma60)
            }
        )
