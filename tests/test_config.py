"""
Comprehensive tests for kairos config module (load_config, _deep_merge).
"""

import logging

import yaml

from kairos.config import _DEFAULT_CONFIG, _deep_merge, load_architecture_config, load_config


class TestDeepMerge:
    """Tests for _deep_merge recursive dict merging."""

    def test_merge_nested_dicts(self):
        """_deep_merge should recursively merge nested dictionaries."""
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 99}}

        _deep_merge(base, override)

        assert base["a"]["x"] == 1  # preserved from base
        assert base["a"]["y"] == 99  # overridden
        assert base["b"] == 3  # untouched

    def test_merge_new_keys(self):
        """_deep_merge should add keys not present in base."""
        base = {"existing": "ok"}
        override = {"new_key": "new_value"}

        _deep_merge(base, override)

        assert base["existing"] == "ok"
        assert base["new_key"] == "new_value"

    def test_merge_override_existing_keys(self):
        """_deep_merge should override existing top-level keys."""
        base = {"key": "old"}
        override = {"key": "new"}

        _deep_merge(base, override)

        assert base["key"] == "new"

    def test_merge_deeply_nested(self):
        """_deep_merge should handle deeply nested structures."""
        base = {
            "dataManager": {
                "exchanges": ["okx"],
                "topSymbols": 50,
                "nested": {"inner": 1, "keep": "yes"},
            }
        }
        override = {
            "dataManager": {
                "exchanges": ["binance", "bybit"],
                "nested": {"inner": 999},
            }
        }

        _deep_merge(base, override)

        assert base["dataManager"]["exchanges"] == ["binance", "bybit"]
        assert base["dataManager"]["topSymbols"] == 50  # preserved
        assert base["dataManager"]["nested"]["inner"] == 999  # overridden
        assert base["dataManager"]["nested"]["keep"] == "yes"  # preserved

    def test_merge_empty_override(self):
        """_deep_merge with empty override dict should leave base unchanged."""
        base = {"a": 1, "b": {"c": 2}}
        backup = dict(base)

        _deep_merge(base, {})

        assert base == backup

    def test_merge_overwrite_non_dict_with_dict(self):
        """_deep_merge should overwrite a non-dict value with a dict."""
        base = {"a": 42}
        override = {"a": {"nested": "now_a_dict"}}

        _deep_merge(base, override)

        assert base["a"] == {"nested": "now_a_dict"}


class TestLoadConfig:
    """Tests for load_config with various file scenarios."""

    def test_load_no_file_returns_defaults(self, monkeypatch):
        """load_config without an existing file should return defaults."""
        from pathlib import Path

        monkeypatch.setattr(
            "kairos.config.get_config_path",
            lambda: Path("/nonexistent/path/config.yaml"),
        )

        result = load_config()

        # Should return a copy of defaults, not the same object
        assert result == _DEFAULT_CONFIG
        assert result is not _DEFAULT_CONFIG

    def test_load_no_file_with_explicit_path(self):
        """load_config with an explicit path that doesn't exist returns defaults."""
        from pathlib import Path

        result = load_config(Path("/nonexistent/path/config.yaml"))

        assert result == _DEFAULT_CONFIG
        assert result is not _DEFAULT_CONFIG

    def test_load_from_yaml_file(self, tmp_path):
        """load_config should load and merge values from a real YAML file."""
        config_file = tmp_path / "config.yaml"
        yaml_content = {
            "exchange": "binance",
            "defaultTimeframe": "5m",
            "dataManager": {
                "exchanges": ["binance", "bybit"],
                "topSymbols": 200,
            },
        }
        with open(config_file, "w") as f:
            yaml.dump(yaml_content, f)

        result = load_config(config_file)

        # Overridden values
        assert result["exchange"] == "binance"
        assert result["defaultTimeframe"] == "5m"
        assert result["dataManager"]["exchanges"] == ["binance", "bybit"]
        assert result["dataManager"]["topSymbols"] == 200

        # Preserved defaults (not in YAML)
        assert result["notificationTimezone"] == "Asia/Shanghai"
        assert result["priceVelocity"]["enabled"] is True
        assert result["volumeSpike"]["minHistorySeconds"] == 600
        assert result["dataManager"]["refreshIntervalHours"] == 4
        assert result["dataManager"]["dedupWindowSeconds"] == 5
        assert result["dataManager"]["symbolCooldownMinutes"] == 30
        assert result["alertPolicy"]["allowedEventTypes"] == [
            "price_velocity",
            "volume_spike",
            "open_interest_change",
            "funding_rate_anomaly",
        ]
        assert result["alertPolicy"]["minPriceChangePct"] == 1.2
        assert result["alertPolicy"]["minOpenInterestChangePct"] == 5.0
        assert result["alertPolicy"]["minFundingRateAbs"] == 0.0005
        assert result["alertPolicy"]["minFundingRateChangeAbs"] == 0.0003
        assert result["futuresMetrics"]["enabled"] is True
        assert result["futuresMetrics"]["openInterest"]["minChangePct"] == 5.0
        assert result["futuresMetrics"]["fundingRate"]["minChangeAbs"] == 0.0003

    def test_load_invalid_yaml_returns_defaults(self, tmp_path, caplog):
        """load_config with invalid YAML should return defaults and log error."""
        config_file = tmp_path / "bad_config.yaml"
        config_file.write_text("invalid: yaml: : {{{ bad syntax")

        with caplog.at_level(logging.WARNING):
            result = load_config(config_file)

        assert result == _DEFAULT_CONFIG
        assert result is not _DEFAULT_CONFIG

    def test_load_empty_file_returns_defaults(self, tmp_path):
        """load_config with an empty file should return defaults."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")

        result = load_config(config_file)

        assert result == _DEFAULT_CONFIG
        assert result is not _DEFAULT_CONFIG

    def test_load_file_with_only_comments(self, tmp_path):
        """load_config with a file containing only YAML comments returns defaults."""
        config_file = tmp_path / "comments.yaml"
        config_file.write_text("# This is a comment\n# Another comment\n")

        result = load_config(config_file)

        assert result == _DEFAULT_CONFIG

    def test_load_partial_override_preserves_default_structure(self, tmp_path):
        """load_config should preserve the full default structure after partial override."""
        config_file = tmp_path / "partial.yaml"
        yaml_content = {
            "exchange": "bybit",
            "notificationTimezone": "UTC",
        }
        with open(config_file, "w") as f:
            yaml.dump(yaml_content, f)

        result = load_config(config_file)

        # All default keys should still be present
        for key in _DEFAULT_CONFIG:
            assert key in result, f"Default key '{key}' missing after merge"

        assert result["exchange"] == "bybit"
        assert result["notificationTimezone"] == "UTC"
        assert result["defaultTimeframe"] == _DEFAULT_CONFIG["defaultTimeframe"]

    def test_load_config_fresh_copy_not_mutate_default(self, tmp_path):
        """load_config result mutations should not affect the module-level default."""
        config_file = tmp_path / "mutate.yaml"
        config_file.write_text("exchange: bybit\n")

        result = load_config(config_file)

        # Mutate the returned dict
        result["exchange"] = "mutated"
        result["newKey"] = "injected"

        # Module default must be unchanged
        assert _DEFAULT_CONFIG["exchange"] == "okx"
        assert "newKey" not in _DEFAULT_CONFIG

    def test_load_config_nested_defaults_are_fresh_copies(self):
        """Nested default sections should not be shared between calls."""
        from pathlib import Path

        first = load_config(Path("/nonexistent/path/config.yaml"))
        second = load_config(Path("/nonexistent/path/config.yaml"))

        first["scanner"]["universeSize"] = 999

        assert second["scanner"]["universeSize"] == 30
        assert _DEFAULT_CONFIG["scanner"]["universeSize"] == 30


class TestArchitectureConfig:
    """Tests for typed architecture config view."""

    def test_architecture_defaults_match_baseline(self):
        """Default typed config reflects docs/architecture.md phase-one baseline."""
        cfg = load_architecture_config()

        assert cfg.scanner.interval_seconds == 300
        assert cfg.scanner.universe_size == 30
        assert cfg.scanner.candidate_limit == 20
        assert cfg.scanner.deep_analysis_limit == 10
        assert cfg.exchanges.primary == "okx"
        assert cfg.exchanges.backups == ["binance", "bybit"]
        assert cfg.scoring.minimum_liquidity_quote_volume == 30_000_000.0
        assert cfg.scoring.cycle_thresholds["winter"] == 7.5
        assert cfg.risk.max_position_pct["major"] == 33.0
        assert cfg.risk.max_leverage["altcoin"] == 5.0
        assert cfg.storage.database_path == "~/.local/share/kairos/kairos.db"
        assert cfg.storage.retention_days == 90
        assert cfg.charts.default_chart_count == 1
        assert cfg.webhook.schema_version == "1.1"

    def test_architecture_config_merges_overrides(self):
        """Typed config accepts YAML-facing camelCase overrides."""
        cfg = load_architecture_config(
            {
                "scanner": {"universeSize": 12, "deepAnalysisLimit": 4},
                "scoring": {"minimumRiskReward": 2.5},
                "storage": {"databasePath": "/tmp/kairos.db"},
            }
        )

        assert cfg.scanner.universe_size == 12
        assert cfg.scanner.deep_analysis_limit == 4
        assert cfg.scoring.minimum_risk_reward == 2.5
        assert cfg.storage.database_path == "/tmp/kairos.db"
