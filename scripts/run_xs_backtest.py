"""
誠實版橫截面多空 walk-forward 回測 runner（M1 第一個數字）。

流程：
  1. 載入 .env（FINMIND_TOKEN）。
  2. build_panel：股價用 FinMind 長歷史（暖身），法人只在 T86 快取窗內抓（inst_start）。
  3. 報告 panel 覆蓋與法人可信度（inst_unreliable 比例）。
  4. 各因子 Rank-IC 掃描（月度 step=20 / horizon=20）。
  5. 取 |ic_t| 最大的單因子 + composite，跑含成本的 quintile + 多空淨值回測。
  6. 印出完整誠實報告，並存 JSON / Markdown。

用法：venv/bin/python scripts/run_xs_backtest.py
"""
import os
import sys
import json
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- 載入 .env ---
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
envp = os.path.join(ROOT, ".env")
if os.path.exists(envp):
    for line in open(envp):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import numpy as np
from quant.data_hub import build_panel
from quant.factors import build_factor_timeseries
from quant.backtest_xs import run_backtest, rank_ic_all_factors

# === 回測窗設定 ===
PRICE_START = "2023-01-01"     # FinMind 股價暖身起點（mom 需 ~252 交易日）
INST_START = "2024-01-01"      # 法人(T86)只抓此日起 → 真法人資料窗
BT_START = "2024-02-01"        # 回測再平衡起點（inst 暖身 20 日後）
BT_END = "2026-06-05"          # 至 T86 快取最後一日
STEP = 20                      # 月度換倉
HORIZON = 20                   # 持有一個月（= step，連續不重疊）
PANEL_CACHE = os.path.join(ROOT, "data", "quant_cache", "panel_bt_2024.pkl")


def main():
    print("=" * 70)
    print("誠實版橫截面多空回測 | price_start=%s inst_start=%s 窗=%s~%s 月度" % (
        PRICE_START, INST_START, BT_START, BT_END))
    print("=" * 70)

    panel = build_panel(start=PRICE_START, inst_start=INST_START,
                        cache_path=PANEL_CACHE, use_cache=True, max_age_hours=72)
    print("panel 檔數：%d" % len(panel))

    # --- 法人可信度 / 覆蓋 ---
    fts = build_factor_timeseries(panel)
    print("通過 build_factor_timeseries（>=260 筆）檔數：%d" % len(fts))
    bad = tot = 0
    cov_start, cov_end = None, None
    for sid, df in panel.items():
        sub = df.loc[INST_START:BT_END]
        if "inst_unreliable" in df.columns:
            bad += int(df.loc[INST_START:BT_END, "inst_unreliable"].sum())
            tot += len(sub)
        if len(df):
            s, e = df.index[0], df.index[-1]
            cov_start = s if cov_start is None else min(cov_start, s)
            cov_end = e if cov_end is None else max(cov_end, e)
    print("價格覆蓋：%s ~ %s" % (cov_start.date() if cov_start is not None else "?",
                              cov_end.date() if cov_end is not None else "?"))
    if tot:
        print("法人 inst_unreliable（窗內、量>0卻法人全0或NaN）比例：%d/%d = %.1f%%"
              % (bad, tot, bad / tot * 100))

    # --- (1) 各因子 Rank-IC ---
    print("\n--- (1) 各因子 Rank-IC（月度，窗 %s~%s）---" % (BT_START, BT_END))
    ic = rank_ic_all_factors(panel, step=STEP, horizon=HORIZON,
                             start=BT_START, end=BT_END)
    for fac, v in ic.items():
        if "error" in v:
            print("  %-10s %s" % (fac, v["error"]))
        else:
            print("  %-10s ic_mean=%+.4f  ic_t=%+.2f  正比率=%.0f%%  期數=%d"
                  % (fac, v["ic_mean"], v["ic_t"], v["ic_pos_rate"], v["rebalances"]))

    # --- 選最有預測力的單因子（|ic_t| 最大）---
    cand = {f: v for f, v in ic.items() if "ic_t" in v and f != "composite"}
    best = max(cand, key=lambda f: abs(cand[f]["ic_t"])) if cand else "composite"
    print("\n最有預測力單因子（|ic_t| 最大）：%s" % best)

    results = {}
    for fac in [best, "composite"]:
        print("\n" + "=" * 70)
        print("--- (2)(3) quintile + 多空（含成本）｜factor=%s ---" % fac)
        r = run_backtest(panel, step=STEP, horizon=HORIZON, n_quantiles=5,
                         factor=fac, start=BT_START, end=BT_END)
        results[fac] = r
        if "error" in r:
            print("  ", r["error"]); continue
        print("  期數=%d  窗=%s  periods/yr=%.1f" % (r["rebalances"], r["window"], r["periods_per_year"]))
        print("  rank-IC: mean=%+.4f  t=%+.2f  正比率=%.0f%%" % (r["ic_mean"], r["ic_t"], r["ic_pos_rate"]))
        print("  quintile 各層每期報酬%%（Q1低分..Q5高分）：", r["quintile_mean_ret_pct"])
        print("  單調(Spearman)=%s  嚴格遞增=%s" % (r["monotonic_spearman"], r["strictly_increasing"]))
        print("  平均換手率=%.3f  平均每期成本=%.3f%%" % (r["avg_turnover"], r["avg_cost_per_period_pct"]))
        print("  多空每期：毛=%+.3f%%  淨=%+.3f%%  淨t=%+.2f"
              % (r["ls_gross_per_period_pct"], r["ls_net_per_period_pct"], r["ls_net_t"]))
        g, nt = r["ls_gross_annual"], r["ls_net_annual"]
        print("  多空年化(毛)：報酬=%+.2f%% 波動=%.2f%% Sharpe=%.2f MaxDD=%.2f%% 勝率=%.0f%%"
              % (g["ann_return_pct"], g["ann_vol_pct"], g["sharpe"], g["max_drawdown_pct"], g["win_rate_pct"]))
        print("  多空年化(淨)：報酬=%+.2f%% 波動=%.2f%% Sharpe=%.2f MaxDD=%.2f%% 勝率=%.0f%%"
              % (nt["ann_return_pct"], nt["ann_vol_pct"], nt["sharpe"], nt["max_drawdown_pct"], nt["win_rate_pct"]))
        print("  淨值曲線（多空淨）：", r["ls_net_equity_curve"])

    # --- 存檔 ---
    outdir = os.path.join(ROOT, "data", "logs")
    os.makedirs(outdir, exist_ok=True)
    stamp = datetime.date.today().isoformat()
    payload = {"price_start": PRICE_START, "inst_start": INST_START,
               "bt_start": BT_START, "bt_end": BT_END, "step": STEP, "horizon": HORIZON,
               "n_panel": len(panel), "rank_ic": ic, "best_factor": best, "results": results}
    jpath = os.path.join(outdir, f"xs_backtest_{stamp}.json")
    with open(jpath, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    print("\n已存：%s" % jpath)
    return payload


if __name__ == "__main__":
    main()
