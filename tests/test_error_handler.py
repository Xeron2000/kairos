"""Tests for minimal ErrorHandler."""
import asyncio
import pytest
from kairos.utils.error_handler import CircuitBreaker, ErrorHandler, ErrorSeverity, error_handler


class TestCircuitBreaker:
    def test_closed_passes(self):
        cb = CircuitBreaker(failure_threshold=2)
        assert cb.call(lambda x: x * 2, 3) == 6

    def test_opens_after_failures(self):
        cb = CircuitBreaker(failure_threshold=2)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("1")))
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("2")))
        with pytest.raises(RuntimeError, match="open"):
            cb.call(lambda: 42)

    def test_resets_after_success(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(2):
            try:
                cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
            except ValueError:
                pass
        assert cb.call(lambda: 42) == 42
        # Should be reset now, one failure should not open
        try:
            cb.call(lambda: (_ for _ in ()).throw(ValueError("single")))
        except ValueError:
            pass
        assert cb.call(lambda: 43) == 43


class TestErrorHandler:
    def setup_method(self):
        self.eh = ErrorHandler()

    def test_handle_api_error(self):
        info = self.eh.handle_api_error(Exception("timeout"), {"op": "test"}, ErrorSeverity.WARNING)
        assert info is not None

    def test_handle_network_error(self):
        info = self.eh.handle_network_error(Exception("connection refused"), {"op": "ws"}, ErrorSeverity.ERROR)
        assert info is not None

    def test_handle_config_error(self):
        info = self.eh.handle_config_error(Exception("bad yaml"), {"file": "config.yaml"}, ErrorSeverity.CRITICAL)
        assert info is not None

    def test_retry_with_backoff_sync(self):
        calls = []
        @self.eh.retry_with_backoff(max_retries=2, base_delay=0.01)
        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("fail")
            return "ok"
        assert flaky() == "ok"
        assert len(calls) == 3

    def test_retry_with_backoff_exhausted(self):
        @self.eh.retry_with_backoff(max_retries=1, base_delay=0.01)
        def always_fail():
            raise RuntimeError("never")
        with pytest.raises(RuntimeError, match="never"):
            always_fail()

    @pytest.mark.asyncio
    async def test_retry_with_backoff_async(self):
        calls = []
        @self.eh.retry_with_backoff(max_retries=2, base_delay=0.01)
        async def flaky_async():
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("fail")
            return "ok"
        result = await flaky_async()
        assert result == "ok"
        assert len(calls) == 3

    def test_circuit_breaker_protect(self):
        failures = [0]
        @self.eh.circuit_breaker_protect("test_cb", failure_threshold=2)
        def cb_func():
            failures[0] += 1
            if failures[0] <= 2:
                raise ValueError("fail")
            return "passed"
        with pytest.raises(ValueError):
            cb_func()
        with pytest.raises(ValueError):
            cb_func()
        with pytest.raises(RuntimeError, match="open"):
            cb_func()
