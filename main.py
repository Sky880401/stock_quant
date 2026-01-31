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

def get_stock_name_zh(stock_id: str) -> str:
    clean_id = stock_id.split('.')[0]
    if not clean_id.isdigit(): return stock_id
    try:
        from FinMind.data import DataLoader
        dl = DataLoader()
        df = dl.taiwan_stock_info()
        row = df[df['stock_id'] == clean_id]
        if not row.empty: return row.iloc[0]['stock_name']
    except: pass
    return clean_id

def fetch_stock_data_smart(stock_id: str):
    """
    智能數據獲取：自動嘗試 .TW 與 .TWO
    """
    clean_id = stock_id.split('.')[0]
    
    # 定義嘗試順序：如果傳入的是 .TWO，就先試 .TWO，失敗再試 .TW；反之亦然
    candidates = []
    if clean_id.isdigit():
        if "TWO" in stock_id:
            candidates = [f"{clean_id}.TWO", f"{clean_id}.TW"]
        else:
            candidates = [f"{clean_id}.TW", f"{clean_id}.TWO"]
    else:
        candidates = [stock_id]

    # 開始輪詢候選代號
    for current_id in candidates:
        # print(f"🔍 Trying {current_id}...") # Debug
        
        # 1. 嘗試 FinMind (主要)
        # FinMind 只認數字，所以其實對它沒差，但這一步是為了確認 Yahoo ID 對應正確
        provider = get_data_provider(PRIMARY_SOURCE)
        try:
            df = provider.get_history(clean_id) # FinMind always uses clean_id
            
            # 如果 FinMind 沒資料，嘗試 Yahoo 獲取歷史數據
            if df.empty or len(df) < 60:
                yf_provider = get_data_provider(FALLBACK_SOURCE)
                df = yf_provider.get_history(current_id)
            
            if df.empty or len(df) < 60:
                continue # 這個後綴失敗，換下一個

            # 2. 嘗試獲取基本面 (PE/PB)
            fundamentals = {}
            try: fundamentals = provider.get_fundamentals(clean_id)
            except: pass

            # 3. Patching (混合補強)
            # 這是最關鍵的一步：用 current_id 去 Yahoo 查
            if (not fundamentals or not fundamentals.get("pe_ratio")) and clean_id.isdigit():
                try:
                    yf_provider = get_data_provider(FALLBACK_SOURCE)
                    yf_funds = yf_provider.get_fundamentals(current_id)
                    if yf_funds and (yf_funds.get("pe_ratio") or yf_funds.get("market_cap")):
                        # Yahoo 查到了！代表 current_id 是正確的後綴
                        if not fundamentals: fundamentals = {}
                        for k, v in yf_funds.items():
                            if k not in fundamentals or fundamentals[k] is None: fundamentals[k] = v
                    else:
                        # Yahoo 查不到基本面，可能代號錯了 (例如用 .TW 查上櫃)
                        # 但如果我們已經有股價了，還是可以勉強接受
                        pass
                except: pass
            
            # 如果成功拿到股價，我們就認定這個 current_id 是對的
            # 回傳時更新 meta ticker
            return "Hybrid", df, fundamentals, current_id

        except Exception as e:
            # print(f"Error fetching {current_id}: {e}")
            continue

    return None, None, None, None # 全部失敗

# ... (analyze_chip 保持原樣 V6.0) ...
def analyze_chip(df):
    if 'Foreign' not in df.columns: 
        return {"score": 0, "status": "Unknown", "reason": "無籌碼數據 (僅技術面參考)"}
    recent = df.tail(5)
    foreign_sum = recent['Foreign'].sum()
    score = 0; status = "Neutral"; reasons = []
    if foreign_sum > 1000: score += 1; reasons.append(f"外資近5日累計買超 {int(foreign_sum/1000)}k 張")
    elif foreign_sum < -1000: score -= 1; reasons.append(f"外資近5日累計賣超 {int(abs(foreign_sum)/1000)}k 張")
    else: reasons.append("外資動向不明顯 (觀望)")
    price_change = df['Close'].iloc[-1] - df['Close'].iloc[-5]
    if price_change > 0 and foreign_sum < 0:
        reasons.append("⚠️ 警示: 價漲量縮/外資倒貨 (背離風險)"); score -= 0.5
    if score > 0.5: status = "Bullish"
    elif score < -0.5: status = "Bearish"
    return {"score": score, "status": status, "reason": " | ".join(reasons)}

# ... (calculate_final_decision 保持原樣 V6.0) ...
def calculate_final_decision(tech_res, fund_res, chip_res, backtest_info=None):
    tech_signal = tech_res.get("signal")
    fund_signal = fund_res.get("signal")
    rsi_val = tech_res.get("raw_data", {}).get("rsi_14", 50)
    base_confidence = 0.5; score = 0
    if tech_signal == "BUY": score += 0.4
    elif tech_signal == "SELL": score -= 0.4
    if fund_signal == "BUY": score += 0.3
    elif fund_signal == "SELL": score -= 0.3
    elif fund_signal == "UNKNOWN": score -= 0.1
    if chip_res['score'] > 0: score += 0.2
    elif chip_res['score'] < 0: score -= 0.2
    roi = backtest_info.get("historical_roi", 0) if backtest_info else 0
    if roi > 50: score += 0.1
    
    risk_flags = []; action = "WATCH"; pos_size = "0%"; time_horizon = "Neutral"
    if rsi_val > 80: score -= 0.3; risk_flags.append("🔥 技術面嚴重過熱 (RSI>80)"); pos_size_cap = 30
    elif rsi_val > 70: risk_flags.append("⚠️ 技術面過熱 (RSI>70)"); pos_size_cap = 50
    else: pos_size_cap = 100
    
    if tech_signal == "BUY" and fund_signal == "SELL":
        risk_flags.append("⚔️ 訊號衝突 (技術多/基本空)"); time_horizon = "Short-term (Speculative)"
        action = "BUY (Speculative)"; score = min(score, 0.4); pos_size_cap = min(pos_size_cap, 30)
    elif tech_signal == "BUY" and fund_signal == "BUY":
        time_horizon = "Mid-Long term"; action = "STRONG BUY"
    else: time_horizon = "Wait & See"

    final_confidence = max(0, min(1, 0.5 + score))
    if "Speculative" not in action:
        if final_confidence >= 0.75: action = "STRONG BUY"
        elif final_confidence >= 0.6: action = "BUY"
        elif final_confidence <= 0.3: action = "STRONG SELL"
        elif final_confidence <= 0.45: action = "SELL"
        else: action = "HOLD / WATCH"

    if "BUY" in action:
        suggested = int(final_confidence * 100); suggested = min(suggested, pos_size_cap)
        if suggested < 20: pos_size = "10-20% (Test Position)"
        elif suggested < 50: pos_size = f"{suggested-10}-{suggested}% (Conservative)"
        else: pos_size = f"{suggested-10}-{suggested}% (Aggressive)"
    else: pos_size = "0% (Cash is King)"

    return {
        "action": action, "position_size": pos_size, "time_horizon": time_horizon,
        "final_confidence": round(final_confidence, 2), "risk_factors": " | ".join(risk_flags) if risk_flags else "None",
        "chip_insight": chip_res['reason'], "tech_insight": f"RSI={rsi_val:.1f}",
        "backtest_support": f"ROI {roi}%" if backtest_info else "N/A"
    }

# === [修改] analyze_single_target 支援正確的 ID 回傳 ===
def analyze_single_target(stock_id: str, run_optimization_if_missing: bool = False):
    clean_id = stock_id.split('.')[0]
    backtest_info = None; config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f: config = json.load(f); 
            if clean_id in config: backtest_info = config[clean_id]
        except: pass
    
    # 這裡的 ID 只是暫時的，真正正確的 ID 會由 fetch_stock_data_smart 決定
    if not backtest_info and run_optimization_if_missing:
        # 優化時使用混合嘗試
        target_input = f"{clean_id}.TW" # 預設嘗試上市
        new_params = find_best_params(target_input) # find_best_params 內部已有 hybrid 機制
        if new_params:
            config[clean_id] = new_params
            os.makedirs("data", exist_ok=True)
            with open(CONFIG_FILE, "w") as f: json.dump(config, f, indent=4)
            backtest_info = new_params

    # [關鍵修改] 接收 4 個回傳值，包含正確的 correct_ticker
    res = fetch_stock_data_smart(stock_id)
    if not res or not res[1] is not None: return None
    source_used, df, fundamentals, correct_ticker = res

    if not fundamentals: fundamentals = {}
    fundamentals["ticker"] = correct_ticker # 使用修正後的 ID
    stock_name = get_stock_name_zh(correct_ticker)

    tech_strat = MACrossoverStrategy()
    fund_strat = ValuationStrategy()
    tech_res = tech_strat.analyze(df, extra_data=fundamentals).to_dict()
    fund_res = fund_strat.analyze(df, extra_data=fundamentals).to_dict()
    chip_res = analyze_chip(df)
    decision = calculate_final_decision(tech_res, fund_res, chip_res, backtest_info)
    chart_path = generate_stock_chart(stock_name, df, strategy_params=backtest_info)

    return {
        "meta": {"source": source_used, "ticker": correct_ticker, "name": stock_name},
        "price_data": {"latest_close": float(df['Close'].iloc[-1]), "volume": int(df['Volume'].iloc[-1])},
        "strategies": {"Technical": tech_res, "Fundamental": fund_res, "Chip": chip_res},
        "backtest_insight": backtest_info, 
        "final_decision": decision,
        "chart_path": chart_path
    }

def generate_moltbot_prompt(data, is_single=False):
    # (保持原樣 V6.0)
    timestamp = datetime.now().isoformat()
    if is_single:
        context = json.dumps(data, indent=2, ensure_ascii=False)
        ticker = data['meta']['ticker']
        name = data['meta'].get('name', ticker)
        dec = data['final_decision']
        chip_info = data['strategies']['Chip']['reason']
        risk_info = dec['risk_factors']
        time_horizon = dec['time_horizon']
        header = f"【BMO 專業投資評鑑: {name} ({ticker})】"
        guidance = f"""
### 🚨 風險與決策邏輯 (必須嚴格遵守):
1. **投資屬性**: 本次建議為 **{time_horizon}** 操作。
2. **風險警示**: 目前偵測到風險因子: [{risk_info}]。
3. **籌碼解讀**: {chip_info}。
4. **基本面**: 若基本面為 SELL，請明確警告估值過高。
"""
    else:
        context = json.dumps(data.get("analysis", {}), indent=2, ensure_ascii=False)
        header = "【BMO 機構級量化決策報告】"
        guidance = ""

    prompt = f"""
{header}
時間: {timestamp}
語言: **繁體中文**
角色: **BMO** - 嚴謹的機構級量化分析師。

--- 分析指引 ---
{guidance}

請依照以下結構撰寫報告：
1. **📊 綜合評級 (Verdict)**: Action 與 建議倉位。
2. **⚖️ 邏輯推演 (Rationale)**: 技術/基本/籌碼。
3. **⛔ 風險與停損 (Risk Control)**: 停損價與風險。

[Input Data]
{context}
"""
    return prompt

def main(): pass
if __name__ == "__main__": main()
