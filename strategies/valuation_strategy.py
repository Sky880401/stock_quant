from .base_strategy import BaseStrategy
from .schema import StrategyResult

class ValuationStrategy(BaseStrategy):
    def analyze(self, df, extra_data=None):
        # 防禦性編程
        if not extra_data:
            return StrategyResult("HOLD", 0.0, "No fundamental data")

        ticker = extra_data.get("ticker", "UNKNOWN")
        pe = extra_data.get("pe_ratio")
        pb = extra_data.get("pb_ratio")

        if pe is None and pb is None:
            return StrategyResult("HOLD", 0.0, "Insufficient Data (Missing PE/PB)")

        # 產業閾值配置 (Config)
        thresholds = {
            "2330": {"pe_buy": 20, "pe_sell": 35, "pb_buy": 4.5, "pb_sell": 8.0}, 
            "2888": {"pe_buy": 10, "pe_sell": 18, "pb_buy": 0.8, "pb_sell": 1.5},
            "DEFAULT": {"pe_buy": 15, "pe_sell": 25, "pb_buy": 1.5, "pb_sell": 4.0}
        }
        
        # 選擇配置
        cfg = thresholds.get("DEFAULT")
        for key in thresholds:
            if key in ticker:
                cfg = thresholds[key]
                break

        # 評分邏輯 (Scoring)
        score = 0
        assumptions = []
        
        # PE Score
        if pe is not None:
            if pe < cfg["pe_buy"]:
                score += 1
                assumptions.append(f"PE Cheap (<{cfg['pe_buy']})")
            elif pe > cfg["pe_sell"]:
                score -= 1
                assumptions.append(f"PE Expensive (>{cfg['pe_sell']})")
        
        # PB Score
        if pb is not None:
            if pb < cfg["pb_buy"]:
                score += 1
                assumptions.append(f"PB Cheap (<{cfg['pb_buy']})")
            elif pb > cfg["pb_sell"]:
                score -= 1
                assumptions.append(f"PB Expensive (>{cfg['pb_sell']})")

        # 訊號生成
        if score >= 1:
            signal = "BUY"
            confidence = 0.8 if score >= 2 else 0.6
        elif score <= -1:
            signal = "SELL"
            confidence = 0.8 if score <= -2 else 0.6
        else:
            signal = "HOLD"
            confidence = 0.5

        return StrategyResult(
            signal=signal,
            confidence=confidence,
            reason=f"Score: {score} (PE={pe}, PB={pb})",
            scores={"valuation_score": score},
            assumptions=assumptions,
            raw_data={"pe": pe, "pb": pb, "thresholds": cfg}
        )
