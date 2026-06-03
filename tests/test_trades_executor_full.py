"""Comprehensive tests for TradeExecutor."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kairos.trades.executor import (
    Order,
    OrderResult,
    OrderSide,
    OrderType,
    PositionSide,
    TradeExecutor,
)


@pytest.fixture
def mock_executor():
    """Create a TradeExecutor with mocked ccxt."""
    with patch("kairos.trades.executor.ccxt.binance") as mock_cls:
        mock_exchange = AsyncMock()
        mock_cls.return_value = mock_exchange
        config = {
            "apiKey": "test_key",
            "secret": "test_secret",
            "testnet": True,
            "defaultLeverage": 5,
            "maxLeverage": 10,
            "marginMode": "isolated",
        }
        executor = TradeExecutor("binance", config)
        executor.exchange = mock_exchange
        yield executor


class TestOrderAndOrderResult:
    """Test Order and OrderResult dataclasses."""

    def test_order_defaults(self):
        order = Order(symbol="BTC/USDT", side=OrderSide.BUY, order_type=OrderType.MARKET, amount=0.01)
        assert order.price is None
        assert order.stop_price is None
        assert order.position_side == PositionSide.LONG
        assert order.leverage == 1
        assert order.reduce_only is False
        assert order.params == {}

    def test_order_result_defaults(self):
        result = OrderResult(success=True)
        assert result.order_id is None
        assert result.filled_price is None
        assert result.error is None

    def test_order_side_enum(self):
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"

    def test_order_type_enum(self):
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP.value == "stop"
        assert OrderType.STOP_LIMIT.value == "stop_limit"

    def test_position_side_enum(self):
        assert PositionSide.LONG.value == "long"
        assert PositionSide.SHORT.value == "short"


class TestTradeExecutorInit:
    """Test TradeExecutor initialization."""

    def test_init_sets_exchange_name(self, mock_executor):
        assert mock_executor.exchange_name == "binance"

    def test_init_sets_leverage(self, mock_executor):
        assert mock_executor.default_leverage == 5
        assert mock_executor.max_leverage == 10

    def test_init_sets_margin_mode(self, mock_executor):
        assert mock_executor.margin_mode == "isolated"


class TestSetLeverage:
    """Test set_leverage method."""

    @pytest.mark.asyncio
    async def test_set_leverage_success(self, mock_executor):
        mock_executor.exchange.set_leverage = AsyncMock(return_value=True)
        result = await mock_executor.set_leverage("BTC/USDT", 5)
        assert result is True
        mock_executor.exchange.set_leverage.assert_called_once_with(5, "BTC/USDT")

    @pytest.mark.asyncio
    async def test_set_leverage_caps_at_max(self, mock_executor):
        mock_executor.exchange.set_leverage = AsyncMock(return_value=True)
        result = await mock_executor.set_leverage("BTC/USDT", 20)
        assert result is True
        mock_executor.exchange.set_leverage.assert_called_once_with(10, "BTC/USDT")

    @pytest.mark.asyncio
    async def test_set_leverage_failure(self, mock_executor):
        mock_executor.exchange.set_leverage = AsyncMock(side_effect=Exception("API error"))
        result = await mock_executor.set_leverage("BTC/USDT", 5)
        assert result is False


class TestSetMarginMode:
    """Test set_margin_mode method."""

    @pytest.mark.asyncio
    async def test_set_margin_mode_success(self, mock_executor):
        mock_executor.exchange.set_margin_mode = AsyncMock(return_value=True)
        result = await mock_executor.set_margin_mode("BTC/USDT", "cross")
        assert result is True
        mock_executor.exchange.set_margin_mode.assert_called_once_with("cross", "BTC/USDT")

    @pytest.mark.asyncio
    async def test_set_margin_mode_uses_default(self, mock_executor):
        mock_executor.exchange.set_margin_mode = AsyncMock(return_value=True)
        result = await mock_executor.set_margin_mode("BTC/USDT")
        assert result is True
        mock_executor.exchange.set_margin_mode.assert_called_once_with("isolated", "BTC/USDT")

    @pytest.mark.asyncio
    async def test_set_margin_mode_failure(self, mock_executor):
        mock_executor.exchange.set_margin_mode = AsyncMock(side_effect=Exception("API error"))
        result = await mock_executor.set_margin_mode("BTC/USDT")
        assert result is False


class TestExecuteOrder:
    """Test execute_order method."""

    @pytest.mark.asyncio
    async def test_execute_market_order_success(self, mock_executor):
        mock_executor.exchange.set_leverage = AsyncMock()
        mock_executor.exchange.create_order = AsyncMock(return_value={
            "id": "12345",
            "average": 50000.0,
            "filled": 0.01,
            "fee": {"cost": 0.5},
        })

        order = Order(symbol="BTC/USDT", side=OrderSide.BUY, order_type=OrderType.MARKET, amount=0.01)
        result = await mock_executor.execute_order(order)

        assert result.success is True
        assert result.order_id == "12345"
        assert result.filled_price == 50000.0
        assert result.filled_amount == 0.01

    @pytest.mark.asyncio
    async def test_execute_limit_order_success(self, mock_executor):
        mock_executor.exchange.set_leverage = AsyncMock()
        mock_executor.exchange.create_order = AsyncMock(return_value={
            "id": "12346",
            "average": 49000.0,
            "filled": 0.01,
        })

        order = Order(
            symbol="BTC/USDT", side=OrderSide.BUY, order_type=OrderType.LIMIT,
            amount=0.01, price=49000.0
        )
        result = await mock_executor.execute_order(order)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_limit_order_no_price(self, mock_executor):
        mock_executor.exchange.set_leverage = AsyncMock()

        order = Order(symbol="BTC/USDT", side=OrderSide.BUY, order_type=OrderType.LIMIT, amount=0.01)
        result = await mock_executor.execute_order(order)

        assert result.success is False
        assert "price" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_stop_order_success(self, mock_executor):
        mock_executor.exchange.set_leverage = AsyncMock()
        mock_executor.exchange.create_order = AsyncMock(return_value={
            "id": "12347",
            "average": 48000.0,
            "filled": 0.01,
        })

        order = Order(
            symbol="BTC/USDT", side=OrderSide.SELL, order_type=OrderType.STOP,
            amount=0.01, stop_price=48000.0
        )
        result = await mock_executor.execute_order(order)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_stop_order_no_stop_price(self, mock_executor):
        mock_executor.exchange.set_leverage = AsyncMock()

        order = Order(symbol="BTC/USDT", side=OrderSide.SELL, order_type=OrderType.STOP, amount=0.01)
        result = await mock_executor.execute_order(order)

        assert result.success is False
        assert "stop_price" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_order_short_position(self, mock_executor):
        mock_executor.exchange.set_leverage = AsyncMock()
        mock_executor.exchange.create_order = AsyncMock(return_value={
            "id": "12348",
            "average": 50000.0,
            "filled": 0.01,
        })

        order = Order(
            symbol="BTC/USDT", side=OrderSide.SELL, order_type=OrderType.MARKET,
            amount=0.01, position_side=PositionSide.SHORT
        )
        result = await mock_executor.execute_order(order)

        assert result.success is True
        call_params = mock_executor.exchange.create_order.call_args[1]["params"]
        assert call_params["positionSide"] == "short"

    @pytest.mark.asyncio
    async def test_execute_order_reduce_only(self, mock_executor):
        mock_executor.exchange.set_leverage = AsyncMock()
        mock_executor.exchange.create_order = AsyncMock(return_value={
            "id": "12349",
            "average": 50000.0,
            "filled": 0.01,
        })

        order = Order(
            symbol="BTC/USDT", side=OrderSide.SELL, order_type=OrderType.MARKET,
            amount=0.01, reduce_only=True
        )
        result = await mock_executor.execute_order(order)

        assert result.success is True
        call_params = mock_executor.exchange.create_order.call_args[1]["params"]
        assert call_params["reduceOnly"] is True

    @pytest.mark.asyncio
    async def test_execute_order_insufficient_funds(self, mock_executor):
        import ccxt
        mock_executor.exchange.set_leverage = AsyncMock()
        mock_executor.exchange.create_order = AsyncMock(side_effect=ccxt.InsufficientFunds("Not enough funds"))

        order = Order(symbol="BTC/USDT", side=OrderSide.BUY, order_type=OrderType.MARKET, amount=0.01)
        result = await mock_executor.execute_order(order)

        assert result.success is False
        assert "insufficient" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_order_invalid_order(self, mock_executor):
        import ccxt
        mock_executor.exchange.set_leverage = AsyncMock()
        mock_executor.exchange.create_order = AsyncMock(side_effect=ccxt.InvalidOrder("Invalid order"))

        order = Order(symbol="BTC/USDT", side=OrderSide.BUY, order_type=OrderType.MARKET, amount=0.01)
        result = await mock_executor.execute_order(order)

        assert result.success is False
        assert "invalid" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_order_network_error(self, mock_executor):
        import ccxt
        mock_executor.exchange.set_leverage = AsyncMock()
        mock_executor.exchange.create_order = AsyncMock(side_effect=ccxt.NetworkError("Network down"))

        order = Order(symbol="BTC/USDT", side=OrderSide.BUY, order_type=OrderType.MARKET, amount=0.01)
        result = await mock_executor.execute_order(order)

        assert result.success is False
        assert "network" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_order_generic_error(self, mock_executor):
        mock_executor.exchange.set_leverage = AsyncMock()
        mock_executor.exchange.create_order = AsyncMock(side_effect=RuntimeError("Something broke"))

        order = Order(symbol="BTC/USDT", side=OrderSide.BUY, order_type=OrderType.MARKET, amount=0.01)
        result = await mock_executor.execute_order(order)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_unsupported_order_type(self, mock_executor):
        mock_executor.exchange.set_leverage = AsyncMock()

        order = Order(symbol="BTC/USDT", side=OrderSide.BUY, order_type=OrderType.STOP_LIMIT, amount=0.01)
        result = await mock_executor.execute_order(order)

        assert result.success is False
        assert "unsupported" in result.error.lower()


class TestClosePosition:
    """Test close_position method."""

    @pytest.mark.asyncio
    async def test_close_position_success(self, mock_executor):
        mock_executor.exchange.fetch_positions = AsyncMock(return_value=[
            {"symbol": "BTC/USDT", "side": "long", "contracts": 0.01}
        ])
        mock_executor.exchange.set_leverage = AsyncMock()
        mock_executor.exchange.create_order = AsyncMock(return_value={
            "id": "12350",
            "average": 50000.0,
            "filled": 0.01,
        })

        result = await mock_executor.close_position("BTC/USDT", PositionSide.LONG)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_close_position_not_found(self, mock_executor):
        mock_executor.exchange.fetch_positions = AsyncMock(return_value=[])

        result = await mock_executor.close_position("BTC/USDT", PositionSide.LONG)

        assert result.success is False
        assert "no" in result.error.lower()

    @pytest.mark.asyncio
    async def test_close_position_partial(self, mock_executor):
        mock_executor.exchange.fetch_positions = AsyncMock(return_value=[
            {"symbol": "BTC/USDT", "side": "long", "contracts": 0.02}
        ])
        mock_executor.exchange.set_leverage = AsyncMock()
        mock_executor.exchange.create_order = AsyncMock(return_value={
            "id": "12351",
            "average": 50000.0,
            "filled": 0.01,
        })

        result = await mock_executor.close_position("BTC/USDT", PositionSide.LONG, amount=0.01)

        assert result.success is True


class TestGetPositions:
    """Test get_positions method."""

    @pytest.mark.asyncio
    async def test_get_positions_success(self, mock_executor):
        mock_executor.exchange.fetch_positions = AsyncMock(return_value=[
            {"symbol": "BTC/USDT", "contracts": 0.01},
            {"symbol": "ETH/USDT", "contracts": 0},
        ])

        positions = await mock_executor.get_positions()

        assert len(positions) == 1
        assert positions[0]["symbol"] == "BTC/USDT"

    @pytest.mark.asyncio
    async def test_get_positions_error(self, mock_executor):
        mock_executor.exchange.fetch_positions = AsyncMock(side_effect=Exception("API error"))

        positions = await mock_executor.get_positions()

        assert positions == []


class TestGetBalance:
    """Test get_balance method."""

    @pytest.mark.asyncio
    async def test_get_balance_success(self, mock_executor):
        mock_executor.exchange.fetch_balance = AsyncMock(return_value={
            "total": {"USDT": 10000},
            "free": {"USDT": 5000},
            "used": {"USDT": 5000},
        })

        balance = await mock_executor.get_balance()

        assert balance["total"]["USDT"] == 10000
        assert balance["free"]["USDT"] == 5000

    @pytest.mark.asyncio
    async def test_get_balance_error(self, mock_executor):
        mock_executor.exchange.fetch_balance = AsyncMock(side_effect=Exception("API error"))

        balance = await mock_executor.get_balance()

        assert balance == {}


class TestGetTicker:
    """Test get_ticker method."""

    @pytest.mark.asyncio
    async def test_get_ticker_success(self, mock_executor):
        mock_executor.exchange.fetch_ticker = AsyncMock(return_value={
            "symbol": "BTC/USDT",
            "last": 50000.0,
        })

        ticker = await mock_executor.get_ticker("BTC/USDT")

        assert ticker["last"] == 50000.0

    @pytest.mark.asyncio
    async def test_get_ticker_error(self, mock_executor):
        mock_executor.exchange.fetch_ticker = AsyncMock(side_effect=Exception("API error"))

        ticker = await mock_executor.get_ticker("BTC/USDT")

        assert ticker == {}


class TestGetFundingRate:
    """Test get_funding_rate method."""

    @pytest.mark.asyncio
    async def test_get_funding_rate_success(self, mock_executor):
        mock_executor.exchange.fetch_funding_rate = AsyncMock(return_value={
            "fundingRate": 0.0001,
            "fundingDatetime": "2024-01-01T00:00:00Z",
            "timestamp": 1704067200000,
        })

        funding = await mock_executor.get_funding_rate("BTC/USDT")

        assert funding["rate"] == 0.0001
        assert funding["symbol"] == "BTC/USDT"

    @pytest.mark.asyncio
    async def test_get_funding_rate_error(self, mock_executor):
        mock_executor.exchange.fetch_funding_rate = AsyncMock(side_effect=Exception("API error"))

        funding = await mock_executor.get_funding_rate("BTC/USDT")

        assert funding == {}
