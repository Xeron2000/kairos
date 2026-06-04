# kairos-scanner-orchestrator

全自动市场扫描编排器 — hermes-agent skill for 5-minute crypto market scanning.

## 功能

每5分钟运行一次完整pipeline：
1. **发现热点币** — Coinglass RSI热力图 / CoinGecko trending
2. **多周期数据拉取** — 日线 + 4H + 15min OHLCV
3. **kairos技术分析** — box-detect, sr, cycle, signal
4. **LLM深度验证** — 假突破识别、分歧判断、周期确认、综合评分
5. **图表推送** — 3张标注图表 + 结构化交易信号 → Telegram

## 前置条件

```bash
# 1. 安装依赖
uv sync --group hermes

# 2. 启动 MCP servers
python -m kairos.mcp.coinglass_server &
python -m kairos.mcp.chart_server &

# 3. 环境变量（可选）
export COINGLASS_API_KEY="your_key"  # 无 key 时使用 CoinGecko 备选
```

## Cron设置

```bash
hermes cron add "every 5 minutes" "Run kairos-scanner-orchestrator: scan hot coins, analyze structures, generate charts, push signals"
```

## 手动触发

在Telegram中：
- `扫描市场` / `scan market` — 运行完整pipeline
- `分析 SOL/USDT` — 分析指定币种
- `查看周期` / `check cycle` — 查看市场周期

## 信号格式示例

```
🔥 交易信号 7/10  ☀️

📊 SOL/USDT  15m

🔄 市场周期：☀️ SUMMER
   BTC 30日涨幅：+25.3%
   波动率：4.2%
   建议：重仓出击，激进杠杆

📦 箱体结构：
   上沿：142.50 | 下沿：138.20
   高度：3.1% | 状态：CONVERGING
   触及：上3次 下4次 | 二次探：✅
   收敛度：85%

🎯 建议操作：
   方向：做多
   入场：139.50-140.00
   止损：137.80 (-1.6%)
   止盈1：142.50 (+1.8%)
   止盈2：145.00 (+3.6%)
   盈亏比：2.2:1

⚠️ 箱体收敛充分，放量突破上沿概率高
   BTC同步向上，共振确认
   注意：上方143有整数关口阻力
```
