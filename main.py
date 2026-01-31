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
# 嘗試優先使用 FinMind，若無則會自動 Fallback
PRIMARY_SOURCE = "finmind"
FALLBACK_SOURCE = "yfinance"

OUTPUT_FILE = "data/latest_report.json"
OUTPUT_MISSION = "data/moltbot_mission.txt"

def fetch_stock_data(stock_id: str):
    """智慧型數據路由"""
    providers = [
        (PRIMARY_SOURCE, get_data_provider(PRIMARY_SOURCE)),
        (FALLBACK_SOURCE, get_data_provider(FALLBACK_SOURCE))
    ]
    for source_name, provider in providers:
        df = provider.get_history(stock_id)
        if not df.empty:
            fundamentals = provider.get_fundamentals(stock_id)
            return source_name, df, fundamentals
        else:
            print(f"   ⚠️ {source_name} returned no data for {stock_id}. Switching...")
    return None, None, None

def generate_moltbot_prompt(report):
    timestamp = report.get("timestamp")
    analysis = report.get("analysis", {})
    
    # === [PROMPT ENGINEERING v2.0] ===
    # 這裡實作了「規則基礎模型 (Rule-Based Model)」的邏輯指導
    prompt = f"""
【NVIDIA 405B Institutional Quant Analysis】
Time: {timestamp}
Role: Senior Portfolio Manager (Risk-Averse)

--- 1. Valuation Framework (產業估值邏輯) ---
請注意，我們已對不同個股採用差異化估值標準：
- **2330 TSMC**: 採用高成長模型 (High Growth Model)，容許較高 PE/PB。若 Signal=SELL，代表已達極端泡沫區。
- **2888 Cathay**: 採用金融模型 (Finance Model)，僅看 PB。若數據缺失，必須標註 "WATCH LIST" 而非強行預測。
- **2317 Foxconn**: 採用製造業模型 (Manufacturing Model)，關注毛利與低估值保護。

--- 2. Conflict Resolution Matrix (訊號衝突處理矩陣) ---
當技術面 (Tech) 與基本面 (Fund) 衝突時，請嚴格遵守以下決策權重：

| Tech Signal | Fund Signal | Final Decision | Logic |
| :--- | :--- | :--- | :--- |
| BUY | SELL | **PROFIT TAKING / NEUTRAL** | 動能過熱，基本面跟不上。建議分批獲利了結，但不做空。 |
| SELL | BUY | **WATCH / ACCUMULATE** | 價值浮現但趨勢向下。可能為「價值陷阱」，建議分批低接或觀察止跌。 |
| SELL | SELL | **STRONG SELL** | 雙重確認，趨勢與價值皆空。 |
| BUY | BUY | **STRONG BUY** | 雙重確認，戴維斯雙擊 (Davis Double Play)。 |
| Any | Missing | **TECHNICAL SPECULATION** | 純技術面操作，部位需減半 (Half Position)。 |

--- 3. Analysis Task ---
根據上述邏輯與下方數據，生成一份 markdown 報告。
對於 2888.TW 若無數據，標題請寫 "2888.TW (Data Insufficient)" 並建議觀望。

--- Input Data Stream ---
{json.dumps(analysis, indent=2, ensure_ascii=False)}
"""
    return prompt

def main():
    print(f"=== Starting Quant Engine (Primary: {PRIMARY_SOURCE}) ===")
    
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
        
        # 注入 Ticker 資訊給策略使用
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
                # 這裡會傳入含 ticker 的 extra_data
                result = strat.analyze(df, extra_data=fundamentals)
                stock_result["strategies"][name] = result
                print(f"   -> {name}: {result['signal']} ({result['reason']})")
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

    print(f"\n=== Report & Mission Generated ===")
    print(f"File: {OUTPUT_MISSION}")

if __name__ == "__main__":
    main()
