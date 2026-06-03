"""
A1 資料管線：為股票池組裝「每檔的日頻面板」供橫截面因子計算。

每檔輸出 DataFrame（日期索引）欄位：
  Close, Volume, Foreign, Trust  —— 來自 fetch_stock_data_smart（已併 TWSE 法人）
  rev_yoy                        —— 月營收年增率(%)，依「公布日」落後對齊（避免 look-ahead）

月營收 look-ahead 處理：M 月營收約於 M+1 月 10 日公布，故把該 YoY 的「生效日」設為
M+1 月 12 日，再 forward-fill 到日頻，確保回測當下不會用到未公布的數字。
"""
import os
import pickle
from datetime import datetime

import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "quant_cache")


_DL = None


def _loader():
    """全域單例 FinMind DataLoader（只登入一次，省額度、避免每檔重登）。"""
    global _DL
    if _DL is None:
        import os as _os
        from FinMind.data import DataLoader
        _DL = DataLoader()
        tok = _os.getenv("FINMIND_TOKEN")
        if tok:
            try:
                _DL.login_by_token(api_token=tok)
            except Exception:
                pass
    return _DL


def _month_revenue_yoy(stock_id):
    """回傳 Series：index=生效日(公布後), value=月營收YoY(%)。失敗回空（含一次重試）。"""
    import time as _time
    df = None
    for attempt in range(2):
        try:
            df = _loader().taiwan_stock_month_revenue(
                stock_id=stock_id, start_date="2023-01-01",
                end_date=datetime.now().strftime("%Y-%m-%d"))
            if df is not None and not df.empty:
                break
        except Exception:
            _time.sleep(0.8)
    try:
        if df is None or df.empty:
            return pd.Series(dtype=float)
        df = df.sort_values(["revenue_year", "revenue_month"])
        df["ym"] = df["revenue_year"] * 100 + df["revenue_month"]
        df = df.drop_duplicates("ym")
        rev = df.set_index("ym")["revenue"].astype(float)
        yoy = (rev / rev.shift(12) - 1.0) * 100.0      # 與去年同月比
        out = {}
        for ym, v in yoy.dropna().items():
            y, m = divmod(int(ym), 100)
            em = m + 1; ey = y
            if em > 12: em = 1; ey += 1
            try:
                eff = pd.Timestamp(year=ey, month=em, day=12)   # 公布後生效日
            except Exception:
                continue
            out[eff] = round(float(v), 1)
        return pd.Series(out).sort_index()
    except Exception:
        return pd.Series(dtype=float)


HISTORY_START = "2016-01-01"   # 橫截面回測需多年歷史


def _price_inst_finmind(stock_id, start=HISTORY_START):
    """用 FinMind 拉長歷史：還原股價(TaiwanStockPriceAdj) + 三大法人，回 df[Close,Volume,Foreign,Trust]。"""
    import time as _time
    dl = _loader()
    end = datetime.now().strftime("%Y-%m-%d")
    price = None
    for _ in range(2):
        try:
            price = dl.taiwan_stock_daily_adj(stock_id=stock_id, start_date=start, end_date=end)
            if price is not None and not price.empty:
                break
        except Exception:
            _time.sleep(0.8)
    if price is None or price.empty:
        return None
    price = price.rename(columns={"close": "Close", "Trading_Volume": "Volume", "date": "Date"})
    price["Date"] = pd.to_datetime(price["Date"])
    price = price.set_index("Date").sort_index()
    df = price[["Close", "Volume"]].astype(float)
    df = df[df["Close"].notna()]
    # 三大法人（FinMind：columns buy/sell/name）→ 外資/投信淨買
    df["Foreign"] = 0.0; df["Trust"] = 0.0
    try:
        ins = dl.taiwan_stock_institutional_investors(stock_id=stock_id, start_date=start, end_date=end)
        if ins is not None and not ins.empty:
            ins["net"] = ins["buy"].astype(float) - ins["sell"].astype(float)
            ins["Date"] = pd.to_datetime(ins["date"])
            piv = ins.pivot_table(index="Date", columns="name", values="net", aggfunc="sum")
            fmap = {"Foreign_Investor": "Foreign", "Investment_Trust": "Trust"}
            for src, dst in fmap.items():
                if src in piv.columns:
                    df[dst] = piv[src].reindex(df.index).fillna(0)
    except Exception:
        pass
    return df


def get_stock_frame(stock_id):
    """組裝單檔面板（Close/Volume/Foreign/Trust/rev_yoy，FinMind 長歷史）。失敗回 None。"""
    import time as _time
    df = _price_inst_finmind(stock_id)
    if df is None or len(df) < 60:
        return None
    df = df[["Close", "Volume", "Foreign", "Trust"]].copy()
    _time.sleep(0.3)                                  # 節流
    yoy = _month_revenue_yoy(stock_id)
    df["rev_yoy"] = float("nan")
    if len(yoy):
        import numpy as np
        # 交易日索引正規化為 tz-naive datetime64，避免與 yoy 生效日對不齊
        idx = pd.DatetimeIndex(df.index).tz_localize(None) if getattr(df.index, "tz", None) else pd.DatetimeIndex(df.index)
        ev = pd.DatetimeIndex(yoy.index).values.astype("datetime64[ns]")
        vals = yoy.values
        pos = np.searchsorted(ev, idx.values.astype("datetime64[ns]"), side="right") - 1
        df["rev_yoy"] = [round(float(vals[p]), 1) if p >= 0 else float("nan") for p in pos]
    return df


def build_panel(universe=None, use_cache=True, max_age_hours=12):
    """組裝整個股票池的面板 dict[stock_id]->DataFrame，帶磁碟快取。"""
    from quant.universe import get_universe
    universe = universe or get_universe()
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, "panel.pkl")
    if use_cache and os.path.exists(path):
        age_h = (datetime.now().timestamp() - os.path.getmtime(path)) / 3600
        if age_h < max_age_hours:
            try:
                with open(path, "rb") as f:
                    return pickle.load(f)
            except Exception:
                pass
    panel = {}
    for sid in universe:
        try:
            fr = get_stock_frame(sid)
            if fr is not None and len(fr) > 60:
                panel[sid] = fr
        except Exception:
            continue
    with open(path, "wb") as f:
        pickle.dump(panel, f)
    return panel
