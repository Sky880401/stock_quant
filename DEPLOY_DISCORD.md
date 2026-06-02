# Stock Quant — Discord 部署指南（主要平台）

> 架構決策：**Discord 為主**（見 `ARCHITECTURE_MULTIPLATFORM_V1.md`）。
> Discord bot 走 Gateway **對外 WebSocket 連線，不需要任何公開網域 / 不開任何對外埠**，
> 因此跟 `project-manager`（Tailscale Funnel 佔 443）**完全不衝突**，是最省、最乾淨的路。

---

## 0. 與 project-manager 的隔離關係

| 項目 | project-manager | stock_quant (Discord) | 衝突 |
|---|---|---|---|
| 對外通道 | Tailscale Funnel 443 → 8000 | **不需要**（Gateway 外連） | ❌ 無 |
| 對外埠 | 8000（經 Funnel） | **不開任何埠** | ❌ 無 |
| 框架 | FastAPI/uvicorn | discord.py（無 web 伺服器） | ❌ 無 |
| 資料 | LXC `data/*.db` | 自己的 `data/*.json` | ❌ 無 |
| 執行管家 | BMO worker（workspace 寫死 project-manager） | 自己的 discord_runner | ⚠️ 各自獨立，勿共用 |

> 結論：**只要不塞進同一個 LXC 跟 project-manager 搶 CPU/記憶體**，零衝突。
> 量化回測/ML 很吃 CPU，建議獨立容器，避免拖垮專案管理 bot。

---

## 1. 部署位置（建議）

**Proxmox 上新開一個 LXC 容器**（例如 #106），跟 project-manager #105 平行。
- 量化運算吃資源 → 獨立容器，故障/負載互不影響。
- Discord 不需網域 → 不必碰 Tailscale Funnel / nginx / cloudflared（repo 內的 `nginx.conf`、`cloudflared.deb`、`docker-compose.yml` 是 LINE/web 時代的產物，Discord-only 用不到）。

> 若暫時不想開新容器，也可先跑在 bmo(Mac) 用 launchd 驗證（見 §6）。

---

## 2. 系統相依（Debian LXC）

```bash
apt update
apt install -y python3-venv python3-pip git build-essential
# TA-Lib 需要 C 函式庫（pip 的 TA-Lib 只是 wrapper）
apt install -y ta-lib   # 若該 repo 沒有，改用原始碼編譯（見下）
```

TA-Lib 若 apt 找不到，原始碼編譯：
```bash
wget https://github.com/ta-lib/ta-lib/releases/download/v0.6.4/ta-lib_0.6.4_amd64.deb
dpkg -i ta-lib_0.6.4_amd64.deb
```

> ⚠️ Python 版本：建議用 **3.11 / 3.12**。bmo 本機是 3.14，`backtrader`、`TA-Lib` 在 3.14 上可能有相容問題；LXC 用穩定版較保險。

---

## 3. 取得程式碼與套件

```bash
cd /root
git clone https://github.com/Sky880401/stock_quant.git
cd stock_quant
python3 -m venv venv
venv/bin/pip install -U pip
venv/bin/pip install -r requirements.txt   # 已補上 discord.py / TA-Lib / yfinance / nvidia 等
```

---

## 4. 設定 .env

```bash
cp .env.example .env
nano .env
```
Discord-only 最少需要：
- `DISCORD_TOKEN`：Discord Developer Portal → Applications → 你的 App → Bot → Reset Token
  - **務必開啟 Bot 的 `MESSAGE CONTENT INTENT`**（程式用 `intents.message_content = True`，沒開 bot 收不到指令內容）
- `NVIDIA_API_KEY`：AI 診斷用（`ai_runner.py` 走 NVIDIA llama-3.1-405b）
- LINE 兩個變數可留空。

邀請 bot 進你的伺服器：Developer Portal → OAuth2 → URL Generator → 勾 `bot` scope + 所需權限（Send Messages / Embed Links / Attach Files / Read Message History）→ 用產生的網址邀請。

---

## 5. 以 systemd 常駐（生產，建議）

`/etc/systemd/system/stock-quant-discord.service`：
```ini
[Unit]
Description=Stock Quant Discord Bot
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/root/stock_quant
ExecStart=/root/stock_quant/venv/bin/python discord_runner.py
Restart=always
RestartSec=5
EnvironmentFile=/root/stock_quant/.env

[Install]
WantedBy=multi-user.target
```
```bash
systemctl daemon-reload
systemctl enable --now stock-quant-discord
systemctl status stock-quant-discord
journalctl -u stock-quant-discord -f      # 看是否出現「🤖 BMO ... 上線」
```

啟動驗證：Discord 頻道輸入 `!a 2330`（台積電）→ 應跳確認鈕 → 確認後回診斷。
第一次先在目標頻道打 `!bind` 綁定（每日掃描用）。

---

## 6. （選用）先在 bmo(Mac) 用 launchd 驗證

`~/Library/LaunchAgents/com.stockquant.discord.plist`，`ProgramArguments` 指向
`/Users/bmo/stock_quant/venv/bin/python` + `discord_runner.py`，`WorkingDirectory` 設專案路徑，
`RunAtLoad`+`KeepAlive`。跟 BMO worker 同模式（記憶：Mac 睡眠時暫停）。

---

## 7. 部署流程（日後更新）

跟 project-manager 同習慣：
```
bmo 改碼 → push GitHub → LXC `git pull` → systemctl restart stock-quant-discord
```
（沒有 DB migration、沒有前端快取問題，比 project-manager 單純。）

---

## 8. 已知待辦 / 架構備註

- `requirements.txt` 原本缺 `discord.py`/`TA-Lib`/`yfinance`/`openai`/`langchain-nvidia-ai-endpoints`，已補。
- `nginx.conf` / `cloudflared.deb` / `docker-compose.yml` / `Procfile` 為 LINE-web 部署殘留，Discord-only 不需要；保留不影響，要清爽可日後移除。
- 若日後要「BMO（Claude Code）也能改 stock_quant」：複製一份 project-manager 的 worker，**獨立 workspace（指向本 repo）+ 獨立 X-Worker-Token + plist label `com.bmo.worker2`**，與現有 worker 各管各的 job 表。
- 大量回測/訓練吃 CPU，必要時對 LXC 設 CPU/記憶體上限，避免影響 Proxmox 上其他容器。
