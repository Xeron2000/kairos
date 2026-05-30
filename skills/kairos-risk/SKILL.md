---
name: kairos-risk
description: 风险控制 - 基于kairos风险控制原则的资金保护
version: 1.0.0
author: pwatch
license: MIT
metadata:
  hermes:
    tags: [trading, crypto, risk, kairos]
    category: finance
    requires_toolsets: [code]
    requires_tools: [code_execution]
---

# 风险控制 - kairos风险控制原则

## 核心概念

kairos风险控制：
- **止损是命**：止损和仓位管理是唯一能保命的防线
- **严格纪律**：坚决不做逆势单，宁愿踏空绝不摸顶
- **敬畏市场**：市场永远是对的，始终保持敬畏之心

## 使用场景

当需要管理风险时使用此skill：
- 检查风险状态
- 验证交易是否允许
- 监控风险指标

## CLI命令

```bash
# 查看风险状态
pwatch risk status

# 检查交易风险
pwatch risk check --symbol BTC/USDT --size 5000

# 输出示例
# ⚠️ Risk Status
# ============================================================
# 💰 Capital: 10,000 USDT
# 📈 Open Positions: 2
# 💵 Total Exposure: 6,600 USDT (66%)
#
# 📊 Daily Stats:
#   Daily PnL: +700 USDT (+7.0%)
#   Daily Loss Limit: 1,000 USDT (10%)
#   Remaining: 300 USDT
#
# ⚠️ Risk Limits:
#   Max Position Size: 33%
#   Max Total Exposure: 66%
#   Max Daily Loss: 10%
#   Max Consecutive Losses: 3
#   Current Consecutive Losses: 0
#
# ✅ Risk Status: HEALTHY
```

## 风险约束

### 仓位限制
- 单笔最大仓位：33%
- 总暴露上限：66%（2个仓位）
- 最大同时持仓：2个

### 损失限制
- 日亏损上限：10%
- 连续亏损上限：3次
- 最大回撤：20%

### 杠杆限制
- BTC/ETH：最多10倍
- 山寨币：最多5倍
- 套利：最多3倍

## 风险检查

### 开仓前检查
1. 单笔仓位 ≤ 33%
2. 总暴露 ≤ 66%
3. 连续亏损 < 3次
4. 止损已设置
5. 盈亏比 ≥ 2:1

### 持仓中检查
1. 止损已设置
2. 定期检查结构
3. 注意出场信号
4. 保持心态平和

## 风险信号

### 高风险信号
- 连续亏损3次
- 总暴露超过66%
- 日亏损超过10%
- 心态失衡

### 应对措施
- 立即停止交易
- 复盘分析原因
- 回归系统纪律
- 等待心态恢复

## LLM风险判断

hermes agent使用此skill时：
1. 调用 `pwatch risk status` 获取风险状态
2. 检查是否满足开仓条件
3. 评估风险收益比
4. 决定是否执行交易

## 注意事项

- 止损是保命的底线
- 连续亏损时必须停止
- 心态失衡时不要交易
- 敬畏市场，顺势而为

## 生存法则

- 不让任何一笔交易的失败影响到整体交易体系的稳定
- 高容错率让你在连续做错几次时依然保持清醒
- 市场永远是对的，始终保持敬畏之心
