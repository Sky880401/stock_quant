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

def fetch_stock_data_smart(stock_id: str):
    """
    智慧型數據獲取 (Hybrid 模式)：
    1. 優先嘗試 FinMind 抓股價。
    2. 若 FinMind 抓到股價但基本面(PE/PB)是空的 -> 自動去 Yahoo 補抓基本面。
    3. 若 FinMind 沒股價 -> 全面切換到 Yahoo。
    """
    clean_id = stock_id.split('.')[0] # FinMind ID
    yf_id = stock_id # Yahoo ID

    # 初始化 Providers
    finmind = get_data_provider(PRIMARY_SOURCE)
    yfinance = get_data_provider(FALLBACK_SOURCE)

    # === Step 1: 嘗試 Primary (FinMind) ===
    if clean_id.isdigit():
        df = finmind.get_history(clean_id)
        if not df.empty:
            source_used = "finmind"
            fundamentals = finmind.get_fundamentals(clean_id)
            
            # [關鍵優化] 混合數據補強 (Hybrid Filling)
            # 如果 FinMind 沒抓到 PE 或 PB，就去 Yahoo 借數據
            if not fundamentals or fundamentals.get("pe_ratio") is None:
                # print(f"   ⚠️ FinMind missing fundamentals for {clean_id}, patching with Yahoo...")
                yf_funds = yfinance.get_fundamentals(yf_id)
                
                # 合併數據：優先保留 FinMind 有的值，缺失的用 Yahoo 補
                if not fundamentals: fundamentals = {}
                for k, v in yf_funds.items():
                    if k not in fundamentals or fundamentals[k] is None:
                        fundamentals[k] = v
                
                if fundamentals.get("pe_ratio"):
                    source_used = "finmind + yfinance(fund)"

            return source_used, df, fundamentals

    # === Step 2: 嘗試 Fallback (Yahoo) ===
    # 如果 Step 1 失敗 (例如美股，或 FinMind 當機)
    df = yfinance.get_history(yf_id)
    if not df.empty:
        fundamentals = yfinance.get_fundamentals(yf_id)
        return "yfinance", df, fundamentals
            
    return None, None, None

def analyze_single_target(stock_id: str):
    """[API] 單一標的分析接口"""
    source_used, df, fundamentals = fetch_stock_data_smart(stock_id)
    
    if df is None or df.empty:
        return None

    if not fundamentals: fundamentals = {}
    fundamentals["ticker"] = stock_id

    strategies = {
        "Technical_MA": MACrossoverStrategy(),
        "Fundamental_Valuation": ValuationStrategy()
    }
    
    results = {
        "meta": {"source": source_used, "ticker": stock_id},
        "price_data": {
            "latest_close": float(df['Close'].iloc[-1]),
            "volume": int(df['Volume'].iloc[-1])
        },
        "strategies": {}
    }

    for name, strat in strategies.items():
        try:
            res_obj = strat.analyze(df, extra_data=fundamentals)
            results["strategies"][name] = res_obj.to_dict() if hasattr(res_obj, 'to_dict') else res_obj
        except Exception as e:
            results["strategies"][name] = {"error": str(e)}
            
    return results

def generate_moltbot_prompt(data, is_single=False):
    """生成 Prompt"""
    timestamp = datetime.now().isoformat()
    
    if is_single:
        context = json.dumps(data, indent=2, ensure_ascii=False)
        ticker = data['meta']['ticker']
        header = f"【NVIDIA 405B 即時個股診斷: {ticker}】"
    else:
        context = json.dumps(data.get("analysis", {}), indent=2, ensure_ascii=False)
        header = "【NVIDIA 405B 機構級量化決策報告】"

    prompt = f"""
{header}
時間: {timestamp}
角色: 華爾街出身的台股資深操盤手 (風格：風險趨避、數據導向)
語言: **繁體中文**

--- 估值邏輯 ---
1. **台積電**: 高成長模型。
2. **一般個股**: 若 PE/PB 數據缺失，必須標註「基本面數據不足，風險極高」，不可僅憑技術面喊進。
3. **混合數據源**: 若看到 source 為 "finmind + yfinance"，代表數據經過多源驗證，可信度較高。

--- 衝突矩陣 ---
- Tech BUY + Fund SELL -> 獲利了結
- Tech SELL + Fund BUY -> 低接
- Tech BUY + Fund MISSING -> **投機性買進 (部位減半)**

--- 任務 ---
請分析數據並給出建議。若基本面數據有補齊，請詳細分析估值位階。

[Input Data]
{context}
"""
    return prompt

def main():
    print(f"=== Starting Quant Engine (Batch) ===")
    report = {"timestamp": datetime.now().isoformat(), "analysis": {}}

    for stock_id in TARGET_STOCKS:
        print(f"Processing {stock_id}...")
        res = analyze_single_target(stock_id)
        if res:
            report["analysis"][stock_id] = res
            print(f"   ✅ Done ({res['meta']['source']})")
        else:
            print(f"   ❌ Failed")

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4, ensure_ascii=False)
    
    mission_text = generate_moltbot_prompt(report, is_single=False)
    with open(OUTPUT_MISSION, "w", encoding="utf-8") as f:
        f.write(mission_text)
    print("=== Batch Completed ===")

if __name__ == "__main__":
    main()
