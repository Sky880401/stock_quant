"""
A4 每日選股排行：用橫截面綜合因子對股票池排序，回傳 Top-N（做多候選）與 Bottom-N（避開）。

非預測單股絕對漲跌，而是「相對強弱排序」——A3 回測顯示這條有微弱但真實的正向 IC。
"""
import pandas as pd


def rank_universe(top_n=10):
    """回傳 (as_of_date, top_list, bottom_list)。每筆: dict(sid, score, mom, revyoy, inst)。"""
    from quant.data_hub import build_panel
    from quant.factors import build_factor_timeseries, cross_section_table

    panel = build_panel(use_cache=True)
    fts = build_factor_timeseries(panel)
    if not fts:
        return None, [], []
    as_of = max(f.index[-1] for f in fts.values())
    tbl = cross_section_table(fts, as_of)
    if tbl.empty:
        return as_of, [], []

    def pack(df):
        out = []
        for sid, r in df.iterrows():
            out.append({
                "sid": sid,
                "score": round(float(r["score"]), 2),
                "mom": round(float(r["mom"]) * 100, 1),
                "revyoy": round(float(r["revyoy"]), 1),
                "inst": round(float(r["inst"]) * 100, 2),
            })
        return out

    return as_of, pack(tbl.head(top_n)), pack(tbl.tail(top_n).iloc[::-1])
