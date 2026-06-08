"""Market data payload normalization helpers."""

from __future__ import annotations

from typing import Any, Mapping


def extract_quote_volume(ticker: Mapping[str, Any]) -> float:
    """Return 24h quote/USD notional volume from a CCXT ticker payload."""
    direct = first_float(ticker, ["quoteVolume", "quoteVolume24h", "turnover", "turnover24h"])
    if direct is not None:
        return direct

    info = ticker.get("info", {})
    if isinstance(info, Mapping):
        quote_notional = first_float(
            info,
            [
                "volUsd24h",
                "volCcyQuote24h",
                "quoteVolume",
                "quoteVolume24h",
                "turnover",
                "turnover24h",
            ],
        )
        if quote_notional is not None:
            return quote_notional

    base_volume = first_float(ticker, ["baseVolume", "volume"])
    if base_volume is None and isinstance(info, Mapping):
        base_volume = first_float(info, ["vol24h", "baseVolume", "volume"])
    price = extract_last_price(ticker)
    return base_volume * price if base_volume is not None and price is not None else 0.0


def extract_last_price(ticker: Mapping[str, Any]) -> float | None:
    """Return the best available last/close price from a ticker payload."""
    value = first_float(ticker, ["last", "close", "markPrice", "lastPrice"])
    if value is not None:
        return value
    info = ticker.get("info", {})
    if isinstance(info, Mapping):
        return first_float(info, ["last", "lastPrice", "markPx", "idxPx"])
    return None


def first_float(mapping: Mapping[str, Any], keys: list[str]) -> float | None:
    """Return the first key that can be parsed as a float."""
    for key in keys:
        value = mapping.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
