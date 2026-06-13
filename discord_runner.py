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

from main import analyze_single_target, generate_moltbot_prompt, get_stock_name_zh, TARGET_STOCKS, fetch_stock_data_smart
from ai_runner import generate_insight
from utils.model_config import get_model, set_model, AVAILABLE_MODELS
from utils.logger import log_info, log_error
from utils.history_recorder import record_user_query
from utils.prediction_log import log_prediction, backfill_matured, accuracy_summary
from utils.quota_manager import check_quota_status, deduct_quota, add_bonus
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
    def __init__(self, ctx, ticker, stock_name, user_id, is_admin, tier='free'):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.ticker = ticker
        self.stock_name = stock_name
        self.user_id = user_id
        self.is_admin = is_admin
        self.tier = tier
        self.value = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """集中守門：只有發起 !a 的本人能操作這組按鈕，其他人點擊一律擋下。"""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "⛔ 這是別人的查詢，請自己打 `!a 代號` 查詢喔。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ 確認分析", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_admin:
            # 按下確認時重新檢查額度，避免同時開多個確認視窗繞過限制（audit 修正）
            allowed, _, limit = check_quota_status(self.user_id, self.tier)
            if not allowed:
                await interaction.response.send_message(
                    f"⛔ 今日額度已用完 ({limit} 次/天)，本次不執行分析。", ephemeral=True)
                self.value = False
                self.stop()
                return
            deduct_quota(self.user_id, self.tier)
        await interaction.response.send_message(f"🚀 BMO 啟動！正在為 **{self.stock_name}** 進行深度運算...", ephemeral=False)
        self.value = True
        self.stop()

    @discord.ui.button(label="❌ 取消", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("已取消 (本次不扣除額度)。", ephemeral=True)
        self.value = False
        self.stop()

# 每日選股排行自動推播設定（台股 UTC+8，收盤 13:30）
# 注意：TWSE 三大法人買賣超當日資料約 15:00~16:00 才陸續公布，
# 14:30 推播會抓到前一日法人資料，故時間設在資料齊備後。
# 09:30 UTC = 17:30 台北時間，可調整。
RANK_PUSH_TIME_UTC = time(hour=9, minute=30, tzinfo=timezone.utc)
RANK_PUSH_N = 8

class QuantBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.target_channel_id = None

    async def on_ready(self):
        log_info(f"🤖 BMO V10.1 (BETA Role + Format) 上線: {self.user.name}")
        await asyncio.to_thread(load_stock_map)
        _register_training_notifier()
        if not self.daily_scan_task.is_running():
            self.daily_scan_task.start()
        if not self.daily_rank_task.is_running():
            self.daily_rank_task.start()

    @tasks.loop(time=RANK_PUSH_TIME_UTC)
    async def daily_rank_task(self):
        # 台股收盤後自動推播選股排行到綁定頻道（沿用 !rank 格式與 send_long 分段）
        if not self.target_channel_id:
            log_info("⏭️ 排行推播略過：尚未綁定頻道（請先在頻道用 !bind）")
            return
        ch = self.get_channel(self.target_channel_id)
        if ch is None:
            log_error(f"排行推播略過：找不到頻道 {self.target_channel_id}")
            return
        try:
            text = await build_rank_text(RANK_PUSH_N)
            if text is None:
                log_info("⏭️ 排行推播略過：排行資料不足或為空")
                return
            await send_long(ch, text)
            log_info("📈 已自動推播每日選股排行")
        except Exception as e:
            log_error(f"排行推播失敗: {e}")

    @tasks.loop(time=time(hour=6, minute=0, tzinfo=timezone.utc))
    async def daily_scan_task(self):
        # P1 閉環：每日回填到期預測的實際結果
        try:
            closed, checked = await asyncio.to_thread(backfill_matured, _latest_price)
            if closed:
                log_info(f"📈 預測回填：{checked} 筆到期，{closed} 筆已結算")
                if self.target_channel_id:
                    ch = self.get_channel(self.target_channel_id)
                    if ch:
                        await ch.send(f"📈 已結算 {closed} 筆到期預測，使用 `!accuracy` 查看最新命中率。")
        except Exception as e:
            log_error(f"預測回填失敗: {e}")

bot = QuantBot()

# --- global permission gate (2026-06-13, Sky) -----------------------
# Non-admin channel members may ONLY use !a (analyze); all other
# commands are rejected. Matches on the command's primary name, so
# aliases (e.g. "a") resolve to "analyze" automatically.
PUBLIC_COMMANDS = {"analyze"}

@bot.check
async def _admin_only_gate(ctx):
    perms = getattr(ctx.author, "guild_permissions", None)
    if perms is not None and perms.administrator:
        return True
    if ctx.command and ctx.command.name in PUBLIC_COMMANDS:
        return True
    raise commands.CheckFailure("admin_only")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("🔒 此指令僅限管理員。一般成員請用 `!a <代號>` 查詢個股分析。")
        return
    if isinstance(error, commands.CommandNotFound):
        return
    log_error("command error (%s): %s" % (getattr(ctx.command, "name", "?"), error))

async def send_long(ctx, text, files=None):
    """Discord 單則上限 2000 字，超過就依段落切塊送出；附件掛在最後一則。"""
    LIMIT = 1990
    chunks = []
    buf = ""
    for para in text.split("\n"):
        # 單段就超長 → 硬切
        while len(para) > LIMIT:
            chunks.append(para[:LIMIT]); para = para[LIMIT:]
        if len(buf) + len(para) + 1 > LIMIT:
            chunks.append(buf); buf = para
        else:
            buf = f"{buf}\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    if not chunks:
        chunks = ["(無內容)"]
    for i, c in enumerate(chunks):
        await ctx.send(c, files=files if (i == len(chunks) - 1 and files) else None)


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
    # 純英數字代號（如 AAPL、TSLA、BRK-B）→ 視為美股，用 yfinance 取公司全名
    if all(c.isalnum() or c in ".-" for c in raw):
        return raw, get_stock_name_zh(raw)
    return raw, raw

@bot.command(name="analyze", aliases=["a"])
async def analyze_stock(ctx, ticker: str = None):
    if not ticker:
        await ctx.send("請輸入代號或股名，台股例 `!a 2330`，美股例 `!a AAPL`")
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
    
    view = ConfirmView(ctx, clean_ticker, stock_name, user_id, is_admin, tier)
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
            roi = (data.get('backtest_insight') or {}).get('historical_roi', "N/A")
            record_user_query(ctx.author.name, data['meta']['ticker'], data['meta']['name'], dec['action'], dec['final_confidence'], roi)

            # P1 預測日誌：存下這次判斷，等 N 日後回填實際結果算命中率
            strat_type = (data.get('backtest_insight') or {}).get('strategy_type', 'N/A')
            log_prediction(
                ticker=data['meta']['ticker'], name=data['meta']['name'],
                action=dec['action'], confidence=dec.get('final_confidence'),
                strategy=strat_type, entry_price=data['price_data']['latest_close'],
            )

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
            
            await send_long(ctx, f"{header}\n\n{ai_response}", files=files)
            
        except Exception as e:
            log_error(f"系統錯誤: {e}")
            await ctx.send(f"❌ 系統錯誤: {str(e)}")

@bot.command(name="gift", aliases=["quota", "give"])
@commands.has_permissions(administrator=True)
async def gift_quota(ctx, member: discord.Member, amount: int):
    """一次性加值：@用戶 給額外 N 次查詢額度（用完才歸零，不影響每日上限）。"""
    new_bonus = add_bonus(member.id, amount)
    await ctx.send(
        f"🎁 已給 **{member.display_name}** 額外 {amount} 次查詢額度（一次性）！\n"
        f"目前加值餘額：**{new_bonus} 次**（用完才歸零，每日免費額度照常）")

@bot.command(name="hotlist", aliases=["hotrank"])
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
            
            keys = [k for k in results.keys()][:25]
            opts = [discord.SelectOption(label=str(k)[:100], value=str(k)[:100]) for k in keys]
            async def _pick(val):
                await ctx.invoke(show_period_analysis, strategy=val)
            await ctx.send("📊 請選擇要查看的策略時間段分析：",
                           view=SimpleSelectView(ctx.author.id, opts, "選策略分析…", _pick))
            return
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
        
        # Sky 反饋：沒給模式→開下拉選單點選（免記 category:/sort: 語法）
        if mode is None:
            opts = [
                discord.SelectOption(label="全部（按勝率）", value="__all__"),
                discord.SelectOption(label="詳細模式", value="detail"),
                discord.SelectOption(label="分類：指標", value="category:indicator"),
                discord.SelectOption(label="分類：ML", value="category:ml"),
                discord.SelectOption(label="分類：價格行為", value="category:price_action"),
                discord.SelectOption(label="分類：綜合", value="category:comprehensive"),
                discord.SelectOption(label="排序：勝率", value="sort:win_rate"),
                discord.SelectOption(label="排序：Sharpe", value="sort:sharpe"),
                discord.SelectOption(label="排序：ROI", value="sort:roi"),
            ]
            async def _pick(val):
                await ctx.invoke(show_strategies, mode=val)
            await ctx.send("📈 請選擇檢視方式：",
                           view=SimpleSelectView(ctx.author.id, opts, "選檢視方式…", _pick))
            return

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


# === 訓練完成自動回傳結果（2026-06-13 Sky）===
def _register_training_notifier():
    """on_ready 時掛上訓練完成回呼。"""
    try:
        from utils.training_queue import get_training_queue, set_completion_callback
        get_training_queue()
        set_completion_callback(_on_training_done)
        log_info("📨 訓練完成通知已掛載")
    except Exception as e:
        log_error(f"掛載訓練通知失敗: {e}")


def _on_training_done(task):
    """worker 執行緒呼叫：把結果排到 bot event loop 發回 Discord。"""
    try:
        asyncio.run_coroutine_threadsafe(_send_training_result(task), bot.loop)
    except Exception as e:
        log_error(f"排程訓練通知失敗: {e}")


async def _send_training_result(task):
    try:
        ch_id = task.get("channel_id")
        if not ch_id:
            return
        channel = bot.get_channel(int(ch_id))
        if channel is None:
            return
        uid = task.get("user_id")
        cfg = task.get("config", {}) or {}
        strat = cfg.get("strategy", "?")
        ticker = cfg.get("stock_ticker", "?")
        tid = task.get("task_id", "?")
        mention = f"<@{uid}>" if uid else ""
        if task.get("status") == "completed":
            res = task.get("results", {}) or {}
            # 防呆：回測因資料不足回 -999 哨兵時，給友善提示而非垃圾數字
            if res.get("best_roi") in (-999, -999.0) or res.get("best_total_trades") == 0:
                e = discord.Embed(title="⚠️ 訓練無有效結果", color=discord.Color.orange(),
                                  description=f"策略 {TRAIN_STRATEGY_LABELS.get(strat, strat)} / {ticker}：這段期間資料太少或沒有產生交易，跑不出有效回測。請改選『近一年』或『全部歷史』再試。")
                e.set_footer(text=f"任務 {tid}")
                await channel.send(content=mention or None, embed=e)
                return
            e = discord.Embed(title="✅ 訓練完成", color=discord.Color.green())
            e.add_field(name="策略", value=TRAIN_STRATEGY_LABELS.get(strat, strat), inline=True)
            e.add_field(name="股票", value=str(ticker), inline=True)
            e.add_field(name="任務ID", value=f"`{tid}`", inline=False)
            if res.get("best_params") is not None:
                bp = ", ".join(f"{k}={v}" for k, v in res["best_params"].items())
                e.add_field(name="最佳參數", value=f"`{bp}`", inline=False)
                e.add_field(name="ROI", value=f"{res.get('best_roi', '?')}%", inline=True)
                e.add_field(name="勝率", value=f"{res.get('best_win_rate', '?')}%", inline=True)
                e.add_field(name="Sharpe", value=f"{res.get('best_sharpe', '?')}", inline=True)
                e.add_field(name="交易次數", value=f"{res.get('best_total_trades', '?')}", inline=True)
                e.add_field(name="最大回撤", value=f"{res.get('best_max_dd', '?')}%", inline=True)
                e.set_footer(text=f"測試 {res.get('successful_combinations', '?')}/{res.get('total_combinations_tested', '?')} 組 | !train-status {tid} 看完整")
            else:
                e.description = f"完成，用 `!train-status {tid}` 看詳情。"
            await channel.send(content=mention or None, embed=e)
        elif task.get("status") == "failed":
            err = str(task.get("error", "未知錯誤"))[:300]
            e = discord.Embed(title="❌ 訓練失敗", color=discord.Color.red(),
                              description=f"策略 {strat} / {ticker}\n錯誤：{err}")
            e.set_footer(text=f"任務 {tid}")
            await channel.send(content=mention or None, embed=e)
    except Exception as ex:
        log_error(f"發送訓練結果失敗: {ex}")


# === 通用互動元件（2026-06-13 Sky：多參數指令改點選）===
class _PanelSelect(discord.ui.Select):
    def __init__(self, owner_id, options, placeholder, on_pick):
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)
        self.owner_id = owner_id
        self._on_pick = on_pick

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("⛔ 這是別人的操作，請自己下指令。", ephemeral=True)
            return
        val = self.values[0]
        await interaction.response.edit_message(content="✅ 已選擇，處理中…", view=None)
        await self._on_pick(val)


class SimpleSelectView(discord.ui.View):
    """單一下拉選單面板：選完即呼叫 on_pick(value)。"""
    def __init__(self, owner_id, options, placeholder, on_pick):
        super().__init__(timeout=90)
        self.add_item(_PanelSelect(owner_id, options, placeholder, on_pick))


class _TickerOnlyModal(discord.ui.Modal, title="輸入股票代號"):
    ti = discord.ui.TextInput(label="股票代號", placeholder="例如 2317 或 2330.TW", required=True, max_length=12)

    def __init__(self, on_submit):
        super().__init__()
        self._on_submit = on_submit

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="✅ 收到，處理中…", view=None)
        await self._on_submit(str(self.ti.value).strip())


class TickerEntryView(discord.ui.View):
    """單一股票代號輸入面板：按鈕→Modal→on_submit(ticker)。"""
    def __init__(self, owner_id, on_submit):
        super().__init__(timeout=90)
        self.owner_id = owner_id
        self._on_submit = on_submit

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("⛔ 這是別人的操作。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="輸入股票代號", emoji="✏️", style=discord.ButtonStyle.primary)
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(_TickerOnlyModal(self._on_submit))


# === !train 互動式選單面板（2026-06-13 Sky 反饋：參數多易打錯）===
# 重點：策略 registry 的 key 是「簡體字」，台灣用戶打繁體會比對不到→報未知策略。
# 下拉選單讓使用者看繁體標籤、程式用正確簡體 key，一次解掉「打錯 + 繁簡不符」。
TRAIN_STRATEGY_LABELS = {
    "MA交叉": "MA 交叉（均線）",
    "RSI反转": "RSI 反轉",
    "MACD动能": "MACD 動能",
    "KD随机指标": "KD 隨機指標",
    "布林带策略": "布林帶策略",
    "价值估值": "價值估值",
    "回撤交易": "回撤交易",
    "混合预测 (ML)": "混合預測（ML）",
    "综合策略": "綜合策略",
}
# 2026-06-13：拿掉太短期間——回測需 ≥100 交易日(run_backtest)，近一週/月/今天必回 -999 垃圾值
TRAIN_PERIODS = [("year", "近一年"), ("ytd", "今年至今"), ("full", "全部歷史")]
TRAIN_ROIS = ["10", "15", "20", "25", "30"]


def _train_strategy_keys():
    """以 registry 實際存在的 key 為準，僅保留有中文標籤者，避免顯示到不存在的策略。"""
    try:
        from strategies.strategy_registry import get_strategy_registry
        keys = list(get_strategy_registry().strategies.keys())
        return [k for k in keys if k in TRAIN_STRATEGY_LABELS] or list(TRAIN_STRATEGY_LABELS.keys())
    except Exception:
        return list(TRAIN_STRATEGY_LABELS.keys())


class TickerModal(discord.ui.Modal, title="輸入股票代號"):
    ticker_input = discord.ui.TextInput(
        label="股票代號", placeholder="例如 2317 或 2330.TW", required=True, max_length=12)

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.ticker = str(self.ticker_input.value).strip()
        await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)


class TrainConfigView(discord.ui.View):
    """!train 的點選式設定面板：策略/時間段/目標ROI 用下拉、股票代號用 Modal。"""

    def __init__(self, ctx, user_id, ticker=None):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.user_id = user_id
        self.ticker = ticker
        self.strategy = None
        self.period = None
        self.target_roi = 15.0
        self.submitted = False
        self._build_selects()

    def _build_selects(self):
        strat = discord.ui.Select(
            placeholder="① 選策略", min_values=1, max_values=1, row=0,
            options=[discord.SelectOption(label=TRAIN_STRATEGY_LABELS[k], value=k)
                     for k in _train_strategy_keys()])
        strat.callback = self._on_strategy
        self.add_item(strat)
        period = discord.ui.Select(
            placeholder="② 選時間段", min_values=1, max_values=1, row=1,
            options=[discord.SelectOption(label=lab, value=v) for v, lab in TRAIN_PERIODS])
        period.callback = self._on_period
        self.add_item(period)
        roi = discord.ui.Select(
            placeholder="③ 選目標 ROI(%)", min_values=1, max_values=1, row=2,
            options=[discord.SelectOption(label=f"{r}%", value=r) for r in TRAIN_ROIS])
        roi.callback = self._on_roi
        self.add_item(roi)

    def build_embed(self):
        e = discord.Embed(title="🎓 眾包訓練設定", color=discord.Color.blurple(),
                          description="用下面的選單**點選**就好，不用打字。選好後按 **✅ 送出訓練**。")
        e.add_field(name="股票代號", value=self.ticker or "（尚未設定，按 ✏️ 輸入）", inline=False)
        e.add_field(name="策略", value=TRAIN_STRATEGY_LABELS.get(self.strategy, "未選"), inline=True)
        e.add_field(name="時間段", value=dict(TRAIN_PERIODS).get(self.period, "未選"), inline=True)
        e.add_field(name="目標ROI", value=f"{self.target_roi:.0f}%", inline=True)
        return e

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "⛔ 這是別人的訓練設定，請自己打 `!train` 開新的。", ephemeral=True)
            return False
        return True

    async def _on_strategy(self, interaction: discord.Interaction):
        self.strategy = interaction.data["values"][0]
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_period(self, interaction: discord.Interaction):
        self.period = interaction.data["values"][0]
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_roi(self, interaction: discord.Interaction):
        self.target_roi = float(interaction.data["values"][0])
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="股票代號", emoji="✏️", style=discord.ButtonStyle.secondary, row=3)
    async def set_ticker(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TickerModal(self))

    @discord.ui.button(label="✅ 送出訓練", style=discord.ButtonStyle.green, row=3)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        missing = []
        if not self.ticker:
            missing.append("股票代號")
        if not self.strategy:
            missing.append("策略")
        if not self.period:
            missing.append("時間段")
        if missing:
            await interaction.response.send_message("⚠️ 還沒選：" + "、".join(missing), ephemeral=True)
            return
        self.submitted = True
        await interaction.response.edit_message(content="🚀 已送出，計算中…", embed=self.build_embed(), view=None)
        self.stop()

    @discord.ui.button(label="❌ 取消", style=discord.ButtonStyle.red, row=3)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="已取消。", embed=None, view=None)
        self.submitted = False
        self.stop()


async def _train_do_submit(ctx, strategy, ticker, period, target_roi):
    """共用送出邏輯：驗策略→解時間段→進佇列→回報（打字路徑與面板路徑共用）。"""
    from utils.training_queue import get_training_queue
    from strategies.strategy_registry import get_strategy_registry

    registry = get_strategy_registry()
    if strategy not in registry.strategies:
        available = ", ".join(list(registry.strategies.keys())[:5])
        await ctx.send(embed=discord.Embed(
            title="❌ 未知策略",
            description=f"策略 `{strategy}` 不存在\n\n**可用策略**: {available}...",
            color=discord.Color.red()))
        return
    try:
        start_date, end_date = _parse_period_to_dates(period)
    except ValueError as e:
        await ctx.send(embed=discord.Embed(title="❌ 無效的時間段", description=str(e), color=discord.Color.red()))
        return
    queue = get_training_queue()
    task_id = queue.submit_training(user_id=ctx.author.id, strategy=strategy, ticker=ticker,
                                    start_date=start_date, end_date=end_date, target_roi=target_roi,
                                    channel_id=ctx.channel.id)
    embed = discord.Embed(title="📊 訓練任務已提交", color=discord.Color.blue())
    embed.add_field(name="任務ID", value=f"`{task_id}`", inline=False)
    embed.add_field(name="策略", value=TRAIN_STRATEGY_LABELS.get(strategy, strategy), inline=True)
    embed.add_field(name="股票", value=ticker, inline=True)
    embed.add_field(name="時間段", value=f"{start_date} ~ {end_date}", inline=True)
    embed.add_field(name="目標ROI", value=f"{target_roi}%", inline=True)
    embed.add_field(name="預計等待時間", value="2-10分鐘 (根據參數數量和伺服器負載)", inline=False)
    embed.set_footer(text="💡 使用 !train-status <task_id> 查看進度")
    await ctx.send(embed=embed)


@bot.command(name="train", aliases=["training", "optimize"])
async def train_strategy(ctx, *args):
    """眾包訓練：不帶完整參數 → 開點選面板；帶 3+ 參數 → 沿用打字路徑。

    面板用法（推薦）: !train  或  !train 2317
    打字用法（熟手）: !train MACD动能 2330.TW month --roi 20
    """
    try:
        # 沒給足參數 → 開互動選單面板（解掉參數多/繁簡key打錯的痛點）
        if len(args) < 3:
            ticker = args[0] if (len(args) >= 1 and not args[0].startswith("--")) else None
            view = TrainConfigView(ctx, ctx.author.id, ticker=ticker)
            await ctx.send(embed=view.build_embed(), view=view)
            await view.wait()
            if not view.submitted:
                return
            await _train_do_submit(ctx, view.strategy, view.ticker, view.period, view.target_roi)
            return

        # 打字路徑（向後相容）
        strategy = args[0]
        ticker = args[1]
        period = args[2]
        target_roi = 15.0
        if len(args) >= 5 and args[3] == "--roi":
            try:
                target_roi = float(args[4])
            except ValueError:
                await ctx.send(f"❌ 目標ROI必須是數字，收到: {args[4]}")
                return
        await _train_do_submit(ctx, strategy, ticker, period, target_roi)

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

class ModelSelect(discord.ui.Select):
    def __init__(self, owner_id):
        self.owner_id = owner_id
        current = get_model()
        options = []
        for label, (model_id, desc) in AVAILABLE_MODELS.items():
            options.append(discord.SelectOption(
                label=label,
                value=model_id,
                description=desc[:100],
                default=(model_id == current),
            ))
        super().__init__(placeholder="選擇交談用的 NVIDIA 模型…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        # 雙重保險：只有 owner 能真正改（按鈕本身已限 owner，但防止別人撈 custom_id）
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("⛔ 只有擁有者可以切換模型。", ephemeral=True)
            return
        chosen = self.values[0]
        ok = set_model(chosen)
        if ok:
            await interaction.response.send_message(f"✅ 已切換交談模型為：`{chosen}`", ephemeral=False)
        else:
            await interaction.response.send_message("❌ 無效的模型。", ephemeral=True)
        self.view.stop()


class ModelSelectView(discord.ui.View):
    def __init__(self, owner_id):
        super().__init__(timeout=60)
        self.owner_id = owner_id
        self.add_item(ModelSelect(owner_id))


@bot.command(name="model", aliases=["setmodel"])
async def select_model(ctx):
    """切換 AI 交談模型（限 bot 擁有者本人）。"""
    if not await bot.is_owner(ctx.author):
        await ctx.send("⛔ 此指令僅限擁有者使用。")
        return
    current = get_model()
    view = ModelSelectView(ctx.author.id)
    await ctx.send(f"🧠 目前模型：`{current}`\n請選擇新的交談模型：", view=view)


def _latest_price(ticker):
    """給預測回填用：回傳該股最新收盤價，失敗回 None。"""
    try:
        res = fetch_stock_data_smart(ticker)
        if res.get("status") == "error":
            return None
        return float(res["df"]["Close"].iloc[-1])
    except Exception:
        return None


@bot.command(name="accuracy", aliases=["acc", "winrate"])
async def show_accuracy(ctx):
    """顯示 BMO 歷史預測命中率（P1 閉環）。"""
    try:
        await ctx.defer()
        s = await asyncio.to_thread(accuracy_summary)
        if s["closed"] == 0:
            await ctx.send(
                f"📊 預測命中率\n目前尚無已結算的預測（{s['open']} 筆等待到期約一個月）。\n"
                f"系統需累積時間才有勝率，這是正常的。"
            )
            return
        lines = [
            "📊 BMO 歷史預測命中率",
            f"整體命中率：{s['hit_rate']}%（已結算 {s['closed']} 筆，{s['open']} 筆待到期）",
            f"平均報酬：{s['avg_return']}%",
        ]
        if s["by_strategy"]:
            from utils.strategy_weights import MIN_SAMPLES
            lines.append("")
            lines.append(f"各策略（Kelly 採用門檻 {MIN_SAMPLES} 筆）：")
            for b in s["by_strategy"][:6]:
                if b["n"] >= MIN_SAMPLES:
                    mark = "✅ 倉位已用P1實測"
                else:
                    mark = f"⏳ 還需{MIN_SAMPLES - b['n']}筆(暫用回測)"
                lines.append(f"{b['strategy']}：{b['rate']}%（{b['hits']}/{b['n']}）{mark}")
        lines.append("")
        lines.append("註：命中＝看多後實際漲、看空後實際跌。合理目標 53-57%。")
        await ctx.send("\n".join(lines))
    except Exception as e:
        log_error(f"!accuracy 失敗: {e}")
        await ctx.send(f"❌ 查詢命中率失敗: {str(e)}")


def _run_walk_forward(ticker):
    from utils.walk_forward import walk_forward
    from strategies.indicators.ma_crossover import MACrossoverStrategy
    from strategies.indicators.institutional_flow import InstitutionalFlowStrategy
    res = fetch_stock_data_smart(ticker)
    if res.get("status") == "error":
        return None
    df = res["df"]
    return {
        "MA交叉": walk_forward(MACrossoverStrategy(), df),
        "法人籌碼動能": walk_forward(InstitutionalFlowStrategy(), df, min_bars=30),
    }


@bot.command(name="validate", aliases=["wf", "backtest_wf"])
async def validate_strategy(ctx, ticker: str = None):
    """P5 walk-forward 驗證：對某股做樣本外回測，揭露策略穩定性/過擬合。"""
    if not ticker:
        async def _run(tk):
            await ctx.invoke(validate_strategy, ticker=tk)
        await ctx.send("🔬 要驗證哪一檔？按下方輸入股票代號：",
                       view=TickerEntryView(ctx.author.id, _run))
        return
    try:
        await ctx.defer()
        clean, name = resolve_ticker_info(ticker)
        out = await asyncio.to_thread(_run_walk_forward, clean)
        if not out:
            await ctx.send(f"❌ 抓不到 {ticker} 的資料")
            return
        lines = [f"🔬 walk-forward 樣本外驗證：{name} ({clean})", ""]
        for strat, r in out.items():
            if r.get("insufficient"):
                lines.append(f"{strat}：{r.get('reason','樣本不足')}")
            else:
                lines.append(
                    f"{strat}：整體命中 {r['overall_hit']}%（{r['samples']}筆/持有{r['horizon']}日）")
                lines.append(f"  分段 {r['segment_hits']}｜波動{r['spread']}％｜{r['stability']}｜判定：{r['verdict']}")
        lines.append("")
        lines.append("註：命中合理目標53-57%；分段波動大代表脆弱/過擬合，>65%要先懷疑樣本。")
        await ctx.send("\n".join(lines))
    except Exception as e:
        log_error(f"!validate 失敗: {e}")
        await ctx.send(f"❌ 驗證失敗: {str(e)}")


@bot.command(name="說明", aliases=["指令", "helpme", "menu"])
async def show_help(ctx):
    """指令總覽（限 bot 擁有者本人）。"""
    if not await bot.is_owner(ctx.author):
        await ctx.send("⛔ 此指令僅限擁有者使用。")
        return
    lines = [
        "📖 BMO 指令總覽（僅你可見）",
        "",
        "【查詢分析】",
        "!a <代號/股名> — 深度診斷（台股例 !a 2330 / !a 台積電 / !a 0050；美股例 !a AAPL / !a TSLA）",
        "!accuracy — 歷史預測命中率 + 各策略 Kelly 採用狀態",
        "!health — 策略健康體檢，依命中率汰弱留強（別名 !體檢）",
        "!rank [n] — 每日橫截面選股排行(做多前段/避開後段，別名 !排行；每日 17:30 台北自動推播至綁定頻道)",
        "!validate <代號> — walk-forward 樣本外驗證（防過擬合）",
        "!策略 — 目前分析用到的策略清單",
        "!strategies — 策略回測績效表（可加 detail / sort:sharpe / category:ml）",
        "",
        "【管理 · 限你】",
        "!gift @用戶 <次數> — 一次性加值查詢額度（別名 !quota !give）",
        "!model — 切換 AI 交談模型",
        "!seed [代號] — 用歷史資料補考、灌入已結算預測校準 P1（別名 !補考）",
        "!說明 — 本清單（別名 !指令 !menu）",
        "",
        "【訓練/其他】",
        "!train <策略> <代號> <時間段> — 眾包參數優化；!train-status <id>；!train-history",
        "!period [策略] — 時間段回測｜!hotlist — 熱搜排行｜!bind — 綁定本頻道",
    ]
    await ctx.send("\n".join(lines))


@bot.command(name="策略", aliases=["strategylist", "strat"])
async def list_active_strategies(ctx):
    """列出目前分析實際使用的策略。"""
    lines = [
        "🧠 BMO 目前使用的策略",
        "",
        "【主策略】回測錦標賽挑勝率最高者當主訊號：",
        "Trend (MA) — 均線順勢",
        "Reversion (RSI) — RSI 乖離逆勢",
        "Momentum (MACD) — MACD 動能",
        "Swing (KD) — KD 短線轉折",
        "PriceAction (Pullback) — 回後上漲型態",
        "",
        "【輔助訊號】與主策略融合：",
        "Fundamental (Valuation) — 本益比/淨值比估值（ETF 自動略過）",
        "Chip — 三大法人籌碼（外資/投信/自營）",
        "Institutional — 法人連續買賣超動能",
        "ML (Adaptive) — 機器學習輔助",
        "",
        "【風險/倉位】Bollinger 布林、ATR 波動率、Kelly 倉位（優先用 P1 實測命中率）",
        "績效數字看 !strategies｜樣本外穩定性看 !validate <代號>",
    ]
    await ctx.send("\n".join(lines))


@bot.command(name="seed", aliases=["補考"])
async def seed_predictions(ctx, ticker: str = None):
    """用歷史資料補考、立即灌入已結算預測校準 P1（限 owner）。"""
    if not await bot.is_owner(ctx.author):
        await ctx.send("⛔ 此指令僅限擁有者使用。")
        return
    try:
        await ctx.defer()
        from main import seed_history_predictions
        if ticker:
            clean, name = resolve_ticker_info(ticker)
            tickers = [clean]
        else:
            tickers = ["2330.TW", "2317.TW", "2454.TW", "2412.TW", "2308.TW",
                       "2882.TW", "0050.TW", "0056.TW", "2603.TW", "3008.TW"]
        total = 0
        for t in tickers:
            total += await asyncio.to_thread(seed_history_predictions, t)
        await ctx.send(
            f"📥 歷史補考完成：寫入 {total} 筆已結算預測（{len(tickers)} 檔）。\n"
            f"用 `!accuracy` 看校準後的命中率；倉位達門檻會自動改用 P1 實測。")
    except Exception as e:
        log_error(f"!seed 失敗: {e}")
        await ctx.send(f"❌ 補考失敗: {str(e)}")


@bot.command(name="health", aliases=["體檢", "汰弱留強"])
async def strategy_health(ctx):
    """策略健康檢查：依 P1 實測命中率汰弱留強，標出哪些可真金下注、哪些該停用。"""
    try:
        await ctx.defer()
        from utils.strategy_weights import MIN_SAMPLES
        HEALTHY, MARGIN = 53.0, 48.0   # 命中率門檻：>=53 健康、48-53 邊緣、<48 不及格
        s = await asyncio.to_thread(accuracy_summary)
        if s["closed"] == 0:
            await ctx.send("🩺 尚無已結算預測可體檢。先用 `!seed` 補考或等預測到期。")
            return

        healthy = weak = pending = 0
        total_hits = sum(b["hits"] for b in s["by_strategy"])
        lines = [
            "🩺 策略健康體檢（依 P1 實測命中率）",
            f"整體：{s['hit_rate']}%（={total_hits}/{s['closed']}）｜平均報酬 {s['avg_return']}%",
            f"門檻：≥{HEALTHY:.0f}% 可下注、{MARGIN:.0f}-{HEALTHY:.0f}% 謹慎、<{MARGIN:.0f}% 建議停用",
            "",
        ]
        for b in sorted(s["by_strategy"], key=lambda x: -x["rate"]):
            rate, n = b["rate"], b["n"]
            if n < MIN_SAMPLES:
                verdict = f"⏳ 樣本不足({n}/{MIN_SAMPLES})，先別重押"; pending += 1
            elif rate >= HEALTHY:
                verdict = "✅ 健康，可真金下注"; healthy += 1
            elif rate >= MARGIN:
                verdict = "🟡 邊緣，謹慎小倉"
            else:
                verdict = "🔴 不及格，建議停用/重調"; weak += 1
            lines.append(f"{b['strategy']}：{rate}%（{b['hits']}/{n}）→ {verdict}")

        lines.append("")
        if healthy:
            lines.append(f"結論：{healthy} 個策略達標可下注、{weak} 個建議停用。Kelly 已自動依命中率縮放倉位。")
        else:
            lines.append("結論：目前沒有策略命中率達標，系統會把倉位壓很小保護你——這是對的，先別大注。")
        lines.append("樣本外穩定性再用 !validate <代號> 交叉確認。")
        await ctx.send("\n".join(lines))
    except Exception as e:
        log_error(f"!health 失敗: {e}")
        await ctx.send(f"❌ 體檢失敗: {str(e)}")


async def build_rank_text(n: int = 8):
    """產生 !rank 排行文字；資料不足回傳 None。供指令與排程推播共用。"""
    from quant.ranker import rank_universe
    n = max(3, min(n, 15))
    as_of, top, bottom = await asyncio.to_thread(rank_universe, n)
    if not top:
        return None
    def nm(sid):
        return get_stock_name_zh(f"{sid}.TW")
    lines = [f"📈 BMO 選股排行（{as_of.strftime('%m/%d')}，綜合動能+月營收YoY+法人）", "",
             f"🟢 做多候選 Top{len(top)}："]
    for i, r in enumerate(top, 1):
        lines.append(f"{i}. {sid_disp(r['sid'])} {nm(r['sid'])}｜分{r['score']}｜動能{r['mom']}% 營收YoY{r['revyoy']}% 法人佔量{r['inst']}%")
    lines.append("")
    lines.append(f"🔴 相對弱勢（避開）：")
    for r in bottom[:5]:
        lines.append(f"・{sid_disp(r['sid'])} {nm(r['sid'])}｜分{r['score']}")
    lines.append("")
    lines.append("註：此為相對強弱排序(非保證漲跌)，回測IC正向但偏弱，僅供參考。")
    return "\n".join(lines)


@bot.command(name="rank", aliases=["排行", "選股"])
async def rank_stocks(ctx, n: int = 8):
    """每日橫截面選股排行：綜合動能+月營收+法人，做多前段、避開後段。"""
    try:
        await ctx.defer()
        text = await build_rank_text(n)
        if text is None:
            await ctx.send("❌ 排行資料不足（panel 尚未建好或因子缺值）")
            return
        await send_long(ctx, text)
    except Exception as e:
        log_error(f"!rank 失敗: {e}")
        await ctx.send(f"❌ 排行產生失敗: {str(e)}")


def sid_disp(sid):
    return str(sid)


@bot.command(name="bind")
async def bind_channel(ctx):
    bot.target_channel_id = ctx.channel.id
    await ctx.send("✅ 綁定成功")

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if token: bot.run(token)
