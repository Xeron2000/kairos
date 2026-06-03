"""Comprehensive tests for ConfigManager — target 95%+ coverage."""

from __future__ import annotations

import copy
import threading
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
import yaml

from kairos.core.config_manager import (
    AUTO_MODE_PROFILES,
    ConfigDiff,
    ConfigManager,
    ConfigUpdateEvent,
    ManagerUpdateResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton before each test."""
    ConfigManager._instance = None
    yield
    ConfigManager._instance = None


@pytest.fixture
def minimal_config() -> Dict[str, Any]:
    """Minimal valid configuration dict."""
    return {
        "exchange": "okx",
        "defaultTimeframe": "5m",
        "checkInterval": "1m",
        "notificationChannels": ["telegram"],
        "notificationSymbols": ["BTC/USDT:USDT", "ETH/USDT:USDT"],
        "autoModeProfile": "conservative",
    }


@pytest.fixture
def tmp_config_path(tmp_path: Path) -> Path:
    """Return a temporary config file path."""
    return tmp_path / "config.yaml"


@pytest.fixture
def write_yaml(tmp_config_path: Path, minimal_config: Dict[str, Any]):
    """Write minimal config to temp file and return path."""
    tmp_config_path.parent.mkdir(parents=True, exist_ok=True)
    with tmp_config_path.open("w") as f:
        yaml.safe_dump(minimal_config, f)
    return tmp_config_path


def _make_manager(config_path: Path | None = None, config: Dict[str, Any] | None = None) -> ConfigManager:
    """Create a ConfigManager with mocked file loading."""
    path = config_path or Path("/fake/config.yaml")
    with patch.object(ConfigManager, "_load_initial"):
        mgr = ConfigManager(config_path=path)
    if config is not None:
        mgr._config = copy.deepcopy(config)
        mgr._last_loaded_at = time.time()
    return mgr


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestConfigDiff:
    def test_creation(self):
        diff = ConfigDiff(
            changed_keys={"exchange", "defaultTimeframe"},
            requires_exchange_reload=True,
            requires_symbol_reload=True,
        )
        assert diff.changed_keys == {"exchange", "defaultTimeframe"}
        assert diff.requires_exchange_reload is True
        assert diff.requires_symbol_reload is True

    def test_frozen(self):
        diff = ConfigDiff(set(), False, False)
        with pytest.raises(AttributeError):
            diff.changed_keys = {"x"}  # type: ignore[misc]


class TestConfigUpdateEvent:
    def test_creation(self):
        diff = ConfigDiff(set(), False, False)
        event = ConfigUpdateEvent(
            new_config={"a": 1},
            previous_config={"a": 0},
            warnings=["w"],
            diff=diff,
        )
        assert event.new_config == {"a": 1}
        assert event.previous_config == {"a": 0}
        assert event.warnings == ["w"]
        assert event.diff is diff

    def test_frozen(self):
        diff = ConfigDiff(set(), False, False)
        event = ConfigUpdateEvent({}, {}, [], diff)
        with pytest.raises(AttributeError):
            event.new_config = {}  # type: ignore[misc]


class TestManagerUpdateResult:
    def test_success_result(self):
        result = ManagerUpdateResult(success=True, errors=[], warnings=[], message="ok", diff=None, config={"x": 1})
        assert result.success is True
        assert result.errors == []
        assert result.config == {"x": 1}

    def test_failure_result(self):
        result = ManagerUpdateResult(
            success=False, errors=["bad"], warnings=["w"], message="fail", diff=None, config={}
        )
        assert result.success is False
        assert "bad" in result.errors


# ---------------------------------------------------------------------------
# Singleton & init
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_instance_returns_same(self):
        with patch.object(ConfigManager, "_load_initial"):
            a = ConfigManager.instance()
            b = ConfigManager.instance()
        assert a is b

    def test_instance_thread_safety(self):
        results: List[ConfigManager] = []

        def grab():
            with patch.object(ConfigManager, "_load_initial"):
                results.append(ConfigManager.instance())

        threads = [threading.Thread(target=grab) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert all(r is results[0] for r in results)


# ---------------------------------------------------------------------------
# subscribe / unsubscribe
# ---------------------------------------------------------------------------


class TestSubscribeUnsubscribe:
    def test_subscribe_adds_listener(self):
        mgr = _make_manager()
        listener = MagicMock()
        mgr.subscribe(listener)
        assert listener in mgr._listeners

    def test_subscribe_no_duplicates(self):
        mgr = _make_manager()
        listener = MagicMock()
        mgr.subscribe(listener)
        mgr.subscribe(listener)
        assert mgr._listeners.count(listener) == 1

    def test_unsubscribe_removes(self):
        mgr = _make_manager()
        listener = MagicMock()
        mgr.subscribe(listener)
        mgr.unsubscribe(listener)
        assert listener not in mgr._listeners

    def test_unsubscribe_nonexistent_is_noop(self):
        mgr = _make_manager()
        mgr.unsubscribe(MagicMock())  # should not raise


# ---------------------------------------------------------------------------
# get_config
# ---------------------------------------------------------------------------


class TestGetConfig:
    def test_returns_deepcopy(self, minimal_config):
        mgr = _make_manager(config=minimal_config)
        cfg1 = mgr.get_config()
        cfg2 = mgr.get_config()
        assert cfg1 == cfg2
        assert cfg1 is not cfg2  # different objects

    def test_copy_result_false(self, minimal_config):
        mgr = _make_manager(config=minimal_config)
        cfg = mgr.get_config(copy_result=False)
        assert cfg is mgr._config


# ---------------------------------------------------------------------------
# last_loaded_at
# ---------------------------------------------------------------------------


class TestLastLoadedAt:
    def test_initial_zero(self):
        mgr = _make_manager()
        assert mgr.last_loaded_at() == 0.0

    def test_updates_on_load(self, minimal_config):
        mgr = _make_manager(config=minimal_config)
        assert mgr.last_loaded_at() > 0


# ---------------------------------------------------------------------------
# _get_default_config
# ---------------------------------------------------------------------------


class TestGetDefaultConfig:
    def test_returns_expected_keys(self):
        mgr = _make_manager()
        default = mgr._get_default_config()
        assert default["exchange"] == "okx"
        assert "BTC/USDT:USDT" in default["notificationSymbols"]
        assert default["autoModeProfile"] == "conservative"
        assert "telegram" in default


# ---------------------------------------------------------------------------
# _load_from_disk
# ---------------------------------------------------------------------------


class TestLoadFromDisk:
    def test_file_not_found(self, tmp_path: Path):
        mgr = _make_manager(config_path=tmp_path / "nope.yaml")
        with pytest.raises(FileNotFoundError):
            mgr._load_from_disk()

    def test_non_dict_root(self, tmp_path: Path):
        p = tmp_path / "bad.yaml"
        p.write_text("- item1\n- item2\n")
        mgr = _make_manager(config_path=p)
        with pytest.raises(ValueError, match="must be a mapping"):
            mgr._load_from_disk()

    def test_valid_yaml(self, write_yaml: Path):
        mgr = _make_manager(config_path=write_yaml)
        cfg = mgr._load_from_disk()
        assert isinstance(cfg, dict)
        assert cfg["exchange"] == "okx"

    def test_empty_yaml(self, tmp_path: Path):
        p = tmp_path / "empty.yaml"
        p.write_text("")
        mgr = _make_manager(config_path=p)
        cfg = mgr._load_from_disk()
        assert isinstance(cfg, dict)


# ---------------------------------------------------------------------------
# _load_initial
# ---------------------------------------------------------------------------


class TestLoadInitial:
    def test_file_not_found_uses_default(self, tmp_path: Path):
        mgr = _make_manager(config_path=tmp_path / "nope.yaml")
        mgr._load_initial()
        assert mgr._config["exchange"] == "okx"

    def test_valid_file(self, write_yaml: Path):
        mgr = _make_manager(config_path=write_yaml)
        mgr._load_initial()
        assert mgr._config["exchange"] == "okx"

    def test_invalid_config_logs_warning(self, tmp_path: Path):
        p = tmp_path / "config.yaml"
        p.write_text(yaml.safe_dump({"exchange": 123}))
        mgr = _make_manager(config_path=p)
        with patch("kairos.core.config_manager.logging", autospec=True) as mock_log:
            mgr._load_initial()
            mock_log.warning.assert_called()


# ---------------------------------------------------------------------------
# reload_from_disk
# ---------------------------------------------------------------------------


class TestReloadFromDisk:
    def test_reloads_config(self, write_yaml: Path, minimal_config):
        mgr = _make_manager(config_path=write_yaml, config=minimal_config)
        old_ts = mgr._last_loaded_at
        time.sleep(0.01)
        result = mgr.reload_from_disk()
        assert isinstance(result, dict)
        assert mgr._last_loaded_at >= old_ts


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_auto_mode_profile_defaults(self):
        mgr = _make_manager()
        cfg = {"autoModeProfile": "balanced"}
        normalized = mgr._normalize(cfg)
        assert normalized["autoModeLimit"] == AUTO_MODE_PROFILES["balanced"]["autoModeLimit"]

    def test_unknown_profile_falls_back(self):
        mgr = _make_manager()
        cfg = {"autoModeProfile": "nonexistent"}
        normalized = mgr._normalize(cfg)
        assert normalized["autoModeProfile"] == "conservative"

    def test_notification_symbols_default_keyword(self):
        mgr = _make_manager()
        cfg = {"notificationSymbols": "default", "exchange": "okx"}
        with patch("kairos.utils.default_symbols.get_default_symbols", return_value=["BTC/USDT:USDT"], autospec=True):
            normalized = mgr._normalize(cfg)
            assert "BTC/USDT:USDT" in normalized["notificationSymbols"]

    def test_notification_symbols_dedup(self):
        mgr = _make_manager()
        cfg = {"notificationSymbols": ["BTC/USDT:USDT", "BTC/USDT:USDT", "ETH/USDT:USDT"]}
        normalized = mgr._normalize(cfg)
        assert normalized["notificationSymbols"].count("BTC/USDT:USDT") == 1
        assert len(normalized["notificationSymbols"]) == 2

    def test_notification_symbols_trim(self):
        mgr = _make_manager()
        cfg = {"notificationSymbols": ["  BTC/USDT:USDT  "]}
        normalized = mgr._normalize(cfg)
        assert normalized["notificationSymbols"] == ["BTC/USDT:USDT"]

    def test_notification_symbols_skip_non_str(self):
        mgr = _make_manager()
        cfg = {"notificationSymbols": [123, None, "BTC/USDT:USDT"]}
        normalized = mgr._normalize(cfg)
        assert normalized["notificationSymbols"] == ["BTC/USDT:USDT"]

    def test_notification_symbols_skip_empty_string(self):
        mgr = _make_manager()
        cfg = {"notificationSymbols": ["BTC/USDT:USDT", "", "  ", "ETH/USDT:USDT"]}
        normalized = mgr._normalize(cfg)
        assert normalized["notificationSymbols"] == ["BTC/USDT:USDT", "ETH/USDT:USDT"]

    def test_check_interval_default(self):
        mgr = _make_manager()
        cfg = {"defaultTimeframe": "15m"}
        normalized = mgr._normalize(cfg)
        assert normalized["checkInterval"] == "15m"

    def test_coerce_called(self):
        mgr = _make_manager()
        cfg = {"defaultThreshold": "5"}
        # defaultThreshold rule expects int, so "5" should be coerced
        with patch.object(mgr, "_coerce_value", return_value=(5, True)) as mock_coerce:
            mgr._normalize(cfg)
            mock_coerce.assert_called()


# ---------------------------------------------------------------------------
# _get_supported_symbols / _clear_symbol_cache
# ---------------------------------------------------------------------------


class TestSupportedSymbols:
    def test_empty_exchange(self):
        mgr = _make_manager()
        assert mgr._get_supported_symbols("") == []

    def test_cached(self):
        mgr = _make_manager()
        mgr._symbol_cache["binance"] = ["BTC/USDT:USDT"]
        result = mgr._get_supported_symbols("binance")
        assert result == ["BTC/USDT:USDT"]

    def test_loads_and_caches(self):
        mgr = _make_manager()
        with patch("kairos.core.config_manager.load_usdt_contracts", return_value=["ETH/USDT:USDT"], autospec=True):
            result = mgr._get_supported_symbols("okx")
        assert result == ["ETH/USDT:USDT"]
        assert mgr._symbol_cache["okx"] == ["ETH/USDT:USDT"]

    def test_clear_cache(self):
        mgr = _make_manager()
        mgr._symbol_cache["okx"] = ["BTC/USDT:USDT"]
        mgr._clear_symbol_cache()
        assert mgr._symbol_cache == {}


# ---------------------------------------------------------------------------
# update_config
# ---------------------------------------------------------------------------


class TestUpdateConfig:
    def _validation_ok(self):
        vr = MagicMock()
        vr.is_valid = True
        vr.errors = []
        vr.warnings = []
        return vr

    def test_validation_failure(self, minimal_config):
        mgr = _make_manager(config=minimal_config)
        vr = MagicMock()
        vr.is_valid = False
        vr.errors = ["bad"]
        vr.warnings = []
        with patch("kairos.core.config_manager.config_validator.validate_config", return_value=vr, autospec=True):
            result = mgr.update_config({"exchange": "binance"})
        assert result.success is False
        assert "bad" in result.errors

    def test_no_valid_symbols(self, minimal_config):
        mgr = _make_manager(config=minimal_config)
        vr = self._validation_ok()
        with (
            patch("kairos.core.config_manager.config_validator.validate_config", return_value=vr, autospec=True),
            patch.object(mgr, "_get_supported_symbols", return_value=["BTC/USDT:USDT"]),
            patch.object(
                mgr,
                "_normalize",
                return_value={
                    "exchange": "binance",
                    "notificationSymbols": ["NONEXIST/USDT:USDT"],
                },
            ),
        ):
            result = mgr.update_config(
                {
                    "exchange": "binance",
                    "notificationSymbols": ["NONEXIST/USDT:USDT"],
                }
            )
        assert result.success is False
        assert result.message is not None
        assert "No valid notification symbols" in result.message

    def test_unchanged_config(self, minimal_config):
        mgr = _make_manager(config=minimal_config)
        vr = self._validation_ok()
        with (
            patch("kairos.core.config_manager.config_validator.validate_config", return_value=vr, autospec=True),
            patch.object(mgr, "_normalize", return_value=copy.deepcopy(minimal_config)),
            patch.object(mgr, "_get_supported_symbols", return_value=["BTC/USDT:USDT", "ETH/USDT:USDT"]),
        ):
            result = mgr.update_config(minimal_config)
        assert result.success is True
        assert result.message == "Configuration unchanged"

    def test_successful_update(self, minimal_config):
        mgr = _make_manager(config=minimal_config)
        vr = self._validation_ok()
        new_config = copy.deepcopy(minimal_config)
        new_config["defaultThreshold"] = 5
        with (
            patch("kairos.core.config_manager.config_validator.validate_config", return_value=vr, autospec=True),
            patch.object(mgr, "_normalize", return_value=new_config),
            patch.object(mgr, "_get_supported_symbols", return_value=["BTC/USDT:USDT", "ETH/USDT:USDT"]),
            patch("kairos.core.config_manager.write_config", autospec=True),
        ):
            result = mgr.update_config(new_config)
        assert result.success is True
        assert result.message == "Configuration updated successfully"
        assert result.diff is not None
        assert "defaultThreshold" in result.diff.changed_keys

    def test_update_notifies_listeners(self, minimal_config):
        mgr = _make_manager(config=minimal_config)
        listener = MagicMock()
        mgr.subscribe(listener)
        vr = self._validation_ok()
        new_config = copy.deepcopy(minimal_config)
        new_config["exchange"] = "binance"
        with (
            patch("kairos.core.config_manager.config_validator.validate_config", return_value=vr, autospec=True),
            patch.object(mgr, "_normalize", return_value=new_config),
            patch.object(mgr, "_get_supported_symbols", return_value=["BTC/USDT:USDT"]),
            patch("kairos.core.config_manager.write_config", autospec=True),
        ):
            mgr.update_config(new_config)
        listener.assert_called_once()
        event = listener.call_args[0][0]
        assert isinstance(event, ConfigUpdateEvent)

    def test_update_clears_symbol_cache_on_symbol_change(self, minimal_config):
        mgr = _make_manager(config=minimal_config)
        vr = self._validation_ok()
        new_config = copy.deepcopy(minimal_config)
        new_config["notificationSymbols"] = ["SOL/USDT:USDT"]
        with (
            patch("kairos.core.config_manager.config_validator.validate_config", return_value=vr, autospec=True),
            patch.object(mgr, "_normalize", return_value=new_config),
            patch.object(mgr, "_get_supported_symbols", return_value=["BTC/USDT:USDT", "SOL/USDT:USDT"]),
            patch("kairos.core.config_manager.write_config", autospec=True),
            patch.object(mgr, "_clear_symbol_cache") as mock_clear,
        ):
            mgr.update_config(new_config)
        mock_clear.assert_called_once()


# ---------------------------------------------------------------------------
# _diff
# ---------------------------------------------------------------------------


class TestDiff:
    def test_no_changes(self):
        mgr = _make_manager()
        old = {"a": 1}
        new = {"a": 1}
        diff = mgr._diff(old, new)
        assert diff.changed_keys == set()
        assert diff.requires_exchange_reload is False
        assert diff.requires_symbol_reload is False

    def test_exchange_change(self):
        mgr = _make_manager()
        old = {"exchange": "okx"}
        new = {"exchange": "binance"}
        diff = mgr._diff(old, new)
        assert "exchange" in diff.changed_keys
        assert diff.requires_exchange_reload is True
        assert diff.requires_symbol_reload is True

    def test_notification_symbols_change(self):
        mgr = _make_manager()
        old = {"notificationSymbols": ["A"]}
        new = {"notificationSymbols": ["B"]}
        diff = mgr._diff(old, new)
        assert diff.requires_symbol_reload is True

    def test_removed_key(self):
        mgr = _make_manager()
        old = {"a": 1, "b": 2}
        new = {"a": 1}
        diff = mgr._diff(old, new)
        assert "b" in diff.changed_keys

    def test_nested_change(self):
        mgr = _make_manager()
        old = {"telegram": {"token": "old"}}
        new = {"telegram": {"token": "new"}}
        diff = mgr._diff(old, new)
        assert "telegram.token" in diff.changed_keys


# ---------------------------------------------------------------------------
# _flatten
# ---------------------------------------------------------------------------


class TestFlatten:
    def test_flat_dict(self):
        mgr = _make_manager()
        result = mgr._flatten({"a": 1, "b": 2})
        assert result == {"a": 1, "b": 2}

    def test_nested_dict(self):
        mgr = _make_manager()
        result = mgr._flatten({"a": {"b": {"c": 1}}})
        assert result == {"a.b.c": 1}

    def test_mixed(self):
        mgr = _make_manager()
        result = mgr._flatten({"x": 1, "y": {"z": 2}})
        assert result == {"x": 1, "y.z": 2}


# ---------------------------------------------------------------------------
# _set_value_by_path
# ---------------------------------------------------------------------------


class TestSetValueByPath:
    def test_top_level(self):
        mgr = _make_manager()
        cfg: Dict[str, Any] = {}
        mgr._set_value_by_path(cfg, "exchange", "binance")
        assert cfg["exchange"] == "binance"

    def test_nested(self):
        mgr = _make_manager()
        cfg: Dict[str, Any] = {}
        mgr._set_value_by_path(cfg, "telegram.token", "abc123")
        assert cfg["telegram"]["token"] == "abc123"

    def test_overwrite_non_dict(self):
        mgr = _make_manager()
        cfg: Dict[str, Any] = {"telegram": "not_a_dict"}
        mgr._set_value_by_path(cfg, "telegram.token", "abc123")
        assert cfg["telegram"]["token"] == "abc123"


# ---------------------------------------------------------------------------
# Coerce helpers
# ---------------------------------------------------------------------------


class TestCoerceInt:
    def test_already_int(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_int(42)
        assert val == 42 and changed is False

    def test_string_digit(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_int("42")
        assert val == 42 and changed is True

    def test_string_signed(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_int("-7")
        assert val == -7 and changed is True

    def test_string_float_like(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_int("3.14")
        assert val == 3 and changed is True

    def test_string_invalid(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_int("abc")
        assert val == "abc" and changed is False

    def test_non_int_non_str(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_int(3.14)
        assert val == 3.14 and changed is False


class TestCoerceFloat:
    def test_already_float(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_float(3.14)
        assert val == 3.14 and changed is False

    def test_from_int(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_float(42)
        assert val == 42.0 and changed is True

    def test_from_string(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_float("2.5")
        assert val == 2.5 and changed is True

    def test_string_invalid(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_float("abc")
        assert val == "abc" and changed is False

    def test_other_type(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_float([1])
        assert val == [1] and changed is False


class TestCoerceBool:
    def test_already_bool(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_bool(True)
        assert val is True and changed is False

    def test_true_strings(self):
        mgr = _make_manager()
        for s in ("true", "yes", "1", "True", "YES"):
            val, changed = mgr._coerce_bool(s)
            assert val is True and changed is True

    def test_false_strings(self):
        mgr = _make_manager()
        for s in ("false", "no", "0", "False", "NO"):
            val, changed = mgr._coerce_bool(s)
            assert val is False and changed is True

    def test_unknown_string(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_bool("maybe")
        assert val == "maybe" and changed is False

    def test_non_bool_non_str(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_bool(42)
        assert val == 42 and changed is False


class TestCoerceList:
    def test_already_list(self):
        mgr = _make_manager()
        rule = MagicMock()
        val, changed = mgr._coerce_list(["a", "b"], rule)
        assert val == ["a", "b"] and changed is False

    def test_comma_separated_string(self):
        mgr = _make_manager()
        rule = MagicMock()
        val, changed = mgr._coerce_list("a,b,c", rule)
        assert val == ["a", "b", "c"] and changed is True

    def test_string_with_spaces(self):
        mgr = _make_manager()
        rule = MagicMock()
        val, changed = mgr._coerce_list(" a , b ", rule)
        assert val == ["a", "b"] and changed is True

    def test_other_type(self):
        mgr = _make_manager()
        rule = MagicMock()
        val, changed = mgr._coerce_list(42, rule)
        assert val == 42 and changed is False


class TestCoerceNumericUnion:
    def test_already_correct_type(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_numeric_union(42, (int, float))
        assert val == 42 and changed is False

    def test_string_to_int(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_numeric_union("42", (int, float))
        assert val == 42 and changed is True

    def test_string_to_float(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_numeric_union("3.14", (int, float))
        assert val == 3.14 and changed is True

    def test_string_with_e(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_numeric_union("1e3", (int, float))
        assert val == 1000.0 and changed is True

    def test_empty_string(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_numeric_union("", (int, float))
        assert val == "" and changed is False

    def test_invalid_string(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_numeric_union("abc", (int, float))
        assert val == "abc" and changed is False

    def test_float_only_union(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_numeric_union("3.14", (float,))
        assert val == 3.14 and changed is True

    def test_non_str_non_matching(self):
        mgr = _make_manager()
        val, changed = mgr._coerce_numeric_union([1], (int, float))
        assert val == [1] and changed is False


class TestCoerceValue:
    def test_int_rule(self):
        mgr = _make_manager()
        rule = MagicMock()
        rule.data_type = int
        val, changed = mgr._coerce_value("5", rule)
        assert val == 5 and changed is True

    def test_float_rule(self):
        mgr = _make_manager()
        rule = MagicMock()
        rule.data_type = float
        val, changed = mgr._coerce_value("3.14", rule)
        assert val == 3.14 and changed is True

    def test_bool_rule(self):
        mgr = _make_manager()
        rule = MagicMock()
        rule.data_type = bool
        val, changed = mgr._coerce_value("true", rule)
        assert val is True and changed is True

    def test_list_rule(self):
        mgr = _make_manager()
        rule = MagicMock()
        rule.data_type = list
        val, changed = mgr._coerce_value("a,b", rule)
        assert val == ["a", "b"] and changed is True

    def test_tuple_rule(self):
        mgr = _make_manager()
        rule = MagicMock()
        rule.data_type = (int, float)
        val, changed = mgr._coerce_value("42", rule)
        assert val == 42 and changed is True

    def test_no_change(self):
        mgr = _make_manager()
        rule = MagicMock()
        rule.data_type = str
        val, changed = mgr._coerce_value("hello", rule)
        assert val == "hello" and changed is False


# ---------------------------------------------------------------------------
# _notify_listeners
# ---------------------------------------------------------------------------


class TestNotifyListeners:
    def test_calls_all_listeners(self):
        mgr = _make_manager()
        listeners = [MagicMock() for _ in range(3)]
        for listener in listeners:
            mgr.subscribe(listener)
        diff = ConfigDiff(set(), False, False)
        mgr._notify_listeners({"a": 1}, {"a": 0}, ["w"], diff)
        for listener in listeners:
            listener.assert_called_once()

    def test_listener_exception_does_not_propagate(self):
        mgr = _make_manager()
        bad_listener = MagicMock(side_effect=RuntimeError("boom"))
        good_listener = MagicMock()
        mgr.subscribe(bad_listener)
        mgr.subscribe(good_listener)
        diff = ConfigDiff(set(), False, False)
        mgr._notify_listeners({}, {}, [], diff)
        good_listener.assert_called_once()

    def test_event_deepcopy(self):
        mgr = _make_manager()
        captured_events: List[ConfigUpdateEvent] = []

        def listener(event: ConfigUpdateEvent):
            captured_events.append(event)

        mgr.subscribe(listener)
        new_cfg = {"x": 1}
        old_cfg = {"x": 0}
        diff = ConfigDiff(set(), False, False)
        mgr._notify_listeners(new_cfg, old_cfg, [], diff)
        # Mutate originals after call
        new_cfg["x"] = 999
        old_cfg["x"] = 999
        # Event should have captured values at call time
        assert captured_events[0].new_config["x"] == 1
        assert captured_events[0].previous_config["x"] == 0


# ---------------------------------------------------------------------------
# AUTO_MODE_PROFILES constant
# ---------------------------------------------------------------------------


class TestAutoModeProfiles:
    def test_three_profiles(self):
        assert set(AUTO_MODE_PROFILES.keys()) == {"conservative", "balanced", "aggressive"}

    def test_each_has_required_keys(self):
        required = {
            "autoModeLimit",
            "autoModeMinQuoteVolume24h",
            "autoModeMinOpenInterestUsd",
            "autoModeMinListingAgeDays",
            "autoModeMaxRecentVolatilityPct",
        }
        for name, profile in AUTO_MODE_PROFILES.items():
            assert required.issubset(profile.keys()), f"{name} missing keys"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_update_with_empty_candidate(self, minimal_config):
        """Empty candidate should pass validation and be unchanged."""
        mgr = _make_manager(config=minimal_config)
        vr = MagicMock()
        vr.is_valid = True
        vr.errors = []
        vr.warnings = []
        with (
            patch("kairos.core.config_manager.config_validator.validate_config", return_value=vr, autospec=True),
            patch.object(mgr, "_normalize", return_value=copy.deepcopy(minimal_config)),
            patch.object(mgr, "_get_supported_symbols", return_value=["BTC/USDT:USDT", "ETH/USDT:USDT"]),
        ):
            result = mgr.update_config({})
        assert result.success is True

    def test_normalize_preserves_original(self):
        mgr = _make_manager()
        original = {"exchange": "okx"}
        original_copy = copy.deepcopy(original)
        mgr._normalize(original)
        assert original == original_copy

    def test_get_supported_symbols_returns_copy(self):
        mgr = _make_manager()
        mgr._symbol_cache["okx"] = ["BTC/USDT:USDT"]
        result1 = mgr._get_supported_symbols("okx")
        result2 = mgr._get_supported_symbols("okx")
        assert result1 == result2
        assert result1 is not result2
