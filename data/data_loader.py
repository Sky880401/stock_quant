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
            
            # 1. 抓股價
            df_price = self.loader.taiwan_stock_daily(stock_id=stock_id, start_date=start, end_date=end)
            if df_price.empty: return pd.DataFrame()
            
            # 2. [新增] 抓籌碼 (三大法人)
            df_chip = self.loader.taiwan_stock_institutional_investors(stock_id=stock_id, start_date=start, end_date=end)
            
            # 整理股價
            df_price = df_price.rename(columns={'open': 'Open', 'max': 'High', 'min': 'Low', 'close': 'Close', 'Trading_Volume': 'Volume', 'date': 'Date'})
            df_price['Date'] = pd.to_datetime(df_price['Date'])
            df_price = df_price.set_index('Date')
            df_price[['Open', 'High', 'Low', 'Close', 'Volume']] = df_price[['Open', 'High', 'Low', 'Close', 'Volume']].apply(pd.to_numeric, errors='coerce')

            # 整理籌碼 (Pivot Table: 轉成 Foreign_Investor, Investment_Trust, Dealer)
            if not df_chip.empty:
                df_chip['name'] = df_chip['name'].map({
                    'Foreign_Investor': 'Foreign', 
                    'Investment_Trust': 'Trust', 
                    'Dealer_Self': 'Dealer',
                    'Dealer_Hedging': 'Dealer' # 合併自營商
                })
                # 買賣超加總
                df_chip = df_chip.groupby(['date', 'name'])['buy_sell'].sum().unstack(fill_value=0)
                df_chip.index = pd.to_datetime(df_chip.index)
                
                # 合併數據 (Left Join 以股價為主)
                df_price = df_price.join(df_chip, how='left').fillna(0)
            else:
                df_price['Foreign'] = 0
                df_price['Trust'] = 0
                df_price['Dealer'] = 0

            return df_price

        except Exception as e:
            # print(f"FinMind Error: {e}")
            return pd.DataFrame()

    def get_fundamentals(self, stock_id: str) -> dict:
        # (保持原樣)
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

class YFinanceProvider(DataProvider):
    # (保持原樣，不需變動)
    def __init__(self): pass
    def _normalize_id(self, stock_id: str) -> str:
        if stock_id.isdigit(): return f"{stock_id}.TW"
        return stock_id
    def get_history(self, stock_id: str, days: int = 365) -> pd.DataFrame:
        target_id = self._normalize_id(stock_id)
        try:
            ticker = yf.Ticker(target_id)
            df = ticker.history(period=f"{days}d")
            if df.empty: return pd.DataFrame()
            df.columns = [c.capitalize() for c in df.columns]
            if df.index.tz is not None: df.index = df.index.tz_localize(None)
            required = ['Open', 'High', 'Low', 'Close', 'Volume']
            if all(c in df.columns for c in required): 
                # Yahoo 沒有籌碼數據，補 0
                df['Foreign'] = 0
                df['Trust'] = 0
                df['Dealer'] = 0
                return df[required + ['Foreign', 'Trust', 'Dealer']]
            return pd.DataFrame()
        except: return pd.DataFrame()
    def get_fundamentals(self, stock_id: str) -> dict:
        target_id = self._normalize_id(stock_id)
        try:
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
