import backtrader as bt
import pandas as pd
import datetime
import os
import sys

# 引用我們自己的數據模組
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.data_loader import get_data_provider

# === 1. 定義策略 (Backtrader 專用格式) ===
class BMO_MA_Strategy(bt.Strategy):
    params = (
        ('fast_period', 20),
        ('slow_period', 60),
        ('rsi_period', 14),
    )

    def log(self, txt, dt=None):
        """記錄日誌功能"""
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()}, {txt}')

    def __init__(self):
        # 建立指標
        self.dataclose = self.datas[0].close
        
        # 簡單移動平均線
        self.ma_fast = bt.indicators.SimpleMovingAverage(
            self.datas[0], period=self.params.fast_period)
        self.ma_slow = bt.indicators.SimpleMovingAverage(
            self.datas[0], period=self.params.slow_period)
            
        # RSI 指標
        self.rsi = bt.indicators.RSI(
            self.datas[0], period=self.params.rsi_period)

        self.order = None

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY EXECUTED, Price: {order.executed.price:.2f}, Cost: {order.executed.value:.2f}, Comm: {order.executed.comm:.2f}')
            elif order.issell():
                self.log(f'SELL EXECUTED, Price: {order.executed.price:.2f}, Cost: {order.executed.value:.2f}, Comm: {order.executed.comm:.2f}')
            self.bar_executed = len(self)

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('Order Canceled/Margin/Rejected')

        self.order = None

    def next(self):
        # 簡單策略邏輯：黃金交叉 + RSI < 70 買進
        
        # 檢查是否有未完成訂單
        if self.order:
            return

        # 若目前無持倉
        if not self.position:
            # 黃金交叉 (快線向上突破慢線)
            if self.ma_fast[0] > self.ma_slow[0] and self.ma_fast[-1] <= self.ma_slow[-1]:
                if self.rsi[0] < 70: # 濾網：避免追高
                    self.log(f'BUY CREATE, {self.dataclose[0]:.2f}')
                    # 全倉買進 (計算股數)
                    size = int(self.broker.getcash() / self.dataclose[0])
                    # 避免資金稍微不足導致下單失敗，保留 1% 現金
                    size = int(size * 0.99)
                    if size > 0:
                        self.order = self.buy(size=size)

        # 若持有倉位
        else:
            # 死亡交叉 (快線向下跌破慢線)
            if self.ma_fast[0] < self.ma_slow[0] and self.ma_fast[-1] >= self.ma_slow[-1]:
                self.log(f'SELL CREATE, {self.dataclose[0]:.2f}')
                self.order = self.sell(size=self.position.size)

# === 2. 執行回測 ===
def run_backtest(ticker="2330"):
    print(f"=== Starting Backtest for {ticker} ===")
    
    # 初始化 Cerebro 引擎
    cerebro = bt.Cerebro()
    
    # 加入策略
    cerebro.addstrategy(BMO_MA_Strategy)

    # 獲取數據 (使用我們現有的 DataProvider)
    # 這裡我們取 3 年數據來回測 (約 750 天)
    provider = get_data_provider("yfinance") 
    df = provider.get_history(ticker, days=1000) 
    
    if df.empty:
        print(f"❌ No data found for {ticker} to backtest.")
        return

    # 轉換 DataFrame 為 Backtrader Data Feed
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)

    # 設定初始資金 (10萬)
    cerebro.broker.setcash(100000.0)
    
    # 設定手續費 (台股約 0.1425%)
    cerebro.broker.setcommission(commission=0.001425)

    print(f'Starting Portfolio Value: {cerebro.broker.getvalue():.2f}')
    
    # 執行
    cerebro.run()
    
    final_value = cerebro.broker.getvalue()
    print(f'Final Portfolio Value: {final_value:.2f}')
    
    # 計算報酬率
    roi = (final_value - 100000.0) / 100000.0 * 100
    print(f'Total Return: {roi:.2f}%')

    # 繪圖 (VPS 無圖形介面，故略過 plot)
    # cerebro.plot()

if __name__ == "__main__":
    # 支援命令列參數輸入代號
    target = sys.argv[1] if len(sys.argv) > 1 else "2330"
    run_backtest(target)
