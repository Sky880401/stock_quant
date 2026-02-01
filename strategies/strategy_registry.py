"""
策略注册表系统 - 维护所有可用策略的元数据
"""

import json
import os
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
from datetime import datetime


@dataclass
class StrategyMetadata:
    """策略元数据"""
    name: str              # 策略名称
    description: str       # 描述
    category: str          # 分类: indicator/ml/price_action/comprehensive
    filepath: str          # 源代码路径
    class_name: str        # 类名
    difficulty: str        # 难度: easy/medium/hard
    
    # 性能指标
    accuracy: float        # 准确率
    win_rate: float        # 胜率
    sharpe_ratio: float    # Sharpe比率
    avg_roi: float         # 平均ROI
    total_trades: int      # 总交易数
    last_updated: str      # 最后更新时间


class StrategyRegistry:
    """策略注册表 - 维护所有可用策略的元数据"""
    
    def __init__(self):
        self.strategies: Dict[str, StrategyMetadata] = {}
        self.registry_file = "data/strategy_registry.json"
        self._load_from_config()
    
    def _load_from_config(self):
        """从 data/strategy_registry.json 加载"""
        try:
            if os.path.exists(self.registry_file):
                with open(self.registry_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                
                for strategy_data in config.get("strategies", []):
                    meta = StrategyMetadata(**strategy_data)
                    self.strategies[meta.name] = meta
            else:
                self._init_default_strategies()
                self._save_to_config()
        except Exception as e:
            print(f"⚠️ 加载策略注册表失败: {e}，使用默认配置")
            self._init_default_strategies()
    
    def _init_default_strategies(self):
        """初始化默认策略列表"""
        defaults = [
            StrategyMetadata(
                name="MA交叉",
                description="20日/50日移动平均线交叉策略，适合趋势跟踪",
                category="indicator",
                filepath="strategies/indicators/ma_crossover.py",
                class_name="MACrossoverStrategy",
                difficulty="easy",
                accuracy=0.62,
                win_rate=0.62,
                sharpe_ratio=1.10,
                avg_roi=8.5,
                total_trades=245,
                last_updated=datetime.now().isoformat()
            ),
            StrategyMetadata(
                name="RSI反转",
                description="RSI超买超卖反转策略，适合震荡市",
                category="indicator",
                filepath="strategies/indicators/rsi_reversion.py",
                class_name="RSIReversionStrategy",
                difficulty="easy",
                accuracy=0.58,
                win_rate=0.58,
                sharpe_ratio=0.95,
                avg_roi=6.2,
                total_trades=312,
                last_updated=datetime.now().isoformat()
            ),
            StrategyMetadata(
                name="MACD动能",
                description="MACD动能驱动策略，综合快慢线信号",
                category="indicator",
                filepath="strategies/indicators/macd_momentum.py",
                class_name="MACDMomentumStrategy",
                difficulty="medium",
                accuracy=0.65,
                win_rate=0.65,
                sharpe_ratio=1.25,
                avg_roi=11.3,
                total_trades=198,
                last_updated=datetime.now().isoformat()
            ),
            StrategyMetadata(
                name="KD随机指标",
                description="KD随机指标策略，快速反应市场过热过冷",
                category="indicator",
                filepath="strategies/indicators/kd_strategy.py",
                class_name="KDBacktestStrategy",
                difficulty="medium",
                accuracy=0.60,
                win_rate=0.60,
                sharpe_ratio=1.02,
                avg_roi=7.8,
                total_trades=267,
                last_updated=datetime.now().isoformat()
            ),
            StrategyMetadata(
                name="布林带策略",
                description="基于布林带的波动率策略，回归均值交易",
                category="indicator",
                filepath="strategies/indicators/bollinger_strategy.py",
                class_name="BollingerStrategy",
                difficulty="medium",
                accuracy=0.64,
                win_rate=0.64,
                sharpe_ratio=1.18,
                avg_roi=10.1,
                total_trades=224,
                last_updated=datetime.now().isoformat()
            ),
            StrategyMetadata(
                name="价值估值",
                description="P/E + PB + 现金流综合估值策略",
                category="indicator",
                filepath="strategies/indicators/valuation_strategy.py",
                class_name="ValuationStrategy",
                difficulty="hard",
                accuracy=0.59,
                win_rate=0.59,
                sharpe_ratio=0.88,
                avg_roi=5.4,
                total_trades=156,
                last_updated=datetime.now().isoformat()
            ),
            StrategyMetadata(
                name="回撤交易",
                description="价格行动回撤进场策略，风险回报比优",
                category="price_action",
                filepath="strategies/price_action/pullback_strategy.py",
                class_name="PullbackStrategy",
                difficulty="medium",
                accuracy=0.66,
                win_rate=0.66,
                sharpe_ratio=1.32,
                avg_roi=12.7,
                total_trades=189,
                last_updated=datetime.now().isoformat()
            ),
            StrategyMetadata(
                name="混合预测 (ML)",
                description="5指标加权混合机器学习模型",
                category="ml",
                filepath="strategies/ml_models/hybrid_predictor.py",
                class_name="HybridPredictor",
                difficulty="hard",
                accuracy=0.68,
                win_rate=0.68,
                sharpe_ratio=1.45,
                avg_roi=15.2,
                total_trades=287,
                last_updated=datetime.now().isoformat()
            ),
            StrategyMetadata(
                name="综合策略",
                description="综合所有指标的高级策略，带AI辅助分析",
                category="comprehensive",
                filepath="strategies/comprehensive_strategy.py",
                class_name="ComprehensiveStrategy",
                difficulty="hard",
                accuracy=0.70,
                win_rate=0.70,
                sharpe_ratio=1.58,
                avg_roi=18.5,
                total_trades=342,
                last_updated=datetime.now().isoformat()
            ),
        ]
        self.strategies = {s.name: s for s in defaults}
    
    def _save_to_config(self):
        """保存到 data/strategy_registry.json"""
        try:
            os.makedirs("data", exist_ok=True)
            config = {
                "generated_at": datetime.now().isoformat(),
                "version": "1.0",
                "strategies": [asdict(s) for s in self.strategies.values()]
            }
            with open(self.registry_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存策略注册表失败: {e}")
    
    def get_by_category(self, category: str) -> List[StrategyMetadata]:
        """按分类返回策略"""
        return [s for s in self.strategies.values() if s.category == category]
    
    def get_top_by_metric(self, metric: str, top_n: int = 5) -> List[StrategyMetadata]:
        """返回某指标Top N的策略"""
        sorted_strats = sorted(
            self.strategies.values(),
            key=lambda x: getattr(x, metric, 0),
            reverse=True
        )
        return sorted_strats[:top_n]
    
    def get_all_sorted(self, sort_by: str = "win_rate") -> List[StrategyMetadata]:
        """返回排序后的所有策略"""
        return sorted(
            self.strategies.values(),
            key=lambda x: getattr(x, sort_by, 0),
            reverse=True
        )
    
    def update_strategy_performance(self, name: str, accuracy: float, 
                                   win_rate: float, sharpe_ratio: float, 
                                   avg_roi: float, total_trades: int):
        """更新策略性能指标"""
        if name in self.strategies:
            self.strategies[name].accuracy = accuracy
            self.strategies[name].win_rate = win_rate
            self.strategies[name].sharpe_ratio = sharpe_ratio
            self.strategies[name].avg_roi = avg_roi
            self.strategies[name].total_trades = total_trades
            self.strategies[name].last_updated = datetime.now().isoformat()
            self._save_to_config()


# 全局实例
_registry = None


def get_strategy_registry() -> StrategyRegistry:
    """获取全局策略注册表实例"""
    global _registry
    if _registry is None:
        _registry = StrategyRegistry()
    return _registry
