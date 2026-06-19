"""Tests for minimal _PerfMon."""
import time
from kairos.utils.performance_monitor import performance_monitor, _PerfMon


class TestPerfMon:
    def setup_method(self):
        self.pm = _PerfMon()

    def test_record_counter(self):
        self.pm.record_counter("hits", 5)
        self.pm.record_counter("hits", 3)
        assert self.pm._counters["hits"] == 8.0

    def test_record_gauge(self):
        self.pm.record_gauge("temperature", 36.6)
        assert self.pm._gauges["temperature"] == 36.6
        self.pm.record_gauge("temperature", 37.0)
        assert self.pm._gauges["temperature"] == 37.0

    def test_timer(self):
        ts = self.pm.start_timer("test_op")
        self.pm.stop_timer(ts, "test_op")
        assert len(self.pm._timers["test_op"]) == 1
        assert self.pm._timers["test_op"][0] >= 0

    def test_time_function_decorator(self):
        @self.pm.time_function("decorated")
        def slow():
            return 42
        assert slow() == 42
        assert len(self.pm._timers["decorated"]) == 1

    def test_global_instance(self):
        assert isinstance(performance_monitor, _PerfMon)
