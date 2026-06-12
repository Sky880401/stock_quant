# 總經理（thin orchestrator）：只負責把各課串成 !a 分析流程。
# 組織架構與各課職責見 depts/README.md。
# 舊程式碼已依職責搬到 depts/ 各課；本檔保留全部舊名稱轉出口，
# 既有 import（discord_runner / test_architecture / scripts 等）完全不用改。
import sys
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategies.indicators.ma_crossover import MACrossoverStrategy
from strategies.indicators.valuation_strategy import ValuationStrategy
from strategies.indicators.bollinger_strategy import BollingerStrategy
from strategies.indicators.kd_strategy import KDAnalyzer
from strategies.price_action.pullback_strategy import PullbackStrategy
from strategies.indicators.institutional_flow import InstitutionalFlowStrategy
from utils.plotter import generate_stock_chart
from optimizer_runner import find_best_params
from utils.logger import log_info, log_warn, log_error
from strategies.ml_models import create_predictor

# === 各課轉出口（保持舊的 `from main import X` 全部可用）===
from depts.config import TARGET_STOCKS, CONFIG_FILE, PRIMARY_SOURCE, FALLBACK_SOURCE
# 數據搜集課
from depts.data_dept import get_stock_name_zh, fetch_stock_data_smart
# 指標演算法課
from depts.indicator_dept import (analyze_chip, calculate_macd_signal,
                                  calculate_rsi_series, calculate_atr,
                                  calculate_final_decision)
# 回測演算法課
from depts.backtest_dept import calculate_kelly_position, seed_history_predictions
# 風控課
from depts.risk_dept import (inst_avoid_alert, INST_AVOID_P20, INST_AVOID_P10,
                             apply_risk_reward_gate, apply_stat_conflict_note,
                             apply_position_caps)
# 報告產出課
from depts.report_dept import generate_moltbot_prompt


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
        # 美股代號（非純數字）直接用原代號，台股才補 .TW
        target_input = f"{clean_id}.TW" if clean_id.isdigit() else clean_id
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
    inst_strat = InstitutionalFlowStrategy()

    # 執行分析
    tech_res = tech_strat.analyze(df, extra_data=fundamentals).to_dict()
    fund_res = fund_strat.analyze(df, extra_data=fundamentals).to_dict()
    chip_res = analyze_chip(df)
    boll_res = boll_strat.analyze(df)
    kd_res = kd_strat.analyze(df)
    inst_res = inst_strat.analyze(df).to_dict()

    decision = calculate_final_decision(tech_res, fund_res, chip_res, boll_res, kd_res, backtest_info, fundamentals, df, inst_res=inst_res)

    # P2 多源資料：新聞情緒（零 API 成本詞典）+ 融資融券趨勢
    news_res = {}; margin_res = {}
    try:
        from crawlers.market_data import news_sentiment, margin_trend
        news_res = news_sentiment(correct_ticker)
        margin_res = margin_trend(correct_ticker)
    except Exception as e:
        log_info(f"P2 多源資料抓取略過: {e}")

    # P3 機率化獲利空間：用該股歷史 N 日後報酬分佈
    profit_space = {}
    try:
        from utils.profit_space import compute_profit_space
        profit_space = compute_profit_space(df)
    except Exception as e:
        log_info(f"P3 獲利空間計算略過: {e}")

    # 風控課三道閘門（順序不可換：降級 → 分歧註記 → 倉位上限）
    apply_risk_reward_gate(decision, profit_space)
    apply_stat_conflict_note(decision, profit_space)
    try:
        _avoid = inst_avoid_alert(df) or {}
    except Exception:
        _avoid = {}
    apply_position_caps(decision, profit_space, _avoid)

    chart_params = backtest_info.get("params", {}) if backtest_info else {}
    chart_path = generate_stock_chart(stock_name, df, strategy_params=chart_params)
    return {
        "meta": {"source": res["source"], "ticker": correct_ticker, "name": stock_name},
        "price_data": {"latest_close": float(df['Close'].iloc[-1]), "volume": int(df['Volume'].iloc[-1])},
        "strategies": {"Technical": tech_res, "Fundamental": fund_res, "Chip": chip_res, "Institutional": inst_res},
        "sentiment": {"news": news_res, "margin": margin_res},
        "inst_avoid_alert": _avoid,
        "profit_space": profit_space,
        "backtest_insight": backtest_info,
        "final_decision": decision,
        "chart_path": chart_path
    }

def main(): pass
if __name__ == "__main__": main()
