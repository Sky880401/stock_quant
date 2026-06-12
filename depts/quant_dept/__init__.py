# 量化研究課：橫截面因子研究與打假驗證（research 線，不在 !a 即時流水線上）。
# 課員：quant/（factors、backtest_xs、ranker、universe、data_hub＝橫截面回測引擎）、
#       scripts/ 研究腳本（run_xs_backtest、holdout_revyoy、audit_revyoy_pit、
#       beta_adjust_revyoy；部分課員目前住在 feat/paper-ledger-settlement 分支）、
#       test_quant_backtest_xs.py、docs/QUANT_XS_INVENTORY_*.md。
# 職責：新因子想法 → 打假管線（point-in-time／存活偏誤／交易成本／hold-out／產業中性化）
#       → 通過打假才得升級進 !a 或紙上帳本；研究結論寫進 docs/ 與帳本，不直接改線上邏輯。
# 中台獨立（2026-06-12）：打假「驗證權」(logic_test_n) 與帳本「記帳權」(paper_ledger)
#       歸風控課監督——本課提策略、不自己當裁判。
# 本課只做組織歸屬、不搬程式碼（quant/ 是獨立套件、路徑不動；見 depts/README.md）。
