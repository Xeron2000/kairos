"""Tests for funding_arb.py module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kairos.arbitrage.funding_arb import ArbitragePosition, FundingArbitrage


@pytest.fixture
def mock_executors():
    """Create mock trade executors."""
    executor_long = MagicMock()
    executor_long.get_ticker = AsyncMock(return_value={"last": 100.0})
    executor_long.execute_order = AsyncMock(
        return_value=MagicMock(success=True, filled_price=100.0, order_id="long_order_1")
    )
    executor_long.close_position = AsyncMock(return_value=True)

    executor_short = MagicMock()
    executor_short.get_ticker = AsyncMock(return_value={"last": 101.0})
    executor_short.execute_order = AsyncMock(
        return_value=MagicMock(success=True, filled_price=101.0, order_id="short_order_1")
    )
    executor_short.close_position = AsyncMock(return_value=True)

    return {"binance": executor_long, "okx": executor_short}


@pytest.fixture
def mock_position_manager():
    """Create mock position manager."""
    pm = MagicMock()

    def _open_position(**kwargs):
        pos = MagicMock()
        pos.id = f"pos_{kwargs.get('side', 'unknown')}"
        return pos

    pm.open_position = MagicMock(side_effect=_open_position)
    pm.close_position = MagicMock()
    return pm


@pytest.fixture
def mock_funding_monitor():
    """Create mock funding monitor."""
    return MagicMock()


@pytest.fixture
def default_config():
    """Default arbitrage config."""
    return {"minSpreadPct": 0.05, "positionSizePct": 0.1, "maxPositions": 3, "closeSpreadPct": 0.01}


@pytest.fixture
def arbitrage(default_config, mock_executors, mock_position_manager, mock_funding_monitor):
    """Create FundingArbitrage instance with mocked dependencies."""
    return FundingArbitrage(
        config=default_config,
        executors=mock_executors,
        position_manager=mock_position_manager,
        funding_monitor=mock_funding_monitor,
    )


@pytest.fixture
def sample_opportunity():
    """Create sample funding opportunity."""
    return MagicMock(
        symbol="BTC/USDT",
        exchange_long="binance",
        exchange_short="okx",
        rate_long=-0.001,
        rate_short=0.002,
        spread=0.05,
        annualized_spread=18.25,
        estimated_daily_profit_pct=0.05,
        confidence=0.8,
        reason="Test opportunity",
    )


class TestArbitragePosition:
    """Test ArbitragePosition dataclass."""

    def test_default_values(self):
        """Test default values for ArbitragePosition."""
        pos = ArbitragePosition(
            id="arb_1",
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_position_id="pos_long",
            short_position_id="pos_short",
            entry_spread=0.05,
            entry_time=1234567890.0,
        )
        assert pos.status == "open"
        assert pos.pnl == 0
        assert pos.funding_collected == 0

    def test_custom_values(self):
        """Test custom values for ArbitragePosition."""
        pos = ArbitragePosition(
            id="arb_2",
            symbol="ETH/USDT",
            long_exchange="okx",
            short_exchange="binance",
            long_position_id="pos_long2",
            short_position_id="pos_short2",
            entry_spread=0.1,
            entry_time=1234567891.0,
            status="closed",
            pnl=100.0,
            funding_collected=50.0,
        )
        assert pos.status == "closed"
        assert pos.pnl == 100.0
        assert pos.funding_collected == 50.0


class TestFundingArbitrageInit:
    """Test FundingArbitrage initialization."""

    def test_default_config(self, arbitrage):
        """Test default configuration values."""
        assert arbitrage.min_spread_pct == 0.05
        assert arbitrage.position_size_pct == 0.1
        assert arbitrage.max_positions == 3
        assert arbitrage.close_spread_pct == 0.01

    def test_custom_config(self, mock_executors, mock_position_manager, mock_funding_monitor):
        """Test custom configuration values."""
        config = {"minSpreadPct": 0.1, "positionSizePct": 0.2, "maxPositions": 5, "closeSpreadPct": 0.02}
        arb = FundingArbitrage(
            config=config,
            executors=mock_executors,
            position_manager=mock_position_manager,
            funding_monitor=mock_funding_monitor,
        )
        assert arb.min_spread_pct == 0.1
        assert arb.position_size_pct == 0.2
        assert arb.max_positions == 5
        assert arb.close_spread_pct == 0.02


class TestEvaluateOpportunity:
    """Test evaluate_opportunity method."""

    @pytest.mark.asyncio
    async def test_already_have_position(self, arbitrage, sample_opportunity):
        """Test rejection when already have position in symbol."""
        # Add existing position
        arbitrage.active_positions["arb_1"] = ArbitragePosition(
            id="arb_1",
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_position_id="pos1",
            short_position_id="pos2",
            entry_spread=0.05,
            entry_time=1234567890.0,
        )

        result = await arbitrage.evaluate_opportunity(sample_opportunity, 10000.0)
        assert result["should_execute"] is False
        assert "Already have position" in result["reason"]

    @pytest.mark.asyncio
    async def test_max_positions_reached(self, arbitrage, sample_opportunity):
        """Test rejection when max positions reached."""
        # Fill up positions
        for i in range(3):
            arbitrage.active_positions[f"arb_{i}"] = ArbitragePosition(
                id=f"arb_{i}",
                symbol=f"SYMBOL_{i}",
                long_exchange="binance",
                short_exchange="okx",
                long_position_id=f"pos_long_{i}",
                short_position_id=f"pos_short_{i}",
                entry_spread=0.05,
                entry_time=1234567890.0,
            )

        result = await arbitrage.evaluate_opportunity(sample_opportunity, 10000.0)
        assert result["should_execute"] is False
        assert "Max positions reached" in result["reason"]

    @pytest.mark.asyncio
    async def test_spread_too_small(self, arbitrage, sample_opportunity):
        """Test rejection when spread too small."""
        sample_opportunity.spread = 0.03  # Below min_spread_pct of 0.05

        result = await arbitrage.evaluate_opportunity(sample_opportunity, 10000.0)
        assert result["should_execute"] is False
        assert "Spread too small" in result["reason"]

    @pytest.mark.asyncio
    async def test_successful_evaluation(self, arbitrage, sample_opportunity):
        """Test successful evaluation."""
        sample_opportunity.spread = 0.1
        sample_opportunity.estimated_daily_profit_pct = 0.05

        result = await arbitrage.evaluate_opportunity(sample_opportunity, 10000.0)
        assert result["should_execute"] is True
        assert result["position_size"] == 1000.0  # 10% of 10000
        assert result["expected_daily_profit_pct"] == 0.05
        assert result["expected_daily_profit"] == 0.5  # 1000 * 0.05 / 100
        assert result["risk_level"] == "medium"  # spread > 0.1 is "low"

    @pytest.mark.asyncio
    async def test_low_risk_evaluation(self, arbitrage, sample_opportunity):
        """Test low risk evaluation when spread > 0.1."""
        sample_opportunity.spread = 0.15

        result = await arbitrage.evaluate_opportunity(sample_opportunity, 10000.0)
        assert result["risk_level"] == "low"


class TestExecuteArbitrage:
    """Test execute_arbitrage method."""

    @pytest.mark.asyncio
    async def test_evaluation_failed(self, arbitrage, sample_opportunity):
        """Test when evaluation fails."""
        sample_opportunity.spread = 0.03  # Too small

        result = await arbitrage.execute_arbitrage(sample_opportunity, 10000.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_executor(self, arbitrage, sample_opportunity, mock_executors):
        """Test when executor missing."""
        # Remove one executor
        arbitrage.executors.pop("binance")

        result = await arbitrage.execute_arbitrage(sample_opportunity, 10000.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_ticker_failed(self, arbitrage, sample_opportunity, mock_executors):
        """Test when get_ticker returns None."""
        mock_executors["binance"].get_ticker.return_value = None

        result = await arbitrage.execute_arbitrage(sample_opportunity, 10000.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_price(self, arbitrage, sample_opportunity, mock_executors):
        """Test when price is zero or None."""
        mock_executors["binance"].get_ticker.return_value = {"last": 0}

        result = await arbitrage.execute_arbitrage(sample_opportunity, 10000.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_long_order_failed(self, arbitrage, sample_opportunity, mock_executors):
        """Test when long order execution fails."""
        mock_executors["binance"].execute_order.return_value = MagicMock(success=False, error="Insufficient balance")

        result = await arbitrage.execute_arbitrage(sample_opportunity, 10000.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_short_order_failed_with_cleanup(self, arbitrage, sample_opportunity, mock_executors):
        """Test when short order fails and cleanup long position."""
        # Long succeeds, short fails
        mock_executors["binance"].execute_order.return_value = MagicMock(
            success=True, filled_price=100.0, order_id="long_order_1"
        )
        mock_executors["okx"].execute_order.return_value = MagicMock(success=False, error="Network error")

        result = await arbitrage.execute_arbitrage(sample_opportunity, 10000.0)
        assert result is None
        # Verify cleanup was attempted
        mock_executors["binance"].close_position.assert_called_once()

    @pytest.mark.asyncio
    async def test_successful_execution(self, arbitrage, sample_opportunity, mock_executors, mock_position_manager):
        """Test successful arbitrage execution."""
        with patch("time.time", return_value=1234567890.0, autospec=True):
            result = await arbitrage.execute_arbitrage(sample_opportunity, 10000.0, leverage=3)

        assert result is not None
        assert result.symbol == "BTC/USDT"
        assert result.long_exchange == "binance"
        assert result.short_exchange == "okx"
        assert result.status == "open"
        assert result.entry_spread == sample_opportunity.spread

        # Verify orders executed
        assert mock_executors["binance"].execute_order.call_count == 1
        assert mock_executors["okx"].execute_order.call_count == 1

        # Verify positions tracked
        assert mock_position_manager.open_position.call_count == 2

        # Verify arbitrage position stored
        assert len(arbitrage.active_positions) == 1
        assert result.id in arbitrage.active_positions


class TestCloseArbitrage:
    """Test close_arbitrage method."""

    @pytest.mark.asyncio
    async def test_close_nonexistent(self, arbitrage):
        """Test closing non-existent arbitrage."""
        # Should not raise
        await arbitrage.close_arbitrage("nonexistent")

    @pytest.mark.asyncio
    async def test_close_already_closed(self, arbitrage, mock_executors):
        """Test closing already closed arbitrage."""
        arb_pos = ArbitragePosition(
            id="arb_1",
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_position_id="pos_long",
            short_position_id="pos_short",
            entry_spread=0.05,
            entry_time=1234567890.0,
            status="closed",
        )
        arbitrage.active_positions["arb_1"] = arb_pos

        await arbitrage.close_arbitrage("arb_1")

        # Should not call close_position
        mock_executors["binance"].close_position.assert_not_called()
        mock_executors["okx"].close_position.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_close(self, arbitrage, mock_executors, mock_position_manager):
        """Test successful arbitrage close."""
        arb_pos = ArbitragePosition(
            id="arb_1",
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_position_id="pos_long",
            short_position_id="pos_short",
            entry_spread=0.05,
            entry_time=1234567890.0,
        )
        arbitrage.active_positions["arb_1"] = arb_pos

        await arbitrage.close_arbitrage("arb_1", "profit_target")

        assert arb_pos.status == "closed"
        mock_executors["binance"].close_position.assert_called_once()
        mock_executors["okx"].close_position.assert_called_once()
        assert mock_position_manager.close_position.call_count == 2

    @pytest.mark.asyncio
    async def test_close_missing_executor(self, arbitrage, mock_executors, mock_position_manager):
        """Test close when executor missing."""
        arb_pos = ArbitragePosition(
            id="arb_1",
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_position_id="pos_long",
            short_position_id="pos_short",
            entry_spread=0.05,
            entry_time=1234567890.0,
        )
        arbitrage.active_positions["arb_1"] = arb_pos

        # Remove one executor
        arbitrage.executors.pop("binance")

        await arbitrage.close_arbitrage("arb_1")

        # Should still close the other side
        mock_executors["okx"].close_position.assert_called_once()
        assert arb_pos.status == "closed"


class TestCloseAll:
    """Test close_all method."""

    @pytest.mark.asyncio
    async def test_close_all_empty(self, arbitrage):
        """Test close all when no positions."""
        await arbitrage.close_all()
        # Should not raise

    @pytest.mark.asyncio
    async def test_close_all_multiple(self, arbitrage, mock_executors, mock_position_manager):
        """Test close all with multiple positions."""
        # Add multiple positions
        for i in range(3):
            arbitrage.active_positions[f"arb_{i}"] = ArbitragePosition(
                id=f"arb_{i}",
                symbol=f"SYMBOL_{i}",
                long_exchange="binance",
                short_exchange="okx",
                long_position_id=f"pos_long_{i}",
                short_position_id=f"pos_short_{i}",
                entry_spread=0.05,
                entry_time=1234567890.0,
            )

        await arbitrage.close_all()

        # All should be closed
        for arb_pos in arbitrage.active_positions.values():
            assert arb_pos.status == "closed"


class TestGetStatus:
    """Test get_status method."""

    def test_empty_status(self, arbitrage):
        """Test status with no positions."""
        status = arbitrage.get_status()
        assert status["active_positions"] == 0
        assert status["max_positions"] == 3
        assert status["positions"] == []

    def test_with_active_positions(self, arbitrage):
        """Test status with active positions."""
        # Add active and closed positions
        arbitrage.active_positions["arb_1"] = ArbitragePosition(
            id="arb_1",
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_position_id="pos1",
            short_position_id="pos2",
            entry_spread=0.05,
            entry_time=1234567890.0,
            status="open",
            funding_collected=10.0,
        )

        arbitrage.active_positions["arb_2"] = ArbitragePosition(
            id="arb_2",
            symbol="ETH/USDT",
            long_exchange="okx",
            short_exchange="binance",
            long_position_id="pos3",
            short_position_id="pos4",
            entry_spread=0.1,
            entry_time=1234567891.0,
            status="closed",
        )

        status = arbitrage.get_status()
        assert status["active_positions"] == 1
        assert len(status["positions"]) == 1

        pos_info = status["positions"][0]
        assert pos_info["id"] == "arb_1"
        assert pos_info["symbol"] == "BTC/USDT"
        assert pos_info["long_exchange"] == "binance"
        assert pos_info["short_exchange"] == "okx"
        assert pos_info["entry_spread"] == 0.05
        assert pos_info["funding_collected"] == 10.0


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_concurrent_evaluation(self, arbitrage, sample_opportunity):
        """Test concurrent evaluations don't interfere."""
        # Run multiple evaluations concurrently
        tasks = [arbitrage.evaluate_opportunity(sample_opportunity, 10000.0) for _ in range(5)]
        results = await asyncio.gather(*tasks)

        # All should succeed (no existing positions)
        for result in results:
            assert result["should_execute"] is True

    @pytest.mark.asyncio
    async def test_position_size_calculation(self, arbitrage, sample_opportunity):
        """Test position size calculation."""
        arbitrage.position_size_pct = 0.25  # 25%

        result = await arbitrage.evaluate_opportunity(sample_opportunity, 100000.0)
        assert result["position_size"] == 25000.0  # 25% of 100k

    @pytest.mark.asyncio
    async def test_minimal_spread(self, arbitrage, sample_opportunity):
        """Test with minimal valid spread."""
        sample_opportunity.spread = 0.051  # Just above min

        result = await arbitrage.evaluate_opportunity(sample_opportunity, 10000.0)
        assert result["should_execute"] is True

    @pytest.mark.asyncio
    async def test_zero_leverage(self, arbitrage, sample_opportunity, mock_executors):
        """Test execution with zero leverage (should use default)."""
        # Default leverage is 2
        # Should still work, leverage=0 might be treated as default
        # This depends on implementation
        # For now, just check it doesn't crash
        await arbitrage.execute_arbitrage(sample_opportunity, 10000.0, leverage=0)

    @pytest.mark.asyncio
    async def test_order_with_none_filled_price(self, arbitrage, sample_opportunity, mock_executors):
        """Test when order returns None filled price."""
        mock_executors["binance"].execute_order.return_value = MagicMock(
            success=True, filled_price=None, order_id="long_order_1"
        )
        mock_executors["okx"].execute_order.return_value = MagicMock(
            success=True, filled_price=None, order_id="short_order_1"
        )

        with patch("time.time", return_value=1234567890.0, autospec=True):
            result = await arbitrage.execute_arbitrage(sample_opportunity, 10000.0)

        # Should use ticker price as fallback
        assert result is not None

    @pytest.mark.asyncio
    async def test_unexpected_exception_in_execute(
        self, arbitrage, sample_opportunity, mock_executors, mock_position_manager
    ):
        """Test exception handling when open_position raises unexpectedly."""
        mock_position_manager.open_position.side_effect = RuntimeError("DB error")

        with patch("time.time", return_value=1234567890.0, autospec=True):
            result = await arbitrage.execute_arbitrage(sample_opportunity, 10000.0)

        assert result is None


class TestIntegration:
    """Test integration scenarios."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, arbitrage, sample_opportunity, mock_executors, mock_position_manager):
        """Test full arbitrage lifecycle."""
        # 1. Evaluate
        evaluation = await arbitrage.evaluate_opportunity(sample_opportunity, 10000.0)
        assert evaluation["should_execute"] is True

        # 2. Execute
        with patch("time.time", return_value=1234567890.0, autospec=True):
            arb_pos = await arbitrage.execute_arbitrage(sample_opportunity, 10000.0)
        assert arb_pos is not None
        assert arb_pos.status == "open"

        # 3. Check status
        status = arbitrage.get_status()
        assert status["active_positions"] == 1

        # 4. Close
        await arbitrage.close_arbitrage(arb_pos.id)
        assert arb_pos.status == "closed"

        # 5. Final status
        status = arbitrage.get_status()
        assert status["active_positions"] == 0

    @pytest.mark.asyncio
    async def test_multiple_symbols(self, arbitrage, mock_executors, mock_position_manager):
        """Test managing multiple arbitrage positions."""
        symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

        for i, symbol in enumerate(symbols):
            opp = MagicMock(
                symbol=symbol,
                exchange_long="binance",
                exchange_short="okx",
                spread=0.1,
                estimated_daily_profit_pct=0.05,
            )

            with patch("time.time", return_value=1234567890.0 + i, autospec=True):
                result = await arbitrage.execute_arbitrage(opp, 10000.0)
                assert result is not None

        # Should have 3 active positions
        assert len(arbitrage.active_positions) == 3
        status = arbitrage.get_status()
        assert status["active_positions"] == 3

        # Close all
        await arbitrage.close_all()
        status = arbitrage.get_status()
        assert status["active_positions"] == 0


class TestMonitorPositions:
    """Test monitor_positions method."""

    @pytest.mark.asyncio
    async def test_no_positions(self, arbitrage):
        """Test monitoring with no positions."""
        await arbitrage.monitor_positions()
        # Should not raise

    @pytest.mark.asyncio
    async def test_skip_closed_position(self, arbitrage, mock_funding_monitor):
        """Test skipping closed positions."""
        arbitrage.active_positions["arb_1"] = ArbitragePosition(
            id="arb_1",
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_position_id="pos1",
            short_position_id="pos2",
            entry_spread=0.05,
            entry_time=1234567890.0,
            status="closed",
        )
        await arbitrage.monitor_positions()
        mock_funding_monitor.get_rates.assert_not_called()

    @pytest.mark.asyncio
    async def test_insufficient_rates(self, arbitrage, mock_funding_monitor):
        """Test when fewer than 2 rates available."""
        arbitrage.active_positions["arb_1"] = ArbitragePosition(
            id="arb_1",
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_position_id="pos1",
            short_position_id="pos2",
            entry_spread=0.05,
            entry_time=1234567890.0,
        )
        mock_funding_monitor.get_rates.return_value = {"binance": MagicMock(rate=-0.001)}
        await arbitrage.monitor_positions()
        # Should not close
        assert arbitrage.active_positions["arb_1"].status == "open"

    @pytest.mark.asyncio
    async def test_missing_exchange_rate(self, arbitrage, mock_funding_monitor):
        """Test when one exchange rate missing."""
        arbitrage.active_positions["arb_1"] = ArbitragePosition(
            id="arb_1",
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_position_id="pos1",
            short_position_id="pos2",
            entry_spread=0.05,
            entry_time=1234567890.0,
        )
        # Two rates but missing one exchange
        mock_funding_monitor.get_rates.return_value = {
            "binance": MagicMock(rate=-0.001),
            "bybit": MagicMock(rate=0.002),
        }
        await arbitrage.monitor_positions()
        assert arbitrage.active_positions["arb_1"].status == "open"

    @pytest.mark.asyncio
    async def test_spread_narrowed_close(self, arbitrage, mock_funding_monitor, mock_executors, mock_position_manager):
        """Test closing when spread narrows."""
        arbitrage.active_positions["arb_1"] = ArbitragePosition(
            id="arb_1",
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_position_id="pos1",
            short_position_id="pos2",
            entry_spread=0.05,
            entry_time=1234567890.0,
        )
        # Spread = |(-0.001) - 0.0015| = 0.0005 < close_spread_pct 0.01
        mock_funding_monitor.get_rates.return_value = {"binance": MagicMock(rate=-0.001), "okx": MagicMock(rate=0.0015)}
        await arbitrage.monitor_positions()
        assert arbitrage.active_positions["arb_1"].status == "closed"

    @pytest.mark.asyncio
    async def test_rates_reversed_close(self, arbitrage, mock_funding_monitor, mock_executors, mock_position_manager):
        """Test closing when rates reverse (long rate > short rate)."""
        arbitrage.active_positions["arb_1"] = ArbitragePosition(
            id="arb_1",
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_position_id="pos1",
            short_position_id="pos2",
            entry_spread=0.05,
            entry_time=1234567890.0,
        )
        # long_rate (0.005) > short_rate (0.001) → reversed
        # spread = 0.004 < close_spread_pct 0.01 → will hit spread_narrowed first
        # So use spread > close_spread_pct: long_rate=0.05, short_rate=0.01
        mock_funding_monitor.get_rates.return_value = {"binance": MagicMock(rate=0.05), "okx": MagicMock(rate=0.01)}
        await arbitrage.monitor_positions()
        assert arbitrage.active_positions["arb_1"].status == "closed"

    @pytest.mark.asyncio
    async def test_healthy_position_no_close(self, arbitrage, mock_funding_monitor):
        """Test healthy position not closed."""
        arbitrage.active_positions["arb_1"] = ArbitragePosition(
            id="arb_1",
            symbol="BTC/USDT",
            long_exchange="binance",
            short_exchange="okx",
            long_position_id="pos1",
            short_position_id="pos2",
            entry_spread=0.05,
            entry_time=1234567890.0,
        )
        # long_rate < short_rate (normal), spread > close_spread_pct
        mock_funding_monitor.get_rates.return_value = {"binance": MagicMock(rate=-0.005), "okx": MagicMock(rate=0.005)}
        await arbitrage.monitor_positions()
        assert arbitrage.active_positions["arb_1"].status == "open"
