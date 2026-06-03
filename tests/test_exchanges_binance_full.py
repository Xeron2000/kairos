"""Comprehensive tests for BinanceExchange."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kairos.exchanges.binance import BinanceExchange


@pytest.fixture
def mock_binance_exchange():
    """Create a BinanceExchange with mocked ccxt."""
    with patch("kairos.exchanges.base.ccxt.exchanges", ["binance"]), \
         patch("kairos.exchanges.base.ccxt.binance") as mock_cls:
        mock_cls.return_value = MagicMock()
        exchange = BinanceExchange()
        yield exchange


class TestBinanceExchangeInit:
    """Test BinanceExchange initialization."""

    def test_init_sets_exchange_name(self, mock_binance_exchange):
        assert mock_binance_exchange.exchange_name == "binance"

    def test_init_sets_default_type_future(self, mock_binance_exchange):
        # options is a MagicMock, verify it was set
        mock_binance_exchange.exchange.options.__setitem__.assert_called_with("defaultType", "future")

    def test_init_ws_not_connected(self, mock_binance_exchange):
        assert not mock_binance_exchange.ws_connected


class TestBinanceWsConnect:
    """Test BinanceExchange._ws_connect."""

    @pytest.mark.asyncio
    async def test_ws_connect_establishes_connection(self, mock_binance_exchange):
        """Test that WebSocket connection is established and symbols subscribed."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        # First recv returns ticker data, then raises to exit loop
        ticker_data = json.dumps({"s": "BTCUSDT", "c": "50000.00", "q": "1000000"})
        mock_ws.recv = AsyncMock(side_effect=[ticker_data, ConnectionError()])

        mock_binance_exchange.running = True

        with patch("kairos.exchanges.binance.websockets.connect", return_value=mock_ws):
            await mock_binance_exchange._ws_connect(["BTC/USDT:USDT"])

        # After connection error, ws_connected should be False
        assert mock_binance_exchange.ws_connected is False

    @pytest.mark.asyncio
    async def test_ws_connect_retries_on_failure(self, mock_binance_exchange):
        """Test that connection retries on failure."""
        call_count = [0]  # Use list for mutation in closure

        async def failing_connect(*args, **kwargs):
            call_count[0] += 1
            raise ConnectionError("Connection failed")

        mock_binance_exchange.running = True

        with patch("kairos.exchanges.binance.websockets.connect", side_effect=failing_connect):
            with patch("kairos.exchanges.binance.asyncio.sleep", new_callable=AsyncMock):
                await mock_binance_exchange._ws_connect(["BTC/USDT:USDT"])

        # Should retry at least once
        assert call_count[0] >= 1

    @pytest.mark.asyncio
    async def test_ws_connect_stops_when_not_running(self, mock_binance_exchange):
        """Test that connection loop stops when running is False."""
        mock_binance_exchange.running = False

        with patch("kairos.exchanges.binance.websockets.connect") as mock_connect:
            await mock_binance_exchange._ws_connect(["BTC/USDT:USDT"])
            mock_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_ws_connect_processes_ticker_data(self, mock_binance_exchange):
        """Test that ticker data is correctly processed."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        ticker_data = json.dumps({"s": "BTCUSDT", "c": "50000.00", "q": "1000000"})
        mock_ws.recv = AsyncMock(side_effect=[ticker_data, asyncio.CancelledError()])

        mock_binance_exchange.running = True

        with patch("kairos.exchanges.binance.websockets.connect", return_value=mock_ws):
            with pytest.raises(asyncio.CancelledError):
                await mock_binance_exchange._ws_connect(["BTC/USDT:USDT"])

        # Price should be stored
        assert mock_binance_exchange.last_prices.get("BTC/USDT:USDT") == 50000.0

    @pytest.mark.asyncio
    async def test_ws_connect_handles_ping(self, mock_binance_exchange):
        """Test that ping messages are handled."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        ping_data = json.dumps({"e": "ping"})
        ticker_data = json.dumps({"s": "BTCUSDT", "c": "50000.00"})
        mock_ws.recv = AsyncMock(side_effect=[ping_data, ticker_data, asyncio.CancelledError()])
        mock_ws.pong = AsyncMock()

        mock_binance_exchange.running = True

        with patch("kairos.exchanges.binance.websockets.connect", return_value=mock_ws):
            with pytest.raises(asyncio.CancelledError):
                await mock_binance_exchange._ws_connect(["BTC/USDT:USDT"])

        mock_ws.pong.assert_called_once()

    @pytest.mark.asyncio
    async def test_ws_connect_handles_data_processing_error(self, mock_binance_exchange):
        """Test that data processing errors break inner loop."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        # First call raises error, then connection exits
        mock_ws.recv = AsyncMock(side_effect=[ValueError("Bad data"), ConnectionError()])

        mock_binance_exchange.running = True

        with patch("kairos.exchanges.binance.websockets.connect", return_value=mock_ws):
            await mock_binance_exchange._ws_connect(["BTC/USDT:USDT"])

    @pytest.mark.asyncio
    async def test_ws_connect_formats_symbols_correctly(self, mock_binance_exchange):
        """Test that symbols are correctly formatted for Binance URI."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)
        mock_ws.recv = AsyncMock(side_effect=[asyncio.CancelledError()])

        mock_binance_exchange.running = True

        with patch("kairos.exchanges.binance.websockets.connect", return_value=mock_ws) as mock_connect:
            with pytest.raises(asyncio.CancelledError):
                await mock_binance_exchange._ws_connect(["BTC/USDT:USDT", "ETH/USDT:USDT"])

            call_args = mock_connect.call_args[0][0]
            assert "btcusdt@ticker" in call_args
            assert "ethusdt@ticker" in call_args

    @pytest.mark.asyncio
    async def test_ws_connect_canonical_symbol_without_colon(self, mock_binance_exchange):
        """Test symbol canonicalization when no colon in original symbol."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        ticker_data = json.dumps({"s": "BTCUSDT", "c": "50000.00"})
        mock_ws.recv = AsyncMock(side_effect=[ticker_data, asyncio.CancelledError()])

        mock_binance_exchange.running = True

        with patch("kairos.exchanges.binance.websockets.connect", return_value=mock_ws):
            with pytest.raises(asyncio.CancelledError):
                await mock_binance_exchange._ws_connect(["BTC/USDT"])

        # Should add :USDT suffix
        assert "BTC/USDT:USDT" in mock_binance_exchange.last_prices
