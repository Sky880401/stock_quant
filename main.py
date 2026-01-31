import json
import os
from datetime import datetime
from data.data_loader import get_data_provider
# 引入新策略
from strategies.comprehensive_strategy import ComprehensiveStrategy 

# === Configuration ===
# 您可以隨意增加更多台股或美股
TARGET_STOCKS = [
    "3019.TW",  # 台股
    #"SPAX.PVT" # 美股 (大型股)
]
DATA_SOURCE = "yfinance"
OUTPUT_FILE = "data/latest_report.json"

def main():
    print(f"🚀 Starting Comprehensive Analysis...")
    provider = get_data_provider(DATA_SOURCE)
    
    # 使用單一全方位策略
    strategy = ComprehensiveStrategy()
    
    final_report = {
        "timestamp": datetime.now().strftime("%Y-%m-%d"),
        "analysis": {}
    }

    for stock_id in TARGET_STOCKS:
        print(f"Analyzing {stock_id}...")
        df = provider.get_history(stock_id, period="2y") # 拿2年資料確保算得出 52週與 200MA
        info = provider.get_fundamentals(stock_id)
        
        # 執行策略
        result = strategy.analyze(df, extra_data=info)
        
        # 存入結果
        final_report["analysis"][stock_id] = result

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_report, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Report saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()