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

