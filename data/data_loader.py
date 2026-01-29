import yfinance as yf
import pandas as pd
from abc import ABC, abstractmethod

class DataProvider(ABC):
    @abstractmethod
    def get_history(self, stock_id: str, period: str = "1y") -> pd.DataFrame:
        pass

    @abstractmethod
    def get_fundamentals(self, stock_id: str) -> dict:
        pass

class YFinanceProvider(DataProvider):
    def get_history(self, stock_id: str, period: str = "1y") -> pd.DataFrame:
        try:
            # 強制 single ticker 下載，避免格式混亂
            stock = yf.Ticker(stock_id)
            df = stock.history(period=period)
            
            if df.empty:
                print(f"⚠️ Warning: No price data found for {stock_id}")
                return pd.DataFrame()

            # 標準化欄位名稱 (移除時區資訊等)
            df.index = df.index.tz_localize(None)
            
            # 確保欄位存在
            required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            if not all(col in df.columns for col in required_cols):
                print(f"⚠️ Warning: Missing columns for {stock_id}. Found: {df.columns}")
                return pd.DataFrame()

            return df[required_cols]
            
        except Exception as e:
            print(f"❌ Error fetching history for {stock_id}: {e}")
            return pd.DataFrame()

    def get_fundamentals(self, stock_id: str) -> dict:
        try:
            ticker = yf.Ticker(stock_id)
            # 使用 fast_info (比較快且穩) 搭配 info
            info = ticker.info
            
            # 嘗試多種 key (因為台股美股 key 有時不同)
            pb = info.get("priceToBook")
            pe = info.get("trailingPE")
            
            return {
                "priceToBook": pb,
                "trailingPE": pe,
                "marketCap": info.get("marketCap"),
                "sector": info.get("sector", "Unknown")
            }
        except Exception as e:
            print(f"❌ Error fetching fundamentals for {stock_id}: {e}")
            return {}

class FinMindProvider(DataProvider):
    def get_history(self, stock_id: str, period: str = "1y") -> pd.DataFrame:
        return pd.DataFrame()

    def get_fundamentals(self, stock_id: str) -> dict:
        return {}

def get_data_provider(source_name: str = "yfinance") -> DataProvider:
    drivers = {
        "yfinance": YFinanceProvider(),
        "finmind": FinMindProvider(),
    }
    return drivers.get(source_name, YFinanceProvider())