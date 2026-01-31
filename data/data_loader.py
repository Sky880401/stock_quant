import pandas as pd
from FinMind.data import DataLoader as FinMindLoader
from datetime import datetime, timedelta

class DataLoader:
    def __init__(self, token=None):
        self.fm = FinMindLoader()
        self.token = token
        if self.token:
            self.fm.login_by_token(api_token=self.token)

    def fetch_data(self, ticker: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """
        從 FinMind 獲取台股價量與籌碼數據 (具備容錯機制)
        """
        # 1. 處理日期預設值
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        # 2. 處理代碼格式 (移除 .TW)
        clean_ticker = ticker.replace(".TW", "").replace(".TWO", "")
        print(f"📥 正在從 FinMind 下載 {clean_ticker} 數據 ({start_date} ~ {end_date})...")

        df_price = pd.DataFrame()
        
        # --- A. 抓取股價 (Price) ---
        try:
            df_price = self.fm.taiwan_stock_daily(
                stock_id=clean_ticker,
                start_date=start_date,
                end_date=end_date
            )
            if df_price.empty:
                print(f"⚠️ 警告: 找不到 {clean_ticker} 的股價數據")
                return pd.DataFrame()

            # 整理股價 DataFrame
            df_price['date'] = pd.to_datetime(df_price['date'])
            df_price = df_price.rename(columns={
                'Trading_Volume': 'Volume',
                'close': 'Close',
                'open': 'Open',
                'max': 'High',
                'min': 'Low',
            })
            df_price = df_price.set_index('date')
            
            # 確保數據是數值型態
            cols_to_numeric = ['Open', 'High', 'Low', 'Close', 'Volume']
            df_price[cols_to_numeric] = df_price[cols_to_numeric].apply(pd.to_numeric, errors='coerce')

        except Exception as e:
            print(f"❌ 股價下載失敗: {e}")
            return pd.DataFrame()

        # --- B. 抓取法人籌碼 (Chips) - 獨立 Try-Except (容錯) ---
        try:
            df_chips = self.fm.taiwan_stock_institutional_investors(
                stock_id=clean_ticker,
                start_date=start_date,
                end_date=end_date
            )
            
            # 檢查是否有資料，且關鍵欄位 'buy_sell' 是否存在
            if not df_chips.empty and 'buy_sell' in df_chips.columns:
                df_chips['date'] = pd.to_datetime(df_chips['date'])
                
                # 樞紐分析：將 'name' 轉為 columns
                pivot_chips = df_chips.pivot_table(
                    index='date', 
                    columns='name', 
                    values='buy_sell', 
                    aggfunc='sum'
                ).fillna(0)
                
                # 合併到主表
                df_final = df_price.join(pivot_chips, how='left').fillna(0)
                
                # 重新命名欄位 (標準化)
                mapping = {
                    'Foreign_Investor': 'Institutional_Foreign', # 外資
                    'Investment_Trust': 'Institutional_Trust',   # 投信
                    'Dealer_Self_Analysis': 'Institutional_Dealer' # 自營商
                }
                df_final = df_final.rename(columns=mapping)
                print(f"✅ 成功下載 {len(df_final)} 筆交易數據 (含籌碼)")
                return df_final

            else:
                # 如果籌碼有問題 (例如缺少欄位)，只印警告但不中斷程式
                if not df_chips.empty:
                    print(f"⚠️ 籌碼數據欄位異常 (Available: {df_chips.columns.tolist()})，僅使用股價分析。")
                else:
                    print("⚠️ 無籌碼數據，僅使用股價分析。")
                return df_price

        except Exception as e:
            # 籌碼下載發生任何其他錯誤，也不要讓程式崩潰
            print(f"⚠️ 籌碼下載失敗 ({e})，僅使用股價分析。")
            return df_price

# 測試區塊
if __name__ == "__main__":
    loader = DataLoader()
    df = loader.fetch_data("2330", "2024-01-01", "2024-01-10")
    print(df.tail())