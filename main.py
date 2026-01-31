import sys
import os
import json
import yfinance as yf
from datetime import datetime
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.data_loader import get_data_provider
from strategies.ma_crossover import MACrossoverStrategy
from strategies.valuation_strategy import ValuationStrategy
from utils.plotter import generate_stock_chart
from optimizer_runner import find_best_params

# 配置
TARGET_STOCKS = ["2330.TW", "2888.TW", "2317.TW"]
PRIMARY_SOURCE = "finmind"
FALLBACK_SOURCE = "yfinance"
CONFIG_FILE = "data/stock_config.json"
OUTPUT_FILE = "data/latest_report.json"
OUTPUT_MISSION = "data/moltbot_mission.txt"

# [新增] 正確獲取中文股名
def get_stock_name_zh(stock_id: str) -> str:
    clean_id = stock_id.split('.')[0]
    if not clean_id.isdigit(): return stock_id # 美股直接回傳
    
    # 1. 嘗試 FinMind (最準確的中文名)
    try:
        from FinMind.data import DataLoader
        dl = DataLoader()
        # 抓取最新的股票清單
        df = dl.taiwan_stock_info()
        row = df[df['stock_id'] == clean_id]
        if not row.empty:
            return row.iloc[0]['stock_name']
    except Exception as e:
        # print(f"FinMind name lookup failed: {e}")
        pass
        
    # 2. Yahoo Fallback
    try:
        yf_id = stock_id if "TW" in stock_id else f"{stock_id}.TW"
        ticker = yf.Ticker(yf_id)
        # Yahoo 的 longName 常常是英文，我們看看有無其他資訊，或直接回傳英文讓 AI 翻譯
        return ticker.info.get('longName') or clean_id
    except:
        return clean_id

def fetch_stock_data_smart(stock_id: str):
    # (保持原樣 v5.1)
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
            if df.empty or len(df) < 60: continue
            
            fundamentals = {}
            try: fundamentals = provider.get_fundamentals(target_id)
            except: pass
            
            # Patching
            if (not fundamentals or not fundamentals.get("pe_ratio")) and clean_id.isdigit():
                try:
                    yf_provider = get_data_provider(FALLBACK_SOURCE)
                    # 嘗試補強時，若原本是 3141，這裡要試 3141.TWO
                    candidates = [f"{clean_id}.TWO", f"{clean_id}.TW"]
                    for c in candidates:
                        yf_funds = yf_provider.get_fundamentals(c)
                        if yf_funds and yf_funds.get("pe_ratio"):
                             if not fundamentals: fundamentals = {}
                             for k, v in yf_funds.items():
                                 if k not in fundamentals or fundamentals[k] is None: fundamentals[k] = v
                             break
                except: pass

            return source_used_name(source_name, fundamentals), df, fundamentals
        except: continue
    return None, None, None

def source_used_name(base, fund):
    if base == "finmind" and fund and fund.get("pe_ratio"): return "finmind + yfinance"
    return base

# ... (calculate_final_decision, analyze_chip 保持原樣，省略) ...
# 請保留原有的 calculate_final_decision 和 analyze_chip

def calculate_final_decision(tech_res, fund_res, chip_res, backtest_info=None):
    base_confidence = tech_res.get("confidence", 0.0)
    chip_bonus = 0.0
    if chip_res['score'] > 0: chip_bonus = 0.15
    elif chip_res['score'] < 0: chip_bonus = -0.15
    roi_bonus = 0.0
    if backtest_info:
        roi = backtest_info.get("historical_roi", 0)
        if roi > 50: roi_bonus = 0.1
        
    final_confidence = max(0.0, base_confidence + chip_bonus + roi_bonus - tech_res.get("risk_penalty", 0))
    tech_signal = tech_res.get("signal")
    action = "WATCH"; pos_size = "0%"
    if tech_signal == "BUY":
        if final_confidence >= 0.8: action, pos_size = "STRONG BUY (Alpha)", "100%"
        elif final_confidence >= 0.6: action, pos_size = "BUY", "50-70%"
        else: action, pos_size = "BUY (Speculative)", "20-30%"
    elif tech_signal == "SELL":
        if final_confidence >= 0.7: action = "STRONG SELL"
        else: action = "SELL"
    return {
        "action": action, "position_size": pos_size, "final_confidence": round(final_confidence, 2),
        "stop_loss_price": tech_res.get("stop_loss", 0.0),
        "chip_insight": chip_res['reason'],
        "backtest_support": f"ROI {backtest_info['historical_roi']}%" if backtest_info else "N/A"
    }

def analyze_chip(df):
    if 'Foreign' not in df.columns: return {"score": 0, "reason": "No Data"}
    recent = df.tail(5)
    foreign_sum = recent['Foreign'].sum()
    trust_sum = recent['Trust'].sum()
    score = 0; reasons = []
    if foreign_sum > 0: score += 1; reasons.append(f"外資近5日買超 {int(foreign_sum/1000)}張")
    elif foreign_sum < 0: score -= 1; reasons.append(f"外資近5日賣超 {int(abs(foreign_sum)/1000)}張")
    if trust_sum > 0: score += 1.5; reasons.append(f"投信近5日買超 {int(trust_sum/1000)}張")
    return {"score": score, "reason": " | ".join(reasons) if reasons else "籌碼中性"}

def analyze_single_target(stock_id: str, run_optimization_if_missing: bool = False):
    clean_id = stock_id.split('.')[0]
    backtest_info = None
    config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                if clean_id in config: backtest_info = config[clean_id]
        except: pass
    
    if not backtest_info and run_optimization_if_missing:
        # 這裡不印 log，交給 Discord 顯示
        target_input = f"{clean_id}.TW" if clean_id.isdigit() else stock_id
        new_params = find_best_params(target_input)
        if new_params:
            config[clean_id] = new_params
            os.makedirs("data", exist_ok=True)
            with open(CONFIG_FILE, "w") as f: json.dump(config, f, indent=4)
            backtest_info = new_params

    source_used, df, fundamentals = fetch_stock_data_smart(stock_id)
    if df is None or df.empty: return None

    if not fundamentals: fundamentals = {}
    fundamentals["ticker"] = stock_id
    
    # [修正] 使用新的中文名稱獲取函數
    stock_name = get_stock_name_zh(stock_id)

    tech_strat = MACrossoverStrategy()
    fund_strat = ValuationStrategy()
    tech_res = tech_strat.analyze(df, extra_data=fundamentals).to_dict()
    fund_res = fund_strat.analyze(df, extra_data=fundamentals).to_dict()
    chip_res = analyze_chip(df)
    decision = calculate_final_decision(tech_res, fund_res, chip_res, backtest_info)
    chart_path = generate_stock_chart(stock_name, df, strategy_params=backtest_info)

    return {
        "meta": {"source": source_used, "ticker": stock_id, "name": stock_name},
        "price_data": {"latest_close": float(df['Close'].iloc[-1]), "volume": int(df['Volume'].iloc[-1])},
        "strategies": {"Technical": tech_res, "Fundamental": fund_res, "Chip": chip_res},
        "backtest_insight": backtest_info, 
        "final_decision": decision,
        "chart_path": chart_path
    }

def generate_moltbot_prompt(data, is_single=False):
    timestamp = datetime.now().isoformat()
    if is_single:
        context = json.dumps(data, indent=2, ensure_ascii=False)
        ticker = data['meta']['ticker']
        name = data['meta'].get('name', ticker)
        chip_info = data['strategies']['Chip']['reason']
        header = f"【BMO 全方位診斷: {name} ({ticker})】"
        chip_text = f"### 💰 籌碼面分析\n- **動向**: {chip_info}"
    else:
        context = json.dumps(data.get("analysis", {}), indent=2, ensure_ascii=False)
        header = "【BMO 機構級量化決策報告】"
        chip_text = ""

    prompt = f"""
{header}
時間: {timestamp}
語言: **繁體中文**
角色: **BMO**

--- 任務 ---
{chip_text}
請撰寫報告。
**注意**: 股名已修正為 "{name}"，請在報告中使用此名稱。

[Input Data]
{context}
"""
    return prompt

def main():
    pass # 供 discord 呼叫

if __name__ == "__main__":
    main()
