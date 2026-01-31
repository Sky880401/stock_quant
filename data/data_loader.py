import pandas as pd
import yfinance as yf
try:
    from FinMind.data import DataLoader as FinMindLoader
except ImportError:
    FinMindLoader = None

from abc import ABC, abstractmethod
from datetime import datetime, timedelta

# ==========================================
# 1. 定義標準介面
# ==========================================
class BaseDataProvider(ABC):
    @abstractmethod
    def fetch_history(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        pass

# ==========================================
# 2. FinMind 來源 (Primary)
# ==========================================
class FinMindProvider(BaseDataProvider):
    def __init__(self, api_token=None):
        if FinMindLoader:
            self.loader = FinMindLoader()
            if api_token:
                self.loader.login_by_token(api_token=api_token)
        else:
            self.loader = None
            print("⚠️ FinMind package not installed. Skipping.")

    def fetch_history(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        if not self.loader: return None
        
        # 移除 .TW (FinMind 格式)
        stock_id = ticker.split('.')[0]
        print(f"   [FinMind] Fetching {stock_id}...")
        
        try:
            df = self.loader.taiwan_stock_daily(
                stock_id=stock_id,
                start_date=start_date,
                end_date=end_date
            )
            if df.empty: return None

            df = df.rename(columns={
                'date': 'date', 'open': 'open', 'max': 'high', 
                'min': 'low', 'close': 'close', 'Trading_Volume': 'volume'
            })
            cols = ['open', 'high', 'low', 'close', 'volume']
            df[cols] = df[cols].apply(pd.to_numeric, errors='coerce')
            return df[['date', 'open', 'high', 'low', 'close', 'volume']]
        except Exception as e:
            print(f"   [FinMind] Error: {e}")
            return None

# ==========================================
# 3. yfinance 來源 (Backup)
# ==========================================
class YFinanceProvider(BaseDataProvider):
    def fetch_history(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        if ".TW" not in ticker and ".TWO" not in ticker:
            ticker = f"{ticker}.TW"
        print(f"   [yfinance] Fetching {ticker}...")

        try:
            df = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if df.empty: return None
            
            df = df.reset_index()
            # 處理 MultiIndex 欄位
            if isinstance(df.columns, pd.MultiIndex):
                try: df.columns = df.columns.get_level_values(0)
                except: pass

            df.columns = [c.lower() for c in df.columns]
            if 'date' not in df.columns and 'datetime' in df.columns:
                 df = df.rename(columns={'datetime': 'date'})

            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            return df[['date', 'open', 'high', 'low', 'close', 'volume']]
        except Exception as e:
            print(f"   [yfinance] Error: {e}")
            return None

# ==========================================
# 4. 統一數據管理器 (Manager)
# ==========================================
class UnifiedDataManager:
    def __init__(self, finmind_token=None):
        self.providers = [
            FinMindProvider(api_token=finmind_token),
            YFinanceProvider()
        ]

    def get_data(self, ticker: str, days: int = 100) -> pd.DataFrame:
        """
        整合邏輯：自動切換來源，並統一回傳格式
        """
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        for provider in self.providers:
            df = provider.fetch_history(ticker, start_date, end_date)
            if df is not None and not df.empty:
                print(f"✅ Data loaded via {provider.__class__.__name__}")
                # 統一格式供策略使用
                df['Date'] = pd.to_datetime(df['date'])
                df = df.set_index('Date')
                df = df.rename(columns={
                    'open': 'Open', 'high': 'High', 'low': 'Low', 
                    'close': 'Close', 'volume': 'Volume'
                })
                return df
                
        print(f"❌ All providers failed for {ticker}")
        return pd.DataFrame()
    
    def get_institutional_data(self, stock_id: str) -> dict:
        # 暫時回傳 None，避免爬蟲錯誤
        return {"foreign": None, "trust": None, "dealer": None}