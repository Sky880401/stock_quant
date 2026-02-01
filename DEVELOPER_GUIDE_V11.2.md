# Stock Quant 开发者手册 V11.2
## 2026年2月1日更新

---

## 📖 目录
1. [系统概述](#系统概述)
2. [Discord命令参考](#discord命令参考)
3. [新增功能演示](#新增功能演示)
4. [功能验证清单](#功能验证清单)
5. [故障排查指南](#故障排查指南)
6. [开发环境设置](#开发环境设置)

---

## 系统概述

### 版本信息
- **当前版本**: V11.2
- **上次更新**: 2026-02-01
- **主要改动**: 
  - 配额系统bug修复
  - 用户热搜排行系统
  - 时间段特定回测分析
  - 混合机器学习预测模型

### 核心组件
```
stock_quant/
├── main.py                    # 主分析引擎
├── discord_runner.py          # Discord机器人
├── optimizer_runner.py        # 回测优化引擎
│
├── strategies/
│   ├── indicators/           # 技术指标策略
│   ├── price_action/        # 价格行动策略
│   └── ml_models/           # 机器学习模型 ← 【NEW】
│       ├── __init__.py
│       └── hybrid_predictor.py
│
├── utils/
│   ├── quota_manager.py      # 配额管理 ← 【修复】
│   ├── user_analytics.py     # 用户分析 ← 【NEW】
│   ├── period_backtest.py    # 时期回测 ← 【NEW】
│   ├── risk_budget.py        # 风险预算
│   ├── history_recorder.py   # 历史记录
│   └── ...其他工具
│
└── data/
    ├── user_query_history.csv    # 用户查询记录
    ├── user_quota.json           # 用户配额 ← 【修复结构】
    └── period_backtest_results.json  # 时期分析结果 ← 【NEW】
```

---

## Discord命令参考

### 🔍 查询类命令

#### 1. **!analyze** (别名: !a)
**用途**: 分析单只股票

**语法**:
```
!analyze <ticker>
```

**参数**:
- `ticker`: 股票代码或名称
  - 数字代码: `2330` → 自动识别为 `2330.TW` 或 `2330.TWO`
  - 完整代码: `2330.TW`, `3141.TWO`
  - 股票名称: `台積電`, `鴻海`
  - 英文代码: `TSMC`, `LRCX`

**示例**:
```
!a 2330
!analyze 台積電
!a TSMC
```

**预期产出**:
1. 确认对话框
   ```
   🧐 您是想查詢 台積電 (2330.TW) 嗎？
   (今日剩餘: 5 次)
   [✅ 確認分析] [❌ 取消]
   ```

2. 分析报告 (30-60秒后)
   ```
   📊 BMO 深度診斷: 台積電 | 現價: 580.00
   
   【AI深度分析报告】
   ✓ 行動: BUY
   ✓ 信心度: 85%
   ✓ 目標價: 600-620
   ✓ 風險提示: 周線轉弱需注意
   ...
   ```

3. 附加技术图表 (PNG图像)

**配额消耗**:
- Free用户: 1次/天 (5次配额)
- Beta用户: 1次/天 (50次配额)
- Premium用户: 1次/天 (100次配额)
- Admin用户: 无限制

---

#### 2. **!hotlist** (别名: !hotrank, !rank)
**用途**: 显示每日热搜排行榜

**语法**:
```
!hotlist
```

**参数**: 无

**示例**:
```
!hotlist
!hotrank
!rank
```

**预期产出**:
```
📊 BMO 每日熱搜排行
─────────────────────

🔥 熱搜股票 TOP 10:
🥇 台積電 (2330.TW)
   查詢: 11 次 | 成功率: 100.0%

🥈 華新 (1605.TW)
   查詢: 5 次 | 成功率: 100.0%

...

👥 活躍用戶 TOP 10:
🔥 skychen.
   查詢: 62 次 | 推薦成功率: 86.7%

⭐ he_sunny
   查詢: 9 次 | 推薦成功率: 88.9%

...

🎯 最佳策略排行:
1. AVOID / WAIT - ROI 565.84% | 成功3次
2. BUY (Speculative) - ROI 200.45% | 成功4次
...
```

**配额消耗**: 无

---

#### 3. **!period** (别名: !backtest_period, !bp)
**用途**: 查询特定时间段的回测分析结果

**语法**:
```
!period [strategy_name]
```

**参数**:
- `strategy_name` (可选): 策略名称
  - 省略时: 显示可用策略列表
  - 指定时: 显示该策略的分析结果

**示例**:
```
!period                          # 显示可用列表
!backtest_period TrendStrategy   # 查看趋势策略分析
!bp RSIStrategy
```

**预期产出**:

无参数时:
```
📊 可用的策略分析
共 3 個策略

1. `TrendStrategy`
2. `RSIStrategy`
3. `MACDStrategy`

使用 !period <strategy_name> 查看詳細分析
```

有参数时:
```
📈 TrendStrategy 時間段分析
分析時間: 2026-02-01 14:30:25

📊 統計摘要
平均ROI: 12.45%
平均勝率: 68.3%
ROI穩定性(標準差): 4.23
最佳時期: 2025-Q2
最差時期: 2025-Q4

時期表現:
• 2025-Full: ROI 12.45% | 勝率 68.3% | 交易數 23
• 2025-Q1: ROI 15.2% | 勝率 71.4% | 交易數 5
• 2025-Q2: ROI 18.9% | 勝率 75.0% | 交易數 6
• 2025-Q3: ROI 8.3% | 勝率 62.5% | 交易數 5
• 2025-Q4: ROI 5.1% | 勝率 55.0% | 交易數 7
```

**配额消耗**: 无

---

#### 4. **!gift**
**用途**: 为用户增加查询配额 (管理员专用)

**语法**:
```
!gift @user_name <amount>
```

**参数**:
- `user_name`: 目标用户 (需要@提及)
- `amount`: 增加的次数 (正整数)

**权限**: 仅管理员可用

**示例**:
```
!gift @skychen. 20
!gift @he_sunny 10
```

**预期产出**:
```
🎁 已為 skychen. 增加 20 次額度！
現在總額度: 25 次/天
```

**说明**:
- 增加的额度会**持久化**保存
- 每天自动重置使用次数，但保留自定义上限
- 例: 用户原限5次，gift 20后，上限变为25次

---

#### 5. **!bind**
**用途**: 绑定公告频道 (管理员专用)

**语法**:
```
!bind
```

**权限**: 仅管理员可用

**示例**:
```
!bind
```

**预期产出**:
```
✅ 綁定成功
```

**说明**:
- 在目标频道执行此命令
- 系统会在该频道发送每日定时公告

---

## 新增功能演示

### 功能1: 配额管理修复 ✅

**问题**: 使用`!gift`后，用户显示的配额仍为旧值

**修复内容**:
```python
# utils/quota_manager.py 中的改动
- 原有结构: {"date": "xxx", "users": {...}}
+ 新结构:   {"date": "xxx", "users": {...}, "limits": {...}}

# 使用 admin_add_quota() 时
- 旧逻辑: max(0, used - amount)  ❌
+ 新逻辑: current_limit + amount  ✓
```

**验证方法**:
```
1. 执行: !gift @test_user 20
2. 预期: 提示新上限为 25
3. 验证: !analyze 后显示 (24/25) 而不是 (4/5)
```

---

### 功能2: 用户热搜排行系统 ✅

**模块**: `utils/user_analytics.py`

**功能**:
- 从 CSV 加载 71 条用户查询记录
- 按用户/股票/策略维度聚合统计
- 计算热搜排行、用户排行、最佳策略
- 生成 3 个美化的 Discord Embed

**数据示例**:
```
用户统计:
  skychen.: 62次查询, 86.7%成功率
  he_sunny: 9次查询, 88.9%成功率

热搜股票:
  台積電(2330.TW): 11次查询, 100%成功率
  華新(1605.TW): 5次查询, 100%成功率

最佳策略:
  AVOID/WAIT: ROI 565.84% (3个成功案例)
  BUY (Speculative): ROI 200.45% (4个成功案例)
```

**API使用**:
```python
from utils.user_analytics import create_ranking_embed, export_analytics_json

# 生成Discord消息
embeds = create_ranking_embed()
await channel.send(embeds=embeds)

# 导出JSON数据（用于ML训练）
analytics = export_analytics_json()
```

---

### 功能3: 时间段特定回测分析 ✅

**模块**: `utils/period_backtest.py`

**功能**:
- 按日期范围筛选历史数据
- 在特定时期内运行单个策略回测
- 对比策略在多个时期的表现
- 支持预定义时期(年度/季度)

**使用示例**:
```python
from utils.period_backtest import (
    analyze_multiple_periods,
    compare_strategy_across_periods,
    get_predefined_periods
)

# 生成预定义时期: 2025-2026年度+季度(10个)
periods = get_predefined_periods(years=[2025, 2026], include_quarters=True)
# 输出: [
#   {'name': '2025-Full', 'start': '2025-01-01', 'end': '2025-12-31'},
#   {'name': '2025-Q1', 'start': '2025-01-01', 'end': '2025-03-31'},
#   ...
# ]

# 分析多个时期
results = analyze_multiple_periods(TrendStrategy, df, periods)
# 输出: [{period, roi, win_rate, total_trades, ...}, ...]

# 对比策略稳定性
comparison = compare_strategy_across_periods(
    TrendStrategy, df, 'TrendStrategy',
    periods=periods
)
# 输出: {
#   strategy, analysis_time, periods,
#   summary: {avg_roi, avg_win_rate, roi_std, best_period, worst_period}
# }
```

**文件位置**: `data/period_backtest_results.json`

---

### 功能4: 混合机器学习预测模型 ✅

**模块**: `strategies/ml_models/hybrid_predictor.py`

**功能**:
- 集成5个技术指标 (MA, RSI, MACD, KD, BB)
- 加权组合生成综合预测信号
- 自适应权重根据波动性调整
- 返回详细置信度和成分分析

**预测器类型**:
```python
from strategies.ml_models import create_predictor

# 基础混合预测器 (固定权重)
predictor1 = create_predictor('hybrid')

# 自适应权重预测器 (根据ATR调整)
predictor2 = create_predictor('adaptive')

# 执行预测
result = predictor.predict(df)
# 输出: {
#   action: 'BUY'/'SELL'/'HOLD',
#   confidence: 0.0-1.0,
#   signal_strength: -1 到 1,
#   components: {
#     ma_crossover: (signal, confidence),
#     rsi: (signal, confidence),
#     ...
#   },
#   timestamp: ISO时间
# }
```

**权重配置**:
```
基础权重 (HybridPredictorBase):
  MA Crossover: 20%
  RSI:          25%
  MACD:         25%
  KD:           15%
  Bollinger:    15%

自适应权重 (AdaptiveWeightPredictor):
  高波动 (ATR>2%):  MA 30%, MACD 30%, RSI 15%, KD 15%, BB 10%
  低波动 (ATR<0.5%): MA 10%, RSI 35%, KD 35%, MACD 10%, BB 10%
  中等波动: 保持基础权重
```

**集成到main.py**:
```python
# main.py第18行新增import
from strategies.ml_models import create_predictor

# calculate_final_decision()中新增10行代码
# ML权重: 10% (辅助角色)
```

---

## 功能验证清单

### ✅ 配额系统 (quota_manager.py)
- [ ] 测试1: 新用户默认5次额度
- [ ] 测试2: Beta用户默认50次额度
- [ ] 测试3: Premium用户默认100次额度
- [ ] 测试4: 使用后剩余次数正确递减
- [ ] 测试5: **管理员gift后上限更新** ← 重点
- [ ] 测试6: 次日自动重置used，但保留limits
- [ ] 测试7: 配额用完时无法查询

**验证脚本**:
```bash
cd /root/stock_quant
python -c "
from utils.quota_manager import check_quota_status, admin_add_quota, deduct_quota
# 测试1
allowed, remaining, limit = check_quota_status(123, tier='free')
assert limit == 5, f'测试1失败: {limit}'
print('✓ 测试1: Free用户5次')

# 测试5 (重点)
new_limit = admin_add_quota(123, 20)
assert new_limit == 25, f'测试5失败: {new_limit}'
allowed, remaining, limit = check_quota_status(123, tier='free')
assert limit == 25, f'测试5验证失败: {limit}'
print('✓ 测试5: Gift后上限更新为25')
"
```

---

### ✅ 用户热搜系统 (user_analytics.py)
- [ ] 测试1: 加载71条CSV记录
- [ ] 测试2: 用户统计 (2用户, 86.7%/88.9%成功率)
- [ ] 测试3: 热搜股票 (台積電11次100%成功率)
- [ ] 测试4: Embed生成 (3个embeds)
- [ ] 测试5: **Discord命令 !hotlist 能正常发送**
- [ ] 测试6: 数据导出JSON用于ML训练

**验证脚本**:
```bash
python -c "
from utils.user_analytics import create_ranking_embed, export_analytics_json
embeds = create_ranking_embed()
assert len(embeds) == 3, f'Embed数量错误: {len(embeds)}'
print(f'✓ 生成{len(embeds)}个embeds')

analytics = export_analytics_json()
print(f'✓ 用户数: {len(analytics[\"user_stats\"])}')
print(f'✓ 股票数: {len(analytics[\"ticker_stats\"])}')
"
```

---

### ✅ 时间段回测系统 (period_backtest.py)
- [ ] 测试1: 数据筛选 (Q1: 90条, Q2: 91条)
- [ ] 测试2: 预定义时期 (10个: 2个年度+8个季度)
- [ ] 测试3: **单时期回测** (返回roi/win_rate/trades)
- [ ] 测试4: 多时期对比 (avg_roi, roi_std)
- [ ] 测试5: 结果持久化 (JSON保存+加载)
- [ ] 测试6: **Discord命令 !period 正常工作**

**验证脚本**:
```bash
python -c "
from utils.period_backtest import (
    filter_data_by_date_range,
    get_predefined_periods,
    load_period_results, save_period_results
)
import pandas as pd

# 测试2
periods = get_predefined_periods(years=[2025], include_quarters=True)
assert len(periods) == 5, f'时期数错误: {len(periods)}'
print(f'✓ 生成{len(periods)}个时期')

# 测试5
test_result = {'strategy': 'Test', 'periods': []}
save_period_results(test_result)
loaded = load_period_results('Test')
assert loaded['strategy'] == 'Test'
print('✓ 结果持久化成功')
"
```

---

### ✅ 混合ML模型 (hybrid_predictor.py)
- [ ] 测试1: HybridPredictorBase导入成功
- [ ] 测试2: 5个指标计算正确
- [ ] 测试3: **加权组合信号生成** (action: BUY/SELL/HOLD)
- [ ] 测试4: AdaptiveWeightPredictor自适应权重
- [ ] 测试5: 连续预测一致性 (5天数据稳定输出)
- [ ] 测试6: main.py集成无误

**验证脚本**:
```bash
python -c "
from strategies.ml_models import HybridPredictorBase, AdaptiveWeightPredictor
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 创建测试数据
dates = pd.date_range(datetime.now() - timedelta(days=100), periods=100, freq='D')
close = 100 + np.cumsum(np.random.randn(100) * 0.5)
df = pd.DataFrame({
    'Close': close,
    'High': close + 0.2,
    'Low': close - 0.2,
    'Volume': [1000000]*100
}, index=dates)

# 测试3
predictor = HybridPredictorBase()
result = predictor.predict(df)
assert result['action'] in ['BUY', 'SELL', 'HOLD']
assert 0 <= result['confidence'] <= 1
print(f'✓ 预测结果: {result[\"action\"]} (置信度{result[\"confidence\"]})')

# 测试4
predictor2 = AdaptiveWeightPredictor()
result2 = predictor2.predict(df)
print(f'✓ 自适应预测: {result2[\"action\"]} (置信度{result2[\"confidence\"]})')
"
```

---

## 故障排查指南

### 问题1: !analyze 显示 "配额已用完"
**症状**: 用户执行`!analyze`后立即收到额度用完提示

**排查步骤**:
```python
# 1. 检查quota_manager.py中的tier判断
from utils.quota_manager import check_quota_status
user_id = <user_discord_id>
allowed, remaining, limit = check_quota_status(user_id, tier='free')
print(f"剩余: {remaining}, 上限: {limit}")  # 应显示正确值

# 2. 检查user_quota.json文件内容
import json
with open('data/user_quota.json') as f:
    data = json.load(f)
    print(data)  # 应包含 "users" 和 "limits" 两个字段
```

**常见原因**:
- [ ] tier参数未正确传递给check_quota_status()
- [ ] JSON文件缺少"limits"字段（旧格式）
- [ ] 用户ID类型不匹配（int vs str）

**解决方案**:
```python
# discord_runner.py第85-90行确保正确传递tier
user_roles = [role.name for role in ctx.author.roles]
tier = 'free'
if any(r in ['Premium', 'VIP'] for r in user_roles):
    tier = 'premium'
elif 'BETA' in user_roles:
    tier = 'beta'
allowed, remaining, limit = check_quota_status(user_id, tier)  # ← 必须传tier
```

---

### 问题2: !hotlist 显示 "暫無數據"
**症状**: 执行!hotlist后返回空结果

**排查步骤**:
```python
# 1. 检查CSV文件是否存在且有数据
import pandas as pd
df = pd.read_csv('data/user_query_history.csv')
print(f"记录数: {len(df)}")  # 应 >= 1

# 2. 测试分析模块
from utils.user_analytics import load_query_history, calculate_user_stats
df = load_query_history()
stats = calculate_user_stats(df)
print(f"用户数: {len(stats)}")  # 应 > 0
```

**常见原因**:
- [ ] CSV文件路径错误或不存在
- [ ] CSV列名有多余空格导致解析失败
- [ ] 没有记录任何用户查询

**解决方案**:
```python
# utils/user_analytics.py第16-18行清理空白
df.columns = df.columns.str.strip()  # 清理列名空白
for col in df.select_dtypes(include=['object']).columns:
    df[col] = df[col].str.strip()   # 清理数据空白
```

---

### 问题3: !period 显示 "沒有可用的時間段分析結果"
**症状**: 执行!period后无任何策略分析数据

**排查步骤**:
```python
# 1. 检查JSON文件是否存在且有数据
from utils.period_backtest import load_period_results
results = load_period_results()
print(f"策略数: {len(results)}")  # 应 > 0

# 2. 手动运行period分析
from utils.period_backtest import analyze_multiple_periods
periods = get_predefined_periods(years=[2025])
# 需要先运行一次分析才会有数据
```

**常见原因**:
- [ ] 从未运行过时期回测分析
- [ ] JSON文件路径错误
- [ ] 策略优化尚未完成

**解决方案**:
```
1. 确保optimizer_runner.py已成功优化股票策略
2. 运行: python -c "from utils.period_backtest import *; ..."
3. 生成的结果会保存到data/period_backtest_results.json
```

---

### 问题4: ML模型预测为 "HOLD"
**症状**: hybrid_predictor总是返回HOLD信号

**排查步骤**:
```python
# 1. 检查各指标计算
from strategies.ml_models import HybridPredictorBase
predictor = HybridPredictorBase()
result = predictor.predict(df)
print(f"信号强度: {result['signal_strength']}")  # 应在 -1 到 1 之间

# 2. 查看各成分贡献
for component, (signal, conf) in result['components'].items():
    print(f"{component}: signal={signal}, confidence={conf}")
```

**常见原因**:
- [ ] 数据不足 (< 50条)
- [ ] 所有指标都在中性区域
- [ ] signal_threshold为±0.3，需要至少30%偏离

**解决方案**:
```python
# 调整阈值（main.py中）
if total_signal > 0.2:  # 从0.3降低到0.2
    action = 'BUY'
elif total_signal < -0.2:
    action = 'SELL'
```

---

## 开发环境设置

### 前置要求
```
Python: 3.9+
OS: Linux/MacOS/Windows
Database: JSON (内置)
```

### 安装步骤

**1. 克隆仓库**
```bash
git clone <repo_url>
cd /root/stock_quant
```

**2. 创建虚拟环境**
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows
```

**3. 安装依赖**
```bash
pip install -r requirements.txt
```

**4. 配置环境变量**
```bash
cp .env.example .env
# 编辑.env，填入Discord Token
# DISCORD_TOKEN=<your_token>
# NVIDIA_API_KEY=<your_key>
```

**5. 运行机器人**
```bash
python discord_runner.py
```

### 运行测试

**单元测试**:
```bash
# 配额管理
python -m pytest tests/test_quota.py -v

# 用户分析
python -m pytest tests/test_analytics.py -v

# 时期回测
python -m pytest tests/test_period_backtest.py -v

# ML模型
python -m pytest tests/test_ml_models.py -v
```

**集成测试**:
```bash
# 完整流程测试
python test_architecture.py
```

### 常用命令

**查看日志**:
```bash
tail -f logs/*.log
```

**清理缓存**:
```bash
find . -type d -name __pycache__ -exec rm -rf {} +
find . -type f -name "*.pyc" -delete
```

**更新依赖**:
```bash
pip install --upgrade -r requirements.txt
```

---

## 附录：API参考

### quota_manager.py
```python
check_quota_status(user_id, tier='free')
# 返回: (allowed: bool, remaining: int, limit: int)

deduct_quota(user_id)
# 返回: 使用后的次数

admin_add_quota(user_id, amount)
# 返回: 用户新的总额度上限
```

### user_analytics.py
```python
load_query_history() -> pd.DataFrame

calculate_user_stats(df) -> Dict[str, Dict]

calculate_ticker_stats(df) -> Dict[str, Dict]

get_top_hot_searches(df, top_n=10) -> List

get_top_users(df, top_n=10) -> List

create_ranking_embed() -> List[discord.Embed]

export_analytics_json() -> Dict
```

### period_backtest.py
```python
filter_data_by_date_range(df, start_date, end_date) -> pd.DataFrame

run_backtest_by_period(strategy_cls, df, period_name, start_date, end_date, **kwargs) -> Dict

analyze_multiple_periods(strategy_cls, df, periods, **kwargs) -> List[Dict]

compare_strategy_across_periods(strategy_cls, df, strategy_name, periods, **kwargs) -> Dict

get_predefined_periods(years=None, include_quarters=True) -> List[Dict]

save_period_results(analysis_result: Dict)

load_period_results(strategy_name: Optional[str]) -> Dict
```

### hybrid_predictor.py
```python
HybridPredictorBase(weights=None)
# 基础混合预测器

AdaptiveWeightPredictor()
# 自适应权重预测器

create_predictor(predictor_type='hybrid') -> HybridPredictorBase
# 工厂函数

predictor.predict(df) -> Dict
# 返回: {action, confidence, signal_strength, components, timestamp}
```

---

## 反馈表单

**请按以下格式提交功能验证结果**:

```
【验证日期】: 2026-02-XX
【测试者】: xxx
【环境】: Linux / Windows / MacOS

【配额管理】
- [ ] 测试1 通过 / 失败 / 跳过
  备注: ___________
- [ ] 测试2 通过 / 失败 / 跳过
  备注: ___________

【用户热搜】
- [ ] Discord命令 !hotlist 正常 / 异常
  症状: ___________
- [ ] 数据准确性: ___________

【时期回测】
- [ ] 时期生成正确
- [ ] 回测结果合理
- [ ] Discord命令 !period 正常

【ML模型】
- [ ] 模型预测合理
- [ ] main.py集成无误
- [ ] 性能可接受

【其他问题】:
- ___________
- ___________

【建议改进】:
- ___________
```

---

**问题反馈**: 请在GitHub Issue或Slack#bug-reports提交

**版本更新**: 2026-02-01 | V11.2
