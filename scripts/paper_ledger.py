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


DEFAULT_VERIFICATION_CAPITAL = 100000.0


def classify_entries(es):
    """分線：回填已結算 / 前進已結算 / 前進開倉中。
    回填筆(kind==backfill_biased)含存活偏誤，永不採計為 edge。
    前進筆(kind != backfill_biased，含舊資料 kind 為 None 者)才是乾淨前進紀錄。"""
    bf_closed, fwd_closed, fwd_open = [], [], []
    for e in es:
        is_bf = e.get("kind") == "backfill_biased"
        if e["status"] == "closed":
            (bf_closed if is_bf else fwd_closed).append(e)
        elif e["status"] == "open" and not is_bf:
            fwd_open.append(e)
    return bf_closed, fwd_closed, fwd_open


def group_stats(group):
    """一組已結算紀錄的摘要。空組回 None。
    回 dict：n、beat_pct(贏大盤比例%)、mean_excess(平均超額%)、equity_mult(累積組合淨值x)。"""
    if not group:
        return None
    ex = [e["excess_pct"] for e in group]
    beat = float(np.mean([1.0 if x > 0 else 0.0 for x in ex])) * 100
    eq = float(np.prod([1 + e["exit_value_return_pct"] / 100 for e in group]))
    return {"n": len(group), "beat_pct": beat,
            "mean_excess": float(np.mean(ex)), "equity_mult": eq}


def polaris_assessment(fwd_closed, ai_cost_raw, capital=DEFAULT_VERIFICATION_CAPITAL):
    """北極星成本覆蓋率評估——只採前進已結算樣本，回填筆一律不採計。
    回 dict，status ∈：
      "no_cost"        未設定 AI_COST_MONTHLY_TWD → 無法驗證成本覆蓋
      "no_fwd_closed"  有成本但前進 closed=0 → 覆蓋率不可計算
      "computed"       有前進 closed → 含 mean_excess/monthly_excess_twd/coverage_pct
    成本覆蓋率% = 估算月超額金額 / AI 月成本 × 100。"""
    if not ai_cost_raw:
        return {"status": "no_cost"}
    cost = float(ai_cost_raw)
    if not fwd_closed:
        return {"status": "no_fwd_closed", "ai_cost": cost}
    mean_excess = float(np.mean([e["excess_pct"] for e in fwd_closed]))
    monthly_excess_twd = capital * (mean_excess / 100.0)
    coverage_pct = (monthly_excess_twd / cost * 100.0) if cost else None
    return {"status": "computed", "ai_cost": cost, "capital": capital,
            "n": len(fwd_closed), "mean_excess": mean_excess,
            "monthly_excess_twd": monthly_excess_twd, "coverage_pct": coverage_pct}


def _verification_capital():
    """假設驗證本金：env STOCK_VERIFICATION_CAPITAL_TWD，預設 100000。"""
    raw = os.environ.get("STOCK_VERIFICATION_CAPITAL_TWD")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return DEFAULT_VERIFICATION_CAPITAL


def _twd(x):
    return format(int(round(x)), ",")


def _print_closed_lines(group):
    for e in group:
        print("   ── 第%d筆 基準日%s 出場%s 組合%+.2f%% 大盤%+.2f%% 超額%+.2f%%"
              % (e["entry_no"], e["as_of_data"], e["exit_date"],
                 e["exit_value_return_pct"], e["benchmark_return_pct"], e["excess_pct"]))


def show(led):
    es = led["entries"]
    bf_closed, fwd_closed, fwd_open = classify_entries(es)
    print("策略：%s ｜基準：%s ｜成本(來回)%.3f%% ｜共 %d 筆"
          % (led["strategy"], led["benchmark"], led.get("cost_round_trip", RT) * 100, len(es)))

    # ── 1) 回填摘要（含存活偏誤，僅供驗算/種子，不能當 edge 證據）
    print("\n🧪 回填摘要（⚠含存活偏誤，僅供驗算/種子，不代表前進 edge）")
    bf = group_stats(bf_closed)
    if bf:
        _print_closed_lines(bf_closed)
        print("   小計 %d 筆：贏大盤 %.0f%%、平均超額 %+.2f%%/月、累積淨值 %.2fx（僅回填，非 edge 證據）"
              % (bf["n"], bf["beat_pct"], bf["mean_excess"], bf["equity_mult"]))
    else:
        print("   （無回填紀錄）")

    # ── 2) 前進已結算摘要（乾淨前進紀錄，唯一可採信的 edge 證據）
    print("\n🔮 前進已結算摘要（乾淨前進紀錄，唯一可採信的 edge 證據）")
    fc = group_stats(fwd_closed)
    if fc:
        _print_closed_lines(fwd_closed)
        print("   小計 %d 筆：贏大盤 %.0f%%、平均超額 %+.2f%%/月、累積淨值 %.2fx"
              % (fc["n"], fc["beat_pct"], fc["mean_excess"], fc["equity_mult"]))
    else:
        print("   尚無前進結算 → edge 未驗證（回填數字不能代替前進結算，不得當 edge 主結論）。")

    # ── 3) 前進開倉中（尚未到期結算）
    print("\n⏳ 前進開倉中（尚未到期結算）")
    if fwd_open:
        for e in fwd_open:
            print("   ── 第%d筆 基準日%s %d檔（到期後 --mark 結算）"
                  % (e["entry_no"], e["as_of_data"], e["n_holdings"]))
    else:
        print("   （無開倉中部位）")

    # ── 北極星成本覆蓋率對照（只採前進已結算樣本；回填筆含偏誤不採計）
    print("\n💰 北極星成本覆蓋率對照（只採前進已結算樣本）")
    pa = polaris_assessment(fwd_closed, os.environ.get("AI_COST_MONTHLY_TWD"),
                            _verification_capital())
    if pa["status"] == "no_cost":
        print("   未設定 AI_COST_MONTHLY_TWD（.env），無法驗證成本覆蓋。")
    elif pa["status"] == "no_fwd_closed":
        print("   AI 月成本 NT$%s ｜尚無前進結算，覆蓋率不可計算（回填筆含偏誤不採計）。"
              % _twd(pa["ai_cost"]))
    else:
        print("   AI 月成本：NT$%s/月" % _twd(pa["ai_cost"]))
        print("   前進平均超額：%+.2f%%/月（%d 筆前進樣本，波動大、僅供方向參考）"
              % (pa["mean_excess"], pa["n"]))
        print("   假設本金：NT$%s（env STOCK_VERIFICATION_CAPITAL_TWD，預設 NT$%s）"
              % (_twd(pa["capital"]), _twd(DEFAULT_VERIFICATION_CAPITAL)))
        print("   估算月超額金額：NT$%s/月" % _twd(pa["monthly_excess_twd"]))
        covered = "已覆蓋 AI 成本" if pa["coverage_pct"] >= 100 else "尚未覆蓋 AI 成本"
        print("   → 成本覆蓋率：%.1f%%（%s）" % (pa["coverage_pct"], covered))


# ──────────────────────────────────────────────────────────────────────────
# #901 驗證第一優先：模擬下單報酬視角（--returns / --show-returns）
#   Sky 指示：成本先不抓，先看『模擬下單到底可得到多少報酬』。
#   分三線：① 已平倉 realized（只採前進 closed；回填可列但明標 biased）
#           ② 開倉中 unrealized MTM（輕量單檔 cache，不重建全市場 panel）
#           ③ 總體目前可量測報酬（前進 closed=0 → 還沒 realized edge；open 只是未實現）
#   缺價誠實列 missing 不可編；快取日期不一致以 price_date_min/max 明示。
# ──────────────────────────────────────────────────────────────────────────
FRAMES_DIR = os.path.join(ROOT, "data", "quant_cache", "frames")
WIDE_FRAMES_DIR = os.path.join(ROOT, "data", "quant_cache", "wide_frames")


def _light_latest_price(sid):
    """單檔最新收盤（輕量路徑，不重建全市場 panel）。先 frames/ 後 wide_frames/。
    回 (price, 'YYYY-MM-DD')；取不到 → (None, None)，由上層誠實列 missing，嚴禁編價。"""
    for base in (FRAMES_DIR, WIDE_FRAMES_DIR):
        f = os.path.join(base, "%s.pkl" % sid)
        if not os.path.exists(f):
            continue
        try:
            df = pd.read_pickle(f)
        except Exception:
            continue
        if "Close" not in getattr(df, "columns", []) or len(df) == 0:
            continue
        s = df["Close"].dropna()
        if len(s) == 0:
            continue
        px = float(s.iloc[-1])
        if px <= 0:
            continue
        return px, str(pd.Timestamp(s.index[-1]).date())
    return None, None


def mtm_open_holdings(entries, price_fn=_light_latest_price):
    """對開倉中 entries 逐檔以最新單檔價算未實現報酬（MTM）。
    回 dict：rets=[{sid,entry_no,entry_price,last_price,price_date,ret_pct}]（有價者）、
            missing=[{sid,entry_no,entry_price}]（取不到價，誠實列出，不編）。"""
    rets, missing = [], []
    for e in entries:
        for h in e.get("holdings", []):
            sid = h["sid"]
            p0 = h.get("entry_price")
            px, pdate = price_fn(sid)
            if px is None or px <= 0 or not p0 or p0 <= 0:
                missing.append({"sid": sid, "entry_no": e.get("entry_no"),
                                "entry_price": p0})
                continue
            rets.append({"sid": sid, "entry_no": e.get("entry_no"), "entry_price": p0,
                         "last_price": px, "price_date": pdate,
                         "ret_pct": (px / p0 - 1) * 100})
    return {"rets": rets, "missing": missing}


def returns_summary(ret_pcts, price_dates=None, rt=RT, cost_already_applied=False):
    """報酬分布統計（輸入為百分比 list）。空組 → count=0、其餘 None（不編造）。
    欄位：count、win_rate、avg_return_pct、median_return_pct、best、worst、
          gross_equal_weight_return_pct、net_if_exit_now_pct、price_date_min/max。
    cost_already_applied=True（已平倉，報酬已含一買一賣成本）：
        gross = mean + 來回成本（還原毛），net_if_exit_now = mean（已是淨報酬）。
    cost_already_applied=False（開倉中 MTM，毛報酬）：
        gross = mean，net_if_exit_now = mean − 來回成本（現在出場的淨報酬）。"""
    if not ret_pcts:
        return {"count": 0, "win_rate": None, "avg_return_pct": None,
                "median_return_pct": None, "best": None, "worst": None,
                "gross_equal_weight_return_pct": None, "net_if_exit_now_pct": None,
                "price_date_min": None, "price_date_max": None}
    arr = np.array(ret_pcts, dtype=float)
    mean = float(arr.mean())
    rt_pct = rt * 100
    if cost_already_applied:
        gross, net_now = mean + rt_pct, mean
    else:
        gross, net_now = mean, mean - rt_pct
    pds = sorted(d for d in (price_dates or []) if d)
    return {"count": int(arr.size),
            "win_rate": float((arr > 0).mean() * 100),
            "avg_return_pct": mean,
            "median_return_pct": float(np.median(arr)),
            "best": float(arr.max()), "worst": float(arr.min()),
            "gross_equal_weight_return_pct": gross,
            "net_if_exit_now_pct": net_now,
            "price_date_min": pds[0] if pds else None,
            "price_date_max": pds[-1] if pds else None}


def realized_summary(fwd_closed):
    """前進已結算報酬摘要（每筆 = 一次等權往返；exit_value_return_pct 已含來回成本）。"""
    rets = [e["exit_value_return_pct"] for e in fwd_closed
            if e.get("exit_value_return_pct") is not None]
    dates = [e.get("exit_date") for e in fwd_closed]
    return returns_summary(rets, dates, cost_already_applied=True)


def open_mtm_summary(fwd_open, price_fn=_light_latest_price):
    """開倉中未實現報酬摘要（逐檔等權）+ missing 清單。"""
    mtm = mtm_open_holdings(fwd_open, price_fn)
    rets = [r["ret_pct"] for r in mtm["rets"]]
    dates = [r["price_date"] for r in mtm["rets"]]
    summ = returns_summary(rets, dates, cost_already_applied=False)
    summ["missing"] = mtm["missing"]
    summ["missing_count"] = len(mtm["missing"])
    summ["detail"] = mtm["rets"]
    return summ


def _print_returns_stats(s, realized):
    print("   count=%d ｜win_rate=%.0f%% ｜avg=%+.2f%% ｜median=%+.2f%% ｜best=%+.2f%% ｜worst=%+.2f%%"
          % (s["count"], s["win_rate"], s["avg_return_pct"], s["median_return_pct"],
             s["best"], s["worst"]))
    if realized:
        print("   gross_equal_weight=%+.2f%%（還原毛）｜net=%+.2f%%（已實現淨，已含來回成本）"
              % (s["gross_equal_weight_return_pct"], s["net_if_exit_now_pct"]))
    else:
        print("   gross_equal_weight=%+.2f%%（未實現毛）｜net_if_exit_now=%+.2f%%（現在出場扣來回成本）"
              % (s["gross_equal_weight_return_pct"], s["net_if_exit_now_pct"]))


def returns_report(led, price_fn=_light_latest_price):
    """#901 模擬下單報酬報表：realized / 開倉MTM / 總體可量測報酬。"""
    es = led["entries"]
    bf_closed, fwd_closed, fwd_open = classify_entries(es)
    rt = led.get("cost_round_trip", RT)

    print("══ 模擬下單報酬（paper orders returns）｜策略 %s ══" % led["strategy"])
    print("   來回成本 %.3f%% ｜共 %d 筆（回填 %d / 前進已結算 %d / 前進開倉中 %d）"
          % (rt * 100, len(es), len(bf_closed), len(fwd_closed), len(fwd_open)))

    rs = realized_summary(fwd_closed)
    ms = open_mtm_summary(fwd_open, price_fn)

    # 主結論前置：誠實話術，避免把未結算當成功
    if rs["count"] == 0:
        print("\n⚠ 主結論前提：目前『前進已結算』= 0 筆 → 還沒有 realized edge（尚無已實現報酬）。")
        print("   下方開倉中 MTM 只是『未實現報酬』，會隨價格波動、尚未落袋，不可當成功。")
        if bf_closed:
            print("   （回填筆含存活偏誤，僅供驗算，永不採計為前進報酬主結論。）")

    # ── ① 已平倉 realized（前進 closed；回填另列、明標 biased）
    print("\n① 已平倉 realized（前進 closed = 唯一可採信報酬證據）")
    if rs["count"]:
        _print_returns_stats(rs, realized=True)
        print("   出場日 price_date_min=%s price_date_max=%s"
              % (rs["price_date_min"], rs["price_date_max"]))
    else:
        print("   尚無前進已結算 → realized 報酬不可計（不得用回填冒充）。")
    bs = returns_summary([e["exit_value_return_pct"] for e in bf_closed],
                         [e.get("exit_date") for e in bf_closed], cost_already_applied=True)
    if bs["count"]:
        print("   ── 回填參考（⚠含存活偏誤，非前進 edge）：%d 筆 avg%+.2f%% median%+.2f%% win%.0f%% best%+.2f%% worst%+.2f%%"
              % (bs["count"], bs["avg_return_pct"], bs["median_return_pct"],
                 bs["win_rate"], bs["best"], bs["worst"]))

    # ── ② 開倉中 unrealized MTM（輕量單檔 cache）
    print("\n② 開倉中 unrealized MTM（未實現；輕量單檔 cache，不重建全市場 panel）")
    if ms["count"] or ms["missing_count"]:
        if ms["count"]:
            _print_returns_stats(ms, realized=False)
            spread = "" if ms["price_date_min"] == ms["price_date_max"] else "（快取跨日，已明示）"
            print("   price_date_min=%s price_date_max=%s%s"
                  % (ms["price_date_min"], ms["price_date_max"], spread))
        if ms["missing_count"]:
            miss = ", ".join("%s(第%s筆)" % (m["sid"], m["entry_no"]) for m in ms["missing"])
            print("   ⚠ 缺價 %d 檔，誠實列 missing（不編價、不納入統計）：%s"
                  % (ms["missing_count"], miss))
    else:
        print("   （無開倉中部位）")

    # ── ③ 總體目前可量測報酬（overall）
    print("\n③ 總體目前可量測報酬（overall）")
    if rs["count"]:
        print("   已實現（前進）：%d 筆，平均淨 %+.2f%%/筆 → 這才是可採信的報酬。"
              % (rs["count"], rs["net_if_exit_now_pct"]))
    else:
        print("   已實現（前進）：0 筆 → 目前可落袋報酬 = 無，edge 尚未驗證。")
    if ms["count"]:
        print("   未實現（開倉 MTM）：%d 檔，毛 %+.2f%% / 現在出場淨 %+.2f%%（僅未實現，非成功）。"
              % (ms["count"], ms["gross_equal_weight_return_pct"], ms["net_if_exit_now_pct"]))
    print("   ⇒ %s" % ("目前無前進結算，唯一可量測者僅未實現 MTM，尚不能宣稱賺到報酬。"
                       if rs["count"] == 0 else
                       "以前進已實現報酬為準；未實現 MTM 僅供追蹤。"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--mark", action="store_true")
    ap.add_argument("--backfill", type=int, default=0)
    ap.add_argument("--tick", action="store_true")
    ap.add_argument("--fresh", action="store_true", help="強制重抓最新股價(月度自動化用)")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--returns", "--show-returns", dest="returns", action="store_true",
                    help="#901 模擬下單報酬視角：realized / 開倉MTM / 總體可量測報酬")
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
    if a.returns:
        returns_report(led)
    else:
        show(led)


if __name__ == "__main__":
    main()
