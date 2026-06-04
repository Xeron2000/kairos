#!/usr/bin/env python3
"""Coinglass RSI MCP Server for kairos trading system.

Provides tools to discover hot/oversold crypto coins using Coinglass RSI heatmap API.
Falls back to CoinGecko trending API when Coinglass API key is unavailable.

Usage:
    python -m kairos.mcp.coinglass_server
"""

import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger("kairos-coinglass-mcp")

COINGLASS_BASE = "https://open-api-v4.coinglass.com/api"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

mcp = FastMCP(
    name="Kairos-Coinglass",
    json_response=True,
)


def _get_coinglass_key() -> Optional[str]:
    """Get Coinglass API key from environment."""
    return os.environ.get("COINGLASS_API_KEY")


def _coinglass_headers() -> Dict[str, str]:
    """Build Coinglass API request headers."""
    key = _get_coinglass_key()
    if not key:
        return {}
    return {"CG-API-KEY": key, "Accept": "application/json"}


# ── Coinglass RSI Tools ─────────────────────────────────────────────────────


@mcp.tool()
async def get_rsi_heatmap() -> Dict[str, Any]:
    """Fetch RSI heatmap data from Coinglass API.

    Returns RSI values for 15m, 1h, 4h, 12h, 24h timeframes for all tracked
    futures pairs. Requires COINGLASS_API_KEY environment variable.

    Returns:
        dict with 'success', 'data' (list of coin RSI entries), 'timestamp'.
    """
    key = _get_coinglass_key()
    if not key:
        return {
            "success": False,
            "error": "COINGLASS_API_KEY not set",
            "hint": "Set COINGLASS_API_KEY env var or use get_trending_coins as fallback",
            "timestamp": datetime.now().isoformat(),
        }

    url = f"{COINGLASS_BASE}/futures/rsi/list"
    logger.info("Fetching Coinglass RSI heatmap from %s", url)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=_coinglass_headers())
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != "0":
            return {
                "success": False,
                "error": f"Coinglass API error: {data.get('msg', 'unknown')}",
                "timestamp": datetime.now().isoformat(),
            }

        entries = data.get("data", [])
        logger.info("Fetched %d RSI entries from Coinglass", len(entries))

        return {
            "success": True,
            "count": len(entries),
            "data": entries,
            "timestamp": datetime.now().isoformat(),
        }
    except httpx.HTTPStatusError as e:
        logger.error("Coinglass HTTP error: %s", e)
        return {
            "success": False,
            "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            "timestamp": datetime.now().isoformat(),
        }
    except httpx.RequestError as e:
        logger.error("Coinglass request error: %s", e)
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }


@mcp.tool()
async def get_hot_coins(
    rsi_high: float = 70.0,
    rsi_low: float = 30.0,
    timeframe: str = "4h",
    limit: int = 20,
) -> Dict[str, Any]:
    """Filter coins by RSI threshold to find overbought/oversold candidates.

    Args:
        rsi_high: RSI threshold for overbought (default 70).
        rsi_low: RSI threshold for oversold (default 30).
        timeframe: RSI timeframe: '15m', '1h', '4h', '12h', '24h' (default '4h').
        limit: Max coins to return (default 20).

    Returns:
        dict with 'overbought' and 'oversold' lists, each coin has symbol, price,
        price changes, and RSI values.
    """
    valid_tfs = {"15m", "1h", "4h", "12h", "24h"}
    if timeframe not in valid_tfs:
        return {
            "success": False,
            "error": f"Invalid timeframe '{timeframe}'. Use: {sorted(valid_tfs)}",
            "timestamp": datetime.now().isoformat(),
        }

    rsi_key_map: Dict[str, str] = {
        "15m": "rsi15m",
        "1h": "rsi1h",
        "4h": "rsi4h",
        "12h": "rsi12h",
        "24h": "rsi24h",
    }
    rsi_field = rsi_key_map[timeframe]

    result = await get_rsi_heatmap()
    if not result.get("success"):
        return result

    entries = result.get("data", [])
    overbought: List[Dict[str, Any]] = []
    oversold: List[Dict[str, Any]] = []

    for entry in entries:
        symbol = entry.get("symbol", "")
        rsi_val = entry.get(rsi_field)
        if rsi_val is None:
            continue

        try:
            rsi_val = float(rsi_val)
        except (TypeError, ValueError):
            continue

        coin_info = {
            "symbol": symbol,
            "price": entry.get("price"),
            "price_1h_change": entry.get("price1hChange"),
            "price_24h_change": entry.get("price24hChange"),
            "rsi_15m": entry.get("rsi15m"),
            "rsi_1h": entry.get("rsi1h"),
            "rsi_4h": entry.get("rsi4h"),
            "rsi_12h": entry.get("rsi12h"),
            "rsi_24h": entry.get("rsi24h"),
        }

        if rsi_val >= rsi_high:
            overbought.append(coin_info)
        elif rsi_val <= rsi_low:
            oversold.append(coin_info)

    overbought.sort(key=lambda c: float(c.get(f"rsi_{timeframe}", 0) or 0), reverse=True)
    oversold.sort(key=lambda c: float(c.get(f"rsi_{timeframe}", 0) or 0))

    return {
        "success": True,
        "timeframe": timeframe,
        "total_entries": len(entries),
        "overbought_count": len(overbought),
        "oversold_count": len(oversold),
        "overbought": overbought[:limit],
        "oversold": oversold[:limit],
        "timestamp": datetime.now().isoformat(),
    }


@mcp.tool()
async def get_coin_rsi(symbol: str = "BTC") -> Dict[str, Any]:
    """Get RSI values across all timeframes for a specific coin.

    Args:
        symbol: Coin symbol without USDT suffix (e.g., 'BTC', 'ETH', 'SOL').

    Returns:
        dict with RSI values for each timeframe and price info.
    """
    result = await get_rsi_heatmap()
    if not result.get("success"):
        return result

    symbol_upper = symbol.upper()
    entries = result.get("data", [])

    for entry in entries:
        entry_symbol = entry.get("symbol", "").upper()
        if entry_symbol == symbol_upper:
            return {
                "success": True,
                "symbol": entry.get("symbol"),
                "price": entry.get("price"),
                "price_1h_change": entry.get("price1hChange"),
                "price_24h_change": entry.get("price24hChange"),
                "rsi": {
                    "15m": entry.get("rsi15m"),
                    "1h": entry.get("rsi1h"),
                    "4h": entry.get("rsi4h"),
                    "12h": entry.get("rsi12h"),
                    "24h": entry.get("rsi24h"),
                },
                "timestamp": datetime.now().isoformat(),
            }

    return {
        "success": False,
        "error": f"Symbol '{symbol_upper}' not found in Coinglass RSI data",
        "timestamp": datetime.now().isoformat(),
    }


# ── CoinGecko Fallback Tools ────────────────────────────────────────────────


@mcp.tool()
async def get_trending_coins() -> Dict[str, Any]:
    """Get trending coins from CoinGecko free API.

    Works without any API key. Used as fallback when Coinglass key unavailable.
    Also fetches market data for top 50 coins by volume.

    Returns:
        dict with 'trending' list and 'top_by_volume' list.
    """
    logger.info("Fetching trending coins from CoinGecko")
    results: Dict[str, Any] = {
        "success": True,
        "source": "coingecko",
        "timestamp": datetime.now().isoformat(),
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Trending search
            trending_url = f"{COINGECKO_BASE}/search/trending"
            trending_resp = await client.get(trending_url)
            trending_resp.raise_for_status()
            trending_data = trending_resp.json()

            trending_coins: List[Dict[str, Any]] = []
            for coin in trending_data.get("coins", [])[:15]:
                item = coin.get("item", {})
                trending_coins.append(
                    {
                        "id": item.get("id"),
                        "symbol": (item.get("symbol") or "").upper(),
                        "name": item.get("name"),
                        "market_cap_rank": item.get("market_cap_rank"),
                        "score": item.get("score"),
                    }
                )
            results["trending"] = trending_coins

            # Top coins by volume
            markets_url = (
                f"{COINGECKO_BASE}/coins/markets"
                "?vs_currency=usd&order=volume_desc&per_page=50&page=1"
                "&sparkline=false&price_change_percentage=1h%2C24h"
            )
            markets_resp = await client.get(markets_url)
            markets_resp.raise_for_status()
            markets_data = markets_resp.json()

            top_coins: List[Dict[str, Any]] = []
            for coin in markets_data:
                top_coins.append(
                    {
                        "id": coin.get("id"),
                        "symbol": (coin.get("symbol") or "").upper(),
                        "name": coin.get("name"),
                        "current_price": coin.get("current_price"),
                        "market_cap": coin.get("market_cap"),
                        "total_volume": coin.get("total_volume"),
                        "price_change_1h": coin.get("price_change_percentage_1h_in_currency"),
                        "price_change_24h": coin.get("price_change_percentage_24h_in_currency"),
                        "market_cap_rank": coin.get("market_cap_rank"),
                    }
                )
            results["top_by_volume"] = top_coins[:30]

            logger.info(
                "CoinGecko: %d trending, %d top-by-volume",
                len(trending_coins),
                len(top_coins),
            )
            return results

    except httpx.HTTPStatusError as e:
        logger.error("CoinGecko HTTP error: %s", e)
        return {
            "success": False,
            "error": f"CoinGecko HTTP {e.response.status_code}",
            "source": "coingecko",
            "timestamp": datetime.now().isoformat(),
        }
    except httpx.RequestError as e:
        logger.error("CoinGecko request error: %s", e)
        return {
            "success": False,
            "error": str(e),
            "source": "coingecko",
            "timestamp": datetime.now().isoformat(),
        }


# ── Entry Point ──────────────────────────────────────────────────────────────


def main() -> None:
    """Run the Coinglass RSI MCP server via stdio."""
    logger.info("Starting Coinglass RSI MCP server")
    key_status = "configured" if _get_coinglass_key() else "missing (use get_trending_coins fallback)"
    logger.info("Coinglass API key: %s", key_status)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
