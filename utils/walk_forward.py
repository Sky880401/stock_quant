"""
P5 walk-forward 驗證 —— 防過擬合的核心工具。

對一個策略做「滾動樣本外」測試：在每個歷史時點，只用「當下以前」的資料算出訊號，
再對照之後 N 日的真實報酬，看方向是否命中。再把整段歷史切成數段，比較各段命中率：
- 各段命中率穩定 → 策略可信
- 各段忽高忽低（變異大）→ 脆弱/過擬合，回測好看實盤會崩

誠實面對：方向命中率合理目標 53-57%，>65% 要先懷疑是不是過擬合或樣本太少。
"""
import numpy as np


def walk_forward(strategy, df, horizon: int = 20, min_bars: int = 200, stride: int = 1, segments: int = 4) -> dict:
    """
    strategy: 具 .analyze(df_slice) 的策略實例
    df: 含 Close 的歷史 DataFrame
    回傳整體與分段的方向命中率、樣本數與穩定性判讀。
    """
    if df is None or "Close" not in df.columns or len(df) < min_bars + horizon + 20:
        return {"insufficient": True, "reason": "歷史資料不足以做 walk-forward"}

    close = df["Close"].values
    n = len(df)
    records = []  # (idx, signal, fwd_ret)
    for i in range(min_bars, n - horizon, stride):
        try:
            res = strategy.analyze(df.iloc[: i + 1])
            sig = res.signal if hasattr(res, "signal") else res.get("signal")
        except Exception:
            continue
        if sig not in ("BUY", "SELL"):
            continue
        fwd = (close[i + horizon] / close[i] - 1.0) * 100.0
        hit = 1 if ((sig == "BUY" and fwd > 0) or (sig == "SELL" and fwd < 0)) else 0
        records.append((i, hit, fwd))

    if len(records) < 8:
        return {"insufficient": True, "reason": f"方向性訊號太少({len(records)}筆)，無法評估"}

    hits = [r[1] for r in records]
    overall = round(np.mean(hits) * 100, 1)

    # 分段（依時間順序切 segments 段）
    seg_rates = []
    chunks = np.array_split(np.array(hits), segments)
    for c in chunks:
        if len(c):
            seg_rates.append(round(float(np.mean(c)) * 100, 1))

    spread = round(max(seg_rates) - min(seg_rates), 1) if seg_rates else 0.0
    if spread <= 12:
        stability = "穩定 ✅"
    elif spread <= 25:
        stability = "中等 ⚠️"
    else:
        stability = "不穩(疑過擬合) ❌"

    verdict = "可信" if (overall >= 52 and spread <= 20) else (
        "勝率不足" if overall < 52 else "命中尚可但不穩")

    return {
        "samples": len(records),
        "horizon": horizon,
        "overall_hit": overall,
        "segment_hits": seg_rates,
        "spread": spread,
        "stability": stability,
        "verdict": verdict,
    }
