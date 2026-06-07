"""
M2 #1 — revyoy 只做多『往前紙上交易帳本』(forward paper trading ledger)。

這是作弊不了的期末考：每月記下「現在該買哪些股」(只用當下資料)，
往前追蹤真實報酬 vs 大盤。未來還沒發生 → 沒有前視、沒有存活偏誤、不能事後改。
帳本進 git → 歷史不可竄改(改了有紀錄)。

模式：
  --open  : 用最新可得資料產生 revyoy Top-quintile 組合，append 一筆 open 紀錄
            (同一個資料月份已存在就不重複)。entry 價=該股最新收盤。
  --show  : 印出目前帳本。
  (--mark : 之後補：對已過持有期的 open 紀錄抓真實出場價、結算 vs 大盤。)

與回測一致：top 20%（quintile 最高分層）、等權、只做多、基準=全候選股等權。
"""
import os
import sys
import json
import argparse
import datetime
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

envp = os.path.join(ROOT, ".env")
if os.path.exists(envp):
    for line in open(envp):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from quant.data_hub import build_panel
from quant.factors import build_factor_timeseries
from quant.backtest_xs import _factor_scores, _master_dates

FACTOR = "revyoy"
EXCLUDE_PREFIX = ("28",)   # 排除金融保險類(28xx)：金控月營收非真業績、見 holdout 註解
N_Q = 5            # quintile → 取最高 1/5
MIN_LIQ = 2e7
MIN_NAMES = 15
PANEL_CACHE = os.path.join(ROOT, "data", "quant_cache", "panel_bt_2024.pkl")
LEDGER = os.path.join(ROOT, "data", "paper", "paper_ledger.json")


def load_ledger():
    if os.path.exists(LEDGER):
        return json.load(open(LEDGER))
    return {"strategy": "revyoy_top_quintile_long_only_equal_weight",
            "benchmark": "universe_equal_weight",
            "horizon_days": 20, "created": None, "entries": []}


def save_ledger(led):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    json.dump(led, open(LEDGER, "w"), ensure_ascii=False, indent=2, default=str)


def latest_scored_date(fts, dates):
    """從最後一天往回找：第一個 revyoy 橫截面有 >=MIN_NAMES 檔的日期。"""
    for d in reversed(dates):
        sc = _factor_scores(fts, d, FACTOR, MIN_LIQ)
        sc = {s: v for s, v in sc.items() if not s.startswith(EXCLUDE_PREFIX)}
        if len(sc) >= MIN_NAMES:
            return d, sc
    return None, {}


def open_entry(led):
    panel = build_panel(cache_path=PANEL_CACHE, use_cache=True, max_age_hours=99999)
    fts = build_factor_timeseries(panel)
    closes = {s: f["close"] for s, f in fts.items()}
    dates = _master_dates(panel)
    d, scores = latest_scored_date(fts, dates)
    if d is None:
        print("找不到足夠橫截面，無法開倉"); return led

    sc = pd.Series(scores).sort_values()       # 低 -> 高
    ordered = list(sc.index)
    m = len(ordered)
    top = ordered[int(round((N_Q - 1) * m / N_Q)):]   # 最高 1/5
    w = round(1.0 / len(top), 4)

    data_month = str(d.date())[:7]
    if any(e["as_of_data"][:7] == data_month for e in led["entries"]):
        print("資料月份 %s 已有紀錄，不重複開倉。用 --show 看帳本。" % data_month)
        return led

    holdings = []
    for s in top:
        px = closes[s].asof(d)
        rev = fts[s]["revyoy"].loc[:d]
        holdings.append({
            "sid": s,
            "entry_price": round(float(px), 2) if pd.notna(px) else None,
            "weight": w,
            "revyoy_z": round(float(scores[s]), 3),
            "rev_yoy_pct": round(float(rev.iloc[-1]), 2) if len(rev) else None,
        })

    entry = {
        "entry_no": len(led["entries"]) + 1,
        "logged_on": datetime.date.today().isoformat(),
        "as_of_data": str(d.date()),     # 用到的最新資料日 = 進場基準日
        "n_holdings": len(holdings),
        "method": "revyoy top quintile (top 20%%), equal weight, long-only, no-lookahead",
        "holdings": sorted(holdings, key=lambda h: -h["revyoy_z"]),
        "status": "open",
        "scheduled_exit_after": "~20 交易日(約1個月)後 --mark 結算",
        "exit_date": None, "exit_value_return_pct": None,
        "benchmark_return_pct": None, "excess_pct": None,
    }
    led["entries"].append(entry)
    if led.get("created") is None:
        led["created"] = datetime.date.today().isoformat()
    save_ledger(led)
    print("✅ 已記第 %d 筆 paper 紀錄（資料基準日 %s，%d 檔，等權各 %.1f%%）"
          % (entry["entry_no"], entry["as_of_data"], len(holdings), w * 100))
    return led


def show(led):
    print("策略：%s ｜基準：%s ｜建立：%s ｜共 %d 筆"
          % (led["strategy"], led["benchmark"], led.get("created"), len(led["entries"])))
    for e in led["entries"]:
        print("\n── 第%d筆 | 進場基準日 %s | %s | %d檔 ──"
              % (e["entry_no"], e["as_of_data"], e["status"], e["n_holdings"]))
        for h in e["holdings"]:
            print("   %-7s 進場價=%-8s revyoy_z=%+.2f 月營收YoY=%s%%"
                  % (h["sid"], h["entry_price"], h["revyoy_z"], h["rev_yoy_pct"]))
        if e["status"] == "closed":
            print("   → 出場 %s：組合報酬=%+.2f%% 大盤=%+.2f%% 超額=%+.2f%%"
                  % (e["exit_date"], e["exit_value_return_pct"],
                     e["benchmark_return_pct"], e["excess_pct"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    led = load_ledger()
    if a.open:
        led = open_entry(led)
    show(led)


if __name__ == "__main__":
    main()
