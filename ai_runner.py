import json
import os
from datetime import datetime
from ai_engine import QuantBrain  # 匯入剛剛寫好的大腦

INPUT_JSON = "data/latest_report.json"
REPORT_DIR = "reports"

def main():
    # 1. 檢查是否有數據
    if not os.path.exists(INPUT_JSON):
        print(f"❌ 錯誤: 找不到 {INPUT_JSON}。請先執行 main.py！")
        return

    # 2. 讀取數據
    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    data_str = json.dumps(data, indent=2, ensure_ascii=False)

    # 3. 初始化混合 AI 引擎
    brain = QuantBrain()

    # 4. 執行深度分析 (Mode A)
    print("="*50)
    print("🚀 啟動 AI 量化分析程序...")
    report_content = brain.analyze_market_report(data_str)

    # 5. 存檔
    os.makedirs(REPORT_DIR, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"{REPORT_DIR}/daily_summary_{date_str}.md"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(report_content)

    print("="*50)
    print(f"✅ 投資日報已生成！")
    print(f"📂 檔案路徑: {filename}")
    print("="*50)

    # (可選) 測試本地端功能
    # print(brain.quick_check("你好，請確認系統運作正常。"))

if __name__ == "__main__":
    main()