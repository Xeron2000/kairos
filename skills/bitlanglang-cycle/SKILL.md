---
name: bitlanglang-cycle
description: 市场周期判断 - 基于Bit浪浪春夏秋冬理论的市场阶段分析
version: 1.0.0
author: pwatch
license: MIT
metadata:
  hermes:
    tags: [trading, crypto, market-cycle, bitlanglang]
    category: finance
    requires_toolsets: [code]
    requires_tools: [code_execution]
---

# 市场周期判断 - Bit浪浪春夏秋冬理论

## 核心概念

Bit浪浪将市场分为四个阶段：
- **春天**：行情启动期，百花齐放
- **夏天**：主升浪狂热期，聚焦龙头
- **秋天**：高位震荡期，补涨行情
- **冬天**：下跌震荡期，空仓等待

## 使用场景

当需要判断当前市场阶段时使用此skill：
- 决定仓位策略
- 调整交易频率
- 选择杠杆水平

## CLI命令

```bash
# 查看当前市场周期
pwatch cycle

# 输出示例
# 🔄 Market Cycle Analysis
# ==================================================
# 📊 Current Phase: SPRING (牛市初期)
# 📈 BTC 30-day Change: +15.2%
# 📉 BTC 7-day Change: +5.8%
# 🌡️  Volatility: 3.2% (Medium)
# 📊 Volume Trend: Increasing
# 💰 Avg Funding Rate: 0.012%
# 💡 Advice: 开始建仓，正常杠杆
```

## 量化指标

### 春天识别
- BTC 30日涨幅：10-30%
- 波动率：中等
- 成交量：增加
- 资金费率：正常

### 夏天识别
- BTC 30日涨幅：>30%
- 波动率：高
- 成交量：增加
- 资金费率：高正

### 秋天识别
- BTC 30日涨幅：高位震荡
- 波动率：低
- 成交量：减少
- 资金费率：极高

### 冬天识别
- BTC 30日涨幅：<-10%
- 波动率：高
- 成交量：减少
- 资金费率：负/极低

## 周期策略

### 春天策略
- 开始建仓，正常杠杆
- 积极寻找右侧跟随大盘突破的机会
- 建立底仓，准备迎接主升浪

### 夏天策略
- 重仓出击，激进杠杆
- 聚焦龙头币
- 利用小分歧做承接或突破

### 秋天策略
- 轻仓防守，保守杠杆
- 降低交易频率
- 严格止损

### 冬天策略
- 空仓等待，无杠杆
- 坚决管住手
- 耐心等待下一个春天

## LLM判断流程

hermes agent使用此skill时：
1. 调用 `pwatch cycle` 获取量化指标
2. 结合LLM分析市场情绪
3. 综合判断当前周期阶段
4. 给出仓位和策略建议

## 注意事项

- 量化指标只是参考，LLM综合判断更重要
- 周期转换是渐进的，不是突然的
- 不同品种可能处于不同周期
- 需要结合大盘和山寨币综合判断
