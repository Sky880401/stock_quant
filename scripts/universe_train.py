# -*- coding: utf-8 -*-
"""全市場批次訓練（研究腳本，跑在 #901）。
把一個策略 × 一組參數網格 × 340 檔全歷史的交易全部匯總，揭穿單檔小樣本的假象。

用法：
  PYTHONPATH=. venv/bin/python scripts/universe_train.py <策略> [--max N]
  策略：MA交叉 / RSI反转 / MACD动能
"""
import sys, os, glob, pickle, itertools, statistics
import pandas as pd
from optimizer_runner import run_backtest, TrendStrategy, RSIStrategy, MACDStrategy

STRAT = {
    "MA交叉": (TrendStrategy, {"fast_period": [10, 15, 20, 25], "slow_period": [40, 50, 60, 70]}),
    "RSI反转": (RSIStrategy, {"rsi_period": [10, 14, 20], "low_threshold": [20, 30, 40], "high_threshold": [60, 70, 80]}),
    "MACD动能": (MACDStrategy, {"fast_period": [8, 12, 15], "slow_period": [20, 26, 30], "signal_period": [5, 9, 12]}),
}

FRAMES_DIR = "data/quant_cache/wide_frames"


def load_universe(max_n=None):
    out = []
    for fp in sorted(glob.glob(os.path.join(FRAMES_DIR, "*.pkl"))):
        sid = os.path.basename(fp)[:-4]
        try:
            df = pickle.load(open(fp, "rb"))
            if "Close" not in df.columns or len(df) < 100:
                continue
            c = df["Close"].astype(float)
            ohlcv = pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c,
                                  "Volume": df.get("Volume", 0)}, index=df.index)
            out.append((sid, ohlcv))
        except Exception:
            continue
        if max_n and len(out) >= max_n:
            break
    return out


def combos(grid):
    keys = list(grid.keys())
    return [dict(zip(keys, v)) for v in itertools.product(*grid.values())]


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in STRAT:
        sys.exit("用法: universe_train.py <MA交叉|RSI反转|MACD动能> [--max N]")
    name = sys.argv[1]
    max_n = None
    if "--max" in sys.argv:
        max_n = int(sys.argv[sys.argv.index("--max") + 1])
    cls, grid = STRAT[name]

    uni = load_universe(max_n)
    cmbs = combos(grid)
    print(f"策略={name} | 股票池={len(uni)} 檔 | 參數組合={len(cmbs)} | 共 {len(uni)*len(cmbs)} 次回測\n", flush=True)

    best = None
    for ci, params in enumerate(cmbs, 1):
        tot_trades = won = 0
        rois, bh_rois, profitable, used = [], [], 0, 0
        for sid, df in uni:
            try:
                roi, win_rate, trades, *_ = run_backtest(cls, df, **params)
            except Exception:
                continue
            if roi == -999 or trades == 0:
                continue
            used += 1
            tot_trades += trades
            won += round(win_rate / 100.0 * trades)
            rois.append(roi)
            if roi > 0:
                profitable += 1
            try:
                bh_rois.append((float(df["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1) * 100)
            except Exception:
                pass
        if tot_trades == 0:
            continue
        pooled_wr = won / tot_trades * 100
        avg_roi = statistics.mean(rois) if rois else 0
        med_roi = statistics.median(rois) if rois else 0
        bh = statistics.mean(bh_rois) if bh_rois else 0
        rec = {"params": params, "pooled_wr": round(pooled_wr, 1), "tot_trades": tot_trades,
               "stocks_used": used, "avg_roi": round(avg_roi, 2), "med_roi": round(med_roi, 2),
               "pct_profitable": round(profitable / used * 100, 1) if used else 0,
               "avg_bh": round(bh, 2), "excess": round(avg_roi - bh, 2)}
        # 以「超額報酬(贏過買進持有)」挑最佳,要求總交易數夠(ROI已修可信)
        score = rec["excess"] if tot_trades >= 100 else -999
        if best is None or score > best[0]:
            best = (score, rec)
        print(f"[{ci}/{len(cmbs)}] {params} → 匯總勝率 {rec['pooled_wr']}% | 總交易 {rec['tot_trades']} "
              f"| 平均ROI {rec['avg_roi']}% vs 買抱 {rec['avg_bh']}% (超額{rec['excess']:+}) "
              f"| 賺錢檔比 {rec['pct_profitable']}%", flush=True)

    print("\n================ 結論 ================")
    if best:
        r = best[1]
        print(f"最佳參數: {r['params']}")
        print(f"匯總勝率: {r['pooled_wr']}%（{r['tot_trades']} 筆交易 / {r['stocks_used']} 檔）")
        print(f"平均ROI: {r['avg_roi']}%  vs 買進持有 {r['avg_bh']}%  →  超額 {r['excess']:+}%")
        print(f"賺錢的股票比例: {r['pct_profitable']}%")
        verdict = "✅ 看起來有點東西" if (r['excess'] > 0 and r['pooled_wr'] >= 53 and r['tot_trades'] >= 100) else "❌ 沒有真實 edge（贏不過買進持有/勝率不夠/樣本不足）"
        print(f"判定: {verdict}")
    else:
        print("沒有任何參數組合產生足夠交易。")


if __name__ == "__main__":
    main()
