"""Tests for minimal PriceCache."""
import time
from kairos.utils.cache_manager import PriceCache, price_cache


class TestPriceCache:
    def setup_method(self):
        self.cache = PriceCache()

    def test_get_prices_miss(self):
        assert self.cache.get_prices(["BTC/USDT"]) == {"BTC/USDT": None}

    def test_set_and_get(self):
        self.cache.set_price("BTC/USDT", 70000.0)
        result = self.cache.get_prices(["BTC/USDT"])
        assert result["BTC/USDT"] == 70000.0

    def test_expiry(self):
        """Price should expire after TTL (default 300s). We simulate by writing an old timestamp."""
        self.cache.set_price("ETH/USDT", 3500.0)
        # Manually expire by setting timestamp far in the past
        self.cache._dict["ETH/USDT"] = (3500.0, time.time() - 1)
        result = self.cache.get_prices(["ETH/USDT"])
        assert result["ETH/USDT"] is None

    def test_multiple_symbols(self):
        self.cache.set_price("BTC/USDT", 70000.0)
        self.cache.set_price("ETH/USDT", 3500.0)
        result = self.cache.get_prices(["BTC/USDT", "ETH/USDT", "SOL/USDT"])
        assert result == {"BTC/USDT": 70000.0, "ETH/USDT": 3500.0, "SOL/USDT": None}

    def test_default_value(self):
        result = self.cache.get_prices(["XRP/USDT"], default=0.0)
        assert result == {"XRP/USDT": 0.0}


class TestGlobalPriceCache:
    def test_global_instance(self):
        assert isinstance(price_cache, PriceCache)
        price_cache.set_price("TEST/USDT", 100.0)
        result = price_cache.get_prices(["TEST/USDT"])
        assert result["TEST/USDT"] == 100.0
