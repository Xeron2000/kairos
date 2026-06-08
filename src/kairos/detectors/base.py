"""Base classes for real-time anomaly detection."""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List


@dataclass
class AnomalyEvent:
    """Event emitted when an anomaly is detected."""

    symbol: str
    event_type: str  # "price_velocity" | "volume_spike" | "open_interest_change" | "funding_rate_anomaly"
    severity: str  # "HIGH" | "MEDIUM" | "LOW"
    data: dict
    timestamp: float = field(default_factory=time.time)


class BaseDetector:
    """Base class for real-time anomaly detectors.

    Detectors are called from WebSocket handler threads. They must be thread-safe
    and should emit events via callbacks rather than blocking.
    """

    def __init__(self, config: dict):
        self.config = config
        self._lock = threading.RLock()
        self._callbacks: List[Callable[[AnomalyEvent], None]] = []
        self.logger = logging.getLogger(self.__class__.__name__)

    def on_event(self, callback: Callable[[AnomalyEvent], None]):
        """Register a callback for anomaly events."""
        self._callbacks.append(callback)

    def _emit(self, event: AnomalyEvent):
        """Emit an anomaly event to all registered callbacks."""
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception as e:
                self.logger.error("Callback error: %s", e)

    def on_price_update(self, symbol: str, price: float, timestamp: float):
        """Called on every price tick from WebSocket. Override in subclass."""

    def on_volume_update(self, symbol: str, cumulative_volume: float, timestamp: float):
        """Called on every volume update from WebSocket. Override in subclass."""

    def update_config(self, config: dict):
        """Update detector configuration at runtime."""
        with self._lock:
            self.config = config
