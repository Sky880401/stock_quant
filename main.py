# ... (Imports 保持原樣，請複製 V10.0 的 imports) ...
import sys
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.data_loader import get_data_provider
from strategies.indicators.ma_crossover import MACrossoverStrategy
from strategies.indicators.valuation_strategy import ValuationStrategy
from strategies.indicators.bollinger_strategy import BollingerStrategy
from strategies.indicators.kd_strategy import KDAnalyzer
from strategies.price_action.pullback_strategy import PullbackStrategy
from utils.plotter import generate_stock_chart
from optimizer_runner import find_best_params
from utils.logger import log_info, log_warn, log_error
from strategies.ml_models import create_predictor

# ... (Helper functions 保持原樣) ...
# ... get_stock_name_zh, fetch_stock_data_smart, analyze_chip, calculate_macd_signal, calculate_atr ...
# 為了節省篇幅，請保留這些函數的原始碼
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
    else: reasons.append("外資觀望"); status="Neutral"
    if (df['Close'].iloc[-1] > df['Close'].iloc[-5]) and foreign_sum < 0: reasons.append("⚠️價漲量縮"); score-=0.5
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

def calculate_kelly_position(win_rate, avg_win_ratio, avg_loss_ratio, max_position=100):
    """
    Kelly準則資金管理：kelly_fraction = (p * b - q) / b
    其中: p=勝率, b=贏損比, q=敗率(1-p)
    使用Kelly的25% (四分之一Kelly) 保守策略
    """
    if win_rate <= 0 or win_rate >= 1:
        return max_position * 0.5
    if avg_win_ratio <= 0 or avg_loss_ratio <= 0:
        return max_position * 0.5
    
    loss_rate = 1.0 - win_rate
    b = avg_win_ratio / avg_loss_ratio
    kelly_fraction = (win_rate * b - loss_rate) / b
    kelly_fraction = max(0, min(kelly_fraction, 0.25))
    conservative_kelly = kelly_fraction * 0.25
    kelly_position = conservative_kelly * max_position
    return max(5, min(kelly_position, max_position))

def calculate_final_decision(tech_res, fund_res, chip_res, bollinger_res, kd_res, backtest_info=None, fundamentals=None, df=None):
    current_price = df['Close'].iloc[-1]
    # ... (變數初始化) ...
    tech_signal = tech_res.get("signal")
    fund_signal = fund_res.get("signal")
    rsi_val = tech_res.get("raw_data", {}).get("rsi_14", 50)
    pe = fundamentals.get("pe_ratio") if fundamentals else None
    
    strategy_type = backtest_info.get("strategy_type", "Trend (MA)") if backtest_info else "Trend (MA)"
    win_rate = backtest_info.get("win_rate", 0) if backtest_info else 0
    macd_status, macd_hist = calculate_macd_signal(df)
    atr = calculate_atr(df)
    atr_pct = (atr / current_price) * 100

    log_info(f"Mode: {strategy_type} | Tech:{tech_signal} RSI:{rsi_val:.1f} ATR:{atr_pct:.1f}%")

    score = 0.5 
    
    # [優化] 根據市場狀態動態調整信號權重
    # 基礎權重
    tech_weight = 0.3      # 技術面權重
    chip_weight = 0.1      # 籌碼面權重
    fund_weight = 0.1      # 基本面權重
    
    # 根據波動率調整
    if atr_pct > 4.0:
        # 高波動時：重視超買超賣信號
        if strategy_type == "Reversion (RSI)":
            tech_weight = 0.4
        chip_weight = 0.15
        fund_weight = 0.05
    elif atr_pct < 1.5:
        # 低波動時：增加基本面比重
        tech_weight = 0.25
        fund_weight = 0.15
        chip_weight = 0.1
    
    # [策略計分區塊 - 動態權重版本]
    if strategy_type == "Reversion (RSI)":
        if rsi_val <= 30: score += tech_weight
        elif rsi_val >= 70: score -= tech_weight
        elif rsi_val < 45: score += tech_weight * 0.3
        elif rsi_val > 55: score -= tech_weight * 0.3
    elif strategy_type == "Momentum (MACD)":
        if "BUY" in macd_status: score += tech_weight
        elif "SELL" in macd_status: score -= tech_weight
    elif strategy_type == "Swing (KD)":
        if kd_res['signal'] == "BUY": score += tech_weight
        elif kd_res['signal'] == "SELL": score -= tech_weight
    elif strategy_type == "PriceAction (Pullback)":
        ma20 = df['Close'].rolling(20).mean().iloc[-1]
        dist = (current_price - ma20) / ma20
        is_red_k = df['Close'].iloc[-1] > df['Open'].iloc[-1]
        if abs(dist) < 0.02 and is_red_k: score += tech_weight * 1.3
        elif dist < -0.05: score -= tech_weight

    else: # Trend
        if tech_signal == "BUY": score += tech_weight
        elif tech_signal == "SELL": score -= tech_weight

    if chip_res['score'] > 0: score += chip_weight
    elif chip_res['score'] < 0: score -= chip_weight
    if fund_signal == "BUY": score += fund_weight
    elif fund_signal == "SELL": score -= fund_weight

    # [新增] 混合预测模型辅助信号
    try:
        predictor = create_predictor('adaptive')
        ml_result = predictor.predict(df)
        ml_action = ml_result.get('action', 'HOLD')
        ml_confidence = ml_result.get('confidence', 0.0)
        
        # ML信号权重(10%)
        ml_weight = 0.1
        if ml_action == "BUY" and ml_confidence > 0.6:
            score += ml_weight * min(ml_confidence, 1.0)
            log_info(f"ML辅助信号: BUY (置信度{ml_confidence:.2f})")
        elif ml_action == "SELL" and ml_confidence > 0.6:
            score -= ml_weight * min(ml_confidence, 1.0)
            log_info(f"ML辅助信号: SELL (置信度{ml_confidence:.2f})")
        else:
            log_info(f"ML辅助信号: {ml_action} (置信度{ml_confidence:.2f})")
    except Exception as e:
        log_warn(f"ML模型调用失败: {str(e)}")

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

    # [優化] 使用Kelly準則計算頭寸，結合ATR波動率限制
    base_kelly_position = 50  # Kelly基礎頭寸
    
    # 從backtest_info提取平均贏損比
    avg_win_ratio = backtest_info.get("avg_win_ratio", 1.5) if backtest_info else 1.5
    avg_loss_ratio = backtest_info.get("avg_loss_ratio", 1.0) if backtest_info else 1.0
    
    # 計算Kelly建議頭寸
    kelly_position = calculate_kelly_position(win_rate / 100 if win_rate > 1 else win_rate, 
                                             avg_win_ratio, avg_loss_ratio, base_kelly_position)
    
    # 根據ATR調整Kelly頭寸
    if atr_pct < 2.0: atm_limit = 1.0  # 低波動可用滿Kelly
    elif atr_pct < 3.0: atm_limit = 0.8
    elif atr_pct < 4.0: atm_limit = 0.6
    else: atm_limit = 0.3  # 高波動大幅降低
    
    final_pos = int(kelly_position * atm_limit)
    if final_pos < 10 and "BUY" in action: final_pos = 10
    elif "EXIT" in action or "REDUCE" in action: final_pos = 0 
    
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
        if strategy_type == "PriceAction (Pullback)":
            key_level_price = current_price * 0.95
            key_level_desc = "嚴格停損 (5%)"
        elif ma_stop >= current_price: 
            key_level_price = atr_stop
            key_level_desc = "動態停損 (ATR)"
        else:
            key_level_price = max(ma_stop, atr_stop)
            key_level_desc = "技術停損"
    else:
        key_level_price = current_price + (atr * atr_multiplier)
        key_level_desc = "趨勢反轉點"

    return {
        "action": action,
        "position_size": pos_str,
        "time_horizon": "Mid-Term",
        "final_confidence": round((100-risk_score)/100, 2) if 'risk_score' in locals() else score,
        "risk_factors": " | ".join(risk_flags) if risk_flags else "Low",
        "chip_insight": chip_res['reason'],
        "tech_insight": f"RSI={rsi_val:.1f}, KD={kd_res['signal']}, MACD={macd_status}",
        # [修改] 強制四捨五入到小數點第二位
        "stop_loss_price": round(key_level_price, 2),
        "stop_loss_desc": key_level_desc,
        "atr_pct": round(atr_pct, 1),
        "win_rate": win_rate
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
        log_info(f"啟動 V10.1 策略錦標賽 (UI Polish): {clean_id}")
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
    
    # 載入所有策略模組
    tech_strat = MACrossoverStrategy()
    fund_strat = ValuationStrategy()
    boll_strat = BollingerStrategy()
    kd_strat = KDAnalyzer()
    
    # 執行分析
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
        win_rate = data['backtest_insight'].get('win_rate_display', 'N/A')
        
        logic_desc = "順勢操作"
        if strat == "Reversion (RSI)": logic_desc = "逆勢乖離操作"
        if strat == "Swing (KD)": logic_desc = "短線轉折操作"
        if strat == "PriceAction (Pullback)": logic_desc = "回後上漲操作 (型態學)"
        
        # [核心優化] 強制策略模型顯示在第一段，且格式化為 Bullet Point
        guidance = f"""
### 🚨 BMO 投資評鑑摘要 (請務必依照此格式輸出報告):
1. **綜合評級區塊** (必須包含以下四點):
   - **Action**: {dec['action']}
   - **建議倉位**: {dec['position_size']} (已考慮波動率)
   - **策略模型**: {strat} (勝率: {win_rate})
   - **{dec['stop_loss_desc']}**: {dec['stop_loss_price']}

2. **詳細邏輯區塊**:
   - 策略適配原因: {logic_desc}
   - 指標解讀: {dec['tech_insight']}
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

請撰寫報告，結構如下：
1. **📊 綜合評級**: 
   - 請列點顯示 Action、倉位、**策略模型** (這是使用者最關心的，請務必列出)、關鍵價位。
2. **🧠 決策邏輯**: 
   - 解釋為何選擇 {data['backtest_insight'].get('strategy_type')}。
   - 分析目前技術面多空。
3. **⛔ 風險管理**: 
   - 說明波動率風險與價位防守邏輯。

[Input Data]
{context}
"""
    return prompt

def main(): pass
if __name__ == "__main__": main()
