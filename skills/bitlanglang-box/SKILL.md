---
name: bitlanglang-box
description: 箱体识别 - 基于Bit浪浪箱体理论的市场结构分析
version: 1.0.0
author: pwatch
license: MIT
metadata:
  hermes:
    tags: [trading, crypto, box-pattern, bitlanglang]
    category: finance
    requires_toolsets: [code]
    requires_tools: [code_execution]
---

# 箱体识别 - Bit浪浪箱体理论

## 核心概念

箱体是价格在区间内来回震荡形成的结构：
- **上沿**：多次触及的高点区域
- **下沿**：多次触及的低点区域
- **二次探顶/底**：箱体成熟的标志
- **收敛**：波动范围逐渐缩小

## 使用场景

当需要分析价格结构时使用此skill：
- 识别箱体突破机会
- 寻找箱底承接机会
- 判断市场蓄力程度

## CLI命令

```bash
# 检测箱体模式
pwatch box-detect --symbol BTC/USDT --timeframe 15m

# 输出示例
# 📦 Box Pattern Detection: BTC/USDT
# ============================================================
# ⏱️  Timeframe: 15m
# 📊 Lookback: 100 bars
#
# ✅ Box Pattern Detected!
#
# 📐 Box Parameters:
#   High: 68,500.00
#   Low: 67,200.00
#   Height: 1,300.00 (1.94%)
#
# 📊 Pattern Quality:
#   Touch High: 3
#   Touch Low: 4
#   Second Test High: ✅
#   Second Test Low: ✅
#   Convergence: 85%
#   Volume Declining: ✅
#
# 🎯 Status: CONVERGING (Ready for breakout)
```

## 箱体识别算法

### 箱体定义
- 初始范围：前N根K线的最高点和最低点
- 扩展条件：价格在范围内震荡
- 成熟标志：二次探顶/底 + 收敛

### 关键参数
- **minBars**：最少K线数（默认10）
- **maxBars**：最多K线数（默认100）
- **touchThresholdPct**：触及容差（默认0.3%）
- **convergenceThreshold**：收敛阈值（默认0.7）

### 箱体状态
- **FORMING**：形成中
- **CONVERGING**：收敛中，接近突破
- **BREAKOUT_UP**：向上突破
- **BREAKOUT_DOWN**：向下突破

## 交易策略

### 箱体突破
- **条件**：收敛充分 + 放量突破
- **进场**：突破确认后
- **止损**：箱体下沿
- **目标**：箱体高度的1-2倍

### 箱底承接
- **条件**：价格触及下沿 + 不创新低
- **进场**：拐点确认后
- **止损**：箱体最下沿
- **目标**：箱体上沿

### 规避中间
- 箱体中间位置不做
- 盈亏比极差
- 耐心等待突破或箱底

## LLM确认流程

hermes agent使用此skill时：
1. 调用 `pwatch box-detect` 获取算法结果
2. 确认箱体结构是否有效
3. 评估收敛程度和突破概率
4. 制定交易计划（进场、止损、目标）

## 注意事项

- 算法只是初步识别，LLM确认更重要
- 需要结合大盘周期判断
- 假突破是常态，需要严格止损
- 箱体中间位置不做，等待突破或箱底
