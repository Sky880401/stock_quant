"""
用户查询统计与热搜排行系统
用途: 分析用户查询数据，生成排行榜和用户推荐成功率统计
"""

import pandas as pd
import os
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict
import discord


QUERY_FILE = "data/user_query_history.csv"


def load_query_history() -> pd.DataFrame:
    """
    加载用户查询历史
    返回: DataFrame或空DataFrame（如果文件不存在）
    """
    if not os.path.exists(QUERY_FILE):
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(QUERY_FILE)
        # 清理空白字符
        df.columns = df.columns.str.strip()
        for col in df.select_dtypes(include=['object']).columns:
            df[col] = df[col].str.strip()
        return df
    except Exception as e:
        print(f"❌ 加载查询历史失败: {e}")
        return pd.DataFrame()


def calculate_user_stats(df: pd.DataFrame) -> Dict[str, Dict]:
    """
    计算每个用户的统计数据
    返回格式: {
        "user_name": {
            "query_count": int,
            "avg_confidence": float,
            "favorite_ticker": str,
            "favorite_action": str,
            "success_rate": float,
            "avg_roi": float,
            "best_strategy": str
        }
    }
    """
    if df.empty:
        return {}
    
    user_stats = {}
    
    for user in df['User'].unique():
        user_df = df[df['User'] == user]
        
        # 计算成功率（基于ROI > 0）
        roi_values = pd.to_numeric(user_df['Backtest_ROI'], errors='coerce')
        valid_roi = roi_values.dropna()
        success_count = (valid_roi > 0).sum()
        total_count = len(valid_roi)
        success_rate = (success_count / total_count * 100) if total_count > 0 else 0
        
        # 平均ROI
        avg_roi = valid_roi[valid_roi > 0].mean() if (valid_roi > 0).any() else 0
        
        # 最常查询的股票
        ticker_counts = user_df['Ticker'].value_counts()
        favorite_ticker = ticker_counts.index[0] if len(ticker_counts) > 0 else "N/A"
        
        # 最常用的Action
        action_counts = user_df['Action'].value_counts()
        favorite_action = action_counts.index[0] if len(action_counts) > 0 else "N/A"
        
        # 平均置信度
        avg_confidence = pd.to_numeric(user_df['Confidence'], errors='coerce').mean()
        
        # 最佳策略（最高平均ROI的Action）
        best_strategy = "N/A"
        best_roi = -float('inf')
        for action in user_df['Action'].unique():
            action_df = user_df[user_df['Action'] == action]
            action_roi = pd.to_numeric(action_df['Backtest_ROI'], errors='coerce').mean()
            if action_roi > best_roi:
                best_roi = action_roi
                best_strategy = action
        
        user_stats[user] = {
            'query_count': len(user_df),
            'avg_confidence': round(avg_confidence, 2) if pd.notna(avg_confidence) else 0,
            'favorite_ticker': favorite_ticker,
            'favorite_action': favorite_action,
            'success_rate': round(success_rate, 1),
            'avg_roi': round(avg_roi, 2),
            'best_strategy': best_strategy
        }
    
    return user_stats


def calculate_ticker_stats(df: pd.DataFrame) -> Dict[str, Dict]:
    """
    计算每个股票的统计数据
    返回格式: {
        "ticker": {
            "stock_name": str,
            "query_count": int,
            "avg_confidence": float,
            "avg_roi": float,
            "success_rate": float,
            "queried_by": List[str],
            "most_common_action": str
        }
    }
    """
    if df.empty:
        return {}
    
    ticker_stats = {}
    
    for ticker in df['Ticker'].unique():
        ticker_df = df[df['Ticker'] == ticker]
        
        # 计算成功率
        roi_values = pd.to_numeric(ticker_df['Backtest_ROI'], errors='coerce')
        valid_roi = roi_values.dropna()
        success_count = (valid_roi > 0).sum()
        total_count = len(valid_roi)
        success_rate = (success_count / total_count * 100) if total_count > 0 else 0
        
        # 平均ROI
        avg_roi = valid_roi[valid_roi > 0].mean() if (valid_roi > 0).any() else 0
        
        # 平均置信度
        avg_confidence = pd.to_numeric(ticker_df['Confidence'], errors='coerce').mean()
        
        # 最常见的Action
        action_counts = ticker_df['Action'].value_counts()
        most_common_action = action_counts.index[0] if len(action_counts) > 0 else "N/A"
        
        # 查询用户列表
        queried_by = ticker_df['User'].unique().tolist()
        
        # 股票名称
        stock_name = ticker_df['StockName'].iloc[0] if len(ticker_df) > 0 else ticker
        
        ticker_stats[ticker] = {
            'stock_name': stock_name,
            'query_count': len(ticker_df),
            'avg_confidence': round(avg_confidence, 2) if pd.notna(avg_confidence) else 0,
            'avg_roi': round(avg_roi, 2),
            'success_rate': round(success_rate, 1),
            'queried_by': queried_by,
            'most_common_action': most_common_action
        }
    
    return ticker_stats


def get_top_hot_searches(df: pd.DataFrame, top_n: int = 10) -> List[Tuple[str, str, int, float]]:
    """
    获取热搜排行榜
    返回: [(ticker, stock_name, query_count, success_rate), ...]
    """
    ticker_stats = calculate_ticker_stats(df)
    
    # 按查询次数排序
    sorted_tickers = sorted(
        ticker_stats.items(),
        key=lambda x: x[1]['query_count'],
        reverse=True
    )[:top_n]
    
    return [
        (ticker, stats['stock_name'], stats['query_count'], stats['success_rate'])
        for ticker, stats in sorted_tickers
    ]


def get_top_users(df: pd.DataFrame, top_n: int = 10) -> List[Tuple[str, int, float]]:
    """
    获取用户排行榜
    返回: [(user_name, query_count, success_rate), ...]
    """
    user_stats = calculate_user_stats(df)
    
    # 按查询次数排序
    sorted_users = sorted(
        user_stats.items(),
        key=lambda x: x[1]['query_count'],
        reverse=True
    )[:top_n]
    
    return [
        (user, stats['query_count'], stats['success_rate'])
        for user, stats in sorted_users
    ]


def get_best_strategies(df: pd.DataFrame, top_n: int = 5) -> List[Tuple[str, float, int]]:
    """
    获取最佳策略排行
    返回: [(action, avg_roi, success_count), ...]
    """
    if df.empty:
        return []
    
    strategy_stats = defaultdict(lambda: {'roi_sum': 0, 'roi_count': 0, 'success_count': 0, 'total_count': 0})
    
    for action in df['Action'].unique():
        action_df = df[df['Action'] == action]
        roi_values = pd.to_numeric(action_df['Backtest_ROI'], errors='coerce')
        valid_roi = roi_values.dropna()
        
        strategy_stats[action]['roi_sum'] = valid_roi.sum()
        strategy_stats[action]['roi_count'] = len(valid_roi)
        strategy_stats[action]['success_count'] = (valid_roi > 0).sum()
        strategy_stats[action]['total_count'] = len(action_df)
    
    # 计算平均ROI和成功率
    strategy_results = []
    for action, stats in strategy_stats.items():
        avg_roi = stats['roi_sum'] / stats['roi_count'] if stats['roi_count'] > 0 else 0
        strategy_results.append((action, round(avg_roi, 2), stats['success_count']))
    
    # 按平均ROI排序
    sorted_strategies = sorted(strategy_results, key=lambda x: x[1], reverse=True)[:top_n]
    
    return sorted_strategies


def create_ranking_embed(title: str = "📊 BMO 每日熱搜排行") -> List[discord.Embed]:
    """
    创建Discord Embed消息
    返回: 一列embeds用于发送到Discord
    """
    df = load_query_history()
    
    if df.empty:
        empty_embed = discord.Embed(
            title="❌ 暫無數據",
            description="尚未有用戶查詢記錄",
            color=discord.Color.red()
        )
        return [empty_embed]
    
    embeds = []
    
    # 第一个embed: 热搜股票排行
    embed1 = discord.Embed(
        title=title,
        description="🔥 熱搜股票 TOP 10",
        color=discord.Color.gold()
    )
    
    hot_tickers = get_top_hot_searches(df, top_n=10)
    if hot_tickers:
        ticker_text = ""
        for i, (ticker, stock_name, count, success_rate) in enumerate(hot_tickers, 1):
            emoji = ["🥇", "🥈", "🥉"] + ["🔟"]*(10-3)
            ticker_text += f"{emoji[i-1]} **{stock_name}** ({ticker})\n"
            ticker_text += f"   查詢: {count} 次 | 成功率: {success_rate:.1f}%\n"
        
        embed1.add_field(name="熱搜排行", value=ticker_text, inline=False)
    else:
        embed1.add_field(name="熱搜排行", value="無數據", inline=False)
    
    embeds.append(embed1)
    
    # 第二个embed: 用户排行榜
    embed2 = discord.Embed(
        title="👥 活躍用戶 TOP 10",
        color=discord.Color.blue()
    )
    
    top_users = get_top_users(df, top_n=10)
    if top_users:
        user_text = ""
        for i, (user, query_count, success_rate) in enumerate(top_users, 1):
            emoji = ["🔥", "⭐", "💫"] + ["💥"]*(10-3)
            user_text += f"{emoji[i-1]} **{user}**\n"
            user_text += f"   查詢: {query_count} 次 | 推薦成功率: {success_rate:.1f}%\n"
        
        embed2.add_field(name="用戶排行", value=user_text, inline=False)
    else:
        embed2.add_field(name="用戶排行", value="無數據", inline=False)
    
    embeds.append(embed2)
    
    # 第三个embed: 最佳策略
    embed3 = discord.Embed(
        title="🎯 最佳策略排行",
        color=discord.Color.green()
    )
    
    best_strategies = get_best_strategies(df, top_n=5)
    if best_strategies:
        strategy_text = ""
        for i, (action, avg_roi, success_count) in enumerate(best_strategies, 1):
            strategy_text += f"{i}. **{action}**\n"
            strategy_text += f"   平均 ROI: {avg_roi:.2f}% | 成功案例: {success_count}\n"
        
        embed3.add_field(name="策略表現", value=strategy_text, inline=False)
    else:
        embed3.add_field(name="策略表現", value="無數據", inline=False)
    
    embeds.append(embed3)
    
    # 添加时间戳
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for embed in embeds:
        embed.set_footer(text=f"更新時間: {timestamp}")
    
    return embeds


def export_analytics_json() -> Dict:
    """
    导出分析数据为JSON格式（用于后续ML模型训练）
    """
    df = load_query_history()
    
    if df.empty:
        return {}
    
    return {
        'user_stats': calculate_user_stats(df),
        'ticker_stats': calculate_ticker_stats(df),
        'hot_searches': get_top_hot_searches(df, top_n=20),
        'top_users': get_top_users(df, top_n=20),
        'best_strategies': get_best_strategies(df, top_n=10)
    }


if __name__ == "__main__":
    # 测试脚本
    df = load_query_history()
    
    if not df.empty:
        print("=" * 60)
        print("📊 用户查询统计")
        print("=" * 60)
        
        user_stats = calculate_user_stats(df)
        print("\n👤 用户统计:")
        for user, stats in user_stats.items():
            print(f"  {user}:")
            print(f"    - 查询次数: {stats['query_count']}")
            print(f"    - 成功率: {stats['success_rate']}%")
            print(f"    - 平均置信度: {stats['avg_confidence']}")
            print(f"    - 最爱股票: {stats['favorite_ticker']}")
            print(f"    - 最佳策略: {stats['best_strategy']}")
        
        print("\n🔥 热搜股票 TOP 10:")
        hot_tickers = get_top_hot_searches(df, top_n=10)
        for i, (ticker, stock_name, count, success_rate) in enumerate(hot_tickers, 1):
            print(f"  {i}. {stock_name} ({ticker}) - {count}次查询, 成功率{success_rate:.1f}%")
        
        print("\n👥 用户排行 TOP 10:")
        top_users = get_top_users(df, top_n=10)
        for i, (user, count, success_rate) in enumerate(top_users, 1):
            print(f"  {i}. {user} - {count}次查询, 成功率{success_rate:.1f}%")
        
        print("\n🎯 最佳策略:")
        best_strats = get_best_strategies(df, top_n=5)
        for i, (action, avg_roi, success_count) in enumerate(best_strats, 1):
            print(f"  {i}. {action} - ROI:{avg_roi:.2f}%, 成功{success_count}次")
    else:
        print("❌ 无查询历史数据")
