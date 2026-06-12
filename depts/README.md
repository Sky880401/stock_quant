# 組織架構（depts/）

把 `!a` 分析流程依「公司部門」拆成各課。**main.py 是總經理**：只負責把各課的產出
串成一條流水線（analyze_single_target），不寫業務邏輯。修 bug / 加功能時，
先問「這是哪一課的事」，只動那一課。

## 組織圖

| 課 | 套件 | 職責 | 課員（既有檔案，路徑未動） |
|---|---|---|---|
| 數據搜集課 | `depts/data_dept` | 股價/基本面/法人買賣超抓取與清洗 | `data/data_loader.py`、`crawlers/`（twse_institutional、market_data、news_scraper） |
| 指標演算法課 | `depts/indicator_dept` | 技術指標計算與綜合計分決策 | `strategies/indicators/`、`strategies/price_action/`、`strategies/ml_models/` |
| 回測演算法課 | `depts/backtest_dept` | Kelly 倉位、歷史補考、參數最佳化 | `optimizer_runner.py`、`backtest_runner.py`、`utils/period_backtest.py`、`utils/walk_forward.py`、`utils/strategy_weights.py`、`utils/prediction_log.py` |
| 風控課 | `depts/risk_dept` | 法人避雷警示、風報比閘門、分歧揭露、倉位壓低 | `utils/profit_space.py`、`utils/risk_budget.py` |
| 報告產出課 | `depts/report_dept` | LLM prompt 組裝與誠實鐵則 | `ai_runner.py`（NVIDIA LLM 呼叫） |
| 推送課 | `depts/delivery_dept` | Discord / LINE 介面 | `discord_runner.py`、`line_bot.py`（系統服務進入點，路徑不可動） |

「課員」= 組織上隸屬該課、但檔案路徑暫時不動的既有模組（移動會弄斷
systemd 進入點或大量 import）。之後若要搬，逐課搬並跑回歸測試。

## 流水線（main.analyze_single_target）

```
數據搜集課.fetch_stock_data_smart
        ↓ df + fundamentals
指標演算法課.analyze_chip / strategies.* / calculate_final_decision  ← 回測演算法課.kelly
        ↓ decision
風控課.apply_risk_reward_gate → apply_stat_conflict_note → apply_position_caps
        ↓ decision(含揭露欄位)
報告產出課.generate_moltbot_prompt → ai_runner(LLM) → 推送課(discord)
```

## 鐵則

- 風控課的調整**只壓倉位/降級/揭露，不翻轉訊號**；所有調整必留說明欄位
  （risk_reward_downgrade / stat_conflict_note / position_cap_note）供報告引用。
- 報告只能引用 Input Data 裡的真實數字，缺失寫缺失。
- 改任何一課之後，跑 `logic_test_n.py`（R1–R9）回歸。

## 部署備註

`!a` 邏輯更新 = 部署 `main.py` + `depts/` +相關課員檔案即可，
不需要動推送課的 bot 功能（自動推播、訓練指令等）。
