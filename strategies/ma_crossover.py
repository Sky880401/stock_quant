import talib
import numpy as np
import pandas as pd
from .base_strategy import BaseStrategy

class MACrossoverStrategy(BaseStrategy):
    def analyze(self, df: pd.DataFrame, extra_data: dict = None) -> dict:
        # 1. 數據量檢查
        if df.empty or len(df) < 25:
            return {
                "signal": "HOLD",
                "confidence": 0.0,
                "reason": "數據不足 (Insufficient Data)",
                "data": {"MA5": "N/A", "MA20": "N/A"}
            }

        try:
            # 2. 轉換為 numpy array 確保 TA-Lib 能吃
            close_prices = df['Close'].values.astype(float)
            
            # 3. 計算均線
            ma5 = talib.SMA(close_prices, timeperiod=5)
            ma20 = talib.SMA(close_prices, timeperiod=20)

            # 4. 取得最新數值 (處理 NaN)
            curr_ma5 = ma5[-1]
            curr_ma20 = ma20[-1]
            prev_ma5 = ma5[-2]
            prev_ma20 = ma20[-2]

            # 檢查是否為 NaN
            if np.isnan(curr_ma5) or np.isnan(curr_ma20):
                return {
                    "signal": "HOLD",
                    "confidence": 0.0,
                    "reason": "均線計算結果為 NaN",
                    "data": {"MA5": "N/A", "MA20": "N/A"}
                }

            # 5. 判斷訊號
            signal = "HOLD"
            reason = "均線無交叉"
            confidence = 0.5

            # 黃金交叉
            if prev_ma5 <= prev_ma20 and curr_ma5 > curr_ma20:
                signal = "BUY"
                reason = "黃金交叉 (MA5 突破 MA20)"
                confidence = 0.8
            
            # 死亡交叉
            elif prev_ma5 >= prev_ma20 and curr_ma5 < curr_ma20:
                signal = "SELL"
                reason = "死亡交叉 (MA5 跌破 MA20)"
                confidence = 0.8
            
            # 均線糾結判斷 (差額小於 1%)
            elif abs(curr_ma5 - curr_ma20) / curr_ma20 < 0.01:
                reason = "均線糾結 (Consolidation)"

            return {
                "signal": signal,
                "confidence": confidence,
                "reason": reason,
                "data": {
                    "MA5": float(curr_ma5),   # 強制轉型為 python float
                    "MA20": float(curr_ma20)
                }
            }

        except Exception as e:
            print(f"❌ MA Strategy Error: {e}")
            return {
                "signal": "ERROR",
                "confidence": 0.0,
                "reason": str(e),
                "data": {}
            }