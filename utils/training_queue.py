"""
众包模型训练队列系统 - 异步训练任务管理
支持参数网格搜索、任务队列、进度追踪
"""

import json
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
import uuid
import itertools
import time
import pandas as pd
from utils.logger import log_info, log_error, log_warn


QUEUE_FILE = "data/training_queue.json"
RESULT_DIR = "data/training_results"
MAX_WORKERS = 2  # 并发任务数 (避免资源耗尽)


class TrainingTask:
    """训练任务对象"""
    
    def __init__(self, task_dict):
        self.__dict__.update(task_dict)
    
    def to_dict(self):
        return self.__dict__
    
    @staticmethod
    def create(user_id: int, strategy: str, ticker: str, 
               start_date: str, end_date: str,
               target_roi: float = 15.0, target_win_rate: float = 0.60,
               param_grid: Optional[Dict] = None, channel_id: Optional[int] = None) -> "TrainingTask":
        """创建新的训练任务"""
        return TrainingTask({
            "task_id": f"train_{datetime.now().strftime('%Y%m%d')}_{str(uuid.uuid4())[:8]}",
            "user_id": user_id,
            "channel_id": channel_id,
            "status": "queued",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "started_at": None,
            "completed_at": None,
            "config": {
                "strategy": strategy,
                "stock_ticker": ticker,
                "start_date": start_date,
                "end_date": end_date,
                "target_roi": target_roi,
                "target_win_rate": target_win_rate,
                "param_grid": param_grid or {}
            },
            "results": None,
            "error": None,
            "progress": 0  # 进度百分比
        })


class TrainingQueue:
    """训练队列管理器"""
    
    def __init__(self):
        self.queue_file = QUEUE_FILE
        self.result_dir = RESULT_DIR
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        self.active_tasks = {}
        self.lock = threading.Lock()  # 文件操作互斥锁
        
        os.makedirs(self.result_dir, exist_ok=True)
        self._ensure_queue_file()
        
        log_info(f"🚀 训练队列初始化完成 (最大并发: {MAX_WORKERS})")
    
    def _ensure_queue_file(self):
        """确保队列文件存在"""
        if not os.path.exists(self.queue_file):
            os.makedirs(os.path.dirname(self.queue_file), exist_ok=True)
            with open(self.queue_file, 'w') as f:
                json.dump({"tasks": []}, f)
    
    def submit_training(self, user_id: int, strategy: str, ticker: str,
                       start_date: str, end_date: str,
                       target_roi: float = 15.0,
                       target_win_rate: float = 0.60,
                       param_grid: Optional[Dict] = None,
                       channel_id: Optional[int] = None) -> str:
        """
        提交訓練任務
        
        返回: task_id 或 None (如果數據驗證失敗)
        """
        # 驗證K線數據充分性
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        try:
            from main import fetch_stock_data_smart

            # 獲取指定時間段的數據 (fetch_stock_data_smart 回傳 dict，K線在 "df" 欄位，索引為日期)
            data_result = fetch_stock_data_smart(ticker)
            df = data_result.get("df") if data_result.get("status") == "success" else None

            if df is not None and not df.empty:
                if not isinstance(df.index, pd.DatetimeIndex):
                    df.index = pd.to_datetime(df.index)
                start = pd.to_datetime(start_date)
                end = pd.to_datetime(end_date)

                # 篩選日期範圍內的數據
                filtered_df = df[(df.index >= start) & (df.index <= end)]
                k_line_count = len(filtered_df)
                
                # 檢查K線數量
                MIN_K_LINES = 100
                if k_line_count < MIN_K_LINES:
                    warning_msg = (
                        f"⚠️ 數據不足警告: {ticker} 在 {start_date} 至 {end_date} 期間只有 {k_line_count} 根K線\n"
                        f"最少要求: {MIN_K_LINES} 根K線\n"
                        f"建議: 選擇更長的時間段 (至少 6 個月)"
                    )
                    log_warn(warning_msg)
                    print(f"⚠️ {warning_msg}")
            else:
                log_warn(f"無法獲取 {ticker} 的數據，將繼續提交任務但可能失敗")
        
        except Exception as e:
            log_warn(f"數據驗證檢查失敗 (非致命): {e}")
        
        # 默認參數網格
        if param_grid is None:
            param_grid = self._get_default_grid(strategy)
        
        task = TrainingTask.create(
            user_id, strategy, ticker, start_date, end_date,
            target_roi, target_win_rate, param_grid, channel_id
        )
        
        # 添加到队列 (线程安全)
        with self.lock:
            with open(self.queue_file, 'r') as f:
                data = json.load(f)
            
            data["tasks"].append(task.to_dict())
            
            with open(self.queue_file, 'w') as f:
                json.dump(data, f, indent=2)
        
        log_info(f"✅ 训练任务提交: {task.task_id} (用户: {user_id}, 策略: {strategy})")
        
        # 异步执行
        self.executor.submit(self._run_training, task.task_id)
        
        return task.task_id
    
    def _get_default_grid(self, strategy: str) -> Dict:
        """根据策略类型返回默认参数网格"""
        grids = {
            "MA交叉": {
                "fast_period": [10, 15, 20, 25],
                "slow_period": [40, 50, 60, 70]
            },
            "RSI反转": {
                "rsi_period": [10, 14, 20],
                "low_threshold": [20, 30, 40],
                "high_threshold": [60, 70, 80]
            },
            "MACD动能": {
                "fast_period": [8, 12, 15],
                "slow_period": [20, 26, 30],
                "signal_period": [5, 9, 12]
            },
            "KD随机指标": {
                "k_period": [9, 14, 21],
                "d_period": [3, 5, 9]
            },
            "布林带策略": {
                "period": [20, 25, 30],
                "std_dev": [1.5, 2.0, 2.5]
            },
        }
        return grids.get(strategy, {"param1": [1, 2], "param2": [3, 4]})
    
    def _run_training(self, task_id: str):
        """后台执行训练 (运行在线程池中)"""
        try:
            task = self.get_task(task_id)
            if not task:
                log_error(f"找不到任务: {task_id}")
                return
            
            # 更新状态为 running
            self._update_task_status(task_id, "running", 
                                    started_at=datetime.utcnow().isoformat() + "Z")
            
            # 执行参数网格搜索
            results = self._execute_grid_search(task, task_id)
            
            # 保存结果
            self._update_task_result(task_id, results, "completed")
            
            log_info(f"✅ 训练完成: {task_id}")
            self._fire_completion(task_id)
            
        except Exception as e:
            log_error(f"❌ 训练失败: {task_id}, {str(e)}")
            self._update_task_error(task_id, str(e))
            self._fire_completion(task_id)
    
    def _execute_grid_search(self, task: TrainingTask, task_id: str) -> Dict:
        """
        执行网格搜索优化参数
        
        返回最优参数组合及其性能指标
        """
        from optimizer_runner import run_backtest
        from main import fetch_stock_data_smart
        from utils.period_backtest import filter_data_by_date_range
        
        config = task.config
        strategy_name = config["strategy"]
        
        # 根据策略名称获取策略类
        strategy_class = self._get_strategy_class(strategy_name)
        if not strategy_class:
            raise ValueError(f"未知策略: {strategy_name}")
        
        # 获取数据
        log_info(f"📥 正在获取数据: {config['stock_ticker']}")
        data_result = fetch_stock_data_smart(config["stock_ticker"])
        if data_result["status"] != "success":
            raise RuntimeError(f"数据获取失败: {config['stock_ticker']}")
        
        df = data_result["df"]
        
        # 按日期范围筛选数据
        df_period = filter_data_by_date_range(df, config["start_date"], config["end_date"])
        if df_period.empty:
            raise RuntimeError(f"日期范围内无数据: {config['start_date']} ~ {config['end_date']}")
        if len(df_period) < 100:
            raise RuntimeError(f"資料太少：此時間段只有 {len(df_period)} 個交易日，回測至少需要 100 個（約 5 個月）。請改選『近一年』或『全部歷史』。")
        
        # 生成参数组合
        param_grid = config["param_grid"]
        param_combinations = self._generate_combinations(param_grid)
        total_combos = len(param_combinations)
        
        log_info(f"🔍 开始网格搜索: {total_combos}个参数组合")
        
        best_result = None
        best_score = -999
        results_log = []
        
        # 遍历所有参数组合
        for i, params in enumerate(param_combinations):
            try:
                # 执行回测 (返回8个值)
                roi, win_rate, total_trades, avg_win_ratio, avg_loss_pnl, max_dd, sharpe, rtot = run_backtest(
                    strategy_class, df_period, **params
                )
                
                # 计算综合评分 (权重可调; win_rate 已是百分比)
                score = roi * 0.4 + sharpe * 100 * 0.4 + win_rate * 0.2
                
                # run_backtest 回傳的 win_rate 已是百分比 (0-100)，不可再乘 100
                result_entry = {
                    "params": params,
                    "roi": round(roi, 2),
                    "win_rate": round(win_rate, 2),
                    "sharpe": round(sharpe, 2),
                    "total_trades": total_trades,
                    "max_dd": round(max_dd * 100, 2),
                    "score": round(score, 2)
                }
                results_log.append(result_entry)
                
                if score > best_score:
                    best_score = score
                    best_result = {
                        "best_params": params,
                        "best_roi": round(roi, 2),
                        "best_win_rate": round(win_rate, 2),
                        "best_sharpe": round(sharpe, 2),
                        "best_max_dd": round(max_dd * 100, 2),
                        "best_total_trades": total_trades,
                        "best_score": round(best_score, 2)
                    }
                
                # 更新进度
                progress = int((i + 1) / total_combos * 100)
                self._update_task_status(task_id, "running", progress=progress)
                
            except Exception as e:
                log_warn(f"⚠️ 参数组合失败: {params}, {str(e)}")
                continue
        
        if not best_result:
            raise RuntimeError("所有参数组合都失败了")
        
        # 添加汇总信息
        best_result["total_combinations_tested"] = total_combos
        best_result["successful_combinations"] = len(results_log)
        best_result["top_results"] = sorted(results_log, key=lambda x: x["score"], reverse=True)[:5]
        
        return best_result
    
    def _get_strategy_class(self, strategy_name: str):
        """根据策略名称获取策略类"""
        from optimizer_runner import TrendStrategy, RSIStrategy, MACDStrategy
        from strategies.indicators.kd_strategy import KDBacktestStrategy
        from strategies.indicators.bollinger_strategy import BollingerStrategy
        from strategies.indicators.valuation_strategy import ValuationStrategy
        from strategies.price_action.pullback_strategy import PullbackStrategy
        
        strategy_map = {
            "MA交叉": TrendStrategy,
            "RSI反转": RSIStrategy,
            "MACD动能": MACDStrategy,
            "KD随机指标": KDBacktestStrategy,
            "布林带策略": BollingerStrategy,
            "价值估值": ValuationStrategy,
            "回撤交易": PullbackStrategy,
        }
        
        return strategy_map.get(strategy_name)
    
    def _generate_combinations(self, param_grid: Dict) -> List[Dict]:
        """生成所有参数组合"""
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        
        combinations = []
        for combo in itertools.product(*values):
            combinations.append(dict(zip(keys, combo)))
        
        return combinations
    
    def get_task(self, task_id: str) -> Optional[TrainingTask]:
        """获取任务详情"""
        with self.lock:
            with open(self.queue_file, 'r') as f:
                data = json.load(f)
            
            for task_dict in data["tasks"]:
                if task_dict["task_id"] == task_id:
                    return TrainingTask(task_dict)
        
        return None
    
    def get_user_tasks(self, user_id: int, limit: int = 10) -> List[TrainingTask]:
        """获取用户的任务历史"""
        with self.lock:
            with open(self.queue_file, 'r') as f:
                data = json.load(f)
            
            user_tasks = [
                TrainingTask(t) for t in data["tasks"]
                if t["user_id"] == user_id
            ]
        
        return sorted(
            user_tasks,
            key=lambda t: t.created_at,
            reverse=True
        )[:limit]
    
    def _update_task_status(self, task_id: str, status: str, **extra_fields):
        """更新任务状态"""
        with self.lock:
            with open(self.queue_file, 'r') as f:
                data = json.load(f)
            
            for task in data["tasks"]:
                if task["task_id"] == task_id:
                    task["status"] = status
                    for k, v in extra_fields.items():
                        task[k] = v
                    break
            
            with open(self.queue_file, 'w') as f:
                json.dump(data, f, indent=2)
    
    def _update_task_result(self, task_id: str, results: Dict, status: str):
        """更新任务结果"""
        self._update_task_status(
            task_id, status,
            completed_at=datetime.utcnow().isoformat() + "Z",
            results=results,
            progress=100
        )
    
    def _update_task_error(self, task_id: str, error: str):
        """更新任务错误"""
        self._update_task_status(
            task_id, "failed",
            completed_at=datetime.utcnow().isoformat() + "Z",
            error=error,
            progress=0
        )

    def _fire_completion(self, task_id: str):
        """任務結束(完成/失敗)後通知 discord_runner 把結果推回頻道；通知錯誤不影響 worker。"""
        try:
            if _completion_callback is None:
                return
            task = self.get_task(task_id)
            if task is not None:
                _completion_callback(task.to_dict())
        except Exception as e:
            log_error(f"訓練完成通知失敗(已忽略): {e}")


# 任務完成回呼（discord_runner 在 on_ready 註冊）
_completion_callback = None


def set_completion_callback(cb):
    """註冊『訓練完成/失敗』回呼。cb(task_dict) 會在 worker 執行緒被呼叫。"""
    global _completion_callback
    _completion_callback = cb


# 全局实例
_queue = None


def get_training_queue() -> TrainingQueue:
    """获取全局训练队列实例"""
    global _queue
    if _queue is None:
        _queue = TrainingQueue()
    return _queue
