#!/usr/bin/env python3
"""
data_hub 三大法人資料層測試：T86 主 + FinMind 備援 + 交叉驗證。

(a) mock 四條邏輯：T86 主、FinMind 備援、全 0 偵測、抽樣對帳示警。
(b) 真實 smoke：2330 最近交易日走 T86 的數字，並與 FinMind 對一筆（應相同）。

用法：
  venv/bin/python test_data_hub_institutional.py          # 只跑 mock 單元測試
  venv/bin/python test_data_hub_institutional.py --smoke  # 另跑真實 smoke（會打 T86/FinMind）
"""
import logging
import sys
from unittest import mock

import pandas as pd

import quant.data_hub as dh

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def _price_df(dates, vol=1000):
    idx = pd.to_datetime(dates)
    return pd.DataFrame({"Close": [100.0] * len(idx), "Volume": [float(vol)] * len(idx)}, index=idx)


def test_t86_primary():
    """(1) T86 有資料 → 用 T86，且完全不打 FinMind。"""
    df = _price_df(["2026-06-03", "2026-06-04"])
    t86_day = {
        "20260603": {"2330": {"Foreign": 5000, "Trust": 1000, "Dealer": 200}},
        "20260604": {"2330": {"Foreign": -3000, "Trust": 500, "Dealer": 0}},
    }
    with mock.patch.object(dh._t86, "fetch_day", side_effect=lambda d: t86_day[d]) as m_t86, \
         mock.patch.object(dh, "_finmind_institutional") as m_fm:
        out = dh._attach_institutional(df, "2330", throttle=0)
    assert out.loc["2026-06-03", "Foreign"] == 5000
    assert out.loc["2026-06-04", "Foreign"] == -3000
    assert out.loc["2026-06-03", "Trust"] == 1000
    m_fm.assert_not_called()            # 關鍵：T86 全覆蓋 → 不消耗 FinMind 配額
    assert not out["inst_unreliable"].any()
    print("✅ test_t86_primary：T86 主來源、未觸發 FinMind")


def test_finmind_fallback():
    """(2) T86 查無（上櫃股/未公布）→ 回退 FinMind 備援補那幾天。"""
    df = _price_df(["2026-06-03", "2026-06-04"])
    fm_df = pd.DataFrame(
        {"Foreign": [777.0, 888.0], "Trust": [11.0, 22.0], "Dealer": [0.0, 0.0]},
        index=pd.to_datetime(["2026-06-03", "2026-06-04"]),
    )
    with mock.patch.object(dh._t86, "fetch_day", return_value={}) as m_t86, \
         mock.patch.object(dh, "_finmind_institutional", return_value=fm_df) as m_fm:
        out = dh._attach_institutional(df, "6488", throttle=0)
    assert m_fm.call_count == 1          # 只打一次 FinMind 補缺
    assert out.loc["2026-06-03", "Foreign"] == 777
    assert out.loc["2026-06-04", "Foreign"] == 888
    print("✅ test_finmind_fallback：T86 查無 → FinMind 備援補上")


def test_all_zero_detection():
    """(3a) 成交量>0 卻三大法人全 0（FinMind 額度用盡靜默回 0 的故障）→ 標記不可信 + WARNING。"""
    df = _price_df(["2026-06-03", "2026-06-04", "2026-06-05"], vol=5000)
    # T86、FinMind 皆查無 → 全留 0；但成交量>0 → 應全部標記不可信
    with mock.patch.object(dh._t86, "fetch_day", return_value={}), \
         mock.patch.object(dh, "_finmind_institutional", return_value=None):
        import logging as _lg
        logger = _lg.getLogger("quant.data_hub")
        records = []
        h = _lg.Handler(); h.emit = lambda r: records.append(r)
        logger.addHandler(h)
        out = dh._attach_institutional(df, "9999", throttle=0)
        logger.removeHandler(h)
    assert out["inst_unreliable"].all()                       # 三筆全標記
    assert any(r.levelno == _lg.WARNING for r in records)     # 高比例 → WARNING
    print("✅ test_all_zero_detection：量>0 但法人全 0 → inst_unreliable + WARNING")


def test_reconcile_mismatch():
    """(3b) 抽樣對帳：T86 與 FinMind 合計差異 > 容忍值 → WARNING 示警。"""
    t86_day = {"20260603": {"2330": {"Foreign": 5000, "Trust": 1000, "Dealer": 0}}}
    fm_df = pd.DataFrame({"Foreign": [9000.0], "Trust": [1000.0], "Dealer": [0.0]},
                         index=pd.to_datetime(["2026-06-03"]))
    import logging as _lg
    logger = _lg.getLogger("quant.data_hub")
    records = []
    h = _lg.Handler(); h.emit = lambda r: records.append(r)
    logger.addHandler(h)
    with mock.patch.object(dh._t86, "fetch_day", side_effect=lambda d: t86_day.get(d, {})), \
         mock.patch.object(dh, "_finmind_institutional", return_value=fm_df):
        res = dh.reconcile_sample([("2330", "20260603")], tolerance=100)
    logger.removeHandler(h)
    assert len(res) == 1
    # T86 合計 6000 vs FinMind 10000 → 差 4000 > 100 → 不符
    assert res[0]["t86"] == 6000 and res[0]["finmind"] == 10000
    assert res[0]["ok"] is False and res[0]["diff"] == 4000
    assert any(r.levelno == _lg.WARNING for r in records)
    print("✅ test_reconcile_mismatch：對帳差異超容忍 → WARNING")


def smoke_2330():
    """(b) 真實 smoke：2330 最近交易日，T86 數字 + 與 FinMind 對一筆。"""
    from crawlers import twse_institutional as t86
    from datetime import datetime, timedelta

    # 往回找最近一個 T86 有資料的交易日
    day = None; dkey = None
    d = datetime.now()
    for _ in range(10):
        k = d.strftime("%Y%m%d")
        got = t86.fetch_day(k)
        if got and "2330" in got:
            day, dkey = got, k
            break
        d -= timedelta(days=1)
    if not day:
        print("⚠️ smoke：近 10 日 T86 無 2330 資料（假日/未公布？）跳過")
        return
    rec = day["2330"]
    print(f"📊 smoke 2330 @ {dkey}（T86 官方）：外資 {rec['Foreign']} 股 / "
          f"投信 {rec['Trust']} 股 / 自營 {rec['Dealer']} 股")
    # 與 FinMind 對同一日合計
    d_iso = f"{dkey[:4]}-{dkey[4:6]}-{dkey[6:]}"
    fm = dh._finmind_institutional("2330", d_iso, d_iso)
    t86_sum = rec["Foreign"] + rec["Trust"]
    if fm is not None and not fm.empty and pd.Timestamp(d_iso) in fm.index:
        fm_sum = float(fm.loc[pd.Timestamp(d_iso), ["Foreign", "Trust"]].sum())
        diff = abs(t86_sum - fm_sum)
        print(f"   對帳：T86 外資+投信={t86_sum} vs FinMind={fm_sum} → 差異 {diff} 股")
        print("   ✅ 一致" if diff == 0 else f"   ⚠️ 有差異 {diff} 股（檢查定義/額度）")
    else:
        print(f"   FinMind 無此日資料（額度/上櫃？）；T86 外資+投信={t86_sum}")


if __name__ == "__main__":
    test_t86_primary()
    test_finmind_fallback()
    test_all_zero_detection()
    test_reconcile_mismatch()
    print("\n🎉 四條 mock 邏輯全數通過\n")
    if "--smoke" in sys.argv:
        print("=== 真實 smoke（打 T86/FinMind）===")
        smoke_2330()
