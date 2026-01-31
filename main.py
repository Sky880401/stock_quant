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

# 1. 數據獲取 (保持原樣，省略細節)
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
            if not df.empty and len(df) > 200: # 確保數據夠長
                fundamentals = provider.get_fundamentals(target_id)
                # 混合數據補強
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
        # 優先取短名 (通常是中文)
        name = ticker.info.get('shortName') or ticker.info.get('longName') or stock_id
        # 簡單過濾亂碼或過長英文 (可選)
        return name
    except: return stock_id

def calculate_final_decision(tech_res, fund_res):
    # 邏輯與 v3.0 相同，計算 final_confidence
    base_confidence = tech_res.get("confidence", 0.0)
    total_penalty = tech_res.get("risk_penalty", 0.0) + fund_res.get("risk_penalty", 0.0)
    final_confidence = max(0.0, base_confidence - total_penalty)
    
    tech_signal = tech_res.get("signal")
    fund_signal = fund_res.get("signal")
    
    action = "WATCH"
    pos_size = "0%"

    if tech_signal == "BUY":
        if final_confidence >= 0.7: action, pos_size = "STRONG BUY", "80-100%"
        elif final_confidence >= 0.5: action, pos_size = "BUY (Standard)", "50%"
        else: action, pos_size = "BUY (Speculative)", "20-30%"
    elif tech_signal == "SELL":
        if final_confidence >= 0.7: action, pos_size = "STRONG SELL", "0%"
        else: action, pos_size = "SELL (Reduce)", "0-20%"
    elif tech_signal == "UNKNOWN":
        action = "WAIT (Data Insufficient)"
    
    # 衝突處理
    if tech_signal == "BUY" and fund_signal == "SELL":
        action = "NEUTRAL / PROFIT TAKING"
        pos_size = "Reduce Position"

    return {
        "action": action,
        "position_size": pos_size,
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
            "volume": int(df['Volume'].iloc[-1]),
            "pct_change": 0.0 # 可由前端計算
        },
        "strategies": {"Technical": tech_res, "Fundamental": fund_res},
        "final_decision": decision
    }

def generate_moltbot_prompt(data, is_single=False):
    timestamp = datetime.now().isoformat()
    if is_single:
        context = json.dumps(data, indent=2, ensure_ascii=False)
        ticker = data['meta']['ticker']
        name = data['meta'].get('name', ticker)
        header = f"【BMO 深度投資診斷: {name} ({ticker})】"
    else:
        context = json.dumps(data.get("analysis", {}), indent=2, ensure_ascii=False)
        header = "【BMO 機構級量化決策報告】"

    prompt = f"""
{header}
時間: {timestamp}
語言: **繁體中文 (Traditional Chinese)**
角色: **BMO (QuantMaster)** - 機構級投資顧問。
風格: 結構清晰、數據導向、風險意識強。

--- 任務要求 (Structure) ---
請根據 Input Data 中的 `raw_data` 與 `final_decision`，嚴格依照以下五大區塊撰寫報告：

### 1. 🎯 綜合評級與操作 (Verdict)
- **核心建議**: 根據 `action` 給出明確指令 (買進/賣出/觀望)。
- **建議倉位**: `position_size`。
- **關鍵停損**: 強調 `stop_loss_price`。
- **信心水準**: `final_confidence` (若低於 0.5 請說明原因)。

### 2. 📈 動能與技術分析 (Momentum & Technicals)
*請引用 `strategies.Technical.raw_data` 中的數據：*
- **動能指標**: 分析 ROC (14/21日) 與 RSI (14日)。目前動能是增強還是減弱？是否有背離？
- **均線架構**: 目前價格相對於 MA20 / MA50 / MA200 的位置。是否多頭排列？
- **位階分析**: **"目前股價位於 52 週低點上方 {data.get('strategies', {}).get('Technical', {}).get('raw_data', {}).get('dist_low_52w_pct', 'N/A')}%"**。

### 3. 🏢 基本面與價值篩選 (Fundamentals & Value)
- **估值狀態**: 引用 PE (本益比) 與 PB (股價淨值比)。
- **價值判斷**: 比較 PE 是否 ≤ 10 (低估) 或歷史區間位置。
- **資料警示**: 若 PE/PB 為 null，必須發出「基本面不透明風險」警示。

### 4. 🌊 市場趨勢與籌碼 (Market Context)
- **長期趨勢**: 根據 MA200 (年線) 判斷目前是牛市還是熊市。
- **風險評估**: 基於 `risk_factors` 說明目前最大風險 (是技術面過熱？還是基本面不明？)。

### 5. 💡 BMO 的一句話 (Summary)
- 用一句話總結這檔股票目前的狀態 (例如：「動能強勁但估值過高，建議短打。」)

--- 
[Input Data]
{context}
"""
    return prompt

def main():
    print(f"=== Starting Quant Engine v4.0 (Deep Analysis) ===")
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
