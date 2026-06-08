"""Futures metrics detector for open-interest and funding-rate anomalies."""

from .base import AnomalyEvent, BaseDetector
from .volume_spike import _parse_seconds


class FuturesMetricsDetector(BaseDetector):
    """Detects open-interest and funding-rate anomalies from periodic REST polls."""

    def __init__(self, config: dict):
        super().__init__(config)
        fm = config.get("futuresMetrics", config)
        oi = fm.get("openInterest", {})
        funding = fm.get("fundingRate", {})

        self.enabled = fm.get("enabled", True)
        self.open_interest_enabled = oi.get("enabled", True)
        self.oi_min_change_pct = float(oi.get("minChangePct", 5.0))
        self.oi_min_notify_seconds = _parse_seconds(oi.get("minNotifyInterval", "30m"))

        self.funding_enabled = funding.get("enabled", True)
        self.funding_abs_threshold = float(funding.get("absRateThreshold", 0.0005))
        self.funding_min_change_abs = float(funding.get("minChangeAbs", 0.0003))
        self.funding_min_notify_seconds = _parse_seconds(funding.get("minNotifyInterval", "30m"))

        self._last_open_interest: dict[str, float] = {}
        self._last_funding_rate: dict[str, float] = {}
        self._last_notify: dict[str, float] = {}

    def on_metrics_update(
        self,
        symbol: str,
        timestamp: float,
        price: float = 0.0,
        open_interest: float | None = None,
        funding_rate: float | None = None,
    ) -> None:
        """Process a sampled futures metrics snapshot."""
        with self._lock:
            if not self.enabled:
                return
            self._check_open_interest(symbol, timestamp, price, open_interest)
            self._check_funding_rate(symbol, timestamp, price, funding_rate)

    def _check_open_interest(
        self,
        symbol: str,
        now: float,
        price: float,
        open_interest: float | None,
    ) -> None:
        if not self.open_interest_enabled or open_interest is None or open_interest <= 0:
            return

        previous = self._last_open_interest.get(symbol)
        self._last_open_interest[symbol] = open_interest
        if previous is None or previous <= 0:
            return

        change_pct = ((open_interest - previous) / previous) * 100
        if abs(change_pct) < self.oi_min_change_pct:
            return

        key = f"{symbol}_open_interest_change"
        if not self._can_notify(key, now, self.oi_min_notify_seconds):
            return

        abs_change = abs(change_pct)
        severity = "HIGH" if abs_change >= self.oi_min_change_pct * 2 else "MEDIUM"
        self._emit(
            AnomalyEvent(
                symbol=symbol,
                event_type="open_interest_change",
                severity=severity,
                data={
                    "price": round(price, 8),
                    "open_interest": round(open_interest, 8),
                    "previous_open_interest": round(previous, 8),
                    "change_pct": round(change_pct, 2),
                    "threshold_pct": self.oi_min_change_pct,
                },
                timestamp=now,
            )
        )

    def _check_funding_rate(
        self,
        symbol: str,
        now: float,
        price: float,
        funding_rate: float | None,
    ) -> None:
        if not self.funding_enabled or funding_rate is None:
            return

        previous = self._last_funding_rate.get(symbol)
        self._last_funding_rate[symbol] = funding_rate
        change_abs = abs(funding_rate - previous) if previous is not None else 0.0
        is_extreme = abs(funding_rate) >= self.funding_abs_threshold
        is_shift = previous is not None and change_abs >= self.funding_min_change_abs
        if not (is_extreme or is_shift):
            return

        key = f"{symbol}_funding_rate_anomaly"
        if not self._can_notify(key, now, self.funding_min_notify_seconds):
            return

        reason = []
        if is_extreme:
            reason.append("extreme")
        if is_shift:
            reason.append("shift")

        severity = "HIGH" if abs(funding_rate) >= self.funding_abs_threshold * 2 else "MEDIUM"
        self._emit(
            AnomalyEvent(
                symbol=symbol,
                event_type="funding_rate_anomaly",
                severity=severity,
                data={
                    "price": round(price, 8),
                    "funding_rate": funding_rate,
                    "previous_funding_rate": previous,
                    "change_abs": change_abs,
                    "abs_threshold": self.funding_abs_threshold,
                    "change_threshold": self.funding_min_change_abs,
                    "reason": "+".join(reason),
                },
                timestamp=now,
            )
        )

    def _can_notify(self, key: str, now: float, cooldown_seconds: float) -> bool:
        last = self._last_notify.get(key)
        if last is None:
            self._last_notify[key] = now
            return True
        if now - last < cooldown_seconds:
            return False
        self._last_notify[key] = now
        return True

    def update_config(self, config: dict):
        with self._lock:
            super().update_config(config)
            updated = FuturesMetricsDetector(config)
            self.enabled = updated.enabled
            self.open_interest_enabled = updated.open_interest_enabled
            self.oi_min_change_pct = updated.oi_min_change_pct
            self.oi_min_notify_seconds = updated.oi_min_notify_seconds
            self.funding_enabled = updated.funding_enabled
            self.funding_abs_threshold = updated.funding_abs_threshold
            self.funding_min_change_abs = updated.funding_min_change_abs
            self.funding_min_notify_seconds = updated.funding_min_notify_seconds
