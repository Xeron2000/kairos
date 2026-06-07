"""Tests for scanner-first architecture baseline behavior."""

from types import SimpleNamespace

import numpy as np

from kairos.scanner import Direction, MarketScanner, analyze_symbol_setup, scan_market


class FakeBlacklist:
    """Blacklist stub that never blocks symbols."""

    def is_blocked(self, symbol: str) -> bool:
        return False


class FakeExchange:
    """Small synchronous exchange fake for scanner tests."""

    def __init__(self, tickers=None, ohlcv=None):
        self._tickers = tickers or {}
        self._ohlcv = ohlcv or {}

    def fetch_tickers(self):
        return self._tickers

    def fetch_ticker(self, symbol):
        return self._tickers.get(symbol, {})

    def fetch_ohlcv(self, symbol, timeframe, limit=100, params=None):
        return self._ohlcv.get((symbol, timeframe))


class RaisingExchange(FakeExchange):
    """Exchange fake that raises from selected data methods."""

    def __init__(self, *, raise_tickers=False, raise_ticker=False, raise_ohlcv=False, tickers=None, ohlcv=None):
        super().__init__(tickers=tickers, ohlcv=ohlcv)
        self.raise_tickers = raise_tickers
        self.raise_ticker = raise_ticker
        self.raise_ohlcv = raise_ohlcv

    def fetch_tickers(self):
        if self.raise_tickers:
            raise RuntimeError("ticker stream unavailable")
        return super().fetch_tickers()

    def fetch_ticker(self, symbol):
        if self.raise_ticker:
            raise RuntimeError("ticker unavailable")
        return super().fetch_ticker(symbol)

    def fetch_ohlcv(self, symbol, timeframe, limit=100, params=None):
        if self.raise_ohlcv:
            raise RuntimeError("ohlcv unavailable")
        return super().fetch_ohlcv(symbol, timeframe, limit=limit, params=params)


def _exchange_getter(fake_exchange):
    return lambda _name: SimpleNamespace(exchange=fake_exchange)


def _exchange_getter_map(exchanges):
    return lambda name: SimpleNamespace(exchange=exchanges[name])


def _make_ohlcv(start: float = 100.0, step: float = 0.2, n: int = 120, last_volume_multiplier: float = 1.0):
    timestamps = np.arange(n, dtype=float) * 60_000
    closes = start + np.arange(n, dtype=float) * step
    opens = closes - step / 2
    highs = closes * 1.01
    lows = closes * 0.99
    volumes = np.full(n, 1_000_000.0)
    volumes[-1] *= last_volume_multiplier
    return np.column_stack([timestamps, opens, highs, lows, closes, volumes]).tolist()


def _make_range_ohlcv(high: float, low: float, close: float, n: int = 120, last_volume_multiplier: float = 1.0):
    timestamps = np.arange(n, dtype=float) * 60_000
    highs = np.full(n, high, dtype=float)
    lows = np.full(n, low, dtype=float)
    closes = np.full(n, close, dtype=float)
    opens = np.full(n, close, dtype=float)
    volumes = np.full(n, 1_000_000.0)
    volumes[-1] *= last_volume_multiplier
    return np.column_stack([timestamps, opens, highs, lows, closes, volumes]).tolist()


def _ticker(symbol: str, quote_volume: float, percentage: float = 3.0):
    return {
        "symbol": symbol,
        "last": 100.0,
        "quoteVolume": quote_volume,
        "percentage": percentage,
        "openInterest": 10_000_000.0,
        "fundingRate": 0.0001,
    }


def test_scan_market_returns_candidates_but_withholds_setups_without_btc_context():
    """BTC context failure should not fail candidate scan, but must block trade setups."""
    tickers = {
        f"COIN{i}/USDT:USDT": _ticker(f"COIN{i}/USDT:USDT", quote_volume=(100 - i) * 10_000_000)
        for i in range(35)
    }
    tickers["DOGE/USDT"] = _ticker("DOGE/USDT", quote_volume=1_000_000_000)
    fake_exchange = FakeExchange(tickers=tickers)

    result = scan_market(
        config={},
        exchange_getter=_exchange_getter(fake_exchange),
        blacklist=FakeBlacklist(),
    )

    assert result["success"] is True
    assert result["schema_version"] == "1.0"
    assert result["symbol"] is None
    assert result["data"]["universe"]["requested_size"] == 30
    assert result["data"]["universe"]["actual_size"] == 30
    assert len(result["data"]["candidates"]) == 20
    assert result["data"]["setups"] == []
    assert result["data"]["qualified_setups"] == []
    assert result["data"]["scanner_policy"]["websocket_role"] == "candidate_hint_only"
    assert result["data"]["scanner_policy"]["execution_enabled"] is False
    assert all(candidate["symbol"].endswith(":USDT") for candidate in result["data"]["candidates"])
    assert all("ticker" not in candidate for candidate in result["data"]["candidates"])
    assert any("BTC 1d OHLCV unavailable" in warning for warning in result["warnings"])


def test_scan_market_uses_backup_when_primary_has_no_candidates():
    """Binance/Bybit can serve as backup when the OKX primary universe is unavailable."""
    backup_symbol = "BACKUP/USDT:USDT"
    fake_okx = FakeExchange(tickers={})
    fake_binance = FakeExchange(tickers={backup_symbol: _ticker(backup_symbol, quote_volume=300_000_000)})

    result = scan_market(
        config={},
        exchange_getter=_exchange_getter_map({"okx": fake_okx, "binance": fake_binance}),
        blacklist=FakeBlacklist(),
    )

    assert result["success"] is True
    assert result["data"]["exchange"] == "binance"
    assert result["data"]["universe"]["actual_size"] == 1
    assert result["data"]["candidates"][0]["symbol"] == backup_symbol
    assert any("using binance backup universe" in warning for warning in result["warnings"])


def test_scan_market_returns_envelope_when_ticker_fetch_raises():
    """Ticker API failures should not escape the standardized MCP envelope."""
    result = scan_market(
        config={},
        exchange_getter=_exchange_getter(RaisingExchange(raise_tickers=True)),
        exchange="okx",
        blacklist=FakeBlacklist(),
    )

    assert result["success"] is True
    assert result["schema_version"] == "1.0"
    assert result["data"]["candidates"] == []
    assert result["data"]["setups"] == []
    assert result["data"]["qualified_setups"] == []
    assert any("did not return ticker data" in warning for warning in result["warnings"])


def test_analyze_symbol_setup_liquidity_gate_prevents_trade_candidate():
    """Manual symbols below the liquidity threshold cannot become trade candidates."""
    fake_exchange = FakeExchange(
        tickers={
            "LOW/USDT:USDT": _ticker("LOW/USDT:USDT", quote_volume=1_000_000),
        }
    )

    result = analyze_symbol_setup(
        "lowusdt",
        config={},
        exchange_getter=_exchange_getter(fake_exchange),
        blacklist=FakeBlacklist(),
    )

    setup = result["data"]["setup"]
    assert result["success"] is True
    assert result["symbol"] == "LOW/USDT:USDT"
    assert setup["action_state"] in {"watch", "no_trade"}
    assert setup["action_state"] != "trade_candidate"
    assert setup["risk"]["account_sizing"] is False
    assert any("below minimum" in warning for warning in result["warnings"])


def test_analyze_symbol_setup_returns_envelope_when_ticker_fetch_raises():
    """Manual analysis should degrade to no-trade instead of raising from ticker failures."""
    result = analyze_symbol_setup(
        "ETH/USDT",
        config={},
        exchange_getter=_exchange_getter(RaisingExchange(raise_ticker=True)),
        blacklist=FakeBlacklist(),
    )

    setup = result["data"]["setup"]
    assert result["success"] is True
    assert result["symbol"] == "ETH/USDT:USDT"
    assert setup["action_state"] == "no_trade"
    assert setup["risk"]["triggered"] is False
    assert setup["risk"]["near_trigger"] is False
    assert any("below minimum" in warning for warning in result["warnings"])


def test_analyze_symbol_setup_returns_envelope_when_ohlcv_fetch_raises():
    """OHLCV failures should withhold setup scoring but keep the response contract."""
    symbol = "ETH/USDT:USDT"
    result = analyze_symbol_setup(
        symbol,
        config={},
        exchange_getter=_exchange_getter(
            RaisingExchange(
                raise_ohlcv=True,
                tickers={symbol: _ticker(symbol, quote_volume=300_000_000)},
            )
        ),
        blacklist=FakeBlacklist(),
    )

    setup = result["data"]["setup"]
    assert result["success"] is True
    assert setup["action_state"] == "watch"
    assert setup["risk"]["triggered"] is False
    assert setup["risk"]["near_trigger"] is False
    assert any("BTC 1d OHLCV unavailable" in warning for warning in result["warnings"])


def test_analyze_symbol_setup_rejects_non_usdt_symbol():
    """Manual analysis requires a canonicalizable USDT perpetual symbol."""
    result = analyze_symbol_setup(
        "BTC/USD",
        config={},
        exchange_getter=_exchange_getter(FakeExchange()),
        blacklist=FakeBlacklist(),
    )

    assert result["success"] is False
    assert result["symbol"] is None
    assert result["errors"] == ["unsupported symbol format: BTC/USD"]


def test_short_risk_reward_requires_positive_target():
    """Short setups must not score RR from zero or negative targets."""
    scanner = MarketScanner(config={})
    risk = scanner._risk_bounds(
        Direction.SHORT,
        "ALT/USDT:USDT",
        {"high": 2.0, "low": 1.0, "height": 1.0},
        current_price=0.99,
        phase="winter",
        btc_trend="down",
    )

    assert risk["targets"] == []
    assert risk["risk_reward_target"] is None
    assert risk["risk_reward"] == 0.0


def test_analyze_symbol_setup_dedupes_btc_context_warnings():
    """BTC context warnings should not be duplicated between setup and envelope."""
    symbol = "ETH/USDT:USDT"
    fake_exchange = FakeExchange(tickers={symbol: _ticker(symbol, quote_volume=300_000_000)})

    result = analyze_symbol_setup(
        symbol,
        config={},
        exchange_getter=_exchange_getter(fake_exchange),
        blacklist=FakeBlacklist(),
    )

    matching = [warning for warning in result["warnings"] if "BTC 1d OHLCV unavailable" in warning]
    assert len(matching) == 1
    assert result["data"]["setup"]["action_state"] == "watch"


def test_analyze_symbol_setup_returns_signal_only_structure_with_complete_data():
    """Complete data returns setup analysis, chart spec, and signal-only risk bounds."""
    btc = "BTC/USDT:USDT"
    symbol = "ETH/USDT:USDT"
    ohlcv = {
        (btc, "1d"): _make_ohlcv(start=80_000, step=100, n=120),
        (symbol, "1d"): _make_ohlcv(start=3000, step=4, n=120),
        (symbol, "4h"): _make_ohlcv(start=3100, step=1, n=120),
        (symbol, "15m"): _make_ohlcv(start=3180, step=1, n=120, last_volume_multiplier=2.0),
    }
    fake_exchange = FakeExchange(
        tickers={
            symbol: _ticker(symbol, quote_volume=300_000_000, percentage=5.0),
        },
        ohlcv=ohlcv,
    )

    result = analyze_symbol_setup(
        "ETH/USDT",
        config={},
        exchange_getter=_exchange_getter(fake_exchange),
        blacklist=FakeBlacklist(),
    )

    setup = result["data"]["setup"]
    assert result["success"] is True
    assert result["symbol"] == symbol
    assert setup["action_state"] in {"no_trade", "watch", "prepare", "trade_candidate"}
    assert setup["execution"]["enabled"] is False
    assert setup["risk"]["account_sizing"] is False
    assert setup["risk"]["max_position_pct"] <= 33.0
    assert setup["risk"]["max_leverage"] <= 10.0
    assert setup["chart_spec"]["generate_now"] is False
    assert "candidate_score" in result["score"]
    assert "setup_score" in result["score"]


def test_analyze_symbol_setup_can_reach_trade_candidate(monkeypatch):
    """A complete deterministic setup should be able to close the trade_candidate path."""
    monkeypatch.setattr("kairos.scanner.BoxDetector.detect", lambda *args, **kwargs: [])

    btc = "BTC/USDT:USDT"
    symbol = "ETH/USDT:USDT"
    ohlcv = {
        (btc, "1d"): _make_ohlcv(start=80_000, step=100, n=120),
        (symbol, "1d"): _make_ohlcv(start=100, step=1, n=120),
        (symbol, "4h"): _make_range_ohlcv(high=115.0, low=100.0, close=114.0, n=120),
        (symbol, "15m"): _make_range_ohlcv(
            high=116.5,
            low=115.0,
            close=116.0,
            n=120,
            last_volume_multiplier=2.0,
        ),
    }
    fake_exchange = FakeExchange(
        tickers={symbol: _ticker(symbol, quote_volume=500_000_000, percentage=8.0)},
        ohlcv=ohlcv,
    )

    result = analyze_symbol_setup(
        symbol,
        config={},
        exchange_getter=_exchange_getter(fake_exchange),
        blacklist=FakeBlacklist(),
    )

    setup = result["data"]["setup"]
    assert setup["action_state"] == "trade_candidate"
    assert setup["direction"] == "long"
    assert setup["setup_score"] >= setup["threshold"]
    assert setup["risk"]["risk_reward"] >= setup["required_risk_reward"]
    assert setup["risk"]["risk_reward_target"] == setup["risk"]["targets"][-1]
    assert setup["execution"]["enabled"] is False
