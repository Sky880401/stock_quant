import pandas as pd
import yfinance as yf
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
import logging

# 配置 logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 抽象基類 (介面)
class DataProvider(ABC):
    @abstractmethod
    def get_history(self, stock_id: str, days: int = 365) -> pd.DataFrame:
        """回傳包含 Open, High, Low, Close, Volume 的 DataFrame"""
        pass

    @abstractmethod
    def get_fundamentals(self, stock_id: str) -> dict:
        """回傳基本面數據字典 (PE, PB)"""
        pass

# 具體實作: FinMind (Primary)
class FinMindProvider(DataProvider):
    def __init__(self):
        try:
            from FinMind.data import DataLoader
            self.loader = DataLoader()
            logging.info("✅ FinMind SDK initialized successfully.")
        except ImportError:
            logging.error("❌ FinMind package not found. Please run: pip install FinMind")
            self.loader = None

    def get_history(self, stock_id: str, days: int = 365) -> pd.DataFrame:
        if not self.loader: return pd.DataFrame()
        
        print(f"   [FinMind] Fetching price history for {stock_id}...")
        try:
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            end_date = datetime.now().strftime('%Y-%m-%d')
            
            # 下載股價
            df = self.loader.taiwan_stock_daily(
                stock_id=stock_id,
                start_date=start_date,
                end_date=end_date
            )
            
            if df.empty:
                print(f"   [FinMind] No data returned for {stock_id}")
                return pd.DataFrame()

            # 欄位標準化 (FinMind -> Standard)
            # FinMind columns: date, stock_id, Trading_Volume, Trading_money, open, max, min, close, ...
            rename_map = {
                'open': 'Open',
                'max': 'High',
                'min': 'Low',
                'close': 'Close',
                'Trading_Volume': 'Volume',
                'date': 'Date'
            }
            df = df.rename(columns=rename_map)
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.set_index('Date')
            
            # 確保數值型別正確
            cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            df[cols] = df[cols].apply(pd.to_numeric, errors='coerce')
            
            return df[cols]

        except Exception as e:
            print(f"   [FinMind] Error: {e}")
            return pd.DataFrame()

    def get_fundamentals(self, stock_id: str) -> dict:
        if not self.loader: return {}
        
        print(f"   [FinMind] Fetching fundamentals for {stock_id}...")
        try:
            # 抓取最近 30 天的本益比數據 (取最新一筆)
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            end_date = datetime.now().strftime('%Y-%m-%d')
            
            df = self.loader.taiwan_stock_per_pbr(
                stock_id=stock_id, 
                start_date=start_date,
                end_date=end_date
            )
            
            if not df.empty:
                latest = df.iloc[-1]
                return {
                    "pe_ratio": latest.get('PER'),
                    "pb_ratio": latest.get('PBR'),
                    "dividend_yield": latest.get('dividend_yield')
                }
            return {}
        except Exception as e:
            print(f"   [FinMind] Fundamental Error: {e}")
            return {}

# 具體實作: Yahoo Finance (Fallback)
class YFinanceProvider(DataProvider):
    def get_history(self, stock_id: str, days: int = 365) -> pd.DataFrame:
        print(f"   [YFinance] Fetching history for {stock_id}...")
        try:
            # yfinance 需要 ".TW" 後綴
            if not stock_id.endswith('.TW'):
                stock_id = f"{stock_id}.TW"
                
            df = yf.download(stock_id, period=f"{days}d", progress=False)
            if df.empty:
                return pd.DataFrame()
            
            # 處理 MultiIndex
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            return df[['Open', 'High', 'Low', 'Close', 'Volume']]
        except Exception as e:
            print(f"   [YFinance] Error: {e}")
            return pd.DataFrame()

    def get_fundamentals(self, stock_id: str) -> dict:
        print(f"   [YFinance] Fetching fundamentals for {stock_id}...")
        try:
            if not stock_id.endswith('.TW'):
                stock_id = f"{stock_id}.TW"
            ticker = yf.Ticker(stock_id)
            info = ticker.info
            return {
                "pe_ratio": info.get("trailingPE"),
                "pb_ratio": info.get("priceToBook"),
                "market_cap": info.get("marketCap")
            }
        except Exception as e:
            print(f"   [YFinance] Error: {e}")
            return {}

# 工廠函數 (Factory)
def get_data_provider(source_name: str = 'finmind') -> DataProvider:
    if source_name.lower() == 'finmind':
        return FinMindProvider()
    elif source_name.lower() == 'yfinance':
        return YFinanceProvider()
    else:
        raise ValueError(f"Unknown data source: {source_name}")
