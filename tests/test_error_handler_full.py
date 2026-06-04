"""Tests for error_handler module — matches current API."""

from datetime import datetime

import pytest

from kairos.utils.error_handler import (
    CircuitBreaker,
    ErrorCategory,
    ErrorHandler,
    ErrorInfo,
    ErrorSeverity,
    error_handler,
)


class TestErrorSeverity:
    def test_values(self):
        assert ErrorSeverity.INFO.value == "info"
        assert ErrorSeverity.WARNING.value == "warning"
        assert ErrorSeverity.ERROR.value == "error"
        assert ErrorSeverity.CRITICAL.value == "critical"


class TestErrorCategory:
    def test_values(self):
        assert ErrorCategory.NETWORK.value == "network"
        assert ErrorCategory.API.value == "api"
        assert ErrorCategory.CONFIGURATION.value == "configuration"
        assert ErrorCategory.VALIDATION.value == "validation"


class TestErrorInfo:
    def test_creation(self):
        info = ErrorInfo(
            error_code="ERR001",
            error_message="Connection timeout",
            error_category=ErrorCategory.NETWORK,
            severity=ErrorSeverity.ERROR,
            timestamp=datetime.now(),
            context={"url": "https://api.example.com"},
        )
        assert info.error_code == "ERR001"
        assert info.severity == ErrorSeverity.ERROR
        assert info.retry_count == 0
        assert info.original_error is None

    def test_default_retry_count(self):
        info = ErrorInfo(
            error_code="E2",
            error_message="msg",
            error_category=ErrorCategory.API,
            severity=ErrorSeverity.WARNING,
            timestamp=datetime.now(),
            context={},
        )
        assert info.retry_count == 0


class TestCircuitBreaker:
    def test_init_defaults(self):
        cb = CircuitBreaker()
        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 60
        assert cb.state == "CLOSED"
        assert cb.failure_count == 0

    def test_init_custom(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
        assert cb.failure_threshold == 3
        assert cb.recovery_timeout == 30

    def test_success_call(self):
        cb = CircuitBreaker()
        result = cb.call(lambda: "ok")
        assert result == "ok"
        assert cb.state == "CLOSED"
        assert cb.failure_count == 0

    def test_failure_increments_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(2):
            try:
                cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))  # noqa
            except Exception:
                pass
        assert cb.failure_count == 2
        assert cb.state == "CLOSED"

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=2)
        for _ in range(2):
            try:
                cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))  # noqa
            except Exception:
                pass
        assert cb.state == "OPEN"

    def test_rejects_when_open(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=999)
        try:
            cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))  # noqa
        except Exception:
            pass
        with pytest.raises(Exception, match="Circuit breaker is open"):
            cb.call(lambda: "should not run")

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        try:
            cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))  # noqa
        except Exception:
            pass
        assert cb.state == "OPEN"
        assert cb._should_attempt_reset() is True


class TestErrorHandler:
    def test_init(self):
        eh = ErrorHandler()
        assert eh.circuit_breakers == {}
        assert eh.error_history == []

    def test_handle_api_error(self):
        """handle_api_error(error, context, severity)."""
        eh = ErrorHandler()
        info = eh.handle_api_error(
            error=ValueError("API timeout"),
            context={"url": "/api/test"},
            severity=ErrorSeverity.ERROR,
        )
        assert info is not None
        assert info.error_category == ErrorCategory.API
        assert "timeout" in info.error_code.lower()

    def test_handle_config_error(self):
        """handle_config_error(error, context)."""
        eh = ErrorHandler()
        info = eh.handle_config_error(
            error=KeyError("exchange"),
            context={"config_file": "config.yaml"},
        )
        assert info.error_code == "CONFIG_ERROR"

    def test_handle_api_error_stores_history(self):
        eh = ErrorHandler()
        eh.handle_api_error(ValueError("test"), context={})
        assert len(eh.error_history) >= 1

    def test_get_error_stats(self):
        eh = ErrorHandler()
        stats = eh.get_error_stats()
        assert isinstance(stats, dict)
        assert "total_errors" in stats

    def test_clear_history(self):
        eh = ErrorHandler()
        eh.handle_api_error(ValueError("x"), context={})
        eh.clear_error_history()
        assert len(eh.error_history) == 0


class TestErrorHandlerRetryAsync:
    @pytest.mark.asyncio
    async def test_async_success(self):
        @error_handler.retry_with_backoff(max_retries=2)
        async def succeed():
            return "ok"

        result = await succeed()
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_async_exhausted(self):
        call_count = [0]

        @error_handler.retry_with_backoff(max_retries=2, base_delay=0.01)
        async def fail():
            call_count[0] += 1
            raise ValueError("always fails")

        with pytest.raises(ValueError, match="always fails"):
            await fail()
        assert call_count[0] >= 2
