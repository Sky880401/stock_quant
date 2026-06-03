"""
A2 橫截面因子：把每檔面板轉成多個「慢變」因子時間序列，供 A3 在每個再平衡日
做橫截面 z-score 排名。所有因子皆只用「當下以前」資料計算（無 look-ahead）。

因子（皆為「越大越偏多」方向）：
  mom    : 12-1 月價格動能（過去約 252→21 交易日報酬，跳過最近一月）
  revyoy : 月營收年增率(%)（已於 data_hub 做公布日落後對齊）
  inst   : 近 20 日法人(外資+投信)淨買 / 近 20 日成交量（集中度，順勢）
  lowvol : 近 60 日報酬波動的負值（低波動因子）
另含 close（再平衡用實際價）、dollar_vol（流動性濾網）。
"""
import numpy as np
import pandas as pd


def build_factor_timeseries(panel: dict) -> dict:
    """panel: {stock_id: DataFrame[Close,Volume,Foreign,Trust,rev_yoy]}
    回傳 {stock_id: DataFrame[mom,revyoy,inst,lowvol,close,dollar_vol]}。"""
    out = {}
    for sid, df in panel.items():
        if df is None or len(df) < 260:
            continue
        close = df["Close"].astype(float)
        vol = df["Volume"].astype(float)
        inst_net = (df["Foreign"].fillna(0) + df["Trust"].fillna(0)).astype(float)

        mom = close.shift(21) / close.shift(252) - 1.0
        inst = inst_net.rolling(20).sum() / vol.rolling(20).sum().replace(0, np.nan)
        lowvol = -close.pct_change().rolling(60).std()
        dollar_vol = (close * vol).rolling(20).mean()

        f = pd.DataFrame({
            "mom": mom,
            "revyoy": df["rev_yoy"].astype(float),
            "inst": inst,
            "lowvol": lowvol,
            "close": close,
            "dollar_vol": dollar_vol,
        })
        out[sid] = f
    return out


FACTOR_COLS = ["mom", "revyoy", "inst", "lowvol"]


def _zscore(s: pd.Series) -> pd.Series:
    s = s.astype(float)
    mu, sd = s.mean(), s.std()
    if not sd or np.isnan(sd):
        return pd.Series(0.0, index=s.index)
    return (s - mu) / sd


def cross_section_scores(fts: dict, date, min_liquidity=2e7, weights=None):
    """在某 date 計算各股的綜合分（各因子橫截面 z-score 等權平均）。

    只納入該日各因子皆有值、且流動性達標的股票。回傳 dict{stock: {scores...}}。
    """
    weights = weights or {c: 1.0 for c in FACTOR_COLS}
    rows = {}
    for sid, f in fts.items():
        if date not in f.index:
            # 取 <= date 的最後一筆（再平衡日未必每檔都有交易）
            sub = f.loc[:date]
            if len(sub) == 0:
                continue
            row = sub.iloc[-1]
        else:
            row = f.loc[date]
        if row[["mom", "revyoy", "inst", "lowvol"]].isna().any():
            continue
        if pd.isna(row["dollar_vol"]) or row["dollar_vol"] < min_liquidity:
            continue
        rows[sid] = row
    if len(rows) < 10:
        return {}
    raw = pd.DataFrame(rows).T
    zs = {c: _zscore(raw[c]) for c in FACTOR_COLS}
    composite = sum(weights[c] * zs[c] for c in FACTOR_COLS) / sum(weights.values())
    return {sid: float(composite[sid]) for sid in raw.index}
