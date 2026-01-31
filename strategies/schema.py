from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

@dataclass
class StrategyResult:
    """
    v3.0 升級：加入風險計量與停損機制
    """
    signal: str  # BUY, SELL, HOLD, UNKNOWN (新狀態)
    confidence: float
    reason: str
    
    # [新增] 風險扣分 (例如資料缺失扣 0.2)
    risk_penalty: float = 0.0
    
    # [新增] 建議停損價 (若無則為 0.0)
    stop_loss: float = 0.0
    
    scores: Dict[str, float] = field(default_factory=dict)
    assumptions: List[str] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {
            "signal": self.signal,
            "confidence": self.confidence,
            "reason": self.reason,
            "risk_penalty": self.risk_penalty,
            "stop_loss": self.stop_loss,
            "scores": self.scores,
            "assumptions": self.assumptions,
            "raw_data": self.raw_data
        }
