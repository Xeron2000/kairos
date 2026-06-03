"""Comprehensive tests for kairos.analysis.support_resistance module."""

import numpy as np
import pytest

from kairos.analysis.support_resistance import PriceLevel, SupportResistance


# ---------------------------------------------------------------------------
# PriceLevel dataclass
# ---------------------------------------------------------------------------

class TestPriceLevel:
    def test_creation_defaults(self):
        level = PriceLevel(
            price=50000.0,
            level_type="resistance",
            strength=3,
            first_test_time=1000.0,
            last_test_time=2000.0,
            touch_count=3,
        )
        assert level.price == 50000.0
        assert level.level_type == "resistance"
        assert level.strength == 3
        assert level.touch_count == 3
        assert level.is_round_number is False
        assert level.volume_at_level == 0

    def test_creation_with_all_fields(self):
        level = PriceLevel(
            price=48000.0,
            level_type="support",
            strength=5,
            first_test_time=100.0,
            last_test_time=900.0,
            touch_count=5,
            is_round_number=True,
            volume_at_level=1234.5,
        )
        assert level.is_round_number is True
        assert level.volume_at_level == 1234.5

    def test_description_property(self):
        level = PriceLevel(
            price=1234.5678,
            level_type="support",
            strength=2,
            first_test_time=0,
            last_test_time=0,
            touch_count=4,
        )
        desc = level.description
        assert "support" in desc
        assert "1234.57" in desc
        assert "2" in desc
        assert "4" in desc

    def test_description_resistance(self):
        level = PriceLevel(
            price=99.1,
            level_type="resistance",
            strength=1,
            first_test_time=0,
            last_test_time=0,
            touch_count=1,
        )
        assert "resistance" in level.description
        assert "99.10" in level.description


# ---------------------------------------------------------------------------
# SupportResistance.__init__
# ---------------------------------------------------------------------------

class TestSupportResistanceInit:
    def test_default_config(self):
        sr = SupportResistance()
        assert sr.lookback_periods == 100
        assert sr.min_touches == 2
        assert sr.proximity_pct == 0.5
        assert sr.round_number_threshold == 1000

    def test_custom_config(self):
        config = {
            "lookbackPeriods": 200,
            "minTouches": 3,
            "proximityPct": 1.0,
            "roundNumberThreshold": 500,
        }
        sr = SupportResistance(config)
        assert sr.lookback_periods == 200
        assert sr.min_touches == 3
        assert sr.proximity_pct == 1.0
        assert sr.round_number_threshold == 500

    def test_partial_config(self):
        sr = SupportResistance({"minTouches": 4})
        assert sr.min_touches == 4
        assert sr.lookback_periods == 100  # default


# ---------------------------------------------------------------------------
# _find_pivot_highs / _find_pivot_lows
# ---------------------------------------------------------------------------

class TestPivotDetection:
    def _make_sr(self):
        return SupportResistance()

    def test_pivot_highs_basic(self):
        sr = self._make_sr()
        # Build array with clear peak at index 5 (window=2)
        highs = np.array([1, 2, 3, 4, 5, 10, 5, 4, 3, 2, 1], dtype=float)
        pivots = sr._find_pivot_highs(highs, window=2)
        # index 5 should be a pivot high (10 is max of [3,4,5,10,5])
        indices = [p[0] for p in pivots]
        assert 5 in indices
        for idx, val in pivots:
            assert val == highs[idx]

    def test_pivot_lows_basic(self):
        sr = self._make_sr()
        lows = np.array([10, 9, 8, 7, 6, 1, 6, 7, 8, 9, 10], dtype=float)
        pivots = sr._find_pivot_lows(lows, window=2)
        indices = [p[0] for p in pivots]
        assert 5 in indices

    def test_pivot_highs_no_peak(self):
        sr = self._make_sr()
        # Monotonically increasing → no pivot high in interior
        highs = np.arange(1, 20, dtype=float)
        pivots = sr._find_pivot_highs(highs, window=2)
        assert len(pivots) == 0

    def test_pivot_lows_no_trough(self):
        sr = self._make_sr()
        lows = np.arange(20, 1, -1, dtype=float)
        pivots = sr._find_pivot_lows(lows, window=2)
        assert len(pivots) == 0

    def test_pivots_short_array(self):
        sr = self._make_sr()
        # Array too short for window=5 → no pivots
        arr = np.array([1, 2, 3], dtype=float)
        assert sr._find_pivot_highs(arr, window=5) == []
        assert sr._find_pivot_lows(arr, window=5) == []

    def test_pivots_custom_window(self):
        sr = self._make_sr()
        highs = np.array([5, 5, 5, 10, 5, 5, 5], dtype=float)
        pivots = sr._find_pivot_highs(highs, window=1)
        indices = [p[0] for p in pivots]
        assert 3 in indices


# ---------------------------------------------------------------------------
# _cluster_levels
# ---------------------------------------------------------------------------

class TestClusterLevels:
    def _make_sr(self):
        return SupportResistance({"proximityPct": 1.0, "minTouches": 2})

    def test_empty_pivots(self):
        sr = self._make_sr()
        result = sr._cluster_levels(
            [], np.array([1, 2, 3]), np.array([100, 200, 300]),
            np.array([1, 2, 3]), "resistance"
        )
        assert result == []

    def test_single_cluster_above_min_touches(self):
        sr = self._make_sr()
        # Two pivots very close together
        pivots = [(0, 100.0), (5, 100.5)]
        prices = np.array([90, 95, 100, 100.5, 98, 100.5, 92] * 2, dtype=float)
        volumes = np.array([100] * 14, dtype=float)
        timestamps = np.arange(14, dtype=float)
        result = sr._cluster_levels(pivots, prices, volumes, timestamps, "resistance")
        assert len(result) >= 1
        assert result[0].level_type == "resistance"

    def test_multiple_clusters(self):
        sr = self._make_sr()
        # Two groups far apart
        pivots = [(0, 100.0), (1, 100.3), (5, 200.0), (6, 200.4)]
        prices = np.array([100, 100.3, 99, 199, 200, 200.4, 195], dtype=float)
        volumes = np.array([50] * 7, dtype=float)
        timestamps = np.arange(7, dtype=float)
        result = sr._cluster_levels(pivots, prices, volumes, timestamps, "support")
        assert len(result) == 2

    def test_cluster_below_min_touches_ignored(self):
        sr = self._make_sr()  # minTouches=2
        # Single pivot far from others
        pivots = [(0, 100.0), (5, 500.0)]
        prices = np.array([100, 500] * 4, dtype=float)
        volumes = np.array([10] * 8, dtype=float)
        timestamps = np.arange(8, dtype=float)
        result = sr._cluster_levels(pivots, prices, volumes, timestamps, "resistance")
        # Both singletons → no cluster meets min_touches=2
        assert len(result) == 0

    def test_last_cluster_included(self):
        sr = self._make_sr()
        # Three close pivots at end
        pivots = [(0, 500.0), (10, 100.0), (11, 100.2), (12, 100.4)]
        prices = np.ones(13, dtype=float) * 100
        volumes = np.ones(13, dtype=float) * 10
        timestamps = np.arange(13, dtype=float)
        result = sr._cluster_levels(pivots, prices, volumes, timestamps, "support")
        # Last cluster of 3 should be included
        assert any(l.touch_count == 3 for l in result)


# ---------------------------------------------------------------------------
# _create_level
# ---------------------------------------------------------------------------

class TestCreateLevel:
    def _make_sr(self):
        return SupportResistance()

    def test_create_level_basic(self):
        sr = self._make_sr()
        cluster = [(2, 100.0), (5, 102.0)]
        prices = np.array([90, 95, 100, 98, 99, 102, 97], dtype=float)
        volumes = np.array([10, 20, 30, 40, 50, 60, 70], dtype=float)
        timestamps = np.array([1000, 2000, 3000, 4000, 5000, 6000, 7000], dtype=float)
        level = sr._create_level(cluster, prices, volumes, timestamps, "resistance")
        assert level.price == pytest.approx(101.0)
        assert level.level_type == "resistance"
        assert level.touch_count == 2
        assert level.strength == 2
        assert level.first_test_time == 3000.0
        assert level.last_test_time == 6000.0

    def test_strength_capped_at_5(self):
        sr = self._make_sr()
        cluster = [(i, 100.0) for i in range(10)]
        prices = np.ones(10, dtype=float)
        volumes = np.ones(10, dtype=float)
        timestamps = np.arange(10, dtype=float)
        level = sr._create_level(cluster, prices, volumes, timestamps, "support")
        assert level.strength == 5
        assert level.touch_count == 10

    def test_out_of_bounds_index_handling(self):
        sr = self._make_sr()
        # Index beyond arrays
        cluster = [(0, 50.0), (100, 60.0)]
        prices = np.array([50, 60], dtype=float)
        volumes = np.array([10, 20], dtype=float)
        timestamps = np.array([1.0, 2.0], dtype=float)
        level = sr._create_level(cluster, prices, volumes, timestamps, "resistance")
        # first_idx=0 valid, last_idx=100 out of bounds → volume fallback
        assert level.first_test_time == 1.0
        assert level.last_test_time == 0  # fallback
        assert level.volume_at_level == 0  # fallback


# ---------------------------------------------------------------------------
# _filter_levels
# ---------------------------------------------------------------------------

class TestFilterLevels:
    def _make_sr(self):
        return SupportResistance()

    def _make_levels(self, prices, level_type):
        return [
            PriceLevel(
                price=p,
                level_type=level_type,
                strength=1,
                first_test_time=0,
                last_test_time=0,
                touch_count=1,
            )
            for p in prices
        ]

    def test_resistance_above_current(self):
        sr = self._make_sr()
        levels = self._make_levels([90, 100, 110, 120], "resistance")
        result = sr._filter_levels(levels, 100, "resistance")
        prices = [l.price for l in result]
        assert all(p > 100 for p in prices)

    def test_support_below_current(self):
        sr = self._make_sr()
        levels = self._make_levels([80, 90, 100, 110], "support")
        result = sr._filter_levels(levels, 100, "support")
        prices = [l.price for l in result]
        assert all(p < 100 for p in prices)

    def test_sorted_by_distance(self):
        sr = self._make_sr()
        levels = self._make_levels([80, 95, 105, 120], "resistance")
        result = sr._filter_levels(levels, 100, "resistance")
        prices = [l.price for l in result]
        # Should be sorted by distance: 105, 120
        assert prices == [105, 120]

    def test_empty_input(self):
        sr = self._make_sr()
        result = sr._filter_levels([], 100, "resistance")
        assert result == []

    def test_all_filtered_out(self):
        sr = self._make_sr()
        levels = self._make_levels([50, 60, 70], "resistance")
        result = sr._filter_levels(levels, 100, "resistance")
        assert result == []


# ---------------------------------------------------------------------------
# _find_nearest
# ---------------------------------------------------------------------------

class TestFindNearest:
    def _make_sr(self):
        return SupportResistance()

    def test_empty_levels(self):
        sr = self._make_sr()
        assert sr._find_nearest([], 100, "resistance") is None

    def test_returns_first(self):
        sr = self._make_sr()
        levels = [
            PriceLevel(110, "resistance", 1, 0, 0, 1),
            PriceLevel(120, "resistance", 1, 0, 0, 1),
        ]
        result = sr._find_nearest(levels, 100, "resistance")
        assert result.price == 110


# ---------------------------------------------------------------------------
# _find_round_numbers
# ---------------------------------------------------------------------------

class TestFindRoundNumbers:
    def _make_sr(self):
        return SupportResistance()

    def test_high_price_step_1000(self):
        sr = self._make_sr()
        levels = sr._find_round_numbers(50000)
        # Should have 1000-step round numbers near 50000
        assert any(abs(l - 50000) < 100 for l in levels)
        for l in levels:
            assert l % 1000 == 0

    def test_medium_price_step_100(self):
        sr = self._make_sr()
        levels = sr._find_round_numbers(5000)
        for l in levels:
            assert l % 100 == 0

    def test_low_price_step_10(self):
        sr = self._make_sr()
        # price=50 is <=100, so step=1 per source code
        levels = sr._find_round_numbers(150)
        for l in levels:
            assert l % 10 == 0

    def test_very_low_price_step_1(self):
        sr = self._make_sr()
        levels = sr._find_round_numbers(5)
        for l in levels:
            assert l % 1 == 0
        assert 5 in levels or 4 in levels

    def test_all_positive(self):
        sr = self._make_sr()
        levels = sr._find_round_numbers(100)
        assert all(l > 0 for l in levels)

    def test_range_within_20_pct(self):
        sr = self._make_sr()
        price = 1000
        levels = sr._find_round_numbers(price)
        for l in levels:
            assert price * 0.8 <= l <= price * 1.2


# ---------------------------------------------------------------------------
# find_levels (integration)
# ---------------------------------------------------------------------------

class TestFindLevels:
    def _make_sr(self):
        return SupportResistance({"proximityPct": 0.5, "minTouches": 2})

    def _make_data(self, n=30):
        np.random.seed(42)
        base = 100
        highs = base + np.random.rand(n) * 10
        lows = base - np.random.rand(n) * 10
        closes = base + np.random.randn(n) * 5
        volumes = np.random.rand(n) * 1000 + 100
        timestamps = np.arange(n, dtype=float)
        return highs, lows, closes, volumes, timestamps

    def test_returns_all_keys(self):
        sr = self._make_sr()
        h, l, c, v, t = self._make_data()
        result = sr.find_levels("BTC/USDT", h, l, c, v, t, 100.0)
        expected_keys = {
            "symbol", "current_price", "resistance_levels", "support_levels",
            "nearest_resistance", "nearest_support", "round_numbers",
        }
        assert set(result.keys()) == expected_keys

    def test_symbol_and_price(self):
        sr = self._make_sr()
        h, l, c, v, t = self._make_data()
        result = sr.find_levels("ETH/USDT", h, l, c, v, t, 2500.0)
        assert result["symbol"] == "ETH/USDT"
        assert result["current_price"] == 2500.0

    def test_resistance_above_price(self):
        sr = self._make_sr()
        h, l, c, v, t = self._make_data()
        price = 100.0
        result = sr.find_levels("BTC/USDT", h, l, c, v, t, price)
        for level in result["resistance_levels"]:
            assert level.price > price

    def test_support_below_price(self):
        sr = self._make_sr()
        h, l, c, v, t = self._make_data()
        price = 100.0
        result = sr.find_levels("BTC/USDT", h, l, c, v, t, price)
        for level in result["support_levels"]:
            assert level.price < price

    def test_max_5_levels_each(self):
        sr = self._make_sr()
        h, l, c, v, t = self._make_data(200)
        result = sr.find_levels("BTC/USDT", h, l, c, v, t, 100.0)
        assert len(result["resistance_levels"]) <= 5
        assert len(result["support_levels"]) <= 5

    def test_round_numbers_list(self):
        sr = self._make_sr()
        h, l, c, v, t = self._make_data()
        result = sr.find_levels("BTC/USDT", h, l, c, v, t, 100.0)
        assert isinstance(result["round_numbers"], list)

    def test_empty_data(self):
        sr = self._make_sr()
        empty = np.array([], dtype=float)
        result = sr.find_levels("BTC/USDT", empty, empty, empty, empty, empty, 100.0)
        assert result["resistance_levels"] == []
        assert result["support_levels"] == []
        assert result["nearest_resistance"] is None
        assert result["nearest_support"] is None


# ---------------------------------------------------------------------------
# calculate_risk_reward
# ---------------------------------------------------------------------------

class TestCalculateRiskReward:
    def _make_sr(self):
        return SupportResistance()

    def test_long_basic(self):
        sr = self._make_sr()
        result = sr.calculate_risk_reward(
            entry_price=100, stop_loss=95, take_profit=110, side="long"
        )
        assert result["entry"] == 100
        assert result["risk"] == 5
        assert result["reward"] == 10
        assert result["rr_ratio"] == pytest.approx(2.0)
        assert result["risk_pct"] == pytest.approx(5.0)
        assert result["reward_pct"] == pytest.approx(10.0)

    def test_short_basic(self):
        sr = self._make_sr()
        result = sr.calculate_risk_reward(
            entry_price=100, stop_loss=105, take_profit=90, side="short"
        )
        assert result["risk"] == 5
        assert result["reward"] == 10
        assert result["rr_ratio"] == pytest.approx(2.0)

    def test_zero_risk(self):
        sr = self._make_sr()
        result = sr.calculate_risk_reward(
            entry_price=100, stop_loss=100, take_profit=110, side="long"
        )
        assert result["risk"] == 0
        assert result["rr_ratio"] == 0

    def test_long_loss_scenario(self):
        sr = self._make_sr()
        result = sr.calculate_risk_reward(
            entry_price=100, stop_loss=98, take_profit=99, side="long"
        )
        assert result["risk"] == 2
        assert result["reward"] == -1
        assert result["rr_ratio"] < 0

    def test_short_loss_scenario(self):
        sr = self._make_sr()
        result = sr.calculate_risk_reward(
            entry_price=100, stop_loss=98, take_profit=101, side="short"
        )
        assert result["risk"] == -2
        assert result["reward"] == -1
        # risk < 0 → rr_ratio = 0 (division guard)
        assert result["rr_ratio"] == 0

    def test_pct_calculations(self):
        sr = self._make_sr()
        result = sr.calculate_risk_reward(
            entry_price=200, stop_loss=190, take_profit=230, side="long"
        )
        assert result["risk_pct"] == pytest.approx(5.0)
        assert result["reward_pct"] == pytest.approx(15.0)
