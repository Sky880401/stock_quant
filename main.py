import json
import os
from datetime import datetime
from data.data_loader import get_data_provider
from strategies.ma_crossover import MACrossoverStrategy
from strategies.valuation_strategy import ValuationStrategy

# === 設定區 ===
TARGET_STOCKS = ["2330.TW", "3141.TWO", "NVDA","CMCSA" ]
DATA_SOURCE = "yfinance"  # 可以在此切換 'finmind'
OUTPUT_FILE = "data/latest_report.json"

def main():
    print(f"🚀 Starting Quant Analysis using source: [{DATA_SOURCE}]...")
    
    # 1. 取得數據驅動器 (Adapter Pattern)
    provider = get_data_provider(DATA_SOURCE)
    
    # 2. 初始化策略
    strategies = {
        "Technical_MA": MACrossoverStrategy(),
        "Fundamental_Valuation": ValuationStrategy()
    }
    
    final_report = {
        "timestamp": datetime.now().isoformat(),
        "source": DATA_SOURCE,
        "analysis": {}
    }

    # 3. 掃描每一檔股票
    for stock_id in TARGET_STOCKS:
        print(f"Analyzing {stock_id}...")
        
        # A. 透過轉接頭獲取數據 (這就是解耦的關鍵！)
        df_history = provider.get_history(stock_id)
        fundamentals = provider.get_fundamentals(stock_id)
        
        stock_result = {
            "current_price": None,
            "strategies": {}
        }

        if not df_history.empty:
            stock_result["current_price"] = float(df_history['Close'].iloc[-1])

        # B. 執行策略
        summary_reasons = []
        for strat_name, strategy in strategies.items():
            result = strategy.analyze(df_history, extra_data=fundamentals)
            stock_result["strategies"][strat_name] = result
            
            if result['signal'] != 'HOLD':
                summary_reasons.append(f"[{strat_name}] {result['signal']}")

        stock_result["Summary"] = "; ".join(summary_reasons) if summary_reasons else "Wait and See"
        final_report["analysis"][stock_id] = stock_result

    # 4. 存檔
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_report, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Analysis complete. Report saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()