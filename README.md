# pwatch

Cryptocurrency futures price monitor & trading system with Hermes Agent integration.

## Install

```bash
uv tool install git+https://github.com/Xeron2000/pwatch
```

## Usage

```bash
pwatch                                         # Start monitoring in background
pwatch run                                     # Run in foreground for debugging
pwatch status                                  # Show background process status
pwatch stop                                    # Stop background process
pwatch logs                                    # Print background log file
pwatch update-markets                          # Update market data
pwatch update-markets --exchanges okx binance  # Update specific exchanges
pwatch config-path                             # Show config directory
```

First run guides you through setup — you'll need a [Telegram Bot Token](https://t.me/botfather). By default `pwatch` starts in background; use `pwatch run` for foreground debugging.

## Config

Located at `~/.config/pwatch/config.yaml`:

```yaml
exchange: "okx"
defaultTimeframe: "5m"
checkInterval: "1m"
defaultThreshold: 1
notificationSymbols: "auto"  # top symbols after quality filters, refreshes every 4h
autoModeProfile: "conservative"
autoModeLimit: 40
autoModeMinQuoteVolume24h: 80000000      # filter out low-turnover symbols
autoModeMinOpenInterestUsd: 25000000     # avoid low-OI, easier-to-manipulate contracts
autoModeMinListingAgeDays: 45            # exclude very new listings
autoModeMaxRecentVolatilityPct: 6.0      # exclude ultra-wild symbols before they enter the pool

telegram:
  token: "your-bot-token"
  chatId: "your-chat-id"
```

## Trading System

pwatch includes a complete trading system based on Bit浪浪's trading philosophy, designed for integration with Hermes Agent.

### Architecture

```
pwatch (CLI)                    hermes agent
├── Data fetching               ├── Read skills
├── Technical analysis          ├── Call CLI for data
├── Trade execution             ├── LLM judgment
├── Risk control                ├── Decision making
└── Structured output           └── Learning & review
```

### CLI Commands

#### Market Analysis
```bash
pwatch cycle                    # Show market cycle phase (春夏秋冬)
pwatch scan                     # Scan for trading symbols
pwatch box-detect --symbol BTC/USDT  # Detect box patterns
pwatch signal --symbol BTC/USDT      # Detect trading signals
pwatch sr --symbol BTC/USDT          # Show support/resistance levels
```

#### Position Management
```bash
pwatch position status          # Show current positions
pwatch position size --capital 10000 --risk-pct 33 --leverage 5
pwatch position history         # Show trade history
pwatch position stats           # Show strategy statistics
```

#### Trading Execution
```bash
pwatch order --symbol BTC/USDT --side long --size 1000
pwatch close --symbol BTC/USDT
```

#### Risk Management
```bash
pwatch risk status              # Show risk status
pwatch risk check --symbol BTC/USDT --size 5000
pwatch history                  # Show trading history
pwatch stats                    # Show trading statistics
```

### Hermes Agent Skills

Modular skills for Hermes Agent integration:

| Skill | Description |
|-------|-------------|
| `bitlanglang-cycle` | Market cycle analysis (春夏秋冬 theory) |
| `bitlanglang-scanner` | Symbol scanning (quantitative + agent analysis) |
| `bitlanglang-box` | Box pattern detection (algorithm + agent confirmation) |
| `bitlanglang-signal` | Trading signals (breakout/pullback/reversal) |
| `bitlanglang-position` | Position management (fixed sizing, leverage limits) |
| `bitlanglang-risk` | Risk control (stop-loss, consecutive loss limits) |
| `bitlanglang-review` | Trade review (history, statistics, learning) |

### Install Skills

```bash
# Copy all skills to Hermes Agent
cp -r skills/bitlanglang-* ~/.hermes/skills/finance/

# Or install individual skills
hermes skills install local/path/to/skills/bitlanglang-cycle
hermes skills install local/path/to/skills/bitlanglang-scanner
hermes skills install local/path/to/skills/bitlanglang-box
hermes skills install local/path/to/skills/bitlanglang-signal
hermes skills install local/path/to/skills/bitlanglang-position
hermes skills install local/path/to/skills/bitlanglang-risk
hermes skills install local/path/to/skills/bitlanglang-review
```

### Risk Constraints

| Parameter | Value |
|-----------|-------|
| Altcoin position size | 33% of capital |
| Altcoin max leverage | 5x |
| BTC/ETH position size | 33% of capital |
| BTC/ETH max leverage | 10x |
| Max simultaneous positions | 2 |
| Consecutive loss limit | 3 (pause trading) |

### Trading Philosophy

Based on Bit浪浪's trading system:

1. **顺势而为** - Follow the trend, never trade against it
2. **敬畏市场** - Respect the market, always be humble
3. **严格止损** - Strict stop-loss is your lifeline
4. **分仓管理** - Fixed position sizing, divide capital
5. **低倍杠杆** - Low leverage: BTC ≤ 10x, altcoins ≤ 5x

## License

MIT
