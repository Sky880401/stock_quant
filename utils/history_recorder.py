import csv
import os
from datetime import datetime

# [修正] 使用絕對路徑，確保檔案寫入正確位置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_FILE = os.path.join(BASE_DIR, "data", "user_query_history.csv")

def record_user_query(user_name, ticker, stock_name, action, confidence, roi):
    """
    記錄使用者的查詢與 BMO 的建議
    """
    try:
        # 確保 data 資料夾存在
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        
        file_exists = os.path.isfile(HISTORY_FILE)
        
        # 使用 'a' (append) 模式寫入，並強制 utf-8-sig (讓 Excel 開啟不亂碼)
        with open(HISTORY_FILE, mode='a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            
            # 如果是新檔案，寫入標頭
            if not file_exists:
                writer.writerow(["Timestamp", "User", "Ticker", "StockName", "Action", "Confidence", "Backtest_ROI"])
                
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                user_name,
                ticker,
                stock_name,
                action,
                confidence,
                roi
            ])
            # print(f"✅ History recorded to {HISTORY_FILE}") # Debug用
    except Exception as e:
        print(f"❌ Failed to record history: {e}")
