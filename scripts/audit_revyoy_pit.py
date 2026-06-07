"""
revyoy 多空結果『打假』稽核（point-in-time / 前視偏誤）。

不改動正式資料管線；載入既有快取 panel（panel_bt_2024.pkl），就地造出
『把月營收公布日 lag 拿掉』的前視版本，與現行（已 lag 至次月12號）版本並列比較
revyoy 的 Rank-IC 與含成本多空。

前視模擬：rev_yoy 是公布日生效後 forward-fill 的階梯序列。把它 shift(-k)（每檔各自）
即把『階梯上升點』往前挪 k 個交易日 = 提早 k 日就知道該月營收：
  offset=0   現行＝公布後次月12號生效（point-in-time 正確）
  offset=-22 約提早一個月知道 ≈ 營收所屬月底就知道（典型 look-ahead bug）
  offset=-44 約提早兩個月 ≈ 營收所屬月初就知道（最強 look-ahead）

用法：venv/bin/python scripts/audit_revyoy_pit.py
"""
import os
import sys
import pickle
import copy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.backtest_xs import run_backtest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL = os.path.join(ROOT, "data", "quant_cache", "panel_bt_2024.pkl")
BT_START, BT_END, STEP, HORIZON = "2024-02-01", "2026-06-05", 20, 20


def shift_revyoy(panel, k):
    """回傳新 panel：每檔 rev_yoy 往前挪 k 個交易日（k>0 = look-ahead）。其餘欄不動。"""
    out = {}
    for sid, df in panel.items():
        d = df.copy()
        if k > 0:
            d["rev_yoy"] = d["rev_yoy"].shift(-k)
        out[sid] = d
    return out


def summarize(r):
    if "error" in r:
        return r["error"]
    return ("ic_mean=%+.4f ic_t=%+.2f 正比率=%.0f%% | 多空淨/期=%+.3f%% 淨t=%+.2f "
            "年化淨Sharpe=%.2f 單調Spearman=%s") % (
        r["ic_mean"], r["ic_t"], r["ic_pos_rate"],
        r["ls_net_per_period_pct"], r["ls_net_t"],
        r["ls_net_annual"]["sharpe"], r["monotonic_spearman"])


def _revyoy(p):
    return run_backtest(p, step=STEP, horizon=HORIZON, n_quantiles=5,
                        factor="revyoy", start=BT_START, end=BT_END)


def gate1_pit(panel):
    """第1關：月營收公布日 lag 敏感度（前視 vs 正確 point-in-time）。"""
    print("=" * 78)
    print("第1關 revyoy 對『月營收公布日 lag』敏感度（前視 vs 正確 point-in-time）")
    print("=" * 78)
    for k in (44, 22, 11, 0):
        p = shift_revyoy(panel, k) if k else panel
        tag = "現行(正確,公布後生效)" if k == 0 else "前視 +%d交易日(約%.1f月)" % (k, k / 22)
        print("\n[offset=-%d] %s" % (k, tag))
        print("  ", summarize(_revyoy(p)))


def gate2_survivorship(panel):
    """第2關：存活者偏誤穩健性——剔除全窗最大贏家、與隨機子池。"""
    import numpy as np
    print("\n" + "=" * 78)
    print("第2關 存活者偏誤穩健性（universe 為『現在清單套到過去』）")
    print("=" * 78)
    ret = {}
    for s, df in panel.items():
        sub = df.loc[BT_START:BT_END, "Close"].dropna()
        if len(sub) > 2:
            ret[s] = sub.iloc[-1] / sub.iloc[0] - 1.0
    ranked = sorted(ret, key=ret.get, reverse=True)
    print("全窗報酬最高 5 檔(典型存活贏家):",
          [(s, round(ret[s] * 100)) for s in ranked[:5]])
    print("\n剔除全窗最大贏家 N 檔後 revyoy：")
    for n in (0, 5, 10, 20):
        drop = set(ranked[:n])
        p = {s: d for s, d in panel.items() if s not in drop}
        r = _revyoy(p)
        print("  剔除前%2d贏家(剩%2d檔): ic_mean=%+.4f ic_t=%+.2f 多空淨t=%+.2f 淨Sharpe=%.2f"
              % (n, len(p), r["ic_mean"], r["ic_t"], r["ls_net_t"],
                 r["ls_net_annual"]["sharpe"]))
    print("\n隨機抽 70%% universe x8 次 revyoy ic_t 分布：")
    keys = list(panel)
    its = []
    for sd in range(8):
        rng = np.random.default_rng(sd)
        sel = rng.choice(keys, int(len(keys) * 0.7), replace=False)
        r = _revyoy({s: panel[s] for s in sel})
        if "error" not in r:
            its.append(r["ic_t"])
    print("  ic_t:", [round(x, 2) for x in its],
          " 中位數=%.2f 最小=%.2f" % (float(np.median(its)), min(its)))


def main():
    panel = pickle.load(open(PANEL, "rb"))
    print("panel 檔數:", len(panel), "| 窗:", BT_START, "~", BT_END)
    gate1_pit(panel)
    gate2_survivorship(panel)


if __name__ == "__main__":
    main()
