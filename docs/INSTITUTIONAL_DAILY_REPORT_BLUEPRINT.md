# 法人日報藍圖骨架（prefer #106 / fallback #201）

> 本文件描述 #901 在 `stock_quant` repo 內落地的最小閉環骨架。
> 目標是先把 **contract / schema / health / freshness / fallback / delivery manifest** 串起來，
> 不在此分支部署 #106。

## 排程邏輯（寫入 repo，避免只存在口頭）

- **17:30**：優先來源 **#106 producer** 產出 JSON 成品。
- **17:45**：備援來源 **#201** 抓取完成，待命。
- **18:00–18:10**：執行驗證（contract / schema / health / freshness），若 #106 不合格則切到 #201。
- **18:30**：一定要送出一份可交付報告（優先 #106，否則 fallback #201）。

對應程式常數位於：
- `depts/delivery_dept/institutional_daily_report.py:SCHEDULE`

## 這次骨架提供的能力

1. `build_preferred_106_payload(...)`
   - 模擬 #106 producer 產出 `institutional_daily_report` JSON。
2. `validate_payload(...)`
   - 驗證必要 meta 欄位、列欄位、ISO-8601 時間格式、當日 freshness。
3. `deliver_prefer_106_fallback_201(...)`
   - 先驗 #106，失敗再驗 #201。
   - 成功後寫出：
     - `institutional_daily_report.json`
     - `delivery_manifest.json`
4. `current_schedule_stage(...)`
   - 把 17:30 / 17:45 / 18:00–18:10 / 18:30 的時段狀態明文化，方便後續接真正 scheduler。

## 交付物路徑

- 核心模組：`depts/delivery_dept/institutional_daily_report.py`
- 測試：`test_institutional_daily_report.py`
- 文件：`docs/INSTITUTIONAL_DAILY_REPORT_BLUEPRINT.md`

## 測試覆蓋

- happy path：#106 合格時優先選 #106
- 過期 `data_date`：#106 stale 時 fallback 到 #201
- 缺欄：缺 `total_balance` 時驗證失敗
- 壞格式：`generated_at` 非 ISO-8601 時驗證失敗
