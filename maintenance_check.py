import os
import sys
from pathlib import Path

# 設定專案根目錄
PROJECT_ROOT = Path(__file__).resolve().parent

# === 1. 定義 V10.0 標準架構 (白名單) ===
# 只有這些檔案應該存在，其他的可能是舊檔案
EXPECTED_FILES = [
    "main.py",
    "discord_runner.py",
    "ai_runner.py",
    "optimizer_runner.py",
    "test_architecture.py", # 剛才的測試檔
    "maintenance_check.py", # 本檔案
    # Data
    "data/stock_config.json",
    "data/user_quota.json",
    "data/user_query_history.csv",
    # Crawlers
    "crawlers/__init__.py",
    "crawlers/news_scraper.py",
    # Strategies - Indicators
    "strategies/__init__.py",
    "strategies/indicators/__init__.py",
    "strategies/indicators/ma_crossover.py",
    "strategies/indicators/rsi_reversion.py",
    "strategies/indicators/macd_momentum.py",
    "strategies/indicators/kd_strategy.py",
    "strategies/indicators/bollinger_strategy.py",
    "strategies/indicators/valuation_strategy.py",
    "strategies/indicators/base_strategy.py",
    "strategies/indicators/schema.py",
    # Strategies - Price Action (V10 新增)
    "strategies/price_action/__init__.py",
    "strategies/price_action/pullback_strategy.py",
    # Utils
    "utils/logger.py",
    "utils/plotter.py",
    "utils/history_recorder.py",
    "utils/quota_manager.py",
    # Configs
    ".env",
    "requirements.txt"
]

def check_file_integrity():
    print("🔍 [1/3] 檢查核心檔案是否存在...")
    missing_count = 0
    for file_rel_path in EXPECTED_FILES:
        full_path = PROJECT_ROOT / file_rel_path
        if not full_path.exists():
            # 容許 data 資料夾內的檔案不存在 (因為可能是動態生成的)
            if "data/" in file_rel_path:
                print(f"   ⚠️  注意: 資料檔尚未生成 (可忽略): {file_rel_path}")
            else:
                print(f"   ❌ 缺失: {file_rel_path}")
                missing_count += 1
    
    if missing_count == 0:
        print("   ✅ 核心架構完整！")
    else:
        print(f"   ❌ 共有 {missing_count} 個核心檔案遺失！")

def find_orphan_files():
    print("\n🧹 [2/3] 掃描「沒用到的檔案」 (Orphan Files)...")
    print("   (這些檔案不在 V10.0 標準架構中，可能是重構後遺留的垃圾)")
    
    orphan_found = False
    
    # 遍歷所有檔案
    for root, dirs, files in os.walk(PROJECT_ROOT):
        # 忽略隱藏目錄 (如 .git, __pycache__, venv)
        if any(part.startswith('.') or part == 'venv' or part == '__pycache__' for part in Path(root).parts):
            continue
            
        for file in files:
            if file.endswith(".py") or file.endswith(".json"):
                full_path = Path(root) / file
                rel_path = full_path.relative_to(PROJECT_ROOT).as_posix()
                
                # 如果這個檔案不在我們的白名單中
                if rel_path not in EXPECTED_FILES:
                    # 特殊排除：忽略 data 資料夾下的暫存檔
                    if not rel_path.startswith("data/"):
                        print(f"   🗑️  發現殭屍檔案: {rel_path}")
                        orphan_found = True
                        
    if not orphan_found:
        print("   ✅ 環境非常乾淨，沒有發現殭屍檔案。")

def test_imports():
    print("\n🚀 [3/3] 測試模組引用 (Import Test)...")
    sys.path.insert(0, str(PROJECT_ROOT))
    
    try:
        from strategies.indicators.ma_crossover import MACrossoverStrategy
        from strategies.price_action.pullback_strategy import PullbackStrategy
        from main import analyze_single_target
        print("   ✅ 所有模組 Import 成功！路徑設定正確。")
    except ImportError as e:
        print(f"   ❌ Import 失敗: {e}")
        print("   請檢查 main.py 或 optimizer_runner.py 的 from ... import 路徑是否修正。")

if __name__ == "__main__":
    print(f"=== BMO V10.0 系統維護檢查 ===\n根目錄: {PROJECT_ROOT}\n")
    check_file_integrity()
    find_orphan_files()
    test_imports()
    print("\n===============================")
