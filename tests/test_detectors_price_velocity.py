"""
Tests for kairos.detectors.price_velocity — PriceVelocityDetector.
"""

import pytest

from kairos.detectors.price_velocity import PriceVelocityDetector

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def detector():
    """Fresh detector with default config."""
    return PriceVelocityDetector({})


@pytest.fixture
def detector_custom():
    """Detector with custom config — short cooldown, custom windows."""
    return PriceVelocityDetector(
        {
            "priceVelocity": {
                "enabled": True,
                "windows": [
                    {"seconds": 10, "threshold": 0.3},
                    {"seconds": 30, "threshold": 0.8},
                ],
                "cooldownSeconds": 30,
            }
        }
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_default_config(self, detector):
        assert detector.enabled is True
        assert len(detector.windows) == 3
        assert detector.windows[0] == {"seconds": 30, "threshold": 0.5}
        assert detector.cooldown_s == 60
        assert detector._price_history == {}
        assert detector._last_notify == {}

    def test_custom_config(self, detector_custom):
        assert detector_custom.enabled is True
        assert len(detector_custom.windows) == 2
        assert detector_custom.windows[0] == {"seconds": 10, "threshold": 0.3}
        assert detector_custom.cooldown_s == 30

    def test_disabled_via_config(self):
        d = PriceVelocityDetector({"priceVelocity": {"enabled": False}})
        assert d.enabled is False

    def test_partial_config_merges_defaults(self):
        d = PriceVelocityDetector({"priceVelocity": {"cooldownSeconds": 120}})
        assert d.cooldown_s == 120
        assert d.enabled is True
        assert len(d.windows) == 3  # default windows preserved


# ---------------------------------------------------------------------------
# on_price_update – basic behaviour
# ---------------------------------------------------------------------------


class TestOnPriceUpdate:
    def test_too_few_ticks_no_emit(self, detector):
        events = []
        detector.on_event(events.append)

        for i in range(4):
            detector.on_price_update("BTC/USDT", 100.0, float(i))

        assert events == []

    def test_no_price_change_below_threshold(self, detector):
        events = []
        detector.on_event(events.append)

        now = 1000.0
        for i in range(10):
            detector.on_price_update("BTC/USDT", 100.0, now - 100 + i)

        assert events == []

    def test_positive_velocity_triggers_event(self, detector):
        events = []
        detector.on_event(events.append)

        now = 1000.0
        detector.on_price_update("BTC/USDT", 100.0, now - 30)
        detector.on_price_update("BTC/USDT", 100.1, now - 20)
        detector.on_price_update("BTC/USDT", 100.2, now - 10)
        detector.on_price_update("BTC/USDT", 100.3, now - 5)
        detector.on_price_update("BTC/USDT", 100.5, now)

        assert len(events) == 1
        ev = events[0]
        assert ev.symbol == "BTC/USDT"
        assert ev.event_type == "price_velocity"
        assert ev.severity == "LOW"
        assert ev.data["change_pct"] == 0.5
        assert ev.data["window_seconds"] == 30
        assert ev.data["price_from"] == 100.0
        assert ev.data["price_to"] == 100.5

    def test_negative_velocity_triggers_event(self, detector):
        events = []
        detector.on_event(events.append)

        now = 1000.0
        detector.on_price_update("ETH/USDT", 200.0, now - 30)
        detector.on_price_update("ETH/USDT", 199.9, now - 20)
        detector.on_price_update("ETH/USDT", 199.8, now - 10)
        detector.on_price_update("ETH/USDT", 199.7, now - 5)
        detector.on_price_update("ETH/USDT", 198.0, now)

        assert len(events) == 1
        ev = events[0]
        assert ev.symbol == "ETH/USDT"
        assert ev.data["change_pct"] == -1.0
        assert ev.data["price_from"] == 200.0
        assert ev.data["price_to"] == 198.0

    def test_emits_only_shortest_triggering_window(self, detector):
        """When 30s window triggers, break — do not also emit for 60s/120s."""
        events = []
        detector.on_event(events.append)

        now = 1000.0
        detector.on_price_update("BTC/USDT", 100.0, now - 120)
        detector.on_price_update("BTC/USDT", 100.0, now - 60)
        detector.on_price_update("BTC/USDT", 100.0, now - 30)
        detector.on_price_update("BTC/USDT", 100.0, now - 10)
        detector.on_price_update("BTC/USDT", 102.0, now)

        assert len(events) == 1
        assert events[0].data["window_seconds"] == 30


# ---------------------------------------------------------------------------
# Severity levels
# ---------------------------------------------------------------------------


class TestSeverity:
    def test_severity_low(self, detector):
        events = []
        detector.on_event(events.append)

        now = 1000.0
        detector.on_price_update("BTC/USDT", 100.0, now - 30)
        detector.on_price_update("BTC/USDT", 100.1, now - 10)
        detector.on_price_update("BTC/USDT", 100.2, now - 5)
        detector.on_price_update("BTC/USDT", 100.3, now - 2)
        detector.on_price_update("BTC/USDT", 100.5, now)
        assert events[0].severity == "LOW"

    def test_severity_medium(self, detector):
        events = []
        detector.on_event(events.append)

        now = 1000.0
        detector.on_price_update("BTC/USDT", 100.0, now - 30)
        detector.on_price_update("BTC/USDT", 100.2, now - 10)
        detector.on_price_update("BTC/USDT", 100.4, now - 5)
        detector.on_price_update("BTC/USDT", 100.6, now - 2)
        detector.on_price_update("BTC/USDT", 101.0, now)
        assert events[0].severity == "MEDIUM"

    def test_severity_high(self, detector):
        events = []
        detector.on_event(events.append)

        now = 1000.0
        detector.on_price_update("BTC/USDT", 100.0, now - 30)
        detector.on_price_update("BTC/USDT", 100.2, now - 10)
        detector.on_price_update("BTC/USDT", 100.5, now - 5)
        detector.on_price_update("BTC/USDT", 100.8, now - 2)
        detector.on_price_update("BTC/USDT", 101.5, now)
        assert events[0].severity == "HIGH"


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------


class TestCooldown:
    def test_cooldown_blocks_second_trigger(self, detector):
        events = []
        detector.on_event(events.append)

        now = 1000.0
        # First trigger — 30s window at 0.5% threshold
        detector.on_price_update("BTC/USDT", 100.0, now - 30)
        detector.on_price_update("BTC/USDT", 100.1, now - 10)
        detector.on_price_update("BTC/USDT", 100.2, now - 5)
        detector.on_price_update("BTC/USDT", 100.3, now - 2)
        detector.on_price_update("BTC/USDT", 100.5, now)
        assert len(events) == 1

        # Second trigger 30s later — MUST use same window (30s),
        # but need to ensure past_price at target_time for 30s window triggers
        # AND the 60s/120s windows do NOT also fire.
        #
        # Problem: the first batch left ticks at t=970 and t=980 in history,
        # which are within 60s of now2=1030. The 60s window target_time=970
        # would find past_price=100.0. If change >= 0.8%, it would fire on
        # the separate "BTC/USDT_60" cooldown key.
        #
        # Solution: add enough stale ticks so 60s window has no past_price.
        # Add a tick at t=950 (outside 60s window at now2=1030:
        # 1030-60=970, so t=950 < 970).
        # Then at now2=1030, 60s window target_time=970 — the most recent
        # tick at or before 970 is at 970 (from the new batch setup).
        # We need the 60s window to NOT trigger — make its change < 0.8%.
        #
        # Simpler: ensure the only tick <= 970 is at the same price as
        # the latest, so change ≈ 0 for 60s window.
        now2 = now + 30  # 1030
        # Place a tick exactly at 970 for 30s window reference
        detector.on_price_update("BTC/USDT", 101.0, now2 - 60)  # t=970
        detector.on_price_update("BTC/USDT", 101.0, now2 - 50)  # t=980
        detector.on_price_update("BTC/USDT", 101.1, now2 - 10)  # t=1020
        detector.on_price_update("BTC/USDT", 101.2, now2 - 5)  # t=1025
        # +0.6% from 101.0 → triggers 30s window (>0.5%)
        # 60s window: no tick <= 970 except t=970 with price 101.0,
        # but that's within 60s (970 is target, and t=970 <= 970 passes).
        # Change from 101.0 to 101.6 in 60s window = 0.59% < 0.8% → SKIP.
        detector.on_price_update("BTC/USDT", 101.6, now2)

        assert len(events) == 1  # still only one — cooldown blocked

    def test_cooldown_expires_allows_new_event(self, detector):
        events = []
        detector.on_event(events.append)

        now = 1000.0
        detector.on_price_update("BTC/USDT", 100.0, now - 30)
        detector.on_price_update("BTC/USDT", 100.1, now - 10)
        detector.on_price_update("BTC/USDT", 100.2, now - 5)
        detector.on_price_update("BTC/USDT", 100.3, now - 2)
        detector.on_price_update("BTC/USDT", 100.5, now)
        assert len(events) == 1

        # After cooldown (60s later). Keep prices near 100.5 so the
        # 60s window does NOT fire on the old 100.0 tick in history.
        now2 = now + 61
        detector.on_price_update("BTC/USDT", 100.5, now2 - 30)
        detector.on_price_update("BTC/USDT", 100.6, now2 - 10)
        detector.on_price_update("BTC/USDT", 100.7, now2 - 5)
        detector.on_price_update("BTC/USDT", 100.8, now2 - 2)
        detector.on_price_update("BTC/USDT", 101.01, now2)  # ~0.507% > 0.5%

        assert len(events) == 2

    def test_cooldown_per_window_independent(self, detector):
        """Different windows have independent cooldowns."""
        events = []
        detector.on_event(events.append)

        now = 1000.0
        # Set up so 30s window does NOT trigger (price at t=970 is 100.5,
        # making 30s change ~0.5% which is right at the 0.5% boundary).
        # 60s window sees t=940 price=100.0 with change 1.0% >= 0.8% → fires.
        detector.on_price_update("BTC/USDT", 100.0, now - 60)
        detector.on_price_update("BTC/USDT", 100.5, now - 30)
        detector.on_price_update("BTC/USDT", 100.6, now - 10)
        detector.on_price_update("BTC/USDT", 100.7, now - 5)
        detector.on_price_update("BTC/USDT", 101.0, now)  # 1.0% at 60s
        assert len(events) == 1
        assert events[0].data["window_seconds"] == 60

        # Now trigger 30s window — independent cooldown key
        now2 = now + 10  # 1010
        detector.on_price_update("BTC/USDT", 100.8, now2 - 30)  # t=980
        detector.on_price_update("BTC/USDT", 100.9, now2 - 10)
        detector.on_price_update("BTC/USDT", 101.0, now2 - 5)
        detector.on_price_update("BTC/USDT", 101.1, now2 - 2)
        detector.on_price_update("BTC/USDT", 101.5, now2)  # ~0.69% > 0.5%

        assert len(events) == 2
        assert events[1].data["window_seconds"] == 30


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_zero_past_price_skipped(self, detector):
        """past_price <= 0 should be skipped — no division by zero."""
        events = []
        detector.on_event(events.append)

        now = 1000.0
        detector.on_price_update("BTC/USDT", 0.0, now - 30)
        detector.on_price_update("BTC/USDT", 0.0, now - 20)
        detector.on_price_update("BTC/USDT", 0.1, now - 10)
        detector.on_price_update("BTC/USDT", 0.2, now - 5)
        detector.on_price_update("BTC/USDT", 0.3, now)
        # No crash — past_price=0 causes window to be skipped

    def test_no_past_price_in_window_no_emit(self, detector):
        """If no tick is <= target_time, skip that window."""
        events = []
        detector.on_event(events.append)

        now = 1000.0
        # All ticks are recent — no tick at or before now-30 for 30s window
        detector.on_price_update("BTC/USDT", 100.0, now - 5)
        detector.on_price_update("BTC/USDT", 100.1, now - 4)
        detector.on_price_update("BTC/USDT", 100.2, now - 3)
        detector.on_price_update("BTC/USDT", 100.3, now - 2)
        detector.on_price_update("BTC/USDT", 100.5, now - 1)
        detector.on_price_update("BTC/USDT", 101.0, now)

        # No event — no past_price for any window
        assert events == []

    def test_multiple_symbols_independent(self, detector):
        events = []
        detector.on_event(events.append)

        now = 1000.0
        # BTC — 0.5% change triggers 30s window
        detector.on_price_update("BTC/USDT", 100.0, now - 30)
        detector.on_price_update("BTC/USDT", 100.1, now - 10)
        detector.on_price_update("BTC/USDT", 100.2, now - 5)
        detector.on_price_update("BTC/USDT", 100.3, now - 2)
        detector.on_price_update("BTC/USDT", 100.5, now)

        # ETH — 0.5% change (200 → 201) triggers 30s window
        detector.on_price_update("ETH/USDT", 200.0, now - 30)
        detector.on_price_update("ETH/USDT", 200.1, now - 10)
        detector.on_price_update("ETH/USDT", 200.2, now - 5)
        detector.on_price_update("ETH/USDT", 200.3, now - 2)
        detector.on_price_update("ETH/USDT", 201.0, now)

        assert len(events) == 2
        symbols = {ev.symbol for ev in events}
        assert symbols == {"BTC/USDT", "ETH/USDT"}

    def test_disabled_detector_no_emit(self):
        d = PriceVelocityDetector({"priceVelocity": {"enabled": False}})
        events = []
        d.on_event(events.append)

        now = 1000.0
        d.on_price_update("BTC/USDT", 100.0, now - 30)
        d.on_price_update("BTC/USDT", 100.1, now - 10)
        d.on_price_update("BTC/USDT", 100.2, now - 5)
        d.on_price_update("BTC/USDT", 100.3, now - 2)
        d.on_price_update("BTC/USDT", 100.5, now)
        assert events == []

    def test_custom_window_triggers(self, detector_custom):
        events = []
        detector_custom.on_event(events.append)

        now = 1000.0
        # 10s window with 0.3% threshold — use 0.35% to avoid float edge
        detector_custom.on_price_update("BTC/USDT", 100.0, now - 10)
        detector_custom.on_price_update("BTC/USDT", 100.1, now - 5)
        detector_custom.on_price_update("BTC/USDT", 100.2, now - 3)
        detector_custom.on_price_update("BTC/USDT", 100.25, now - 1)
        detector_custom.on_price_update("BTC/USDT", 100.35, now)  # +0.35%

        assert len(events) == 1
        assert events[0].data["window_seconds"] == 10


# ---------------------------------------------------------------------------
# update_config
# ---------------------------------------------------------------------------


class TestUpdateConfig:
    def test_update_config_changes_settings(self, detector):
        detector.update_config({"priceVelocity": {"enabled": False, "cooldownSeconds": 120}})
        assert detector.enabled is False
        assert detector.cooldown_s == 120

    def test_update_config_empty_noop(self, detector):
        detector.update_config({})
        assert detector.enabled is True


# ---------------------------------------------------------------------------
# Callback errors
# ---------------------------------------------------------------------------


class TestCallbackErrors:
    def test_one_callback_error_does_not_block_others(self, detector):
        events_a = []
        events_b = []

        def bad_callback(event):
            raise RuntimeError("boom")

        detector.on_event(bad_callback)
        detector.on_event(events_a.append)
        detector.on_event(events_b.append)

        now = 1000.0
        detector.on_price_update("BTC/USDT", 100.0, now - 30)
        detector.on_price_update("BTC/USDT", 100.1, now - 10)
        detector.on_price_update("BTC/USDT", 100.2, now - 5)
        detector.on_price_update("BTC/USDT", 100.3, now - 2)
        detector.on_price_update("BTC/USDT", 100.5, now)

        assert len(events_a) == 1
        assert len(events_b) == 1
