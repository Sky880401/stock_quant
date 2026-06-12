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
    if df.empty or len(df) < 100: return -999.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0, 0.0
    if not isinstance(df.index, pd.DatetimeIndex): df.index = pd.to_datetime(df.index)
    df = df[~df.index.duplicated(keep='first')].sort_index()
    if df.isnull().values.any(): df = df.ffill().bfill()

    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_cls, **kwargs)
    vol_col = 'Volume' if 'Volume' in df.columns else 'volume'
    data = bt.feeds.PandasData(dataname=df, volume=vol_col)
    cerebro.adddata(data)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.001425)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")  # [新增]
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")  # [新增]
    
    try:
        results = cerebro.run()
        strat = results[0]
        roi = (cerebro.broker.getvalue() - 100000.0) / 100000.0 * 100
        
        trade_analysis = strat.analyzers.trades.get_analysis()
        total_trades = trade_analysis.get('total', {}).get('total', 0)
        won_trades = trade_analysis.get('won', {}).get('total', 0)
        
        win_rate = (won_trades / total_trades * 100) if total_trades > 0 else 0.0
        
        # [新增] 計算平均贏損比
        avg_win_pnl = 0.0
        avg_loss_pnl = 0.0
        won_pnl = trade_analysis.get('won', {}).get('pnl', {}).get('total', 0)
        lost_pnl = abs(trade_analysis.get('lost', {}).get('pnl', {}).get('total', 0))
        
        if won_trades > 0:
            avg_win_pnl = won_pnl / won_trades
        if (total_trades - won_trades) > 0:
            avg_loss_pnl = lost_pnl / (total_trades - won_trades)
        
        avg_win_ratio = avg_win_pnl / avg_loss_pnl if avg_loss_pnl > 0 else 1.5
        
        # [新增] Sharpe比率 (風險調整後報酬)
        returns_analysis = strat.analyzers.returns.get_analysis()
        rtot = returns_analysis.get('rtot', 0)
        
        # [新增] 最大回撤
        drawdown_analysis = strat.analyzers.drawdown.get_analysis()
        max_dd = abs(drawdown_analysis.get('max', {}).get('drawdown', 0.0))
        
        # Sharpe簡化計算: ROI / max_dd (高過簡化，但快速)
        sharpe_approx = roi / max(max_dd, 0.01) if max_dd > 0 else roi * 10
        
        return roi, win_rate, total_trades, avg_win_ratio, avg_loss_pnl, max_dd, sharpe_approx, rtot
    except: 
        return -999.0, 0.0, 0, 1.5, 1.0, 0.0, 0.0, 0.0

def run_walk_forward_analysis(strategy_cls, df, params, train_ratio=0.8):
    """
    樣本外驗證 (Walk-Forward Analysis)
    - 用前80%訓練，後20%測試
    - 返回 (in_sample_score, out_of_sample_score)
    """
    if len(df) < 100:
        return 0.0, 0.0
    
    split_idx = int(len(df) * train_ratio)
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]
    
    # In-Sample (訓練集)
    roi_is, wr_is, trades_is, _, _, dd_is, sharpe_is, _ = run_backtest(strategy_cls, train_df, **params)
    is_score = roi_is * 0.7 + wr_is * 0.3 - dd_is * 0.1
    
    # Out-of-Sample (測試集)
    roi_os, wr_os, trades_os, _, _, dd_os, sharpe_os, _ = run_backtest(strategy_cls, test_df, **params)
    os_score = roi_os * 0.7 + wr_os * 0.3 - dd_os * 0.1
    
    return is_score, os_score

def find_best_params(ticker):
    df = get_data_hybrid(ticker)
    if df.empty or len(df) < 200: return None

    results = []

    def test_strat(name, cls, params_list, fixed_params={}):
        best_roi = -999; best_wr = 0; best_trades = 0; best_p = None
        best_avg_ratio = 1.5; best_avg_loss = 1.0
        best_os_score = -999
        best_max_dd = 999  # [新增] 最小化最大回撤
        best_sharpe = -999  # [新增] 最大化Sharpe
        
        for p in params_list:
            run_params = {**p, **fixed_params}
            roi, wr, trades, avg_ratio, avg_loss, max_dd, sharpe, rtot = run_backtest(cls, df, **run_params)
            
            # [新增] Walk-Forward驗證
            is_score, os_score = run_walk_forward_analysis(cls, df, run_params, train_ratio=0.8)
            
            # [優化邏輯] 綜合多個指標的評分
            # IS/OS均衡 + 風險調整 + Sharpe比率
            combined_score = (is_score * 0.6 + os_score * 0.4) * (1.0 - max_dd / 50.0)  # 懲罰高回撤
            
            if combined_score > best_roi:
                best_roi = combined_score
                best_wr = wr
                best_trades = trades
                best_p = p
                best_avg_ratio = avg_ratio
                best_avg_loss = avg_loss
                best_os_score = os_score
                best_max_dd = max_dd
                best_sharpe = sharpe
        
        return {
            "type": name,
            "roi": best_roi,
            "win_rate": best_wr,
            "trades": best_trades,
            "params": best_p,
            "avg_win_ratio": best_avg_ratio,
            "avg_loss_pnl": best_avg_loss,
            "out_of_sample_score": best_os_score,
            "max_drawdown": round(best_max_dd, 2),  # [新增]
            "sharpe_ratio": round(best_sharpe, 2)   # [新增]
        }

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
        "win_rate": winner['win_rate'] if winner['trades'] > 0 else 0,
        "win_rate_display": win_rate_display,
        "avg_win_ratio": round(winner['avg_win_ratio'], 2),
        "avg_loss_ratio": 1.0,  # 標準化損失為1.0用於Kelly計算
        "last_updated": datetime.now().isoformat()
    }
