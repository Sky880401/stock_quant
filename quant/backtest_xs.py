"""
A3 橫截面回測 —— 驗證綜合因子有沒有 alpha。

做法（walk-forward、無 look-ahead）：
  取一條主交易日序列，每 step 個交易日為再平衡日 t；
  在 t 用「<= t」資料算各股綜合分（cross_section_scores），
  forward return = t 起算 h 個交易日後的報酬。
指標：
  IC      : 每個再平衡日，綜合分與未來報酬的「排序相關(rank-IC)」，再取平均
  IC t-stat: mean(IC)/std(IC)*sqrt(N)，> 2 才算穩定顯著
  多空價差 : 前 quantile 組平均報酬 − 後 quantile 組平均報酬
  Top vs 全體: 做多組是否勝過等權全體
"""
import numpy as np
import pandas as pd

from quant.factors import build_factor_timeseries, cross_section_scores


def _master_dates(panel):
    idx = None
    for df in panel.values():
        idx = df.index if idx is None else idx.union(df.index)
    return pd.DatetimeIndex(sorted(idx))


def run_backtest(panel, step=20, horizon=20, quantile=0.2, min_liquidity=2e7):
    fts = build_factor_timeseries(panel)
    closes = {s: f["close"] for s, f in fts.items()}
    dates = _master_dates(panel)
    if len(dates) < 300:
        return {"error": "歷史不足"}

    ics, long_rets, short_rets, uni_rets = [], [], [], []
    n_dates = 0
    i = 260  # 暖身：因子需 252 日
    while i + horizon < len(dates):
        d = dates[i]; d2 = dates[i + horizon]
        scores = cross_section_scores(fts, d, min_liquidity=min_liquidity)
        if len(scores) >= 15:
            fwd = {}
            for s in scores:
                c = closes[s]
                p0 = c.asof(d); p1 = c.asof(d2)
                if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                    fwd[s] = p1 / p0 - 1.0
            common = [s for s in scores if s in fwd]
            if len(common) >= 15:
                sc = pd.Series({s: scores[s] for s in common})
                fr = pd.Series({s: fwd[s] for s in common})
                # rank-IC
                ic = sc.rank().corr(fr.rank())
                if pd.notna(ic):
                    ics.append(ic)
                k = max(1, int(len(common) * quantile))
                order = sc.sort_values(ascending=False)
                top = order.index[:k]; bot = order.index[-k:]
                long_rets.append(fr[top].mean())
                short_rets.append(fr[bot].mean())
                uni_rets.append(fr.mean())
                n_dates += 1
        i += step

    if n_dates < 5:
        return {"error": f"再平衡樣本太少({n_dates})"}

    ics = np.array(ics)
    ic_mean = float(np.mean(ics))
    ic_t = float(ic_mean / (np.std(ics) + 1e-9) * np.sqrt(len(ics)))
    spread = float(np.mean(long_rets) - np.mean(short_rets))
    return {
        "rebalances": n_dates,
        "horizon": horizon,
        "ic_mean": round(ic_mean, 4),
        "ic_t": round(ic_t, 2),
        "ic_pos_rate": round(float((ics > 0).mean()) * 100, 1),
        "long_avg": round(float(np.mean(long_rets)) * 100, 2),
        "short_avg": round(float(np.mean(short_rets)) * 100, 2),
        "universe_avg": round(float(np.mean(uni_rets)) * 100, 2),
        "long_short_spread": round(spread * 100, 2),
        "long_beat_uni": round((float(np.mean(long_rets)) - float(np.mean(uni_rets))) * 100, 2),
    }
