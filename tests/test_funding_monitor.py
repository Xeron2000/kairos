"""Tests for FundingRateMonitor."""

import pytest
from unittest.mock import MagicMock, patch
from kairos.arbitrage.funding_monitor import (
    FundingRate, FundingOpportunity, FundingRateMonitor
)


class TestFundingRate:
    """Test FundingRate dataclass."""
    
    def test_init(self):
        """Test FundingRate initialization."""
        rate = FundingRate(
            symbol="BTC/USDT",
            exchange="okx",
            rate=0.01,
            annualized=36.5
        )
        assert rate.symbol == "BTC/USDT"
        assert rate.exchange == "okx"
        assert rate.rate == 0.01
        assert rate.annualized == 36.5
        assert rate.next_time is None
    
    def test_is_extreme_positive(self):
        """Test is_extreme property with extreme positive rate."""
        rate = FundingRate(
            symbol="BTC/USDT",
            exchange="okx",
            rate=0.1,
            annualized=100.0
        )
        assert rate.is_extreme is True
    
    def test_is_extreme_negative(self):
        """Test is_extreme property with extreme negative rate."""
        rate = FundingRate(
            symbol="BTC/USDT",
            exchange="okx",
            rate=-0.1,
            annualized=-100.0
        )
        assert rate.is_extreme is True
    
    def test_is_extreme_normal(self):
        """Test is_extreme property with normal rate."""
        rate = FundingRate(
            symbol="BTC/USDT",
            exchange="okx",
            rate=0.01,
            annualized=10.0
        )
        assert rate.is_extreme is False
    
    def test_direction_positive(self):
        """Test direction property with positive rate."""
        rate = FundingRate(
            symbol="BTC/USDT",
            exchange="okx",
            rate=0.01,
            annualized=10.0
        )
        assert rate.direction == "positive"
    
    def test_direction_negative(self):
        """Test direction property with negative rate."""
        rate = FundingRate(
            symbol="BTC/USDT",
            exchange="okx",
            rate=-0.01,
            annualized=-10.0
        )
        assert rate.direction == "negative"


class TestFundingOpportunity:
    """Test FundingOpportunity dataclass."""
    
    def test_init(self):
        """Test FundingOpportunity initialization."""
        opportunity = FundingOpportunity(
            symbol="BTC/USDT",
            exchange_long="okx",
            exchange_short="bybit",
            rate_long=-0.01,
            rate_short=0.02,
            spread=0.03,
            annualized_spread=10.95,
            estimated_daily_profit_pct=0.03,
            confidence=0.8,
            reason="Funding rate spread"
        )
        assert opportunity.symbol == "BTC/USDT"
        assert opportunity.exchange_long == "okx"
        assert opportunity.exchange_short == "bybit"
        assert opportunity.rate_long == -0.01
        assert opportunity.rate_short == 0.02
        assert opportunity.spread == 0.03
        assert opportunity.annualized_spread == 10.95
        assert opportunity.estimated_daily_profit_pct == 0.03
        assert opportunity.confidence == 0.8
        assert opportunity.reason == "Funding rate spread"


class TestFundingRateMonitor:
    """Test FundingRateMonitor class."""
    
    def test_init(self):
        """Test FundingRateMonitor initialization."""
        config = {
            "minSpreadPct": 0.05,
            "extremeRateThreshold": 0.05,
            "updateInterval": 300
        }
        
        monitor = FundingRateMonitor(config)
        
        assert monitor.min_spread_pct == 0.05
        assert monitor.extreme_rate_threshold == 0.05
        assert monitor.update_interval == 300