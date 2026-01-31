import backtrader as bt
import pandas as pd

# === 1. 回測專用策略 (給 optimizer_runner 用) ===
class KDBacktestStrategy(bt.Strategy):
    """
    僅供 Backtrader 回測引擎使用
    """
    params = (('period', 9), ('period_dfast', 3), ('period_dslow', 3), 
              ('upper', 80), ('lower', 20))

    def __init__(self):
        # 這裡會用到 Backtrader 內部機制，必須在 Cerebro 內才能跑
        self.stoch = bt.indicators.Stochastic(
            self.datas[0],
            period=self.params.period,
            period_dfast=self.params.period_dfast,
            period_dslow=self.params.period_dslow
        )
        self.crossover = bt.indicators.CrossOver(self.stoch.percK, self.stoch.percD)

    def next(self):
        k = self.stoch.percK[0]
        if not self.position:
            if self.crossover > 0 and k < self.params.upper:
                self.buy()
        else:
            if self.crossover < 0 or k > self.params.upper:
                self.close()

# === 2. 實時分析器 (給 main.py 用) ===
class KDAnalyzer:
    """
    純 Pandas 計算，不依賴 Backtrader 引擎
    """
    def analyze(self, df: pd.DataFrame, extra_data: dict = None):
        if df.empty or len(df) < 9:
            return {"signal": "UNKNOWN", "k": 50, "d": 50}

        # 手動計算 KD (Pandas 版本)
        high = df['High']
        low = df['Low']
        close = df['Close']
        
        # RSV
        period = 9
        lowest_low = low.rolling(window=period).min()
        highest_high = high.rolling(window=period).max()
        
        # 避免除以零
        denominator = highest_high - lowest_low
        denominator = denominator.replace(0, 1e-9) 
        
        rsv = 100 * ((close - lowest_low) / denominator)
        rsv = rsv.fillna(50)
        
        # 計算 K, D (平滑)
        k_values = []
        d_values = []
        k = 50
        d = 50
        
        for val in rsv:
            k = (2/3) * k + (1/3) * val
            d = (2/3) * d + (1/3) * k
            k_values.append(k)
            d_values.append(d)
            
        curr_k = k_values[-1]
        curr_d = d_values[-1]
        prev_k = k_values[-2]
        prev_d = d_values[-2]
        
        signal = "NEUTRAL"
        reasons = []
        
        # 判斷交叉
        if prev_k < prev_d and curr_k > curr_d:
            signal = "BUY"
            reasons.append(f"KD黃金交叉 (K={curr_k:.1f})")
        elif prev_k > prev_d and curr_k < curr_d:
            signal = "SELL"
            reasons.append(f"KD死亡交叉 (K={curr_k:.1f})")
        else:
            if curr_k > 80: 
                signal = "SELL"
                reasons.append(f"KD過熱 (K={curr_k:.1f})")
            elif curr_k < 20: 
                signal = "BUY"
                reasons.append(f"KD超賣 (K={curr_k:.1f})")
            else:
                status = "多方排列" if curr_k > curr_d else "空方排列"
                reasons.append(f"KD中性 ({status})")

        return {
            "signal": signal,
            "k": round(curr_k, 2),
            "d": round(curr_d, 2),
            "reason": " | ".join(reasons)
        }
