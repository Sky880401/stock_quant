import pandas as pd
import yfinance as yf
import requests
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class DataProvider(ABC):
    @abstractmethod
    def get_history(self, stock_id: str, days: int = 365) -> pd.DataFrame:
        pass
    @abstractmethod
    def get_fundamentals(self, stock_id: str) -> dict:
        pass

# FinMind Provider
class FinMindProvider(DataProvider):
    def __init__(self):
        try:
            from FinMind.data import DataLoader
            self.loader = DataLoader()
        except ImportError:
            self.loader = None

    def get_history(self, stock_id: str, days: int = 365) -> pd.DataFrame:
        if not self.loader or not stock_id.isdigit(): return pd.DataFrame()
        try:
            start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            end = datetime.now().strftime('%Y-%m-%d')
            df = self.loader.taiwan_stock_daily(stock_id=stock_id, start_date=start, end_date=end)
            if df.empty: return pd.DataFrame()
            
            df = df.rename(columns={'open': 'Open', 'max': 'High', 'min': 'Low', 'close': 'Close', 'Trading_Volume': 'Volume', 'date': 'Date'})
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.set_index('Date')
            df[['Open', 'High', 'Low', 'Close', 'Volume']] = df[['Open', 'High', 'Low', 'Close', 'Volume']].apply(pd.to_numeric, errors='coerce')
            return df[['Open', 'High', 'Low', 'Close', 'Volume']]
        except: return pd.DataFrame()

    def get_fundamentals(self, stock_id: str) -> dict:
        # (保持原樣，省略以節省空間)
        return {}

# YFinance Provider (Anti-Block Version)
class YFinanceProvider(DataProvider):
    def __init__(self):
        # [關鍵優化] 建立偽裝的 Session
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

    def _normalize_id(self, stock_id: str) -> str:
        if stock_id.isdigit(): return f"{stock_id}.TW"
        return stock_id

    def get_history(self, stock_id: str, days: int = 365) -> pd.DataFrame:
        target_id = self._normalize_id(stock_id)
        print(f"   [YFinance] Fetching history for {target_id}...")
        
        try:
            # 傳入 session 進行偽裝
            ticker = yf.Ticker(target_id, session=self.session)
            df = ticker.history(period=f"{days}d")
            
            if df.empty:
                # 再次確認是否因為下市
                print(f"   ⚠️ Warning: No data for {target_id} (Delisted or Blocked?)")
                return pd.DataFrame()
            
            df.columns = [c.capitalize() for c in df.columns]
            if df.index.tz is not None: df.index = df.index.tz_localize(None)
            
            required = ['Open', 'High', 'Low', 'Close', 'Volume']
            if all(c in df.columns for c in required): return df[required]
            return pd.DataFrame()

        except Exception as e:
            print(f"   [YFinance] Error: {e}")
            return pd.DataFrame()

    def get_fundamentals(self, stock_id: str) -> dict:
        target_id = self._normalize_id(stock_id)
        try:
            ticker = yf.Ticker(target_id, session=self.session)
            info = ticker.info
            return {
                "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
                "pb_ratio": info.get("priceToBook"),
                "market_cap": info.get("marketCap"),
                "ticker": target_id
            }
        except: return {}

def get_data_provider(source_name: str = 'finmind') -> DataProvider:
    if source_name.lower() == 'finmind': return FinMindProvider()
    elif source_name.lower() == 'yfinance': return YFinanceProvider()
    else: raise ValueError(f"Unknown source: {source_name}")
