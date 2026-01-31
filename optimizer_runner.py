import backtrader as bt
import pandas as pd
import os
import sys
import json
from datetime import datetime

# 引用數據模組
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.data_loader import get_data_provider

CONFIG_FILE = "data/stock_config.json"

class OptimizationStrategy(bt.Strategy):
    params = (('fast_period', 20), ('slow_period', 60))
    def __init__(self):
        self.ma_fast = bt.indicators.SimpleMovingAverage(self.datas[0], period=self.params.fast_period)
        self.ma_slow = bt.indicators.SimpleMovingAverage(self.datas[0], period=self.params.slow_period)
        self.crossover = bt.indicators.CrossOver(self.ma_fast, self.ma_slow)

    def next(self):
        price = self.datas[0].close[0]
        if not self.position:
            if self.crossover > 0:
                cash = self.broker.getcash()
                size = int((cash * 0.99) / price)
                if size > 0: self.buy(size=size)
        elif self.crossover < 0:
            self.close()

# [修正] 更強大的數據獲取
def get_data_hybrid(ticker):
    clean_id = ticker.split('.')[0]
    
    # 1. FinMind (優先，台股不分上市櫃)
    if clean_id.isdigit():
        try:
            provider = get_data_provider("finmind")
            df = provider.get_history(clean_id, days=1095)
            if not df.empty and len(df) > 200: return df
        except: pass
        
    # 2. Yahoo (需區分 TW/TWO)
    # 我們嘗試兩次：先試傳進來的 (可能是 .TWO)，失敗再試 .TW
    candidates = [ticker]
    if clean_id.isdigit():
        candidates = [f"{clean_id}.TWO", f"{clean_id}.TW"] # 優先試上櫃，再試上市
    
    provider = get_data_provider("yfinance")
    for cand in candidates:
        try:
            df = provider.get_history(cand, days=1095)
            if not df.empty and len(df) > 200: return df
        except: continue
            
    return pd.DataFrame()

def find_best_params(ticker):
    # print(f"🚀 Optimizing {ticker}...")
    df = get_data_hybrid(ticker)
    if df.empty: return None

    param_combinations = [
        (5, 10), (5, 20), (10, 20), (10, 60), 
        (20, 60), (20, 120), (60, 200)
    ]
    best_roi = -999.0
    best_params = (20, 60)

    for fast, slow in param_combinations:
        if fast >= slow: continue
        cerebro = bt.Cerebro()
        cerebro.addstrategy(OptimizationStrategy, fast_period=fast, slow_period=slow)
        data = bt.feeds.PandasData(dataname=df)
        cerebro.adddata(data)
        cerebro.broker.setcash(100000.0)
        cerebro.broker.setcommission(commission=0.001425)
        cerebro.run()
        
        final_value = cerebro.broker.getvalue()
        roi = (final_value - 100000.0) / 100000.0 * 100
        if roi > best_roi:
            best_roi = roi
            best_params = (fast, slow)

    return {
        "fast_ma": best_params[0],
        "slow_ma": best_params[1],
        "historical_roi": round(best_roi, 2),
        "last_updated": datetime.now().isoformat()
    }
    
# main 保持原樣，略
