# -*- coding: utf-8 -*-
"""小型股 vs 大型股 因子選股力(Rank-IC)對照。
快速方向檢查(非完整打假):rev_yoy 延遲1月避前視;size代理=平均成交額。
"""
import glob, os, pickle
import numpy as np
import pandas as pd

FR = sorted(glob.glob("data/quant_cache/wide_frames/*.pkl"))
close, revy, inst, turn = {}, {}, {}, {}
for fp in FR:
    sid = os.path.basename(fp)[:-4]
    try:
        df = pickle.load(open(fp, "rb"))
        if "Close" not in df or len(df) < 300:
            continue
        c = df["Close"].astype(float)
        close[sid] = c
        revy[sid] = df.get("rev_yoy")
        f = df.get("Foreign", 0); t = df.get("Trust", 0)
        inst[sid] = (pd.Series(f).fillna(0) + pd.Series(t).fillna(0)) if "Foreign" in df else None
        turn[sid] = float((c * df.get("Volume", 0)).mean())
    except Exception:
        continue

C = pd.DataFrame(close).sort_index()
RY = pd.DataFrame({k: v for k, v in revy.items() if v is not None}).reindex(C.index)
# rev_yoy 延遲約1月(21交易日)避前視
RY = RY.shift(21)
mom = C.shift(21) / C.shift(252) - 1.0            # 12-1 月動能
fwd = C.shift(-21) / C - 1.0                       # 未來約1月報酬
dates = C.index[252:-21:21]                         # 月度取樣

ts = pd.Series(turn)
med = ts.median()
small = set(ts[ts <= med].index)
large = set(ts[ts > med].index)
print(f"股票池 {len(close)} 檔 | 小型(低成交額) {len(small)} | 大型 {len(large)}")
print("(size 代理=平均成交額;rev_yoy 已延遲1月;月度 IC)\n")

def ic_scan(factor_df, name, subset):
    ics = []
    cols = [c for c in factor_df.columns if c in subset]
    for d in dates:
        if d not in factor_df.index or d not in fwd.index:
            continue
        x = factor_df.loc[d, cols]
        y = fwd.loc[d, cols]
        m = x.notna() & y.notna()
        if m.sum() < 10:
            continue
        xr, yr = x[m].rank(), y[m].rank()
        if xr.std()==0 or yr.std()==0:
            continue
        ic = np.corrcoef(xr, yr)[0,1]
        if not np.isnan(ic):
            ics.append(ic)
    if not ics:
        return None
    arr = np.array(ics)
    t = arr.mean() / arr.std() * np.sqrt(len(arr)) if arr.std() > 0 else 0
    return arr.mean(), t, (arr > 0).mean(), len(arr)

print("%-10s %-8s %9s %7s %8s %6s" % ("因子", "族群", "IC均值", "t值", "正比率", "期數"))
print("-" * 56)
for fname, fdf in [("revyoy", RY), ("mom", mom)]:
    for label, subset in [("小型股", small), ("大型股", large)]:
        r = ic_scan(fdf, fname, subset)
        if r:
            print("%-10s %-8s %+9.4f %+7.2f %7.0f%% %6d" % (fname, label, r[0], r[1], r[2]*100, r[3]))
    print("-" * 56)
print("\n解讀:同一因子若『小型股 IC明顯>大型股』→ 小型股確實是因子的金礦角落(符合假設)。")
