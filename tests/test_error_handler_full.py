"""Comprehensive tests for error_handler."""

import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from kairos.utils.error_handler import (
    CircuitBreaker,
    ErrorHandler,
    ErrorInfo,
    ErrorSeverity,
    error_handler,
)


class TestErrorSeverity:
    """Test ErrorSeverity enum."""

    def test_values(self):
        assert ErrorSeverity.LOW.value == "low"
        assert ErrorSeverity.MEDIUM.value == "medium"
        assert ErrorSeverity.HIGH.value == "high"
        assert ErrorSeverity.CRITICAL.value == "critical"


class TestErrorInfo:
    """Test ErrorInfo dataclass."""

    def test_creation(self):
        info = ErrorInfo(
            timestamp=datetime.now(),
            error_type="ValueError",
            message="Test error",
            severity=ErrorSeverity.LOW,
            component="test",
            operation="test_op",
        )
        assert info.error_type == "ValueError"
        assert info.severity == ErrorSeverity.LOW


class TestCircuitBreaker:
    """Test CircuitBreaker class."""

    def test_init(self):
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60)
        assert cb.name == "test"
        assert cb.failure_threshold == 3
        assert cb.recovery_timeout == 60
        assert cb.state == "CLOSED"
        assert cb.failure_count == 0

    def test_success_call(self):
        cb = CircuitBreaker("test")
        result = cb.call(lambda: "success")
        assert result == "success"
        assert cb.failure_count == 0
        assert cb.state == "CLOSED"

    def test_failure_increments_count(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("test")))
        assert cb.failure_count == 1

    def test_opens_after_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=2)
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError("test")))
        assert cb.state == "OPEN"

    def test_rejects_when_open(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=60)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("test")))
        assert cb.state == "OPEN"
        with pytest.raises(Exception, match="Circuit breaker"):
            cb.call(lambda: "success")

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("test")))
        assert cb.state == "OPEN"
        time.sleep(0.01)
        # Should transition to HALF_OPEN and then CLOSED on success
        result = cb.call(lambda: "success")
        assert result == "success"
        assert cb.state == "CLOSED"


class TestErrorHandler:
    """Test ErrorHandler class."""

    def test_init(self):
        handler = ErrorHandler()
        assert handler.max_history_size == 1000
        assert len(handler.error_history) == 0

    def test_retry_with_backoff_success(self):
        handler = ErrorHandler()
        call_count = [0]

        @handler.retry_with_backoff(max_retries=3, base_delay=0.01)
        def func():
            call_count[0] += 1
            return "success"

        result = func()
        assert result == "success"
        assert call_count[0] == 1

    def test_retry_with_backoff_retries(self):
        handler = ErrorHandler()
        call_count = [0]

        @handler.retry_with_backoff(max_retries=3, base_delay=0.01)
        def func():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("Not yet")
            return "success"

        result = func()
        assert result == "success"
        assert call_count[0] == 3

    def test_retry_with_backoff_exhausted(self):
        handler = ErrorHandler()

        @handler.retry_with_backoff(max_retries=2, base_delay=0.01)
        def func():
            raise ValueError("Always fails")

        with pytest.raises(ValueError):
            func()

    def test_handle_error(self):
        handler = ErrorHandler()
        error = ValueError("Test error")
        handler.handle_error(error, {"component": "test"}, ErrorSeverity.LOW)
        assert len(handler.error_history) == 1

    def test_handle_config_error(self):
        handler = ErrorHandler()
        error = ValueError("Config error")
        handler.handle_config_error(error, {"component": "config"}, ErrorSeverity.MEDIUM)
        assert len(handler.error_history) == 1

    def test_get_circuit_breaker(self):
        handler = ErrorHandler()
        cb1 = handler.get_circuit_breaker("test")
        cb2 = handler.get_circuit_breaker("test")
        assert cb1 is cb2

    def test_get_error_stats(self):
        handler = ErrorHandler()
        handler.handle_error(ValueError("test"), {}, ErrorSeverity.LOW)
        stats = handler.get_error_stats()
        assert stats["total_errors"] == 1

    def test_clear_history(self):
        handler = ErrorHandler()
        handler.handle_error(ValueError("test"), {}, ErrorSeverity.LOW)
        handler.clear_history()
        assert len(handler.error_history) == 0


class TestErrorHandlerRetryAsync:
    """Test ErrorHandler.retry_with_backoff_async method."""

    @pytest.mark.asyncio
    async def test_async_success(self):
        handler = ErrorHandler()
        call_count = [0]

        @handler.retry_with_backoff_async(max_retries=3, base_delay=0.01)
        async def func():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ValueError("Not yet")
            return "success"

        result = await func()
        assert result == "success"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_async_exhausted(self):
        handler = ErrorHandler()

        @handler.retry_with_backoff_async(max_retries=2, base_delay=0.01)
        async def func():
            raise ValueError("Always fails")

        with pytest.raises(ValueError):
            await func()
