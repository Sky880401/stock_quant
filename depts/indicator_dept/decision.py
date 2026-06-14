# 指標演算法課：綜合計分決策（原 main.py 的 calculate_final_decision，邏輯原樣搬入）
# 計分匯總各指標訊號 → Action；倉位由回測演算法課的 Kelly 提供。
import pandas as pd

from utils.logger import log_info, log_warn
from strategies.ml_models import create_predictor
from depts.backtest_dept.kelly import calculate_kelly_position
from .technical import calculate_macd_signal, calculate_rsi_series, calculate_atr


def calculate_final_decision(tech_res, fund_res, chip_res, bollinger_res, kd_res, backtest_info=None, fundamentals=None, df=None, inst_res=None):
    current_price = df['Close'].iloc[-1]
    # ... (變數初始化) ...
    tech_signal = tech_res.get("signal")
    fund_signal = fund_res.get("signal")
    rsi_val = tech_res.get("raw_data", {}).get("rsi_14", 50)
    pe = fundamentals.get("pe_ratio") if fundamentals else None

    strategy_type = backtest_info.get("strategy_type", "Trend (MA)") if backtest_info else "Trend (MA)"
    win_rate = backtest_info.get("win_rate", 0) if backtest_info else 0
    macd_status, macd_hist = calculate_macd_signal(df)
    # [使用者反饋] RSI 反應太快易誤判 → 對 RSI 序列做短期 EMA 平滑去抖動，
    # 用平滑後的值來觸發 Reversion 計分；rsi_val(原始) 仍保留供 tech_insight 回報。
    rsi_eff = rsi_val
    _rsi_series = calculate_rsi_series(df)
    if _rsi_series is not None and len(_rsi_series.dropna()) >= 3:
        _rsi_smooth = _rsi_series.ewm(span=3, adjust=False).mean().iloc[-1]
        if pd.notna(_rsi_smooth):
            rsi_eff = float(_rsi_smooth)
    atr = calculate_atr(df)
    # ATR 可能為 NaN（High/Low 有缺值時 rolling 均值為 NaN），會讓 atr_pct、停損價一路變成 nan
    # 顯示給使用者。退回「現價 3%」當保守波動估計，與 calculate_atr 例外分支的 fallback 一致。
    if pd.isna(atr):
        atr = current_price * 0.03
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

    # [P4 動態權重] 依該策略 P1 累積的真實命中率調整技術面話語權
    # （樣本不足時 multiplier=1.0，隨 P1 結算自動生效）
    try:
        from utils.strategy_weights import get_strategy_multiplier
        p4_mult, p4_src = get_strategy_multiplier(strategy_type)
        tech_weight *= p4_mult
    except Exception:
        p4_mult, p4_src = 1.0, "預設"

    # [策略計分區塊 - 動態權重版本]
    score_before_tech = score  # 記錄技術面計分前的分數，供 RSI 閘門削減用
    if strategy_type == "Reversion (RSI)":
        # 順勢均值回歸：多頭買回檔、空頭賣反彈，不逆勢對作（這是原本命中率低的主因）
        ma200_now = df['Close'].rolling(200).mean().iloc[-1]
        in_uptrend = current_price > ma200_now if pd.notna(ma200_now) else True
        if in_uptrend:
            # 多頭：超賣是買點；不因超買而做空（順勢續抱）
            if rsi_eff <= 40: score += tech_weight
            elif rsi_eff <= 50: score += tech_weight * 0.3
            elif rsi_eff >= 82: score -= tech_weight * 0.3   # 僅極端過熱才略減
        else:
            # 空頭：反彈是賣點；不因超賣而抄底（接刀）
            if rsi_eff >= 60: score -= tech_weight
            elif rsi_eff >= 50: score -= tech_weight * 0.3
            elif rsi_eff <= 18: score += tech_weight * 0.3   # 僅極端超跌才略加
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

    # [使用者反饋] RSI 反應太快易誤判 → 把 KD/MACD 從「小幅加分」改成「閘門/否決」。
    # 僅當主訊號來自 RSI 時介入：MACD 與 KD 兩個慢速指標都與 RSI 訊號反向 → 否決(大幅削減)；
    # 至少一個慢指標同向 → 放行，維持原 tech_weight 分數。
    # 主策略本身就是 Momentum(MACD) / Swing(KD) 時不重複計分；Trend / PriceAction 不介入。
    macd_dir = 1 if "BUY" in macd_status else (-1 if "SELL" in macd_status else 0)
    kd_dir = 1 if kd_res['signal'] == "BUY" else (-1 if kd_res['signal'] == "SELL" else 0)
    if strategy_type == "Reversion (RSI)":
        tech_delta = score - score_before_tech
        rsi_dir = 1 if tech_delta > 0 else (-1 if tech_delta < 0 else 0)
        if rsi_dir != 0:
            both_oppose = (macd_dir == -rsi_dir) and (kd_dir == -rsi_dir)
            if both_oppose:
                # 兩個慢速指標一致反向 → 否決，技術分削減為 0.2 倍
                score = score_before_tech + tech_delta * 0.2
                log_info(f"RSI 閘門否決：MACD/KD 皆反向，技術分削減 (rsi_dir={rsi_dir})")

    if chip_res['score'] > 0: score += chip_weight
    elif chip_res['score'] < 0: score -= chip_weight
    if fund_signal == "BUY": score += fund_weight
    elif fund_signal == "SELL": score -= fund_weight

    # [新增] 法人籌碼動能策略（用 confidence 調節強度，併入籌碼面權重）
    if inst_res:
        inst_w = 0.12
        if inst_res.get("signal") == "BUY":
            score += inst_w * max(0.4, inst_res.get("confidence", 0.5))
        elif inst_res.get("signal") == "SELL":
            score -= inst_w * max(0.4, inst_res.get("confidence", 0.5))

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
    base_kelly_position = 100  # 以「佔總資金 %」為單位（quarter-Kelly 內已含單檔上限）

    # 從backtest_info提取平均贏損比
    avg_win_ratio = backtest_info.get("avg_win_ratio", 1.5) if backtest_info else 1.5
    avg_loss_ratio = backtest_info.get("avg_loss_ratio", 1.0) if backtest_info else 1.0

    # [P4] Kelly 倉位優先用 P1 實測命中率（樣本足夠時），否則退回回測勝率
    kelly_wr = win_rate / 100 if win_rate > 1 else win_rate
    wr_source = f"回測{kelly_wr*100:.1f}%"
    try:
        from utils.strategy_weights import get_hit_rate
        p1_rate, p1_n = get_hit_rate(strategy_type)
        if p1_rate is not None:
            kelly_wr = p1_rate / 100.0
            wr_source = f"P1實測{p1_rate}%({p1_n}筆)"
    except Exception:
        pass

    # 計算Kelly建議頭寸
    kelly_position = calculate_kelly_position(kelly_wr, avg_win_ratio, avg_loss_ratio, base_kelly_position)

    # 根據ATR調整Kelly頭寸
    if atr_pct < 2.0: atm_limit = 1.0  # 低波動可用滿Kelly
    elif atr_pct < 3.0: atm_limit = 0.8
    elif atr_pct < 4.0: atm_limit = 0.6
    else: atm_limit = 0.3  # 高波動大幅降低

    final_pos = int(round(kelly_position * atm_limit))
    # 中性(HOLD)時減半，明確看多才給足 Kelly 建議
    if action == "HOLD (Neutral)":
        final_pos = int(final_pos * 0.5)

    if action in ["EXIT / SELL", "REDUCE / UNDERWEIGHT"]:
        pos_str = "0% (出清/減碼)"
    elif final_pos <= 0:
        pos_str = "0-2% (訊號不足，觀望)"
    else:
        low = max(0, int(round(final_pos * 0.6)))
        pos_str = f"{final_pos}%" if low >= final_pos else f"{low}-{final_pos}%"

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
        "final_confidence": round(max(0.0, min(score, 1.0)), 2),  # audit 修正:不再引用殘留的 risk_score,夾在 0~1
        "risk_factors": " | ".join(risk_flags) if risk_flags else "Low",
        "chip_insight": chip_res['reason'],
        "inst_insight": (inst_res or {}).get('reason', ''),
        "tech_insight": f"RSI={rsi_val:.1f}, KD={kd_res['signal']}, MACD={macd_status}",
        "p4_weight": f"{p4_mult:.2f}x ({p4_src})",
        "position_basis": f"倉位勝率來源：{wr_source}",
        # [修改] 強制四捨五入到小數點第二位
        "stop_loss_price": round(key_level_price, 2),
        "stop_loss_desc": key_level_desc,
        "atr_pct": round(atr_pct, 1),
        "win_rate": win_rate
    }
