"""
M2 #1 — revyoy 只做多『往前紙上交易帳本』(forward paper trading ledger)。

這是作弊不了的期末考：每月記下「現在該買哪些股」(只用當下資料)，
往前追蹤真實報酬 vs 大盤。未來還沒發生 → 沒有前視、沒有存活偏誤、不能事後改。
帳本進 git → 歷史不可竄改(改了有紀錄)。

模式：
  --open      用最新可得資料產生 revyoy Top-quintile 組合，append 一筆 open 紀錄(同資料月不重複)。
  --mark      對已過持有期(20交易日)的 open 紀錄抓真實出場價結算 vs 大盤(全候選股等權)。
  --backfill N  補 N 筆歷史『已結算』紀錄(過去各月真前進報酬)；⚠含存活偏誤，僅供驗算/種子。
  --show      印帳本 + 績效統計。
  --tick      = mark + (距上次開倉滿一個月則 open)，給月度自動化用。

與回測一致：top 20%、等權、只做多、含一買一賣成本(0.586%)、基準=全候選股等權。
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
from quant.backtest_xs import _factor_scores, _master_dates, _round_trip_cost

FACTOR = "revyoy"
EXCLUDE_PREFIX = ("28",)   # 排除金融保險類(28xx)：金控月營收非真業績
N_Q = 5
MIN_LIQ = 2e7
MIN_NAMES = 15
HORIZON = 20               # 持有 20 交易日(約1個月)
RT = _round_trip_cost()    # 一買一賣成本率 ≈ 0.586%
PRICE_START = "2023-01-01"   # 與回測同窗：價格暖身(mom 需~252日)
INST_START = "2024-01-01"    # 法人(T86)窗起點
PANEL_CACHE = os.path.join(ROOT, "data", "quant_cache", "panel_bt_2024.pkl")
LEDGER = os.path.join(ROOT, "data", "paper", "paper_ledger.json")


def load_ledger():
    if os.path.exists(LEDGER):
        return json.load(open(LEDGER))
    return {"strategy": "revyoy_top_quintile_long_only_equal_weight",
            "benchmark": "universe_equal_weight", "cost_round_trip": round(RT, 5),
            "horizon_days": HORIZON, "created": None, "entries": []}


def save_ledger(led):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    json.dump(led, open(LEDGER, "w"), ensure_ascii=False, indent=2, default=str)


def _ctx(fresh=False):
    """載入 panel，回 (closes, fts, dates)。fresh=True 強制重抓最新股價(月度結算/開倉用)。"""
    if fresh:
        panel = build_panel(cache_path=PANEL_CACHE, use_cache=False,
                            start=PRICE_START, inst_start=INST_START)
    else:
        panel = build_panel(cache_path=PANEL_CACHE, use_cache=True, max_age_hours=99999,
                            start=PRICE_START, inst_start=INST_START)
    fts = build_factor_timeseries(panel)
    closes = {s: f["close"] for s, f in fts.items()}
    return closes, fts, _master_dates(panel)


def _top_quintile(fts, d):
    """在 d 日選 revyoy 最高 quintile(ex-financials)；回 (top_list, scores)。"""
    sc = _factor_scores(fts, d, FACTOR, MIN_LIQ)
    sc = {s: v for s, v in sc.items() if not s.startswith(EXCLUDE_PREFIX)}
    if len(sc) < MIN_NAMES:
        return None, {}
    ordered = list(pd.Series(sc).sort_values().index)
    m = len(ordered)
    return ordered[int(round((N_Q - 1) * m / N_Q)):], sc


def _bench_ret(closes, d0, d1):
    """全候選股等權報酬(基準)。"""
    rs = [float(c.asof(d1) / c.asof(d0) - 1) for c in closes.values()
          if pd.notna(c.asof(d0)) and pd.notna(c.asof(d1)) and c.asof(d0) > 0]
    return float(np.mean(rs)) if rs else None


def _port_ret_net(holdings, closes, d1):
    """組合等權報酬(扣一買一賣成本)。"""
    rs = []
    for h in holdings:
        c = closes.get(h["sid"]); p0 = h["entry_price"]
        if c is None or not p0:
            continue
        p1 = c.asof(d1)
        if pd.notna(p1) and p0 > 0:
            rs.append(float(p1 / p0 - 1))
    return (float(np.mean(rs)) - RT) if rs else None


def _make_holdings(top, sc, fts, closes, d):
    w = round(1.0 / len(top), 4)
    hs = []
    for s in top:
        px = closes[s].asof(d)
        rev = fts[s]["revyoy"].loc[:d]
        hs.append({"sid": s, "entry_price": round(float(px), 2) if pd.notna(px) else None,
                   "weight": w, "revyoy_z": round(float(sc[s]), 3),
                   "rev_yoy_pct": round(float(rev.iloc[-1]), 2) if len(rev) else None})
    return sorted(hs, key=lambda h: -h["revyoy_z"])


def open_entry(led, closes=None, fts=None, dates=None):
    if fts is None:
        closes, fts, dates = _ctx()
    d = None
    for dd in reversed(dates):
        top, sc = _top_quintile(fts, dd)
        if top:
            d = dd; break
    if d is None:
        print("找不到足夠橫截面，無法開倉"); return led
    if any(e["as_of_data"][:7] == str(d.date())[:7] for e in led["entries"]):
        print("資料月份 %s 已有紀錄，不重複開倉。" % str(d.date())[:7]); return led
    holdings = _make_holdings(top, sc, fts, closes, d)
    entry = {"entry_no": len(led["entries"]) + 1, "kind": "forward",
             "logged_on": datetime.date.today().isoformat(), "as_of_data": str(d.date()),
             "n_holdings": len(holdings),
             "method": "revyoy top quintile, equal weight, long-only, no-lookahead",
             "holdings": holdings, "status": "open",
             "exit_date": None, "exit_value_return_pct": None,
             "benchmark_return_pct": None, "excess_pct": None}
    led["entries"].append(entry)
    led["created"] = led.get("created") or datetime.date.today().isoformat()
    save_ledger(led)
    print("✅ 已開第 %d 筆(前進)：基準日 %s，%d 檔等權各 %.1f%%"
          % (entry["entry_no"], entry["as_of_data"], len(holdings), holdings[0]["weight"] * 100))
    return led


def mark(led, closes=None, fts=None, dates=None):
    if fts is None:
        closes, fts, dates = _ctx()
    changed = 0
    for e in led["entries"]:
        if e["status"] != "open":
            continue
        d0 = pd.Timestamp(e["as_of_data"])
        i0 = int(dates.searchsorted(d0))
        if i0 + HORIZON > len(dates) - 1:
            due_est = (d0 + pd.Timedelta(days=30)).date()
            print("⏳ 第%d筆未到期(基準日%s)，約 %s(滿20交易日)後可結算"
                  % (e["entry_no"], e["as_of_data"], due_est)); continue
        d1 = dates[i0 + HORIZON]
        port = _port_ret_net(e["holdings"], closes, d1)
        bench = _bench_ret(closes, d0, d1)
        if port is None or bench is None:
            print("⚠ 第%d筆取價不足，略過" % e["entry_no"]); continue
        e["status"] = "closed"; e["exit_date"] = str(d1.date())
        e["exit_value_return_pct"] = round(port * 100, 2)
        e["benchmark_return_pct"] = round(bench * 100, 2)
        e["excess_pct"] = round((port - bench) * 100, 2)
        changed += 1
        print("✅ 第%d筆結算 %s→%s：組合%+.2f%% 大盤%+.2f%% 超額%+.2f%%"
              % (e["entry_no"], e["as_of_data"], e["exit_date"],
                 e["exit_value_return_pct"], e["benchmark_return_pct"], e["excess_pct"]))
    if changed:
        save_ledger(led)
    else:
        print("（沒有到期可結算的開倉）")
    return led


def backfill(led, n, closes=None, fts=None, dates=None):
    if fts is None:
        closes, fts, dates = _ctx()
    months = {e["as_of_data"][:7] for e in led["entries"]}
    end = len(dates) - 1 - HORIZON
    anchors = sorted(i for i in (end - k * HORIZON for k in range(n)) if i > 260)
    added = 0
    for i in anchors:
        d0, d1 = dates[i], dates[i + HORIZON]
        if str(d0.date())[:7] in months:
            continue
        top, sc = _top_quintile(fts, d0)
        if not top:
            continue
        holdings = _make_holdings(top, sc, fts, closes, d0)
        port = _port_ret_net(holdings, closes, d1)
        bench = _bench_ret(closes, d0, d1)
        if port is None or bench is None:
            continue
        led["entries"].append({
            "entry_no": len(led["entries"]) + 1, "kind": "backfill_biased",
            "logged_on": datetime.date.today().isoformat(), "as_of_data": str(d0.date()),
            "n_holdings": len(holdings), "method": "revyoy top quintile (BACKFILL,含存活偏誤)",
            "holdings": holdings, "status": "closed", "exit_date": str(d1.date()),
            "exit_value_return_pct": round(port * 100, 2),
            "benchmark_return_pct": round(bench * 100, 2),
            "excess_pct": round((port - bench) * 100, 2)})
        months.add(str(d0.date())[:7]); added += 1
    # entry_no 依 as_of_data 重排，保持時序
    led["entries"].sort(key=lambda e: e["as_of_data"])
    for k, e in enumerate(led["entries"], 1):
        e["entry_no"] = k
    save_ledger(led)
    print("已補 %d 筆歷史結算（⚠含存活偏誤，僅供驗算/種子，非乾淨前進紀錄）" % added)
    return led


def show(led):
    es = led["entries"]
    print("策略：%s ｜基準：%s ｜成本(來回)%.3f%% ｜共 %d 筆"
          % (led["strategy"], led["benchmark"], led.get("cost_round_trip", RT) * 100, len(es)))
    for e in es:
        tag = "🔮前進" if e.get("kind") != "backfill_biased" else "🧪回填"
        line = "── 第%d筆 %s | 基準日%s | %s | %d檔" % (e["entry_no"], tag, e["as_of_data"], e["status"], e["n_holdings"])
        if e["status"] == "closed":
            line += " → 出場%s 組合%+.2f%% 大盤%+.2f%% 超額%+.2f%%" % (
                e["exit_date"], e["exit_value_return_pct"], e["benchmark_return_pct"], e["excess_pct"])
        print(line)
    closed = [e for e in es if e["status"] == "closed"]
    if closed:
        fwd = [e for e in closed if e.get("kind") != "backfill_biased"]
        ex = [e["excess_pct"] for e in closed]
        beat = np.mean([1.0 if x > 0 else 0.0 for x in ex]) * 100
        eq = float(np.prod([1 + e["exit_value_return_pct"] / 100 for e in closed]))
        print("\n📊 已結算 %d 筆（前進%d / 回填%d）：贏大盤 %.0f%%、平均超額 %+.2f%%/月、累積組合淨值 %.2fx"
              % (len(closed), len(fwd), len(closed) - len(fwd), beat, float(np.mean(ex)), eq))
    open_n = [e for e in es if e["status"] == "open"]
    if open_n:
        print("⏳ 開倉中未結算：%d 筆（到期後 --mark 結算）" % len(open_n))
    # 北極星對照（中台監督）：AI 月成本 vs 紙上策略覆蓋能力。
    # 只採「前進」筆（回填筆含存活偏誤不採計）；成本由 .env AI_COST_MONTHLY_TWD 設定，
    # 未設定/無樣本就誠實寫缺失，不編數字。
    ai_cost = os.environ.get("AI_COST_MONTHLY_TWD")
    fwd_closed = [e for e in es if e["status"] == "closed" and e.get("kind") != "backfill_biased"]
    print()
    if not ai_cost:
        print("💰 北極星對照：未設定 AI_COST_MONTHLY_TWD（.env），略過成本對照。")
    elif not fwd_closed:
        print("💰 北極星對照：AI 月成本 NT$%s ｜尚無已結算的前進紀錄，等首筆前進結算後開始對照（回填筆含偏誤不採計）。"
              % format(int(float(ai_cost)), ","))
    else:
        mx = float(np.mean([e["excess_pct"] for e in fwd_closed]))
        cost = float(ai_cost)
        if mx > 0:
            need = cost / (mx / 100.0)
            print("💰 北極星對照：AI 月成本 NT$%s ｜前進平均超額 %+.2f%%/月 → 需投入本金約 NT$%s 才覆蓋成本"
                  "（樣本僅 %d 筆前進，波動大、僅供方向參考）"
                  % (format(int(cost), ","), mx, format(int(round(need, -3)), ","), len(fwd_closed)))
        else:
            print("💰 北極星對照：AI 月成本 NT$%s ｜前進平均超額 %+.2f%%/月 ≤ 0，目前紙上策略無法覆蓋成本"
                  "（誠實紀錄，%d 筆前進樣本）" % (format(int(cost), ","), mx, len(fwd_closed)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--mark", action="store_true")
    ap.add_argument("--backfill", type=int, default=0)
    ap.add_argument("--tick", action="store_true")
    ap.add_argument("--fresh", action="store_true", help="強制重抓最新股價(月度自動化用)")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    led = load_ledger()
    if a.backfill or a.mark or a.open or a.tick:
        closes, fts, dates = _ctx(fresh=a.fresh)
        if a.backfill:
            led = backfill(led, a.backfill, closes, fts, dates)
        if a.mark or a.tick:
            led = mark(led, closes, fts, dates)
        if a.open or a.tick:
            led = open_entry(led, closes, fts, dates)
    show(led)


if __name__ == "__main__":
    main()
