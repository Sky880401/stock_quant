from abc import ABC, abstractmethod
import pandas as pd

class BaseStrategy(ABC):
    @abstractmethod
    def analyze(self, df: pd.DataFrame) -> dict:
        """
        所有策略都必須實作這個方法
        Input: DataFrame (含 OHLCV)
        Output: Dict {signal: 'BUY'/'SELL'/'HOLD', confidence: int, reason: str}
        """
        pass