"""Tests for DataManager — WebSocket orchestration and signal delivery."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kairos.data.data_manager import DataManager, _collect_futures_metrics, _is_usdt_perpetual

# ── Helpers ────────────────────────────────────────────────────


def _make_config(**overrides):
    """Build a minimal DataManager config with defaults."""
    dm = {
        "exchanges": ["okx"],
        "topSymbols": 10,
        "refreshIntervalHours": 4,
        "dedupWindowSeconds": 5,
    }
    dm.update(overrides)
    return {
        "dataManager": dm,
        "priceVelocity": {"enabled": True, "windows": [{"seconds": 30, "threshold": 0.5}]},
        "volumeSpike": {"enabled": True, "multiplier": 3.0},
        "futuresMetrics": {
            "enabled": True,
            "pollIntervalSeconds": 300,
            "openInterest": {"enabled": True, "minChangePct": 5.0, "minNotifyInterval": "30m"},
            "fundingRate": {
                "enabled": True,
                "absRateThreshold": 0.0005,
                "minChangeAbs": 0.0003,
                "minNotifyInterval": "30m",
            },
        },
    }


def _mock_exchange():
    """Create a mock exchange with fetch_tickers returning USDT perpetuals."""
    ex = MagicMock()
    ex.exchange.fetch_tickers.return_value = {
        "BTC/USDT:USDT": {"quoteVolume": 1e10, "baseVolume": 1e10},
        "ETH/USDT:USDT": {"quoteVolume": 5e9, "baseVolume": 5e9},
        "SOL/USDT:USDT": {"quoteVolume": 2e9, "baseVolume": 2e9},
        "XRP/USDT:USDT": {"quoteVolume": 1e9, "baseVolume": 1e9},
        "DOGE/USDT": {"quoteVolume": 3e9},  # Spot, not perpetual
        None: None,
        123: None,  # Non-string key
        "BTC/USD": {"quoteVolume": 1e9},  # Not USDT
    }
    ex.last_prices = {}
    ex.start_websocket = MagicMock()
    ex.stop_websocket = MagicMock()
    ex.register_detector = MagicMock()
    return ex


# ── Tests: _is_usdt_perpetual ──────────────────────────────────


class TestIsUsdtPerpetual:
    def test_perpetual_symbol(self):
        assert _is_usdt_perpetual("BTC/USDT:USDT") is True
        assert _is_usdt_perpetual("ETH/USDT:USDT") is True
        assert _is_usdt_perpetual("SOL/USDT:USDT") is True

    def test_spot_symbol(self):
        assert _is_usdt_perpetual("BTC/USDT") is False

    def test_other_base(self):
        assert _is_usdt_perpetual("BTC/BUSD:USDT") is False
        # Only /USDT: pattern matches
        assert _is_usdt_perpetual("BTC/BUSD:USDT") is False

    def test_empty(self):
        assert _is_usdt_perpetual("") is False

    def test_malformed(self):
        assert _is_usdt_perpetual("BTC-USDT-SWAP") is False


# ── Tests: DataManager construction ─────────────────────────────


class TestDataManagerConstruction:
    def test_defaults(self):
        dm = DataManager({})
        assert dm._exchange_names == ["okx", "binance", "bybit"]
        assert dm._top_n == 30
        assert dm._refresh_hours == 4.0
        assert dm._dedup_window == 5.0
        assert dm.running is False

    def test_custom_config(self):
        config = _make_config(topSymbols=20, refreshIntervalHours=2, dedupWindowSeconds=3)
        dm = DataManager(config)
        assert dm._top_n == 20
        assert dm._refresh_hours == 2.0
        assert dm._dedup_window == 3.0

    def test_custom_exchanges(self):
        config = _make_config(exchanges=["binance"])
        dm = DataManager(config)
        assert dm._exchange_names == ["binance"]

    def test_detector_configs_passed(self):
        config = {
            "dataManager": {"exchanges": ["okx"], "topSymbols": 10},
            "priceVelocity": {"enabled": True, "cooldownSeconds": 120},
            "volumeSpike": {"enabled": False, "multiplier": 5.0},
            "futuresMetrics": {"enabled": True, "pollIntervalSeconds": 120},
        }
        dm = DataManager(config)
        assert dm._velocity_config["cooldownSeconds"] == 120
        assert dm._spike_config["multiplier"] == 5.0
        assert dm._metrics_config["pollIntervalSeconds"] == 120

    def test_alert_policy_defaults_to_all_futures_anomalies(self):
        dm = DataManager({})
        assert dm._alert_policy_enabled is True
        assert dm._allowed_event_types == {
            "price_velocity",
            "volume_spike",
            "open_interest_change",
            "funding_rate_anomaly",
        }
        assert dm._min_price_change_pct == 1.2
        assert dm._min_volume_ratio == 6.0
        assert dm._min_open_interest_change_pct == 5.0
        assert dm._min_funding_rate_abs == 0.0005
        assert dm._min_funding_rate_change_abs == 0.0003


# ── Tests: Symbol discovery ────────────────────────────────────


class TestSymbolDiscovery:
    @pytest.mark.asyncio
    async def test_filters_usdt_perpetuals(self):
        dm = DataManager(_make_config(topSymbols=100))
        mock_ex = _mock_exchange()
        symbols = await dm._discover_symbols(mock_ex, 100)
        # Only USDT perpetuals: BTC/USDT:USDT, ETH/USDT:USDT, SOL/USDT:USDT, XRP/USDT:USDT
        assert "BTC/USDT:USDT" in symbols
        assert "ETH/USDT:USDT" in symbols
        assert "DOGE/USDT" not in symbols  # Spot, filtered out
        assert "BTC/USD" not in symbols  # Wrong base

    @pytest.mark.asyncio
    async def test_sorts_by_volume_desc(self):
        dm = DataManager(_make_config(topSymbols=100))
        mock_ex = _mock_exchange()
        symbols = await dm._discover_symbols(mock_ex, 100)
        # BTC should be first (highest volume)
        assert symbols[0] == "BTC/USDT:USDT"

    @pytest.mark.asyncio
    async def test_sorts_okx_swap_by_quote_notional_not_vol_ccy(self):
        dm = DataManager(_make_config(topSymbols=2))
        mock_ex = MagicMock()
        mock_ex.exchange.fetch_tickers.return_value = {
            "BTC/USDT:USDT": {
                "last": 63_109.1,
                "quoteVolume": None,
                "baseVolume": 14_805_902.16,
                "info": {"vol24h": "14805902.16", "volCcy24h": "148059.0216"},
            },
            "SMALL/USDT:USDT": {"last": 1.0, "quoteVolume": 50_000_000},
        }

        symbols = await dm._discover_symbols(mock_ex, 2)

        assert symbols == ["BTC/USDT:USDT", "SMALL/USDT:USDT"]

    @pytest.mark.asyncio
    async def test_respects_top_n(self):
        dm = DataManager(_make_config(topSymbols=2))
        mock_ex = _mock_exchange()
        symbols = await dm._discover_symbols(mock_ex, 2)
        assert len(symbols) == 2

    @pytest.mark.asyncio
    async def test_empty_tickers(self):
        dm = DataManager(_make_config())
        mock_ex = MagicMock()
        mock_ex.exchange.fetch_tickers.return_value = {}
        symbols = await dm._discover_symbols(mock_ex, 100)
        assert symbols == []


# ── Tests: start / stop ────────────────────────────────────────


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_creates_exchange_and_starts_ws(self):
        """Test start() creates exchange, discovers symbols, starts WS."""
        dm = DataManager(_make_config())
        mock_ex = _mock_exchange()

        with patch("kairos.data.data_manager._EXCHANGE_CLASSES", {"okx": lambda: mock_ex}):
            with patch("kairos.data.data_manager.WebhookClient") as mock_wc_cls:
                mock_wc = MagicMock()
                mock_wc.is_configured.return_value = False
                mock_wc_cls.return_value = mock_wc

                with patch("kairos.data.data_manager.PriceVelocityDetector") as mock_pv_cls:
                    with patch("kairos.data.data_manager.VolumeSpikeDetector") as mock_vs_cls:
                        mock_pv = MagicMock()
                        mock_vs = MagicMock()
                        mock_pv_cls.return_value = mock_pv
                        mock_vs_cls.return_value = mock_vs

                        try:
                            await asyncio.wait_for(dm.start(), timeout=2)
                        except asyncio.TimeoutError:
                            pass  # start_websocket may hang (it spawns a thread)

        # Verify exchange started WebSocket
        mock_ex.start_websocket.assert_called()
        # Verify detectors registered
        mock_ex.register_detector.assert_called()
        assert mock_ex.register_detector.call_count >= 2

    @pytest.mark.asyncio
    async def test_start_skips_unknown_exchange(self):
        dm = DataManager(_make_config(exchanges=["nonexistent"]))
        # Should not raise
        await dm.start()
        assert dm.exchanges == {}

    @pytest.mark.asyncio
    async def test_stop_cleans_up(self):
        dm = DataManager(_make_config())
        dm.running = True
        mock_ex = MagicMock()
        mock_ex.stop_websocket = MagicMock()
        dm.exchanges = {"okx": mock_ex}

        with patch("kairos.data.data_manager.WebhookClient") as mock_wc_cls:
            mock_wc = MagicMock()
            mock_wc.close = AsyncMock()
            mock_wc_cls.return_value = mock_wc
            dm._webhook = mock_wc

            await dm.stop()

        mock_ex.stop_websocket.assert_called_once()
        mock_wc.close.assert_called_once()
        assert dm.running is False

    @pytest.mark.asyncio
    async def test_stop_handles_exchange_error(self):
        dm = DataManager(_make_config())
        dm.running = True
        mock_ex = MagicMock()
        mock_ex.stop_websocket.side_effect = RuntimeError("stop failed")
        dm.exchanges = {"okx": mock_ex}

        with patch("kairos.data.data_manager.WebhookClient") as mock_wc_cls:
            mock_wc = MagicMock()
            mock_wc.close = AsyncMock()
            mock_wc_cls.return_value = mock_wc
            dm._webhook = mock_wc

            # Should not raise despite exchange error
            await dm.stop()
        mock_wc.close.assert_called_once()


# ── Tests: Register detectors ──────────────────────────────────


class TestRegisterDetectors:
    def test_registers_both_detectors(self):
        dm = DataManager(_make_config())
        mock_ex = MagicMock()
        mock_ex.register_detector = MagicMock()

        with patch("kairos.data.data_manager.PriceVelocityDetector") as mock_pv:
            with patch("kairos.data.data_manager.VolumeSpikeDetector") as mock_vs:
                mock_pv_instance = MagicMock()
                mock_vs_instance = MagicMock()
                mock_pv.return_value = mock_pv_instance
                mock_vs.return_value = mock_vs_instance

                dm._register_detectors("okx", mock_ex)

        assert mock_ex.register_detector.call_count == 2

    def test_can_disable_velocity(self):
        config = _make_config()
        config["priceVelocity"]["enabled"] = False
        dm = DataManager(config)
        mock_ex = MagicMock()
        mock_ex.register_detector = MagicMock()

        with patch("kairos.data.data_manager.VolumeSpikeDetector") as mock_vs:
            mock_vs_instance = MagicMock()
            mock_vs.return_value = mock_vs_instance
            dm._register_detectors("okx", mock_ex)

        # Only volume spike registered
        assert mock_ex.register_detector.call_count == 1

    def test_can_disable_spike(self):
        config = _make_config()
        config["volumeSpike"]["enabled"] = False
        dm = DataManager(config)
        mock_ex = MagicMock()
        mock_ex.register_detector = MagicMock()

        with patch("kairos.data.data_manager.PriceVelocityDetector") as mock_pv:
            mock_pv_instance = MagicMock()
            mock_pv.return_value = mock_pv_instance
            dm._register_detectors("okx", mock_ex)

        assert mock_ex.register_detector.call_count == 1

    def test_registers_metrics_detector(self):
        dm = DataManager(_make_config())

        with patch("kairos.data.data_manager.FuturesMetricsDetector") as mock_fm:
            mock_instance = MagicMock()
            mock_fm.return_value = mock_instance

            dm._register_metrics_detector("okx")

        assert dm._metrics_detectors["okx"] == mock_instance
        mock_instance.on_event.assert_called_once_with(dm._on_anomaly_event)

    def test_can_disable_metrics_detector(self):
        config = _make_config()
        config["futuresMetrics"]["enabled"] = False
        dm = DataManager(config)

        dm._register_metrics_detector("okx")

        assert dm._metrics_detectors == {}


class TestFuturesMetricsPolling:
    @pytest.mark.asyncio
    async def test_poll_futures_metrics_forwards_snapshots_to_detector(self):
        dm = DataManager(_make_config())
        exchange = MagicMock()
        exchange.exchange = MagicMock()
        detector = MagicMock()
        dm.exchanges = {"okx": exchange}
        dm._symbols_by_exchange = {"okx": ["BTC/USDT:USDT"]}
        dm._metrics_detectors = {"okx": detector}

        with patch(
            "kairos.data.data_manager._collect_futures_metrics",
            return_value={
                "BTC/USDT:USDT": {
                    "price": 65000.0,
                    "open_interest": 1000000.0,
                    "funding_rate": 0.0006,
                }
            },
        ) as mock_collect:
            await dm._poll_futures_metrics()

        mock_collect.assert_called_once_with(exchange.exchange, ["BTC/USDT:USDT"], True)
        detector.on_metrics_update.assert_called_once()
        kwargs = detector.on_metrics_update.call_args.kwargs
        assert kwargs["symbol"] == "BTC/USDT:USDT"
        assert kwargs["price"] == 65000.0
        assert kwargs["open_interest"] == 1000000.0
        assert kwargs["funding_rate"] == 0.0006

    def test_collect_futures_metrics_prefers_zero_funding_rate_from_ticker(self):
        exchange_client = MagicMock()
        exchange_client.fetch_tickers.return_value = {
            "BTC/USDT:USDT": {
                "last": 65000.0,
                "openInterestValue": 1000000.0,
                "fundingRate": 0.0,
            }
        }
        exchange_client.publicGetPublicOpenInterest.return_value = {"data": []}
        exchange_client.fetch_funding_rates.return_value = {"BTC/USDT:USDT": {"fundingRate": 0.0009}}

        snapshots = _collect_futures_metrics(exchange_client, ["BTC/USDT:USDT"], True)

        assert snapshots["BTC/USDT:USDT"]["price"] == 65000.0
        assert snapshots["BTC/USDT:USDT"]["open_interest"] == 1000000.0
        assert snapshots["BTC/USDT:USDT"]["funding_rate"] == 0.0


# ── Tests: Signal dedup + dispatch ─────────────────────────────


class TestAnomalyEventDispatch:
    @pytest.mark.asyncio
    async def test_alert_policy_allows_strong_price_velocity(self):
        dm = DataManager(_make_config())
        dm.running = True
        dm._loop = asyncio.get_running_loop()

        mock_wc = MagicMock()
        mock_wc.send = AsyncMock()
        dm._webhook = mock_wc

        event = MagicMock()
        event.symbol = "BTC/USDT:USDT"
        event.event_type = "price_velocity"
        event.data = {
            "price": 65000.0,
            "price_to": 65000.0,
            "change_pct": 1.5,
            "window_seconds": 30,
            "threshold": 0.5,
        }
        event.severity = "MEDIUM"

        dm._on_anomaly_event(event)
        await asyncio.sleep(0.01)

        assert mock_wc.send.call_count == 1

    @pytest.mark.asyncio
    async def test_alert_policy_allows_strong_volume_spike_by_default(self):
        dm = DataManager(_make_config())
        dm.running = True
        dm._loop = asyncio.get_running_loop()

        mock_wc = MagicMock()
        mock_wc.send = AsyncMock()
        dm._webhook = mock_wc

        event = MagicMock()
        event.symbol = "ETH/USDT:USDT"
        event.event_type = "volume_spike"
        event.data = {"price": 3000.0, "ratio": 10.0, "window_minutes": 10}
        event.severity = "HIGH"

        dm._on_anomaly_event(event)
        await asyncio.sleep(0.01)

        assert mock_wc.send.call_count == 1

    @pytest.mark.asyncio
    async def test_alert_policy_drops_small_price_move(self):
        dm = DataManager(_make_config())
        dm.running = True
        dm._loop = asyncio.get_running_loop()

        mock_wc = MagicMock()
        mock_wc.send = AsyncMock()
        dm._webhook = mock_wc

        event = MagicMock()
        event.symbol = "SOL/USDT:USDT"
        event.event_type = "price_velocity"
        event.data = {
            "price": 100.0,
            "price_to": 100.5,
            "change_pct": 0.8,
            "window_seconds": 30,
            "threshold": 0.5,
        }
        event.severity = "MEDIUM"

        dm._on_anomaly_event(event)
        await asyncio.sleep(0.01)

        assert mock_wc.send.call_count == 0

    @pytest.mark.asyncio
    async def test_alert_policy_allows_open_interest_change_by_default(self):
        dm = DataManager(_make_config())
        dm.running = True
        dm._loop = asyncio.get_running_loop()

        mock_wc = MagicMock()
        mock_wc.send = AsyncMock()
        dm._webhook = mock_wc

        event = MagicMock()
        event.symbol = "BTC/USDT:USDT"
        event.event_type = "open_interest_change"
        event.data = {
            "price": 65000.0,
            "open_interest": 1060.0,
            "previous_open_interest": 1000.0,
            "change_pct": 6.0,
        }
        event.severity = "MEDIUM"

        dm._on_anomaly_event(event)
        await asyncio.sleep(0.01)

        assert mock_wc.send.call_count == 1

    @pytest.mark.asyncio
    async def test_alert_policy_allows_funding_rate_shift_by_default(self):
        dm = DataManager(_make_config())
        dm.running = True
        dm._loop = asyncio.get_running_loop()

        mock_wc = MagicMock()
        mock_wc.send = AsyncMock()
        dm._webhook = mock_wc

        event = MagicMock()
        event.symbol = "ETH/USDT:USDT"
        event.event_type = "funding_rate_anomaly"
        event.data = {
            "price": 3000.0,
            "funding_rate": 0.0004,
            "previous_funding_rate": 0.0001,
            "change_abs": 0.0003,
            "reason": "shift",
        }
        event.severity = "MEDIUM"

        dm._on_anomaly_event(event)
        await asyncio.sleep(0.01)

        assert mock_wc.send.call_count == 1

    @pytest.mark.asyncio
    async def test_symbol_cooldown_does_not_block_different_event_types(self):
        dm = DataManager(_make_config(symbolCooldownMinutes=240, dedupWindowSeconds=0))
        dm.running = True
        dm._loop = asyncio.get_running_loop()

        mock_wc = MagicMock()
        mock_wc.send = AsyncMock()
        dm._webhook = mock_wc

        price_event = MagicMock()
        price_event.symbol = "BTC/USDT:USDT"
        price_event.event_type = "price_velocity"
        price_event.data = {
            "price": 65000.0,
            "price_to": 65000.0,
            "change_pct": 1.5,
            "window_seconds": 30,
            "threshold": 0.5,
        }
        price_event.severity = "MEDIUM"

        oi_event = MagicMock()
        oi_event.symbol = "BTC/USDT:USDT"
        oi_event.event_type = "open_interest_change"
        oi_event.data = {
            "price": 65100.0,
            "open_interest": 1060.0,
            "previous_open_interest": 1000.0,
            "change_pct": 6.0,
        }
        oi_event.severity = "MEDIUM"

        dm._on_anomaly_event(price_event)
        dm._on_anomaly_event(oi_event)
        await asyncio.sleep(0.01)

        assert mock_wc.send.call_count == 2

    @pytest.mark.asyncio
    async def test_symbol_cooldown_still_blocks_same_event_type_repeats(self):
        dm = DataManager(_make_config(symbolCooldownMinutes=240, dedupWindowSeconds=0))
        dm.running = True
        dm._loop = asyncio.get_running_loop()

        mock_wc = MagicMock()
        mock_wc.send = AsyncMock()
        dm._webhook = mock_wc

        event1 = MagicMock()
        event1.symbol = "BTC/USDT:USDT"
        event1.event_type = "price_velocity"
        event1.data = {
            "price": 65000.0,
            "price_to": 65000.0,
            "change_pct": 1.5,
            "window_seconds": 30,
            "threshold": 0.5,
        }
        event1.severity = "MEDIUM"

        event2 = MagicMock()
        event2.symbol = "BTC/USDT:USDT"
        event2.event_type = "price_velocity"
        event2.data = {
            "price": 65100.0,
            "price_to": 65100.0,
            "change_pct": 1.6,
            "window_seconds": 30,
            "threshold": 0.5,
        }
        event2.severity = "MEDIUM"

        dm._on_anomaly_event(event1)
        dm._on_anomaly_event(event2)
        await asyncio.sleep(0.01)

        assert mock_wc.send.call_count == 1

    @pytest.mark.asyncio
    async def test_deduplicates_within_window(self):
        dm = DataManager(_make_config(dedupWindowSeconds=5))
        dm.running = True
        dm._loop = asyncio.get_running_loop()

        mock_wc = MagicMock()
        mock_wc.send = AsyncMock()
        dm._webhook = mock_wc

        event1 = MagicMock()
        event1.symbol = "BTC/USDT:USDT"
        event1.event_type = "price_velocity"
        event1.data = {
            "price": 65000.0,
            "price_to": 65000.0,
            "change_pct": 1.5,
            "window_seconds": 30,
            "threshold": 0.5,
        }
        event1.severity = "MEDIUM"

        event2 = MagicMock()
        event2.symbol = "BTC/USDT:USDT"
        event2.event_type = "price_velocity"
        event2.data = {
            "price": 65100.0,
            "price_to": 65100.0,
            "change_pct": 1.6,
            "window_seconds": 30,
            "threshold": 0.5,
        }
        event2.severity = "MEDIUM"

        # First event should be dispatched
        dm._on_anomaly_event(event1)
        # Second within dedup window should be dropped
        dm._on_anomaly_event(event2)

        # Give async callback a moment
        await asyncio.sleep(0.01)

        # Only one signal sent to webhook
        assert mock_wc.send.call_count == 1

    @pytest.mark.asyncio
    async def test_different_symbols_not_deduped(self):
        dm = DataManager(_make_config(dedupWindowSeconds=5))
        dm.running = True
        dm._loop = asyncio.get_running_loop()

        mock_wc = MagicMock()
        mock_wc.send = AsyncMock()
        dm._webhook = mock_wc

        event_btc = MagicMock(
            symbol="BTC/USDT:USDT",
            event_type="price_velocity",
            data={"price": 65000.0, "price_to": 65000.0, "change_pct": 1.5},
            severity="MEDIUM",
        )
        event_eth = MagicMock(
            symbol="ETH/USDT:USDT",
            event_type="price_velocity",
            data={"price": 3000.0, "price_to": 3000.0, "change_pct": 1.5},
            severity="MEDIUM",
        )

        dm._on_anomaly_event(event_btc)
        dm._on_anomaly_event(event_eth)

        await asyncio.sleep(0.01)
        # Both should be dispatched (different symbols)
        assert mock_wc.send.call_count == 2

    def test_drops_when_not_running(self):
        dm = DataManager(_make_config())
        dm.running = False
        dm._loop = None

        event = MagicMock(
            symbol="BTC/USDT:USDT", event_type="price_velocity", data={"price": 65000.0}, severity="MEDIUM"
        )
        # Should not raise
        dm._on_anomaly_event(event)

    def test_build_condition_price_velocity(self):
        event = MagicMock()
        event.event_type = "price_velocity"
        event.data = {"window_seconds": 30, "threshold": 0.5, "price": 65000.0}
        result = DataManager._build_condition(event)
        assert "30s" in result
        assert "0.5" in result
        assert "pct" in result

    def test_build_condition_volume_spike(self):
        event = MagicMock()
        event.event_type = "volume_spike"
        event.data = {"ratio": 3.5, "window_minutes": 10}
        result = DataManager._build_condition(event)
        assert "3.5" in result
        assert "10min" in result

    def test_build_condition_open_interest_change(self):
        event = MagicMock()
        event.event_type = "open_interest_change"
        event.data = {
            "change_pct": 6.0,
            "open_interest": 1060.0,
            "previous_open_interest": 1000.0,
        }
        result = DataManager._build_condition(event)
        assert "oi_change=6.0%" in result
        assert "current=1060.0" in result
        assert "previous=1000.0" in result

    def test_build_condition_funding_rate_anomaly(self):
        event = MagicMock()
        event.event_type = "funding_rate_anomaly"
        event.data = {
            "funding_rate": 0.0007,
            "change_abs": 0.0003,
            "reason": "extreme+shift",
        }
        result = DataManager._build_condition(event)
        assert "funding_rate=0.0007" in result
        assert "change_abs=0.0003" in result
        assert "reason=extreme+shift" in result

    def test_build_condition_unknown(self):
        event = MagicMock()
        event.event_type = "unknown_event"
        event.data = {}
        result = DataManager._build_condition(event)
        assert result == "unknown"


# ── Tests: Refresh loop ────────────────────────────────────────


class TestRefreshLoop:
    @pytest.mark.asyncio
    async def test_refresh_logs_changes(self):
        dm = DataManager(_make_config(refreshIntervalHours=0.001))  # Very short for test
        dm.running = True
        dm._refresh_task = asyncio.create_task(dm._refresh_loop())

        # Let it run one iteration
        await asyncio.sleep(0.1)
        dm.running = False
        dm._refresh_task.cancel()
        try:
            await dm._refresh_task
        except asyncio.CancelledError:
            pass
        # Should not crash
