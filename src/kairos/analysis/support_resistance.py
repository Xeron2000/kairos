"""Support and resistance level detection."""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class PriceLevel:
    """Represents a support or resistance level."""
    price: float
    level_type: str  # "support" or "resistance"
    strength: int  # 1-5, how many times tested
    first_test_time: float
    last_test_time: float
    touch_count: int
    is_round_number: bool = False  # e.g., 50000, 1000
    volume_at_level: float = 0  # Volume when price touched this level

    @property
    def description(self) -> str:
        """Human-readable description."""
        return f"{self.level_type} @ {self.price:.2f} (strength: {self.strength}, touches: {self.touch_count})"


class SupportResistance:
    """Detects support and resistance levels."""

    def __init__(self, config: dict | None = None):
        self.logger = logging.getLogger("kairos.analysis.sr")
        config = config or {}

        # Configuration
        self.lookback_periods = config.get("lookbackPeriods", 100)
        self.min_touches = config.get("minTouches", 2)
        self.proximity_pct = config.get("proximityPct", 0.5)  # 0.5% proximity to merge levels
        self.round_number_threshold = config.get("roundNumberThreshold", 1000)  # Round numbers every $1000

    def find_levels(
        self,
        symbol: str,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
        timestamps: np.ndarray,
        current_price: float
    ) -> dict:
        """Find support and resistance levels."""
        # Find pivot points
        pivots_high = self._find_pivot_highs(highs)
        pivots_low = self._find_pivot_lows(lows)

        # Cluster nearby levels
        resistance_levels = self._cluster_levels(
            pivots_high, highs, volumes, timestamps, "resistance"
        )
        support_levels = self._cluster_levels(
            pivots_low, lows, volumes, timestamps, "support"
        )

        # Add round number levels
        round_levels = self._find_round_numbers(current_price)

        # Filter and rank levels
        resistance_levels = self._filter_levels(resistance_levels, current_price, "resistance")
        support_levels = self._filter_levels(support_levels, current_price, "support")

        # Find nearest levels
        nearest_resistance = self._find_nearest(resistance_levels, current_price, "resistance")
        nearest_support = self._find_nearest(support_levels, current_price, "support")

        return {
            "symbol": symbol,
            "current_price": current_price,
            "resistance_levels": resistance_levels[:5],  # Top 5
            "support_levels": support_levels[:5],  # Top 5
            "nearest_resistance": nearest_resistance,
            "nearest_support": nearest_support,
            "round_numbers": round_levels
        }

    def _find_pivot_highs(self, highs: np.ndarray, window: int = 5) -> list[tuple[int, float]]:
        """Find pivot high points."""
        pivots = []
        for i in range(window, len(highs) - window):
            if highs[i] == max(highs[i-window:i+window+1]):
                pivots.append((i, highs[i]))
        return pivots

    def _find_pivot_lows(self, lows: np.ndarray, window: int = 5) -> list[tuple[int, float]]:
        """Find pivot low points."""
        pivots = []
        for i in range(window, len(lows) - window):
            if lows[i] == min(lows[i-window:i+window+1]):
                pivots.append((i, lows[i]))
        return pivots

    def _cluster_levels(
        self,
        pivots: list[tuple[int, float]],
        prices: np.ndarray,
        volumes: np.ndarray,
        timestamps: np.ndarray,
        level_type: str
    ) -> list[PriceLevel]:
        """Cluster nearby pivot points into levels."""
        if not pivots:
            return []

        # Sort by price
        pivots_sorted = sorted(pivots, key=lambda x: x[1])

        levels = []
        current_cluster = [pivots_sorted[0]]

        for i in range(1, len(pivots_sorted)):
            prev_price = current_cluster[-1][1]
            curr_price = pivots_sorted[i][1]

            # Check if close enough to merge
            if abs(curr_price - prev_price) / prev_price * 100 < self.proximity_pct:
                current_cluster.append(pivots_sorted[i])
            else:
                # Create level from cluster
                if len(current_cluster) >= self.min_touches:
                    level = self._create_level(current_cluster, prices, volumes, timestamps, level_type)
                    levels.append(level)
                current_cluster = [pivots_sorted[i]]

        # Don't forget last cluster
        if len(current_cluster) >= self.min_touches:
            level = self._create_level(current_cluster, prices, volumes, timestamps, level_type)
            levels.append(level)

        return levels

    def _create_level(
        self,
        cluster: list[tuple[int, float]],
        prices: np.ndarray,
        volumes: np.ndarray,
        timestamps: np.ndarray,
        level_type: str
    ) -> PriceLevel:
        """Create a PriceLevel from a cluster of pivots."""
        # Average price of cluster
        avg_price = np.mean([p[1] for p in cluster])

        # Calculate strength based on touches and recency
        touch_count = len(cluster)
        strength = min(touch_count, 5)

        # Get timestamps
        first_idx = cluster[0][0]
        last_idx = cluster[-1][0]

        # Average volume at this level
        avg_volume = np.mean(volumes[first_idx:last_idx+1]) if last_idx < len(volumes) else 0

        return PriceLevel(
            price=avg_price,
            level_type=level_type,
            strength=strength,
            first_test_time=timestamps[first_idx] if first_idx < len(timestamps) else 0,
            last_test_time=timestamps[last_idx] if last_idx < len(timestamps) else 0,
            touch_count=touch_count,
            volume_at_level=avg_volume
        )

    def _filter_levels(
        self,
        levels: list[PriceLevel],
        current_price: float,
        level_type: str
    ) -> list[PriceLevel]:
        """Filter and sort levels by relevance."""
        if level_type == "resistance":
            # Only keep levels above current price
            levels = [l for l in levels if l.price > current_price]
        else:
            # Only keep levels below current price
            levels = [l for l in levels if l.price < current_price]

        # Sort by distance from current price
        levels.sort(key=lambda l: abs(l.price - current_price))

        return levels

    def _find_nearest(
        self,
        levels: list[PriceLevel],
        current_price: float,
        level_type: str
    ) -> Optional[PriceLevel]:
        """Find nearest level."""
        if not levels:
            return None
        return levels[0]

    def _find_round_numbers(self, current_price: float) -> list[float]:
        """Find round number levels near current price."""
        round_levels = []

        # Determine step size based on price
        if current_price > 10000:
            step = 1000
        elif current_price > 1000:
            step = 100
        elif current_price > 100:
            step = 10
        else:
            step = 1

        # Find round numbers within 20% of current price
        range_low = current_price * 0.8
        range_high = current_price * 1.2

        level = (range_low // step) * step
        while level <= range_high:
            if level > 0:
                round_levels.append(level)
            level += step

        return round_levels

    def calculate_risk_reward(
        self,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        side: str
    ) -> dict:
        """Calculate risk/reward ratio."""
        if side == "long":
            risk = entry_price - stop_loss
            reward = take_profit - entry_price
        else:
            risk = stop_loss - entry_price
            reward = entry_price - take_profit

        rr_ratio = reward / risk if risk > 0 else 0

        return {
            "entry": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk": risk,
            "reward": reward,
            "risk_pct": (risk / entry_price * 100),
            "reward_pct": (reward / entry_price * 100),
            "rr_ratio": rr_ratio
        }
