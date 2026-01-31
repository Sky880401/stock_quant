import sys
import os
import json
from datetime import datetime

# 強制路徑優先權
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.data_loader import get_data_provider
from strategies.ma_crossover import MACrossoverStrategy
from strategies.valuation_strategy import ValuationStrategy

# === 全局配置 ===
TARGET_STOCKS = ["2330.TW", "2888.TW", "2317.TW"]
DATA_SOURCE = "yfinance" 
OUTPUT_JSON = "data/latest_report.json"
OUTPUT_MISSION = "data/moltbot_mission.txt"

def generate_moltbot_prompt(report):
    """
    生成針對 NVIDIA Llama 3.1 405B 優化的超長上下文 Prompt
    """
    timestamp = report.get("timestamp", datetime.now().isoformat())
    data_source = report.get("data_source", "Unknown")
    analysis = report.get("analysis", {})

    # === [關鍵更新] 405B 專用 System Prompt ===
    prompt_content = f"""
【NVIDIA NIM 雲端運算任務書】
時間: {timestamp}
資料來源: {data_source}
執行架構: NVIDIA Llama 3.1 405B (Instruct)

--- 角色定義 (System Persona) ---
你現在是 **QuantMaster AI**，一個運行於 NVIDIA H100 集群上的頂級金融決策大腦。
你擁有 **Llama 3.1 405B** 的完整推理能力，能夠處理極度複雜的非線性市場數據。

你的思考模式必須包含：
1. **多維度檢核 (Multi-dimensional Check)**：當技術面與基本面衝突時，不只是回報衝突，而是要推論「為什麼」會有衝突（是主力洗盤？還是基本面滯後？）。
2. **風險厭惡 (Risk Aversion)**：你是機構投資者的代理人，非散戶。首要任務是「本金保護」，其次才是「獲利」。
3. **宏觀視角 (Macro Awareness)**：請假設你是台股的總操盤手，綜合判斷電子（2330, 2317）與金融（2888）的資金輪動關係。

--- 任務目標 (Objective) ---
閱讀下方的 JSON 原始數據，撰寫一份 **"Alpha-Seeking Daily Report" (尋求超額報酬日報)**。
檔名格式：`reports/daily_summary_{datetime.now().strftime('%Y%m%d')}_nvidia.md`

--- 報告輸出格式要求 (Markdown) ---
# 🏛️ NVIDIA 405B Market Insight ({datetime.now().strftime('%Y-%m-%d')})

## 1. Executive Summary (決策摘要)
* **Market Temperature**: (0-100, 基於 405B 的信心指數)
* **Alpha Opportunities**: (列出最有潛力的標的)

## 2. Deep Inference (深度推理)
*(在此區塊，請展示你的思考過程。針對每一個訊號衝突，給出你的機率預測)*
* **2330.TW**: ...
* **2317.TW**: ...

## 3. Institutional Action Plan (機構操作建議)
| Ticker | Action | Entry | Stop Loss | R/R Ratio | Logic |
|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | ... |

--- [原始數據串流 Input Data Stream] ---
{json.dumps(analysis, indent=2, ensure_ascii=False)}
"""
    return prompt_content

def main():
    print(f"=== Starting Quant Engine (Source: {DATA_SOURCE}) ===")
    
    # 1. 初始化 Data Provider
    try:
        provider = get_data_provider(DATA_SOURCE)
    except ImportError as e:
        print(f"[Fatal Error] Data Provider Import Failed: {e}")
        return

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

    # 3. 執行迴圈 (數據獲取 + 策略運算)
    for stock_id in TARGET_STOCKS:
        print(f"\nProcessing {stock_id}...")
        
        # 獲取數據
        df = provider.get_history(stock_id)
        fundamentals = provider.get_fundamentals(stock_id)
        
        stock_result = {
            "price_data": {
                "latest_close": float(df['Close'].iloc[-1]) if not df.empty else None
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
    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4, ensure_ascii=False)
    print(f"\n✅ Data analysis saved to {OUTPUT_JSON}")

    # 5. 生成給 405B 的任務指令書
    mission_text = generate_moltbot_prompt(report)
    with open(OUTPUT_MISSION, "w", encoding="utf-8") as f:
        f.write(mission_text)
    print(f"✅ NVIDIA Mission Context updated: {OUTPUT_MISSION}")
    print("   (Ready for 'ai_runner.py' execution)")

if __name__ == "__main__":
    main()
