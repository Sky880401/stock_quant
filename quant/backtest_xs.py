"""
A3 橫截面回測 —— 誠實版：含交易成本、quintile 五分層、多空淨值曲線。

做法（walk-forward、無 look-ahead）：
  取一條主交易日序列，每 step 個交易日為再平衡日 t；
  在 t 用「<= t」資料算因子分（單因子 rank 或綜合 cross_section_scores），
  forward return = 由 t（含）持有到 t+horizon 的報酬。
  ── 無前視保證：因子只用 <= t 的資料；報酬只用 t→t+horizon（未來）的價格。

指標：
  rank-IC      : 每個再平衡日，因子分與未來報酬的「排序相關」，再取平均
  IC t-stat    : mean(IC)/std(IC)*sqrt(N)，> 2 才算穩定顯著
  quintile     : 依因子分切 5 層（Q1 最低分…Q5 最高分），各層等權平均報酬，
                 檢查 Q1<Q2<…<Q5 是否單調（真因子應單調）
  多空(Q5−Q1)  : 逐期『複利淨值曲線』+ 年化報酬 / 年化波動 / Sharpe / 最大回撤
  交易成本     : 依每期『換手率』扣（賣出證交稅 0.3% + 買賣手續費各 0.1425%）

成本模型（台股）：
  證交稅 tax_rate=0.003（僅賣出課），手續費 fee_rate=0.001425（買、賣各課，常打折 discount）。
  單邊（買或賣）成本率 ≈ fee*discount（買） / fee*discount + tax（賣）。
  某期實際成本 = 該腿換手率 × 單邊成本（賣掉舊持股 + 買進新持股 → 視為一買一賣）。
  換手率 turnover = 0.5 * Σ|w_t - w_{t-1}|（權重變動的一半，0~1）。
"""
import numpy as np
import pandas as pd

from quant.factors import (
    FACTOR_COLS,
    build_factor_timeseries,
    cross_section_scores,
    _zscore,
)

# 台股預設成本參數
DEFAULT_TAX = 0.003        # 證交稅，賣出時課
DEFAULT_FEE = 0.001425     # 證券商手續費，買賣各課
DEFAULT_DISCOUNT = 1.0     # 手續費折扣（1.0=不打折；可傳 0.6 等）


def _master_dates(panel):
    idx = None
    for df in panel.values():
        idx = df.index if idx is None else idx.union(df.index)
    return pd.DatetimeIndex(sorted(idx))


def _round_trip_cost(tax=DEFAULT_TAX, fee=DEFAULT_FEE, discount=DEFAULT_DISCOUNT):
    """一次『換掉 100% 持股』（賣舊買新）的成本率。
    賣出：fee*discount + tax；買進：fee*discount。"""
    return (fee * discount + tax) + (fee * discount)


def _factor_scores(fts, date, factor, min_liquidity):
    """回傳 {sid: 該因子在 date 的橫截面 z-score 分數}。
    factor='composite' → 用 cross_section_scores（四因子等權綜合）。
    factor in FACTOR_COLS → 單因子（取該因子值的橫截面 z-score）。
    只納入該日四因子皆有值且流動性達標的股票（與綜合分同一 universe，確保可比）。"""
    if factor == "composite":
        return cross_section_scores(fts, date, min_liquidity=min_liquidity)
    rows = {}
    for sid, f in fts.items():
        sub = f.loc[:date]
        if len(sub) == 0:
            continue
        row = sub.iloc[-1]
        if row[FACTOR_COLS].isna().any():
            continue
        if pd.isna(row["dollar_vol"]) or row["dollar_vol"] < min_liquidity:
            continue
        rows[sid] = row
    if len(rows) < 10:
        return {}
    raw = pd.DataFrame(rows).T
    z = _zscore(raw[factor])
    return {sid: float(z[sid]) for sid in raw.index}


def _fwd_returns(closes, scores, d, d2):
    """t→t+horizon 的未來報酬（用 close.asof 取再平衡日當期可得價）。"""
    fwd = {}
    for s in scores:
        c = closes[s]
        p0 = c.asof(d)
        p1 = c.asof(d2)
        if pd.notna(p0) and pd.notna(p1) and p0 > 0:
            fwd[s] = p1 / p0 - 1.0
    return fwd


def _max_drawdown(equity):
    """淨值曲線（含起點 1.0）的最大回撤（負值，例 -0.18）。"""
    eq = np.asarray(equity, dtype=float)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def _annualize(period_rets, periods_per_year):
    """由逐期報酬序列算 年化報酬 / 年化波動 / Sharpe / MaxDD / 淨值曲線。"""
    r = np.asarray(period_rets, dtype=float)
    n = len(r)
    if n == 0:
        return {"ann_return": 0.0, "ann_vol": 0.0, "sharpe": 0.0,
                "max_drawdown": 0.0, "win_rate": 0.0, "equity": [1.0], "n_periods": 0}
    equity = np.cumprod(1.0 + r)
    equity = np.concatenate([[1.0], equity])
    total_growth = float(equity[-1])
    years = n / periods_per_year
    ann_return = total_growth ** (1.0 / years) - 1.0 if years > 0 and total_growth > 0 else float("nan")
    mean_p = float(np.mean(r))
    std_p = float(np.std(r, ddof=1)) if n > 1 else 0.0
    ann_vol = std_p * np.sqrt(periods_per_year)
    sharpe = (mean_p * periods_per_year) / ann_vol if ann_vol > 0 else 0.0
    return {
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": _max_drawdown(equity),
        "win_rate": float((r > 0).mean()),
        "equity": [round(float(x), 4) for x in equity],
        "n_periods": n,
    }


def run_backtest(panel, step=20, horizon=20, n_quantiles=5, min_liquidity=2e7,
                 factor="composite", start=None, end=None,
                 tax=DEFAULT_TAX, fee=DEFAULT_FEE, discount=DEFAULT_DISCOUNT,
                 min_names=15, warmup=260):
    """誠實版橫截面 walk-forward 回測。

    參數
      step        : 再平衡間隔（交易日）。月度 ≈ 20。
      horizon     : 持有期（交易日），= step 時即連續不重疊持有（淨值可直接累乘）。
      n_quantiles : 分層數（5 = quintile）。
      factor      : 'composite'（四因子等權）或 FACTOR_COLS 之一（單因子）。
      start/end   : 回測窗（'YYYY-MM-DD'）；用於把窗限制在『真法人(T86)資料』區間。
      tax/fee/discount : 成本參數（見模組 docstring）。
      min_names   : 每期最少共同股數，否則跳過該期。
      warmup      : 暖身交易日數（因子需 ~252 日；預設 260）。
    回傳 dict（含各層淨值/年化指標/單調性/含成本前後多空）。
    """
    fts = build_factor_timeseries(panel)
    closes = {s: f["close"] for s, f in fts.items()}
    dates = _master_dates(panel)
    start = pd.Timestamp(start) if start else None
    end = pd.Timestamp(end) if end else None

    ics = []
    # 每層逐期報酬；layer_rets[q] = list（q=0 最低分…n_quantiles-1 最高分）
    layer_rets = [[] for _ in range(n_quantiles)]
    uni_rets = []
    ls_gross, ls_net, turnovers = [], [], []
    prev_long_w, prev_short_w = {}, {}    # 上期 Q5 / Q1 權重（算換手率）
    rebal_dates = []
    rt_cost = _round_trip_cost(tax, fee, discount)

    i = warmup
    n = 0
    while i + horizon < len(dates):
        d = dates[i]
        d2 = dates[i + horizon]
        if (start is not None and d < start) or (end is not None and d2 > end):
            i += step
            continue
        scores = _factor_scores(fts, d, factor, min_liquidity)
        if len(scores) >= min_names:
            fwd = _fwd_returns(closes, scores, d, d2)
            common = [s for s in scores if s in fwd]
            if len(common) >= min_names:
                sc = pd.Series({s: scores[s] for s in common}).sort_values()
                fr = pd.Series({s: fwd[s] for s in common})
                # rank-IC（因子分 vs 未來報酬）
                ic = sc.rank().corr(fr.rank())
                if pd.notna(ic):
                    ics.append(ic)
                # ---- quintile 分層（依分數由低到高切 n 層）----
                ordered = list(sc.index)            # 低分 → 高分
                m = len(ordered)
                qrets = []
                bounds = [int(round(k * m / n_quantiles)) for k in range(n_quantiles + 1)]
                for q in range(n_quantiles):
                    seg = ordered[bounds[q]:bounds[q + 1]]
                    qr = float(fr[seg].mean()) if seg else float("nan")
                    layer_rets[q].append(qr)
                    qrets.append(qr)
                uni_rets.append(float(fr.mean()))
                # ---- 多空（Q_top − Q_bottom）等權，含成本 ----
                top_seg = ordered[bounds[n_quantiles - 1]:bounds[n_quantiles]]   # 高分=做多
                bot_seg = ordered[bounds[0]:bounds[1]]                            # 低分=做空
                long_w = {s: 1.0 / len(top_seg) for s in top_seg}
                short_w = {s: 1.0 / len(bot_seg) for s in bot_seg}
                gross = qrets[n_quantiles - 1] - qrets[0]
                # 換手率：兩腿各算 0.5*Σ|Δw|，首期視為全建倉(=1.0)
                def _turn(prev, cur):
                    keys = set(prev) | set(cur)
                    return 0.5 * sum(abs(cur.get(k, 0.0) - prev.get(k, 0.0)) for k in keys)
                t_long = _turn(prev_long_w, long_w)
                t_short = _turn(prev_short_w, short_w)
                turnover = t_long + t_short          # 多空兩腿合計換手
                cost = turnover * rt_cost
                net = gross - cost
                ls_gross.append(gross)
                ls_net.append(net)
                turnovers.append(turnover)
                prev_long_w, prev_short_w = long_w, short_w
                rebal_dates.append(d)
                n += 1
        i += step

    if n < 5:
        return {"error": f"再平衡樣本太少({n})；窗={start}~{end}、warmup={warmup}"}

    periods_per_year = 252.0 / horizon
    ics = np.array(ics)
    ic_mean = float(np.mean(ics))
    ic_std = float(np.std(ics, ddof=1)) if len(ics) > 1 else 0.0
    ic_t = ic_mean / (ic_std + 1e-12) * np.sqrt(len(ics)) if ic_std > 0 else 0.0

    # 各層平均報酬（每期）與單調性
    layer_mean = [float(np.nanmean(x)) if len(x) else float("nan") for x in layer_rets]
    # 單調遞增檢查：層序(0..n-1) 與 平均報酬 的 Spearman 排序相關
    valid = [(k, layer_mean[k]) for k in range(n_quantiles) if not np.isnan(layer_mean[k])]
    if len(valid) >= 3:
        ks = pd.Series([v[0] for v in valid])
        vs = pd.Series([v[1] for v in valid])
        # Spearman = Pearson of ranks（避免依賴 scipy）
        mono_spearman = float(ks.rank().corr(vs.rank()))
        strictly_increasing = all(valid[j][1] < valid[j + 1][1] for j in range(len(valid) - 1))
    else:
        mono_spearman = float("nan")
        strictly_increasing = False

    gross_stats = _annualize(ls_gross, periods_per_year)
    net_stats = _annualize(ls_net, periods_per_year)

    # 多空淨報酬顯著性（逐期淨報酬的 t 值）
    ls_net_arr = np.array(ls_net)
    ls_net_mean = float(np.mean(ls_net_arr))
    ls_net_t = (ls_net_mean / (np.std(ls_net_arr, ddof=1) + 1e-12) * np.sqrt(len(ls_net_arr))
                if len(ls_net_arr) > 1 else 0.0)

    return {
        "factor": factor,
        "rebalances": n,
        "step": step,
        "horizon": horizon,
        "periods_per_year": round(periods_per_year, 2),
        "window": [str(rebal_dates[0].date()), str(rebal_dates[-1].date())],
        "cost_params": {"tax": tax, "fee": fee, "discount": discount,
                        "round_trip_cost": round(rt_cost, 5)},
        # IC
        "ic_mean": round(ic_mean, 4),
        "ic_t": round(float(ic_t), 2),
        "ic_pos_rate": round(float((ics > 0).mean()) * 100, 1),
        # quintile 分層
        "quintile_mean_ret_pct": [round(x * 100, 3) for x in layer_mean],
        "monotonic_spearman": round(mono_spearman, 3) if not np.isnan(mono_spearman) else None,
        "strictly_increasing": strictly_increasing,
        # 換手與成本
        "avg_turnover": round(float(np.mean(turnovers)), 3),
        "avg_cost_per_period_pct": round(float(np.mean(turnovers)) * rt_cost * 100, 3),
        # 多空（每期，%）
        "ls_gross_per_period_pct": round(float(np.mean(ls_gross)) * 100, 3),
        "ls_net_per_period_pct": round(ls_net_mean * 100, 3),
        "ls_net_t": round(float(ls_net_t), 2),
        # 年化（含成本前 / 後）
        "ls_gross_annual": {
            "ann_return_pct": round(gross_stats["ann_return"] * 100, 2),
            "ann_vol_pct": round(gross_stats["ann_vol"] * 100, 2),
            "sharpe": round(gross_stats["sharpe"], 2),
            "max_drawdown_pct": round(gross_stats["max_drawdown"] * 100, 2),
            "win_rate_pct": round(gross_stats["win_rate"] * 100, 1),
        },
        "ls_net_annual": {
            "ann_return_pct": round(net_stats["ann_return"] * 100, 2),
            "ann_vol_pct": round(net_stats["ann_vol"] * 100, 2),
            "sharpe": round(net_stats["sharpe"], 2),
            "max_drawdown_pct": round(net_stats["max_drawdown"] * 100, 2),
            "win_rate_pct": round(net_stats["win_rate"] * 100, 1),
        },
        "ls_net_equity_curve": net_stats["equity"],
        "rebal_dates": [str(x.date()) for x in rebal_dates],
    }


def rank_ic_all_factors(panel, step=20, horizon=20, min_liquidity=2e7,
                        start=None, end=None, min_names=15, warmup=260):
    """逐因子 Rank-IC 掃描：對每個單因子 + 綜合分，回 (ic_mean, ic_t, ic_pos_rate, n)。
    用於先看哪個因子最有預測力，再決定多空用誰。"""
    out = {}
    for fac in FACTOR_COLS + ["composite"]:
        r = run_backtest(panel, step=step, horizon=horizon, min_liquidity=min_liquidity,
                         factor=fac, start=start, end=end, min_names=min_names, warmup=warmup)
        if "error" in r:
            out[fac] = {"error": r["error"]}
        else:
            out[fac] = {"ic_mean": r["ic_mean"], "ic_t": r["ic_t"],
                        "ic_pos_rate": r["ic_pos_rate"], "rebalances": r["rebalances"]}
    return out
