import backtrader as bt

class PullbackStrategy(bt.Strategy):
    """
    V10.0 價格行為策略：趨勢回調 (Pullback)
    靈感來源：漢唐/銘旺科 PDF 操作紀錄 (回後上漲)
    """
    params = (
        ('trend_ma_period', 60),  # 季線看趨勢
        ('entry_ma_period', 20),  # 月線找買點
        ('stop_loss_pct', 0.05),  # 5% 停損
        ('take_profit_pct', 0.10) # 10% 停利
    )

    def __init__(self):
        self.trend_ma = bt.indicators.SMA(self.data.close, period=self.params.trend_ma_period)
        self.entry_ma = bt.indicators.SMA(self.data.close, period=self.params.entry_ma_period)
        self.order = None

    def next(self):
        if self.order: return 

        if not self.position:
            # 1. 趨勢向上 (收盤 > 季線 且 季線向上)
            is_trend_up = (self.data.close[0] > self.trend_ma[0]) and (self.trend_ma[0] > self.trend_ma[-5])
            
            if is_trend_up:
                # 2. 回調月線 (距離 < 3%)
                dist_to_ma20 = abs(self.data.close[0] - self.entry_ma[0]) / self.entry_ma[0]
                is_pullback = dist_to_ma20 < 0.03
                
                # 3. 紅K確認
                is_bullish_candle = self.data.close[0] > self.data.open[0]

                if is_pullback and is_bullish_candle:
                    price = self.data.close[0]
                    stop_price = price * (1.0 - self.params.stop_loss_pct)
                    limit_price = price * (1.0 + self.params.take_profit_pct)
                    self.buy_bracket(limitprice=limit_price, stopprice=stop_price)
        else:
            # 跌破季線強制出場 (最後防線)
            if self.data.close[0] < self.trend_ma[0]:
                self.close()
