import sys
import os
import time
from pathlib import Path
from dotenv import load_dotenv
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from utils.model_config import get_model

# === 環境變數載入 ===
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
env_path = Path(PROJECT_ROOT) / '.env'
load_dotenv(dotenv_path=env_path, override=True)

# 依模型快取 client，避免每次查詢都新建 ChatNVIDIA(底層 httpx 連線池)造成記憶體/連線洩漏。
# !model 切換時會用不同 key 取得對應 client；數量有界(可用模型數)。
_CLIENT_CACHE = {}


def get_nvidia_client():
    """初始化 NVIDIA 客戶端（模型由 !model 指令切換，預設 Llama 3.3 70B）。同模型重用同一 client。"""
    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        print("❌ Error: NVIDIA_API_KEY missing.")
        return None

    model = get_model()
    client = _CLIENT_CACHE.get(model)
    if client is None:
        client = ChatNVIDIA(
            model=model,
            api_key=api_key,
            temperature=0.2,
            top_p=0.7,
            max_tokens=4096
        )
        _CLIENT_CACHE[model] = client
    return client

def generate_insight(prompt_content: str) -> str:
    """
    [新功能] 提供給 Discord 呼叫的即時分析接口
    """
    llm = get_nvidia_client()
    if not llm:
        return "❌ 系統錯誤：無法連接 AI 大腦 (API Key Missing)"

    try:
        print("   [AI] Thinking (405B)...")
        response = llm.invoke(prompt_content)
        return response.content if hasattr(response, 'content') else str(response)
    except Exception as e:
        return f"❌ AI 推理失敗: {str(e)}"

# 保留舊有的檔案批次處理功能 (供 main.py 使用)
def run_cloud_analysis():
    print(f"=== Starting AI Analysis (Batch Mode) ===")
    INPUT_MISSION = os.path.join(PROJECT_ROOT, "data/moltbot_mission.txt")
    OUTPUT_REPORT_DIR = os.path.join(PROJECT_ROOT, "reports")

    if not os.path.exists(INPUT_MISSION):
        print("❌ No mission file found.")
        return

    with open(INPUT_MISSION, "r", encoding="utf-8") as f:
        mission_content = f.read()

    report_content = generate_insight(mission_content)

    os.makedirs(OUTPUT_REPORT_DIR, exist_ok=True)
    today_str = time.strftime("%Y%m%d")
    report_path = os.path.join(OUTPUT_REPORT_DIR, f"daily_summary_{today_str}_nvidia.md")
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)
    print(f"✅ Report saved to: {report_path}")

if __name__ == "__main__":
    run_cloud_analysis()
