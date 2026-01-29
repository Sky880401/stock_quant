import yfinance as yf
import pandas as pd
from abc import ABC, abstractmethod

class DataProvider(ABC):
    """
    抽象基類 (Abstract Base Class)
    定義所有數據提供者必須遵守的規格。
    """
    @abstractmethod
    def get_history(self, stock_id: str, period: str = "1y") -> pd.DataFrame:
        """回傳標準化的 OHLCV DataFrame"""
        pass

    @abstractmethod
    def get_fundamentals(self, stock_id: str) -> dict:
        """回傳基本面數據字典"""
        pass

class YFinanceProvider(DataProvider):
    """
    具體實作：使用 Yahoo Finance (Free)
    """
    def get_history(self, stock_id: str, period: str = "1y") -> pd.DataFrame:
        try:
            # yfinance 下載
            df = yf.download(stock_id, period=period, progress=False)
            
            if df.empty:
                print(f"Warning: No price data found for {stock_id}")
                return pd.DataFrame()

            # 處理 MultiIndex (針對新版 yfinance)
            if isinstance(df.columns, pd.MultiIndex):
                try:
                    df = df.xs(stock_id, level=1, axis=1)
                except:
                    df.columns = df.columns.get_level_values(0)

            # 重新命名以符合標準
            required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            # 簡單檢查，若欄位不足直接回傳以免報錯
            if not all(col in df.columns for col in required_cols):
                return df 
            
            return df[required_cols]
            
        except Exception as e:
            print(f"Error fetching history for {stock_id}: {e}")
            return pd.DataFrame()

    def get_fundamentals(self, stock_id: str) -> dict:
        try:
            ticker = yf.Ticker(stock_id)
            info = ticker.info
            # 取得關鍵基本面數據
            return {
                "priceToBook": info.get("priceToBook"),
                "trailingPE": info.get("trailingPE"),
                "marketCap": info.get("marketCap"),
                "sector": info.get("sector"),
                "dividendYield": info.get("dividendYield")
            }
        except Exception as e:
            print(f"Error fetching fundamentals for {stock_id}: {e}")
            return {}

class FinMindProvider(DataProvider):
    """
    預留實作：未來對接 FinMind
    """
    def get_history(self, stock_id: str, period: str = "1y") -> pd.DataFrame:
        print(f"[Placeholder] Fetching from FinMind for {stock_id}...")
        return pd.DataFrame()

    def get_fundamentals(self, stock_id: str) -> dict:
        return {}

def get_data_provider(source_name: str = "yfinance") -> DataProvider:
    """工廠函數：切換數據源"""
    drivers = {
        "yfinance": YFinanceProvider(),
        "finmind": FinMindProvider(),
    }
    return drivers.get(source_name, YFinanceProvider())