import sys
import os
import json
from datetime import datetime

# 強制路徑優先權
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.data_loader import get_data_provider
from strategies.ma_crossover import MACrossoverStrategy
from strategies.valuation_strategy import ValuationStrategy

# 配置
TARGET_STOCKS = ["2330.TW", "2888.TW", "2317.TW"]
PRIMARY_SOURCE = "finmind"
FALLBACK_SOURCE = "yfinance"

OUTPUT_FILE = "data/latest_report.json"
OUTPUT_MISSION = "data/moltbot_mission.txt"

def fetch_stock_data(stock_id: str):
    """智慧型數據路由"""
    # 針對 FinMind 移除 .TW 後綴 (如果有的話)
    finmind_id = stock_id.replace(".TW", "")
    
    # 針對 YFinance 確保有 .TW 後綴
    yf_id = stock_id if stock_id.endswith(".TW") else f"{stock_id}.TW"

    providers = [
        (PRIMARY_SOURCE, get_data_provider(PRIMARY_SOURCE), finmind_id),
        (FALLBACK_SOURCE, get_data_provider(FALLBACK_SOURCE), yf_id)
    ]
    
    for source_name, provider, clean_id in providers:
        try:
            df = provider.get_history(clean_id)
            if not df.empty:
                fundamentals = provider.get_fundamentals(clean_id)
                return source_name, df, fundamentals
            else:
                print(f"   ⚠️ {source_name} returned no data for {clean_id}. Switching...")
        except Exception as e:
            print(f"   ⚠️ {source_name} Error: {e}")
            
    return None, None, None

def generate_moltbot_prompt(report):
    timestamp = report.get("timestamp")
    analysis = report.get("analysis", {})
    
    # === [PROMPT ENGINEERING v2.2 - Traditional Chinese] ===
    prompt = f"""
【NVIDIA 405B 機構級量化決策報告】
時間: {timestamp}
角色: 華爾街出身的台股資深操盤手 (風格：風險趨避、邏輯嚴謹、用詞犀利)
語言要求: **繁體中文 (Traditional Chinese)**

--- 1. 估值模型架構 (Valuation Framework) ---
- **2330 台積電**: 採用「高成長模型 (High Growth)」。允許較高 PE/PB，但若訊號為 SELL 則代表極度泡沫。
- **2888 國泰金**: 採用「金融股模型」，僅看 PB (股價淨值比)。若數據缺失，請建議「暫時觀望」。
- **2317 鴻海**: 採用「製造業模型」，關注毛利保護。

--- 2. 衝突決策矩陣 (Conflict Matrix) ---
當「技術面 (Tech)」與「基本面 (Fund)」訊號衝突時，請嚴格執行以下紀律：

| 技術面 | 基本面 | 最終決策 | 操盤邏輯 |
| :--- | :--- | :--- | :--- |
| BUY | SELL | **獲利了結 (PROFIT TAKING)** | 籌碼過熱，價值面跟不上。建議分批出場，不做空。 |
| SELL | BUY | **低接/觀察 (ACCUMULATE)** | 價值浮現但趨勢向下（可能是錯殺）。建議分批佈局。 |
| SELL | SELL | **強力賣出 (STRONG SELL)** | 趨勢與價值雙殺。 |
| BUY | BUY | **強力買進 (STRONG BUY)** | 戴維斯雙擊 (Davis Double Play)。 |

--- 3. 報告撰寫要求 ---
請根據下方數據，撰寫一份給基金經理人的晨報。
* **標題**: 請包含日期與「NVIDIA 405B 決策日報」。
* **個股分析**: 每一檔股票都要有「訊號解讀」與「操作建議」。
* **語氣**: 不要像機器人，要像一個有經驗的分析師。例如：「雖然技術面轉強，但考慮到估值過高，我們認為這只是死貓跳...」

--- [輸入數據流 Input Data] ---
{json.dumps(analysis, indent=2, ensure_ascii=False)}
"""
    return prompt

def main():
    print(f"=== Starting Quant Engine v2.2 (Primary: {PRIMARY_SOURCE}) ===")
    
    strategies = {
        "Technical_MA": MACrossoverStrategy(),
        "Fundamental_Valuation": ValuationStrategy()
    }
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "analysis": {}
    }

    for stock_id in TARGET_STOCKS:
        print(f"\nProcessing {stock_id}...")
        source_used, df, fundamentals = fetch_stock_data(stock_id)
        
        if df is None or df.empty:
            print(f"❌ All sources failed for {stock_id}")
            report["analysis"][stock_id] = {"error": "No data"}
            continue
        
        print(f"   ✅ Data acquired from: {source_used}")
        
        # 注入 Ticker
        if fundamentals:
            fundamentals["ticker"] = stock_id
        else:
            fundamentals = {"ticker": stock_id}

        stock_result = {
            "meta": {"source": source_used},
            "price_data": {
                "latest_close": float(df['Close'].iloc[-1]),
                "volume": int(df['Volume'].iloc[-1])
            },
            "strategies": {}
        }

        for name, strat in strategies.items():
            try:
                # 執行策略
                result_obj = strat.analyze(df, extra_data=fundamentals)
                
                # 序列化
                if hasattr(result_obj, 'to_dict'):
                    result = result_obj.to_dict()
                else:
                    result = result_obj 

                stock_result["strategies"][name] = result
                print(f"   -> {name}: {result.get('signal')} ({result.get('reason')})")
                
            except Exception as e:
                print(f"   -> {name} Failed: {e}")
                stock_result["strategies"][name] = {"error": str(e)}

        report["analysis"][stock_id] = stock_result

    # 輸出
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4, ensure_ascii=False)
    
    # 生成 Mission Prompt
    mission_text = generate_moltbot_prompt(report)
    with open(OUTPUT_MISSION, "w", encoding="utf-8") as f:
        f.write(mission_text)

    print(f"\n=== Report Generated: {OUTPUT_FILE} ===")
    print(f"=== AI Mission Ready: {OUTPUT_MISSION} ===")

if __name__ == "__main__":
    main()
