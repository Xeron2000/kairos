# MCP Scanner Contracts

## Scenario: Architecture Baseline Phase 1 Scanner

### 1. Scope / Trigger

- Trigger: changes to MCP response contracts, high-level scanner tool signatures, deterministic scoring boundaries, and architecture config sections.
- Applies to the primary MCP server and scanner service code under `src/kairos/`.
- `docs/architecture.md` remains the product/architecture source of truth; this spec captures implementation contracts.

### 2. Signatures

- MCP tool: `scan_market(exchange: str = "") -> dict[str, Any]`
- MCP tool: `analyze_symbol_setup(symbol: str, exchange: str = "") -> dict[str, Any]`
- Service callable: `kairos.scanner.scan_market(config=None, exchange_getter=None, exchange=None, blacklist=None) -> dict[str, Any]`
- Service callable: `kairos.scanner.analyze_symbol_setup(symbol, config=None, exchange_getter=None, exchange=None, blacklist=None) -> dict[str, Any]`
- Config loader: `load_architecture_config(config: Mapping[str, Any] | None = None) -> KairosArchitectureConfig`

### 3. Contracts

- Core MCP envelope fields: `success`, `schema_version`, `timestamp`, `symbol`, `data`, `score`, `reasons`, `warnings`, `errors`.
- Symbol format: all scanner entry points normalize user input to `BASE/USDT:USDT`.
- Scanner defaults: OKX primary exchange, Top 30 futures universe, Top 20 candidates, Top 10 deep analyses, timeframes `1d`, `4h`, `15m`.
- Scoring ownership: Kairos deterministic code produces `candidate_score` and `setup_score`; LLM/Hermes may veto only.
- Action states: `no_trade`, `watch`, `prepare`, `trade_candidate`.
- Risk output is bounded guidance only: max position percentage, max leverage, entry zone, structural stop, targets, RR, invalidation. It must not include account-equity sizing or order placement.
- Chart behavior: scanner returns `chart_spec`; scans do not generate chart files by default.

### 4. Validation & Error Matrix

- Missing/invalid symbol -> `success=false`, standardized envelope, error message in `errors`.
- Exchange initialization failure -> `success=false`, standardized envelope, no candidates or setups.
- BTC `1d` context missing in `scan_market` -> `success=true`, candidates may be returned, `qualified_setups=[]`, warning explains setups were withheld.
- Manual symbol below `minimumLiquidityQuoteVolume` -> `success=true`, action state `watch` or `no_trade`, never `trade_candidate`.
- Required timeframe missing for a candidate -> setup action state `watch`, warning lists missing timeframes.
- Setup score below threshold or RR below requirement -> never `trade_candidate`.

### 5. Good/Base/Bad Cases

- Good: high-liquidity symbol with BTC context, usable 4H structure, 15m trigger, sufficient RR -> eligible for `trade_candidate`.
- Base: liquid symbol without trigger -> `watch` or `prepare` with chart spec and risk bounds.
- Bad: missing BTC context or below-liquidity symbol -> no trade candidate even if ticker movement looks interesting.

### 6. Tests Required

- Envelope helper includes all standard fields and preserves `symbol`, `data`, `score`, `reasons`, `warnings`, `errors`.
- Symbol normalization covers `BTC/USDT`, `BTCUSDT`, and `BTC/USDT:USDT`.
- Config tests assert scanner/scoring/risk/storage/chart/webhook defaults.
- Scanner tests assert BTC-context failure withholds setups and liquidity gate blocks `trade_candidate`.
- MCP server tests assert high-level tools delegate and preserve the standardized envelope.

### 7. Wrong vs Correct

#### Wrong

```python
return {"success": True, "signal": {"action": "buy now", "position_size": "10000 USDT"}}
```

#### Correct

```python
return make_mcp_envelope(
    success=True,
    symbol="BTC/USDT:USDT",
    data={"setup": {"action_state": "prepare", "risk": {"account_sizing": False}}},
    score={"setup_score": 5.8},
    warnings=["15m trigger not active"],
)
```

## Scenario: Legacy Symbol Scan and Webhook Regression Contracts

### 1. Scope / Trigger

- Trigger: changes to legacy MCP tools in `src/kairos/mcp_server.py`, Hermes webhook payload fields, or `kairos-mcp` launcher dependencies.
- Applies to `scan_symbols`, `SignalEvent.to_payload()`, HMAC signing, `main()`, `pyproject.toml`, `uv.lock`, and `run.sh`.
- This scenario protects install/startup and candidate-filter regressions while the scanner-first `scan_market` surface continues to evolve.

### 2. Signatures

- MCP tool: `scan_symbols(exchange="okx", min_volume=80000000, min_oi=25000000, min_age=45, max_volatility=6.0, formula="basic") -> dict[str, Any]`
- Webhook payload builder: `SignalEvent.to_payload() -> dict[str, Any]`
- Webhook signer: `_sign(payload: dict, secret: str) -> str`
- Entrypoint: `kairos-mcp = "kairos.mcp_server:main"`; launcher: `run.sh` invokes `uv run --directory "$SCRIPT_DIR" kairos-mcp`.

### 3. Contracts

- `scan_symbols` must only scan active USDT derivative markets when market metadata exposes type flags; spot markets must not be accepted when explicitly marked as spot.
- `scan_symbols` must enforce `min_volume`, `min_oi`, and `max_volatility` before returning candidates.
- `scan_symbols` may derive `min_age` from common market metadata fields (`created`, `timestamp`, `listedAt`, `listingTime`, or exchange `info` equivalents). If age metadata is absent, it must return a warning and must not pretend age filtering happened.
- Candidate entries include `symbol`, `volume_24h`, `open_interest`, `age_days`, `price`, `change_24h_pct`, and `score` for the `perfect` formula.
- `SignalEvent.to_payload()` must include `severity` and `change_pct` because Hermes uses them to prioritize anomaly hints.
- HMAC signing uses compact canonical JSON via `json.dumps(payload, separators=(",", ":"), ensure_ascii=False)`.
- Because `kairos-mcp` imports `mcp.server.fastmcp`, webhook imports `httpx`, and the entrypoint uses `anyio.run` at runtime, `mcp`, `httpx`, and `anyio` are base dependencies, not only optional extras or transitive assumptions.

### 4. Validation & Error Matrix

- Exchange factory unavailable -> `scan_symbols` returns `success=false` with an error.
- `load_markets` raises -> `scan_symbols` returns `success=false` with the exception message.
- Per-symbol ticker/OI fetch raises -> that symbol is skipped and the scan continues.
- Volume below `min_volume`, OI below `min_oi`, or `abs(percentage) > max_volatility` -> candidate is excluded.
- Age metadata present and age below `min_age` -> candidate is excluded.
- Age metadata absent and `min_age > 0` -> candidate may be filtered by supported filters, response includes a warning and `summary.min_age_unsupported`.
- Config load failure in `main()` -> server starts with `{}` config and still constructs `DataManager`.

### 5. Good/Base/Bad Cases

- Good: active USDT swap with sufficient quote volume, OI, acceptable volatility, and age metadata older than `min_age` -> returned candidate.
- Base: active USDT market with no listing-age metadata -> returned only if supported filters pass, with unsupported-age warning.
- Bad: low volume/OI, excessive volatility, explicit spot market, inactive market, or too-new market with known listing timestamp -> excluded.

### 6. Tests Required

- Mock-based `scan_symbols` tests must assert `min_volume`, `min_oi`, `max_volatility`, supported `min_age`, and unsupported `min_age` warning behavior.
- Mock-based OI tests must cover ticker-provided OI, `fetch_open_interest`, and fetch failure.
- Webhook tests must assert `severity` and `change_pct` are included in payload and covered by canonical HMAC signing.
- Entrypoint/dependency tests must assert `mcp`, `httpx`, and `anyio` are base runtime dependencies and `run.sh` does not need `--extra hermes` to start `kairos-mcp`.
- Coverage checks for this area must keep `src/kairos/mcp_server.py` at or above 80%.

### 7. Wrong vs Correct

#### Wrong

```python
if vol >= min_volume:
    candidates.append({"open_interest": ticker.get("openInterest") or 0})
# min_oi, max_volatility, and min_age are only echoed in the response.
```

#### Correct

```python
open_interest = _open_interest(exchange, symbol, ticker)
age_days = _market_age_days(market)
if vol < min_volume or open_interest < min_oi or abs(change) > max_volatility:
    continue
if age_days is None:
    warnings.append("min_age is unsupported for symbols without listing metadata")
elif age_days < min_age:
    continue
```
