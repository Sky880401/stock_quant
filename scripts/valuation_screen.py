"""
回測強化②初版：加『估值因子』（深度資料）並用產業中性化篩選器測。
因子（越大越偏多=越便宜/高息）：
  earnings_yield = 1/PER（益本比，高=便宜）
  book_yield     = 1/PBR（高=便宜）
  div_yield      = 殖利率
資料：FinMind taiwan_stock_per_pbr（逐檔快取）。對齊 panel 交易日(asof,無前視)。
跑 RAW vs NEUTRAL，與 revyoy(對照) 並列。仍含存活偏誤、~27月。
"""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "scripts"))
envp = os.path.join(ROOT, ".env")
if os.path.exists(envp):
    for line in open(envp):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())

from quant.data_hub import build_panel
from quant.factors import build_factor_timeseries
from quant.backtest_xs import _master_dates
from factor_screen_neutral import industry_map, run

PER_DIR = os.path.join(ROOT, "data", "quant_cache", "per")


def fetch_per(sid):
    import pickle
    os.makedirs(PER_DIR, exist_ok=True)
    fp = os.path.join(PER_DIR, sid + ".pkl")
    if os.path.exists(fp):
        try:
            return pickle.load(open(fp, "rb"))
        except Exception:
            pass
    from FinMind.data import DataLoader
    import time
    dl = DataLoader()
    tok = os.environ.get("FINMIND_TOKEN")
    if tok:
        dl.login_by_token(api_token=tok)
    try:
        df = dl.taiwan_stock_per_pbr(stock_id=sid, start_date="2023-01-01")
    except Exception:
        df = None
    time.sleep(0.25)
    if df is None or len(df) == 0:
        df = pd.DataFrame()
    pickle.dump(df, open(fp, "wb"))
    return df


def attach_valuation(fts):
    """對每檔加 earnings_yield/book_yield/div_yield（對齊各自 close 的交易日 index，asof）。"""
    keep = {}
    for sid, f in fts.items():
        per = fetch_per(sid)
        if len(per) == 0:
            continue
        per = per.copy()
        per["date"] = pd.to_datetime(per["date"])
        per = per.set_index("date").sort_index()
        idx = pd.DatetimeIndex(f.index)
        def ser(col):
            s = per[col].reindex(per.index)
            return pd.Series([float(s.asof(d)) if pd.notna(s.asof(d)) else np.nan for d in idx], index=f.index)
        PER = ser("PER"); PBR = ser("PBR")
        f["earnings_yield"] = (1.0 / PER).where(PER > 0)
        f["book_yield"] = (1.0 / PBR).where(PBR > 0)
        f["div_yield"] = ser("dividend_yield")
        keep[sid] = f
    return keep


def main():
    panel = build_panel(cache_path=os.path.join(ROOT, "data/quant_cache/panel_bt_2024.pkl"),
                        use_cache=True, max_age_hours=99999, start="2023-01-01", inst_start="2024-01-01")
    fts = build_factor_timeseries(panel)
    print("抓估值資料(PER/PBR)中… %d 檔" % len(fts))
    fts = attach_valuation(fts)
    closes = {s: f["close"] for s, f in fts.items()}
    dates = _master_dates(panel)
    ind = industry_map(list(fts.keys()))
    print("有估值資料檔數：%d\n" % len(fts))

    print("=" * 84)
    print("估值因子 · 產業中性化篩選 | RAW vs NEUTRAL | 含成本、ex-fin、~27月")
    print("=" * 84)
    print("%-15s | %-22s | %-22s" % ("因子", "RAW", "NEUTRAL(同產業內)"))
    print("%-15s | %-22s | %-22s" % ("", "ic_t 超額/月(t) 贏%", "ic_t 超額/月(t) 贏%"))
    print("-" * 84)
    for fac in ["earnings_yield", "book_yield", "div_yield", "revyoy"]:
        r = run(fts, ind, closes, dates, fac, False)
        n = run(fts, ind, closes, dates, fac, True)
        flag = " ✅" if (n["ex_t"] > 2 or n["ic_t"] > 2) else ""
        print("%-15s | %5.2f %+6.2f%%(%+.1f) %3.0f | %5.2f %+6.2f%%(%+.1f) %3.0f%s"
              % (fac, r["ic_t"], r["ex"], r["ex_t"], r["beat"],
                 n["ic_t"], n["ex"], n["ex_t"], n["beat"], flag))
    print("-" * 84)
    print("讀法：益本比/淨值比高=便宜。NEUTRAL t>2 → 產業內『便宜的股票』會贏 = 價值因子有 edge。")


if __name__ == "__main__":
    main()
