"""Tests for shared MCP schema helpers."""

from kairos.mcp_schema import make_mcp_envelope, normalize_symbol


def test_make_mcp_envelope_has_standard_fields():
    """Envelope includes the architecture baseline fields."""
    result = make_mcp_envelope(
        success=True,
        symbol="BTC/USDT:USDT",
        data={"value": 1},
        score={"setup_score": 6.0},
        reasons=["reason"],
        warnings=["warning"],
        errors=[],
        timestamp="2026-06-06T00:00:00+00:00",
    )

    assert result == {
        "success": True,
        "schema_version": "1.0",
        "timestamp": "2026-06-06T00:00:00+00:00",
        "symbol": "BTC/USDT:USDT",
        "data": {"value": 1},
        "score": {"setup_score": 6.0},
        "reasons": ["reason"],
        "warnings": ["warning"],
        "errors": [],
    }


def test_normalize_symbol_accepts_supported_forms():
    """External forms normalize to CCXT USDT perpetual format."""
    assert normalize_symbol("BTC/USDT") == "BTC/USDT:USDT"
    assert normalize_symbol("btcusdt") == "BTC/USDT:USDT"
    assert normalize_symbol("ETH/USDT:USDT") == "ETH/USDT:USDT"


def test_normalize_symbol_rejects_unsupported_forms():
    """Scanner entry points should not score non-USDT perpetual symbols."""
    import pytest

    with pytest.raises(ValueError, match="unsupported symbol format"):
        normalize_symbol("BTC/USD")
