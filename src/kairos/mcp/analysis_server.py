#!/usr/bin/env python3
"""Kairos Analysis MCP Server.

Wraps kairos analysis modules (cycle, box, SR) as MCP tools for hermes-agent.
hermes-agent calls these tools directly via function calling instead of CLI commands.

Usage:
    python -m kairos.mcp.analysis_server
"""

from __future__ import annotations

import logging
import sys
from dataclasses import asdict
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger("kairos-analysis-mcp")

mcp = FastMCP(name="Kairos-Analysis", json_response=True)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _to_array(data: Any) -> np.ndarray:
    """Convert list/tuple to numpy float64 array."""
    if isinstance(data, np.ndarray):
        return data.astype(np.float64)
    return np.array(data, dtype=np.float64)


def _serialize_enum(obj: Any) -> Any:
    """Recursively convert Enum values to strings and dataclasses to dicts."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _serialize_enum(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_enum(v) for v in obj]
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _serialize_enum(v) for k, v in asdict(obj).items()}
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def _compute_trend(closes: np.ndarray) -> str:
    """Compute simple trend direction via linear regression slope."""
    if len(closes) < 5:
        return "sideways"
    recent = closes[-20:] if len(closes) >= 20 else closes
    if len(recent) < 3:
        return "sideways"
    x = np.arange(len(recent))
    slope = np.polyfit(x, recent, 1)[0]
    threshold = recent[-1] * 0.001 if recent[-1] > 0 else 0.01
    if slope > threshold:
        return "up"
    if slope < -threshold:
        return "down"
    return "sideways"


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------


@mcp.tool()
def analyze_cycle(
    btc_prices: List[float],
    btc_volumes: List[float],
    altcoin_correlation: float = 0.8,
    avg_funding_rate: float = 0.01,
    total_market_cap_change_30d: float = 0.0,
) -> Dict[str, Any]:
    """Analyze BTC market cycle phase (spring/summer/autumn/winter theory).

    Uses Bit浪浪's four-season market cycle theory with quantitative scoring.

    Args:
        btc_prices: Daily BTC closing prices (at least 30 entries)
        btc_volumes: Daily BTC volumes (same length as prices)
        altcoin_correlation: How correlated altcoins are with BTC (0-1)
        avg_funding_rate: Average perpetual funding rate
        total_market_cap_change_30d: Total market cap 30-day change %

    Returns:
        dict with phase, confidence, indicators, description, and strategy advice.
    """
    try:
        from kairos.analysis.cycle import CycleDetector

        prices_arr = _to_array(btc_prices)
        volumes_arr = _to_array(btc_volumes)

        if len(prices_arr) < 30:
            return {
                "success": False,
                "error": "Need at least 30 daily prices for cycle detection",
            }

        detector = CycleDetector()
        cycle = detector.detect_phase(
            btc_prices=prices_arr,
            btc_volumes=volumes_arr,
            altcoin_correlation=altcoin_correlation,
            avg_funding_rate=avg_funding_rate,
            total_market_cap_change_30d=total_market_cap_change_30d,
        )

        strategy = {
            "spring": [
                "积极寻找右侧跟随大盘突破的机会",
                "建立底仓，准备迎接主升浪",
                "聚焦龙头币和次新币",
            ],
            "summer": [
                "聚焦龙头，重仓出击",
                "加息周期远离山寨",
                "顺势加仓，移动止盈",
            ],
            "autumn": [
                "收缩防守，轻仓操作",
                "补涨行情，快进快出",
                "注意高位风险",
            ],
            "winter": [
                "空仓等待，管住手",
                "耐心等待下一个春天",
                "不要妄想在震荡行情中多空双吃",
            ],
        }

        result = {
            "success": True,
            "phase": cycle.phase.value,
            "confidence": cycle.confidence,
            "btc_trend": cycle.btc_trend,
            "btc_change_30d": cycle.btc_change_30d,
            "btc_change_7d": cycle.btc_change_7d,
            "volatility": cycle.volatility,
            "volume_trend": cycle.volume_trend,
            "altcoin_correlation": cycle.altcoin_correlation,
            "funding_rates_avg": cycle.funding_rates_avg,
            "market_cap_change_30d": cycle.market_cap_change_30d,
            "description": cycle.description,
            "position_advice": cycle.position_advice,
            "strategy": strategy.get(cycle.phase.value, []),
        }
        return result

    except Exception as e:
        logger.error("analyze_cycle failed: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool()
def detect_boxes(
    symbol: str,
    timeframe: str,
    highs: List[float],
    lows: List[float],
    closes: List[float],
    volumes: List[float],
    timestamps: List[float],
    current_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Detect box patterns in OHLCV price data.

    Uses box theory: price consolidates between parallel support/resistance,
    forming a "box". Breakout from box signals next directional move.

    Args:
        symbol: Trading symbol (e.g. "BTC/USDT")
        timeframe: Chart timeframe (e.g. "15m", "4h", "1d")
        highs: High prices array
        lows: Low prices array
        closes: Close prices array
        volumes: Volume array
        timestamps: UNIX timestamps in milliseconds
        current_price: Current price for breakout check (optional)

    Returns:
        dict with boxes list and trend direction.
    """
    try:
        from kairos.analysis.box_pattern import BoxDetector

        highs_arr = _to_array(highs)
        lows_arr = _to_array(lows)
        closes_arr = _to_array(closes)
        volumes_arr = _to_array(volumes)
        timestamps_arr = _to_array(timestamps)

        detector = BoxDetector()
        boxes = detector.detect(
            symbol=symbol,
            timeframe=timeframe,
            highs=highs_arr,
            lows=lows_arr,
            closes=closes_arr,
            volumes=volumes_arr,
            timestamps=timestamps_arr,
        )

        # Check breakout for each box if current price is available
        if current_price is not None and boxes:
            avg_vol = float(np.mean(volumes_arr[-20:])) if len(volumes_arr) >= 20 else float(np.mean(volumes_arr))
            last_vol = float(volumes_arr[-1]) if len(volumes_arr) > 0 else avg_vol
            for box in boxes:
                detector.check_breakout(
                    box=box,
                    current_price=current_price,
                    current_volume=last_vol,
                    avg_volume=avg_vol,
                )

        trend = _compute_trend(closes_arr)

        boxes_out = []
        for box in boxes:
            box_dict = asdict(box)
            # Convert Enum to string
            box_dict["status"] = box.status.value
            boxes_out.append(box_dict)

        return {
            "success": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "trend": trend,
            "box_count": len(boxes_out),
            "boxes": boxes_out,
        }

    except Exception as e:
        logger.error("detect_boxes failed: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool()
def find_sr_levels(
    symbol: str,
    highs: List[float],
    lows: List[float],
    closes: List[float],
    volumes: List[float],
    timestamps: List[float],
    current_price: float,
) -> Dict[str, Any]:
    """Find support and resistance levels in price data.

    Detects pivot-based S/R levels, clusters nearby pivots, identifies
    round-number levels, and ranks by strength and proximity.

    Args:
        symbol: Trading symbol
        highs: High prices array
        lows: Low prices array
        closes: Close prices array
        volumes: Volume array
        timestamps: UNIX timestamps in milliseconds
        current_price: Current market price

    Returns:
        dict with resistance_levels, support_levels, nearest levels, round_numbers.
    """
    try:
        from kairos.analysis.support_resistance import SupportResistance

        highs_arr = _to_array(highs)
        lows_arr = _to_array(lows)
        closes_arr = _to_array(closes)
        volumes_arr = _to_array(volumes)
        timestamps_arr = _to_array(timestamps)

        sr = SupportResistance()
        result = sr.find_levels(
            symbol=symbol,
            highs=highs_arr,
            lows=lows_arr,
            closes=closes_arr,
            volumes=volumes_arr,
            timestamps=timestamps_arr,
            current_price=current_price,
        )

        def _enrich_level(level: Any) -> dict:
            """Convert PriceLevel to dict with distance_pct."""
            d = asdict(level) if hasattr(level, "__dataclass_fields__") else level
            d["distance_pct"] = round(abs(float(d["price"]) - current_price) / current_price * 100, 2)
            return d

        out = {
            "success": True,
            "symbol": result.get("symbol", symbol),
            "current_price": current_price,
            "resistance_levels": [_enrich_level(r) for r in result.get("resistance_levels", [])],
            "support_levels": [_enrich_level(s) for s in result.get("support_levels", [])],
            "round_numbers": result.get("round_numbers", []),
        }

        nr = result.get("nearest_resistance")
        if nr:
            out["nearest_resistance"] = _enrich_level(nr)

        ns = result.get("nearest_support")
        if ns:
            out["nearest_support"] = _enrich_level(ns)

        return out

    except Exception as e:
        logger.error("find_sr_levels failed: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool()
def analyze_symbol(
    symbol: str,
    current_price: float,
    timeframe_data: Dict[str, Dict[str, List[float]]],
) -> Dict[str, Any]:
    """Full multi-timeframe analysis for a trading symbol.

    Runs box detection + S/R levels on each provided timeframe, then
    computes consolidated multi-timeframe signals for entry evaluation.

    This is the primary analysis tool. hermes-agent collects OHLCV data
    for 1d/4h/15m, then calls this once per candidate coin.

    Args:
        symbol: Trading symbol (e.g. "BTC/USDT", "SOL/USDT")
        current_price: Current market price
        timeframe_data: Dict keyed by timeframe string (e.g. "1d", "4h", "15m").
            Each value is a dict with keys: highs, lows, closes, volumes, timestamps
            (each a list of floats). Timestamps are UNIX ms.

    Returns:
        Multi-timeframe analysis with per-TF box/SR data and consolidated signals.
    """
    try:
        tf_results: Dict[str, dict] = {}
        daily_trend = "sideways"

        for tf_key, ohlcv in timeframe_data.items():
            highs = _to_array(ohlcv.get("highs", []))
            lows = _to_array(ohlcv.get("lows", []))
            closes = _to_array(ohlcv.get("closes", []))
            volumes = _to_array(ohlcv.get("volumes", []))
            timestamps = _to_array(ohlcv.get("timestamps", []))

            if len(closes) < 5:
                tf_results[tf_key] = {"trend": "insufficient_data"}
                continue

            trend = _compute_trend(closes)
            if tf_key == "1d":
                daily_trend = trend

            # Box detection
            boxes_result = detect_boxes(
                symbol=symbol,
                timeframe=tf_key,
                highs=highs.tolist(),
                lows=lows.tolist(),
                closes=closes.tolist(),
                volumes=volumes.tolist(),
                timestamps=timestamps.tolist(),
                current_price=current_price,
            )

            # SR levels
            sr_result = find_sr_levels(
                symbol=symbol,
                highs=highs.tolist(),
                lows=lows.tolist(),
                closes=closes.tolist(),
                volumes=volumes.tolist(),
                timestamps=timestamps.tolist(),
                current_price=current_price,
            )

            tf_results[tf_key] = {
                "trend": trend,
                "boxes": boxes_result.get("boxes", []) if boxes_result.get("success") else [],
                "box_count": boxes_result.get("box_count", 0),
                "sr": sr_result if sr_result.get("success") else None,
            }

        # --- multi-timeframe summary ---
        h4 = tf_results.get("4h", {})
        min15 = tf_results.get("15m", {})

        h4_boxes = h4.get("boxes", [])
        min15_boxes = min15.get("boxes", [])

        h4_box = h4_boxes[0] if h4_boxes else None
        min15_box = min15_boxes[0] if min15_boxes else None

        h4_has_box = h4_box is not None
        h4_box_status = h4_box.get("status", "none") if h4_box else "none"
        h4_box_ready = h4_box.get("is_ready", False) if h4_box else False

        # Entry detection on 15m
        min15_has_entry = False
        min15_entry_type = "none"

        if min15_box:
            status = min15_box.get("status", "forming")
            is_ready = min15_box.get("is_ready", False)
            if status in ("breakout_up",):
                min15_has_entry = True
                min15_entry_type = "box_breakout"
            elif is_ready and daily_trend == "up":
                min15_has_entry = True
                min15_entry_type = "box_ready"
            elif status in ("converging",) and daily_trend == "up":
                min15_has_entry = True
                min15_entry_type = "box_bounce"

        # Also check SR support bounce if no box entry
        if not min15_has_entry:
            min15_sr = min15.get("sr")
            if min15_sr and min15_sr.get("nearest_support"):
                ns = min15_sr["nearest_support"]
                dist = ns.get("distance_pct", 100)
                # Within 2% of strong support could be a bounce entry
                if dist < 2.0 and ns.get("strength", 0) >= 2:
                    min15_has_entry = True
                    min15_entry_type = "sr_bounce"

        # Risk/reward from 15m SR
        risk_reward: Dict[str, Any] = {}
        sr_15m = min15.get("sr")
        if sr_15m:
            nr = sr_15m.get("nearest_resistance")
            ns = sr_15m.get("nearest_support")
            if nr:
                risk_reward["nearest_resistance"] = {
                    "price": nr.get("price"),
                    "distance_pct": nr.get("distance_pct"),
                }
            if ns:
                risk_reward["nearest_support"] = {
                    "price": ns.get("price"),
                    "distance_pct": ns.get("distance_pct"),
                }
            risk_reward["upside_room_pct"] = nr.get("distance_pct") if nr else None
            risk_reward["downside_risk_pct"] = ns.get("distance_pct") if ns else None

        # Non-BTC coins always need BTC comparison for resonance check
        is_btc = "BTC" in symbol.upper().split("/")[0]
        needs_btc = not is_btc

        return {
            "success": True,
            "symbol": symbol,
            "current_price": current_price,
            "timeframes": tf_results,
            "multi_tf_summary": {
                "daily_trend": daily_trend,
                "h4_has_box": h4_has_box,
                "h4_box_status": h4_box_status,
                "h4_box_ready": h4_box_ready,
                "min15_has_entry": min15_has_entry,
                "min15_entry_type": min15_entry_type,
                "needs_btc_comparison": needs_btc,
            },
            "risk_reward": risk_reward,
        }

    except Exception as e:
        logger.error("analyze_symbol failed: %s", e)
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
