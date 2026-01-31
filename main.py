import sys
import os
import json
import yfinance as yf
from datetime import datetime

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

# ... (保留 fetch_stock_data_smart 與 source_used_name，省略以節省篇幅) ...
def fetch_stock_data_smart(stock_id: str):
    clean_id = stock_id.split('.')[0]
    yf_id = stock_id
    providers = []
    if clean_id.isdigit():
        providers.append((PRIMARY_SOURCE, get_data_provider(PRIMARY_SOURCE), clean_id))
        providers.append((FALLBACK_SOURCE, get_data_provider(FALLBACK_SOURCE), yf_id))
    else:
        providers.append((FALLBACK_SOURCE, get_data_provider(FALLBACK_SOURCE), yf_id))
        
    for source_name, provider, target_id in providers:
        try:
            df = provider.get_history(target_id)
            if not df.empty:
                fundamentals = provider.get_fundamentals(target_id)
                if (not fundamentals or not fundamentals.get("pe_ratio")) and clean_id.isdigit():
                     yf_funds = get_data_provider(FALLBACK_SOURCE).get_fundamentals(yf_id)
                     if not fundamentals: fundamentals = {}
                     for k,v in yf_funds.items():
                         if k not in fundamentals or fundamentals[k] is None: fundamentals[k] = v
                return source_used_name(source_name, fundamentals), df, fundamentals
        except: continue
    return None, None, None

def source_used_name(base, fund):
    if base == "finmind" and fund and fund.get("pe_ratio"): return "finmind + yfinance"
    return base

def get_stock_name(stock_id: str) -> str:
    try:
        query_id = f"{stock_id}.TW" if stock_id.isdigit() else stock_id
        ticker = yf.Ticker(query_id)
        # 優先取短名，通常比較乾淨
        return ticker.info.get('shortName') or ticker.info.get('longName') or stock_id
    except:
        return stock_id

def calculate_final_decision(tech_res, fund_res):
    # ... (保持 v3.0 的決策邏輯，省略) ...
    base_confidence = tech_res.get("confidence", 0.0)
    total_penalty = tech_res.get("risk_penalty", 0.0) + fund_res.get("risk_penalty", 0.0)
    final_confidence = max(0.0, base_confidence - total_penalty)
    tech_signal = tech_res.get("signal")
    fund_signal = fund_res.get("signal")
    
    action = "WATCH"
    position_size = "0%"
    
    if tech_signal == "BUY":
        if final_confidence >= 0.75: action, position_size = "STRONG BUY", "100% (Full)"
        elif final_confidence >= 0.5: action, position_size = "BUY (Speculative)", "50% (Half)"
        else: action, position_size = "WATCH (High Risk)", "0%"
    elif tech_signal == "SELL":
        if final_confidence >= 0.7: action = "STRONG SELL"
        else: action = "SELL (Reduce)"
    
    if tech_signal == "BUY" and fund_signal == "UNKNOWN":
        action, position_size = "BUY (Technical Only)", "30-50% (Risk Managed)"

    return {
        "action": action,
        "position_size": position_size,
        "final_confidence": round(final_confidence, 2),
        "stop_loss_price": tech_res.get("stop_loss", 0.0),
        "risk_factors": f"Penalty: -{total_penalty}" if total_penalty > 0 else "None"
    }

def analyze_single_target(stock_id: str):
    source_used, df, fundamentals = fetch_stock_data_smart(stock_id)
    if df is None or df.empty: return None

    if not fundamentals: fundamentals = {}
    fundamentals["ticker"] = stock_id
    stock_name = get_stock_name(stock_id)

    tech_strat = MACrossoverStrategy()
    fund_strat = ValuationStrategy()
    
    tech_res = tech_strat.analyze(df, extra_data=fundamentals).to_dict()
    fund_res = fund_strat.analyze(df, extra_data=fundamentals).to_dict()
    decision = calculate_final_decision(tech_res, fund_res)

    return {
        "meta": {"source": source_used, "ticker": stock_id, "name": stock_name},
        "price_data": {
            "latest_close": float(df['Close'].iloc[-1]),
            "volume": int(df['Volume'].iloc[-1])
        },
        "strategies": {"Technical": tech_res, "Fundamental": fund_res},
        "final_decision": decision
    }

def generate_moltbot_prompt(data, is_single=False):
    timestamp = datetime.now().isoformat()
    if is_single:
        context = json.dumps(data, indent=2, ensure_ascii=False)
        ticker = data['meta']['ticker']
        # 這裡的 name 可能是英文，留給 AI 翻譯
        raw_name = data['meta'].get('name', ticker)
        header = f"【BMO 即時個股診斷: {ticker}】"
    else:
        context = json.dumps(data.get("analysis", {}), indent=2, ensure_ascii=False)
        header = "【BMO 機構級量化決策報告】"

    prompt = f"""
{header}
時間: {timestamp}
語言: **繁體中文 (Traditional Chinese)** - 必須嚴格執行。
角色: **BMO** - 您的台灣在地化量化投資顧問。

--- 翻譯與術語轉換指令 (Strict Translation Rules) ---
1. **股名翻譯**: 若 Input Data 中的股名是英文 (如 "Taiwan Semiconductor..."), 請務必翻譯成台灣通用的中文名稱 (如 "台積電")。
2. **訊號翻譯**:
   - BUY -> 買進
   - SELL -> 賣出
   - HOLD -> 續抱/觀望
   - STRONG BUY -> 強力買進
   - Technical Only -> 僅依技術面
3. **專有名詞**:
   - Stop Loss -> 停損點
   - Position Size -> 建議倉位

--- 任務 ---
請以 BMO 的口吻撰寫報告。
開頭範例：「Hi, 我是 BMO。關於 **[中文股名]** ({data.get('meta', {}).get('ticker', '')}) 的分析如下...」

[Input Data]
{context}
"""
    return prompt

def main():
    print(f"=== Starting Quant Engine v3.2 (Localization) ===")
    report = {"timestamp": datetime.now().isoformat(), "analysis": {}}
    for stock_id in TARGET_STOCKS:
        print(f"Processing {stock_id}...")
        res = analyze_single_target(stock_id)
        if res:
            report["analysis"][stock_id] = res
            print(f"   ✅ Done ({res['meta']['name']})")
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4, ensure_ascii=False)
    mission_text = generate_moltbot_prompt(report, is_single=False)
    with open(OUTPUT_MISSION, "w", encoding="utf-8") as f:
        f.write(mission_text)
    print("=== Batch Completed ===")

if __name__ == "__main__":
    main()
