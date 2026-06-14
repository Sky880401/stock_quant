"""
A1 資料管線：為股票池組裝「每檔的日頻面板」供橫截面因子計算。

每檔輸出 DataFrame（日期索引）欄位：
  Close, Volume          —— 股價/成交量（FinMind taiwan_stock_daily，長歷史）
  Foreign, Trust, Dealer —— 三大法人「淨買股數」。主來源＝證交所官方 T86
                            （crawlers/twse_institutional.py，免 token、免費）；
                            T86 查無該股/該日（上櫃股、或當下未公布）才回退 FinMind 備援。
  inst_unreliable        —— 健全檢查標記：成交量>0 卻三大法人全 0 或出現 NaN 的「不可信」筆。
                            專治 FinMind 額度用盡時靜默回 0 的故障。
  rev_yoy                —— 月營收年增率(%)，依「公布日」落後對齊（避免 look-ahead）

三大法人來源策略（省 FinMind 配額）：
  1) 主來源逐日查 T86 全市場日報（每日一請求、本地快取，全股池共用）。
  2) 僅當某股有「T86 查無」的日子時，才對該股額外打一次 FinMind 補那幾天 → TWSE 個股完全
     不會觸發 FinMind，配額只花在上櫃/缺漏。
  3) 不論來源都跑單一來源健全檢查；另有獨立的 reconcile_sample() 抽樣對帳（預設關閉）。

月營收 look-ahead 處理：M 月營收約於 M+1 月 10 日公布，故把該 YoY 的「生效日」設為
M+1 月 12 日，再 forward-fill 到日頻，確保回測當下不會用到未公布的數字。
"""
import logging
import os
import pickle
from datetime import datetime

import pandas as pd

from crawlers import twse_institutional as _t86

log = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "quant_cache")


_DL = None
_last_call = [0.0]
_MIN_INTERVAL = 0.9   # FinMind 有短時間爆量限制(與每小時600不同)，每次呼叫間隔節流


def _throttle():
    import time as _t
    dt_ = _t.time() - _last_call[0]
    if dt_ < _MIN_INTERVAL:
        _t.sleep(_MIN_INTERVAL - dt_)
    _last_call[0] = _t.time()


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
    for attempt in range(3):
        try:
            _throttle()
            df = _loader().taiwan_stock_month_revenue(
                stock_id=stock_id, start_date="2015-01-01",
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


def _price_finmind(stock_id, start=HISTORY_START):
    """用 FinMind 拉長歷史「股價」(未還原 taiwan_stock_daily) → df[Close,Volume]。失敗回 None。

    法人在此不抓；法人主來源為 T86，見 _attach_institutional()。
    """
    import time as _time
    dl = _loader()
    end = datetime.now().strftime("%Y-%m-%d")
    price = None
    for _ in range(3):
        try:
            _throttle()
            # 還原股價(adj)需付費級；免費用未還原 taiwan_stock_daily（除息跳空為已知雜訊）
            price = dl.taiwan_stock_daily(stock_id=stock_id, start_date=start, end_date=end)
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
    return df


# FinMind 三大法人 name 欄 → 我方欄位（與既有對應一致：外資、投信；自營商盡力併）
_FM_INST_MAP = {
    "Foreign_Investor": "Foreign",
    "Investment_Trust": "Trust",
    "Dealer_self": "Dealer",
    "Dealer_Hedging": "Dealer",
}


def _finmind_institutional(stock_id, start, end):
    """FinMind 三大法人「淨買股數」→ df[index=Date, Foreign/Trust/Dealer]。失敗回 None。

    僅當 T86 對該股有缺漏日時才會被呼叫（備援），避免無謂消耗 FinMind 配額。
    """
    import time as _time
    dl = _loader()
    ins = None
    for _ in range(3):
        try:
            _throttle()
            ins = dl.taiwan_stock_institutional_investors(
                stock_id=stock_id, start_date=start, end_date=end)
            if ins is not None and not ins.empty:
                break
        except Exception:
            _time.sleep(0.8)
    if ins is None or ins.empty:
        return None
    try:
        ins = ins.copy()
        ins["net"] = ins["buy"].astype(float) - ins["sell"].astype(float)
        ins["Date"] = pd.to_datetime(ins["date"])
        ins["col"] = ins["name"].map(_FM_INST_MAP)
        ins = ins[ins["col"].notna()]
        piv = ins.pivot_table(index="Date", columns="col", values="net", aggfunc="sum")
        for c in ("Foreign", "Trust", "Dealer"):
            if c not in piv.columns:
                piv[c] = 0.0
        return piv[["Foreign", "Trust", "Dealer"]].fillna(0.0)
    except Exception:
        return None


def _attach_institutional(df, stock_id, throttle=0.35, inst_start=None):
    """把三大法人併入 df：主來源 T86，缺漏日回退 FinMind 備援。回傳同一 df。

    新增欄：Foreign/Trust/Dealer（淨買股數）、inst_unreliable（bool 健全檢查標記）。
    來源策略：先逐日查 T86 全市場日報（本地快取、全股池共用）；只有當「T86 查無」的
    交易日存在時，才對該股打一次 FinMind 補那幾天 → TWSE 個股完全不觸發 FinMind。

    inst_start：若指定（Timestamp/str），只對 >= inst_start 的交易日抓/併法人；更早的日子
      法人留 0、且**不觸發任何 T86/FinMind 抓取**。用途：價格歷史可向前拉很長（FinMind 便宜、
      供因子暖身），但法人只在 T86 快取窗內抓（慢/稀缺），避免回測暖身段把 T86 逐日打爆。
    """
    import time as _time
    clean = str(stock_id).split(".")[0]
    for col in ("Foreign", "Trust", "Dealer"):
        df[col] = 0.0
    inst_start = pd.Timestamp(inst_start) if inst_start is not None else None

    # ---- pass 1：主來源 T86（逐日，沿用 crawler 的快取/抓取，不重寫抓取邏輯）----
    missing = []   # T86 查無該股的日期
    cache_mem = {}
    for ts in df.index:
        if inst_start is not None and ts < inst_start:
            continue   # 暖身段：法人留 0，不抓
        dkey = ts.strftime("%Y%m%d")
        day = cache_mem.get(dkey)
        if day is None:
            path = os.path.join(_t86.CACHE_DIR, f"{dkey}.json")
            existed = os.path.exists(path)
            day = _t86.fetch_day(dkey)
            cache_mem[dkey] = day
            if not existed:
                _time.sleep(throttle)   # 只有真的去抓才節流
        rec = day.get(clean)
        if rec:
            df.at[ts, "Foreign"] = rec["Foreign"]
            df.at[ts, "Trust"] = rec["Trust"]
            df.at[ts, "Dealer"] = rec["Dealer"]
        else:
            missing.append(ts)

    n_t86 = len(df) - len(missing)
    n_fm = 0
    # ---- pass 2：僅對 T86 缺漏日回退 FinMind 備援 ----
    if missing:
        start = min(missing).strftime("%Y-%m-%d")
        end = max(missing).strftime("%Y-%m-%d")
        fm = _finmind_institutional(clean, start, end)
        if fm is not None and not fm.empty:
            miss_set = set(missing)
            for ts in fm.index:
                if ts in miss_set:
                    df.at[ts, "Foreign"] = fm.at[ts, "Foreign"]
                    df.at[ts, "Trust"] = fm.at[ts, "Trust"]
                    df.at[ts, "Dealer"] = fm.at[ts, "Dealer"]
                    n_fm += 1
            log.info("[data_hub] %s 此筆改用 FinMind 備援：T86 查無 %d 個交易日，"
                     "FinMind 補上 %d 筆（例 %s）",
                     clean, len(missing), n_fm, start)
        else:
            log.info("[data_hub] %s T86 查無 %d 個交易日，FinMind 備援亦無資料（留 0）",
                     clean, len(missing))

    n_none = len(missing) - n_fm
    log.info("[data_hub] %s 法人來源彙整：T86 %d 筆 / FinMind 備援 %d 筆 / 缺 %d 筆",
             clean, n_t86, n_fm, n_none)

    _sanity_check_institutional(df, clean)
    return df


def _sanity_check_institutional(df, stock_id):
    """單一來源健全檢查（不論來源都跑）：成交量>0 卻三大法人全 0、或 NaN/異常 → 標記不可信。

    在 df 上新增 bool 欄 inst_unreliable，並依不可信比例記 WARNING/INFO。
    這專治 FinMind 額度用盡時「靜默回 0」的故障（也涵蓋 T86 當日未公布）。
    """
    inst = df[["Foreign", "Trust", "Dealer"]]
    vol = df["Volume"].fillna(0)
    all_zero = (inst.fillna(0) == 0).all(axis=1)
    has_nan = inst.isna().any(axis=1)
    unreliable = ((vol > 0) & all_zero) | has_nan
    df["inst_unreliable"] = unreliable
    n_bad = int(unreliable.sum())
    if n_bad:
        frac = n_bad / max(len(df), 1)
        msg = ("[data_hub] %s 法人健全檢查：%d/%d 筆可疑（成交量>0 但三大法人全 0 或 NaN），"
               "已標記 inst_unreliable")
        # 大比例可疑＝明顯故障（如配額用盡靜默回 0）→ WARNING；零星可能只是無法人進出 → INFO
        if frac >= 0.5:
            log.warning(msg + "；可疑比例 %.0f%% 偏高，疑似資料來源故障", stock_id, n_bad, len(df), frac * 100)
        else:
            log.info(msg, stock_id, n_bad, len(df))
    return df


FRAMES_DIR = os.path.join(CACHE_DIR, "frames")


def get_stock_frame(stock_id, use_cache=True, max_age_days=2, start=None, inst_start=None):
    """組裝單檔面板（Close/Volume/Foreign/Trust/Dealer/inst_unreliable/rev_yoy）。失敗回 None。

    股價走 FinMind 長歷史；三大法人走「T86 主 + FinMind 備援」（見 _attach_institutional）。
    逐檔磁碟快取：抓過的存 data/quant_cache/frames/<sid>.pkl，回填可中斷續跑、
    重建免重打 FinMind（省配額）。

    start     : 股價歷史起點（FinMind，便宜）；None=用 HISTORY_START。
    inst_start: 法人(T86/FinMind)只抓 >= 此日的交易日（見 _attach_institutional）；
                供回測「價格暖身長、法人窗短」用。非預設值時自動換獨立快取檔名，避免污染線上 frame。
    """
    import time as _time
    os.makedirs(FRAMES_DIR, exist_ok=True)
    tag = ""
    if start is not None or inst_start is not None:
        tag = "_bt%s_%s" % (str(start or "")[:10], str(inst_start or "")[:10])
    fpath = os.path.join(FRAMES_DIR, f"{stock_id}{tag}.pkl")
    if use_cache and os.path.exists(fpath):
        age_d = (datetime.now().timestamp() - os.path.getmtime(fpath)) / 86400
        if age_d < max_age_days:
            try:
                return pickle.load(open(fpath, "rb"))
            except Exception:
                pass
    df = _price_finmind(stock_id, start=start or HISTORY_START)
    if df is None or len(df) < 60:
        return None
    df = _attach_institutional(df, stock_id, inst_start=inst_start)  # T86 主 + FinMind 備援 + 健全檢查
    df = df[["Close", "Volume", "Foreign", "Trust", "Dealer", "inst_unreliable"]].copy()
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
    try:
        pickle.dump(df, open(fpath, "wb"))   # 逐檔快取，回填可續跑
    except Exception:
        pass
    return df


def build_panel(universe=None, use_cache=True, max_age_hours=12,
                start=None, inst_start=None, cache_path=None):
    """組裝整個股票池的面板 dict[stock_id]->DataFrame，帶磁碟快取。

    start/inst_start：見 get_stock_frame（回測用：價格暖身長、法人窗短）。
    cache_path：自訂聚合快取檔（非預設窗時建議指定，避免覆蓋線上 panel.pkl）。
    """
    from quant.universe import get_universe
    universe = universe or get_universe()
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = cache_path or os.path.join(CACHE_DIR, "panel.pkl")
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
            fr = get_stock_frame(sid, start=start, inst_start=inst_start)
            if fr is not None and len(fr) > 60:
                panel[sid] = fr
        except Exception:
            continue
    # 只在 panel 非空時才寫快取：避免某次抓取全失敗(空 panel)被快取，
    # 之後 max_age_hours 內持續回傳空結果(選股/回測拿到空資料卻不報錯)。
    if panel:
        with open(path, "wb") as f:
            pickle.dump(panel, f)
    return panel


def reconcile_sample(samples=None, tolerance=0, verbose=True):
    """【獨立抽樣對帳】抽幾檔×幾日同時抓 T86 與 FinMind，比對三大法人(外資+投信)合計。

    **預設不在回測流程內呼叫**（回測上千筆若每筆雙抓會打爆 FinMind 免費額度）；
    供手動或定期 debug 跑。差異(股數)超過 tolerance 即記 WARNING。

    參數
      samples   : [(stock_id, "YYYYMMDD"), ...]；None 時用內建少量樣本（2330 等）。
      tolerance : 容忍差異（股）。T86 與 FinMind 同為股數、定義一致時應接近 0。
    回傳 list[dict]：每筆 {stock,date,t86,finmind,diff,ok,source_note}。
    """
    if samples is None:
        # 由呼叫端傳交易日較準；這裡給少量範例股，日期需呼叫端覆寫或自行確認為交易日
        samples = []
        log.warning("[reconcile] 未提供 samples（[(stock_id, 'YYYYMMDD')...]）→ 不對帳")
        return []

    results = []
    for sid, dkey in samples:
        clean = str(sid).split(".")[0]
        # T86：全市場日報取該股外資+投信合計
        day = _t86.fetch_day(dkey)
        rec = day.get(clean)
        t86_sum = None if rec is None else (rec["Foreign"] + rec["Trust"])
        # FinMind：該股單日外資+投信合計
        d_iso = f"{dkey[:4]}-{dkey[4:6]}-{dkey[6:]}"
        fm = _finmind_institutional(clean, d_iso, d_iso)
        fm_sum = None
        if fm is not None and not fm.empty:
            ts = pd.Timestamp(d_iso)
            if ts in fm.index:
                fm_sum = float(fm.at[ts, "Foreign"] + fm.at[ts, "Trust"])
        if t86_sum is None or fm_sum is None:
            note = f"無法對帳（T86={t86_sum}, FinMind={fm_sum}）"
            ok = None
            diff = None
            if verbose:
                log.warning("[reconcile] %s %s %s", clean, dkey, note)
        else:
            diff = abs(t86_sum - fm_sum)
            ok = diff <= tolerance
            note = "一致" if ok else f"不符！差異 {diff} 股 > 容忍 {tolerance}"
            if verbose:
                (log.info if ok else log.warning)(
                    "[reconcile] %s %s T86=%s FinMind=%s → %s",
                    clean, dkey, t86_sum, fm_sum, note)
        results.append({"stock": clean, "date": dkey, "t86": t86_sum,
                        "finmind": fm_sum, "diff": diff, "ok": ok, "source_note": note})
    return results
