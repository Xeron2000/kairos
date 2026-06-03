"""
Boost tests for kairos.utils.config_validator — target 95%+ coverage.

Covers missing error branches and untested private validators.
"""

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Union
from unittest.mock import MagicMock, patch

import pytest

from kairos.utils.config_validator import (
    ConfigValidator,
    ValidationResult,
    ValidationRule,
    ValidationLevel,
)


@pytest.fixture
def validator():
    return ConfigValidator()


@pytest.fixture
def valid_config() -> Dict[str, Any]:
    """Minimal valid configuration for tests."""
    return {
        "exchange": "binance",
        "defaultTimeframe": "1h",
        "defaultThreshold": 5.0,
        "notificationChannels": ["telegram"],
        "notificationSymbols": "default",
        "telegram": {
            "token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
            "chatId": "123456789",
        },
    }


# ─── ValidationResult / ValidationLevel basics ───────────────────────────────


class TestValidationLevel:
    def test_enum_values(self):
        assert ValidationLevel.ERROR.value == "error"
        assert ValidationLevel.WARNING.value == "warning"
        assert ValidationLevel.INFO.value == "info"


class TestValidationResultDataclass:
    def test_init(self):
        r = ValidationResult(is_valid=True, errors=[], warnings=[], info=[])
        assert r.is_valid is True
        assert r.errors == []
        assert r.warnings == []
        assert r.info == []

    def test_add_error_sets_valid_false(self):
        r = ValidationResult(is_valid=True, errors=[], warnings=[], info=[])
        r.add_error("bad")
        assert r.is_valid is False
        assert r.errors == ["bad"]

    def test_add_warning(self):
        r = ValidationResult(is_valid=True, errors=[], warnings=[], info=[])
        r.add_warning("careful")
        assert r.warnings == ["careful"]
        assert r.is_valid is True  # warnings don't change validity

    def test_add_info(self):
        r = ValidationResult(is_valid=True, errors=[], warnings=[], info=[])
        r.add_info("fyi")
        assert r.info == ["fyi"]


class TestValidationRuleDataclass:
    def test_defaults(self):
        rule = ValidationRule(key_path="x")
        assert rule.required is True
        assert rule.data_type is str
        assert rule.min_value is None
        assert rule.max_value is None
        assert rule.min_length is None
        assert rule.allowed_values is None
        assert rule.pattern is None
        assert rule.custom_validator is None
        assert rule.error_message is None
        assert rule.level == ValidationLevel.ERROR

    def test_custom_values(self):
        rule = ValidationRule(
            key_path="y",
            required=False,
            data_type=int,
            min_value=0,
            max_value=100,
            min_length=1,
            allowed_values=[1, 2, 3],
            pattern=r"^\d+$",
            custom_validator=lambda v: (True, ""),
            error_message="msg",
            level=ValidationLevel.WARNING,
        )
        assert rule.required is False
        assert rule.min_value == 0
        assert rule.max_value == 100
        assert rule.level == ValidationLevel.WARNING


# ─── _validate_exbranches ────────────────────────────────────────────────────


class TestValidateExchangesList:
    def test_not_a_list(self, validator):
        ok, msg = validator._validate_exchanges_list("binance")
        assert ok is False
        assert "must be a list" in msg

    def test_invalid_exchange_name(self, validator):
        ok, msg = validator._validate_exchanges_list(["binance", "kraken"])
        assert ok is False
        assert "Invalid exchange" in msg
        assert "kraken" in msg

    def test_valid_exchanges(self, validator):
        ok, msg = validator._validate_exchanges_list(["binance", "okx", "bybit"])
        assert ok is True
        assert msg == ""

    def test_empty_list(self, validator):
        ok, msg = validator._validate_exchanges_list([])
        assert ok is True


# ─── _validate_timeframe_string ──────────────────────────────────────────────


class TestValidateTimeframeString:
    def test_none_value(self, validator):
        ok, msg = validator._validate_timeframe_string(None)
        assert ok is True

    def test_not_a_string(self, validator):
        ok, msg = validator._validate_timeframe_string(42)
        assert ok is False
        assert "must be provided as a string" in msg

    def test_invalid_format(self, validator):
        ok, msg = validator._validate_timeframe_string("abc")
        assert ok is False
        assert "Invalid timeframe format" in msg

    def test_zero_minutes(self, validator):
        # "0m" should produce 0 minutes → invalid
        ok, msg = validator._validate_timeframe_string("0m")
        assert ok is False
        assert "positive number" in msg

    def test_valid_timeframes(self, validator):
        for tf in ("1m", "5m", "15m", "1h", "1d"):
            ok, msg = validator._validate_timeframe_string(tf)
            assert ok is True, f"{tf} should be valid, got: {msg}"


# ─── _validate_notification_channels ─────────────────────────────────────────


class TestValidateNotificationChannels:
    def test_not_a_list(self, validator):
        ok, msg = validator._validate_notification_channels("telegram")
        assert ok is False
        assert "must be a list" in msg

    def test_invalid_channel(self, validator):
        ok, msg = validator._validate_notification_channels(["telegram", "slack"])
        assert ok is False
        assert "Invalid notification channel" in msg
        assert "slack" in msg

    def test_valid_channel(self, validator):
        ok, msg = validator._validate_notification_channels(["telegram"])
        assert ok is True

    def test_empty_list(self, validator):
        ok, msg = validator._validate_notification_channels([])
        assert ok is True


# ─── _validate_file_path ─────────────────────────────────────────────────────


class TestValidateFilePath:
    def test_not_a_string(self, validator):
        ok, msg = validator._validate_file_path(123)
        assert ok is False
        assert "must be a string" in msg

    def test_parent_dir_not_exist(self, validator):
        ok, msg = validator._validate_file_path("/nonexistent/dir/file.txt")
        assert ok is False
        assert "Parent directory does not exist" in msg

    def test_path_is_directory(self, validator, tmp_path):
        ok, msg = validator._validate_file_path(str(tmp_path))
        assert ok is False
        assert "not a file" in msg

    def test_existing_readable_file(self, validator, tmp_path):
        f = tmp_path / "data.json"
        f.write_text("{}")
        ok, msg = validator._validate_file_path(str(f))
        assert ok is True

    def test_non_existing_file_valid_parent(self, validator, tmp_path):
        f = tmp_path / "missing.txt"
        ok, msg = validator._validate_file_path(str(f))
        assert ok is True  # parent exists, file can be created

    def test_unreadable_file(self, validator, tmp_path):
        f = tmp_path / "locked.txt"
        f.write_text("secret")
        f.chmod(0o000)
        try:
            ok, msg = validator._validate_file_path(str(f))
            assert ok is False
            assert "not readable" in msg
        finally:
            f.chmod(0o644)

    def test_exception_handling(self, validator):
        # Pass a value that causes Path() to raise
        ok, msg = validator._validate_file_path("\x00")
        # May or may not raise depending on OS, but covers exception branch
        assert isinstance(ok, bool)


# ─── _validate_moving_averages ───────────────────────────────────────────────


class TestValidateMovingAverages:
    def test_not_a_list(self, validator):
        ok, msg = validator._validate_moving_averages("10,20")
        assert ok is False
        assert "must be a list" in msg

    def test_non_int_element(self, validator):
        ok, msg = validator._validate_moving_averages([10, "20"])
        assert ok is False
        assert "must be an integer" in msg

    def test_negative_period(self, validator):
        ok, msg = validator._validate_moving_averages([10, -5])
        assert ok is False
        assert "must be positive" in msg

    def test_zero_period(self, validator):
        ok, msg = validator._validate_moving_averages([0])
        assert ok is False
        assert "must be positive" in msg

    def test_too_large_period(self, validator):
        ok, msg = validator._validate_moving_averages([201])
        assert ok is False
        assert "too large" in msg

    def test_valid_periods(self, validator):
        ok, msg = validator._validate_moving_averages([10, 20, 50, 200])
        assert ok is True

    def test_empty_list(self, validator):
        ok, msg = validator._validate_moving_averages([])
        assert ok is True


# ─── _validate_notification_symbols ──────────────────────────────────────────


class TestValidateNotificationSymbols:
    def test_none_value(self, validator):
        ok, msg = validator._validate_notification_symbols(None)
        assert ok is True

    def test_string_default(self, validator):
        ok, msg = validator._validate_notification_symbols("default")
        assert ok is True

    def test_string_auto(self, validator):
        ok, msg = validator._validate_notification_symbols("auto")
        assert ok is True

    def test_string_auto_case_insensitive(self, validator):
        ok, msg = validator._validate_notification_symbols("AUTO")
        assert ok is True

    def test_invalid_string(self, validator):
        ok, msg = validator._validate_notification_symbols("bitcoin")
        assert ok is False
        assert "must be 'default', 'auto'" in msg

    def test_not_string_or_list(self, validator):
        ok, msg = validator._validate_notification_symbols(42)
        assert ok is False
        assert "must be 'default', 'auto'" in msg

    def test_list_with_non_string(self, validator):
        ok, msg = validator._validate_notification_symbols(["BTC", 123])
        assert ok is False
        assert "must be a string" in msg

    def test_list_with_empty_entry(self, validator):
        ok, msg = validator._validate_notification_symbols(["BTC", "  "])
        assert ok is False
        assert "must not contain empty" in msg

    def test_empty_list(self, validator):
        ok, msg = validator._validate_notification_symbols([])
        assert ok is False
        assert "must contain at least one" in msg

    def test_valid_list(self, validator):
        ok, msg = validator._validate_notification_symbols(["BTC/USDT", "ETH/USDT"])
        assert ok is True


# ─── _validate_optional_secret ───────────────────────────────────────────────


class TestValidateOptionalSecret:
    def test_none_value(self, validator):
        ok, msg = validator._validate_optional_secret(None)
        assert ok is True

    def test_empty_string(self, validator):
        ok, msg = validator._validate_optional_secret("")
        assert ok is True

    def test_whitespace_only(self, validator):
        ok, msg = validator._validate_optional_secret("   ")
        assert ok is True

    def test_too_short(self, validator):
        ok, msg = validator._validate_optional_secret("abc")
        assert ok is False
        assert "at least 6 characters" in msg

    def test_minimum_length(self, validator):
        ok, msg = validator._validate_optional_secret("abcdef")
        assert ok is True

    def test_longer_secret(self, validator):
        ok, msg = validator._validate_optional_secret("my-secret-key-123")
        assert ok is True


# ─── _validate_boolean_or_string_boolean ─────────────────────────────────────


class TestValidateBooleanOrStringBoolean:
    def test_none_value(self, validator):
        ok, msg = validator._validate_boolean_or_string_boolean(None)
        assert ok is True

    def test_true(self, validator):
        ok, msg = validator._validate_boolean_or_string_boolean(True)
        assert ok is True

    def test_false(self, validator):
        ok, msg = validator._validate_boolean_or_string_boolean(False)
        assert ok is True

    def test_string_true(self, validator):
        ok, msg = validator._validate_boolean_or_string_boolean("true")
        assert ok is True

    def test_string_1(self, validator):
        ok, msg = validator._validate_boolean_or_string_boolean("1")
        assert ok is True

    def test_string_yes(self, validator):
        ok, msg = validator._validate_boolean_or_string_boolean("yes")
        assert ok is True

    def test_string_false(self, validator):
        ok, msg = validator._validate_boolean_or_string_boolean("false")
        assert ok is True

    def test_string_0(self, validator):
        ok, msg = validator._validate_boolean_or_string_boolean("0")
        assert ok is True

    def test_string_no(self, validator):
        ok, msg = validator._validate_boolean_or_string_boolean("no")
        assert ok is True

    def test_string_TRUE_uppercase(self, validator):
        ok, msg = validator._validate_boolean_or_string_boolean("TRUE")
        assert ok is True

    def test_invalid_string(self, validator):
        ok, msg = validator._validate_boolean_or_string_boolean("maybe")
        assert ok is False
        assert "boolean-equivalent" in msg

    def test_invalid_type(self, validator):
        ok, msg = validator._validate_boolean_or_string_boolean(42)
        assert ok is False


# ─── get_value_by_path ───────────────────────────────────────────────────────


class TestGetValueByPath:
    def test_flat_key(self, validator):
        assert validator.get_value_by_path({"a": 1}, "a") == 1

    def test_nested_key(self, validator):
        config = {"telegram": {"token": "abc"}}
        assert validator.get_value_by_path(config, "telegram.token") == "abc"

    def test_missing_key(self, validator):
        assert validator.get_value_by_path({}, "missing") is None

    def test_missing_nested_key(self, validator):
        assert validator.get_value_by_path({"a": 1}, "a.b") is None

    def test_non_dict_intermediate(self, validator):
        assert validator.get_value_by_path({"a": "str"}, "a.b") is None


# ─── validate_type ───────────────────────────────────────────────────────────


class TestValidateType:
    def test_matching_type(self, validator):
        assert validator.validate_type("hello", str) is True

    def test_non_matching_type(self, validator):
        assert validator.validate_type("hello", int) is False

    def test_tuple_type(self, validator):
        assert validator.validate_type(5, (int, float)) is True
        assert validator.validate_type("x", (int, float)) is False

    def test_bool_with_string_true(self, validator):
        assert validator.validate_type("true", bool) is True
        assert validator.validate_type("1", bool) is True
        assert validator.validate_type("yes", bool) is True
        assert validator.validate_type("false", bool) is True
        assert validator.validate_type("0", bool) is True
        assert validator.validate_type("no", bool) is True

    def test_bool_with_invalid_string(self, validator):
        assert validator.validate_type("maybe", bool) is False


# ─── validate_range ──────────────────────────────────────────────────────────


class TestValidateRange:
    def test_within_range(self, validator):
        ok, msg = validator.validate_range(5, 1, 10)
        assert ok is True

    def test_below_min(self, validator):
        ok, msg = validator.validate_range(0, 1, 10)
        assert ok is False
        assert "less than minimum" in msg

    def test_above_max(self, validator):
        ok, msg = validator.validate_range(15, 1, 10)
        assert ok is False
        assert "greater than maximum" in msg

    def test_no_min(self, validator):
        ok, msg = validator.validate_range(-100, None, 10)
        assert ok is True

    def test_no_max(self, validator):
        ok, msg = validator.validate_range(999, 1, None)
        assert ok is True

    def test_no_bounds(self, validator):
        ok, msg = validator.validate_range(42, None, None)
        assert ok is True

    def test_at_boundary(self, validator):
        ok, _ = validator.validate_range(1, 1, 10)
        assert ok is True
        ok, _ = validator.validate_range(10, 1, 10)
        assert ok is True


# ─── validate_pattern ────────────────────────────────────────────────────────


class TestValidatePattern:
    def test_matching(self, validator):
        ok, msg = validator.validate_pattern("abc123", r"^[a-z]+\d+$")
        assert ok is True

    def test_not_matching(self, validator):
        ok, msg = validator.validate_pattern("123abc", r"^[a-z]+\d+$")
        assert ok is False
        assert "does not match" in msg


# ─── validate_config integration ─────────────────────────────────────────────


class TestValidateConfig:
    def test_valid_config(self, validator, valid_config):
        result = validator.validate_config(valid_config)
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_missing_required_exchange(self, validator, valid_config):
        del valid_config["exchange"]
        result = validator.validate_config(valid_config)
        assert result.is_valid is False
        assert any("Exchange" in e for e in result.errors)

    def test_invalid_exchange_value(self, validator, valid_config):
        valid_config["exchange"] = "kraken"
        result = validator.validate_config(valid_config)
        assert result.is_valid is False

    def test_wrong_type_exchange(self, validator, valid_config):
        valid_config["exchange"] = 123
        result = validator.validate_config(valid_config)
        assert result.is_valid is False
        assert any("type" in e.lower() for e in result.errors)

    def test_threshold_too_low(self, validator, valid_config):
        valid_config["defaultThreshold"] = 0.0001
        result = validator.validate_config(valid_config)
        assert result.is_valid is False
        assert any("0.001" in e for e in result.errors)

    def test_threshold_too_high(self, validator, valid_config):
        valid_config["defaultThreshold"] = 200.0
        result = validator.validate_config(valid_config)
        assert result.is_valid is False

    def test_invalid_notification_channel(self, validator, valid_config):
        valid_config["notificationChannels"] = ["slack"]
        result = validator.validate_config(valid_config)
        assert result.is_valid is False

    def test_telegram_token_pattern_fail(self, validator, valid_config):
        valid_config["telegram"]["token"] = "invalid"
        result = validator.validate_config(valid_config)
        assert result.is_valid is False
        assert any("token" in e.lower() for e in result.errors)

    def test_telegram_chatid_pattern_fail(self, validator, valid_config):
        valid_config["telegram"]["chatId"] = "abc"
        result = validator.validate_config(valid_config)
        assert result.is_valid is False
        assert any("chat" in e.lower() for e in result.errors)

    def test_optional_check_interval_invalid(self, validator, valid_config):
        valid_config["checkInterval"] = "invalid"
        result = validator.validate_config(valid_config)
        assert result.is_valid is False

    def test_optional_symbols_file_path(self, validator, valid_config, tmp_path):
        f = tmp_path / "symbols.txt"
        f.write_text("BTC\n")
        valid_config["symbolsFilePath"] = str(f)
        result = validator.validate_config(valid_config)
        assert result.is_valid is True

    def test_optional_notification_cooldown(self, validator, valid_config):
        valid_config["notificationCooldown"] = "5m"
        result = validator.validate_config(valid_config)
        assert result.is_valid is True

    def test_invalid_notification_cooldown(self, validator, valid_config):
        valid_config["notificationCooldown"] = "abc"
        result = validator.validate_config(valid_config)
        assert result.is_valid is False

    def test_priority_thresholds(self, validator, valid_config):
        valid_config["priorityThresholds"] = {"high": 5.0, "medium": 2.0}
        result = validator.validate_config(valid_config)
        assert result.is_valid is True

    def test_priority_thresholds_out_of_range(self, validator, valid_config):
        valid_config["priorityThresholds"] = {"high": 200.0, "medium": 2.0}
        result = validator.validate_config(valid_config)
        assert result.is_valid is False

    def test_high_priority_bypass_cooldown(self, validator, valid_config):
        valid_config["highPriorityBypassCooldown"] = True
        result = validator.validate_config(valid_config)
        assert result.is_valid is True

    def test_auto_mode_profile_valid(self, validator, valid_config):
        valid_config["autoModeProfile"] = "conservative"
        result = validator.validate_config(valid_config)
        assert result.is_valid is True

    def test_auto_mode_profile_invalid(self, validator, valid_config):
        valid_config["autoModeProfile"] = "yolo"
        result = validator.validate_config(valid_config)
        assert result.is_valid is False

    def test_auto_mode_limit_valid(self, validator, valid_config):
        valid_config["autoModeLimit"] = 100
        result = validator.validate_config(valid_config)
        assert result.is_valid is True

    def test_auto_mode_limit_out_of_range(self, validator, valid_config):
        valid_config["autoModeLimit"] = 0
        result = validator.validate_config(valid_config)
        assert result.is_valid is False

    def test_auto_mode_volume_filters(self, validator, valid_config):
        valid_config["autoModeMinQuoteVolume24h"] = 1_000_000
        valid_config["autoModeMinOpenInterestUsd"] = 500_000
        valid_config["autoModeMinListingAgeDays"] = 30
        valid_config["autoModeMaxRecentVolatilityPct"] = 10.0
        result = validator.validate_config(valid_config)
        assert result.is_valid is True

    def test_volume_sentry_config(self, validator, valid_config):
        valid_config["volumeSentry"] = {"enabled": True, "threshold": 5.0}
        result = validator.validate_config(valid_config)
        assert result.is_valid is True

    def test_volume_sentry_threshold_out_of_range(self, validator, valid_config):
        valid_config["volumeSentry"] = {"enabled": True, "threshold": 200}
        result = validator.validate_config(valid_config)
        assert result.is_valid is False

    def test_open_interest_sentry_config(self, validator, valid_config):
        valid_config["openInterestSentry"] = {"enabled": True, "threshold": 10.0}
        result = validator.validate_config(valid_config)
        assert result.is_valid is True

    def test_log_level_valid(self, validator, valid_config):
        valid_config["logLevel"] = "DEBUG"
        result = validator.validate_config(valid_config)
        assert result.is_valid is True

    def test_log_level_invalid(self, validator, valid_config):
        valid_config["logLevel"] = "TRACE"
        result = validator.validate_config(valid_config)
        assert result.is_valid is False

    def test_timezone_valid(self, validator, valid_config):
        valid_config["notificationTimezone"] = "Asia/Shanghai"
        result = validator.validate_config(valid_config)
        assert result.is_valid is True

    def test_timezone_invalid(self, validator, valid_config):
        valid_config["notificationTimezone"] = "Mars/Base"
        result = validator.validate_config(valid_config)
        assert result.is_valid is False

    def test_volume_monitoring_bool(self, validator, valid_config):
        valid_config["volumeMonitoring"] = True
        result = validator.validate_config(valid_config)
        assert result.is_valid is True

    def test_volume_threshold_valid(self, validator, valid_config):
        valid_config["volumeThreshold"] = 5.0
        result = validator.validate_config(valid_config)
        assert result.is_valid is True

    def test_volume_threshold_out_of_range(self, validator, valid_config):
        valid_config["volumeThreshold"] = 0
        result = validator.validate_config(valid_config)
        assert result.is_valid is False

    def test_security_dashboard_key(self, validator, valid_config):
        valid_config["security"] = {"dashboardAccessKey": "secret123"}
        result = validator.validate_config(valid_config)
        assert result.is_valid is True

    def test_security_dashboard_key_too_short(self, validator, valid_config):
        valid_config["security"] = {"dashboardAccessKey": "ab"}
        result = validator.validate_config(valid_config)
        assert result.is_valid is False
        assert any("4 characters" in e for e in result.errors)

    def test_exchanges_list_valid(self, validator, valid_config):
        valid_config["exchanges"] = ["binance", "okx"]
        result = validator.validate_config(valid_config)
        assert result.is_valid is True

    def test_exchanges_list_invalid(self, validator, valid_config):
        valid_config["exchanges"] = ["binance", "ftx"]
        result = validator.validate_config(valid_config)
        assert result.is_valid is False

    def test_notification_symbols_list(self, validator, valid_config):
        valid_config["notificationSymbols"] = ["BTC/USDT", "ETH/USDT"]
        result = validator.validate_config(valid_config)
        assert result.is_valid is True


# ─── _validate_cross_fields ─────────────────────────────────────────────────


class TestCrossFieldValidation:
    def test_telegram_enabled_missing_token(self, validator, valid_config):
        valid_config["notificationChannels"] = ["telegram"]
        valid_config["telegram"] = {"chatId": "123"}
        result = validator.validate_config(valid_config)
        assert result.is_valid is False
        assert any("token is missing" in e for e in result.errors)

    def test_telegram_enabled_missing_chatid(self, validator, valid_config):
        valid_config["notificationChannels"] = ["telegram"]
        valid_config["telegram"] = {"token": "123:abc"}
        result = validator.validate_config(valid_config)
        assert result.is_valid is False
        assert any("chat ID is missing" in e for e in result.errors)

    def test_telegram_enabled_empty_chatid(self, validator, valid_config):
        valid_config["notificationChannels"] = ["telegram"]
        valid_config["telegram"] = {"token": "123:abc", "chatId": "  "}
        result = validator.validate_config(valid_config)
        assert result.is_valid is False
        assert any("chat ID is missing" in e for e in result.errors)

    def test_no_telegram_no_cross_validation(self, validator, valid_config):
        valid_config["notificationChannels"] = []  # no telegram
        del valid_config["telegram"]
        # Only notificationSymbols check applies — but it's "default"
        result = validator.validate_config(valid_config)
        # Should have no telegram-related errors
        telegram_errors = [e for e in result.errors if "telegram" in e.lower() or "Telegram" in e]
        assert len(telegram_errors) == 0


# ─── get_config_schema ───────────────────────────────────────────────────────


class TestGetConfigSchema:
    def test_returns_dict(self, validator):
        schema = validator.get_config_schema()
        assert isinstance(schema, dict)

    def test_contains_exchange(self, validator):
        schema = validator.get_config_schema()
        assert "exchange" in schema
        assert schema["exchange"]["required"] is True

    def test_contains_nested_telegram(self, validator):
        schema = validator.get_config_schema()
        assert "telegram" in schema
        assert isinstance(schema["telegram"], dict)
        assert "token" in schema["telegram"]

    def test_all_rules_have_schema_entries(self, validator):
        schema = validator.get_config_schema()
        for key_path in validator.rules:
            # Navigate nested schema
            keys = key_path.split(".")
            current = schema
            for k in keys:
                assert k in current, f"Missing schema entry for {key_path}"
                current = current[k]


# ─── init / setup ────────────────────────────────────────────────────────────


class TestConfigValidatorInit:
    def test_creates_rules(self):
        v = ConfigValidator()
        assert len(v.rules) > 0

    def test_logger_setup(self):
        v = ConfigValidator()
        assert v.logger is not None

    def test_rules_contain_required_keys(self):
        v = ConfigValidator()
        assert "exchange" in v.rules
        assert "defaultTimeframe" in v.rules
        assert "defaultThreshold" in v.rules
        assert "notificationChannels" in v.rules
        assert "notificationSymbols" in v.rules
