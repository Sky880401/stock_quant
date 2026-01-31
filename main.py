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
CONFIG_FILE = "data/stock_config.json"

OUTPUT_FILE = "data/latest_report.json"
OUTPUT_MISSION = "data/moltbot_mission.txt"

def fetch_stock_data_smart(stock_id: str):
    clean_id = stock_id.split('.')[0]
    yf_id = stock_id
    providers = []
    
    # 定義查詢順序
    if clean_id.isdigit():
        providers.append((PRIMARY_SOURCE, get_data_provider(PRIMARY_SOURCE), clean_id))
        providers.append((FALLBACK_SOURCE, get_data_provider(FALLBACK_SOURCE), yf_id))
    else:
        providers.append((FALLBACK_SOURCE, get_data_provider(FALLBACK_SOURCE), yf_id))
        
    for source_name, provider, target_id in providers:
        try:
            # 1. 獲取股價 (這是最核心的，不能失敗)
            df = provider.get_history(target_id)
            if df.empty or len(df) < 60: # 放寬限制，至少要有 60 天均線數據
                continue

            # 2. 獲取基本面 (允許失敗)
            fundamentals = {}
            try:
                fundamentals = provider.get_fundamentals(target_id)
            except: pass # 基本面抓不到就算了
            
            # 3. [關鍵修正] 混合數據補強 (獨立 Try-Catch)
            # 只有當是台股且基本面缺失時才嘗試補強
            if (not fundamentals or not fundamentals.get("pe_ratio")) and clean_id.isdigit():
                try:
                    yf_provider = get_data_provider(FALLBACK_SOURCE)
                    yf_funds = yf_provider.get_fundamentals(yf_id)
                    if not fundamentals: fundamentals = {}
                    for k, v in yf_funds.items():
                        if k not in fundamentals or fundamentals[k] is None:
                            fundamentals[k] = v
                except Exception as e:
                    # 補強失敗沒關係，我們還有股價就好
                    # print(f"   ⚠️ Patching failed for {stock_id}: {e}")
                    pass

            return source_used_name(source_name, fundamentals), df, fundamentals

        except Exception as e:
            # print(f"   ⚠️ Provider {source_name} failed: {e}")
            continue
            
    return None, None, None

def source_used_name(base, fund):
    if base == "finmind" and fund and fund.get("pe_ratio"): return "finmind + yfinance"
    return base

def get_stock_name(stock_id: str) -> str:
    try:
        query_id = f"{stock_id}.TW" if stock_id.isdigit() else stock_id
        ticker = yf.Ticker(query_id)
        name = ticker.info.get('shortName') or ticker.info.get('longName') or stock_id
        return name
    except: return stock_id

def calculate_final_decision(tech_res, fund_res, backtest_info=None):
    base_confidence = tech_res.get("confidence", 0.0)
    total_penalty = tech_res.get("risk_penalty", 0.0) + fund_res.get("risk_penalty", 0.0)
    
    roi_bonus = 0.0
    if backtest_info and backtest_info.get("historical_roi", 0) > 50:
        roi_bonus = 0.15 # 提高獎勵
        
    final_confidence = max(0.0, base_confidence - total_penalty + roi_bonus)
    
    tech_signal = tech_res.get("signal")
    fund_signal = fund_res.get("signal")
    
    action = "WATCH"
    pos_size = "0%"

    if tech_signal == "BUY":
        if final_confidence >= 0.75: action, pos_size = "STRONG BUY", "80-100%"
        elif final_confidence >= 0.5: action, pos_size = "BUY (Standard)", "50%"
        else: action, pos_size = "BUY (Speculative)", "20-30%"
    elif tech_signal == "SELL":
        if final_confidence >= 0.7: action, pos_size = "STRONG SELL", "0%"
        else: action, pos_size = "SELL (Reduce)", "0-20%"
    elif tech_signal == "UNKNOWN":
        action = "WAIT"

    return {
        "action": action,
        "position_size": pos_size,
        "final_confidence": round(final_confidence, 2),
        "stop_loss_price": tech_res.get("stop_loss", 0.0),
        "risk_factors": f"Penalty: {total_penalty}, Bonus: {roi_bonus}",
        "backtest_support": f"ROI {backtest_info['historical_roi']}%" if backtest_info else "N/A"
    }

def analyze_single_target(stock_id: str):
    source_used, df, fundamentals = fetch_stock_data_smart(stock_id)
    if df is None or df.empty: return None

    if not fundamentals: fundamentals = {}
    fundamentals["ticker"] = stock_id
    stock_name = get_stock_name(stock_id)
    clean_id = stock_id.split('.')[0]

    backtest_info = None
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                if clean_id in config:
                    backtest_info = config[clean_id]
        except: pass

    tech_strat = MACrossoverStrategy()
    fund_strat = ValuationStrategy()
    
    tech_res = tech_strat.analyze(df, extra_data=fundamentals).to_dict()
    fund_res = fund_strat.analyze(df, extra_data=fundamentals).to_dict()
    decision = calculate_final_decision(tech_res, fund_res, backtest_info)

    return {
        "meta": {"source": source_used, "ticker": stock_id, "name": stock_name},
        "price_data": {
            "latest_close": float(df['Close'].iloc[-1]),
            "volume": int(df['Volume'].iloc[-1]),
        },
        "strategies": {"Technical": tech_res, "Fundamental": fund_res},
        "backtest_insight": backtest_info, 
        "final_decision": decision
    }

def generate_moltbot_prompt(data, is_single=False):
    timestamp = datetime.now().isoformat()
    if is_single:
        context = json.dumps(data, indent=2, ensure_ascii=False)
        ticker = data['meta']['ticker']
        name = data['meta'].get('name', ticker)
        
        bt_info = data.get('backtest_insight')
        bt_text = ""
        if bt_info:
            bt_text = f"""
### 🏆 歷史回測驗證
- **最佳參數**: MA {bt_info['fast_ma']} / {bt_info['slow_ma']}
- **過去三年報酬**: **{bt_info['historical_roi']}%**
- **解讀**: 此策略有歷史數據支持，請納入評估。
"""
        header = f"【BMO 深度投資診斷: {name} ({ticker})】"
    else:
        context = json.dumps(data.get("analysis", {}), indent=2, ensure_ascii=False)
        header = "【BMO 機構級量化決策報告】"
        bt_text = ""

    prompt = f"""
{header}
時間: {timestamp}
語言: **繁體中文**
角色: **BMO** - 數據驅動的量化顧問。

--- 任務要求 ---
{bt_text}

請撰寫報告：
1. **Verdict**: 給出明確操作建議 (Strong Buy / Buy / Watch)。
2. **Analysis**: 引用 ROC, RSI, MA 數據。
3. **Risk**: 若基本面缺失 (PE/PB N/A)，請明確指出風險，並強調 **技術面停損點**。

[Input Data]
{context}
"""
    return prompt

def main():
    print(f"=== Starting Quant Engine v4.2 (Robust Patching) ===")
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
