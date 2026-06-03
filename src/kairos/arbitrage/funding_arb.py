"""Funding rate arbitrage execution logic."""

import logging
import time
from dataclasses import dataclass
from typing import Optional

from ..trades.executor import Order, OrderSide, OrderType, PositionSide, TradeExecutor
from ..trades.position import PositionManager
from .funding_monitor import FundingOpportunity, FundingRateMonitor


@dataclass
class ArbitragePosition:
    """Represents an active arbitrage position."""

    id: str
    symbol: str
    long_exchange: str
    short_exchange: str
    long_position_id: str
    short_position_id: str
    entry_spread: float
    entry_time: float
    status: str = "open"  # open, closed, partial
    pnl: float = 0
    funding_collected: float = 0


class FundingArbitrage:
    """Manages funding rate arbitrage operations."""

    def __init__(
        self,
        config: dict,
        executors: dict[str, TradeExecutor],
        position_manager: PositionManager,
        funding_monitor: FundingRateMonitor,
    ):
        self.logger = logging.getLogger("kairos.arbitrage.arb")
        self.config = config
        self.executors = executors
        self.position_manager = position_manager
        self.funding_monitor = funding_monitor

        # Arbitrage config
        self.min_spread_pct = config.get("minSpreadPct", 0.05)
        self.position_size_pct = config.get("positionSizePct", 0.1)  # 10% of capital
        self.max_positions = config.get("maxPositions", 3)
        self.close_spread_pct = config.get("closeSpreadPct", 0.01)  # Close when spread narrows

        # Active arbitrage positions
        self.active_positions: dict[str, ArbitragePosition] = {}

    async def evaluate_opportunity(self, opportunity: FundingOpportunity, capital: float) -> dict:
        """Evaluate if an arbitrage opportunity is worth taking."""
        # Check if we already have this symbol
        for arb_pos in self.active_positions.values():
            if arb_pos.symbol == opportunity.symbol and arb_pos.status == "open":
                return {"should_execute": False, "reason": "Already have position in this symbol"}

        # Check max positions
        if len(self.active_positions) >= self.max_positions:
            return {"should_execute": False, "reason": "Max positions reached"}

        # Calculate position size
        position_size = capital * self.position_size_pct

        # Check if spread is significant enough
        if opportunity.spread < self.min_spread_pct:
            return {
                "should_execute": False,
                "reason": f"Spread too small ({opportunity.spread:.3f}% < {self.min_spread_pct}%)",
            }

        # Calculate expected daily profit
        daily_profit_pct = opportunity.estimated_daily_profit_pct

        return {
            "should_execute": True,
            "position_size": position_size,
            "expected_daily_profit_pct": daily_profit_pct,
            "expected_daily_profit": position_size * daily_profit_pct / 100,
            "risk_level": "low" if opportunity.spread > 0.1 else "medium",
        }

    async def execute_arbitrage(
        self, opportunity: FundingOpportunity, capital: float, leverage: int = 2
    ) -> Optional[ArbitragePosition]:
        """Execute a funding rate arbitrage."""
        # Evaluate first
        evaluation = await self.evaluate_opportunity(opportunity, capital)
        if not evaluation["should_execute"]:
            self.logger.info(f"Skipping arbitrage: {evaluation['reason']}")
            return None

        position_size = evaluation["position_size"]

        # Get executors
        long_executor = self.executors.get(opportunity.exchange_long)
        short_executor = self.executors.get(opportunity.exchange_short)

        if not long_executor or not short_executor:
            self.logger.error("Missing executor for one or both exchanges")
            return None

        try:
            # Calculate amount (simplified - would need price)
            long_ticker = await long_executor.get_ticker(opportunity.symbol)
            short_ticker = await short_executor.get_ticker(opportunity.symbol)

            if not long_ticker or not short_ticker:
                return None

            long_price = long_ticker.get("last", 0)
            short_price = short_ticker.get("last", 0)

            if not long_price or not short_price:
                return None

            # Calculate amount based on position size
            amount = position_size / long_price

            # Execute long position
            long_order = Order(
                symbol=opportunity.symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                amount=amount,
                leverage=leverage,
                position_side=PositionSide.LONG,
            )

            long_result = await long_executor.execute_order(long_order)
            if not long_result.success:
                self.logger.error(f"Failed to execute long: {long_result.error}")
                return None

            # Execute short position
            short_order = Order(
                symbol=opportunity.symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                amount=amount,
                leverage=leverage,
                position_side=PositionSide.SHORT,
            )

            short_result = await short_executor.execute_order(short_order)
            if not short_result.success:
                # Try to close the long position
                self.logger.error(f"Failed to execute short: {short_result.error}")
                await long_executor.close_position(opportunity.symbol, PositionSide.LONG, amount)
                return None

            # Track positions
            long_pos = self.position_manager.open_position(
                symbol=opportunity.symbol,
                side="long",
                entry_price=long_result.filled_price or long_price,
                amount=amount,
                leverage=leverage,
                strategy="funding_arb",
                notes=f"Arb long on {opportunity.exchange_long}",
            )

            short_pos = self.position_manager.open_position(
                symbol=opportunity.symbol,
                side="short",
                entry_price=short_result.filled_price or short_price,
                amount=amount,
                leverage=leverage,
                strategy="funding_arb",
                notes=f"Arb short on {opportunity.exchange_short}",
            )

            # Create arbitrage position
            arb_id = f"arb_{opportunity.symbol}_{int(time.time())}"
            arb_position = ArbitragePosition(
                id=arb_id,
                symbol=opportunity.symbol,
                long_exchange=opportunity.exchange_long,
                short_exchange=opportunity.exchange_short,
                long_position_id=long_pos.id,
                short_position_id=short_pos.id,
                entry_spread=opportunity.spread,
                entry_time=time.time(),
            )

            self.active_positions[arb_id] = arb_position

            self.logger.info(
                f"Executed arbitrage {arb_id}: {opportunity.symbol} "
                f"long@{opportunity.exchange_long} short@{opportunity.exchange_short} "
                f"spread={opportunity.spread:.3f}%"
            )

            return arb_position

        except Exception as e:
            self.logger.error(f"Failed to execute arbitrage: {e}")
            return None

    async def monitor_positions(self):
        """Monitor active arbitrage positions and close if needed."""
        for arb_id, arb_pos in list(self.active_positions.items()):
            if arb_pos.status != "open":
                continue

            # Get current funding rates
            rates = self.funding_monitor.get_rates(arb_pos.symbol)
            if len(rates) < 2:
                continue

            long_rate = rates.get(arb_pos.long_exchange)
            short_rate = rates.get(arb_pos.short_exchange)

            if not long_rate or not short_rate:
                continue

            current_spread = abs(long_rate.rate - short_rate.rate)

            # Close if spread has narrowed significantly
            if current_spread < self.close_spread_pct:
                await self.close_arbitrage(arb_id, "spread_narrowed")
                continue

            # Close if rates have reversed
            if long_rate.rate > short_rate.rate:
                await self.close_arbitrage(arb_id, "rates_reversed")

    async def close_arbitrage(self, arb_id: str, reason: str = "manual"):
        """Close an arbitrage position."""
        arb_pos = self.active_positions.get(arb_id)
        if not arb_pos or arb_pos.status != "open":
            return

        self.logger.info(f"Closing arbitrage {arb_id}: {reason}")

        # Close both positions
        long_executor = self.executors.get(arb_pos.long_exchange)
        short_executor = self.executors.get(arb_pos.short_exchange)

        if long_executor:
            await long_executor.close_position(arb_pos.symbol, PositionSide.LONG)

        if short_executor:
            await short_executor.close_position(arb_pos.symbol, PositionSide.SHORT)

        # Update position status
        arb_pos.status = "closed"

        # Close tracked positions
        self.position_manager.close_position(arb_pos.long_position_id, 0)  # Would need actual price
        self.position_manager.close_position(arb_pos.short_position_id, 0)

    async def close_all(self):
        """Close all arbitrage positions."""
        for arb_id in list(self.active_positions.keys()):
            await self.close_arbitrage(arb_id, "close_all")

    def get_status(self) -> dict:
        """Get status of all arbitrage positions."""
        active = [p for p in self.active_positions.values() if p.status == "open"]

        return {
            "active_positions": len(active),
            "max_positions": self.max_positions,
            "positions": [
                {
                    "id": p.id,
                    "symbol": p.symbol,
                    "long_exchange": p.long_exchange,
                    "short_exchange": p.short_exchange,
                    "entry_spread": p.entry_spread,
                    "funding_collected": p.funding_collected,
                }
                for p in active
            ],
        }
