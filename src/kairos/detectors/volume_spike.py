"""Volume spike detector — detects abnormal volume surges in real time.

Tracks cumulative 24h volume deltas from WebSocket ticker updates to compute
per-minute volume, then compares against a rolling average to find spikes.
"""

from collections import deque

from .base import AnomalyEvent, BaseDetector

# Maximum per-symbol volume samples (1 per second × 10 minutes)
_MAX_SAMPLES = 600


class VolumeSpikeDetector(BaseDetector):
    """Detects when recent volume significantly exceeds the rolling average."""

    def __init__(self, config: dict):
        super().__init__(config)
        vs = config.get("volumeSpike", config)
        self.enabled = vs.get("enabled", True)
        self.multiplier = vs.get("multiplier", 3.0)
        self.window_minutes = vs.get("windowMinutes", 10)
        self.min_history_seconds = _parse_seconds(vs.get("minHistorySeconds", self.window_minutes * 60))
        self.min_notify_seconds = _parse_seconds(vs.get("minNotifyInterval", "2m"))

        # symbol -> deque of (timestamp_s, cumulative_volume)
        self._volume_history: dict[str, deque] = {}
        # symbol -> last notification timestamp
        self._last_notify: dict[str, float] = {}
        # symbol -> latest price from the ticker stream, used as webhook context.
        self._last_price: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public API (called from WS handler thread)
    # ------------------------------------------------------------------

    def on_volume_update(self, symbol: str, cumulative_volume: float, timestamp: float):
        with self._lock:
            if not self.enabled:
                return

            history = self._volume_history.get(symbol)
            if history is None:
                history = deque(maxlen=_MAX_SAMPLES)
                self._volume_history[symbol] = history

            history.append((timestamp, cumulative_volume))
            self._check_spike(symbol, timestamp)

    def on_price_update(self, symbol: str, price: float, timestamp: float):
        with self._lock:
            if not self.enabled:
                return
            self._last_price[symbol] = price

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check_spike(self, symbol: str, now: float):
        history = self._volume_history[symbol]
        if len(history) < 10:
            return
        if history[-1][0] - history[0][0] < self.min_history_seconds:
            return

        window_start = now - self.window_minutes * 60
        recent_cutoff = now - 60  # last 1 minute

        # Compute per-minute volume deltas from cumulative values
        # We need at least 2 data points in the recent window
        recent_deltas = []
        window_deltas = []

        items = list(history)
        for i in range(1, len(items)):
            t_prev, v_prev = items[i - 1]
            t_curr, v_curr = items[i]
            delta = v_curr - v_prev
            if delta < 0:
                # Volume counter reset (new 24h window) — skip
                continue
            dt = t_curr - t_prev
            if dt <= 0:
                continue

            if t_curr >= recent_cutoff:
                recent_deltas.append(delta)
            elif t_curr >= window_start:
                window_deltas.append(delta)

        if not recent_deltas or not window_deltas:
            return

        # Compare volume RATE (per-tick average) not raw sum
        recent_avg = sum(recent_deltas) / len(recent_deltas)
        window_avg = sum(window_deltas) / len(window_deltas)

        if window_avg <= 0:
            return

        ratio = recent_avg / window_avg

        if ratio < self.multiplier:
            return

        # Cooldown check
        last = self._last_notify.get(symbol, 0)
        if now - last < self.min_notify_seconds:
            return
        self._last_notify[symbol] = now

        severity = "HIGH" if ratio >= self.multiplier * 2 else "MEDIUM" if ratio >= self.multiplier * 1.5 else "LOW"

        self._emit(
            AnomalyEvent(
                symbol=symbol,
                event_type="volume_spike",
                severity=severity,
                data={
                    "price": round(self._last_price.get(symbol, 0.0), 8),
                    "ratio": round(ratio, 2),
                    "recent_avg": round(recent_avg, 2),
                    "window_avg": round(window_avg, 2),
                    "window_minutes": self.window_minutes,
                },
                timestamp=now,
            )
        )

    def update_config(self, config: dict):
        with self._lock:
            super().update_config(config)
            vs = config.get("volumeSpike", config)
            self.enabled = vs.get("enabled", True)
            self.multiplier = vs.get("multiplier", 3.0)
            self.window_minutes = vs.get("windowMinutes", 10)
            self.min_history_seconds = _parse_seconds(vs.get("minHistorySeconds", self.window_minutes * 60))
            self.min_notify_seconds = _parse_seconds(vs.get("minNotifyInterval", "2m"))


def _parse_seconds(value) -> float:
    """Parse a duration string like '2m', '30s', '1h' to seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower()
    if s.endswith("s"):
        return float(s[:-1])
    if s.endswith("m"):
        return float(s[:-1]) * 60
    if s.endswith("h"):
        return float(s[:-1]) * 3600
    return float(s)
