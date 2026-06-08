# CLAUDE.md — stock_quant 開發守則（給在 #901 stock-dev 上跑的 Claude Code）

## 這台機器的角色
你在 **#901 stock-dev**（開發測試機，隔離）。你可以自由改碼、跑測試、commit 到「功能分支」。
**禁止自行部署到正式機 #106**。部署一律由真人（Sky）在 Discord 確認後才進行。

## 環境
- Python 3.11 venv 在 `./venv`（用 `venv/bin/python` / `venv/bin/pip`）。
- TA-Lib：系統 C 庫用官方 .deb 裝好了；pip 的 `TA-Lib` wrapper 已裝。別重裝 C 庫。
- 部署分支 `discord-deploy-prep`；正式機 #106（Debian12、systemd 服務 `stock-quant-discord`）。

## 硬規則（踩過的雷，務必遵守）
- **`.env` 不能有行內註解**：systemd EnvironmentFile 會把 `KEY=value # 註解` 整行吃進去 → 壞掉。註解只能獨立成行。
- **NVIDIA 模型**：用 `meta/llama-3.3-70b-instruct`（已驗證）。`llama-3.1` 系列已下架（呼叫回 404 純文字→`.json()` 爆）。reasoning 型模型回 `content=null` 不可用。**模型清單列得出 ≠ 叫得動，務必先實測**。NVIDIA 會限流，連打要 `sleep` 節流。
- **法人籌碼以證交所官方 T86 為準**（`crawlers/twse_institutional.py`，免 token）：股數 ÷ 1000 = 張，漲跌用「當日」比對。FinMind 法人額度不足會回**全 0 假資料**，別誤信。
- **報告鐵則**：只用 Input Data 的數字；缺值就寫「數據缺失」；**禁止編造價格/數字**。

## 誠實的實證結論（別靠調參硬拱）
單一大型股 10–60 日方向命中率約 48–50%（近效率市場），連最強法人訊號也 ~49.8%；拉長 horizon 更差。
→ 單股方向預測沒穩定 edge。價值在**誠實倉位（Kelly）+ 風控**；未來 alpha 方向是**橫截面排序（多空）**而非單股方向。

## Discord 指令參考
`!a 2330` 查股 / `!model` 切模型(owner) / `!accuracy` / `!validate 2330` / `!bind`。

## 開發流程
1. 改碼 → 用 venv 跑相關測試確認沒壞。
2. 開「功能分支」commit（例 `fix/xxx`），**不要直接動 `discord-deploy-prep` 或 `main`**。
3. push 後回報 Sky：改了什麼、測試結果、分支/PR。**部署等 Sky 點頭**。

## 內化知識庫（操盤邏輯 RAG，2026-06-08 接入）
- 已把 Sky 提供的操盤 PDF 內化成可檢索知識庫（`data/knowledge/stock.kb.json`）。
- **做操盤/策略/型態判斷相關工作前，先查它當參考**：
  `venv/bin/python scripts/kb_query.py stock "<你的問題>"`（回最相關規則 + 出處）。
- 用法定位：知識庫是**參考框架/操盤規則**，**數字一律以即時真實資料為準**，守上面「報告鐵則」，別讓 PDF 文字凌駕真實數據或變成亂喊買賣。
- 圖：知識塊註明「本頁有 N 張圖」時，需看圖再用視覺直讀原 PDF；通用視覺模型讀線圖會唬爛，別自動採信。
- 更新知識：在 #107（有 NAS 掛載+fitz）重新 ingest → 把新 `stock.kb.json` commit 進 repo。
