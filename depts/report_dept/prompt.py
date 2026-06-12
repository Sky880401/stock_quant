# 報告產出課：報告 prompt 組裝（原 main.py 的 generate_moltbot_prompt，邏輯原樣搬入）
import json
from datetime import datetime


def generate_moltbot_prompt(data, is_single=False):
    timestamp = datetime.now().isoformat()
    if is_single:
        context = json.dumps(data, indent=2, ensure_ascii=False)
        ticker = data['meta']['ticker']
        name = data['meta'].get('name', ticker)
        dec = data['final_decision']
        bi = data.get('backtest_insight') or {}      # 美股/無回測參數時為 None，需防呆
        strat = bi.get('strategy_type', 'Trend')
        win_rate = bi.get('win_rate_display', 'N/A')

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

    _alert = (data.get("inst_avoid_alert") or {}) if isinstance(data, dict) else {}
    if _alert.get("level") in ("heavy", "extreme"):
        alert_section = """5. **🛑 法人避雷警示**:
   - 看 [Input Data] 的 inst_avoid_alert:**必須**在報告最上方加一個醒目警示區塊,引用其 meaning 與 inst_20d_ratio 數字,並明說「此為統計性避雷提示、非預測」。
6. """
        alert_ban = ""
    else:
        alert_section = "5. "
        alert_ban = "\n⚠️ 本檔 inst_avoid_alert 未觸發(none/no_data):整份報告禁止出現「法人避雷」「避雷警示」等字樣或任何相關段落,連「不需要警示」也不准寫。\n"

    prompt = f"""
【BMO 專業投資評鑑: {name} ({ticker})】
時間: {timestamp}

⚠️ 鐵則：**只能引用 [Input Data] 裡實際出現的數字**（現價、停損價、勝率、籌碼、報酬等）。
嚴禁自行編造或臆測任何價位/數據。若某欄位是 nan、缺失或 N/A，就明白寫「數據缺失，不評估」，不要用記憶中的歷史價格填補。

{alert_ban}--- 分析指引 ---
{guidance}

請撰寫報告，結構如下：
1. **📊 綜合評級**: 
   - 請列點顯示 Action、倉位、**策略模型** (這是使用者最關心的，請務必列出)、關鍵價位。
2. **🧠 決策邏輯**: 
   - 解釋為何選擇 {(data.get('backtest_insight') or {}).get('strategy_type', 'Trend')}。
   - 分析目前技術面多空。
   - 若 final_decision 含 risk_reward_downgrade 欄位,**必須**完整引用該欄位內容,解釋為何降級。
   - 若 final_decision 含 stat_conflict_note 欄位,**必須**在決策邏輯中如實呈現該分歧說明,不得淡化。
   - 若 final_decision 含 position_cap_note 欄位,**必須**在風險管理段引用該說明,解釋倉位為何被壓低。
3. **💰 獲利空間 (機率化)**:
   - 根據 profit_space 欄位說明：持有約 N 交易日的上漲機率、期望報酬、目標價區間(target_low~target_high)、下檔風險。
   - 這是基於該股歷史報酬分佈的統計值，請如實引用數字，不要誇大。若 insufficient 為真就說樣本不足。
4. **🔍 籌碼與消息面**:
   - 根據 sentiment 欄位解讀三大法人籌碼(Chip)、融資融券(margin)、新聞情緒(news)，三者是否與技術面同向或背離。
{alert_section}**⛔ 風險管理**:
   - 說明波動率風險與價位防守邏輯。

[Input Data]
{context}
"""
    return prompt
