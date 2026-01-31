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

# === 策略類別 ===
class OptimizationStrategy(bt.Strategy):
    params = (
        ('fast_period', 20),
        ('slow_period', 60),
    )

    def __init__(self):
        self.ma_fast = bt.indicators.SimpleMovingAverage(
            self.datas[0], period=self.params.fast_period)
        self.ma_slow = bt.indicators.SimpleMovingAverage(
            self.datas[0], period=self.params.slow_period)
        # 黃金/死亡交叉指標
        self.crossover = bt.indicators.CrossOver(self.ma_fast, self.ma_slow)

    def next(self):
        # 取得當前股價
        price = self.datas[0].close[0]
        
        if not self.position:
            if self.crossover > 0: # 黃金交叉 -> 買進
                # [修正] 計算可用資金能買幾股 (All-in)
                cash = self.broker.getcash()
                size = int(cash / price)
                # 保留一點點現金避免手續費導致下單失敗
                size = int(size * 0.99)
                
                if size > 0:
                    self.buy(size=size)
                    
        elif self.crossover < 0: # 死亡交叉 -> 賣出
            self.close() # 平倉所有部位

# === 數據獲取 (Hybrid 模式) ===
def get_data_hybrid(ticker):
    """
    與 main.py 一致的獲取邏輯：
    先試 FinMind (純數字) -> 失敗試 Yahoo (.TW)
    """
    clean_id = ticker.split('.')[0]
    
    # 1. 嘗試 FinMind (如果是台股)
    if clean_id.isdigit():
        try:
            provider = get_data_provider("finmind")
            df = provider.get_history(clean_id, days=1095)
            if not df.empty and len(df) > 200:
                return df
        except: pass
        
    # 2. 嘗試 Yahoo (Fallback)
    try:
        provider = get_data_provider("yfinance")
        # 確保傳給 Yahoo 的有 .TW
        yf_id = ticker if "TW" in ticker or not clean_id.isdigit() else f"{ticker}.TW"
        df = provider.get_history(yf_id, days=1095)
        if not df.empty and len(df) > 200:
            return df
    except: pass
    
    return pd.DataFrame() # 失敗回傳空

# === 優化核心邏輯 ===
def find_best_params(ticker):
    print(f"\n🚀 Optimizing strategy for {ticker}...")
    
    # 1. 獲取數據
    df = get_data_hybrid(ticker)
    
    if df.empty:
        print(f"❌ Data insufficient for {ticker}")
        return None

    # 2. 定義要測試的參數組合 (快線, 慢線)
    # 這次我們擴充一些更具攻擊性的組合
    param_combinations = [
        (5, 10), (5, 20),           # 短線當沖/隔日沖型
        (10, 20), (10, 60),         # 波段型
        (20, 60), (20, 120),        # 台股生命線型 (季線/半年線)
        (60, 200)                   # 長線投資型
    ]

    best_roi = -999.0
    best_params = (20, 60)

    # 3. 迴圈測試
    for fast, slow in param_combinations:
        if fast >= slow: continue

        cerebro = bt.Cerebro()
        cerebro.addstrategy(OptimizationStrategy, fast_period=fast, slow_period=slow)
        data = bt.feeds.PandasData(dataname=df)
        cerebro.adddata(data)
        cerebro.broker.setcash(100000.0)
        cerebro.broker.setcommission(commission=0.001425) # 台股手續費

        cerebro.run()
        
        final_value = cerebro.broker.getvalue()
        roi = (final_value - 100000.0) / 100000.0 * 100
        
        # print(f"   Testing MA {fast}/{slow}: ROI = {roi:.2f}%") # 減少洗版

        if roi > best_roi:
            best_roi = roi
            best_params = (fast, slow)

    print(f"🏆 Winner for {ticker}: MA {best_params[0]}/{best_params[1]} (ROI: {best_roi:.2f}%)")
    
    return {
        "fast_ma": best_params[0],
        "slow_ma": best_params[1],
        "historical_roi": round(best_roi, 2),
        "last_updated": datetime.now().isoformat()
    }

# === 主程序 ===
def main():
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["2330", "2317", "2888"]
    
    # 讀取現有 Config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
        except: config = {}
    else:
        config = {}

    for t in targets:
        clean_ticker = t.split('.')[0] 
        # 傳入完整代號讓 hybrid 函數處理
        target_input = f"{clean_ticker}.TW" if clean_ticker.isdigit() else t
        
        result = find_best_params(target_input)
        
        if result:
            config[clean_ticker] = result

    # 存檔
    os.makedirs("data", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)
    
    print(f"\n✅ Optimization complete! Config saved to {CONFIG_FILE}")

if __name__ == "__main__":
    main()
