import discord
from discord.ext import commands, tasks
import os
import asyncio
import sys
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

class ConfirmView(discord.ui.View):
    def __init__(self, ctx, ticker, stock_name):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.ticker = ticker
        self.stock_name = stock_name
        self.value = None

    @discord.ui.button(label="✅ 確認分析", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("這不是你的按鈕！", ephemeral=True)
            return
        await interaction.response.send_message(f"🚀 BMO 啟動！正在為 **{self.stock_name}** 進行深度運算...", ephemeral=False)
        self.value = True
        self.stop()

    @discord.ui.button(label="❌ 取消", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author: return
        await interaction.response.send_message("已取消。", ephemeral=True)
        self.value = False
        self.stop()

class QuantBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.target_channel_id = None

    async def on_ready(self):
        log_info(f"🤖 BMO V6.2 (UX) 上線: {self.user.name}")
        if not self.daily_scan_task.is_running():
            self.daily_scan_task.start()

    @tasks.loop(time=time(hour=6, minute=0, tzinfo=timezone.utc))
    async def daily_scan_task(self):
        if not self.target_channel_id: return
        channel = self.get_channel(self.target_channel_id)
        if not channel: return
        pass 

bot = QuantBot()

def resolve_ticker_info(ticker_input):
    raw = ticker_input.upper().strip()
    candidates = []
    if raw.isdigit(): candidates = [f"{raw}.TW", f"{raw}.TWO"]
    else: candidates = [raw]
    for c in candidates:
        name = get_stock_name_zh(c)
        if name != c: return c, name
    return candidates[0], candidates[0]

@bot.command(name="analyze", aliases=["a"])
async def analyze_stock(ctx, ticker: str = None):
    user_name = ctx.author.name
    log_info(f"使用者 {user_name} 查詢: {ticker}")

    if not ticker:
        await ctx.send("請輸入代號，例如 `!a 2313`")
        return
        
    try:
        clean_ticker, stock_name = resolve_ticker_info(ticker)
    except Exception as e:
        log_error(f"代號解析錯誤: {e}")
        await ctx.send(f"❌ 代號解析錯誤: {e}")
        return
    
    view = ConfirmView(ctx, clean_ticker, stock_name)
    msg = await ctx.send(f"🧐 您是想查詢 **{stock_name} ({clean_ticker})** 嗎？", view=view)
    await view.wait()
    await msg.edit(view=None)
    
    if view.value is True:
        try:
            data = await asyncio.to_thread(analyze_single_target, clean_ticker, True)
            if not data:
                await ctx.send(f"❌ 分析失敗：無法獲取 {clean_ticker} 的數據。")
                return

            dec = data['final_decision']
            roi = data['backtest_insight']['historical_roi'] if data['backtest_insight'] else "N/A"
            record_user_query(user_name, data['meta']['ticker'], data['meta']['name'], dec['action'], dec['final_confidence'], roi)

            prompt = generate_moltbot_prompt(data, is_single=True)
            ai_response = await asyncio.to_thread(generate_insight, prompt)
            
            final_name = data['meta']['name']
            header = f"📊 **BMO 深度診斷: {final_name}**"
            
            files = []
            if data.get('chart_path') and os.path.exists(data['chart_path']):
                files.append(discord.File(data['chart_path']))
            
            # [UX優化] 不再發送圖片路徑文字，直接發送圖片物件
            await ctx.send(f"{header}\n\n{ai_response}", files=files)
            
        except Exception as e:
            log_error(f"系統錯誤: {e}")
            await ctx.send(f"❌ 系統錯誤: {str(e)}")

@bot.command(name="bind")
async def bind_channel(ctx):
    bot.target_channel_id = ctx.channel.id
    await ctx.send("✅ 綁定成功")

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if token: bot.run(token)
