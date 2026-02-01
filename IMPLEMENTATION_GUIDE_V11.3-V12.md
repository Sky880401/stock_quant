# 订阅等级差异化与多平台架构 - 实现指南
## Implementation Guide for V11.3 & V12.0

---

## 第一部分: 订阅等级差异化 (V11.3) - 2-3周

### 阶段1: 数据结构升级 (2-3天)

**Step 1.1: 扩展user_quota.json**

```python
# utils/quota_manager.py - 在 __init__ 中添加
def migrate_quota_v2():
    """从V11.2迁移到V11.3数据结构"""
    
    old_data = load_quota()
    
    if 'model_preference' not in old_data.get('users', {}).get(list(old_data.get('users', {}).keys())[0] if old_data.get('users') else {}, {}):
        # 需要迁移
        for user_id in old_data.get('users', {}):
            old_data['users'][user_id] = {
                'used_today': old_data['users'][user_id],
                'tier': 'free',  # 默认值
                'subscription': {
                    'level': 'free',
                    'start_date': datetime.now().isoformat(),
                    'end_date': None,
                    'monthly_fee': 0
                },
                'model_preference': {
                    'primary': 'hybrid',
                    'fallback': 'hybrid'
                }
            }
        
        save_quota(old_data)
```

**Step 1.2: 创建model_performance.json**

```bash
# data/model_performance.json - 初始内容
{
  "generated_at": "2026-02-01T00:00:00",
  "last_updated_by": "system",
  "update_frequency": "daily",
  "models": {
    "hybrid": {
      "description": "基础混合 (5指标MA/RSI/MACD/KD/BB)",
      "version": "1.0",
      "accuracy": 0.65,
      "win_rate": 0.65,
      "avg_roi": 12.5,
      "sharpe_ratio": 1.20,
      "total_predictions": 523,
      "winning_predictions": 340,
      "tier_access": ["free", "beta", "premium", "pro"],
      "performance_by_date": {}
    },
    "adaptive": {
      "description": "自适应权重 (基于ATR调整)",
      "version": "1.0",
      "accuracy": 0.68,
      "win_rate": 0.68,
      "avg_roi": 15.2,
      "sharpe_ratio": 1.45,
      "total_predictions": 287,
      "winning_predictions": 195,
      "tier_access": ["beta", "premium", "pro"],
      "performance_by_date": {}
    }
  },
  "tier_mapping": {
    "free": ["hybrid"],
    "beta": ["hybrid", "adaptive"],
    "premium": ["adaptive"],
    "pro": ["adaptive"]
  }
}
```

### 阶段2: 模型选择器 (4-5天)

**Step 2.1: 创建strategies/model_selector.py**

```python
# strategies/model_selector.py (150行)

from typing import Dict, List, Optional
from dataclasses import dataclass
import json

@dataclass
class ModelInfo:
    name: str
    accuracy: float
    win_rate: float
    avg_roi: float
    sharpe: float
    tier_access: List[str]
    description: str

class ModelSelector:
    def __init__(self):
        self.performance = self.load_performance()
    
    def load_performance(self) -> Dict:
        """从JSON加载模型性能数据"""
        with open('data/model_performance.json') as f:
            return json.load(f)
    
    def get_available_models(self, user_tier: str) -> List[str]:
        """获取用户可用模型列表"""
        mapping = self.performance['tier_mapping']
        return mapping.get(user_tier, ['hybrid'])
    
    def select_best_model(self, user_tier: str, user_preference: Optional[str] = None) -> str:
        """
        选择最优模型
        优先级:
        1. 用户偏好设置
        2. 用户等级可用的最高性能模型
        3. 降级到free tier模型
        """
        available = self.get_available_models(user_tier)
        
        if user_preference and user_preference in available:
            return user_preference
        
        # 按win_rate排序，返回最高性能的
        ranked = sorted(
            available,
            key=lambda m: self.performance['models'][m]['win_rate'],
            reverse=True
        )
        
        return ranked[0] if ranked else 'hybrid'
    
    def get_model_comparison(self, user_tier: str) -> Dict:
        """生成用户可用模型的性能对比"""
        available = self.get_available_models(user_tier)
        
        comparison = []
        for model in available:
            model_data = self.performance['models'][model]
            comparison.append({
                'name': model,
                'description': model_data['description'],
                'accuracy': model_data['accuracy'],
                'win_rate': model_data['win_rate'],
                'avg_roi': model_data['avg_roi'],
                'sharpe': model_data['sharpe_ratio']
            })
        
        # 按win_rate排序
        comparison.sort(key=lambda x: x['win_rate'], reverse=True)
        
        return {
            'tier': user_tier,
            'available_models': available,
            'comparison': comparison,
            'recommended': comparison[0]['name'] if comparison else 'hybrid'
        }
    
    def update_model_performance(self, model_name: str, prediction_result: Dict, actual_result: Dict):
        """
        更新模型性能数据
        
        prediction_result: {action, confidence, signal_strength, ...}
        actual_result: {win: True/False, roi: float, ...}
        """
        model_data = self.performance['models'][model_name]
        
        # 更新总计数
        model_data['total_predictions'] += 1
        
        if actual_result.get('win', False):
            model_data['winning_predictions'] += 1
        
        # 重新计算metrics
        model_data['win_rate'] = model_data['winning_predictions'] / model_data['total_predictions']
        
        # 保存更新
        self._save_performance()
    
    def _save_performance(self):
        """保存更新的性能数据"""
        with open('data/model_performance.json', 'w') as f:
            json.dump(self.performance, f, indent=2)


class PredictionTracker:
    """预测跟踪 - 记录模型预测结果用于性能评估"""
    
    def __init__(self):
        self.log_file = 'data/prediction_log.json'
    
    def log_prediction(self, user_id: str, model_name: str, prediction: Dict, timestamp: str):
        """记录预测"""
        log_entry = {
            'timestamp': timestamp,
            'user_id': user_id,
            'model': model_name,
            'ticker': prediction.get('ticker'),
            'action': prediction.get('action'),
            'confidence': prediction.get('confidence'),
            'signal_strength': prediction.get('signal_strength')
        }
        
        # 追加到日志
        logs = self._load_logs()
        logs.append(log_entry)
        self._save_logs(logs)
    
    def log_result(self, prediction_id: str, actual_result: Dict):
        """记录预测结果 (事后验证)"""
        # 匹配预测日志并更新结果
        pass
    
    def get_model_accuracy(self, model_name: str, days: int = 30) -> float:
        """计算模型在过去N天的准确度"""
        # 实现细节
        pass
```

**Step 2.2: 集成到main.py**

```python
# main.py - 在 calculate_final_decision() 中

from strategies.model_selector import ModelSelector, PredictionTracker

class AnalysisEngine:
    def __init__(self):
        self.model_selector = ModelSelector()
        self.tracker = PredictionTracker()
    
    def calculate_final_decision(self, df, ticker, user_id, user_tier):
        """
        改进的决策逻辑，支持模型选择
        """
        
        # 1. 选择最优模型
        model_name = self.model_selector.select_best_model(user_tier)
        
        # 2. 执行预测
        predictor = create_predictor(model_name)
        prediction = predictor.predict(df)
        
        # 3. 记录预测
        self.tracker.log_prediction(
            user_id=user_id,
            model_name=model_name,
            prediction=prediction,
            timestamp=datetime.now().isoformat()
        )
        
        # 4. 返回结果（包含使用的模型信息）
        return {
            **prediction,
            'model_used': model_name,
            'available_models': self.model_selector.get_available_models(user_tier)
        }
```

### 阶段3: Discord命令 (3-4天)

**Step 3.1: 添加新命令到discord_runner.py**

```python
# discord_runner.py - 添加新命令

@bot.command(name='models', aliases=['model_info', 'available_models'])
async def show_models(ctx):
    """显示用户可用的模型"""
    
    user_tier = get_user_tier([role.name for role in ctx.author.roles])
    
    selector = ModelSelector()
    comparison = selector.get_model_comparison(user_tier)
    
    embed = discord.Embed(
        title=f"📊 您的可用模型 ({user_tier.upper()})",
        description=f"推薦模型: **{comparison['recommended']}**",
        color=discord.Color.blue()
    )
    
    # 添加模型对比
    for model_info in comparison['comparison']:
        embed.add_field(
            name=f"• {model_info['name']}",
            value=f"準確度: {model_info['accuracy']:.1%} | ROI: {model_info['avg_roi']:.1f}% | Sharpe: {model_info['sharpe']:.2f}",
            inline=False
        )
    
    embed.set_footer(text="下次分析時將自動使用推薦模型")
    
    await ctx.send(embed=embed)


@bot.command(name='set_model')
async def set_preferred_model(ctx, model_name: str):
    """设置用户偏好模型"""
    
    user_tier = get_user_tier([role.name for role in ctx.author.roles])
    selector = ModelSelector()
    
    available = selector.get_available_models(user_tier)
    
    if model_name not in available:
        await ctx.send(f"❌ 此模型不在您的可用列表中\n可用模型: {', '.join(available)}")
        return
    
    # 更新用户偏好
    update_user_model_preference(ctx.author.id, model_name)
    
    await ctx.send(f"✅ 已設定偏好模型: **{model_name}**\n下次分析時將使用此模型")


@bot.command(name='model_accuracy')
async def show_model_stats(ctx):
    """显示各模型性能统计"""
    
    user_tier = get_user_tier([role.name for role in ctx.author.roles])
    
    selector = ModelSelector()
    comparison = selector.get_model_comparison(user_tier)
    
    embed = discord.Embed(
        title="🎯 模型性能統計",
        color=discord.Color.green()
    )
    
    for model_info in comparison['comparison']:
        embed.add_field(
            name=model_info['name'],
            value=f"• 準確度: {model_info['accuracy']:.1%}\n"
                  f"• 勝率: {model_info['win_rate']:.1%}\n"
                  f"• 平均ROI: {model_info['avg_roi']:.2f}%\n"
                  f"• Sharpe比率: {model_info['sharpe']:.2f}",
            inline=True
        )
    
    await ctx.send(embed=embed)
```

---

## 第二部分: 多平台架构 (V12.0) - 3-4周

### 阶段1: 基础适配器框架 (5-6天)

**Step 1.1: 创建adapters/base_adapter.py**

```python
# adapters/base_adapter.py (100行)

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import json

@dataclass
class Message:
    """规范化的消息对象"""
    user_id: str
    platform: str  # 'discord' | 'line' | 'telegram'
    command: str
    parameters: Dict[str, Any]
    timestamp: str


class BaseAdapter(ABC):
    """平台适配器基类"""
    
    @abstractmethod
    async def send_text(self, user_id: str, message: str) -> bool:
        """发送文本消息"""
        pass
    
    @abstractmethod
    async def send_embed(self, user_id: str, embed_data: Dict) -> bool:
        """发送富文本消息"""
        pass
    
    @abstractmethod
    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """获取用户信息"""
        pass
    
    @abstractmethod
    async def on_command(self, message: Message):
        """处理命令"""
        pass


class DiscordAdapter(BaseAdapter):
    """Discord适配器 (现有机制包装)"""
    
    async def send_text(self, user_id: str, message: str) -> bool:
        try:
            user = await bot.fetch_user(int(user_id))
            await user.send(message)
            return True
        except:
            return False
    
    async def send_embed(self, user_id: str, embed_data: Dict) -> bool:
        try:
            embed = self._dict_to_embed(embed_data)
            user = await bot.fetch_user(int(user_id))
            await user.send(embed=embed)
            return True
        except:
            return False
    
    def _dict_to_embed(self, data: Dict) -> discord.Embed:
        """将字典转换为Discord Embed"""
        embed = discord.Embed(
            title=data.get('title'),
            description=data.get('description'),
            color=data.get('color', 0x0099FF)
        )
        
        for field in data.get('fields', []):
            embed.add_field(
                name=field['name'],
                value=field['value'],
                inline=field.get('inline', False)
            )
        
        return embed


class LineAdapter(BaseAdapter):
    """Line适配器 (V12.0实现)"""
    
    def __init__(self):
        self.line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
    
    async def send_text(self, user_id: str, message: str) -> bool:
        try:
            self.line_bot_api.push_message(
                user_id,
                TextSendMessage(text=message)
            )
            return True
        except Exception as e:
            logger.error(f"Line send_text failed: {e}")
            return False
    
    async def send_embed(self, user_id: str, embed_data: Dict) -> bool:
        try:
            flex_msg = self._dict_to_flex(embed_data)
            self.line_bot_api.push_message(
                user_id,
                FlexMessage(alt_text=embed_data.get('title', 'Message'), contents=flex_msg)
            )
            return True
        except Exception as e:
            logger.error(f"Line send_embed failed: {e}")
            return False
    
    def _dict_to_flex(self, data: Dict) -> Dict:
        """将字典转换为Line Flex Message"""
        bubble = {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#0099FF",
                "contents": [{
                    "type": "text",
                    "text": data.get('title', ''),
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "size": "xxl"
                }]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": field['name'],
                        "weight": "bold",
                        "size": "sm",
                        "color": "#0099FF",
                        "margin": "lg"
                    },
                    {
                        "type": "text",
                        "text": field['value'],
                        "size": "xs",
                        "color": "#999999",
                        "wrap": True,
                        "margin": "sm"
                    }
                ] for field in data.get('fields', [])
            }
        }
        
        return bubble


class PlatformManager:
    """跨平台管理器"""
    
    def __init__(self):
        self.adapters: Dict[str, BaseAdapter] = {
            'discord': DiscordAdapter(),
            'line': LineAdapter()
        }
    
    async def broadcast_announcement(self, message: str, embeds: List[Dict] = None):
        """广播公告到所有平台"""
        
        tasks = []
        
        # Discord广播
        for user_id in get_all_discord_users():
            if embeds:
                for embed in embeds:
                    tasks.append(self.adapters['discord'].send_embed(user_id, embed))
            else:
                tasks.append(self.adapters['discord'].send_text(user_id, message))
        
        # Line广播
        for user_id in get_all_line_users():
            if embeds:
                for embed in embeds:
                    tasks.append(self.adapters['line'].send_embed(user_id, embed))
            else:
                tasks.append(self.adapters['line'].send_text(user_id, message))
        
        results = await asyncio.gather(*tasks)
        return sum(results)  # 返回成功发送数
```

### 阶段2: 数据同步 (5-6天)

**Step 2.1: 创建utils/sync_manager.py**

```python
# utils/sync_manager.py (150行)

import asyncio
from datetime import datetime
import json

class SyncManager:
    """跨平台数据同步管理"""
    
    def __init__(self, platform_manager):
        self.pm = platform_manager
        self.last_sync = {}
    
    async def sync_quota_data(self):
        """同步配额数据"""
        
        quota = load_quota()
        
        # 同时更新两个平台的缓存
        tasks = [
            self._update_cache('discord', 'quota', quota),
            self._update_cache('line', 'quota', quota)
        ]
        
        await asyncio.gather(*tasks)
        self.last_sync['quota'] = datetime.now()
        logger.info("✓ Quota data synced to all platforms")
    
    async def sync_analytics(self):
        """同步分析数据"""
        
        analytics = export_analytics_json()
        
        tasks = [
            self._update_cache('discord', 'analytics', analytics),
            self._update_cache('line', 'analytics', analytics)
        ]
        
        await asyncio.gather(*tasks)
        self.last_sync['analytics'] = datetime.now()
    
    async def _update_cache(self, platform: str, cache_type: str, data: Any):
        """更新平台缓存"""
        cache_file = f"cache/{platform}_{cache_type}_cache.json"
        
        os.makedirs("cache", exist_ok=True)
        with open(cache_file, 'w') as f:
            json.dump(data, f)
    
    async def start_continuous_sync(self, interval: int = 300):
        """启动连续同步 (每5分钟)"""
        
        while True:
            try:
                await self.sync_quota_data()
                await self.sync_analytics()
                # 可以添加更多同步任务
                
                await asyncio.sleep(interval)
                
            except Exception as e:
                logger.error(f"Sync failed: {e}")
                await asyncio.sleep(60)
```

### 阶段3: Line Bot集成 (7-8天)

**Step 3.1: 创建line_runner.py**

```python
# line_runner.py (200行)

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from adapters.line_adapter import LineAdapter
from strategies.model_selector import ModelSelector

app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

adapter = LineAdapter()
selector = ModelSelector()


@app.route("/callback", methods=['POST'])
def callback():
    """Line Webhook回调"""
    
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    
    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """处理Line消息"""
    
    user_id = event.source.user_id
    text = event.message.text
    
    # 解析命令
    if text.startswith('/'):
        command = text.split()[0][1:]  # 移除/
        params = text.split()[1:] if len(text.split()) > 1 else []
        
        if command == 'analyze' and params:
            ticker = params[0]
            # 执行分析 (复用Discord逻辑)
            handle_analyze(user_id, ticker)
        
        elif command == 'hotlist':
            handle_hotlist(user_id)
        
        elif command == 'models':
            handle_models(user_id)
        
        # ... 其他命令


def handle_analyze(user_id, ticker):
    """处理分析请求"""
    
    # 获取用户信息
    user_tier = get_line_user_tier(user_id)
    
    # 选择模型
    model_name = selector.select_best_model(user_tier)
    
    # 执行分析...
    
    # 发送结果
    adapter.send_text(user_id, f"分析 {ticker} 中...")


def handle_hotlist(user_id):
    """处理热搜请求"""
    
    from utils.user_analytics import create_ranking_embed
    
    embeds = create_ranking_embed()
    
    for embed in embeds:
        adapter.send_embed(user_id, embed)


if __name__ == '__main__':
    app.run(port=5000)
```

---

## 实现优先级

### Week 1: 基础模型选择器
- [ ] 数据结构升级
- [ ] ModelSelector类实现
- [ ] Discord命令集成
- 预期: 30-40小时

### Week 2-3: 多平台基础设施
- [ ] BaseAdapter实现
- [ ] Line适配器开发
- [ ] 数据同步框架
- 预期: 40-50小时

### Week 4+: 集成与优化
- [ ] 端到端测试
- [ ] 性能优化
- [ ] 文档完善
- 预期: 20-30小时

---

**更新日期**: 2026-02-01 | **版本**: 1.0
