import sys
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.data_loader import get_data_provider
from strategies.ma_crossover import MACrossoverStrategy
from strategies.valuation_strategy import ValuationStrategy
from strategies.bollinger_strategy import BollingerStrategy
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
    # (保持原樣)
    log_info(f"正在獲取數據: {stock_id} ...")
    clean_id = stock_id.split('.')[0]
    candidates = [f"{clean_id}.TWO", f"{clean_id}.TW"] if "TWO" in stock_id else [f"{clean_id}.TW", f"{clean_id}.TWO"]
    if not clean_id.isdigit(): candidates = [stock_id]
    last_error = "未知"
    for current_id in candidates:
        provider = get_data_provider(PRIMARY_SOURCE)
        try:
            df = provider.get_history(clean_id)
            if df.empty or len(df) < 60:
                yf_provider = get_data_provider(FALLBACK_SOURCE)
                df = yf_provider.get_history(current_id)
            if df.empty: last_error = "查無數據"; continue
            if len(df) < 60: last_error = "數據不足"; continue
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
            log_info(f"數據獲取成功: {current_id}")
            return {"status": "success", "source": "Hybrid", "df": df, "fundamentals": fundamentals, "ticker": current_id}
        except Exception as e: last_error = str(e); continue
    return {"status": "error", "reason": last_error}

def analyze_chip(df):
    # (保持原樣)
    if 'Foreign' not in df.columns: return {"score": 0, "status": "Neutral", "reason": "無籌碼"}
    df['Foreign'] = df['Foreign'].fillna(0)
    recent = df.tail(5)
    foreign_sum = recent['Foreign'].sum()
    score = 0; status = "Neutral"; reasons = []
    if foreign_sum > 1000: score+=1; reasons.append(f"外資買超 {int(foreign_sum/1000)}k"); status="Bullish"
    elif foreign_sum < -1000: score-=1; reasons.append(f"外資賣超 {int(abs(foreign_sum)/1000)}k"); status="Bearish"
    else: reasons.append("外資觀望"); status="Neutral"
    if (df['Close'].iloc[-1] > df['Close'].iloc[-5]) and foreign_sum < 0: reasons.append("⚠️價漲量縮/外資倒貨"); score-=0.5
    return {"score": score, "status": status, "reason": " | ".join(reasons)}

def calculate_macd_signal(df):
    # (保持原樣)
    try:
        exp12 = df['Close'].ewm(span=12, adjust=False).mean()
        exp26 = df['Close'].ewm(span=26, adjust=False).mean()
        macd = exp12 - exp26
        signal = macd.ewm(span=9, adjust=False).mean()
        curr_macd = macd.iloc[-1]; curr_sig = signal.iloc[-1]
        prev_macd = macd.iloc[-2]; prev_sig = signal.iloc[-2]
        status = "NEUTRAL"
        if curr_macd > curr_sig: status = "BUY" if prev_macd <= prev_sig else "HOLD BUY"
        elif curr_macd < curr_sig: status = "SELL" if prev_macd >= prev_sig else "HOLD SELL"
        return status, curr_macd - curr_sig
    except: return "NEUTRAL", 0.0

# [核心修改] 加入 current_price 並修正停損邏輯
def calculate_final_decision(tech_res, fund_res, chip_res, bollinger_res, backtest_info=None, fundamentals=None, df=None):
    current_price = df['Close'].iloc[-1]
    tech_signal = tech_res.get("signal")
    fund_signal = fund_res.get("signal")
    rsi_val = tech_res.get("raw_data", {}).get("rsi_14", 50)
    pe = fundamentals.get("pe_ratio") if fundamentals else None
    strategy_type = backtest_info.get("strategy_type", "Trend (MA)") if backtest_info else "Trend (MA)"
    macd_status, macd_hist = calculate_macd_signal(df)

    log_info(f"模式: {strategy_type} | Price={current_price:.2f} | Tech={tech_signal}, RSI={rsi_val:.1f}")

    score = 0
    # 策略適配
    if strategy_type == "Reversion (RSI)":
        if rsi_val < 35: score += 0.5 
        elif rsi_val > 65: score -= 0.5
    elif strategy_type == "Momentum (MACD)":
        if "BUY" in macd_status: score += 0.5
        elif "SELL" in macd_status: score -= 0.5
    else:
        if tech_signal == "BUY": score += 0.4
        elif tech_signal == "SELL": score -= 0.4

    # 基本面與籌碼
    is_growth_stock = False
    if pe and pe > 25 and tech_signal == "BUY" and chip_res['score'] > 0:
        is_growth_stock = True; fund_signal = "NEUTRAL (Growth)"; score += 0.1
    if fund_signal == "BUY": score += 0.3
    elif fund_signal == "SELL": score -= 0.3
    if chip_res['score'] > 0: score += 0.2
    elif chip_res['score'] < 0: score -= 0.2
    roi = backtest_info.get("historical_roi", 0) if backtest_info else 0
    if roi > 30: score += 0.1

    risk_flags = []; action = "WATCH"; time_horizon = "Neutral"
    
    # 鐵律
    rsi_threshold = 80 if is_growth_stock else 75
    if strategy_type == "Reversion (RSI)": rsi_threshold = 70
    if fund_signal == "SELL" and rsi_val >= rsi_threshold and chip_res['status'] == "Neutral":
        return {
            "action": "AVOID / WAIT", "position_size": "0%", "time_horizon": "Wait for Pullback",
            "final_confidence": 0.0, "risk_factors": "🔥 估值過高且過熱 (Iron Rule)", 
            "chip_insight": chip_res['reason'], "tech_insight": f"RSI={rsi_val:.1f}", "backtest_support": f"ROI {roi}%",
            "stop_loss_price": "N/A"
        }

    if bollinger_res['signal'] == "SELL":
        score -= 0.2
        risk_flags.append(bollinger_res['reason'])

    final_confidence = max(0, min(1, 0.5 + score))
    if final_confidence >= 0.75: action = "STRONG BUY"
    elif final_confidence >= 0.6: action = "BUY"
    elif final_confidence <= 0.35: action = "SELL"
    else: action = "HOLD / WATCH"

    # 時間屬性
    if strategy_type == "Reversion (RSI)" and "BUY" in action: time_horizon = "Short-term (Swing)"
    elif strategy_type == "Momentum (MACD)" and "BUY" in action: time_horizon = "Mid-term (Trend Start)"
    elif "BUY" in action: time_horizon = "Mid-Long term"

    # [關鍵修正] 智慧停損計算 (Smart Stop Loss)
    # 預設停損來自技術面 (通常是均線)
    raw_stop_loss = tech_res.get("stop_loss", 0.0)
    
    # 1. 如果是 BUY，但停損價 >= 現價 (這是 User 遇到的 Bug)
    # 這代表均線在頭上 (空頭排列)，不能當停損
    if "BUY" in action and raw_stop_loss >= current_price:
        # 改用近期低點 (Recent Low) 或 布林下軌 作為停損
        # 這裡簡單用 Current Price * 0.9 (10% 停損) 或 前波低點估算
        # 更精準的做法是找 df['Low'].tail(20).min()
        recent_low = df['Low'].tail(10).min()
        if recent_low < current_price:
            stop_loss_price = recent_low * 0.98 # 低點再往下 2%
            risk_flags.append("停損設為近期低點 (均線為壓力)")
        else:
            stop_loss_price = current_price * 0.9 # 強制 10%
    else:
        stop_loss_price = raw_stop_loss

    # 2. 如果是 SELL，停損價應該在現價之上 (停利/回補點)
    if "SELL" in action and stop_loss_price <= current_price:
        stop_loss_price = current_price * 1.05 # 強制 5% 停損

    if "BUY" in action:
        suggested = int(final_confidence * 100)
        pos_size = f"{max(0, suggested-20)}-{suggested}%"
    else:
        pos_size = "0%"

    return {
        "action": action,
        "position_size": pos_size,
        "time_horizon": time_horizon,
        "final_confidence": round(final_confidence, 2),
        "risk_factors": " | ".join(risk_flags) if risk_flags else "None",
        "chip_insight": chip_res['reason'],
        "tech_insight": f"RSI={rsi_val:.1f}, MACD={macd_status} ({strategy_type})",
        "backtest_support": f"ROI {roi}% ({strategy_type})",
        "stop_loss_price": round(stop_loss_price, 2)
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
        log_info(f"啟動策略錦標賽 (MA/RSI/MACD): {clean_id}")
        target_input = f"{clean_id}.TW"
        new_params = find_best_params(target_input)
        if new_params:
            config[clean_id] = new_params
            os.makedirs("data", exist_ok=True)
            with open(CONFIG_FILE, "w") as f: json.dump(config, f, indent=4)
            backtest_info = new_params
    res = fetch_stock_data_smart(stock_id)
    if res["status"] == "error": return {"error": res["reason"]}
    df = res["df"]; fundamentals = res["fundamentals"]; correct_ticker = res["ticker"]
    if not fundamentals: fundamentals = {}
    fundamentals["ticker"] = correct_ticker
    stock_name = get_stock_name_zh(correct_ticker)
    tech_strat = MACrossoverStrategy()
    fund_strat = ValuationStrategy()
    boll_strat = BollingerStrategy()
    tech_res = tech_strat.analyze(df, extra_data=fundamentals).to_dict()
    fund_res = fund_strat.analyze(df, extra_data=fundamentals).to_dict()
    chip_res = analyze_chip(df)
    boll_res = boll_strat.analyze(df)
    # [修正] 傳入 df
    decision = calculate_final_decision(tech_res, fund_res, chip_res, boll_res, backtest_info, fundamentals, df)
    chart_params = backtest_info.get("params", {}) if backtest_info else {}
    chart_path = generate_stock_chart(stock_name, df, strategy_params=chart_params)
    return {
        "meta": {"source": res["source"], "ticker": correct_ticker, "name": stock_name},
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
### 🚨 BMO 決策摘要:
1. **策略模式**: {data['backtest_insight'].get('strategy_type', 'Trend')}。
2. **Action**: {dec['action']}。
3. **停損價**: {dec['stop_loss_price']} (請解釋此價位的意義，若為支撐位請說明)。
4. **風險**: {dec['risk_factors']}。
"""
    else:
        context = json.dumps(data.get("analysis", {}), indent=2, ensure_ascii=False)
        header = "【BMO 機構級量化決策報告】"
        guidance = ""

    prompt = f"""
【BMO 專業投資評鑑: {name} ({ticker})】
時間: {timestamp}
(直接輸出內容，不複誦設定)

--- 分析指引 ---
{guidance}

請撰寫報告：
1. **📊 綜合評級**: Action / 倉位 / 策略類型。
2. **🧠 策略邏輯**: 針對該策略 (MA/RSI/MACD) 進行現況解讀。
3. **⛔ 風險與停損**: 明確指出停損價，並提醒如果跌破該價位代表什麼意義。

[Input Data]
{context}
"""
    return prompt

def main(): pass
if __name__ == "__main__": main()
