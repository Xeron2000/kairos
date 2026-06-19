"""Minimal performance monitoring. Only counter/gauge/timer used by exchange base."""

from __future__ import annotations

import functools
import logging
import time
from collections import defaultdict

logger = logging.getLogger(__name__)


class _PerfMon:
    """Thin wrapper around counters, gauges, and timers."""

    def __init__(self) -> None:
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._timers: dict[str, list[float]] = defaultdict(list)

    def record_counter(self, name: str, value: float = 1.0) -> None:
        self._counters[name] += value

    def record_gauge(self, name: str, value: float) -> None:
        self._gauges[name] = value

    def start_timer(self, name: str) -> float:
        """Return start timestamp to pass to stop_timer."""
        return time.time()

    def stop_timer(self, start_ts: float, name: str) -> None:
        self._timers[name].append(time.time() - start_ts)

    def time_function(self, name: str):
        """Decorator to time a function call."""

        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                ts = self.start_timer(name)
                try:
                    return func(*args, **kwargs)
                finally:
                    self.stop_timer(ts, name)

            return wrapper

        return decorator


performance_monitor = _PerfMon()
