import os
from openai import OpenAI
from dotenv import load_dotenv

# 載入 .env 變數
load_dotenv()

class QuantBrain:
    def __init__(self):
        # 統一使用 NVIDIA API 作為唯一運算中心
        nv_key = os.getenv("NVIDIA_API_KEY")
        if not nv_key:
            print("⚠️ 警告: 未偵測到 NVIDIA_API_KEY，系統無法運作。")
        
        self.client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=nv_key
        )

    def analyze_market_report(self, context_data):
        """
        Mode A (戰略大腦): 使用 Llama 3.1 405B
        用途: 盤後深度分析、策略回測報告
        """
        print("🧠 [Mode A] 呼叫 NVIDIA (405B) 進行深度戰略分析...")
        try:
            response = self.client.chat.completions.create(
                model="meta/llama-3.3-70b-instruct",
                messages=[
                    {"role": "system", "content": "你是華爾街頂尖量化架構師。請根據傳入的 JSON 數據，撰寫一份專業的 Markdown 投資日報 (繁體中文)。重點分析：市場情緒、衝突訊號 (Technical vs Fundamental)、以及具體的買賣建議 (含止損位)。"},
                    {"role": "user", "content": context_data}
                ],
                temperature=0.2,  # 低隨機性，追求嚴謹
                max_tokens=4096   # 允許生成長篇報告
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"❌ 深度分析失敗: {e}"

    def quick_check(self, text):
        """
        Mode B (戰術執行): 使用 Llama 3.1 70B
        用途: 盤中即時問答、Discord 指令、訊號檢查
        優勢: 比 405B 快，比 Local 8B 聰明非常多
        """
        print("⚡ [Mode B] 呼叫 NVIDIA (70B) 進行盤中即時掃描...")
        try:
            response = self.client.chat.completions.create(
                model="meta/llama-3.3-70b-instruct",
                messages=[
                    {"role": "system", "content": "你是高頻交易員的助手。請用簡潔、果斷的語氣 (繁體中文) 回答盤中查詢。若涉及數據，請確保精準。"},
                    {"role": "user", "content": text}
                ],
                temperature=0.4, # 保持靈活但不過度發散
                max_tokens=1024  # 限制回應長度，提升回應速度
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"❌ 即時分析失敗: {e}"

    def strategy_consult(self, symbol, market_data_text):
        """
        Mode A+ (單點戰略): 注入即時數據
        """
        print(f"🧠 [Mode A+] 呼叫 NVIDIA (405B) 深度分析 {symbol}...")
        try:
            # 👇 關鍵修改：將即時數據塞入 Prompt
            prompt = f"""
            請針對 {symbol} 進行深度投資戰略分析。
            
            【即時市場數據】
            {market_data_text}
            
            【分析要求】
            1. 請**嚴格基於上述提供的數據**進行分析，嚴禁編造價格。
            2. 解讀目前市場情緒。
            3. 分析技術面與基本面是否有衝突。
            4. 給出具體操作建議 (進場/止損/獲利)，需符合目前股價位階。
            5. 使用繁體中文 Markdown 格式。
            """
            
            response = self.client.chat.completions.create(
                model="meta/llama-3.3-70b-instruct",
                messages=[
                    {"role": "system", "content": "你是華爾街對沖基金的首席策略師。你必須依據使用者提供的真實數據進行分析，不可產生幻覺。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2048
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"❌ 戰略分析失敗: {e}"