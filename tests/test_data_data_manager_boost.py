"""
Comprehensive tests for kairos.data.data_manager module.
Target: 95%+ coverage.
"""

import asyncio
import time
import threading
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
import pytest

from kairos.data.data_manager import (
    ExchangeType,
    MarketData,
    DataManager,
    DataService,
)


# ──────────────────────────────────────────────────────────────────────
# ExchangeType enum
# ──────────────────────────────────────────────────────────────────────

class TestExchangeType:
    def test_values(self):
        assert ExchangeType.BINANCE == "binance"
        assert ExchangeType.OKX == "okx"
        assert ExchangeType.BYBIT == "bybit"

    def test_from_string(self):
        assert ExchangeType("binance") == ExchangeType.BINANCE
        assert ExchangeType("okx") == ExchangeType.OKX
        assert ExchangeType("bybit") == ExchangeType.BYBIT

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            ExchangeType("unknown")


# ──────────────────────────────────────────────────────────────────────
# MarketData dataclass
# ──────────────────────────────────────────────────────────────────────

class TestMarketData:
    def test_defaults(self):
        md = MarketData(symbol="BTCUSDT", exchange="binance", price=50000.0,
                        volume_24h=100.0, timestamp=1234567890)
        assert md.symbol == "BTCUSDT"
        assert md.exchange == "binance"
        assert md.price == 50000.0
        assert md.volume_24h == 100.0
        assert md.timestamp == 1234567890
        assert md.bid == 0.0
        assert md.ask == 0.0
        assert md.high_24h == 0.0
        assert md.low_24h == 0.0
        assert md.change_24h == 0.0
        assert md.funding_rate == 0.0
        assert md.open_interest == 0.0

    def test_custom_values(self):
        md = MarketData(
            symbol="ETHUSDT", exchange="okx", price=3000.0,
            volume_24h=500.0, timestamp=9999,
            bid=2999.0, ask=3001.0, high_24h=3100.0,
            low_24h=2900.0, change_24h=2.5,
            funding_rate=0.001, open_interest=10000.0,
        )
        assert md.bid == 2999.0
        assert md.funding_rate == 0.001
        assert md.open_interest == 10000.0


# ──────────────────────────────────────────────────────────────────────
# DataManager
# ──────────────────────────────────────────────────────────────────────

class TestDataManagerInit:
    def test_init_defaults(self):
        dm = DataManager()
        assert dm.exchanges == {}
        assert dm.market_data == {}
        assert dm.running is False
        assert dm.callbacks == []
        assert isinstance(dm._lock, threading.Lock)


class TestDataManagerInitialize:
    @pytest.mark.asyncio
    async def test_initialize_default_exchanges(self):
        dm = DataManager()
        with patch("kairos.data.data_manager.OkxExchange") as MockOkx, \
             patch("kairos.data.data_manager.BybitExchange") as MockBybit:
            await dm.initialize()
            assert ExchangeType.OKX in dm.exchanges
            assert ExchangeType.BYBIT in dm.exchanges
            assert ExchangeType.BINANCE not in dm.exchanges
            MockOkx.assert_called_once()
            MockBybit.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_with_binance(self):
        dm = DataManager()
        with patch("kairos.data.data_manager.BinanceExchange") as MockBn, \
             patch("kairos.data.data_manager.OkxExchange"), \
             patch("kairos.data.data_manager.BybitExchange"):
            await dm.initialize([ExchangeType.BINANCE])
            assert ExchangeType.BINANCE in dm.exchanges
            MockBn.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_exception_handled(self):
        dm = DataManager()
        with patch("kairos.data.data_manager.OkxExchange", side_effect=Exception("init fail")), \
             patch("kairos.data.data_manager.BybitExchange"):
            # Should not raise
            await dm.initialize([ExchangeType.OKX, ExchangeType.BYBIT])
            assert ExchangeType.OKX not in dm.exchanges
            assert ExchangeType.BYBIT in dm.exchanges


class TestDataManagerUpdateMarketData:
    def test_update_creates_new_entry(self):
        dm = DataManager()
        dm._update_market_data("BTCUSDT", "binance", 50000.0)
        assert "BTCUSDT" in dm.market_data
        assert "binance" in dm.market_data["BTCUSDT"]
        data = dm.market_data["BTCUSDT"]["binance"]
        assert data.price == 50000.0
        assert data.symbol == "BTCUSDT"

    def test_update_normalizes_colon_suffix(self):
        dm = DataManager()
        dm._update_market_data("BTCUSDT:USDT", "okx", 50000.0)
        assert "BTCUSDT" in dm.market_data
        assert "BTCUSDT:USDT" not in dm.market_data

    def test_update_existing_entry_updates_price(self):
        dm = DataManager()
        dm._update_market_data("BTCUSDT", "binance", 50000.0)
        old_ts = dm.market_data["BTCUSDT"]["binance"].timestamp
        # Small delay so timestamp differs
        dm._update_market_data("BTCUSDT", "binance", 51000.0)
        assert dm.market_data["BTCUSDT"]["binance"].price == 51000.0

    def test_update_notifies_callbacks(self):
        dm = DataManager()
        callback = MagicMock()
        dm.add_callback(callback)
        dm._update_market_data("BTCUSDT", "binance", 50000.0)
        callback.assert_called_once()
        data = callback.call_args[0][0]
        assert data.price == 50000.0

    def test_update_callback_exception_handled(self):
        dm = DataManager()
        bad_callback = MagicMock(side_effect=Exception("cb error"))
        good_callback = MagicMock()
        dm.add_callback(bad_callback)
        dm.add_callback(good_callback)
        # Should not raise
        dm._update_market_data("BTCUSDT", "binance", 50000.0)
        good_callback.assert_called_once()


class TestDataManagerNotifyCallbacks:
    def test_notify_empty_callbacks(self):
        dm = DataManager()
        md = MarketData(symbol="X", exchange="y", price=1.0,
                        volume_24h=0, timestamp=0)
        # Should not raise
        dm._notify_callbacks(md)

    def test_notify_multiple_callbacks(self):
        dm = DataManager()
        c1 = MagicMock()
        c2 = MagicMock()
        dm.add_callback(c1)
        dm.add_callback(c2)
        md = MarketData(symbol="X", exchange="y", price=1.0,
                        volume_24h=0, timestamp=0)
        dm._notify_callbacks(md)
        c1.assert_called_once_with(md)
        c2.assert_called_once_with(md)


class TestDataManagerGetMethods:
    @pytest.fixture
    def populated_dm(self):
        dm = DataManager()
        dm._update_market_data("BTCUSDT", "binance", 50000.0)
        dm._update_market_data("BTCUSDT", "okx", 50001.0)
        dm._update_market_data("ETHUSDT", "binance", 3000.0)
        return dm

    def test_get_market_data_with_exchange(self, populated_dm):
        data = populated_dm.get_market_data("BTCUSDT", ExchangeType.BINANCE)
        assert data is not None
        assert data.price == 50000.0
        assert data.exchange == "binance"

    def test_get_market_data_without_exchange_returns_first(self, populated_dm):
        data = populated_dm.get_market_data("BTCUSDT")
        assert data is not None
        assert data.symbol == "BTCUSDT"

    def test_get_market_data_nonexistent_symbol(self, populated_dm):
        assert populated_dm.get_market_data("DOGEUSDT") is None

    def test_get_market_data_wrong_exchange(self, populated_dm):
        assert populated_dm.get_market_data("BTCUSDT", ExchangeType.BYBIT) is None

    def test_get_all_market_data(self, populated_dm):
        result = populated_dm.get_all_market_data("BTCUSDT")
        assert len(result) == 2
        assert "binance" in result
        assert "okx" in result

    def test_get_all_market_data_nonexistent(self, populated_dm):
        assert populated_dm.get_all_market_data("DOGEUSDT") == {}

    def test_get_price(self, populated_dm):
        assert populated_dm.get_price("BTCUSDT", "binance") == 50000.0

    def test_get_price_no_exchange(self, populated_dm):
        price = populated_dm.get_price("BTCUSDT")
        assert price is not None

    def test_get_price_nonexistent(self, populated_dm):
        assert populated_dm.get_price("DOGEUSDT") is None

    def test_get_volume(self, populated_dm):
        populated_dm._update_market_data("BTCUSDT", "binance", 50000.0)
        vol = populated_dm.get_volume("BTCUSDT", "binance")
        assert vol is not None

    def test_get_volume_nonexistent(self, populated_dm):
        assert populated_dm.get_volume("DOGEUSDT") is None

    def test_get_funding_rate(self, populated_dm):
        assert populated_dm.get_funding_rate("BTCUSDT", "binance") == 0.0

    def test_get_funding_rate_nonexistent(self, populated_dm):
        assert populated_dm.get_funding_rate("DOGEUSDT") is None

    def test_get_open_interest(self, populated_dm):
        assert populated_dm.get_open_interest("BTCUSDT", "binance") == 0.0

    def test_get_open_interest_nonexistent(self, populated_dm):
        assert populated_dm.get_open_interest("DOGEUSDT") is None


class TestDataManagerStartStop:
    @pytest.mark.asyncio
    async def test_start_calls_exchange_websocket(self):
        dm = DataManager()
        mock_exchange = MagicMock()
        dm.exchanges[ExchangeType.OKX] = mock_exchange

        with patch("kairos.data.data_manager.PriceDetector") as MockDetector:
            mock_detector = MagicMock()
            MockDetector.return_value = mock_detector

            async def fake_sleep(t):
                dm.running = False  # Stop after first loop
            with patch("asyncio.sleep", side_effect=fake_sleep):
                await dm.start(["BTCUSDT"])

            mock_detector.add_callback.assert_called_once()
            mock_exchange.register_detector.assert_called_once_with(mock_detector)
            mock_exchange.start_websocket.assert_called_once_with(["BTCUSDT"])

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self):
        dm = DataManager()
        dm.running = True
        mock_exchange = MagicMock()
        dm.exchanges[ExchangeType.OKX] = mock_exchange
        await dm.stop()
        assert dm.running is False
        mock_exchange.stop_websocket.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_handles_exception(self):
        dm = DataManager()
        dm.running = True
        mock_exchange = MagicMock(side_effect=Exception("stop err"))
        dm.exchanges[ExchangeType.OKX] = mock_exchange
        # Should not raise
        await dm.stop()
        assert dm.running is False

    @pytest.mark.asyncio
    async def test_start_exchange_websocket_exception(self):
        dm = DataManager()
        mock_exchange = MagicMock()
        mock_exchange.register_detector.side_effect = Exception("ws fail")
        dm.exchanges[ExchangeType.OKX] = mock_exchange

        with patch("kairos.data.data_manager.PriceDetector"):
            # Should not raise
            await dm._start_exchange_websocket(
                ExchangeType.OKX, mock_exchange, ["BTCUSDT"]
            )


# ──────────────────────────────────────────────────────────────────────
# DataService
# ──────────────────────────────────────────────────────────────────────

class TestDataServiceInit:
    def test_init_defaults(self):
        ds = DataService()
        assert isinstance(ds.data_manager, DataManager)
        assert ds.is_initialized is False
        assert ds._cache == {}
        assert ds._cache_ttl == 5


class TestDataServiceInitialize:
    @pytest.mark.asyncio
    async def test_initialize_default(self):
        ds = DataService()
        with patch.object(ds.data_manager, "initialize", new_callable=AsyncMock) as mock_init:
            await ds.initialize()
            mock_init.assert_called_once()
            args = mock_init.call_args[0][0]
            assert ExchangeType.OKX in args
            assert ExchangeType.BYBIT in args
            assert ds.is_initialized is True

    @pytest.mark.asyncio
    async def test_initialize_with_binance(self):
        ds = DataService()
        with patch.object(ds.data_manager, "initialize", new_callable=AsyncMock):
            await ds.initialize(["binance", "okx"])
            assert ds.is_initialized is True

    @pytest.mark.asyncio
    async def test_initialize_unknown_exchange_skipped(self):
        ds = DataService()
        with patch.object(ds.data_manager, "initialize", new_callable=AsyncMock) as mock_init:
            await ds.initialize(["okx", "unsupported"])
            args = mock_init.call_args[0][0]
            assert len(args) == 1
            assert ExchangeType.OKX in args


class TestDataServiceStart:
    @pytest.mark.asyncio
    async def test_start_initializes_if_needed(self):
        ds = DataService()
        with patch.object(ds, "initialize", new_callable=AsyncMock) as mock_init, \
             patch.object(ds.data_manager, "start", new_callable=AsyncMock) as mock_start:
            await ds.start(["BTCUSDT"])
            mock_init.assert_called_once()
            mock_start.assert_called_once_with(["BTCUSDT"])

    @pytest.mark.asyncio
    async def test_start_skips_init_if_initialized(self):
        ds = DataService()
        ds.is_initialized = True
        with patch.object(ds, "initialize", new_callable=AsyncMock) as mock_init, \
             patch.object(ds.data_manager, "start", new_callable=AsyncMock) as mock_start:
            await ds.start(["BTCUSDT"])
            mock_init.assert_not_called()
            mock_start.assert_called_once()


class TestDataServiceGetPrice:
    def test_get_price_from_manager(self):
        ds = DataService()
        ds.data_manager.get_price = MagicMock(return_value=50000.0)
        result = ds.get_price("BTCUSDT", "binance")
        assert result == 50000.0
        assert "BTCUSDT:binance" in ds._cache

    def test_get_price_cached(self):
        ds = DataService()
        ds._cache["BTCUSDT:binance"] = (time.time(), 50000.0)
        ds.data_manager.get_price = MagicMock(return_value=99999.0)
        result = ds.get_price("BTCUSDT", "binance")
        assert result == 50000.0  # From cache
        ds.data_manager.get_price.assert_not_called()

    def test_get_price_cache_expired(self):
        ds = DataService()
        ds._cache["BTCUSDT:binance"] = (time.time() - 10, 50000.0)
        ds.data_manager.get_price = MagicMock(return_value=51000.0)
        result = ds.get_price("BTCUSDT", "binance")
        assert result == 51000.0  # Refreshed

    def test_get_price_none_not_cached(self):
        ds = DataService()
        ds.data_manager.get_price = MagicMock(return_value=None)
        result = ds.get_price("DOGEUSDT")
        assert result is None
        assert "DOGEUSDT:None" not in ds._cache

    def test_get_price_no_exchange(self):
        ds = DataService()
        ds.data_manager.get_price = MagicMock(return_value=3000.0)
        result = ds.get_price("ETHUSDT")
        assert result == 3000.0


class TestDataServiceOtherGets:
    def test_get_volume(self):
        ds = DataService()
        ds.data_manager.get_volume = MagicMock(return_value=100.0)
        assert ds.get_volume("BTCUSDT", "binance") == 100.0

    def test_get_funding_rate(self):
        ds = DataService()
        ds.data_manager.get_funding_rate = MagicMock(return_value=0.001)
        assert ds.get_funding_rate("BTCUSDT") == 0.001

    def test_get_open_interest(self):
        ds = DataService()
        ds.data_manager.get_open_interest = MagicMock(return_value=500000.0)
        assert ds.get_open_interest("BTCUSDT", "okx") == 500000.0

    def test_get_market_data(self):
        ds = DataService()
        md = MarketData(symbol="BTCUSDT", exchange="binance", price=50000.0,
                        volume_24h=100.0, timestamp=0)
        ds.data_manager.get_market_data = MagicMock(return_value=md)
        result = ds.get_market_data("BTCUSDT", "binance")
        assert result == md
        ds.data_manager.get_market_data.assert_called_once_with(
            "BTCUSDT", ExchangeType.BINANCE
        )

    def test_get_market_data_no_exchange(self):
        ds = DataService()
        ds.data_manager.get_market_data = MagicMock(return_value=None)
        ds.get_market_data("BTCUSDT")
        ds.data_manager.get_market_data.assert_called_once_with("BTCUSDT", None)

    def test_get_all_symbols(self):
        ds = DataService()
        ds.data_manager.market_data = {"BTCUSDT": {}, "ETHUSDT": {}}
        assert set(ds.get_all_symbols()) == {"BTCUSDT", "ETHUSDT"}


class TestDataServiceCallback:
    def test_add_callback(self):
        ds = DataService()
        cb = MagicMock()
        ds.add_callback(cb)
        assert cb in ds.data_manager.callbacks


class TestDataServiceStop:
    @pytest.mark.asyncio
    async def test_stop(self):
        ds = DataService()
        with patch.object(ds.data_manager, "stop", new_callable=AsyncMock) as mock_stop:
            await ds.stop()
            mock_stop.assert_called_once()


# ──────────────────────────────────────────────────────────────────────
# Integration-level edge cases
# ──────────────────────────────────────────────────────────────────────

class TestDataManagerEdgeCases:
    def test_get_market_data_empty_exchanges_dict(self):
        """get_market_data returns first value when no exchange specified."""
        dm = DataManager()
        md = MarketData(symbol="X", exchange="y", price=1.0,
                        volume_24h=0, timestamp=0)
        dm.market_data["X"] = {"y": md}
        result = dm.get_market_data("X")
        assert result == md

    def test_get_market_data_no_exchange_no_data(self):
        """get_market_data returns None when symbol exists but dict empty."""
        dm = DataManager()
        dm.market_data["X"] = {}
        result = dm.get_market_data("X")
        assert result is None

    def test_update_multiple_exchanges_same_symbol(self):
        dm = DataManager()
        dm._update_market_data("BTCUSDT", "binance", 50000.0)
        dm._update_market_data("BTCUSDT", "okx", 50001.0)
        assert len(dm.market_data["BTCUSDT"]) == 2
        assert dm.market_data["BTCUSDT"]["binance"].price == 50000.0
        assert dm.market_data["BTCUSDT"]["okx"].price == 50001.0
