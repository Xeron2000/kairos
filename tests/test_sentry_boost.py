"""Comprehensive tests for PriceSentry."""

import asyncio
import time
from queue import Queue
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kairos.core.sentry import PriceSentry, load_config


@pytest.fixture
def mock_config():
    """Provide a valid mock configuration."""
    return {
        "exchange": "binance",
        "notificationSymbols": ["BTC/USDT", "ETH/USDT"],
        "scanInterval": 60,
        "alertCooldown": 300,
        "priceChangeThreshold": 2.0,
        "telegram": {"token": "test_token", "chatId": "12345"},
        "notificationChannels": ["telegram"],
    }


@pytest.fixture
def sentry(mock_config):
    """Create a PriceSentry with mocked dependencies."""
    with patch("kairos.core.sentry.load_config", return_value=mock_config), \
         patch("kairos.core.sentry.config_validator.validate_config") as mock_validate, \
         patch("kairos.core.sentry.performance_monitor"), \
         patch("kairos.core.sentry.load_usdt_contracts", return_value=["BTC/USDT", "ETH/USDT"]):
        mock_validate.return_value = MagicMock(is_valid=True, warnings=[], info=[], errors=[])
        s = PriceSentry()
        yield s


class TestLoadConfig:
    """Test load_config function."""

    def test_returns_dict(self):
        with patch("kairos.core.sentry.config_manager") as mock_mgr:
            mock_mgr.get_config.return_value = {"key": "value"}
            result = load_config()
            assert isinstance(result, dict)


class TestPriceSentryInit:
    """Test PriceSentry initialization."""

    def test_init_success(self, sentry):
        assert sentry.config is not None
        assert sentry.running is False

    def test_init_invalid_config(self, mock_config):
        with patch("kairos.core.sentry.load_config", return_value=mock_config), \
             patch("kairos.core.sentry.config_validator.validate_config") as mock_validate, \
             patch("kairos.core.sentry.performance_monitor"):
            mock_validate.return_value = MagicMock(is_valid=False, errors=["Invalid"], warnings=[], info=[])
            with pytest.raises(ValueError, match="Configuration validation failed"):
                PriceSentry()

    def test_init_with_warnings(self, mock_config):
        with patch("kairos.core.sentry.load_config", return_value=mock_config), \
             patch("kairos.core.sentry.config_validator.validate_config") as mock_validate, \
             patch("kairos.core.sentry.performance_monitor"), \
             patch("kairos.core.sentry.load_usdt_contracts", return_value=["BTC/USDT"]):
            mock_validate.return_value = MagicMock(is_valid=True, warnings=["Test warning"], info=[], errors=[])
            s = PriceSentry()
            assert s is not None


class TestPriceSentryStartStop:
    """Test start and stop methods."""

    @pytest.mark.asyncio
    async def test_start(self, sentry):
        with patch.object(sentry, "_run_monitoring_loop", new_callable=AsyncMock) as mock_loop:
            mock_loop.side_effect = asyncio.CancelledError()
            with pytest.raises(asyncio.CancelledError):
                await sentry.start()
            assert sentry.running is True

    @pytest.mark.asyncio
    async def test_stop(self, sentry):
        sentry.running = True
        sentry._exchange = MagicMock()
        await sentry.stop()
        assert sentry.running is False


class TestPriceSentryConfig:
    """Test configuration-related methods."""

    def test_update_config(self, sentry):
        new_config = {
            "exchange": "binance",
            "notificationSymbols": ["BTC/USDT"],
            "scanInterval": 30,
        }
        with patch("kairos.core.sentry.config_validator.validate_config") as mock_validate:
            mock_validate.return_value = MagicMock(is_valid=True, warnings=[], info=[], errors=[])
            with patch("kairos.core.sentry.load_usdt_contracts", return_value=["BTC/USDT"]):
                result = sentry.update_config(new_config)
                assert isinstance(result, dict)

    def test_get_notification_symbols(self, sentry):
        symbols = sentry.get_notification_symbols()
        assert isinstance(symbols, list)

    def test_set_notification_symbols(self, sentry):
        sentry.set_notification_symbols(["BTC/USDT", "ETH/USDT"])
        assert "BTC/USDT" in sentry.notification_symbols


class TestPriceSentryMonitoring:
    """Test monitoring methods."""

    def test_check_price_changes(self, sentry):
        sentry._last_prices = {"BTC/USDT": 50000.0}
        sentry._current_prices = {"BTC/USDT": 51000.0}
        
        changes = sentry._check_price_changes()
        assert isinstance(changes, dict)

    def test_should_alert(self, sentry):
        sentry._alert_cooldown = 60
        sentry._last_alert_time = {}
        
        result = sentry._should_alert("BTC/USDT")
        assert isinstance(result, bool)

    def test_should_alert_cooldown(self, sentry):
        sentry._alert_cooldown = 60
        sentry._last_alert_time = {"BTC/USDT": time.time()}
        
        result = sentry._should_alert("BTC/USDT")
        assert result is False


class TestPriceSentryWebSocket:
    """Test WebSocket-related methods."""

    def test_handle_ws_error(self, sentry):
        sentry._ws_consecutive_failures = 0
        sentry._handle_ws_error(Exception("Connection failed"))
        assert sentry._ws_consecutive_failures == 1

    def test_handle_ws_success(self, sentry):
        sentry._ws_consecutive_failures = 3
        sentry._handle_ws_success()
        assert sentry._ws_consecutive_failures == 0

    def test_should_alert_ws_failures(self, sentry):
        sentry._ws_consecutive_failures = 5
        sentry._ws_max_failures = 5
        sentry._ws_alert_sent = False
        
        result = sentry._should_alert_ws_failures()
        assert result is True

    def test_should_not_alert_ws_failures(self, sentry):
        sentry._ws_consecutive_failures = 2
        sentry._ws_max_failures = 5
        
        result = sentry._should_alert_ws_failures()
        assert result is False


class TestPriceSentryAnomaly:
    """Test anomaly handling methods."""

    def test_handle_anomaly_event(self, sentry):
        event = MagicMock()
        event.symbol = "BTC/USDT"
        event.severity = "HIGH"
        
        with patch.object(sentry, "_send_notification") as mock_send:
            sentry._handle_anomaly_event(event)
            # Should process the event

    def test_process_anomaly_queue(self, sentry):
        sentry._anomaly_events = Queue()
        sentry._anomaly_events.put(MagicMock(symbol="BTC/USDT"))
        
        with patch.object(sentry, "_handle_anomaly_event"):
            sentry._process_anomaly_queue()


class TestPriceSentryNotification:
    """Test notification methods."""

    def test_send_notification(self, sentry):
        with patch("kairos.core.sentry.send_notifications") as mock_send:
            mock_send.return_value = {"success": True}
            result = sentry._send_notification("Test message", "HIGH")
            assert result is True

    def test_send_notification_failure(self, sentry):
        with patch("kairos.core.sentry.send_notifications") as mock_send:
            mock_send.return_value = {"success": False, "reason": "error"}
            result = sentry._send_notification("Test message", "HIGH")
            assert result is False

    def test_format_alert_message(self, sentry):
        message = sentry._format_alert_message("BTC/USDT", 50000.0, 51000.0, 2.0)
        assert isinstance(message, str)
        assert "BTC/USDT" in message
