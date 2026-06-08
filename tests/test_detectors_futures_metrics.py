"""Tests for futures metrics anomaly detection."""

from kairos.detectors.futures_metrics import FuturesMetricsDetector


def _make_detector(**overrides):
    config = {
        "futuresMetrics": {
            "enabled": True,
            "openInterest": {
                "enabled": True,
                "minChangePct": 5.0,
                "minNotifyInterval": "0s",
            },
            "fundingRate": {
                "enabled": True,
                "absRateThreshold": 0.0005,
                "minChangeAbs": 0.0003,
                "minNotifyInterval": "0s",
            },
        }
    }
    for section, values in overrides.items():
        config["futuresMetrics"].setdefault(section, {}).update(values)
    return FuturesMetricsDetector(config)


def test_open_interest_change_emits_after_baseline():
    detector = _make_detector(fundingRate={"enabled": False})
    events = []
    detector.on_event(events.append)

    detector.on_metrics_update("BTC/USDT:USDT", 1000.0, price=65000.0, open_interest=1000.0)
    detector.on_metrics_update("BTC/USDT:USDT", 1060.0, price=65100.0, open_interest=1060.0)

    assert len(events) == 1
    event = events[0]
    assert event.event_type == "open_interest_change"
    assert event.severity == "MEDIUM"
    assert event.data["price"] == 65100.0
    assert event.data["change_pct"] == 6.0
    assert event.data["previous_open_interest"] == 1000.0


def test_open_interest_change_uses_absolute_change_for_short_side():
    detector = _make_detector(fundingRate={"enabled": False})
    events = []
    detector.on_event(events.append)

    detector.on_metrics_update("ETH/USDT:USDT", 1000.0, price=3000.0, open_interest=1000.0)
    detector.on_metrics_update("ETH/USDT:USDT", 1060.0, price=2950.0, open_interest=900.0)

    assert len(events) == 1
    assert events[0].severity == "HIGH"
    assert events[0].data["change_pct"] == -10.0


def test_open_interest_first_sample_only_sets_baseline():
    detector = _make_detector(fundingRate={"enabled": False})
    events = []
    detector.on_event(events.append)

    detector.on_metrics_update("SOL/USDT:USDT", 1000.0, price=120.0, open_interest=2000.0)

    assert events == []


def test_funding_rate_extreme_emits_on_first_sample():
    detector = _make_detector(openInterest={"enabled": False})
    events = []
    detector.on_event(events.append)

    detector.on_metrics_update("BTC/USDT:USDT", 1000.0, price=65000.0, funding_rate=0.0007)

    assert len(events) == 1
    event = events[0]
    assert event.event_type == "funding_rate_anomaly"
    assert event.severity == "MEDIUM"
    assert event.data["funding_rate"] == 0.0007
    assert event.data["reason"] == "extreme"


def test_funding_rate_shift_emits_even_when_absolute_rate_is_below_extreme_threshold():
    detector = _make_detector(openInterest={"enabled": False})
    events = []
    detector.on_event(events.append)

    detector.on_metrics_update("ETH/USDT:USDT", 1000.0, price=3000.0, funding_rate=0.0001)
    detector.on_metrics_update("ETH/USDT:USDT", 1060.0, price=3020.0, funding_rate=0.0004)

    assert len(events) == 1
    assert events[0].data["funding_rate"] == 0.0004
    assert round(events[0].data["change_abs"], 6) == 0.0003
    assert events[0].data["reason"] == "shift"


def test_funding_rate_cooldown_suppresses_repeats():
    detector = FuturesMetricsDetector(
        {
            "futuresMetrics": {
                "openInterest": {"enabled": False},
                "fundingRate": {
                    "enabled": True,
                    "absRateThreshold": 0.0005,
                    "minChangeAbs": 0.0003,
                    "minNotifyInterval": "30m",
                },
            }
        }
    )
    events = []
    detector.on_event(events.append)

    detector.on_metrics_update("BTC/USDT:USDT", 1000.0, price=65000.0, funding_rate=0.0007)
    detector.on_metrics_update("BTC/USDT:USDT", 1100.0, price=65100.0, funding_rate=0.0010)

    assert len(events) == 1


def test_flattened_config_is_supported():
    detector = FuturesMetricsDetector(
        {
            "enabled": True,
            "openInterest": {
                "enabled": True,
                "minChangePct": 4.0,
                "minNotifyInterval": "0s",
            },
            "fundingRate": {"enabled": False},
        }
    )
    events = []
    detector.on_event(events.append)

    detector.on_metrics_update("XRP/USDT:USDT", 1000.0, price=0.5, open_interest=100.0)
    detector.on_metrics_update("XRP/USDT:USDT", 1060.0, price=0.51, open_interest=104.1)

    assert len(events) == 1
    assert events[0].data["threshold_pct"] == 4.0
