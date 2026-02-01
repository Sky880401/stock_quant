# LINE Bot 部署指南

## 📋 概述

本指南說明如何將 LINE Bot 反饋系統部署到生產環境。系統將接收用戶反饋並自動建立 GitHub Issues。

---

## 🏗️ 部署架構

```
┌─────────────────────────────────────────────────────────────┐
│                       用戶端 (LINE App)                     │
└──────────────────────┬──────────────────────────────────────┘
                       │ LINE Messaging API
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   LINE Webhook Server                       │
│                (line_webhook.py - Flask)                    │
│                      :5000/webhook                          │
└──────────────────────┬──────────────────────────────────────┘
                       │ Validate & Parse
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              LINE Bot Logic (line_bot.py)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │FeedbackMgr   │  │ValidationMgr │  │GitHubMgr     │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└──────────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          │            │            │
          ▼            ▼            ▼
      [JSON File] [GitHub API] [LINE Reply]
  line_feedback.json
```

---

## 🚀 部署選項

### 選項 1: Heroku 部署 (推薦，免費)

#### 1.1 先決條件
- Heroku 帳戶 (免費)
- Heroku CLI 已安裝
- Git 已配置

#### 1.2 部署步驟

```bash
# 1. 登入 Heroku
heroku login

# 2. 建立 Heroku 應用
heroku create your-linebot-app

# 3. 設置環境變數
heroku config:set LINE_CHANNEL_SECRET=your_secret
heroku config:set LINE_CHANNEL_ACCESS_TOKEN=your_token
heroku config:set GITHUB_TOKEN=your_github_token
heroku config:set GITHUB_REPO=owner/repo

# 4. 部署 (自動從 Git 推送)
git push heroku main

# 5. 查看日誌
heroku logs --tail

# 6. 應用 URL
# 將此 URL 設置到 LINE Console: https://your-linebot-app.herokuapp.com/webhook
```

#### 1.3 Procfile

確保根目錄有 `Procfile`:
```
web: gunicorn line_webhook:app
```

---

### 選項 2: Docker 部署

#### 2.1 Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安裝依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用代碼
COPY . .

# 暴露端口
EXPOSE 5000

# 環境變數 (從 .env 或容器環境讀取)
ENV FLASK_APP=line_webhook.py
ENV PYTHONUNBUFFERED=1

# 健康檢查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# 運行應用
CMD ["gunicorn", \
     "line_webhook:app", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "4", \
     "--threads", "2", \
     "--worker-class", "gthread", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
```

#### 2.2 構建和運行

```bash
# 構建鏡像
docker build -t stock-quant-linebot .

# 本地運行 (用於測試)
docker run -p 5000:5000 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  stock-quant-linebot

# 推送到 Docker Hub
docker tag stock-quant-linebot your_username/stock-quant-linebot
docker push your_username/stock-quant-linebot

# 在遠程服務器拉取並運行
docker pull your_username/stock-quant-linebot
docker run -d -p 5000:5000 \
  --env-file .env \
  -v /data:/app/data \
  --restart unless-stopped \
  --name linebot \
  your_username/stock-quant-linebot
```

---

### 選項 3: Linux 服務器 + Systemd

#### 3.1 安裝依賴

```bash
# 安裝 Python 和 pip
sudo apt update
sudo apt install python3.11 python3-pip python3-venv

# 克隆倉庫
git clone https://github.com/your_username/stock_quant /opt/stock_quant
cd /opt/stock_quant

# 建立虛擬環境
python3 -m venv venv
source venv/bin/activate

# 安裝 Python 依賴
pip install -r requirements.txt
pip install gunicorn
```

#### 3.2 配置 Systemd 服務

創建 `/etc/systemd/system/linebot.service`:

```ini
[Unit]
Description=Stock Quant LINE Bot
After=network.target

[Service]
Type=notify
User=www-data
Group=www-data
WorkingDirectory=/opt/stock_quant

# 環境變數
EnvironmentFile=/opt/stock_quant/.env

# 啟動命令
ExecStart=/opt/stock_quant/venv/bin/gunicorn \
    line_webhook:app \
    --bind 127.0.0.1:5000 \
    --workers 4 \
    --timeout 120 \
    --access-logfile /var/log/linebot/access.log \
    --error-logfile /var/log/linebot/error.log

# 自動重啟
Restart=on-failure
RestartSec=5s

# 安全性
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

#### 3.3 啟動服務

```bash
# 建立日誌目錄
sudo mkdir -p /var/log/linebot
sudo chown www-data:www-data /var/log/linebot

# 重新加載 systemd
sudo systemctl daemon-reload

# 啟動服務
sudo systemctl start linebot

# 設置開機自啟
sudo systemctl enable linebot

# 查看狀態
sudo systemctl status linebot

# 查看日誌
sudo journalctl -u linebot -f
```

---

### 選項 4: Nginx 反向代理

#### 4.1 安裝 Nginx

```bash
sudo apt install nginx
```

#### 4.2 配置 Nginx

編輯 `/etc/nginx/sites-available/linebot.conf`:

```nginx
upstream linebot_app {
    server 127.0.0.1:5000;
    keepalive 64;
}

server {
    listen 80;
    server_name yourbotdomain.com;

    # 重定向到 HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourbotdomain.com;

    # SSL 證書 (從 Let's Encrypt 或其他來源)
    ssl_certificate /etc/letsencrypt/live/yourbotdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourbotdomain.com/privkey.pem;

    # SSL 配置
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # 日誌
    access_log /var/log/nginx/linebot.access.log combined;
    error_log /var/log/nginx/linebot.error.log warn;

    # LINE Webhook
    location /webhook {
        proxy_pass http://linebot_app;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # 健康檢查
    location /health {
        proxy_pass http://linebot_app;
        access_log off;
    }

    # 管理員端點 (可選，限制 IP)
    location /feedback {
        proxy_pass http://linebot_app;
        # 只允許特定 IP
        allow 203.0.113.0;  # 您的 IP
        deny all;
    }
}
```

#### 4.3 啟用站點

```bash
sudo ln -s /etc/nginx/sites-available/linebot.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

#### 4.4 配置 SSL (Let's Encrypt)

```bash
# 安裝 Certbot
sudo apt install certbot python3-certbot-nginx

# 獲取證書
sudo certbot certonly --nginx -d yourbotdomain.com

# 自動更新 (已包含在 certbot)
sudo systemctl enable certbot.timer
```

---

## 📊 監控和日誌

### 應用日誌

```bash
# Heroku
heroku logs --tail

# Systemd
sudo journalctl -u linebot -f

# Docker
docker logs -f linebot

# Nginx
tail -f /var/log/nginx/linebot.access.log
tail -f /var/log/nginx/linebot.error.log
```

### 監控指標

```bash
# 檢查反饋統計
curl https://yourbotdomain.com/feedback/stats

# 列出最近反饋
curl "https://yourbotdomain.com/feedback/list?limit=20"

# 健康檢查
curl https://yourbotdomain.com/health
```

---

## 🔐 安全性清單

- [ ] 使用 HTTPS (SSL/TLS)
- [ ] 環境變數安全存儲 (.env 不提交到 Git)
- [ ] GitHub Token 權限最小化 (僅 `repo` 和 `issues`)
- [ ] LINE Channel Secret 保密
- [ ] 定期更新依賴 (`pip install --upgrade -r requirements.txt`)
- [ ] 設置防火牆規則 (僅允許 LINE IP)
- [ ] 監控日誌以檢測異常
- [ ] 定期備份反饋數據 (data/line_feedback.json)

### LINE 官方 IP 地址

允許這些 IP 訪問您的 webhook:

```
203.104.144.0/24
203.104.145.0/24
203.104.146.0/24
```

配置 UFW (Ubuntu):
```bash
sudo ufw allow from 203.104.144.0/24
sudo ufw allow from 203.104.145.0/24
sudo ufw allow from 203.104.146.0/24
```

---

## 🔄 更新和維護

### 更新應用代碼

```bash
# 獲取最新代碼
git pull origin main

# 重啟應用
sudo systemctl restart linebot  # Systemd

# 或 Docker
docker pull your_username/stock-quant-linebot
docker stop linebot
docker rm linebot
docker run -d ... your_username/stock-quant-linebot
```

### 數據備份

```bash
# 定期備份反饋數據
cp data/line_feedback.json data/line_feedback.$(date +%Y%m%d_%H%M%S).json

# 自動備份 (Cron)
# 編輯: sudo crontab -e
# 添加: 0 */6 * * * cp /opt/stock_quant/data/line_feedback.json /backup/linebot_feedback_$(date +\%Y\%m\%d).json
```

---

## 🎯 測試清單

在部署到生產環境前，驗證以下內容:

- [ ] 啟動應用不出錯
- [ ] Health check 返回 200 OK
- [ ] LINE Webhook 簽名驗證成功
- [ ] 能接收並解析消息
- [ ] 能建立 GitHub Issues
- [ ] 反饋存儲到 JSON 文件
- [ ] 防垃圾機制有效
- [ ] 敏感詞過濾工作正常
- [ ] 用戶能收到回覆
- [ ] 管理員端點正常

---

## 📞 故障排除

### 常見問題

**問題**: Webhook 返回 401 Unauthorized

**解決方案**:
- 驗證 LINE_CHANNEL_SECRET 正確
- 驗證 LINE_CHANNEL_ACCESS_TOKEN 有效且未過期
- 檢查 X-Line-Signature header 驗證

**問題**: GitHub Issue 未建立

**解決方案**:
- 驗證 GITHUB_TOKEN 有效
- 驗證倉庫訪問權限
- 檢查 GITHUB_REPO 格式 (owner/repo)

**問題**: 高延遲或超時

**解決方案**:
- 增加 Gunicorn workers: `--workers 8`
- 增加超時: `--timeout 180`
- 檢查網絡連接

---

## 📈 性能優化

### 推薦配置

| 配置 | 開發 | 生產 |
|------|------|------|
| Workers | 1-2 | 4-8 |
| Threads/Worker | 1 | 2-4 |
| Timeout | 30s | 120s |
| Max Requests | 0 | 1000 |
| Buffer Size | 2048 | 8192 |

### Gunicorn 優化

```bash
gunicorn line_webhook:app \
  --workers 8 \
  --threads 4 \
  --worker-class gthread \
  --timeout 120 \
  --max-requests 1000 \
  --max-requests-jitter 100 \
  --access-logfile - \
  --error-logfile - \
  --log-level info
```

---

**最後更新**: 2025-01-31  
**版本**: 1.0.0
