"""Configuration loading and typed architecture defaults for Kairos."""

import logging
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping

import yaml

from kairos.paths import get_config_path

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG: Dict[str, Any] = {
    "exchange": "okx",
    "defaultTimeframe": "1d",
    "notificationTimezone": "Asia/Shanghai",
    "dataManager": {
        "exchanges": ["okx", "binance", "bybit"],
        "topSymbols": 30,
        "refreshIntervalHours": 4,
        "dedupWindowSeconds": 5,
    },
    "priceVelocity": {
        "enabled": True,
        "windows": [
            {"seconds": 30, "threshold": 0.5},
            {"seconds": 60, "threshold": 0.8},
            {"seconds": 120, "threshold": 1.2},
        ],
        "cooldownSeconds": 60,
    },
    "volumeSpike": {
        "enabled": True,
        "multiplier": 3.0,
        "windowMinutes": 10,
        "minNotifyInterval": "2m",
    },
    "scanner": {
        "intervalSeconds": 300,
        "universeSize": 30,
        "candidateLimit": 20,
        "deepAnalysisLimit": 10,
        "totalTimeoutSeconds": 75,
        "exchangeRequestTimeoutSeconds": 8,
        "symbolAnalysisTimeoutSeconds": 12,
        "timeframes": ["1d", "4h", "15m"],
        "generateChartsByDefault": False,
    },
    "exchanges": {
        "primary": "okx",
        "backups": ["binance", "bybit"],
        "rateLimit": True,
        "canonicalQuote": "USDT",
        "settle": "USDT",
    },
    "scoring": {
        "candidateWeights": {
            "quoteVolume": 4.0,
            "priceVelocity": 2.0,
            "openInterest": 1.0,
            "funding": 1.0,
            "relativeStrength": 2.0,
        },
        "setupWeights": {
            "dailyTrend": 1.5,
            "structure": 2.0,
            "entryTrigger": 2.0,
            "btcResonance": 1.0,
            "marketCycle": 1.0,
            "volumeConfirmation": 1.0,
            "riskReward": 1.5,
        },
        "cycleThresholds": {
            "spring": 5.5,
            "summer": 5.5,
            "autumn": 6.5,
            "winter": 7.5,
        },
        "minimumLiquidityQuoteVolume": 30_000_000.0,
        "minimumRiskReward": 1.8,
        "strictRiskReward": 2.2,
        "shortThresholdPremium": 0.5,
    },
    "risk": {
        "maxPositionPct": {
            "major": 33.0,
            "altcoin": 33.0,
        },
        "maxLeverage": {
            "major": 10.0,
            "altcoin": 5.0,
        },
        "weakCyclePositionMultiplier": 0.5,
        "shortPositionMultiplier": 0.75,
        "inverseCyclePositionMultiplier": 0.5,
    },
    "storage": {
        "databasePath": "~/.local/share/kairos/kairos.db",
        "retentionDays": 90,
        "jsonlExport": False,
        "jsonlPath": "",
    },
    "charts": {
        "defaultChartCount": 1,
        "outputPath": "~/.local/share/kairos/charts",
        "cleanupDays": 7,
        "multiTimeframeScoreThreshold": 8.0,
    },
    "webhook": {
        "url": "http://localhost:8644/webhooks/kairos-signals",
        "secretEnv": "KAIROS_WEBHOOK_SECRET",
        "schemaVersion": "1.1",
        "maxRetries": 5,
        "initialBackoffSeconds": 0.5,
        "maxBackoffSeconds": 45.0,
    },
}


@dataclass(frozen=True)
class ScannerConfig:
    """Scanner workflow limits and timeout budgets."""

    interval_seconds: int = 300
    universe_size: int = 30
    candidate_limit: int = 20
    deep_analysis_limit: int = 10
    total_timeout_seconds: int = 75
    exchange_request_timeout_seconds: int = 8
    symbol_analysis_timeout_seconds: int = 12
    timeframes: list[str] = field(default_factory=lambda: ["1d", "4h", "15m"])
    generate_charts_by_default: bool = False


@dataclass(frozen=True)
class ExchangesConfig:
    """Exchange selection and symbol-normalization settings."""

    primary: str = "okx"
    backups: list[str] = field(default_factory=lambda: ["binance", "bybit"])
    rate_limit: bool = True
    canonical_quote: str = "USDT"
    settle: str = "USDT"


@dataclass(frozen=True)
class ScoringConfig:
    """Deterministic scoring thresholds and weights owned by Kairos."""

    candidate_weights: dict[str, float] = field(
        default_factory=lambda: {
            "quoteVolume": 4.0,
            "priceVelocity": 2.0,
            "openInterest": 1.0,
            "funding": 1.0,
            "relativeStrength": 2.0,
        }
    )
    setup_weights: dict[str, float] = field(
        default_factory=lambda: {
            "dailyTrend": 1.5,
            "structure": 2.0,
            "entryTrigger": 2.0,
            "btcResonance": 1.0,
            "marketCycle": 1.0,
            "volumeConfirmation": 1.0,
            "riskReward": 1.5,
        }
    )
    cycle_thresholds: dict[str, float] = field(
        default_factory=lambda: {
            "spring": 5.5,
            "summer": 5.5,
            "autumn": 6.5,
            "winter": 7.5,
        }
    )
    minimum_liquidity_quote_volume: float = 30_000_000.0
    minimum_risk_reward: float = 1.8
    strict_risk_reward: float = 2.2
    short_threshold_premium: float = 0.5


@dataclass(frozen=True)
class RiskConfig:
    """Signal-only risk bounds; these are not execution commands."""

    max_position_pct: dict[str, float] = field(default_factory=lambda: {"major": 33.0, "altcoin": 33.0})
    max_leverage: dict[str, float] = field(default_factory=lambda: {"major": 10.0, "altcoin": 5.0})
    weak_cycle_position_multiplier: float = 0.5
    short_position_multiplier: float = 0.75
    inverse_cycle_position_multiplier: float = 0.5


@dataclass(frozen=True)
class StorageConfig:
    """First-version persistence configuration."""

    database_path: str = "~/.local/share/kairos/kairos.db"
    retention_days: int = 90
    jsonl_export: bool = False
    jsonl_path: str = ""


@dataclass(frozen=True)
class ChartConfig:
    """Chart generation policy returned as specs, not generated by scans."""

    default_chart_count: int = 1
    output_path: str = "~/.local/share/kairos/charts"
    cleanup_days: int = 7
    multi_timeframe_score_threshold: float = 8.0


@dataclass(frozen=True)
class WebhookConfig:
    """Webhook delivery configuration for auxiliary anomaly hints."""

    url: str = "http://localhost:8644/webhooks/kairos-signals"
    secret_env: str = "KAIROS_WEBHOOK_SECRET"
    schema_version: str = "1.1"
    max_retries: int = 5
    initial_backoff_seconds: float = 0.5
    max_backoff_seconds: float = 45.0


@dataclass(frozen=True)
class KairosArchitectureConfig:
    """Typed configuration view for the architecture-baseline modules."""

    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    exchanges: ExchangesConfig = field(default_factory=ExchangesConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    charts: ChartConfig = field(default_factory=ChartConfig)
    webhook: WebhookConfig = field(default_factory=WebhookConfig)


def load_config(path: Path | None = None) -> Dict[str, Any]:
    """Load and merge config from YAML file with defaults.

    Returns a merged dict where config file values override defaults.
    """
    config = deepcopy(_DEFAULT_CONFIG)

    filepath = path or get_config_path()
    if not filepath.exists():
        logger.info("No config file found at %s, using defaults", filepath)
        return config

    try:
        with open(filepath, "r") as f:
            loaded = yaml.safe_load(f) or {}
    except Exception:
        logger.exception("Failed to load config from %s, using defaults", filepath)
        return config

    _deep_merge(config, loaded)
    return config


def _deep_merge(base: dict, override: dict) -> None:
    """Recursively merge override into base (in-place)."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def load_architecture_config(config: Mapping[str, Any] | None = None) -> KairosArchitectureConfig:
    """Build a typed architecture config from a raw config mapping.

    The raw mapping may use the YAML-facing camelCase keys from `_DEFAULT_CONFIG`.
    Missing values are filled from architecture defaults.
    """
    raw = deepcopy(_DEFAULT_CONFIG)
    if config:
        _deep_merge(raw, dict(config))

    scanner = raw.get("scanner", {})
    exchanges = raw.get("exchanges", {})
    scoring = raw.get("scoring", {})
    risk = raw.get("risk", {})
    storage = raw.get("storage", {})
    charts = raw.get("charts", {})
    webhook = raw.get("webhook", {})

    return KairosArchitectureConfig(
        scanner=ScannerConfig(
            interval_seconds=int(scanner.get("intervalSeconds", 300)),
            universe_size=int(scanner.get("universeSize", 30)),
            candidate_limit=int(scanner.get("candidateLimit", 20)),
            deep_analysis_limit=int(scanner.get("deepAnalysisLimit", 10)),
            total_timeout_seconds=int(scanner.get("totalTimeoutSeconds", 75)),
            exchange_request_timeout_seconds=int(scanner.get("exchangeRequestTimeoutSeconds", 8)),
            symbol_analysis_timeout_seconds=int(scanner.get("symbolAnalysisTimeoutSeconds", 12)),
            timeframes=list(scanner.get("timeframes", ["1d", "4h", "15m"])),
            generate_charts_by_default=bool(scanner.get("generateChartsByDefault", False)),
        ),
        exchanges=ExchangesConfig(
            primary=str(exchanges.get("primary", "okx")),
            backups=list(exchanges.get("backups", ["binance", "bybit"])),
            rate_limit=bool(exchanges.get("rateLimit", True)),
            canonical_quote=str(exchanges.get("canonicalQuote", "USDT")),
            settle=str(exchanges.get("settle", "USDT")),
        ),
        scoring=ScoringConfig(
            candidate_weights={k: float(v) for k, v in scoring.get("candidateWeights", {}).items()}
            or ScoringConfig().candidate_weights,
            setup_weights={k: float(v) for k, v in scoring.get("setupWeights", {}).items()}
            or ScoringConfig().setup_weights,
            cycle_thresholds={k: float(v) for k, v in scoring.get("cycleThresholds", {}).items()}
            or ScoringConfig().cycle_thresholds,
            minimum_liquidity_quote_volume=float(scoring.get("minimumLiquidityQuoteVolume", 30_000_000.0)),
            minimum_risk_reward=float(scoring.get("minimumRiskReward", 1.8)),
            strict_risk_reward=float(scoring.get("strictRiskReward", 2.2)),
            short_threshold_premium=float(scoring.get("shortThresholdPremium", 0.5)),
        ),
        risk=RiskConfig(
            max_position_pct={k: float(v) for k, v in risk.get("maxPositionPct", {}).items()}
            or RiskConfig().max_position_pct,
            max_leverage={k: float(v) for k, v in risk.get("maxLeverage", {}).items()} or RiskConfig().max_leverage,
            weak_cycle_position_multiplier=float(risk.get("weakCyclePositionMultiplier", 0.5)),
            short_position_multiplier=float(risk.get("shortPositionMultiplier", 0.75)),
            inverse_cycle_position_multiplier=float(risk.get("inverseCyclePositionMultiplier", 0.5)),
        ),
        storage=StorageConfig(
            database_path=str(storage.get("databasePath", "~/.local/share/kairos/kairos.db")),
            retention_days=int(storage.get("retentionDays", 90)),
            jsonl_export=bool(storage.get("jsonlExport", False)),
            jsonl_path=str(storage.get("jsonlPath", "")),
        ),
        charts=ChartConfig(
            default_chart_count=int(charts.get("defaultChartCount", 1)),
            output_path=str(charts.get("outputPath", "~/.local/share/kairos/charts")),
            cleanup_days=int(charts.get("cleanupDays", 7)),
            multi_timeframe_score_threshold=float(charts.get("multiTimeframeScoreThreshold", 8.0)),
        ),
        webhook=WebhookConfig(
            url=str(webhook.get("url", "http://localhost:8644/webhooks/kairos-signals")),
            secret_env=str(webhook.get("secretEnv", "KAIROS_WEBHOOK_SECRET")),
            schema_version=str(webhook.get("schemaVersion", "1.1")),
            max_retries=int(webhook.get("maxRetries", 5)),
            initial_backoff_seconds=float(webhook.get("initialBackoffSeconds", 0.5)),
            max_backoff_seconds=float(webhook.get("maxBackoffSeconds", 45.0)),
        ),
    )
