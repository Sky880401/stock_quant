"""
①+③：用 yfinance 批次抓全上市普通股、依流動性(近60日成交值)濾出 top-N，
含中小型、排掉沒量的殭屍股。價格資料一併存下重用(省 FinMind 配額)。
輸出：data/quant_cache/wide_universe.json (ids + industry) + wide_prices.pkl (Close/Volume)
"""
import os, sys, json, pickle, time
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from quant.universe_expanded import get_universe_expanded

TOPN = 350
OUT_UNI = os.path.join(ROOT, "data", "quant_cache", "wide_universe.json")
OUT_PX = os.path.join(ROOT, "data", "quant_cache", "wide_prices.pkl")


def main():
    import yfinance as yf
    ids = get_universe_expanded()
    ind = json.load(open(os.path.join(ROOT, "data/quant_cache/twse_common_list.json")))["industry"]
    print("候選上市普通股：%d 檔，yfinance 批次抓價中…" % len(ids))
    tickers = [s + ".TW" for s in ids]
    closes, vols = {}, {}
    CH = 150
    for j in range(0, len(tickers), CH):
        chunk = tickers[j:j + CH]
        try:
            df = yf.download(chunk, period="9mo", interval="1d", progress=False,
                             auto_adjust=True, threads=True, group_by="ticker")
        except Exception as e:
            print("  chunk %d 失敗: %s" % (j, e)); continue
        for t in chunk:
            sid = t[:-3]
            try:
                sub = df[t] if isinstance(df.columns, pd.MultiIndex) else df
                c = sub["Close"].dropna(); v = sub["Volume"].dropna()
                if len(c) >= 100:
                    closes[sid] = c; vols[sid] = v
            except Exception:
                pass
        print("  進度 %d/%d，已收 %d 檔" % (min(j + CH, len(tickers)), len(tickers), len(closes)))
        time.sleep(1)

    # 近60日平均成交值排名
    liq = {}
    for sid in closes:
        c, v = closes[sid], vols[sid]
        n = min(60, len(c))
        liq[sid] = float((c.iloc[-n:] * v.iloc[-n:]).mean())
    ranked = sorted(liq, key=lambda s: -liq[s])
    top = ranked[:TOPN]
    print("\n有效報價檔數：%d，取流動性 top %d" % (len(closes), len(top)))
    print("最小流動性(第%d名)：%.1f 萬/日" % (TOPN, liq[top[-1]] / 1e4))

    uni = {"ids": top, "industry": {s: ind.get(s, "其他") for s in top}}
    json.dump(uni, open(OUT_UNI, "w"), ensure_ascii=False)
    pickle.dump({"close": {s: closes[s] for s in top}, "vol": {s: vols[s] for s in top}},
                open(OUT_PX, "wb"))
    # 產業分布
    from collections import Counter
    cc = Counter(uni["industry"].values())
    print("產業分布前8：", dict(cc.most_common(8)))
    print("✅ 存 wide_universe.json + wide_prices.pkl")


if __name__ == "__main__":
    main()
