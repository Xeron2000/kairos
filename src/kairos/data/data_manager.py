"""Data Manager - WebSocket orchestration, detector wiring, signal delivery.

Auto-discovers top USDT perpetual contracts per exchange, starts real-time
WebSocket feeds, routes ticks through per-exchange anomaly detectors, and
delivers deduplicated trading signals to Hermes webhook.
"""

import asyncio
import logging
import threading
import time
from typing import Any, Dict, List

import anyio

from kairos.detectors.futures_metrics import FuturesMetricsDetector
from kairos.detectors.price_velocity import PriceVelocityDetector
from kairos.detectors.volume_spike import VolumeSpikeDetector
from kairos.exchanges.binance import BinanceExchange
from kairos.exchanges.bybit import BybitExchange
from kairos.exchanges.okx import OkxExchange
from kairos.utils.blacklist import Blacklist
from kairos.utils.market_data import extract_quote_volume
from kairos.webhook import SignalEvent, WebhookClient

logger = logging.getLogger(__name__)

# Exchange class registry - ordered by priority (OKX > Binance > Bybit)
_EXCHANGE_CLASSES = {
    "okx": OkxExchange,
    "binance": BinanceExchange,
    "bybit": BybitExchange,
}
_SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}


# USDT perpetual symbol suffix patterns

# ────────────────────────────────────────────────────────────────
# DataManager
# ────────────────────────────────────────────────────────────────

class DataManager:
    """Orchestrates exchange WebSocket feeds → detectors → Hermes webhook."""

    def __init__(self, config: Dict[str, Any]):
        dm = config.get("dataManager", {})
        self._exchange_names: List[str] = dm.get("exchanges", ["okx", "binance", "bybit"])
        self._top_n: int = dm.get("topSymbols", 30)
        self._refresh_hours: float = float(dm.get("refreshIntervalHours", 4))
        self._dedup_window: float = float(dm.get("dedupWindowSeconds", 5))
        self._symbol_cooldown: float = float(dm.get("symbolCooldownMinutes", 30)) * 60

        self.exchanges: Dict[str, Any] = {}
        self._webhook = WebhookClient()
        self._blacklist = Blacklist()

        # ── Detector configs ──
        self._velocity_config = config.get("priceVelocity", {})
        self._spike_config = config.get("volumeSpike", {})
        self._metrics_config = config.get("futuresMetrics", {})

        # ── Alert policy ──
        policy = config.get("alertPolicy", {})
        self._alert_policy_enabled: bool = bool(policy.get("enabled", True))
        self._allowed_event_types: set[str] | None = _normalize_event_types(
            policy.get(
                "allowedEventTypes",
                ["price_velocity", "volume_spike", "open_interest_change", "funding_rate_anomaly"],
            )
        )
        self._min_severity_rank: int = _severity_rank(policy.get("minSeverity", "MEDIUM"))
        self._min_price_change_pct: float = _float_config(policy.get("minPriceChangePct", 1.2), 1.2)
        self._min_volume_ratio: float = _float_config(policy.get("minVolumeRatio", 6.0), 6.0)
        self._min_open_interest_change_pct: float = _float_config(
            policy.get("minOpenInterestChangePct", 5.0), 5.0
        )
        self._min_funding_rate_abs: float = _float_config(policy.get("minFundingRateAbs", 0.0005), 0.0005)
        self._min_funding_rate_change_abs: float = _float_config(
            policy.get("minFundingRateChangeAbs", 0.0003), 0.0003
        )
        self._metrics_poll_interval: float = _float_config(self._metrics_config.get("pollIntervalSeconds", 300), 300)
        self._fetch_funding_per_symbol: bool = bool(self._metrics_config.get("fetchFundingPerSymbol", True))

        # ── Dedup state ──
        self._last_sent: Dict[str, float] = {}  # "symbol__event_type" → timestamp
        self._symbol_event_last_sent: Dict[str, float] = {}  # "symbol__event_type" → timestamp
        self._dedup_lock = threading.Lock()

        # ── Metrics polling state ──
        self._symbols_by_exchange: Dict[str, List[str]] = {}
        self._metrics_detectors: Dict[str, FuturesMetricsDetector] = {}
        self._metrics_task: asyncio.Task | None = None

        # ── Thread-safe webhook dispatch ──
        self._loop: asyncio.AbstractEventLoop | None = None

        # ── Lifecycle ──
        self.running = False
        self._refresh_task: asyncio.Task | None = None

    # ── Bootstrap ──────────────────────────────────────────────

    async def start(self) -> None:
        """Initialize exchanges, discover symbols, start detectors + WebSocket."""
        logger.info("DataManager starting...")
        self._loop = asyncio.get_running_loop()

        # 1. Create exchange instances
        for name in self._exchange_names:
            cls = _EXCHANGE_CLASSES.get(name)
            if cls is None:
                logger.warning("Unknown exchange: %s - skipping", name)
                continue
            self.exchanges[name] = cls()
            logger.info("Exchange created: %s", name)

        # 2. Discover top symbols per exchange
        symbols_map: Dict[str, List[str]] = {}
        for name, exchange in self.exchanges.items():
            try:
                symbols = await self._discover_symbols(exchange, self._top_n)
                symbols_map[name] = symbols
                logger.info(
                    "Symbols discovered for %s: %d (top %d)",
                    name,
                    len(symbols),
                    self._top_n,
                )
            except Exception:
                logger.exception("Symbol discovery failed for %s - skipping WS", name)
                symbols_map[name] = []

        # 3. Register detectors and start WebSocket
        self._symbols_by_exchange = symbols_map
        for name, exchange in self.exchanges.items():
            symbols = symbols_map.get(name, [])
            if not symbols:
                continue

            self._register_detectors(name, exchange)
            self._register_metrics_detector(name)
            exchange.start_websocket(symbols)
            logger.info("WebSocket started for %s with %d symbols", name, len(symbols))

        # 4. Start periodic symbol refresh
        self.running = True
        self._refresh_task = asyncio.ensure_future(self._refresh_loop())
        if self._metrics_detectors:
            self._metrics_task = asyncio.ensure_future(self._futures_metrics_loop())

        logger.info(
            "DataManager started: exchanges=%s webhook=%s",
            list(self.exchanges.keys()),
            "configured" if self._webhook.is_configured() else "UNCONFIGURED",
        )

    async def stop(self) -> None:
        """Graceful shutdown - stop WebSocket, cancel refresh, close webhook."""
        logger.info("DataManager stopping...")
        self.running = False

        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass

        if self._metrics_task:
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass

        for name, exchange in self.exchanges.items():
            try:
                exchange.stop_websocket()
                logger.info("WebSocket stopped: %s", name)
            except Exception:
                logger.exception("Error stopping exchange: %s", name)

        await self._webhook.close()
        logger.info("DataManager stopped")

    # ── Symbol Discovery ──────────────────────────────────────

    async def _discover_symbols(self, exchange, top_n: int) -> List[str]:
        """Discover top `top_n` USDT perpetual symbols by 24h volume."""
        tickers = await anyio.to_thread.run_sync(exchange.exchange.fetch_tickers)  # type: ignore[attr-defined]

        candidates: List[tuple] = []  # (symbol, volume)
        for sym, ticker in tickers.items():
            if ticker is None:
                continue
            if not isinstance(sym, str):
                continue
            # Filter USDT perpetual: symbol ends with ":USDT" or "/USDT:"
            if not (_is_usdt_perpetual(sym)):
                continue
            vol = extract_quote_volume(ticker)
            if vol <= 0:
                continue
            candidates.append((sym, vol))

        candidates.sort(key=lambda x: x[1], reverse=True)
        symbols = [s for s, _ in candidates[:top_n]]
        # Filter blacklisted
        symbols = [s for s in symbols if not self._blacklist.is_blocked(s)]
        return symbols

    # ── Detectors ──────────────────────────────────────────────

    def _register_detectors(self, name: str, exchange) -> None:
        """Register per-exchange velocity + spike detectors."""
        if self._velocity_config.get("enabled", True):
            v = PriceVelocityDetector(self._velocity_config)
            v.on_event(self._on_anomaly_event)
            exchange.register_detector(v)
            logger.info("Velocity detector registered: %s", name)

        if self._spike_config.get("enabled", True):
            s = VolumeSpikeDetector(self._spike_config)
            s.on_event(self._on_anomaly_event)
            exchange.register_detector(s)
            logger.info("Spike detector registered: %s", name)

    def _register_metrics_detector(self, name: str) -> None:
        """Register periodic futures metrics detector for OI/funding anomalies."""
        if not self._metrics_config.get("enabled", True):
            return
        detector = FuturesMetricsDetector(self._metrics_config)
        detector.on_event(self._on_anomaly_event)
        self._metrics_detectors[name] = detector
        logger.info("Futures metrics detector registered: %s", name)

    # ── Anomaly Event → Webhook ────────────────────────────────

    def _on_anomaly_event(self, event) -> None:
        """Callback from detectors: dedup + deliver via webhook."""
        if not self.running:
            return

        # Check blacklist
        if self._blacklist.is_blocked(event.symbol):
            logger.debug("Blacklist drop: %s", event.symbol)
            return

        if not self._passes_alert_policy(event):
            return

        # Dedup key: symbol + event_type
        dedup_key = f"{event.symbol}__{event.event_type}"
        now = time.time()
        with self._dedup_lock:
            last = self._last_sent.get(dedup_key, 0)
            if now - last < self._dedup_window:
                logger.debug("Dedup drop: %s (%.1fs since last)", dedup_key, now - last)
                return

            # Per-symbol+event cooldown suppresses repeats without hiding a different futures anomaly.
            symbol_event_last = self._symbol_event_last_sent.get(dedup_key, 0)
            if now - symbol_event_last < self._symbol_cooldown:
                logger.debug(
                    "Cooldown drop: %s (%ds since last, cooldown %ds)",
                    dedup_key,
                    int(now - symbol_event_last),
                    int(self._symbol_cooldown),
                )
                return

            self._last_sent[dedup_key] = now
            self._symbol_event_last_sent[dedup_key] = now

        # Build signal
        data = event.data
        signal = SignalEvent(
            event=event.event_type,
            symbol=event.symbol,
            price=data.get("price_to", data.get("price", 0)),
            condition=self._build_condition(event),
            exchange="",  # stripped per design
            change_pct=data.get("change_pct", 0),
            severity=event.severity,
        )

        # Schedule async webhook send from WS thread → main loop
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self._webhook.send(signal), self._loop
            )

    def _passes_alert_policy(self, event) -> bool:
        """Return True when an anomaly is worth forwarding to Hermes."""
        if not self._alert_policy_enabled:
            return True

        event_type = str(event.event_type).strip().lower()
        if self._allowed_event_types is not None and event_type not in self._allowed_event_types:
            logger.debug("Alert policy drop: event_type=%s symbol=%s", event.event_type, event.symbol)
            return False

        if _severity_rank(event.severity, default=0) < self._min_severity_rank:
            logger.debug(
                "Alert policy drop: severity=%s symbol=%s event_type=%s",
                event.severity,
                event.symbol,
                event.event_type,
            )
            return False

        data = event.data or {}
        if event_type == "price_velocity":
            change_pct = abs(_float_config(data.get("change_pct", 0.0), 0.0))
            if change_pct < self._min_price_change_pct:
                logger.debug(
                    "Alert policy drop: change_pct=%.2f min=%.2f symbol=%s",
                    change_pct,
                    self._min_price_change_pct,
                    event.symbol,
                )
                return False

        if event_type == "volume_spike":
            ratio = _float_config(data.get("ratio", 0.0), 0.0)
            if ratio < self._min_volume_ratio:
                logger.debug(
                    "Alert policy drop: ratio=%.2f min=%.2f symbol=%s",
                    ratio,
                    self._min_volume_ratio,
                    event.symbol,
                )
                return False

        if event_type == "open_interest_change":
            change_pct = abs(_float_config(data.get("change_pct", 0.0), 0.0))
            if change_pct < self._min_open_interest_change_pct:
                logger.debug(
                    "Alert policy drop: oi_change_pct=%.2f min=%.2f symbol=%s",
                    change_pct,
                    self._min_open_interest_change_pct,
                    event.symbol,
                )
                return False

        if event_type == "funding_rate_anomaly":
            funding_rate = abs(_float_config(data.get("funding_rate", 0.0), 0.0))
            change_abs = abs(_float_config(data.get("change_abs", 0.0), 0.0))
            if funding_rate < self._min_funding_rate_abs and change_abs < self._min_funding_rate_change_abs:
                logger.debug(
                    "Alert policy drop: funding=%.6f min=%.6f change=%.6f min_change=%.6f symbol=%s",
                    funding_rate,
                    self._min_funding_rate_abs,
                    change_abs,
                    self._min_funding_rate_change_abs,
                    event.symbol,
                )
                return False

        return True

    @staticmethod
    def _build_condition(event) -> str:
        """Build human-readable condition string from AnomalyEvent data."""
        data = event.data
        if event.event_type == "price_velocity":
            ws = data.get("window_seconds", "?")
            th = data.get("threshold", "?")
            return f"{ws}s_{th}pct"
        if event.event_type == "volume_spike":
            ratio = data.get("ratio", "?")
            wm = data.get("window_minutes", "?")
            return f"{ratio}x_{wm}min"
        if event.event_type == "open_interest_change":
            change = data.get("change_pct", "?")
            current = data.get("open_interest", "?")
            previous = data.get("previous_open_interest", "?")
            return f"oi_change={change}% current={current} previous={previous}"
        if event.event_type == "funding_rate_anomaly":
            rate = data.get("funding_rate", "?")
            change = data.get("change_abs", "?")
            reason = data.get("reason", "?")
            return f"funding_rate={rate} change_abs={change} reason={reason}"
        return "unknown"

    # ── Periodic Refresh ──────────────────────────────────────

    async def _refresh_loop(self) -> None:
        """Periodically refresh top symbols and log changes.

        New symbols are logged but not auto-subscribed - restart kairos-mcp to
        pick up WebSocket subscription changes.
        """
        while self.running:
            await asyncio.sleep(self._refresh_hours * 3600)
            if not self.running:
                break

            logger.info("Periodic symbol refresh starting...")
            for name, exchange in self.exchanges.items():
                try:
                    new_symbols = await self._discover_symbols(exchange, self._top_n)
                    current_symbols = set(exchange.last_prices.keys())
                    added = set(new_symbols) - current_symbols
                    removed = current_symbols - set(new_symbols)
                    if added or removed:
                        logger.warning(
                            "%s top-100 changed: +%d -%d. Restart kairos-mcp to apply.",
                            name,
                            len(added),
                            len(removed),
                        )
                except Exception:
                    logger.exception("Refresh failed for %s", name)

    # ── Futures Metrics Polling ────────────────────────────────

    async def _futures_metrics_loop(self) -> None:
        """Poll open-interest and funding-rate metrics for discovered symbols."""
        while self.running:
            try:
                await self._poll_futures_metrics()
            except Exception:
                logger.exception("Futures metrics poll failed")
            await asyncio.sleep(self._metrics_poll_interval)

    async def _poll_futures_metrics(self) -> None:
        for name, detector in self._metrics_detectors.items():
            exchange = self.exchanges.get(name)
            if exchange is None:
                continue
            symbols = self._symbols_by_exchange.get(name, [])
            if not symbols:
                continue
            snapshots = await anyio.to_thread.run_sync(
                _collect_futures_metrics,
                exchange.exchange,
                symbols,
                self._fetch_funding_per_symbol,
            )
            now = time.time()
            for symbol, data in snapshots.items():
                detector.on_metrics_update(
                    symbol=symbol,
                    timestamp=now,
                    price=data.get("price", 0.0),
                    open_interest=data.get("open_interest"),
                    funding_rate=data.get("funding_rate"),
                )


# ── Helpers ────────────────────────────────────────────────────

def _is_usdt_perpetual(symbol: str) -> bool:
    """Check if a CCXT unified symbol is a USDT perpetual contract."""
    return symbol.endswith(":USDT") and "/USDT:" in symbol


def _collect_futures_metrics(
    exchange_client: Any,
    symbols: List[str],
    fetch_funding_per_symbol: bool,
) -> Dict[str, Dict[str, float | None]]:
    """Collect price, open-interest, and funding snapshots for symbols."""
    tickers = _fetch_metrics_tickers(exchange_client)
    oi_by_symbol = _fetch_open_interest_map(exchange_client)
    funding_by_symbol = _fetch_funding_rate_map(exchange_client, symbols, fetch_funding_per_symbol)

    snapshots: Dict[str, Dict[str, float | None]] = {}
    for symbol in symbols:
        ticker = _ticker_for_symbol(tickers, symbol)
        price = _extract_price(ticker)
        ticker_open_interest = _extract_open_interest(ticker)
        ticker_funding_rate = _extract_funding_rate(ticker)
        open_interest = ticker_open_interest if ticker_open_interest is not None else oi_by_symbol.get(symbol)
        funding_rate = ticker_funding_rate if ticker_funding_rate is not None else funding_by_symbol.get(symbol)
        snapshots[symbol] = {
            "price": price,
            "open_interest": open_interest,
            "funding_rate": funding_rate,
        }
    return snapshots


def _fetch_metrics_tickers(exchange_client: Any) -> Dict[str, Any]:
    fetch_tickers = getattr(exchange_client, "fetch_tickers", None)
    if not callable(fetch_tickers):
        return {}
    try:
        payload = fetch_tickers(params={"instType": "SWAP"})
    except TypeError:
        try:
            payload = fetch_tickers()
        except Exception as exc:
            logger.debug("Metrics fetch_tickers failed: %s", exc)
            return {}
    except Exception as exc:
        logger.debug("Metrics fetch_tickers with swap params failed: %s", exc)
        try:
            payload = fetch_tickers()
        except Exception as fallback_exc:
            logger.debug("Metrics fetch_tickers fallback failed: %s", fallback_exc)
            return {}
    return payload if isinstance(payload, dict) else {}


def _fetch_open_interest_map(exchange_client: Any) -> Dict[str, float]:
    """Fetch open interest in bulk when supported by the exchange client."""
    method = getattr(exchange_client, "publicGetPublicOpenInterest", None)
    if not callable(method):
        return {}
    try:
        payload = method({"instType": "SWAP"})
    except Exception as exc:
        logger.debug("Bulk open-interest fetch failed: %s", exc)
        return {}

    data = payload.get("data", []) if isinstance(payload, dict) else []
    result: Dict[str, float] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        symbol = _symbol_from_inst_id(row.get("instId"))
        value = _float_config(row.get("oiUsd") or row.get("oiCcy") or row.get("oi"), 0.0)
        if symbol and value:
            result[symbol] = value
    return result


def _fetch_funding_rate_map(
    exchange_client: Any,
    symbols: List[str],
    fetch_per_symbol: bool,
) -> Dict[str, float]:
    """Fetch funding rates, using bulk when available and per-symbol fallback when configured."""
    result: Dict[str, float] = {}
    fetch_funding_rates = getattr(exchange_client, "fetch_funding_rates", None)
    if callable(fetch_funding_rates):
        try:
            payload = fetch_funding_rates(symbols)
        except TypeError:
            try:
                payload = fetch_funding_rates()
            except Exception as exc:
                logger.debug("Bulk funding-rate fetch failed: %s", exc)
                payload = {}
        except Exception as exc:
            logger.debug("Bulk funding-rate fetch failed: %s", exc)
            payload = {}
        result.update(_funding_rates_from_payload(payload))

    missing = [symbol for symbol in symbols if symbol not in result]
    fetch_funding_rate = getattr(exchange_client, "fetch_funding_rate", None)
    if not fetch_per_symbol or not callable(fetch_funding_rate):
        return result

    for symbol in missing:
        try:
            payload = fetch_funding_rate(symbol)
        except Exception as exc:
            logger.debug("Funding-rate fetch failed for %s: %s", symbol, exc)
            continue
        rate = _extract_funding_rate(payload if isinstance(payload, dict) else {})
        if rate is not None:
            result[symbol] = rate
    return result


def _funding_rates_from_payload(payload: Any) -> Dict[str, float]:
    if not isinstance(payload, dict):
        return {}
    result: Dict[str, float] = {}
    items = payload.items()
    if isinstance(payload.get("data"), list):
        items = [(row.get("symbol") or row.get("instId"), row) for row in payload["data"] if isinstance(row, dict)]
    for key, value in items:
        if not isinstance(value, dict):
            continue
        symbol = _normalize_metric_symbol(str(key or value.get("symbol") or ""))
        if not symbol:
            symbol = _symbol_from_inst_id(value.get("instId") or value.get("info", {}).get("instId"))
        rate = _extract_funding_rate(value)
        if symbol and rate is not None:
            result[symbol] = rate
    return result


def _ticker_for_symbol(tickers: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    ticker = tickers.get(symbol)
    if isinstance(ticker, dict):
        return ticker
    normalized = _normalize_metric_symbol(symbol)
    for key, value in tickers.items():
        if _normalize_metric_symbol(str(key)) == normalized and isinstance(value, dict):
            return value
    return {}


def _extract_price(payload: Dict[str, Any]) -> float:
    for key in ("last", "close", "markPrice", "indexPrice"):
        value = _float_config(payload.get(key), 0.0)
        if value:
            return value
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    for key in ("last", "lastPrice", "markPx", "idxPx"):
        value = _float_config(info.get(key), 0.0)
        if value:
            return value
    return 0.0


def _extract_open_interest(payload: Dict[str, Any]) -> float | None:
    for key in ("openInterestValue", "openInterestAmount", "openInterest", "oiUsd", "oiCcy"):
        value = _float_config(payload.get(key), 0.0)
        if value:
            return value
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    for key in ("openInterestValue", "openInterestAmount", "openInterest", "oiUsd", "oiCcy"):
        value = _float_config(info.get(key), 0.0)
        if value:
            return value
    return None


def _extract_funding_rate(payload: Dict[str, Any]) -> float | None:
    for key in ("fundingRate", "funding_rate"):
        if key in payload:
            return _float_config(payload.get(key), 0.0)
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    for key in ("fundingRate", "funding_rate"):
        if key in info:
            return _float_config(info.get(key), 0.0)
    return None


def _symbol_from_inst_id(value: Any) -> str:
    if not value:
        return ""
    parts = str(value).split("-")
    if len(parts) >= 2:
        return f"{parts[0].upper()}/{parts[1].upper()}:USDT"
    return ""


def _normalize_metric_symbol(value: str) -> str:
    symbol = value.strip().upper()
    if not symbol:
        return ""
    if "-" in symbol and "/" not in symbol:
        return _symbol_from_inst_id(symbol)
    if "/USDT" in symbol and ":" not in symbol:
        return f"{symbol}:USDT"
    return symbol


def _normalize_event_types(value: Any) -> set[str] | None:
    """Normalize an event-type allowlist; empty means allow all types."""
    if value is None:
        return None
    if isinstance(value, str):
        raw_values = [value]
    else:
        try:
            raw_values = list(value)
        except TypeError:
            raw_values = [value]
    normalized = {str(item).strip().lower() for item in raw_values if str(item).strip()}
    return normalized or None


def _severity_rank(value: Any, default: int = _SEVERITY_RANK["LOW"]) -> int:
    """Map LOW/MEDIUM/HIGH to sortable ranks."""
    return _SEVERITY_RANK.get(str(value).strip().upper(), default)


def _float_config(value: Any, default: float) -> float:
    """Parse numeric config values with a safe fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
