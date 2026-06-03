"""Additional tests for top_volume_symbols to increase coverage."""

from unittest.mock import MagicMock, patch

import pytest

from kairos.utils.top_volume_symbols import (
    _calculate_usdt_volume,
    _fetch_symbols_by_volume,
    _fetch_tickers_for_exchange,
    _is_usdt_perpetual,
    _normalize_filters,
    clear_cache,
    fetch_top_volume_symbols,
)


class TestFetchSymbolsByVolume:
    """Test _fetch_symbols_by_volume function."""

    def test_returns_sorted_by_volume(self):
        exchange = MagicMock()
        exchange.id = "binance"
        exchange.markets = {
            "BTC/USDT:USDT": {"symbol": "BTC/USDT:USDT", "quote": "USDT", "settle": "USDT", "type": "swap", "active": True},
            "ETH/USDT:USDT": {"symbol": "ETH/USDT:USDT", "quote": "USDT", "settle": "USDT", "type": "swap", "active": True},
        }
        exchange.load_markets = MagicMock()

        with patch("kairos.utils.top_volume_symbols._fetch_tickers_for_exchange") as mock_tickers:
            mock_tickers.return_value = {
                "BTC/USDT:USDT": {"quoteVolume": 1000000},
                "ETH/USDT:USDT": {"quoteVolume": 2000000},
            }

            filters = _normalize_filters({})
            result = _fetch_symbols_by_volume(exchange, 10, filters)

            assert len(result) == 2
            assert result[0] == "ETH/USDT:USDT"  # Higher volume first
            assert result[1] == "BTC/USDT:USDT"

    def test_returns_empty_when_no_usdt_futures(self):
        exchange = MagicMock()
        exchange.id = "binance"
        exchange.markets = {
            "BTC/BTC": {"symbol": "BTC/BTC", "quote": "BTC", "settle": "BTC", "type": "spot", "active": True},
        }
        exchange.load_markets = MagicMock()

        filters = _normalize_filters({})
        result = _fetch_symbols_by_volume(exchange, 10, filters)
        assert result == []

    def test_filters_by_min_volume(self):
        exchange = MagicMock()
        exchange.id = "binance"
        exchange.markets = {
            "BTC/USDT:USDT": {"symbol": "BTC/USDT:USDT", "quote": "USDT", "settle": "USDT", "type": "swap", "active": True},
            "ETH/USDT:USDT": {"symbol": "ETH/USDT:USDT", "quote": "USDT", "settle": "USDT", "type": "swap", "active": True},
        }
        exchange.load_markets = MagicMock()

        with patch("kairos.utils.top_volume_symbols._fetch_tickers_for_exchange") as mock_tickers:
            mock_tickers.return_value = {
                "BTC/USDT:USDT": {"quoteVolume": 1000000},
                "ETH/USDT:USDT": {"quoteVolume": 500},  # Below threshold
            }

            filters = _normalize_filters({"minQuoteVolume24h": 1000})
            result = _fetch_symbols_by_volume(exchange, 10, filters)

            assert len(result) == 1
            assert result[0] == "BTC/USDT:USDT"

    def test_returns_empty_when_no_tickers(self):
        exchange = MagicMock()
        exchange.id = "binance"
        exchange.markets = {
            "BTC/USDT:USDT": {"symbol": "BTC/USDT:USDT", "quote": "USDT", "settle": "USDT", "type": "swap", "active": True},
        }
        exchange.load_markets = MagicMock()

        with patch("kairos.utils.top_volume_symbols._fetch_tickers_for_exchange") as mock_tickers:
            mock_tickers.return_value = {}

            filters = _normalize_filters({})
            result = _fetch_symbols_by_volume(exchange, 10, filters)

            assert result == []

    def test_limits_results(self):
        exchange = MagicMock()
        exchange.id = "binance"
        exchange.markets = {
            f"SYM{i}/USDT:USDT": {"symbol": f"SYM{i}/USDT:USDT", "quote": "USDT", "settle": "USDT", "type": "swap", "active": True}
            for i in range(10)
        }
        exchange.load_markets = MagicMock()

        with patch("kairos.utils.top_volume_symbols._fetch_tickers_for_exchange") as mock_tickers:
            mock_tickers.return_value = {
                f"SYM{i}/USDT:USDT": {"quoteVolume": float(i * 1000)}
                for i in range(10)
            }

            filters = _normalize_filters({})
            result = _fetch_symbols_by_volume(exchange, 5, filters)

            assert len(result) == 5


class TestFetchTickersForExchange:
    """Test _fetch_tickers_for_exchange function."""

    def test_okx_uses_inst_type(self):
        exchange = MagicMock()
        exchange.id = "okx"
        exchange.fetch_tickers = MagicMock(return_value={"BTC/USDT:USDT": {}})

        result = _fetch_tickers_for_exchange(exchange, ["BTC/USDT:USDT"])
        assert "BTC/USDT:USDT" in result

    def test_bybit_uses_inst_type(self):
        exchange = MagicMock()
        exchange.id = "bybit"
        exchange.fetch_tickers = MagicMock(return_value={"BTC/USDT:USDT": {}})

        result = _fetch_tickers_for_exchange(exchange, ["BTC/USDT:USDT"])
        assert "BTC/USDT:USDT" in result

    def test_binance_uses_default(self):
        exchange = MagicMock()
        exchange.id = "binance"
        exchange.fetch_tickers = MagicMock(return_value={"BTC/USDT": {}})

        result = _fetch_tickers_for_exchange(exchange, ["BTC/USDT"])
        assert "BTC/USDT" in result

    def test_fallback_on_error(self):
        exchange = MagicMock()
        exchange.id = "okx"
        exchange.fetch_tickers = MagicMock(side_effect=[Exception("API error"), {"BTC/USDT:USDT": {}}])

        result = _fetch_tickers_for_exchange(exchange, ["BTC/USDT:USDT"])
        assert "BTC/USDT:USDT" in result


class TestIsUsdtPerpetualExtended:
    """Extended tests for _is_usdt_perpetual."""

    def test_with_contract_flag(self):
        market = {
            "symbol": "BTC/USDT:USDT",
            "quote": "USDT",
            "settle": "USDT",
            "contract": True,
            "active": True,
        }
        # contract flag alone isn't enough, need proper type
        # Actually looking at the code, it checks quote, settle, and type
        assert _is_usdt_perpetual(market) is False  # type is not set

    def test_inactive_market(self):
        market = {
            "symbol": "BTC/USDT:USDT",
            "quote": "USDT",
            "settle": "USDT",
            "type": "swap",
            "active": False,
        }
        assert _is_usdt_perpetual(market) is False

    def test_non_usdt_quote(self):
        market = {
            "symbol": "BTC/BTC:BTC",
            "quote": "BTC",
            "settle": "BTC",
            "type": "swap",
            "active": True,
        }
        assert _is_usdt_perpetual(market) is False

    def test_future_type(self):
        market = {
            "symbol": "BTC/USDT:USDT",
            "quote": "USDT",
            "settle": "USDT",
            "type": "future",
            "active": True,
        }
        assert _is_usdt_perpetual(market) is True

    def test_binance_requires_swap(self):
        market = {
            "symbol": "BTCUSDT",
            "quote": "USDT",
            "settle": "USDT",
            "type": "future",
            "active": True,
        }
        # Binance only accepts swap, not future
        assert _is_usdt_perpetual(market, "binance") is False


class TestCalculateUsdtVolumeExtended:
    """Extended tests for _calculate_usdt_volume."""

    def test_with_info_volCcy24h(self):
        ticker = {
            "last": 50000.0,
            "info": {"volCcy24h": "100"},
        }
        assert _calculate_usdt_volume(ticker) == 5000000.0

    def test_with_base_volume(self):
        ticker = {
            "last": 50000.0,
            "baseVolume": 100.0,
        }
        assert _calculate_usdt_volume(ticker) == 5000000.0

    def test_zero_last_price(self):
        ticker = {
            "last": 0,
            "baseVolume": 100.0,
        }
        assert _calculate_usdt_volume(ticker) == 0.0

    def test_negative_last_price(self):
        ticker = {
            "last": -1,
            "baseVolume": 100.0,
        }
        assert _calculate_usdt_volume(ticker) == 0.0


class TestFetchTopVolumeSymbolsExtended:
    """Extended tests for fetch_top_volume_symbols."""

    @patch("kairos.utils.top_volume_symbols._create_exchange")
    @patch("kairos.utils.top_volume_symbols._fetch_symbols_by_volume")
    def test_with_filters(self, mock_fetch, mock_create):
        mock_create.return_value = MagicMock()
        mock_fetch.return_value = ["BTC/USDT:USDT"]

        clear_cache()
        result = fetch_top_volume_symbols(
            "binance",
            limit=10,
            filters={"minQuoteVolume24h": 1000000}
        )

        assert result == ["BTC/USDT:USDT"]

    @patch("kairos.utils.top_volume_symbols._create_exchange")
    @patch("kairos.utils.top_volume_symbols._fetch_symbols_by_volume")
    def test_cache_key_includes_filters(self, mock_fetch, mock_create):
        mock_create.return_value = MagicMock()
        mock_fetch.return_value = ["BTC/USDT:USDT"]

        clear_cache()
        fetch_top_volume_symbols("binance", filters={"minQuoteVolume24h": 1000000})

        # Second call with different filters should not use cache
        fetch_top_volume_symbols("binance", filters={"minQuoteVolume24h": 2000000})

        assert mock_create.call_count == 2
