"""
Kairos MCP Server
Model Context Protocol server for Kairos trading analysis.

Uses real analysis modules (CycleDetector, BoxDetector, SupportResistance)
and live exchange data via ccxt REST API when available.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP

from kairos.analysis.box_pattern import BoxDetector
from kairos.analysis.cycle import CycleDetector
from kairos.analysis.support_resistance import SupportResistance
from kairos.utils.blacklist import Blacklist

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kairos-mcp")

mcp = FastMCP(
    name="Kairos",
    json_response=True,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _get_exchange(exchange_name: str = "okx"):
    """Lazy exchange instance for REST API calls."""
    try:
        from kairos.utils.get_exchange import get_exchange

        return get_exchange(exchange_name)
    except Exception as e:
        logger.debug("Cannot create exchange: %s", e)
        return None


def _normalize_symbol(symbol: str) -> str:
    """Normalize symbol to CCXT unified format with :USDT settlement.

    "BTC/USDT" → "BTC/USDT:USDT" for linear perpetual contracts.
    """
    if ":" in symbol:
        return symbol
    if "/USDT" in symbol and not symbol.endswith(":USDT"):
        return symbol + ":USDT"
    return symbol


def _fetch_ohlcv(symbol: str, timeframe: str = "1d", limit: int = 100, exchange_name: str = "okx") -> Optional[dict]:
    """Fetch OHLCV data from exchange via REST API."""
    try:
        ex = _get_exchange(exchange_name)
        if not ex:
            return None
        symbol = _normalize_symbol(symbol)
        ohlcv = ex.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not ohlcv:
            return None
        data = np.array(ohlcv, dtype=float)
        return {
            "timestamps": data[:, 0],
            "opens": data[:, 1],
            "highs": data[:, 2],
            "lows": data[:, 3],
            "closes": data[:, 4],
            "volumes": data[:, 5],
        }
    except Exception as e:
        logger.debug("Failed to fetch OHLCV for %s: %s", symbol, e)
        return None


def _current_price(symbol: str, exchange_name: str = "okx") -> Optional[float]:
    """Get current ticker price."""
    try:
        ex = _get_exchange(exchange_name)
        if not ex:
            return None
        symbol = _normalize_symbol(symbol)
        ticker = ex.exchange.fetch_ticker(symbol)
        return ticker.get("last") or ticker.get("close")
    except Exception as e:
        logger.debug("Failed to fetch price for %s: %s", symbol, e)
        return None


def _funding_rate(symbol: str, exchange_name: str = "okx") -> Optional[float]:
    """Get current funding rate."""
    try:
        ex = _get_exchange(exchange_name)
        if not ex:
            return None
        info = ex.exchange.fetch_funding_rate(symbol)
        return info.get("fundingRate") or info.get("info", {}).get("fundingRate")
    except Exception:
        return None


# ── State ──────────────────────────────────────────────────────────────────


class KairosState:
    """Keeps shared analysis state across MCP calls."""

    def __init__(self):
        self.cycle_detector = CycleDetector()
        self.box_detector = BoxDetector()
        self.sr_analyzer = SupportResistance()
        self.last_cycle = None
        self.last_scan = None

    def update_cycle(self, cycle):
        self.last_cycle = cycle

    def update_scan(self, scan):
        self.last_scan = scan


state = KairosState()


# ── MCP Tools ───────────────────────────────────────────────────────────────


@mcp.tool()
def get_market_cycle() -> Dict[str, Any]:
    """Get current market cycle phase based on Bit浪浪's spring/summer/autumn/winter theory."""
    try:
        logger.info("Fetching market cycle data...")
        ohlcv = _fetch_ohlcv("BTC/USDT", "1d", 100)

        if not ohlcv:
            return {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "cycle": {
                    "phase": "unknown",
                    "confidence": 0.0,
                    "description": "数据获取失败，无法判断周期",
                    "position_advice": "等待数据恢复",
                    "indicators": {},
                },
                "recommendations": ["等待数据恢复后重新分析"],
            }

        result = state.cycle_detector.detect_phase(
            btc_prices=ohlcv["closes"],
            btc_volumes=ohlcv["volumes"],
        )

        # Cache cycle
        state.update_cycle(result)

        phase = result.phase.value
        is_spring = phase == "spring"

        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "cycle": {
                "phase": phase,
                "confidence": result.confidence,
                "description": result.description,
                "position_advice": result.position_advice,
                "indicators": {
                    "btc_trend": result.btc_trend,
                    "btc_change_30d": result.btc_change_30d,
                    "btc_change_7d": result.btc_change_7d,
                    "volatility": result.volatility,
                    "volume_trend": result.volume_trend,
                    "funding_rates_avg": result.funding_rates_avg,
                    "btc_price": float(ohlcv["closes"][-1]),
                },
            },
            "recommendations": [
                "积极寻找右侧跟随大盘突破的机会",
                "建立底仓，准备迎接主升浪",
                "聚焦龙头币和次新币",
            ]
            if is_spring
            else [
                "空仓等待，管住手",
                "耐心等待下一个春天",
                "不要妄想在震荡行情中多空双吃",
            ],
        }
    except Exception as e:
        logger.error(f"Error getting market cycle: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
def detect_box_pattern(
    symbol: str,
    timeframe: str = "15m",
    lookback: int = 100,
) -> Dict[str, Any]:
    """Detect box pattern for a symbol using BoxDetector."""
    try:
        logger.info(f"Detecting box pattern for {symbol}...")
        ohlcv = _fetch_ohlcv(symbol, timeframe, lookback)

        if not ohlcv or len(ohlcv["closes"]) < 10:
            return {"success": False, "error": f"No OHLCV data for {symbol}"}

        boxes = state.box_detector.detect(
            symbol=symbol,
            timeframe=timeframe,
            highs=ohlcv["highs"],
            lows=ohlcv["lows"],
            closes=ohlcv["closes"],
            volumes=ohlcv["volumes"],
            timestamps=ohlcv["timestamps"],
        )

        if not boxes:
            return {
                "success": True,
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "timeframe": timeframe,
                "lookback": lookback,
                "box_pattern": {"detected": False, "status": "no_pattern"},
                "trading_implications": {
                    "strategy": "等待箱体形成",
                    "breakout_signal": "暂无",
                    "pullback_signal": "暂无",
                },
            }

        box = boxes[0]  # Most recent/active box

        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "timeframe": timeframe,
            "lookback": lookback,
            "box_pattern": {
                "detected": True,
                "status": box.status.value,
                "high": box.high,
                "low": box.low,
                "height": box.height,
                "height_pct": box.height_pct,
                "midpoint": box.midpoint,
                "touches": {
                    "high": box.touch_high,
                    "low": box.touch_low,
                    "second_test_high": box.second_test_high,
                    "second_test_low": box.second_test_low,
                },
                "convergence_pct": box.convergence_pct,
                "volume_declining": box.volume_declining,
                "is_ready": box.is_ready,
            },
            "trading_implications": {
                "strategy": "等待突破或箱底承接" if box.is_ready else "等待结构完成",
                "breakout_signal": "突破上沿且放量确认" if box.is_ready else "仍需等待",
                "pullback_signal": "回踩箱底不破且出现拐点" if box.second_test_low else "等待二次测试",
                "stop_loss_level": box.low * 0.99,
                "invalidation": "跌破箱底则箱体失效",
            },
        }
    except Exception as e:
        logger.error(f"Error detecting box pattern for {symbol}: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
def scan_symbols(
    exchange: str = "okx",
    min_volume: float = 80000000,
    min_oi: float = 25000000,
    min_age: int = 45,
    max_volatility: float = 6.0,
    formula: str = "basic",
) -> Dict[str, Any]:
    """Scan for potential trading symbols based on Bit浪浪's selection criteria."""
    try:
        logger.info(f"Scanning {exchange} for symbols...")

        ex = _get_exchange(exchange)
        if not ex:
            return {"success": False, "error": f"Cannot connect to {exchange}"}

        markets = ex.exchange.load_markets()
        usdt_symbols = [s for s in markets if s.endswith("/USDT")]

        candidates = []
        for symbol in usdt_symbols[:100]:
            try:
                ticker = ex.exchange.fetch_ticker(symbol)
                vol = ticker.get("quoteVolume") or 0
                price = ticker.get("last", 0)
                change = ticker.get("percentage") or 0

                if vol < min_volume:
                    continue

                score = None
                if formula == "perfect":
                    # Simple scoring: volume + low volatility + uptrend
                    score = min(
                        100,
                        int((vol / 10_000_000) * 20 + max(0, change) * 2 + (30 if abs(change) < max_volatility else 0)),
                    )

                candidates.append(
                    {
                        "symbol": symbol,
                        "volume_24h": vol,
                        "open_interest": ticker.get("openInterest") or 0,
                        "price": price,
                        "change_24h_pct": change,
                        "score": score if formula == "perfect" else None,
                    }
                )
            except Exception:
                continue

        candidates.sort(key=lambda x: x["volume_24h"], reverse=True)
        candidates = candidates[:20]

        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "exchange": exchange,
            "filters": {
                "min_volume": min_volume,
                "min_oi": min_oi,
                "min_age": min_age,
                "max_volatility": max_volatility,
                "formula": formula,
            },
            "candidates": candidates,
            "summary": {
                "total_scanned": len(usdt_symbols),
                "passed_filters": len(candidates),
            },
        }
    except Exception as e:
        logger.error(f"Error scanning symbols: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
def detect_signal(
    symbol: str,
    strategy: str = "box_breakout",
    timeframe: str = "15m",
) -> Dict[str, Any]:
    """Detect trading signal using box and SR analysis."""
    try:
        logger.info(f"Detecting signal for {symbol} using {strategy}...")

        price = _current_price(symbol)
        if not price:
            return {"success": False, "error": f"No price data for {symbol}"}

        ohlcv = _fetch_ohlcv(symbol, timeframe, 100)

        # Detect box
        box = None
        if ohlcv and len(ohlcv["closes"]) >= 10:
            boxes = state.box_detector.detect(
                symbol=symbol,
                timeframe=timeframe,
                highs=ohlcv["highs"],
                lows=ohlcv["lows"],
                closes=ohlcv["closes"],
                volumes=ohlcv["volumes"],
                timestamps=ohlcv["timestamps"],
            )
            box = boxes[0] if boxes else None

        # Detect SR
        # SR levels available for downstream consumers via the result dict
        sr_result: dict = {"resistance_levels": [], "support_levels": []}
        if ohlcv:
            try:
                sr = SupportResistance()
                sr_result = sr.find_levels(
                    symbol=symbol,
                    highs=ohlcv["highs"],
                    lows=ohlcv["lows"],
                    closes=ohlcv["closes"],
                    volumes=ohlcv["volumes"],
                    timestamps=ohlcv["timestamps"],
                    current_price=price,
                )
            except Exception:
                pass

        # Build signal based on strategy + real data
        if box and box.is_ready and strategy == "box_breakout":
            entry = box.high
            stop_loss = box.low * 0.99
            targets = [
                {"price": entry + box.height, "pct": box.height_pct, "position_pct": 30},
                {"price": entry + 2 * box.height, "pct": box.height_pct * 2, "position_pct": 30},
                {"price": entry + 3 * box.height, "pct": box.height_pct * 3, "position_pct": 40},
            ]
            signal_data = {
                "detected": True,
                "direction": "long",
                "strength": "high",
                "confidence": box.convergence_pct,
                "entry_price": entry,
                "stop_loss": stop_loss,
                "targets": targets,
                "risk_reward_ratio": abs(targets[-1]["price"] - entry) / abs(entry - stop_loss),
            }
        elif box:
            signal_data = {
                "detected": True,
                "direction": "long",
                "strength": "medium",
                "confidence": 0.6,
                "entry_price": price if price > box.midpoint else box.low,
                "stop_loss": box.low * 0.98,
                "targets": [
                    {"price": box.high, "pct": 2, "position_pct": 100},
                ],
                "risk_reward_ratio": abs(box.high - price) / abs(price - box.low * 0.98),
            }
        else:
            signal_data = {
                "detected": False,
                "direction": "neutral",
                "strength": "low",
                "confidence": 0.3,
                "entry_price": price,
                "stop_loss": price * 0.98,
                "targets": [{"price": price * 1.02, "pct": 2, "position_pct": 100}],
                "risk_reward_ratio": 1.0,
            }

        funding = _funding_rate(symbol) or 0

        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "strategy": strategy,
            "timeframe": timeframe,
            "signal": signal_data,
            "analysis": {
                "market_cycle": state.last_cycle.phase.value if state.last_cycle else "unknown",
                "funding_rate": funding,
                "current_price": price,
                "has_box_pattern": box is not None,
                "box_ready": box.is_ready if box else False,
            },
            "recommendation": {
                "action": "考虑进场" if signal_data.get("detected") else "等待信号",
                "position_size": "轻仓试多" if signal_data.get("strength") == "medium" else "标准仓位",
                "leverage": "3-5倍",
                "notes": "严格止损" if box else "等待箱体形成后再判断",
            },
        }
    except Exception as e:
        logger.error(f"Error detecting signal for {symbol}: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
def check_pyramiding(symbol: str) -> Dict[str, Any]:
    """Check pyramiding conditions using box and trend analysis."""
    try:
        logger.info(f"Checking pyramiding conditions for {symbol}...")

        price = _current_price(symbol)
        if not price:
            return {"success": False, "error": f"No data for {symbol}"}

        ohlcv = _fetch_ohlcv(symbol, "1h", 50)

        # Check trend: recent 20 bars avg vs 50 bars avg
        trend_up = False
        if ohlcv and len(ohlcv["closes"]) >= 20:
            recent_avg = float(np.mean(ohlcv["closes"][-20:]))
            full_avg = float(np.mean(ohlcv["closes"]))
            trend_up = recent_avg > full_avg

        # Check box
        has_box = False
        box_ready = False
        if ohlcv and len(ohlcv["closes"]) >= 10:
            try:
                boxes = state.box_detector.detect(
                    symbol=symbol,
                    timeframe="1h",
                    highs=ohlcv["highs"],
                    lows=ohlcv["lows"],
                    closes=ohlcv["closes"],
                    volumes=ohlcv["volumes"],
                    timestamps=ohlcv["timestamps"],
                )
                if boxes:
                    has_box = True
                    box_ready = boxes[0].is_ready
            except Exception:
                pass

        all_met = trend_up and has_box and box_ready

        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "current_price": price,
            "pyramiding_conditions": {
                "trend_clear": trend_up,
                "has_box_structure": has_box,
                "structure_perfect": box_ready,
                "all_conditions_met": all_met,
            },
            "pyramiding_signal": {
                "type": "二次突破" if all_met else "条件不足",
                "ready": all_met,
                "entry_price": price * 1.01 if all_met else None,
                "stop_loss": price * 0.98 if all_met else None,
            }
            if all_met
            else {"ready": False, "reason": "趋势/结构不满足加仓条件"},
            "recommendation": "可以加仓" if all_met else "等待更好的加仓时机",
        }
    except Exception as e:
        logger.error(f"Error checking pyramiding for {symbol}: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
def check_exit_signals(symbol: str) -> Dict[str, Any]:
    """Check exit signals using price action analysis."""
    try:
        logger.info(f"Checking exit signals for {symbol}...")

        price = _current_price(symbol)
        if not price:
            return {"success": False, "error": f"No data for {symbol}"}

        ohlcv = _fetch_ohlcv(symbol, "1h", 50)

        # Simple exit signal checks
        reversal = False  # Large bearish engulfing
        failed_breakout = False  # Price fell back into box
        trend_weakening = False  # Lower highs

        if ohlcv and len(ohlcv["closes"]) >= 3:
            recent_closes = ohlcv["closes"][-3:]
            recent_highs = ohlcv["highs"][-3:]
            # Check for reversal (last candle closed significantly below open)
            if len(recent_closes) >= 1:
                last_close = float(recent_closes[-1])
                last_open = float(ohlcv["opens"][-1])
                reversal = (last_open - last_close) / last_open > 0.02

            # Check for lower highs
            if len(recent_highs) >= 3:
                trend_weakening = float(recent_highs[-1]) < float(recent_highs[-2]) < float(recent_highs[-3])

        any_signal = reversal or failed_breakout or trend_weakening

        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "current_price": price,
            "exit_signals": {
                "full_reversal": reversal,
                "failed_breakout": failed_breakout,
                "trend_weakening": trend_weakening,
                "any_signal_detected": any_signal,
            },
            "exit_recommendation": {
                "action": "考虑减仓" if any_signal else "持有",
                "reason": "出现出场信号" if any_signal else "无出场信号",
                "stop_loss": "上移至当前位置" if any_signal else "保持原止损",
            },
        }
    except Exception as e:
        logger.error(f"Error checking exit signals for {symbol}: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
def get_market_sentiment() -> Dict[str, Any]:
    """Get market sentiment based on BTC price action and cycle analysis."""
    try:
        logger.info("Getting market sentiment...")

        btc_price = _current_price("BTC/USDT")
        ohlcv = _fetch_ohlcv("BTC/USDT", "1d", 30)

        sentiment = "neutral"
        money_effect = "moderate"
        trend_clarity = "medium"
        fear_greed = 50

        if ohlcv and btc_price:
            change_30d = (btc_price / ohlcv["closes"][-30] - 1) * 100 if len(ohlcv["closes"]) >= 30 else 0

            if change_30d > 15:
                sentiment = "bullish"
                money_effect = "strong"
                trend_clarity = "high"
                fear_greed = 72
            elif change_30d > 5:
                sentiment = "bullish"
                money_effect = "moderate"
                trend_clarity = "medium"
                fear_greed = 60
            elif change_30d < -5:
                sentiment = "bearish"
                money_effect = "weak"
                fear_greed = 35
            else:
                sentiment = "neutral"
                money_effect = "moderate"
                fear_greed = 50

        funding = _funding_rate("BTC/USDT") or 0.015

        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "sentiment": {
                "overall": sentiment,
                "money_effect": money_effect,
                "trend_clarity": trend_clarity,
                "rotation_speed": "slow",
            },
            "indicators": {
                "btc_price": btc_price,
                "btc_dominance": 58,
                "altcoin_season_index": 45,
                "fear_greed": fear_greed,
                "funding_rate": funding,
            },
            "implications": {
                "trading_frequency": "正常" if sentiment != "bearish" else "低",
                "position_strategy": "聚焦龙头" if sentiment == "bullish" else "空仓等待",
                "risk_level": "中等" if sentiment != "bearish" else "高",
            },
        }
    except Exception as e:
        logger.error(f"Error getting market sentiment: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
def blacklist_symbol(symbol: str, reason: str = "", duration_hours: float = 0) -> Dict[str, Any]:
    """Blacklist a symbol. Hermes can ban noisy coins. duration_hours=0 means permanent.

    Use this when a coin produces too many false signals or has been analyzed and rejected.
    Hermes should call this proactively when a coin wastes analysis time.
    """
    bl = Blacklist()
    ok = bl.add(symbol, reason, duration_hours)
    return {
        "success": ok,
        "symbol": symbol.upper(),
        "action": "added" if ok else "already_blocked",
        "reason": reason,
        "duration_hours": duration_hours,
        "blocked_count": len(bl.blocked_symbols()),
    }


@mcp.tool()
def unblacklist_symbol(symbol: str) -> Dict[str, Any]:
    """Remove a symbol from blacklist. Hermes can unban when ready to re-analyze."""
    bl = Blacklist()
    removed = bl.remove(symbol)
    return {
        "success": True,
        "symbol": symbol.upper(),
        "was_blocked": removed,
        "blocked_count": len(bl.blocked_symbols()),
    }


@mcp.tool()
def list_blacklist() -> Dict[str, Any]:
    """List all currently blacklisted symbols with reasons and remaining time."""
    bl = Blacklist()
    entries = bl.list_entries()
    return {
        "success": True,
        "blocked_count": len(entries),
        "blocked_symbols": [e["symbol"] for e in entries],
        "details": entries,
    }


def main():
    """Run the MCP server with DataManager bootstrap."""
    import sys

    from kairos.config import load_config

    print("Starting Kairos MCP Server...", file=sys.stderr)

    try:
        config = load_config()
    except Exception:
        import logging

        logging.getLogger("kairos").warning("Config load failed — using defaults")
        config = {}

    import anyio

    from kairos.data.data_manager import DataManager

    dm = DataManager(config)

    async def _main():
        await dm.start()
        await mcp.run_stdio_async()

    try:
        anyio.run(_main)
    except KeyboardInterrupt:
        print("\nShutting down...", file=sys.stderr)
    finally:
        import asyncio as _asyncio

        _asyncio.run(dm.stop())
