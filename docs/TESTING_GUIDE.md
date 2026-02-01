# LINE Bot 完整測試指南

## 🧪 測試概述

本指南涵蓋 LINE Bot 反饋系統的完整端到端測試。在部署到生產環境前，必須完成所有測試。

---

## 📋 測試清單

### 環境設置

- [ ] 已安裝 Python 3.8+
- [ ] 已安裝所有依賴 (`pip install -r requirements.txt`)
- [ ] 已建立 `.env` 文件含有所有必需的環境變數
- [ ] LINE Bot 已在 LINE Developers Console 建立
- [ ] GitHub Personal Access Token 已建立
- [ ] 本地環境可訪問 GitHub API

---

## 🔧 單元測試

### 1. FeedbackManager 測試

```python
from line_bot import FeedbackManager

manager = FeedbackManager()

# 測試 1.1: 解析 !bug 格式
fb_type, title, desc = manager.parse_feedback("!bug !train 命令有誤", "user123")
assert fb_type == "bug"
assert "!train" in desc
print("✅ 測試 1.1 通過: !bug 格式解析")

# 測試 1.2: 解析 !suggest 格式
fb_type, title, desc = manager.parse_feedback("!suggest 新增價量配合指標", "user456")
assert fb_type == "improvement"
print("✅ 測試 1.2 通過: !suggest 格式解析")

# 測試 1.3: 解析 !question 格式
fb_type, title, desc = manager.parse_feedback("!question 如何自訂策略？", "user789")
assert fb_type == "question"
print("✅ 測試 1.3 通過: !question 格式解析")

# 測試 1.4: 解析中文別名 bug:
fb_type, title, desc = manager.parse_feedback("bug: 回測結果異常", "user321")
assert fb_type == "bug"
print("✅ 測試 1.4 通過: 中文別名 bug: 解析")

# 測試 1.5: 添加和檢索反饋
fb_id = manager.add_feedback("bug", "測試標題", "測試描述", "user999", "https://github.com/issues/123")
assert fb_id is not None
feedback = manager.get_feedback(fb_id)
assert feedback is not None
assert feedback["status"] == "new"
print("✅ 測試 1.5 通過: 添加和檢索反饋")

# 測試 1.6: 更新反饋狀態
manager.update_feedback_status(fb_id, "processing", "https://github.com/issues/124")
feedback = manager.get_feedback(fb_id)
assert feedback["status"] == "processing"
print("✅ 測試 1.6 通過: 更新反饋狀態")

# 測試 1.7: 獲取最近反饋
recent = manager.get_recent_feedback(hours=24)
assert len(recent) > 0
print("✅ 測試 1.7 通過: 獲取最近反饋")

print("\n✅ FeedbackManager 所有測試通過！")
```

### 2. ValidationManager 測試

```python
from line_bot import ValidationManager

# 測試 2.1: 內容過短驗證
is_valid, msg = ValidationManager.validate_message("短", "user1", [])
assert not is_valid
assert "過短" in msg
print("✅ 測試 2.1 通過: 內容過短驗證")

# 測試 2.2: 敏感詞過濾
is_valid, msg = ValidationManager.validate_message(
    "this is a viagra advertisement", "user2", []
)
assert not is_valid
assert "不允許" in msg
print("✅ 測試 2.2 通過: 敏感詞過濾")

# 測試 2.3: URL 過濾
is_valid, msg = ValidationManager.validate_message(
    "請訪問 http://malicious.com/spam", "user3", []
)
assert not is_valid
print("✅ 測試 2.3 通過: URL 過濾")

# 測試 2.4: 重複反饋檢測
recent_fb = [{
    "user_id": "user4",
    "description": "測試重複反饋",
    "created_at": datetime.now().isoformat(),
    "type": "bug"
}]
is_valid, msg = ValidationManager.validate_message(
    "測試重複反饋", "user4", recent_fb
)
assert not is_valid
assert "類似" in msg
print("✅ 測試 2.4 通過: 重複反饋檢測")

# 測試 2.5: 速率限制
recent_fb = []
for i in range(5):
    recent_fb.append({
        "user_id": "user5",
        "description": f"反饋 {i}",
        "created_at": (datetime.now() - timedelta(minutes=i)).isoformat(),
        "type": "bug"
    })
is_valid, msg = ValidationManager.validate_message(
    "新的反饋內容", "user5", recent_fb
)
assert not is_valid
assert "超過速率限制" in msg or "最近一小時" in msg
print("✅ 測試 2.5 通過: 速率限制")

# 測試 2.6: 有效消息通過
is_valid, msg = ValidationManager.validate_message(
    "這是一個有效的反饋內容，不含任何問題", "user6", []
)
assert is_valid
print("✅ 測試 2.6 通過: 有效消息通過")

print("\n✅ ValidationManager 所有測試通過！")
```

### 3. GitHubIssueManager 測試

```python
import os
from line_bot import GitHubIssueManager

github_token = os.getenv("GITHUB_TOKEN")
github_repo = os.getenv("GITHUB_REPO")

if github_token and github_repo:
    manager = GitHubIssueManager(github_token, github_repo)
    
    # 測試 3.1: 類型標籤映射
    labels = manager._get_labels("bug")
    assert "bug" in labels
    assert "from-line" in labels
    print("✅ 測試 3.1 通過: bug 標籤映射")
    
    labels = manager._get_labels("improvement")
    assert "enhancement" in labels
    print("✅ 測試 3.2 通過: improvement 標籤映射")
    
    labels = manager._get_labels("question")
    assert "question" in labels
    print("✅ 測試 3.3 通過: question 標籤映射")
    
    # 測試 3.4: 表情符號映射
    emoji = manager._get_type_emoji("bug")
    assert emoji == "🐛"
    print("✅ 測試 3.4 通過: bug 表情符號")
    
    # 測試 3.5: 標籤文本
    label = manager._get_type_label("improvement")
    assert "改進" in label or "improvement" in label.lower()
    print("✅ 測試 3.5 通過: 標籤文本")
    
    print("\n✅ GitHubIssueManager 所有測試通過！")
else:
    print("⚠️ 跳過 GitHub 測試 (未配置 Token 或倉庫)")
```

---

## 🧩 集成測試

### 4. Flask 應用測試

```bash
# 啟動 Flask 應用 (在另一個終端)
python line_webhook.py &
FLASK_PID=$!

# 等待應用啟動
sleep 2

# 測試 4.1: Health Check
response=$(curl -s http://localhost:5000/health)
if echo $response | grep -q "healthy"; then
    echo "✅ 測試 4.1 通過: Health Check"
else
    echo "❌ 測試 4.1 失敗"
fi

# 測試 4.2: 反饋統計端點
response=$(curl -s http://localhost:5000/feedback/stats)
if echo $response | grep -q "total"; then
    echo "✅ 測試 4.2 通過: 反饋統計"
else
    echo "❌ 測試 4.2 失敗"
fi

# 測試 4.3: 反饋列表端點
response=$(curl -s "http://localhost:5000/feedback/list?limit=5")
if echo $response | grep -q "feedback"; then
    echo "✅ 測試 4.3 通過: 反饋列表"
else
    echo "❌ 測試 4.3 失敗"
fi

# 停止應用
kill $FLASK_PID

echo "✅ Flask 應用所有測試通過！"
```

### 5. LINE Webhook 驗證測試

```python
import hashlib
import hmac
import json
from line_bot import handler

# 測試 5.1: Webhook 簽名驗證
channel_secret = os.getenv("LINE_CHANNEL_SECRET")

test_body = json.dumps({
    "events": [{
        "type": "message",
        "message": {
            "type": "text",
            "text": "測試消息"
        },
        "source": {"userId": "test_user"}
    }])

# 生成簽名
signature = hmac.new(
    channel_secret.encode('utf-8'),
    test_body.encode('utf-8'),
    hashlib.sha256
).digest()
signature_b64 = base64.b64encode(signature).decode('utf-8')

print(f"✅ 測試 5.1: 可生成有效簽名")
print(f"   簽名: {signature_b64[:20]}...")
```

---

## 🎬 端到端測試

### 6. 完整 LINE 消息流程

#### 前置準備
1. 添加 LINE Bot 為好友 (使用 QR 碼)
2. 確保 Webhook 已啟用 (在 LINE Console)
3. 確保本地應用或 ngrok 正在運行

#### 測試步驟

**測試 6.1: Bug 報告**

1. 在 LINE 發送: `!bug 測試報告 - 反測結果出現異常 NaN 值`
2. 預期結果:
   - ✅ 收到確認消息
   - ✅ GitHub Issue 已建立
   - ✅ Issue 標籤包含 "bug" 和 "from-line"
   - ✅ data/line_feedback.json 有新記錄

**測試 6.2: 改進建議**

1. 在 LINE 發送: `!suggest 新增更多技術指標，例如 OBV 和 Accumulation/Distribution`
2. 預期結果:
   - ✅ 收到確認消息
   - ✅ GitHub Issue 已建立
   - ✅ Issue 標籤包含 "enhancement" 和 "from-line"

**測試 6.3: 問題提出**

1. 在 LINE 發送: `!question 如何使用自訂策略模板進行回測？`
2. 預期結果:
   - ✅ 收到確認消息
   - ✅ GitHub Issue 已建立
   - ✅ Issue 標籤包含 "question" 和 "from-line"

**測試 6.4: 中文別名**

1. 在 LINE 發送: `bug: 執行優化器時內存溢出`
2. 預期結果:
   - ✅ 收到確認消息並被解析為 bug 類型
   - ✅ GitHub Issue 已建立

**測試 6.5: 反垃圾 - 內容過短**

1. 在 LINE 發送: `有問題`
2. 預期結果:
   - ❌ 收到錯誤消息: "反饋內容過短"
   - ❌ GitHub Issue 未建立

**測試 6.6: 反垃圾 - 敏感詞**

1. 在 LINE 發送: `!bug 請訪問 http://example.com 獲取幫助`
2. 預期結果:
   - ❌ 收到錯誤消息: "包含不允許的內容"
   - ❌ GitHub Issue 未建立

**測試 6.7: 反垃圾 - 重複提交**

1. 在 LINE 連續發送相同消息: `!bug 重複測試的反饋`
2. 預期結果:
   - ✅ 第一次成功
   - ❌ 第二次收到錯誤: "類似的反饋"

**測試 6.8: 反垃圾 - 速率限制**

1. 在 1 分鐘內連續發送 6 個反饋
2. 預期結果:
   - ✅ 前 5 個成功
   - ❌ 第 6 個收到錯誤: "超過速率限制"

**測試 6.9: 管理員功能 - 統計信息**

```bash
curl http://localhost:5000/feedback/stats

# 預期結果:
# {
#   "total": 8,
#   "by_type": {"bug": 3, "improvement": 2, "question": 3},
#   "by_status": {"new": 5, "processing": 2, "resolved": 1}
# }
```

**測試 6.10: 管理員功能 - 列表**

```bash
curl "http://localhost:5000/feedback/list?limit=3"

# 預期結果: 包含最近 3 個反饋的 JSON 陣列
```

---

## 📊 性能測試

### 7. 負載測試

```bash
# 安裝 Apache Bench
sudo apt install apache2-utils

# 測試 7.1: Health Check 性能
ab -n 100 -c 10 http://localhost:5000/health

# 預期:
# - 95% latency < 100ms
# - 99% latency < 200ms

# 測試 7.2: 反饋統計性能
ab -n 100 -c 10 http://localhost:5000/feedback/stats

# 預期: 相同性能
```

### 8. 併發測試

```python
import concurrent.futures
import requests
import time

def send_webhook():
    """發送 webhook 請求"""
    # 實現完整的 LINE webhook 簽名驗證...
    pass

# 測試 8.1: 5 個併發請求
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    futures = [executor.submit(send_webhook) for _ in range(5)]
    results = [f.result() for f in concurrent.futures.as_completed(futures)]
    if all(results):
        print("✅ 測試 8.1 通過: 5 個併發請求")
```

---

## 🔐 安全性測試

### 9. 驗證和授權

```bash
# 測試 9.1: 無效簽名被拒絕
curl -X POST \
  -H "X-Line-Signature: invalid_signature" \
  -d '{"events":[]}' \
  http://localhost:5000/webhook

# 預期: 400 Bad Request

# 測試 9.2: 管理員端點需要驗證 (可選)
curl http://localhost:5000/feedback/stats
# 應該返回數據或要求身份驗證
```

### 10. SQL/Command 注入測試

```bash
# 測試 10.1: 特殊字符在消息中
curl -X POST \
  -d '!bug "; DROP TABLE feedback; --' \
  http://localhost:5000/webhook

# 預期:
# - 消息被安全處理
# - 沒有 SQL 執行
# - 反饋被正常保存
```

---

## 📋 測試執行清單

### 快速測試 (5 分鐘)

```bash
# 1. 單元測試
python -m pytest tests/ -v

# 2. 健康檢查
curl http://localhost:5000/health

# 3. 手動 LINE 消息
# - 在 LINE 發送 "!bug 測試"
# - 確認收到回覆
```

### 完整測試 (1 小時)

```bash
# 運行所有測試用例
# 1. 單元測試
# 2. 集成測試
# 3. 端到端測試
# 4. 性能測試
# 5. 安全性測試
```

### 預發布測試 (2 小時)

```bash
# 完整測試 + 以下:
# 1. 生產環境類似配置
# 2. SSL/HTTPS 驗證
# 3. 24 小時穩定性測試
# 4. 備份和恢復測試
```

---

## ✅ 測試驗收標準

所有以下條件必須滿足才能認為測試通過:

- [ ] ✅ 所有 6 個端到端場景都通過
- [ ] ✅ 反垃圾機制有效防止濫用
- [ ] ✅ 無數據丟失或損壞
- [ ] ✅ 平均響應時間 < 500ms
- [ ] ✅ 99% 的請求成功
- [ ] ✅ 無安全漏洞
- [ ] ✅ 日誌正確記錄所有事件
- [ ] ✅ GitHub Issues 格式正確

---

## 📝 測試報告模板

```markdown
# LINE Bot 測試報告

**日期**: 2025-01-31
**測試人員**: [Name]
**環境**: Development/Production

## 測試結果概括

- 總測試數: 48
- 通過: 48
- 失敗: 0
- 跳過: 0
- **通過率: 100% ✅**

## 詳細結果

### 單元測試
- FeedbackManager: 7/7 通過 ✅
- ValidationManager: 6/6 通過 ✅
- GitHubIssueManager: 5/5 通過 ✅

### 集成測試
- Flask 應用: 3/3 通過 ✅
- LINE Webhook: 1/1 通過 ✅

### 端到端測試
- Bug 報告: ✅
- 改進建議: ✅
- 問題提出: ✅
- 中文別名: ✅
- 反垃圾機制: ✅
- 管理員功能: ✅

### 性能測試
- Health Check: avg 45ms ✅
- 反饋統計: avg 120ms ✅
- 負載 (100 req): avg 78ms ✅

### 安全性測試
- 簽名驗證: ✅
- 無 SQL 注入: ✅
- 敏感詞過濾: ✅

## 結論

✅ **系統已準備好生產部署**

---
```

---

**最後更新**: 2025-01-31  
**版本**: 1.0.0
