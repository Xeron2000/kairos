---
name: kairos-signal
description: 交易信号 - 基于kairos进场策略的信号生成
version: 1.0.0
author: pwatch
license: MIT
metadata:
  hermes:
    tags: [trading, crypto, signal, kairos]
    category: finance
    requires_toolsets: [code]
    requires_tools: [code_execution]
---

# 交易信号 - kairos进场策略

## 核心概念

kairos进场策略：
- **趋势初期**：大级别箱体突破
- **趋势中期**：利用"分歧"寻找介入机会
- **小级别精准**：找"拐点"和"回踩企稳"

## 使用场景

当需要获取交易信号时使用此skill：
- 检测突破信号
- 识别拐点机会
- 评估进场时机

## CLI命令

```bash
# 检测交易信号
pwatch signal --symbol BTC/USDT --strategy box_breakout

# 输出示例
# 🎯 Trading Signal Detection: BTC/USDT
# ============================================================
# 📊 Strategy: box_breakout
#
# ✅ Box Breakout Signal Detected!
#
# 📊 Signal Quality: HIGH
# 🎯 Direction: LONG
#
# 📐 Entry Parameters:
#   Entry Price: 68,500
#   Stop Loss: 67,200 (box low)
#   Risk: 1,300 (1.90%)
#
# 🎯 Targets:
#   TP1: 69,800 (+1.90%) - 30% position
#   TP2: 71,100 (+3.80%) - 30% position
#   TP3: 73,700 (+7.60%) - 40% position
```

## 信号策略

### box_breakout（箱体突破）
- **条件**：箱体收敛 + 放量突破上沿
- **进场**：突破确认后
- **止损**：箱体下沿
- **目标**：箱体高度的1-2倍

### small_pullback（小分歧）
- **条件**：主升浪初期/中期的横盘回踩
- **进场**：箱体底部低点做承接
- **止损**：箱体下沿
- **目标**：前高或更高

### large_pullback（大分歧）
- **条件**：主升浪中后期的深度调整
- **进场**：调整结束，结构收敛后
- **止损**：调整低点
- **目标**：二波行情

### double_bottom（双底）
- **条件**：下跌后反弹再跌不破前低
- **进场**：第二个底确认后
- **止损**：双底最低点
- **目标**：颈线或更高

## 右侧信号判断

### 不创新低的拐点
- 等待价格砸下来、反弹、再次下砸
- 当价格再次下探但不再创出新低时
- 代表下跌趋势终结，是右侧买点

### 回踩企稳
- 价格向上突破后回落
- 回踩前期支撑位并且"踩住"
- 重新拐头向上时入场

### 假突破后的反包
- 价格假突破后，迅速被一根强力K线全部吞没
- 代表诱空或诱多结束
- 是强烈的反向进场信号

## LLM判断流程

hermes agent使用此skill时：
1. 调用 `pwatch signal` 获取算法信号
2. 结合大盘周期判断信号有效性
3. 评估盈亏比和风险
4. 决定是否执行交易

## 注意事项

- 算法信号只是参考，LLM判断更重要
- 需要结合大盘周期和选币逻辑
- 右侧信号比左侧更安全
- 严格止损是生存的关键
