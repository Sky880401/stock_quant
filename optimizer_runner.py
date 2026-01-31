import backtrader as bt
import pandas as pd
import os
import sys
import json
from datetime import datetime
import logging

logging.getLogger('yfinance').setLevel(logging.CRITICAL)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.data_loader import get_data_provider

CONFIG_FILE = "data/stock_config.json"

# === 策略 1: 趨勢跟隨 (Trend Following) ===
class TrendStrategy(bt.Strategy):
    params = (('fast_period', 20), ('slow_period', 60))
    def __init__(self):
        self.ma_fast = bt.indicators.SimpleMovingAverage(self.datas[0], period=self.params.fast_period)
        self.ma_slow = bt.indicators.SimpleMovingAverage(self.datas[0], period=self.params.slow_period)
        self.crossover = bt.indicators.CrossOver(self.ma_fast, self.ma_slow)
    def next(self):
        if not self.position:
            if self.crossover > 0: self.buy()
        elif self.crossover < 0: self.close()

# === 策略 2: 均值回歸 (Mean Reversion - RSI) ===
class RSIStrategy(bt.Strategy):
    params = (('rsi_period', 14), ('low_threshold', 30), ('high_threshold', 70))
    def __init__(self):
        self.rsi = bt.indicators.RSI(self.datas[0], period=self.params.rsi_period)
    def next(self):
        if not self.position:
            # 超賣回補 (逆勢買進)
            if self.rsi < self.params.low_threshold: 
                self.buy()
        else:
            # 超買獲利 (逆勢賣出)
            if self.rsi > self.params.high_threshold:
                self.close()

def get_data_hybrid(ticker):
    # (保持原樣，省略以節省篇幅，請保留原本的 Hybrid 邏輯)
    clean_id = ticker.split('.')[0]
    candidates = [f"{clean_id}.TW", f"{clean_id}.TWO"] if clean_id.isdigit() else [ticker]
    provider = get_data_provider("yfinance")
    for cand in candidates:
        try:
            df = provider.get_history(cand, days=1095)
            if not df.empty and len(df) > 200: return df
        except: continue
    # 最後嘗試 FinMind
    if clean_id.isdigit():
        try:
            return get_data_provider("finmind").get_history(clean_id, days=1095)
        except: pass
    return pd.DataFrame()

def run_backtest(strategy_cls, df, **kwargs):
    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_cls, **kwargs)
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.001425)
    cerebro.run()
    return (cerebro.broker.getvalue() - 100000.0) / 100000.0 * 100

def find_best_params(ticker):
    df = get_data_hybrid(ticker)
    if df.empty or len(df) < 200: return None

    # === Round 1: 測試趨勢策略 ===
    trend_params = [
        (5, 10), (10, 20), (20, 60), (60, 200)
    ]
    best_trend_roi = -999
    best_trend_p = (20, 60)
    
    for f, s in trend_params:
        roi = run_backtest(TrendStrategy, df, fast_period=f, slow_period=s)
        if roi > best_trend_roi:
            best_trend_roi = roi
            best_trend_p = (f, s)

    # === Round 2: 測試 RSI 策略 ===
    rsi_params = [
        (30, 70), (20, 80), (40, 60) # (低點買, 高點賣)
    ]
    best_rsi_roi = -999
    best_rsi_p = (30, 70)
    
    for l, h in rsi_params:
        roi = run_backtest(RSIStrategy, df, rsi_period=14, low_threshold=l, high_threshold=h)
        if roi > best_rsi_roi:
            best_rsi_roi = roi
            best_rsi_p = (l, h)

    # === Final: 策略錦標賽決賽 ===
    # 誰的 ROI 高，誰就贏
    if best_trend_roi >= best_rsi_roi:
        winner = "Trend (MA)"
        final_roi = best_trend_roi
        params = {"fast_ma": best_trend_p[0], "slow_ma": best_trend_p[1]}
    else:
        winner = "Reversion (RSI)"
        final_roi = best_rsi_roi
        params = {"rsi_low": best_rsi_p[0], "rsi_high": best_rsi_p[1]}

    print(f"🏆 {ticker} Winner: {winner} (ROI: {final_roi:.2f}%) vs Loser: {min(best_trend_roi, best_rsi_roi):.2f}%")

    return {
        "strategy_type": winner, # 記錄是誰贏了
        "params": params,
        "historical_roi": round(final_roi, 2),
        "last_updated": datetime.now().isoformat()
    }
