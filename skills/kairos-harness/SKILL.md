---
name: kairos-harness
description: How Hermes uses the kairos trading signal harness — signal filtering, MCP tool orchestration, decision flow
---

# kairos-harness

**IMPORTANT: You receive real-time market signals from kairos. Your job is to filter noise and confirm quality.**

## Signal Flow

```
Kairos WebSocket → detector catches anomaly → SignalEvent POST to you
                                                      │
                                                      ▼
                                              You receive SignalEvent
                                                      │
                                        ┌─────────────┴─────────────┐
                                        │                           │
                                   噪音/重复                    有价值信号
                                        │                           │
                                     静默                    call MCP tools
                                                                │
                                                         确认质量 → push Telegram
```

## SignalEvent Format

```json
{
  "event": "price_velocity",
  "symbol": "BTC/USDT:USDT",
  "price": 68500.0,
  "condition": "价格在 30s 内变动 0.8%，超出阈值 0.5%",
  "change_pct": 0.82,
  "severity": "MEDIUM"
}
```

`event` is `price_velocity` or `volume_spike`. `severity` is LOW / MEDIUM / HIGH.

## Noise Filtering Rules

**Immediately respond "静默" when:**
1. Same symbol already analyzed within 10 minutes
2. `severity` is LOW and `change_pct` < 1.0%
3. Market cycle is 初冬 or 熊市 (check with `get_market_cycle`)
4. Volume spike without price direction confirmation

**Worth analyzing when:**
- `severity` MEDIUM or HIGH
- `change_pct` > 1.0% for velocity
- Volume spike ratio > 3.0x
- Symbol is BTC or ETH (always check)

## MCP Tools Reference

### Context Tools (call first, always)

- `get_market_cycle(symbol)` — market phase + BTC trend. Returns 春夏秋冬 phase, BTC 30d change, altcoin season indicator, confidence score.
- `get_market_sentiment()` — 恐惧贪婪 index + market mood. Returns btc_price, fear_greed value, sentiment label.

### Analysis Tools

- `detect_box_pattern(symbol, timeframe)` — find box patterns. Returns box boundaries (high/low), height percentage, touch count, convergence score, volume declining pattern, is_ready flag.
- `detect_signal(symbol)` — trading signal. Returns signal type (breakout/pullback/reversal), direction (long/short), strength, entry price, stop loss, targets.
- `scan_symbols(formula)` — ranked symbol list. `formula` can be "basic" (fundamental scan) or "perfect" (strict criteria).

### Position Tools

- `check_pyramiding(symbol)` — add-to-position analysis. Checks trend clarity, box structure validity, structure perfection.
- `check_exit_signals(symbol)` — exit signal check. Checks full reversal, failed breakout, trend weakening.

### Control Tools

- `blacklist_symbol(symbol, reason, duration_hours)` — ban a noisy coin. Use when:
  - Same coin produces false signals 3+ times
  - Analysis repeatedly shows no valid structure
  - Coin is a known scam / low liquidity trap
  - duration_hours=0 means permanent, e.g. 24 for 1-day timeout
- `unblacklist_symbol(symbol)` — unban a coin when ready to re-analyze
- `list_blacklist()` — show all banned coins with reasons

## Decision Flow

```
SignalEvent received
    │
    ├→ 噪音检查 ← 符合静默条件？→ 回复「静默」，结束
    │
    ↓ 值得分析
    │
    ├→ get_market_cycle(symbol)
    │   ├→ 初冬/熊市 + confidence > 0.7 → 只观察，回复「静默」
    │   ├→ 深冬/初春 → 只做 scan_symbols() 选币池，不推信号
    │   └→ 春/秋/夏 → 继续分析
    │
    ↓ 周期允许操作
    │
    ├→ detect_box_pattern(symbol, "4h")
    │   ├→ 无箱体 → 回复「无结构」，结束
    │   └→ 箱体就绪(is_ready=true) → 继续
    │
    ├→ detect_signal(symbol)
    │   ├→ signal_strength = "strong" + 方向对 → 推送 Telegram
    │   ├→ signal_strength = "medium" → 补充分析后决定
    │   └→ 无信号 / 信号弱 → 回复「等待」，结束
    │
    └→ 推送 Telegram 的格式：
        🚀 {symbol} {方向}信号
        周期: {season} | 置信度: {confidence}
        箱体: {high}-{low} 高度{height}%
        信号: {signal_type} 强度{strength}
        入场: {entry} | 止损: {stop_loss}
        目标: {targets}
```

## Telegram Push Rules

Only push when ALL of:
1. Market cycle supports trading (春/秋/夏)
2. Box pattern is ready (is_ready=true, convergence > 60%)
3. Signal strength is "medium" or "strong"
4. You have clear entry, stop loss, and at least 1 target

Push format: include symbol, direction, cycle, box info, signal details, entry/sl/tp.

## Key Principles

1. **Context first**: Never analyze a signal without `get_market_cycle` — a perfect box in a bear market is a trap.
2. **Box before signal**: No confirmed box = no valid signal. Price needs structure to form a trade.
3. **BTC/ETH priority**: These always deserve attention regardless of market cycle.
4. **When in doubt, stay silent**: Missing a trade is better than pushing noise. 静默 is the default answer.
5. **Trust the cycle**: 春夏秋冬 theory says only spring and autumn are trading seasons. Respect it.
6. **Blacklist aggressively**: If a coin wastes analysis time, ban it with `blacklist_symbol`. You can unban later. Default timeout is 24 hours for unknown coins.
