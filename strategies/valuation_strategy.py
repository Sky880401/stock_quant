from .base_strategy import BaseStrategy

class ValuationStrategy(BaseStrategy):
    def analyze(self, df, extra_data=None):
        # 防禦性編程
        if not extra_data:
            return {"signal": "HOLD", "confidence": 0.0, "reason": "No fundamental data"}

        # 從 extra_data 中嘗試獲取 ticker (需由 main.py 注入)
        ticker = extra_data.get("ticker", "UNKNOWN")
        pe = extra_data.get("pe_ratio")
        pb = extra_data.get("pb_ratio")

        # 若核心數據全無
        if pe is None and pb is None:
            return {"signal": "HOLD", "confidence": 0.0, "reason": "Insufficient Data (Missing PE/PB)"}

        # === 產業差異化閾值 (Sector-Specific Thresholds) ===
        # 格式: { "Ticker": {"pe_buy": x, "pe_sell": y, "pb_buy": a, "pb_sell": b} }
        thresholds = {
            "2330": {"pe_buy": 20, "pe_sell": 35, "pb_buy": 4.5, "pb_sell": 8.0}, # 高成長/高護城河
            "2888": {"pe_buy": 10, "pe_sell": 18, "pb_buy": 0.8, "pb_sell": 1.5}, # 金融股 (看 PB 為主)
            "2317": {"pe_buy": 12, "pe_sell": 20, "pb_buy": 1.2, "pb_sell": 2.5}, # 代工製造 (低毛利)
            "DEFAULT": {"pe_buy": 15, "pe_sell": 25, "pb_buy": 1.5, "pb_sell": 4.0}
        }

        # 模糊匹配 (處理 2330.TW 與 2330 的差異)
        cfg = thresholds.get("DEFAULT")
        for key in thresholds:
            if key in ticker:
                cfg = thresholds[key]
                break

        signal = "HOLD"
        reason_parts = []
        score = 0  # 簡單計分 (-2 ~ +2)

        # PE 邏輯
        if pe is not None:
            if pe < cfg["pe_buy"]:
                score += 1
                reason_parts.append(f"PE({pe:.1f})<Buy({cfg['pe_buy']})")
            elif pe > cfg["pe_sell"]:
                score -= 1
                reason_parts.append(f"PE({pe:.1f})>Sell({cfg['pe_sell']})")
            else:
                reason_parts.append(f"PE({pe:.1f}) Fair")

        # PB 邏輯
        if pb is not None:
            if pb < cfg["pb_buy"]:
                score += 1
                reason_parts.append(f"PB({pb:.1f})<Buy({cfg['pb_buy']})")
            elif pb > cfg["pb_sell"]:
                score -= 1
                reason_parts.append(f"PB({pb:.1f})>Sell({cfg['pb_sell']})")
            else:
                reason_parts.append(f"PB({pb:.1f}) Fair")

        # 綜合判斷
        if score >= 1:
            signal = "BUY"
            confidence = 0.8 if score >= 2 else 0.6
        elif score <= -1:
            signal = "SELL"
            confidence = 0.8 if score <= -2 else 0.6
        
        # 特殊處理：國泰金若無 PE 但有 PB，僅依賴 PB
        if "2888" in ticker and pe is None and pb is not None:
            reason_parts.append("(Finance Sector: Prioritize PB)")

        return {
            "signal": signal,
            "confidence": confidence,
            "reason": "; ".join(reason_parts),
            "data": {"pe": pe, "pb": pb, "thresholds_used": cfg}
        }
