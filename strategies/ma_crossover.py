import talib
import pandas as pd
import numpy as np
from .base_strategy import BaseStrategy
from .schema import StrategyResult

class MACrossoverStrategy(BaseStrategy):
    def analyze(self, df: pd.DataFrame, extra_data: dict = None) -> StrategyResult:
        # 數據長度檢查 (因需計算 MA200，至少需要 200 根 K 線)
        if df is None or len(df) < 200:
            return StrategyResult("UNKNOWN", 0.0, "Insufficient data (Need > 200 bars)", risk_penalty=1.0)

        close = df['Close'].values
        high = df['High'].values
        low = df['Low'].values

        # === 1. 趨勢指標 (Trend) ===
        ma20 = talib.SMA(close, timeperiod=20)
        ma50 = talib.SMA(close, timeperiod=50)
        ma200 = talib.SMA(close, timeperiod=200)
        
        c_price = close[-1]
        c_ma20, c_ma50, c_ma200 = ma20[-1], ma50[-1], ma200[-1]

        # === 2. 動能指標 (Momentum) ===
        # RSI (相對強弱)
        rsi = talib.RSI(close, timeperiod=14)
        c_rsi = rsi[-1]
        
        # ROC (變動率 - 動能速度)
        roc_14 = talib.ROC(close, timeperiod=14)[-1]
        roc_21 = talib.ROC(close, timeperiod=21)[-1]

        # === 3. 位階指標 (Position) ===
        # 52週 (約252交易日) 高低點
        # 取最近 252 天 (若不足則取全體)
        lookback = min(len(low), 252)
        low_52w = np.min(low[-lookback:])
        high_52w = np.max(high[-lookback:])
        
        # 目前股價距離 52週低點的幅度 (%)
        dist_low_52w = ((c_price - low_52w) / low_52w) * 100
        
        # 均線乖離率 (Bias)
        bias_20 = ((c_price - c_ma20) / c_ma20) * 100
        bias_200 = ((c_price - c_ma200) / c_ma200) * 100

        # === 4. 綜合訊號邏輯 ===
        score = 0
        assumptions = []

        # A. 趨勢濾網 (Trend Filter)
        if c_price > c_ma200:
            score += 1
            assumptions.append("Price > MA200 (Long-term Bullish)")
        else:
            score -= 1
            assumptions.append("Price < MA200 (Long-term Bearish)")

        # B. 動能共振 (Momentum Resonance)
        if roc_14 > 0 and roc_21 > 0:
            score += 0.5
            assumptions.append("ROC Momentum Positive")
        
        # C. RSI 狀態
        if c_rsi > 70: assumptions.append("RSI Overbought")
        elif c_rsi < 30: assumptions.append("RSI Oversold")

        # D. 黃金/死亡交叉
        if ma20[-1] > ma50[-1] and ma20[-2] <= ma50[-2]:
            score += 1
            assumptions.append("Golden Cross (MA20/50)")

        # === 5. 輸出結果 ===
        signal = "HOLD"
        if score >= 1.5: signal = "BUY"
        elif score <= -1.5: signal = "SELL"

        # 計算停損 (ATR 或 MA 支撐)
        stop_loss = c_ma50 if c_price > c_ma50 else c_ma200

        return StrategyResult(
            signal=signal,
            confidence=0.8 if abs(score) >= 2 else 0.5,
            reason=f"Score: {score} | RSI: {c_rsi:.1f} | 52w Pos: +{dist_low_52w:.1f}%",
            risk_penalty=0.0,
            stop_loss=float(f"{stop_loss:.2f}"),
            scores={"tech_score": score},
            assumptions=assumptions,
            raw_data={
                "price": c_price,
                "ma20": c_ma20, "ma50": c_ma50, "ma200": c_ma200,
                "rsi_14": c_rsi,
                "roc_14": roc_14, "roc_21": roc_21,
                "low_52w": low_52w, "high_52w": high_52w,
                "dist_low_52w_pct": dist_low_52w, # 距離52週低點 %
                "bias_200_pct": bias_200 # 距離年線 %
            }
        )
