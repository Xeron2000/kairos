"""Comprehensive tests for src/kairos/core/sentry.py

Coverage target: 95%+
Strategy: Mock all external dependencies before import.
"""

import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock heavy external deps that aren't installed in test env
for mod in ["ccxt", "ccxt.async_support"]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

from kairos.core.sentry import PriceSentry, load_config

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config():
    """Standard mock configuration matching real schema."""
    return {
        "exchange": "binance",
        "defaultTimeframe": "5m",
        "defaultThreshold": 1.0,
        "checkInterval": "5m",
        "notificationSymbols": ["BTC/USDT", "ETH/USDT"],
        "notificationCooldown": "5m",
        "autoModeLimit": 50,
        "autoModeMinQuoteVolume24h": 0,
        "autoModeMinOpenInterestUsd": 0,
        "autoModeMinListingAgeDays": 0,
        "autoModeMaxRecentVolatilityPct": 0,
    }


@pytest.fixture
def valid_validation():
    r = MagicMock()
    r.is_valid = True
    r.warnings = []
    r.info = []
    r.errors = []
    return r


@pytest.fixture
def invalid_validation():
    r = MagicMock()
    r.is_valid = False
    r.errors = ["Bad config"]
    r.warnings = []
    r.info = []
    return r


@pytest.fixture
def mock_exchange():
    ex = MagicMock()
    ex.ws_connected = True
    return ex


def _build_sentry(
    mock_config,
    validation_result,
    mock_exchange,
    available_symbols=None,
    fetch_symbols=None,
):
    """Helper to construct a PriceSentry with all deps mocked."""
    if available_symbols is None:
        available_symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    if fetch_symbols is None:
        fetch_symbols = ["BTC/USDT", "ETH/USDT"]

    with (
        patch("kairos.core.sentry.load_config", return_value=mock_config, autospec=True),
        patch("kairos.core.sentry.config_validator.validate_config", return_value=validation_result, autospec=True),
        patch("kairos.core.sentry.get_exchange", return_value=mock_exchange, autospec=True),
        patch("kairos.core.sentry.Notifier", autospec=True) as notifier_cls,
        patch("kairos.core.sentry.load_usdt_contracts", return_value=available_symbols, autospec=True),
        patch("kairos.core.sentry.fetch_top_volume_symbols", return_value=fetch_symbols, autospec=True),
        patch("kairos.core.sentry.performance_monitor", autospec=True),
        patch("kairos.core.sentry.config_manager", autospec=True),
        patch("kairos.core.sentry.parse_timeframe", return_value=5, autospec=True),
        patch("kairos.core.sentry.notification_cooldown", autospec=True),
    ):
        notifier = MagicMock()
        notifier.send.return_value = {"success": True}
        notifier_cls.return_value = notifier
        sentry = PriceSentry()
        return sentry


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    @patch("kairos.core.sentry.config_manager", autospec=True)
    def test_returns_config(self, mgr):
        mgr.get_config.return_value = {"exchange": "binance"}
        assert load_config() == {"exchange": "binance"}

    @patch("kairos.core.sentry.config_manager", autospec=True)
    def test_empty_config(self, mgr):
        mgr.get_config.return_value = {}
        assert load_config() == {}


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_success(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        assert sentry.config == mock_config
        assert sentry.matched_symbols == ["BTC/USDT", "ETH/USDT"]
        assert sentry.notifier is not None
        assert sentry.exchange is mock_exchange

    def test_validation_failure_raises(self, mock_config, invalid_validation, mock_exchange):
        with pytest.raises(ValueError, match="Configuration validation failed"):
            _build_sentry(mock_config, invalid_validation, mock_exchange)

    def test_logs_warnings(self, mock_config, mock_exchange):
        vr = MagicMock()
        vr.is_valid = True
        vr.warnings = ["Deprecated key"]
        vr.info = ["Info msg"]
        vr.errors = []

        with patch("logging.warning", autospec=True) as lw, patch("logging.info", autospec=True) as li:
            _build_sentry(mock_config, vr, mock_exchange)
            # Code uses f-string: logging.warning(f"Configuration warning: {warning}")
            lw.assert_any_call("Configuration warning: Deprecated key")
            li.assert_any_call("Configuration info: Info msg")

    def test_no_available_symbols(self, mock_config, valid_validation, mock_exchange):
        """When load_usdt_contracts returns empty, matched_symbols stays empty."""
        with (
            patch("kairos.core.sentry.load_config", return_value=mock_config, autospec=True),
            patch("kairos.core.sentry.config_validator.validate_config", return_value=valid_validation, autospec=True),
            patch("kairos.core.sentry.get_exchange", return_value=mock_exchange, autospec=True),
            patch("kairos.core.sentry.Notifier", return_value=MagicMock()),
            patch("kairos.core.sentry.load_usdt_contracts", return_value=[], autospec=True),
            patch("kairos.core.sentry.performance_monitor", autospec=True),
            patch("kairos.core.sentry.config_manager", autospec=True),
            patch("kairos.core.sentry.parse_timeframe", return_value=5, autospec=True),
            patch("kairos.core.sentry.notification_cooldown", autospec=True),
        ):
            sentry = PriceSentry()
            assert sentry.matched_symbols == []

    def test_no_matching_symbols_returns_empty(self, mock_config, valid_validation, mock_exchange):
        """When symbols don't match available contracts, ValueError is caught and init returns early."""
        config = {**mock_config, "notificationSymbols": ["MISSING/USDT"]}
        with (
            patch("kairos.core.sentry.load_config", return_value=config, autospec=True),
            patch("kairos.core.sentry.config_validator.validate_config", return_value=valid_validation, autospec=True),
            patch("kairos.core.sentry.get_exchange", return_value=mock_exchange, autospec=True),
            patch("kairos.core.sentry.Notifier", return_value=MagicMock()),
            patch("kairos.core.sentry.load_usdt_contracts", return_value=["BTC/USDT"], autospec=True),
            patch("kairos.core.sentry.performance_monitor", autospec=True),
            patch("kairos.core.sentry.config_manager", autospec=True),
            patch("kairos.core.sentry.parse_timeframe", return_value=5, autospec=True),
            patch("kairos.core.sentry.notification_cooldown", autospec=True),
        ):
            # ValueError is caught in __init__ and logged, then returns early
            sentry = PriceSentry()
            assert sentry.matched_symbols == []

    def test_general_exception_reraises(self, mock_config):
        """Any unexpected exception during init is re-raised."""
        with (
            patch("kairos.core.sentry.load_config", side_effect=RuntimeError("boom")),
            patch("kairos.core.sentry.performance_monitor", autospec=True),
            patch("kairos.core.sentry.config_manager", autospec=True),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                PriceSentry()

    def test_auto_mode_init(self, mock_config, valid_validation, mock_exchange):
        """Auto mode uses fetch_top_volume_symbols."""
        config = {**mock_config, "notificationSymbols": "auto"}
        sentry = _build_sentry(config, valid_validation, mock_exchange, fetch_symbols=["BTC/USDT"])
        assert sentry.matched_symbols == ["BTC/USDT"]
        assert sentry._auto_mode is True

    def test_empty_list_triggers_auto_mode(self, mock_config, valid_validation, mock_exchange):
        """Empty notificationSymbols is falsy, so _sync_symbols treats it as auto mode."""
        config = {**mock_config, "notificationSymbols": []}
        sentry = _build_sentry(config, valid_validation, mock_exchange, fetch_symbols=["BTC/USDT"])
        assert sentry._auto_mode is True
        assert sentry.matched_symbols == ["BTC/USDT"]


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------


class TestRun:
    @pytest.mark.asyncio
    async def test_empty_symbols_returns_early(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange, available_symbols=[], fetch_symbols=[])
        # force empty
        sentry.matched_symbols = []
        await sentry.run()
        mock_exchange.start_websocket.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_start_failure(self, mock_config, valid_validation, mock_exchange):
        mock_exchange.start_websocket.side_effect = ConnectionError("fail")
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        with pytest.raises(ConnectionError):
            await sentry.run()

    @pytest.mark.asyncio
    async def test_starts_websocket(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        # Make run() exit after start_websocket by raising after first sleep
        call_count = [0]

        async def interrupting_sleep(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] > 1:
                raise RuntimeError("stop")

        with patch("asyncio.sleep", side_effect=interrupting_sleep, autospec=True):
            with pytest.raises(RuntimeError, match="stop"):
                await sentry.run()
        mock_exchange.start_websocket.assert_called_once_with(["BTC/USDT", "ETH/USDT"])


# ---------------------------------------------------------------------------
# _send_alert / _cooldown_seconds
# ---------------------------------------------------------------------------


class TestAlerts:
    def test_send_alert_success(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        result = sentry._send_alert("BTC/USDT", "alert!")
        assert result["success"] is True
        sentry.notifier.send.assert_called_once_with("alert!")

    def test_send_alert_failure(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry.notifier.send.return_value = {"success": False, "reason": "rate limited"}
        result = sentry._send_alert("BTC/USDT", "msg")
        assert result["success"] is False

    def test_cooldown_seconds_uses_config(self, mock_config, valid_validation, mock_exchange):
        """_cooldown_seconds calls parse_timeframe on notificationCooldown."""
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        with patch("kairos.core.sentry.parse_timeframe", return_value=10, autospec=True):
            result = sentry._cooldown_seconds()
        assert result == 600.0  # 10 * 60

    def test_cooldown_seconds_parse_error(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        with patch("kairos.core.sentry.parse_timeframe", side_effect=Exception("bad")):
            result = sentry._cooldown_seconds()
        assert result == 300.0


# ---------------------------------------------------------------------------
# _format_combined_alert
# ---------------------------------------------------------------------------


class TestFormatAlert:
    def test_empty_events(self):
        assert PriceSentry._format_combined_alert("BTC/USDT", {}) == ""

    def test_price_velocity_high(self):
        ev = MagicMock()
        ev.severity = "HIGH"
        ev.data = {"change_pct": 5.2, "window_seconds": 60, "price_from": 100.0, "price_to": 105.2}
        result = PriceSentry._format_combined_alert("BTC/USDT", {"price_velocity": ev})
        assert "BTC/USDT" in result
        assert "5.20%" in result
        assert "🔼" in result

    def test_price_velocity_negative(self):
        ev = MagicMock()
        ev.severity = "MEDIUM"
        ev.data = {"change_pct": -3.1, "window_seconds": 30, "price_from": 200.0, "price_to": 193.8}
        result = PriceSentry._format_combined_alert("ETH/USDT", {"price_velocity": ev})
        assert "3.10%" in result
        assert "🔽" in result

    def test_volume_spike(self):
        ev = MagicMock()
        ev.severity = "LOW"
        ev.data = {"ratio": 3.5, "window_minutes": 5}
        result = PriceSentry._format_combined_alert("SOL/USDT", {"volume_spike": ev})
        assert "3.5x" in result

    def test_batch_move(self):
        batch = {"change_pct": 2.5, "minutes": 15, "price_from": 100.0, "price_to": 102.5}
        result = PriceSentry._format_combined_alert("BTC/USDT", {"batch_move": batch})
        assert "2.50%" in result

    def test_price_plus_volume_confirmation(self):
        price_ev = MagicMock()
        price_ev.severity = "HIGH"
        price_ev.data = {"change_pct": 4.0, "window_seconds": 60, "price_from": 100, "price_to": 104}
        vol_ev = MagicMock()
        vol_ev.severity = "MEDIUM"
        vol_ev.data = {"ratio": 5.0, "window_minutes": 5}
        result = PriceSentry._format_combined_alert("BTC/USDT", {"price_velocity": price_ev, "volume_spike": vol_ev})
        assert "量能确认" in result

    def test_volume_only_message(self):
        vol_ev = MagicMock()
        vol_ev.severity = "LOW"
        vol_ev.data = {"ratio": 2.0, "window_minutes": 10}
        result = PriceSentry._format_combined_alert("BTC/USDT", {"volume_spike": vol_ev})
        assert "量能异常" in result

    def test_price_only_message(self):
        price_ev = MagicMock()
        price_ev.severity = "LOW"
        price_ev.data = {"change_pct": 1.5, "window_seconds": 60, "price_from": 100, "price_to": 101.5}
        result = PriceSentry._format_combined_alert("BTC/USDT", {"price_velocity": price_ev})
        assert "待量能确认" in result

    def test_batch_plus_volume(self):
        batch = {"change_pct": -2.0, "minutes": 10, "price_from": 100, "price_to": 98}
        vol_ev = MagicMock()
        vol_ev.severity = "MEDIUM"
        vol_ev.data = {"ratio": 3.0, "window_minutes": 10}
        result = PriceSentry._format_combined_alert("BTC/USDT", {"batch_move": batch, "volume_spike": vol_ev})
        assert "下跌异动已获得量能确认" in result

    def test_severity_priority(self):
        """Higher severity event determines icon."""
        lo = MagicMock()
        lo.severity = "LOW"
        lo.data = {"change_pct": 1, "window_seconds": 60, "price_from": 100, "price_to": 101}
        hi = MagicMock()
        hi.severity = "HIGH"
        hi.data = {"ratio": 5.0, "window_minutes": 5}
        result = PriceSentry._format_combined_alert("X/USDT", {"price_velocity": lo, "volume_spike": hi})
        assert "🚨" in result


# ---------------------------------------------------------------------------
# _group_batch_events
# ---------------------------------------------------------------------------


class TestGroupBatchEvents:
    def test_groups_by_symbol(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        events = [
            {"symbol": "BTC/USDT", "change_pct": 5},
            {"symbol": "ETH/USDT", "change_pct": 3},
            {"symbol": "BTC/USDT", "change_pct": 1},
        ]
        result = sentry._group_batch_events(events)
        assert "BTC/USDT" in result
        assert "ETH/USDT" in result
        # Last BTC event wins (overwrites batch_move)
        assert result["BTC/USDT"]["batch_move"]["change_pct"] == 1

    def test_empty(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        assert sentry._group_batch_events([]) == {}


# ---------------------------------------------------------------------------
# _process_config_updates / _apply_config_update
# ---------------------------------------------------------------------------


class TestConfigUpdates:
    def test_enqueue_and_process(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        event = MagicMock()
        event.new_config = mock_config
        event.diff = MagicMock()
        event.diff.changed_keys = ["defaultThreshold"]
        event.diff.requires_symbol_reload = False
        event.warnings = []

        sentry._enqueue_config_update(event)
        assert not sentry._config_events.empty()

        with patch.object(sentry, "_apply_config_update") as mock_apply:
            sentry._process_config_updates()
            mock_apply.assert_called_once_with(event)

    def test_process_empty_queue(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry._process_config_updates()  # no-op

    def test_apply_config_update(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        event = MagicMock()
        event.new_config = {"exchange": "okx"}
        event.diff = MagicMock()
        event.diff.changed_keys = ["defaultThreshold"]
        event.diff.requires_symbol_reload = False
        event.warnings = []

        with patch.object(sentry, "_refresh_runtime_settings") as rr:
            sentry._apply_config_update(event)
            assert sentry.config == {"exchange": "okx"}
            rr.assert_called_once()

    def test_apply_triggers_reload_on_symbol_change(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        event = MagicMock()
        event.new_config = mock_config
        event.diff = MagicMock()
        event.diff.changed_keys = ["notificationSymbols"]
        event.diff.requires_symbol_reload = True
        event.warnings = []

        with (
            patch.object(sentry, "_refresh_runtime_settings"),
            patch.object(sentry, "_reload_runtime_components") as rr,
        ):
            sentry._apply_config_update(event)
            rr.assert_called_once_with(event)

    def test_apply_logs_warnings(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        event = MagicMock()
        event.new_config = mock_config
        event.diff = MagicMock()
        event.diff.changed_keys = []
        event.diff.requires_symbol_reload = False
        event.warnings = ["Watch out"]

        with (
            patch.object(sentry, "_refresh_runtime_settings"),
            patch("logging.warning", autospec=True) as lw,
        ):
            sentry._apply_config_update(event)
            lw.assert_any_call("Configuration warning: %s", "Watch out")

    def test_apply_slow_update_warning(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        event = MagicMock()
        event.new_config = mock_config
        event.diff = MagicMock()
        event.diff.changed_keys = []
        event.diff.requires_symbol_reload = False
        event.warnings = []

        with (
            patch.object(sentry, "_refresh_runtime_settings"),
            patch("time.time", side_effect=[0, 10], autospec=True),
            patch("logging.warning", autospec=True) as lw,
        ):
            sentry._apply_config_update(event)
            lw.assert_any_call("Configuration update processing exceeded 5s target: %.2fs", 10.0)


# ---------------------------------------------------------------------------
# _refresh_runtime_settings
# ---------------------------------------------------------------------------


class TestRefreshRuntimeSettings:
    def test_sets_attributes(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        with patch("kairos.core.sentry.parse_timeframe", return_value=15, autospec=True):
            sentry._refresh_runtime_settings()
        assert sentry.minutes == 15
        assert sentry.threshold == 1.0

    def test_parse_error_falls_back(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry.minutes = 10
        # parse_timeframe fails for timeframe "5m" but succeeds for fallback "5m"
        # Need side_effect that fails on first call, succeeds on subsequent
        call_count = [0]

        def selective_fail(arg):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("bad")
            return 5

        with patch("kairos.core.sentry.parse_timeframe", side_effect=selective_fail, autospec=True):
            sentry._refresh_runtime_settings()
        # Falls back to getattr(self, "minutes", parse_timeframe("5m")) = 10
        assert sentry.minutes == 10

    def test_updates_notification_cooldown(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        with patch("kairos.core.sentry.parse_timeframe", return_value=5, autospec=True):
            sentry._refresh_runtime_settings()
        # notification_cooldown.update_default_cooldown called with 5*60=300

    def test_updates_notifier(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry.notifier.update_config.reset_mock()
        sentry._refresh_runtime_settings()
        sentry.notifier.update_config.assert_called_once_with(sentry.config)


# ---------------------------------------------------------------------------
# _rebuild_notification_filter_locked
# ---------------------------------------------------------------------------


class TestNotificationFilter:
    def test_no_selection_clears(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry.config["notificationSymbols"] = None
        sentry._rebuild_notification_filter_locked()
        assert sentry.notification_symbols is None

    def test_auto_clears(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry.config["notificationSymbols"] = "auto"
        sentry._rebuild_notification_filter_locked()
        assert sentry.notification_symbols is None

    def test_filters_against_monitored(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry.matched_symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
        sentry.config["notificationSymbols"] = ["BTC/USDT", "SOL/USDT"]
        sentry._rebuild_notification_filter_locked()
        assert sentry.notification_symbols == ["BTC/USDT", "SOL/USDT"]

    def test_warns_on_missing(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry.matched_symbols = ["BTC/USDT"]
        sentry.config["notificationSymbols"] = ["BTC/USDT", "DOGE/USDT"]
        with patch("logging.warning", autospec=True) as lw:
            sentry._rebuild_notification_filter_locked()
            lw.assert_any_call(
                "Notification symbols ignored because they are not monitored: %s",
                "DOGE/USDT",
            )

    def test_invalid_type_warns(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry.config["notificationSymbols"] = 12345
        with patch("logging.warning", autospec=True) as lw:
            sentry._rebuild_notification_filter_locked()
            lw.assert_any_call(
                "Ignored notificationSymbols of type %s; expected list of symbol strings.",
                "int",
            )

    def test_all_missing_clears(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry.matched_symbols = ["BTC/USDT"]
        sentry.config["notificationSymbols"] = ["MISSING/USDT"]
        sentry._rebuild_notification_filter_locked()
        assert sentry.notification_symbols is None


# ---------------------------------------------------------------------------
# _auto_mode_filters
# ---------------------------------------------------------------------------


class TestAutoModeFilters:
    def test_returns_dict(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        result = sentry._auto_mode_filters()
        assert "minQuoteVolume24h" in result
        assert "minOpenInterestUsd" in result


# ---------------------------------------------------------------------------
# _check_auto_refresh
# ---------------------------------------------------------------------------


class TestAutoRefresh:
    def test_skips_if_not_auto(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry._auto_mode = False
        sentry._check_auto_refresh()  # no-op

    def test_skips_if_too_soon(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry._auto_mode = True
        sentry._last_auto_refresh = time.time()
        with patch("kairos.core.sentry.fetch_top_volume_symbols", autospec=True) as f:
            sentry._check_auto_refresh()
            f.assert_not_called()

    def test_refreshes_symbols(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry._auto_mode = True
        sentry._last_auto_refresh = 0
        sentry.matched_symbols = ["BTC/USDT"]

        with (
            patch("kairos.core.sentry.fetch_top_volume_symbols", return_value=["BTC/USDT", "SOL/USDT"], autospec=True),
            patch("kairos.core.sentry.time.time", return_value=9999999, autospec=True),
        ):
            sentry._check_auto_refresh()

        assert sentry.matched_symbols == ["BTC/USDT", "SOL/USDT"]
        mock_exchange.close.assert_called()
        mock_exchange.start_websocket.assert_called()

    def test_no_change_skips_restart(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry._auto_mode = True
        sentry._last_auto_refresh = 0

        with (
            patch("kairos.core.sentry.fetch_top_volume_symbols", return_value=["BTC/USDT", "ETH/USDT"], autospec=True),
            patch("kairos.core.sentry.time.time", return_value=9999999, autospec=True),
            patch("logging.info", autospec=True) as li,
        ):
            sentry._check_auto_refresh()
            li.assert_any_call("Auto refresh: no symbol changes detected")

    def test_empty_refresh_keeps_current(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry._auto_mode = True
        sentry._last_auto_refresh = 0
        old = list(sentry.matched_symbols)

        with (
            patch("kairos.core.sentry.fetch_top_volume_symbols", return_value=[], autospec=True),
            patch("kairos.core.sentry.time.time", return_value=9999999, autospec=True),
        ):
            sentry._check_auto_refresh()
        assert sentry.matched_symbols == old

    def test_exception_logged(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry._auto_mode = True
        sentry._last_auto_refresh = 0

        with (
            patch("kairos.core.sentry.fetch_top_volume_symbols", side_effect=Exception("api")),
            patch("kairos.core.sentry.time.time", return_value=9999999, autospec=True),
            patch("logging.error", autospec=True) as le,
        ):
            sentry._check_auto_refresh()
            le.assert_called()


# ---------------------------------------------------------------------------
# _snapshot_runtime_state
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_returns_tuple(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry.minutes = 5
        sentry.threshold = 1.0
        sentry._check_interval = 300
        sentry.notification_symbols = ["BTC/USDT"]
        result = sentry._snapshot_runtime_state()
        assert len(result) == 5
        assert result[0] == 5
        assert result[1] == 1.0
        assert result[2] == 300
        assert "BTC/USDT" in result[3]
        assert result[4] == ["BTC/USDT"]

    def test_no_notification_filter(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry.minutes = 5
        sentry.threshold = 1.0
        sentry._check_interval = 300
        sentry.notification_symbols = None
        result = sentry._snapshot_runtime_state()
        assert result[4] is None


# ---------------------------------------------------------------------------
# _setup_detectors
# ---------------------------------------------------------------------------


class TestSetupDetectors:
    def test_creates_and_registers(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        with (
            patch("kairos.core.sentry.PriceVelocityDetector", autospec=True) as pvd,
            patch("kairos.core.sentry.VolumeSpikeDetector", autospec=True) as vsd,
        ):
            pvd.return_value = MagicMock()
            vsd.return_value = MagicMock()
            sentry._setup_detectors()
            assert hasattr(sentry, "_velocity_detector")
            assert hasattr(sentry, "_volume_detector")
            mock_exchange.register_detector.assert_any_call(sentry._velocity_detector)
            mock_exchange.register_detector.assert_any_call(sentry._volume_detector)


# ---------------------------------------------------------------------------
# _process_anomaly_events
# ---------------------------------------------------------------------------


class TestProcessAnomalyEvents:
    @pytest.mark.asyncio
    async def test_empty_queue(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        await sentry._process_anomaly_events()
        sentry.notifier.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_processes_price_event(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        ev = MagicMock()
        ev.symbol = "BTC/USDT"
        ev.event_type = "price_velocity"
        ev.severity = "HIGH"
        ev.data = {"change_pct": 5, "window_seconds": 60, "price_from": 100, "price_to": 105}
        sentry._anomaly_events.put(ev)

        with patch("kairos.core.sentry.notification_cooldown", autospec=True) as nc:
            nc.should_notify.return_value = True
            await sentry._process_anomaly_events()
            sentry.notifier.send.assert_called()

    @pytest.mark.asyncio
    async def test_skips_cooldown(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        ev = MagicMock()
        ev.symbol = "BTC/USDT"
        ev.event_type = "price_velocity"
        ev.severity = "HIGH"
        sentry._anomaly_events.put(ev)

        with patch("kairos.core.sentry.notification_cooldown", autospec=True) as nc:
            nc.should_notify.return_value = False
            await sentry._process_anomaly_events()
            sentry.notifier.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_volume_only(self, mock_config, valid_validation, mock_exchange):
        """Volume-only events without price confirmation are skipped."""
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        ev = MagicMock()
        ev.symbol = "BTC/USDT"
        ev.event_type = "volume_spike"
        ev.severity = "MEDIUM"
        sentry._anomaly_events.put(ev)

        with patch("kairos.core.sentry.notification_cooldown", autospec=True) as nc:
            nc.should_notify.return_value = True
            await sentry._process_anomaly_events()
            sentry.notifier.send.assert_not_called()


# ---------------------------------------------------------------------------
# _reload_runtime_components
# ---------------------------------------------------------------------------


class TestReloadComponents:
    def test_reloads_exchange_and_symbols(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        event = MagicMock()
        event.diff.changed_keys = ["notificationSymbols"]

        new_exchange = MagicMock()
        with (
            patch("kairos.core.sentry.get_exchange", return_value=new_exchange, autospec=True),
            patch("kairos.core.sentry.load_usdt_contracts", return_value=["BTC/USDT", "SOL/USDT"], autospec=True),
            patch("kairos.core.sentry.parse_timeframe", return_value=5, autospec=True),
            patch("kairos.core.sentry.notification_cooldown", autospec=True),
        ):
            sentry._reload_runtime_components(event)

        assert sentry.exchange is new_exchange
        new_exchange.start_websocket.assert_called()

    def test_handles_exchange_reload_failure(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        event = MagicMock()
        event.diff.changed_keys = []

        with (
            patch("kairos.core.sentry.get_exchange", side_effect=Exception("fail")),
            patch("logging.error", autospec=True) as le,
        ):
            sentry._reload_runtime_components(event)
            le.assert_called()

    def test_handles_symbol_reload_failure(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        event = MagicMock()
        event.diff.changed_keys = []

        with (
            patch("kairos.core.sentry.get_exchange", return_value=MagicMock()),
            patch("kairos.core.sentry.load_usdt_contracts", side_effect=ValueError("no symbols")),
            patch("logging.error", autospec=True) as le,
        ):
            sentry._reload_runtime_components(event)
            le.assert_called()

    def test_empty_symbols_skips_websocket(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        event = MagicMock()
        event.diff.changed_keys = []

        with (
            patch("kairos.core.sentry.get_exchange", return_value=MagicMock()),
            patch("kairos.core.sentry.load_usdt_contracts", return_value=[], autospec=True),
            patch("kairos.core.sentry.parse_timeframe", return_value=5, autospec=True),
            patch("kairos.core.sentry.notification_cooldown", autospec=True),
            patch("logging.warning", autospec=True) as lw,
        ):
            sentry._reload_runtime_components(event)
            lw.assert_any_call("Symbol reload produced empty set; skipping websocket")


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_alert_flow(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        ev = MagicMock()
        ev.symbol = "BTC/USDT"
        ev.event_type = "price_velocity"
        ev.severity = "HIGH"
        ev.data = {"change_pct": 10, "window_seconds": 60, "price_from": 50000, "price_to": 55000}
        sentry._anomaly_events.put(ev)

        with patch("kairos.core.sentry.notification_cooldown", autospec=True) as nc:
            nc.should_notify.return_value = True
            await sentry._process_anomaly_events()
            sentry.notifier.send.assert_called()
            msg = sentry.notifier.send.call_args[0][0]
            assert "BTC/USDT" in msg

    def test_ws_failure_tracking(self, mock_config, valid_validation, mock_exchange):
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        assert sentry._ws_consecutive_failures == 0
        sentry._ws_consecutive_failures = 5
        sentry._ws_alert_sent = False
        assert sentry._ws_consecutive_failures == 5


# ---------------------------------------------------------------------------
# run() loop internals
# ---------------------------------------------------------------------------


class TestRunLoop:
    """Test the main monitoring loop inside run()."""

    def _make_run_test_sentry(self, mock_config, valid_validation, mock_exchange, max_iterations=3):
        """Helper: build sentry + patches for run() loop tests."""
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        iter_count = [0]

        # Exit via _process_config_updates mock to avoid continue-skips-sleep issue
        def count_iterations():
            iter_count[0] += 1
            if iter_count[0] > max_iterations:
                raise SystemExit()

        return sentry, count_iterations, lambda: 999999

    @pytest.mark.asyncio
    async def test_loop_processes_batch_events(self, mock_config, valid_validation, mock_exchange):
        """Loop detects batch movements and sends alerts."""
        sentry, sleep_fn, time_fn = self._make_run_test_sentry(
            mock_config, valid_validation, mock_exchange, sleep_raises_after=2
        )
        batch_result = [{"symbol": "BTC/USDT", "change_pct": 5.0, "minutes": 15, "price_from": 100, "price_to": 105}]
        with (
            patch("kairos.core.sentry.monitor_top_movers", new_callable=AsyncMock, return_value=batch_result, autospec=True),
            patch("kairos.core.sentry.time.time", side_effect=time_fn, autospec=True),
            patch("asyncio.sleep", side_effect=sleep_fn, autospec=True),
            patch.object(sentry, "_process_config_updates"),
            patch.object(sentry, "_process_anomaly_events", new_callable=AsyncMock),
        ):
            with pytest.raises(SystemExit):
                await sentry.run()
        sentry.notifier.send.assert_called()

    @pytest.mark.asyncio
    async def test_loop_no_movements(self, mock_config, valid_validation, mock_exchange):
        """Loop handles empty monitor result."""
        sentry, sleep_fn, time_fn = self._make_run_test_sentry(
            mock_config, valid_validation, mock_exchange, sleep_raises_after=2, time_returns=[0, 0, 0, 999999]
        )
        with (
            patch("kairos.core.sentry.monitor_top_movers", new_callable=AsyncMock, return_value=[], autospec=True),
            patch("kairos.core.sentry.time.time", side_effect=time_fn, autospec=True),
            patch("asyncio.sleep", side_effect=sleep_fn, autospec=True),
            patch.object(sentry, "_process_config_updates"),
            patch.object(sentry, "_process_anomaly_events", new_callable=AsyncMock),
        ):
            with pytest.raises(SystemExit):
                await sentry.run()
        sentry.notifier.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_loop_monitor_exception(self, mock_config, valid_validation, mock_exchange):
        """Loop catches monitor_top_movers exceptions and continues."""
        # Use a large time_returns so the exception handler has enough time values
        sentry, sleep_fn, time_fn = self._make_run_test_sentry(
            mock_config, valid_validation, mock_exchange, sleep_raises_after=2, time_returns=[0, 0] + [999999] * 50
        )
        with (
            patch("kairos.core.sentry.monitor_top_movers", new_callable=AsyncMock, side_effect=Exception("api")),
            patch("kairos.core.sentry.time.time", side_effect=time_fn, autospec=True),
            patch("asyncio.sleep", side_effect=sleep_fn, autospec=True),
            patch.object(sentry, "_process_config_updates"),
            patch.object(sentry, "_process_anomaly_events", new_callable=AsyncMock),
        ):
            with pytest.raises(SystemExit):
                await sentry.run()

    @pytest.mark.asyncio
    async def test_loop_ws_reconnect(self, mock_config, valid_validation, mock_exchange):
        """Loop reconnects WebSocket when disconnected."""
        sentry, sleep_fn, _ = self._make_run_test_sentry(
            mock_config, valid_validation, mock_exchange, sleep_raises_after=2
        )
        mock_exchange.ws_connected = False
        mock_exchange.check_ws_connection.return_value = None

        def time_side():
            time_side.c = getattr(time_side, "c", 0) + 1
            return 0 if time_side.c <= 2 else 120

        with (
            patch("kairos.core.sentry.monitor_top_movers", new_callable=AsyncMock, return_value=[], autospec=True),
            patch("kairos.core.sentry.time.time", side_effect=time_side, autospec=True),
            patch("asyncio.sleep", side_effect=sleep_fn, autospec=True),
            patch.object(sentry, "_process_config_updates"),
            patch.object(sentry, "_process_anomaly_events", new_callable=AsyncMock),
        ):
            with pytest.raises(SystemExit):
                await sentry.run()
        assert sentry._ws_consecutive_failures >= 1

    @pytest.mark.asyncio
    async def test_loop_ws_alert_threshold(self, mock_config, valid_validation, mock_exchange):
        """Loop sends WS alert after max consecutive failures."""
        sentry, sleep_fn, _ = self._make_run_test_sentry(
            mock_config, valid_validation, mock_exchange, sleep_raises_after=2
        )
        mock_exchange.ws_connected = False
        sentry._ws_consecutive_failures = 4

        def time_side():
            time_side.c = getattr(time_side, "c", 0) + 1
            return 0 if time_side.c <= 2 else 120

        with (
            patch("kairos.core.sentry.monitor_top_movers", new_callable=AsyncMock, return_value=[], autospec=True),
            patch("kairos.core.sentry.time.time", side_effect=time_side, autospec=True),
            patch("asyncio.sleep", side_effect=sleep_fn, autospec=True),
            patch.object(sentry, "_process_config_updates"),
            patch.object(sentry, "_process_anomaly_events", new_callable=AsyncMock),
        ):
            with pytest.raises(SystemExit):
                await sentry.run()
        sentry.notifier.send.assert_called()
        assert sentry._ws_alert_sent is True

    @pytest.mark.asyncio
    async def test_loop_ws_connected_resets(self, mock_config, valid_validation, mock_exchange):
        """Loop resets failure counter when WS reconnected."""
        sentry, sleep_fn, _ = self._make_run_test_sentry(
            mock_config, valid_validation, mock_exchange, sleep_raises_after=2
        )
        mock_exchange.ws_connected = True
        sentry._ws_consecutive_failures = 3

        def time_side():
            time_side.c = getattr(time_side, "c", 0) + 1
            return 0 if time_side.c <= 2 else 120

        with (
            patch("kairos.core.sentry.monitor_top_movers", new_callable=AsyncMock, return_value=[], autospec=True),
            patch("kairos.core.sentry.time.time", side_effect=time_side, autospec=True),
            patch("asyncio.sleep", side_effect=sleep_fn, autospec=True),
            patch.object(sentry, "_process_config_updates"),
            patch.object(sentry, "_process_anomaly_events", new_callable=AsyncMock),
        ):
            with pytest.raises(SystemExit):
                await sentry.run()
        assert sentry._ws_consecutive_failures == 0
        assert sentry._ws_alert_sent is False

    @pytest.mark.asyncio
    async def test_loop_cleanup_on_exit(self, mock_config, valid_validation, mock_exchange):
        """Loop calls exchange.close() in finally block."""
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        # Warmup sleep succeeds, loop sleep raises SystemExit
        call_count = [0]

        async def sleep_after_warmup(*a, **kw):
            call_count[0] += 1
            if call_count[0] > 1:
                raise SystemExit()

        with patch("asyncio.sleep", side_effect=sleep_after_warmup, autospec=True):
            with pytest.raises(SystemExit):
                await sentry.run()
        mock_exchange.close.assert_called()

    @pytest.mark.asyncio
    async def test_loop_cleanup_exception(self, mock_config, valid_validation, mock_exchange):
        """Loop handles exchange.close() exception gracefully."""
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        mock_exchange.close.side_effect = Exception("close fail")
        call_count = [0]

        async def sleep_after_warmup(*a, **kw):
            call_count[0] += 1
            if call_count[0] > 1:
                raise SystemExit()

        with patch("asyncio.sleep", side_effect=sleep_after_warmup, autospec=True):
            with pytest.raises(SystemExit):
                await sentry.run()


# ---------------------------------------------------------------------------
# _refresh_runtime_settings edge cases
# ---------------------------------------------------------------------------


class TestRefreshRuntimeEdgeCases:
    def test_check_interval_zero_falls_back(self, mock_config, valid_validation, mock_exchange):
        """Zero interval falls back to timeframe duration."""
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry.minutes = 5
        call_count = [0]

        def pf(arg):
            call_count[0] += 1
            if call_count[0] == 1:  # timeframe
                return 5
            if call_count[0] == 2:  # interval
                return 0
            return 5  # fallback

        with patch("kairos.core.sentry.parse_timeframe", side_effect=pf, autospec=True):
            sentry._refresh_runtime_settings()
        assert sentry._check_interval == 300  # 5 * 60

    def test_check_interval_negative_falls_back(self, mock_config, valid_validation, mock_exchange):
        """Negative interval falls back."""
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry.minutes = 10
        call_count = [0]

        def pf(arg):
            call_count[0] += 1
            if call_count[0] == 1:
                return 10
            if call_count[0] == 2:
                return -1
            return 10

        with patch("kairos.core.sentry.parse_timeframe", side_effect=pf, autospec=True):
            sentry._refresh_runtime_settings()
        assert sentry._check_interval == 600  # 10 * 60

    def test_check_interval_parse_error(self, mock_config, valid_validation, mock_exchange):
        """Interval parse error falls back to previous."""
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        sentry.minutes = 5
        sentry._check_interval = 999
        call_count = [0]

        def pf(arg):
            call_count[0] += 1
            if call_count[0] == 1:
                return 5  # timeframe OK
            # interval raises, fallback also calls parse_timeframe("5m")
            # Make 3rd call (fallback) succeed
            if call_count[0] == 3:
                return 5
            raise Exception("bad interval")

        with patch("kairos.core.sentry.parse_timeframe", side_effect=pf, autospec=True):
            sentry._refresh_runtime_settings()
        assert sentry._check_interval == 999  # keeps previous

    def test_cooldown_parse_error(self, mock_config, valid_validation, mock_exchange):
        """notificationCooldown parse error is logged."""
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        call_count = [0]

        def pf(arg):
            call_count[0] += 1
            if call_count[0] <= 2:
                return 5
            raise Exception("bad cooldown")

        with patch("kairos.core.sentry.parse_timeframe", side_effect=pf, autospec=True), patch("logging.error", autospec=True) as le:
            sentry._refresh_runtime_settings()
        le.assert_called()


# ---------------------------------------------------------------------------
# _sync_symbols edge cases
# ---------------------------------------------------------------------------


class TestSyncSymbols:
    def test_auto_mode_no_symbols_raises(self, mock_config, valid_validation, mock_exchange):
        """Auto mode with empty fetch raises ValueError."""
        config = {**mock_config, "notificationSymbols": "auto"}
        with (
            patch("kairos.core.sentry.load_config", return_value=config, autospec=True),
            patch("kairos.core.sentry.config_validator.validate_config", return_value=valid_validation, autospec=True),
            patch("kairos.core.sentry.get_exchange", return_value=mock_exchange, autospec=True),
            patch("kairos.core.sentry.Notifier", return_value=MagicMock()),
            patch("kairos.core.sentry.fetch_top_volume_symbols", return_value=[], autospec=True),
            patch("kairos.core.sentry.performance_monitor", autospec=True),
            patch("kairos.core.sentry.config_manager", autospec=True),
            patch("kairos.core.sentry.parse_timeframe", return_value=5, autospec=True),
            patch("kairos.core.sentry.notification_cooldown", autospec=True),
        ):
            sentry = PriceSentry()
            # ValueError caught in __init__, matched_symbols stays empty
            assert sentry.matched_symbols == []

    def test_non_auto_with_partial_match(self, mock_config, valid_validation, mock_exchange):
        """Non-auto mode with partial symbol match."""
        config = {**mock_config, "notificationSymbols": ["BTC/USDT", "MISSING/USDT", 123, "  "]}
        sentry = _build_sentry(config, valid_validation, mock_exchange, available_symbols=["BTC/USDT", "ETH/USDT"])
        # Only BTC/USDT matches; MISSING/USDT filtered, 123 skipped (not str), "  " skipped
        assert "BTC/USDT" in sentry.matched_symbols

    def test_non_auto_no_selection_raises(self, mock_config, valid_validation, mock_exchange):
        """Non-auto with no notificationSymbols raises."""
        config = {**mock_config, "notificationSymbols": None}
        with (
            patch("kairos.core.sentry.load_config", return_value=config, autospec=True),
            patch("kairos.core.sentry.config_validator.validate_config", return_value=valid_validation, autospec=True),
            patch("kairos.core.sentry.get_exchange", return_value=mock_exchange, autospec=True),
            patch("kairos.core.sentry.Notifier", return_value=MagicMock()),
            patch("kairos.core.sentry.load_usdt_contracts", return_value=["BTC/USDT"], autospec=True),
            patch("kairos.core.sentry.performance_monitor", autospec=True),
            patch("kairos.core.sentry.config_manager", autospec=True),
            patch("kairos.core.sentry.parse_timeframe", return_value=5, autospec=True),
            patch("kairos.core.sentry.notification_cooldown", autospec=True),
        ):
            # None is falsy → auto mode path
            sentry = PriceSentry()
            # Falls into auto mode, fetch_top_volume_symbols called
            assert sentry._auto_mode is True


# ---------------------------------------------------------------------------
# _format_combined_alert edge cases
# ---------------------------------------------------------------------------


class TestFormatAlertEdge:
    def test_batch_move_negative_with_volume(self):
        batch = {"change_pct": -4.0, "minutes": 10, "price_from": 100, "price_to": 96}
        vol = MagicMock()
        vol.severity = "MEDIUM"
        vol.data = {"ratio": 3.0, "window_minutes": 10}
        result = PriceSentry._format_combined_alert("BTC/USDT", {"batch_move": batch, "volume_spike": vol})
        assert "下跌异动已获得量能确认" in result

    def test_batch_move_positive_with_volume(self):
        batch = {"change_pct": 3.0, "minutes": 10, "price_from": 100, "price_to": 103}
        vol = MagicMock()
        vol.severity = "MEDIUM"
        vol.data = {"ratio": 2.5, "window_minutes": 10}
        result = PriceSentry._format_combined_alert("ETH/USDT", {"batch_move": batch, "volume_spike": vol})
        assert "价格异动已获得量能确认" in result

    def test_severity_via_priority_key(self):
        """_severity helper falls back to priority key."""
        ev = {
            "priority": "HIGH",
            "change_pct": 2,
            "window_seconds": 60,
            "price_from": 100,
            "price_to": 102,
            "minutes": 15,
        }
        result = PriceSentry._format_combined_alert("X/USDT", {"batch_move": ev})
        assert "🚨" in result


# ---------------------------------------------------------------------------
# KeyboardInterrupt handling
# ---------------------------------------------------------------------------


class TestKeyboardInterrupt:
    @pytest.mark.asyncio
    async def test_keyboard_interrupt_closes_exchange(self, mock_config, valid_validation, mock_exchange):
        """KeyboardInterrupt triggers cleanup."""
        sentry = _build_sentry(mock_config, valid_validation, mock_exchange)
        call_count = [0]

        async def kb_sleep(*a, **kw):
            call_count[0] += 1
            if call_count[0] > 1:
                raise KeyboardInterrupt()

        with patch("asyncio.sleep", side_effect=kb_sleep, autospec=True):
            await sentry.run()
        mock_exchange.close.assert_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
