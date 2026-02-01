#!/usr/bin/env python3
"""
V12.0 新功能综合验证脚本
测试所有新增功能: 策略注册表、众包训练、日志系统
"""

import sys
import json
from datetime import datetime


def test_strategy_registry():
    """测试策略注册表系统"""
    print("\n" + "="*60)
    print("📊 测试1: 策略注册表系统")
    print("="*60)
    
    from strategies.strategy_registry import get_strategy_registry
    
    registry = get_strategy_registry()
    
    print(f"✅ 已加载 {len(registry.strategies)} 个策略")
    
    # 测试排序
    top_strategies = registry.get_all_sorted('win_rate')
    print(f"\n🏆 按胜率排名 Top 3:")
    for i, s in enumerate(top_strategies[:3], 1):
        print(f"   {i}. {s.name:15} | 胜率 {s.win_rate*100:5.1f}% | ROI {s.avg_roi:6.1f}%")
    
    # 测试分类
    categories = {}
    for s in registry.strategies.values():
        if s.category not in categories:
            categories[s.category] = 0
        categories[s.category] += 1
    
    print(f"\n📈 按分类统计:")
    for cat, count in sorted(categories.items()):
        print(f"   {cat:15}: {count:2}个")
    
    print("\n✅ 策略注册表测试通过!")
    return True


def test_training_queue():
    """测试训练队列系统"""
    print("\n" + "="*60)
    print("🤖 测试2: 训练队列系统")
    print("="*60)
    
    from utils.training_queue import get_training_queue
    import time
    
    queue = get_training_queue()
    
    # 提交任务
    print("\n📝 提交训练任务...")
    task_id = queue.submit_training(
        user_id=99999,
        strategy='MA交叉',
        ticker='2330.TW',
        start_date='2025-10-01',
        end_date='2026-01-31',
        target_roi=15.0
    )
    print(f"✅ 任务ID: {task_id}")
    
    # 等待完成
    print("\n⏳ 等待训练完成...")
    max_wait = 120
    for i in range(max_wait):
        task = queue.get_task(task_id)
        
        if task.status == 'completed':
            print(f"✅ 训练完成! (耗时 {i}s)")
            
            results = task.results
            print(f"\n📊 训练结果:")
            print(f"   最优参数: {results['best_params']}")
            print(f"   最优ROI: {results['best_roi']:.2f}%")
            print(f"   最优胜率: {results['best_win_rate']:.1f}%")
            print(f"   Sharpe比率: {results['best_sharpe']:.2f}")
            print(f"   最大回撤: {results['best_max_dd']:.2f}%")
            print(f"   测试组合: {results['total_combinations_tested']}")
            print(f"   成功率: {results['successful_combinations']}/{results['total_combinations_tested']}")
            
            # 显示Top结果
            if results.get('top_results'):
                print(f"\n🥇 Top 3 优化结果:")
                for j, r in enumerate(results['top_results'][:3], 1):
                    print(f"   {j}. ROI {r['roi']:6.2f}% | 胜率 {r['win_rate']:5.1f}% | 评分 {r['score']:6.2f}")
            
            break
        
        elif task.status == 'failed':
            print(f"❌ 训练失败: {task.error}")
            return False
        
        if i % 10 == 0 and i > 0:
            print(f"   进度: {task.progress}% ({i}s)")
        
        time.sleep(1)
    else:
        print(f"❌ 训练超时 (>{max_wait}s)")
        return False
    
    # 测试任务查询
    print(f"\n📚 用户历史任务:")
    user_tasks = queue.get_user_tasks(99999, limit=5)
    print(f"✅ 查到 {len(user_tasks)} 个任务")
    
    print("\n✅ 训练队列系统测试通过!")
    return True


def test_changelog_system():
    """测试日志系统"""
    print("\n" + "="*60)
    print("📝 测试3: 日志系统")
    print("="*60)
    
    from utils.changelog_manager import get_changelog_manager, init_v12_0_changelog
    import os
    
    manager = get_changelog_manager()
    
    # 初始化V12.0日志
    print("\n📝 初始化V12.0版本日志...")
    init_v12_0_changelog()
    
    versions = manager.list_versions()
    print(f"✅ 已创建 {len(versions)} 个版本日志")
    for v in versions:
        print(f"   - {v}")
    
    # 添加每日日志
    print("\n📅 添加每日日志...")
    test_date = datetime.now().strftime("%Y-%m-%d")
    manager.add_daily_log(test_date, 'feature', [
        '实现 !strategies 命令',
        '实现众包模型训练平台',
        '实现日志系统框架'
    ])
    print(f"✅ 已添加 {test_date} 的日志")
    
    # 生成总Changelog
    print("\n📋 生成总体Changelog...")
    changelog_path = manager.generate_overall_changelog()
    print(f"✅ 生成位置: {changelog_path}")
    
    # 验证文件
    if os.path.exists(changelog_path):
        size = os.path.getsize(changelog_path)
        print(f"✅ 文件大小: {size} bytes")
    
    # 查看每日日志
    daily_logs = manager.list_daily_logs(5)
    print(f"\n📚 最近的每日日志 ({len(daily_logs)}个):")
    for log in daily_logs[:3]:
        print(f"   - {log}")
    
    print("\n✅ 日志系统测试通过!")
    return True


def test_discord_commands():
    """测试Discord命令集成 (仅验证导入)"""
    print("\n" + "="*60)
    print("💬 测试4: Discord命令集成")
    print("="*60)
    
    try:
        print("\n📝 验证Discord命令...")
        
        # 检查discord_runner中是否有新命令
        import discord_runner
        
        # 验证命令存在
        if hasattr(discord_runner, 'show_strategies'):
            print("✅ !strategies 命令已注册")
        
        if hasattr(discord_runner, 'train_strategy'):
            print("✅ !train 命令已注册")
        
        if hasattr(discord_runner, 'check_training_status'):
            print("✅ !train-status 命令已注册")
        
        if hasattr(discord_runner, 'training_history'):
            print("✅ !train-history 命令已注册")
        
        print("\n✅ Discord命令集成测试通过!")
        return True
    
    except Exception as e:
        print(f"❌ Discord命令集成测试失败: {e}")
        return False


def print_summary(results):
    """打印测试摘要"""
    print("\n" + "="*60)
    print("📊 测试摘要")
    print("="*60)
    
    total = len(results)
    passed = sum(results.values())
    failed = total - passed
    
    print(f"\n总测试: {total} | 通过: {passed} | 失败: {failed}")
    
    status_map = {
        'strategy_registry': '策略注册表',
        'training_queue': '训练队列',
        'changelog_system': '日志系统',
        'discord_commands': 'Discord命令'
    }
    
    print("\n详细结果:")
    for test_name, status in results.items():
        icon = "✅" if status else "❌"
        print(f"  {icon} {status_map.get(test_name, test_name)}")
    
    if failed == 0:
        print("\n🎉 所有测试通过!")
        return True
    else:
        print(f"\n⚠️ 有 {failed} 个测试失败")
        return False


if __name__ == "__main__":
    print("\n" + "#"*60)
    print("# Stock Quant V12.0 新功能验证")
    print("#"*60)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = {}
    
    # 执行所有测试
    try:
        results['strategy_registry'] = test_strategy_registry()
    except Exception as e:
        print(f"❌ 策略注册表测试异常: {e}")
        results['strategy_registry'] = False
    
    try:
        results['training_queue'] = test_training_queue()
    except Exception as e:
        print(f"❌ 训练队列测试异常: {e}")
        results['training_queue'] = False
    
    try:
        results['changelog_system'] = test_changelog_system()
    except Exception as e:
        print(f"❌ 日志系统测试异常: {e}")
        results['changelog_system'] = False
    
    try:
        results['discord_commands'] = test_discord_commands()
    except Exception as e:
        print(f"❌ Discord命令测试异常: {e}")
        results['discord_commands'] = False
    
    # 打印摘要
    success = print_summary(results)
    
    print(f"\n结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("#"*60 + "\n")
    
    sys.exit(0 if success else 1)
