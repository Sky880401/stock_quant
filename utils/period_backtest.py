"""
时间段特定回测分析模块
用途: 支持在特定历史时期内进行回测，用于分析策略在不同市场环境下的表现
"""

import pandas as pd
import backtrader as bt
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import json
import os


PERIOD_RESULTS_FILE = "data/period_backtest_results.json"


def filter_data_by_date_range(df: pd.DataFrame, start_date: Optional[str], end_date: Optional[str]) -> pd.DataFrame:
    """
    按日期范围筛选数据
    参数:
        df: 原始数据DataFrame
        start_date: 开始日期 (格式: "2026-01-01" 或 "2025-01")
        end_date: 结束日期 (格式: "2026-01-31" 或 "2025-12")
    返回:
        筛选后的DataFrame（仅包含指定时期内的数据）
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    
    # 如果提供了开始日期
    if start_date:
        start_dt = pd.to_datetime(start_date)
        df = df[df.index >= start_dt]
    
    # 如果提供了结束日期
    if end_date:
        end_dt = pd.to_datetime(end_date)
        # 如果只是年月，添加到月末
        if len(end_date) == 7:  # "2026-01" 格式
            end_dt = end_dt + pd.DateOffset(months=1) - timedelta(days=1)
        df = df[df.index <= end_dt]
    
    return df


def run_backtest_by_period(strategy_cls, df: pd.DataFrame, period_name: str, 
                          start_date: Optional[str] = None, 
                          end_date: Optional[str] = None,
                          **kwargs) -> Dict:
    """
    在特定时间段内运行回测
    参数:
        strategy_cls: 策略类
        df: 完整的历史数据DataFrame
        period_name: 时间段名称 (例如 "2025-Q1", "2026-01", "2025-Full")
        start_date: 时间段开始日期
        end_date: 时间段结束日期
        **kwargs: 策略参数
    返回:
        {
            'period': 'xxx',
            'start_date': 'xxx',
            'end_date': 'xxx',
            'data_points': int,
            'roi': float,
            'win_rate': float,
            'total_trades': int,
            'avg_win_ratio': float,
            'max_drawdown': float,
            'sharpe': float,
            'trades': list
        }
    """
    # 筛选时间段数据
    period_df = filter_data_by_date_range(df, start_date, end_date)
    
    if period_df.empty or len(period_df) < 10:
        return {
            'period': period_name,
            'start_date': str(start_date),
            'end_date': str(end_date),
            'error': '数据不足，无法进行回测',
            'data_points': len(period_df)
        }
    
    # 执行回测（复用optimizer_runner中的逻辑）
    if not isinstance(period_df.index, pd.DatetimeIndex):
        period_df.index = pd.to_datetime(period_df.index)
    period_df = period_df[~period_df.index.duplicated(keep='first')].sort_index()
    if period_df.isnull().values.any():
        period_df = period_df.fillna(method='ffill').fillna(method='bfill')
    
    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_cls, **kwargs)
    vol_col = 'Volume' if 'Volume' in period_df.columns else 'volume'
    data = bt.feeds.PandasData(dataname=period_df, volume=vol_col)
    cerebro.adddata(data)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.001425)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    
    try:
        results = cerebro.run()
        strat = results[0]
        
        # 计算ROI
        roi = (cerebro.broker.getvalue() - 100000.0) / 100000.0 * 100
        
        # 交易分析
        trade_analysis = strat.analyzers.trades.get_analysis()
        total_trades = trade_analysis.get('total', {}).get('total', 0)
        won_trades = trade_analysis.get('won', {}).get('total', 0)
        
        win_rate = (won_trades / total_trades * 100) if total_trades > 0 else 0.0
        
        # 平均赢损比
        avg_win_pnl = 0.0
        avg_loss_pnl = 0.0
        won_pnl = trade_analysis.get('won', {}).get('pnl', {}).get('total', 0)
        lost_pnl = abs(trade_analysis.get('lost', {}).get('pnl', {}).get('total', 0))
        
        if won_trades > 0:
            avg_win_pnl = won_pnl / won_trades
        if (total_trades - won_trades) > 0:
            avg_loss_pnl = lost_pnl / (total_trades - won_trades)
        
        avg_win_ratio = avg_win_pnl / avg_loss_pnl if avg_loss_pnl > 0 else 1.5
        
        # Sharpe比率和最大回撤
        drawdown_analysis = strat.analyzers.drawdown.get_analysis()
        max_dd = abs(drawdown_analysis.get('max', {}).get('drawdown', 0.0))
        sharpe_approx = roi / max(max_dd, 0.01) if max_dd > 0 else roi * 10
        
        # 获取交易列表
        trades_list = []
        for trade_data in trade_analysis.get('trades', []):
            if isinstance(trade_data, dict):
                trades_list.append({
                    'pnl': trade_data.get('pnl', 0),
                    'pnl%': trade_data.get('pnl%', 0)
                })
        
        result = {
            'period': period_name,
            'start_date': str(period_df.index[0].date()) if len(period_df) > 0 else str(start_date),
            'end_date': str(period_df.index[-1].date()) if len(period_df) > 0 else str(end_date),
            'data_points': len(period_df),
            'roi': round(roi, 2),
            'win_rate': round(win_rate, 1),
            'total_trades': total_trades,
            'avg_win_ratio': round(avg_win_ratio, 2),
            'max_drawdown': round(max_dd, 2),
            'sharpe': round(sharpe_approx, 2),
            'trades': trades_list[:5]  # 只保留前5个交易
        }
        
        return result
    
    except Exception as e:
        return {
            'period': period_name,
            'start_date': str(start_date),
            'end_date': str(end_date),
            'error': str(e),
            'data_points': len(period_df)
        }


def analyze_multiple_periods(strategy_cls, df: pd.DataFrame, periods: List[Dict],
                            **kwargs) -> List[Dict]:
    """
    分析多个时间段
    参数:
        strategy_cls: 策略类
        df: 完整历史数据
        periods: 时间段列表，每个元素为 {'name': 'xxx', 'start': 'xxx', 'end': 'xxx'}
        **kwargs: 策略参数
    返回:
        多个时间段的回测结果列表
    """
    results = []
    for period in periods:
        result = run_backtest_by_period(
            strategy_cls, df,
            period.get('name', 'unknown'),
            period.get('start'),
            period.get('end'),
            **kwargs
        )
        results.append(result)
    
    return results


def get_predefined_periods(years: Optional[List[int]] = None, 
                          include_quarters: bool = True) -> List[Dict]:
    """
    生成预定义的时间段列表
    参数:
        years: 年份列表 (例如 [2025, 2026])
        include_quarters: 是否包含季度分析
    返回:
        时间段列表
    """
    if years is None:
        years = [2025, 2026]
    
    periods = []
    
    for year in years:
        # 整年
        periods.append({
            'name': f'{year}-Full',
            'start': f'{year}-01-01',
            'end': f'{year}-12-31'
        })
        
        # 按月（可选）
        if include_quarters:
            # 四个季度
            quarters = [
                {'name': f'{year}-Q1', 'start': f'{year}-01-01', 'end': f'{year}-03-31'},
                {'name': f'{year}-Q2', 'start': f'{year}-04-01', 'end': f'{year}-06-30'},
                {'name': f'{year}-Q3', 'start': f'{year}-07-01', 'end': f'{year}-09-30'},
                {'name': f'{year}-Q4', 'start': f'{year}-10-01', 'end': f'{year}-12-31'},
            ]
            periods.extend(quarters)
    
    return periods


def compare_strategy_across_periods(strategy_cls, df: pd.DataFrame, strategy_name: str,
                                   periods: Optional[List[Dict]] = None,
                                   **kwargs) -> Dict:
    """
    对比策略在多个时期的表现
    返回:
        {
            'strategy': 'xxx',
            'analysis_time': 'xxx',
            'periods': [...],
            'summary': {
                'avg_roi': float,
                'avg_win_rate': float,
                'most_stable_period': str,
                'best_period': str,
                'worst_period': str
            }
        }
    """
    if periods is None:
        periods = get_predefined_periods()
    
    period_results = analyze_multiple_periods(strategy_cls, df, periods, **kwargs)
    
    # 过滤掉有错误的结果
    valid_results = [r for r in period_results if 'error' not in r]
    
    if not valid_results:
        return {
            'strategy': strategy_name,
            'error': '所有时期分析都失败了',
            'periods': period_results
        }
    
    # 计算统计数据
    rois = [r['roi'] for r in valid_results]
    win_rates = [r['win_rate'] for r in valid_results]
    
    summary = {
        'avg_roi': round(sum(rois) / len(rois), 2),
        'avg_win_rate': round(sum(win_rates) / len(win_rates), 1),
        'roi_std': round(pd.Series(rois).std(), 2),  # ROI标准差（衡量稳定性）
        'best_period': valid_results[rois.index(max(rois))]['period'],
        'worst_period': valid_results[rois.index(min(rois))]['period'],
        'total_periods': len(valid_results)
    }
    
    return {
        'strategy': strategy_name,
        'analysis_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'periods': period_results,
        'summary': summary
    }


def save_period_results(analysis_result: Dict):
    """保存分析结果到文件"""
    os.makedirs(os.path.dirname(PERIOD_RESULTS_FILE), exist_ok=True)
    
    # 加载现有结果
    existing = {}
    if os.path.exists(PERIOD_RESULTS_FILE):
        try:
            with open(PERIOD_RESULTS_FILE, 'r') as f:
                existing = json.load(f)
        except:
            pass
    
    # 添加新结果
    strategy_name = analysis_result.get('strategy', 'unknown')
    existing[strategy_name] = analysis_result
    
    # 保存
    with open(PERIOD_RESULTS_FILE, 'w') as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)


def load_period_results(strategy_name: Optional[str] = None) -> Dict:
    """加载保存的分析结果"""
    if not os.path.exists(PERIOD_RESULTS_FILE):
        return {}
    
    try:
        with open(PERIOD_RESULTS_FILE, 'r') as f:
            data = json.load(f)
            if strategy_name:
                return data.get(strategy_name, {})
            return data
    except:
        return {}


if __name__ == "__main__":
    # 使用示例
    print("时间段特定回测分析模块已加载")
    print("\n主要功能:")
    print("1. filter_data_by_date_range() - 按日期筛选数据")
    print("2. run_backtest_by_period() - 在特定时期内回测")
    print("3. analyze_multiple_periods() - 分析多个时期")
    print("4. compare_strategy_across_periods() - 对比策略在多个时期的表现")
    print("5. save_period_results() / load_period_results() - 持久化结果")
