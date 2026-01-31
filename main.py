import sys
import os
import json
import pandas as pd
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
    # (保持原樣，省略)
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
    # (保持原樣，省略)
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
    # (保持原樣，省略)
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

# [核心修改] 根據 backtest_info 的 strategy_type 來調整評分邏輯
def calculate_final_decision(tech_res, fund_res, chip_res, bollinger_res, backtest_info=None, fundamentals=None):
    tech_signal = tech_res.get("signal")
    fund_signal = fund_res.get("signal")
    rsi_val = tech_res.get("raw_data", {}).get("rsi_14", 50)
    pe = fundamentals.get("pe_ratio") if fundamentals else None
    
    # 判斷當前股票是「趨勢型」還是「震盪型」
    strategy_type = backtest_info.get("strategy_type", "Trend (MA)") if backtest_info else "Trend (MA)"
    log_info(f"決策模式: {strategy_type} | Tech={tech_signal}, Fund={fund_signal}, RSI={rsi_val:.1f}")

    score = 0
    
    # === 策略適配邏輯 ===
    if strategy_type == "Reversion (RSI)":
        # 震盪型股票：喜歡低買高賣，對 RSI 訊號加權
        if rsi_val < 35: 
            score += 0.5 
            log_info("RSI 策略觸發: 超賣反彈訊號")
        elif rsi_val > 65: 
            score -= 0.5
            log_info("RSI 策略觸發: 超買回檔訊號")
    else:
        # 趨勢型股票：看均線
        if tech_signal == "BUY": score += 0.4
        elif tech_signal == "SELL": score -= 0.4

    # 基本面 (30%)
    is_growth_stock = False
    if pe and pe > 25 and tech_signal == "BUY" and chip_res['score'] > 0:
        is_growth_stock = True
        fund_signal = "NEUTRAL (Growth)"
        score += 0.1
    
    if fund_signal == "BUY": score += 0.3
    elif fund_signal == "SELL": score -= 0.3
    
    # 籌碼面 (20%)
    if chip_res['score'] > 0: score += 0.2
    elif chip_res['score'] < 0: score -= 0.2
    
    # 回測加分
    roi = backtest_info.get("historical_roi", 0) if backtest_info else 0
    if roi > 30: score += 0.1 # 門檻稍微降低，鼓勵高ROI策略

    risk_flags = []
    action = "WATCH"
    pos_size = "0%"
    time_horizon = "Neutral"

    # 鐵律 (Iron Rule)
    rsi_threshold = 80 if is_growth_stock else 75
    # 如果是震盪型，RSI > 70 就很危險了
    if strategy_type == "Reversion (RSI)": rsi_threshold = 70
    
    if fund_signal == "SELL" and rsi_val >= rsi_threshold and chip_res['status'] == "Neutral":
        return {
            "action": "AVOID / WAIT", "position_size": "0%", "time_horizon": "Wait for Pullback",
            "final_confidence": 0.0, "risk_factors": "🔥 估值過高且過熱 (Iron Rule)", 
            "chip_insight": chip_res['reason'], "tech_insight": f"RSI={rsi_val:.1f}", "backtest_support": f"ROI {roi}% ({strategy_type})"
        }

    # 布林通道風險
    if bollinger_res['signal'] == "SELL":
        score -= 0.2
        risk_flags.append(f"{bollinger_res['reason']}")

    # 決策轉換
    final_confidence = max(0, min(1, 0.5 + score))
    
    if final_confidence >= 0.75: action = "STRONG BUY"
    elif final_confidence >= 0.6: action = "BUY"
    elif final_confidence <= 0.35: action = "SELL"
    else: action = "HOLD / WATCH"

    # 如果是震盪型股票，BUY 建議通常都是短線
    if strategy_type == "Reversion (RSI)" and "BUY" in action:
        time_horizon = "Short-term (Swing Trade)"
        if rsi_val > 50: action = "HOLD" # 震盪股 RSI>50 不追價
    
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
        "tech_insight": f"RSI={rsi_val:.1f} ({strategy_type})",
        "backtest_support": f"ROI {roi}% ({strategy_type})"
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
        log_info(f"啟動策略錦標賽優化: {clean_id}")
        target_input = f"{clean_id}.TW"
        # 這裡會執行 Trend vs RSI 的比賽
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
    
    decision = calculate_final_decision(tech_res, fund_res, chip_res, boll_res, backtest_info, fundamentals)
    
    # 這裡的 params 只取 MA 部分畫圖，如果贏家是 RSI，圖表還是畫 MA 給人看參考
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
### 🚨 BMO 決策邏輯:
1. **策略模式**: {data['backtest_insight'].get('strategy_type', 'Trend')} (AI 判斷此股適合的策略)。
2. **Action**: {dec['action']}。
3. **投資屬性**: {dec['time_horizon']}。
4. **風險警示**: {dec['risk_factors']}。
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
1. **📊 綜合評級**: Action / 倉位。
2. **🧠 AI 策略解讀**: 解釋為何 AI 選擇了這個策略 (例如：因為此股近期震盪，RSI 逆勢策略報酬率較高)。
3. **⛔ 風險與停損**: 給出具體價位。

[Input Data]
{context}
"""
    return prompt

def main(): pass
if __name__ == "__main__": main()
