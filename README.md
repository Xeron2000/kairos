# pwatch

Cryptocurrency futures price monitor & trading system with Hermes Agent integration.

## Trading System

Based on Bit浪浪's trading philosophy. See `skills/` for Hermes Agent integration.

### CLI Commands

```bash
pwatch cycle                    # Market cycle phase
pwatch scan                     # Scan symbols
pwatch box-detect --symbol BTC/USDT  # Box pattern
pwatch signal --symbol BTC/USDT      # Trading signal
pwatch position status          # Positions
pwatch risk status              # Risk status
pwatch history                  # Trade history
```

### Skills

| Skill | Description |
|-------|-------------|
| `bitlanglang-cycle` | Market cycle (春夏秋冬) |
| `bitlanglang-scanner` | Symbol scanning |
| `bitlanglang-box` | Box detection |
| `bitlanglang-signal` | Trading signals |
| `bitlanglang-position` | Position management |
| `bitlanglang-risk` | Risk control |
| `bitlanglang-review` | Trade review |

## License

MIT
