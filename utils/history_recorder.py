import csv
import os
from datetime import datetime

HISTORY_FILE = "data/user_query_history.csv"

def record_user_query(user_name, ticker, stock_name, action, confidence, roi):
    """
    記錄使用者的查詢與 BMO 的建議
    """
    file_exists = os.path.isfile(HISTORY_FILE)
    
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    
    with open(HISTORY_FILE, mode='a', newline='', encoding='utf-8') as f:
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
