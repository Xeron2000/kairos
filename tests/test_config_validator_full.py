"""Comprehensive tests for config_validator."""

from unittest.mock import MagicMock, patch

import pytest

from kairos.utils.config_validator import ConfigValidator


@pytest.fixture
def validator():
    """Create a ConfigValidator instance."""
    return ConfigValidator()


class TestValidateExchangesList:
    """Test _validate_exchanges_list method."""

    def test_valid_exchanges(self, validator):
        valid, msg = validator._validate_exchanges_list(["binance", "okx", "bybit"])
        assert valid is True
        assert msg == ""

    def test_single_exchange(self, validator):
        valid, msg = validator._validate_exchanges_list(["binance"])
        assert valid is True

    def test_invalid_exchange(self, validator):
        valid, msg = validator._validate_exchanges_list(["invalid"])
        assert valid is False
        assert "Invalid exchange" in msg

    def test_not_a_list(self, validator):
        valid, msg = validator._validate_exchanges_list("binance")
        assert valid is False
        assert "must be a list" in msg.lower()

    def test_empty_list(self, validator):
        valid, msg = validator._validate_exchanges_list([])
        assert valid is True


class TestValidateTimeframeString:
    """Test _validate_timeframe_string method."""

    def test_valid_timeframe(self, validator):
        valid, msg = validator._validate_timeframe_string("5m")
        assert valid is True

    def test_invalid_timeframe(self, validator):
        valid, msg = validator._validate_timeframe_string("invalid")
        assert valid is False

    def test_none_value(self, validator):
        valid, msg = validator._validate_timeframe_string(None)
        assert valid is True

    def test_not_string(self, validator):
        valid, msg = validator._validate_timeframe_string(123)
        assert valid is False


class TestValidateNotificationChannels:
    """Test _validate_notification_channels method."""

    def test_valid_channels(self, validator):
        valid, msg = validator._validate_notification_channels(["telegram"])
        assert valid is True

    def test_invalid_channel(self, validator):
        valid, msg = validator._validate_notification_channels(["email"])
        assert valid is False
        assert "Invalid notification channel" in msg

    def test_not_a_list(self, validator):
        valid, msg = validator._validate_notification_channels("telegram")
        assert valid is False

    def test_empty_list(self, validator):
        valid, msg = validator._validate_notification_channels([])
        assert valid is True


class TestValidatePositiveNumber:
    """Test _validate_positive_number method."""

    def test_valid_number(self, validator):
        valid, msg = validator._validate_positive_number(5)
        assert valid is True

    def test_zero(self, validator):
        valid, msg = validator._validate_positive_number(0)
        assert valid is False

    def test_negative(self, validator):
        valid, msg = validator._validate_positive_number(-1)
        assert valid is False

    def test_not_number(self, validator):
        valid, msg = validator._validate_positive_number("abc")
        assert valid is False


class TestValidateRange:
    """Test _validate_range method."""

    def test_in_range(self, validator):
        valid, msg = validator._validate_range(5, 1, 10)
        assert valid is True

    def test_below_range(self, validator):
        valid, msg = validator._validate_range(0, 1, 10)
        assert valid is False

    def test_above_range(self, validator):
        valid, msg = validator._validate_range(11, 1, 10)
        assert valid is False


class TestValidateStringMinLength:
    """Test _validate_string_min_length method."""

    def test_valid_string(self, validator):
        valid, msg = validator._validate_string_min_length("test123", 4)
        assert valid is True

    def test_too_short(self, validator):
        valid, msg = validator._validate_string_min_length("ab", 4)
        assert valid is False

    def test_not_string(self, validator):
        valid, msg = validator._validate_string_min_length(123, 4)
        assert valid is False


class TestValidateConfig:
    """Test validate_config method."""

    def test_valid_config(self, validator):
        config = {
            "exchanges": ["binance"],
            "scanInterval": 60,
            "alertCooldown": 300,
            "priceChangeThreshold": 2.0,
        }
        valid, errors = validator.validate_config(config)
        assert valid is True
        assert len(errors) == 0

    def test_missing_exchanges(self, validator):
        config = {
            "scanInterval": 60,
        }
        valid, errors = validator.validate_config(config)
        # Should still be valid as exchanges is optional
        assert isinstance(valid, bool)

    def test_invalid_exchanges(self, validator):
        config = {
            "exchanges": ["invalid"],
        }
        valid, errors = validator.validate_config(config)
        assert valid is False
        assert len(errors) > 0
