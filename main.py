import json
import os
from datetime import datetime, timedelta
from data.data_loader import DataLoader 
# 👇 修改這裡：從 my_strategies 匯入
from my_strategies.ma_crossover import MACrossoverStrategy
from my_strategies.valuation_strategy import ValuationStrategy

# 設定要分析的股票
TICKERS = ["2330.TW"] 

def main():
    print("🚀 啟動量化分析主程序...")
    
    # 初始化 FinMind 數據載入器
    loader = DataLoader()

    # 初始化策略
    strategies = [
        MACrossoverStrategy(short_window=5, long_window=20),
        ValuationStrategy(threshold=0.8) 
    ]

    final_report = []

    for ticker in TICKERS:
        print(f"\n🔍 分析標的: {ticker}")
        
        # 設定日期範圍 (過去一年)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        
        # 下載數據
        df = loader.fetch_data(
            ticker=ticker, 
            start_date=start_date.strftime("%Y-%m-%d"), 
            end_date=end_date.strftime("%Y-%m-%d")
        )

        if df.empty:
            print(f"⚠️ 無法取得 {ticker} 數據，跳過分析。")
            continue

        # 執行策略分析
        ticker_result = {
            "symbol": ticker,
            "timestamp": datetime.now().isoformat(),
            "strategies": {}
        }

        # 整合訊號
        bullish_votes = 0
        bearish_votes = 0

        for strategy in strategies:
            result = strategy.analyze(df)
            strategy_name = strategy.__class__.__name__
            ticker_result["strategies"][strategy_name] = result
            
            print(f"   👉 {strategy_name}: {result['signal']} (信心: {result.get('confidence', 'N/A')})")

            if result['signal'] == 'BUY':
                bullish_votes += 1
            elif result['signal'] == 'SELL':
                bearish_votes += 1

        # 產生綜合結論
        if bullish_votes > bearish_votes:
            final_signal = "BUY"
        elif bearish_votes > bullish_votes:
            final_signal = "SELL"
        else:
            final_signal = "HOLD"

        ticker_result["final_signal"] = final_signal
        
        # 補充最新價格資訊
        latest_data = df.iloc[-1]
        ticker_result["market_data"] = {
            "close": float(latest_data["Close"]),
            "volume": int(latest_data["Volume"]),
            "foreign_buy": int(latest_data.get("Institutional_Foreign", 0))
        }
        
        final_report.append(ticker_result)

    # 輸出結果
    output_path = "data/latest_report.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_report, f, indent=4, ensure_ascii=False)
        
    print(f"\n✅ 分析完成！結果已儲存至 {output_path}")

if __name__ == "__main__":
    main()