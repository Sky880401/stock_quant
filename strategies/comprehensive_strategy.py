import talib
import numpy as np
import pandas as pd
from .base_strategy import BaseStrategy

class ComprehensiveStrategy(BaseStrategy):
    """
    全方位量化策略：同時計算價值面與動能面指標
    並在 Python 層預先進行「狀態解讀」，防止 AI 產生數值幻覺。
    """
    def analyze(self, df: pd.DataFrame, extra_data: dict = None) -> dict:
        # 1. 數據基本檢查
        if df.empty or len(df) < 200:
            return self._default_result("數據不足 (需至少 200 天資料)")

        try:
            # === A. 數據準備 ===
            close = df['Close'].values.astype(float)
            high = df['High'].values.astype(float)
            low = df['Low'].values.astype(float)
            volume = df['Volume'].values.astype(float)
            current_price = float(close[-1])
            avg_volume = np.mean(volume[-20:]) # 20日均量

            # 防呆處理 NaN 的小函數
            def clean(val): return float(val) if not np.isnan(val) else 0.0

            # === B. 價值指標 (Value Metrics) ===
            lookback_52w = min(len(df), 252)
            low_52w = np.min(low[-lookback_52w:])
            high_52w = np.max(high[-lookback_52w:])
            
            # 距離 52 週低點的幅度 (%)
            dist_from_low = ((current_price - low_52w) / low_52w) * 100
            
            # P/E Ratio
            pe_ratio = extra_data.get("trailingPE") if extra_data else None
            sector = extra_data.get("sector", "Unknown") if extra_data else "Unknown"

            # --- [左腦邏輯] 價值狀態判讀 ---
            val_status = "一般 (Fair)"
            if pe_ratio is not None:
                if pe_ratio < 12 and dist_from_low < 15:
                    val_status = "低估且低檔 (Undervalued & Low)"
                elif pe_ratio > 35:
                    val_status = "高估 (Overvalued)"
            
            if dist_from_low > 80:
                val_status += " / 處於高檔 (High Level)"

            # === C. 動能與技術指標 (Momentum & Technicals) ===
            rsi = talib.RSI(close, timeperiod=14)[-1]
            roc_14 = talib.ROC(close, timeperiod=14)[-1]
            roc_21 = talib.ROC(close, timeperiod=21)[-1]

            ma20 = talib.SMA(close, timeperiod=20)[-1]
            ma50 = talib.SMA(close, timeperiod=50)[-1]
            ma200 = talib.SMA(close, timeperiod=200)[-1]

            # --- [左腦邏輯] RSI 狀態判讀 (避免 AI 幻覺) ---
            rsi_status = "中性 (Neutral)"
            if rsi >= 80:
                rsi_status = "極度超買 (Extreme Overbought)"
            elif rsi >= 70:
                rsi_status = "超買 (Overbought)"
            elif rsi <= 30:
                rsi_status = "超賣 (Oversold)"
            elif rsi <= 20:
                rsi_status = "極度超賣 (Extreme Oversold)"

            # --- [左腦邏輯] 趨勢狀態判讀 ---
            trend_status = "盤整 (Consolidation)"
            if current_price > ma20 > ma50 > ma200:
                trend_status = "強勢多頭排列 (Strong Bullish)"
            elif current_price < ma20 < ma50 < ma200:
                trend_status = "空頭排列 (Bearish)"
            elif current_price > ma200:
                trend_status = "長多短整理 (Bullish Trend)"

            # === D. 異常偵測 (針對 SPAX 這種非股票資產) ===
            warning_msg = ""
            if avg_volume < 10000: # 成交量太低
                warning_msg = "⚠️ 警告：成交量極低，可能為流動性不足或非股票資產"
            
            # === E. 綜合訊號生成 ===
            signal = "HOLD"
            reason = "無明顯訊號"

            is_value_buy = (pe_ratio is not None and pe_ratio < 15 and dist_from_low < 15)
            is_momentum_buy = (rsi > 50 and roc_14 > 0 and current_price > ma50)

            if is_value_buy:
                signal = "BUY"
                reason = "價值浮現 (低本益比 + 接近低點)"
            elif is_momentum_buy:
                signal = "BUY"
                reason = "動能轉強 (RSI強勢 + 均線支撐)"
            
            if "超買" in rsi_status:
                reason += " / 注意 RSI 過熱風險"

            return {
                "signal": signal,
                "confidence": 0.8 if (is_value_buy or is_momentum_buy) else 0.5,
                "reason": reason,
                "data": {
                    "price": current_price,
                    "sector": sector,
                    "avg_volume": clean(avg_volume),
                    "PE_Ratio": float(pe_ratio) if pe_ratio else "N/A",
                    "Low_52w": clean(low_52w),
                    "Dist_Low_52w_Pct": clean(dist_from_low),
                    
                    # 關鍵：加入預先判讀的文字狀態
                    "Valuation_Status": val_status, 
                    
                    "RSI_14": clean(rsi),
                    "RSI_Status": rsi_status, # AI 直接讀這個欄位就不會錯
                    
                    "ROC_14": clean(roc_14),
                    "ROC_21": clean(roc_21),
                    "MA20": clean(ma20),
                    "MA50": clean(ma50),
                    "MA200": clean(ma200),
                    "Trend": trend_status,
                    "Warning": warning_msg
                }
            }

        except Exception as e:
            print(f"Strategy Error: {e}")
            return self._default_result(f"Error: {str(e)}")

    def _default_result(self, reason):
        return {"signal": "HOLD", "confidence": 0.0, "reason": reason, "data": {}}