import discord
from discord.ext import commands
import os
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

# === 1. 環境變數載入 ===
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
env_path = Path(PROJECT_ROOT) / '.env'
load_dotenv(dotenv_path=env_path, override=True)

# 強制路徑優先權
sys.path.insert(0, PROJECT_ROOT)

# === 2. 初始化機器人 ===
class QuantBot(commands.Bot):
    def __init__(self):
        # 啟用必要意圖
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def on_ready(self):
        print("-" * 30)
        print(f"🤖 QuantMaster Bot 上線: {self.user.name}")
        print(f"🚀 核心引擎: NVIDIA Llama 3.1 405B")
        print("-" * 30)
        
        # 嘗試發送上線通知
        channel_id = os.getenv("DISCORD_CHANNEL_ID")
        if channel_id:
            try:
                channel = self.get_channel(int(channel_id))
                if channel:
                    await channel.send("✅ **QuantMaster 系統上線** (Command Fixed)")
            except Exception as e:
                print(f"⚠️ 無法發送上線通知: {e}")

# 實例化 Bot
bot = QuantBot()

# === 3. 註冊指令 (關鍵修正：移至全域範圍) ===
@bot.command(name="report")
async def send_report(ctx):
    """指令: !report - 發送最新的投資日報"""
    print(f"📩 收到指令 !report，來自 {ctx.author}")
    try:
        # 1. 取得日期字串
        json_path = os.path.join(PROJECT_ROOT, 'data/latest_report.json')
        
        if os.path.exists(json_path):
            with open(json_path, 'r') as f:
                data = json.load(f)
                timestamp = data.get('timestamp', '')[:10].replace('-', '')
        else:
            await ctx.send("⚠️ 警告: 找不到原始數據，將使用今日日期。")
            import time
            timestamp = time.strftime("%Y%m%d")

        # 2. 尋找報告檔案
        report_filename = f"daily_summary_{timestamp}_nvidia.md"
        report_path = os.path.join(PROJECT_ROOT, "reports", report_filename)
        
        if os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            # 3. 發送 (處理長度限制)
            header = f"📊 **NVIDIA 405B 投資日報 ({timestamp})**"
            if len(content) > 1900:
                await ctx.send(f"{header}\n(報告過長，請查看附件)", file=discord.File(report_path))
            else:
                await ctx.send(f"{header}\n\n{content}")
        else:
            await ctx.send(f"❌ 找不到今日報告: `{report_filename}`\n請確認是否已執行 `ai_runner.py`。")
            
    except Exception as e:
        error_msg = f"❌ 發送失敗: {str(e)}"
        print(error_msg)
        await ctx.send(error_msg)

# === 4. 啟動 ===
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ [Fatal] DISCORD_TOKEN 未設定。")
    else:
        try:
            bot.run(token)
        except Exception as e:
            print(f"❌ 運行錯誤: {e}")
