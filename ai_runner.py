import json
import requests
import sys
import os
from datetime import datetime

# === 設定區 ===
REPORT_FILE = "data/latest_report.json"
OLLAMA_API_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3"  # 或 mistral，取決於您安裝的模型

def load_report():
    if not os.path.exists(REPORT_FILE):
        print(f"❌ Report file not found: {REPORT_FILE}")
        return None
    with open(REPORT_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def generate_prompt(data):
    """將量化數據轉換為 AI 的 Prompt (專業華爾街分析師版)"""
    
    # 1. 取得當前日期，增強時效感
    today_date = datetime.now().strftime("%Y年%m月%d日")
    
    # 2. 整理數據摘要
    summary_text = ""
    analysis = data.get("analysis", {})
    
    for stock, info in analysis.items():
        price = info.get("current_price")
        # 處理價格為 None 的情況 (例如抓不到數據)
        price_str = f"{price:.2f}" if price is not None else "數據缺失 (N/A)"
        
        strat_summary = info.get("Summary", "無訊號")
        
        # 取得細部策略訊號
        ma_signal = info.get("strategies", {}).get("Technical_MA", {}).get("signal", "N/A")
        val_signal = info.get("strategies", {}).get("Fundamental_Valuation", {}).get("signal", "N/A")
        
        # 取得關鍵數據 (如果有)
        ma_data = info.get("strategies", {}).get("Technical_MA", {}).get("data", {})
        val_data = info.get("strategies", {}).get("Fundamental_Valuation", {}).get("data", {})
        
        summary_text += f"""
        ---
        【股票代號】: {stock}
        【目前股價】: {price_str}
        【技術面訊號 (均線策略)】: {ma_signal} (MA5 vs MA20)
        【基本面訊號 (估值策略)】: {val_signal} (PB Ratio: {val_data.get('PB_Ratio', 'N/A')})
        【策略綜合摘要】: {strat_summary}
        """

    # 3. 建構強力 Prompt
    prompt = f"""
    [System Role]:
    你現在是華爾街頂尖的量化交易分析師 (Senior Quant Analyst)。
    你的風格是：專業、客觀、數據導向，且嚴格使用「繁體中文 (Traditional Chinese)」撰寫報告。

    [Context]:
    今天是 {today_date}。
    我將提供你一份最新的量化模型運算數據（JSON Parser Output）。
    這些數據是我們內部系統剛剛生成的最新結果。

    [Input Data]:
    {summary_text}

    [Task]:
    請根據上述數據，撰寫一份《今日量化投資日報》。
    
    [Output Requirements]:
    1. **語言限制**：必須全程使用流暢的「繁體中文」。
    2. **標題**：請使用吸引人的財經日報標題。
    3. **個股點評**：
       - 對每一檔股票進行分析。
       - 如果訊號是 "HOLD"，請解釋為「觀望」或「趨勢不明」，並建議耐心等待。
       - 如果訊號是 "BUY" 或 "SELL"，請強調這是基於技術面還是基本面。
       - 對於「數據缺失」的股票 (如 N/A)，請務必提出風險警示 (Risk Warning)。
    4. **美股與台股區分**：請在分析中自然地識別出哪些是台股 (代號有 .TW/.TWO)，哪些是美股 (如 NVDA, CMCSA)。
    5. **總結建議**：給出一個整體的市場操作建議 (保守/積極/觀望)。

    [Response Start]:
    """
    return prompt

def call_ollama(prompt):
    print("🤖 AI 分析師正在撰寫日報... (正在思考中)")
    
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False
    }
    
    try:
        response = requests.post(OLLAMA_API_URL, json=payload)
        response.raise_for_status()
        result = response.json()
        return result['response']
    except Exception as e:
        return f"❌ Error calling Ollama: {e}"

def main():
    # 1. 讀取報告
    report_data = load_report()
    if not report_data:
        return

    # 2. 生成 Prompt
    prompt = generate_prompt(report_data)
    
    # 3. 呼叫 AI
    ai_reply = call_ollama(prompt)
    
    # 4. 輸出結果
    print("\n" + "="*50)
    print(ai_reply)
    print("="*50 + "\n")

if __name__ == "__main__":
    main()