import json
import os
from datetime import datetime

# 定義檔案路徑
INPUT_JSON = "data/latest_report.json"
OUTPUT_MISSION = "data/moltbot_mission.txt"  # 這是給 Moltbot 看的「任務簡報」

def generate_moltbot_prompt(report):
    timestamp = report.get("timestamp", datetime.now().isoformat())
    data_source = report.get("data_source", "Unknown")
    analysis = report.get("analysis", {})

    # 1. 定義角色與任務 (System Prompt)
    # 我們直接在這邊告訴 Moltbot 它的身分和它要做什麼
    prompt_content = f"""
【Moltbot 任務指令書】
時間: {timestamp}
來源: {data_source}

角色設定：
你是一位專業的華爾街量化分析師。你的任務是閱讀下方的「原始交易數據」，並撰寫一份高品質的「投資日報」。

任務目標：
請根據數據，將分析結果寫入到一個新的 Markdown 檔案中，檔名請命名為 `reports/daily_summary_{datetime.now().strftime('%Y%m%d')}.md`。

分析報告結構要求：
1. **市場情緒速覽**：根據所有股票的訊號給出整體評分 (1-10分)。
2. **個股深度掃描**：
   - 重點分析訊號發生衝突的股票 (如: 技術面看多但基本面看空)。
   - 特別關注清單中的 2330.TW (台積電), 2317.TW (鴻海)。
3. **行動建議**：明確列出今天適合「買進」、「賣出」或「觀望」的標的。

--- [以下是原始數據 JSON] ---
{json.dumps(analysis, indent=2, ensure_ascii=False)}
"""
    return prompt_content

def main():
    # 檢查 JSON 是否存在
    if not os.path.exists(INPUT_JSON):
        print(f"❌ 錯誤: 找不到 {INPUT_JSON}。請先執行 main.py！")
        return

    # 讀取 JSON
    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 生成給 Moltbot 的指令內容
    mission_text = generate_moltbot_prompt(data)

    # 寫入文字檔 (這就是 File-based Handoff)
    with open(OUTPUT_MISSION, "w", encoding="utf-8") as f:
        f.write(mission_text)

    print("="*60)
    print(f"✅ Moltbot 任務簡報已生成！路徑: {OUTPUT_MISSION}")
    print("接下來請開啟 Moltbot 並輸入指令：")
    print(f'👉 "Please read {os.path.abspath(OUTPUT_MISSION)} and execute the instructions inside."')
    print("="*60)

if __name__ == "__main__":
    main()