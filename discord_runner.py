import discord
import os
import glob
import json
import pandas as pd
from datetime import datetime, timedelta
from discord.ext import commands
from discord.ui import Button, View
from dotenv import load_dotenv
from ai_engine import QuantBrain
from data.data_loader import DataLoader

# 1. 載入環境變數
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# 2. 設定 Intent (這就是剛剛缺少的關鍵設定)
intents = discord.Intents.default()
intents.message_content = True

# 3. 初始化 Bot、大腦與數據載入器
bot = commands.Bot(command_prefix='!', intents=intents)
brain = QuantBrain()
loader = DataLoader()
REPORT_DIR = "reports"

# --- 輔助函式: 抓取並整理數據 ---
def get_stock_context(symbol):
    """抓取 FinMind 數據並計算技術指標，轉為文字摘要"""
    try:
        # 抓取過去 90 天數據 (計算季線 MA60 用)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)
        
        # 呼叫 DataLoader
        df = loader.fetch_data(symbol, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
        
        if df.empty:
            return "無法取得最新數據，請小心風險。"

        # 計算指標
        latest = df.iloc[-1]
        close = latest['Close']
        ma5 = df['Close'].rolling(5).mean().iloc[-1]
        ma20 = df['Close'].rolling(20).mean().iloc[-1]
        ma60 = df['Close'].rolling(60).mean().iloc[-1]
        
        # 籌碼資訊 (如果有)
        foreign = latest.get('Institutional_Foreign', 0)
        trust = latest.get('Institutional_Trust', 0)
        
        # 產生摘要字串
        context = f"""
        - 資料日期: {latest.name.strftime('%Y-%m-%d')}
        - 最新收盤價: {close}
        - 成交量: {latest['Volume']}
        - 5日均線(MA5): {ma5:.2f} (趨勢: {'多頭' if close > ma5 else '空頭'})
        - 20日均線(MA20): {ma20:.2f} (月線)
        - 60日均線(MA60): {ma60:.2f} (季線)
        - 外資買賣超: {foreign} 張
        - 投信買賣超: {trust} 張
        """
        return context
    except Exception as e:
        return f"數據讀取錯誤: {str(e)}"

# --- 定義互動介面 (按鈕選單) ---
class AnalysisView(View):
    def __init__(self, symbol):
        super().__init__(timeout=180) # 按鈕存活 3 分鐘
        self.symbol = symbol

    # 按鈕 1: 70B 快速掃描
    @discord.ui.button(label="🚀 70B 快速掃描", style=discord.ButtonStyle.green, emoji="⚡")
    async def fast_scan(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        
        # 取得即時數據作為上下文
        context_data = get_stock_context(self.symbol)
        
        prompt = f"""
        請針對股票代號 {self.symbol} 進行盤中掃描。
        參考數據:
        {context_data}
        
        【規則】回傳嚴格 JSON 格式，包含: symbol, action(BUY/SELL/HOLD), price_target, reason, trend, confidence。
        """
        raw_response = brain.quick_check(prompt)
        
        try:
            clean_json = raw_response.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)
            
            action = data.get("action", "").upper()
            # 決定顏色
            if "BUY" in action:
                color = 0x2ecc71 # Green
            elif "SELL" in action:
                color = 0xe74c3c # Red
            else:
                color = 0x95a5a6 # Grey
            
            embed = discord.Embed(title=f"📊 {data.get('symbol', self.symbol)} 戰術掃描", description=f"**建議**: {action}", color=color)
            embed.add_field(name="🎯 目標價", value=str(data.get("price_target", "N/A")), inline=True)
            embed.add_field(name="📈 趨勢", value=str(data.get("trend", "N/A")), inline=True)
            embed.add_field(name="🤖 信心", value=f"{data.get('confidence', 'N/A')}%", inline=True)
            embed.add_field(name="💡 理由", value=str(data.get("reason", "N/A")), inline=False)
            embed.set_footer(text="Powered by NVIDIA NIM • Llama 3.1 70B")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(f"⚠️ 解析失敗: {raw_response}")

    # 按鈕 2: 405B 深度戰略
    @discord.ui.button(label="🧠 405B 深度戰略", style=discord.ButtonStyle.blurple, emoji="♟️")
    async def deep_dive(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        status_msg = await interaction.followup.send(f"🔄 正在檢索 {self.symbol} 最新數據並進行戰略推演 (需時約 15 秒)...", ephemeral=True)
        
        # 1. 抓取數據 (Python)
        market_context = get_stock_context(self.symbol)
        
        # 2. 餵給 AI (Cloud)
        report = brain.strategy_consult(self.symbol, market_context)
        
        # 3. 回傳結果 (切分長訊息)
        if len(report) > 1900:
            chunk1 = report[:1900]
            chunk2 = report[1900:]
            await interaction.followup.send(f"📄 **{self.symbol} 深度戰略報告 (Part 1)**\n{chunk1}")
            await interaction.followup.send(f"📄 **(Part 2)**\n{chunk2}")
        else:
            await interaction.followup.send(f"📄 **{self.symbol} 深度戰略報告**\n{report}")

# --- Bot 事件與指令 ---
@bot.event
async def on_ready():
    print(f'✅ 量化戰情室 (Interactive Mode) 已上線: {bot.user}')
    print('   系統架構: Pure Cloud (NVIDIA 405B/70B) + FinMind Data')

@bot.command(name="check")
async def check_stock(ctx, symbol: str):
    """
    召喚互動面板
    """
    view = AnalysisView(symbol)
    await ctx.send(f"👇 請選擇針對 **{symbol}** 的分析引擎：", view=view)

@bot.command(name="report")
async def latest_report(ctx):
    list_of_files = glob.glob(f'{REPORT_DIR}/*.md') 
    if not list_of_files:
        await ctx.send("❌ 無報告檔案。")
        return
    latest_file = max(list_of_files, key=os.path.getctime)
    filename = os.path.basename(latest_file)
    await ctx.send(f"📄 傳送最新日報: {filename}")
    with open(latest_file, 'rb') as f:
        await ctx.send(file=discord.File(f, filename))

if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("❌ 錯誤: 未找到 DISCORD_TOKEN，請檢查 .env 檔案。")