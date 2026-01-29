from abc import ABC, abstractmethod
import pandas as pd

class BaseStrategy(ABC):
    @abstractmethod
    def analyze(self, df: pd.DataFrame, extra_data: dict = None) -> dict:
        """
        Input: 
            df: 歷史股價 (DataFrame)
            extra_data: 基本面或其他數據 (dict)
        Output:
            dict: { "signal": "BUY/SELL/HOLD", "confidence": float, "reason": str, "data": {} }
        """
        pass