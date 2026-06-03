"""Comprehensive tests for RiskManager."""

from unittest.mock import MagicMock

import pytest

from kairos.trades.position import Position, PositionManager, PositionStatus
from kairos.trades.risk import RiskConfig, RiskManager


@pytest.fixture
def mock_position_manager():
    """Create a mock PositionManager."""
    pm = MagicMock(spec=PositionManager)
    pm.get_open_positions.return_value = []
    return pm


@pytest.fixture
def risk_manager(mock_position_manager):
    """Create a RiskManager with default config."""
    config = {"risk": {}}
    return RiskManager(config, mock_position_manager)


class TestRiskConfig:
    """Test RiskConfig dataclass."""

    def test_defaults(self):
        config = RiskConfig()
        assert config.max_position_size_pct == 0.33
        assert config.max_leverage_btc == 10
        assert config.max_leverage_alt == 5
        assert config.max_drawdown_pct == 0.20
        assert config.max_daily_loss_pct == 0.10
        assert config.max_consecutive_losses == 3
        assert config.max_open_positions == 2
        assert config.min_risk_reward_ratio == 2.0

    def test_custom_values(self):
        config = RiskConfig(max_leverage_btc=20, max_open_positions=5)
        assert config.max_leverage_btc == 20
        assert config.max_open_positions == 5


class TestCalculatePositionSize:
    """Test calculate_position_size method."""

    def test_basic_calculation(self, risk_manager):
        result = risk_manager.calculate_position_size(
            capital=10000, entry_price=50000, stop_loss=49000, leverage=5, is_btc=True
        )
        assert result["position_size"] > 0
        assert result["leverage"] == 5
        assert result["margin_required"] > 0

    def test_caps_leverage_for_btc(self, risk_manager):
        result = risk_manager.calculate_position_size(
            capital=10000, entry_price=50000, stop_loss=49000, leverage=20, is_btc=True
        )
        assert result["leverage"] == 10  # max_leverage_btc

    def test_caps_leverage_for_alt(self, risk_manager):
        result = risk_manager.calculate_position_size(
            capital=10000, entry_price=100, stop_loss=90, leverage=20, is_btc=False
        )
        assert result["leverage"] == 5  # max_leverage_alt

    def test_limits_position_value(self, risk_manager):
        result = risk_manager.calculate_position_size(
            capital=10000, entry_price=50000, stop_loss=49000, leverage=1, is_btc=True
        )
        max_value = 10000 * 0.33  # max_position_size_pct
        assert result["position_value"] <= max_value

    def test_zero_risk_per_unit(self, risk_manager):
        result = risk_manager.calculate_position_size(
            capital=10000, entry_price=50000, stop_loss=50000, leverage=5, is_btc=True
        )
        assert result["position_size"] == 0


class TestCheckPositionAllowed:
    """Test check_position_allowed method."""

    def test_allowed_when_no_positions(self, risk_manager):
        allowed, msg = risk_manager.check_position_allowed(10000, "BTC/USDT", 1000)
        assert allowed is True
        assert msg == "OK"

    def test_blocked_by_daily_loss(self, risk_manager):
        risk_manager.daily_pnl = -1500  # > 10% of 10000
        allowed, msg = risk_manager.check_position_allowed(10000, "BTC/USDT", 1000)
        assert allowed is False
        assert "daily loss" in msg.lower()

    def test_blocked_by_consecutive_losses(self, risk_manager):
        risk_manager.consecutive_losses = 3
        allowed, msg = risk_manager.check_position_allowed(10000, "BTC/USDT", 1000)
        assert allowed is False
        assert "consecutive" in msg.lower()

    def test_blocked_by_exposure(self, risk_manager, mock_position_manager):
        pos = MagicMock()
        pos.entry_price = 50000
        pos.amount = 0.15
        mock_position_manager.get_open_positions.return_value = [pos]

        allowed, msg = risk_manager.check_position_allowed(10000, "BTC/USDT", 1000)
        assert allowed is False
        assert "exposure" in msg.lower()

    def test_blocked_by_max_positions(self, risk_manager, mock_position_manager):
        pos1 = MagicMock()
        pos1.entry_price = 50000
        pos1.amount = 0.01
        pos2 = MagicMock()
        pos2.entry_price = 3000
        pos2.amount = 0.1
        mock_position_manager.get_open_positions.return_value = [pos1, pos2]
        allowed, msg = risk_manager.check_position_allowed(10000, "BTC/USDT", 1000)
        assert allowed is False
        assert "concurrent" in msg.lower()


class TestValidateStopLoss:
    """Test validate_stop_loss method."""

    def test_valid_long_stop_loss(self, risk_manager):
        valid, msg = risk_manager.validate_stop_loss(50000, 49000, "long")
        assert valid is True

    def test_invalid_long_stop_loss_above_entry(self, risk_manager):
        valid, msg = risk_manager.validate_stop_loss(50000, 51000, "long")
        assert valid is False
        assert "below" in msg.lower()

    def test_valid_short_stop_loss(self, risk_manager):
        valid, msg = risk_manager.validate_stop_loss(50000, 51000, "short")
        assert valid is True

    def test_invalid_short_stop_loss_below_entry(self, risk_manager):
        valid, msg = risk_manager.validate_stop_loss(50000, 49000, "short")
        assert valid is False
        assert "above" in msg.lower()

    def test_tight_stop_loss_warning(self, risk_manager):
        valid, msg = risk_manager.validate_stop_loss(50000, 49900, "long")
        assert valid is True
        assert "tight" in msg.lower()

    def test_wide_stop_loss_warning(self, risk_manager):
        valid, msg = risk_manager.validate_stop_loss(50000, 40000, "long")
        assert valid is True
        assert "wide" in msg.lower()


class TestValidateTakeProfit:
    """Test validate_take_profit method."""

    def test_valid_long_take_profit(self, risk_manager):
        valid, msg, rr = risk_manager.validate_take_profit(50000, 49000, 52000, "long")
        assert valid is True
        assert rr == 2.0

    def test_invalid_long_take_profit_below_entry(self, risk_manager):
        valid, msg, rr = risk_manager.validate_take_profit(50000, 49000, 48000, "long")
        assert valid is False
        assert "above" in msg.lower()

    def test_valid_short_take_profit(self, risk_manager):
        valid, msg, rr = risk_manager.validate_take_profit(50000, 51000, 48000, "short")
        assert valid is True
        assert rr == 2.0

    def test_invalid_short_take_profit_above_entry(self, risk_manager):
        valid, msg, rr = risk_manager.validate_take_profit(50000, 51000, 52000, "short")
        assert valid is False
        assert "below" in msg.lower()

    def test_low_rr_ratio(self, risk_manager):
        valid, msg, rr = risk_manager.validate_take_profit(50000, 49000, 50500, "long")
        assert valid is False
        assert "too low" in msg.lower()

    def test_zero_risk(self, risk_manager):
        valid, msg, rr = risk_manager.validate_take_profit(50000, 50000, 52000, "long")
        assert rr == 0


class TestUpdateDailyPnl:
    """Test update_daily_pnl method."""

    def test_positive_pnl_resets_consecutive(self, risk_manager):
        risk_manager.consecutive_losses = 2
        risk_manager.update_daily_pnl(100)
        assert risk_manager.consecutive_losses == 0
        assert risk_manager.daily_pnl == 100

    def test_negative_pnl_increments_consecutive(self, risk_manager):
        risk_manager.update_daily_pnl(-100)
        assert risk_manager.consecutive_losses == 1
        assert risk_manager.daily_pnl == -100

    def test_accumulates_pnl(self, risk_manager):
        risk_manager.update_daily_pnl(100)
        risk_manager.update_daily_pnl(-50)
        assert risk_manager.daily_pnl == 50


class TestResetDailyStats:
    """Test reset_daily_stats method."""

    def test_resets_stats(self, risk_manager):
        risk_manager.daily_pnl = -500
        risk_manager.consecutive_losses = 3
        risk_manager.reset_daily_stats()
        assert risk_manager.daily_pnl == 0.0
        assert risk_manager.consecutive_losses == 0


class TestGetRiskSummary:
    """Test get_risk_summary method."""

    def test_summary_with_no_positions(self, risk_manager):
        summary = risk_manager.get_risk_summary(10000)
        assert summary["capital"] == 10000
        assert summary["open_positions"] == 0
        assert summary["total_exposure"] == 0
        assert summary["exposure_pct"] == 0

    def test_summary_with_positions(self, risk_manager, mock_position_manager):
        pos = MagicMock()
        pos.entry_price = 50000
        pos.amount = 0.01
        mock_position_manager.get_open_positions.return_value = [pos]

        summary = risk_manager.get_risk_summary(10000)
        assert summary["open_positions"] == 1
        assert summary["total_exposure"] == 500  # 50000 * 0.01

    def test_summary_with_daily_pnl(self, risk_manager):
        risk_manager.daily_pnl = -200
        summary = risk_manager.get_risk_summary(10000)
        assert summary["daily_pnl"] == -200
        assert summary["daily_pnl_pct"] == -2.0

    def test_summary_zero_capital(self, risk_manager):
        summary = risk_manager.get_risk_summary(0)
        assert summary["exposure_pct"] == 0
        assert summary["daily_pnl_pct"] == 0
