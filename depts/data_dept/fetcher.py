# 數據搜集課：抓取器（原 main.py 的 get_stock_name_zh / fetch_stock_data_smart，邏輯原樣搬入）
from data.data_loader import get_data_provider
from utils.logger import log_info
from depts.config import PRIMARY_SOURCE, FALLBACK_SOURCE


# 全市場股票清單只抓一次並快取：原本每次 get_stock_name_zh 都 new DataLoader 並整批下載
# taiwan_stock_info()，既洩漏連線又浪費頻寬。
_STOCK_INFO_DF = None

# 本地股名快取(data/stock_names.json, code->name):股名查詢優先讀這裡,不靠會限流的
# FinMind taiwan_stock_info()。FinMind 限流時股名也不會退回代號。
import os as _os
import json as _json
_NAME_MAP = None
_NAME_MAP_PATH = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), "data", "stock_names.json")


def _name_map():
    global _NAME_MAP
    if _NAME_MAP is None:
        try:
            with open(_NAME_MAP_PATH, encoding="utf-8") as f:
                _NAME_MAP = _json.load(f)
        except Exception:
            _NAME_MAP = {}
    return _NAME_MAP


def _stock_info_df():
    global _STOCK_INFO_DF
    if _STOCK_INFO_DF is None:
        from FinMind.data import DataLoader
        df = DataLoader().taiwan_stock_info()
        if df is not None and not df.empty:
            _STOCK_INFO_DF = df
        else:
            return df
    return _STOCK_INFO_DF


def get_stock_name_zh(stock_id: str) -> str:
    clean_id = stock_id.split('.')[0]
    _nm = _name_map().get(clean_id)  # 本地股名快取優先,不靠 FinMind 限流
    if _nm:
        return _nm
    if not clean_id.isdigit():
        # 非台股代號（含美股）→ 用 yfinance 取公司全名；失敗就回代號本身
        try:
            import yfinance as yf
            info = yf.Ticker(clean_id).info
            name = info.get("longName") or info.get("shortName")
            if name:
                return f"{name} ({clean_id})"
        except Exception:
            pass
        return clean_id
    try:
        df = _stock_info_df()
        if df is not None:
            row = df[df['stock_id'] == clean_id]
            if not row.empty: return row.iloc[0]['stock_name']
    except: pass
    return clean_id

def fetch_stock_data_smart(stock_id: str):
    log_info(f"正在獲取數據: {stock_id} ...")
    clean_id = stock_id.split('.')[0]
    candidates = [f"{clean_id}.TWO", f"{clean_id}.TW"] if "TWO" in stock_id else [f"{clean_id}.TW", f"{clean_id}.TWO"]
    if not clean_id.isdigit(): candidates = [stock_id]
    last_error = "未知"
    for current_id in candidates:
        provider = get_data_provider(PRIMARY_SOURCE)
        try:
            df = provider.get_history(clean_id)
            if df.empty or len(df) < 60:
                yf_provider = get_data_provider(FALLBACK_SOURCE)
                df = yf_provider.get_history(current_id)
            if df.empty: last_error = "查無數據"; continue
            # 丟掉 Close 為 NaN 的列（FinMind 常回傳今日未成交/暫停交易的空白列，
            # 會導致 latest_close、RSI 變 nan，AI 拿不到價格就亂編）
            df = df[df['Close'].notna()]
            if df.empty: last_error = "查無有效收盤價"; continue
            if len(df) < 60: last_error = "數據不足"; continue
            fundamentals = {}
            try: fundamentals = provider.get_fundamentals(clean_id)
            except: pass
            if not fundamentals or not fundamentals.get("pe_ratio"):
                try:
                    yf_provider = get_data_provider(FALLBACK_SOURCE)
                    yf_funds = yf_provider.get_fundamentals(current_id)
                    if yf_funds and (yf_funds.get("pe_ratio") or yf_funds.get("market_cap")):
                        if not fundamentals: fundamentals = {}
                        for k, v in yf_funds.items():
                            if k not in fundamentals or fundamentals[k] is None: fundamentals[k] = v
                except: pass
            # 用 TWSE 官方三大法人買賣超覆寫籌碼欄（FinMind 匿名額度太低會是 0）
            try:
                from crawlers.twse_institutional import attach_institutional
                df = attach_institutional(df, current_id)
            except Exception as e:
                log_info(f"TWSE 法人併入略過: {e}")
            log_info(f"數據獲取成功: {current_id}")
            return {"status": "success", "source": "Hybrid", "df": df, "fundamentals": fundamentals, "ticker": current_id}
        except Exception as e: last_error = str(e); continue
    return {"status": "error", "reason": last_error}
