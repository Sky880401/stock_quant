#!/usr/bin/env python3
"""
#901 stock 驗證流程第一階段測試：
  - 分線（回填已結算 / 前進已結算 / 前進開倉中）
  - 北極星成本覆蓋率（只採前進 closed；未設成本/無前進 closed/可計算 三種情境）

主結論不得用回填數字假裝 edge：classify_entries 必須把回填 closed 與前進 closed 分開，
北極星 polaris_assessment 只吃 fwd_closed。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.paper_ledger import (classify_entries, group_stats,
                                   polaris_assessment, DEFAULT_VERIFICATION_CAPITAL)


def _bf_closed(no, excess, ret):
    return {"entry_no": no, "kind": "backfill_biased", "status": "closed",
            "as_of_data": "2024-0%d-01" % no, "exit_date": "2024-0%d-28" % no,
            "n_holdings": 15, "exit_value_return_pct": ret,
            "benchmark_return_pct": ret - excess, "excess_pct": excess}


def _fwd_closed(no, excess, ret):
    e = _bf_closed(no, excess, ret)
    e["kind"] = "forward"
    return e


def _fwd_open(no):
    # 舊資料前進筆的 kind 可能是 None；分線需把 None 視為前進
    return {"entry_no": no, "kind": None, "status": "open",
            "as_of_data": "2026-06-05", "n_holdings": 15,
            "exit_value_return_pct": None, "benchmark_return_pct": None,
            "excess_pct": None}


# ── 情境 A：只有回填 closed + 一筆前進 open ──────────────────────────────
def test_backfill_only_plus_one_forward_open():
    es = [_bf_closed(1, 4.0, 6.0), _bf_closed(2, -1.0, 1.0), _fwd_open(9)]
    bf_closed, fwd_closed, fwd_open = classify_entries(es)
    assert len(bf_closed) == 2, "兩筆回填 closed 應入回填線"
    assert fwd_closed == [], "前進 closed 應為 0，不能把回填當前進"
    assert len(fwd_open) == 1 and fwd_open[0]["entry_no"] == 9, "kind=None 的 open 視為前進開倉中"

    # 北極星：有成本但前進 closed=0 → 覆蓋率不可計算（即使回填很漂亮也不採計）
    pa = polaris_assessment(fwd_closed, "3500", DEFAULT_VERIFICATION_CAPITAL)
    assert pa["status"] == "no_fwd_closed", "前進 closed=0 時不可計算覆蓋率"
    assert pa["ai_cost"] == 3500.0
    print("✅ A 只有回填 closed + 一筆前進 open：回填2 / 前進closed0 / 前進open1，覆蓋率不可計算")


# ── 情境 B：設定 AI_COST_MONTHLY_TWD 但無前進 closed ───────────────────────
def test_cost_set_but_no_forward_closed():
    fwd_closed = []
    pa = polaris_assessment(fwd_closed, "3500", DEFAULT_VERIFICATION_CAPITAL)
    assert pa["status"] == "no_fwd_closed"

    # 未設定成本 → 無法驗證成本覆蓋
    pa_none = polaris_assessment([_fwd_closed(1, 4.0, 6.0)], None)
    assert pa_none["status"] == "no_cost", "未設成本應為 no_cost"
    pa_empty = polaris_assessment([_fwd_closed(1, 4.0, 6.0)], "")
    assert pa_empty["status"] == "no_cost", "空字串成本視為未設定"
    print("✅ B 成本已設但無前進 closed → no_fwd_closed；未設成本 → no_cost")


# ── 情境 C：有前進 closed 且能算覆蓋率 ───────────────────────────────────
def test_forward_closed_coverage_computed():
    # 兩筆前進 closed，平均超額 = (4 + 2)/2 = 3.0%
    fwd_closed = [_fwd_closed(1, 4.0, 6.0), _fwd_closed(2, 2.0, 3.0)]
    pa = polaris_assessment(fwd_closed, "3500", 100000.0)
    assert pa["status"] == "computed"
    assert abs(pa["mean_excess"] - 3.0) < 1e-9, "平均超額應為 3.0%"
    # 估算月超額 = 100000 * 3% = 3000
    assert abs(pa["monthly_excess_twd"] - 3000.0) < 1e-9
    # 覆蓋率 = 3000 / 3500 * 100 ≈ 85.7%
    assert abs(pa["coverage_pct"] - (3000.0 / 3500.0 * 100)) < 1e-9
    assert pa["n"] == 2

    # 自訂本金可拉高覆蓋率：本金 200000 → 月超額 6000 → 覆蓋率 ~171%
    pa2 = polaris_assessment(fwd_closed, "3500", 200000.0)
    assert pa2["coverage_pct"] > 100, "本金加倍後應覆蓋成本"

    # 負超額 → 覆蓋率為負（誠實紀錄，不藏）
    pa_neg = polaris_assessment([_fwd_closed(1, -2.0, -1.0)], "3500", 100000.0)
    assert pa_neg["coverage_pct"] < 0

    # group_stats 只看被餵進去的那組
    gs = group_stats(fwd_closed)
    assert gs["n"] == 2 and abs(gs["mean_excess"] - 3.0) < 1e-9
    print("✅ C 有前進 closed：平均超額3.0%、月超額NT$3,000、覆蓋率≈85.7%；本金200k→已覆蓋；負超額誠實為負")


# ── 主結論不得用回填假裝 edge：回填漂亮但前進尚無，覆蓋率仍不可計算 ──────────
def test_backfill_pretty_does_not_fake_edge():
    es = [_bf_closed(i, 5.0, 7.0) for i in range(1, 6)] + [_fwd_open(6)]
    bf_closed, fwd_closed, fwd_open = classify_entries(es)
    assert group_stats(bf_closed)["mean_excess"] == 5.0  # 回填很漂亮
    assert fwd_closed == []
    pa = polaris_assessment(fwd_closed, "3500")
    assert pa["status"] == "no_fwd_closed", "回填再漂亮也不能拿來算覆蓋率"
    print("✅ D 回填5筆平均超額5%%但前進0 → 覆蓋率不可計算，回填不冒充 edge")


def _run():
    tests = [test_backfill_only_plus_one_forward_open,
             test_cost_set_but_no_forward_closed,
             test_forward_closed_coverage_computed,
             test_backfill_pretty_does_not_fake_edge]
    for t in tests:
        t()
    print("\n🎉 全部 %d 項通過" % len(tests))


if __name__ == "__main__":
    _run()
