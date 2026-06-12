"""
M2 Step1+ — revyoy「只做多」分段對答案（hold-out / 樣本外）測試。

目的（回應 Sky 的想法）：
  把時間軸切成幾段、各自獨立『對答案』，看 revyoy 這個訊號是不是
  只在某一段運氣好、還是跨段都站得住；並做『擴張式 hold-out』：
  只信到切點 T、把 T 之後當成沒看過的新題目，檢查猜得準不準。

誠實守則：
  - 完全重用 backtest_xs 的無前視邏輯（因子只用 <=t 資料、報酬只用 t->t+H）。
  - 砍掉放空：只做多最高分那層 Q5（買營收成長最快的一群）。
  - 基準 = 全候選股等權平均（uni）。Q5 超額 = 純粹「往高 revyoy 傾斜」的價值。
  - 只做多成本：每期換手 × 一買一賣成本率（賣稅0.3%+雙邊手續費）。
  - 樣本短（~27 個月），近段期數少 → 結論只能當『方向性』，已標注。
"""
import os
import sys
import json
import datetime
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 載入 .env（FINMIND_TOKEN 等；用快取 panel 其實不需網路，但保險）
envp = os.path.join(ROOT, ".env")
if os.path.exists(envp):
    for line in open(envp):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from quant.data_hub import build_panel
from quant.factors import build_factor_timeseries
from quant.backtest_xs import (
    _factor_scores, _fwd_returns, _master_dates, _round_trip_cost,
    _annualize, DEFAULT_TAX, DEFAULT_FEE, DEFAULT_DISCOUNT,
)

FACTOR = "revyoy"
# 排除金融保險類(28xx)：金控『月營收』混投資/保費/評價損益，波動爆大、低基期就噴，
# 不是真業績成長 → revenue-growth 因子業界慣例一律剔除金融。
EXCLUDE_PREFIX = ("28",)
STEP = 20
HORIZON = 20
N_Q = 5
MIN_LIQ = 2e7
MIN_NAMES = 15
WARMUP = 260
BT_START = pd.Timestamp("2024-02-01")
PANEL_CACHE = os.path.join(ROOT, "data", "quant_cache", "panel_bt_2024.pkl")

# 我（Claude）挑的切點：把時間軸切成幾段獨立對答案
SEGMENTS = [
    ("2024 整年",   "2024-02-01", "2024-12-31"),
    ("2025 上半",   "2025-01-01", "2025-06-30"),
    ("2025 下半",   "2025-07-01", "2025-12-31"),
    ("2026 至今",   "2026-01-01", "2026-12-31"),
]
# 擴張式 hold-out：只信到切點、之後全當新題目（含 Sky 指定 2026-03-30）
HOLDOUT_CUTOFFS = ["2024-12-31", "2025-06-30", "2025-12-31", "2026-03-30"]


def collect_periods():
    """逐月 walk-forward，回傳每個再平衡日的只做多紀錄（list of dict）。"""
    panel = build_panel(cache_path=PANEL_CACHE, use_cache=True, max_age_hours=99999)
    fts = build_factor_timeseries(panel)
    closes = {s: f["close"] for s, f in fts.items()}
    dates = _master_dates(panel)
    rt = _round_trip_cost(DEFAULT_TAX, DEFAULT_FEE, DEFAULT_DISCOUNT)

    recs = []
    prev_long_w = {}
    i = WARMUP
    while i + HORIZON < len(dates):
        d = dates[i]
        d2 = dates[i + HORIZON]
        if d < BT_START:
            i += STEP
            continue
        scores = _factor_scores(fts, d, FACTOR, MIN_LIQ)
        scores = {s: v for s, v in scores.items() if not s.startswith(EXCLUDE_PREFIX)}
        if len(scores) >= MIN_NAMES:
            fwd = _fwd_returns(closes, scores, d, d2)
            common = [s for s in scores if s in fwd]
            if len(common) >= MIN_NAMES:
                sc = pd.Series({s: scores[s] for s in common}).sort_values()
                fr = pd.Series({s: fwd[s] for s in common})
                ic = sc.rank().corr(fr.rank())
                ordered = list(sc.index)           # 低分 -> 高分
                m = len(ordered)
                b = [int(round(k * m / N_Q)) for k in range(N_Q + 1)]
                top = ordered[b[N_Q - 1]:b[N_Q]]   # Q5 = 高 revyoy = 做多
                bot = ordered[b[0]:b[1]]            # Q1 = 低 revyoy
                long_w = {s: 1.0 / len(top) for s in top}
                # 只做多換手（賣舊買新）
                keys = set(prev_long_w) | set(long_w)
                turn = 0.5 * sum(abs(long_w.get(k, 0.0) - prev_long_w.get(k, 0.0)) for k in keys)
                cost = turn * rt
                q5 = float(fr[top].mean())
                q1 = float(fr[bot].mean())
                uni = float(fr.mean())
                recs.append({
                    "date": d, "n": len(common),
                    "ic": float(ic) if pd.notna(ic) else np.nan,
                    "q5_gross": q5, "q1": q1, "uni": uni,
                    "q5_excess": q5 - uni,          # 超額（vs 全體等權）
                    "q5_net": q5 - cost,            # 只做多扣成本後絕對報酬
                    "q5_net_excess": (q5 - cost) - uni,
                    "beat_uni": q5 > uni,           # 這個月有沒有贏全體平均
                    "turnover": turn,
                })
                prev_long_w = long_w
        i += STEP
    return recs, rt


def seg_stats(recs, lo, hi):
    lo, hi = pd.Timestamp(lo), pd.Timestamp(hi)
    sub = [r for r in recs if lo <= r["date"] <= hi]
    if not sub:
        return None
    ics = np.array([r["ic"] for r in sub if not np.isnan(r["ic"])])
    ic_mean = float(np.mean(ics)) if len(ics) else float("nan")
    ic_t = (ic_mean / (np.std(ics, ddof=1) + 1e-12) * np.sqrt(len(ics))
            if len(ics) > 1 else float("nan"))
    exn = np.array([r["q5_net_excess"] for r in sub])
    ex_t = (float(np.mean(exn)) / (np.std(exn, ddof=1) + 1e-12) * np.sqrt(len(exn))
            if len(exn) > 1 else float("nan"))
    ppy = 252.0 / HORIZON
    q5net = _annualize([r["q5_net"] for r in sub], ppy)
    uni = _annualize([r["uni"] for r in sub], ppy)
    return {
        "n_periods": len(sub),
        "span": [str(sub[0]["date"].date()), str(sub[-1]["date"].date())],
        "ic_mean": round(ic_mean, 4),
        "ic_t": round(float(ic_t), 2) if not np.isnan(ic_t) else None,
        "beat_uni_rate_pct": round(float(np.mean([r["beat_uni"] for r in sub])) * 100, 0),
        "q5_net_excess_per_period_pct": round(float(np.mean(exn)) * 100, 3),
        "q5_net_excess_t": round(float(ex_t), 2) if not np.isnan(ex_t) else None,
        "q5_net_ann_pct": round(q5net["ann_return"] * 100, 2),
        "uni_ann_pct": round(uni["ann_return"] * 100, 2),
        "q5_net_sharpe": round(q5net["sharpe"], 2),
        "q5_net_maxdd_pct": round(q5net["max_drawdown"] * 100, 2),
    }


def main():
    recs, rt = collect_periods()
    print("=" * 74)
    print("revyoy 只做多 · 分段對答案（hold-out）｜每期=賣稅0.3%+雙邊手續費後")
    print("一買一賣成本率=%.4f%%  基準=全候選股等權平均(uni)" % (rt * 100))
    print("=" * 74)
    print("總再平衡期數：%d  範圍：%s ~ %s"
          % (len(recs), recs[0]["date"].date(), recs[-1]["date"].date()))

    # 全期
    full = seg_stats(recs, "2000-01-01", "2100-01-01")
    print("\n【全期 全部 %d 個月】" % full["n_periods"])
    print("  IC=%.4f (t=%s)  贏大盤月比率=%.0f%%" % (full["ic_mean"], full["ic_t"], full["beat_uni_rate_pct"]))
    print("  只做多年化(淨)=%+.2f%%  vs 全體等權=%+.2f%%  超額/月=%+.3f%%(t=%s)  Sharpe=%.2f  MaxDD=%.2f%%"
          % (full["q5_net_ann_pct"], full["uni_ann_pct"], full["q5_net_excess_per_period_pct"],
             full["q5_net_excess_t"], full["q5_net_sharpe"], full["q5_net_maxdd_pct"]))

    # 分段
    print("\n【分段獨立對答案】每段只看自己那幾個月（看訊號是不是只在某段運氣好）")
    seg_out = {}
    for name, lo, hi in SEGMENTS:
        s = seg_stats(recs, lo, hi)
        seg_out[name] = s
        if s is None:
            print("  %-10s 無資料" % name); continue
        print("  %-10s 期數=%2d  IC=%+.3f(t=%s)  贏大盤%3.0f%%  超額/月=%+.3f%%(t=%s)  只做多年化=%+.1f%% vs 大盤%+.1f%%"
              % (name, s["n_periods"], s["ic_mean"], s["ic_t"], s["beat_uni_rate_pct"],
                 s["q5_net_excess_per_period_pct"], s["q5_net_excess_t"],
                 s["q5_net_ann_pct"], s["uni_ann_pct"]))

    # 擴張式 hold-out：只信到切點、之後全當新題目
    print("\n【擴張式 hold-out】只信到切點 T、T 之後全當沒看過的新題目，看猜得準不準")
    ho_out = {}
    for cut in HOLDOUT_CUTOFFS:
        s = seg_stats(recs, cut, "2100-01-01")
        ho_out[cut] = s
        if s is None:
            print("  切到 %s 之後：無資料" % cut); continue
        print("  只信到 %s → 之後 %2d 個月：IC=%+.3f(t=%s)  贏大盤%3.0f%%  超額/月=%+.3f%%(t=%s)  只做多年化=%+.1f%%"
              % (cut, s["n_periods"], s["ic_mean"], s["ic_t"], s["beat_uni_rate_pct"],
                 s["q5_net_excess_per_period_pct"], s["q5_net_excess_t"], s["q5_net_ann_pct"]))

    # 逐月明細（讓你直接看哪幾個月翻車）
    print("\n【逐月對答案明細】(date | 贏? | Q5淨 | 大盤 | 超額)")
    for r in recs:
        print("  %s  %s  Q5淨=%+6.2f%%  大盤=%+6.2f%%  超額=%+6.2f%%"
              % (r["date"].date(), "✅" if r["beat_uni"] else "❌",
                 r["q5_net"] * 100, r["uni"] * 100, r["q5_net_excess"] * 100))

    # 存檔
    outdir = os.path.join(ROOT, "data", "logs")
    os.makedirs(outdir, exist_ok=True)
    stamp = datetime.date.today().isoformat()
    payload = {
        "factor": FACTOR, "long_only": True, "benchmark": "universe_equal_weight",
        "step": STEP, "horizon": HORIZON, "n_quantiles": N_Q,
        "round_trip_cost": rt, "n_periods": len(recs),
        "full": full, "segments": seg_out, "holdout_cutoffs": ho_out,
        "monthly": [{"date": str(r["date"].date()), "beat_uni": r["beat_uni"],
                     "q5_net_pct": round(r["q5_net"] * 100, 3),
                     "uni_pct": round(r["uni"] * 100, 3),
                     "q5_net_excess_pct": round(r["q5_net_excess"] * 100, 3),
                     "ic": round(r["ic"], 4) if not np.isnan(r["ic"]) else None}
                    for r in recs],
    }
    jpath = os.path.join(outdir, f"holdout_revyoy_{stamp}.json")
    with open(jpath, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    print("\n已存：%s" % jpath)


if __name__ == "__main__":
    main()
