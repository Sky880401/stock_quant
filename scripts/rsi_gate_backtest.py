#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
技術面隔離回測 harness — RSI 閘門 + EMA 去抖動改動的前後命中率量化。

只隔離 Reversion(RSI) 技術子訊號，比較：
  OLD：原始 RSI 觸發 + KD/MACD 小幅加分(confirm_weight=0.08)
  NEW：EMA(span=3) 平滑 RSI 觸發 + KD/MACD 閘門否決(兩者皆反向才否決)

沿用 main.py 既有的多空趨勢過濾(ma200 in_uptrend)與門檻(40/50/82、60/50/18)，
並復用 main.py 的 calculate_rsi_series / calculate_macd_signal。

不修改 main.py。資料抓取復用 data.data_loader.get_data_provider。

執行範例：
    python scripts/rsi_gate_backtest.py
    python scripts/rsi_gate_backtest.py --symbols 2330 2317 0050 --horizon 5 --days 730
    python scripts/rsi_gate_backtest.py --source yfinance
"""
import argparse
import os
import sys

import pandas as pd

# 讓 harness 可從專案根目錄匯入 main / data
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.data_loader import get_data_provider  # noqa: E402
from main import calculate_rsi_series, calculate_macd_signal  # noqa: E402

# 可改的代表性標的清單（大型權值 + 0050 ETF + 波動較大者）
DEFAULT_SYMBOLS = ["2330", "2317", "2454", "0050", "3008", "6669"]

CONFIRM_WEIGHT = 0.08  # OLD 邏輯：KD/MACD 小幅加分
TECH_WEIGHT = 0.3      # 與 main.py 基礎技術面權重一致（方向計算只看正負號）


def calculate_kd_series(df, fastk_period=9, slowk_period=3, slowd_period=3):
    """簡單 stochastic KD（純 pandas，避免 talib 依賴）。回傳 (K, D) 序列。"""
    low_min = df["Low"].rolling(fastk_period).min()
    high_max = df["High"].rolling(fastk_period).max()
    rsv = (df["Close"] - low_min) / (high_max - low_min).replace(0, 1e-9) * 100
    k = rsv.ewm(span=slowk_period, adjust=False).mean()
    d = k.ewm(span=slowd_period, adjust=False).mean()
    return k, d


def macd_dir_at(df_slice):
    """沿用 main.calculate_macd_signal，回傳方向 1/-1/0。"""
    status, _ = calculate_macd_signal(df_slice)
    if "BUY" in status:
        return 1
    if "SELL" in status:
        return -1
    return 0


def kd_dir_at(k, d, i):
    """KD 金叉/死叉方向（與 hybrid_predictor 同精神：金叉且未超買=BUY）。"""
    if i < 1:
        return 0
    ck, cd = k.iloc[i], d.iloc[i]
    pk, pd_ = k.iloc[i - 1], d.iloc[i - 1]
    if pd.isna(ck) or pd.isna(cd) or pd.isna(pk) or pd.isna(pd_):
        return 0
    if pk <= pd_ and ck > cd and ck < 50:
        return 1
    if pk >= pd_ and ck < cd and ck > 50:
        return -1
    return 0


def reversion_delta(rsi_eff, in_uptrend):
    """沿用 main.py 的 Reversion(RSI) 計分規則，回傳技術分增量（正=偏多、負=偏空）。"""
    w = TECH_WEIGHT
    if in_uptrend:
        if rsi_eff <= 40:
            return w
        if rsi_eff <= 50:
            return w * 0.3
        if rsi_eff >= 82:
            return -w * 0.3
    else:
        if rsi_eff >= 60:
            return -w
        if rsi_eff >= 50:
            return -w * 0.3
        if rsi_eff <= 18:
            return w * 0.3
    return 0.0


def signal_to_dir(score):
    if score > 1e-9:
        return "BUY"
    if score < -1e-9:
        return "SELL"
    return "HOLD"


def run_symbol(df, horizon):
    """逐根 K 棒計算 OLD / NEW 兩種變體的 Reversion(RSI) 子訊號與命中。"""
    closes = df["Close"]
    ma200 = closes.rolling(200).mean()
    rsi_series = calculate_rsi_series(df)
    rsi_smooth = rsi_series.ewm(span=3, adjust=False).mean() if rsi_series is not None else None
    k_series, d_series = calculate_kd_series(df)

    stats = {
        v: {"signals": 0, "hits": 0, "ret_sum": 0.0}
        for v in ("OLD", "NEW")
    }
    n = len(df)
    for i in range(200, n - horizon):
        if pd.isna(ma200.iloc[i]) or rsi_series is None or pd.isna(rsi_series.iloc[i]):
            continue
        in_uptrend = closes.iloc[i] > ma200.iloc[i]
        df_slice = df.iloc[: i + 1]  # 只用到當下為止的歷史

        macd_dir = macd_dir_at(df_slice)
        kd_dir = kd_dir_at(k_series, d_series, i)

        entry = closes.iloc[i]
        fwd = closes.iloc[i + horizon]
        ret_pct = (fwd - entry) / entry * 100.0

        # --- OLD：原始 RSI + KD/MACD 小幅加分 ---
        old_delta = reversion_delta(rsi_series.iloc[i], in_uptrend)
        if abs(old_delta) > 1e-9:  # 只在 RSI 進入可操作區才視為子訊號
            old_score = old_delta + macd_dir * CONFIRM_WEIGHT + kd_dir * CONFIRM_WEIGHT
            old_dir = signal_to_dir(old_score)
            _record(stats["OLD"], old_dir, ret_pct)

        # --- NEW：EMA 平滑 RSI + KD/MACD 閘門否決 ---
        if rsi_smooth is not None and not pd.isna(rsi_smooth.iloc[i]):
            new_delta = reversion_delta(rsi_smooth.iloc[i], in_uptrend)
            if abs(new_delta) > 1e-9:
                rsi_dir = 1 if new_delta > 0 else -1
                both_oppose = (macd_dir == -rsi_dir) and (kd_dir == -rsi_dir)
                new_dir = "HOLD" if both_oppose else signal_to_dir(new_delta)
                _record(stats["NEW"], new_dir, ret_pct)

    return stats


def _record(bucket, direction, ret_pct):
    if direction == "HOLD":
        return
    bucket["signals"] += 1
    hit = (direction == "BUY" and ret_pct > 0) or (direction == "SELL" and ret_pct < 0)
    if hit:
        bucket["hits"] += 1
    # SELL 命中報酬以「下跌幅度為正」累計，方向化報酬
    bucket["ret_sum"] += ret_pct if direction == "BUY" else -ret_pct


def fmt_row(label, old, new):
    def cell(b):
        s = b["signals"]
        wr = (b["hits"] / s * 100.0) if s else 0.0
        ar = (b["ret_sum"] / s) if s else 0.0
        return f"{s:>4} {wr:>5.1f}% {ar:>+6.2f}%"
    return f"{label:<8} | OLD {cell(old)} | NEW {cell(new)}"


def main():
    ap = argparse.ArgumentParser(description="RSI 閘門前後命中率隔離回測 harness")
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="標的清單")
    ap.add_argument("--horizon", type=int, default=5, help="forward N 根 K 棒判定命中")
    ap.add_argument("--days", type=int, default=730, help="抓取歷史天數")
    ap.add_argument("--source", default="finmind", help="資料源: finmind / yfinance")
    args = ap.parse_args()

    provider = get_data_provider(args.source)
    total = {v: {"signals": 0, "hits": 0, "ret_sum": 0.0} for v in ("OLD", "NEW")}
    rows = []
    fetched = 0

    print(f"== RSI 閘門隔離回測 (horizon={args.horizon}, source={args.source}) ==")
    print(f"格式: 標的 | OLD 訊號數 命中率 平均報酬 | NEW 訊號數 命中率 平均報酬\n")

    for sym in args.symbols:
        try:
            df = provider.get_history(sym, days=args.days)
        except Exception as e:
            print(f"{sym}: 抓取失敗 ({e})")
            continue
        if df is None or df.empty or len(df) < 210:
            print(f"{sym}: 資料不足或不可用 (len={0 if df is None else len(df)})")
            continue
        fetched += 1
        st = run_symbol(df, args.horizon)
        rows.append(fmt_row(sym, st["OLD"], st["NEW"]))
        for v in ("OLD", "NEW"):
            for k in ("signals", "hits", "ret_sum"):
                total[v][k] += st[v][k]

    for r in rows:
        print(r)

    if fetched == 0:
        print("\n[資料源不可用] 無法取得任何歷史資料，harness 已可執行，請於有網路/Token 環境重跑。")
        return

    print("-" * 70)
    print(fmt_row("TOTAL", total["OLD"], total["NEW"]))


if __name__ == "__main__":
    main()
