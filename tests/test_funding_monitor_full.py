"""Comprehensive tests for FundingRateMonitor with 95%+ coverage."""

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kairos.arbitrage.funding_monitor import (
    FundingOpportunity,
    FundingRate,
    FundingRateMonitor,
)


class TestFundingRate:
    """Test FundingRate dataclass."""

    def test_init_defaults(self):
        """Test default values."""
        rate = FundingRate(symbol="BTC/USDT", exchange="binance", rate=0.01, annualized=36.5)
        assert rate.symbol == "BTC/USDT"
        assert rate.exchange == "binance"
        assert rate.rate == 0.01
        assert rate.annualized == 36.5
        assert rate.next_time is None
        assert isinstance(rate.timestamp, float)

    def test_init_with_next_time(self):
        """Test with next_time provided."""
        rate = FundingRate(
            symbol="ETH/USDT",
            exchange="okx",
            rate=-0.02,
            annualized=-73.0,
            next_time="2024-01-01T08:00:00",
        )
        assert rate.next_time == "2024-01-01T08:00:00"

    def test_is_extreme_true(self):
        """Test is_extreme with annualized > 50."""
        rate = FundingRate("BTC/USDT", "binance", 0.1, 100.0)
        assert rate.is_extreme is True

    def test_is_extreme_true_negative(self):
        """Test is_extreme with annualized < -50."""
        rate = FundingRate("BTC/USDT", "binance", -0.1, -100.0)
        assert rate.is_extreme is True

    def test_is_extreme_false(self):
        """Test is_extreme with annualized within 50."""
        rate = FundingRate("BTC/USDT", "binance", 0.01, 10.0)
        assert rate.is_extreme is False

    def test_is_extreme_boundary(self):
        """Test is_extreme at boundary (50)."""
        rate = FundingRate("BTC/USDT", "binance", 0.05, 50.0)
        assert rate.is_extreme is False  # 50 is not > 50

    def test_direction_positive(self):
        """Test direction with positive rate."""
        rate = FundingRate("BTC/USDT", "binance", 0.01, 36.5)
        assert rate.direction == "positive"

    def test_direction_negative(self):
        """Test direction with negative rate."""
        rate = FundingRate("BTC/USDT", "binance", -0.01, -36.5)
        assert rate.direction == "negative"

    def test_direction_zero(self):
        """Test direction with zero rate."""
        rate = FundingRate("BTC/USDT", "binance", 0.0, 0.0)
        assert rate.direction == "negative"  # 0 > 0 is False


class TestFundingOpportunity:
    """Test FundingOpportunity dataclass."""

    def test_init(self):
        """Test full initialization."""
        opp = FundingOpportunity(
            symbol="BTC/USDT",
            exchange_long="okx",
            exchange_short="binance",
            rate_long=-0.02,
            rate_short=0.03,
            spread=0.05,
            annualized_spread=54.75,
            estimated_daily_profit_pct=0.15,
            confidence=0.7,
            reason="Funding spread",
        )
        assert opp.symbol == "BTC/USDT"
        assert opp.exchange_long == "okx"
        assert opp.exchange_short == "binance"
        assert opp.rate_long == -0.02
        assert opp.rate_short == 0.03
        assert opp.spread == 0.05
        assert opp.annualized_spread == 54.75
        assert opp.estimated_daily_profit_pct == 0.15
        assert opp.confidence == 0.7
        assert opp.reason == "Funding spread"

    def test_init_default_reason(self):
        """Test default empty reason."""
        opp = FundingOpportunity(
            symbol="ETH/USDT",
            exchange_long="binance",
            exchange_short="okx",
            rate_long=0.01,
            rate_short=0.02,
            spread=0.01,
            annualized_spread=10.95,
            estimated_daily_profit_pct=0.03,
            confidence=0.5,
        )
        assert opp.reason == ""


class TestFundingRateMonitorInit:
    """Test FundingRateMonitor initialization."""

    @patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True)
    def test_init_default_config(self, mock_ccxt):
        """Test with default config."""
        mock_ccxt.binance = MagicMock()
        mock_ccxt.okx = MagicMock()
        mock_ccxt.bybit = MagicMock()

        monitor = FundingRateMonitor()

        assert monitor.min_spread_pct == 0.05
        assert monitor.extreme_rate_threshold == 0.05
        assert monitor.update_interval == 300
        assert "binance" in monitor.exchanges
        assert "okx" in monitor.exchanges
        assert "bybit" in monitor.exchanges

    @patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True)
    def test_init_custom_config(self, mock_ccxt):
        """Test with custom config."""
        mock_ccxt.binance = MagicMock()
        config = {
            "exchanges": ["binance"],
            "minSpreadPct": 0.1,
            "extremeRateThreshold": 0.1,
            "updateInterval": 600,
            "binance": {"apiKey": "key", "secret": "secret"},
        }
        monitor = FundingRateMonitor(config)

        assert monitor.min_spread_pct == 0.1
        assert monitor.extreme_rate_threshold == 0.1
        assert monitor.update_interval == 600
        assert len(monitor.exchanges) == 1

    @patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True)
    def test_init_exchange_failure(self, mock_ccxt):
        """Test exchange initialization failure."""
        type(mock_ccxt).__getattr__ = MagicMock(side_effect=AttributeError("No such exchange"))
        monitor = FundingRateMonitor({"exchanges": ["invalid"]})
        assert len(monitor.exchanges) == 0

    @patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True)
    def test_init_exchange_with_password(self, mock_ccxt):
        """Test exchange with password config."""
        mock_exchange_class = MagicMock()
        mock_ccxt.okx = mock_exchange_class
        config = {
            "exchanges": ["okx"],
            "okx": {"apiKey": "key", "secret": "secret", "password": "pass"},
        }
        monitor = FundingRateMonitor(config)
        assert monitor is not None
        mock_exchange_class.assert_called_once_with(
            {
                "enableRateLimit": True,
                "apiKey": "key",
                "secret": "secret",
                "password": "pass",
            }
        )


class TestFundingRateMonitorFetch:
    """Test funding rate fetching."""

    @pytest.fixture
    def monitor(self):
        """Create monitor with mocked exchanges."""
        with patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True) as mock_ccxt:
            mock_binance = MagicMock()
            mock_ccxt.binance = MagicMock(return_value=mock_binance)
            monitor = FundingRateMonitor({"exchanges": ["binance"]})
            monitor.exchanges["binance"] = mock_binance
            return monitor

    @pytest.mark.asyncio
    async def test_update_funding_rates_success(self, monitor):
        """Test successful funding rate update."""
        mock_exchange = monitor.exchanges["binance"]
        mock_exchange.fetch_funding_rates = AsyncMock(
            return_value={
                "BTC/USDT": {
                    "fundingRate": 0.01,
                    "fundingDatetime": "2024-01-01T08:00:00",
                    "timestamp": 1704067200000,
                },
            }
        )

        await monitor.update_funding_rates()

        assert "BTC/USDT" in monitor.funding_rates["binance"]
        rate = monitor.funding_rates["binance"]["BTC/USDT"]
        assert rate.rate == 1.0  # 0.01 * 100
        assert rate.annualized == 0.01 * 3 * 365 * 100

    @pytest.mark.asyncio
    async def test_update_funding_rates_with_symbols(self, monitor):
        """Test update with specific symbols."""
        mock_exchange = monitor.exchanges["binance"]
        mock_exchange.fetch_funding_rates = AsyncMock(
            return_value={
                "BTC/USDT": {"fundingRate": 0.01},
            }
        )

        await monitor.update_funding_rates(["BTC/USDT"])

        mock_exchange.fetch_funding_rates.assert_called_once_with(["BTC/USDT"])

    @pytest.mark.asyncio
    async def test_update_funding_rates_none_rate(self, monitor):
        """Test handling of None funding rate."""
        mock_exchange = monitor.exchanges["binance"]
        mock_exchange.fetch_funding_rates = AsyncMock(
            return_value={
                "BTC/USDT": {"fundingRate": None},
            }
        )

        await monitor.update_funding_rates()

        assert "BTC/USDT" not in monitor.funding_rates["binance"]

    @pytest.mark.asyncio
    async def test_update_funding_rates_exception(self, monitor):
        """Test handling of fetch exception."""
        mock_exchange = monitor.exchanges["binance"]
        mock_exchange.fetch_funding_rates = AsyncMock(side_effect=Exception("Network error"))

        # Should not raise
        await monitor.update_funding_rates()

    @pytest.mark.asyncio
    async def test_update_funding_rates_multiple_exchanges(self):
        """Test updating multiple exchanges."""
        with patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True) as mock_ccxt:
            mock_binance = MagicMock()
            mock_okx = MagicMock()
            mock_ccxt.binance = MagicMock(return_value=mock_binance)
            mock_ccxt.okx = MagicMock(return_value=mock_okx)

            monitor = FundingRateMonitor({"exchanges": ["binance", "okx"]})
            monitor.exchanges["binance"] = mock_binance
            monitor.exchanges["okx"] = mock_okx

            mock_binance.fetch_funding_rates = AsyncMock(
                return_value={
                    "BTC/USDT": {"fundingRate": 0.01},
                }
            )
            mock_okx.fetch_funding_rates = AsyncMock(
                return_value={
                    "BTC/USDT": {"fundingRate": 0.02},
                }
            )

            await monitor.update_funding_rates()

            assert "BTC/USDT" in monitor.funding_rates["binance"]
            assert "BTC/USDT" in monitor.funding_rates["okx"]


class TestFundingRateMonitorQueries:
    """Test query methods."""

    @pytest.fixture
    def monitor_with_data(self):
        """Monitor with populated data."""
        with patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True) as mock_ccxt:
            mock_binance = MagicMock()
            mock_okx = MagicMock()
            mock_ccxt.binance = MagicMock(return_value=mock_binance)
            mock_ccxt.okx = MagicMock(return_value=mock_okx)

            monitor = FundingRateMonitor({"exchanges": ["binance", "okx"]})
            monitor.funding_rates = {
                "binance": {
                    "BTC/USDT": FundingRate("BTC/USDT", "binance", 0.01, 36.5),
                    "ETH/USDT": FundingRate("ETH/USDT", "binance", -0.02, -73.0),
                },
                "okx": {
                    "BTC/USDT": FundingRate("BTC/USDT", "okx", 0.03, 109.5),
                    "SOL/USDT": FundingRate("SOL/USDT", "okx", 0.001, 3.65),
                },
            }
            return monitor

    def test_get_rates_found(self, monitor_with_data):
        """Test get_rates for existing symbol."""
        rates = monitor_with_data.get_rates("BTC/USDT")
        assert len(rates) == 2
        assert "binance" in rates
        assert "okx" in rates

    def test_get_rates_not_found(self, monitor_with_data):
        """Test get_rates for non-existing symbol."""
        rates = monitor_with_data.get_rates("XRP/USDT")
        assert len(rates) == 0

    def test_get_extreme_rates_default_threshold(self, monitor_with_data):
        """Test get_extreme_rates with default threshold."""
        extreme = monitor_with_data.get_extreme_rates()
        # ETH/USDT has rate -0.02, absolute 0.02 < 0.05*100=5, so not extreme
        # BTC/USDT okx has rate 0.03 < 5
        assert len(extreme) == 0

    def test_get_extreme_rates_custom_threshold(self, monitor_with_data):
        """Test get_extreme_rates with custom threshold."""
        extreme = monitor_with_data.get_extreme_rates(threshold=0.001)
        # threshold * 100 = 0.1, so rates with abs > 0.1 are extreme
        # BTC/USDT binance: 0.01 < 0.1
        # ETH/USDT binance: 0.02 < 0.1
        # BTC/USDT okx: 0.03 < 0.1
        # SOL/USDT okx: 0.001 < 0.1
        assert len(extreme) == 0

    def test_get_extreme_rates_high_rates(self, monitor_with_data):
        """Test get_extreme_rates with high rates."""
        monitor_with_data.funding_rates["binance"]["BTC/USDT"] = FundingRate("BTC/USDT", "binance", 10.0, 10950.0)
        extreme = monitor_with_data.get_extreme_rates()
        assert len(extreme) == 1
        assert extreme[0].symbol == "BTC/USDT"

    def test_get_statistics_empty(self):
        """Test get_statistics with no data."""
        with patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True) as mock_ccxt:
            mock_binance = MagicMock()
            mock_ccxt.binance = MagicMock(return_value=mock_binance)
            monitor = FundingRateMonitor({"exchanges": ["binance"]})
            stats = monitor.get_statistics()
            assert stats == {"total_symbols": 0}

    def test_get_statistics_with_data(self, monitor_with_data):
        """Test get_statistics with data."""
        stats = monitor_with_data.get_statistics()
        assert stats["total_symbols"] == 3  # BTC, ETH, SOL
        assert stats["total_exchanges"] == 2
        assert "avg_rate" in stats
        assert "max_rate" in stats
        assert "min_rate" in stats
        assert "extreme_positive" in stats
        assert "extreme_negative" in stats


class TestFundingRateMonitorOpportunities:
    """Test opportunity detection."""

    @pytest.fixture
    def monitor(self):
        """Monitor for opportunity testing."""
        with patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True) as mock_ccxt:
            mock_binance = MagicMock()
            mock_okx = MagicMock()
            mock_ccxt.binance = MagicMock(return_value=mock_binance)
            mock_ccxt.okx = MagicMock(return_value=mock_okx)

            monitor = FundingRateMonitor(
                {
                    "exchanges": ["binance", "okx"],
                    "minSpreadPct": 0.05,
                }
            )
            return monitor

    def test_find_opportunities_with_spread(self, monitor):
        """Test opportunity detection with sufficient spread."""
        monitor.funding_rates = {
            "binance": {
                "BTC/USDT": FundingRate("BTC/USDT", "binance", -0.02, -73.0),
            },
            "okx": {
                "BTC/USDT": FundingRate("BTC/USDT", "okx", 0.03, 109.5),
            },
        }

        opportunities = monitor.find_opportunities()
        assert len(opportunities) == 1
        opp = opportunities[0]
        assert opp.symbol == "BTC/USDT"
        assert opp.exchange_long == "binance"  # lower rate
        assert opp.exchange_short == "okx"  # higher rate
        assert opp.spread == pytest.approx(0.05, abs=1e-10)
        assert opp.annualized_spread == pytest.approx(0.05 * 3 * 365, abs=1e-10)

    def test_find_opportunities_reversed_order(self, monitor):
        """Test opportunity when higher-rate exchange comes first in dict."""
        # okx has higher rate, binance has lower — okx listed first
        monitor.funding_rates = {
            "okx": {
                "BTC/USDT": FundingRate("BTC/USDT", "okx", 0.04, 146.0),
            },
            "binance": {
                "BTC/USDT": FundingRate("BTC/USDT", "binance", -0.02, -73.0),
            },
        }

        opportunities = monitor.find_opportunities()
        assert len(opportunities) == 1
        opp = opportunities[0]
        assert opp.exchange_long == "binance"  # lower rate
        assert opp.exchange_short == "okx"  # higher rate

    def test_find_opportunities_no_spread(self, monitor):
        """Test no opportunity when spread too small."""
        monitor.funding_rates = {
            "binance": {
                "BTC/USDT": FundingRate("BTC/USDT", "binance", 0.01, 36.5),
            },
            "okx": {
                "BTC/USDT": FundingRate("BTC/USDT", "okx", 0.01, 36.5),
            },
        }

        opportunities = monitor.find_opportunities()
        assert len(opportunities) == 0

    def test_find_opportunities_below_threshold(self, monitor):
        """Test no opportunity when spread below min_spread_pct."""
        monitor.funding_rates = {
            "binance": {
                "BTC/USDT": FundingRate("BTC/USDT", "binance", 0.01, 36.5),
            },
            "okx": {
                "BTC/USDT": FundingRate("BTC/USDT", "okx", 0.02, 73.0),
            },
        }

        opportunities = monitor.find_opportunities()
        assert len(opportunities) == 0

    def test_find_opportunities_multiple_symbols(self, monitor):
        """Test multiple symbols with opportunities."""
        monitor.funding_rates = {
            "binance": {
                "BTC/USDT": FundingRate("BTC/USDT", "binance", -0.02, -73.0),
                "ETH/USDT": FundingRate("ETH/USDT", "binance", -0.01, -36.5),
            },
            "okx": {
                "BTC/USDT": FundingRate("BTC/USDT", "okx", 0.04, 146.0),
                "ETH/USDT": FundingRate("ETH/USDT", "okx", 0.06, 219.0),
            },
        }

        opportunities = monitor.find_opportunities()
        assert len(opportunities) == 2
        # Should be sorted by annualized_spread descending
        assert opportunities[0].symbol == "ETH/USDT"
        assert opportunities[1].symbol == "BTC/USDT"

    def test_find_opportunities_single_exchange(self, monitor):
        """Test no opportunity with single exchange."""
        monitor.funding_rates = {
            "binance": {
                "BTC/USDT": FundingRate("BTC/USDT", "binance", 0.01, 36.5),
            },
        }

        opportunities = monitor.find_opportunities()
        assert len(opportunities) == 0

    def test_find_opportunities_confidence(self, monitor):
        """Test confidence calculation."""
        monitor.funding_rates = {
            "binance": {
                "BTC/USDT": FundingRate("BTC/USDT", "binance", -0.05, -182.5),
            },
            "okx": {
                "BTC/USDT": FundingRate("BTC/USDT", "okx", 0.05, 182.5),
            },
        }

        opportunities = monitor.find_opportunities()
        assert len(opportunities) == 1
        opp = opportunities[0]
        # spread = 0.10, confidence = min(0.10 / 0.1, 1.0) = 1.0
        assert opp.confidence == 1.0

    def test_find_opportunities_reason(self, monitor):
        """Test reason string."""
        monitor.funding_rates = {
            "binance": {
                "BTC/USDT": FundingRate("BTC/USDT", "binance", -0.02, -73.0),
            },
            "okx": {
                "BTC/USDT": FundingRate("BTC/USDT", "okx", 0.03, 109.5),
            },
        }

        opportunities = monitor.find_opportunities()
        opp = opportunities[0]
        assert "Funding spread" in opp.reason
        assert "binance" in opp.reason
        assert "okx" in opp.reason


class TestFundingRateMonitorEdgeCases:
    """Test edge cases and error handling."""

    @patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True)
    def test_init_no_exchanges(self, mock_ccxt):
        """Test with empty exchange list."""
        monitor = FundingRateMonitor({"exchanges": []})
        assert len(monitor.exchanges) == 0

    @patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True)
    def test_init_duplicate_exchanges(self, mock_ccxt):
        """Test with duplicate exchange names."""
        mock_binance = MagicMock()
        mock_ccxt.binance = MagicMock(return_value=mock_binance)
        monitor = FundingRateMonitor({"exchanges": ["binance", "binance"]})
        assert len(monitor.exchanges) == 1

    @pytest.mark.asyncio
    async def test_update_funding_rates_empty_exchanges(self):
        """Test update with no exchanges."""
        with patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True) as mock_ccxt:
            _ = mock_ccxt
            monitor = FundingRateMonitor({"exchanges": []})
            # Should not raise
            await monitor.update_funding_rates()

    def test_get_rates_empty_symbol(self):
        """Test get_rates with empty symbol."""
        with patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True) as mock_ccxt:
            mock_binance = MagicMock()
            mock_ccxt.binance = MagicMock(return_value=mock_binance)
            monitor = FundingRateMonitor({"exchanges": ["binance"]})
            rates = monitor.get_rates("")
            assert len(rates) == 0

    def test_get_extreme_rates_empty(self):
        """Test get_extreme_rates with no data."""
        with patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True) as mock_ccxt:
            mock_binance = MagicMock()
            mock_ccxt.binance = MagicMock(return_value=mock_binance)
            monitor = FundingRateMonitor({"exchanges": ["binance"]})
            extreme = monitor.get_extreme_rates()
            assert len(extreme) == 0

    def test_find_opportunities_empty(self):
        """Test find_opportunities with no data."""
        with patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True) as mock_ccxt:
            mock_binance = MagicMock()
            mock_ccxt.binance = MagicMock(return_value=mock_binance)
            monitor = FundingRateMonitor({"exchanges": ["binance"]})
            opportunities = monitor.find_opportunities()
            assert len(opportunities) == 0

    def test_get_statistics_single_rate(self):
        """Test get_statistics with single rate."""
        with patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True) as mock_ccxt:
            mock_binance = MagicMock()
            mock_ccxt.binance = MagicMock(return_value=mock_binance)
            monitor = FundingRateMonitor({"exchanges": ["binance"]})
            monitor.funding_rates = {
                "binance": {
                    "BTC/USDT": FundingRate("BTC/USDT", "binance", 0.01, 36.5),
                },
            }
            stats = monitor.get_statistics()
            assert stats["total_symbols"] == 1
            assert stats["avg_rate"] == 0.01
            assert stats["max_rate"] == 0.01
            assert stats["min_rate"] == 0.01


class TestFundingRateMonitorIntegration:
    """Integration tests with mocked async operations."""

    @pytest.mark.asyncio
    async def test_full_workflow(self):
        """Test complete workflow from init to opportunity detection."""
        with patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True) as mock_ccxt:
            mock_binance = MagicMock()
            mock_okx = MagicMock()
            mock_ccxt.binance = MagicMock(return_value=mock_binance)
            mock_ccxt.okx = MagicMock(return_value=mock_okx)

            monitor = FundingRateMonitor(
                {
                    "exchanges": ["binance", "okx"],
                    "minSpreadPct": 0.05,
                }
            )

            # Mock fetch responses
            mock_binance.fetch_funding_rates = AsyncMock(
                return_value={
                    "BTC/USDT": {
                        "fundingRate": -0.0002,
                        "fundingDatetime": "2024-01-01T08:00:00",
                        "timestamp": 1704067200000,
                    },
                }
            )
            mock_okx.fetch_funding_rates = AsyncMock(
                return_value={
                    "BTC/USDT": {
                        "fundingRate": 0.0003,
                        "fundingDatetime": "2024-01-01T08:00:00",
                        "timestamp": 1704067200000,
                    },
                }
            )

            # Update rates
            await monitor.update_funding_rates()

            # Verify rates stored
            assert "BTC/USDT" in monitor.funding_rates["binance"]
            assert "BTC/USDT" in monitor.funding_rates["okx"]

            # Get rates for symbol
            rates = monitor.get_rates("BTC/USDT")
            assert len(rates) == 2

            # Find opportunities
            opportunities = monitor.find_opportunities()
            assert len(opportunities) == 1
            opp = opportunities[0]
            assert opp.symbol == "BTC/USDT"
            assert opp.exchange_long == "binance"
            assert opp.exchange_short == "okx"

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        """Test workflow with one exchange failing."""
        with patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True) as mock_ccxt:
            mock_binance = MagicMock()
            mock_okx = MagicMock()
            mock_ccxt.binance = MagicMock(return_value=mock_binance)
            mock_ccxt.okx = MagicMock(return_value=mock_okx)

            monitor = FundingRateMonitor(
                {
                    "exchanges": ["binance", "okx"],
                    "minSpreadPct": 0.05,
                }
            )

            # Binance succeeds, okx fails
            mock_binance.fetch_funding_rates = AsyncMock(
                return_value={
                    "BTC/USDT": {"fundingRate": 0.01},
                }
            )
            mock_okx.fetch_funding_rates = AsyncMock(side_effect=Exception("Timeout"))

            await monitor.update_funding_rates()

            # Only binance data should be present
            assert "BTC/USDT" in monitor.funding_rates["binance"]
            assert len(monitor.funding_rates["okx"]) == 0

    @pytest.mark.asyncio
    async def test_update_multiple_symbols(self):
        """Test updating multiple symbols at once."""
        with patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True) as mock_ccxt:
            mock_binance = MagicMock()
            mock_ccxt.binance = MagicMock(return_value=mock_binance)

            monitor = FundingRateMonitor({"exchanges": ["binance"]})

            mock_binance.fetch_funding_rates = AsyncMock(
                return_value={
                    "BTC/USDT": {"fundingRate": 0.01},
                    "ETH/USDT": {"fundingRate": -0.02},
                    "SOL/USDT": {"fundingRate": 0.005},
                }
            )

            await monitor.update_funding_rates()

            assert len(monitor.funding_rates["binance"]) == 3
            assert "BTC/USDT" in monitor.funding_rates["binance"]
            assert "ETH/USDT" in monitor.funding_rates["binance"]
            assert "SOL/USDT" in monitor.funding_rates["binance"]


class TestFundingRateMonitorLogging:
    """Test logging behavior."""

    @patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True)
    def test_logger_name(self, mock_ccxt):
        """Test logger name."""
        mock_binance = MagicMock()
        mock_ccxt.binance = MagicMock(return_value=mock_binance)
        monitor = FundingRateMonitor({"exchanges": ["binance"]})
        assert monitor.logger.name == "kairos.arbitrage.funding"

    @pytest.mark.asyncio
    async def test_fetch_logs_error(self, caplog):
        """Test error logging on fetch failure."""
        with patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True) as mock_ccxt:
            mock_binance = MagicMock()
            mock_ccxt.binance = MagicMock(return_value=mock_binance)
            monitor = FundingRateMonitor({"exchanges": ["binance"]})
            monitor.exchanges["binance"] = mock_binance

            mock_binance.fetch_funding_rates = AsyncMock(side_effect=Exception("Test error"))

            with caplog.at_level(logging.ERROR):
                await monitor.update_funding_rates()

            assert "Failed to fetch funding rates for binance" in caplog.text

    @patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True)
    def test_init_logs_success(self, mock_ccxt, caplog):
        """Test success logging on init."""
        mock_binance = MagicMock()
        mock_ccxt.binance = MagicMock(return_value=mock_binance)

        with caplog.at_level(logging.INFO):
            monitor = FundingRateMonitor({"exchanges": ["binance"]})
            assert monitor is not None

        assert "Initialized exchange binance" in caplog.text

    @patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True)
    def test_init_logs_failure(self, mock_ccxt, caplog):
        """Test failure logging on init error."""
        mock_ccxt.binance = MagicMock(side_effect=Exception("Init error"))

        with caplog.at_level(logging.ERROR):
            monitor = FundingRateMonitor({"exchanges": ["binance"]})
            assert monitor is not None

        assert "Failed to initialize exchange binance" in caplog.text


class TestFundingRateMonitorDataIntegrity:
    """Test data integrity and consistency."""

    @pytest.fixture
    def monitor(self):
        """Monitor for data integrity tests."""
        with patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True) as mock_ccxt:
            mock_binance = MagicMock()
            mock_ccxt.binance = MagicMock(return_value=mock_binance)
            monitor = FundingRateMonitor({"exchanges": ["binance"]})
            return monitor

    def test_funding_rates_structure(self, monitor):
        """Test funding_rates data structure."""
        assert isinstance(monitor.funding_rates, dict)
        assert "binance" in monitor.funding_rates
        assert isinstance(monitor.funding_rates["binance"], dict)

    def test_rate_conversion(self, monitor):
        """Test rate conversion in _fetch_funding_rates."""
        mock_exchange = monitor.exchanges["binance"]
        mock_exchange.fetch_funding_rates = AsyncMock(
            return_value={
                "BTC/USDT": {
                    "fundingRate": 0.001,  # 0.1%
                    "fundingDatetime": "2024-01-01T08:00:00",
                    "timestamp": 1704067200000,
                },
            }
        )

        asyncio.run(monitor.update_funding_rates())

        rate = monitor.funding_rates["binance"]["BTC/USDT"]
        assert rate.rate == 0.1  # 0.001 * 100
        assert rate.annualized == 0.001 * 3 * 365 * 100

    def test_timestamp_handling(self, monitor):
        """Test timestamp handling."""
        mock_exchange = monitor.exchanges["binance"]
        mock_exchange.fetch_funding_rates = AsyncMock(
            return_value={
                "BTC/USDT": {
                    "fundingRate": 0.01,
                    "timestamp": 1704067200000,  # milliseconds
                },
            }
        )

        asyncio.run(monitor.update_funding_rates())

        rate = monitor.funding_rates["binance"]["BTC/USDT"]
        assert rate.timestamp == 1704067200.0  # converted to seconds

    def test_timestamp_fallback(self, monitor):
        """Test timestamp fallback to current time."""
        mock_exchange = monitor.exchanges["binance"]
        mock_exchange.fetch_funding_rates = AsyncMock(
            return_value={
                "BTC/USDT": {
                    "fundingRate": 0.01,
                    # no timestamp field
                },
            }
        )

        before = time.time()
        asyncio.run(monitor.update_funding_rates())
        after = time.time()

        rate = monitor.funding_rates["binance"]["BTC/USDT"]
        assert before <= rate.timestamp <= after


class TestFundingRateMonitorConfiguration:
    """Test configuration handling."""

    @patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True)
    def test_config_defaults(self, mock_ccxt):
        """Test all default config values."""
        mock_binance = MagicMock()
        mock_ccxt.binance = MagicMock(return_value=mock_binance)
        monitor = FundingRateMonitor()
        assert monitor.min_spread_pct == 0.05
        assert monitor.extreme_rate_threshold == 0.05
        assert monitor.update_interval == 300

    @patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True)
    def test_config_partial(self, mock_ccxt):
        """Test partial config override."""
        mock_binance = MagicMock()
        mock_ccxt.binance = MagicMock(return_value=mock_binance)
        monitor = FundingRateMonitor({"minSpreadPct": 0.1})
        assert monitor.min_spread_pct == 0.1
        assert monitor.extreme_rate_threshold == 0.05  # default

    @patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True)
    def test_exchange_config_passing(self, mock_ccxt):
        """Test exchange config is passed correctly."""
        mock_binance_class = MagicMock()
        mock_ccxt.binance = mock_binance_class
        config = {
            "exchanges": ["binance"],
            "binance": {
                "apiKey": "test_key",
                "secret": "test_secret",
                "password": "test_pass",
            },
        }
        monitor = FundingRateMonitor(config)
        assert monitor is not None
        mock_binance_class.assert_called_once_with(
            {
                "enableRateLimit": True,
                "apiKey": "test_key",
                "secret": "test_secret",
                "password": "test_pass",
            }
        )


class TestFundingRateMonitorPerformance:
    """Test performance characteristics."""

    @pytest.mark.asyncio
    async def test_concurrent_fetch(self):
        """Test that exchanges are fetched concurrently."""
        with patch("kairos.arbitrage.funding_monitor.ccxt", autospec=True) as mock_ccxt:
            mock_binance = MagicMock()
            mock_okx = MagicMock()
            mock_ccxt.binance = MagicMock(return_value=mock_binance)
            mock_ccxt.okx = MagicMock(return_value=mock_okx)

            monitor = FundingRateMonitor({"exchanges": ["binance", "okx"]})

            call_order = []

            async def mock_fetch(symbols=None):
                call_order.append("start")
                await asyncio.sleep(0.01)
                call_order.append("end")
                return {}

            mock_binance.fetch_funding_rates = mock_fetch
            mock_okx.fetch_funding_rates = mock_fetch

            await monitor.update_funding_rates()

            # Both should start before either ends (concurrent)
            assert len(call_order) == 4
            # The order should be start, start, end, end (concurrent)
            assert call_order[0] == "start"
            assert call_order[1] == "start"
