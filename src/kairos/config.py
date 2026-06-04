"""Simple YAML config loader for Kairos."""

import logging
from pathlib import Path
from typing import Any, Dict

import yaml

from kairos.paths import get_config_path

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG: Dict[str, Any] = {
    "exchange": "okx",
    "defaultTimeframe": "1d",
    "notificationTimezone": "Asia/Shanghai",
    "dataManager": {
        "exchanges": ["okx", "binance", "bybit"],
        "topSymbols": 100,
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
}


def load_config(path: Path | None = None) -> Dict[str, Any]:
    """Load and merge config from YAML file with defaults.

    Returns a merged dict where config file values override defaults.
    """
    config = dict(_DEFAULT_CONFIG)  # shallow copy

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
