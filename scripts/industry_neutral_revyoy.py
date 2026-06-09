"""
回測強化①：revyoy 產業中性化檢驗。
問題：revyoy 只做多的 alpha，是真選股、還是只是「買到熱門產業(AI供應鏈)」？
做法：在『同產業內』對 revyoy 做 z-score(去產業均值) 再排名 → top quintile 變成
      「各產業裡營收成長最快的」而非「整體最快(會擠在AI)」。基準仍=全候選股等權。
      跑 raw vs neutral 並排比較 + 印持股產業分布(看中性化有沒有打散集中度)。
誠實：仍含存活偏誤(同原universe)、樣本~27月；這支只回答『是不是只是買產業』。
"""
import os, sys, json
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
envp = os.path.join(ROOT, ".env")
if os.path.exists(envp):
    for line in open(envp):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())

from quant.data_hub import build_panel
from quant.factors import build_factor_timeseries, FACTOR_COLS
from quant.backtest_xs import _fwd_returns, _master_dates, _round_trip_cost, _annualize

STEP, HORIZON, N_Q = 20, 20, 5
MIN_LIQ, MIN_NAMES, WARMUP = 2e7, 15, 260
BT_START = pd.Timestamp("2024-02-01")
EXCLUDE_PREFIX = ("28",)
RT = _round_trip_cost()
PANEL_CACHE = os.path.join(ROOT, "data", "quant_cache", "panel_bt_2024.pkl")
IND_CACHE = os.path.join(ROOT, "data", "quant_cache", "industry_map.json")
PPY = 252.0 / HORIZON


def industry_map(sids):
    if os.path.exists(IND_CACHE):
        m = json.load(open(IND_CACHE))
        if all(s in m for s in sids):
            return m
    from FinMind.data import DataLoader
    dl = DataLoader()
    tok = os.environ.get("FINMIND_TOKEN")
    if tok:
        dl.login_by_token(api_token=tok)
    df = dl.taiwan_stock_info()
    m = {}
    for sid in sids:
        r = df[df.stock_id == sid]
        m[sid] = str(r.iloc[0]["industry_category"]) if len(r) else "其他"
    json.dump(m, open(IND_CACHE, "w"), ensure_ascii=False)
    return m


def scores_at(fts, ind, d, neutralize):
    """回 {sid: 分數}。neutralize=True → 同產業內 z-score；False → 整體 z-score(raw)。"""
    rows = {}
    for sid, f in fts.items():
        if sid.startswith(EXCLUDE_PREFIX):
            continue
        sub = f.loc[:d]
        if len(sub) == 0:
            continue
        row = sub.iloc[-1]
        if row[FACTOR_COLS].isna().any():
            continue
        if pd.isna(row["dollar_vol"]) or row["dollar_vol"] < MIN_LIQ:
            continue
        rows[sid] = (float(row["revyoy"]), ind.get(sid, "其他"))
    if len(rows) < MIN_NAMES:
        return {}
    df = pd.DataFrame([(s, v, i) for s, (v, i) in rows.items()], columns=["sid", "rev", "ind"])
    if neutralize:
        def z(x):
            sd = x.std(ddof=0)
            return (x - x.mean()) / sd if len(x) >= 2 and sd > 0 else x * 0.0
        df["score"] = df.groupby("ind")["rev"].transform(z)
    else:
        sd = df["rev"].std(ddof=0)
        df["score"] = (df["rev"] - df["rev"].mean()) / sd if sd > 0 else 0.0
    return dict(zip(df["sid"], df["score"])), dict(zip(df["sid"], df["ind"]))


def collect(fts, ind, closes, dates, neutralize):
    recs, top_inds = [], {}
    i = WARMUP
    while i + HORIZON < len(dates):
        d, d2 = dates[i], dates[i + HORIZON]
        if d < BT_START:
            i += STEP; continue
        res = scores_at(fts, ind, d, neutralize)
        if res and len(res[0]) >= MIN_NAMES:
            sc, indmap = res
            fwd = _fwd_returns(closes, sc, d, d2)
            common = [s for s in sc if s in fwd]
            if len(common) >= MIN_NAMES:
                ssc = pd.Series({s: sc[s] for s in common}).sort_values()
                fr = pd.Series({s: fwd[s] for s in common})
                ic = ssc.rank().corr(fr.rank())
                ordered = list(ssc.index); m = len(ordered)
                top = ordered[int(round((N_Q - 1) * m / N_Q)):]
                q5 = float(fr[top].mean()); uni = float(fr.mean())
                recs.append({"date": d, "ic": float(ic) if pd.notna(ic) else np.nan,
                             "q5_net": q5 - RT, "uni": uni, "excess": (q5 - RT) - uni,
                             "beat": (q5 - RT) > uni})
                for s in top:
                    top_inds[indmap[s]] = top_inds.get(indmap[s], 0) + 1
        i += STEP
    return recs, top_inds


def summary(recs):
    ics = np.array([r["ic"] for r in recs if not np.isnan(r["ic"])])
    ic_t = float(np.mean(ics)) / (np.std(ics, ddof=1) + 1e-12) * np.sqrt(len(ics))
    ex = np.array([r["excess"] for r in recs])
    ex_t = float(np.mean(ex)) / (np.std(ex, ddof=1) + 1e-12) * np.sqrt(len(ex))
    ann = _annualize([r["q5_net"] for r in recs], PPY)
    uann = _annualize([r["uni"] for r in recs], PPY)
    return {"n": len(recs), "ic": float(np.mean(ics)), "ic_t": float(ic_t),
            "beat": float(np.mean([r["beat"] for r in recs])) * 100,
            "ex": float(np.mean(ex)) * 100, "ex_t": float(ex_t),
            "ann": ann["ann_return"] * 100, "uni_ann": uann["ann_return"] * 100}


def seg(recs, lo, hi):
    sub = [r for r in recs if pd.Timestamp(lo) <= r["date"] <= pd.Timestamp(hi)]
    if len(sub) < 3:
        return None
    ex = np.array([r["excess"] for r in sub])
    ext = float(np.mean(ex)) / (np.std(ex, ddof=1) + 1e-12) * np.sqrt(len(ex))
    return {"n": len(sub), "ex": float(np.mean(ex)) * 100, "ex_t": float(ext),
            "beat": float(np.mean([r["beat"] for r in sub])) * 100}


def main():
    panel = build_panel(cache_path=PANEL_CACHE, use_cache=True, max_age_hours=99999,
                        start="2023-01-01", inst_start="2024-01-01")
    fts = build_factor_timeseries(panel)
    closes = {s: f["close"] for s, f in fts.items()}
    dates = _master_dates(panel)
    ind = industry_map(list(fts.keys()))

    print("=" * 72)
    print("revyoy 只做多 · 產業中性化檢驗（raw vs 同產業內排名）")
    print("含 0.586% 來回成本、基準=全候選股等權、ex-financials、~27月")
    print("=" * 72)

    out = {}
    for tag, neu in [("RAW 整體排名", False), ("NEUTRAL 產業中性", True)]:
        recs, inds = collect(fts, ind, closes, dates, neu)
        s = summary(recs)
        out[tag] = (s, inds, recs)
        print("\n【%s】期數=%d" % (tag, s["n"]))
        print("  IC=%.3f(t=%.2f) 贏大盤%.0f%% 超額/月=%+.3f%%(t=%.2f) 只做多年化=%+.1f%% vs 大盤%+.1f%%"
              % (s["ic"], s["ic_t"], s["beat"], s["ex"], s["ex_t"], s["ann"], s["uni_ann"]))
        print("  分段超額/月(t)：", end="")
        for nm, lo, hi in [("2024", "2024-02-01", "2024-12-31"), ("2025", "2025-01-01", "2025-12-31"),
                            ("2026", "2026-01-01", "2026-12-31")]:
            g = seg(recs, lo, hi)
            print("%s %+.2f%%(t%.1f) | " % (nm, g["ex"], g["ex_t"]) if g else "%s - | " % nm, end="")
        print()
        topn = sorted(inds.items(), key=lambda x: -x[1])[:6]
        tot = sum(inds.values())
        print("  持股產業分布前6：" + "  ".join("%s %.0f%%" % (k, v / tot * 100) for k, v in topn))

    print("\n判讀：NEUTRAL 的超額/alpha 若仍顯著(t>2) → 有『同產業內』真選股本事，不只是買產業；")
    print("      若 NEUTRAL 大幅縮水/不顯著 → 原 alpha 主要來自押對產業(如AI)，要小心。")


if __name__ == "__main__":
    main()
