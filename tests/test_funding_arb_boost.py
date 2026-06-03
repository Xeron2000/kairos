"""Comprehensive tests for FundingArbitrage."""

import time
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from kairos.arbitrage.funding_arb import ArbitragePosition, FundingArbitrage
from kairos.arbitrage.funding_monitor import FundingOpportunity


@pytest.fixture
def mock_executors():
    """Create mock trade executors."""
    return {
        "binance": MagicMock(),
        "okx": MagicMock(),
    }


@pytest.fixture
def mock_position_manager():
    """Create mock position manager."""
    pm = MagicMock()
    pm.get_open_positions.return_value = []
    return pm


@pytest.fixture
def mock_funding_monitor():
    """Create mock funding monitor."""
    fm = MagicMock()
    return fm


@pytest.fixture
def arbitrage(mock_executors, mock_position_manager, mock_funding_monitor):
    """Create a FundingArbitrage instance."""
    config = {
        "minSpreadPct": 0.05,
        "positionSizePct": 0.1,
        "maxPositions": 3,
        "closeSpreadPct": 0.01,
    }
    return FundingArbitrage(config, mock_executors, mock_position_manager, mock_funding_monitor)


class TestArbitragePosition:
    """Test ArbitragePosition dataclass."""

    def test_creation(self):
        pos = ArbitragePosition(
            id="arb_1",
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_position_id="long_1",
            short_position_id="short_1",
            entry_spread=0.1,
            entry_time=time.time(),
        )
        assert pos.id == "arb_1"
        assert pos.status == "open"
        assert pos.pnl == 0
        assert pos.funding_collected == 0


class TestFundingArbitrageInit:
    """Test FundingArbitrage initialization."""

    def test_init(self, arbitrage):
        assert arbitrage.min_spread_pct == 0.05
        assert arbitrage.position_size_pct == 0.1
        assert arbitrage.max_positions == 3
        assert arbitrage.close_spread_pct == 0.01
        assert arbitrage.active_positions == {}


class TestEvaluateOpportunity:
    """Test evaluate_opportunity method."""

    @pytest.mark.asyncio
    async def test_should_execute(self, arbitrage):
        opportunity = FundingOpportunity(
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_rate=0.01,
            short_rate=-0.02,
            spread=0.1,
            estimated_daily_profit_pct=0.5,
        )

        result = await arbitrage.evaluate_opportunity(opportunity, 10000)
        assert result["should_execute"] is True
        assert "position_size" in result

    @pytest.mark.asyncio
    async def test_already_have_position(self, arbitrage):
        arbitrage.active_positions["arb_1"] = ArbitragePosition(
            id="arb_1",
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_position_id="long_1",
            short_position_id="short_1",
            entry_spread=0.1,
            entry_time=time.time(),
        )

        opportunity = FundingOpportunity(
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_rate=0.01,
            short_rate=-0.02,
            spread=0.1,
            estimated_daily_profit_pct=0.5,
        )

        result = await arbitrage.evaluate_opportunity(opportunity, 10000)
        assert result["should_execute"] is False
        assert "Already have position" in result["reason"]

    @pytest.mark.asyncio
    async def test_max_positions_reached(self, arbitrage):
        for i in range(3):
            arbitrage.active_positions[f"arb_{i}"] = ArbitragePosition(
                id=f"arb_{i}",
                symbol=f"SYM{i}/USDT",
                long_exchange="binance",
                short_exchange="okx",
                long_position_id=f"long_{i}",
                short_position_id=f"short_{i}",
                entry_spread=0.1,
                entry_time=time.time(),
            )

        opportunity = FundingOpportunity(
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_rate=0.01,
            short_rate=-0.02,
            spread=0.1,
            estimated_daily_profit_pct=0.5,
        )

        result = await arbitrage.evaluate_opportunity(opportunity, 10000)
        assert result["should_execute"] is False
        assert "Max positions" in result["reason"]

    @pytest.mark.asyncio
    async def test_spread_too_small(self, arbitrage):
        opportunity = FundingOpportunity(
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_rate=0.01,
            short_rate=-0.01,
            spread=0.01,
            estimated_daily_profit_pct=0.1,
        )

        result = await arbitrage.evaluate_opportunity(opportunity, 10000)
        assert result["should_execute"] is False
        assert "Spread too small" in result["reason"]


class TestExecuteArbitrage:
    """Test execute_arbitrage method."""

    @pytest.mark.asyncio
    async def test_execute_success(self, arbitrage):
        opportunity = FundingOpportunity(
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_rate=0.01,
            short_rate=-0.02,
            spread=0.1,
            estimated_daily_profit_pct=0.5,
        )

        # Mock executor responses
        arbitrage.executors["binance"].execute_order = AsyncMock(return_value=MagicMock(
            success=True, order_id="long_1", filled_price=50000.0
        ))
        arbitrage.executors["okx"].execute_order = AsyncMock(return_value=MagicMock(
            success=True, order_id="short_1", filled_price=50100.0
        ))

        result = await arbitrage.execute_arbitrage(opportunity, 1000)
        assert result["success"] is True
        assert len(arbitrage.active_positions) == 1

    @pytest.mark.asyncio
    async def test_execute_long_failure(self, arbitrage):
        opportunity = FundingOpportunity(
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_rate=0.01,
            short_rate=-0.02,
            spread=0.1,
            estimated_daily_profit_pct=0.5,
        )

        arbitrage.executors["binance"].execute_order = AsyncMock(return_value=MagicMock(
            success=False, error="Insufficient funds"
        ))

        result = await arbitrage.execute_arbitrage(opportunity, 1000)
        assert result["success"] is False


class TestCloseArbitrage:
    """Test close_arbitrage method."""

    @pytest.mark.asyncio
    async def test_close_success(self, arbitrage):
        # Create an active position
        arb_pos = ArbitragePosition(
            id="arb_1",
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_position_id="long_1",
            short_position_id="short_1",
            entry_spread=0.1,
            entry_time=time.time(),
        )
        arbitrage.active_positions["arb_1"] = arb_pos

        # Mock executor responses
        arbitrage.executors["binance"].close_position = AsyncMock(return_value=MagicMock(
            success=True, filled_price=51000.0
        ))
        arbitrage.executors["okx"].close_position = AsyncMock(return_value=MagicMock(
            success=True, filled_price=50900.0
        ))

        result = await arbitrage.close_arbitrage("arb_1", 51000.0, 50900.0)
        assert result["success"] is True
        assert arbitrage.active_positions["arb_1"].status == "closed"

    @pytest.mark.asyncio
    async def test_close_not_found(self, arbitrage):
        result = await arbitrage.close_arbitrage("nonexistent", 50000.0, 50000.0)
        assert result["success"] is False
        assert "not found" in result["reason"].lower()


class TestGetActivePositions:
    """Test get_active_positions method."""

    def test_get_active_positions(self, arbitrage):
        arbitrage.active_positions["arb_1"] = ArbitragePosition(
            id="arb_1",
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_position_id="long_1",
            short_position_id="short_1",
            entry_spread=0.1,
            entry_time=time.time(),
        )

        positions = arbitrage.get_active_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "BTC/USDT"

    def test_get_active_positions_empty(self, arbitrage):
        positions = arbitrage.get_active_positions()
        assert len(positions) == 0


class TestGetStats:
    """Test get_stats method."""

    def test_get_stats(self, arbitrage):
        stats = arbitrage.get_stats()
        assert "active_positions" in stats
        assert "total_pnl" in stats
        assert stats["active_positions"] == 0
