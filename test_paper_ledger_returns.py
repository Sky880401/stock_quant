#!/usr/bin/env python3
"""
#901 模擬下單報酬視角（--returns）測試。

Sky 指示：成本先不抓，先驗『模擬下單到底可得多少報酬』。
本測試覆蓋四種必驗情境（不依賴真實 cache，價格以 fake price_fn 注入）：
  a. 無前進 closed 但有前進 open → 只能報未實現 MTM，realized 為空。
  b. 有前進 closed → realized 報酬可算。
  c. 回填不得混入前進 realized 主結論（realized_summary 只吃 fwd_closed）。
  d. 缺價格 → 列 missing，不可編價、不納入統計。

venv 無 pytest，故附 main runner 直接跑。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.paper_ledger import (classify_entries, realized_summary,
                                   open_mtm_summary, mtm_open_holdings,
                                   returns_summary, RT)


def _holding(sid, p0):
    return {"sid": sid, "entry_price": p0, "weight": 0.1}


def _fwd_open(no, holdings):
    return {"entry_no": no, "kind": "forward", "status": "open",
            "as_of_data": "2026-06-05", "n_holdings": len(holdings),
            "holdings": holdings, "exit_value_return_pct": None}


def _fwd_closed(no, ret):
    return {"entry_no": no, "kind": "forward", "status": "closed",
            "as_of_data": "2024-0%d-01" % no, "exit_date": "2024-0%d-28" % no,
            "n_holdings": 3, "exit_value_return_pct": ret}


def _bf_closed(no, ret):
    e = _fwd_closed(no, ret)
    e["kind"] = "backfill_biased"
    return e


def _fake_prices(table):
    """table: {sid: (price, date)}；缺者回 (None, None) 模擬取不到價。"""
    def fn(sid):
        return table.get(sid, (None, None))
    return fn


# ── 情境 a：無前進 closed 但有前進 open → 只能報未實現 MTM ─────────────────
def test_a_open_mtm_only_no_forward_closed():
    es = [_bf_closed(1, 8.0), _fwd_open(9, [_holding("AAA", 100.0),
                                            _holding("BBB", 200.0)])]
    bf_closed, fwd_closed, fwd_open = classify_entries(es)
    assert fwd_closed == [], "前進 closed 應為 0"
    rs = realized_summary(fwd_closed)
    assert rs["count"] == 0, "realized 無樣本不可編造"
    assert rs["avg_return_pct"] is None and rs["net_if_exit_now_pct"] is None

    # AAA +10%、BBB -5% → 毛 = +2.5%；現在出場淨 = 2.5 - RT%
    prices = _fake_prices({"AAA": (110.0, "2026-06-12"), "BBB": (190.0, "2026-06-11")})
    ms = open_mtm_summary(fwd_open, prices)
    assert ms["count"] == 2 and ms["missing_count"] == 0
    assert abs(ms["gross_equal_weight_return_pct"] - 2.5) < 1e-9
    assert abs(ms["net_if_exit_now_pct"] - (2.5 - RT * 100)) < 1e-9
    assert ms["win_rate"] == 50.0
    # 快取跨日要明示 min/max
    assert ms["price_date_min"] == "2026-06-11" and ms["price_date_max"] == "2026-06-12"
    print("✅ a 無前進 closed：realized 空、開倉 MTM 毛+2.50%%/淨%+.2f%%、跨日 %s..%s"
          % (ms["net_if_exit_now_pct"], ms["price_date_min"], ms["price_date_max"]))


# ── 情境 b：有前進 closed → realized 可算 ─────────────────────────────────
def test_b_forward_closed_realized_computed():
    fwd_closed = [_fwd_closed(1, 6.0), _fwd_closed(2, -2.0)]
    rs = realized_summary(fwd_closed)
    assert rs["count"] == 2
    assert abs(rs["avg_return_pct"] - 2.0) < 1e-9            # (6 + -2)/2
    assert abs(rs["net_if_exit_now_pct"] - 2.0) < 1e-9       # 已含成本 → net = mean
    assert abs(rs["gross_equal_weight_return_pct"] - (2.0 + RT * 100)) < 1e-9  # 還原毛
    assert rs["win_rate"] == 50.0
    assert rs["best"] == 6.0 and rs["worst"] == -2.0
    assert rs["price_date_min"] == "2024-01-28" and rs["price_date_max"] == "2024-02-28"
    print("✅ b 前進 closed 2 筆：avg+2.00%% net+2.00%% gross%+.2f%% win50%%"
          % rs["gross_equal_weight_return_pct"])


# ── 情境 c：回填不得混入前進 realized 主結論 ──────────────────────────────
def test_c_backfill_excluded_from_realized():
    es = [_bf_closed(1, 30.0), _bf_closed(2, 25.0), _fwd_closed(3, 1.0),
          _fwd_open(4, [_holding("AAA", 100.0)])]
    bf_closed, fwd_closed, fwd_open = classify_entries(es)
    assert len(bf_closed) == 2 and len(fwd_closed) == 1
    rs = realized_summary(fwd_closed)
    # realized 只反映那 1 筆前進 (+1%)，絕不被漂亮回填 (+30/+25) 汙染
    assert rs["count"] == 1 and abs(rs["avg_return_pct"] - 1.0) < 1e-9
    bs = returns_summary([e["exit_value_return_pct"] for e in bf_closed],
                         cost_already_applied=True)
    assert bs["count"] == 2 and abs(bs["avg_return_pct"] - 27.5) < 1e-9
    assert rs["avg_return_pct"] != bs["avg_return_pct"], "前進與回填線必須分離"
    print("✅ c 回填(avg+27.50%%)不混入前進 realized(avg+1.00%%)，主結論只採前進")


# ── 情境 d：缺價格 → 列 missing，不可編、不納入統計 ───────────────────────
def test_d_missing_price_listed_not_fabricated():
    entry = _fwd_open(7, [_holding("AAA", 100.0), _holding("GONE", 50.0),
                          _holding("ZERO", 80.0)])
    # GONE 取不到價；ZERO 取到 0（無效）→ 兩者皆 missing
    prices = _fake_prices({"AAA": (120.0, "2026-06-12"), "ZERO": (0.0, "2026-06-12")})
    mtm = mtm_open_holdings([entry], prices)
    priced = {r["sid"] for r in mtm["rets"]}
    missing = {m["sid"] for m in mtm["missing"]}
    assert priced == {"AAA"}, "只有 AAA 有有效價"
    assert missing == {"GONE", "ZERO"}, "缺價/無效價皆列 missing"

    ms = open_mtm_summary([entry], prices)
    assert ms["count"] == 1 and ms["missing_count"] == 2
    assert abs(ms["gross_equal_weight_return_pct"] - 20.0) < 1e-9  # 只用 AAA，不編缺價
    print("✅ d 缺價列 missing：有價 %s、missing %s、統計只用有價檔"
          % (sorted(priced), sorted(missing)))


def _run():
    tests = [test_a_open_mtm_only_no_forward_closed,
             test_b_forward_closed_realized_computed,
             test_c_backfill_excluded_from_realized,
             test_d_missing_price_listed_not_fabricated]
    for t in tests:
        t()
    print("\n🎉 全部 %d 項通過" % len(tests))


if __name__ == "__main__":
    _run()
