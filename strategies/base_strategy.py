from abc import ABC, abstractmethod
import pandas as pd
from .schema import StrategyResult

class BaseStrategy(ABC):
    @abstractmethod
    def analyze(self, df: pd.DataFrame, extra_data: dict = None) -> StrategyResult:
        """
        Input: 
            df: 歷史股價 (DataFrame)
            extra_data: 基本面或其他數據 (dict)
        Output:
            StrategyResult 物件 (嚴格型別)
        """
        pass
