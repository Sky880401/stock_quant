import sys
import os
import time
from pathlib import Path
from dotenv import load_dotenv
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_core.prompts import ChatPromptTemplate

# === 環境變數載入 (Critical Fix) ===
# 強制載入專案根目錄下的 .env 檔案
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
env_path = Path(PROJECT_ROOT) / '.env'
load_dotenv(dotenv_path=env_path, override=True)

# === 配置區 ===
MODEL_NAME = "meta/llama-3.1-405b-instruct"
INPUT_MISSION = os.path.join(PROJECT_ROOT, "data/moltbot_mission.txt")
OUTPUT_REPORT_DIR = os.path.join(PROJECT_ROOT, "reports")

def run_cloud_analysis():
    print(f"=== Starting AI Analysis (Architecture: NVIDIA Cloud Only) ===")
    
    # 1. 驗證 API Key
    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        print("❌ Fatal Error: 'NVIDIA_API_KEY' not found in .env or environment variables.")
        print(f"   Looking for .env at: {env_path}")
        sys.exit(1)

    # 2. 檢查任務檔
    if not os.path.exists(INPUT_MISSION):
        print(f"❌ Error: Mission file '{INPUT_MISSION}' not found.")
        print("   Please run 'main.py' to generate data first.")
        return

    with open(INPUT_MISSION, "r", encoding="utf-8") as f:
        mission_content = f.read()

    # 3. 初始化 NVIDIA 405B 模型
    try:
        llm = ChatNVIDIA(
            model=MODEL_NAME,
            api_key=api_key,
            temperature=0.2,
            top_p=0.7,
            max_completion_tokens=4096
        )
        print(f"🚀 Connected to NVIDIA NIM ({MODEL_NAME})")
    except Exception as e:
        print(f"❌ Connection Failed: {e}")
        return

    # 4. 執行雲端推論
    print("   [Cloud] Uploading context & reasoning...")
    start_time = time.time()
    
    try:
        response = llm.invoke(mission_content)
        report_content = response.content if hasattr(response, 'content') else str(response)
    except Exception as e:
        print(f"❌ Inference Error: {e}")
        return

    elapsed = time.time() - start_time
    print(f"   [Cloud] Analysis complete in {elapsed:.2f}s.")

    # 5. 存檔
    os.makedirs(OUTPUT_REPORT_DIR, exist_ok=True)
    today_str = time.strftime("%Y%m%d") # 格式化日期
    report_path = os.path.join(OUTPUT_REPORT_DIR, f"daily_summary_{today_str}_nvidia.md")
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)
        
    print(f"✅ Report saved to: {report_path}")

if __name__ == "__main__":
    run_cloud_analysis()
