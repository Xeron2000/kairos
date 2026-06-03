"""Comprehensive tests for ConfigManager."""

import copy
from unittest.mock import MagicMock, patch

import pytest

from kairos.core.config_manager import ConfigManager, ConfigDiff, ManagerUpdateResult


@pytest.fixture
def config_manager():
    """Create a fresh ConfigManager instance."""
    # Reset singleton
    ConfigManager._instance = None
    manager = ConfigManager()
    return manager


class TestConfigDiff:
    """Test ConfigDiff dataclass."""

    def test_creation(self):
        diff = ConfigDiff(changed_keys={"key1"}, symbol_change=True, exchange_change=False)
        assert diff.changed_keys == {"key1"}
        assert diff.symbol_change is True
        assert diff.exchange_change is False


class TestManagerUpdateResult:
    """Test ManagerUpdateResult dataclass."""

    def test_creation(self):
        result = ManagerUpdateResult(
            success=True,
            errors=[],
            warnings=[],
            message="OK",
            diff=None,
            config={"key": "value"},
        )
        assert result.success is True
        assert result.errors == []


class TestConfigManager:
    """Test ConfigManager class."""

    def test_singleton(self, config_manager):
        manager2 = ConfigManager()
        assert config_manager is manager2

    def test_get_config(self, config_manager):
        config = config_manager.get_config()
        assert isinstance(config, dict)

    def test_get_config_copy(self, config_manager):
        config1 = config_manager.get_config(copy_result=True)
        config2 = config_manager.get_config(copy_result=True)
        assert config1 == config2
        assert config1 is not config2

    def test_subscribe_unsubscribe(self, config_manager):
        listener = MagicMock()
        config_manager.subscribe(listener)
        assert listener in config_manager._listeners

        config_manager.unsubscribe(listener)
        assert listener not in config_manager._listeners

    def test_subscribe_duplicate(self, config_manager):
        listener = MagicMock()
        config_manager.subscribe(listener)
        config_manager.subscribe(listener)
        assert config_manager._listeners.count(listener) == 1

    def test_unsubscribe_nonexistent(self, config_manager):
        listener = MagicMock()
        # Should not raise
        config_manager.unsubscribe(listener)

    def test_normalize(self, config_manager):
        raw = {
            "exchanges": ["binance"],
            "scanInterval": 60,
        }
        normalized = config_manager._normalize(raw)
        assert isinstance(normalized, dict)

    def test_get_supported_symbols(self, config_manager):
        symbols = config_manager._get_supported_symbols("binance")
        assert isinstance(symbols, list)

    def test_compute_diff(self, config_manager):
        old = {"key1": "value1", "key2": "value2"}
        new = {"key1": "value1_new", "key3": "value3"}
        diff = config_manager._compute_diff(old, new)
        assert isinstance(diff, ConfigDiff)
