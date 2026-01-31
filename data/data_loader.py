import pandas as pd
import yfinance as yf
from abc import ABC, abstractmethod

# 抽象基類 (介面)
class DataProvider(ABC):
    @abstractmethod
    def get_history(self, stock_id: str, period: str = "1y") -> pd.DataFrame:
        """回傳包含 Open, High, Low, Close, Volume 的 DataFrame"""
        pass

    @abstractmethod
    def get_fundamentals(self, stock_id: str) -> dict:
        """回傳基本面數據字典"""
        pass

# 具體實作: Yahoo Finance
class YFinanceProvider(DataProvider):
    def get_history(self, stock_id: str, period: str = "1y") -> pd.DataFrame:
        print(f"   [Data] Fetching history for {stock_id} from yfinance...")
        try:
            # yfinance 最近更新後，回傳格式可能包含 MultiIndex，需做處理
            df = yf.download(stock_id, period=period, progress=False)
            if df.empty:
                return pd.DataFrame()
            
            # 確保欄位扁平化 (若有 MultiIndex)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            return df[['Open', 'High', 'Low', 'Close', 'Volume']]
        except Exception as e:
            print(f"   [Error] Download failed for {stock_id}: {e}")
            return pd.DataFrame()

    def get_fundamentals(self, stock_id: str) -> dict:
        print(f"   [Data] Fetching fundamentals for {stock_id}...")
        try:
            ticker = yf.Ticker(stock_id)
            info = ticker.info
            return {
                "pb_ratio": info.get("priceToBook"),
                "pe_ratio": info.get("trailingPE"),
                "market_cap": info.get("marketCap"),
                "currency": info.get("currency")
            }
        except Exception as e:
            print(f"   [Error] Fundamentals failed for {stock_id}: {e}")
            return {}

# 具體實作: FinMind (預留骨架)
class FinMindProvider(DataProvider):
    def get_history(self, stock_id: str, period: str = "1y") -> pd.DataFrame:
        print(f"   [Data] Would fetch from FinMind for {stock_id}")
        return pd.DataFrame()

    def get_fundamentals(self, stock_id: str) -> dict:
        return {}

# 工廠函數
def get_data_provider(source_name: str = 'yfinance') -> DataProvider:
    if source_name.lower() == 'yfinance':
        return YFinanceProvider()
    elif source_name.lower() == 'finmind':
        return FinMindProvider()
    else:
        raise ValueError(f"Unknown data source: {source_name}")
