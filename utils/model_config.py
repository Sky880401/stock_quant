"""
AI 模型設定（執行期可切換）。
由 Discord `!model` 指令（限 bot owner）寫入，ai_runner / ai_engine 讀取。
存成 data/ai_model.json，重啟後保留選擇。
"""
import os
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(PROJECT_ROOT, "data", "ai_model.json")

# 預設模型（已驗證可用、回繁中正常）
DEFAULT_MODEL = "meta/llama-3.3-70b-instruct"

# 可選模型白名單：顯示名 -> (model_id, 說明)
AVAILABLE_MODELS = {
    "Llama 3.3 70B (平衡 · 預設)": ("meta/llama-3.3-70b-instruct", "速度與品質均衡，預設首選"),
    "Llama 4 Maverick (最新)":      ("meta/llama-4-maverick-17b-128e-instruct", "Meta 最新世代，長上下文"),
    "Qwen3-Next 80B (中文強)":      ("qwen/qwen3-next-80b-a3b-instruct", "中文理解佳、推理力強"),
    "Llama 3.1 8B (快 · 省)":       ("meta/llama-3.1-8b-instruct", "回應最快，適合簡單查詢"),
}

_VALID_IDS = {mid for mid, _ in AVAILABLE_MODELS.values()}


def get_model() -> str:
    """回傳目前選用的 model id；檔案不存在或無效時回預設。"""
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            mid = json.load(f).get("model")
        if mid in _VALID_IDS:
            return mid
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return DEFAULT_MODEL


def set_model(model_id: str) -> bool:
    """設定 model id；非白名單則拒絕並回 False。"""
    if model_id not in _VALID_IDS:
        return False
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"model": model_id}, f, ensure_ascii=False, indent=2)
    return True
