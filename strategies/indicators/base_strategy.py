from abc import ABC, abstractmethod
import pandas as pd
from .schema import StrategyResult

class SignalBuffer:
    """信號緩衝與確認機制 - 減少虛假信號"""
    def __init__(self, buffer_bars=2):
        self.buffer_bars = buffer_bars
        self.signal_buffer = []
    
    def confirm_signal(self, current_signal):
        """需要 buffer_bars 根K線在同一方向才視為確認"""
        if current_signal in ["BUY", "SELL"]:
            self.signal_buffer.append(current_signal)
            if len(self.signal_buffer) > self.buffer_bars:
                self.signal_buffer.pop(0)
            if len(self.signal_buffer) >= self.buffer_bars:
                if all(s == current_signal for s in self.signal_buffer):
                    return current_signal
        else:
            self.signal_buffer = []
        return "HOLD"
    
    def reset(self):
        self.signal_buffer = []

class BaseStrategy(ABC):
    def __init__(self, use_signal_buffer=True, buffer_bars=2):
        self.use_signal_buffer = use_signal_buffer
        self.signal_buffer = SignalBuffer(buffer_bars) if use_signal_buffer else None
    
    @abstractmethod
    def analyze(self, df: pd.DataFrame, extra_data: dict = None) -> StrategyResult:
        """Analyze stock data and return StrategyResult"""
        pass
