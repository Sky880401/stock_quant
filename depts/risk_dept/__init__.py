# 風控課：法人避雷警示與三道風控閘門（降級/分歧揭露/倉位上限）。
# 鐵則：只壓低或揭露、絕不翻轉訊號（錯誤的BUY賠真錢、錯誤的REDUCE只少賺）。
# 課員：utils/profit_space.py、utils/risk_budget.py（路徑未動，見 depts/README.md）
from .inst_alert import inst_avoid_alert, INST_AVOID_P20, INST_AVOID_P10
from .gates import apply_risk_reward_gate, apply_stat_conflict_note, apply_position_caps
