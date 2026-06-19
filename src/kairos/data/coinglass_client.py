"""Best-effort CoinGlass encrypted API client for market context.

The response decryption algorithm is based on the local research artifact in
`/home/xeron/Coding/coinglass-decrypt/`. CoinGlass context is optional evidence
for Hermes and must not become a hard dependency for Kairos signal generation.
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
import time
from dataclasses import dataclass
from statistics import fmean
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)

COINGLASS_BASE_URL = "https://capi.coinglass.com"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_RSI_PAGE_SIZE = 500
MAX_LIMIT = 500

_KEY_TABLE = {
    "55": "170b070da9654622",
    "66": "d6537d845a964081",
    "77": "863f08689c97435b",
}

_RSI_FIELDS = {
    "5m": "rsi5m",
    "15m": "rsi15m",
    "1h": "rsi1h",
    "4h": "rsi4h",
    "12h": "rsi12h",
    "24h": "rsi24h",
    "1w": "rsi1w",
}


class CoinGlassError(RuntimeError):
    """Base class for CoinGlass client failures."""


class CoinGlassAPIError(CoinGlassError):
    """Raised when CoinGlass returns an application-level error."""


class CoinGlassDecodeError(CoinGlassError):
    """Raised when encrypted payload decryption or parsing fails."""


class CoinGlassDataError(CoinGlassError):
    """Raised when a requested normalized datum is unavailable."""


@dataclass(frozen=True)
class CoinGlassEndpoint:
    """Allowlisted CoinGlass endpoint metadata."""

    path: str
    description: str


COINGLASS_ENDPOINTS = {
    "spot_rsi": CoinGlassEndpoint("/api/spot/rsi/list", "Spot RSI heatmap list"),
    "index_rsi": CoinGlassEndpoint("/api/index/rsiMap", "Index RSI map"),
    "funding_rank": CoinGlassEndpoint("/api/fundingRate/rank", "Extreme funding-rate rank"),
    "funding_avg": CoinGlassEndpoint("/api/fundingRate/avg", "BTC/ETH aggregate funding"),
    "funding_list": CoinGlassEndpoint("/api/fundingRate/list", "Per-symbol funding by exchange"),
    "futures_top": CoinGlassEndpoint("/api/futures/top/coins/tickers", "Top futures ticker context"),
    "open_interest_info": CoinGlassEndpoint("/api/openInterest/info", "Per-symbol open-interest context"),
    "long_short_rate": CoinGlassEndpoint("/api/futures/longShortRate", "Per-symbol long/short flow"),
    "liquidation_today": CoinGlassEndpoint("/api/futures/liquidation/today", "Per-symbol liquidation today"),
}


def decrypt_coinglass_response(encrypted_body: str | bytes, user_token_b64: str, v: str, url: str = "") -> Any:
    """Decrypt a CoinGlass encrypted response body into JSON-native data."""
    try:
        body_text = encrypted_body.decode() if isinstance(encrypted_body, bytes) else encrypted_body
        outer = json.loads(body_text)
        payload = base64.b64decode(outer["data"])
        token = base64.b64decode(user_token_b64)

        key0 = _derive_key0(str(v), url)
        step1 = _aes_ecb_decrypt(token, key0.encode())
        actual_key = gzip.decompress(step1).decode()

        step2 = _aes_ecb_decrypt(payload, actual_key.encode())
        plain = gzip.decompress(step2).decode()
        return json.loads(plain)
    except (KeyError, ValueError, json.JSONDecodeError, OSError) as exc:
        raise CoinGlassDecodeError(f"Cannot decrypt CoinGlass response: {exc}") from exc


def fetch_coinglass_endpoint(
    path: str,
    params: Mapping[str, Any] | None = None,
    *,
    client: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    base_url: str = COINGLASS_BASE_URL,
) -> Any:
    """Fetch a CoinGlass endpoint and decrypt it when encrypted headers are present."""
    url = _build_url(path, base_url)
    request_params = dict(params or {})
    headers = _request_headers()
    owns_client = client is None

    active_client = client or httpx.Client(timeout=timeout)
    try:
        response = active_client.get(url, params=request_params, headers=headers)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise CoinGlassAPIError(f"CoinGlass request failed for {path}: {exc}") from exc
    finally:
        if owns_client:
            active_client.close()

    user = response.headers.get("user")
    version = response.headers.get("v")
    if user and version:
        return decrypt_coinglass_response(response.content, user, version, str(response.url))

    return _parse_plain_response(response, path)


def get_rsi_heatmap(
    *,
    source: str = "spot",
    page_size: int = DEFAULT_RSI_PAGE_SIZE,
    page_num: int = 1,
    limit: int | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Return normalized CoinGlass RSI entries."""
    normalized_source = source.lower().strip()
    if normalized_source == "spot":
        payload = fetch_coinglass_endpoint(
            COINGLASS_ENDPOINTS["spot_rsi"].path,
            {"pageSize": max(1, min(int(page_size), MAX_LIMIT)), "pageNum": max(1, int(page_num))},
            client=client,
        )
        raw_entries = _extract_entries(payload)
        total = _to_int(payload.get("total")) if isinstance(payload, Mapping) else None
    elif normalized_source == "index":
        payload = fetch_coinglass_endpoint(COINGLASS_ENDPOINTS["index_rsi"].path, client=client)
        raw_entries = _extract_entries(payload)
        total = len(raw_entries)
    else:
        raise CoinGlassDataError("source must be 'spot' or 'index'")

    entries = [_normalize_rsi_entry(entry) for entry in raw_entries if isinstance(entry, Mapping)]
    entries = [entry for entry in entries if entry["symbol"]]
    if limit is not None:
        entries = entries[: _clamp_limit(limit)]

    return {
        "source": normalized_source,
        "total": total if total is not None else len(entries),
        "count": len(entries),
        "entries": entries,
    }


def get_hot_coins(
    *,
    timeframe: str = "4h",
    rsi_high: float = 70.0,
    rsi_low: float = 30.0,
    limit: int = 20,
    source: str = "spot",
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Return overbought and oversold coins by RSI threshold."""
    timeframe_key = _normalize_timeframe(timeframe)
    heatmap = get_rsi_heatmap(source=source, client=client)
    max_items = _clamp_limit(limit)

    overbought: list[dict[str, Any]] = []
    oversold: list[dict[str, Any]] = []
    for entry in heatmap["entries"]:
        rsi_value = _to_float(entry["rsi"].get(timeframe_key))
        if rsi_value is None:
            continue
        if rsi_value >= float(rsi_high):
            overbought.append(entry)
        elif rsi_value <= float(rsi_low):
            oversold.append(entry)

    overbought.sort(key=lambda item: float(item["rsi"][timeframe_key]), reverse=True)
    oversold.sort(key=lambda item: float(item["rsi"][timeframe_key]))

    return {
        "source": heatmap["source"],
        "timeframe": timeframe_key,
        "rsi_high": float(rsi_high),
        "rsi_low": float(rsi_low),
        "total_entries": heatmap["count"],
        "overbought_count": len(overbought),
        "oversold_count": len(oversold),
        "overbought": overbought[:max_items],
        "oversold": oversold[:max_items],
    }


def get_coin_rsi(symbol: str, *, source: str = "index", client: httpx.Client | None = None) -> dict[str, Any]:
    """Return normalized RSI context for one base symbol."""
    base = normalize_coin_symbol(symbol)
    heatmap = get_rsi_heatmap(source=source, client=client)
    for entry in heatmap["entries"]:
        if entry["symbol"] == base:
            return {"source": heatmap["source"], "symbol": base, "entry": entry}
    raise CoinGlassDataError(f"{base} not found in CoinGlass {heatmap['source']} RSI data")


def get_funding_extremes(*, limit: int = 20, client: httpx.Client | None = None) -> dict[str, Any]:
    """Return normalized extreme funding-rate ranks."""
    payload = fetch_coinglass_endpoint(COINGLASS_ENDPOINTS["funding_rank"].path, client=client)
    if not isinstance(payload, Mapping):
        raise CoinGlassDataError("CoinGlass funding rank returned an unexpected payload")
    max_items = _clamp_limit(limit)
    return {
        "source": "fundingRate/rank",
        "most_negative": [_normalize_funding_rank(entry) for entry in _as_list(payload.get("min"))[:max_items]],
        "most_positive": [_normalize_funding_rank(entry) for entry in _as_list(payload.get("max"))[:max_items]],
    }


def get_market_funding_average(*, client: httpx.Client | None = None) -> dict[str, Any]:
    """Return BTC/ETH aggregate funding averages from CoinGlass."""
    payload = fetch_coinglass_endpoint(COINGLASS_ENDPOINTS["funding_avg"].path, client=client)
    if not isinstance(payload, Mapping):
        raise CoinGlassDataError("CoinGlass funding average returned an unexpected payload")
    return {
        "source": "fundingRate/avg",
        "btc_funding_by_volume": _to_float(payload.get("btcFundingByVol")),
        "btc_funding_by_open_interest": _to_float(payload.get("btcFundingByOi")),
        "eth_funding_by_volume": _to_float(payload.get("ethFundingByVol")),
        "eth_funding_by_open_interest": _to_float(payload.get("ethFundingByOi")),
    }


def get_symbol_context(symbol: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    """Return optional CoinGlass context sections for a single base symbol."""
    base = normalize_coin_symbol(symbol)
    warnings: list[str] = []
    sections: dict[str, Any] = {}

    _add_section(sections, warnings, "rsi", lambda: get_coin_rsi(base, source="index", client=client)["entry"])
    _add_section(sections, warnings, "funding", lambda: _symbol_funding_context(base, client=client))
    _add_section(sections, warnings, "futures", lambda: _symbol_futures_context(base, client=client))
    _add_section(sections, warnings, "open_interest", lambda: _open_interest_context(base, client=client))
    _add_section(sections, warnings, "long_short", lambda: _long_short_context(base, client=client))
    _add_section(sections, warnings, "liquidation_today", lambda: _liquidation_today_context(base, client=client))

    return {
        "source": "coinglass",
        "symbol": base,
        "sections": sections,
        "section_count": len(sections),
        "warnings": warnings,
    }


def normalize_coin_symbol(symbol: str) -> str:
    """Normalize user/exchange symbols to a CoinGlass base symbol such as BTC."""
    value = str(symbol or "").upper().strip()
    if not value:
        raise CoinGlassDataError("symbol is required")
    value = value.split(":", 1)[0]
    for separator in ("/", "-", "_"):
        if separator in value:
            value = value.split(separator, 1)[0]
            break
    for suffix in ("USDT", "USDC", "USD", "PERP"):
        if value.endswith(suffix) and len(value) > len(suffix):
            value = value[: -len(suffix)]
            break
    return value


def _derive_key0(v: str, url: str = "") -> str:
    if v == "1":
        parsed = urlparse(url)
        constant = parsed.path or url.split("?", 1)[0]
    else:
        constant = _KEY_TABLE.get(v)
        if constant is None:
            raise ValueError(f"Unknown CoinGlass encryption version: {v}")
    return base64.b64encode(constant.encode()).decode()[:16]


def _aes_ecb_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def _build_url(path: str, base_url: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _request_headers() -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "cache-ts-v2": str(int(time.time() * 1000)),
        "encryption": "true",
        "language": "en",
        "Origin": "https://www.coinglass.com",
        "Referer": "https://www.coinglass.com/pro/i/RsiHeatMap",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/125.0.0.0 Safari/537.36",
    }


def _parse_plain_response(response: httpx.Response, path: str) -> Any:
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise CoinGlassAPIError(f"CoinGlass returned non-JSON response for {path}") from exc

    if isinstance(payload, Mapping):
        code = str(payload.get("code", "0"))
        success = payload.get("success")
        if success is False or code not in {"0", "None"}:
            message = payload.get("msg") or payload.get("message") or payload.get("error") or payload
            raise CoinGlassAPIError(f"CoinGlass API error for {path}: {message}")
        if "data" in payload and len(payload) <= 4:
            return payload["data"]
    return payload


def _extract_entries(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping):
        for key in ("list", "data", "items", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _normalize_rsi_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    rsi = {timeframe: _to_float(entry.get(field)) for timeframe, field in _RSI_FIELDS.items() if field in entry}
    price_change = {
        "5m": _to_float(entry.get("priceChangePercent5m")),
        "15m": _to_float(entry.get("priceChangePercent15m")),
        "1h": _to_float(entry.get("priceChangePercent1h")),
        "4h": _to_float(entry.get("priceChangePercent4h")),
        "12h": _to_float(entry.get("priceChangePercent12h")),
        "24h": _to_float(entry.get("priceChangePercent24h")),
        "7d": _to_float(entry.get("priceChangePercent7d")),
        "30d": _to_float(entry.get("priceChangePercent30d")),
    }
    return {
        "symbol": normalize_coin_symbol(str(entry.get("symbol", ""))) if entry.get("symbol") else "",
        "name": entry.get("name"),
        "rank": _to_int(entry.get("rank")),
        "price": _to_float(entry.get("price")),
        "rsi": {key: value for key, value in rsi.items() if value is not None},
        "price_change_pct": {key: value for key, value in price_change.items() if value is not None},
    }


def _normalize_timeframe(timeframe: str) -> str:
    value = str(timeframe).lower().strip()
    if value not in _RSI_FIELDS:
        raise CoinGlassDataError(f"timeframe must be one of {sorted(_RSI_FIELDS)}")
    return value


def _normalize_funding_rank(entry: Any) -> dict[str, Any]:
    item = entry if isinstance(entry, Mapping) else {}
    return {
        "symbol": normalize_coin_symbol(str(item.get("symbol", ""))) if item.get("symbol") else "",
        "exchange": item.get("exchangeName"),
        "instrument_id": item.get("originalSymbol"),
        "quote_currency": item.get("quoteCurrency"),
        "funding_rate": _to_float(item.get("fundingRate")),
        "predicted_rate": _to_float(item.get("predictedRate")),
    }


def _symbol_funding_context(base: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    payload = fetch_coinglass_endpoint(
        COINGLASS_ENDPOINTS["funding_list"].path,
        {"pageSize": DEFAULT_RSI_PAGE_SIZE, "pageNum": 1},
        client=client,
    )
    for entry in _extract_entries(payload):
        if not isinstance(entry, Mapping) or normalize_coin_symbol(str(entry.get("symbol", ""))) != base:
            continue
        rows = [_normalize_funding_exchange(item) for item in _as_list(entry.get("stableCoin"))]
        rows = [row for row in rows if row["funding_rate"] is not None]
        rows.sort(key=lambda item: abs(float(item["funding_rate"])), reverse=True)
        rates = [float(row["funding_rate"]) for row in rows]
        return {
            "exchange_count": len(rows),
            "average_funding_rate": round(fmean(rates), 8) if rates else None,
            "max_abs_funding_rate": max((abs(rate) for rate in rates), default=None),
            "exchanges": rows[:12],
        }
    raise CoinGlassDataError(f"{base} funding data not found")


def _normalize_funding_exchange(entry: Any) -> dict[str, Any]:
    item = entry if isinstance(entry, Mapping) else {}
    return {
        "exchange": item.get("exName"),
        "instrument_id": item.get("instrumentId"),
        "funding_rate": _to_float(item.get("fundingRate")),
        "interval_hours": _to_int(item.get("intervalHours")),
        "next_funding_time": _to_int(item.get("nextFundingTime")),
    }


def _symbol_futures_context(base: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    payload = fetch_coinglass_endpoint(COINGLASS_ENDPOINTS["futures_top"].path, client=client)
    rows = []
    for entry in _extract_entries(payload):
        if isinstance(entry, Mapping) and normalize_coin_symbol(str(entry.get("symbol", ""))) == base:
            rows.append(
                {
                    "exchange": entry.get("exchangeName"),
                    "instrument_id": entry.get("originalSymbol"),
                    "quote_currency": entry.get("quoteCurrency"),
                    "price": _to_float(entry.get("price")),
                    "price_change_24h_pct": _to_float(entry.get("priceChangePercent")),
                    "funding_rate": _to_float(entry.get("fundingRate")),
                    "open_interest": _to_float(entry.get("openInterest")),
                    "open_interest_amount": _to_float(entry.get("openInterestAmount")),
                    "volume_usd_24h": _to_float(entry.get("volUsd")),
                }
            )
    if not rows:
        raise CoinGlassDataError(f"{base} futures ticker data not found")
    rows.sort(key=lambda item: item["volume_usd_24h"] or 0.0, reverse=True)
    return {"exchange_count": len(rows), "top_markets": rows[:12]}


def _open_interest_context(base: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    payload = fetch_coinglass_endpoint(COINGLASS_ENDPOINTS["open_interest_info"].path, {"symbol": base}, client=client)
    rows = []
    for entry in _extract_entries(payload):
        if not isinstance(entry, Mapping):
            continue
        rows.append(
            {
                "exchange": entry.get("exchangeName"),
                "open_interest": _to_float(entry.get("openInterest")),
                "open_interest_amount": _to_float(entry.get("openInterestAmount")),
                "volume_usd_24h": _to_float(entry.get("volUsd")),
                "oi_change_pct_5m": _to_float(entry.get("m5OIChangePercent")),
                "oi_change_pct_15m": _to_float(entry.get("m15OIChangePercent")),
                "oi_change_pct_4h": _to_float(entry.get("h4OIChangePercent")),
                "oi_change_pct_24h": _to_float(entry.get("oichangePercent")),
                "oi_change_pct_7d": _to_float(entry.get("oiChangePercent7d")),
            }
        )
    rows = [row for row in rows if row["open_interest"] is not None]
    if not rows:
        raise CoinGlassDataError(f"{base} open-interest data not found")
    rows.sort(key=lambda item: item["open_interest"] or 0.0, reverse=True)
    return {
        "exchange_count": len(rows),
        "top_exchanges": rows[:12],
        "top_open_interest": rows[0]["open_interest"],
        "top_exchange": rows[0]["exchange"],
    }


def _long_short_context(base: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    payload = fetch_coinglass_endpoint(
        COINGLASS_ENDPOINTS["long_short_rate"].path,
        {"timeType": 2, "symbol": base},
        client=client,
    )
    container = _extract_entries(payload)
    exchange_entries = _extract_entries(container[0]) if container and isinstance(container[0], Mapping) else container
    rows = []
    for entry in exchange_entries:
        if not isinstance(entry, Mapping):
            continue
        rows.append(
            {
                "exchange": entry.get("exchangeName"),
                "long_rate": _to_float(entry.get("longRate")),
                "short_rate": _to_float(entry.get("shortRate")),
                "long_volume_usd": _to_float(entry.get("longVolUsd")),
                "short_volume_usd": _to_float(entry.get("shortVolUsd")),
                "total_volume_usd": _to_float(entry.get("totalVolUsd")),
            }
        )
    rows = [row for row in rows if row["total_volume_usd"] is not None]
    if not rows:
        raise CoinGlassDataError(f"{base} long/short data not found")
    rows.sort(key=lambda item: item["total_volume_usd"] or 0.0, reverse=True)
    long_volume = sum(row["long_volume_usd"] or 0.0 for row in rows)
    short_volume = sum(row["short_volume_usd"] or 0.0 for row in rows)
    total_volume = long_volume + short_volume
    return {
        "exchange_count": len(rows),
        "aggregate_long_rate": round(long_volume / total_volume * 100, 2) if total_volume else None,
        "aggregate_short_rate": round(short_volume / total_volume * 100, 2) if total_volume else None,
        "top_exchanges": rows[:12],
    }


def _liquidation_today_context(base: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    payload = fetch_coinglass_endpoint(
        COINGLASS_ENDPOINTS["liquidation_today"].path,
        {"symbol": base},
        client=client,
    )
    if not isinstance(payload, Mapping):
        raise CoinGlassDataError(f"{base} liquidation data not found")
    ticker = payload.get("ticker") if isinstance(payload.get("ticker"), Mapping) else {}
    return {
        "liquidation_usd": _to_float(payload.get("liquidationUsd")),
        "long_liquidation_usd": _to_float(payload.get("longLiquidationUsd")),
        "short_liquidation_usd": _to_float(payload.get("shortLiquidationUsd")),
        "long_liquidation_rate": _to_float(payload.get("longLiquidationRate")),
        "short_liquidation_rate": _to_float(payload.get("shortLiquidationRate")),
        "liquidation_traders": _to_int(payload.get("liquidationTraders")),
        "max_order": payload.get("maxOrder"),
        "ticker": {
            "price": _to_float(ticker.get("price")),
            "price_change_24h_pct": _to_float(ticker.get("priceChangePercent")),
            "long_rate": _to_float(ticker.get("longRate")),
            "short_rate": _to_float(ticker.get("shortRate")),
            "total_volume_usd": _to_float(ticker.get("totalVolUsd")),
        },
    }


def _add_section(sections: dict[str, Any], warnings: list[str], name: str, loader: Any) -> None:
    try:
        sections[name] = loader()
    except CoinGlassError as exc:
        warnings.append(f"{name}: {exc}")
    except Exception as exc:
        logger.debug("Unexpected CoinGlass %s context failure: %s", name, exc)
        warnings.append(f"{name}: {exc}")


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _clamp_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))
