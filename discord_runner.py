import discord
from discord.ext import commands, tasks
import os
import asyncio
import sys
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
from datetime import time, timezone

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

@bot.command(name="bind")
async def bind_channel(ctx):
    bot.target_channel_id = ctx.channel.id
    await ctx.send("✅ 綁定成功")

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if token: bot.run(token)
