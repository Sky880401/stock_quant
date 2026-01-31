import talib
import pandas as pd
import numpy as np
from .base_strategy import BaseStrategy
from .schema import StrategyResult

class MACrossoverStrategy(BaseStrategy):
    def analyze(self, df: pd.DataFrame, extra_data: dict = None) -> StrategyResult:
        if df is None or len(df) < 60:
            return StrategyResult("UNKNOWN", 0.0, "Insufficient data", risk_penalty=0.5)

        close_prices = df['Close'].values
        ma5 = talib.SMA(close_prices, timeperiod=5)
        ma20 = talib.SMA(close_prices, timeperiod=20)
        ma60 = talib.SMA(close_prices, timeperiod=60)
        rsi = talib.RSI(close_prices, timeperiod=14)

        c_close = close_prices[-1]
        c_ma5, c_ma20, c_ma60 = ma5[-1], ma20[-1], ma60[-1]
        c_rsi = rsi[-1] if not np.isnan(rsi[-1]) else 50.0

        # === 訊號判斷 ===
        signal = "HOLD"
        score = 0
        
        if c_ma5 > c_ma20 > c_ma60: score += 2    # 多頭排列
        elif c_ma5 < c_ma20 < c_ma60: score -= 2  # 空頭排列
        
        # RSI 濾網
        if c_rsi > 75: score -= 0.5
        elif c_rsi < 25: score += 0.5

        if score >= 1.5: signal = "BUY"
        elif score <= -1.5: signal = "SELL"

        # === [關鍵優化] 計算停損價 ===
        # 多頭停損設在 MA60 (趨勢線) 下方 1%
        # 空頭停損設在 MA60 上方 1%
        stop_loss = 0.0
        if signal == "BUY":
            stop_loss = c_ma60 * 0.99
        elif signal == "SELL":
            stop_loss = c_ma60 * 1.01
        else:
            stop_loss = c_ma60 # 參考價

        return StrategyResult(
            signal=signal,
            confidence=0.8 if abs(score)>1.5 else 0.5,
            reason=f"MA Score: {score}, RSI: {c_rsi:.1f}",
            risk_penalty=0.0,
            stop_loss=float(f"{stop_loss:.2f}"), # 取小數點兩位
            raw_data={"price": c_close, "ma60": c_ma60, "rsi": c_rsi}
        )
