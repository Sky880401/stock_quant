"""
①+②：建寬版 panel。股價 yfinance(免FinMind配額)、法人 T86(快取,免費)、
月營收 FinMind(每日限額→撞限就停、逐檔快取可續)。
每跑一次：盡量補月營收(到 MAX_NEW 或撞限)，並用『目前有齊資料』的股票建 panel。
輸出 data/quant_cache/panel_wide.pkl。給 cron 每日跑、逐步補滿 350 檔。
"""
import os, sys, json, pickle, time
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

from quant.data_hub import _attach_institutional, _month_revenue_yoy
REV_DIR = os.path.join(ROOT, "data", "quant_cache", "wide_rev")
UNI = json.load(open(os.path.join(ROOT, "data/quant_cache/wide_universe.json")))
OUT = os.path.join(ROOT, "data", "quant_cache", "panel_wide.pkl")
MAX_NEW = 400          # 單次最多新抓幾檔月營收(配合每日限額)


def get_rev_cached(sid):
    os.makedirs(REV_DIR, exist_ok=True)
    fp = os.path.join(REV_DIR, sid + ".pkl")
    if os.path.exists(fp):
        try:
            return pickle.load(open(fp, "rb")), True
        except Exception:
            pass
    return None, False


def fetch_rev(sid):
    """回 (yoy_series, ok)；撞限/錯誤回 (None, False) 並由呼叫端決定停不停。"""
    try:
        yoy = _month_revenue_yoy(sid)
        import pickle as pk
        pk.dump(yoy, open(os.path.join(REV_DIR, sid + ".pkl"), "wb"))
        return yoy, True
    except Exception as e:
        msg = str(e).lower()
        limited = "limit" in msg or "402" in msg or "request" in msg or "level" in msg
        return None, ("LIMIT" if limited else "ERR")


def main():
    import yfinance as yf
    ids = UNI["ids"]
    print("寬版 panel：目標 %d 檔，yfinance 抓長歷史(start 2023)…" % len(ids))
    tickers = [s + ".TW" for s in ids]
    px = {}
    for j in range(0, len(tickers), 150):
        df = yf.download(tickers[j:j + 150], start="2023-01-01", interval="1d",
                         progress=False, auto_adjust=True, threads=True, group_by="ticker")
        for t in tickers[j:j + 150]:
            sid = t[:-3]
            try:
                sub = df[t] if isinstance(df.columns, pd.MultiIndex) else df
                c = sub["Close"].dropna()
                if len(c) >= 260:
                    px[sid] = sub.loc[c.index, ["Close", "Volume"]]
            except Exception:
                pass
        time.sleep(1)
    print("  有長歷史(>=260日)：%d 檔" % len(px))

    # 補月營收(撞限就停)
    new, stop = 0, False
    for sid in px:
        yoy, cached = get_rev_cached(sid)
        if cached:
            continue
        if new >= MAX_NEW or stop:
            break
        yoy, ok = fetch_rev(sid)
        time.sleep(0.3)
        if ok == "LIMIT":
            print("  ⚠ 撞 FinMind 每日限額，今天停在這(隔天 cron 續)"); stop = True; break
        if ok is True:
            new += 1
    print("  本次新抓月營收 %d 檔" % new)

    # 用『價+營收都有』的股票建 panel（T86 從快取 attach）；逐檔 frame 快取→可續、再跑跳過已完成
    WIDE_FRAMES = os.path.join(ROOT, "data", "quant_cache", "wide_frames")
    os.makedirs(WIDE_FRAMES, exist_ok=True)
    panel = {}
    done = 0
    for sid in px:
        ffp = os.path.join(WIDE_FRAMES, sid + ".pkl")
        if os.path.exists(ffp):
            try:
                panel[sid] = pickle.load(open(ffp, "rb")); continue
            except Exception:
                pass
        yoy, cached = get_rev_cached(sid)
        if not cached or yoy is None or len(yoy) == 0:
            continue
        df = px[sid].copy()
        df.index = pd.DatetimeIndex(df.index).tz_localize(None) if getattr(df.index, "tz", None) else pd.DatetimeIndex(df.index)
        try:
            df = _attach_institutional(df, sid, inst_start="2024-01-01")
        except Exception:
            continue
        ev = pd.DatetimeIndex(yoy.index).values.astype("datetime64[ns]")
        vals = yoy.values
        pos = np.searchsorted(ev, df.index.values.astype("datetime64[ns]"), side="right") - 1
        df["rev_yoy"] = [round(float(vals[p]), 1) if p >= 0 else float("nan") for p in pos]
        cols = ["Close", "Volume", "Foreign", "Trust", "rev_yoy"]
        if all(c in df.columns for c in cols):
            frame = df[[c for c in ["Close", "Volume", "Foreign", "Trust", "Dealer", "inst_unreliable", "rev_yoy"] if c in df.columns]]
            pickle.dump(frame, open(ffp, "wb"))   # 逐檔快取
            panel[sid] = frame; done += 1
    pickle.dump(panel, open(OUT, "wb"))
    print("✅ panel_wide.pkl：%d 檔有齊(本次新組 %d) / 目標 %d" % (len(panel), done, len(ids)))


if __name__ == "__main__":
    main()
