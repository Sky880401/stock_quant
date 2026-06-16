# 風控課：三道閘門（原 main.py analyze_single_target 內的三段 try 區塊，邏輯原樣搬入）
# 共同原則：只降級/註記/壓上限，不翻轉訊號；全部 in-place 修改 decision dict。


def apply_risk_reward_gate(decision, profit_space):
    """風險報酬閘門:技術面 Action 與機率化獲利空間打架時降級,並留下說明欄位"""
    try:
        ps = profit_space or {}
        if (not ps.get("insufficient")) and ps.get("samples") and "BUY" in str(decision.get("action", "")):
            prob_up = ps.get("prob_up")
            exp_ret = ps.get("expected_return")
            downside = abs(ps.get("downside") or 0)
            bad_odds = ((prob_up is not None and prob_up < 50)
                        or (exp_ret is not None and exp_ret <= 0)
                        or (downside > 0 and exp_ret is not None and exp_ret < 0.4 * downside))
            if bad_odds:
                decision["risk_reward_downgrade"] = (
                    f"技術面原始訊號為 {decision['action']},但機率化獲利空間不支持:"
                    f"20日上漲機率 {prob_up}%、期望報酬 {exp_ret}% 對下檔 {ps.get('downside')}%"
                    f",風險報酬比不足,故降級為 HOLD。")
                decision["action"] = "HOLD (Neutral)"
                decision["position_size"] = "0-2% (風險報酬不佳,降級)"
    except Exception:
        pass


def apply_stat_conflict_note(decision, profit_space):
    """反向檢核:減碼/出場訊號但統計分佈強烈偏多 → 註記分歧(不翻轉訊號,風控優先;
    錯誤的BUY賠真錢、錯誤的REDUCE只少賺,維持不對稱處理)"""
    try:
        ps = profit_space or {}
        act = str(decision.get("action", ""))
        if (not ps.get("insufficient")) and ps.get("samples") and \
           ("REDUCE" in act or "SELL" in act or "EXIT" in act):
            prob_up = ps.get("prob_up")
            exp_ret = ps.get("expected_return")
            downside = abs(ps.get("downside") or 0)
            if prob_up is not None and exp_ret is not None \
               and prob_up >= 60 and exp_ret >= 0.4 * downside:
                note = (f"訊號分歧:技術/籌碼面給出 {act},但該股歷史20日報酬分佈偏多"
                        f"(上漲機率 {prob_up}%、期望報酬 {exp_ret}%)。")
                # 上漲機率強烈偏多(>=65%)→不再硬留賣出/減碼與自家多頭預測打架,降級為觀望
                # (仍不翻成 BUY,維持不對稱:錯誤BUY賠真錢、錯誤觀望只少賺)
                if prob_up >= 65:
                    decision["action"] = "HOLD (Neutral)"
                    decision["position_size"] = "0-2% (訊號分歧,降級觀望)"
                    note += "因上漲機率偏高,已將原賣出/減碼降級為觀望(不轉為買進),請自行權衡。"
                else:
                    note += "本系統以風險控制優先、維持原建議,但此背離須如實揭露,請自行權衡。"
                decision["stat_conflict_note"] = note
    except Exception:
        pass


def apply_position_caps(decision, profit_space, avoid):
    """倉位強化:1) 避雷 heavy/extreme 壓低倉位上限 2) BUY 優勢偏薄時上限減半
    3) HOLD 但統計分佈明顯看壞(期望報酬<0且上漲機率<40%)時上限壓至1%
    (風控性壓低、不翻轉訊號;錯過不買只少賺,符合系統不對稱原則)"""
    _avoid = avoid or {}
    try:
        import re as _re
        ps = profit_space or {}
        act = str(decision.get("action", ""))
        pos = str(decision.get("position_size", ""))
        m = _re.match(r"(?:(\d+)-)?(\d+)%", pos)
        if m and ("BUY" in act or "HOLD" in act):
            low = int(m.group(1)) if m.group(1) else int(m.group(2))
            high = int(m.group(2))
            cap = None
            why = []
            lv = _avoid.get("level")
            if lv == "extreme":
                cap = 1
                why.append(f"法人避雷 extreme(20日法人賣壓比 {_avoid.get('inst_20d_ratio')})")
            elif lv == "heavy":
                cap = 2
                why.append(f"法人避雷 heavy(20日法人賣壓比 {_avoid.get('inst_20d_ratio')})")
            if "BUY" in act and (not ps.get("insufficient")) and ps.get("samples"):
                exp_ret = ps.get("expected_return")
                downside = abs(ps.get("downside") or 0)
                if exp_ret is not None and downside > 0 and 0.4 * downside <= exp_ret < 0.7 * downside:
                    thin_cap = max(1, high // 2)
                    cap = thin_cap if cap is None else min(cap, thin_cap)
                    why.append(f"優勢偏薄(期望報酬 {exp_ret}% 不足下檔 {ps.get('downside')}% 的0.7倍)")
            # 第4輪隨機驗證缺口A:HOLD 配多%倉位但統計分佈明顯看壞(如27.6%勝率配3-5%)
            # → 壓到1%並留書面理由;只管「建議持有多少」、不把 HOLD 翻成 REDUCE
            if "HOLD" in act and (not ps.get("insufficient")) and ps.get("samples"):
                exp_ret = ps.get("expected_return")
                prob_up = ps.get("prob_up")
                if exp_ret is not None and prob_up is not None and exp_ret < 0 and prob_up < 40:
                    cap = 1 if cap is None else min(cap, 1)
                    why.append(f"統計分佈看壞(20日上漲機率 {prob_up}%、期望報酬 {exp_ret}%)")
            if cap is not None and high > cap:
                new_low = min(low, cap)
                decision["position_size"] = (f"{cap}%" if new_low >= cap else f"{new_low}-{cap}%") + " (上限壓低)"
                decision["position_cap_note"] = (
                    f"倉位上限由 {pos} 壓至 {cap}%:" + ";".join(why)
                    + "。此為風控性壓低、非預測,訊號本身不變。")
    except Exception:
        pass
