# LINE Bot 設置指南

## 📋 概述

本指南說明如何配置並部署 LINE Bot 反饋系統。該系統允許用戶通過 LINE Messaging 應用提交 bug、改進建議和問題，這些反饋會自動轉換為 GitHub Issue。

## 🔧 先決條件

1. **Python 環境**: Python 3.8+
2. **LINE 帳戶**: 個人或企業帳戶
3. **GitHub 帳戶**: 用於建立 Issues
4. **公共 IP 或 Ngrok**: LINE Webhook 需要公開 URL

## 📱 步驟 1: 建立 LINE Official Account

### 1.1 建立 LINE Developers 帳戶

1. 訪問 [LINE Developers](https://developers.line.biz/zh-hant/)
2. 點擊 **登入** (使用 LINE 帳戶)
3. 同意 LINE Developers 條款

### 1.2 建立 Provider

1. 訪問 [LINE Console](https://developers.line.biz/console)
2. 點擊 **建立**
3. 輸入 Provider 名稱 (例如: "Stock Quant Bot")

### 1.3 建立 Channel

1. 選擇您剛建立的 Provider
2. 點擊 **建立 Channel**
3. 選擇 **Line Official Account API**
4. 填寫 Channel 信息:
   - **Channel 名稱**: Stock Quant Bot
   - **Channel 類別**: 工具/工作效率
   - **頻道描述**: 用於股票量化交易的反饋系統

## 🔑 步驟 2: 獲取憑證

### 2.1 Channel Access Token

1. 在 Console 中選擇您的 Channel
2. 轉到 **Settings** → **Basic settings**
3. 向下滾動到 **Channel access token**
4. 點擊 **Issue** 按鈕

```bash
複製 Token: ChannelAccessToken_xxxxxxxxxxxxxxxx
```

### 2.2 Channel Secret

在同一頁面上找到 **Channel secret**:

```bash
複製 Secret: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 2.3 將憑證添加到 .env

```bash
# 複製 .env.example 到 .env
cp .env.example .env

# 編輯 .env 並填入:
LINE_CHANNEL_SECRET=your_channel_secret
LINE_CHANNEL_ACCESS_TOKEN=your_channel_access_token
```

## 🐙 步驟 3: GitHub 配置

### 3.1 建立 GitHub Personal Access Token

1. 訪問 [GitHub Settings → Tokens](https://github.com/settings/tokens)
2. 點擊 **Generate new token** (classic)
3. 填寫信息:
   - **Note**: Line Bot GitHub Access
   - **Expiration**: 無限制 (Recommended)
   - **Select scopes**: 
     - ✅ `repo` (完整控制)
     - ✅ `issues` (建立 Issue)

4. 點擊 **Generate token**
5. **複製 Token** (只會顯示一次)

### 3.2 在 .env 中添加 GitHub 配置

```bash
# .env
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
GITHUB_REPO=your_username/your_repo  # 例如: mojocolo/stock_quant
```

## 🌐 步驟 4: Webhook 配置

### 4.1 本地測試 (使用 Ngrok)

如果您在本地開發，需要暴露端口:

```bash
# 1. 安裝 ngrok
brew install ngrok  # macOS
# 或下載: https://ngrok.com/download

# 2. 啟動 ngrok
ngrok http 5000

# 複製轉發 URL: https://xxxxx.ngrok.io
```

### 4.2 配置 Webhook URL

1. 在 LINE Console 中選擇您的 Channel
2. 轉到 **Messaging API** 標籤
3. 找到 **Webhook settings**
4. 點擊 **Edit** 按鈕
5. 輸入 Webhook URL (使用 ngrok URL 進行本地測試):
   ```
   https://xxxxx.ngrok.io/webhook
   ```
6. 點擊 **Update** 並 **Enable**

## 🚀 步驟 5: 安裝依賴

```bash
# 安裝必要的 Python 包
pip install -r requirements.txt

# 確保包括:
# - line-bot-sdk
# - flask
# - python-dotenv
# - requests
```

## ▶️ 步驟 6: 運行 Bot

### 開發模式

```bash
python line_webhook.py
```

服務器將在 `http://localhost:5000` 啟動

### 測試 Webhook

1. 在 LINE Console 中，轉到 **Messaging API**
2. 找到 **Webhook settings** 下的 **Test** 按鈕
3. 點擊以發送測試事件 (應收到 200 OK)

## 📝 使用 Bot

### 添加 Bot 為好友

1. 在 LINE Console 中轉到 **Channel**
2. 向下滾動找到 **QR code**
3. 用 LINE 應用掃描或點擊鏈接

### 發送反饋

發送以下格式的消息:

```
!bug <標題>
<描述>

!suggest <標題>
<描述>

!question <標題>
<描述>
```

**中文別名也支持:**
```
bug: <標題>
改進: <標題>
問題: <標題>
```

## 📊 管理員操作

### 查看反饋統計

```bash
curl http://localhost:5000/feedback/stats
```

### 列出最近反饋

```bash
curl "http://localhost:5000/feedback/list?limit=10"
```

## 🐛 故障排除

### 問題: Webhook 未收到事件

**解決方案:**
1. 確認 Webhook URL 已啟用
2. 檢查 LINE Console 中的 Webhook logs
3. 確認 ngrok/服務器正在運行
4. 檢查防火牆設置

### 問題: GitHub Issue 未建立

**解決方案:**
1. 驗證 GITHUB_TOKEN 有效
2. 驗證 GITHUB_REPO 格式正確 (owner/repo)
3. 檢查 Token 具有 `repo` 和 `issues` 權限
4. 查看應用日誌中的錯誤

### 問題: InvalidSignatureError

**解決方案:**
1. 驗證 LINE_CHANNEL_SECRET 正確
2. 確認 .env 已加載
3. 檢查沒有空格或換行符

## 🔒 安全性最佳實踐

1. **不要將 .env 提交到 Git**
   ```bash
   # 確保 .gitignore 包含:
   echo ".env" >> .gitignore
   ```

2. **限制 GitHub Token 範圍**
   - 僅授予必要權限
   - 定期輪換 Token
   - 監控 Token 使用情況

3. **啟用 LINE 驗證**
   - 始終驗證 X-Line-Signature header
   - 使用 HTTPS
   - 限制 Webhook 訪問

## 📦 生產部署

### 使用 Gunicorn

```bash
pip install gunicorn

gunicorn line_webhook:app \
  --bind 0.0.0.0:8000 \
  --workers 4 \
  --threads 2 \
  --worker-class gthread
```

### 使用 Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
ENV FLASK_APP=line_webhook.py

CMD ["gunicorn", "line_webhook:app", "--bind", "0.0.0.0:5000"]
```

構建和運行:
```bash
docker build -t stock-quant-line-bot .
docker run -p 5000:5000 --env-file .env stock-quant-line-bot
```

### 反向代理 (Nginx)

```nginx
server {
    listen 443 ssl http2;
    server_name yourbot.example.com;

    ssl_certificate /etc/ssl/certs/your_cert.crt;
    ssl_certificate_key /etc/ssl/private/your_key.key;

    location /webhook {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /health {
        proxy_pass http://127.0.0.1:5000;
    }
}
```

## 📞 支援

如有問題，請查看:
- [LINE Developers 文檔](https://developers.line.biz/docs/)
- [line-bot-sdk GitHub](https://github.com/line/line-bot-sdk-python)
- [Stock Quant Issues](https://github.com/your_repo/issues)

---

**最後更新**: 2025-01-31
**版本**: 1.0.0
