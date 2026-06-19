"""Tests for the optional CoinGlass encrypted market-context client."""

import base64
import gzip
import json

import httpx
import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from kairos.data import coinglass_client as cg


def _encrypt_aes_ecb(plain: bytes, key: bytes) -> bytes:
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(plain) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _encrypted_response(payload: object, *, v: str = "55", url: str = "") -> tuple[str, str]:
    actual_key = "abcdefghijklmnop"
    key0 = cg._derive_key0(v, url).encode()
    user = base64.b64encode(_encrypt_aes_ecb(gzip.compress(actual_key.encode()), key0)).decode()
    encrypted_payload = _encrypt_aes_ecb(gzip.compress(json.dumps(payload).encode()), actual_key.encode())
    body = json.dumps({"data": base64.b64encode(encrypted_payload).decode()})
    return body, user


def test_decrypt_coinglass_response_round_trips_synthetic_payload():
    payload = {"list": [{"symbol": "BTC", "rsi4h": 72.5}], "total": 1}
    body, user = _encrypted_response(payload)

    assert cg.decrypt_coinglass_response(body, user, "55") == payload


def test_fetch_coinglass_endpoint_decrypts_mock_response():
    payload = [{"symbol": "ETH", "fundingRate": 0.001}]
    body, user = _encrypted_response(payload)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/fundingRate/rank"
        assert request.headers["encryption"] == "true"
        return httpx.Response(200, text=body, headers={"user": user, "v": "55"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    assert cg.fetch_coinglass_endpoint("/api/fundingRate/rank", client=client) == payload


def test_fetch_coinglass_endpoint_raises_on_plain_api_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "40001", "msg": "Required parameter missing", "success": False})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(cg.CoinGlassAPIError, match="Required parameter missing"):
        cg.fetch_coinglass_endpoint("/api/openInterest/info", client=client)


def test_hot_coins_normalizes_and_filters_rsi_entries(monkeypatch):
    def fake_fetch(path, params=None, **_kwargs):
        assert path == cg.COINGLASS_ENDPOINTS["spot_rsi"].path
        assert params == {"pageSize": 500, "pageNum": 1}
        return {
            "total": 3,
            "list": [
                {"symbol": "SENT", "price": "1.2", "rank": 9, "rsi4h": "76.2", "rsi1h": "65"},
                {"symbol": "SYN", "price": "0.2", "rank": 10, "rsi4h": "21.4", "rsi1h": "35"},
                {"symbol": "BTC", "price": "61412", "rank": 0, "rsi4h": "51.9", "rsi1h": "40"},
            ],
        }

    monkeypatch.setattr(cg, "fetch_coinglass_endpoint", fake_fetch)

    result = cg.get_hot_coins(timeframe="4h", rsi_high=70, rsi_low=30, limit=10)

    assert result["overbought_count"] == 1
    assert result["oversold_count"] == 1
    assert result["overbought"][0]["symbol"] == "SENT"
    assert result["oversold"][0]["symbol"] == "SYN"
    assert result["overbought"][0]["rsi"]["4h"] == 76.2


def test_symbol_context_degrades_by_section(monkeypatch):
    def fake_fetch(path, params=None, **_kwargs):
        if path == cg.COINGLASS_ENDPOINTS["index_rsi"].path:
            return [{"symbol": "BTC", "price": 61000, "rsi4h": 41, "rsi24h": 25}]
        if path == cg.COINGLASS_ENDPOINTS["funding_list"].path:
            raise cg.CoinGlassAPIError("funding down")
        if path == cg.COINGLASS_ENDPOINTS["futures_top"].path:
            return [{"symbol": "BTC", "exchangeName": "Binance", "volUsd": 10_000_000, "openInterest": 5_000_000}]
        if path == cg.COINGLASS_ENDPOINTS["open_interest_info"].path:
            return [{"exchangeName": "Binance", "openInterest": 5_000_000, "volUsd": 10_000_000}]
        if path == cg.COINGLASS_ENDPOINTS["long_short_rate"].path:
            return [{"list": [{"exchangeName": "Binance", "longVolUsd": 52, "shortVolUsd": 48, "totalVolUsd": 100}]}]
        if path == cg.COINGLASS_ENDPOINTS["liquidation_today"].path:
            return {"liquidationUsd": 1000, "longLiquidationUsd": 700, "shortLiquidationUsd": 300, "ticker": {"price": 61000}}
        raise AssertionError(path)

    monkeypatch.setattr(cg, "fetch_coinglass_endpoint", fake_fetch)

    result = cg.get_symbol_context("BTC/USDT:USDT")

    assert result["symbol"] == "BTC"
    assert result["section_count"] == 5
    assert result["sections"]["rsi"]["rsi"]["24h"] == 25
    assert result["sections"]["long_short"]["aggregate_long_rate"] == 52.0
    assert any("funding down" in warning for warning in result["warnings"])


def test_normalize_coin_symbol_supports_exchange_formats():
    assert cg.normalize_coin_symbol("BTC/USDT:USDT") == "BTC"
    assert cg.normalize_coin_symbol("ETHUSDT") == "ETH"
    assert cg.normalize_coin_symbol("SOL-USDT-SWAP") == "SOL"
