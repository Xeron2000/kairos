# kairos

> 古希腊语：καιρός — 关键时刻，恰当时机

Crypto futures trading signal harness for Hermes Agent. Based on Bit浪浪's trading philosophy.

> 复制下面这段文字发给你的 Hermes Agent。它会自动完成 kairos 的安装、配置和启动。

```
请帮我安装并配置 kairos 加密货币交易信号 harness。按顺序执行：

1. 克隆仓库并安装依赖：
   git clone https://github.com/Xeron2000/kairos ~/kairos 2>/dev/null || true
   cd ~/kairos && uv sync

2. 复制技能文件到 Hermes 技能目录：
   mkdir -p ~/.hermes/skills/kairos
   cp -r ~/kairos/skills/kairos-* ~/.hermes/skills/kairos/

3. 编辑 ~/.hermes/config.yaml，在 skills 段修改 external_dirs 为：
   external_dirs: [~/.hermes/skills/kairos]

4. 创建 webhook 订阅（如果还没有的话，先运行 hermes webhook list 检查）：
   如果没有 kairos-signals 订阅，运行：
   echo 'Y' | hermes webhook subscribe --name kairos-signals --url /webhooks/kairos-signals --prompt "你是交易信号过滤器。收到kairos推送的SignalEvent后：1.无意义/重复信号回复「静默」2.有价值的信号调用kairos MCP工具深度分析3.确认的高质量信号推送Telegram。详细规则见kairos-harness技能。" --delivery telegram
   记下输出的 secret 密钥。

5. 注册 kairos 为 MCP 服务（把 YOUR_SECRET 替换为上一步的密钥）：
   echo 'Y' | hermes mcp add kairos --command ~/kairos/run.sh --env KAIROS_WEBHOOK_SECRET=YOUR_SECRET

6. 重启 gateway 加载 MCP 工具：
   systemctl --user restart hermes-gateway

7. 验证工具可用（会列出 10 个 kairos 工具）：
   sleep 3 && tail -5 ~/.hermes/logs/gateway.log

完成后告诉我是否成功。"```

先决条件：服务器已安装 `git`、`uv`，且 Hermes 已配置 Telegram 和 webhook 平台。

## Architecture

```
Kairos (MCP Server)                  Hermes Agent
┌──────────────────────┐     POST    ┌──────────────┐
│  WebSocket feeds     │ ──────────> │  LLM filter   │
│  Anomaly detectors   │  SignalEvent│  MCP tool calls│
│  Technical analysis  │ <────────── │  Telegram push │
└──────────────────────┘   tools     └──────────────┘
```

Kairos watches markets via WebSocket 24/7, detects anomalies (price velocity, volume spikes), and pushes SignalEvent to Hermes via webhook. Hermes filters noise, calls MCP tools for deep analysis, and pushes high-quality signals to Telegram.

## MCP Tools

| Tool | Description |
|------|-------------|
| `get_market_cycle` | 春夏秋冬 market phase + BTC trend + altcoin season |
| `detect_box_pattern` | Box pattern detection with convergence scoring |
| `scan_symbols` | Symbol scanning with formula-based ranking |
| `detect_signal` | Trading signal (breakout/pullback/reversal) |
| `get_market_sentiment` | 恐惧贪婪指数 + market sentiment overview |
| `check_pyramiding` | Pyramiding condition analysis |
| `check_exit_signals` | Exit signal detection (6 types) |
| `blacklist_symbol` | Ban a noisy coin (Hermes-controlled blacklist) |
| `unblacklist_symbol` | Unban a coin |
| `list_blacklist` | Show all banned coins with reasons |

## Skills

| Skill | Description |
|-------|-------------|
| `kairos-harness` | **How Hermes uses kairos** — signal filtering, tool calling, decision flow |
| `kairos-cycle` | 春夏秋冬周期判断 |
| `kairos-scanner` | 量化选币 |
| `kairos-box` | 箱体识别 |
| `kairos-signal` | 交易信号 |
| `kairos-market-sentiment` | 市场氛围 |
| `kairos-pyramiding` | 加仓分析 |
| `kairos-exit-signals` | 出场信号 |
| `kairos-selection-formula` | 选币完美公式 |
| `kairos-divergence` | 分歧理论 |
| `kairos-new-coin` | 新币交易 |
| `kairos-scanner-orchestrator` | 全自动扫描编排 |

## Quick Start

```bash
git clone https://github.com/Xeron2000/kairos ~/kairos
cd ~/kairos && uv sync
export KAIROS_WEBHOOK_SECRET="<from hermes webhook subscribe>"
uv run kairos-mcp
```

MCP server starts, connects to exchanges, begins scanning.

## Philosophy

顺势而为 · 敬畏市场 · 严格止损

## License

MIT
