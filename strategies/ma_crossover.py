import talib
from .base_strategy import BaseStrategy

class MACrossoverStrategy(BaseStrategy):
    def analyze(self, df, extra_data=None):
        if df is None or len(df) < 20:
            return {"signal": "HOLD", "confidence": 0.0, "reason": "Insufficient data"}

        # 計算 MA (注意: talib 接受 numpy array)
        close_prices = df['Close'].values
        ma5 = talib.SMA(close_prices, timeperiod=5)
        ma20 = talib.SMA(close_prices, timeperiod=20)

        # 取得最新一天的值
        latest_ma5 = ma5[-1]
        latest_ma20 = ma20[-1]
        prev_ma5 = ma5[-2]
        prev_ma20 = ma20[-2]

        # 邏輯判斷
        signal = "HOLD"
        reason = f"MA5({latest_ma5:.2f}) vs MA20({latest_ma20:.2f})"
        confidence = 0.5

        # 黃金交叉 (MA5 向上突破 MA20)
        if prev_ma5 <= prev_ma20 and latest_ma5 > latest_ma20:
            signal = "BUY"
            reason = "Golden Crossover: MA5 crossed above MA20"
            confidence = 0.8
        # 死亡交叉 (MA5 向下突破 MA20)
        elif prev_ma5 >= prev_ma20 and latest_ma5 < latest_ma20:
            signal = "SELL"
            reason = "Death Crossover: MA5 crossed below MA20"
            confidence = 0.8

        return {
            "signal": signal,
            "confidence": confidence,
            "reason": reason,
            "data": {"ma5": latest_ma5, "ma20": latest_ma20}
        }