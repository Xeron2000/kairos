"""Comprehensive tests for DataManager and DataService."""

import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from kairos.data.data_manager import (
    DataManager,
    DataService,
    ExchangeType,
    MarketData,
)


class TestExchangeType:
    """Test ExchangeType enum."""

    def test_values(self):
        assert ExchangeType.BINANCE.value == "binance"
        assert ExchangeType.OKX.value == "okx"
        assert ExchangeType.BYBIT.value == "bybit"


class TestMarketData:
    """Test MarketData dataclass."""

    def test_creation(self):
        data = MarketData(
            symbol="BTC/USDT",
            exchange="binance",
            price=50000.0,
            volume_24h=1000000.0,
            timestamp=int(time.time() * 1000),
        )
        assert data.symbol == "BTC/USDT"
        assert data.price == 50000.0
        assert data.bid == 0.0
        assert data.ask == 0.0

    def test_defaults(self):
        data = MarketData(
            symbol="BTC/USDT",
            exchange="binance",
            price=50000.0,
            volume_24h=0.0,
            timestamp=0,
        )
        assert data.high_24h == 0.0
        assert data.low_24h == 0.0
        assert data.change_24h == 0.0
        assert data.funding_rate == 0.0
        assert data.open_interest == 0.0


class TestDataManager:
    """Test DataManager class."""

    @pytest.fixture
    def manager(self):
        return DataManager()

    def test_init(self, manager):
        assert manager.exchanges == {}
        assert manager.market_data == {}
        assert manager.running is False
        assert manager.callbacks == []

    def test_add_callback(self, manager):
        callback = MagicMock()
        manager.add_callback(callback)
        assert callback in manager.callbacks

    def test_update_market_data_new(self, manager):
        manager._update_market_data("BTC/USDT", "binance", 50000.0)
        assert "BTC/USDT" in manager.market_data
        assert "binance" in manager.market_data["BTC/USDT"]
        assert manager.market_data["BTC/USDT"]["binance"].price == 50000.0

    def test_update_market_data_existing(self, manager):
        manager._update_market_data("BTC/USDT", "binance", 50000.0)
        manager._update_market_data("BTC/USDT", "binance", 51000.0)
        assert manager.market_data["BTC/USDT"]["binance"].price == 51000.0

    def test_update_market_data_with_colon(self, manager):
        manager._update_market_data("BTC/USDT:USDT", "binance", 50000.0)
        assert "BTC/USDT" in manager.market_data

    def test_notify_callbacks(self, manager):
        callback = MagicMock()
        manager.add_callback(callback)

        data = MarketData("BTC/USDT", "binance", 50000.0, 0.0, 0)
        manager._notify_callbacks(data)

        callback.assert_called_once_with(data)

    def test_notify_callbacks_error(self, manager):
        callback = MagicMock(side_effect=Exception("Error"))
        manager.add_callback(callback)

        data = MarketData("BTC/USDT", "binance", 50000.0, 0.0, 0)
        # Should not raise
        manager._notify_callbacks(data)

    def test_get_market_data(self, manager):
        manager._update_market_data("BTC/USDT", "binance", 50000.0)

        data = manager.get_market_data("BTC/USDT")
        assert data is not None
        assert data.price == 50000.0

    def test_get_market_data_with_exchange(self, manager):
        manager._update_market_data("BTC/USDT", "binance", 50000.0)
        manager._update_market_data("BTC/USDT", "okx", 51000.0)

        data = manager.get_market_data("BTC/USDT", ExchangeType.BINANCE)
        assert data.price == 50000.0

    def test_get_market_data_not_found(self, manager):
        data = manager.get_market_data("BTC/USDT")
        assert data is None

    def test_get_all_market_data(self, manager):
        manager._update_market_data("BTC/USDT", "binance", 50000.0)
        manager._update_market_data("BTC/USDT", "okx", 51000.0)

        all_data = manager.get_all_market_data("BTC/USDT")
        assert len(all_data) == 2

    def test_get_all_market_data_empty(self, manager):
        all_data = manager.get_all_market_data("BTC/USDT")
        assert all_data == {}

    def test_get_price(self, manager):
        manager._update_market_data("BTC/USDT", "binance", 50000.0)

        price = manager.get_price("BTC/USDT")
        assert price == 50000.0

    def test_get_price_with_exchange(self, manager):
        manager._update_market_data("BTC/USDT", "binance", 50000.0)

        price = manager.get_price("BTC/USDT", "binance")
        assert price == 50000.0

    def test_get_price_not_found(self, manager):
        price = manager.get_price("BTC/USDT")
        assert price is None

    def test_get_volume(self, manager):
        manager._update_market_data("BTC/USDT", "binance", 50000.0)
        manager.market_data["BTC/USDT"]["binance"].volume_24h = 1000000.0

        volume = manager.get_volume("BTC/USDT")
        assert volume == 1000000.0

    def test_get_volume_not_found(self, manager):
        volume = manager.get_volume("BTC/USDT")
        assert volume is None

    def test_get_funding_rate(self, manager):
        manager._update_market_data("BTC/USDT", "binance", 50000.0)
        manager.market_data["BTC/USDT"]["binance"].funding_rate = 0.0001

        rate = manager.get_funding_rate("BTC/USDT")
        assert rate == 0.0001

    def test_get_open_interest(self, manager):
        manager._update_market_data("BTC/USDT", "binance", 50000.0)
        manager.market_data["BTC/USDT"]["binance"].open_interest = 1000000.0

        oi = manager.get_open_interest("BTC/USDT")
        assert oi == 1000000.0


class TestDataService:
    """Test DataService class."""

    @pytest.fixture
    def service(self):
        return DataService()

    def test_init(self, service):
        assert service.is_initialized is False
        assert service._cache == {}
        assert service._cache_ttl == 5

    def test_get_price_with_cache(self, service):
        service.data_manager._update_market_data("BTC/USDT", "binance", 50000.0)

        # First call
        price1 = service.get_price("BTC/USDT")
        assert price1 == 50000.0

        # Second call should use cache
        price2 = service.get_price("BTC/USDT")
        assert price2 == 50000.0

    def test_get_price_cache_expired(self, service):
        service.data_manager._update_market_data("BTC/USDT", "binance", 50000.0)

        # First call
        service.get_price("BTC/USDT")

        # Expire cache
        service._cache["BTC/USDT:None"] = (time.time() - 10, 50000.0)

        # Update price
        service.data_manager._update_market_data("BTC/USDT", "binance", 51000.0)

        # Should get new price
        price = service.get_price("BTC/USDT")
        assert price == 51000.0

    def test_get_volume(self, service):
        service.data_manager._update_market_data("BTC/USDT", "binance", 50000.0)
        service.data_manager.market_data["BTC/USDT"]["binance"].volume_24h = 1000000.0

        volume = service.get_volume("BTC/USDT")
        assert volume == 1000000.0

    def test_get_funding_rate(self, service):
        service.data_manager._update_market_data("BTC/USDT", "binance", 50000.0)
        service.data_manager.market_data["BTC/USDT"]["binance"].funding_rate = 0.0001

        rate = service.get_funding_rate("BTC/USDT")
        assert rate == 0.0001

    def test_get_open_interest(self, service):
        service.data_manager._update_market_data("BTC/USDT", "binance", 50000.0)
        service.data_manager.market_data["BTC/USDT"]["binance"].open_interest = 1000000.0

        oi = service.get_open_interest("BTC/USDT")
        assert oi == 1000000.0

    def test_get_market_data(self, service):
        service.data_manager._update_market_data("BTC/USDT", "binance", 50000.0)

        data = service.get_market_data("BTC/USDT")
        assert data is not None
        assert data.price == 50000.0

    def test_get_all_symbols(self, service):
        service.data_manager._update_market_data("BTC/USDT", "binance", 50000.0)
        service.data_manager._update_market_data("ETH/USDT", "okx", 3000.0)

        symbols = service.get_all_symbols()
        assert set(symbols) == {"BTC/USDT", "ETH/USDT"}

    def test_add_callback(self, service):
        callback = MagicMock()
        service.add_callback(callback)
        assert callback in service.data_manager.callbacks
