"""Comprehensive tests for supported_markets."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kairos.utils.supported_markets import (
    DEFAULT_MARKETS,
    _ensure_parent_dir,
    _is_derivatives_market,
    _is_usdt_contract,
    _read_supported_markets,
    _write_supported_markets,
    filter_usdt_symbols,
    list_cached_exchanges,
    load_usdt_contracts,
    refresh_exchange_markets,
    refresh_supported_markets,
)


class TestIsUsdtContract:
    """Test _is_usdt_contract function."""

    def test_with_colon(self):
        assert _is_usdt_contract("BTC/USDT:USDT") is True

    def test_with_slash(self):
        assert _is_usdt_contract("BTC/USDT") is True

    def test_not_usdt(self):
        assert _is_usdt_contract("BTC/BTC") is False

    def test_empty_string(self):
        assert _is_usdt_contract("") is False


class TestFilterUsdtSymbols:
    """Test filter_usdt_symbols function."""

    def test_filters_usdt_symbols(self):
        symbols = ["BTC/USDT:USDT", "BTC/BTC:BTC", "ETH/USDT:USDT", "ETH/ETH:ETH"]
        result = filter_usdt_symbols(symbols)
        assert result == ["BTC/USDT:USDT", "ETH/USDT:USDT"]

    def test_empty_input(self):
        assert filter_usdt_symbols([]) == []

    def test_no_usdt_symbols(self):
        symbols = ["BTC/BTC", "ETH/ETH"]
        result = filter_usdt_symbols(symbols)
        assert result == []


class TestIsDerivativesMarket:
    """Test _is_derivatives_market function."""

    def test_swap(self):
        assert _is_derivatives_market({"type": "swap"}) is True

    def test_future(self):
        assert _is_derivatives_market({"type": "future"}) is True

    def test_spot(self):
        assert _is_derivatives_market({"type": "spot"}) is False

    def test_futures(self):
        assert _is_derivatives_market({"type": "futures"}) is True

    def test_perpetual(self):
        assert _is_derivatives_market({"type": "perpetual"}) is True

    def test_option(self):
        assert _is_derivatives_market({"type": "option"}) is True


class TestReadSupportedMarkets:
    """Test _read_supported_markets function."""

    def test_file_not_exists(self, tmp_path):
        with patch("kairos.utils.supported_markets.SUPPORTED_MARKETS_PATH", tmp_path / "nonexistent.json"):
            result = _read_supported_markets()
            assert result == {}

    def test_valid_json(self, tmp_path):
        data = {"binance": ["BTC/USDT", "ETH/USDT"]}
        path = tmp_path / "markets.json"
        path.write_text(json.dumps(data))

        with patch("kairos.utils.supported_markets.SUPPORTED_MARKETS_PATH", path):
            result = _read_supported_markets()
            assert result == data

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "markets.json"
        path.write_text("invalid json")

        with patch("kairos.utils.supported_markets.SUPPORTED_MARKETS_PATH", path):
            result = _read_supported_markets()
            assert result == {}

    def test_not_dict(self, tmp_path):
        path = tmp_path / "markets.json"
        path.write_text(json.dumps(["BTC/USDT"]))

        with patch("kairos.utils.supported_markets.SUPPORTED_MARKETS_PATH", path):
            result = _read_supported_markets()
            assert result == {}

    def test_non_list_values(self, tmp_path):
        data = {"binance": "not a list"}
        path = tmp_path / "markets.json"
        path.write_text(json.dumps(data))

        with patch("kairos.utils.supported_markets.SUPPORTED_MARKETS_PATH", path):
            result = _read_supported_markets()
            assert result == {}


class TestWriteSupportedMarkets:
    """Test _write_supported_markets function."""

    def test_writes_json(self, tmp_path):
        data = {"binance": ["BTC/USDT", "ETH/USDT"]}
        path = tmp_path / "markets.json"

        with patch("kairos.utils.supported_markets.SUPPORTED_MARKETS_PATH", path):
            _write_supported_markets(data)

        written = json.loads(path.read_text())
        assert written == data


class TestEnsureParentDir:
    """Test _ensure_parent_dir function."""

    def test_creates_directory(self, tmp_path):
        path = tmp_path / "subdir" / "file.json"
        _ensure_parent_dir(path)
        assert path.parent.exists()


class TestListCachedExchanges:
    """Test list_cached_exchanges function."""

    def test_returns_exchanges(self, tmp_path):
        data = {"binance": ["BTC/USDT"], "okx": ["ETH/USDT"]}
        path = tmp_path / "markets.json"
        path.write_text(json.dumps(data))

        with patch("kairos.utils.supported_markets.SUPPORTED_MARKETS_PATH", path):
            result = list_cached_exchanges()
            assert set(result) == {"binance", "okx"}

    def test_empty_file(self, tmp_path):
        path = tmp_path / "markets.json"
        path.write_text("{}")

        with patch("kairos.utils.supported_markets.SUPPORTED_MARKETS_PATH", path):
            result = list_cached_exchanges()
            assert result == []


class TestRefreshSupportedMarkets:
    """Test refresh_supported_markets function."""

    @patch("kairos.utils.supported_markets._fetch_exchange_symbols")
    def test_refresh_multiple(self, mock_fetch, tmp_path):
        mock_fetch.return_value = ["BTC/USDT:USDT"]

        with patch("kairos.utils.supported_markets.SUPPORTED_MARKETS_PATH", tmp_path / "markets.json"):
            result = refresh_supported_markets(["binance", "okx"])

        assert "binance" in result
        assert "okx" in result

    @patch("kairos.utils.supported_markets._fetch_exchange_symbols")
    def test_refresh_with_error(self, mock_fetch, tmp_path):
        mock_fetch.return_value = []  # Returns empty list on error

        with patch("kairos.utils.supported_markets.SUPPORTED_MARKETS_PATH", tmp_path / "markets.json"):
            result = refresh_supported_markets(["binance"])

        # When _fetch returns empty, nothing is refreshed
        assert isinstance(result, dict)
        assert "binance" not in result


class TestRefreshExchangeMarkets:
    """Test refresh_exchange_markets function."""

    @patch("kairos.utils.supported_markets._fetch_exchange_symbols")
    def test_refresh_single(self, mock_fetch, tmp_path):
        mock_fetch.return_value = ["BTC/USDT:USDT", "ETH/USDT:USDT"]

        with patch("kairos.utils.supported_markets.SUPPORTED_MARKETS_PATH", tmp_path / "markets.json"):
            result = refresh_exchange_markets("binance")

        assert result == ["BTC/USDT:USDT", "ETH/USDT:USDT"]

    @patch("kairos.utils.supported_markets._fetch_exchange_symbols")
    def test_refresh_error(self, mock_fetch, tmp_path):
        mock_fetch.return_value = []  # Returns empty list on error

        with patch("kairos.utils.supported_markets.SUPPORTED_MARKETS_PATH", tmp_path / "markets.json"):
            result = refresh_exchange_markets("binance")

        assert isinstance(result, list)
        assert result == []


class TestLoadUsdtContracts:
    """Test load_usdt_contracts function."""

    def test_loads_from_cache(self, tmp_path):
        data = {"binance": ["BTC/USDT:USDT", "ETH/USDT:USDT", "BTC/BTC:BTC"]}
        path = tmp_path / "markets.json"
        path.write_text(json.dumps(data))

        with patch("kairos.utils.supported_markets.SUPPORTED_MARKETS_PATH", path):
            result = load_usdt_contracts("binance")

        assert "BTC/USDT:USDT" in result
        assert "ETH/USDT:USDT" in result
        assert "BTC/BTC:BTC" not in result

    def test_no_cache_uses_defaults(self, tmp_path):
        with patch("kairos.utils.supported_markets.SUPPORTED_MARKETS_PATH", tmp_path / "markets.json"):
            result = load_usdt_contracts("binance")

        # Should use DEFAULT_MARKETS for binance
        assert len(result) > 0
        assert result == DEFAULT_MARKETS["binance"]
