---
name: kairos-scanner-orchestrator
description: 全自动市场扫描编排器 - 5分钟周期发现热点币→多周期分析→图表推送
version: 1.0.0
author: kairos
license: MIT
metadata:
  hermes:
    tags: [trading, crypto, scanner, orchestrator, kairos]
    category: finance
    requires_toolsets: [mcp]
    requires_tools: [coinglass_mcp, analysis_mcp, chart_mcp]
---

# 全自动市场扫描编排器

基于Bit浪浪交易系统的全自动扫描pipeline。每5分钟运行一次：发现热点币 → 多周期技术分析 → LLM深度验证 → 标注图表推送。

## 架构

```
Coinglass MCP → Analysis MCP → LLM验证 → Chart MCP → Telegram
    (RSI热点)   (box/sr/cycle)   (深度判断)   (标注图表)   (推送)
```

全部通过 MCP function calling，无 CLI 调用。

## Cron设置

```bash
hermes cron add "every 5 minutes" "运行kairos-scanner-orchestrator：扫描热点币，分析结构，生成图表，推送信号"
```

首次运行前确保：
1. Coinglass MCP server 已启动（或COINGLASS_API_KEY已设置）
2. Analysis MCP server 已启动（`python -m kairos.mcp.analysis_server`）
3. Chart MCP server 已启动（`python -m kairos.mcp.chart_server`）
4. 交易所API密钥已配置（CCXT环境变量或`~/.config/kairos/trading.yaml`）

---

## 执行流程

### Step 1：发现热点币

**目标**：用Coinglass RSI热力图动态发现市场热点，替代固定监控列表。

**方法**：
- 调用Coinglass MCP `get_hot_coins` 工具
- 参数：`rsi_high=70, rsi_low=30, timeframe="4h", limit=15`
- 获取两类候选：
  - **超买候选** (RSI 4H > 70)：强势币，可能在主升浪中，找回调/分歧后的二波机会
  - **超卖候选** (RSI 4H < 30)：弱势币，可能超跌反弹，找箱底不创新低的拐点

**备选**：如果Coinglass API key未设置，使用 `get_trending_coins` (CoinGecko) 作为备选。

**输出**：候选币列表（通常10-15个），每个包含symbol、当前价格、各周期RSI、价格变化。

---

### Step 2：多周期数据拉取

**目标**：为每个候选币拉取三个时间周期的OHLCV数据，同时拉取BTC数据用于共振判断。

**对每个候选币**：
```
symbol = "SOL/USDT"
exchange = "okx"
daily   = fetch_ohlcv(symbol, "1d", 100)
h4      = fetch_ohlcv(symbol, "4h", 100)
min15   = fetch_ohlcv(symbol, "15m", 100)
```

**同时拉取BTC**：
```
btc_daily  = fetch_ohlcv("BTC/USDT", "1d", 100)
btc_h4     = fetch_ohlcv("BTC/USDT", "4h", 100)
btc_min15  = fetch_ohlcv("BTC/USDT", "15m", 100)
```

**数据获取方式**：hermes通过 `code_execution` tool 直接调用 CCXT Python库获取OHLCV数据（不经过CLI）。示例：
```python
import ccxt
exchange = ccxt.okx()
ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
# 返回 [[ts, o, h, l, c, v], ...]
```

---

### Step 3：Kairos Analysis MCP 技术分析

**目标**：通过 Analysis MCP 的 function calling 运行分析，获取结构化JSON结果。

**BTC周期分析**（全局，只需一次）：
- 调用 Analysis MCP `analyze_cycle` 工具
- 参数：btc_prices, btc_volumes（来自Step 2的BTC日线数据）
- 获取结果：phase, confidence, btc_change_30d, volatility, volume_trend, description, position_advice

**每个候选币分析**：
- 调用 Analysis MCP `analyze_symbol` 工具（一次调用完成多周期分析）
- 参数：
  ```json
  {
    "symbol": "SOL/USDT",
    "current_price": 123.45,
    "timeframe_data": {
      "1d": {highs, lows, closes, volumes, timestamps},
      "4h": {highs, lows, closes, volumes, timestamps},
      "15m": {highs, lows, closes, volumes, timestamps}
    }
  }
  ```
- 返回结构化JSON：每周期 boxes + SR + trend + multi_tf_summary + risk_reward
- 无需分别调用 box-detect / sr / signal，一个工具返回所有分析结果

**多周期联动过滤**（Bit浪浪核心逻辑）：

筛选条件：
1. **日线方向**：必须为上升趋势或横盘整理（不是下降趋势）
   - 使用日线数据：计算20日均线斜率
   - `slope > 0` → 上升趋势 ✅
   - `slope ≈ 0` → 横盘整理 ✅（等待突破）
   - `slope < 0` → 下降趋势 ❌（排除）

2. **上方空间**：日线级别，当前价格上方是否有足够空间
   - 检查日线SR分析中的最近阻力位
   - 距离最近阻力位 > 5% → 空间充足 ✅
   - 距离最近阻力位 < 2% → 空间不足 ❌

3. **4H箱体状态**：必须存在有效箱体
   - `status == CONVERGING` → 准备突破 ✅
   - `status == FORMING` → 观察中 ⚠️
   - `second_test_high or second_test_low == True` → 结构成熟 ✅
   - 无箱体 → 跳过

4. **15m入场结构**：必须有入场信号
   - 箱体突破（带量） → 顺势跟进
   - 箱底承接（不创新低） → 低吸
   - 回踩企稳 → 确认入场
   - 无信号 → 降低评分

5. **BTC共振**：候选币方向必须与BTC一致
   - 候选币上升趋势 + BTC上升趋势 → 共振 ✅
   - 候选币上升趋势 + BTC下跌趋势 → 非共振 ❌（排除）
   - 或检查15m价格相关性 > 0.6

---

### Step 4：LLM深度验证

**目标**：hermes用自己的LLM推理能力验证算法结果，排除假信号。

对每个通过Step 3的候选币，执行以下判断：

**箱体结构有效性验证**：
- 箱体高度是否合理？（1%-15%之间，太窄可能是噪音，太宽结构松散）
- 触及次数是否足够？（上沿≥2次、下沿≥2次才成熟）
- 收敛是否真实？（近期波幅确实在缩小）
- 成交量是否配合？（箱体内缩量，突破放量）

**假突破风险评估**：
- 高位 + 五浪末端 + 小平台突破 → 极高假突破风险
- "小分歧"阶段追突破 → 高风险，建议等箱底承接
- 低位的首次突破 → 风险可控，值得试错
- 如果有假突破迹象 → 标注"改追突破为等回踩承接"

**分歧阶段判断**：
- 刚突破后首次横盘 → **小分歧**：在横盘箱底做承接
- 连续拉升后深度调整 → **大分歧**：等结构收敛后做二波
- 高位震荡 → **秋天/冬天**：不做或轻仓

**周期确认**：
- BTC当前周期 + 该币的隐含周期（基于自身涨跌幅和波动率）
- 春天/夏天 → 可以积极参与
- 秋天 → 轻仓、严格止损、降低预期
- 冬天 → 直接跳过

**综合评分**（1-10）：

| 因子 | 权重 | 说明 |
|------|------|------|
| 日线趋势方向 | 2 | 上升趋势得2分，横盘得1分 |
| 上方空间 | 2 | 空间>10%得2分，5-10%得1分 |
| 4H箱体成熟度 | 2 | converging+二次探得2分 |
| 15m入场信号 | 2 | 明确拐点/突破得2分 |
| BTC共振 | 1 | 共振得1分 |
| 周期匹配 | 1 | 春夏得1分，秋天得0.5分 |

- 总分 ≥ 5 → 生成图表并推送
- 总分 3-4 → 记录但不推送（等待进一步确认）
- 总分 < 3 → 跳过

---

### Step 5：图表生成与Telegram推送

**对评分≥5的候选币**：

**生成三类图表**：
1. **15m入场图表**（`generate_analysis_chart`）
   - 标注箱体矩形、S/R水平线、进出场箭头、分歧标签
   
2. **多周期概览图**（`generate_multi_tf_chart`）
   - 日线+4H+15min三面板，每面板标注各自的箱体和S/R
   
3. **BTC共振对比图**（`generate_btc_comparison_chart`）
   - BTC和候选币同周期并排对比

**组装Telegram消息**：

```markdown
🔥 交易信号 #{score}/10  {emoji}

📊 {SYMBOL}  {timeframe}

🔄 市场周期：{phase_emoji} {phase_name}
   BTC 30日涨幅：{btc_change}%
   波动率：{volatility}%
   建议：{advice}

📦 箱体结构：
   上沿：{box_high}
   下沿：{box_low}
   高度：{box_height_pct}%
   状态：{box_status}
   触及上沿：{touch_high}次 | 触及下沿：{touch_low}次
   收敛度：{convergence}%
   二次探：{second_test}

🎯 建议操作：
   方向：{direction}
   入场区间：{entry_zone}
   止损：{stop_loss}（{stop_pct}%）
   止盈1：{tp1}（{tp1_pct}%）
   止盈2：{tp2}（{tp2_pct}%）
   盈亏比：{rr_ratio}

⚖️ 风险参数：
   建议仓位：{position_size}%（{max_position}%上限）
   最大杠杆：{max_leverage}x
   当前持仓数：{current_positions}/2

⚠️ 风险提示：{risk_notes}

{analysis_narrative}
```

**附加图表文件**：3张PNG图片

---

## 风险约束（硬编码，不可被LLM覆盖）

以下规则必须在任何交易信号中严格执行：

| 规则 | 参数 |
|------|------|
| 山寨币仓位上限 | 33% |
| BTC/ETH仓位上限 | 33% |
| 山寨币最大杠杆 | 5x |
| BTC/ETH最大杠杆 | 10x |
| 最大同时持仓数 | 2 |
| 连续日亏损暂停 | 3次 |
| 止损必须设置 | 绝对强制 |

---

## 使用场景

### 自动监控模式
```bash
# hermes cron定时触发（推荐）
hermes cron add "every 5 minutes" "Run kairos-scanner-orchestrator full pipeline"
```

### 手动触发模式
在Telegram中直接对hermes说：
- "扫描市场" / "scan market" → 运行完整pipeline
- "分析 SOL/USDT" → 对指定币种运行Step 2-5
- "查看周期" / "check cycle" → 只运行BTC周期分析

## MCP Server 清单

| MCP Server | 启动命令 | 提供工具 |
|------------|----------|----------|
| Coinglass MCP | `python -m kairos.mcp.coinglass_server` | get_rsi_heatmap, get_hot_coins, get_coin_rsi, get_trending_coins |
| Analysis MCP | `python -m kairos.mcp.analysis_server` | analyze_cycle, detect_boxes, find_sr_levels, analyze_symbol |
| Chart MCP | `python -m kairos.mcp.chart_server` | generate_analysis_chart, generate_multi_tf_chart, generate_btc_comparison_chart |

---

## 注意事项

- **5分钟周期**：适合15min图表，每3根K线触发一次分析。如果市场活跃，可能每轮推送1-5个信号。
- **低阈值策略**：多推送让LLM验证，而非算法严格过滤。宁可多推几个假信号让你确认，也不能漏掉真机会。
- **图表文件清理**：Chart MCP server自动清理1小时前的旧图表文件。
- **Coinglass API限制**：免费API可能有频率限制。如果频繁429，调整cron间隔或使用CoinGecko备选。
- **交易所API限制**：每个候选币拉3个周期的OHLCV，如果候选池15个币 = 45次API调用。注意交易所频率限制。
- **只做合约**：所有分析针对永续合约交易对（USDT保证金）。
- **周期和仓位匹配**：春天→正常仓位，夏天→重仓，秋天→轻仓，冬天→空仓。
