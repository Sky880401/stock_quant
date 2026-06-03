"""
TWSE 官方三大法人買賣超抓取 + 本地快取（免 token、免費、官方來源）。

取代 FinMind（匿名額度太低導致法人欄位全 0）。資料來自證交所 T86 日報：
每天一個請求拿全市場所有個股的外資/投信/自營買賣超，存成 data/twse_chip/<date>.json 快取，
之後同一天不再重抓。單位：股。

注意：T86 僅含上市(TWSE)；上櫃(TPEx)未涵蓋，查無者法人欄位留 0。
"""
import os
import json
import time
import requests

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "twse_chip")
_T86 = "https://www.twse.com.tw/rwd/zh/fund/T86?date={date}&selectType=ALL&response=json"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_session = requests.Session()


def _num(s):
    s = (s or "").replace(",", "").strip()
    if s in ("", "-", "--"):
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def fetch_day(date_yyyymmdd: str) -> dict:
    """回傳 {stock_id: {'Foreign':n,'Trust':n,'Dealer':n}}；非交易日回 {}。帶本地快取。"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{date_yyyymmdd}.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    out = {}
    try:
        r = _session.get(_T86.format(date=date_yyyymmdd), headers=_HEADERS, timeout=20)
        j = r.json()
        if j.get("stat") == "OK":
            for row in (j.get("data") or []):
                if not row or not row[0].strip():
                    continue
                sid = row[0].strip()
                # 欄位：4=外資買賣超 10=投信買賣超 11=自營商買賣超
                out[sid] = {"Foreign": _num(row[4]), "Trust": _num(row[10]), "Dealer": _num(row[11])}
    except Exception as e:
        print(f"TWSE T86 {date_yyyymmdd} 抓取失敗: {e}")
        return {}   # 失敗不快取，下次重試
    with open(path, "w") as f:
        json.dump(out, f)
    return out


def attach_institutional(df, stock_id, throttle=0.35):
    """把三大法人買賣超併入價格 df（依日期），覆寫 Foreign/Trust/Dealer 欄。

    df 需 DatetimeIndex；逐日查快取，缺的日期才向 TWSE 抓（含節流）。回傳 df。
    """
    if df is None or len(df) == 0:
        return df
    clean = str(stock_id).split(".")[0]
    for col in ("Foreign", "Trust", "Dealer"):
        df[col] = 0
    cache_mem = {}
    for ts in df.index:
        dkey = ts.strftime("%Y%m%d")
        day = cache_mem.get(dkey)
        if day is None:
            path = os.path.join(CACHE_DIR, f"{dkey}.json")
            existed = os.path.exists(path)
            day = fetch_day(dkey)
            cache_mem[dkey] = day
            if not existed:
                time.sleep(throttle)   # 只有真的去抓才節流
        rec = day.get(clean)
        if rec:
            df.at[ts, "Foreign"] = rec["Foreign"]
            df.at[ts, "Trust"] = rec["Trust"]
            df.at[ts, "Dealer"] = rec["Dealer"]
    return df
