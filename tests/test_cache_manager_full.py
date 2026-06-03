"""Comprehensive tests for CacheManager and related classes."""

import time
from unittest.mock import patch

import pytest

from kairos.utils.cache_manager import (
    AlertHistoryManager,
    CacheEntry,
    CacheManager,
    CacheStrategy,
    NotificationCooldownManager,
    PriceCacheManager,
)


class TestCacheEntry:
    """Test CacheEntry dataclass."""

    def test_is_expired_no_ttl(self):
        entry = CacheEntry(value="test")
        assert entry.is_expired() is False

    def test_is_expired_with_ttl_not_expired(self):
        entry = CacheEntry(value="test", ttl=100.0)
        assert entry.is_expired() is False

    def test_is_expired_with_ttl_expired(self):
        entry = CacheEntry(value="test", timestamp=time.time() - 200, ttl=100.0)
        assert entry.is_expired() is True

    def test_update_access(self):
        entry = CacheEntry(value="test")
        assert entry.access_count == 0
        entry.update_access()
        assert entry.access_count == 1


class TestCacheManager:
    """Test CacheManager class."""

    @pytest.fixture
    def cache(self):
        return CacheManager(max_size=5, default_ttl=10.0)

    def test_init(self, cache):
        assert cache.max_size == 5
        assert cache.default_ttl == 10.0
        assert cache.strategy == CacheStrategy.LRU

    def test_set_and_get(self, cache):
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_default(self, cache):
        assert cache.get("missing", "default") == "default"

    def test_delete(self, cache):
        cache.set("key1", "value1")
        assert cache.delete("key1") is True
        assert cache.get("key1") is None

    def test_delete_missing(self, cache):
        assert cache.delete("missing") is False

    def test_clear(self, cache):
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()
        assert cache.size() == 0

    def test_contains(self, cache):
        cache.set("key1", "value1")
        assert cache.contains("key1") is True
        assert cache.contains("missing") is False

    def test_contains_operator(self, cache):
        cache.set("key1", "value1")
        assert "key1" in cache
        assert "missing" not in cache

    def test_size(self, cache):
        assert cache.size() == 0
        cache.set("key1", "value1")
        assert cache.size() == 1

    def test_is_empty(self, cache):
        assert cache.is_empty() is True
        cache.set("key1", "value1")
        assert cache.is_empty() is False

    def test_keys(self, cache):
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        assert set(cache.keys()) == {"key1", "key2"}

    def test_values(self, cache):
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        assert set(cache.values()) == {"value1", "value2"}

    def test_items(self, cache):
        cache.set("key1", "value1")
        items = cache.items()
        assert len(items) == 1
        assert items[0] == ("key1", "value1")

    def test_get_keys(self, cache):
        cache.set("key1", "value1")
        assert cache.get_keys() == ["key1"]

    def test_get_values(self, cache):
        cache.set("key1", "value1")
        assert cache.get_values() == ["value1"]

    def test_eviction_lru(self, cache):
        """Test LRU eviction when cache is full."""
        for i in range(6):
            cache.set(f"key{i}", f"value{i}")
        assert cache.size() == 5
        assert cache.get("key0") is None  # Evicted
        assert cache.get("key5") == "value5"

    def test_eviction_fifo(self):
        cache = CacheManager(max_size=3, strategy=CacheStrategy.FIFO)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        cache.set("key4", "value4")
        assert cache.get("key1") is None
        assert cache.get("key4") == "value4"

    def test_eviction_lfu(self):
        cache = CacheManager(max_size=3, strategy=CacheStrategy.LFU)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        # Access key1 and key2 multiple times
        cache.get("key1")
        cache.get("key1")
        cache.get("key2")
        cache.set("key4", "value4")
        # key3 should be evicted (least frequently used)
        assert cache.get("key3") is None

    def test_cleanup_expired(self, cache):
        cache.set("key1", "value1", ttl=0.01)
        time.sleep(0.02)
        count = cache.cleanup_expired()
        assert count == 1
        assert cache.size() == 0

    def test_resize(self, cache):
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.resize(1)
        assert cache.max_size == 1

    def test_set_strategy(self, cache):
        cache.set_strategy(CacheStrategy.FIFO)
        assert cache.strategy == CacheStrategy.FIFO

    def test_get_expired_entries(self, cache):
        cache.set("key1", "value1", ttl=0.01)
        time.sleep(0.02)
        expired = cache.get_expired_entries()
        assert "key1" in expired

    def test_cleanup_expired_entries(self, cache):
        cache.set("key1", "value1", ttl=0.01)
        time.sleep(0.02)
        count = cache.cleanup_expired_entries()
        assert count == 1

    def test_get_stats(self, cache):
        cache.set("key1", "value1")
        cache.get("key1")
        stats = cache.get_stats()
        assert stats["size"] == 1
        assert stats["hits"] == 1
        assert stats["max_size"] == 5

    def test_generate_key_string(self, cache):
        assert cache._generate_key("test") == "test"

    def test_generate_key_tuple(self, cache):
        key = cache._generate_key(("a", "b"))
        assert isinstance(key, str)
        assert len(key) == 32  # MD5 hash

    def test_generate_key_dict(self, cache):
        key = cache._generate_key({"a": 1, "b": 2})
        assert isinstance(key, str)

    def test_ttl_override(self, cache):
        cache.set("key1", "value1", ttl=0.01)
        time.sleep(0.02)
        assert cache.get("key1") is None

    def test_default_ttl(self):
        cache = CacheManager(default_ttl=0.01)
        cache.set("key1", "value1")
        time.sleep(0.02)
        assert cache.get("key1") is None

    def test_no_ttl_never_expires(self):
        cache = CacheManager()
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"


class TestPriceCacheManager:
    """Test PriceCacheManager class."""

    @pytest.fixture
    def price_cache(self):
        return PriceCacheManager(max_size=100, default_ttl=60.0)

    def test_set_and_get_price(self, price_cache):
        price_cache.set_price("BTC/USDT", 50000.0)
        assert price_cache.get_price("BTC/USDT") == 50000.0

    def test_get_price_default(self, price_cache):
        assert price_cache.get_price("missing", 0.0) == 0.0

    def test_set_and_get_prices(self, price_cache):
        prices = {"BTC/USDT": 50000.0, "ETH/USDT": 3000.0}
        price_cache.set_prices(prices)
        result = price_cache.get_prices(["BTC/USDT", "ETH/USDT"])
        assert result["BTC/USDT"] == 50000.0
        assert result["ETH/USDT"] == 3000.0

    def test_get_prices_missing(self, price_cache):
        result = price_cache.get_prices(["BTC/USDT"], default=0.0)
        assert result["BTC/USDT"] == 0.0

    def test_add_to_price_history(self, price_cache):
        price_cache.add_to_price_history("BTC/USDT", 50000.0)
        price_cache.add_to_price_history("BTC/USDT", 51000.0)
        history = price_cache.get_price_history("BTC/USDT")
        assert len(history) == 2
        assert history[0] == 50000.0
        assert history[1] == 51000.0

    def test_get_price_history_limit(self, price_cache):
        for i in range(10):
            price_cache.add_to_price_history("BTC/USDT", 50000.0 + i)
        history = price_cache.get_price_history("BTC/USDT", limit=5)
        assert len(history) == 5

    def test_delete_price(self, price_cache):
        price_cache.set_price("BTC/USDT", 50000.0)
        assert price_cache.delete_price("BTC/USDT") is True
        assert price_cache.get_price("BTC/USDT") is None

    def test_clear_prices(self, price_cache):
        price_cache.set_price("BTC/USDT", 50000.0)
        price_cache.clear_prices()
        assert price_cache.get_price("BTC/USDT") is None

    def test_cleanup_expired_prices(self, price_cache):
        price_cache.set_price("BTC/USDT", 50000.0, ttl=0.01)
        time.sleep(0.02)
        count = price_cache.cleanup_expired_prices()
        assert count == 1


class TestAlertHistoryManager:
    """Test AlertHistoryManager class."""

    @pytest.fixture
    def alert_mgr(self):
        return AlertHistoryManager(max_alerts=100)

    def test_add_alert(self, alert_mgr):
        alert_id = alert_mgr.add_alert({"type": "price", "symbol": "BTC/USDT"})
        assert alert_id is not None

    def test_get_recent_alerts(self, alert_mgr):
        alert_mgr.add_alert({"type": "price", "symbol": "BTC/USDT"})
        alert_mgr.add_alert({"type": "volume", "symbol": "ETH/USDT"})
        alerts = alert_mgr.get_recent_alerts(limit=10)
        assert len(alerts) == 2

    def test_get_alerts_history(self, alert_mgr):
        for i in range(5):
            alert_mgr.add_alert({"type": "price", "symbol": f"SYM{i}/USDT"})
        history = alert_mgr.get_alerts_history(limit=3)
        assert len(history) == 3

    def test_clear_alerts(self, alert_mgr):
        alert_mgr.add_alert({"type": "price"})
        alert_mgr.clear_alerts()
        assert len(alert_mgr.get_recent_alerts()) == 0

    def test_get_alert_by_id(self, alert_mgr):
        alert_id = alert_mgr.add_alert({"type": "price", "symbol": "BTC/USDT"})
        alert = alert_mgr.get_alert_by_id(alert_id)
        assert alert is not None
        assert alert["symbol"] == "BTC/USDT"

    def test_get_alert_by_id_not_found(self, alert_mgr):
        assert alert_mgr.get_alert_by_id("nonexistent") is None

    def test_get_stats(self, alert_mgr):
        alert_mgr.add_alert({"type": "price"})
        stats = alert_mgr.get_stats()
        assert stats["total_alerts"] == 1


class TestNotificationCooldownManager:
    """Test NotificationCooldownManager class."""

    @pytest.fixture
    def cooldown_mgr(self):
        return NotificationCooldownManager(default_cooldown_seconds=1.0)

    def test_should_notify_first_time(self, cooldown_mgr):
        assert cooldown_mgr.should_notify("BTC/USDT") is True

    def test_should_notify_within_cooldown(self, cooldown_mgr):
        cooldown_mgr.record_notification("BTC/USDT")
        assert cooldown_mgr.should_notify("BTC/USDT") is False

    def test_should_notify_after_cooldown(self, cooldown_mgr):
        cooldown_mgr.record_notification("BTC/USDT", cooldown_seconds=0.01)
        time.sleep(0.02)
        assert cooldown_mgr.should_notify("BTC/USDT") is True

    def test_bypass_cooldown(self, cooldown_mgr):
        cooldown_mgr.record_notification("BTC/USDT")
        assert cooldown_mgr.should_notify("BTC/USDT", bypass_cooldown=True) is True

    def test_get_remaining_cooldown(self, cooldown_mgr):
        cooldown_mgr.record_notification("BTC/USDT")
        remaining = cooldown_mgr.get_remaining_cooldown("BTC/USDT")
        assert remaining > 0

    def test_get_remaining_cooldown_expired(self, cooldown_mgr):
        cooldown_mgr.record_notification("BTC/USDT", cooldown_seconds=0.01)
        time.sleep(0.02)
        remaining = cooldown_mgr.get_remaining_cooldown("BTC/USDT")
        assert remaining == 0.0

    def test_clear(self, cooldown_mgr):
        cooldown_mgr.record_notification("BTC/USDT")
        cooldown_mgr.clear()
        assert cooldown_mgr.should_notify("BTC/USDT") is True

    def test_update_default_cooldown(self, cooldown_mgr):
        cooldown_mgr.update_default_cooldown(5.0)
        # Verify the default cooldown was updated
        cooldown_mgr.record_notification("BTC/USDT")
        remaining = cooldown_mgr.get_remaining_cooldown("BTC/USDT")
        assert remaining > 1.0
