"""Tests for mcp_server.py - adapted for real analysis module implementation.

Mocks external exchange calls (_fetch_ohlcv, _current_price, _funding_rate)
and tests the MCP tool functions with real CycleDetector/BoxDetector/SupportResistance.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from kairos.mcp_server import (
    KairosState,
    check_exit_signals,
    check_pyramiding,
    detect_box_pattern,
    detect_signal,
    get_market_cycle,
    get_market_sentiment,
    get_position_status,
    get_risk_status,
    get_statistics,
    get_trade_history,
    scan_symbols,
    state,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_ohlcv(n=100, base_price=68500.0):
    """Build a realistic OHLCV dict for mock returns."""
    prices = np.linspace(base_price * 0.95, base_price, n)
    return {
        "timestamps": np.arange(n, dtype=float) * 3600000.0,
        "opens": prices * 0.999,
        "highs": prices * 1.01,
        "lows": prices * 0.99,
        "closes": prices,
        "volumes": np.ones(n) * 1000.0,
    }


@pytest.fixture(autouse=True)
def mock_helpers():
    """Mock all external exchange helpers."""
    with (
        patch("kairos.mcp_server._fetch_ohlcv", return_value=_make_ohlcv()),
        patch("kairos.mcp_server._current_price", return_value=68500.0, autospec=True),
        patch("kairos.mcp_server._funding_rate", return_value=0.0001, autospec=True),
    ):
        yield


# ── KairosState ──────────────────────────────────────────────────────────────


class TestKairosState:
    """Test KairosState class."""

    def test_init(self):
        s = KairosState()
        assert s.cycle_detector is not None
        assert s.box_detector is not None
        assert s.sr_analyzer is not None
        assert s.last_cycle is None
        assert s.last_scan is None

    def test_update_cycle(self):
        s = KairosState()
        cycle = {"phase": "spring", "confidence": 0.8}
        s.update_cycle(cycle)
        assert s.last_cycle == cycle

    def test_update_scan(self):
        s = KairosState()
        scan = {"candidates": ["BTC/USDT"]}
        s.update_scan(scan)
        assert s.last_scan == scan


# ── get_market_cycle ─────────────────────────────────────────────────────────


class TestGetMarketCycle:
    """Tests for get_market_cycle()."""

    def test_returns_success(self):
        result = get_market_cycle()
        assert result["success"] is True
        assert "cycle" in result
        assert result["cycle"]["phase"] in ("spring", "summer", "autumn", "winter", "unknown")

    def test_no_data(self):
        with patch("kairos.mcp_server._fetch_ohlcv", return_value=None, autospec=True):
            result = get_market_cycle()
            assert result["success"] is True
            assert result["cycle"]["phase"] == "unknown"

    def test_handles_exception(self):
        with patch("kairos.mcp_server._fetch_ohlcv", side_effect=Exception("boom")):
            result = get_market_cycle()
            assert result["success"] is False
            assert "boom" in result["error"]


# ── detect_box_pattern ───────────────────────────────────────────────────────


class TestDetectBoxPattern:
    """Tests for detect_box_pattern()."""

    def test_with_data(self):
        result = detect_box_pattern("BTC/USDT")
        assert result["success"] is True
        assert "box_pattern" in result
        assert result["symbol"] == "BTC/USDT"

    def test_no_data(self):
        with patch("kairos.mcp_server._fetch_ohlcv", return_value=None, autospec=True):
            result = detect_box_pattern("BTC/USDT")
            assert result["success"] is False

    def test_insufficient_data(self):
        """When OHLCV has too few bars."""
        short_ohlcv = _make_ohlcv(n=5)
        with patch("kairos.mcp_server._fetch_ohlcv", return_value=short_ohlcv, autospec=True):
            result = detect_box_pattern("BTC/USDT")
            assert result["success"] is False

    def test_handles_error(self):
        with patch("kairos.mcp_server._fetch_ohlcv", side_effect=Exception("connection lost")):
            result = detect_box_pattern("BTC/USDT")
            assert result["success"] is False


# ── scan_symbols ─────────────────────────────────────────────────────────────


class TestScanSymbols:
    """Tests for scan_symbols()."""

    def test_no_exchange(self):
        with patch("kairos.mcp_server._get_exchange", return_value=None, autospec=True):
            result = scan_symbols()
            assert result["success"] is False
            assert "Cannot connect" in result["error"]

    def test_handles_exception(self):
        with patch("kairos.mcp_server._get_exchange", side_effect=Exception("fail")):
            result = scan_symbols()
            assert result["success"] is False


# ── detect_signal ────────────────────────────────────────────────────────────


class TestDetectSignal:
    """Tests for detect_signal()."""

    def test_with_data(self):
        result = detect_signal("BTC/USDT")
        assert result["success"] is True
        assert "signal" in result

    def test_no_price(self):
        with patch("kairos.mcp_server._current_price", return_value=None, autospec=True):
            result = detect_signal("BTC/USDT")
            assert result["success"] is False
            assert "No price data" in result["error"]

    def test_different_strategies(self):
        """All strategies should return success."""
        for strategy in ("box_breakout", "small_pullback", "large_pullback"):
            result = detect_signal("BTC/USDT", strategy=strategy)
            assert result["success"] is True


# ── position / risk / history / stats ────────────────────────────────────────


class TestPositionAndRisk:
    """Tests for position and risk functions."""

    def test_get_position_status_returns(self):
        result = get_position_status()
        assert result["success"] is True
        assert "positions" in result

    def test_get_risk_status_returns(self):
        result = get_risk_status()
        assert result["success"] is True
        assert "risk_status" in result

    def test_get_trade_history_returns(self):
        result = get_trade_history(limit=5)
        assert result["success"] is True
        assert "trades" in result

    def test_get_trade_history_empty(self):
        with patch("kairos.mcp_server.PositionManager", side_effect=Exception("no data")):
            result = get_trade_history()
            assert result["success"] is True
            assert result["trades"] == []

    def test_get_statistics_returns(self):
        result = get_statistics()
        assert result["success"] is True

    def test_get_statistics_empty(self):
        with patch("kairos.mcp_server.PositionManager", side_effect=Exception("no data")):
            result = get_statistics()
            assert result["success"] is True


# ── pyramiding / exit / sentiment ────────────────────────────────────────────


class TestOtherTools:
    """Tests for pyramiding, exit signals, and sentiment."""

    def test_check_pyramiding(self):
        result = check_pyramiding("BTC/USDT")
        assert result["success"] is True
        assert "pyramiding_conditions" in result

    def test_check_pyramiding_no_data(self):
        with patch("kairos.mcp_server._current_price", return_value=None, autospec=True):
            result = check_pyramiding("BTC/USDT")
            assert result["success"] is False

    def test_check_exit_signals(self):
        result = check_exit_signals("BTC/USDT")
        assert result["success"] is True
        assert "exit_signals" in result

    def test_check_exit_signals_no_data(self):
        with patch("kairos.mcp_server._current_price", return_value=None, autospec=True):
            result = check_exit_signals("BTC/USDT")
            assert result["success"] is False

    def test_get_market_sentiment(self):
        result = get_market_sentiment()
        assert result["success"] is True
        assert "sentiment" in result
        assert result["sentiment"]["overall"] in ("bullish", "bearish", "neutral")

    def test_get_market_sentiment_no_data(self):
        with (
            patch("kairos.mcp_server._current_price", return_value=None, autospec=True),
            patch("kairos.mcp_server._fetch_ohlcv", return_value=None, autospec=True),
        ):
            result = get_market_sentiment()
            assert result["success"] is True
            assert result["sentiment"]["overall"] == "neutral"


# ── State singleton ──────────────────────────────────────────────────────────


class TestState:
    """Tests for the state singleton."""

    def test_state_singleton_exists(self):
        assert state is not None
        assert state.cycle_detector is not None
        assert state.box_detector is not None
