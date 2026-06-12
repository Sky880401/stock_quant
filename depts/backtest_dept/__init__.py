# 回測演算法課：Kelly 資金管理與歷史補考（回測對標）。
# 課員：optimizer_runner.py、backtest_runner.py、utils/period_backtest.py、
#       walk_forward.py、strategy_weights.py（路徑未動，見 depts/README.md）
from .kelly import calculate_kelly_position
from .seed_history import seed_history_predictions
