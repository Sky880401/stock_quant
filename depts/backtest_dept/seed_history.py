# 回測演算法課：歷史補考（原 main.py 的 seed_history_predictions，邏輯原樣搬入）
import os
import json

from strategies.indicators.ma_crossover import MACrossoverStrategy
from strategies.indicators.valuation_strategy import ValuationStrategy
from strategies.indicators.bollinger_strategy import BollingerStrategy
from strategies.indicators.kd_strategy import KDAnalyzer
from strategies.indicators.institutional_flow import InstitutionalFlowStrategy

from depts.config import CONFIG_FILE
from depts.data_dept import get_stock_name_zh, fetch_stock_data_smart
# 注意:指標課的 import 放在函式內做延遲載入——
# 因指標課 decision.py 需要本課的 kelly,在模組頂層互相 import 會循環。


def seed_history_predictions(stock_id, horizon=20, step=10, max_anchors=20):
    """用歷史資料補考：倒帶到過去各時點，只用當時以前資料算決策，
    再跟 horizon 個交易日後的真實價對標，直接寫入已結算預測（補 P1 資料）。

    回傳寫入筆數。注意：訊號為點位內樣本外（不偷看未來價），但 strategy_type
    沿用目前設定，屬半時光機，僅供快速校準。
    """
    from utils.prediction_log import log_closed
    from depts.indicator_dept import analyze_chip, calculate_final_decision  # 延遲載入避免循環
    res = fetch_stock_data_smart(stock_id)
    if res.get("status") == "error":
        return 0
    df = res["df"]; fundamentals = res.get("fundamentals") or {}
    correct_ticker = res["ticker"]; fundamentals["ticker"] = correct_ticker
    name = get_stock_name_zh(correct_ticker)

    clean_id = correct_ticker.split('.')[0]
    backtest_info = None
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f: cfg = json.load(f)
            backtest_info = cfg.get(clean_id)
        except Exception: pass

    tech_s, fund_s = MACrossoverStrategy(), ValuationStrategy()
    boll_s, kd_s, inst_s = BollingerStrategy(), KDAnalyzer(), InstitutionalFlowStrategy()

    n = len(df); written = 0
    # 由最近可結算的時點往回取樣（需留 horizon 天才有未來價可比）
    anchors = list(range(n - horizon - 1, 199, -step))[:max_anchors]
    for i in anchors:
        sub = df.iloc[:i + 1]
        if len(sub) < 200:
            continue
        try:
            tech_r = tech_s.analyze(sub, extra_data=fundamentals).to_dict()
            fund_r = fund_s.analyze(sub, extra_data=fundamentals).to_dict()
            chip_r = analyze_chip(sub)
            boll_r = boll_s.analyze(sub)
            kd_r = kd_s.analyze(sub)
            inst_r = inst_s.analyze(sub).to_dict()
            dec = calculate_final_decision(tech_r, fund_r, chip_r, boll_r, kd_r,
                                           backtest_info, fundamentals, sub, inst_res=inst_r)
        except Exception:
            continue
        entry = float(df['Close'].iloc[i])
        actual = float(df['Close'].iloc[i + horizon])
        ts = df.index[i].strftime("%Y-%m-%d %H:%M:%S")
        strat = (backtest_info or {}).get("strategy_type", "Trend (MA)")
        if log_closed(correct_ticker, name, dec["action"], dec.get("final_confidence"),
                      strat, entry, actual, ts=ts, horizon_days=horizon):
            written += 1
    return written
