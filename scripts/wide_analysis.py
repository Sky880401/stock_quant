"""
④+⑤：寬版 panel 上的兩個分析。
④ 中性化因子篩選：小型股(更廣更沒效率)裡，有沒有因子中性化後 t>2 = 真選股 edge？
⑤ 產業資金流測試(Sky的idea)：把法人(外資+投信)淨買加總到產業層級=『資金流向』，
   測『產業資金流入 能不能預測該產業下個月漲』(跨產業 rank-IC + 多空輪動)。
"""
import os, sys, json, pickle
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "scripts"))
from quant.factors import build_factor_timeseries
from quant.backtest_xs import _master_dates, _fwd_returns, _round_trip_cost
from factor_screen_neutral import enrich, run

STEP = HORIZON = 20
WARMUP = 260
BT_START = pd.Timestamp("2024-02-01")
RT = _round_trip_cost()


def factor_screen(fts, ind, closes, dates):
    print("\n【④ 中性化因子篩選（寬版 %d 檔）】 找 NEUTRAL t>2 的真選股因子" % len(fts))
    print("%-10s | RAW ic_t 超額(t) 贏%% | NEUTRAL ic_t 超額(t) 贏%%" % "")
    print("-" * 70)
    hits = []
    for fac in ["mom", "revyoy", "inst", "lowvol", "rev_accel", "reversal"]:
        r = run(fts, ind, closes, dates, fac, False)
        n = run(fts, ind, closes, dates, fac, True)
        flag = " ✅" if (n["ex_t"] > 2 or n["ic_t"] > 2) else ""
        if flag:
            hits.append(fac)
        print("%-10s | %5.2f %+6.2f%%(%+.1f) %3.0f | %5.2f %+6.2f%%(%+.1f) %3.0f%s"
              % (fac, r["ic_t"], r["ex"], r["ex_t"], r["beat"],
                 n["ic_t"], n["ex"], n["ex_t"], n["beat"], flag))
    return hits


def sector_flow(fts, ind, closes, dates):
    """⑤ 產業資金流：每期算各產業的法人淨買強度(inst因子的產業均值)，
    測它與該產業未來20日報酬的跨產業 rank-IC；並做『買流入最強產業 vs 流出最弱』多空。"""
    industries = sorted(set(ind.get(s, "其他") for s in fts))
    ics, ls = [], []
    i = WARMUP
    while i + HORIZON < len(dates):
        d, d2 = dates[i], dates[i + HORIZON]
        if d < BT_START:
            i += STEP; continue
        # 各股當期 inst 流(=法人淨買/量) + 未來報酬
        flow_s, fwd_s, ind_s = {}, {}, {}
        for s, f in fts.items():
            sub = f.loc[:d]
            if len(sub) == 0 or pd.isna(sub.iloc[-1].get("inst")):
                continue
            c = closes[s]; p0 = c.asof(d); p1 = c.asof(d2)
            if pd.isna(p0) or pd.isna(p1) or p0 <= 0:
                continue
            flow_s[s] = float(sub.iloc[-1]["inst"]); fwd_s[s] = p1 / p0 - 1.0
            ind_s[s] = ind.get(s, "其他")
        if len(flow_s) < 20:
            i += STEP; continue
        df = pd.DataFrame({"flow": flow_s, "fwd": fwd_s, "ind": pd.Series(ind_s)})
        g = df.groupby("ind").agg(flow=("flow", "mean"), fwd=("fwd", "mean"), n=("flow", "size"))
        g = g[g["n"] >= 2]                       # 至少2檔的產業才算
        if len(g) < 5:
            i += STEP; continue
        ic = g["flow"].rank().corr(g["fwd"].rank())
        if pd.notna(ic):
            ics.append(float(ic))
        # 多空：資金流入最強的前1/3產業 - 最弱1/3
        gg = g.sort_values("flow")
        k = max(1, len(gg) // 3)
        ls.append(float(gg["fwd"].iloc[-k:].mean() - gg["fwd"].iloc[:k].mean()))
        i += STEP
    ics, ls = np.array(ics), np.array(ls)
    ic_t = float(np.mean(ics)) / (np.std(ics, ddof=1) + 1e-12) * np.sqrt(len(ics)) if len(ics) > 1 else 0
    ls_t = float(np.mean(ls)) / (np.std(ls, ddof=1) + 1e-12) * np.sqrt(len(ls)) if len(ls) > 1 else 0
    print("\n【⑤ 產業資金流 → 預測產業輪動（Sky 的 idea）】期數=%d" % len(ics))
    print("  跨產業 rank-IC(資金流 vs 未來報酬)=%.3f (t=%.2f)" % (float(np.mean(ics)), ic_t))
    print("  買流入最強產業/賣流出最弱 多空：每期%+.3f%% (t=%.2f)" % (float(np.mean(ls)) * 100, ls_t))
    print("  → t>2 才算『資金流能預測輪動』；否則代表流向多已反映在價、追不到。")
    return ic_t, ls_t


def main():
    panel = pickle.load(open(os.path.join(ROOT, "data/quant_cache/panel_wide.pkl"), "rb"))
    ind = json.load(open(os.path.join(ROOT, "data/quant_cache/wide_universe.json")))["industry"]
    fts = enrich(build_factor_timeseries(panel))
    closes = {s: f["close"] for s, f in fts.items()}
    dates = _master_dates(panel)
    print("=" * 70)
    print("寬版分析 | panel %d 檔 → factor可用 %d 檔 | ~27月" % (len(panel), len(fts)))
    print("=" * 70)
    hits = factor_screen(fts, ind, closes, dates)
    sector_flow(fts, ind, closes, dates)
    print("\n" + "=" * 70)
    print("④ 結論：中性化後存活因子 = %s" % (hits if hits else "（無 → 小型股池也沒找到產業內選股 edge）"))


if __name__ == "__main__":
    main()
