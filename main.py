import json
import os
from datetime import datetime
from data.data_loader import UnifiedDataManager  # 確保這裡不會報錯
from strategies.ma_crossover import MACrossoverStrategy

# 設定
TARGET_STOCKS = ["2330.TW", "2317.TW"]
OUTPUT_FILE = "data/latest_report.json"
FINMIND_TOKEN = "" 

def main():
    print(f"=== Starting Hybrid Quant Engine ===")
    
    # 這裡會初始化剛剛定義的類別
    provider = UnifiedDataManager(finmind_token=FINMIND_TOKEN)
    strategy = MACrossoverStrategy()
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "analysis": {}
    }

    for stock_id in TARGET_STOCKS:
        print(f"\nProcessing {stock_id}...")
        
        # 呼叫 get_data (只需傳入 stock_id 與天數)
        df = provider.get_data(stock_id, days=120)
        
        if df is None or df.empty:
            print(f"   Skipping {stock_id} (No Data)")
            continue

        chips = provider.get_institutional_data(stock_id)

        try:
            result = strategy.analyze(df)
            
            stock_data = {
                "price_data": {
                    "latest_close": float(df['Close'].iloc[-1]),
                    "volume": int(df['Volume'].iloc[-1])
                },
                "institutional_data": chips,
                "strategies": {
                    "Technical_MA": result
                }
            }
            report["analysis"][stock_id] = stock_data
            print(f"   -> Signal: {result['signal']}")
            
        except Exception as e:
            print(f"   -> Error: {e}")

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4, ensure_ascii=False)
    
    print(f"\n=== Report generated: {OUTPUT_FILE} ===")

    # 嘗試生成 AI Prompt
    try:
        from ai_runner import generate_moltbot_prompt
        with open("data/moltbot_mission.txt", "w", encoding="utf-8") as f:
            f.write(generate_moltbot_prompt(report))
        print("✅ AI Mission Prompt updated.")
    except Exception as e:
        print(f"⚠️ Prompt generation skipped: {e}")

if __name__ == "__main__":
    main()