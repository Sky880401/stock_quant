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
        await interaction.response.send_message(f"🚀 BMO 啟動！正在為 **{self.stock_name}** 進行深度運算 (含回測優化)...", ephemeral=False)
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
        print(f"🤖 BMO Interactive (v6.0 Fixed) 上線: {self.user.name}")
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="!a <代號>"))
        if not self.daily_scan_task.is_running():
            self.daily_scan_task.start()

    @tasks.loop(time=time(hour=6, minute=0, tzinfo=timezone.utc))
    async def daily_scan_task(self):
        if not self.target_channel_id: return
        channel = self.get_channel(self.target_channel_id)
        if not channel: return
        # 自動掃描邏輯...
        pass 

bot = QuantBot()

def resolve_ticker_info(ticker_input):
    """
    只查名稱，不跑分析
    優先猜 .TW (上市)，因為數量最多
    """
    raw = ticker_input.upper().strip()
    candidates = []
    if raw.isdigit(): 
        # [修正] 優先 .TW，其次 .TWO
        candidates = [f"{raw}.TW", f"{raw}.TWO"]
    else: candidates = [raw]
    
    for c in candidates:
        name = get_stock_name_zh(c)
        if name != c:
            return c, name
    
    return candidates[0], candidates[0]

@bot.command(name="analyze", aliases=["a"])
async def analyze_stock(ctx, ticker: str = None):
    if not ticker:
        await ctx.send("請輸入代號，例如 `!a 2313`")
        return
        
    try:
        clean_ticker, stock_name = resolve_ticker_info(ticker)
    except Exception as e:
        await ctx.send(f"❌ 代號解析錯誤: {e}")
        return
    
    view = ConfirmView(ctx, clean_ticker, stock_name)
    msg = await ctx.send(f"🧐 您是想查詢 **{stock_name} ({clean_ticker})** 嗎？", view=view)
    await view.wait()
    await msg.edit(view=None)
    
    if view.value is True:
        try:
            # 傳遞給 main.py，內部會自動處理 .TW/.TWO 容錯
            data = await asyncio.to_thread(analyze_single_target, clean_ticker, True)
            
            if not data:
                await ctx.send(f"❌ 分析失敗：無法獲取 {clean_ticker} 的數據。")
                return

            prompt = generate_moltbot_prompt(data, is_single=True)
            ai_response = await asyncio.to_thread(generate_insight, prompt)
            
            # 使用正確的名稱 (可能在 analyze_single_target 中被修正了)
            final_name = data['meta']['name']
            header = f"📊 **BMO 深度診斷: {final_name}**"
            
            files = []
            if data.get('chart_path') and os.path.exists(data['chart_path']):
                files.append(discord.File(data['chart_path']))
                
            await ctx.send(f"{header}\n\n{ai_response}", files=files)
            
        except Exception as e:
            await ctx.send(f"❌ 系統錯誤: {str(e)}")

@bot.command(name="bind")
async def bind_channel(ctx):
    bot.target_channel_id = ctx.channel.id
    await ctx.send("✅ 綁定成功")

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if token: bot.run(token)
