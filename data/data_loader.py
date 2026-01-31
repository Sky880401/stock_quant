import pandas as pd
import yfinance as yf
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
        if not self.loader or not stock_id.isdigit(): return {}
        try:
            start = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            end = datetime.now().strftime('%Y-%m-%d')
            df = self.loader.taiwan_stock_per_pbr(stock_id=stock_id, start_date=start, end_date=end)
            if not df.empty:
                latest = df.iloc[-1]
                return {"pe_ratio": latest.get('PER'), "pb_ratio": latest.get('PBR'), "dividend_yield": latest.get('dividend_yield')}
            return {}
        except: return {}

# YFinance Provider (Standard Version)
class YFinanceProvider(DataProvider):
    def __init__(self):
        pass # [修正] 不再手動建立 Session，交給 yfinance 處理

    def _normalize_id(self, stock_id: str) -> str:
        if stock_id.isdigit(): return f"{stock_id}.TW"
        return stock_id

    def get_history(self, stock_id: str, days: int = 365) -> pd.DataFrame:
        target_id = self._normalize_id(stock_id)
        print(f"   [YFinance] Fetching history for {target_id}...")
        
        try:
            # [修正] 移除 session 參數
            ticker = yf.Ticker(target_id) 
            df = ticker.history(period=f"{days}d")
            
            if df.empty:
                print(f"   ⚠️ Warning: No data for {target_id}")
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
            # [修正] 移除 session 參數
            ticker = yf.Ticker(target_id)
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
