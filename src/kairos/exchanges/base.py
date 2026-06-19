import asyncio
import bisect
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import deque

import ccxt

from kairos.detectors.base import BaseDetector
from kairos.utils.cache_manager import price_cache
from kairos.utils.error_handler import ErrorSeverity, error_handler
from kairos.utils.performance_monitor import performance_monitor

# Historical price storage configuration
HISTORICAL_PRICE_MAX_AGE_MS = 60 * 60 * 1000  # 1 hour in milliseconds
HISTORICAL_PRICE_MAX_LEN = 3600  # Max records per symbol (1 per second for 1 hour)
HISTORICAL_PRICE_CLEANUP_INTERVAL = 60  # Cleanup every 60 seconds


class BaseExchange(ABC):
    def __init__(self, exchange_name):
        try:
            if exchange_name not in ccxt.exchanges:
                raise ValueError(f"Exchange {exchange_name} not supported by ccxt")

            self.exchange_name = exchange_name
            self.exchange = getattr(ccxt, exchange_name)(
                {
                    "enableRateLimit": True,
                    "timeout": 8000,
                }
            )

            # WebSocket related properties
            self.ws = None
            self.ws_connected = False
            self.ws_data = {}
            self.last_prices = {}
            self.historical_prices = {}
            self._price_lock = threading.Lock()
            self._last_cleanup_time = 0  # Track last cleanup time
            self.ws_thread = None
            self.running = False

            # Anomaly detectors (registered externally)
            self._detectors: list[BaseDetector] = []

            logging.info(f"BaseExchange initialized for {exchange_name}")

        except Exception as e:
            error_handler.handle_config_error(
                e,
                {
                    "component": "BaseExchange",
                    "operation": "initialization",
                    "exchange_name": exchange_name,
                },
                ErrorSeverity.CRITICAL,
            )
            raise

    def _get_ohlcv_params(self, symbol):
        """Parameters forwarded to fetch_ohlcv for historical data."""
        return {}

    def register_detector(self, detector: BaseDetector) -> None:
        """Register an anomaly detector to receive price/volume updates."""
        self._detectors.append(detector)

    def _notify_detectors_price(self, symbol: str, price: float) -> None:
        """Notify all detectors of a price update (called from WS thread)."""
        if not (0 < price < 1e12):
            logging.debug("Ignoring out-of-range price for %s: %s", symbol, price)
            return
        ts = time.time()
        for d in self._detectors:
            try:
                d.on_price_update(symbol, price, ts)
            except Exception as e:
                logging.debug("Detector price error: %s", e)

    def _notify_detectors_volume(self, symbol: str, cumulative_volume: float) -> None:
        """Notify all detectors of a volume update (called from WS thread)."""
        ts = time.time()
        for d in self._detectors:
            try:
                d.on_volume_update(symbol, cumulative_volume, ts)
            except Exception as e:
                logging.debug("Detector volume error: %s", e)

    def _store_historical_price(self, symbol: str, price: float) -> None:
        """Store historical price with automatic cleanup.

        Uses deque for O(1) append and automatic size limiting.
        Periodic cleanup removes entries older than HISTORICAL_PRICE_MAX_AGE_MS.
        """
        timestamp = int(time.time() * 1000)

        with self._price_lock:
            if symbol not in self.historical_prices:
                self.historical_prices[symbol] = deque(maxlen=HISTORICAL_PRICE_MAX_LEN)
            self.historical_prices[symbol].append((timestamp, price))

        # Periodic cleanup (not on every message)
        current_time = time.time()
        if current_time - self._last_cleanup_time >= HISTORICAL_PRICE_CLEANUP_INTERVAL:
            self._cleanup_historical_prices()
            self._last_cleanup_time = current_time

    def _cleanup_historical_prices(self) -> None:
        """Remove historical price entries older than HISTORICAL_PRICE_MAX_AGE_MS."""
        cutoff = int(time.time() * 1000) - HISTORICAL_PRICE_MAX_AGE_MS
        total_removed = 0

        with self._price_lock:
            for symbol in list(self.historical_prices.keys()):
                prices = self.historical_prices[symbol]
                original_len = len(prices)
                while prices and prices[0][0] < cutoff:
                    prices.popleft()
                total_removed += original_len - len(prices)
                if not prices:
                    del self.historical_prices[symbol]

        if total_removed > 0:
            logging.debug(
                "Cleaned up %d old historical price entries, %d symbols remaining",
                total_removed,
                len(self.historical_prices),
            )

    @abstractmethod
    async def _ws_connect(self, symbols):
        """Establish WebSocket connection and subscribe to market data"""
        raise NotImplementedError

    @error_handler.circuit_breaker_protect("websocket_start", failure_threshold=5, recovery_timeout=60)
    def start_websocket(self, symbols):
        """Start WebSocket connection thread"""
        try:
            logging.info(f"Starting WebSocket connection for {self.exchange_name}, number of symbols: {len(symbols)}")

            # Print symbol list for debugging
            for i, symbol in enumerate(symbols):
                logging.debug(f"Symbol {i + 1}/{len(symbols)}: {symbol}")

            self.running = True

            def run_websocket_loop():
                logging.info(f"WebSocket thread started, creating new event loop for {self.exchange_name}")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._ws_connect(symbols))
                except Exception as e:
                    error_handler.handle_network_error(
                        e,
                        {
                            "component": "BaseExchange",
                            "operation": "websocket_loop",
                            "exchange": self.exchange_name,
                        },
                        ErrorSeverity.ERROR,
                    )
                    logging.error(f"Error running WebSocket thread: {e}")
                finally:
                    logging.info("WebSocket thread ending, closing event loop")
                    loop.close()

            self.ws_thread = threading.Thread(target=run_websocket_loop)
            self.ws_thread.daemon = True
            self.ws_thread.start()
            logging.info(f"WebSocket thread started: {self.ws_thread.name}")

            # Wait for connection to establish
            timeout = 10
            start_time = time.time()
            logging.info(f"Waiting for WebSocket connection to establish, timeout: {timeout} seconds")
            while not self.ws_connected and time.time() - start_time < timeout:
                time.sleep(0.1)

            if not self.ws_connected:
                error_msg = "WebSocket connection establishment failed, timeout"
                error_handler.handle_network_error(
                    Exception(error_msg),
                    {
                        "component": "BaseExchange",
                        "operation": "websocket_start",
                        "exchange": self.exchange_name,
                    },
                    ErrorSeverity.ERROR,
                )
                raise ConnectionError(error_msg)

            logging.info(f"WebSocket connection successfully established, exchange: {self.exchange_name}")

        except Exception as e:
            error_handler.handle_network_error(
                e,
                {
                    "component": "BaseExchange",
                    "operation": "websocket_start",
                    "exchange": self.exchange_name,
                },
                ErrorSeverity.ERROR,
            )
            raise

    def stop_websocket(self):
        """Stop WebSocket connection"""
        self.running = False
        if self.ws_thread:
            self.ws_thread.join(timeout=5)
            self.ws_thread = None
        logging.info(f"WebSocket connection closed for {self.exchange_name}")

    @error_handler.retry_with_backoff(max_retries=3, base_delay=1.0, max_delay=10.0)
    @performance_monitor.time_function("get_current_prices")
    async def get_current_prices(self, symbols):
        """Get current prices (from WebSocket data)"""
        try:
            # First try to get prices from cache
            cached_prices = price_cache.get_prices(symbols)

            # Check which symbols are missing from cache
            missing_symbols = [s for s in symbols if cached_prices.get(s) is None]

            if not missing_symbols:
                performance_monitor.record_counter("cache_hits", len(symbols))
                return cached_prices

            # For missing symbols, fetch from API or WebSocket
            result = cached_prices.copy()

            if not self.ws_connected:
                # If WebSocket not connected, use API call (non-blocking)
                try:
                    timer_id = performance_monitor.start_timer("api_price_fetch")
                    for symbol in missing_symbols:
                        ticker = await asyncio.to_thread(self.exchange.fetch_ticker, symbol)
                        if ticker and hasattr(ticker, "__getitem__") and "last" in ticker and ticker["last"]:
                            price = float(ticker["last"])
                            result[symbol] = price
                            price_cache.set_price(symbol, price)
                            performance_monitor.record_counter("cache_misses", 1)
                    performance_monitor.stop_timer(timer_id, "api_price_fetch")
                except Exception as e:
                    error_handler.handle_api_error(
                        e,
                        {
                            "component": "BaseExchange",
                            "operation": "get_current_prices_api",
                            "symbols": symbols,
                        },
                        ErrorSeverity.WARNING,
                    )
                    performance_monitor.record_counter("api_errors", 1)
                    logging.error(f"Error getting current prices via API: {e}")

                return result

            # If WebSocket is connected, try to get from WebSocket data
            with self._price_lock:
                ws_snapshot = {s: self.last_prices[s] for s in missing_symbols if s in self.last_prices}
            for symbol, price in ws_snapshot.items():
                result[symbol] = price
                price_cache.set_price(symbol, price)
                performance_monitor.record_counter("cache_misses", 1)

            # For symbols still missing, use API
            still_missing = [s for s in symbols if result.get(s) is None]
            if still_missing:
                try:
                    timer_id = performance_monitor.start_timer("api_price_fetch_missing")
                    for symbol in still_missing:
                        ticker = await asyncio.to_thread(self.exchange.fetch_ticker, symbol)
                        if ticker and hasattr(ticker, "__getitem__") and "last" in ticker and ticker["last"]:
                            price = float(ticker["last"])
                            result[symbol] = price
                            price_cache.set_price(symbol, price)
                            performance_monitor.record_counter("cache_misses", 1)
                    performance_monitor.stop_timer(timer_id, "api_price_fetch_missing")
                except Exception as e:
                    error_handler.handle_api_error(
                        e,
                        {
                            "component": "BaseExchange",
                            "operation": "get_current_prices_missing",
                            "symbols": still_missing,
                        },
                        ErrorSeverity.WARNING,
                    )
                    performance_monitor.record_counter("api_errors", 1)
                    logging.error(f"Error getting current prices for missing symbols: {e}")

            # Record cache performance metrics
            total_symbols = len(symbols)
            cache_hits = total_symbols - len(missing_symbols)
            hit_rate = (cache_hits / total_symbols * 100) if total_symbols > 0 else 0
            performance_monitor.record_gauge("cache_hit_rate", hit_rate)

            return result

        except Exception as e:
            error_handler.handle_api_error(
                e,
                {
                    "component": "BaseExchange",
                    "operation": "get_current_prices",
                    "symbols": symbols,
                },
                ErrorSeverity.ERROR,
            )
            performance_monitor.record_counter("get_current_prices_errors", 1)
            raise

    def _fetch_ohlcv_price(self, symbol: str, minutes: int):
        """Fetch close price from N minutes ago via REST API (blocking). Returns float or None."""
        try:
            since = int((time.time() - minutes * 60) * 1000)
            ohlcv = self.exchange.fetch_ohlcv(symbol, "1m", since=since, limit=1, params=self._get_ohlcv_params(symbol))
            if ohlcv and len(ohlcv) > 0:
                return float(ohlcv[0][4])
        except Exception as e:
            logging.error("Error fetching OHLCV for %s: %s", symbol, e)
        return None

    @staticmethod
    def _bisect_closest(prices_deque, target_time_ms):
        """Find the price entry closest to target_time_ms using binary search.

        Assumes prices_deque is sorted by timestamp (append-only).
        Returns (timestamp_ms, price) or None.
        """
        if not prices_deque:
            return None
        timestamps = [entry[0] for entry in prices_deque]
        idx = bisect.bisect_left(timestamps, target_time_ms)
        # Check idx and idx-1 for closest
        best = None
        best_diff = float("inf")
        for candidate_idx in (idx - 1, idx):
            if 0 <= candidate_idx < len(prices_deque):
                diff = abs(prices_deque[candidate_idx][0] - target_time_ms)
                if diff < best_diff:
                    best_diff = diff
                    best = prices_deque[candidate_idx]
        return best

    async def get_price_minutes_ago(self, symbols, minutes):
        """Get prices from specified minutes ago (from historical data)"""
        if not self.ws_connected:
            result = {}
            for symbol in symbols:
                price = await asyncio.to_thread(self._fetch_ohlcv_price, symbol, minutes)
                if price is not None:
                    result[symbol] = price
            return result

        target_time = int(time.time() * 1000) - (minutes * 60 * 1000)
        result = {}

        for symbol in symbols:
            with self._price_lock:
                has_history = symbol in self.historical_prices and self.historical_prices[symbol]
                snapshot = list(self.historical_prices[symbol]) if has_history else []

            if snapshot:
                closest = self._bisect_closest(snapshot, target_time)

                if closest is None or abs(closest[0] - target_time) > (10 * 60 * 1000):
                    price = await asyncio.to_thread(self._fetch_ohlcv_price, symbol, minutes)
                    if price is not None:
                        result[symbol] = price
                else:
                    result[symbol] = closest[1]
            else:
                price = await asyncio.to_thread(self._fetch_ohlcv_price, symbol, minutes)
                if price is not None:
                    result[symbol] = price

        return result

    def close(self):
        """Close connection"""
        self.stop_websocket()
        if hasattr(self.exchange, "close"):
            self.exchange.close()

    @error_handler.circuit_breaker_protect("websocket_reconnect", failure_threshold=3, recovery_timeout=30)
    def check_ws_connection(self):
        """Check WebSocket connection status and attempt to reconnect"""
        try:
            if not self.ws_connected and self.running:
                logging.warning(f"{self.exchange_name} WebSocket connection disconnected, attempting to reconnect")
                # Get currently subscribed symbols
                symbols = list(self.last_prices.keys())
                if not symbols:
                    error_handler.handle_network_error(
                        Exception("No available symbol list for reconnection"),
                        {
                            "component": "BaseExchange",
                            "operation": "check_ws_connection",
                            "exchange": self.exchange_name,
                        },
                        ErrorSeverity.ERROR,
                    )
                    logging.error("No available symbol list for reconnection")
                    return False

                # Restart WebSocket
                try:
                    self.start_websocket(symbols)
                    return True
                except Exception as e:
                    error_handler.handle_network_error(
                        e,
                        {
                            "component": "BaseExchange",
                            "operation": "websocket_reconnect",
                            "exchange": self.exchange_name,
                        },
                        ErrorSeverity.ERROR,
                    )
                    logging.error(f"WebSocket reconnection failed: {e}")
                    return False
            return self.ws_connected

        except Exception as e:
            error_handler.handle_network_error(
                e,
                {
                    "component": "BaseExchange",
                    "operation": "check_ws_connection",
                    "exchange": self.exchange_name,
                },
                ErrorSeverity.ERROR,
            )
            return False
