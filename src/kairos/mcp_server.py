"""
Kairos MCP Server
Model Context Protocol server for Kairos trading analysis.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP

from kairos.analysis.box_pattern import BoxDetector
from kairos.analysis.cycle import CycleDetector
from kairos.analysis.support_resistance import SupportResistance
from kairos.data.data_manager import data_service

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kairos-mcp")

# Initialize MCP server
mcp = FastMCP(
    name="Kairos",
    json_response=True
)

# Global state
class KairosState:
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

@mcp.tool()
def get_market_cycle() -> Dict[str, Any]:
    """
    Get current market cycle phase based on Bit浪浪's spring/summer/autumn/winter theory.
    
    Returns:
        Dictionary with market cycle analysis including phase, confidence, and indicators.
    """
    try:
        logger.info("Fetching market cycle data...")
        
        # 使用数据服务获取BTC价格
        btc_price = data_service.get_price("BTC/USDT")
        btc_volume = data_service.get_volume("BTC/USDT")
        btc_funding = data_service.get_funding_rate("BTC/USDT")
        
        # 计算周期阶段（简化逻辑）
        # 实际应该使用CycleDetector
        if btc_price and btc_price > 60000:
            phase = "spring"
            confidence = 0.75
            description = "行情启动期，百花齐放，开始试仓"
            position_advice = "开始建仓，正常杠杆"
            btc_trend = "up"
            btc_change_30d = 15.2
            btc_change_7d = 5.8
            volatility = 3.2
            volume_trend = "increasing"
        else:
            phase = "winter"
            confidence = 0.6
            description = "下跌震荡期，空仓冬眠，管住手"
            position_advice = "空仓等待，无杠杆"
            btc_trend = "down"
            btc_change_30d = -10.5
            btc_change_7d = -3.2
            volatility = 5.8
            volume_trend = "decreasing"
        
        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "cycle": {
                "phase": phase,
                "confidence": confidence,
                "description": description,
                "position_advice": position_advice,
                "indicators": {
                    "btc_trend": btc_trend,
                    "btc_change_30d": btc_change_30d,
                    "btc_change_7d": btc_change_7d,
                    "volatility": volatility,
                    "volume_trend": volume_trend,
                    "funding_rates_avg": btc_funding or 0.012,
                    "btc_price": btc_price
                }
            },
            "recommendations": [
                "积极寻找右侧跟随大盘突破的机会",
                "建立底仓，准备迎接主升浪",
                "聚焦龙头币和次新币"
            ] if phase == "spring" else [
                "空仓等待，管住手",
                "耐心等待下一个春天",
                "不要妄想在震荡行情中多空双吃"
            ]
        }
    except Exception as e:
        logger.error(f"Error getting market cycle: {e}")
        return {"success": False, "error": str(e)}

@mcp.tool()
def detect_box_pattern(
    symbol: str,
    timeframe: str = "15m",
    lookback: int = 100
) -> Dict[str, Any]:
    """
    Detect box pattern for a symbol.
    
    Args:
        symbol: Trading symbol (e.g., "BTC/USDT")
        timeframe: Timeframe for analysis (1m, 5m, 15m, 1h, 4h, 1d)
        lookback: Number of bars to look back
        
    Returns:
        Box pattern analysis with status and trading implications.
    """
    try:
        logger.info(f"Detecting box pattern for {symbol}...")
        
        # 获取价格数据
        price = data_service.get_price(symbol)
        if not price:
            return {"success": False, "error": f"No data for {symbol}"}
        
        # 使用BoxDetector分析
        # 这里简化处理，实际应该使用真实数据
        high = price * 1.02  # 假设高点
        low = price * 0.98   # 假设低点
        
        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "timeframe": timeframe,
            "lookback": lookback,
            "box_pattern": {
                "detected": True,
                "status": "converging",
                "high": high,
                "low": low,
                "height": high - low,
                "height_pct": ((high - low) / low) * 100,
                "midpoint": (high + low) / 2,
                "touches": {
                    "high": 3,
                    "low": 4,
                    "second_test_high": True,
                    "second_test_low": True
                },
                "convergence_pct": 0.85,
                "volume_declining": True,
                "is_ready": True,
                "start_time": "2026-05-30T10:00:00",
                "end_time": "2026-05-31T14:30:00"
            },
            "trading_implications": {
                "strategy": "等待突破或箱底承接",
                "breakout_signal": "突破上沿且放量确认",
                "pullback_signal": "回踩箱底不破且出现拐点",
                "stop_loss_level": low * 0.99,
                "invalidation": "跌破箱底则箱体失效"
            }
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
    formula: str = "basic"
) -> Dict[str, Any]:
    """
    Scan for potential trading symbols based on Bit浪浪's selection criteria.
    
    Args:
        exchange: Exchange to scan (okx, binance, bybit)
        min_volume: Minimum 24h volume in USDT
        min_oi: Minimum open interest in USDT
        min_age: Minimum listing age in days
        max_volatility: Maximum volatility percentage
        formula: Selection formula (basic, perfect)
        
    Returns:
        List of potential trading symbols with analysis.
    """
    try:
        logger.info(f"Scanning {exchange} for symbols...")
        
        # 获取所有可用的符号
        available_symbols = data_service.get_all_symbols()
        
        candidates = []
        for symbol in available_symbols:
            data = data_service.get_market_data(symbol)
            if data:
                # 检查是否符合筛选条件
                if (data.volume_24h >= min_volume and 
                    data.open_interest >= min_oi):
                    
                    # 计算分数
                    score = 0
                    if formula == "perfect":
                        # 完美公式评分
                        score = 85  # 简化评分
                    
                    candidates.append({
                        "symbol": symbol,
                        "volume_24h": data.volume_24h,
                        "open_interest": data.open_interest,
                        "listing_age_days": 180,  # 假设值
                        "volatility_pct": 4.2,  # 假设值
                        "correlation_with_btc": 0.85,  # 假设值
                        "box_pattern": {
                            "detected": True,
                            "status": "converging",
                            "high": data.price * 1.02,
                            "low": data.price * 0.98,
                            "convergence_pct": 0.82
                        },
                        "signal_strength": "medium",
                        "score": score if formula == "perfect" else None
                    })
        
        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "exchange": exchange,
            "filters": {
                "min_volume": min_volume,
                "min_oi": min_oi,
                "min_age": min_age,
                "max_volatility": max_volatility,
                "formula": formula
            },
            "candidates": candidates,
            "summary": {
                "total_scanned": len(available_symbols),
                "passed_filters": len(candidates),
                "with_box_patterns": len([c for c in candidates if c["box_pattern"]["detected"]]),
                "high_signal": 0,
                "medium_signal": len(candidates),
                "low_signal": 0
            }
        }
    except Exception as e:
        logger.error(f"Error scanning symbols: {e}")
        return {"success": False, "error": str(e)}

@mcp.tool()
def detect_signal(
    symbol: str,
    strategy: str = "box_breakout",
    timeframe: str = "15m"
) -> Dict[str, Any]:
    """
    Detect trading signal for a specific symbol.
    
    Args:
        symbol: Trading symbol (e.g., "BTC/USDT")
        strategy: Signal strategy (box_breakout, small_pullback, large_pullback, double_bottom, divergence)
        timeframe: Timeframe for analysis (1m, 5m, 15m, 1h, 4h, 1d)
        
    Returns:
        Trading signal with entry, stop loss, and targets.
    """
    try:
        logger.info(f"Detecting signal for {symbol} using {strategy} strategy...")
        
        # 获取价格数据
        price = data_service.get_price(symbol)
        if not price:
            return {"success": False, "error": f"No data for {symbol}"}
        
        # 根据策略计算信号
        if strategy == "box_breakout":
            entry_price = price
            stop_loss = price * 0.98
            target1 = price * 1.02
            target2 = price * 1.04
            target3 = price * 1.06
        elif strategy == "small_pullback":
            entry_price = price * 0.99
            stop_loss = price * 0.97
            target1 = price * 1.01
            target2 = price * 1.03
            target3 = price * 1.05
        else:
            entry_price = price
            stop_loss = price * 0.98
            target1 = price * 1.02
            target2 = price * 1.04
            target3 = price * 1.06
        
        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "strategy": strategy,
            "timeframe": timeframe,
            "signal": {
                "detected": True,
                "direction": "long",
                "strength": "high",
                "confidence": 0.85,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "stop_loss_pct": ((price - stop_loss) / price) * 100,
                "targets": [
                    {"price": target1, "pct": ((target1 - price) / price) * 100, "position_pct": 30},
                    {"price": target2, "pct": ((target2 - price) / price) * 100, "position_pct": 30},
                    {"price": target3, "pct": ((target3 - price) / price) * 100, "position_pct": 40}
                ],
                "risk_reward_ratio": 4.0,
                "pattern": {
                    "type": strategy,
                    "description": "箱体收敛充分，放量突破上沿",
                    "box_high": price * 1.02,
                    "box_low": price * 0.98,
                    "convergence_pct": 0.85,
                    "volume_confirmation": True
                }
            },
            "analysis": {
                "market_cycle": "spring",
                "cycle_alignment": True,
                "btc_correlation": 0.82,
                "funding_rate": data_service.get_funding_rate(symbol) or 0.012,
                "open_interest_change": "+5.2%"
            },
            "recommendation": {
                "action": "考虑进场",
                "position_size": "轻仓试多",
                "leverage": "3-5倍",
                "notes": "严格止损，箱体下沿防守"
            }
        }
    except Exception as e:
        logger.error(f"Error detecting signal for {symbol}: {e}")
        return {"success": False, "error": str(e)}

@mcp.tool()
def get_position_status() -> Dict[str, Any]:
    """
    Get current position status.
    
    Returns:
        List of current positions with P&L and risk metrics.
    """
    try:
        logger.info("Getting position status...")
        
        # Mock response
        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "positions": [
                {
                    "symbol": "BTC/USDT",
                    "side": "long",
                    "size_usdt": 10000,
                    "leverage": 5,
                    "entry_price": 67800.0,
                    "current_price": data_service.get_price("BTC/USDT") or 68500.0,
                    "unrealized_pnl_usdt": 515.79,
                    "unrealized_pnl_pct": 5.16,
                    "stop_loss": 67200.0,
                    "take_profit": 71000.0,
                    "liquidation_price": 54240.0,
                    "opened_at": "2026-05-30T14:30:00"
                }
            ],
            "summary": {
                "total_positions": 1,
                "total_exposure_usdt": 50000,
                "total_unrealized_pnl_usdt": 515.79,
                "available_slots": 1,
                "risk_status": "normal"
            }
        }
    except Exception as e:
        logger.error(f"Error getting position status: {e}")
        return {"success": False, "error": str(e)}

@mcp.tool()
def get_risk_status() -> Dict[str, Any]:
    """
    Get overall risk status.
    
    Returns:
        Risk metrics and warnings.
    """
    try:
        logger.info("Getting risk status...")
        
        # Mock response
        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "risk_status": {
                "overall_level": "normal",
                "consecutive_losses": 0,
                "daily_loss_pct": 0.5,
                "max_daily_loss_pct": 3.0,
                "position_concentration": 0.4,
                "max_concentration": 0.6,
                "market_cycle_alignment": True
            },
            "warnings": [],
            "restrictions": [],
            "recommendations": [
                "当前风险水平正常，可以正常交易",
                "注意控制单笔亏损在2.5%以内",
                "保持与市场周期一致的仓位策略"
            ]
        }
    except Exception as e:
        logger.error(f"Error getting risk status: {e}")
        return {"success": False, "error": str(e)}

@mcp.tool()
def get_trade_history(limit: int = 10) -> Dict[str, Any]:
    """
    Get recent trade history.
    
    Args:
        limit: Number of trades to return
        
    Returns:
        List of recent trades with performance metrics.
    """
    try:
        logger.info(f"Getting last {limit} trades...")
        
        # Mock response
        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "trades": [
                {
                    "id": "trade_001",
                    "symbol": "ETH/USDT",
                    "side": "long",
                    "entry_price": 3200.0,
                    "exit_price": 3350.0,
                    "size_usdt": 5000,
                    "leverage": 5,
                    "pnl_usdt": 234.38,
                    "pnl_pct": 4.69,
                    "opened_at": "2026-05-28T10:00:00",
                    "closed_at": "2026-05-29T14:30:00",
                    "strategy": "box_breakout",
                    "market_cycle": "spring"
                }
            ],
            "statistics": {
                "total_trades": 15,
                "winning_trades": 10,
                "losing_trades": 5,
                "win_rate": 0.67,
                "avg_win_pct": 4.2,
                "avg_loss_pct": -2.1,
                "profit_factor": 2.0,
                "max_drawdown_pct": 5.8
            }
        }
    except Exception as e:
        logger.error(f"Error getting trade history: {e}")
        return {"success": False, "error": str(e)}

@mcp.tool()
def get_statistics(strategy: Optional[str] = None) -> Dict[str, Any]:
    """
    Get trading statistics.
    
    Args:
        strategy: Filter by strategy (optional)
        
    Returns:
        Performance statistics and metrics.
    """
    try:
        logger.info("Getting trading statistics...")
        
        # Mock response
        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "period": {
                "start": "2026-05-01",
                "end": "2026-05-31",
                "days": 31
            },
            "performance": {
                "total_pnl_pct": 12.5,
                "total_pnl_usdt": 3750.0,
                "avg_daily_pnl_pct": 0.4,
                "best_day_pct": 3.2,
                "worst_day_pct": -1.8,
                "sharpe_ratio": 1.8,
                "sortino_ratio": 2.5
            },
            "by_strategy": {
                "box_breakout": {
                    "trades": 8,
                    "win_rate": 0.75,
                    "avg_pnl_pct": 3.8,
                    "total_pnl_pct": 8.5
                },
                "small_pullback": {
                    "trades": 5,
                    "win_rate": 0.6,
                    "avg_pnl_pct": 2.1,
                    "total_pnl_pct": 3.2
                },
                "large_pullback": {
                    "trades": 2,
                    "win_rate": 0.5,
                    "avg_pnl_pct": 1.5,
                    "total_pnl_pct": 0.8
                }
            },
            "by_cycle": {
                "spring": {
                    "trades": 12,
                    "win_rate": 0.75,
                    "total_pnl_pct": 10.2
                },
                "summer": {
                    "trades": 3,
                    "win_rate": 0.67,
                    "total_pnl_pct": 2.3
                }
            }
        }
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        return {"success": False, "error": str(e)}

@mcp.tool()
def check_pyramiding(
    symbol: str
) -> Dict[str, Any]:
    """
    Check pyramiding conditions for a symbol.
    
    Args:
        symbol: Trading symbol
        
    Returns:
        Pyramiding analysis with conditions and recommendations.
    """
    try:
        logger.info(f"Checking pyramiding conditions for {symbol}...")
        
        # 获取价格数据
        price = data_service.get_price(symbol)
        if not price:
            return {"success": False, "error": f"No data for {symbol}"}
        
        # Mock response
        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "current_position": {
                "side": "long",
                "entry_price": price * 0.95,
                "current_price": price,
                "unrealized_pnl_pct": 5.4,
                "position_size": 10000
            },
            "pyramiding_conditions": {
                "has_base_position": True,
                "base_position_profitable": True,
                "trend_clear": True,
                "structure_perfect": True,
                "all_conditions_met": True
            },
            "pyramiding_signal": {
                "type": "二次突破",
                "entry_price": price * 1.01,
                "stop_loss": price * 0.98,
                "position_size_pct": 30,
                "risk_reward_ratio": 3.0
            },
            "risk_warning": "加仓风险较高，严格止损"
        }
    except Exception as e:
        logger.error(f"Error checking pyramiding for {symbol}: {e}")
        return {"success": False, "error": str(e)}

@mcp.tool()
def check_exit_signals(
    symbol: str
) -> Dict[str, Any]:
    """
    Check exit signals for a symbol.
    
    Args:
        symbol: Trading symbol
        
    Returns:
        Exit signal analysis with recommendations.
    """
    try:
        logger.info(f"Checking exit signals for {symbol}...")
        
        # 获取价格数据
        price = data_service.get_price(symbol)
        if not price:
            return {"success": False, "error": f"No data for {symbol}"}
        
        # Mock response
        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "current_position": {
                "side": "long",
                "entry_price": price * 0.95,
                "current_price": price,
                "unrealized_pnl_pct": 5.4,
                "position_size": 10000
            },
            "exit_signals": {
                "full_reversal": False,
                "failed_breakout": False,
                "lost_leadership": False,
                "market_top": False,
                "any_signal_detected": False
            },
            "exit_recommendation": {
                "action": "持有",
                "reason": "无出场信号",
                "stop_loss": "上移至成本价",
                "position_adjustment": "无"
            }
        }
    except Exception as e:
        logger.error(f"Error checking exit signals for {symbol}: {e}")
        return {"success": False, "error": str(e)}

@mcp.tool()
def get_market_sentiment() -> Dict[str, Any]:
    """
    Get market sentiment analysis.
    
    Returns:
        Market sentiment with money effect and trend clarity.
    """
    try:
        logger.info("Getting market sentiment...")
        
        # 获取BTC价格来判断市场情绪
        btc_price = data_service.get_price("BTC/USDT")
        
        if btc_price and btc_price > 60000:
            sentiment = "bullish"
            money_effect = "strong"
            trend_clarity = "high"
        else:
            sentiment = "bearish"
            money_effect = "weak"
            trend_clarity = "low"
        
        # Mock response
        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "sentiment": {
                "overall": sentiment,
                "money_effect": money_effect,
                "trend_clarity": trend_clarity,
                "rotation_speed": "slow"
            },
            "indicators": {
                "btc_dominance": 58,
                "altcoin_season_index": 45,
                "fear_greed": 72 if sentiment == "bullish" else 35,
                "funding_rate": 0.015
            },
            "implications": {
                "trading_frequency": "正常" if sentiment == "bullish" else "低",
                "position_strategy": "聚焦龙头" if sentiment == "bullish" else "空仓等待",
                "risk_level": "中等" if sentiment == "bullish" else "高"
            }
        }
    except Exception as e:
        logger.error(f"Error getting market sentiment: {e}")
        return {"success": False, "error": str(e)}

def main():
    """Run the MCP server."""
    print("Starting Kairos MCP Server...")
    print("Available tools:")
    print("  - get_market_cycle: 获取市场周期分析")
    print("  - detect_box_pattern: 检测箱体形态")
    print("  - scan_symbols: 扫描潜在交易币种")
    print("  - detect_signal: 检测交易信号")
    print("  - get_position_status: 获取持仓状态")
    print("  - get_risk_status: 获取风险状态")
    print("  - get_trade_history: 获取交易历史")
    print("  - get_statistics: 获取统计数据")
    print("  - check_pyramiding: 检查加仓条件")
    print("  - check_exit_signals: 检查出场信号")
    print("  - get_market_sentiment: 获取市场氛围")
    print()
    print("Starting server...")
    
    # Run with stdio transport for local integration
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()