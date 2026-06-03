"""Comprehensive tests for kairos.utils.top_volume_symbols module."""

import time
from unittest.mock import MagicMock, patch, PropertyMock
import pytest
import ccxt

import kairos.utils.top_volume_symbols as _mod
from kairos.utils.top_volume_symbols import (
    fetch_top_volume_symbols,
    _normalize_filters,
    _create_exchange,
    _fetch_symbols_by_volume,
    _calculate_usdt_volume,
    _fetch_tickers_for_exchange,
    _fetch_open_interest_map,
    _extract_open_interest_usd,
    _listing_age_days,
    _recent_volatility_pct,
    _is_usdt_perpetual,
    _fetch_tickers_individually,
    get_cache_age,
    clear_cache,
    _CACHE_TTL_SECONDS,
)


def _get_cache():
    """Access module's live cache (survives clear_cache reassignment)."""
    return _mod._volume_cache


def _default_cache_key(exchange_name="binance", limit=20):
    """Build the exact cache key fetch_top_volume_symbols uses with default filters."""
    nf = _normalize_filters({})
    return f"{exchange_name}_{limit}_{tuple(sorted(nf.items()))}"


@pytest.fixture(autouse=True)
def clear_volume_cache():
    """Clear cache before each test."""
    clear_cache()
    yield
    clear_cache()


# ── _normalize_filters ─────────────────────────────────────────────

class TestNormalizeFilters:
    def test_defaults(self):
        result = _normalize_filters({})
        assert result == {
            "minQuoteVolume24h": 0.0,
            "minOpenInterestUsd": 0.0,
            "minListingAgeDays": 0,
            "maxRecentVolatilityPct": 0.0,
        }

    def test_custom_values(self):
        result = _normalize_filters({
            "minQuoteVolume24h": 1000000,
            "minOpenInterestUsd": 500000,
            "minListingAgeDays": 30,
            "maxRecentVolatilityPct": 5.5,
        })
        assert result == {
            "minQuoteVolume24h": 1000000.0,
            "minOpenInterestUsd": 500000.0,
            "minListingAgeDays": 30,
            "maxRecentVolatilityPct": 5.5,
        }

    def test_none_values_default_to_zero(self):
        result = _normalize_filters({
            "minQuoteVolume24h": None,
            "minOpenInterestUsd": None,
        })
        assert result["minQuoteVolume24h"] == 0.0
        assert result["minOpenInterestUsd"] == 0.0

    def test_string_numeric_values(self):
        result = _normalize_filters({
            "minQuoteVolume24h": "100000",
            "minListingAgeDays": "7",
        })
        assert result["minQuoteVolume24h"] == 100000.0
        assert result["minListingAgeDays"] == 7


# ── _create_exchange ────────────────────────────────────────────────

class TestCreateExchange:
    def test_okx(self):
        exchange = _create_exchange("okx")
        assert isinstance(exchange, ccxt.okx)

    def test_binance(self):
        exchange = _create_exchange("binance")
        assert isinstance(exchange, ccxt.binance)

    def test_bybit(self):
        exchange = _create_exchange("bybit")
        assert isinstance(exchange, ccxt.bybit)

    def test_case_insensitive(self):
        exchange = _create_exchange("OKX")
        assert isinstance(exchange, ccxt.okx)

    def test_whitespace_trimmed(self):
        exchange = _create_exchange("  binance  ")
        assert isinstance(exchange, ccxt.binance)

    def test_unsupported_exchange_raises(self):
        with pytest.raises(ValueError, match="Unsupported exchange"):
            _create_exchange("kraken")

    def test_binance_options(self):
        exchange = _create_exchange("binance")
        assert exchange.options.get("defaultType") == "swap"


# ── _is_usdt_perpetual ──────────────────────────────────────────────

class TestIsUsdtPerpetual:
    def test_valid_swap(self):
        market = {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap"}
        assert _is_usdt_perpetual(market) is True

    def test_binance_swap_only(self):
        market = {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap"}
        assert _is_usdt_perpetual(market, "binance") is True

    def test_binance_future_rejected(self):
        market = {"active": True, "quote": "USDT", "settle": "USDT", "type": "future"}
        assert _is_usdt_perpetual(market, "binance") is False

    def test_non_binance_future_accepted(self):
        market = {"active": True, "quote": "USDT", "settle": "USDT", "type": "future"}
        assert _is_usdt_perpetual(market, "okx") is True

    def test_inactive_market(self):
        market = {"active": False, "quote": "USDT", "settle": "USDT", "type": "swap"}
        assert _is_usdt_perpetual(market) is False

    def test_non_usdt_quote(self):
        market = {"active": True, "quote": "BTC", "settle": "USDT", "type": "swap"}
        assert _is_usdt_perpetual(market) is False

    def test_non_usdt_settle(self):
        market = {"active": True, "quote": "USDT", "settle": "BTC", "type": "swap"}
        assert _is_usdt_perpetual(market) is False

    def test_spot_type(self):
        market = {"active": True, "quote": "USDT", "settle": "USDT", "type": "spot"}
        assert _is_usdt_perpetual(market) is False


# ── _calculate_usdt_volume ──────────────────────────────────────────

class TestCalculateUsdtVolume:
    def test_quote_volume(self):
        ticker = {"quoteVolume": 1000000}
        assert _calculate_usdt_volume(ticker) == 1000000.0

    def test_quote_volume_zero_fallback(self):
        ticker = {"quoteVolume": 0, "last": 50000, "baseVolume": 100}
        assert _calculate_usdt_volume(ticker) == 5000000.0

    def test_quote_volume_none_fallback(self):
        ticker = {"quoteVolume": None, "last": 50000, "baseVolume": 100}
        assert _calculate_usdt_volume(ticker) == 5000000.0

    def test_last_price_from_close(self):
        ticker = {"close": 50000, "baseVolume": 100}
        assert _calculate_usdt_volume(ticker) == 5000000.0

    def test_okx_volCcy24h(self):
        ticker = {"last": 50000, "info": {"volCcy24h": "200"}}
        assert _calculate_usdt_volume(ticker) == 10000000.0

    def test_okx_volCcy24h_invalid(self):
        ticker = {"last": 50000, "info": {"volCcy24h": "invalid"}, "baseVolume": 100}
        assert _calculate_usdt_volume(ticker) == 5000000.0

    def test_no_volume(self):
        ticker = {"last": 50000}
        assert _calculate_usdt_volume(ticker) == 0

    def test_no_price(self):
        ticker = {"baseVolume": 100}
        assert _calculate_usdt_volume(ticker) == 0

    def test_zero_price(self):
        ticker = {"last": 0, "baseVolume": 100}
        assert _calculate_usdt_volume(ticker) == 0


# ── _listing_age_days ───────────────────────────────────────────────

class TestListingAgeDays:
    def test_no_created(self):
        assert _listing_age_days({}) == 0

    @patch("kairos.utils.top_volume_symbols.time.time")
    def test_recent_listing(self, mock_time):
        mock_time.return_value = 1700000000  # ~2023-11-14
        # 1 day ago in ms
        created = (1700000000 - 86400) * 1000
        assert _listing_age_days({"created": created}) == 1

    @patch("kairos.utils.top_volume_symbols.time.time")
    def test_old_listing(self, mock_time):
        mock_time.return_value = 1700000000
        # 100 days ago in ms
        created = (1700000000 - 100 * 86400) * 1000
        assert _listing_age_days({"created": created}) == 100


# ── _extract_open_interest_usd ──────────────────────────────────────

class TestExtractOpenInterestUsd:
    def test_none_input(self):
        assert _extract_open_interest_usd(None, None) == 0

    def test_empty_dict(self):
        assert _extract_open_interest_usd({}, {}) == 0

    def test_openInterestValue(self):
        oi = {"openInterestValue": 1000000}
        assert _extract_open_interest_usd(oi, None) == 1000000.0

    def test_openInterestUsd(self):
        oi = {"openInterestUsd": 500000}
        assert _extract_open_interest_usd(oi, None) == 500000.0

    def test_openInterestAmountUsd(self):
        oi = {"openInterestAmountUsd": 250000}
        assert _extract_open_interest_usd(oi, None) == 250000.0

    def test_openInterestQuote(self):
        oi = {"openInterestQuote": 750000}
        assert _extract_open_interest_usd(oi, None) == 750000.0

    def test_amount_times_last_price(self):
        oi = {"openInterestAmount": 10}
        ticker = {"last": 50000}
        assert _extract_open_interest_usd(oi, ticker) == 500000.0

    def test_amount_times_close_price(self):
        oi = {"openInterestAmount": 10}
        ticker = {"close": 50000}
        assert _extract_open_interest_usd(oi, ticker) == 500000.0

    def test_no_amount_no_price(self):
        oi = {"openInterestAmount": 10}
        assert _extract_open_interest_usd(oi, None) == 0

    def test_non_dict_input(self):
        assert _extract_open_interest_usd("invalid", None) == 0


# ── _recent_volatility_pct ──────────────────────────────────────────

class TestRecentVolatilityPct:
    def test_candles_with_moves(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_ohlcv.return_value = [
            [0, 0, 0, 0, 100],
            [0, 0, 0, 0, 105],
            [0, 0, 0, 0, 102],
        ]
        result = _recent_volatility_pct(mock_exchange, "BTC/USDT")
        # max move: 5% (100->105)
        assert result == pytest.approx(5.0)

    def test_two_candles_calculates_move(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_ohlcv.return_value = [
            [0, 0, 0, 0, 100],
            [0, 0, 0, 0, 110],
        ]
        result = _recent_volatility_pct(mock_exchange, "BTC/USDT")
        assert result == pytest.approx(10.0)

    def test_negative_close_returns_inf(self):
        """Negative close passes truthiness check, hits prev<=0 branch."""
        mock_exchange = MagicMock()
        mock_exchange.fetch_ohlcv.return_value = [
            [0, 0, 0, 0, -1],
            [0, 0, 0, 0, 100],
        ]
        result = _recent_volatility_pct(mock_exchange, "BTC/USDT")
        assert result == float("inf")

    def test_single_candle_returns_inf(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_ohlcv.return_value = [[0, 0, 0, 0, 100]]
        result = _recent_volatility_pct(mock_exchange, "BTC/USDT")
        assert result == float("inf")

    def test_fetch_error_returns_inf(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_ohlcv.side_effect = Exception("network error")
        result = _recent_volatility_pct(mock_exchange, "BTC/USDT")
        assert result == float("inf")

    def test_empty_candles(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_ohlcv.return_value = []
        result = _recent_volatility_pct(mock_exchange, "BTC/USDT")
        assert result == float("inf")

    def test_zero_previous_close(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_ohlcv.return_value = [
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 100],
        ]
        result = _recent_volatility_pct(mock_exchange, "BTC/USDT")
        assert result == float("inf")


# ── _fetch_tickers_for_exchange ─────────────────────────────────────

class TestFetchTickersForExchange:
    def test_okx_with_instType(self):
        mock_exchange = MagicMock()
        mock_exchange.id = "okx"
        mock_exchange.fetch_tickers.return_value = {"BTC/USDT": {"last": 50000}}
        result = _fetch_tickers_for_exchange(mock_exchange, ["BTC/USDT"])
        assert "BTC/USDT" in result
        mock_exchange.fetch_tickers.assert_called_with(params={"instType": "SWAP"})

    def test_bybit_with_instType(self):
        mock_exchange = MagicMock()
        mock_exchange.id = "bybit"
        mock_exchange.fetch_tickers.return_value = {"BTC/USDT": {"last": 50000}}
        result = _fetch_tickers_for_exchange(mock_exchange, ["BTC/USDT"])
        mock_exchange.fetch_tickers.assert_called_with(params={"instType": "SWAP"})

    def test_binance_fallback(self):
        mock_exchange = MagicMock()
        mock_exchange.id = "binance"
        mock_exchange.fetch_tickers.return_value = {"BTC/USDT": {"last": 50000}}
        result = _fetch_tickers_for_exchange(mock_exchange, ["BTC/USDT"])
        mock_exchange.fetch_tickers.assert_called_with()

    def test_instType_fails_fallback(self):
        mock_exchange = MagicMock()
        mock_exchange.id = "okx"
        mock_exchange.fetch_tickers.side_effect = [
            Exception("instType error"),
            {"BTC/USDT": {"last": 50000}},
        ]
        result = _fetch_tickers_for_exchange(mock_exchange, ["BTC/USDT"])
        assert "BTC/USDT" in result

    def test_all_fetches_fail(self):
        mock_exchange = MagicMock()
        mock_exchange.id = "binance"
        mock_exchange.fetch_tickers.side_effect = Exception("all fail")
        mock_exchange.fetch_ticker.return_value = {"BTC/USDT": {"last": 50000}}
        result = _fetch_tickers_for_exchange(mock_exchange, ["BTC/USDT"])
        # Should fallback to individual fetch
        mock_exchange.fetch_ticker.assert_called()


# ── _fetch_open_interest_map ────────────────────────────────────────

class TestFetchOpenInterestMap:
    def test_batch_fetch(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_open_interests.return_value = {"BTC/USDT": {"openInterestUsd": 1000}}
        result = _fetch_open_interest_map(mock_exchange, ["BTC/USDT"])
        assert result == {"BTC/USDT": {"openInterestUsd": 1000}}

    def test_batch_fetch_fails_fallback(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_open_interests.side_effect = Exception("batch error")
        mock_exchange.fetch_open_interest.return_value = {"openInterestUsd": 500}
        result = _fetch_open_interest_map(mock_exchange, ["BTC/USDT"])
        assert "BTC/USDT" in result
        assert result["BTC/USDT"] == {"openInterestUsd": 500}

    def test_individual_fetch_exception_skips(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_open_interests.side_effect = Exception("batch error")
        mock_exchange.fetch_open_interest.side_effect = Exception("individual error")
        result = _fetch_open_interest_map(mock_exchange, ["BTC/USDT"])
        assert "BTC/USDT" not in result

    def test_no_batch_support(self):
        mock_exchange = MagicMock(spec=[])  # No fetch_open_interests
        result = _fetch_open_interest_map(mock_exchange, ["BTC/USDT"])
        assert result == {}


# ── _fetch_tickers_individually ─────────────────────────────────────

class TestFetchTickersIndividually:
    def test_success(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_ticker.return_value = {"last": 50000}
        result = _fetch_tickers_individually(mock_exchange, ["BTC/USDT"])
        assert "BTC/USDT" in result

    def test_failure_skips(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_ticker.side_effect = Exception("fail")
        result = _fetch_tickers_individually(mock_exchange, ["BTC/USDT"])
        assert result == {}


# ── get_cache_age ───────────────────────────────────────────────────

class TestGetCacheAge:
    def test_no_cache(self):
        assert get_cache_age("binance") is None

    def test_cached_returns_age(self):
        cache_key = _default_cache_key("binance", 20)
        _get_cache()[cache_key] = (["BTC/USDT"], time.time() - 100)
        age = get_cache_age("binance", 20)
        assert age is not None
        assert age >= 100

    def test_custom_filters_key(self):
        filters = {"minQuoteVolume24h": 1000000}
        normalized = _normalize_filters(filters)
        cache_key = f"okx_10_{tuple(sorted(normalized.items()))}"
        _get_cache()[cache_key] = (["ETH/USDT"], time.time() - 50)
        age = get_cache_age("okx", 10, filters)
        assert age is not None


# ── clear_cache ─────────────────────────────────────────────────────

class TestClearCache:
    def test_clears_cache(self):
        _get_cache()["test"] = (["BTC/USDT"], time.time())
        assert len(_get_cache()) == 1
        clear_cache()
        assert len(_get_cache()) == 0


# ── _fetch_symbols_by_volume ────────────────────────────────────────

class TestFetchSymbolsByVolume:
    def test_no_usdt_futures(self):
        mock_exchange = MagicMock()
        mock_exchange.id = "binance"
        mock_exchange.markets = {"BTC/BTC": {"active": True, "quote": "BTC", "settle": "BTC", "type": "swap"}}
        result = _fetch_symbols_by_volume(mock_exchange, 10, _normalize_filters({}))
        assert result == []

    def test_basic_volume_sorting(self):
        mock_exchange = MagicMock()
        mock_exchange.id = "binance"
        mock_exchange.markets = {
            "BTC/USDT": {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap"},
            "ETH/USDT": {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap"},
        }
        mock_exchange.fetch_tickers.return_value = {
            "BTC/USDT": {"quoteVolume": 2000000},
            "ETH/USDT": {"quoteVolume": 1000000},
        }
        result = _fetch_symbols_by_volume(mock_exchange, 10, _normalize_filters({}))
        assert result == ["BTC/USDT", "ETH/USDT"]

    def test_min_volume_filter(self):
        mock_exchange = MagicMock()
        mock_exchange.id = "binance"
        mock_exchange.markets = {
            "BTC/USDT": {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap"},
            "ETH/USDT": {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap"},
        }
        mock_exchange.fetch_tickers.return_value = {
            "BTC/USDT": {"quoteVolume": 2000000},
            "ETH/USDT": {"quoteVolume": 500000},
        }
        filters = _normalize_filters({"minQuoteVolume24h": 1000000})
        result = _fetch_symbols_by_volume(mock_exchange, 10, filters)
        assert result == ["BTC/USDT"]

    def test_limit_respected(self):
        mock_exchange = MagicMock()
        mock_exchange.id = "binance"
        mock_exchange.markets = {
            "BTC/USDT": {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap"},
            "ETH/USDT": {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap"},
            "SOL/USDT": {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap"},
        }
        mock_exchange.fetch_tickers.return_value = {
            "BTC/USDT": {"quoteVolume": 3000000},
            "ETH/USDT": {"quoteVolume": 2000000},
            "SOL/USDT": {"quoteVolume": 1000000},
        }
        result = _fetch_symbols_by_volume(mock_exchange, 2, _normalize_filters({}))
        assert len(result) == 2
        assert result[0] == "BTC/USDT"

    def test_missing_ticker_skipped(self):
        mock_exchange = MagicMock()
        mock_exchange.id = "binance"
        mock_exchange.markets = {
            "BTC/USDT": {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap"},
            "ETH/USDT": {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap"},
        }
        mock_exchange.fetch_tickers.return_value = {
            "BTC/USDT": {"quoteVolume": 2000000},
            # ETH/USDT missing
        }
        result = _fetch_symbols_by_volume(mock_exchange, 10, _normalize_filters({}))
        assert result == ["BTC/USDT"]

    def test_open_interest_filter(self):
        mock_exchange = MagicMock()
        mock_exchange.id = "binance"
        mock_exchange.markets = {
            "BTC/USDT": {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap"},
            "ETH/USDT": {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap"},
        }
        mock_exchange.fetch_tickers.return_value = {
            "BTC/USDT": {"quoteVolume": 2000000},
            "ETH/USDT": {"quoteVolume": 1000000},
        }
        mock_exchange.fetch_open_interests.return_value = {
            "BTC/USDT": {"openInterestValue": 1000000},
            "ETH/USDT": {"openInterestValue": 500000},
        }
        filters = _normalize_filters({"minOpenInterestUsd": 800000})
        result = _fetch_symbols_by_volume(mock_exchange, 10, filters)
        assert result == ["BTC/USDT"]

    def test_listing_age_filter(self):
        mock_exchange = MagicMock()
        mock_exchange.id = "binance"
        now_ms = int(time.time() * 1000)
        mock_exchange.markets = {
            "BTC/USDT": {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap", "created": now_ms - 100 * 86400 * 1000},
            "ETH/USDT": {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap", "created": now_ms - 10 * 86400 * 1000},
        }
        mock_exchange.fetch_tickers.return_value = {
            "BTC/USDT": {"quoteVolume": 2000000},
            "ETH/USDT": {"quoteVolume": 1000000},
        }
        filters = _normalize_filters({"minListingAgeDays": 30})
        result = _fetch_symbols_by_volume(mock_exchange, 10, filters)
        assert result == ["BTC/USDT"]

    def test_volatility_filter(self):
        mock_exchange = MagicMock()
        mock_exchange.id = "binance"
        mock_exchange.markets = {
            "BTC/USDT": {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap"},
            "ETH/USDT": {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap"},
        }
        mock_exchange.fetch_tickers.return_value = {
            "BTC/USDT": {"quoteVolume": 2000000},
            "ETH/USDT": {"quoteVolume": 1000000},
        }
        # BTC volatility = 10%, ETH volatility = 3%
        mock_exchange.fetch_ohlcv.side_effect = [
            [[0, 0, 0, 0, 100], [0, 0, 0, 0, 110]],  # BTC: 10%
            [[0, 0, 0, 0, 100], [0, 0, 0, 0, 103]],  # ETH: 3%
        ]
        filters = _normalize_filters({"maxRecentVolatilityPct": 5})
        result = _fetch_symbols_by_volume(mock_exchange, 10, filters)
        assert result == ["ETH/USDT"]

    def test_all_filtered_out(self):
        mock_exchange = MagicMock()
        mock_exchange.id = "binance"
        mock_exchange.markets = {
            "BTC/USDT": {"active": True, "quote": "USDT", "settle": "USDT", "type": "swap"},
        }
        mock_exchange.fetch_tickers.return_value = {
            "BTC/USDT": {"quoteVolume": 100},
        }
        filters = _normalize_filters({"minQuoteVolume24h": 1000000})
        result = _fetch_symbols_by_volume(mock_exchange, 10, filters)
        assert result == []


# ── fetch_top_volume_symbols ────────────────────────────────────────

class TestFetchTopVolumeSymbols:
    @patch("kairos.utils.top_volume_symbols._create_exchange")
    @patch("kairos.utils.top_volume_symbols._fetch_symbols_by_volume")
    def test_basic_fetch(self, mock_fetch, mock_create):
        mock_create.return_value = MagicMock()
        mock_fetch.return_value = ["BTC/USDT", "ETH/USDT"]
        result = fetch_top_volume_symbols("binance", 10)
        assert result == ["BTC/USDT", "ETH/USDT"]
        mock_create.assert_called_once_with("binance")

    @patch("kairos.utils.top_volume_symbols._create_exchange")
    @patch("kairos.utils.top_volume_symbols._fetch_symbols_by_volume")
    def test_caching(self, mock_fetch, mock_create):
        mock_create.return_value = MagicMock()
        mock_fetch.return_value = ["BTC/USDT"]
        # First call
        result1 = fetch_top_volume_symbols("binance", 10)
        # Second call (should use cache)
        result2 = fetch_top_volume_symbols("binance", 10)
        assert result1 == result2
        mock_create.assert_called_once()  # Only called once

    @patch("kairos.utils.top_volume_symbols._create_exchange")
    @patch("kairos.utils.top_volume_symbols._fetch_symbols_by_volume")
    def test_cache_expiry(self, mock_fetch, mock_create):
        mock_create.return_value = MagicMock()
        mock_fetch.return_value = ["BTC/USDT"]
        # First call
        fetch_top_volume_symbols("binance", 10)
        # Manually expire cache
        cache = _get_cache()
        for key in list(cache.keys()):
            data, _ = cache[key]
            cache[key] = (data, time.time() - _CACHE_TTL_SECONDS - 1)
        # Second call (should refetch)
        fetch_top_volume_symbols("binance", 10)
        assert mock_create.call_count == 2

    @patch("kairos.utils.top_volume_symbols._create_exchange")
    def test_error_with_cache_fallback(self, mock_create):
        mock_create.side_effect = Exception("connection error")
        # Pre-populate cache
        cache_key = _default_cache_key("binance", 20)
        _get_cache()[cache_key] = (["BTC/USDT"], time.time() - _CACHE_TTL_SECONDS - 1)
        result = fetch_top_volume_symbols("binance", 20)
        assert result == ["BTC/USDT"]  # Fallback to expired cache

    @patch("kairos.utils.top_volume_symbols._create_exchange")
    def test_error_no_cache_returns_empty(self, mock_create):
        mock_create.side_effect = Exception("connection error")
        result = fetch_top_volume_symbols("binance", 20)
        assert result == []

    @patch("kairos.utils.top_volume_symbols._create_exchange")
    @patch("kairos.utils.top_volume_symbols._fetch_symbols_by_volume")
    def test_empty_result_not_cached(self, mock_fetch, mock_create):
        mock_create.return_value = MagicMock()
        mock_fetch.return_value = []
        fetch_top_volume_symbols("binance", 10)
        # Cache should be empty
        assert len(_get_cache()) == 0

    @patch("kairos.utils.top_volume_symbols._create_exchange")
    @patch("kairos.utils.top_volume_symbols._fetch_symbols_by_volume")
    def test_custom_filters(self, mock_fetch, mock_create):
        mock_create.return_value = MagicMock()
        mock_fetch.return_value = ["BTC/USDT"]
        filters = {"minQuoteVolume24h": 1000000}
        result = fetch_top_volume_symbols("binance", 10, filters)
        assert result == ["BTC/USDT"]
        # Verify filters passed correctly
        call_args = mock_fetch.call_args
        assert call_args[0][2]["minQuoteVolume24h"] == 1000000.0


# ── Integration-style tests ─────────────────────────────────────────

class TestIntegration:
    def test_full_flow_with_all_filters(self):
        """Test complete flow with all filter types active."""
        mock_exchange = MagicMock()
        mock_exchange.id = "binance"
        now_ms = int(time.time() * 1000)
        mock_exchange.markets = {
            "BTC/USDT": {
                "active": True, "quote": "USDT", "settle": "USDT", "type": "swap",
                "created": now_ms - 100 * 86400 * 1000,
            },
            "ETH/USDT": {
                "active": True, "quote": "USDT", "settle": "USDT", "type": "swap",
                "created": now_ms - 5 * 86400 * 1000,
            },
        }
        mock_exchange.fetch_tickers.return_value = {
            "BTC/USDT": {"quoteVolume": 2000000, "last": 50000},
            "ETH/USDT": {"quoteVolume": 1000000, "last": 3000},
        }
        mock_exchange.fetch_open_interests.return_value = {
            "BTC/USDT": {"openInterestValue": 1000000},
            "ETH/USDT": {"openInterestValue": 100000},
        }
        # BTC: 2% vol, ETH: 8% vol
        mock_exchange.fetch_ohlcv.side_effect = [
            [[0, 0, 0, 0, 100], [0, 0, 0, 0, 102]],
            [[0, 0, 0, 0, 100], [0, 0, 0, 0, 108]],
        ]

        filters = {
            "minQuoteVolume24h": 500000,
            "minOpenInterestUsd": 200000,
            "minListingAgeDays": 30,
            "maxRecentVolatilityPct": 5,
        }

        with patch("kairos.utils.top_volume_symbols._create_exchange", return_value=mock_exchange):
            result = fetch_top_volume_symbols("binance", 10, filters)
            assert result == ["BTC/USDT"]
