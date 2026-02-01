import discord
from discord.ext import commands, tasks
import os
import asyncio
import sys
import pandas as pd
import json
from pathlib import Path
from dotenv import load_dotenv
from datetime import time, timezone, datetime, timedelta
from typing import Tuple

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
load_dotenv(dotenv_path=Path(PROJECT_ROOT) / '.env', override=True)

from main import analyze_single_target, generate_moltbot_prompt, get_stock_name_zh, TARGET_STOCKS
from ai_runner import generate_insight
from utils.logger import log_info, log_error
from utils.history_recorder import record_user_query
from utils.quota_manager import check_quota_status, deduct_quota, admin_add_quota
from utils.user_analytics import create_ranking_embed
from utils.period_backtest import load_period_results, get_predefined_periods

# Load stock map
STOCK_MAP = {}
def load_stock_map():
    global STOCK_MAP
    try:
        print("📥 Loading stock list from FinMind...")
        from FinMind.data import DataLoader
        dl = DataLoader()
        df = dl.taiwan_stock_info()
        for index, row in df.iterrows():
            STOCK_MAP[row['stock_name']] = row['stock_id']
        print(f"✅ Stock map loaded: {len(STOCK_MAP)} entries.")
    except Exception as e:
        print(f"❌ Failed to load stock map: {e}")

class ConfirmView(discord.ui.View):
    def __init__(self, ctx, ticker, stock_name, user_id, is_admin):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.ticker = ticker
        self.stock_name = stock_name
        self.user_id = user_id
        self.is_admin = is_admin
        self.value = None

    @discord.ui.button(label="✅ 確認分析", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("這不是你的按鈕！", ephemeral=True)
            return
        
        if not self.is_admin:
            deduct_quota(self.user_id)
        
        await interaction.response.send_message(f"🚀 BMO 啟動！正在為 **{self.stock_name}** 進行深度運算...", ephemeral=False)
        self.value = True
        self.stop()

    @discord.ui.button(label="❌ 取消", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author: return
        await interaction.response.send_message("已取消 (本次不扣除額度)。", ephemeral=True)
        self.value = False
        self.stop()

class QuantBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.target_channel_id = None

    async def on_ready(self):
        log_info(f"🤖 BMO V10.1 (BETA Role + Format) 上線: {self.user.name}")
        await asyncio.to_thread(load_stock_map)
        if not self.daily_scan_task.is_running():
            self.daily_scan_task.start()

    @tasks.loop(time=time(hour=6, minute=0, tzinfo=timezone.utc))
    async def daily_scan_task(self):
        if not self.target_channel_id: return
        pass 

bot = QuantBot()

def resolve_ticker_info(ticker_input):
    raw = ticker_input.strip().upper()
    if raw.isdigit():
        candidates = [f"{raw}.TW", f"{raw}.TWO"]
        for c in candidates:
            name = get_stock_name_zh(c)
            if name != c: return c, name
        return candidates[0], candidates[0]
    if raw in STOCK_MAP: return f"{STOCK_MAP[raw]}.TW", raw
    for name, stock_id in STOCK_MAP.items():
        if raw in name: return f"{stock_id}.TW", name
    return raw, raw

@bot.command(name="analyze", aliases=["a"])
async def analyze_stock(ctx, ticker: str = None):
    if not ticker:
        await ctx.send("請輸入代號或股名，例如 `!a 2330`")
        return

    user_id = ctx.author.id
    
    # [修改] 身分組判斷邏輯
    is_admin = ctx.author.guild_permissions.administrator
    user_roles = [role.name for role in ctx.author.roles]
    
    tier = 'free'
    if any(r in ['Premium', 'VIP'] for r in user_roles):
        tier = 'premium'
    elif 'BETA' in user_roles: # 判斷 BETA 身分組
        tier = 'beta'
    
    allowed, remaining, limit = check_quota_status(user_id, tier)
    
    if is_admin:
        allowed = True
        remaining = "∞ (Admin)"
    elif not allowed:
        await ctx.send(f"⛔ **今日額度已用完**\n您的額度: {limit} 次/天。\n請升級會員或明日再試。")
        return

    try:
        clean_ticker, stock_name = resolve_ticker_info(ticker)
    except Exception as e:
        await ctx.send(f"❌ 代號解析錯誤: {e}")
        return
    
    view = ConfirmView(ctx, clean_ticker, stock_name, user_id, is_admin)
    msg = await ctx.send(f"🧐 您是想查詢 **{stock_name} ({clean_ticker})** 嗎？\n(今日剩餘: {remaining} 次)", view=view)
    await view.wait()
    await msg.edit(view=None)
    
    if view.value is True:
        try:
            data = await asyncio.to_thread(analyze_single_target, clean_ticker, True)
            if "error" in data:
                await ctx.send(f"❌ **分析中斷**: {data['error']}")
                return

            dec = data['final_decision']
            roi = data['backtest_insight']['historical_roi'] if data['backtest_insight'] else "N/A"
            record_user_query(ctx.author.name, data['meta']['ticker'], data['meta']['name'], dec['action'], dec['final_confidence'], roi)

            prompt = generate_moltbot_prompt(data, is_single=True)
            ai_response = await asyncio.to_thread(generate_insight, prompt)
            
            final_name = data['meta']['name']
            
            # [修改] 強制格式化現價為 2 位小數
            raw_price = data['price_data']['latest_close']
            current_price = f"{raw_price:.2f}"
            
            header = f"📊 **BMO 深度診斷: {final_name}** | **現價: {current_price}**"
            
            files = []
            if data.get('chart_path') and os.path.exists(data['chart_path']):
                files.append(discord.File(data['chart_path']))
            
            await ctx.send(f"{header}\n\n{ai_response}", files=files)
            
        except Exception as e:
            log_error(f"系統錯誤: {e}")
            await ctx.send(f"❌ 系統錯誤: {str(e)}")

@bot.command(name="gift")
@commands.has_permissions(administrator=True)
async def gift_quota(ctx, member: discord.Member, amount: int):
    new_limit = admin_add_quota(member.id, amount)
    await ctx.send(f"🎁 已為 **{member.display_name}** 增加 {amount} 次額度！\n現在總額度: **{new_limit} 次/天**")

@bot.command(name="hotlist", aliases=["hotrank", "rank"])
async def show_hotlist(ctx):
    """
    顯示每日熱搜排行榜
    """
    try:
        await ctx.defer()
        embeds = await asyncio.to_thread(create_ranking_embed)
        await ctx.send(embeds=embeds)
    except Exception as e:
        log_error(f"熱搜排行生成失敗: {e}")
        await ctx.send(f"❌ 生成排行榜失敗: {str(e)}")

@bot.command(name="period", aliases=["backtest_period", "bp"])
async def show_period_analysis(ctx, strategy: str = None):
    """
    顯示特定時間段的回測結果
    使用: !period [strategy_name]
    例: !period TrendStrategy
    """
    try:
        await ctx.defer()
        
        if not strategy:
            # 显示可用的分析结果
            results = await asyncio.to_thread(load_period_results)
            if not results:
                await ctx.send("❌ 沒有可用的時間段分析結果\n請先執行回測分析: !analyze <ticker>")
                return
            
            strategies_list = list(results.keys())
            embed = discord.Embed(
                title="📊 可用的策略分析",
                description=f"共 {len(strategies_list)} 個策略",
                color=discord.Color.blue()
            )
            
            text = ""
            for i, strat_name in enumerate(strategies_list[:10], 1):
                text += f"{i}. `{strat_name}`\n"
            
            embed.add_field(name="策略列表", value=text or "無", inline=False)
            embed.set_footer(text="使用 !period <strategy_name> 查看詳細分析")
            
            await ctx.send(embed=embed)
        else:
            # 显示特定策略的分析结果
            result = await asyncio.to_thread(load_period_results, strategy)
            
            if not result or 'error' in result:
                await ctx.send(f"❌ 找不到策略 `{strategy}` 的分析結果")
                return
            
            # 创建embed显示结果
            embed = discord.Embed(
                title=f"📈 {strategy} 時間段分析",
                description=f"分析時間: {result.get('analysis_time', 'N/A')}",
                color=discord.Color.green()
            )
            
            # 摘要信息
            summary = result.get('summary', {})
            summary_text = f"""
📊 **統計摘要**
平均ROI: **{summary.get('avg_roi', 'N/A')}%**
平均勝率: **{summary.get('avg_win_rate', 'N/A')}%**
ROI穩定性(標準差): **{summary.get('roi_std', 'N/A')}**
最佳時期: **{summary.get('best_period', 'N/A')}**
最差時期: **{summary.get('worst_period', 'N/A')}**
"""
            embed.add_field(name="摘要", value=summary_text.strip(), inline=False)
            
            # 時期詳情
            periods = result.get('periods', [])
            if periods:
                periods_text = ""
                for p in periods[:5]:  # 只显示前5个
                    if 'error' in p:
                        periods_text += f"❌ {p.get('period', 'Unknown')}: {p.get('error', 'Error')}\n"
                    else:
                        periods_text += f"• **{p.get('period')}**: ROI {p.get('roi')}% | 勝率 {p.get('win_rate')}% | 交易數 {p.get('total_trades')}\n"
                
                embed.add_field(name="時期表現", value=periods_text or "無", inline=False)
            
            await ctx.send(embed=embed)
    
    except Exception as e:
        log_error(f"時間段分析顯示失敗: {e}")
        await ctx.send(f"❌ 顯示分析結果失敗: {str(e)}")

def _parse_period_to_dates(period: str) -> Tuple[str, str]:
    """解析时间段字符串为开始日期和结束日期"""
    from datetime import datetime, timedelta
    
    today = datetime.now()
    
    # 支持的时间段格式
    if period == "today":
        start = today.strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
    elif period == "week":
        start = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
    elif period == "month":
        start = (today - timedelta(days=30)).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
    elif period == "year":
        start = (today - timedelta(days=365)).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
    elif period == "ytd":  # Year-to-date
        start = f"{today.year}-01-01"
        end = today.strftime("%Y-%m-%d")
    elif period == "full":
        start = "2020-01-01"
        end = today.strftime("%Y-%m-%d")
    elif "-" in period:  # 自定义日期范围: YYYY-MM-DD:YYYY-MM-DD
        parts = period.split(":")
        if len(parts) == 2:
            start, end = parts[0], parts[1]
        else:
            raise ValueError(f"无效的日期格式: {period}")
    else:
        raise ValueError(f"未知的时间段: {period}")
    
    return start, end


def _status_color(status: str):
    """根据状态返回对应的颜色"""
    colors = {
        "queued": discord.Color.greyple(),
        "running": discord.Color.blue(),
        "completed": discord.Color.green(),
        "failed": discord.Color.red()
    }
    return colors.get(status, discord.Color.greyple())


def _diagnose_training_result(results: dict) -> tuple:
    """
    診斷訓練結果的品質，判斷是否異常
    
    返回: (status, issues_list, recommendations_list)
    - status: "✅ 正常" | "⚠️ 需要改進" | "❌ 嚴重異常"
    - issues_list: 發現的問題列表
    - recommendations_list: 建議清單
    """
    issues = []
    recommendations = []
    status = "✅ 正常"
    
    roi = results.get('best_roi', 0)
    win_rate = results.get('best_win_rate', 0)
    sharpe = results.get('best_sharpe', 0)
    total_trades = results.get('total_trades', 0)
    total_combinations = results.get('total_combinations_tested', 1)
    successful_combinations = results.get('successful_combinations', 0)
    success_rate = (successful_combinations / total_combinations * 100) if total_combinations > 0 else 0
    
    # 檢查ROI
    if roi == -999.0:
        issues.append("❌ ROI為-999% (所有參數組合失敗)")
        status = "❌ 嚴重異常"
        if total_trades == 0:
            recommendations.append("✓ 原因: 數據不足或時間段過短 (無交易信號)")
            recommendations.append("✓ 解決方案: 選擇更長的時間段 (至少6個月)")
        else:
            recommendations.append("✓ 檢查策略邏輯是否有參數衝突")
    elif roi < -50:
        issues.append(f"⚠️ ROI過低 ({roi:.2f}%)")
        status = "❌ 嚴重異常"
        recommendations.append("✓ 考慮調整策略參數或時間段")
    elif roi < 0:
        issues.append(f"⚠️ ROI為負 ({roi:.2f}%)")
        if status != "❌ 嚴重異常":
            status = "⚠️ 需要改進"
        recommendations.append("✓ 檢查市場環境是否適合該策略")
    
    # 檢查勝率
    if win_rate == 0.0 and total_trades == 0:
        issues.append("❌ 沒有交易信號 (勝率 0%)")
        if roi != -999.0:
            status = "❌ 嚴重異常"
    elif win_rate == 0.0 and total_trades > 0:
        issues.append("❌ 無交易勝利 (勝率 0%)")
        if status != "❌ 嚴重異常":
            status = "⚠️ 需要改進"
    elif win_rate < 30:
        issues.append(f"⚠️ 勝率過低 ({win_rate:.1f}%)")
        if status != "❌ 嚴重異常":
            status = "⚠️ 需要改進"
        recommendations.append("✓ 調整進場/出場條件以改善勝率")
    
    # 檢查Sharpe比率
    if sharpe == 0.0:
        issues.append("❌ Sharpe比率為0 (無風險調整收益)")
        if status != "❌ 嚴重異常" and status != "⚠️ 需要改進":
            status = "⚠️ 需要改進"
    elif sharpe < 0.5:
        issues.append(f"⚠️ Sharpe比率低 ({sharpe:.2f})")
        if status != "❌ 嚴重異常":
            status = "⚠️ 需要改進"
        recommendations.append("✓ 提高風險調整後收益，增加穩定性")
    
    # 檢查成功率
    if total_combinations > 0 and success_rate < 50:
        issues.append(f"⚠️ 參數組合成功率低 ({success_rate:.1f}%)")
        if status != "❌ 嚴重異常":
            status = "⚠️ 需要改進"
        recommendations.append(f"✓ 檢查參數範圍是否過於激進 ({successful_combinations}/{total_combinations} 組合成功)")
    
    # 檢查交易次數
    if total_trades < 5:
        issues.append(f"⚠️ 交易次數太少 ({total_trades}筆)")
        recommendations.append("✓ 增加時間段或調整策略敏感度以產生更多交易")
    
    # 無問題的正常情況
    if not issues:
        recommendations = [
            "✓ 結果屬於正常範圍",
            "✓ 繼續使用此參數組合或微調優化",
            "✓ 定期回測以監控效能"
        ]
    
    return (status, issues, recommendations)


@bot.command(name="strategies", aliases=["strats", "models"])
async def show_strategies(ctx, mode: str = None):
    """
    顯示所有可用策略
    
    用法:
        !strategies              # 簡潔模式 (按勝率排序)
        !strategies detail       # 詳細模式
        !strategies category:ml  # 按分類篩選 (ml/indicator/price_action)
        !strategies sort:sharpe  # 按Sharpe比率排序
    """
    try:
        from strategies.strategy_registry import get_strategy_registry
        
        registry = get_strategy_registry()
        
        # 解析參數
        if mode and mode.startswith("category:"):
            category = mode.split(":")[1]
            strategies = registry.get_by_category(category)
            title = f"🎯 {category.upper()} 類策略 ({len(strategies)}個)"
            detailed = False
        elif mode and mode.startswith("sort:"):
            metric = mode.split(":")[1]
            strategies = registry.get_all_sorted(metric)
            title = f"📊 按 {metric} 排序的策略"
            detailed = False
        elif mode == "detail":
            strategies = registry.get_all_sorted()
            title = "📋 所有策略 (詳細模式)"
            detailed = True
        else:
            strategies = registry.get_all_sorted()
            title = "📊 所有可用策略"
            detailed = False
        
        if not strategies:
            await ctx.send("未找到匹配的策略。")
            return
        
        # 詳細模式：每個策略獨占一個embed
        if detailed:
            for strat in strategies[:6]:  # Discord限制最多10個embed
                difficulty_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(strat.difficulty, "⚪")
                category_emoji = {"indicator": "📈", "ml": "🤖", "price_action": "💹", "comprehensive": "🔷"}.get(strat.category, "❓")
                
                embed = discord.Embed(
                    title=f"{category_emoji} {strat.name}",
                    description=strat.description,
                    color=discord.Color.blue()
                )
                embed.add_field(name="分類", value=strat.category, inline=True)
                embed.add_field(name="難度", value=f"{difficulty_emoji} {strat.difficulty}", inline=True)
                embed.add_field(name="準確率", value=f"{strat.accuracy*100:.1f}%", inline=True)
                embed.add_field(name="勝率", value=f"{strat.win_rate*100:.1f}%", inline=True)
                embed.add_field(name="Sharpe比率", value=f"{strat.sharpe_ratio:.2f}", inline=True)
                embed.add_field(name="平均ROI", value=f"{strat.avg_roi:.1f}%", inline=True)
                embed.add_field(name="歷史交易", value=f"{strat.total_trades}筆", inline=False)
                embed.set_footer(text=f"更新於: {strat.last_updated[:10]}")
                await ctx.send(embed=embed)
        else:
            # 簡潔模式：表格形式
            embed = discord.Embed(title=title, color=discord.Color.green())
            
            strategy_table = "策略名稱 | 分類 | 勝率 | Sharpe | ROI\n"
            strategy_table += "───────────────|──────|──────|────────|──────\n"
            
            for strat in strategies[:15]:  # 最多顯示15個
                category_short = {"indicator": "指標", "ml": "ML", "price_action": "價格", "comprehensive": "綜合"}.get(strat.category, "其他")
                strategy_table += f"{strat.name:13} | {category_short:4} | {strat.win_rate*100:5.1f}% | {strat.sharpe_ratio:6.2f} | {strat.avg_roi:5.1f}%\n"
            
            embed.description = f"```\n{strategy_table}\n```"
            embed.set_footer(text="💡 使用 !strategies detail 查看詳細資訊 | !strategies sort:sharpe 按其他指標排序")
            await ctx.send(embed=embed)
    
    except Exception as e:
        log_error(f"!strategies 命令失敗: {e}")
        await ctx.send(f"❌ 發生錯誤: {str(e)}")


@bot.command(name="train", aliases=["training", "optimize"])
async def train_strategy(ctx, *args):
    """
    眾包訓練命令: 提交策略參數優化任務
    
    用法:
        !train MA交叉 2330.TW month --roi 20
        !train RSI反轉 2888.TW year
        !train --help
    
    支持的策略: MA交叉, RSI反轉, MACD動能, KD隨機指標, 布林帶策略, 價值估值, 回撤交易
    支持的時間段: today, week, month, year, ytd, full, 或自訂義 YYYY-MM-DD:YYYY-MM-DD
    """
    try:
        from utils.training_queue import get_training_queue
        from strategies.strategy_registry import get_strategy_registry
        
        # 手動解析參數
        if len(args) < 3:
            embed = discord.Embed(
                title="❌ 參數缺失",
                description="**用法**: `!train <策略> <股票代碼> <時間段> [--roi 目標ROI]`\n\n"
                           "**示例**: `!train MA交叉 2330.TW month --roi 20`\n\n"
                           "**支持的時間段**: today, week, month, year, ytd, full",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
        
        strategy = args[0]
        ticker = args[1]
        period = args[2]
        target_roi = 15.0  # 預設值
        
        # 解析 --roi 參數
        if len(args) >= 5 and args[3] == "--roi":
            try:
                target_roi = float(args[4])
            except ValueError:
                await ctx.send(f"❌ 目標ROI必須是數字，收到: {args[4]}")
                return
        
        # 檢查策略是否存在
        registry = get_strategy_registry()
        if strategy not in registry.strategies:
            available = ", ".join(list(registry.strategies.keys())[:5])
            embed = discord.Embed(
                title="❌ 未知策略",
                description=f"策略 `{strategy}` 不存在\n\n**可用策略**: {available}...",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
        
        # 解析時間段
        try:
            start_date, end_date = _parse_period_to_dates(period)
        except ValueError as e:
            embed = discord.Embed(
                title="❌ 無效的時間段",
                description=str(e),
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
        
        # 提交訓練任務
        queue = get_training_queue()
        task_id = queue.submit_training(
            user_id=ctx.author.id,
            strategy=strategy,
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            target_roi=target_roi
        )
        
        embed = discord.Embed(
            title="📊 訓練任務已提交",
            color=discord.Color.blue()
        )
        embed.add_field(name="任務ID", value=f"`{task_id}`", inline=False)
        embed.add_field(name="策略", value=strategy, inline=True)
        embed.add_field(name="股票", value=ticker, inline=True)
        embed.add_field(name="時間段", value=f"{start_date} ~ {end_date}", inline=True)
        embed.add_field(name="目標ROI", value=f"{target_roi}%", inline=True)
        embed.add_field(
            name="預計等待時間",
            value="2-10分鐘 (根據參數數量和伺服器負載)",
            inline=False
        )
        embed.set_footer(text="💡 使用 !train-status <task_id> 查看進度")
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        log_error(f"!train 命令失敗: {e}")
        await ctx.send(f"❌ 錯誤: {str(e)}")


@bot.command(name="train-status", aliases=["train_status"])
async def check_training_status(ctx, task_id: str = None):
    """查看訓練任務狀態和結果"""
    from utils.training_queue import get_training_queue
    
    try:
        if not task_id:
            embed = discord.Embed(
                title="❌ 參數缺失",
                description="用法: `!train-status <task_id>`\n\n使用 `!train-history` 查看你的任務列表",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
        
        queue = get_training_queue()
        task = queue.get_task(task_id)
        
        if not task:
            await ctx.send(f"❌ 找不到任務: `{task_id}`")
            return
        
        if task.user_id != ctx.author.id:
            await ctx.send("❌ 你沒有權限查看此任務 (只有提交者可查看)")
            return
        
        status_emoji = {
            "queued": "⏳",
            "running": "▶️",
            "completed": "✅",
            "failed": "❌"
        }.get(task.status, "❓")
        
        embed = discord.Embed(
            title=f"{status_emoji} 訓練任務 {task_id[:20]}...",
            color=_status_color(task.status)
        )
        
        embed.add_field(name="狀態", value=task.status.upper(), inline=True)
        embed.add_field(name="進度", value=f"{task.progress}%", inline=True)
        embed.add_field(name="策略", value=task.config["strategy"], inline=True)
        embed.add_field(name="股票", value=task.config["stock_ticker"], inline=True)
        embed.add_field(
            name="時間段",
            value=f"{task.config['start_date']} ~ {task.config['end_date']}",
            inline=True
        )
        
        if task.status == "completed" and task.results:
            results = task.results
            embed.add_field(
                name="🏆 最優參數",
                value=f"```json\n{json.dumps(results['best_params'], ensure_ascii=False, indent=2)[:500]}\n```",
                inline=False
            )
            embed.add_field(
                name="📊 性能指標",
                value=(
                    f"**ROI**: {results['best_roi']:.2f}%\n"
                    f"**勝率**: {results['best_win_rate']:.1f}%\n"
                    f"**Sharpe**: {results['best_sharpe']:.2f}\n"
                    f"**最大回撤**: {results['best_max_dd']:.2f}%"
                ),
                inline=False
            )
            embed.add_field(
                name="🔍 搜尋統計",
                value=(
                    f"**測試組合**: {results['total_combinations_tested']}\n"
                    f"**成功組合**: {results['successful_combinations']}\n"
                    f"**成功率**: {results['successful_combinations']*100/results['total_combinations_tested']:.1f}%"
                ),
                inline=False
            )
            
            # 添加診斷結果
            status_diagnosis, issues, recommendations = _diagnose_training_result(results)
            diagnosis_text = f"**狀態**: {status_diagnosis}\n\n"
            if issues:
                diagnosis_text += "**發現的問題**:\n" + "\n".join(issues) + "\n\n"
            if recommendations:
                diagnosis_text += "**建議**:\n" + "\n".join(recommendations)
            embed.add_field(name="🔬 結果診斷", value=diagnosis_text, inline=False)
            
            # 添加Top 3結果
            if results['top_results']:
                top_text = ""
                for i, r in enumerate(results['top_results'][:3], 1):
                    top_text += f"{i}. ROI {r['roi']:.2f}% | 勝率 {r['win_rate']:.1f}% | 評分 {r['score']:.2f}\n"
                embed.add_field(name="🥇 Top 3 結果", value=top_text, inline=False)
        
        elif task.status == "failed":
            embed.add_field(name="❌ 錯誤", value=task.error or "未知錯誤", inline=False)
        
        elif task.status == "running":
            embed.add_field(name="⏳ 狀態", value=f"正在優化中，進度: {task.progress}%", inline=False)
        
        elif task.status == "queued":
            embed.add_field(name="⏳ 狀態", value="等待中，請稍候...", inline=False)
        
        embed.set_footer(text=f"建立於: {task.created_at[:10]}")
        await ctx.send(embed=embed)
        
    except Exception as e:
        log_error(f"!train-status 命令失敗: {e}")
        await ctx.send(f"❌ 錯誤: {str(e)}")


@bot.command(name="train-history")
async def training_history(ctx):
    """顯示你的訓練歷史"""
    from utils.training_queue import get_training_queue
    
    try:
        queue = get_training_queue()
        tasks = queue.get_user_tasks(ctx.author.id, limit=10)
        
        if not tasks:
            await ctx.send("你還沒有提交過訓練任務。\n\n使用 `!train <策略> <股票> <時間段>` 提交任務。")
            return
        
        embed = discord.Embed(
            title="📚 你的訓練歷史 (最近10個任務)",
            color=discord.Color.blue()
        )
        
        for task in tasks:
            status_emoji = {
                "queued": "⏳",
                "running": "▶️",
                "completed": "✅",
                "failed": "❌"
            }.get(task.status, "❓")
            
            if task.status == "completed" and task.results:
                roi = task.results.get("best_roi", 0)
                win_rate = task.results.get("best_win_rate", 0)
                task_info = (
                    f"{status_emoji} **{task.status.upper()}** ✨\n"
                    f"策略: {task.config['strategy']}\n"
                    f"股票: {task.config['stock_ticker']}\n"
                    f"結果: ROI {roi:.2f}% | 勝率 {win_rate:.1f}%\n"
                    f"ID: `{task.task_id}`"
                )
            else:
                task_info = (
                    f"{status_emoji} {task.status.upper()}\n"
                    f"策略: {task.config['strategy']}\n"
                    f"股票: {task.config['stock_ticker']}\n"
                    f"ID: `{task.task_id}`"
                )
            
            embed.add_field(name=task.created_at[:10], value=task_info, inline=False)
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        log_error(f"!train-history 命令失敗: {e}")
        await ctx.send(f"❌ 錯誤: {str(e)}")

@bot.command(name="bind")
async def bind_channel(ctx):
    bot.target_channel_id = ctx.channel.id
    await ctx.send("✅ 綁定成功")

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if token: bot.run(token)
