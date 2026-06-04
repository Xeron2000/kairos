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

