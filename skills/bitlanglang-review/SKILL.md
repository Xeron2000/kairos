---
name: bitlanglang-review
description: 复盘学习 - 基于Bit浪浪复盘方法的交易总结
version: 1.0.0
author: pwatch
license: MIT
metadata:
  hermes:
    tags: [trading, crypto, review, bitlanglang]
    category: finance
    requires_toolsets: [code]
    requires_tools: [code_execution]
---

# 复盘学习 - Bit浪浪复盘方法

## 核心概念

Bit浪浪复盘方法：
- **裸K推演**：逐根回放K线，验证逻辑
- **逐单剖析**：分析亏损单，分类总结
- **深挖情绪**：找出深层心态诱因
- **总结规律**：找出市场共性

## 使用场景

当需要复盘交易时使用此skill：
- 回顾交易历史
- 分析盈亏原因
- 总结经验教训
- 优化交易策略

## CLI命令

```bash
# 查看交易历史
pwatch history --limit 50

# 查看策略统计
pwatch stats --strategy box_breakout

# 输出示例
# 📊 Trading Statistics
# ============================================================
# 🎯 Strategy: box_breakout
#
# 📈 Overall Performance:
#   Total Trades: 45
#   Wins: 28 (62.2%)
#   Losses: 17 (37.8%)
#   Total PnL: +8,500 USDT
#   Avg Win: +450 USDT
#   Avg Loss: -280 USDT
#   Best Trade: +2,100 USDT
#   Worst Trade: -800 USDT
```

## 复盘流程

### 裸K推演训练
1. 调出过去15分钟或5分钟K线图
2. 遮住后续走势
3. 一根一根向后回放
4. 在每个结构节点问自己：这里是箱体还是趋势？该在哪里做多/做空？防守设在哪里？
5. 然后播放实际走势，验证自己的逻辑

### 逐单剖析亏损原因
1. 调出一周交割单
2. 重点分析亏损单
3. 将亏损分类：
   - **体系内试错**：逻辑正确，可以接受
   - **犯病/上头亏损**：必须反思

### 深挖情绪诱因
1. 诚实面对自己
2. 找出深层心态诱因
3. 例如：连续亏损是因为之前"卖飞"了某波行情，导致后来产生强烈的踏空焦虑

### 总结周期规律
1. 总结不同周期下资金轮动的规律
2. 回顾这波行情是谁先启动、谁在跟涨、谁在最后补涨
3. 找出市场的共性，作为下次行情的预案

## 学习机制

### 每N笔交易后回顾
- 分析最近N笔交易的盈亏
- 找出成功和失败的模式
- 调整策略参数

### 每日/周总结
- 总结当日/当周的交易
- 分析市场周期变化
- 制定下一步计划

### 人工反馈
- 通过Telegram与hermes agent沟通
- 提供主观判断和情绪反馈
- 帮助agent学习交易习惯

## LLM复盘流程

hermes agent使用此skill时：
1. 调用 `pwatch history` 获取交易历史
2. 调用 `pwatch stats` 获取策略统计
3. 分析盈亏原因和模式
4. 总结经验教训
5. 更新skill和策略参数

## 复盘记录模板

```
日期：2024-01-15
品种：BTC/USDT
方向：做多
进场价：68000
止损价：67200
止盈目标：70000/72000/75000
仓位：0.735 BTC (50,000 USDT)
杠杆：5x
盈亏比：2.5:1
策略：箱体突破
周期：春天
心态：平静
备注：日线结构完美，上方无压力
```

## 注意事项

- 复盘是提升的关键
- 诚实面对自己的错误
- 从亏损中学习
- 持续优化策略
