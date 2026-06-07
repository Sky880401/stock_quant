# 漲跌預測部門藍圖（Prediction Department Blueprint）

> 對象：stock_quant 量化預測模組。本文以**現有程式碼**為基礎（`quant/`、`crawlers/`、`utils/prediction_log.py`、`discord_runner.py`），不是從零規劃。
> 核心立場（承襲 CLAUDE.md 實證結論）：**單股方向預測沒有穩定 edge（命中率 ~48–50%，近效率市場）。部門價值在「橫截面相對排序 + 誠實倉位(Kelly) + 風控監控」，不是猜單股漲跌。**

---

## 1. 資料來源與取得方式、更新頻率　📌

| 資料 | 來源 / 模組 | 取得方式 | 更新頻率 |
|---|---|---|---|
| 日線價量（Close/Volume） | FinMind → `quant/data_hub.py`（`fetch_stock_data_smart`） | API，本地 pickle 快取於 `data/quant_cache/` | 每交易日收盤後一次；節流 `_MIN_INTERVAL=0.9s` |
| 三大法人買賣超（外資/投信/自營） | **證交所官方 T86**：`crawlers/twse_institutional.py` | 每日一個請求拿全市場，快取 `data/twse_chip/<date>.json` | 每交易日；**法人資料公布後**（約 17:00 後） |
| 月營收年增率（rev_yoy） | FinMind 月營收 → `data_hub` | 依**公布日落後對齊**（M 月營收生效日設 M+1/12，forward-fill） | 每月（10 日左右公布） |
| 股票池 universe | `quant/universe.py`（跨產業流動性中大型股 ~90 檔） | 靜態清單，`get_universe()` 單一入口 | 手動維護；未來改「近 60 日成交值動態取前 N」 |

**鐵則**　🔴
- 法人**只信 T86 官方**；FinMind 法人額度不足會回**全 0 假資料**，禁用。
- 所有因子**只用「當下以前」資料**（no look-ahead）；月營收已做公布日落後對齊。
- 報告只用 Input Data 數字，缺值寫「數據缺失」，**禁止編造價格**。

---

## 2. 模型與特徵工程流程　📌

> 採「由簡到繁、先驗證再加深」順序，避免過擬合。

### 2.1 橫截面因子（主力 alpha 方向）— 已實作 `quant/factors.py`　🔄
每檔面板 → 慢變因子時間序列 → 每個再平衡日做**橫截面 z-score 排名**：
- `mom`：12-1 月動能（過去 ~252→21 交易日報酬，跳過最近一月，避反轉雜訊）
- `revyoy`：月營收年增率（已落後對齊）
- `inst`：近 20 日法人淨買 / 近 20 日量（順勢集中度）
- `lowvol`：近 60 日報酬波動的負值（低波動因子）
- 濾網：`dollar_vol` 流動性、`close` 實際再平衡價

### 2.2 時間序列 / 技術指標（單股輔助，不作主決策）
- `strategies/indicators/*`：MA cross、RSI 反轉、MACD、KD、Bollinger（TA-Lib）。
- `strategies/ml_models/hybrid_predictor.py`：多指標加權置信度集成 → 產生方向信號，**僅供 Discord 個股問答與 P1 記錄**，不視為穩定 edge。

### 2.3 機器學習 / 深度學習（演進路線，非即刻）　🛠️
- **階段一（現況）**：因子等權 / 線性合成分數 → rank-IC 驗證。
- **階段二**：橫截面 **LightGBM ranker**（label = 未來 h 日橫截面排序報酬），特徵 = 2.1 因子 + 衍生（因子動量、產業中性化）。優先 GBDT 而非 DL（樣本/雜訊比不利深度模型）。
- **階段三（觀望）**：序列模型（LSTM/Temporal）僅在階段二 IC t-stat 穩定 > 2 後再評估，避免燒算力買雜訊。

### 2.4 驗證鐵則 — 已實作 `quant/backtest_xs.py`　🔄
walk-forward、無 look-ahead，每 step 再平衡：
- **rank-IC** 均值 + **IC t-stat = mean/std·√N（> 2 才算顯著）**
- 多空價差（前 quantile − 後 quantile）
- Top 組 vs 等權全體
> 任何新因子/模型**先過 backtest_xs 的 IC t-stat 門檻**，沒過不上線。

---

## 3. 預測門檻與倉位管理（Kelly）　📌

### 3.1 排序門檻 — 已實作 `quant/ranker.py`
- 不預測單股絕對漲跌，輸出 **Top-N 做多候選 / Bottom-N 避開**。
- 進場門檻：須通過 `dollar_vol` 流動性濾網 + 綜合分位於 Top 分組。

### 3.2 倉位（誠實 Kelly）— `utils/risk_budget.py` + `discord_runner.py`
- **倉位大小由實測命中率驅動，非由模型自信度**：P1 樣本達 `MIN_SAMPLES` 後，Kelly 自動改用**該策略歷史命中率**縮放（見 `!accuracy`）。
- 命中率 ≤ 50% 的策略 → Kelly ≈ 0 / 建議停用（系統會標示）。
- **分數 Kelly（half-Kelly 為宜）** + 單檔上限 + ATR/Bollinger 波動調整，避免重押。
- 樣本不足期：保守固定小注，明示「樣本累積中」。

---

## 4. 自動化流程與報表　📌

> 全部已掛在 `discord_runner.py` 的 `tasks.loop`，無需另起 cron；節點即 Discord 服務本身。

| 排程 | 時間 | 動作 | 模組 |
|---|---|---|---|
| 每日選股排行推播　🔄 | **17:30 台北（法人公布後）** | `build_rank_text` → 推播 Top/Bottom 至**綁定頻道** | `daily_rank_task` / `quant.ranker` |
| 預測回填閉環　🔄 | 每日 06:00 UTC | 回填到期預測實際結果、結算命中 → 通知 `!accuracy` | `daily_scan_task` / `backfill_matured` |
| 每日掃描 | 每日 | 個股訊號掃描 | `daily_scan_task` |

**Discord 指令（人工查詢）**
- `!rank [n]`（別名 `!排行 !選股`）：當日橫截面排行
- `!accuracy`（`!acc !winrate`）：歷史命中率 + 各策略 Kelly 採用狀態
- `!a 2330` 查股 / `!validate 2330` 回測 / `!bind` 綁定推播頻道

**報表機制**：排行/命中率以 Discord embed 分段（`send_long`）輸出；圖表存 `reports/`；版本紀錄 `data/logs/`。

---

## 5. 風險與監控機制（命中率監控、策略退化警報）　📌

### 5.1 P1 預測閉環（地基）— `utils/prediction_log.py`　🔄
- 每次方向判斷存 `data/predictions.db`；只對「看多/看空」計分，HOLD → `skipped`（誠實，不灌水）。
- `DEFAULT_HORIZON_DAYS=30`；到期前 `status=open`，到期 `backfill_matured` 回填實際報酬判定命中。
- 累積真實勝率 → 餵 §3.2 Kelly 與 §3 動態權重。

### 5.2 退化警報（建議實作）　🛠️
- **滾動命中率監控**：近 N 筆（如 60 筆）命中率跌破門檻（如 < 48%）→ Discord 自動告警、該策略 Kelly 降至 0。
- **IC 漂移監控**：每月重跑 `backtest_xs`，rank-IC t-stat 由 >2 跌破 → 標記因子退化。
- **資料健康檢查**：T86 當日全 0 / 抓取失敗 / universe 缺檔 → 推播警告（`maintenance_check.py` 可擴充）。
- **過擬合防線**：新模型一律 walk-forward 出 sample 驗證，禁止用全樣本調參拱 IC。

### 5.3 紅線（CLAUDE.md）
- 禁自行部署正式機 #106；部署等 Sky。
- `.env` 禁行內註解；NVIDIA 用 `meta/llama-3.3-70b-instruct` 並節流。

---

## 6. 實作優先順序　🛠️

1. **🥇 監控先行（最高 CP）**：滾動命中率退化警報 + T86 資料健康檢查（保護現有閉環，低成本高價值）。
2. **🥈 鞏固橫截面**：universe 改「動態取近 60 日成交值前 N」；factors 加產業中性化；每月自動重跑 `backtest_xs` 並推播 IC 報表。
3. **🥉 Kelly 落地**：確認 half-Kelly + 單檔上限 + 命中率驅動縮放在 `!accuracy` / 推播中完整呈現。
4. **進階模型**：階段二 LightGBM ranker（僅在 §2.4 IC 門檻通過後）。
5. **觀望**：序列/DL 模型 —— 只有在 GBDT ranker IC t-stat 穩定 > 2 後才投入。

> 一句話總結：**先守住「誠實命中率 + 風控監控」，再用橫截面排序找微弱但真實的 alpha；單股方向預測不投入額外資源。**
