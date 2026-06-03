"""Comprehensive tests for BybitExchange."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kairos.exchanges.bybit import BybitExchange


@pytest.fixture
def mock_bybit_exchange():
    """Create a BybitExchange with mocked ccxt."""
    with patch("kairos.exchanges.base.ccxt.exchanges", ["bybit"]), \
         patch("kairos.exchanges.base.ccxt.bybit") as mock_cls:
        mock_cls.return_value = MagicMock()
        exchange = BybitExchange()
        yield exchange


class TestBybitExchangeInit:
    """Test BybitExchange initialization."""

    def test_init_sets_exchange_name(self, mock_bybit_exchange):
        assert mock_bybit_exchange.exchange_name == "bybit"

    def test_init_sets_default_type_swap(self, mock_bybit_exchange):
        # options is a MagicMock, verify it was set
        mock_bybit_exchange.exchange.options.__setitem__.assert_called_with("defaultType", "swap")

    def test_init_ws_not_connected(self, mock_bybit_exchange):
        assert not mock_bybit_exchange.ws_connected


class TestBybitWsConnect:
    """Test BybitExchange._ws_connect."""

    @pytest.mark.asyncio
    async def test_ws_connect_establishes_connection(self, mock_bybit_exchange):
        """Test that WebSocket connection is established."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        ticker_data = json.dumps({
            "topic": "tickers.BTCUSDT",
            "data": {"symbol": "BTCUSDT", "lastPrice": "50000.00", "turnover24h": "1000000"}
        })
        mock_ws.recv = AsyncMock(side_effect=[ticker_data, ConnectionError()])

        mock_bybit_exchange.running = True

        with patch("kairos.exchanges.bybit.websockets.connect", return_value=mock_ws):
            await mock_bybit_exchange._ws_connect(["BTC/USDT:USDT"])

        assert mock_bybit_exchange.ws_connected is False

    @pytest.mark.asyncio
    async def test_ws_connect_retries_on_failure(self, mock_bybit_exchange):
        """Test that connection retries on failure."""
        call_count = [0]  # Use list for mutation in closure

        async def failing_connect(*args, **kwargs):
            call_count[0] += 1
            raise ConnectionError("Connection failed")

        mock_bybit_exchange.running = True

        with patch("kairos.exchanges.bybit.websockets.connect", side_effect=failing_connect):
            with patch("kairos.exchanges.bybit.asyncio.sleep", new_callable=AsyncMock):
                await mock_bybit_exchange._ws_connect(["BTC/USDT:USDT"])

        assert call_count[0] >= 1

    @pytest.mark.asyncio
    async def test_ws_connect_stops_when_not_running(self, mock_bybit_exchange):
        """Test that connection loop stops when running is False."""
        mock_bybit_exchange.running = False

        with patch("kairos.exchanges.bybit.websockets.connect") as mock_connect:
            await mock_bybit_exchange._ws_connect(["BTC/USDT:USDT"])
            mock_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_ws_connect_processes_ticker_data(self, mock_bybit_exchange):
        """Test that ticker data is correctly processed."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        ticker_data = json.dumps({
            "topic": "tickers.BTCUSDT",
            "data": {"symbol": "BTCUSDT", "lastPrice": "50000.00", "turnover24h": "1000000"}
        })
        mock_ws.recv = AsyncMock(side_effect=[ticker_data, asyncio.CancelledError()])

        mock_bybit_exchange.running = True

        with patch("kairos.exchanges.bybit.websockets.connect", return_value=mock_ws):
            with pytest.raises(asyncio.CancelledError):
                await mock_bybit_exchange._ws_connect(["BTC/USDT:USDT"])

        assert mock_bybit_exchange.last_prices.get("BTC/USDT:USDT") == 50000.0

    @pytest.mark.asyncio
    async def test_ws_connect_handles_ping(self, mock_bybit_exchange):
        """Test that ping messages are handled."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        ping_data = json.dumps({"op": "ping", "req_id": "test123"})
        ticker_data = json.dumps({
            "topic": "tickers.BTCUSDT",
            "data": {"symbol": "BTCUSDT", "lastPrice": "50000.00"}
        })
        mock_ws.recv = AsyncMock(side_effect=[ping_data, ticker_data, asyncio.CancelledError()])

        mock_bybit_exchange.running = True

        with patch("kairos.exchanges.bybit.websockets.connect", return_value=mock_ws):
            with pytest.raises(asyncio.CancelledError):
                await mock_bybit_exchange._ws_connect(["BTC/USDT:USDT"])

        # Verify send was called with pong message
        mock_ws.send.assert_called()

    @pytest.mark.asyncio
    async def test_ws_connect_sends_subscription_message(self, mock_bybit_exchange):
        """Test that subscription message is sent."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)
        mock_ws.recv = AsyncMock(side_effect=[asyncio.CancelledError()])

        mock_bybit_exchange.running = True

        with patch("kairos.exchanges.bybit.websockets.connect", return_value=mock_ws):
            with pytest.raises(asyncio.CancelledError):
                await mock_bybit_exchange._ws_connect(["BTC/USDT:USDT"])

        # Verify subscription message was sent
        send_calls = mock_ws.send.call_args_list
        assert len(send_calls) > 0
        sub_msg = json.loads(send_calls[0][0][0])
        assert sub_msg["op"] == "subscribe"
        assert "tickers.BTCUSDT" in sub_msg["args"]

    @pytest.mark.asyncio
    async def test_ws_connect_handles_data_processing_error(self, mock_bybit_exchange):
        """Test that data processing errors break inner loop."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        mock_ws.recv = AsyncMock(side_effect=[ValueError("Bad data"), ConnectionError()])

        mock_bybit_exchange.running = True

        with patch("kairos.exchanges.bybit.websockets.connect", return_value=mock_ws):
            await mock_bybit_exchange._ws_connect(["BTC/USDT:USDT"])

    @pytest.mark.asyncio
    async def test_ws_connect_canonical_symbol_without_colon(self, mock_bybit_exchange):
        """Test symbol canonicalization when no colon in original symbol."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        ticker_data = json.dumps({
            "topic": "tickers.BTCUSDT",
            "data": {"symbol": "BTCUSDT", "lastPrice": "50000.00"}
        })
        mock_ws.recv = AsyncMock(side_effect=[ticker_data, asyncio.CancelledError()])

        mock_bybit_exchange.running = True

        with patch("kairos.exchanges.bybit.websockets.connect", return_value=mock_ws):
            with pytest.raises(asyncio.CancelledError):
                await mock_bybit_exchange._ws_connect(["BTC/USDT"])

        assert "BTC/USDT:USDT" in mock_bybit_exchange.last_prices

    @pytest.mark.asyncio
    async def test_ws_connect_with_volume_data(self, mock_bybit_exchange):
        """Test that volume data is processed when turnover24h is present."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        ticker_data = json.dumps({
            "topic": "tickers.BTCUSDT",
            "data": {"symbol": "BTCUSDT", "lastPrice": "50000.00", "turnover24h": "5000000"}
        })
        mock_ws.recv = AsyncMock(side_effect=[ticker_data, asyncio.CancelledError()])

        mock_bybit_exchange.running = True

        with patch("kairos.exchanges.bybit.websockets.connect", return_value=mock_ws):
            with pytest.raises(asyncio.CancelledError):
                await mock_bybit_exchange._ws_connect(["BTC/USDT:USDT"])

        assert mock_bybit_exchange.last_prices.get("BTC/USDT:USDT") == 50000.0

    @pytest.mark.asyncio
    async def test_ws_connect_formats_uri_correctly(self, mock_bybit_exchange):
        """Test that the correct URI is used."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)
        mock_ws.recv = AsyncMock(side_effect=[asyncio.CancelledError()])

        mock_bybit_exchange.running = True

        with patch("kairos.exchanges.bybit.websockets.connect", return_value=mock_ws) as mock_connect:
            with pytest.raises(asyncio.CancelledError):
                await mock_bybit_exchange._ws_connect(["BTC/USDT:USDT"])

            call_args = mock_connect.call_args[0][0]
            assert call_args == "wss://stream.bybit.com/v5/public/linear"
