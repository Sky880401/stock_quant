import sys
import os
import json
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.data_loader import get_data_provider
from strategies.ma_crossover import MACrossoverStrategy
from strategies.valuation_strategy import ValuationStrategy
from utils.plotter import generate_stock_chart
from optimizer_runner import find_best_params
from utils.logger import log_info, log_warn, log_error

# 配置
TARGET_STOCKS = ["2330.TW", "2888.TW", "2317.TW"]
CONFIG_FILE = "data/stock_config.json"
PRIMARY_SOURCE = "finmind"
FALLBACK_SOURCE = "yfinance"

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
    log_info(f"正在獲取數據: {stock_id} ...")
    clean_id = stock_id.split('.')[0]
    
    candidates = []
    if clean_id.isdigit():
        if "TWO" in stock_id: candidates = [f"{clean_id}.TWO", f"{clean_id}.TW"]
        else: candidates = [f"{clean_id}.TW", f"{clean_id}.TWO"]
    else: candidates = [stock_id]

    for current_id in candidates:
        provider = get_data_provider(PRIMARY_SOURCE)
        try:
            df = provider.get_history(clean_id)
            if df.empty or len(df) < 60:
                yf_provider = get_data_provider(FALLBACK_SOURCE)
                df = yf_provider.get_history(current_id)
            
            if df.empty or len(df) < 60: continue

            fundamentals = {}
            try: fundamentals = provider.get_fundamentals(clean_id)
            except: pass

            if (not fundamentals or not fundamentals.get("pe_ratio")) and clean_id.isdigit():
                try:
                    yf_provider = get_data_provider(FALLBACK_SOURCE)
                    yf_funds = yf_provider.get_fundamentals(current_id)
                    if yf_funds and (yf_funds.get("pe_ratio") or yf_funds.get("market_cap")):
                        if not fundamentals: fundamentals = {}
                        for k, v in yf_funds.items():
                            if k not in fundamentals or fundamentals[k] is None: fundamentals[k] = v
                except: pass
            
            log_info(f"數據獲取成功: {current_id} (Length: {len(df)})")
            return "Hybrid", df, fundamentals, current_id

        except Exception as e:
            # 這裡不記錄 log，因為嘗試失敗很正常，不需要洗版
            continue

    # [優化] 改用 WARN，並明確指出可能原因
    log_warn(f"無法獲取任何數據: {stock_id} (可能已下市或代號錯誤)")
    return None, None, None, None

def analyze_chip(df):
    if 'Foreign' not in df.columns: 
        return {"score": 0, "status": "Neutral", "reason": "無籌碼數據"}
    
    # [修復] 確保無 NaN
    df['Foreign'] = df['Foreign'].fillna(0)
    
    recent = df.tail(5)
    foreign_sum = recent['Foreign'].sum()
    score = 0; status = "Neutral"; reasons = []

    if foreign_sum > 1000: score += 1; reasons.append(f"外資買超 {int(foreign_sum/1000)}k"); status="Bullish"
    elif foreign_sum < -1000: score -= 1; reasons.append(f"外資賣超 {int(abs(foreign_sum)/1000)}k"); status="Bearish"
    else: reasons.append("外資觀望"); status="Neutral"
    
    if (df['Close'].iloc[-1] > df['Close'].iloc[-5]) and foreign_sum < 0:
        reasons.append("⚠️價漲量縮/外資倒貨")
        score -= 0.5
    
    return {"score": score, "status": status, "reason": " | ".join(reasons)}

def calculate_final_decision(tech_res, fund_res, chip_res, backtest_info=None, fundamentals=None):
    tech_signal = tech_res.get("signal")
    fund_signal = fund_res.get("signal")
    rsi_val = tech_res.get("raw_data", {}).get("rsi_14", 50)
    
    pe = fundamentals.get("pe_ratio") if fundamentals else None
    
    log_info(f"決策參數: Tech={tech_signal}, Fund={fund_signal}, RSI={rsi_val:.1f}, Chip={chip_res['status']}, PE={pe}")

    score = 0
    if tech_signal == "BUY": score += 0.4
    elif tech_signal == "SELL": score -= 0.4
    
    is_growth_stock = False
    if pe and pe > 25 and tech_signal == "BUY" and chip_res['score'] > 0:
        is_growth_stock = True
        fund_signal = "NEUTRAL (Growth)"
        score += 0.1
    
    if fund_signal == "BUY": score += 0.3
    elif fund_signal == "SELL": score -= 0.3
    
    if chip_res['score'] > 0: score += 0.2
    elif chip_res['score'] < 0: score -= 0.2
    
    roi = backtest_info.get("historical_roi", 0) if backtest_info else 0
    if roi > 50: score += 0.1

    risk_flags = []
    action = "WATCH"
    pos_size = "0%"
    time_horizon = "Neutral"

    rsi_threshold = 80 if is_growth_stock else 75
    
    if fund_signal == "SELL" and rsi_val >= rsi_threshold and chip_res['status'] == "Neutral":
        log_warn("觸發鐵律: 估值過高且過熱 -> 強制觀望")
        return {
            "action": "AVOID / WAIT",
            "position_size": "0%",
            "time_horizon": "Wait for Pullback",
            "final_confidence": 0.0,
            "risk_factors": "🔥 估值過高且缺乏籌碼支撐 (Avoid Chasing)",
            "chip_insight": chip_res['reason'],
            "tech_insight": f"RSI={rsi_val:.1f}",
            "backtest_support": f"ROI {roi}%"
        }

    pos_size_cap = 100
    if rsi_val > 80:
        score -= 0.3; risk_flags.append("🔥 技術面嚴重過熱 (RSI>80)"); pos_size_cap = 20
    elif rsi_val > 70:
        risk_flags.append("⚠️ 技術面過熱 (RSI>70)"); pos_size_cap = 50

    if tech_signal == "BUY" and fund_signal == "SELL":
        risk_flags.append("⚔️ 訊號衝突 (技術多/基本空)")
        time_horizon = "Short-term (Speculative)"
        action = "BUY (Speculative)"
        score = min(score, 0.4)
        pos_size_cap = min(pos_size_cap, 30)
    elif tech_signal == "BUY" and fund_signal == "BUY":
        time_horizon = "Mid-Long term"
        action = "STRONG BUY"
    else:
        time_horizon = "Wait & See"

    final_confidence = max(0, min(1, 0.5 + score))
    
    if "Speculative" not in action and "AVOID" not in action:
        if final_confidence >= 0.75: action = "STRONG BUY"
        elif final_confidence >= 0.6: action = "BUY"
        elif final_confidence <= 0.35: action = "SELL"
        else: action = "HOLD / WATCH"

    if "BUY" in action and 65 <= rsi_val < 80:
        action = "BUY ON PULLBACK"
        risk_flags.append("建議等待拉回至 MA20/60 支撐")

    if "BUY" in action:
        suggested = int(final_confidence * 100)
        suggested = min(suggested, pos_size_cap)
        if suggested < 20: pos_size = "10-20% (Test)"
        elif suggested < 50: pos_size = f"{suggested-10}-{suggested}% (Conservative)"
        else: pos_size = f"{suggested-10}-{suggested}% (Aggressive)"
    else:
        pos_size = "0%"

    return {
        "action": action,
        "position_size": pos_size,
        "time_horizon": time_horizon,
        "final_confidence": round(final_confidence, 2),
        "risk_factors": " | ".join(risk_flags) if risk_flags else "None",
        "chip_insight": chip_res['reason'],
        "tech_insight": f"RSI={rsi_val:.1f}",
        "backtest_support": f"ROI {roi}%" if backtest_info else "N/A"
    }

def analyze_single_target(stock_id: str, run_optimization_if_missing: bool = False):
    clean_id = stock_id.split('.')[0]
    backtest_info = None; config = {}
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f: config = json.load(f); 
            if clean_id in config: backtest_info = config[clean_id]
        except: pass
    
    if not backtest_info and run_optimization_if_missing:
        log_info(f"啟動即時回測優化: {clean_id}")
        target_input = f"{clean_id}.TW"
        new_params = find_best_params(target_input)
        if new_params:
            config[clean_id] = new_params
            os.makedirs("data", exist_ok=True)
            with open(CONFIG_FILE, "w") as f: json.dump(config, f, indent=4)
            backtest_info = new_params

    res = fetch_stock_data_smart(stock_id)
    if not res or not res[1] is not None: return None
    source_used, df, fundamentals, correct_ticker = res

    if not fundamentals: fundamentals = {}
    fundamentals["ticker"] = correct_ticker
    stock_name = get_stock_name_zh(correct_ticker)

    tech_strat = MACrossoverStrategy()
    fund_strat = ValuationStrategy()
    tech_res = tech_strat.analyze(df, extra_data=fundamentals).to_dict()
    fund_res = fund_strat.analyze(df, extra_data=fundamentals).to_dict()
    chip_res = analyze_chip(df)
    decision = calculate_final_decision(tech_res, fund_res, chip_res, backtest_info, fundamentals)
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
    timestamp = datetime.now().isoformat()
    if is_single:
        context = json.dumps(data, indent=2, ensure_ascii=False)
        ticker = data['meta']['ticker']
        name = data['meta'].get('name', ticker)
        dec = data['final_decision']
        
        guidance = f"""
### 🚨 決策核心邏輯:
1. **Action**: {dec['action']}。
2. **投資屬性**: {dec['time_horizon']}。
3. **風險警示**: {dec['risk_factors']}。
4. **操作建議**: 若為 PULLBACK，請明確指出觀察均線位置。
"""
    else:
        context = json.dumps(data.get("analysis", {}), indent=2, ensure_ascii=False)
        header = "【BMO 機構級量化決策報告】"
        guidance = ""

    prompt = f"""
【BMO 專業投資評鑑: {name} ({ticker})】
時間: {timestamp}
語言: **繁體中文**
角色: **BMO**

--- 分析指引 ---
{guidance}

請撰寫報告：
1. **📊 綜合評級**: Action / 倉位 / 屬性。
2. **⚖️ 邏輯推演**: 整合技術/基本/籌碼。
3. **⛔ 風險與停損**: 給出具體價位。

[Input Data]
{context}
"""
    return prompt

def main(): pass
if __name__ == "__main__": main()
