"""
混合预测模型 - 基于现有技术指标的置信度集成系统
用途: 结合多个技术指标生成综合预测信号，为后续ML模型扩展提供基础
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, List, Optional
import talib
from datetime import datetime


class HybridPredictorBase:
    """
    混合预测器基类
    集成多个技术指标，通过加权组合生成综合预测信号
    """
    
    def __init__(self, weights: Optional[Dict[str, float]] = None):
        """
        参数:
            weights: 各指标的权重字典，格式: {'ma_crossover': 0.2, 'rsi': 0.3, ...}
        """
        self.default_weights = {
            'ma_crossover': 0.20,   # 移动平均线交叉
            'rsi': 0.25,            # RSI相对强度
            'macd': 0.25,           # MACD动量
            'kd': 0.15,             # KD指标
            'bb': 0.15              # 布林带
        }
        
        self.weights = weights or self.default_weights
        # 归一化权重
        total = sum(self.weights.values())
        self.weights = {k: v/total for k, v in self.weights.items()}
        
        self.signals = {}
        self.confidences = {}
    
    def calculate_ma_signal(self, df: pd.DataFrame, fast_period: int = 20, 
                           slow_period: int = 60) -> Tuple[float, float]:
        """
        移动平均线信号
        返回: (signal, confidence)
        signal: -1(卖出), 0(持仓), 1(买入)
        confidence: 0-1的置信度
        """
        if len(df) < slow_period:
            return 0, 0.0
        
        close = df['Close'].values
        ma_fast = talib.SMA(close, fast_period)
        ma_slow = talib.SMA(close, slow_period)
        
        current_fast = ma_fast[-1]
        current_slow = ma_slow[-1]
        prev_fast = ma_fast[-2]
        prev_slow = ma_slow[-2]
        
        # 判断交叉
        if prev_fast <= prev_slow and current_fast > current_slow:
            signal = 1  # 金叉买入
            confidence = min(1.0, (current_fast - current_slow) / current_slow * 100)
        elif prev_fast >= prev_slow and current_fast < current_slow:
            signal = -1  # 死叉卖出
            confidence = min(1.0, (current_slow - current_fast) / current_slow * 100)
        else:
            signal = 0
            # 距离交叉越近，置信度越高
            distance = abs(current_fast - current_slow) / current_slow
            confidence = max(0.0, 1.0 - distance * 10)
        
        return signal, confidence
    
    def calculate_rsi_signal(self, df: pd.DataFrame, period: int = 14,
                            oversold: float = 30, overbought: float = 70) -> Tuple[float, float]:
        """
        RSI相对强度信号
        """
        if len(df) < period:
            return 0, 0.0
        
        close = df['Close'].values
        rsi = talib.RSI(close, period)
        
        current_rsi = rsi[-1]
        
        if pd.isna(current_rsi):
            return 0, 0.0
        
        if current_rsi < oversold:
            signal = 1  # 超卖买入
            confidence = min(1.0, (oversold - current_rsi) / oversold)
        elif current_rsi > overbought:
            signal = -1  # 超买卖出
            confidence = min(1.0, (current_rsi - overbought) / (100 - overbought))
        else:
            signal = 0
            # 中立区置信度
            confidence = abs(current_rsi - 50) / 50
        
        return signal, confidence
    
    def calculate_macd_signal(self, df: pd.DataFrame, fast: int = 12,
                             slow: int = 26, signal: int = 9) -> Tuple[float, float]:
        """
        MACD动量信号
        """
        if len(df) < slow + signal:
            return 0, 0.0
        
        close = df['Close'].values
        macd, signal_line, histogram = talib.MACD(close, fast, slow, signal)
        
        current_macd = macd[-1]
        current_signal = signal_line[-1]
        current_hist = histogram[-1]
        
        if pd.isna(current_macd) or pd.isna(current_signal):
            return 0, 0.0
        
        if current_hist > 0 and current_macd > current_signal:
            signal = 1  # MACD向上买入
            confidence = min(1.0, abs(current_hist) / (abs(current_macd) + 0.01))
        elif current_hist < 0 and current_macd < current_signal:
            signal = -1  # MACD向下卖出
            confidence = min(1.0, abs(current_hist) / (abs(current_macd) + 0.01))
        else:
            signal = 0
            confidence = 0.3
        
        return signal, confidence
    
    def calculate_bb_signal(self, df: pd.DataFrame, period: int = 20,
                           num_std: float = 2.0) -> Tuple[float, float]:
        """
        布林带信号
        """
        if len(df) < period:
            return 0, 0.0
        
        close = df['Close'].values
        upper, middle, lower = talib.BBANDS(close, period, num_std, num_std, 0)
        
        current_close = close[-1]
        current_upper = upper[-1]
        current_lower = lower[-1]
        current_middle = middle[-1]
        
        if pd.isna(current_upper) or pd.isna(current_lower):
            return 0, 0.0
        
        total_width = current_upper - current_lower
        close_to_lower = current_close - current_lower
        
        if close_to_lower / total_width < 0.2:
            signal = 1  # 触及下轨买入
            confidence = min(1.0, 1.0 - (close_to_lower / total_width) * 5)
        elif close_to_lower / total_width > 0.8:
            signal = -1  # 触及上轨卖出
            confidence = min(1.0, ((close_to_lower / total_width) - 0.8) * 5)
        else:
            signal = 0
            # 中间位置置信度
            distance_to_middle = abs(current_close - current_middle)
            confidence = max(0.1, 1.0 - distance_to_middle / (total_width / 2))
        
        return signal, confidence
    
    def calculate_kd_signal(self, df: pd.DataFrame, fastk_period: int = 9,
                           slowk_period: int = 3, slowd_period: int = 3) -> Tuple[float, float]:
        """
        KD随机指标信号
        """
        if len(df) < fastk_period + slowk_period:
            return 0, 0.0
        
        high = df['High'].values
        low = df['Low'].values
        close = df['Close'].values
        
        slowk, slowd = talib.STOCH(high, low, close, fastk_period, slowk_period, slowd_period)
        
        current_k = slowk[-1]
        current_d = slowd[-1]
        prev_k = slowk[-2] if len(slowk) > 1 else current_k
        prev_d = slowd[-2] if len(slowd) > 1 else current_d
        
        if pd.isna(current_k) or pd.isna(current_d):
            return 0, 0.0
        
        if prev_k <= prev_d and current_k > current_d and current_k < 50:
            signal = 1  # KD金叉且未超买
            confidence = min(1.0, (50 - current_k) / 50)
        elif prev_k >= prev_d and current_k < current_d and current_k > 50:
            signal = -1  # KD死叉且未超卖
            confidence = min(1.0, (current_k - 50) / 50)
        else:
            signal = 0
            confidence = 0.2
        
        return signal, confidence
    
    def predict(self, df: pd.DataFrame) -> Dict[str, any]:
        """
        综合预测
        返回:
            {
                'action': 'BUY' | 'SELL' | 'HOLD',
                'confidence': 0-1,
                'signal_strength': -1到1,
                'components': {
                    'ma_crossover': (signal, conf),
                    'rsi': (signal, conf),
                    ...
                }
            }
        """
        components = {}
        
        # 收集所有信号
        try:
            if self.weights.get('ma_crossover', 0) > 0:
                components['ma_crossover'] = self.calculate_ma_signal(df)
            if self.weights.get('rsi', 0) > 0:
                components['rsi'] = self.calculate_rsi_signal(df)
            if self.weights.get('macd', 0) > 0:
                components['macd'] = self.calculate_macd_signal(df)
            if self.weights.get('bb', 0) > 0:
                components['bb'] = self.calculate_bb_signal(df)
            if self.weights.get('kd', 0) > 0:
                components['kd'] = self.calculate_kd_signal(df)
        except Exception as e:
            print(f"⚠️ 计算信号时出错: {e}")
            return {
                'action': 'HOLD',
                'confidence': 0.0,
                'signal_strength': 0.0,
                'error': str(e)
            }
        
        # 加权组合
        total_signal = 0.0
        total_confidence = 0.0
        
        for indicator, (signal, confidence) in components.items():
            weight = self.weights.get(indicator, 0)
            total_signal += signal * weight
            total_confidence += confidence * weight
        
        # 确定行动和置信度
        if total_signal > 0.3:
            action = 'BUY'
        elif total_signal < -0.3:
            action = 'SELL'
        else:
            action = 'HOLD'
        
        return {
            'action': action,
            'confidence': round(total_confidence, 2),
            'signal_strength': round(total_signal, 2),
            'components': components,
            'timestamp': datetime.now().isoformat()
        }


class AdaptiveWeightPredictor(HybridPredictorBase):
    """
    自适应权重预测器
    根据市场波动性自动调整权重
    """
    
    def __init__(self):
        super().__init__()
        self.atr_period = 14
    
    def calculate_adaptive_weights(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        根据ATR计算自适应权重
        高波动性 → 增加趋势指标权重
        低波动性 → 增加超买超卖指标权重
        """
        if len(df) < self.atr_period:
            return self.weights
        
        high = df['High'].values
        low = df['Low'].values
        close = df['Close'].values
        
        atr = talib.ATR(high, low, close, self.atr_period)
        current_atr = atr[-1]
        
        # 归一化ATR
        atr_pct = current_atr / close[-1] * 100
        
        if atr_pct > 2.0:  # 高波动性
            adaptive = {
                'ma_crossover': 0.30,
                'macd': 0.30,
                'rsi': 0.15,
                'kd': 0.15,
                'bb': 0.10
            }
        elif atr_pct < 0.5:  # 低波动性
            adaptive = {
                'ma_crossover': 0.10,
                'rsi': 0.35,
                'kd': 0.35,
                'macd': 0.10,
                'bb': 0.10
            }
        else:  # 中等波动性
            adaptive = self.default_weights.copy()
        
        # 归一化
        total = sum(adaptive.values())
        return {k: v/total for k, v in adaptive.items()}
    
    def predict(self, df: pd.DataFrame) -> Dict:
        """
        使用自适应权重进行预测
        """
        self.weights = self.calculate_adaptive_weights(df)
        return super().predict(df)


def create_predictor(predictor_type: str = 'hybrid') -> HybridPredictorBase:
    """
    工厂函数，创建预测器实例
    """
    if predictor_type == 'adaptive':
        return AdaptiveWeightPredictor()
    else:  # 默认混合预测器
        return HybridPredictorBase()


if __name__ == "__main__":
    print("混合预测模型模块已加载")
    print("\n主要类:")
    print("1. HybridPredictorBase - 基础混合预测器")
    print("2. AdaptiveWeightPredictor - 自适应权重预测器")
    print("\n使用示例:")
    print(">>> predictor = create_predictor('hybrid')")
    print(">>> result = predictor.predict(df)")
    print(">>> print(result['action'], result['confidence'])")
