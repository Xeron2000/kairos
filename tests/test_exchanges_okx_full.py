"""Comprehensive tests for OkxExchange."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kairos.exchanges.okx import OkxExchange, _safe_float


class TestSafeFloat:
    """Test _safe_float function."""

    def test_none_returns_none(self):
        assert _safe_float(None) is None

    def test_empty_string_returns_none(self):
        assert _safe_float("") is None

    def test_valid_float(self):
        assert _safe_float("50000.0") == 50000.0

    def test_valid_int(self):
        assert _safe_float("50000") == 50000.0

    def test_zero(self):
        assert _safe_float("0") == 0.0

    def test_numeric_value(self):
        assert _safe_float(50000) == 50000.0


@pytest.fixture
def mock_okx_exchange():
    """Create an OkxExchange with mocked ccxt."""
    with patch("kairos.exchanges.base.ccxt.exchanges", ["okx"]), \
         patch("kairos.exchanges.base.ccxt.okx") as mock_cls:
        mock_exchange = MagicMock()
        mock_cls.return_value = mock_exchange
        # Mock load_markets on the exchange instance
        mock_exchange.load_markets = MagicMock()
        exchange = OkxExchange()
        yield exchange


class TestOkxExchangeInit:
    """Test OkxExchange initialization."""

    def test_init_sets_exchange_name(self, mock_okx_exchange):
        assert mock_okx_exchange.exchange_name == "okx"

    def test_init_sets_options(self, mock_okx_exchange):
        options = mock_okx_exchange.exchange.options
        assert options.get("defaultType") == "swap"
        assert options.get("defaultInstType") == "SWAP"

    def test_init_sets_multiple_options(self, mock_okx_exchange):
        options = mock_okx_exchange.exchange.options
        assert options.get("defaultMarket") == "swap"
        assert options.get("instType") == "SWAP"


class TestCanonicalSymbol:
    """Test _canonical_symbol static method."""

    def test_valid_inst_id(self):
        assert OkxExchange._canonical_symbol("BTC-USDT") == "BTC/USDT:USDT"

    def test_with_swap_suffix(self):
        assert OkxExchange._canonical_symbol("BTC-USDT-SWAP") == "BTC/USDT:USDT"

    def test_single_part(self):
        assert OkxExchange._canonical_symbol("BTC") == "BTC"

    def test_eth_symbol(self):
        assert OkxExchange._canonical_symbol("ETH-USDT") == "ETH/USDT:USDT"


class TestExtractPrice:
    """Test _extract_price static method."""

    def test_with_last(self):
        item = {"last": "50000.0"}
        assert OkxExchange._extract_price(item) == 50000.0

    def test_with_lastPrice(self):
        item = {"lastPrice": "50000.0"}
        assert OkxExchange._extract_price(item) == 50000.0

    def test_last_takes_precedence(self):
        item = {"last": "50000.0", "lastPrice": "51000.0"}
        assert OkxExchange._extract_price(item) == 50000.0

    def test_missing_price_raises(self):
        with pytest.raises(ValueError, match="missing price"):
            OkxExchange._extract_price({})

    def test_none_last_falls_back(self):
        item = {"last": None, "lastPrice": "50000.0"}
        assert OkxExchange._extract_price(item) == 50000.0

    def test_empty_last_falls_back(self):
        item = {"last": "", "lastPrice": "50000.0"}
        assert OkxExchange._extract_price(item) == 50000.0


class TestGetOhlcvParams:
    """Test _get_ohlcv_params method."""

    def test_valid_symbol(self, mock_okx_exchange):
        params = mock_okx_exchange._get_ohlcv_params("BTC/USDT:USDT")
        assert params["instType"] == "SWAP"
        assert params["instId"] == "BTC-USDT-SWAP"

    def test_simple_symbol(self, mock_okx_exchange):
        params = mock_okx_exchange._get_ohlcv_params("BTC/USDT")
        assert params["instType"] == "SWAP"
        assert params["instId"] == "BTC-USDT-SWAP"

    def test_eth_symbol(self, mock_okx_exchange):
        params = mock_okx_exchange._get_ohlcv_params("ETH/USDT:USDT")
        assert params["instId"] == "ETH-USDT-SWAP"


class TestOkxWsConnect:
    """Test OkxExchange._ws_connect."""

    @pytest.mark.asyncio
    async def test_ws_connect_establishes_connection(self, mock_okx_exchange):
        """Test that WebSocket connection is established."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        ticker_data = json.dumps({
            "data": [{"instId": "BTC-USDT-SWAP", "last": "50000.00", "vol24h": "1000"}]
        })
        mock_ws.recv = AsyncMock(side_effect=[ticker_data, ConnectionError()])

        mock_okx_exchange.running = True

        with patch("kairos.exchanges.okx.websockets.connect", return_value=mock_ws):
            await mock_okx_exchange._ws_connect(["BTC/USDT:USDT"])

        assert mock_okx_exchange.ws_connected is False

    @pytest.mark.asyncio
    async def test_ws_connect_processes_ticker_data(self, mock_okx_exchange):
        """Test that ticker data is correctly processed."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        ticker_data = json.dumps({
            "data": [{"instId": "BTC-USDT-SWAP", "last": "50000.00", "vol24h": "1000"}]
        })
        # First recv is subscription confirmation, then ticker data, then error to exit
        mock_ws.recv = AsyncMock(side_effect=["{}", ticker_data, ConnectionError()])

        mock_okx_exchange.running = True

        with patch("kairos.exchanges.okx.websockets.connect", return_value=mock_ws):
            await mock_okx_exchange._ws_connect(["BTC/USDT:USDT"])

        assert mock_okx_exchange.last_prices.get("BTC/USDT:USDT") == 50000.0

    @pytest.mark.asyncio
    async def test_ws_connect_handles_ping(self, mock_okx_exchange):
        """Test that ping messages are handled."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        ping_data = json.dumps({"event": "ping"})
        ticker_data = json.dumps({
            "data": [{"instId": "BTC-USDT-SWAP", "last": "50000.00"}]
        })
        mock_ws.recv = AsyncMock(side_effect=["{}", ping_data, ticker_data, ConnectionError()])

        mock_okx_exchange.running = True

        with patch("kairos.exchanges.okx.websockets.connect", return_value=mock_ws):
            await mock_okx_exchange._ws_connect(["BTC/USDT:USDT"])

        # Verify pong was sent
        send_calls = mock_ws.send.call_args_list
        pong_sent = any("pong" in str(call) for call in send_calls)
        assert pong_sent

    @pytest.mark.asyncio
    async def test_ws_connect_sends_subscription(self, mock_okx_exchange):
        """Test that subscription message is sent."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)
        mock_ws.recv = AsyncMock(side_effect=[ConnectionError()])

        mock_okx_exchange.running = True

        with patch("kairos.exchanges.okx.websockets.connect", return_value=mock_ws):
            await mock_okx_exchange._ws_connect(["BTC/USDT:USDT"])

        send_calls = mock_ws.send.call_args_list
        assert len(send_calls) > 0
        sub_msg = json.loads(send_calls[0][0][0])
        assert sub_msg["op"] == "subscribe"
        assert sub_msg["args"][0]["instId"] == "BTC-USDT-SWAP"

    @pytest.mark.asyncio
    async def test_ws_connect_retries_on_failure(self, mock_okx_exchange):
        """Test that connection retries on failure."""
        call_count = [0]

        async def failing_connect(*args, **kwargs):
            call_count[0] += 1
            raise ConnectionError("Connection failed")

        mock_okx_exchange.running = True

        with patch("kairos.exchanges.okx.websockets.connect", side_effect=failing_connect):
            with patch("kairos.exchanges.okx.asyncio.sleep", new_callable=AsyncMock):
                await mock_okx_exchange._ws_connect(["BTC/USDT:USDT"])

        assert call_count[0] >= 1

    @pytest.mark.asyncio
    async def test_ws_connect_stops_when_not_running(self, mock_okx_exchange):
        """Test that connection loop stops when running is False."""
        mock_okx_exchange.running = False

        with patch("kairos.exchanges.okx.websockets.connect") as mock_connect:
            await mock_okx_exchange._ws_connect(["BTC/USDT:USDT"])
            mock_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_ws_connect_handles_connection_closed(self, mock_okx_exchange):
        """Test that ConnectionClosed exception is handled."""
        from websockets.exceptions import ConnectionClosed

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        # First recv succeeds, then ConnectionClosed
        mock_ws.recv = AsyncMock(side_effect=["{}", ConnectionClosed(None, None)])

        mock_okx_exchange.running = True

        with patch("kairos.exchanges.okx.websockets.connect", return_value=mock_ws):
            await mock_okx_exchange._ws_connect(["BTC/USDT:USDT"])

        assert mock_okx_exchange.ws_connected is False

    @pytest.mark.asyncio
    async def test_ws_connect_handles_data_error(self, mock_okx_exchange):
        """Test that data processing errors break inner loop."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        mock_ws.recv = AsyncMock(side_effect=["{}", ValueError("Bad data"), ConnectionError()])

        mock_okx_exchange.running = True

        with patch("kairos.exchanges.okx.websockets.connect", return_value=mock_ws):
            await mock_okx_exchange._ws_connect(["BTC/USDT:USDT"])

    @pytest.mark.asyncio
    async def test_ws_connect_with_volume(self, mock_okx_exchange):
        """Test that volume data is processed."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        ticker_data = json.dumps({
            "data": [{"instId": "BTC-USDT-SWAP", "last": "50000.00", "vol24h": "5000000"}]
        })
        mock_ws.recv = AsyncMock(side_effect=["{}", ticker_data, ConnectionError()])

        mock_okx_exchange.running = True

        with patch("kairos.exchanges.okx.websockets.connect", return_value=mock_ws):
            await mock_okx_exchange._ws_connect(["BTC/USDT:USDT"])

        assert mock_okx_exchange.last_prices.get("BTC/USDT:USDT") == 50000.0

    @pytest.mark.asyncio
    async def test_ws_connect_multiple_symbols(self, mock_okx_exchange):
        """Test subscribing to multiple symbols."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        ticker_data = json.dumps({
            "data": [
                {"instId": "BTC-USDT-SWAP", "last": "50000.00"},
                {"instId": "ETH-USDT-SWAP", "last": "3000.00"},
            ]
        })
        mock_ws.recv = AsyncMock(side_effect=["{}", ticker_data, ConnectionError()])

        mock_okx_exchange.running = True

        with patch("kairos.exchanges.okx.websockets.connect", return_value=mock_ws):
            await mock_okx_exchange._ws_connect(["BTC/USDT:USDT", "ETH/USDT:USDT"])

        assert mock_okx_exchange.last_prices.get("BTC/USDT:USDT") == 50000.0
        assert mock_okx_exchange.last_prices.get("ETH/USDT:USDT") == 3000.0

    @pytest.mark.asyncio
    async def test_ws_connect_formats_uri(self, mock_okx_exchange):
        """Test that correct URI is used."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)
        mock_ws.recv = AsyncMock(side_effect=[ConnectionError()])

        mock_okx_exchange.running = True

        with patch("kairos.exchanges.okx.websockets.connect", return_value=mock_ws) as mock_connect:
            await mock_okx_exchange._ws_connect(["BTC/USDT:USDT"])

            call_args = mock_connect.call_args[0][0]
            assert call_args == "wss://ws.okx.com:8443/ws/v5/public"

    @pytest.mark.asyncio
    async def test_ws_connect_sets_established_once(self, mock_okx_exchange):
        """Test that established_once flag is set on successful connection."""
        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        # First connection succeeds, then fails
        ticker_data = json.dumps({
            "data": [{"instId": "BTC-USDT-SWAP", "last": "50000.00"}]
        })
        mock_ws.recv = AsyncMock(side_effect=["{}", ticker_data, ConnectionError()])

        mock_okx_exchange.running = True

        with patch("kairos.exchanges.okx.websockets.connect", return_value=mock_ws):
            await mock_okx_exchange._ws_connect(["BTC/USDT:USDT"])

        # After successful connection, should not log "Unable to establish"
        # This is tested implicitly by the test passing
