import os
from openai import OpenAI
from dotenv import load_dotenv

# 載入 .env 變數
load_dotenv()

class QuantBrain:
    def __init__(self):
        # 1. 初始化雲端大腦 (NVIDIA API) - 負責複雜分析
        # 如果沒有設定 key，會報錯提醒
        nv_key = os.getenv("NVIDIA_API_KEY")
        if not nv_key:
            print("⚠️ 警告: 未偵測到 NVIDIA_API_KEY，雲端功能將失效。")
        
        self.cloud_client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=nv_key
        )

        # 2. 初始化本地手腳 (Ollama) - 負責快速處理
        self.local_client = OpenAI(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            api_key="ollama"  # 本地不需要真實 Key
        )

    def analyze_market_report(self, context_data):
        """Mode A: 使用 NVIDIA Llama 3.1 405B 生成深度日報"""
        print("🧠 正在呼叫 NVIDIA Cloud (Llama 3.1 405B) 進行深度分析...")
        try:
            response = self.cloud_client.chat.completions.create(
                model="meta/llama-3.1-405b-instruct",
                messages=[
                    {"role": "system", "content": "你是華爾街量化架構師。請根據傳入的 JSON 數據，撰寫一份專業的 Markdown 投資日報 (繁體中文)。重點分析：市場情緒、衝突訊號 (Technical vs Fundamental)、以及具體的買賣建議。"},
                    {"role": "user", "content": context_data}
                ],
                temperature=0.2,
                max_tokens=2048
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"❌ 雲端分析失敗: {e}"

    def quick_check(self, text):
        """Mode B: 使用本地 Ollama (Llama 3.1) 進行快速回應"""
        print("⚡ 正在呼叫本地 Ollama (Llama 3.1) ...")
        try:
            response = self.local_client.chat.completions.create(
                model="llama3.1",
                messages=[
                    {"role": "user", "content": text}
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"❌ 本地分析失敗: {e}"