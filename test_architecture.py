import sys
import os

# 設定路徑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("🔍 開始架構完整性測試...")

try:
    print("1. [測試] 載入指標策略模組...", end="")
    from strategies.indicators.ma_crossover import MACrossoverStrategy
    from strategies.indicators.rsi_reversion import RSIStrategy
    from strategies.indicators.macd_momentum import MACDStrategy
    from strategies.indicators.kd_strategy import KDAnalyzer, KDBacktestStrategy
    print(" ✅ PASS")
except ImportError as e:
    print(f" ❌ FAIL: {e}")
    sys.exit(1)

try:
    print("2. [測試] 載入核心邏輯 (Main)...", end="")
    from main import calculate_final_decision, analyze_single_target
    print(" ✅ PASS")
except ImportError as e:
    print(f" ❌ FAIL: {e}")
    sys.exit(1)

try:
    print("3. [測試] 載入優化器 (Optimizer)...", end="")
    from optimizer_runner import find_best_params
    print(" ✅ PASS")
except ImportError as e:
    print(f" ❌ FAIL: {e}")
    sys.exit(1)

print("\n🎉 架構重構成功！所有模組路徑皆正確。")
