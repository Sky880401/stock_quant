# LINE Bot 快速參考卡片

## 🚀 30 秒快速開始

```bash
# 1. 複製配置文件
cp .env.example .env

# 2. 編輯 .env 並填入 4 個值:
# LINE_CHANNEL_SECRET=xxx
# LINE_CHANNEL_ACCESS_TOKEN=xxx
# GITHUB_TOKEN=xxx
# GITHUB_REPO=owner/repo

# 3. 安裝依賴
pip install -r requirements.txt

# 4. 運行應用
python line_webhook.py

# 5. 暴露 URL (開發)
ngrok http 5000

# 6. 配置 LINE Console
# Messaging API → Webhook URL → https://xxxxx.ngrok.io/webhook

# 7. 在 LINE 中測試
# !bug 測試消息
```

---

## 📝 消息格式速查

| 命令 | 範例 | 結果 |
|------|------|------|
| `!bug` | `!bug 命令出錯` | 建立 🐛 Bug Issue |
| `!suggest` | `!suggest 新增功能` | 建立 ✨ 改進 Issue |
| `!question` | `!question 如何用？` | 建立 ❓ 問題 Issue |
| `bug:` | `bug: 出現 NaN` | 建立 🐛 Bug Issue |
| `改進:` | `改進: 優化性能` | 建立 ✨ 改進 Issue |
| `問題:` | `問題: 配置問題` | 建立 ❓ 問題 Issue |

---

## 🔍 管理員 API 速查

### 統計信息
```bash
curl http://localhost:5000/feedback/stats
```

**回應**:
```json
{
  "total": 10,
  "by_type": {"bug": 4, "improvement": 3, "question": 3},
  "by_status": {"new": 5, "processing": 3, "resolved": 2}
}
```

### 最近反饋
```bash
curl "http://localhost:5000/feedback/list?limit=5"
```

### 健康檢查
```bash
curl http://localhost:5000/health
```

---

## 🔧 配置環境變數

| 變數 | 來源 | 說明 |
|------|------|------|
| `LINE_CHANNEL_SECRET` | LINE Console → Basic Settings | 頻道密鑰 |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Console → Basic Settings | 訪問令牌 |
| `GITHUB_TOKEN` | GitHub Settings → Tokens → Generate | 必須有 `repo` 和 `issues` 權限 |
| `GITHUB_REPO` | 您的倉庫 | 格式: `owner/repo` |

**獲取 LINE 憑證**:
1. 訪問 https://developers.line.biz/console
2. 選擇 Channel
3. 轉到 Messaging API
4. 複製 Channel Secret 和 Access Token

**獲取 GitHub Token**:
1. 訪問 https://github.com/settings/tokens
2. 點擊 Generate new token
3. 選擇 `repo` 和 `issues` 範圍
4. 複製 Token

---

## ⚙️ 部署選項對比

### 本地開發 (推薦用於測試)
```bash
python line_webhook.py
ngrok http 5000
```

### Heroku (推薦用於生產)
```bash
heroku create myapp
heroku config:set LINE_CHANNEL_SECRET=xxx
heroku config:set LINE_CHANNEL_ACCESS_TOKEN=xxx
heroku config:set GITHUB_TOKEN=xxx
heroku config:set GITHUB_REPO=owner/repo
git push heroku main
```

Webhook URL: `https://myapp.herokuapp.com/webhook`

### Docker (推薦用於自主服務器)
```bash
docker build -t linebot .
docker run -p 5000:5000 --env-file .env linebot
```

### Linux Systemd (推薦用於永久運行)
```bash
sudo systemctl start linebot
sudo systemctl status linebot
sudo journalctl -u linebot -f
```

---

## 🐛 常見問題

### Q: 不收到 LINE 消息？
**A**: 
1. 檢查 Webhook URL 在 LINE Console 是否已啟用
2. 運行 `curl http://localhost:5000/health` 確保應用運行
3. 檢查 ngrok 或服務器 URL 是否正確
4. 查看日誌: `heroku logs --tail` 或 `docker logs -f`

### Q: GitHub Issue 未建立？
**A**:
1. 驗證 GITHUB_TOKEN 有效 (試試 `curl -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user`)
2. 檢查倉庫名稱格式 (應為 `owner/repo`)
3. 確認 Token 具有 `repo` 和 `issues` 權限
4. 查看日誌中的錯誤消息

### Q: 拒絕看起來有效的消息？
**A**: 可能觸發了反垃圾機制:
- ❌ 內容少於 10 字
- ❌ 包含敏感詞或 URL
- ❌ 2 小時內有相似反饋
- ❌ 1 小時內已提交 5 個反饋

### Q: 如何重新啟動應用？
**A**:
```bash
# Heroku
heroku dyno:restart

# Docker
docker restart linebot

# Systemd
sudo systemctl restart linebot

# 本地開發
# Ctrl+C 然後重新運行
python line_webhook.py
```

---

## 📊 系統狀態監控

### 查看最近的日誌
```bash
# Heroku
heroku logs --tail -n 100

# Docker
docker logs --tail=100 -f linebot

# Systemd
sudo journalctl -u linebot -n 100 -f

# 本地
# 查看控制台輸出
```

### 監控反饋
```bash
# 每 30 秒檢查一次統計
watch -n 30 'curl -s http://localhost:5000/feedback/stats | jq'

# 或定期檢查
for i in {1..10}; do
  echo "檢查 $i:"
  curl http://localhost:5000/feedback/stats
  sleep 30
done
```

---

## 📁 檔案結構

```
/root/stock_quant/
├── line_bot.py              ← 核心邏輯
├── line_webhook.py          ← Web 服務
├── .env                     ← 配置 (私密，不提交)
├── .env.example             ← 配置模板
├── requirements.txt         ← 依賴
├── Procfile                 ← Heroku 配置
├── docker-compose.yml       ← Docker 配置
└── docs/
    ├── SETUP_LINE_BOT.md              ← 設置指南
    ├── DEPLOYMENT_GUIDE.md            ← 部署指南
    ├── TESTING_GUIDE.md               ← 測試指南
    └── LINE_BOT_SUMMARY.md            ← 完整總結
```

---

## 🧪 快速測試

### 本地測試
```bash
# 1. 啟動應用
python line_webhook.py &

# 2. 健康檢查
curl http://localhost:5000/health

# 3. 檢查統計
curl http://localhost:5000/feedback/stats

# 4. 停止應用
kill %1
```

### LINE 真實測試
1. 添加 Bot 為好友
2. 發送: `!bug 測試 bug 報告`
3. 驗證:
   - ✅ 收到確認消息
   - ✅ GitHub Issue 已建立 (#號碼)
   - ✅ data/line_feedback.json 已更新

---

## 🚨 緊急停止

```bash
# Heroku
heroku dyno:stop

# Docker
docker stop linebot

# Systemd
sudo systemctl stop linebot

# 本地
Ctrl+C
```

---

## 📞 更多幫助

- 完整設置指南: [SETUP_LINE_BOT.md](SETUP_LINE_BOT.md)
- 部署選項詳解: [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)
- 完整測試步驟: [TESTING_GUIDE.md](TESTING_GUIDE.md)
- 系統架構詳情: [LINE_BOT_SUMMARY.md](LINE_BOT_SUMMARY.md)

---

**最後更新**: 2025-01-31  
**版本**: 1.0.0  
**狀態**: ✅ 生產就緒

💡 **提示**: 將此文件存儲在方便的位置，以便快速參考！
