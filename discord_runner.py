import discord
from discord.ext import commands
import os
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

# === 環境設置 ===
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
load_dotenv(dotenv_path=Path(PROJECT_ROOT) / '.env', override=True)

# 引入我們剛剛改好的模組
from main import analyze_single_target, generate_moltbot_prompt
from ai_runner import generate_insight

# === Bot 初始化 ===
class QuantBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def on_ready(self):
        print(f"🤖 QuantMaster Bot (v2.5 Real-time) 上線: {self.user.name}")

bot = QuantBot()

# === Helper: 智慧代號解析 ===
async def resolve_ticker(ctx, raw_input):
    """
    嘗試順序：
    1. 原始輸入 (美股或完整代號)
    2. + .TW (上市)
    3. + .TWO (上櫃)
    """
    candidates = []
    raw_input = raw_input.upper().strip()

    # 如果是純數字 (台股)
    if raw_input.isdigit():
        candidates = [f"{raw_input}.TW", f"{raw_input}.TWO"]
    else:
        # 可能是美股 (NVDA) 或已帶後綴 (2330.TW)
        candidates = [raw_input]

    status_msg = await ctx.send(f"🔍 正在搜尋代號與數據: {raw_input} ...")
    
    for ticker in candidates:
        # 呼叫 main.py 的分析功能
        # 這裡用 to_thread 避免卡死 Discord 機器人的心跳
        data = await asyncio.to_thread(analyze_single_target, ticker)
        
        if data:
            await status_msg.edit(content=f"✅ 找到數據 ({ticker})，405B 正在思考中...")
            return data
            
    await status_msg.edit(content=f"❌ 找不到代號 `{raw_input}` 的數據 (已嘗試: {candidates})")
    return None

# === 指令: 即時分析 ===
@bot.command(name="analyze", aliases=["a", "查"])
async def analyze_stock(ctx, ticker: str = None):
    """
    指令: !analyze <代號>
    範例: !analyze 2330 (自動測 .TW/.TWO)
    範例: !analyze NVDA (美股)
    """
    if not ticker:
        await ctx.send("請輸入代號，例如: `!analyze 2330` 或 `!analyze NVDA`")
        return

    # 1. 獲取數據 (含智慧後綴嘗試)
    quant_data = await resolve_ticker(ctx, ticker)
    if not quant_data:
        return

    try:
        # 2. 生成 Prompt
        prompt = generate_moltbot_prompt(quant_data, is_single=True)
        
        # 3. 呼叫 NVIDIA AI (非同步執行)
        ai_response = await asyncio.to_thread(generate_insight, prompt)
        
        # 4. 回傳結果
        header = f"📊 **NVIDIA 405B 即時診斷: {quant_data['meta']['ticker']}**"
        
        # 切割過長訊息
        if len(ai_response) > 1900:
            # 存成暫存檔發送
            tmp_path = "reports/temp_insight.md"
            os.makedirs("reports", exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(ai_response)
            await ctx.send(f"{header}\n(完整報告請見附件)", file=discord.File(tmp_path))
        else:
            await ctx.send(f"{header}\n\n{ai_response}")

    except Exception as e:
        await ctx.send(f"❌ 分析過程發生錯誤: {str(e)}")

# === 指令: 原有的日報 ===
@bot.command(name="report")
async def send_daily_report(ctx):
    # (保留原本的邏輯)
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
                if len(content) > 1900:
                    await ctx.send(f"📊 **日報 ({ts})**", file=discord.File(report_path))
                else:
                    await ctx.send(f"📊 **日報 ({ts})**\n\n{content}")
            else:
                await ctx.send("❌ 找不到今日日報檔案。")
        else:
            await ctx.send("❌ 找不到原始數據。")
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if token:
        bot.run(token)
    else:
        print("❌ DISCORD_TOKEN missing")
