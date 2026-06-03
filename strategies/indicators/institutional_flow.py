"""
法人籌碼動能策略 v2 —— 深化版。

理論依據（台股實證）：法人「集中且持續」的買賣超（institutional herding）對後續
報酬有預測力，且應「順著做」(momentum) 而非逆勢；外資與投信同向（共識）訊號最強，
分散/零星的法人進出沒有預測力。(Market states and institutional herds, Taiwan;
QFII aggressive net buying amplifies momentum.)

因此計分三支柱：
  1) 持續性 persistence：外資連續淨買/賣天數（趨勢強度）
  2) 集中度 concentration：法人淨買佔成交量比重（買盤是否夠重）
  3) 法人共識 consensus：外資 + 投信是否同向（兩大法人一致）

依賴 df 內 Foreign / Trust / Dealer 欄位（FinMindProvider 併入，單位：股）。
"""
import numpy as np
import pandas as pd

from .base_strategy import BaseStrategy
from .schema import StrategyResult


def _streak(vals):
    """回傳同向連續天數（帶正負號）。"""
    sign = np.sign(vals)
    if len(sign) == 0 or sign[-1] == 0:
        return 0
    s = 0
    for v in reversed(sign):
        if v == sign[-1] and v != 0:
            s += 1
        else:
            break
    return int(s * sign[-1])


class InstitutionalFlowStrategy(BaseStrategy):
    def analyze(self, df: pd.DataFrame, extra_data: dict = None) -> StrategyResult:
        if df is None or len(df) < 20 or "Foreign" not in df.columns:
            return StrategyResult("UNKNOWN", 0.0, "無法人籌碼資料", risk_penalty=0.5)
        for col in ("Foreign", "Trust", "Dealer"):
            if col not in df.columns:
                df[col] = 0

        recent = df.tail(20).copy()
        foreign = recent["Foreign"].fillna(0)
        trust = recent["Trust"].fillna(0)
        vol = recent["Volume"].replace(0, np.nan)

        f5, f10 = foreign.tail(5).sum(), foreign.tail(10).sum()
        t5 = trust.tail(5).sum()
        f_streak = _streak(foreign.tail(8).values)
        # 集中度：近 5 日法人(外資+投信)淨買佔成交量比
        try:
            conc = float((foreign + trust).tail(5).sum() / vol.tail(5).sum())
        except Exception:
            conc = 0.0
        consensus = (np.sign(f5) == np.sign(t5)) and f5 != 0  # 外資投信同向

        score = 0.0
        a = []
        # 1) 持續性（連續同向天數，順勢）
        if f_streak >= 3:
            score += 1.0; a.append(f"外資連{f_streak}日買")
        elif f_streak <= -3:
            score -= 1.0; a.append(f"外資連{abs(f_streak)}日賣")
        elif f5 > 0:
            score += 0.4; a.append("外資5日偏買")
        elif f5 < 0:
            score -= 0.4; a.append("外資5日偏賣")

        # 2) 集中度（買盤夠重才算數）
        if conc > 0.08:
            score += 0.8; a.append(f"法人佔量{conc*100:.0f}%(重)")
        elif conc > 0.03:
            score += 0.3
        elif conc < -0.08:
            score -= 0.8; a.append(f"法人賣壓{conc*100:.0f}%")
        elif conc < -0.03:
            score -= 0.3

        # 3) 法人共識（外資+投信同向 → 加成）
        if consensus and f5 > 0 and t5 > 0:
            score += 0.7; a.append("外資投信同買")
        elif consensus and f5 < 0 and t5 < 0:
            score -= 0.7; a.append("外資投信同賣")

        # 順勢：分數夠強才出手（門檻較 v1 寬，讓訊號更常觸發但仍要求共識/集中）
        signal = "HOLD"
        if score >= 1.2:
            signal = "BUY"
        elif score <= -1.2:
            signal = "SELL"
        conf = round(min(1.0, abs(score) / 2.5), 2)

        return StrategyResult(
            signal=signal,
            confidence=conf,
            reason=" | ".join(a) or "法人無明顯動向",
            scores={"inst_score": round(score, 2)},
            assumptions=a,
            raw_data={
                "foreign_5d": int(f5), "foreign_10d": int(f10), "trust_5d": int(t5),
                "foreign_streak": f_streak, "concentration": round(conc, 4),
                "consensus": bool(consensus),
            },
        )
