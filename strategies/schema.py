from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

@dataclass
class StrategyResult:
    """
    統一策略輸出格式，確保所有策略都講同一種語言
    """
    signal: str  # BUY, SELL, HOLD, WAIT
    confidence: float  # 0.0 ~ 1.0
    reason: str  # 人類可讀的摘要
    
    # 關鍵：將隱性規則顯性化
    scores: Dict[str, float] = field(default_factory=dict)  # {"pe_score": 1.0, "trend_score": -0.5}
    assumptions: List[str] = field(default_factory=list)    # ["PE < 15 is BUY", "MA5 > MA20"]
    
    # 原始數據快照 (用於 Debug 或 AI 深度分析)
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {
            "signal": self.signal,
            "confidence": self.confidence,
            "reason": self.reason,
            "scores": self.scores,
            "assumptions": self.assumptions,
            "raw_data": self.raw_data
        }
