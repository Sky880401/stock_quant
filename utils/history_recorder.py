import csv
import os
from datetime import datetime
from pathlib import Path

# [修正] 鎖定絕對路徑：從 utils 資料夾往上兩層找到根目錄
BASE_DIR = Path(__file__).resolve().parent.parent
HISTORY_FILE = BASE_DIR / "data" / "user_query_history.csv"

def record_user_query(user_name, ticker, stock_name, action, confidence, roi):
    """
    記錄使用者的查詢與 BMO 的建議
    """
    try:
        # 確保 data 資料夾存在
        os.makedirs(HISTORY_FILE.parent, exist_ok=True)
        
        file_exists = HISTORY_FILE.exists()
        
        # 使用 utf-8-sig 寫入 (Excel 相容)
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
            
        print(f"📝 History saved: {user_name} -> {ticker} ({action})")
        
    except Exception as e:
        print(f"❌ CSV Write Error: {e}")
