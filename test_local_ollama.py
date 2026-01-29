import requests
import json

# 設定指向本地的 Ollama (VM 內部 IP 通常是 localhost 或 127.0.0.1)
url = "http://localhost:11434/api/generate"

payload = {
    "model": "llama3",  # 請確認您的模型名稱
    "prompt": "我是剛架好的 Rocky Linux 量化系統，請給我一句鼓勵的話。",
    "stream": False
}

try:
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        result = response.json()
        print("連線成功！本地模型回應：")
        print(result['response'])
    else:
        print(f"連線失敗: {response.status_code}, {response.text}")
except Exception as e:
    print(f"無法連線到 Ollama，請檢查 Port 11434 是否被防火牆擋住。\n錯誤訊息: {e}")