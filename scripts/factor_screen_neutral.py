"""
回測強化②：產業中性化『因子篩選器』。
目的：既然 revyoy 中性化後 edge 歸零(=產業賭注)，用同一把尺去淘——
      哪個因子『產業中性化後』IC/超額 t 還 >2 = 真正的產業內選股 alpha。
測：現有 mom/revyoy/inst/lowvol + 新衍生 rev_accel(營收加速度) / reversal(短期反轉)。
每因子都跑 RAW vs NEUTRAL(同產業內z-score) 並列；含成本、基準=全候選股等權、ex-financials。
誠實：仍含存活偏誤、~27月小樣本；這是『篩選方向』，不是最終定論。
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

# 候選因子（皆「越大越偏多」方向）
FACTORS = ["mom", "revyoy", "inst", "lowvol", "rev_accel", "reversal"]


def industry_map(sids):
    if os.path.exists(IND_CACHE):
        m = json.load(open(IND_CACHE))
        if all(s in m for s in sids):
            return m
    from FinMind.data import DataLoader
    dl = DataLoader(); tok = os.environ.get("FINMIND_TOKEN")
    if tok: dl.login_by_token(api_token=tok)
    df = dl.taiwan_stock_info(); m = {}
    for sid in sids:
        r = df[df.stock_id == sid]
        m[sid] = str(r.iloc[0]["industry_category"]) if len(r) else "其他"
    json.dump(m, open(IND_CACHE, "w"), ensure_ascii=False); return m


def enrich(fts):
    """加兩個衍生因子：rev_accel(營收YoY的~1月變化)、reversal(近月報酬反向)。皆 causal。"""
    for sid, f in fts.items():
        f["rev_accel"] = f["revyoy"] - f["revyoy"].shift(21)
        f["reversal"] = -(f["close"] / f["close"].shift(21) - 1.0)
    return fts


def valid_universe(fts, d):
    """同一 universe(四因子皆有值+流動性+非金融)，回 {sid:(row, industry)}。"""
    out = {}
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
        out[sid] = row
    return out


def score(univ_rows, ind, factor, neutralize):
    """回 {sid: 分數}（factor 的 raw z 或 同產業內 z）；缺該因子值的剔除。"""
    data = [(s, float(r[factor]), ind.get(s, "其他")) for s, r in univ_rows.items()
            if pd.notna(r.get(factor))]
    if len(data) < MIN_NAMES:
        return {}
    df = pd.DataFrame(data, columns=["sid", "val", "ind"])
    if neutralize:
        def z(x):
            sd = x.std(ddof=0)
            return (x - x.mean()) / sd if len(x) >= 2 and sd > 0 else x * 0.0
        df["s"] = df.groupby("ind")["val"].transform(z)
    else:
        sd = df["val"].std(ddof=0)
        df["s"] = (df["val"] - df["val"].mean()) / sd if sd > 0 else 0.0
    return dict(zip(df["sid"], df["s"]))


def run(fts, ind, closes, dates, factor, neutralize):
    ics, ex, beat = [], [], []
    i = WARMUP
    while i + HORIZON < len(dates):
        d, d2 = dates[i], dates[i + HORIZON]
        if d < BT_START:
            i += STEP; continue
        univ = valid_universe(fts, d)
        sc = score(univ, ind, factor, neutralize)
        if len(sc) >= MIN_NAMES:
            fwd = _fwd_returns(closes, sc, d, d2)
            common = [s for s in sc if s in fwd]
            if len(common) >= MIN_NAMES:
                ssc = pd.Series({s: sc[s] for s in common}).sort_values()
                fr = pd.Series({s: fwd[s] for s in common})
                ic = ssc.rank().corr(fr.rank())
                if pd.notna(ic):
                    ics.append(float(ic))
                ordered = list(ssc.index); m = len(ordered)
                top = ordered[int(round((N_Q - 1) * m / N_Q)):]
                q5n = float(fr[top].mean()) - RT; uni = float(fr.mean())
                ex.append(q5n - uni); beat.append(1.0 if q5n > uni else 0.0)
        i += STEP
    ics, ex = np.array(ics), np.array(ex)
    ic_t = float(np.mean(ics)) / (np.std(ics, ddof=1) + 1e-12) * np.sqrt(len(ics)) if len(ics) > 1 else 0
    ex_t = float(np.mean(ex)) / (np.std(ex, ddof=1) + 1e-12) * np.sqrt(len(ex)) if len(ex) > 1 else 0
    return {"ic": float(np.mean(ics)), "ic_t": ic_t, "ex": float(np.mean(ex)) * 100,
            "ex_t": ex_t, "beat": float(np.mean(beat)) * 100 if len(beat) else 0, "n": len(ex)}


def main():
    panel = build_panel(cache_path=PANEL_CACHE, use_cache=True, max_age_hours=99999,
                        start="2023-01-01", inst_start="2024-01-01")
    fts = enrich(build_factor_timeseries(panel))
    closes = {s: f["close"] for s, f in fts.items()}
    dates = _master_dates(panel)
    ind = industry_map(list(fts.keys()))

    print("=" * 86)
    print("產業中性化『因子篩選器』 | RAW vs NEUTRAL(同產業內) | 含成本、ex-fin、~27月")
    print("找 NEUTRAL 後 ex_t / ic_t 還 >2 的 = 真正的產業內選股因子")
    print("=" * 86)
    print("%-10s | %-22s | %-22s" % ("因子", "RAW (整體排名)", "NEUTRAL (同產業內)"))
    print("%-10s | %-22s | %-22s" % ("", "ic_t  超額/月(t)  贏%", "ic_t  超額/月(t)  贏%"))
    print("-" * 86)
    rows = []
    for fac in FACTORS:
        r = run(fts, ind, closes, dates, fac, False)
        n = run(fts, ind, closes, dates, fac, True)
        rows.append((fac, r, n))
        flag = " ✅真選股?" if (n["ex_t"] > 2 or n["ic_t"] > 2) else ""
        print("%-10s | %5.2f  %+6.2f%%(%+.1f)  %3.0f | %5.2f  %+6.2f%%(%+.1f)  %3.0f%s"
              % (fac, r["ic_t"], r["ex"], r["ex_t"], r["beat"],
                 n["ic_t"], n["ex"], n["ex_t"], n["beat"], flag))
    print("-" * 86)
    survivors = [f for f, r, n in rows if n["ex_t"] > 2 or n["ic_t"] > 2]
    print("\n中性化後仍顯著(t>2)的因子：%s" % (survivors if survivors else "（無 → 目前沒有純產業內選股 alpha，需找更多/更好的因子或資料）"))
    print("注意：~27月小樣本+存活偏誤，這是方向篩選非定論；存活者請再做穩健性+延長樣本。")


if __name__ == "__main__":
    main()
