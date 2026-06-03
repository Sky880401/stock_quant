"""
P4 動態權重 —— 用 P1 預測日誌累積的「真實命中率」動態調整各策略在融合時的話語權。

核心：最近準的策略給更多權重，最近不準的降權。這才是「越問越準」的務實版
（adaptive ensemble weighting），不是 query 數量讓它變準，而是已驗證標籤累積。

誠實設計：
- 樣本不足（< MIN_SAMPLES）時退回中性權重 1.0，不亂調 —— 系統剛上線本來就沒資料。
- 命中率以 50% 為基準（隨機水準），高於 50 加權、低於 50 降權，並夾在 [0.5, 1.5]。
"""
MIN_SAMPLES = 10        # 至少累積這麼多筆已結算預測才採用
WEIGHT_FLOOR = 0.5
WEIGHT_CEIL = 1.5


def _rate_to_weight(hit_rate: float) -> float:
    # 50% → 1.0；100% → 1.5；0% → 0.5
    w = 1.0 + (hit_rate - 50.0) / 100.0
    return max(WEIGHT_FLOOR, min(WEIGHT_CEIL, w))


def get_hit_rate(strategy_type: str, min_samples: int = MIN_SAMPLES):
    """回傳該策略的 P1 實測命中率 (rate_pct, n)；樣本不足回 (None, n)。"""
    try:
        from utils.prediction_log import accuracy_summary
        s = accuracy_summary()
        for b in s.get("by_strategy", []):
            if b["strategy"] == strategy_type:
                if b["n"] >= min_samples:
                    return b["rate"], b["n"]
                return None, b["n"]
    except Exception:
        pass
    return None, 0


def get_strategy_multiplier(strategy_type: str) -> tuple:
    """回傳 (multiplier, source_desc)。source 標明用 P1 真實命中率或預設。"""
    try:
        from utils.prediction_log import accuracy_summary
        s = accuracy_summary()
        for b in s.get("by_strategy", []):
            if b["strategy"] == strategy_type and b["n"] >= MIN_SAMPLES:
                return _rate_to_weight(b["rate"]), f"P1實測{b['rate']}%({b['n']}筆)"
    except Exception:
        pass
    return 1.0, "預設(P1樣本不足)"
