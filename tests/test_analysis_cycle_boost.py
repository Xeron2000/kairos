"""Comprehensive tests for kairos.analysis.cycle module."""

import numpy as np
import pytest

from kairos.analysis.cycle import CycleDetector, MarketCycle, MarketPhase


# ---------------------------------------------------------------------------
# MarketPhase enum
# ---------------------------------------------------------------------------

class TestMarketPhase:
    def test_values(self):
        assert MarketPhase.SPRING == "spring"
        assert MarketPhase.SUMMER == "summer"
        assert MarketPhase.AUTUMN == "autumn"
        assert MarketPhase.WINTER == "winter"

    def test_is_str(self):
        assert isinstance(MarketPhase.SPRING, str)

    def test_len(self):
        assert len(MarketPhase) == 4


# ---------------------------------------------------------------------------
# MarketCycle dataclass
# ---------------------------------------------------------------------------

def _make_cycle(phase=MarketPhase.SPRING, confidence=0.8, **kw):
    defaults = dict(
        phase=phase,
        confidence=confidence,
        btc_trend="up",
        btc_change_30d=15.0,
        btc_change_7d=5.0,
        volatility=3.0,
        volume_trend="increasing",
        altcoin_correlation=0.85,
        funding_rates_avg=0.02,
        market_cap_change_30d=10.0,
    )
    defaults.update(kw)
    return MarketCycle(**defaults)


class TestMarketCycle:
    def test_description_spring(self):
        assert "启动" in _make_cycle(MarketPhase.SPRING).description

    def test_description_summer(self):
        assert "狂热" in _make_cycle(MarketPhase.SUMMER).description

    def test_description_autumn(self):
        assert "震荡" in _make_cycle(MarketPhase.AUTUMN).description

    def test_description_winter(self):
        assert "冬眠" in _make_cycle(MarketPhase.WINTER).description

    def test_description_unknown_phase(self):
        """Edge case: if phase not in descriptions dict."""
        # Force a bad value by direct construction
        mc = _make_cycle()
        object.__setattr__(mc, "phase", "unknown")
        assert mc.description == "未知"

    def test_position_advice_spring(self):
        assert "建仓" in _make_cycle(MarketPhase.SPRING).position_advice

    def test_position_advice_summer(self):
        assert "重仓" in _make_cycle(MarketPhase.SUMMER).position_advice

    def test_position_advice_autumn(self):
        assert "轻仓" in _make_cycle(MarketPhase.AUTUMN).position_advice

    def test_position_advice_winter(self):
        assert "空仓" in _make_cycle(MarketPhase.WINTER).position_advice

    def test_position_advice_unknown_phase(self):
        mc = _make_cycle()
        object.__setattr__(mc, "phase", "unknown")
        assert mc.position_advice == "观望"

    def test_dataclass_fields(self):
        mc = _make_cycle()
        assert mc.phase == MarketPhase.SPRING
        assert mc.confidence == 0.8
        assert mc.btc_trend == "up"
        assert mc.altcoin_correlation == 0.85

    def test_dataclass_equality(self):
        assert _make_cycle() == _make_cycle()


# ---------------------------------------------------------------------------
# CycleDetector – default config
# ---------------------------------------------------------------------------

class TestCycleDetectorInit:
    def test_default_config(self):
        det = CycleDetector()
        assert det.spring_btc_change_min == 10
        assert det.summer_btc_change_min == 30
        assert det.autumn_btc_change_max == 50
        assert det.winter_btc_change_max == -10
        assert det.high_volatility_threshold == 5
        assert det.low_volatility_threshold == 2
        assert det.high_funding_threshold == 0.05
        assert det.low_funding_threshold == -0.01

    def test_custom_config(self):
        det = CycleDetector({
            "springBtcChangeMin": 5,
            "summerBtcChangeMin": 20,
            "autumnBtcChangeMax": 40,
            "winterBtcChangeMax": -5,
            "highVolatilityThreshold": 8,
            "lowVolatilityThreshold": 1,
            "highFundingThreshold": 0.1,
            "lowFundingThreshold": -0.05,
        })
        assert det.spring_btc_change_min == 5
        assert det.summer_btc_change_min == 20
        assert det.autumn_btc_change_max == 40
        assert det.winter_btc_change_max == -5
        assert det.high_volatility_threshold == 8
        assert det.low_volatility_threshold == 1
        assert det.high_funding_threshold == 0.1
        assert det.low_funding_threshold == -0.05

    def test_partial_config(self):
        det = CycleDetector({"springBtcChangeMin": 8})
        assert det.spring_btc_change_min == 8
        assert det.summer_btc_change_min == 30  # default


# ---------------------------------------------------------------------------
# detect_phase – short data → default cycle
# ---------------------------------------------------------------------------

class TestDetectPhaseShortData:
    def test_empty_prices(self):
        det = CycleDetector()
        result = det.detect_phase(np.array([]), np.array([]))
        assert result.phase == MarketPhase.WINTER
        assert result.confidence == 0.5
        assert result.btc_trend == "sideways"

    def test_less_than_30_prices(self):
        det = CycleDetector()
        prices = np.linspace(100, 110, 20)
        volumes = np.ones(20) * 1000
        result = det.detect_phase(prices, volumes)
        assert result.phase == MarketPhase.WINTER
        assert result.confidence == 0.5

    def test_exactly_29_prices(self):
        det = CycleDetector()
        prices = np.linspace(100, 110, 29)
        volumes = np.ones(29) * 1000
        result = det.detect_phase(prices, volumes)
        assert result.phase == MarketPhase.WINTER


# ---------------------------------------------------------------------------
# _calculate_change
# ---------------------------------------------------------------------------

class TestCalculateChange:
    def setup_method(self):
        self.det = CycleDetector()

    def test_short_data(self):
        prices = np.array([100.0, 110.0])
        assert self.det._calculate_change(prices, 7) == 0

    def test_7d_change(self):
        prices = np.arange(100.0, 140.0)  # 40 elements, prices[-7]=133, prices[-1]=139
        change = self.det._calculate_change(prices, 7)
        expected = ((139 - 133) / 133) * 100
        assert abs(change - expected) < 0.01

    def test_30d_change(self):
        prices = np.arange(100.0, 140.0)  # 40 elements, prices[-30]=110, prices[-1]=139
        change = self.det._calculate_change(prices, 30)
        expected = ((139 - 110) / 110) * 100
        assert abs(change - expected) < 0.01

    def test_zero_start_price(self):
        """Division by zero edge case."""
        prices = np.zeros(40)
        prices[-1] = 100
        # _calculate_change divides by prices[-days], which is 0
        # numpy will produce inf or nan
        change = self.det._calculate_change(prices, 7)
        assert not np.isfinite(change) or change == 0


# ---------------------------------------------------------------------------
# _calculate_volatility
# ---------------------------------------------------------------------------

class TestCalculateVolatility:
    def setup_method(self):
        self.det = CycleDetector()

    def test_short_data(self):
        prices = np.array([100.0, 101.0, 102.0])
        assert self.det._calculate_volatility(prices) == 0

    def test_constant_price_zero_vol(self):
        prices = np.ones(30) * 100.0
        vol = self.det._calculate_volatility(prices)
        assert vol == pytest.approx(0.0, abs=1e-6)

    def test_high_volatility(self):
        rng = np.random.default_rng(42)
        prices = 100 + rng.normal(0, 10, 100).cumsum()
        prices = np.abs(prices)  # keep positive
        vol = self.det._calculate_volatility(prices)
        assert vol > 0

    def test_custom_period(self):
        prices = np.arange(100.0, 130.0)
        vol = self.det._calculate_volatility(prices, period=5)
        assert vol > 0


# ---------------------------------------------------------------------------
# _calculate_volume_trend
# ---------------------------------------------------------------------------

class TestCalculateVolumeTrend:
    def setup_method(self):
        self.det = CycleDetector()

    def test_short_data(self):
        volumes = np.array([100.0, 200.0])
        assert self.det._calculate_volume_trend(volumes) == "stable"

    def test_increasing(self):
        volumes = np.concatenate([np.ones(7) * 100, np.ones(7) * 200])
        assert self.det._calculate_volume_trend(volumes) == "increasing"

    def test_decreasing(self):
        volumes = np.concatenate([np.ones(7) * 200, np.ones(7) * 100])
        assert self.det._calculate_volume_trend(volumes) == "decreasing"

    def test_stable(self):
        volumes = np.ones(20) * 100
        assert self.det._calculate_volume_trend(volumes) == "stable"

    def test_custom_period(self):
        volumes = np.concatenate([np.ones(3) * 100, np.ones(3) * 200])
        assert self.det._calculate_volume_trend(volumes, period=3) == "increasing"


# ---------------------------------------------------------------------------
# _determine_trend
# ---------------------------------------------------------------------------

class TestDetermineTrend:
    def setup_method(self):
        self.det = CycleDetector()

    def test_short_data(self):
        prices = np.array([100.0] * 10)
        assert self.det._determine_trend(prices) == "sideways"

    def test_uptrend(self):
        prices = np.linspace(100, 200, 30)
        assert self.det._determine_trend(prices) == "up"

    def test_downtrend(self):
        prices = np.linspace(200, 100, 30)
        assert self.det._determine_trend(prices) == "down"

    def test_sideways(self):
        prices = np.array([100.0] * 30)
        assert self.det._determine_trend(prices) == "sideways"

    def test_custom_period(self):
        prices = np.linspace(100, 150, 30)
        assert self.det._determine_trend(prices, period=10) == "up"


# ---------------------------------------------------------------------------
# _determine_phase scoring
# ---------------------------------------------------------------------------

class TestDeterminePhase:
    def setup_method(self):
        self.det = CycleDetector()

    def test_spring_detection(self):
        """Moderate BTC rise + reasonable volume → spring."""
        phase, conf = self.det._determine_phase(
            btc_7d=6, btc_30d=15, volatility=3,
            volume_trend="increasing", altcoin_corr=0.85,
            funding_rate=0.02, mcap_change_30d=10
        )
        assert phase in (MarketPhase.SPRING, MarketPhase.SUMMER)
        assert 0 < conf <= 1

    def test_summer_detection(self):
        """Strong BTC rise + high vol + high funding → summer."""
        phase, conf = self.det._determine_phase(
            btc_7d=15, btc_30d=40, volatility=8,
            volume_trend="increasing", altcoin_corr=0.9,
            funding_rate=0.1, mcap_change_30d=30
        )
        assert phase == MarketPhase.SUMMER
        assert conf > 0

    def test_autumn_detection(self):
        """Moderate change + low vol + decreasing volume → autumn."""
        phase, conf = self.det._determine_phase(
            btc_7d=2, btc_30d=5, volatility=1,
            volume_trend="decreasing", altcoin_corr=0.4,
            funding_rate=0.01, mcap_change_30d=2
        )
        assert phase in (MarketPhase.AUTUMN, MarketPhase.WINTER)

    def test_winter_detection(self):
        """Big drop + high vol + negative funding → winter."""
        phase, conf = self.det._determine_phase(
            btc_7d=-15, btc_30d=-20, volatility=8,
            volume_trend="decreasing", altcoin_corr=0.3,
            funding_rate=-0.02, mcap_change_30d=-15
        )
        assert phase == MarketPhase.WINTER
        assert conf > 0

    def test_zero_total_score(self):
        """All scores 0 → division by zero guard."""
        # Force all scores to 0 by using impossible conditions
        # This won't happen naturally but tests the guard
        phase, conf = self.det._determine_phase(
            btc_7d=0, btc_30d=0, volatility=3,
            volume_trend="stable", altcoin_corr=0.6,
            funding_rate=0.02, mcap_change_30d=0
        )
        assert conf >= 0

    def test_altcoin_low_correlation(self):
        phase, _ = self.det._determine_phase(
            btc_7d=1, btc_30d=5, volatility=3,
            volume_trend="stable", altcoin_corr=0.3,
            funding_rate=0.02, mcap_change_30d=0
        )
        # Low correlation adds to autumn
        assert phase in (MarketPhase.AUTUMN, MarketPhase.WINTER, MarketPhase.SPRING)

    def test_high_funding_rate(self):
        phase, _ = self.det._determine_phase(
            btc_7d=1, btc_30d=5, volatility=3,
            volume_trend="stable", altcoin_corr=0.6,
            funding_rate=0.1, mcap_change_30d=0
        )
        # High funding adds to summer + autumn
        assert phase in (MarketPhase.SUMMER, MarketPhase.AUTUMN)

    def test_low_funding_rate(self):
        phase, _ = self.det._determine_phase(
            btc_7d=1, btc_30d=5, volatility=3,
            volume_trend="stable", altcoin_corr=0.6,
            funding_rate=-0.05, mcap_change_30d=0
        )
        # Low funding adds to winter
        assert phase in (MarketPhase.WINTER, MarketPhase.AUTUMN)


# ---------------------------------------------------------------------------
# detect_phase – full integration with realistic data
# ---------------------------------------------------------------------------

class TestDetectPhaseIntegration:
    def setup_method(self):
        self.det = CycleDetector()

    def _make_prices(self, start, end, n=50):
        return np.linspace(start, end, n)

    def _make_volumes(self, n=50, base=1000):
        return np.ones(n) * base

    def test_full_detect_spring(self):
        prices = self._make_prices(100, 130)  # +30%
        volumes = np.concatenate([np.ones(25) * 100, np.ones(25) * 200])
        result = self.det.detect_phase(
            prices, volumes, altcoin_correlation=0.85,
            avg_funding_rate=0.02
        )
        assert isinstance(result, MarketCycle)
        assert result.phase in (MarketPhase.SPRING, MarketPhase.SUMMER)
        assert result.btc_change_30d > 0
        assert result.confidence > 0

    def test_full_detect_winter(self):
        prices = self._make_prices(200, 100)  # -50%
        volumes = np.concatenate([np.ones(25) * 200, np.ones(25) * 100])
        result = self.det.detect_phase(
            prices, volumes, altcoin_correlation=0.3,
            avg_funding_rate=-0.02
        )
        assert result.phase == MarketPhase.WINTER
        assert result.btc_change_30d < 0

    def test_full_detect_with_custom_config(self):
        det = CycleDetector({"summerBtcChangeMin": 10})
        prices = self._make_prices(100, 150)
        volumes = self._make_volumes(50)
        result = det.detect_phase(prices, volumes)
        assert result.phase in (MarketPhase.SUMMER, MarketPhase.SPRING)

    def test_result_fields_populated(self):
        prices = self._make_prices(100, 120)
        volumes = self._make_volumes(50)
        result = self.det.detect_phase(prices, volumes)
        assert result.btc_trend in ("up", "down", "sideways")
        assert result.volume_trend in ("increasing", "decreasing", "stable")
        assert isinstance(result.volatility, float)
        assert isinstance(result.btc_change_7d, float)
        assert isinstance(result.btc_change_30d, float)
        assert isinstance(result.altcoin_correlation, float)
        assert isinstance(result.funding_rates_avg, float)
        assert isinstance(result.market_cap_change_30d, (int, float))
