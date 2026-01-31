import discord
from discord.ext import commands
import os
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
load_dotenv(dotenv_path=Path(PROJECT_ROOT) / '.env', override=True)

from main import analyze_single_target, generate_moltbot_prompt
from ai_runner import generate_insight

class QuantBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def on_ready(self):
        print(f"🤖 BMO (QuantMaster) 上線: {self.user.name}")
        # 設定機器人狀態
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="台股盤勢 | !analyze"))

bot = QuantBot()

async def resolve_ticker(ctx, raw_input):
    candidates = []
    raw_input = raw_input.upper().strip()
    if raw_input.isdigit():
        candidates = [f"{raw_input}.TW", f"{raw_input}.TWO"]
    else:
        candidates = [raw_input]

    status_msg = await ctx.send(f"🔍 BMO 正在搜尋代號: **{raw_input}** ...")
    
    for ticker in candidates:
        data = await asyncio.to_thread(analyze_single_target, ticker)
        if data:
            # [UX優化] 抓取中文名稱
            stock_name = data['meta'].get('name', ticker)
            clean_ticker = data['meta']['ticker']
            
            # [UX優化] 回應文案修改
            await status_msg.edit(content=f"✅ 找到 **{stock_name}** ({clean_ticker})，BMO 正在思考中... 🧠")
            return data
            
    await status_msg.edit(content=f"❌ BMO 找不到代號 `{raw_input}` 的數據。")
    return None

@bot.command(name="analyze", aliases=["a", "查"])
async def analyze_stock(ctx, ticker: str = None):
    if not ticker:
        await ctx.send("請輸入代號，例如: `!a 2330`")
        return

    quant_data = await resolve_ticker(ctx, ticker)
    if not quant_data:
        return

    try:
        prompt = generate_moltbot_prompt(quant_data, is_single=True)
        ai_response = await asyncio.to_thread(generate_insight, prompt)
        
        # [UX優化] 標題與格式
        stock_name = quant_data['meta'].get('name', ticker)
        header = f"📊 **BMO 投資診斷室: {stock_name}**"
        
        if len(ai_response) > 1900:
            tmp_path = "reports/temp_insight.md"
            os.makedirs("reports", exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(ai_response)
            await ctx.send(f"{header}\n(完整報告請見附件)", file=discord.File(tmp_path))
        else:
            await ctx.send(f"{header}\n\n{ai_response}")

    except Exception as e:
        await ctx.send(f"❌ BMO 發生錯誤: {str(e)}")

@bot.command(name="report")
async def send_daily_report(ctx):
    # (保持原樣，僅修改標題顯示)
    try:
        json_path = os.path.join(PROJECT_ROOT, 'data/latest_report.json')
        if os.path.exists(json_path):
            import json
            data = json.load(open(json_path))
            ts = data.get('timestamp', '')[:10].replace('-', '')
            report_path = os.path.join(PROJECT_ROOT, "reports", f"daily_summary_{ts}_nvidia.md")
            
            if os.path.exists(report_path):
                with open(report_path, "r", encoding="utf-8") as f:
                    content = f.read()
                header = f"🗓️ **BMO 每日市場掃描 ({ts})**"
                if len(content) > 1900:
                    await ctx.send(f"{header}", file=discord.File(report_path))
                else:
                    await ctx.send(f"{header}\n\n{content}")
            else:
                await ctx.send("❌ 尚未生成今日日報。")
        else:
            await ctx.send("❌ 無數據。")
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if token:
        bot.run(token)
    else:
        print("❌ DISCORD_TOKEN missing")
