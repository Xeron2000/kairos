"""Shared MCP response schema helpers."""

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

MCP_SCHEMA_VERSION = "1.0"


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp for API payloads."""
    return datetime.now(timezone.utc).isoformat()


def normalize_symbol(symbol: str) -> str:
    """Normalize external symbols to CCXT USDT perpetual format.

    Accepted inputs include `BTC/USDT`, `BTCUSDT`, and `BTC/USDT:USDT`.
    """
    value = symbol.strip().upper()
    if not value:
        raise ValueError("symbol is required")

    if value.endswith(":USDT") and "/USDT:" in value:
        return value
    if value.endswith("/USDT"):
        return f"{value}:USDT"
    if value.endswith("USDT") and "/" not in value and ":" not in value:
        base = value[: -len("USDT")]
        if not base:
            raise ValueError(f"invalid USDT symbol: {symbol}")
        return f"{base}/USDT:USDT"
    raise ValueError(f"unsupported symbol format: {symbol}")


def make_mcp_envelope(
    *,
    success: bool,
    data: Mapping[str, Any] | None = None,
    symbol: str | None = None,
    score: Mapping[str, Any] | None = None,
    reasons: Iterable[str] | None = None,
    warnings: Iterable[str] | None = None,
    errors: Iterable[str] | None = None,
    timestamp: str | None = None,
    schema_version: str = MCP_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Build the standardized core MCP response envelope."""
    return {
        "success": success,
        "schema_version": schema_version,
        "timestamp": timestamp or utc_timestamp(),
        "symbol": symbol,
        "data": dict(data or {}),
        "score": dict(score or {}),
        "reasons": list(reasons or []),
        "warnings": list(warnings or []),
        "errors": list(errors or []),
    }
