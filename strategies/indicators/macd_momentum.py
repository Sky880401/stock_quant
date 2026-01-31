import backtrader as bt

class MACDStrategy(bt.Strategy):
    """
    MACD 動能策略 (Momentum)
    邏輯：
    - 快線突破慢線 (黃金交叉) -> 買進
    - 快線跌破慢線 (死亡交叉) -> 賣出
    """
    params = (('fast_period', 12), ('slow_period', 26), ('signal_period', 9))

    def __init__(self):
        self.macd = bt.indicators.MACD(
            self.datas[0], 
            period_me1=self.params.fast_period, 
            period_me2=self.params.slow_period, 
            period_signal=self.params.signal_period
        )
        self.crossover = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)

    def next(self):
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.close()
