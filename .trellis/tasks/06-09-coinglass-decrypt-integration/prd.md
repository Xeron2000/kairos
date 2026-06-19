# Integrate CoinGlass Decrypted Market Data

## Goal

Use the local `/home/xeron/Coding/coinglass-decrypt/` findings to enrich Kairos/Hermes with optional CoinGlass market context, especially RSI hot/oversold coins.

## Scope

- Add a Kairos-owned CoinGlass encrypted response client.
- Expose verified CoinGlass context through the primary `kairos-mcp` server used by Hermes.
- Keep CoinGlass as best-effort context and scoring evidence only; Kairos must still operate when CoinGlass is unavailable.
- Add tests for decryption, normalization, and MCP graceful-degradation behavior.

## Verified Endpoints

- `/api/spot/rsi/list`: spot RSI list with 15m/1h/4h/12h/24h.
- `/api/index/rsiMap`: broader RSI map with 5m and 1w fields.
- `/api/fundingRate/rank`: extreme funding rate rank.
- `/api/fundingRate/avg`: BTC/ETH aggregate funding.
- `/api/fundingRate/list`: per-symbol per-exchange funding list.
- `/api/futures/top/coins/tickers`: futures ticker/OI/funding/volume context.
- `/api/openInterest/info?symbol=BTC`: per-exchange OI context for a base symbol.
- `/api/futures/longShortRate?timeType=2&symbol=BTC`: long/short flow context.
- `/api/futures/liquidation/today?symbol=BTC`: current-day liquidation context.

## Non-Goals

- No trade execution.
- No claim that CoinGlass data alone makes a signal profitable.
- No hard dependency on reverse-engineered endpoints for the main scanner.
- No broad arbitrary internal endpoint proxy.

## Acceptance

- Unit tests pass for synthetic encrypted payload round-trip.
- MCP tools return `success=false` with clear errors instead of raising on upstream failures.
- Hermes can call RSI hot coins and single-symbol context directly from the main MCP server.
