# Stock Quant 架构设计方案
## 多平台与订阅等级差异化方案 | V1.0

---

## 目录
1. [需求分析](#需求分析)
2. [订阅等级差异化](#订阅等级差异化)
3. [多平台架构](#多平台架构-line集成)
4. [数据同步策略](#数据同步策略)
5. [实现路线图](#实现路线图)

---

## 需求分析

### 需求1: 基于预测模型准确度的订阅等级差异化

**背景**:
用户希望不同付费等级的用户能够使用不同性能的预测模型，以体现订阅价值差异。

**具体需求**:
```
┌─────────┬──────────────────┬──────────────┐
│ 等级    │ 推荐模型         │ 特性         │
├─────────┼──────────────────┼──────────────┤
│ Free    │ 基础混合模型     │ 5指标加权    │
│ Beta    │ 自适应权重模型   │ 动态权重调整 │
│ Premium │ 集成模型 (多选)  │ 3+种模型可选 │
│ Pro     │ Premium增强版    │ 模型融合     │
└─────────┴──────────────────┴──────────────┘
```

### 需求2: Multi-Platform架构（Discord为主，Line可选）

**背景**:
未来可能扩展到Line等其他平台。需要统一的架构支持多平台。

**需求**:
- Discord: 主要平台 (现状)
- Line: 辅助平台 (计划中)
- Telegram: 可选 (未来)
- **关键**: 跨平台数据同步实时一致

---

## 订阅等级差异化

### 1. 数据结构扩展

#### 1.1 用户信息扩展 (user_quota.json)

**现有结构**:
```json
{
  "date": "2026-02-01",
  "users": {
    "123456": 1
  },
  "limits": {
    "123456": 5
  }
}
```

**扩展结构 (V11.3+)**:
```json
{
  "date": "2026-02-01",
  "users": {
    "123456": {
      "used_today": 1,
      "tier": "free",
      "subscription": {
        "level": "free",
        "start_date": "2026-01-01",
        "end_date": null,
        "monthly_fee": 0
      },
      "model_preference": {
        "primary": "hybrid",
        "fallback": "hybrid"
      },
      "model_performance": {
        "hybrid": {"win_rate": 0.65, "total": 20},
        "adaptive": {"win_rate": 0.68, "total": 15}
      }
    }
  },
  "limits": {
    "123456": 5
  },
  "model_accuracy": {
    "hybrid": {"avg_roi": 12.5, "win_rate": 0.65},
    "adaptive": {"avg_roi": 15.2, "win_rate": 0.68},
    "ensemble": {"avg_roi": 18.7, "win_rate": 0.72}
  }
}
```

#### 1.2 模型性能追踪

**新表: data/model_performance.json**:
```json
{
  "generated_at": "2026-02-01T14:30:00",
  "models": {
    "hybrid": {
      "description": "基础混合 (5指标)",
      "accuracy": 0.65,
      "win_rate": 0.65,
      "avg_roi": 12.5,
      "sharpe": 1.2,
      "total_predictions": 523,
      "winning_predictions": 340,
      "tier_access": ["free", "beta", "premium", "pro"]
    },
    "adaptive": {
      "description": "自适应权重 (动态调整)",
      "accuracy": 0.68,
      "win_rate": 0.68,
      "avg_roi": 15.2,
      "sharpe": 1.45,
      "total_predictions": 287,
      "winning_predictions": 195,
      "tier_access": ["beta", "premium", "pro"]
    },
    "ensemble": {
      "description": "集成模型 (多模型融合)",
      "accuracy": 0.72,
      "win_rate": 0.72,
      "avg_roi": 18.7,
      "sharpe": 1.8,
      "total_predictions": 156,
      "winning_predictions": 112,
      "tier_access": ["premium", "pro"]
    },
    "lstm": {
      "description": "深度学习 (长短期记忆)",
      "accuracy": 0.75,
      "win_rate": 0.75,
      "avg_roi": 22.3,
      "sharpe": 2.1,
      "total_predictions": 89,
      "winning_predictions": 67,
      "tier_access": ["pro"]
    }
  },
  "tier_mapping": {
    "free": ["hybrid"],
    "beta": ["hybrid", "adaptive"],
    "premium": ["adaptive", "ensemble"],
    "pro": ["adaptive", "ensemble", "lstm"]
  }
}
```

### 2. 实现架构

#### 2.1 模型选择器 (新模块)

**文件**: `strategies/model_selector.py` (150行)

```python
class ModelSelector:
    """根据用户等级和偏好选择最优模型"""
    
    def __init__(self):
        self.model_performance = self.load_model_performance()
        self.tier_models = self.model_performance['tier_mapping']
    
    def get_available_models(self, user_tier):
        """获取用户可用的模型列表"""
        return self.tier_models.get(user_tier, ['hybrid'])
    
    def select_best_model(self, user_tier, use_case='default'):
        """
        根据等级和场景选择最优模型
        
        use_case:
          - 'default': 使用最高性能模型
          - 'stable': 使用稳定性最好的模型
          - 'fast': 使用最快的模型
          - 'user_preference': 使用用户选择的模型
        """
        available = self.get_available_models(user_tier)
        
        if use_case == 'default':
            # 按性能排序，返回最佳
            ranked = sorted(
                available,
                key=lambda m: self.model_performance['models'][m]['win_rate'],
                reverse=True
            )
            return ranked[0]
        
        elif use_case == 'stable':
            # 按Sharpe比率排序
            ranked = sorted(
                available,
                key=lambda m: self.model_performance['models'][m]['sharpe'],
                reverse=True
            )
            return ranked[0]
        
        else:
            # 首选模型
            return available[0] if available else 'hybrid'
    
    def get_model_recommendation(self, user_tier, historical_data):
        """
        给出模型推荐，包含性能对比
        
        返回:
        {
          'recommended': 'adaptive',
          'reason': '自适应权重模型性能最佳',
          'accuracy': 0.68,
          'performance_vs_baseline': '+5.3%',
          'available_models': ['hybrid', 'adaptive'],
          'model_comparison': [
            {
              'model': 'hybrid',
              'win_rate': 0.65,
              'avg_roi': 12.5
            },
            {
              'model': 'adaptive',
              'win_rate': 0.68,
              'avg_roi': 15.2
            }
          ]
        }
        """
        available = self.get_available_models(user_tier)
        
        # 获取性能数据
        models_data = []
        for model in available:
            models_data.append({
                'model': model,
                'win_rate': self.model_performance['models'][model]['win_rate'],
                'avg_roi': self.model_performance['models'][model]['avg_roi']
            })
        
        # 排序找最佳
        best = max(models_data, key=lambda x: x['win_rate'])
        
        return {
            'recommended': best['model'],
            'reason': f"{best['model']}策略性能最佳 (胜率{best['win_rate']:.1%})",
            'accuracy': best['win_rate'],
            'available_models': available,
            'model_comparison': models_data
        }


class PredictionWithModelTracking:
    """预测时跟踪模型性能"""
    
    def predict_with_tracking(self, df, user_id, user_tier):
        """
        执行预测并追踪模型性能
        """
        selector = ModelSelector()
        model_name = selector.select_best_model(user_tier)
        
        # 加载对应模型
        predictor = create_predictor(model_name)
        result = predictor.predict(df)
        
        # 记录预测 (用于后续性能评估)
        self.track_prediction(user_id, model_name, result)
        
        return {
            **result,
            'model_used': model_name,
            'model_tier_access': selector.get_available_models(user_tier)
        }
    
    def track_prediction(self, user_id, model_name, prediction_result):
        """记录预测以供性能追踪"""
        # 实现细节: 追加到performance_log.json
        pass
```

#### 2.2 Discord集成

**discord_runner.py中的新命令**:

```python
@bot.command(name='models', aliases=['model_info'])
async def show_available_models(ctx):
    """显示用户可用的模型及性能对比"""
    
    # 获取用户等级
    user_roles = [role.name for role in ctx.author.roles]
    tier = get_user_tier(user_roles)
    
    # 获取模型选择器建议
    selector = ModelSelector()
    recommendation = selector.get_model_recommendation(tier, None)
    
    # 构建Embed
    embed = discord.Embed(
        title=f"📊 您的模型選項 ({tier.upper()}用戶)",
        description=f"推薦: **{recommendation['recommended']}** ({recommendation['reason']})",
        color=discord.Color.blue()
    )
    
    # 模型对比
    comparison_text = ""
    for model in recommendation['model_comparison']:
        comparison_text += f"• **{model['model']}**\n"
        comparison_text += f"  勝率: {model['win_rate']:.1%} | ROI: {model['avg_roi']:.1f}%\n"
    
    embed.add_field(
        name="模型性能對比",
        value=comparison_text,
        inline=False
    )
    
    await ctx.send(embed=embed)


@bot.command(name='analyze_with_model')
async def analyze_with_specific_model(ctx, ticker, model='default'):
    """使用指定模型进行分析"""
    
    # 验证模型可用性
    user_roles = [role.name for role in ctx.author.roles]
    tier = get_user_tier(user_roles)
    
    selector = ModelSelector()
    available = selector.get_available_models(tier)
    
    if model != 'default' and model not in available:
        await ctx.send(f"❌ 此模型不在您的可用模型中 (可用: {available})")
        return
    
    # 执行分析
    # ... 省略现有代码 ...
    # 使用选定的model进行预测
```

### 3. 等级定价方案

```
┌──────────────────────────────────────────────┐
│ 订阅方案对比                                 │
├─────────┬──────┬──────────┬─────────────────┤
│ 等级    │ 价格 │ 配额/天  │ 可用模型        │
├─────────┼──────┼──────────┼─────────────────┤
│ Free    │ 免费 │ 5        │ • Hybrid        │
│ Beta    │ NT$99│ 50       │ • Hybrid        │
│         │  /mo │          │ • Adaptive      │
├─────────┼──────┼──────────┼─────────────────┤
│Premium  │NT$499│ 100      │ • Adaptive      │
│         │  /mo │ + 无限   │ • Ensemble      │
│         │      │ 回测     │ • Custom        │
├─────────┼──────┼──────────┼─────────────────┤
│ Pro     │NT$999│ 不限     │ • LSTM          │
│         │  /mo │ + VIP    │ • Ensemble      │
│         │      │ 支持     │ • 私有模型训练  │
└─────────┴──────┴──────────┴─────────────────┘

性能差异:
Free:     胜率 65%   ROI 12.5%   Sharpe 1.2
Beta:     胜率 68%   ROI 15.2%   Sharpe 1.45
Premium:  胜率 72%   ROI 18.7%   Sharpe 1.8
Pro:      胜率 75%   ROI 22.3%   Sharpe 2.1
```

---

## 多平台架构 (Line集成)

### 1. 架构设计

#### 1.1 平台无关的核心层

**设计原则**:
```
┌────────────────────────────────────────┐
│      业务逻辑层 (平台无关)            │
│  - 分析引擎                            │
│  - 模型预测                            │
│  - 数据持久化                          │
└────────────────────────────────────────┘
  ↓ ↓ ↓
┌─────────────────────┐  ┌──────────────┐  ┌─────────────┐
│ Discord Adapter     │  │ Line Adapter │  │ Telegram    │
│ (discord.py)        │  │ (line-bot-sdk)  │ Adapter     │
└─────────────────────┘  └──────────────┘  └─────────────┘
```

#### 1.2 适配器模式

**新文件**: `adapters/` 目录

```
adapters/
├── __init__.py
├── base_adapter.py         # 基础适配器接口
├── discord_adapter.py      # Discord实现
├── line_adapter.py         # Line实现 (V11.3+)
└── telegram_adapter.py     # Telegram实现 (未来)
```

**base_adapter.py**:
```python
from abc import ABC, abstractmethod
from typing import Dict, Any, List

class BaseAdapter(ABC):
    """平台适配器基类"""
    
    @abstractmethod
    async def send_message(self, user_id: str, message: str) -> bool:
        """发送文本消息"""
        pass
    
    @abstractmethod
    async def send_embed(self, user_id: str, embed_data: Dict) -> bool:
        """发送富文本消息 (Embed/RichMenu)"""
        pass
    
    @abstractmethod
    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """获取用户信息"""
        pass
    
    @abstractmethod
    async def set_user_tier(self, user_id: str, tier: str) -> bool:
        """设置用户等级"""
        pass
    
    def normalize_user_id(self, platform_id: str) -> str:
        """将平台特定ID规范化为统一格式"""
        pass
    
    def normalize_message(self, platform_message: Any) -> Dict:
        """将平台特定消息规范化"""
        pass


class AnalysisRequest(BaseAdapter):
    """分析请求对象 (平台无关)"""
    
    def __init__(self):
        self.user_id = None          # 规范化的用户ID
        self.platform = None         # 'discord' / 'line' / 'telegram'
        self.command = None          # '!analyze' / '/analyze'
        self.parameters = {}         # 参数字典
        self.timestamp = None


class AnalysisResponse(BaseAdapter):
    """分析响应对象 (平台无关)"""
    
    def __init__(self):
        self.status = 'pending'      # pending / success / error
        self.content = {}            # 通用内容
        self.embeds = []             # 富文本消息列表
        self.files = []              # 附件列表 (图表等)


class PlatformManager:
    """平台管理器 - 统一处理多平台"""
    
    def __init__(self):
        self.adapters: Dict[str, BaseAdapter] = {}
        self._register_adapters()
    
    def _register_adapters(self):
        """注册所有可用适配器"""
        from adapters.discord_adapter import DiscordAdapter
        from adapters.line_adapter import LineAdapter
        
        self.adapters['discord'] = DiscordAdapter()
        self.adapters['line'] = LineAdapter()
    
    async def process_request(self, request: AnalysisRequest) -> AnalysisResponse:
        """处理跨平台请求"""
        
        adapter = self.adapters.get(request.platform)
        if not adapter:
            raise ValueError(f"未知平台: {request.platform}")
        
        # 执行通用业务逻辑
        response = await self._execute_analysis(request)
        
        # 适配到目标平台格式
        await adapter.send_response(request.user_id, response)
        
        return response
    
    async def _execute_analysis(self, request: AnalysisRequest) -> AnalysisResponse:
        """执行分析 (平台无关)"""
        # 这里是核心业务逻辑
        pass
```

### 2. Line适配器实现 (V11.3+)

**文件**: `adapters/line_adapter.py` (200行)

```python
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexMessage, BubbleContainer
)
import json

class LineAdapter(BaseAdapter):
    """Line平台适配器"""
    
    def __init__(self):
        self.line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
        self.handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
    
    async def send_message(self, user_id: str, message: str) -> bool:
        """发送文本消息到Line"""
        try:
            self.line_bot_api.push_message(
                user_id,
                TextSendMessage(text=message)
            )
            return True
        except Exception as e:
            logger.error(f"Line消息发送失败: {e}")
            return False
    
    async def send_embed(self, user_id: str, embed_data: Dict) -> bool:
        """发送富文本消息 (Flex Message)"""
        try:
            flex_message = self._convert_embed_to_flex(embed_data)
            self.line_bot_api.push_message(
                user_id,
                FlexMessage(alt_text=embed_data['title'], contents=flex_message)
            )
            return True
        except Exception as e:
            logger.error(f"Line Flex消息发送失败: {e}")
            return False
    
    def _convert_embed_to_flex(self, embed_data: Dict) -> Dict:
        """将Discord Embed转换为Line Flex Message格式"""
        
        bubble = {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": embed_data.get('title', ''),
                        "weight": "bold",
                        "size": "xxl",
                        "color": "#FFFFFF"
                    }
                ],
                "backgroundColor": "#0099FF"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": self._build_flex_fields(embed_data.get('fields', []))
            }
        }
        
        return bubble
    
    def _build_flex_fields(self, fields: List[Dict]) -> List[Dict]:
        """构建Flex字段"""
        contents = []
        
        for field in fields:
            contents.append({
                "type": "box",
                "layout": "vertical",
                "margin": "lg",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "text",
                        "text": field['name'],
                        "weight": "bold",
                        "size": "sm",
                        "color": "#0099FF"
                    },
                    {
                        "type": "text",
                        "text": field['value'],
                        "size": "xs",
                        "color": "#999999",
                        "wrap": True
                    }
                ]
            })
        
        return contents
    
    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """从Line获取用户信息"""
        try:
            profile = self.line_bot_api.get_profile(user_id)
            return {
                'user_id': user_id,
                'platform': 'line',
                'display_name': profile.display_name,
                'user_avatar_url': profile.user_id_picture_url,
                'status_message': profile.status_message
            }
        except Exception as e:
            logger.error(f"获取Line用户信息失败: {e}")
            return None
    
    async def set_user_tier(self, user_id: str, tier: str) -> bool:
        """设置用户等级 (通过Line Rich Menu)"""
        # Line实现: 根据tier显示不同的Rich Menu
        pass
```

### 3. 数据同步架构

#### 3.1 同步策略

**原则**: 
- 单一真实数据源 (主要为本地JSON)
- 各平台缓存本地数据
- 实时双向同步

**同步流程**:
```
Discord 更新              Line 更新
    ↓                        ↓
┌─────────────────────────────────────┐
│    Core Data Layer                  │
│  (data/*.json)                      │
└─────────────────────────────────────┘
    ↓                        ↓
Discord Cache            Line Cache
(实时同步)               (实时同步)
```

#### 3.2 实现架构

**新模块**: `utils/sync_manager.py` (200行)

```python
class DataSyncManager:
    """跨平台数据同步管理器"""
    
    def __init__(self):
        self.data_sources = {}  # 各平台的本地缓存
        self.last_sync = {}     # 上次同步时间
        self.is_syncing = False
    
    async def sync_quota_data(self):
        """同步用户配额数据"""
        
        # 读取主数据源
        master_data = self.load_master_quota()
        
        # 同时更新所有平台缓存
        tasks = [
            self.adapters['discord'].update_quota_cache(master_data),
            self.adapters['line'].update_quota_cache(master_data)
        ]
        
        await asyncio.gather(*tasks)
        
        self.last_sync['quota'] = datetime.now()
        logger.info("配额数据同步完成")
    
    async def sync_analytics_data(self):
        """同步分析数据 (热搜排行等)"""
        
        analytics = self.load_master_analytics()
        
        tasks = [
            self.adapters['discord'].update_analytics_cache(analytics),
            self.adapters['line'].update_analytics_cache(analytics)
        ]
        
        await asyncio.gather(*tasks)
        
        self.last_sync['analytics'] = datetime.now()
        logger.info("分析数据同步完成")
    
    async def sync_model_performance(self):
        """同步模型性能数据"""
        
        perf = self.load_master_model_performance()
        
        tasks = [
            self.adapters['discord'].update_model_cache(perf),
            self.adapters['line'].update_model_cache(perf)
        ]
        
        await asyncio.gather(*tasks)
    
    async def handle_user_action_discord(self, action: str, data: Dict):
        """处理Discord用户操作，同步到Line"""
        
        # 更新主数据源
        self.update_master_data(action, data)
        
        # 通知Line进行同步
        await self.adapters['line'].sync_action(action, data)
    
    async def handle_user_action_line(self, action: str, data: Dict):
        """处理Line用户操作，同步到Discord"""
        
        # 更新主数据源
        self.update_master_data(action, data)
        
        # 通知Discord进行同步
        await self.adapters['discord'].sync_action(action, data)
    
    async def start_continuous_sync(self):
        """启动持续同步任务"""
        
        while True:
            try:
                # 每5分钟同步一次
                await self.sync_quota_data()
                await self.sync_analytics_data()
                await self.sync_model_performance()
                
                await asyncio.sleep(300)  # 5分钟
                
            except Exception as e:
                logger.error(f"同步失败: {e}")
                await asyncio.sleep(60)  # 错误后60秒重试
```

---

## 实现路线图

### 第一阶段 (V11.2 - 现阶段) ✅
- ✅ 基础混合模型 (5指标)
- ✅ 自适应权重模型
- ✅ 用户分析系统
- ✅ 时期回测系统

### 第二阶段 (V11.3 - 1-2周)
- [ ] 模型选择器实现
- [ ] 模型性能追踪
- [ ] 订阅等级差异化 (Discord)
- [ ] 模型推荐系统

**工作量**: 40-50小时

### 第三阶段 (V12.0 - 2-3周)
- [ ] Line适配器开发
- [ ] 跨平台同步架构
- [ ] 统一用户管理系统
- [ ] 平台适配器通用框架

**工作量**: 60-80小时

### 第四阶段 (V12.1+ - 后续)
- [ ] LSTM模型集成
- [ ] XGBoost模型集成
- [ ] Prophet时间序列模型
- [ ] Telegram适配器
- [ ] 微信小程序适配

---

## 优先级建议

### 紧急 (立即开始)
1. ✅ 配额系统修复 (已完成)
2. ✅ 热搜排行系统 (已完成)
3. ✅ 时期回测系统 (已完成)
4. ✅ ML混合模型 (已完成)

### 高优先级 (V11.3, 1-2周)
1. 订阅等级差异化 (模型选择器)
2. 模型性能追踪系统
3. Discord中的模型推荐命令

### 中优先级 (V12.0, 2-3周)
1. Line平台适配
2. 跨平台数据同步

### 低优先级 (V12.1+)
1. 高级ML模型 (LSTM/XGBoost)
2. 其他平台支持

---

## 技术栈 (推荐)

### 后端框架
- **discord.py**: Discord集成 (现有)
- **line-bot-sdk**: Line Bot SDK (新增)
- **asyncio**: 异步编程 (现有)

### 数据存储
- **JSON**: 本地持久化 (现有)
- **Redis**: 分布式缓存 (可选, V12+)
- **MongoDB**: 历史数据存档 (可选, V12+)

### ML框架
- **talib-python**: 技术指标计算 (现有)
- **tensorflow/keras**: LSTM模型 (V12+)
- **xgboost**: 梯度提升 (V12+)
- **statsmodels**: 时间序列 (V12+)

---

## 成本分析

| 工作项 | 估算小时 | 难度 | 风险 |
|--------|---------|------|------|
| 模型选择器 | 12 | 中 | 低 |
| 性能追踪 | 8 | 低 | 低 |
| Discord集成 | 6 | 低 | 低 |
| Line适配器 | 20 | 中 | 中 |
| 数据同步 | 15 | 中 | 中 |
| **总计** | **61** | - | - |

**时间表** (假设全职):
- V11.3: 2-3周
- V12.0: 3-4周
- V12.1+: 持续迭代

---

**文档版本**: 1.0 | 发布日期: 2026-02-01 | 架构师: Dev Team
