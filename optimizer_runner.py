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
# [修改] 引用新的 Backtest 類別
from strategies.kd_strategy import KDBacktestStrategy

CONFIG_FILE = "data/stock_config.json"

# 其他策略保持原樣
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

class RSIStrategy(bt.Strategy):
    params = (('rsi_period', 14), ('low_threshold', 30), ('high_threshold', 70))
    def __init__(self):
        self.rsi = bt.indicators.RSI(self.datas[0], period=self.params.rsi_period)
    def next(self):
        if not self.position:
            if self.rsi < self.params.low_threshold: self.buy()
        else:
            if self.rsi > self.params.high_threshold: self.close()

class MACDStrategy(bt.Strategy):
    params = (('fast_period', 12), ('slow_period', 26), ('signal_period', 9))
    def __init__(self):
        self.macd = bt.indicators.MACD(self.datas[0], period_me1=self.params.fast_period, period_me2=self.params.slow_period, period_signal=self.params.signal_period)
        self.crossover = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)
    def next(self):
        if not self.position:
            if self.crossover > 0: self.buy()
        elif self.crossover < 0: self.close()

def get_data_hybrid(ticker):
    clean_id = ticker.split('.')[0]
    candidates = [f"{clean_id}.TW", f"{clean_id}.TWO"] if clean_id.isdigit() else [ticker]
    provider = get_data_provider("yfinance")
    for cand in candidates:
        try:
            df = provider.get_history(cand, days=1095)
            if not df.empty and len(df) > 200: return df
        except: continue
    if clean_id.isdigit():
        try: return get_data_provider("finmind").get_history(clean_id, days=1095)
        except: pass
    return pd.DataFrame()

def run_backtest(strategy_cls, df, **kwargs):
    if df.empty or len(df) < 100: return -999.0
    if not isinstance(df.index, pd.DatetimeIndex): df.index = pd.to_datetime(df.index)
    df = df[~df.index.duplicated(keep='first')].sort_index()
    if df.isnull().values.any(): df = df.fillna(method='ffill').fillna(method='bfill')

    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_cls, **kwargs)
    vol_col = 'Volume' if 'Volume' in df.columns else 'volume'
    data = bt.feeds.PandasData(dataname=df, volume=vol_col)
    cerebro.adddata(data)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.001425)
    
    try:
        cerebro.run()
        return (cerebro.broker.getvalue() - 100000.0) / 100000.0 * 100
    except: return -999.0

def find_best_params(ticker):
    df = get_data_hybrid(ticker)
    if df.empty or len(df) < 200: return None

    # Trend (MA)
    best_trend_roi = -999; best_trend_p = (20, 60)
    for f, s in [(5, 10), (10, 20), (20, 60), (60, 200)]:
        roi = run_backtest(TrendStrategy, df, fast_period=f, slow_period=s)
        if roi > best_trend_roi: best_trend_roi = roi; best_trend_p = (f, s)

    # Reversion (RSI)
    best_rsi_roi = -999; best_rsi_p = (30, 70)
    for l, h in [(30, 70), (20, 80), (40, 60)]:
        roi = run_backtest(RSIStrategy, df, rsi_period=14, low_threshold=l, high_threshold=h)
        if roi > best_rsi_roi: best_rsi_roi = roi; best_rsi_p = (l, h)

    # Momentum (MACD)
    best_macd_roi = -999; best_macd_p = (12, 26, 9)
    for f, s, sig in [(12, 26, 9), (5, 35, 5)]:
        roi = run_backtest(MACDStrategy, df, fast_period=f, slow_period=s, signal_period=sig)
        if roi > best_macd_roi: best_macd_roi = roi; best_macd_p = (f, s, sig)

    # Swing (KD) - 使用 KDBacktestStrategy
    best_kd_roi = -999; best_kd_p = (9, 3, 3)
    roi_kd = run_backtest(KDBacktestStrategy, df, period=9, period_dfast=3, period_dslow=3)
    if roi_kd > best_kd_roi: best_kd_roi = roi_kd

    results = [
        {"type": "Trend (MA)", "roi": best_trend_roi, "params": {"fast_ma": best_trend_p[0], "slow_ma": best_trend_p[1]}},
        {"type": "Reversion (RSI)", "roi": best_rsi_roi, "params": {"rsi_low": best_rsi_p[0], "rsi_high": best_rsi_p[1]}},
        {"type": "Momentum (MACD)", "roi": best_macd_roi, "params": {"macd_fast": best_macd_p[0], "macd_slow": best_macd_p[1], "macd_signal": best_macd_p[2]}},
        {"type": "Swing (KD)", "roi": best_kd_roi, "params": {"kd_period": 9}}
    ]
    
    winner = max(results, key=lambda x: x['roi'])
    return {
        "strategy_type": winner['type'],
        "params": winner['params'],
        "historical_roi": round(winner['roi'], 2),
        "last_updated": datetime.now().isoformat()
    }
