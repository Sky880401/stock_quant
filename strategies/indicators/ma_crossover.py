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

        # === 4. 綜合訊號邏輯（趨勢濾網 + 12-1 時間序列動能 + 回檔進場）===
        # 理論依據：Moskowitz/Ooi/Pedersen (2012) 時間序列動能、200MA 趨勢濾網、
        #          日頻訊號最弱→用 12-1 月動能(跳過最近一月)當主濾網，買回檔不追突破。
        assumptions = []

        # 12-1 個月時間序列動能：約 252 交易日前 → 約 21 交易日前的報酬（跳過最近一月）
        if len(close) >= 252:
            mom_12_1 = close[-21] / close[-252] - 1.0
        else:
            mom_12_1 = close[-21] / close[0] - 1.0
        bias_20 = (c_price - c_ma20) / c_ma20      # 相對 MA20 乖離（判斷是否回檔/過熱）
        golden = ma20[-1] > ma50[-1] and ma20[-2] <= ma50[-2]

        # 多頭結構：站上年線 + 中期均線多排 + 12-1 動能為正（三重確認）
        uptrend = (c_price > c_ma200) and (c_ma50 > c_ma200) and (mom_12_1 > 0)
        # 空頭結構：跌破年線 + 中期均線空排
        downtrend = (c_price < c_ma200) and (c_ma50 < c_ma200)

        signal = "HOLD"
        conf = 0.5
        score = 0.0
        if uptrend:
            assumptions.append(f"多頭(>MA200,12-1動能{mom_12_1*100:.0f}%)")
            extended = bias_20 > 0.12 or c_rsi > 75      # 過熱/乖離過大 → 不追
            pullback = (-0.08 <= bias_20 <= 0.03) and (38 <= c_rsi <= 62)  # 回檔到均線附近
            if extended:
                assumptions.append("漲多乖離/超買→等回檔")
            elif pullback:
                signal = "BUY"; conf = 0.8; score = 2
                assumptions.append("多頭回檔買點(近MA20/中性RSI)")
            elif golden and c_rsi < 70:
                signal = "BUY"; conf = 0.65; score = 1.5
                assumptions.append("多頭黃金交叉")
        elif downtrend:
            assumptions.append("空頭(<MA200,均線空排)")
            # 反彈到均線附近且未超賣 → 偏空（出場/避開），不抄底
            if c_rsi >= 50 and bias_20 >= -0.02:
                signal = "SELL"; conf = 0.7; score = -2
                assumptions.append("空頭反彈賣點")
        else:
            assumptions.append("盤整/趨勢不明→觀望")

        # 計算停損 (ATR 或 MA 支撐)
        stop_loss = c_ma50 if c_price > c_ma50 else c_ma200

        return StrategyResult(
            signal=signal,
            confidence=conf,
            reason=f"{'/'.join(assumptions[:2])} | RSI {c_rsi:.0f} | 乖離{bias_20*100:.1f}%",
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
