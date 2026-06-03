"""Comprehensive tests for FundingRateMonitor."""

import time
from unittest.mock import MagicMock, patch

import pytest

from kairos.arbitrage.funding_monitor import (
    FundingOpportunity,
    FundingRate,
    FundingRateMonitor,
)


class TestFundingRate:
    """Test FundingRate dataclass."""

    def test_creation(self):
        rate = FundingRate(
            symbol="BTC/USDT",
            exchange="binance",
            rate=0.01,
            annualized=36.5,
        )
        assert rate.symbol == "BTC/USDT"
        assert rate.exchange == "binance"
        assert rate.rate == 0.01
        assert rate.annualized == 36.5

    def test_is_extreme(self):
        rate = FundingRate("BTC/USDT", "binance", 0.1, 100.0)
        assert rate.is_extreme is True

    def test_is_not_extreme(self):
        rate = FundingRate("BTC/USDT", "binance", 0.001, 10.0)
        assert rate.is_extreme is False

    def test_direction_positive(self):
        rate = FundingRate("BTC/USDT", "binance", 0.01, 36.5)
        assert rate.direction == "positive"

    def test_direction_negative(self):
        rate = FundingRate("BTC/USDT", "binance", -0.01, -36.5)
        assert rate.direction == "negative"


class TestFundingOpportunity:
    """Test FundingOpportunity dataclass."""

    def test_creation(self):
        opp = FundingOpportunity(
            symbol="BTC/USDT",
            exchange_long="binance",
            exchange_short="okx",
            rate_long=-0.01,
            rate_short=0.02,
            spread=0.03,
            annualized_spread=10.95,
            estimated_daily_profit_pct=0.03,
            confidence=0.8,
        )
        assert opp.symbol == "BTC/USDT"
        assert opp.spread == 0.03
        assert opp.confidence == 0.8


class TestFundingRateMonitor:
    """Test FundingRateMonitor class."""

    @pytest.fixture
    def monitor(self):
        with patch("kairos.arbitrage.funding_monitor.ccxt"):
            config = {
                "exchanges": ["binance"],
                "minSpreadPct": 0.05,
                "extremeRateThreshold": 0.05,
                "updateInterval": 300,
            }
            return FundingRateMonitor(config)

    def test_init(self, monitor):
        assert monitor.min_spread_pct == 0.05
        assert monitor.extreme_rate_threshold == 0.05
        assert monitor.update_interval == 300

    def test_init_default_config(self):
        with patch("kairos.arbitrage.funding_monitor.ccxt"):
            monitor = FundingRateMonitor()
            assert monitor.min_spread_pct == 0.05

    def test_add_funding_rate(self, monitor):
        rate = FundingRate("BTC/USDT", "binance", 0.01, 36.5)
        monitor.add_funding_rate(rate)
        assert "binance" in monitor.funding_rates
        assert "BTC/USDT" in monitor.funding_rates["binance"]

    def test_get_funding_rate(self, monitor):
        rate = FundingRate("BTC/USDT", "binance", 0.01, 36.5)
        monitor.add_funding_rate(rate)

        result = monitor.get_funding_rate("BTC/USDT", "binance")
        assert result is not None
        assert result.rate == 0.01

    def test_get_funding_rate_not_found(self, monitor):
        result = monitor.get_funding_rate("BTC/USDT", "binance")
        assert result is None

    def test_get_all_rates_for_symbol(self, monitor):
        rate1 = FundingRate("BTC/USDT", "binance", 0.01, 36.5)
        rate2 = FundingRate("BTC/USDT", "okx", -0.02, -73.0)
        monitor.add_funding_rate(rate1)
        monitor.add_funding_rate(rate2)

        rates = monitor.get_all_rates_for_symbol("BTC/USDT")
        assert len(rates) == 2

    def test_get_all_rates_for_symbol_empty(self, monitor):
        rates = monitor.get_all_rates_for_symbol("BTC/USDT")
        assert len(rates) == 0

    def test_find_opportunities(self, monitor):
        rate1 = FundingRate("BTC/USDT", "binance", -0.02, -73.0)
        rate2 = FundingRate("BTC/USDT", "okx", 0.03, 109.5)
        monitor.add_funding_rate(rate1)
        monitor.add_funding_rate(rate2)

        opportunities = monitor.find_opportunities()
        assert len(opportunities) > 0
        assert opportunities[0].symbol == "BTC/USDT"

    def test_find_opportunities_no_spread(self, monitor):
        rate1 = FundingRate("BTC/USDT", "binance", 0.01, 36.5)
        rate2 = FundingRate("BTC/USDT", "okx", 0.01, 36.5)
        monitor.add_funding_rate(rate1)
        monitor.add_funding_rate(rate2)

        opportunities = monitor.find_opportunities()
        assert len(opportunities) == 0

    def test_find_opportunities_below_threshold(self, monitor):
        rate1 = FundingRate("BTC/USDT", "binance", 0.01, 36.5)
        rate2 = FundingRate("BTC/USDT", "okx", 0.02, 73.0)
        monitor.add_funding_rate(rate1)
        monitor.add_funding_rate(rate2)

        # Spread is 0.01, below threshold of 0.05
        opportunities = monitor.find_opportunities()
        assert len(opportunities) == 0

    def test_get_extreme_rates(self, monitor):
        rate1 = FundingRate("BTC/USDT", "binance", 0.1, 100.0)
        rate2 = FundingRate("ETH/USDT", "okx", 0.001, 10.0)
        monitor.add_funding_rate(rate1)
        monitor.add_funding_rate(rate2)

        extreme = monitor.get_extreme_rates()
        assert len(extreme) == 1
        assert extreme[0].symbol == "BTC/USDT"

    def test_clear_rates(self, monitor):
        rate = FundingRate("BTC/USDT", "binance", 0.01, 36.5)
        monitor.add_funding_rate(rate)

        monitor.clear_rates()
        assert len(monitor.funding_rates.get("binance", {})) == 0

    def test_get_stats(self, monitor):
        rate = FundingRate("BTC/USDT", "binance", 0.01, 36.5)
        monitor.add_funding_rate(rate)

        stats = monitor.get_stats()
        assert "total_rates" in stats
        assert stats["total_rates"] == 1
