# ... (保留前面所有 import 和 helper functions: get_stock_name_zh, fetch_stock_data_smart, analyze_chip, calculate_macd_signal, calculate_atr) ...
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
from strategies.kd_strategy import KDAnalyzer
from utils.plotter import generate_stock_chart
from optimizer_runner import find_best_params
from utils.logger import log_info, log_warn, log_error

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
    if 'Foreign' not in df.columns: return {"score": 0, "status": "Neutral", "reason": "無籌碼"}
    df['Foreign'] = df['Foreign'].fillna(0)
    recent = df.tail(5)
    foreign_sum = recent['Foreign'].sum()
    score = 0; status = "Neutral"; reasons = []
    if foreign_sum > 1000: score+=1; reasons.append(f"外資累積買超 {int(foreign_sum/1000)}k"); status="Bullish"
    elif foreign_sum < -1000: score-=1; reasons.append(f"外資累積賣超 {int(abs(foreign_sum)/1000)}k"); status="Bearish"
    else: reasons.append("外資動向不明 (觀望)"); status="Neutral"
    if (df['Close'].iloc[-1] > df['Close'].iloc[-5]) and foreign_sum < 0: reasons.append("⚠️價漲量縮/外資倒貨"); score-=0.5
    return {"score": score, "status": status, "reason": " | ".join(reasons)}

def calculate_macd_signal(df):
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

def calculate_atr(df, period=14):
    try:
        high = df['High']; low = df['Low']; close = df['Close'].shift(1)
        tr = pd.concat([high-low, (high-close).abs(), (low-close).abs()], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean().iloc[-1]
        return atr
    except: return df['Close'].iloc[-1] * 0.03

def calculate_final_decision(tech_res, fund_res, chip_res, bollinger_res, kd_res, backtest_info=None, fundamentals=None, df=None):
    # (保持原樣 V9.1 的決策邏輯，為節省篇幅省略細節，請確保完整複製 V9.1 的代碼)
    # ...
    # 這裡請貼上 V9.1 的 calculate_final_decision 完整代碼
    current_price = df['Close'].iloc[-1]
    tech_signal = tech_res.get("signal")
    fund_signal = fund_res.get("signal")
    rsi_val = tech_res.get("raw_data", {}).get("rsi_14", 50)
    pe = fundamentals.get("pe_ratio") if fundamentals else None
    
    strategy_type = backtest_info.get("strategy_type", "Trend (MA)") if backtest_info else "Trend (MA)"
    macd_status, macd_hist = calculate_macd_signal(df)
    atr = calculate_atr(df)
    atr_pct = (atr / current_price) * 100

    log_info(f"Mode: {strategy_type} | Tech:{tech_signal} RSI:{rsi_val:.1f} ATR:{atr_pct:.1f}%")

    score = 0.5 
    if strategy_type == "Reversion (RSI)":
        if rsi_val <= 30: score += 0.3 
        elif rsi_val >= 70: score -= 0.3 
        elif rsi_val < 45: score += 0.1 
        elif rsi_val > 55: score -= 0.1 
    elif strategy_type == "Momentum (MACD)":
        if "BUY" in macd_status: score += 0.3
        elif "SELL" in macd_status: score -= 0.3
    elif strategy_type == "Swing (KD)":
        if kd_res['signal'] == "BUY": score += 0.3
        elif kd_res['signal'] == "SELL": score -= 0.3
    else: 
        if tech_signal == "BUY": score += 0.3
        elif tech_signal == "SELL": score -= 0.3

    if chip_res['score'] > 0: score += 0.1
    elif chip_res['score'] < 0: score -= 0.1
    
    if fund_signal == "BUY": score += 0.1
    elif fund_signal == "SELL": score -= 0.1

    risk_flags = []
    if bollinger_res['signal'] == "SELL":
        score -= 0.15
        risk_flags.append(bollinger_res['reason'])
    
    if atr_pct > 3.0:
        score -= 0.1 
        risk_flags.append(f"高波動(ATR {atr_pct:.1f}%)")

    action = "HOLD"
    if score >= 0.85: action = "STRONG BUY"
    elif score >= 0.65: action = "BUY"
    elif score >= 0.45: action = "HOLD (Neutral)"
    elif score >= 0.25: action = "REDUCE / UNDERWEIGHT"
    else: action = "EXIT / SELL"

    base_pos = int(score * 100)
    if atr_pct < 2.0: pos_limit = 100
    elif atr_pct < 4.0: pos_limit = 60
    else: pos_limit = 30
    
    final_pos = min(base_pos, pos_limit)
    if final_pos < 10: final_pos = 0 
    
    if action in ["EXIT / SELL", "REDUCE / UNDERWEIGHT"]:
        pos_str = "0-10% (出清/減碼)"
    else:
        pos_str = f"{max(0, final_pos-10)}-{final_pos}%"

    atr_multiplier = 2.0 if atr_pct > 3.0 else 1.5 
    atr_stop = current_price - (atr * atr_multiplier)
    ma_stop = tech_res.get("stop_loss", 0.0)
    
    key_level_desc = "停損價"
    key_level_price = 0.0

    if "BUY" in action or "HOLD" in action:
        if ma_stop >= current_price: 
            key_level_price = current_price - (atr * atr_multiplier)
            key_level_desc = "動態停損 (ATR)"
        else:
            key_level_price = max(ma_stop, current_price - (atr * atr_multiplier))
            key_level_desc = "技術停損"
    else:
        key_level_price = current_price + (atr * atr_multiplier)
        key_level_desc = "趨勢反轉點"

    return {
        "action": action,
        "position_size": pos_str,
        "time_horizon": "Mid-Term",
        "final_confidence": round((100-risk_score)/100, 2) if 'risk_score' in locals() else score, # 修正變數
        "risk_factors": " | ".join(risk_flags) if risk_flags else "Low",
        "chip_insight": chip_res['reason'],
        "tech_insight": f"RSI={rsi_val:.1f}, KD={kd_res['signal']}, MACD={macd_status}",
        "stop_loss_price": round(key_level_price, 2),
        "stop_loss_desc": key_level_desc,
        "atr_pct": round(atr_pct, 1)
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
        log_info(f"啟動 V9.3 策略錦標賽 (Win Rate): {clean_id}")
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
    kd_strat = KDAnalyzer()
    
    tech_res = tech_strat.analyze(df, extra_data=fundamentals).to_dict()
    fund_res = fund_strat.analyze(df, extra_data=fundamentals).to_dict()
    chip_res = analyze_chip(df)
    boll_res = boll_strat.analyze(df)
    kd_res = kd_strat.analyze(df)
    
    decision = calculate_final_decision(tech_res, fund_res, chip_res, boll_res, kd_res, backtest_info, fundamentals, df)
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
        strat = data['backtest_insight'].get('strategy_type', 'Trend')
        # [修改] 使用新的顯示欄位
        win_rate_display = data['backtest_insight'].get('win_rate_display', 'N/A')
        
        # [核心優化] 讓 Prompt 指導 LLM 產生 Highlight
        guidance = f"""
### 🚨 BMO 投資評鑑摘要 (請嚴格依照此數據生成報告，並對重點項目加粗):
1. **策略模型**: {strat} (歷史勝率: {win_rate_display})。
2. **Action**: {dec['action']}。
3. **倉位**: {dec['position_size']} (已考量 ATR {dec['atr_pct']}% 波動)。
4. **{dec['stop_loss_desc']}**: {dec['stop_loss_price']}。
"""
    else:
        context = json.dumps(data.get("analysis", {}), indent=2, ensure_ascii=False)
        header = "【BMO 機構級量化決策報告】"
        guidance = ""

    prompt = f"""
【BMO 專業投資評鑑: {name} ({ticker})】
時間: {timestamp}

--- 分析指引 ---
{guidance}

請撰寫報告，務必在 Discord 輸出時，將以下欄位使用 Markdown 加粗 (**...**) 或 程式碼區塊 (`...`) 強調：
- **Action** (例如: `STRONG BUY`)
- **建議倉位**
- **策略勝率**
- **關鍵價位**

報告結構：
1. **📊 綜合評級**: Action / 倉位 / 勝率。
2. **🧠 決策邏輯**: 
   - 說明 AI 選擇 {data['backtest_insight'].get('strategy_type')} 的原因。
   - 解讀目前技術指標狀態。
3. **⛔ 風險管理**: 
   - 波動率風險提示。
   - 關鍵價位說明。

[Input Data]
{context}
"""
    return prompt

def main(): pass
if __name__ == "__main__": main()
