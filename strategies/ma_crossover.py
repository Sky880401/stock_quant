import talib
import pandas as pd
import numpy as np
from .base_strategy import BaseStrategy
from .schema import StrategyResult

class MACrossoverStrategy(BaseStrategy):
    def analyze(self, df: pd.DataFrame, extra_data: dict = None) -> StrategyResult:
        if df is None or len(df) < 60:
            return StrategyResult("HOLD", 0.0, "Insufficient data")

        close_prices = df['Close'].values
        
        # === 計算指標 ===
        ma5 = talib.SMA(close_prices, timeperiod=5)
        ma20 = talib.SMA(close_prices, timeperiod=20)
        ma60 = talib.SMA(close_prices, timeperiod=60)
        # [新增] RSI 指標
        rsi = talib.RSI(close_prices, timeperiod=14)

        c_ma5, c_ma20, c_ma60 = ma5[-1], ma20[-1], ma60[-1]
        c_rsi = rsi[-1] if not np.isnan(rsi[-1]) else 50.0

        # === 邏輯判斷 ===
        signal = "HOLD"
        confidence = 0.5
        reason = "Neutral"
        score = 0
        assumptions = []

        # MA 邏輯
        if c_ma5 > c_ma20 > c_ma60:
            score += 2
            assumptions.append("MA Bullish Alignment")
        elif c_ma5 < c_ma20 < c_ma60:
            score -= 2
            assumptions.append("MA Bearish Alignment")
        elif c_ma5 > c_ma20 and ma5[-2] <= ma20[-2]:
            score += 1
            assumptions.append("MA Golden Cross")
        elif c_ma5 < c_ma20 and ma5[-2] >= ma20[-2]:
            score -= 1
            assumptions.append("MA Death Cross")

        # [新增] RSI 濾網邏輯
        if c_rsi > 75:
            score -= 0.5 # 過熱扣分
            assumptions.append(f"RSI Overbought ({c_rsi:.1f})")
        elif c_rsi < 25:
            score += 0.5 # 超賣加分 (可能有反彈)
            assumptions.append(f"RSI Oversold ({c_rsi:.1f})")
        else:
            assumptions.append(f"RSI Neutral ({c_rsi:.1f})")

        # 最終訊號
        if score >= 1.5:
            signal = "BUY"
            confidence = 0.8
            reason = "Strong Bullish Techs"
        elif score <= -1.5:
            signal = "SELL"
            confidence = 0.8
            reason = "Strong Bearish Techs"
        elif score > 0:
            signal = "BUY"
            confidence = 0.6
            reason = "Weak Bullish"
        elif score < 0:
            signal = "SELL"
            confidence = 0.6
            reason = "Weak Bearish"

        return StrategyResult(
            signal=signal,
            confidence=confidence,
            reason=reason,
            scores={"tech_score": score, "rsi": c_rsi},
            assumptions=assumptions,
            raw_data={"price": float(close_prices[-1]), "ma5": float(c_ma5), "rsi": float(c_rsi)}
        )
