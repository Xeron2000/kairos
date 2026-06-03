"""Comprehensive tests for monitor_top_movers."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kairos.utils.monitor_top_movers import format_movers_message, monitor_top_movers


@pytest.fixture
def mock_exchange():
    """Create a mock exchange."""
    exchange = AsyncMock()
    exchange.get_price_minutes_ago = AsyncMock(return_value={
        "BTC/USDT:USDT": 49000.0,
        "ETH/USDT:USDT": 2900.0,
    })
    exchange.get_current_prices = AsyncMock(return_value={
        "BTC/USDT:USDT": 50000.0,
        "ETH/USDT:USDT": 3000.0,
    })
    return exchange


@pytest.fixture
def config():
    return {
        "priorityThresholds": {"high": 5.0, "medium": 2.0},
        "highPriorityBypassCooldown": True,
    }


class TestMonitorTopMovers:
    """Test monitor_top_movers function."""

    @pytest.mark.asyncio
    async def test_detects_movers(self, mock_exchange, config):
        result = await monitor_top_movers(
            minutes=5, symbols=["BTC/USDT:USDT", "ETH/USDT:USDT"],
            threshold=1.0, exchange=mock_exchange, config=config,
        )
        assert result is not None
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_returns_none_when_no_movers(self, mock_exchange, config):
        mock_exchange.get_current_prices.return_value = {
            "BTC/USDT:USDT": 49050.0,  # Only ~0.1% change
        }
        mock_exchange.get_price_minutes_ago.return_value = {
            "BTC/USDT:USDT": 49000.0,
        }

        result = await monitor_top_movers(
            minutes=5, symbols=["BTC/USDT:USDT"],
            threshold=5.0, exchange=mock_exchange, config=config,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_filters_by_allowed_symbols(self, mock_exchange, config):
        result = await monitor_top_movers(
            minutes=5, symbols=["BTC/USDT:USDT", "ETH/USDT:USDT"],
            threshold=1.0, exchange=mock_exchange, config=config,
            allowed_symbols=["BTC/USDT:USDT"],
        )
        assert result is not None
        assert all(e["symbol"] == "BTC/USDT:USDT" for e in result)

    @pytest.mark.asyncio
    async def test_with_cooldown_manager(self, mock_exchange, config):
        cooldown_mgr = MagicMock()
        cooldown_mgr.should_notify.return_value = True

        result = await monitor_top_movers(
            minutes=5, symbols=["BTC/USDT:USDT"],
            threshold=1.0, exchange=mock_exchange, config=config,
            cooldown_manager=cooldown_mgr,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_cooldown_blocks_notification(self, mock_exchange, config):
        cooldown_mgr = MagicMock()
        cooldown_mgr.should_notify.return_value = False

        result = await monitor_top_movers(
            minutes=5, symbols=["BTC/USDT:USDT", "ETH/USDT:USDT"],
            threshold=1.0, exchange=mock_exchange, config=config,
            cooldown_manager=cooldown_mgr,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_exchange(self, config):
        with pytest.raises(ValueError, match="Exchange must implement"):
            await monitor_top_movers(
                minutes=5, symbols=["BTC/USDT:USDT"],
                threshold=1.0, exchange=None, config=config,
            )

    @pytest.mark.asyncio
    async def test_exchange_missing_methods(self, config):
        exchange = MagicMock(spec=[])  # No methods
        with pytest.raises(ValueError, match="Exchange must implement"):
            await monitor_top_movers(
                minutes=5, symbols=["BTC/USDT:USDT"],
                threshold=1.0, exchange=exchange, config=config,
            )

    @pytest.mark.asyncio
    async def test_priority_assignment(self, mock_exchange, config):
        mock_exchange.get_current_prices.return_value = {
            "BTC/USDT:USDT": 55000.0,  # ~12% change = HIGH
            "ETH/USDT:USDT": 3050.0,   # ~5% change = HIGH
        }

        result = await monitor_top_movers(
            minutes=5, symbols=["BTC/USDT:USDT", "ETH/USDT:USDT"],
            threshold=1.0, exchange=mock_exchange, config=config,
        )
        assert result is not None
        # Both should be HIGH priority
        for event in result:
            assert event["priority"] == "HIGH"

    @pytest.mark.asyncio
    async def test_sorting_by_priority_and_change(self, mock_exchange, config):
        mock_exchange.get_current_prices.return_value = {
            "BTC/USDT:USDT": 52000.0,  # ~6% change = HIGH
            "ETH/USDT:USDT": 3020.0,   # ~4% change = MEDIUM
        }

        result = await monitor_top_movers(
            minutes=5, symbols=["BTC/USDT:USDT", "ETH/USDT:USDT"],
            threshold=1.0, exchange=mock_exchange, config=config,
        )
        assert result is not None
        assert result[0]["priority"] == "HIGH"

    @pytest.mark.asyncio
    async def test_direction_up(self, mock_exchange, config):
        result = await monitor_top_movers(
            minutes=5, symbols=["BTC/USDT:USDT"],
            threshold=1.0, exchange=mock_exchange, config=config,
        )
        assert result is not None
        assert result[0]["direction"] == "up"

    @pytest.mark.asyncio
    async def test_direction_down(self, mock_exchange, config):
        mock_exchange.get_current_prices.return_value = {
            "BTC/USDT:USDT": 48000.0,  # Down ~2%
        }

        result = await monitor_top_movers(
            minutes=5, symbols=["BTC/USDT:USDT"],
            threshold=1.0, exchange=mock_exchange, config=config,
        )
        assert result is not None
        assert result[0]["direction"] == "down"


class TestFormatMoversMessage:
    """Test format_movers_message function."""

    def test_basic_format(self):
        top_movers = [
            ("BTC/USDT:USDT", 5.5, "HIGH"),
            ("ETH/USDT:USDT", 2.3, "MEDIUM"),
        ]
        initial_prices = {"BTC/USDT:USDT": 49000.0, "ETH/USDT:USDT": 2900.0}
        updated_prices = {"BTC/USDT:USDT": 51700.0, "ETH/USDT:USDT": 2967.0}

        message = format_movers_message(
            exchange_name="Binance", minutes=5, timezone_str="UTC",
            threshold=1.0, monitored_count=10, scope_count=2,
            detected_count=2, top_movers=top_movers,
            initial_prices=initial_prices, updated_prices=updated_prices,
        )

        assert "Binance" in message
        assert "BTC/USDT:USDT" in message
        assert "HIGH" in message

    def test_format_with_high_priority(self):
        top_movers = [("BTC/USDT:USDT", 8.0, "HIGH")]
        initial_prices = {"BTC/USDT:USDT": 50000.0}
        updated_prices = {"BTC/USDT:USDT": 54000.0}

        message = format_movers_message(
            exchange_name="Binance", minutes=5, timezone_str="UTC",
            threshold=1.0, monitored_count=10, scope_count=1,
            detected_count=1, top_movers=top_movers,
            initial_prices=initial_prices, updated_prices=updated_prices,
        )

        assert "🚨" in message

    def test_format_with_low_priority(self):
        top_movers = [("BTC/USDT:USDT", 1.5, "LOW")]
        initial_prices = {"BTC/USDT:USDT": 50000.0}
        updated_prices = {"BTC/USDT:USDT": 50750.0}

        message = format_movers_message(
            exchange_name="Binance", minutes=5, timezone_str="UTC",
            threshold=1.0, monitored_count=10, scope_count=1,
            detected_count=1, top_movers=top_movers,
            initial_prices=initial_prices, updated_prices=updated_prices,
        )

        assert "ℹ️" in message

    def test_format_limits_to_6_movers(self):
        top_movers = [(f"SYM{i}/USDT", float(i), "LOW") for i in range(10)]
        initial_prices = {f"SYM{i}/USDT": 100.0 for i in range(10)}
        updated_prices = {f"SYM{i}/USDT": 100.0 + i for i in range(10)}

        message = format_movers_message(
            exchange_name="Binance", minutes=5, timezone_str="UTC",
            threshold=1.0, monitored_count=10, scope_count=10,
            detected_count=10, top_movers=top_movers,
            initial_prices=initial_prices, updated_prices=updated_prices,
        )

        # Should only contain first 6
        assert "SYM5" in message
        assert "SYM6" not in message
