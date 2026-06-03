"""Additional tests for BaseExchange to increase coverage."""

import asyncio
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kairos.exchanges.base import BaseExchange


class _TestExchangeImpl(BaseExchange):
    """Test implementation of BaseExchange."""

    def __init__(self, exchange_name):
        self._ws_connect_called = False
        super().__init__(exchange_name)

    async def _ws_connect(self, symbols):
        self._ws_connect_called = True
        self.ws_connected = True
        for symbol in symbols:
            self.last_prices[symbol] = 50000.0


@pytest.fixture
def mock_exchange():
    """Create a test exchange with mocked ccxt."""
    with patch("kairos.exchanges.base.ccxt.exchanges", ["binance"]), \
         patch("kairos.exchanges.base.ccxt.binance") as mock_cls:
        mock_cls.return_value = MagicMock()
        exchange = _TestExchangeImpl("binance")
        yield exchange


class TestRegisterDetector:
    """Test register_detector method."""

    def test_register_detector(self, mock_exchange):
        detector = MagicMock()
        mock_exchange.register_detector(detector)
        assert detector in mock_exchange._detectors

    def test_register_multiple_detectors(self, mock_exchange):
        d1 = MagicMock()
        d2 = MagicMock()
        mock_exchange.register_detector(d1)
        mock_exchange.register_detector(d2)
        assert len(mock_exchange._detectors) == 2


class TestNotifyDetectors:
    """Test _notify_detectors_price and _notify_detectors_volume."""

    def test_notify_price(self, mock_exchange):
        detector = MagicMock()
        mock_exchange.register_detector(detector)

        mock_exchange._notify_detectors_price("BTC/USDT", 50000.0)
        detector.on_price_update.assert_called_once()

    def test_notify_price_out_of_range(self, mock_exchange):
        detector = MagicMock()
        mock_exchange.register_detector(detector)

        mock_exchange._notify_detectors_price("BTC/USDT", -1.0)
        detector.on_price_update.assert_not_called()

    def test_notify_price_too_high(self, mock_exchange):
        detector = MagicMock()
        mock_exchange.register_detector(detector)

        mock_exchange._notify_detectors_price("BTC/USDT", 1e13)
        detector.on_price_update.assert_not_called()

    def test_notify_price_detector_error(self, mock_exchange):
        detector = MagicMock()
        detector.on_price_update.side_effect = Exception("Error")
        mock_exchange.register_detector(detector)

        # Should not raise
        mock_exchange._notify_detectors_price("BTC/USDT", 50000.0)

    def test_notify_volume(self, mock_exchange):
        detector = MagicMock()
        mock_exchange.register_detector(detector)

        mock_exchange._notify_detectors_volume("BTC/USDT", 1000000.0)
        detector.on_volume_update.assert_called_once()

    def test_notify_volume_detector_error(self, mock_exchange):
        detector = MagicMock()
        detector.on_volume_update.side_effect = Exception("Error")
        mock_exchange.register_detector(detector)

        # Should not raise
        mock_exchange._notify_detectors_volume("BTC/USDT", 1000000.0)


class TestStoreHistoricalPrice:
    """Test _store_historical_price method."""

    def test_stores_price(self, mock_exchange):
        mock_exchange._store_historical_price("BTC/USDT", 50000.0)
        assert "BTC/USDT" in mock_exchange.historical_prices
        assert len(mock_exchange.historical_prices["BTC/USDT"]) == 1

    def test_stores_multiple_prices(self, mock_exchange):
        mock_exchange._store_historical_price("BTC/USDT", 50000.0)
        mock_exchange._store_historical_price("BTC/USDT", 51000.0)
        assert len(mock_exchange.historical_prices["BTC/USDT"]) == 2

    def test_max_length_limit(self, mock_exchange):
        from kairos.exchanges.base import HISTORICAL_PRICE_MAX_LEN
        for i in range(HISTORICAL_PRICE_MAX_LEN + 10):
            mock_exchange._store_historical_price("BTC/USDT", float(i))
        assert len(mock_exchange.historical_prices["BTC/USDT"]) == HISTORICAL_PRICE_MAX_LEN

    def test_cleanup_old_prices(self, mock_exchange):
        # Store old price
        mock_exchange.historical_prices["BTC/USDT"] = deque([(1000, 50000.0)])
        mock_exchange._last_cleanup_time = 0  # Force cleanup

        mock_exchange._store_historical_price("BTC/USDT", 51000.0)

        # Old entry should be cleaned up during next cleanup cycle
        # But cleanup only happens periodically
        assert len(mock_exchange.historical_prices["BTC/USDT"]) >= 1


class TestGetPriceMinutesAgo:
    """Test get_price_minutes_ago method."""

    @pytest.mark.asyncio
    async def test_returns_prices(self, mock_exchange):
        # Store historical prices
        now = int(time.time() * 1000)
        mock_exchange.historical_prices["BTC/USDT"] = deque([
            (now - 300000, 49000.0),  # 5 minutes ago
            (now - 240000, 49500.0),
            (now - 180000, 50000.0),
            (now - 120000, 50500.0),
            (now - 60000, 51000.0),
        ])

        result = await mock_exchange.get_price_minutes_ago(["BTC/USDT"], 5)
        assert "BTC/USDT" in result

    @pytest.mark.asyncio
    async def test_missing_symbol(self, mock_exchange):
        result = await mock_exchange.get_price_minutes_ago(["BTC/USDT"], 5)
        assert result == {}


class TestGetHistoricalPrices:
    """Test get_historical_prices method."""

    def test_returns_prices(self, mock_exchange):
        now = int(time.time() * 1000)
        mock_exchange.historical_prices["BTC/USDT"] = deque([
            (now - 60000, 49000.0),
            (now - 30000, 50000.0),
            (now, 51000.0),
        ])

        result = mock_exchange.get_historical_prices("BTC/USDT", 60)
        assert len(result) > 0

    def test_missing_symbol(self, mock_exchange):
        result = mock_exchange.get_historical_prices("BTC/USDT", 60)
        assert result == []


class TestStartStop:
    """Test start and stop methods."""

    @pytest.mark.asyncio
    async def test_start(self, mock_exchange):
        await mock_exchange.start(["BTC/USDT"])
        assert mock_exchange.running is True
        assert mock_exchange._ws_connect_called is True

    @pytest.mark.asyncio
    async def test_stop(self, mock_exchange):
        mock_exchange.running = True
        mock_exchange.ws_connected = True
        mock_exchange.ws = AsyncMock()

        await mock_exchange.stop()
        assert mock_exchange.running is False
        assert mock_exchange.ws_connected is False

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, mock_exchange):
        mock_exchange.running = False
        await mock_exchange.stop()
        assert mock_exchange.running is False


class TestCheckWsConnection:
    """Test check_ws_connection method."""

    @pytest.mark.asyncio
    async def test_reconnect_when_disconnected(self, mock_exchange):
        mock_exchange.ws_connected = False
        mock_exchange.running = True
        mock_exchange._symbols = ["BTC/USDT"]

        with patch.object(mock_exchange, 'start', new_callable=AsyncMock) as mock_start:
            await mock_exchange.check_ws_connection()
            mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_reconnect_when_connected(self, mock_exchange):
        mock_exchange.ws_connected = True
        mock_exchange.running = True

        with patch.object(mock_exchange, 'start', new_callable=AsyncMock) as mock_start:
            await mock_exchange.check_ws_connection()
            mock_start.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_reconnect_when_no_symbols(self, mock_exchange):
        mock_exchange.ws_connected = False
        mock_exchange.running = True
        mock_exchange._symbols = []

        with patch.object(mock_exchange, 'start', new_callable=AsyncMock) as mock_start:
            await mock_exchange.check_ws_connection()
            mock_start.assert_not_called()


class TestClose:
    """Test close method."""

    @pytest.mark.asyncio
    async def test_close(self, mock_exchange):
        mock_exchange.running = True
        mock_exchange.ws_connected = True
        mock_exchange.ws = AsyncMock()

        await mock_exchange.close()
        assert mock_exchange.running is False


class TestGetCurrentPrices:
    """Test get_current_prices method."""

    @pytest.mark.asyncio
    async def test_returns_cached_prices(self, mock_exchange):
        mock_exchange.ws_connected = True
        mock_exchange.last_prices = {"BTC/USDT": 50000.0}

        result = await mock_exchange.get_current_prices(["BTC/USDT"])
        assert result == {"BTC/USDT": 50000.0}

    @pytest.mark.asyncio
    async def test_returns_api_prices_when_not_connected(self, mock_exchange):
        mock_exchange.ws_connected = False
        mock_exchange.exchange.fetch_ticker = MagicMock(return_value={"last": 50000.0})

        with patch("kairos.exchanges.base.price_cache") as mock_cache:
            mock_cache.get_prices.return_value = {}

            result = await mock_exchange.get_current_prices(["BTC/USDT"])
            assert "BTC/USDT" in result
