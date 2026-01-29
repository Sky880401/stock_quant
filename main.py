import json
import os
from datetime import datetime
from data.data_loader import get_data_provider
from strategies.ma_crossover import MACrossoverStrategy
from strategies.valuation_strategy import ValuationStrategy

# 配置
TARGET_STOCKS = ["2330.TW", "2888.TW", "2317.TW"]
DATA_SOURCE = "yfinance"  # 未來只需改成 "finmind"
OUTPUT_FILE = "data/latest_report.json"

def main():
    print(f"=== Starting Quant Engine (Source: {DATA_SOURCE}) ===")
    
    # 1. 初始化 Data Provider (Adapter Pattern)
    provider = get_data_provider(DATA_SOURCE)
    
    # 2. 初始化策略
    strategies = {
        "Technical_MA": MACrossoverStrategy(),
        "Fundamental_Valuation": ValuationStrategy()
    }
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "data_source": DATA_SOURCE,
        "analysis": {}
    }

    # 3. 執行迴圈
    for stock_id in TARGET_STOCKS:
        print(f"\nProcessing {stock_id}...")
        
        # 獲取數據
        df = provider.get_history(stock_id)
        fundamentals = provider.get_fundamentals(stock_id)
        
        stock_result = {
            "price_data": {
                "latest_close": df['Close'].iloc[-1] if not df.empty else None
            },
            "strategies": {}
        }

        # 執行所有策略
        for name, strat in strategies.items():
            try:
                result = strat.analyze(df, extra_data=fundamentals)
                stock_result["strategies"][name] = result
                print(f"   -> {name}: {result['signal']} ({result['reason']})")
            except Exception as e:
                print(f"   -> {name} Failed: {e}")
                stock_result["strategies"][name] = {"error": str(e)}

        report["analysis"][stock_id] = stock_result

    # 4. 輸出 JSON 報告
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4, ensure_ascii=False)
    
    print(f"\n=== Analysis Complete. Report saved to {OUTPUT_FILE} ===")

if __name__ == "__main__":
    main()