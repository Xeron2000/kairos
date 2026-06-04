"""Tests for BaseExchange extra methods — updated to current API."""

from unittest.mock import MagicMock

import pytest

from kairos.exchanges.base import BaseExchange


class _TestExchangeImpl(BaseExchange):
    """Minimal concrete exchange for testing BaseExchange methods."""

    def __init__(self, exchange_name="okx"):
        super().__init__(exchange_name)

    async def _ws_connect(self, symbols):
        return


class TestGetCurrentPrices:
    @pytest.mark.asyncio
    async def test_returns_prices(self):
        ex = _TestExchangeImpl()
        ex.exchange.fetch_ticker = MagicMock(return_value={"last": 100.0})
        result = await ex.get_current_prices(["BTC/USDT", "ETH/USDT"])
        assert isinstance(result, dict)
        assert len(result) > 0


class TestGetPriceMinutesAgo:
    @pytest.mark.asyncio
    async def test_returns_prices(self):
        ex = _TestExchangeImpl()
        ex.exchange.fetch_ohlcv = MagicMock(
            return_value=[
                [1_700_000_000_000, 100, 101, 99, 100.5, 1_000],
            ]
        )
        result = await ex.get_price_minutes_ago(["BTC/USDT"], 5)
        assert isinstance(result, dict)


class TestRegisterDetector:
    def test_register(self):
        ex = _TestExchangeImpl()
        mock_detector = MagicMock()
        ex.register_detector(mock_detector)
        assert mock_detector in ex._detectors

    def test_register_multiple(self):
        ex = _TestExchangeImpl()
        d1, d2 = MagicMock(), MagicMock()
        ex.register_detector(d1)
        ex.register_detector(d2)
        assert len(ex._detectors) == 2


class TestClose:
    def test_close(self):
        ex = _TestExchangeImpl()
        ex.close()  # should not raise
