"""
法人籌碼動能策略 —— 用三大法人(外資/投信/自營)的連續買賣超與佔成交量比重，
判斷主力資金方向。台股短中線高度受法人主導，這是價量之外最有 alpha 的維度。

依賴 df 內的 Foreign / Trust / Dealer 欄位（由 FinMindProvider 併入，單位：股）。
無這些欄位時回 UNKNOWN（不影響其他策略）。
"""
import numpy as np
import pandas as pd

from .base_strategy import BaseStrategy
from .schema import StrategyResult


class InstitutionalFlowStrategy(BaseStrategy):
    def analyze(self, df: pd.DataFrame, extra_data: dict = None) -> StrategyResult:
        if df is None or len(df) < 20 or "Foreign" not in df.columns:
            return StrategyResult("UNKNOWN", 0.0, "無法人籌碼資料", risk_penalty=0.5)

        for col in ("Foreign", "Trust", "Dealer"):
            if col not in df.columns:
                df[col] = 0
        recent = df.tail(10).copy()
        foreign = recent["Foreign"].fillna(0)
        trust = recent["Trust"].fillna(0)
        vol = recent["Volume"].replace(0, np.nan)

        score = 0.0
        assumptions = []

        # 1. 外資近 5 日累積買賣超（量大、趨勢主導）
        f5 = foreign.tail(5).sum()
        if f5 > 0:
            score += 1.0; assumptions.append(f"外資5日買超{int(f5/1000)}k")
        elif f5 < 0:
            score -= 1.0; assumptions.append(f"外資5日賣超{int(abs(f5)/1000)}k")

        # 2. 外資連續買/賣天數（連續性 = 趨勢強度）
        sign = np.sign(foreign.tail(5).values)
        streak = 0
        for s in reversed(sign):
            if s == sign[-1] and s != 0:
                streak += 1
            else:
                break
        if streak >= 3:
            score += 0.6 * np.sign(sign[-1]); assumptions.append(f"外資連{streak}日同向")

        # 3. 投信動能（台股強短線訊號：作帳/認養）
        t5 = trust.tail(5).sum()
        if t5 > 0:
            score += 0.7; assumptions.append(f"投信5日買超{int(t5/1000)}k")
        elif t5 < 0:
            score -= 0.7; assumptions.append(f"投信5日賣超{int(abs(t5)/1000)}k")

        # 4. 法人買超佔成交量比重（買盤強度，避免被大量稀釋）
        try:
            inst_ratio = (foreign + trust).tail(5).sum() / vol.tail(5).sum()
            if inst_ratio > 0.10:
                score += 0.4; assumptions.append("法人佔量比高(強買盤)")
            elif inst_ratio < -0.10:
                score -= 0.4; assumptions.append("法人佔量比負(強賣壓)")
        except Exception:
            inst_ratio = 0.0

        # 5. 價量法人背離：價漲但法人賣 → 警訊
        price_chg = (recent["Close"].iloc[-1] - recent["Close"].iloc[0]) / recent["Close"].iloc[0]
        if price_chg > 0.03 and (f5 + t5) < 0:
            score -= 0.5; assumptions.append("⚠️價漲法人賣(背離)")

        signal = "HOLD"
        if score >= 1.2:
            signal = "BUY"
        elif score <= -1.2:
            signal = "SELL"
        conf = min(1.0, abs(score) / 2.5)

        return StrategyResult(
            signal=signal,
            confidence=round(conf, 2),
            reason=" | ".join(assumptions) or "法人無明顯動向",
            scores={"inst_score": round(score, 2)},
            assumptions=assumptions,
            raw_data={
                "foreign_5d": int(f5), "trust_5d": int(t5),
                "foreign_streak": int(streak),
                "inst_volume_ratio": round(float(inst_ratio), 4),
            },
        )
