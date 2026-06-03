"""Tests for trade_cli.py - adapted for real exchange-based implementation.

Mocks external exchange calls (_fetch_ohlcv, _current_price, _funding_rate)
and tests business logic of CLI command functions.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import numpy as np
import pytest

# Mock exchange modules before importing trade_cli
from kairos.app.trade_cli import (
    _current_price,
    _fetch_ohlcv,
    _funding_rate,
    cmd_box_detect,
    cmd_cycle,
    cmd_funding,
    cmd_funding_extreme,
    cmd_funding_opportunities,
    cmd_funding_status,
    cmd_pattern,
    cmd_signal,
    cmd_sr,
    get_trading_commands,
    load_config,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_ohlcv_return(prices=None, volumes=None, n=100):
    """Build a realistic OHLCV dict for mock returns."""
    base = prices if prices is not None else np.linspace(67000, 69000, n)
    return {
        "timestamps": np.arange(n, dtype=float) * 3600000.0,
        "opens": np.ones(n) * base[0],
        "highs": np.ones(n) * base[0] * 1.01,
        "lows": np.ones(n) * base[0] * 0.99,
        "closes": base,
        "volumes": np.ones(n) * 1000.0,
    }


def _make_args(**kwargs):
    """Create SimpleNamespace with given attributes."""
    ns = SimpleNamespace()
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


@pytest.fixture(autouse=True)
def mock_exchange_helpers():
    """Globally mock exchange helpers to prevent real API calls."""
    with (
        patch("kairos.app.trade_cli._fetch_ohlcv", return_value=_make_ohlcv_return()),
        patch("kairos.app.trade_cli._current_price", return_value=68500.0, autospec=True),
        patch("kairos.app.trade_cli._funding_rate", return_value=0.0001, autospec=True),
    ):
        yield


@pytest.fixture
def no_ohlcv():
    """Patches _fetch_ohlcv to return None (simulating offline)."""
    with patch("kairos.app.trade_cli._fetch_ohlcv", return_value=None, autospec=True):
        yield


@pytest.fixture
def mock_config_yaml():
    """Provides a mock config file."""
    with patch("builtins.open", mock_open(read_data="defaultExchange: okx")):
        with patch("kairos.app.trade_cli.Path", autospec=True) as mock_path:
            config_path = MagicMock()
            config_path.exists.return_value = True
            config_path.__truediv__ = MagicMock(return_value=config_path)
            mock_home = MagicMock()
            mock_home.__truediv__ = MagicMock(return_value=config_path)
            mock_path.home.return_value = mock_home
            yield mock_path


# ── Helper functions ─────────────────────────────────────────────────────────


class TestHelpers:
    """Test helper functions."""

    def test_fetch_ohlcv_real_call(self):
        """Test _fetch_ohlcv with no exchange (returns None)."""
        with patch("kairos.app.trade_cli.get_exchange", side_effect=Exception("no connection")):
            result = _fetch_ohlcv("BTC/USDT")
            assert result is None

    def test_current_price_no_exchange(self):
        """Test _current_price with no exchange (returns None)."""
        with patch("kairos.app.trade_cli.get_exchange", side_effect=Exception("no connection")):
            result = _current_price("BTC/USDT")
            assert result is None

    def test_funding_rate_no_exchange(self):
        """Test _funding_rate with no exchange (returns None)."""
        with patch("kairos.app.trade_cli.get_exchange", side_effect=Exception("no connection")):
            result = _funding_rate("BTC/USDT")
            assert result is None


# ── load_config ──────────────────────────────────────────────────────────────


class TestLoadConfig:
    """Tests for load_config()."""

    def test_load_config_success(self, mock_config_yaml):

        from kairos.app.trade_cli import load_config as lc

        result = lc()
        assert result == {"defaultExchange": "okx"}

    @patch("kairos.app.trade_cli.Path", autospec=True)
    @patch("kairos.app.trade_cli.sys.exit", side_effect=SystemExit(1))
    def test_load_config_not_found(self, mock_exit, mock_path):
        config_path = MagicMock()
        config_path.exists.return_value = False
        config_path.__truediv__ = MagicMock(return_value=config_path)
        mock_home = MagicMock()
        mock_home.__truediv__ = MagicMock(return_value=config_path)
        mock_path.home.return_value = mock_home

        with pytest.raises(SystemExit):
            load_config()


# ── cmd_cycle ────────────────────────────────────────────────────────────────


class TestCmdCycle:
    """Tests for cmd_cycle()."""

    def test_cycle_with_data(self, capsys, mock_config_yaml):
        """cmd_cycle should print cycle info when OHLCV available."""
        cmd_cycle(_make_args())
        captured = capsys.readouterr()
        assert "Market Cycle Analysis" in captured.out

    def test_cycle_no_data(self, capsys, no_ohlcv, mock_config_yaml):
        """cmd_cycle should show warning when OHLCV unavailable."""
        cmd_cycle(_make_args())
        captured = capsys.readouterr()
        assert "Could not fetch" in captured.out


# ── cmd_box_detect ───────────────────────────────────────────────────────────


class TestCmdBoxDetect:
    """Tests for cmd_box_detect()."""

    def test_box_detect_with_data(self, capsys):
        """cmd_box_detect should attempt box detection."""
        cmd_box_detect(_make_args(symbol="BTC/USDT"))
        captured = capsys.readouterr()
        assert "Box Pattern Detection" in captured.out

    def test_box_detect_no_data(self, capsys, no_ohlcv):
        """cmd_box_detect should warn when no data."""
        cmd_box_detect(_make_args(symbol="BTC/USDT"))
        captured = capsys.readouterr()
        assert "Could not fetch" in captured.out


# ── cmd_signal ───────────────────────────────────────────────────────────────


class TestCmdSignal:
    """Tests for cmd_signal()."""

    def test_signal_with_data(self, capsys):
        """cmd_signal should print signal info."""
        cmd_signal(_make_args(symbol="BTC/USDT"))
        captured = capsys.readouterr()
        assert "Trading Signal" in captured.out

    def test_signal_no_price(self, capsys):
        """cmd_signal should warn when price unavailable."""
        with patch("kairos.app.trade_cli._current_price", return_value=None, autospec=True):
            cmd_signal(_make_args(symbol="BTC/USDT"))
        captured = capsys.readouterr()
        assert "Could not fetch" in captured.out


# ── cmd_sr ───────────────────────────────────────────────────────────────────


class TestCmdSr:
    """Tests for cmd_sr()."""

    def test_sr_with_data(self, capsys):
        """cmd_sr should show SR levels."""
        cmd_sr(_make_args(symbol="BTC/USDT"))
        captured = capsys.readouterr()
        assert "Support & Resistance" in captured.out

    def test_sr_no_price(self, capsys):
        """cmd_sr should warn when no price."""
        with patch("kairos.app.trade_cli._current_price", return_value=None, autospec=True):
            cmd_sr(_make_args(symbol="BTC/USDT"))
        captured = capsys.readouterr()
        assert "Could not fetch" in captured.out


# ── cmd_pattern ──────────────────────────────────────────────────────────────


class TestCmdPattern:
    """Tests for cmd_pattern()."""

    def test_pattern_with_data(self, capsys):
        """cmd_pattern with valid data."""
        cmd_pattern(_make_args(symbol="BTC/USDT"))
        captured = capsys.readouterr()
        assert "K-Line Pattern" in captured.out

    def test_pattern_no_data(self, capsys, no_ohlcv):
        """cmd_pattern with no data."""
        with patch("kairos.app.trade_cli._current_price", return_value=None, autospec=True):
            cmd_pattern(_make_args(symbol="BTC/USDT"))
        captured = capsys.readouterr()
        assert "No data available" in captured.out


# ── cmd_funding ──────────────────────────────────────────────────────────────


class TestCmdFunding:
    """Tests for funding commands."""

    def test_funding_status(self, capsys):
        """cmd_funding_status should print funding rates."""
        cmd_funding_status(_make_args())
        captured = capsys.readouterr()
        assert "Funding Rates" in captured.out

    def test_funding_extreme(self, capsys):
        """cmd_funding_extreme should print extreme rates."""
        cmd_funding_extreme(_make_args())
        captured = capsys.readouterr()
        assert "Extreme" in captured.out

    def test_funding_opportunities(self, capsys):
        """cmd_funding_opportunities should print opportunities."""
        cmd_funding_opportunities(_make_args())
        captured = capsys.readouterr()
        assert "Funding Arbitrage" in captured.out

    def test_funding_dispatcher(self, capsys):
        """cmd_funding dispatches to subcommands."""
        cmd_funding(_make_args(subcmd="status"))


# ── Command Registration ─────────────────────────────────────────────────────


class TestRegistration:
    """Tests for command registration."""

    def test_get_trading_commands(self):
        """get_trading_commands returns expected commands."""
        cmds = get_trading_commands()
        assert "cycle" in cmds
        assert "scan" in cmds
        assert "box-detect" in cmds
        assert "signal" in cmds
        assert "sr" in cmds
        assert "position" in cmds
        assert "order" in cmds
        assert "risk" in cmds
        assert "history" in cmds
        assert "stats" in cmds
        assert callable(cmds["cycle"])
        assert callable(cmds["signal"])
