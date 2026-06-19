"""Error handling: circuit breaker, retry, and error logging.

Only the subset used by exchanges/base.py is kept.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


class ErrorSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class _ErrorCategory(Enum):
    NETWORK = "network"
    API = "api"
    CONFIGURATION = "configuration"


@dataclass
class _ErrorInfo:
    code: str
    message: str
    category: _ErrorCategory
    severity: ErrorSeverity
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    context: dict[str, Any] = field(default_factory=dict)


class CircuitBreaker:
    """Opens after N consecutive failures, auto-resets after timeout."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0) -> None:
        self._threshold = failure_threshold
        self._timeout = recovery_timeout
        self._failures = 0
        self._last_failure: float | None = None
        self._open = False

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        if self._open:
            if self._last_failure and time.time() - self._last_failure >= self._timeout:
                self._open = False
            else:
                raise RuntimeError("Circuit breaker is open")
        try:
            result = func(*args, **kwargs)
            self._failures = 0
            return result
        except Exception:
            self._failures += 1
            self._last_failure = time.time()
            if self._failures >= self._threshold:
                self._open = True
            raise


class ErrorHandler:
    """Minimal error handler — circuit breaker, retry, logging."""

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)
        self._breakers: dict[str, CircuitBreaker] = {}

    # -- circuit breaker decorator ------------------------------------------

    def circuit_breaker_protect(self, name: str, failure_threshold: int = 5, recovery_timeout: int = 60) -> Callable:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(failure_threshold, recovery_timeout)
        cb = self._breakers[name]

        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                return cb.call(func, *args, **kwargs)

            return wrapper

        return decorator

    # -- retry decorator ----------------------------------------------------

    def retry_with_backoff(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 10.0,
    ) -> Callable:
        def decorator(func: Callable) -> Callable:
            if asyncio.iscoroutinefunction(func):

                @functools.wraps(func)
                async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                    last_exc: Exception | None = None
                    for attempt in range(max_retries + 1):
                        try:
                            return await func(*args, **kwargs)
                        except Exception as e:
                            last_exc = e
                            if attempt == max_retries:
                                raise
                            delay = min(base_delay * (2**attempt), max_delay)
                            self._logger.warning(
                                "Retry %d/%d for %s after %.1fs: %s",
                                attempt + 1,
                                max_retries,
                                func.__name__,
                                delay,
                                e,
                            )
                            await asyncio.sleep(delay)
                    assert last_exc is not None
                    raise last_exc

                return async_wrapper

            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                last_exc: Exception | None = None
                for attempt in range(max_retries + 1):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        last_exc = e
                        if attempt == max_retries:
                            raise
                        delay = min(base_delay * (2**attempt), max_delay)
                        self._logger.warning(
                            "Retry %d/%d for %s after %.1fs: %s",
                            attempt + 1,
                            max_retries,
                            func.__name__,
                            delay,
                            e,
                        )
                        time.sleep(delay)
                assert last_exc is not None
                raise last_exc

            return wrapper

        return decorator

    # -- error logging helpers ----------------------------------------------

    def handle_api_error(
        self, error: Exception, context: dict[str, Any], severity: ErrorSeverity = ErrorSeverity.ERROR
    ) -> _ErrorInfo:
        return self._log(_ErrorCategory.API, error, context, severity)

    def handle_network_error(
        self, error: Exception, context: dict[str, Any], severity: ErrorSeverity = ErrorSeverity.WARNING
    ) -> _ErrorInfo:
        return self._log(_ErrorCategory.NETWORK, error, context, severity)

    def handle_config_error(
        self, error: Exception, context: dict[str, Any], severity: ErrorSeverity = ErrorSeverity.ERROR
    ) -> _ErrorInfo:
        return self._log(_ErrorCategory.CONFIGURATION, error, context, severity)

    def _log(
        self,
        cat: _ErrorCategory,
        error: Exception,
        context: dict[str, Any],
        severity: ErrorSeverity,
    ) -> _ErrorInfo:
        info = _ErrorInfo(
            code=f"{cat.value.upper()}_ERROR",
            message=str(error),
            category=cat,
            severity=severity,
            context=context,
        )
        log_msg = f"[{info.code}] {info.message} | {context}"
        if severity == ErrorSeverity.CRITICAL:
            self._logger.critical(log_msg, exc_info=error)
        elif severity == ErrorSeverity.ERROR:
            self._logger.error(log_msg, exc_info=error)
        elif severity == ErrorSeverity.WARNING:
            self._logger.warning(log_msg, exc_info=error)
        else:
            self._logger.info(log_msg, exc_info=error)
        return info


error_handler = ErrorHandler()
