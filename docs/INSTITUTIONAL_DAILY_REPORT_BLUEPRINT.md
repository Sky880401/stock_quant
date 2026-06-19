# 法人日報藍圖骨架（prefer #106 / fallback #201）

> 本文件描述 #901 在 `stock_quant` repo 內落地的最小閉環骨架。
> 目標是先把 **contract / schema / health / freshness / fallback / delivery manifest** 串起來，
> 不在此分支部署 #106。

## 排程邏輯（寫入 repo，避免只存在口頭）

| 時刻 | 角色 | 動作 | 產物 |
|---|---|---|---|
| **17:30** | #106 producer | 產出優先來源 JSON 成品 | `<base>/<date>/106_preferred.json` |
| **17:45** | #201 relay | 抓取備援來源並落地待命 | `<base>/<date>/201_fallback.json` |
| **18:00–18:10** | #901 驗證 | contract / schema / health / freshness；#106 不合格則切 #201 | — |
| **18:30** | #901 交付 | **必送**一份可交付報告（prefer #106，否則 fallback #201） | `<base>/<date>/delivery/` |

對應程式常數位於：
- `depts/delivery_dept/institutional_daily_report.py:SCHEDULE`
- 關鍵時刻 `time` 物件：`DELIVERY_DEADLINE` / `VALIDATION_WINDOW_START` / `VALIDATION_WINDOW_END`

## 路徑/檔名約定（整合層，供 cron / shell wrapper 與下游核對）

由 `build_delivery_paths(base_dir, data_date)` 統一推導，不在各處硬編字串：

```
<base>/<YYYY-MM-DD>/106_preferred.json                       ← #106 producer（17:30）
<base>/<YYYY-MM-DD>/201_fallback.json                        ← #201 relay（17:45）
<base>/<YYYY-MM-DD>/delivery/institutional_daily_report.json ← 交付成品（18:30 前）
<base>/<YYYY-MM-DD>/delivery/delivery_manifest.json          ← 交付 manifest
```

檔名常數：`PREFERRED_106_FILENAME` / `FALLBACK_201_FILENAME` / `DELIVERY_FILENAME` / `MANIFEST_FILENAME`。

## 交易日參數流（expected_data_date）

- `validate_payload` / `deliver_prefer_106_fallback_201` / `run_scheduled_delivery` 皆吃 `expected_data_date`。
- 未指定時，`run_scheduled_delivery` 用 `resolve_expected_trading_date(now)` 推導 —
  **僅跳過週末**，⚠️ **未接台股休市日曆**（國定假日 / 補班 / 颱風假未處理）。
  正式機應由上游交易日曆明確帶入 `expected_data_date`，不要依賴此近似。

## 入口（可被 cron / shell wrapper 呼叫）

1. Python 函式：`run_scheduled_delivery(base_dir=..., now=..., expected_data_date=...)`
   — 依路徑約定讀兩槽位 → 驗證 → 交付，回傳 `DeliveryDecision`。
2. CLI（`python3 -m depts.delivery_dept.institutional_daily_report`）：
   - `deliver --preferred-106 P --fallback-201 P --output-dir D [--expected-data-date D] [--now T]`
     — 直接給兩個 payload 路徑 → 產出 delivery payload + manifest。
   - `run --base-dir B [--expected-data-date D] [--now T]` — cron 模式，依約定路徑。
   - 回傳碼：`0`=交付成功、`2`=驗證/路徑失敗（兩來源皆不可交付等）。
3. Shell wrapper：`scripts/run_institutional_daily_report.sh`
   — 含建議 crontab（`0 18 * * 1-5`，平日 18:00 進驗證視窗），正式機才掛、本分支不掛。

## 這次骨架提供的能力

1. `build_preferred_106_payload(...)`
   - 模擬 #106 producer 產出 `institutional_daily_report` JSON。
2. `validate_payload(...)`
   - **contract**：必要 meta 欄位齊全；`schema_version` / `report_type` 相符；
     `source_job_id` 在白名單；可選 `expected_source_job_id` 綁定槽位
     （#106 槽不能塞 #201 成品，反之亦然）。
   - **schema**：列欄位不只檢查「有沒有」，還檢查 `stock_id` 為非空字串、四個買賣超欄位
     為真數字（排除 bool 偽裝）、`stock_id` 不得重複。
   - **health**：`health.status` 必須是 `green` / `yellow` / `red`；`red` 直接判不可交付，
     `yellow` 視為降級但仍可交付。
   - **freshness**：`data_date` / `generated_at` 必須等於預期交易日（預設 `now.date()`，
     可由 `expected_data_date` 覆寫以支援假日後第一個交易日）；`generated_at` 不得是未來
     （容許 `DEFAULT_FUTURE_SKEW` 的跨機時鐘偏移）。
3. `deliver_prefer_106_fallback_201(...)`
   - 先驗 #106（綁定槽位 `expected_source_job_id="106"`），失敗再驗 #201。
   - 成功後寫出：
     - `institutional_daily_report.json`
     - `delivery_manifest.json`（含 `manifest_schema_version`、`delivery_payload_sha256`
       校驗碼、`delivered_within_deadline` 是否在 18:30 前、`health_status`、
       `candidates` 每個來源的稽核軌跡 selected/rejected/skipped、`validation_errors`）。
4. `current_schedule_stage(...)`
   - 把 17:30 / 17:45 / 18:00–18:10 / 18:30 的時段狀態明文化，方便後續接真正 scheduler。

## Delivery manifest 欄位

| 欄位 | 意義 |
|---|---|
| `manifest_schema_version` | manifest 格式版本 |
| `selected_source_job_id` | 實際交付來源（`106` 或 `201`） |
| `fallback_triggered` | 是否退場到 #201 |
| `delivered_within_deadline` | 交付時刻是否 ≤ 18:30 |
| `delivery_payload_sha256` | 交付檔內容 SHA-256，供下游核對 |
| `health_status` | 採用來源的 health 狀態 |
| `candidates[]` | 每個來源的 `status`（selected/rejected/skipped）與 `error` |
| `validation_errors` | 被拒來源的失敗原因（key 為 job id） |

## 交付物路徑

- 核心模組：`depts/delivery_dept/institutional_daily_report.py`
- Shell wrapper：`scripts/run_institutional_daily_report.sh`
- 測試：`test_institutional_daily_report.py`
- 文件：`docs/INSTITUTIONAL_DAILY_REPORT_BLUEPRINT.md`

## 已能模擬真實流程 / 仍未接正式機（誠實邊界）

**已能模擬**：
- 路徑/檔名約定、交易日資料夾分流、CLI/wrapper 入口、prefer→fallback 決策、manifest 稽核軌跡，
  皆可端到端跑（`run` 模式從 `<base>/<date>/` 讀兩槽位 → 寫 `delivery/`）。

**仍未接正式機（mock / 近似）**：
- #106 producer 與 #201 relay 的「實際資料來源」仍是測試用 builder 造的 payload，
  尚未接真正的 #106 計算 / #201 抓取管線。
- `resolve_expected_trading_date` 只跳週末，未接台股休市日曆。
- crontab 未掛、未部署 #106（依規定本分支只做 #901 開發測試）。

## 測試覆蓋（共 31 例，`python3 -m unittest test_institutional_daily_report`）

- happy path：#106 合格時優先選 #106
- 過期 `data_date`：#106 stale 時 fallback 到 #201
- 缺欄：缺 `total_balance` 時驗證失敗
- 壞格式：`generated_at` 非 ISO-8601 時驗證失敗
- contract：槽位與宣告 `source_job_id` 不符時被拒（單元 + 交付流程兩層）
- health：`red` 判不可交付並 fallback；未知狀態被拒；`yellow` 可交付
- schema：重複 `stock_id`、非數字欄位、bool 偽裝數字、空 `stock_id` 皆被拒
- freshness：未來 `generated_at` 被拒；`expected_data_date` 可覆寫當日
- manifest：校驗碼長度、deadline 旗標、candidates 狀態、健康狀態
- 邊界：排程時段邊界、逾時交付旗標、106/201 皆不可交付時 raise
- 整合層：路徑約定推導、交易日跳週末、#201 builder 標 yellow、
  `run_scheduled_delivery`（prefer 106 / 106 缺檔 fallback 201 / 指定交易日 / 兩槽位皆缺 raise）、
  CLI `deliver` 與 `run` 回傳碼（0 成功 / 2 失敗）
