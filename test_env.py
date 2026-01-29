import yfinance as yf
import talib
import pandas as pd
import numpy as np

def run_smoke_test():
    print("🚀 系統自我檢測開始 (System Check Initiated)...")
    print("-" * 50)

    # 1. 測試網路數據抓取 (Data Feed Check)
    stock_id = "2330.TW"  # 台積電
    print(f"📡 正在嘗試連線 yfinance 下載 {stock_id} 資料...")
    
    try:
        # 下載最近 100 天的資料
        df = yf.download(stock_id, period="100d", progress=False)
        
        if df.empty:
            print("❌ 錯誤：抓不到資料，請檢查網路連線或股票代碼。")
            return
        
        # --- 修正點：處理 yfinance 的多層索引問題 ---
        # 如果是多層索引 (Price, Ticker)，我們把 Ticker 那層拿掉，只留 Price (Open, High, Low, Close...)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
            
        print(f"✅ 成功下載資料，共 {len(df)} 筆。")
        
        # 確保取出來的是純數值 (float)
        last_close = float(df['Close'].iloc[-1])
        print(f"   最新收盤價 (Close): {last_close:.2f}")
        
    except Exception as e:
        print(f"❌ yfinance 資料處理失敗: {e}")
        return

    # 2. 測試 TA-Lib 運算 (Core Engine Check)
    print("-" * 50)
    print("⚙️ 正在測試 TA-Lib 數學運算引擎...")
    
    try:
        # 計算 20日移動平均線 (SMA)
        # 確保輸入的是 numpy array
        close_prices = df['Close'].values
            
        sma_20 = talib.SMA(close_prices, timeperiod=20)
        
        # 檢查最後一筆是否有數值
        last_sma = sma_20[-1]
        
        if np.isnan(last_sma):
             print("⚠️ 警告：SMA 計算結果為 NaN (可能是資料筆數不足)")
        else:
             print(f"✅ TA-Lib 運算成功！")
             print(f"   台積電 20日均線 (SMA20): {last_sma:.2f}")

    except Exception as e:
        print(f"❌ TA-Lib 呼叫失敗 (這通常是 C Library 沒裝好): {e}")
        return

    print("-" * 50)
    print("🎉 恭喜！環境建置 (Environment Setup) 100% 成功！")
    print("   Ready for Quantitative Development.")

if __name__ == "__main__":
    run_smoke_test()