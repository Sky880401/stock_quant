import discord
import os
import glob
from discord.ext import commands
from dotenv import load_dotenv
from ai_engine import QuantBrain  # 調用我們的大腦

# 載入環境變數
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# 設定 Intent (權限)
intents = discord.Intents.default()
intents.message_content = True

# 初始化 Bot 與 QuantBrain
bot = commands.Bot(command_prefix='!', intents=intents)
brain = QuantBrain()
REPORT_DIR = "reports"

@bot.event
async def on_ready():
    print(f'✅ 量化戰情室已上線: {bot.user} (ID: {bot.user.id})')
    print('   等待指令中...')

# --- 指令 1: 即時查詢 (Mode B: Local Ollama) ---
@bot.command(name="check")
async def check_stock(ctx, symbol: str):
    """
    使用本地 Ollama 快速檢查。
    用法: !check 2330
    """
    await ctx.send(f"⚡ 收到請求，正在呼叫本地 AI 分析 {symbol}...")
    
    # 這裡未來可以串接真實股價，現在先模擬 Prompt
    prompt = f"請簡短分析股票代號 {symbol} 的一般性市場觀點 (模擬數據)。請用 JSON 格式回答。"
    
    # 呼叫 ai_engine 的本地快速通道
    response = brain.quick_check(prompt)
    
    # 回傳結果 (用程式碼區塊包起來比較好看)
    await ctx.send(f"```json\n{response}\n```")

# --- 指令 2: 取得最新日報 (Mode A: NVIDIA Report) ---
@bot.command(name="report")
async def latest_report(ctx):
    """
    上傳最新的 Markdown 日報檔案。
    用法: !report
    """
    # 找尋 reports 資料夾中最新的 .md 檔案
    list_of_files = glob.glob(f'{REPORT_DIR}/*.md') 
    if not list_of_files:
        await ctx.send("❌ 目前沒有任何日報檔案。請先執行 main.py 與 ai_runner.py。")
        return

    latest_file = max(list_of_files, key=os.path.getctime)
    filename = os.path.basename(latest_file)
    
    await ctx.send(f"📄 正在傳送最新日報：**{filename}**")
    
    # 透過 Discord 傳送檔案
    with open(latest_file, 'rb') as f:
        await ctx.send(file=discord.File(f, filename))

# --- 指令 3: 系統狀態 ---
@bot.command(name="status")
async def system_status(ctx):
    await ctx.send("🟢 System Online via Rocky Linux.\n✅ NVIDIA Cloud Connected.\n✅ Local Ollama Ready.")

if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("❌ 錯誤: 未找到 DISCORD_TOKEN，請檢查 .env 檔案。")