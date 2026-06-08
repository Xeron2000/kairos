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

        # ── Dedup state ──
        self._last_sent: Dict[str, float] = {}  # "symbol__event_type" → timestamp
        self._symbol_last_sent: Dict[str, float] = {}  # symbol → timestamp
        self._dedup_lock = threading.Lock()

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
        for name, exchange in self.exchanges.items():
            symbols = symbols_map.get(name, [])
            if not symbols:
                continue

            self._register_detectors(name, exchange)
            exchange.start_websocket(symbols)
            logger.info("WebSocket started for %s with %d symbols", name, len(symbols))

        # 4. Start periodic symbol refresh
        self.running = True
        self._refresh_task = asyncio.ensure_future(self._refresh_loop())

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

    # ── Anomaly Event → Webhook ────────────────────────────────

    def _on_anomaly_event(self, event) -> None:
        """Callback from detectors: dedup + deliver via webhook."""
        if not self.running:
            return

        # Check blacklist
        if self._blacklist.is_blocked(event.symbol):
            logger.debug("Blacklist drop: %s", event.symbol)
            return

        # Dedup key: symbol + event_type
        dedup_key = f"{event.symbol}__{event.event_type}"
        now = time.time()
        with self._dedup_lock:
            last = self._last_sent.get(dedup_key, 0)
            if now - last < self._dedup_window:
                logger.debug("Dedup drop: %s (%.1fs since last)", dedup_key, now - last)
                return

            # Per-symbol cooldown: skip same symbol within cooldown window
            symbol_last = self._symbol_last_sent.get(event.symbol, 0)
            if now - symbol_last < self._symbol_cooldown:
                logger.debug(
                    "Cooldown drop: %s (%ds since last, cooldown %ds)",
                    event.symbol,
                    int(now - symbol_last),
                    int(self._symbol_cooldown),
                )
                return

            self._last_sent[dedup_key] = now
            self._symbol_last_sent[event.symbol] = now

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


# ── Helpers ────────────────────────────────────────────────────

def _is_usdt_perpetual(symbol: str) -> bool:
    """Check if a CCXT unified symbol is a USDT perpetual contract."""
    return symbol.endswith(":USDT") and "/USDT:" in symbol
