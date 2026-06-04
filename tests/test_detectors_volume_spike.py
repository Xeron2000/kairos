"""
Tests for kairos.detectors.volume_spike — VolumeSpikeDetector and _parse_seconds.
"""

import pytest

from kairos.detectors.volume_spike import VolumeSpikeDetector, _parse_seconds

# ---------------------------------------------------------------------------
# _parse_seconds
# ---------------------------------------------------------------------------


class TestParseSeconds:
    def test_int(self):
        assert _parse_seconds(120) == 120.0

    def test_float(self):
        assert _parse_seconds(45.5) == 45.5

    def test_seconds_suffix(self):
        assert _parse_seconds("30s") == 30.0

    def test_minutes_suffix(self):
        assert _parse_seconds("2m") == 120.0

    def test_hours_suffix(self):
        assert _parse_seconds("1h") == 3600.0

    def test_decimal_minutes(self):
        assert _parse_seconds("1.5m") == 90.0

    def test_whitespace_trimmed(self):
        assert _parse_seconds("  5m  ") == 300.0

    def test_case_insensitive(self):
        assert _parse_seconds("2M") == 120.0
        assert _parse_seconds("1H") == 3600.0

    def test_no_suffix_treated_as_float(self):
        assert _parse_seconds("90") == 90.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def detector():
    """Fresh VolumeSpikeDetector with default config."""
    return VolumeSpikeDetector({})


@pytest.fixture
def detector_custom():
    """Detector with custom config — low multiplier, short window."""
    return VolumeSpikeDetector(
        {
            "volumeSpike": {
                "enabled": True,
                "multiplier": 2.0,
                "windowMinutes": 5,
                "minNotifyInterval": "30s",
            }
        }
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _feed_window_history(detector, symbol, base_time, num_ticks=10):
    """Feed steady low-volume ticks in the window period.

    Ticks spread from base_time-300 to base_time-120, each with delta=20.
    At end, cumulative volume = 1000 + (num_ticks-1)*20.
    """
    for i in range(num_ticks):
        t = base_time - 300 + i * 20  # 700, 720, ..., 880
        detector.on_volume_update(symbol, 1000.0 + i * 20, t)


def _last_cumulative(num_ticks=10):
    """Return the last cumulative volume after _feed_window_history."""
    return 1000.0 + (num_ticks - 1) * 20


def _feed_spike(detector, symbol, base_time, spike_delta):
    """Feed a single large recent tick at base_time.

    Must call _feed_window_history first so deltas are established.
    """
    cum = _last_cumulative() + spike_delta
    detector.on_volume_update(symbol, cum, base_time)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_default_config(self, detector):
        assert detector.enabled is True
        assert detector.multiplier == 3.0
        assert detector.window_minutes == 10
        assert detector.min_notify_seconds == 120  # 2m
        assert detector._volume_history == {}
        assert detector._last_notify == {}

    def test_custom_config(self, detector_custom):
        assert detector_custom.enabled is True
        assert detector_custom.multiplier == 2.0
        assert detector_custom.window_minutes == 5
        assert detector_custom.min_notify_seconds == 30

    def test_disabled_via_config(self):
        d = VolumeSpikeDetector({"volumeSpike": {"enabled": False}})
        assert d.enabled is False

    def test_partial_config_merges_defaults(self):
        d = VolumeSpikeDetector({"volumeSpike": {"multiplier": 5.0}})
        assert d.multiplier == 5.0
        assert d.window_minutes == 10  # default
        assert d.min_notify_seconds == 120  # default


# ---------------------------------------------------------------------------
# on_volume_update – basic behaviour
# ---------------------------------------------------------------------------


class TestOnVolumeUpdate:
    def test_too_few_ticks_no_emit(self, detector):
        events = []
        detector.on_event(events.append)
        for i in range(9):
            detector.on_volume_update("BTC/USDT", float(i * 100), float(i))
        assert events == []

    def test_no_spike_below_multiplier(self, detector):
        """Steady volume — ratio below default multiplier of 3.0."""
        events = []
        detector.on_event(events.append)

        base_time = 1000.0
        _feed_window_history(detector, "BTC/USDT", base_time)
        # spike_delta=50 → window_avg≈20, recent includes 2 late window
        # ticks + spike → (40+50)/3=30, 30/20=1.5 < 3.0 → no spike
        _feed_spike(detector, "BTC/USDT", base_time, 50)

        assert events == []

    def test_spike_detected(self, detector_custom):
        """Large recent delta exceeds multiplier."""
        events = []
        detector_custom.on_event(events.append)

        base_time = 1000.0
        _feed_window_history(detector_custom, "BTC/USDT", base_time)
        # spike_delta=90 → with 2 late window deltas of 20 each:
        # recent_avg = (20+20+90)/3 = 43.33, window_avg ≈ 20
        # ratio ≈ 2.17 > 2.0 → spike
        _feed_spike(detector_custom, "BTC/USDT", base_time, 90)

        assert len(events) == 1
        ev = events[0]
        assert ev.symbol == "BTC/USDT"
        assert ev.event_type == "volume_spike"

    def test_event_data_fields(self, detector_custom):
        events = []
        detector_custom.on_event(events.append)

        base_time = 1000.0
        _feed_window_history(detector_custom, "BTC/USDT", base_time)
        _feed_spike(detector_custom, "BTC/USDT", base_time, 90)

        ev = events[0]
        assert "ratio" in ev.data
        assert "recent_avg" in ev.data
        assert "window_avg" in ev.data
        assert ev.data["window_minutes"] == 5
        assert ev.data["ratio"] > detector_custom.multiplier


# ---------------------------------------------------------------------------
# Severity levels
# ---------------------------------------------------------------------------


class TestSeverity:
    def test_severity_low(self, detector_custom):
        events = []
        detector_custom.on_event(events.append)

        base_time = 1000.0
        _feed_window_history(detector_custom, "BTC/USDT", base_time)
        # spike_delta=50 → recent_avg=50, window_avg=20, ratio=2.5 → LOW
        _feed_spike(detector_custom, "BTC/USDT", base_time, 50)

        assert len(events) == 1
        assert events[0].severity == "LOW"

    def test_severity_medium(self, detector_custom):
        events = []
        detector_custom.on_event(events.append)

        base_time = 1000.0
        _feed_window_history(detector_custom, "BTC/USDT", base_time)
        # spike_delta=70 → recent_avg=70, window_avg=20, ratio=3.5 → MEDIUM
        _feed_spike(detector_custom, "BTC/USDT", base_time, 70)

        assert len(events) == 1
        assert events[0].severity == "MEDIUM"

    def test_severity_high(self, detector_custom):
        events = []
        detector_custom.on_event(events.append)

        base_time = 1000.0
        _feed_window_history(detector_custom, "BTC/USDT", base_time)
        # Need ratio >= 4.0 for HIGH
        # recent_avg = (40 + X) / 3 >= 80 → X >= 200
        _feed_spike(detector_custom, "BTC/USDT", base_time, 200)

        assert len(events) == 1
        assert events[0].severity == "HIGH"


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------


class TestCooldown:
    def test_cooldown_blocks_second_trigger(self, detector_custom):
        events = []
        detector_custom.on_event(events.append)

        base_time = 1000.0
        _feed_window_history(detector_custom, "BTC/USDT", base_time)
        _feed_spike(detector_custom, "BTC/USDT", base_time, 90)
        assert len(events) == 1

        # Second spike 10s later — within 30s cooldown
        base2 = base_time + 10
        _feed_window_history(detector_custom, "BTC/USDT", base2)
        _feed_spike(detector_custom, "BTC/USDT", base2, 90)
        assert len(events) == 1  # blocked

    def test_cooldown_expires_allows_new_event(self, detector_custom):
        events = []
        detector_custom.on_event(events.append)

        base_time = 1000.0
        _feed_window_history(detector_custom, "BTC/USDT", base_time)
        _feed_spike(detector_custom, "BTC/USDT", base_time, 90)
        assert len(events) == 1

        # After cooldown expires (31s later)
        base2 = base_time + 31
        _feed_window_history(detector_custom, "BTC/USDT", base2)
        _feed_spike(detector_custom, "BTC/USDT", base2, 90)
        assert len(events) == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_negative_delta_skipped(self, detector_custom):
        """Volume counter reset (negative delta) should be ignored."""
        events = []
        detector_custom.on_event(events.append)

        base_time = 1000.0
        # Feed window ticks with a reset in the middle
        _feed_window_history(detector_custom, "BTC/USDT", base_time)
        # Now inject a tick that resets cumulative volume
        _feed_spike(detector_custom, "BTC/USDT", base_time, 90)

        # Should still detect the spike (negative deltas just skipped)
        assert len(events) == 1

    def test_zero_dt_skipped(self, detector_custom):
        """Consecutive ticks with same timestamp (dt=0) — no crash."""
        events = []
        detector_custom.on_event(events.append)

        base_time = 1000.0
        _feed_window_history(detector_custom, "BTC/USDT", base_time)
        # Duplicate timestamp
        last_cum = _last_cumulative()
        detector_custom.on_volume_update("BTC/USDT", last_cum + 50, base_time)
        detector_custom.on_volume_update("BTC/USDT", last_cum + 90, base_time)
        # No crash — dt=0 pairs are skipped

    def test_window_avg_zero_no_emit(self, detector_custom):
        """When all window deltas are zero, skip division."""
        events = []
        detector_custom.on_event(events.append)

        base_time = 1000.0
        # Feed ticks with identical cumulative volume (deltas=0)
        for i in range(10):
            t = base_time - 300 + i * 20
            detector_custom.on_volume_update("BTC/USDT", 1000.0, t)
        # Recent spike
        detector_custom.on_volume_update("BTC/USDT", 2000.0, base_time)

        # window_avg = 0 → ratio computation skipped
        assert events == []

    def test_no_window_deltas_no_emit(self, detector_custom):
        """All ticks are in the recent period — no window deltas."""
        events = []
        detector_custom.on_event(events.append)

        base_time = 1000.0
        # All ticks within last 60s
        for i in range(12):
            t = base_time - 50 + i * 4
            detector_custom.on_volume_update("BTC/USDT", float((i + 1) * 1000), t)

        assert events == []

    def test_disabled_detector_no_emit(self):
        d = VolumeSpikeDetector({"volumeSpike": {"enabled": False}})
        events = []
        d.on_event(events.append)

        base_time = 1000.0
        for i in range(15):
            t = base_time - 720 + i * 50
            d.on_volume_update("BTC/USDT", float((i + 1) * 2000), t)
        assert events == []

    def test_multiple_symbols_independent(self, detector_custom):
        events = []
        detector_custom.on_event(events.append)

        base_time = 1000.0
        _feed_window_history(detector_custom, "BTC/USDT", base_time)
        _feed_spike(detector_custom, "BTC/USDT", base_time, 90)

        _feed_window_history(detector_custom, "ETH/USDT", base_time)
        _feed_spike(detector_custom, "ETH/USDT", base_time, 90)

        assert len(events) == 2
        symbols = {ev.symbol for ev in events}
        assert symbols == {"BTC/USDT", "ETH/USDT"}


# ---------------------------------------------------------------------------
# update_config
# ---------------------------------------------------------------------------


class TestUpdateConfig:
    def test_update_config_changes_settings(self, detector):
        detector.update_config(
            {
                "volumeSpike": {
                    "enabled": False,
                    "multiplier": 5.0,
                    "windowMinutes": 20,
                    "minNotifyInterval": "5m",
                }
            }
        )
        assert detector.enabled is False
        assert detector.multiplier == 5.0
        assert detector.window_minutes == 20
        assert detector.min_notify_seconds == 300

    def test_update_config_empty_noop(self, detector):
        detector.update_config({})
        assert detector.enabled is True
        assert detector.multiplier == 3.0


# ---------------------------------------------------------------------------
# Callback errors
# ---------------------------------------------------------------------------


class TestCallbackErrors:
    def test_one_callback_error_does_not_block_others(self, detector_custom):
        events_a = []
        events_b = []

        def bad_callback(event):
            raise RuntimeError("boom")

        detector_custom.on_event(bad_callback)
        detector_custom.on_event(events_a.append)
        detector_custom.on_event(events_b.append)

        base_time = 1000.0
        _feed_window_history(detector_custom, "BTC/USDT", base_time)
        _feed_spike(detector_custom, "BTC/USDT", base_time, 90)

        assert len(events_a) == 1
        assert len(events_b) == 1
