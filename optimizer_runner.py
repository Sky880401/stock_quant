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
from strategies.indicators.kd_strategy import KDBacktestStrategy

CONFIG_FILE = "data/stock_config.json"

# === 策略類別 (Trend, RSI, MACD 保持原樣) ===
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
    # (保持原樣)
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
    if df.empty or len(df) < 100: return -999.0, 0.0, 0
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
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    
    try:
        results = cerebro.run()
        strat = results[0]
        roi = (cerebro.broker.getvalue() - 100000.0) / 100000.0 * 100
        
        trade_analysis = strat.analyzers.trades.get_analysis()
        total_trades = trade_analysis.get('total', {}).get('total', 0)
        won_trades = trade_analysis.get('won', {}).get('total', 0)
        
        win_rate = (won_trades / total_trades * 100) if total_trades > 0 else 0.0
        
        return roi, win_rate, total_trades
    except: return -999.0, 0.0, 0

def find_best_params(ticker):
    df = get_data_hybrid(ticker)
    if df.empty or len(df) < 200: return None

    results = []

    def test_strat(name, cls, params_list, fixed_params={}):
        best_roi = -999; best_wr = 0; best_trades = 0; best_p = None
        for p in params_list:
            run_params = {**p, **fixed_params}
            roi, wr, trades = run_backtest(cls, df, **run_params)
            
            # [邏輯優化] 優先選 ROI 高的，但如果 ROI 差不多，選勝率高的
            if roi > best_roi:
                best_roi = roi; best_wr = wr; best_trades = trades; best_p = p
        
        return {"type": name, "roi": best_roi, "win_rate": best_wr, "trades": best_trades, "params": best_p}

    # Round 1: Trend
    results.append(test_strat("Trend (MA)", TrendStrategy, [{'fast_period': f, 'slow_period': s} for f, s in [(5,10), (10,20), (20,60), (60,200)]]))
    # Round 2: Reversion
    results.append(test_strat("Reversion (RSI)", RSIStrategy, [{'low_threshold': l, 'high_threshold': h} for l, h in [(30,70), (20,80), (40,60)]], {'rsi_period': 14}))
    # Round 3: Momentum
    results.append(test_strat("Momentum (MACD)", MACDStrategy, [{'fast_period': f, 'slow_period': s, 'signal_period': sig} for f, s, sig in [(12,26,9), (5,35,5)]]))
    # Round 4: Swing
    results.append(test_strat("Swing (KD)", KDBacktestStrategy, [{'period': 9, 'period_dfast': 3, 'period_dslow': 3}]))

    # [關鍵優化] 錦標賽評分標準
    for res in results:
        # 如果交易次數 < 3，大幅扣分 (懲罰不交易的策略)
        penalty = -50 if res['trades'] < 3 else 0
        res['score'] = res['roi'] * 0.7 + res['win_rate'] * 0.3 + penalty
    
    winner = max(results, key=lambda x: x['score'])
    
    # 格式化勝率顯示
    win_rate_display = f"{winner['win_rate']:.1f}%" if winner['trades'] > 0 else "N/A (No Trades)"
    
    print(f"🏆 {ticker} Winner: {winner['type']} (ROI: {winner['roi']:.2f}%, Win: {win_rate_display})")

    return {
        "strategy_type": winner['type'],
        "params": winner['params'],
        "historical_roi": round(winner['roi'], 2),
        "win_rate": winner['win_rate'] if winner['trades'] > 0 else 0, # 數字
        "win_rate_display": win_rate_display, # 字串
        "last_updated": datetime.now().isoformat()
    }
