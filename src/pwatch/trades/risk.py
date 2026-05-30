"""Risk management for trading operations."""

import logging
from dataclasses import dataclass
from typing import Optional

from .position import Position, PositionManager


@dataclass
class RiskConfig:
    """Risk management configuration."""
    max_position_size_pct: float = 0.33  # Max 33% of capital per position
    max_total_exposure_pct: float = 0.66  # Max 66% total exposure (2 positions * 33%)
    max_leverage_btc: int = 10  # Max leverage for BTC/ETH
    max_leverage_alt: int = 5  # Max leverage for altcoins
    max_drawdown_pct: float = 0.20  # Max 20% drawdown before halt
    max_daily_loss_pct: float = 0.10  # Max 10% daily loss
    max_consecutive_losses: int = 3  # Max consecutive losses before pause
    max_open_positions: int = 2  # Max simultaneous positions
    min_risk_reward_ratio: float = 2.0  # Min R:R ratio for entry


class RiskManager:
    """Manages risk limits and position sizing."""
    
    def __init__(self, config: dict, position_manager: PositionManager):
        self.logger = logging.getLogger("pwatch.trades.risk")
        self.config = RiskConfig(**config.get("risk", {}))
        self.position_manager = position_manager
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
    
    def calculate_position_size(
        self,
        capital: float,
        entry_price: float,
        stop_loss: float,
        leverage: int,
        is_btc: bool = True
    ) -> dict:
        """Calculate position size based on risk parameters."""
        # Determine max leverage
        max_leverage = self.config.max_leverage_btc if is_btc else self.config.max_leverage_alt
        leverage = min(leverage, max_leverage)
        
        # Calculate risk per trade (distance to stop loss)
        risk_per_unit = abs(entry_price - stop_loss)
        risk_pct = risk_per_unit / entry_price
        
        # Max position value based on capital
        max_position_value = capital * self.config.max_position_size_pct
        
        # Position size based on risk (risking max_position_size_pct of capital)
        risk_amount = capital * self.config.max_position_size_pct
        position_size = risk_amount / risk_per_unit if risk_per_unit > 0 else 0
        
        # Cap by max position value
        position_value = position_size * entry_price
        if position_value > max_position_value:
            position_size = max_position_value / entry_price
        
        # Adjust for leverage
        margin_required = (position_size * entry_price) / leverage
        
        return {
            "position_size": round(position_size, 8),
            "position_value": round(position_size * entry_price, 2),
            "margin_required": round(margin_required, 2),
            "leverage": leverage,
            "risk_amount": round(risk_amount, 2),
            "risk_pct": round(risk_pct * 100, 2)
        }
    
    def check_position_allowed(
        self,
        capital: float,
        symbol: str,
        position_value: float
    ) -> tuple[bool, str]:
        """Check if a new position is allowed."""
        # Check daily loss limit
        if abs(self.daily_pnl) > capital * self.config.max_daily_loss_pct:
            return False, f"Daily loss limit reached ({self.daily_pnl:.2f})"
        
        # Check consecutive losses
        if self.consecutive_losses >= self.config.max_consecutive_losses:
            return False, f"Max consecutive losses reached ({self.consecutive_losses})"
        
        # Check total exposure
        open_positions = self.position_manager.get_open_positions()
        total_exposure = sum(
            p.entry_price * p.amount for p in open_positions
        )
        new_total = total_exposure + position_value
        if new_total > capital * self.config.max_total_exposure_pct:
            return False, f"Total exposure limit would be exceeded ({new_total:.2f} > {capital * self.config.max_total_exposure_pct:.2f})"
        
        # Check max drawdown (simplified - would need equity tracking)
        # For now, just check if we have too many open positions
        if len(open_positions) >= self.config.max_open_positions:
            return False, f"Max concurrent positions reached ({self.config.max_open_positions})"
        
        return True, "OK"
    
    def validate_stop_loss(
        self,
        entry_price: float,
        stop_loss: float,
        side: str
    ) -> tuple[bool, str]:
        """Validate stop loss placement."""
        if side == "long":
            if stop_loss >= entry_price:
                return False, "Stop loss must be below entry for long positions"
            risk_pct = (entry_price - stop_loss) / entry_price * 100
        else:
            if stop_loss <= entry_price:
                return False, "Stop loss must be above entry for short positions"
            risk_pct = (stop_loss - entry_price) / entry_price * 100
        
        # Warn if stop is too tight (< 0.5%) or too wide (> 10%)
        if risk_pct < 0.5:
            return True, f"Warning: Stop loss is very tight ({risk_pct:.2f}%)"
        if risk_pct > 10:
            return True, f"Warning: Stop loss is very wide ({risk_pct:.2f}%)"
        
        return True, "OK"
    
    def validate_take_profit(
        self,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        side: str
    ) -> tuple[bool, str, float]:
        """Validate take profit and calculate R:R ratio."""
        if side == "long":
            if take_profit <= entry_price:
                return False, "Take profit must be above entry for long", 0
            risk = entry_price - stop_loss
            reward = take_profit - entry_price
        else:
            if take_profit >= entry_price:
                return False, "Take profit must be below entry for short", 0
            risk = stop_loss - entry_price
            reward = entry_price - take_profit
        
        rr_ratio = reward / risk if risk > 0 else 0
        
        if rr_ratio < self.config.min_risk_reward_ratio:
            return False, f"R:R ratio too low ({rr_ratio:.2f} < {self.config.min_risk_reward_ratio})", rr_ratio
        
        return True, "OK", rr_ratio
    
    def update_daily_pnl(self, pnl: float):
        """Update daily PnL tracking."""
        self.daily_pnl += pnl
        
        # Track consecutive losses
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
    
    def reset_daily_stats(self):
        """Reset daily statistics."""
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
    
    def get_risk_summary(self, capital: float) -> dict:
        """Get current risk status summary."""
        open_positions = self.position_manager.get_open_positions()
        total_exposure = sum(p.entry_price * p.amount for p in open_positions)
        
        return {
            "capital": capital,
            "open_positions": len(open_positions),
            "total_exposure": total_exposure,
            "exposure_pct": (total_exposure / capital * 100) if capital > 0 else 0,
            "daily_pnl": self.daily_pnl,
            "daily_pnl_pct": (self.daily_pnl / capital * 100) if capital > 0 else 0,
            "consecutive_losses": self.consecutive_losses,
            "max_drawdown_pct": self.config.max_drawdown_pct * 100,
            "max_daily_loss_pct": self.config.max_daily_loss_pct * 100
        }
