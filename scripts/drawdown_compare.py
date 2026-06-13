# -*- coding: utf-8 -*-
"""最大回撤對照：3 個最佳組 × 340 檔，比『策略 vs 買進持有』誰摔得輕、誰風險調整後較優。"""
import os, glob, pickle, statistics
import numpy as np
import pandas as pd
from optimizer_runner import run_backtest, TrendStrategy, RSIStrategy, MACDStrategy

BEST = [
    ("MA交叉", TrendStrategy, {"fast_period": 20, "slow_period": 40}),
    ("RSI反转", RSIStrategy, {"rsi_period": 10, "low_threshold": 40, "high_threshold": 80}),
    ("MACD动能", MACDStrategy, {"fast_period": 15, "slow_period": 30, "signal_period": 12}),
]
FRAMES = sorted(glob.glob("data/quant_cache/wide_frames/*.pkl"))


def load():
    out = []
    for fp in FRAMES:
        try:
            df = pickle.load(open(fp, "rb"))
            if "Close" not in df or len(df) < 100:
                continue
            c = df["Close"].astype(float)
            out.append((os.path.basename(fp)[:-4],
                        pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c,
                                      "Volume": df.get("Volume", 0)}, index=df.index)))
        except Exception:
            continue
    return out


def bh_maxdd(close):
    c = close.values.astype(float)
    peak = np.maximum.accumulate(c)
    return float(((peak - c) / peak).max() * 100)


uni = load()
print(f"股票池 {len(uni)} 檔\n")
print("%-9s %9s %9s %9s %9s %11s %11s" % ("策略", "策略ROI", "策略回撤", "買抱ROI", "買抱回撤", "策略報酬/撤", "買抱報酬/撤"))
print("-" * 78)
for name, cls, params in BEST:
    s_rois, s_dds, b_rois, b_dds = [], [], [], []
    for sid, df in uni:
        try:
            roi, wr, trades, _aw, _al, mdd, _sh, _rt = run_backtest(cls, df, **params)
        except Exception:
            continue
        if roi == -999 or trades == 0:
            continue
        s_rois.append(roi); s_dds.append(mdd)
        b_rois.append((float(df["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1) * 100)
        b_dds.append(bh_maxdd(df["Close"]))
    sr, sd = statistics.mean(s_rois), statistics.mean(s_dds)
    br, bd = statistics.mean(b_rois), statistics.mean(b_dds)
    s_ratio = sr / sd if sd else 0
    b_ratio = br / bd if bd else 0
    print("%-9s %8.1f%% %8.1f%% %8.1f%% %8.1f%% %11.2f %11.2f" % (name, sr, sd, br, bd, s_ratio, b_ratio))
print("-" * 78)
print("\n解讀：『報酬/撤』= 每承受 1% 回撤換到多少 ROI（風險調整後效率，越高越好）。")
print("若策略回撤明顯小於買抱、或報酬/撤更高 → 代表它是『賺少但更安全/更有效率』，不是純廢。")
