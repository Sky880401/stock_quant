# 修改 strategies/ma_crossover.py

import talib
import numpy as np # 確保引入 numpy
from .base_strategy import BaseStrategy

class MACrossoverStrategy(BaseStrategy):
    def analyze(self, df, extra_data=None):
        if df is None or len(df) < 60: # 修正：至少要有 60 根 K 線才能算 MA60
            return {"signal": "HOLD", "confidence": 0.0, "reason": "Insufficient data (Need >60 bars)"}

        close_prices = df['Close'].values
        high_prices = df['High'].values
        low_prices = df['Low'].values

        # 1. 擴充技術指標 (增加 MA60 與 ATR)
        ma5 = talib.SMA(close_prices, timeperiod=5)
        ma20 = talib.SMA(close_prices, timeperiod=20)
        ma60 = talib.SMA(close_prices, timeperiod=60) # 新增季線
        atr = talib.ATR(high_prices, low_prices, close_prices, timeperiod=14) # 新增 ATR 用於計算止損

        # 取得最新值
        curr_price = close_prices[-1]
        latest_ma5 = ma5[-1]
        latest_ma20 = ma20[-1]
        latest_ma60 = ma60[-1]
        latest_atr = atr[-1]

        # 2. 優化邏輯 (黃金交叉 + 均線排列)
        signal = "HOLD"
        reason = "Consolidation"
        
        # 簡單判斷：均線多頭排列
        if latest_ma5 > latest_ma20 > latest_ma60:
            signal = "BUY"
            reason = "Bullish Alignment (MA5 > MA20 > MA60)"
        elif latest_ma5 < latest_ma20 < latest_ma60:
            signal = "SELL"
            reason = "Bearish Alignment (MA5 < MA20 < MA60)"
        
        # 3. 計算建議止損與目標價 (讓 AI 有數據可以寫)
        stop_loss = curr_price - (2.0 * latest_atr) if signal == "BUY" else curr_price + (2.0 * latest_atr)
        target_price = curr_price + (3.0 * latest_atr) if signal == "BUY" else curr_price - (3.0 * latest_atr)

        return {
            "signal": signal,
            "confidence": 0.8,
            "reason": reason,
            # 關鍵：這裡傳出的數據越豐富，AI 寫的報告越準
            "data": {
                "close": float(curr_price),
                "ma5": float(latest_ma5),
                "ma20": float(latest_ma20),
                "ma60": float(latest_ma60),
                "atr": float(latest_atr),
                "suggested_stop": float(stop_loss),
                "suggested_target": float(target_price)
            }
        }