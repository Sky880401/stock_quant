import backtrader as bt
import pandas as pd

class BollingerStrategy:
    """
    布林通道策略 (Mean Reversion / Volatility)
    邏輯：
    1. 計算 20日均線 + 2倍標準差 (上軌) 與 -2倍標準差 (下軌)。
    2. 若收盤價 > 上軌 -> 超買 (High Risk)。
    3. 若收盤價 < 下軌 -> 超賣 (Potential Bounce)。
    4. 帶寬 (Bandwidth) -> 判斷變盤前兆 (Squeeze)。
    """
    def analyze(self, df: pd.DataFrame, extra_data: dict = None):
        if df.empty or len(df) < 20:
            return {"signal": "UNKNOWN", "confidence": 0.0, "risk_penalty": 0.0, "reason": "數據不足"}

        # 計算布林通道
        period = 20
        std_dev = 2
        
        df = df.copy()
        df['MA20'] = df['Close'].rolling(window=period).mean()
        df['STD'] = df['Close'].rolling(window=period).std()
        df['Upper'] = df['MA20'] + (df['STD'] * std_dev)
        df['Lower'] = df['MA20'] - (df['STD'] * std_dev)
        
        # 取得最新一筆數據
        latest = df.iloc[-1]
        close = latest['Close']
        upper = latest['Upper']
        lower = latest['Lower']
        ma20 = latest['MA20']
        
        # 計算 %B 指標 (股價在通道的相對位置)
        # > 1.0 = 突破上軌, < 0.0 = 跌破下軌
        pb_ratio = (close - lower) / (upper - lower) if (upper - lower) != 0 else 0.5
        
        signal = "NEUTRAL"
        confidence = 0.5
        risk_penalty = 0.0
        reasons = []

        # 判斷邏輯
        if close > upper:
            signal = "SELL" # 短線過熱，可能有回檔風險
            reasons.append(f"股價突破上軌 (Price {close} > Upper {upper:.1f})")
            risk_penalty = 0.2
            confidence = 0.7
        elif close < lower:
            signal = "BUY" # 超賣，可能有反彈
            reasons.append(f"股價跌破下軌 (Price {close} < Lower {lower:.1f})")
            confidence = 0.6
        else:
            # 在通道內
            if close > ma20:
                reasons.append("股價位於中軌之上 (偏多)")
            else:
                reasons.append("股價位於中軌之下 (偏空)")
        
        return {
            "signal": signal,
            "confidence": confidence,
            "risk_penalty": risk_penalty,
            "pb_ratio": round(pb_ratio, 2),
            "reason": " | ".join(reasons)
        }
