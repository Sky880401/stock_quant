from .base_strategy import BaseStrategy

class ValuationStrategy(BaseStrategy):
    def analyze(self, df, extra_data=None):
        if not extra_data:
            return {"signal": "HOLD", "confidence": 0.0, "reason": "No fundamental data"}

        pb_ratio = extra_data.get("pb_ratio")
        
        if pb_ratio is None:
            return {"signal": "HOLD", "confidence": 0.0, "reason": "PB Ratio is None"}

        signal = "HOLD"
        confidence = 0.5
        reason = f"PB Ratio is {pb_ratio}"

        if pb_ratio < 1.0:
            signal = "BUY"
            confidence = 0.9
            reason = f"Undervalued: PB ({pb_ratio}) < 1.0"
        elif pb_ratio > 1.5:
            signal = "SELL"
            confidence = 0.7
            reason = f"Overvalued: PB ({pb_ratio}) > 1.5"

        return {
            "signal": signal,
            "confidence": confidence,
            "reason": reason,
            "data": {"pb_ratio": pb_ratio}
        }