"""Regression tests for MCP server P0/P1 behavior and coverage."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

import kairos.mcp_server as mcp_server
from kairos.mcp_server import (
    _fetch_ohlcv,
    _funding_rate,
    _get_exchange,
    _market_age_days,
    _normalize_symbol,
    _open_interest,
    _safe_float,
    analyze_symbol_setup,
    blacklist_symbol,
    check_exit_signals,
    check_pyramiding,
    detect_box_pattern,
    detect_signal,
    get_market_cycle,
    get_market_sentiment,
    list_blacklist,
    main,
    scan_market,
    scan_symbols,
    state,
    unblacklist_symbol,
)


class DummyBox:
    """Minimal box object used by MCP tool branch tests."""

    def __init__(self, is_ready: bool = True):
        self.status = SimpleNamespace(value="ready" if is_ready else "forming")
        self.high = 110.0
        self.low = 100.0
        self.height = 10.0
        self.height_pct = 10.0
        self.midpoint = 105.0
        self.touch_high = 3
        self.touch_low = 3
        self.second_test_high = True
        self.second_test_low = True
        self.convergence_pct = 0.82
        self.volume_declining = True
        self.is_ready = is_ready


def make_ohlcv(price: float = 100.0, n: int = 60, trend: float = 0.0, bearish_last: bool = False) -> dict:
    """Build OHLCV dict in the shape returned by mcp_server._fetch_ohlcv."""
    timestamps = np.arange(n, dtype=float)
    closes = price + np.arange(n, dtype=float) * trend
    opens = closes - 1.0
    highs = closes + 2.0
    lows = closes - 2.0
    volumes = np.full(n, 1_000_000.0, dtype=float)
    if bearish_last:
        opens[-1] = closes[-1] * 1.05
        highs[-3:] = [120.0, 115.0, 110.0]
    return {
        "timestamps": timestamps,
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "closes": closes,
        "volumes": volumes,
    }


def make_exchange(markets: dict, tickers: dict | None = None, ohlcv=None):
    """Create wrapped exchange mock returned by _get_exchange."""
    client = MagicMock()
    client.load_markets.return_value = markets
    client.fetch_ticker.side_effect = lambda symbol: (tickers or {}).get(symbol, {})
    client.fetch_ohlcv.return_value = ohlcv or []
    client.has = {}
    return MagicMock(exchange=client)


def test_helper_normalize_symbol_and_safe_float():
    assert _normalize_symbol("BTC/USDT") == "BTC/USDT:USDT"
    assert _normalize_symbol("BTC/USDT:USDT") == "BTC/USDT:USDT"
    assert _normalize_symbol("BTCUSDT") == "BTCUSDT"
    assert _safe_float("12.5") == 12.5
    assert _safe_float(None, 7.0) == 7.0
    assert _safe_float("bad", 3.0) == 3.0


def test_get_exchange_returns_none_on_factory_error():
    with patch("kairos.utils.get_exchange.get_exchange", side_effect=RuntimeError("boom")):
        assert _get_exchange("okx") is None


def test_fetch_ohlcv_success_empty_and_exception_paths():
    exchange = make_exchange({}, ohlcv=[[1, 10, 12, 9, 11, 100]])
    with patch("kairos.mcp_server._get_exchange", return_value=exchange):
        result = _fetch_ohlcv("BTC/USDT")
    assert result is not None
    assert result["closes"].tolist() == [11.0]
    exchange.exchange.fetch_ohlcv.assert_called_once_with("BTC/USDT:USDT", "1d", limit=100)

    exchange.exchange.fetch_ohlcv.return_value = []
    with patch("kairos.mcp_server._get_exchange", return_value=exchange):
        assert _fetch_ohlcv("BTC/USDT") is None

    exchange.exchange.fetch_ohlcv.side_effect = RuntimeError("exchange down")
    with patch("kairos.mcp_server._get_exchange", return_value=exchange):
        assert _fetch_ohlcv("BTC/USDT") is None

    with patch("kairos.mcp_server._get_exchange", return_value=None):
        assert _fetch_ohlcv("BTC/USDT") is None


def test_funding_rate_success_and_failure_paths():
    exchange = make_exchange({})
    exchange.exchange.fetch_funding_rate.return_value = {"info": {"fundingRate": "0.012"}}
    with patch("kairos.mcp_server._get_exchange", return_value=exchange):
        assert _funding_rate("BTC/USDT") == "0.012"

    exchange.exchange.fetch_funding_rate.side_effect = RuntimeError("no funding")
    with patch("kairos.mcp_server._get_exchange", return_value=exchange):
        assert _funding_rate("BTC/USDT") is None

    with patch("kairos.mcp_server._get_exchange", return_value=None):
        assert _funding_rate("BTC/USDT") is None


def test_market_age_days_supports_metadata_and_missing_metadata():
    listed = datetime.now(timezone.utc) - timedelta(days=60)
    created_age = _market_age_days({"created": listed.timestamp() * 1000})
    info_age = _market_age_days({"info": {"listTime": str(listed.timestamp() * 1000)}})
    assert created_age is not None and created_age >= 59
    assert info_age is not None and info_age >= 59
    assert _market_age_days({}) is None
    assert _market_age_days({"created": "not-a-time"}) is None


def test_open_interest_from_ticker_fetch_and_failure():
    client = MagicMock()
    assert _open_interest(client, "BTC/USDT", {"openInterestValue": "123"}) == 123.0

    client.has = {"fetchOpenInterest": True}
    client.fetch_open_interest.return_value = {"openInterestAmount": "456"}
    assert _open_interest(client, "BTC/USDT", {}) == 456.0

    client.fetch_open_interest.side_effect = RuntimeError("unsupported")
    assert _open_interest(client, "BTC/USDT", {}) == 0.0

    client.has = {"fetchOpenInterest": False}
    assert _open_interest(client, "BTC/USDT", {}) == 0.0


def test_scan_symbols_applies_volume_oi_volatility_and_age_warning():
    markets = {
        "HIGH/USDT": {"quote": "USDT", "active": True},
        "LOWVOL/USDT": {"quote": "USDT", "active": True},
        "LOWOI/USDT": {"quote": "USDT", "active": True},
        "WILD/USDT": {"quote": "USDT", "active": True},
        "SPOT/BTC": {"quote": "BTC", "active": True},
        "SPOT/USDT": {"quote": "USDT", "active": True, "spot": True},
        "LEGACYSPOT/USDT": {"quote": "USDT", "active": True, "type": "spot"},
    }
    tickers = {
        "HIGH/USDT": {"last": 10, "quoteVolume": 200, "percentage": 3, "openInterest": 80},
        "LOWVOL/USDT": {"last": 10, "quoteVolume": 20, "percentage": 3, "openInterest": 80},
        "LOWOI/USDT": {"last": 10, "quoteVolume": 200, "percentage": 3, "openInterest": 10},
        "WILD/USDT": {"last": 10, "quoteVolume": 200, "percentage": 12, "openInterest": 80},
        "SPOT/USDT": {"last": 10, "quoteVolume": 500, "percentage": 1, "openInterest": 500},
        "LEGACYSPOT/USDT": {"last": 10, "quoteVolume": 500, "percentage": 1, "openInterest": 500},
    }
    exchange = make_exchange(markets, tickers)

    with patch("kairos.mcp_server._get_exchange", return_value=exchange):
        result = scan_symbols(min_volume=100, min_oi=50, max_volatility=6, min_age=45)

    assert result["success"] is True
    assert [candidate["symbol"] for candidate in result["candidates"]] == ["HIGH/USDT"]
    assert result["summary"]["total_scanned"] == 4
    assert result["summary"]["min_age_unsupported"] == 4
    assert "min_age is unsupported" in result["warnings"][0]


def test_scan_symbols_filters_by_supported_age_sorts_and_scores():
    old = (datetime.now(timezone.utc) - timedelta(days=90)).timestamp() * 1000
    new = (datetime.now(timezone.utc) - timedelta(days=3)).timestamp() * 1000
    markets = {
        "OLD/USDT": {"quote": "USDT", "active": True, "created": old},
        "NEW/USDT": {"quote": "USDT", "active": True, "created": new},
        "BIGGER/USDT": {"quote": "USDT", "active": True, "created": old},
    }
    tickers = {
        "OLD/USDT": {"last": 10, "quoteVolume": 200, "percentage": 1, "openInterest": 80},
        "NEW/USDT": {"last": 10, "quoteVolume": 900, "percentage": 1, "openInterest": 80},
        "BIGGER/USDT": {"last": 10, "quoteVolume": 500, "percentage": 2, "openInterest": 80},
    }
    exchange = make_exchange(markets, tickers)

    with patch("kairos.mcp_server._get_exchange", return_value=exchange):
        result = scan_symbols(min_volume=100, min_oi=50, max_volatility=6, min_age=45, formula="perfect")

    assert [candidate["symbol"] for candidate in result["candidates"]] == ["BIGGER/USDT", "OLD/USDT"]
    assert result["summary"]["min_age_supported"] == 3
    assert result["summary"]["min_age_unsupported"] == 0
    assert result["warnings"] == []
    assert all(candidate["score"] is not None for candidate in result["candidates"])


def test_scan_symbols_uses_fetch_open_interest_when_ticker_lacks_oi():
    markets = {"BTC/USDT": {"quote": "USDT", "active": True}}
    tickers = {"BTC/USDT": {"last": 10, "quoteVolume": 200, "percentage": 1}}
    exchange = make_exchange(markets, tickers)
    exchange.exchange.has = {"fetchOpenInterest": True}
    exchange.exchange.fetch_open_interest.return_value = {"openInterestValue": "75"}

    with patch("kairos.mcp_server._get_exchange", return_value=exchange):
        result = scan_symbols(min_volume=100, min_oi=50, max_volatility=6, min_age=0)

    assert result["candidates"][0]["open_interest"] == 75.0


def test_scan_symbols_no_exchange_and_top_level_error_paths():
    with patch("kairos.mcp_server._get_exchange", return_value=None):
        assert scan_symbols()["success"] is False

    exchange = make_exchange({})
    exchange.exchange.load_markets.side_effect = RuntimeError("markets unavailable")
    with patch("kairos.mcp_server._get_exchange", return_value=exchange):
        result = scan_symbols()
    assert result == {"success": False, "error": "markets unavailable"}


def test_get_market_cycle_unknown_and_error_paths():
    with patch("kairos.mcp_server._fetch_ohlcv", return_value=None):
        result = get_market_cycle()
    assert result["success"] is True
    assert result["cycle"]["phase"] == "unknown"

    with patch("kairos.mcp_server._fetch_ohlcv", side_effect=RuntimeError("cycle exploded")):
        result = get_market_cycle()
    assert result == {"success": False, "error": "cycle exploded"}


def test_detect_box_pattern_no_pattern_ready_and_error_paths():
    ohlcv = make_ohlcv(n=20)
    detector = MagicMock()
    detector.detect.return_value = []
    with patch("kairos.mcp_server._fetch_ohlcv", return_value=ohlcv), patch.object(state, "box_detector", detector):
        result = detect_box_pattern("BTC/USDT")
    assert result["success"] is True
    assert result["box_pattern"]["status"] == "no_pattern"

    detector.detect.return_value = [DummyBox(is_ready=True)]
    with patch("kairos.mcp_server._fetch_ohlcv", return_value=ohlcv), patch.object(state, "box_detector", detector):
        result = detect_box_pattern("BTC/USDT")
    assert result["box_pattern"]["detected"] is True
    assert result["trading_implications"]["stop_loss_level"] == 99.0

    detector.detect.side_effect = RuntimeError("box failure")
    with patch("kairos.mcp_server._fetch_ohlcv", return_value=ohlcv), patch.object(state, "box_detector", detector):
        result = detect_box_pattern("BTC/USDT")
    assert result == {"success": False, "error": "box failure"}


def test_detect_signal_box_ready_medium_neutral_and_error_paths():
    ohlcv = make_ohlcv(n=50)
    detector = MagicMock()
    detector.detect.return_value = [DummyBox(is_ready=True)]
    with (
        patch("kairos.mcp_server._current_price", return_value=106.0),
        patch("kairos.mcp_server._fetch_ohlcv", return_value=ohlcv),
        patch("kairos.mcp_server._funding_rate", return_value=0.01),
        patch("kairos.mcp_server.SupportResistance") as sr_cls,
        patch.object(state, "box_detector", detector),
    ):
        sr_cls.return_value.find_levels.side_effect = RuntimeError("sr optional failure")
        result = detect_signal("BTC/USDT", strategy="box_breakout")
    assert result["success"] is True
    assert result["signal"]["strength"] == "high"
    assert result["analysis"]["has_box_pattern"] is True

    detector.detect.return_value = [DummyBox(is_ready=False)]
    with (
        patch("kairos.mcp_server._current_price", return_value=104.0),
        patch("kairos.mcp_server._fetch_ohlcv", return_value=ohlcv),
        patch("kairos.mcp_server._funding_rate", return_value=None),
        patch.object(state, "box_detector", detector),
    ):
        result = detect_signal("BTC/USDT", strategy="support_bounce")
    assert result["signal"]["strength"] == "medium"

    detector.detect.return_value = []
    with (
        patch("kairos.mcp_server._current_price", return_value=104.0),
        patch("kairos.mcp_server._fetch_ohlcv", return_value=ohlcv),
        patch.object(state, "box_detector", detector),
    ):
        result = detect_signal("BTC/USDT")
    assert result["signal"]["detected"] is False

    with patch("kairos.mcp_server._current_price", side_effect=RuntimeError("signal failure")):
        assert detect_signal("BTC/USDT") == {"success": False, "error": "signal failure"}


def test_check_pyramiding_ready_no_ohlcv_and_error_paths():
    detector = MagicMock()
    detector.detect.return_value = [DummyBox(is_ready=True)]
    with (
        patch("kairos.mcp_server._current_price", return_value=120.0),
        patch("kairos.mcp_server._fetch_ohlcv", return_value=make_ohlcv(price=100, n=50, trend=1.0)),
        patch.object(state, "box_detector", detector),
    ):
        result = check_pyramiding("BTC/USDT")
    assert result["pyramiding_conditions"]["all_conditions_met"] is True
    assert result["pyramiding_signal"]["ready"] is True

    with (
        patch("kairos.mcp_server._current_price", return_value=120.0),
        patch("kairos.mcp_server._fetch_ohlcv", return_value=None),
    ):
        result = check_pyramiding("BTC/USDT")
    assert result["pyramiding_conditions"]["all_conditions_met"] is False

    with patch("kairos.mcp_server._current_price", side_effect=RuntimeError("pyramid failure")):
        assert check_pyramiding("BTC/USDT") == {"success": False, "error": "pyramid failure"}


def test_check_exit_signals_reversal_trend_weakening_and_error_paths():
    with (
        patch("kairos.mcp_server._current_price", return_value=100.0),
        patch("kairos.mcp_server._fetch_ohlcv", return_value=make_ohlcv(n=10, bearish_last=True)),
    ):
        result = check_exit_signals("BTC/USDT")
    assert result["exit_signals"]["full_reversal"] is True
    assert result["exit_signals"]["trend_weakening"] is True
    assert result["exit_recommendation"]["action"] == "考虑减仓"

    with patch("kairos.mcp_server._current_price", side_effect=RuntimeError("exit failure")):
        assert check_exit_signals("BTC/USDT") == {"success": False, "error": "exit failure"}


def test_get_market_sentiment_branches_and_error_path():
    with (
        patch("kairos.mcp_server._current_price", return_value=130.0),
        patch("kairos.mcp_server._fetch_ohlcv", return_value=make_ohlcv(price=100, n=30)),
        patch("kairos.mcp_server._funding_rate", return_value=0.02),
    ):
        assert get_market_sentiment()["sentiment"]["overall"] == "bullish"

    with (
        patch("kairos.mcp_server._current_price", return_value=90.0),
        patch("kairos.mcp_server._fetch_ohlcv", return_value=make_ohlcv(price=100, n=30)),
        patch("kairos.mcp_server._funding_rate", return_value=None),
    ):
        result = get_market_sentiment()
    assert result["sentiment"]["overall"] == "bearish"
    assert result["indicators"]["funding_rate"] == 0.015

    with patch("kairos.mcp_server._current_price", side_effect=RuntimeError("sentiment failure")):
        assert get_market_sentiment() == {"success": False, "error": "sentiment failure"}


def test_blacklist_tools_use_blacklist_backend(tmp_path):
    path = tmp_path / "blacklist.json"
    real_blacklist = mcp_server.Blacklist
    with patch("kairos.mcp_server.Blacklist", side_effect=lambda: real_blacklist(str(path))):
        added = blacklist_symbol("doge/usdt", reason="noisy", duration_hours=1)
        assert added["success"] is True
        assert added["symbol"] == "DOGE/USDT"
        assert list_blacklist()["blocked_symbols"] == ["DOGE/USDT"]
        removed = unblacklist_symbol("DOGE/USDT")
        assert removed["was_blocked"] is True
        assert list_blacklist()["blocked_count"] == 0


def test_scan_market_and_analyze_symbol_setup_preserve_exchange_argument():
    expected = {"success": True}
    with patch("kairos.mcp_server.run_scan_market", return_value=expected) as scan:
        assert scan_market("okx") == expected
    scan.assert_called_once_with(exchange="okx")

    with patch("kairos.mcp_server.run_analyze_symbol_setup", return_value=expected) as analyze:
        assert analyze_symbol_setup("BTC/USDT", exchange="binance") == expected
    analyze.assert_called_once_with(symbol="BTC/USDT", exchange="binance")


def test_main_bootstrap_success_config_failure_and_keyboard_interrupt():
    dm = MagicMock()
    dm.start = AsyncMock()
    dm.stop = AsyncMock()
    mcp_run = AsyncMock()

    real_anyio_run = mcp_server.anyio.run

    def run_async(fn):
        real_anyio_run(fn)

    with (
        patch("kairos.config.load_config", return_value={"ok": True}) as load_config,
        patch("kairos.data.data_manager.DataManager", return_value=dm) as dm_cls,
        patch.object(mcp_server.mcp, "run_stdio_async", mcp_run),
        patch("kairos.mcp_server.anyio.run", side_effect=run_async) as anyio_run,
    ):
        main()
    load_config.assert_called_once()
    dm_cls.assert_called_once_with({"ok": True})
    anyio_run.assert_called_once()
    dm.start.assert_awaited_once()
    mcp_run.assert_awaited_once()
    dm.stop.assert_awaited_once()

    with (
        patch("kairos.config.load_config", side_effect=RuntimeError("bad config")),
        patch("kairos.data.data_manager.DataManager", return_value=dm) as dm_cls,
        patch("kairos.mcp_server.anyio.run", side_effect=KeyboardInterrupt) as anyio_run,
    ):
        main()
    dm_cls.assert_called_with({})
    anyio_run.assert_called_once()


def test_launcher_dependencies_are_default_runtime_dependencies():
    pyproject = Path("pyproject.toml").read_text()
    dependencies_block = pyproject.split("dependencies = [", 1)[1].split("]", 1)[0]
    hermes_block = pyproject.split("hermes = [", 1)[1].split("]", 1)[0]
    assert '"anyio>=4.0.0"' in dependencies_block
    assert '"mcp>=1.0.0"' in dependencies_block
    assert '"httpx>=0.27.0"' in dependencies_block
    assert "mcp" not in hermes_block
    assert "httpx" not in hermes_block

    launcher = Path("run.sh").read_text()
    assert "uv run --directory" in launcher
    assert "--extra hermes" not in launcher
