# quant/ 橫截面選股模組 盤點報告（2026-06-07）

> 純盤點（唯讀），未改動任何既有程式碼。本檔為新增交付物，供 Sky 審查。
> 範圍：`quant/` 下的 universe.py、data_hub.py、factors.py、ranker.py、backtest_xs.py。

---

## 結論（先講）

1. **五個檔都「有實作、可離線跑通」，不是空殼。** 用合成資料實測：模組全數 import 成功，`run_backtest()` 能端到端回出完整指標 dict（rebalances / ic_mean / ic_t / long_short_spread …）。
2. **資料流是通的**：`universe → data_hub.build_panel → factors.build_factor_timeseries → (cross_section_scores | cross_section_table) → ranker.rank_universe / backtest_xs.run_backtest`。
3. **最大隱憂（與 CLAUDE.md 正面衝突）**：`data_hub.py` docstring 宣稱資料來自 `fetch_stock_data_smart`（已併 TWSE T86 法人），**但實際程式碼是直接打 FinMind**（`taiwan_stock_daily` + `taiwan_stock_institutional_investors`），**完全沒接 `crawlers/twse_institutional.py`（官方 T86）**。CLAUDE.md 明寫「FinMind 法人額度不足會回全 0 假資料」。⇒ 目前 `inst` 因子很可能餵到一堆 0，污染回測與排行。
4. **要跑「誠實的多空 walk-forward 回測」目前主要缺三塊**：(a) **交易成本**（賣出稅 0.3% + 手續費，現在完全沒扣）、(b) **分層 quintile 回測**（現在只有 top/bottom 兩端，沒有 5 層單調性）、(c) **多空價差「淨值曲線」**（現在只回平均報酬純量，沒有逐期累乘的淨值/回撤）。Rank-IC 已有。
5. **Universe = 92 檔，全為上市（TWSE）大型權值股 + 6 檔 ETF；不含上櫃（TPEx）。** T86 crawler 本身也僅涵蓋上市（其 docstring 自述「T86 僅含上市，上櫃未涵蓋」）。

---

## (1) 各檔實作、完成度、串接（資料流）

資料流總覽：

```
universe.get_universe()  ──(代號清單, 92檔)──┐
                                            ▼
data_hub.build_panel()  ── dict{sid: DF[Close,Volume,Foreign,Trust,rev_yoy]} ──┐
   ├ get_stock_frame() 逐檔（磁碟快取 frames/<sid>.pkl）                        │
   ├ _price_inst_finmind()  ← FinMind 股價+三大法人                            │
   └ _month_revenue_yoy()   ← FinMind 月營收，公布日落後對齊(避 look-ahead)     │
                                                                              ▼
factors.build_factor_timeseries() ── dict{sid: DF[mom,revyoy,inst,lowvol,close,dollar_vol]}
                                            │
                ┌───────────────────────────┴───────────────────────────┐
                ▼                                                         ▼
factors.cross_section_scores(date)                       factors.cross_section_table(date)
 (回 {sid: 綜合分})                                       (回含各因子原始值+z-score 的表)
                │                                                         │
                ▼                                                         ▼
backtest_xs.run_backtest(panel)                          ranker.rank_universe(top_n)
 (walk-forward 驗證 alpha)                                (每日 Top-N/Bottom-N 推播)
```

### `universe.py`（39 行）— 完整可跑
- 硬寫 `_CORE` 清單，過濾非法代號後 `get_universe()` 回 **92 檔**（純數字代號、不含 `.TW`）。
- docstring 預告未來可改「依近 60 日成交值動態取前 N」，目前**尚未實作**（靜態清單）。
- ⚠️ 小瑕疵：原始清單裡有一個手誤 `"3developmental"`，被 `s.isdigit()` 濾掉（不致命，但代表來源未清乾淨）。

### `data_hub.py`（194 行）— 可跑，但資料來源與 docstring 不符（重點問題）
- `build_panel()`：對整個 universe 逐檔組面板，含 12h 整體快取 + 逐檔 `frames/<sid>.pkl` 磁碟快取（可中斷續跑、省 FinMind 配額）。
- `_price_inst_finmind()`：**直接用 FinMind** 抓「未還原」日線（除息跳空為已知雜訊，非還原股價）+ 三大法人淨買（外資 `Foreign`、投信 `Trust`）。
- `_month_revenue_yoy()`：月營收 YoY，**生效日設為公布月 12 日再 forward-fill**，look-ahead 處理做得正確。
- ❌ **與 CLAUDE.md 衝突**：docstring 說來源是 `fetch_stock_data_smart`（已併官方 T86），實際沒接 `crawlers/twse_institutional.py`。FinMind 匿名/低額度法人會回全 0 → `inst` 因子失真。
- ⚠️ 還原股價：用未還原日線，`mom`(12-1 動能)、`lowvol`(波動) 會被除權息跳空污染。

### `factors.py`（106 行）— 完整可跑
- `build_factor_timeseries()`：要求每檔 ≥260 筆，算 4 因子（皆「越大越偏多」）：
  - `mom` = close.shift(21)/close.shift(252)-1（12-1 月動能，跳過最近一月）
  - `revyoy` = 月營收 YoY（已落後對齊）
  - `inst` = 近 20 日法人淨買 / 近 20 日量（集中度）
  - `lowvol` = -近 60 日報酬波動（低波動）
  - 另含 `close`、`dollar_vol`（20 日均額，流動性濾網）
- `cross_section_scores()` / `cross_section_table()`：某日做橫截面 z-score 等權合成；門檻：4 因子皆有值、`dollar_vol ≥ min_liquidity(2e7)`、納入股數 ≥10 才回傳。
- 設計乾淨；權重 `weights` 已預留可調介面（目前等權）。

### `ranker.py`（35 行）— 完整可跑（線上推播用）
- `rank_universe(top_n=10)`：build_panel → factor → 取最新交易日 `cross_section_table` → 回 (as_of, Top-N, Bottom-N)，每筆含 sid/score/mom/revyoy/inst。供 Discord `!rank` 每日推播。

### `backtest_xs.py`（82 行）— 可跑，但「誠實版」缺料（見下節）
- `run_backtest(panel, step=20, horizon=20, quantile=0.2, min_liquidity=2e7)`：
  - 暖身 260 日，之後每 `step` 日為再平衡日 t，未來報酬取 t→t+horizon。
  - 用 `c.asof(d)` 取價（再平衡日缺值時取 ≤d 最後一筆），避免 KeyError。
  - 算 **rank-IC** 序列 → ic_mean、**ic_t = mean/std·√N**、ic 正比率；top/bottom quantile 各取 k 檔算 long_avg / short_avg / long_short_spread / long_beat_uni。
  - 樣本門檻：每期共同股 ≥15、總再平衡 ≥5。
- ✅ 有：walk-forward、無 look-ahead、rank-IC、IC t-stat、多空兩端平均。
- ❌ 缺：交易成本、quintile 分層、淨值曲線（淨量/回撤/Sharpe）。

---

## (2) 要跑「誠實的橫截面多空 walk-forward 回測」還缺什麼

需求：台股賣出稅 0.3% + 手續費、Rank-IC、分層(quintile)回測、多空價差淨值。逐項對照：

| 需求 | 現況 | 缺口 |
|---|---|---|
| Rank-IC | ✅ 已有（ic_mean / ic_t / ic_pos_rate） | 無 |
| 賣出稅 0.3% + 手續費 | ❌ 完全沒扣，用毛報酬 | **需在每次再平衡換手時扣成本**：賣出證交稅 0.3%、買賣手續費各 0.1425%（常打折）。多空各腿都要扣，且空方還有借券成本可考慮 |
| 分層 quintile 回測 | ❌ 只有 top/bottom 兩端（quantile=0.2 取頭尾） | **需切 5 層、各層平均報酬，檢查單調性**（Q1>Q2>…>Q5 才是真因子，不是只看兩端） |
| 多空價差「淨值」 | ❌ 只回各期平均報酬「純量」 | **需逐期累乘成淨值曲線**（long、short、long-short、universe 四條），並算年化報酬 / 年化波動 / Sharpe / MaxDD / 勝率 |

其他「誠實度」缺口（建議一併補）：
- **還原股價**：目前用未還原日線，`mom`/`lowvol` 受除權息污染 → 應改用還原報酬，或至少在報酬計算處還原。
- **法人資料真實性**：`inst` 因子目前可能餵 FinMind 全 0（見上）。回測前須確認資料非假 0，否則該因子等於雜訊。
- **換手率/容量**：成本要乘上「實際換手率」才公允；目前完全等權重配、未記錄前後持股差。
- **存活者偏誤**：universe 是「今日的大型股」靜態清單，回測歷史隱含存活者偏誤（已退場/縮水的股票不在內）。

---

## (3) Universe 規模與資料覆蓋

- **規模**：92 檔（`get_universe()` 實測）。組成為跨產業上市大型權值股 + 6 檔 ETF（0050/0056/00878/00919/006208/00929）。
- **市場別**：**僅上市（TWSE）**。清單全是上市大型股；無上櫃（TPEx）個股。
- **法人（T86）涵蓋**：
  - 倉內目前 quant 管線**並未使用** `crawlers/twse_institutional.py`（官方 T86，免 token），而是用 FinMind 法人。
  - `twse_institutional.py` 本身僅涵蓋**上市（T86）**，其註解自述「T86 僅含上市(TWSE)；上櫃(TPEx)未涵蓋，查無者法人欄位留 0」。
  - ⇒ 即使日後切回官方 T86，法人覆蓋仍是上市 only；上櫃需另接 TPEx 來源。

---

## (4) 完成藍圖 M1 的下一步清單（依優先序）

> 原則：先把「資料是真的」做對，再談回測誠實度，最後才擴 universe。順序錯了會在假資料上調參。

1. **【最高】修正法人資料來源：quant 管線接官方 T86，停用 FinMind 法人**
   - 改 `quant/data_hub.py`：`_price_inst_finmind()` 的法人段改用 `crawlers/twse_institutional.py`（`attach_institutional` / `fetch_day`）；或新增 `_inst_twse()` 取代。加防呆：偵測「整段法人為 0」就標記資料無效，別當真值。
   - 同步把 docstring 改成符合實作。

2. **【高】回測加入交易成本**
   - 改 `quant/backtest_xs.py`：每次再平衡對 long/short 兩腿扣賣出稅 0.3% + 手續費（買賣各 0.1425%，可設 `fee`/`tax`/`discount` 參數）。先做「滿額換手」近似，之後再用實際換手率。

3. **【高】回測加入 quintile 分層 + 單調性**
   - 改 `quant/backtest_xs.py`：把 top/bottom 兩端擴成 5 層，輸出各層平均報酬與單調性檢定（如 Spearman of 層序 vs 報酬）。

4. **【高】輸出多空淨值曲線與風險指標**
   - 改 `quant/backtest_xs.py`：long/short/long-short/universe 四條逐期累乘淨值；加年化報酬、年化波動、Sharpe、MaxDD、勝率。`run_backtest` 回傳結構擴充（或回 DataFrame）。

5. **【中】還原股價（除權息）**
   - 改 `quant/data_hub.py`：價格欄改用還原序列（或在 `factors.py` 報酬/動能/波動計算處還原）；確保 `mom`/`lowvol`/回測報酬一致用還原口徑。

6. **【中】處理存活者偏誤 / 動態 universe**
   - 改 `quant/universe.py`：實作 docstring 預告的「依近 60 日成交值動態取前 N」，並考慮 point-in-time 成分（回測各期用當期可投資清單，而非今日清單）。

7. **【低】擴增上櫃（TPEx）覆蓋**
   - 新增 TPEx 籌碼/價格來源（新 crawler 或 FinMind 上櫃），再把 OTC 代號納入 universe；法人需另接 TPEx 三大法人日報。

8. **【低】補測試**
   - 為 `quant/` 加單元測試（合成 panel 跑 `build_factor_timeseries` / `run_backtest`，斷言成本扣抵、quintile 單調、淨值連乘正確）。目前 repo 無針對 quant 的測試。

---

## 附：本次驗證紀錄

- `from quant.universe import get_universe` → 92 檔。
- 合成 20 檔 × 400 交易日 panel 跑 `run_backtest()` → 回出 `rebalances/horizon/ic_mean/ic_t/ic_pos_rate/long_avg/short_avg/universe_avg/long_short_spread/long_beat_uni`（模組功能正常）。
- 全 quant 模組 import 無誤；`_zscore` 行為正確（mean≈0）。
