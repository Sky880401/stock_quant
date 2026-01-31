import logging
from langchain_community.llms import Ollama
from langchain_core.prompts import PromptTemplate

# 若要使用 NVIDIA API，可解除以下註解並替換 implementation
# from langchain_nvidia_ai_endpoints import ChatNVIDIA

class QuantAnalystAgent:
    def __init__(self, model_name="llama3.3", temperature=0.2):
        """
        初始化量化分析 Agent
        :param model_name: Ollama 模型名稱 (e.g., 'llama3.3', 'deepseek-r1')
        :param temperature: 溫度設低 (0.2) 以確保分析客觀、減少幻覺
        """
        self.model_name = model_name
        self.logger = logging.getLogger(__name__)
        
        # 初始化 LLM (本地 Ollama)
        try:
            self.llm = Ollama(model=model_name, temperature=temperature)
            self.logger.info(f"🧠 AI Agent initialized with model: {model_name}")
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize Ollama: {e}")
            raise e

    def _build_prompt(self, ticker, context, signal_data):
        """
        建構「量化架構師」專用的 Prompt
        """
        template = """
        # Role: The Quant Architect (AI Financial Strategist)
        你是由頂尖對沖基金開發的「量化架構師」。你的任務是根據提供的【市場數據】與【演算法訊號】，撰寫一份專業的「深度投資戰略報告」。

        ## 1. Input Data (市場數據)
        * **標的 (Ticker)**: {ticker}
        * **最新收盤 (Close)**: {close}
        * **成交量 (Volume)**: {volume}
        * **MA5 (短線成本)**: {ma5}
        * **MA20 (月線支撐)**: {ma20}
        * **MA60 (季線趨勢)**: {ma60}
        * **RSI (相對強弱)**: {rsi}
        * **ATR (波動率)**: {atr}

        ## 2. Algo Signal (演算法訊號)
        * **主要訊號**: {action}
        * **建議止損 (Stop Loss)**: {stop_loss}
        * **建議目標 (Target)**: {target_price}

        ## 3. Instructions (執行準則)
        請嚴格遵守以下邏輯進行分析（不要只看訊號，要尋找數據中的矛盾）：
        1.  **市場情緒判定**：
            * 若 收盤價 < MA5 且 MA5 下彎 -> 定義為「短線修正」。
            * 若 收盤價 > MA20 且 MA20 > MA60 -> 定義為「中長線多頭」。
        2.  **衝突分析 (Conflict Check)**：**最重要的一步！**
            * 檢查「演算法訊號」與「趨勢」是否衝突？（例如：訊號是 BUY，但股價跌破 MA60）。
            * 檢查 RSI 是否過熱 (>75) 或過冷 (<25)。
            * 若發現矛盾，必須在報告中標註 `⚠️ Warning`。
        3.  **操作建議 (Action Plan)**：
            * 基於 ATR 計算風險回報比 (RR Ratio)。
            * 必須給出明確的「進場區間」、「止損價位」與「獲利目標」。

        ## 4. Output Format (Markdown Report)
        請使用 **繁體中文 (Traditional Chinese)**，並依照以下格式輸出：

        # 📊 {ticker} 深度戰略報告 (Quant Architect Edition)
        =======================================================

        ### 1. Executive Summary (市場情緒)
        [簡述目前多空趨勢，必須引用 MA 排列狀況]

        ### 2. Deep Dive Analysis (技術面深度解析)
        * **均線系統**：[分析 MA5, MA20, MA60 的乖離與支撐壓力]
        * **動能指標**：RSI 目前數值為 {rsi}，顯示 [超買/超賣/中性]。
        * **籌碼/量能**：[若成交量異常請在此說明，若無則略過]

        ### 3. Conflict Alert (衝突警示)
        [若無衝突請寫「✅ 指標共振，無明顯衝突」。若有，請寫「⚠️ 訊號矛盾：...」]

        ### 4. Strategic Action (戰略操作)
        * **訊號判定**: **{action}**
        * **進場策略**: [具體進場價位區間]
        * **風控防線 (Stop Loss)**: {stop_loss} (基於 ATR 動態止損)
        * **獲利目標 (Take Profit)**: {target_price}
        * **風險評估**: [請計算並說明此筆交易的 RR Ratio 是否合理]

        (End of Report)
        """
        
        # 處理可能的 None 值，避免報錯
        safe_context = {k: (v if v is not None else "N/A") for k, v in context.items()}
        safe_signal = {k: (v if v is not None else "N/A") for k, v in signal_data.items()}

        prompt = PromptTemplate(
            template=template,
            input_variables=["ticker", "close", "volume", "ma5", "ma20", "ma60", "rsi", "atr", "action", "stop_loss", "target_price"]
        )

        return prompt.format(
            ticker=ticker,
            close=safe_context.get('close'),
            volume=safe_context.get('volume'),
            ma5=safe_context.get('ma5'),
            ma20=safe_context.get('ma20'),
            ma60=safe_context.get('ma60'),
            rsi=safe_context.get('rsi'),
            atr=safe_context.get('atr'),
            action=safe_signal.get('action'),
            stop_loss=safe_signal.get('suggested_stop', safe_signal.get('stop_loss')), # 兼容不同 key
            target_price=safe_signal.get('suggested_target', safe_signal.get('target_price'))
        )

    def generate_deep_report(self, ticker, market_context, signal_data):
        """
        執行生成任務
        """
        try:
            self.logger.info(f"🧠 AI Analyst starts thinking for {ticker}...")
            
            # 1. 建構 Prompt
            final_prompt = self._build_prompt(ticker, market_context, signal_data)
            
            # 2. 呼叫模型
            response = self.llm.invoke(final_prompt)
            
            return response

        except Exception as e:
            self.logger.error(f"❌ AI Generation Error: {e}")
            return f"⚠️ 無法生成報告，系統錯誤: {str(e)}"

# 測試用
if __name__ == "__main__":
    # 模擬數據
    dummy_context = {
        "close": 1775.0, "volume": 35000, 
        "ma5": 1787.0, "ma20": 1734.0, "ma60": 1551.0, 
        "rsi": 62.5, "atr": 25.0
    }
    dummy_signal = {
        "action": "WAIT", 
        "suggested_stop": 1725.0, 
        "suggested_target": 1850.0
    }
    
    agent = QuantAnalystAgent(model_name="llama3.3")
    print(agent.generate_deep_report("2330.TW", dummy_context, dummy_signal))