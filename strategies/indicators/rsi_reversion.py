import backtrader as bt

class RSIStrategy(bt.Strategy):
    """
    RSI 均值回歸策略 (Reversion)
    邏輯：
    - RSI < low_threshold (超賣) -> 買進
    - RSI > high_threshold (超買) -> 賣出
    """
    params = (('rsi_period', 14), ('low_threshold', 30), ('high_threshold', 70))

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.datas[0], period=self.params.rsi_period)

    def next(self):
        if not self.position:
            if self.rsi < self.params.low_threshold:
                self.buy()
        else:
            if self.rsi > self.params.high_threshold:
                self.close()
