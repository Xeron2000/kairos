"""Comprehensive tests for top_volume_symbols."""

from unittest.mock import MagicMock, patch

import pytest

from kairos.utils.top_volume_symbols import (
    _calculate_usdt_volume,
    _create_exchange,
    _extract_open_interest_usd,
    _is_usdt_perpetual,
    _listing_age_days,
    _normalize_filters,
    clear_cache,
    fetch_top_volume_symbols,
    get_cache_age,
)


class TestNormalizeFilters:
    """Test _normalize_filters function."""

    def test_empty_filters(self):
        result = _normalize_filters({})
        assert result["minQuoteVolume24h"] == 0
        assert result["minOpenInterestUsd"] == 0
        assert result["minListingAgeDays"] == 0
        assert result["maxRecentVolatilityPct"] == 0

    def test_with_values(self):
        result = _normalize_filters({
            "minQuoteVolume24h": 1000000,
            "minOpenInterestUsd": 500000,
            "minListingAgeDays": 30,
            "maxRecentVolatilityPct": 10.0,
        })
        assert result["minQuoteVolume24h"] == 1000000.0
        assert result["minOpenInterestUsd"] == 500000.0
        assert result["minListingAgeDays"] == 30
        assert result["maxRecentVolatilityPct"] == 10.0

    def test_with_none_values(self):
        result = _normalize_filters({"minQuoteVolume24h": None})
        assert result["minQuoteVolume24h"] == 0


class TestCreateExchange:
    """Test _create_exchange function."""

    @patch("kairos.utils.top_volume_symbols.ccxt")
    def test_create_binance(self, mock_ccxt):
        mock_cls = MagicMock()
        mock_ccxt.binance = mock_cls
        _create_exchange("binance")
        mock_cls.assert_called_once()

    @patch("kairos.utils.top_volume_symbols.ccxt")
    def test_create_okx(self, mock_ccxt):
        mock_cls = MagicMock()
        mock_ccxt.okx = mock_cls
        _create_exchange("okx")
        mock_cls.assert_called_once()

    @patch("kairos.utils.top_volume_symbols.ccxt")
    def test_create_bybit(self, mock_ccxt):
        mock_cls = MagicMock()
        mock_ccxt.bybit = mock_cls
        _create_exchange("bybit")
        mock_cls.assert_called_once()

    def test_create_unsupported(self):
        with pytest.raises(ValueError, match="Unsupported exchange"):
            _create_exchange("unsupported")


class TestIsUsdtPerpetual:
    """Test _is_usdt_perpetual function."""

    def test_valid_perpetual(self):
        market = {
            "symbol": "BTC/USDT:USDT",
            "quote": "USDT",
            "settle": "USDT",
            "type": "swap",
            "linear": True,
            "active": True,
        }
        assert _is_usdt_perpetual(market) is True

    def test_not_usdt_settle(self):
        market = {
            "symbol": "BTC/BTC:BTC",
            "settle": "BTC",
            "type": "swap",
            "linear": True,
            "active": True,
        }
        assert _is_usdt_perpetual(market) is False

    def test_not_swap(self):
        market = {
            "symbol": "BTC/USDT",
            "settle": "USDT",
            "type": "spot",
            "linear": True,
            "active": True,
        }
        assert _is_usdt_perpetual(market) is False

    def test_not_active(self):
        market = {
            "symbol": "BTC/USDT:USDT",
            "settle": "USDT",
            "type": "swap",
            "linear": True,
            "active": False,
        }
        assert _is_usdt_perpetual(market) is False

    def test_binance_format(self):
        market = {
            "symbol": "BTCUSDT",
            "quote": "USDT",
            "settle": "USDT",
            "type": "swap",
            "linear": True,
            "active": True,
        }
        assert _is_usdt_perpetual(market, "binance") is True


class TestCalculateUsdtVolume:
    """Test _calculate_usdt_volume function."""

    def test_with_quote_volume(self):
        ticker = {"quoteVolume": 1000000.0}
        assert _calculate_usdt_volume(ticker) == 1000000.0

    def test_without_quote_volume(self):
        ticker = {"baseVolume": 100.0, "last": 50000.0}
        assert _calculate_usdt_volume(ticker) == 5000000.0

    def test_no_volume(self):
        ticker = {}
        assert _calculate_usdt_volume(ticker) == 0.0


class TestExtractOpenInterestUsd:
    """Test _extract_open_interest_usd function."""

    def test_with_open_interest(self):
        oi = {"openInterestValue": 5000000.0}
        ticker = {"last": 50000.0}
        assert _extract_open_interest_usd(oi, ticker) == 5000000.0

    def test_with_base_value(self):
        oi = {"openInterestAmount": 100.0}
        ticker = {"last": 50000.0}
        assert _extract_open_interest_usd(oi, ticker) == 5000000.0

    def test_no_data(self):
        assert _extract_open_interest_usd({}, {}) == 0.0


class TestListingAgeDays:
    """Test _listing_age_days function."""

    def test_with_timestamp(self):
        import time
        market = {"created": int((time.time() - 86400 * 30) * 1000)}  # 30 days ago
        age = _listing_age_days(market)
        assert 29 <= age <= 31

    def test_no_timestamp(self):
        market = {}
        assert _listing_age_days(market) == 0


class TestFetchTopVolumeSymbols:
    """Test fetch_top_volume_symbols function."""

    @patch("kairos.utils.top_volume_symbols._create_exchange")
    @patch("kairos.utils.top_volume_symbols._fetch_symbols_by_volume")
    def test_fetch_success(self, mock_fetch, mock_create):
        mock_exchange = MagicMock()
        mock_create.return_value = mock_exchange
        mock_fetch.return_value = ["BTC/USDT:USDT", "ETH/USDT:USDT"]

        clear_cache()
        result = fetch_top_volume_symbols("binance", limit=2)

        assert result == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
        mock_create.assert_called_once_with("binance")

    @patch("kairos.utils.top_volume_symbols._create_exchange")
    @patch("kairos.utils.top_volume_symbols._fetch_symbols_by_volume")
    def test_fetch_with_cache(self, mock_fetch, mock_create):
        mock_exchange = MagicMock()
        mock_create.return_value = mock_exchange
        mock_fetch.return_value = ["BTC/USDT:USDT"]

        clear_cache()
        result1 = fetch_top_volume_symbols("binance")
        result2 = fetch_top_volume_symbols("binance")

        assert result1 == result2
        assert mock_create.call_count == 1  # Only called once due to cache

    @patch("kairos.utils.top_volume_symbols._create_exchange")
    def test_fetch_error_with_cache_fallback(self, mock_create):
        # First call succeeds and caches
        mock_exchange = MagicMock()
        mock_create.return_value = mock_exchange

        with patch("kairos.utils.top_volume_symbols._fetch_symbols_by_volume", return_value=["BTC/USDT:USDT"]):
            clear_cache()
            result1 = fetch_top_volume_symbols("binance")

        assert result1 == ["BTC/USDT:USDT"]

        # Second call fails - should still get cached data
        mock_create.side_effect = Exception("API error")
        result2 = fetch_top_volume_symbols("binance")

        # Should return cached data
        assert result2 == ["BTC/USDT:USDT"]

    @patch("kairos.utils.top_volume_symbols._create_exchange")
    def test_fetch_error_no_cache(self, mock_create):
        mock_create.side_effect = Exception("API error")

        clear_cache()
        result = fetch_top_volume_symbols("binance")
        assert result == []


class TestGetCacheAge:
    """Test get_cache_age function."""

    def test_no_cache(self):
        clear_cache()
        assert get_cache_age("binance") is None

    @patch("kairos.utils.top_volume_symbols._create_exchange")
    @patch("kairos.utils.top_volume_symbols._fetch_symbols_by_volume")
    def test_with_cache(self, mock_fetch, mock_create):
        mock_create.return_value = MagicMock()
        mock_fetch.return_value = ["BTC/USDT:USDT"]

        clear_cache()
        fetch_top_volume_symbols("binance")

        age = get_cache_age("binance")
        assert age is not None
        assert age >= 0


class TestClearCache:
    """Test clear_cache function."""

    def test_clear_cache(self):
        clear_cache()
        assert get_cache_age("binance") is None
