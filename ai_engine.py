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
        Mode A (重型坦克): 使用 Llama 3.1 405B
        用途: 盤後深度分析、策略回測報告
        """
        print("🧠 [Mode A] 呼叫 NVIDIA (405B) 進行深度戰略分析...")
        try:
            response = self.client.chat.completions.create(
                model="meta/llama-3.1-405b-instruct",
                messages=[
                    {"role": "system", "content": "你是華爾街頂尖量化架構師。請根據傳入的 JSON 數據，撰寫一份專業的 Markdown 投資日報 (繁體中文)。重點分析：市場情緒、衝突訊號 (Technical vs Fundamental)、以及具體的買賣建議 (含止損位)。"},
                    {"role": "user", "content": context_data}
                ],
                temperature=0.2, # 低隨機性，追求嚴謹
                max_tokens=2048
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"❌ 深度分析失敗: {e}"

    def quick_check(self, text):
        """
        Mode B (快速反應部隊): 使用 Llama 3.1 70B
        用途: 盤中即時問答、Discord 指令、訊號檢查
        優勢: 速度比 405B 快，準度遠勝 Local 8B
        """
        print("⚡ [Mode B] 呼叫 NVIDIA (70B) 進行盤中即時掃描...")
        try:
            response = self.client.chat.completions.create(
                # 這裡改用 70B 模型，速度與智商的最佳平衡點
                model="meta/llama-3.1-70b-instruct", 
                messages=[
                    {"role": "system", "content": "你是高頻交易員的助手。請用簡潔、果斷的語氣 (繁體中文) 回答盤中查詢。若涉及數據，請確保精準。"},
                    {"role": "user", "content": text}
                ],
                temperature=0.5, # 稍微靈活一點
                max_tokens=512   # 回答短一點，速度優先
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"❌ 即時分析失敗: {e}"