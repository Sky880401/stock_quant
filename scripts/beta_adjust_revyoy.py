"""
M2 #2 — revyoy 只做多『扣掉 beta』檢查：純選股 alpha 還剩多少？

問題：Q5（高 revyoy）贏大盤，是真會選股，還是只是「比較敢衝」(高 beta)？
做法：時間序列 OLS  Q5_net_t = alpha + beta * mkt_t + eps_t
  mkt = 全候選股等權平均報酬（uni，與先前對比的基準一致）。
  beta : Q5 相對大盤的攻擊性（>1=比大盤兇、漲多跌也多）。
  alpha: 扣掉「跟著大盤」那塊後、純靠選股的每期超額。alpha 的 t>2 才算真本事。
  R^2  : Q5 被大盤解釋掉的比例（越高=越像只是大盤的放大版）。
分全期 + 各段（看純 alpha 是不是也只在近期出現）。
誠實：mkt 用候選股自身等權（Q5 是其子集，會有機械相關）→ 這測的是
  「Q5 是不是只是候選池的高 beta 版」，正是我們要問的；已標注。
"""
import os
import sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from holdout_revyoy import collect_periods, HORIZON

PPY = 252.0 / HORIZON


def ols(y, x):
    """y = a + b*x。回 (a, b, t_a, t_b, r2, n)。"""
    y = np.asarray(y, float); x = np.asarray(x, float)
    n = len(y)
    if n < 3:
        return None
    xbar, ybar = x.mean(), y.mean()
    sxx = float(((x - xbar) ** 2).sum())
    if sxx == 0:
        return None
    b = float(((x - xbar) * (y - ybar)).sum() / sxx)
    a = float(ybar - b * xbar)
    resid = y - a - b * x
    s2 = float((resid ** 2).sum() / (n - 2))
    se_b = (s2 / sxx) ** 0.5
    se_a = (s2 * (1.0 / n + xbar ** 2 / sxx)) ** 0.5
    t_a = a / se_a if se_a > 0 else float("nan")
    t_b = b / se_b if se_b > 0 else float("nan")
    sst = float(((y - ybar) ** 2).sum())
    r2 = 1.0 - (resid ** 2).sum() / sst if sst > 0 else float("nan")
    return a, b, t_a, t_b, r2, n


def ann_alpha(a):
    """月 alpha → 年化（複利）。"""
    return (1.0 + a) ** PPY - 1.0


def report(name, recs, lo, hi):
    import pandas as pd
    lo, hi = pd.Timestamp(lo), pd.Timestamp(hi)
    sub = [r for r in recs if lo <= r["date"] <= hi]
    if len(sub) < 3:
        print("  %-10s 期數<3，略" % name); return None
    y = [r["q5_net"] for r in sub]      # 只做多扣成本後 Q5
    x = [r["uni"] for r in sub]         # 大盤(候選股等權)
    res = ols(y, x)
    if res is None:
        print("  %-10s OLS 失敗" % name); return None
    a, b, t_a, t_b, r2, n = res
    naive_excess = float(np.mean([r["q5_net_excess"] for r in sub]))  # 沒扣beta的超額
    print("  %-10s n=%2d | beta=%.2f | 純alpha/月=%+.3f%%(t=%+.2f) 年化=%+.1f%% | R²=%.2f | (沒扣beta超額=%+.3f%%)"
          % (name, n, b, a * 100, t_a, ann_alpha(a) * 100, r2, naive_excess * 100))
    return {"n": n, "beta": round(b, 3), "alpha_per_period_pct": round(a * 100, 4),
            "alpha_t": round(t_a, 2), "alpha_ann_pct": round(ann_alpha(a) * 100, 2),
            "r2": round(r2, 3), "naive_excess_pct": round(naive_excess * 100, 4)}


def main():
    recs, rt = collect_periods()
    print("=" * 80)
    print("revyoy 只做多 · 扣 beta 純選股 alpha 檢查 | OLS: Q5_net = alpha + beta*大盤")
    print("大盤=全候選股等權；alpha t>2 才算真選股本事；beta>1=比大盤敢衝")
    print("=" * 80)
    print("\n【全期】")
    full = report("全期", recs, "2000-01-01", "2100-01-01")
    print("\n【分段：純 alpha 是不是也只在近期才有？】")
    segs = {}
    for name, lo, hi in [("2024 整年", "2024-02-01", "2024-12-31"),
                          ("2025 全年", "2025-01-01", "2025-12-31"),
                          ("2025下+26", "2025-07-01", "2026-12-31"),
                          ("2026 至今", "2026-01-01", "2026-12-31")]:
        segs[name] = report(name, recs, lo, hi)
    print("\n【擴張式 hold-out 的純 alpha】")
    hos = {}
    for cut in ["2024-12-31", "2025-06-30", "2025-12-31"]:
        hos["after_" + cut] = report("信到" + cut[5:], recs, cut, "2100-01-01")

    print("\n判讀指引：")
    print("  beta 顯著>1 且 alpha 不顯著(t<2) → 贏大盤多半只是『更敢衝』，不是選股 → 別當 alpha")
    print("  alpha t>2 且年化仍正          → 扣掉敢衝後仍有真選股超額 → 值得開帳本實證")

    import json, datetime
    outdir = os.path.join(ROOT, "data", "logs")
    stamp = datetime.date.today().isoformat()
    with open(os.path.join(outdir, f"beta_adjust_revyoy_{stamp}.json"), "w") as f:
        json.dump({"full": full, "segments": segs, "holdout": hos}, f,
                  ensure_ascii=False, indent=2, default=str)
    print("\n已存：data/logs/beta_adjust_revyoy_%s.json" % stamp)


if __name__ == "__main__":
    main()
