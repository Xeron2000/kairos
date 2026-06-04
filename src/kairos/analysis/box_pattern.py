"""Box pattern detection for trading analysis."""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np


class BoxStatus(str, Enum):
    FORMING = "forming"  # Box is still forming
    CONVERGING = "converging"  # Price converging, near breakout
    BREAKOUT_UP = "breakout_up"  # Broke upward
    BREAKOUT_DOWN = "breakout_down"  # Broke downward
    INVALID = "invalid"  # Box pattern invalidated


@dataclass
class BoxPattern:
    """Represents a box pattern."""
    symbol: str
    timeframe: str
    high: float  # Box upper boundary
    low: float  # Box lower boundary
    start_time: float
    end_time: float
    status: BoxStatus
    touch_high: int = 0  # Number of touches at high
    touch_low: int = 0  # Number of touches at low
    second_test_high: bool = False  # Has second test at high
    second_test_low: bool = False  # Has second test at low
    convergence_pct: float = 0.0  # How much price has converged (0-1)
    volume_declining: bool = False  # Volume declining during consolidation
    breakout_price: Optional[float] = None
    breakout_time: Optional[float] = None

    @property
    def height(self) -> float:
        """Box height in absolute terms."""
        return self.high - self.low

    @property
    def height_pct(self) -> float:
        """Box height as percentage of low."""
        return (self.height / self.low * 100) if self.low > 0 else 0

    @property
    def midpoint(self) -> float:
        """Box midpoint."""
        return (self.high + self.low) / 2

    @property
    def is_ready(self) -> bool:
        """Check if box is ready for breakout (has second test and convergence)."""
        return (self.second_test_high or self.second_test_low) and self.convergence_pct > 0.7


class BoxDetector:
    """Detects box patterns in price data."""

    def __init__(self, config: dict | None = None):
        self.logger = logging.getLogger("kairos.analysis.box")
        config = config or {}

        # Configuration
        self.min_bars = config.get("minBars", 10)  # Minimum bars for a box
        self.max_bars = config.get("maxBars", 100)  # Maximum bars for a box
        self.touch_threshold_pct = config.get("touchThresholdPct", 0.3)  # % from high/low to count as touch
        self.convergence_threshold = config.get("convergenceThreshold", 0.7)  # 70% convergence
        self.min_volume_decline_pct = config.get("minVolumeDeclinePct", 0.3)  # 30% volume decline

    def detect(
        self,
        symbol: str,
        timeframe: str,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
        timestamps: np.ndarray
    ) -> list[BoxPattern]:
        """Detect box patterns in OHLCV data."""
        boxes = []

        if len(highs) < self.min_bars:
            return boxes

        # Find potential box regions using sliding window
        i = 0
        while i < len(highs) - self.min_bars:
            # Look for consolidation after a move
            box = self._try_detect_box(
                symbol, timeframe,
                highs[i:], lows[i:], closes[i:],
                volumes[i:], timestamps[i:]
            )

            if box and box.status != BoxStatus.INVALID:
                boxes.append(box)
                # Skip ahead past this box
                box_bars = int((box.end_time - box.start_time) / (timestamps[1] - timestamps[0])) if len(timestamps) > 1 else self.min_bars
                i += max(box_bars, self.min_bars)
            else:
                i += 1

        return boxes

    def _try_detect_box(
        self,
        symbol: str,
        timeframe: str,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
        timestamps: np.ndarray
    ) -> Optional[BoxPattern]:
        """Try to detect a single box pattern starting from the beginning of data."""
        if len(highs) < self.min_bars:
            return None

        # Find initial high and low
        initial_high = np.max(highs[:self.min_bars])
        initial_low = np.min(lows[:self.min_bars])

        # Box height must be reasonable (not too tight, not too wide)
        height_pct = (initial_high - initial_low) / initial_low * 100 if initial_low > 0 else 0
        if height_pct < 1 or height_pct > 15:  # 1-15% range
            return None

        # Extend box while price stays within bounds
        box_high = initial_high
        box_low = initial_low
        touch_high = 0
        touch_low = 0
        box_end = self.min_bars

        for i in range(self.min_bars, min(len(highs), self.max_bars)):
            # Update box boundaries if price exceeds slightly
            if highs[i] > box_high * (1 + self.touch_threshold_pct / 100):
                break  # Price broke above box
            if lows[i] < box_low * (1 - self.touch_threshold_pct / 100):
                break  # Price broke below box

            # Count touches
            if abs(highs[i] - box_high) / box_high * 100 < self.touch_threshold_pct:
                touch_high += 1
            if abs(lows[i] - box_low) / box_low * 100 < self.touch_threshold_pct:
                touch_low += 1

            box_end = i

        # Check if we have enough bars
        if box_end < self.min_bars:
            return None

        # Check for second tests
        second_test_high = touch_high >= 2
        second_test_low = touch_low >= 2

        # Calculate convergence (range getting tighter)
        recent_range = np.max(highs[max(0, box_end-5):box_end]) - np.min(lows[max(0, box_end-5):box_end])
        initial_range = box_high - box_low
        convergence = 1 - (recent_range / initial_range) if initial_range > 0 else 0

        # Check volume decline
        early_vol = np.mean(volumes[:self.min_bars]) if len(volumes) >= self.min_bars else 0
        recent_vol = np.mean(volumes[max(0, box_end-5):box_end])
        volume_declining = (recent_vol < early_vol * (1 - self.min_volume_decline_pct)) if early_vol > 0 else False

        # Determine status
        if convergence > self.convergence_threshold and (second_test_high or second_test_low):
            status = BoxStatus.CONVERGING
        else:
            status = BoxStatus.FORMING

        return BoxPattern(
            symbol=symbol,
            timeframe=timeframe,
            high=box_high,
            low=box_low,
            start_time=timestamps[0],
            end_time=timestamps[box_end],
            status=status,
            touch_high=touch_high,
            touch_low=touch_low,
            second_test_high=second_test_high,
            second_test_low=second_test_low,
            convergence_pct=convergence,
            volume_declining=volume_declining
        )

    def check_breakout(
        self,
        box: BoxPattern,
        current_price: float,
        current_volume: float,
        avg_volume: float
    ) -> Optional[BoxPattern]:
        """Check if a box has broken out."""
        if box.status in [BoxStatus.BREAKOUT_UP, BoxStatus.BREAKOUT_DOWN]:
            return box  # Already broken out

        # Check for upward breakout
        if current_price > box.high * 1.005:  # 0.5% above box high
            # Volume should confirm breakout
            if current_volume > avg_volume * 1.5:
                box.status = BoxStatus.BREAKOUT_UP
                box.breakout_price = current_price
                box.breakout_time = float("inf")  # Would need actual timestamp
                return box

        # Check for downward breakout
        if current_price < box.low * 0.995:  # 0.5% below box low
            if current_volume > avg_volume * 1.5:
                box.status = BoxStatus.BREAKOUT_DOWN
                box.breakout_price = current_price
                box.breakout_time = float("inf")
                return box

        return box
