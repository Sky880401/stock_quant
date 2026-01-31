from .base_strategy import BaseStrategy
import pandas as pd

class MACrossoverStrategy(BaseStrategy):
    # 👇 關鍵修正：加入 __init__ 來接收參數
    def __init__(self, short_window=5, long_window=20):
        self.short_window = short_window
        self.long_window = long_window

    def analyze(self, df: pd.DataFrame) -> dict:
        # 複製一份數據以免動到原始資料
        data = df.copy()
        
        # 計算移動平均線
        data['SMA_Short'] = data['Close'].rolling(window=self.short_window).mean()
        data['SMA_Long'] = data['Close'].rolling(window=self.long_window).mean()
        
        # 取得最後兩筆數據來判斷交叉
        if len(data) < self.long_window:
            return {"signal": "HOLD", "confidence": 0, "reason": "數據不足"}

        last_close = data.iloc[-1]
        prev_close = data.iloc[-2]
        
        # 黃金交叉 (短線向上突破長線)
        if prev_close['SMA_Short'] <= prev_close['SMA_Long'] and last_close['SMA_Short'] > last_close['SMA_Long']:
            return {
                "signal": "BUY",
                "confidence": 80,
                "reason": f"黃金交叉 (MA{self.short_window} > MA{self.long_window})"
            }
            
        # 死亡交叉 (短線向下跌破長線)
        elif prev_close['SMA_Short'] >= prev_close['SMA_Long'] and last_close['SMA_Short'] < last_close['SMA_Long']:
            return {
                "signal": "SELL",
                "confidence": 80,
                "reason": f"死亡交叉 (MA{self.short_window} < MA{self.long_window})"
            }
            
        else:
            return {
                "signal": "HOLD",
                "confidence": 50,
                "reason": "無交叉訊號"
            }