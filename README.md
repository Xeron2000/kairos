# kairos

> 古希腊语：καιρός — 关键时刻，恰当时机

Crypto futures trading signal harness for Hermes Agent. Based on Bit浪浪's trading philosophy.

> Copy and send to your Hermes Agent for automatic installation, configuration, and launch:

```
Please install and configure the kairos crypto trading signal harness. The server needs git, uv, and Hermes with Telegram and webhook platforms configured. Steps: 1) git clone https://github.com/Xeron2000/kairos ~/kairos && cd ~/kairos && uv sync  2) mkdir -p ~/.hermes/skills/kairos && cp -r ~/kairos/skills/kairos-* ~/.hermes/skills/kairos/  3) Edit ~/.hermes/config.yaml, set skills.external_dirs to [~/.hermes/skills/kairos]  4) hermes webhook subscribe kairos-signals --prompt "You are a strict Kairos futures trade gate. Webhook anomalies are candidate hints only. Analyze this payload with kairos MCP tools: {__raw__}. Handle price_velocity, volume_spike, open_interest_change, and funding_rate_anomaly. For health_check, test, unsupported, noisy events, or any case where evaluate_trade_opportunity(symbol) does not return push_allowed == true, return exactly KAIROS_NO_SIGNAL and nothing else. Hermes may veto but must never promote watch/prepare/no_trade into an alert. Only produce a concise Telegram-ready Chinese KISS alert when Kairos deterministic analysis returns push_allowed with direction, entry zone, stop, target, and valid risk/reward. Load kairos-harness for the full rules." --skills kairos-harness --deliver telegram (save the secret)  5) hermes mcp add kairos --command ~/kairos/run.sh --env KAIROS_WEBHOOK_SECRET=<secret>  6) systemctl --user restart hermes-gateway  7) Tell me if successful.
```

## Architecture

```
Kairos (MCP Server)                  Hermes Agent
┌──────────────────────┐     POST    ┌──────────────┐
│  WebSocket feeds     │ ──────────> │  LLM filter   │
│  Anomaly detectors   │  SignalEvent│  MCP tool calls│
│  Technical analysis  │ <────────── │  Telegram push │
└──────────────────────┘   tools     └──────────────┘
```

Kairos watches markets via WebSocket 24/7, detects futures anomalies (price velocity, volume spikes, open-interest changes, and funding-rate anomalies), and pushes SignalEvent to Hermes via webhook. Hermes filters noise, calls MCP tools for deep analysis, and pushes only high-quality trade opportunities to Telegram.

## MCP Tools

| Tool | Description |
|------|-------------|
| `scan_market` | Scanner-first Top 30 market discovery with deterministic setup scoring |
| `analyze_symbol_setup` | Deterministic symbol setup analysis; `trade_candidate` is required before Telegram push |
| `evaluate_trade_opportunity` | Explicit `push_allowed` gate for Hermes Telegram alerts |
| `get_market_cycle` | 春夏秋冬 market phase + BTC trend + altcoin season |
| `detect_box_pattern` | Box pattern detection with convergence scoring |
| `scan_symbols` | Legacy symbol scanning with formula-based ranking |
| `detect_signal` | Trading signal (breakout/pullback/reversal) |
| `get_market_sentiment` | Fear & Greed index + market sentiment |
| `check_pyramiding` | Pyramiding condition analysis |
| `check_exit_signals` | Exit signal detection (6 types) |
| `blacklist_symbol` | Ban a noisy coin (Hermes-controlled blacklist) |
| `unblacklist_symbol` | Unban a coin |
| `list_blacklist` | Show all banned coins with reasons |

## Skills

| Skill | Description |
|-------|-------------|
| `kairos-harness` | **How Hermes uses kairos** — signal filtering, tool calling, decision flow |
| `kairos-cycle` | Market cycle analysis (春夏秋冬) |
| `kairos-scanner` | Symbol scanner |
| `kairos-box` | Box pattern detection |
| `kairos-signal` | Trading signals |
| `kairos-market-sentiment` | Market sentiment |
| `kairos-pyramiding` | Pyramiding analysis |
| `kairos-exit-signals` | Exit signals |
| `kairos-selection-formula` | Selection formula |
| `kairos-divergence` | Divergence theory |
| `kairos-new-coin` | New coin trading |
| `kairos-scanner-orchestrator` | Auto scan orchestrator |

## Philosophy

顺势而为 · 敬畏市场 · 严格止损

## License

MIT
