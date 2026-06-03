"""Comprehensive tests for PerformanceMonitor."""

import time
from unittest.mock import MagicMock, patch

import pytest

from kairos.utils.performance_monitor import (
    Metric,
    MetricType,
    PerformanceMonitor,
    PerformanceSnapshot,
)


class TestMetric:
    """Test Metric dataclass."""

    def test_to_dict(self):
        metric = Metric(name="test", type=MetricType.COUNTER, value=42.0, tags={"env": "test"})
        d = metric.to_dict()
        assert d["name"] == "test"
        assert d["type"] == "counter"
        assert d["value"] == 42.0
        assert d["tags"] == {"env": "test"}


class TestPerformanceSnapshot:
    """Test PerformanceSnapshot dataclass."""

    def test_to_dict(self):
        snapshot = PerformanceSnapshot(
            timestamp=1.0, cpu_percent=50.0, memory_percent=60.0,
            memory_used_mb=1024.0, memory_available_mb=2048.0,
            disk_usage_percent=70.0, thread_count=10, open_files=5,
            network_connections=3,
        )
        d = snapshot.to_dict()
        assert d["cpu_percent"] == 50.0
        assert d["thread_count"] == 10


class TestPerformanceMonitor:
    """Test PerformanceMonitor class."""

    @pytest.fixture
    def monitor(self):
        return PerformanceMonitor(max_history_size=100, collection_interval=0.1)

    def test_init(self, monitor):
        assert monitor.max_history_size == 100
        assert monitor.collection_interval == 0.1
        assert monitor._running is False

    def test_start_and_stop(self, monitor):
        monitor.start()
        assert monitor._running is True
        time.sleep(0.2)
        monitor.stop()
        assert monitor._running is False

    def test_start_already_running(self, monitor):
        monitor.start()
        monitor.start()  # Should not raise
        monitor.stop()

    def test_stop_not_running(self, monitor):
        monitor.stop()  # Should not raise

    def test_record_counter(self, monitor):
        monitor.record_counter("requests", 1)
        monitor.record_counter("requests", 2)
        assert monitor.counters["requests"] == 3

    def test_record_counter_with_tags(self, monitor):
        monitor.record_counter("requests", 1, tags={"method": "GET"})
        assert monitor.counters["requests"] == 1

    def test_record_gauge(self, monitor):
        monitor.record_gauge("temperature", 25.0)
        assert monitor.custom_metrics["temperature"].value == 25.0

    def test_record_gauge_with_tags(self, monitor):
        monitor.record_gauge("temperature", 25.0, tags={"location": "server1"})
        assert monitor.custom_metrics["temperature"].tags == {"location": "server1"}

    def test_start_and_stop_timer(self, monitor):
        timer_id = monitor.start_timer("operation")
        assert timer_id in monitor.active_timers
        time.sleep(0.01)
        monitor.stop_timer(timer_id, "operation")
        assert timer_id not in monitor.active_timers
        assert "operation" in monitor.timer_history
        assert len(monitor.timer_history["operation"]) == 1

    def test_stop_timer_not_found(self, monitor):
        monitor.stop_timer("nonexistent", "operation")  # Should not raise

    def test_record_histogram(self, monitor):
        monitor.record_histogram("response_time", 100.0)
        monitor.record_histogram("response_time", 200.0)
        assert len(monitor.histograms["response_time"]) == 2

    def test_record_histogram_max_size(self):
        monitor = PerformanceMonitor()
        for i in range(1100):
            monitor.record_histogram("test", float(i))
        assert len(monitor.histograms["test"]) == 1000

    def test_time_function_decorator(self, monitor):
        @monitor.time_function("test_func")
        def slow_function():
            time.sleep(0.01)
            return "result"

        result = slow_function()
        assert result == "result"
        assert "test_func" in monitor.timer_history

    def test_get_metrics(self, monitor):
        monitor.record_counter("test", 1)
        monitor.record_counter("test", 2)
        metrics = monitor.get_metrics()
        assert len(metrics) == 2

    def test_get_metrics_with_limit(self, monitor):
        for i in range(10):
            monitor.record_counter("test", i)
        metrics = monitor.get_metrics(limit=5)
        assert len(metrics) == 5

    def test_get_system_snapshots(self, monitor):
        monitor.system_snapshots.append(
            PerformanceSnapshot(
                timestamp=time.time(), cpu_percent=50.0, memory_percent=60.0,
                memory_used_mb=1024.0, memory_available_mb=2048.0,
                disk_usage_percent=70.0, thread_count=10, open_files=5,
                network_connections=3,
            )
        )
        snapshots = monitor.get_system_snapshots()
        assert len(snapshots) == 1

    def test_get_system_snapshots_with_limit(self, monitor):
        for i in range(5):
            monitor.system_snapshots.append(
                PerformanceSnapshot(
                    timestamp=time.time(), cpu_percent=float(i), memory_percent=60.0,
                    memory_used_mb=1024.0, memory_available_mb=2048.0,
                    disk_usage_percent=70.0, thread_count=10, open_files=5,
                    network_connections=3,
                )
            )
        snapshots = monitor.get_system_snapshots(limit=3)
        assert len(snapshots) == 3

    def test_get_timer_stats(self, monitor):
        for i in range(10):
            timer_id = monitor.start_timer("test")
            time.sleep(0.001)
            monitor.stop_timer(timer_id, "test")

        stats = monitor.get_timer_stats("test")
        assert stats["count"] == 10
        assert stats["min"] > 0
        assert stats["max"] >= stats["min"]
        assert stats["avg"] > 0

    def test_get_timer_stats_empty(self, monitor):
        stats = monitor.get_timer_stats("nonexistent")
        assert stats == {}

    def test_get_histogram_stats(self, monitor):
        for i in range(10):
            monitor.record_histogram("test", float(i))

        stats = monitor.get_histogram_stats("test")
        assert stats["count"] == 10
        assert stats["min"] == 0.0
        assert stats["max"] == 9.0

    def test_get_histogram_stats_empty(self, monitor):
        stats = monitor.get_histogram_stats("nonexistent")
        assert stats == {}

    def test_percentile(self, monitor):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert monitor._percentile(values, 50) == 3.0
        assert monitor._percentile(values, 90) == 5.0
        assert monitor._percentile(values, 0) == 1.0

    def test_percentile_empty(self, monitor):
        assert monitor._percentile([], 50) == 0.0

    def test_get_system_stats_empty(self, monitor):
        stats = monitor.get_system_stats()
        assert stats == {}

    def test_get_system_stats_with_data(self, monitor):
        monitor.system_snapshots.append(
            PerformanceSnapshot(
                timestamp=time.time(), cpu_percent=50.0, memory_percent=60.0,
                memory_used_mb=1024.0, memory_available_mb=2048.0,
                disk_usage_percent=70.0, thread_count=10, open_files=5,
                network_connections=3,
            )
        )
        stats = monitor.get_system_stats()
        assert "uptime_seconds" in stats
        assert "recent_cpu_avg" in stats

    def test_get_performance_report(self, monitor):
        monitor.record_counter("test", 1)
        report = monitor.get_performance_report()
        assert "timestamp" in report
        assert "system_stats" in report
        assert "recent_metrics" in report

    def test_export_metrics_json(self, monitor):
        monitor.record_counter("test", 1)
        result = monitor.export_metrics("json")
        assert isinstance(result, str)
        assert "test" in result

    def test_export_metrics_csv(self, monitor):
        monitor.record_counter("test", 1)
        result = monitor.export_metrics("csv")
        assert "timestamp,name,type,value,tags" in result

    def test_export_metrics_unsupported(self, monitor):
        with pytest.raises(ValueError, match="Unsupported format"):
            monitor.export_metrics("xml")

    def test_reset_metrics(self, monitor):
        monitor.record_counter("test", 1)
        monitor.record_gauge("gauge", 1.0)
        monitor.record_histogram("hist", 1.0)
        monitor.reset_metrics()
        assert len(monitor.metrics) == 0
        assert len(monitor.custom_metrics) == 0
        assert len(monitor.counters) == 0
        assert len(monitor.histograms) == 0

    def test_cleanup_old_data(self, monitor):
        monitor.record_counter("test", 1)
        time.sleep(0.01)
        monitor.cleanup_old_data(max_age_seconds=0.005)
        # Old data should be cleaned up
        assert len(monitor.metrics) == 0

    def test_cleanup_old_data_keeps_recent(self, monitor):
        monitor.record_counter("test", 1)
        monitor.cleanup_old_data(max_age_seconds=60)
        assert len(monitor.metrics) == 1

    def test_timer_history_max_size(self, monitor):
        for i in range(150):
            timer_id = monitor.start_timer("test")
            monitor.stop_timer(timer_id, "test")
        assert len(monitor.timer_history["test"]) == 100

    def test_take_system_snapshot(self, monitor):
        snapshot = monitor._take_system_snapshot()
        assert isinstance(snapshot, PerformanceSnapshot)
        assert snapshot.cpu_percent >= 0
        assert snapshot.memory_percent >= 0
