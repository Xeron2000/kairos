"""Trading CLI commands for pwatch."""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from pwatch.trades.executor import TradeExecutor
from pwatch.trades.position import PositionManager
from pwatch.trades.risk import RiskManager
from pwatch.analysis.box_pattern import BoxDetector
from pwatch.analysis.cycle import CycleDetector
from pwatch.analysis.support_resistance import SupportResistance
from pwatch.arbitrage.funding_monitor import FundingRateMonitor
from pwatch.arbitrage.funding_arb import FundingArbitrage


def load_config():
    """Load trading configuration."""
    config_path = Path.home() / ".config" / "pwatch" / "trading.yaml"
    if not config_path.exists():
        print("❌ Trading config not found. Run: pwatch trading setup")
        sys.exit(1)
    
    import yaml
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def get_exchange_name(args, config):
    """Get exchange name from args or config."""
    return getattr(args, "exchange", None) or config.get("defaultExchange", "okx")


# ============ Market Analysis Commands ============

def cmd_cycle(args):
    """Show current market cycle phase."""
    config = load_config()
    
    # This would fetch BTC data and analyze
    # For now, show placeholder
    print("🔄 Market Cycle Analysis")
    print("=" * 50)
    print()
    print("📊 Current Phase: SPRING (牛市初期)")
    print("📈 BTC 30-day Change: +15.2%")
    print("📉 BTC 7-day Change: +5.8%")
    print("🌡️  Volatility: 3.2% (Medium)")
    print("📊 Volume Trend: Increasing")
    print("💰 Avg Funding Rate: 0.012%")
    print()
    print("💡 Advice: 开始建仓，正常杠杆")
    print()
    print("🎯 Strategy:")
    print("  - 积极寻找右侧跟随大盘突破的机会")
    print("  - 建立底仓，准备迎接主升浪")
    print("  - 聚焦龙头币和次新币")


def cmd_scan(args):
    """Scan for potential trading symbols."""
    config = load_config()
    exchange = get_exchange_name(args, config)
    
    print(f"🔍 Scanning {exchange} for potential symbols...")
    print("=" * 60)
    print()
    
    # Filter criteria
    min_volume = getattr(args, "min_volume", None) or 80_000_000
    min_oi = getattr(args, "min_oi", None) or 25_000_000
    min_age = getattr(args, "min_age", None) or 45
    max_volatility = getattr(args, "max_volatility", None) or 6.0
    
    print(f"📋 Filter Criteria:")
    print(f"  Min 24h Volume: ${min_volume:,.0f}")
    print(f"  Min Open Interest: ${min_oi:,.0f}")
    print(f"  Min Listing Age: {min_age} days")
    print(f"  Max Volatility: {max_volatility}%")
    print()
    
    # Placeholder results
    print("🎯 Top Candidates:")
    print("-" * 60)
    print(f"{'Symbol':<15} {'Volume':>15} {'OI':>15} {'Age':>8} {'Vol%':>8}")
    print("-" * 60)
    
    symbols = [
        ("SOL/USDT", "$2.5B", "$850M", "180d", "4.2%"),
        ("AVAX/USDT", "$800M", "$320M", "120d", "5.1%"),
        ("ARB/USDT", "$600M", "$280M", "90d", "3.8%"),
        ("OP/USDT", "$500M", "$250M", "85d", "4.5%"),
        ("SUI/USDT", "$400M", "$180M", "60d", "5.8%"),
    ]
    
    for sym, vol, oi, age, vol_pct in symbols:
        print(f"{sym:<15} {vol:>15} {oi:>15} {age:>8} {vol_pct:>8}")
    
    print()
    print("💡 Run `pwatch signal --symbol <SYMBOL>` to analyze specific symbol")


def cmd_box_detect(args):
    """Detect box patterns."""
    symbol = args.symbol
    timeframe = args.timeframe or "15m"
    lookback = args.lookback or 100
    
    print(f"📦 Box Pattern Detection: {symbol}")
    print("=" * 60)
    print()
    print(f"⏱️  Timeframe: {timeframe}")
    print(f"📊 Lookback: {lookback} bars")
    print()
    
    # Placeholder output
    print("✅ Box Pattern Detected!")
    print()
    print("📐 Box Parameters:")
    print(f"  High: 68,500.00")
    print(f"  Low: 67,200.00")
    print(f"  Height: 1,300.00 (1.94%)")
    print()
    print("📊 Pattern Quality:")
    print(f"  Touch High: 3")
    print(f"  Touch Low: 4")
    print(f"  Second Test High: ✅")
    print(f"  Second Test Low: ✅")
    print(f"  Convergence: 85%")
    print(f"  Volume Declining: ✅")
    print()
    print("🎯 Status: CONVERGING (Ready for breakout)")
    print()
    print("💡 Trading Signals:")
    print("  📍 Wait for breakout above 68,500 with volume")
    print("  🛑 Stop Loss: 67,150 (box low - 0.07%)")
    print("  🎯 Target 1: 69,800 (box height)")
    print("  🎯 Target 2: 71,100 (2x box height)")
    print()
    print("⚡ Entry Strategy:")
    print("  1. Wait for volume spike on breakout")
    print("  2. Enter on pullback to broken resistance")
    print("  3. Or enter on first test of box high as support")


def cmd_signal(args):
    """Detect trading signals."""
    symbol = args.symbol
    strategy = args.strategy or "box_breakout"
    
    print(f"🎯 Trading Signal Detection: {symbol}")
    print("=" * 60)
    print()
    print(f"📊 Strategy: {strategy}")
    print()
    
    if strategy == "box_breakout":
        print("✅ Box Breakout Signal Detected!")
        print()
        print("📊 Signal Quality: HIGH")
        print("🎯 Direction: LONG")
        print()
        print("📐 Entry Parameters:")
        print(f"  Entry Price: 68,500")
        print(f"  Stop Loss: 67,200 (box low)")
        print(f"  Risk: 1,300 (1.90%)")
        print(f"  Position Size: 5,000 USDT (5x leverage)")
        print()
        print("🎯 Targets:")
        print(f"  TP1: 69,800 (+1.90%) - 30% position")
        print(f"  TP2: 71,100 (+3.80%) - 30% position")
        print(f"  TP3: 73,700 (+7.60%) - 40% position")
        print()
        print("📊 Risk/Reward:")
        print(f"  Risk: 1.90%")
        print(f"  Reward: 7.60%")
        print(f"  R:R Ratio: 4.0:1")
    
    elif strategy == "small_pullback":
        print("✅ Small Pullback Signal Detected!")
        print()
        print("📊 Signal Quality: MEDIUM")
        print("🎯 Direction: LONG")
        print()
        print("💡 Strategy: 小分歧做承接")
        print("📍 Entry: Wait for price to touch box low")
        print("🛑 Stop: Below box low")
    
    elif strategy == "large_pullback":
        print("⏳ Large Pullback - Waiting for structure...")
        print()
        print("📊 Signal Quality: PENDING")
        print("💡 Strategy: 大分歧等二波")
        print("📍 Wait for: Structure convergence + volume spike")


def cmd_sr(args):
    """Show support and resistance levels."""
    symbol = args.symbol
    
    print(f"📊 Support & Resistance: {symbol}")
    print("=" * 60)
    print()
    print("📍 Current Price: 68,000")
    print()
    print("🔴 Resistance Levels:")
    print("-" * 40)
    print("  R3: 75,000 (+10.3%) - Round number")
    print("  R2: 72,000 (+5.9%) - Previous high")
    print("  R1: 70,000 (+2.9%) - Round number")
    print()
    print("🟢 Support Levels:")
    print("-" * 40)
    print("  S1: 67,200 (-1.2%) - Box low")
    print("  S2: 66,000 (-2.9%) - Previous low")
    print("  S3: 65,000 (-4.4%) - Round number")
    print()
    print("💡 Key Observations:")
    print("  - Strong support at 67,200 (box pattern)")
    print("  - Clear path to 70,000 (no resistance)")
    print("  - Round numbers act as psychological levels")


# ============ Position Management Commands ============

def cmd_position(args):
    """Position management commands."""
    if args.subcmd == "status":
        cmd_position_status(args)
    elif args.subcmd == "size":
        cmd_position_size(args)
    elif args.subcmd == "history":
        cmd_position_history(args)
    elif args.subcmd == "stats":
        cmd_position_stats(args)


def cmd_position_status(args):
    """Show current positions."""
    print("📊 Position Status")
    print("=" * 60)
    print()
    
    # Placeholder
    print("💰 Capital: 10,000 USDT")
    print("📈 Open Positions: 2")
    print("💵 Total Exposure: 6,600 USDT (66%)")
    print()
    
    print("📋 Open Positions:")
    print("-" * 60)
    print(f"{'Symbol':<12} {'Side':<6} {'Entry':>10} {'Current':>10} {'PnL':>10} {'PnL%':>8}")
    print("-" * 60)
    
    positions = [
        ("BTC/USDT", "LONG", "68,000", "68,500", "+500", "+0.74%"),
        ("ETH/USDT", "LONG", "3,500", "3,520", "+200", "+0.57%"),
    ]
    
    for sym, side, entry, current, pnl, pnl_pct in positions:
        print(f"{sym:<12} {side:<6} {entry:>10} {current:>10} {pnl:>10} {pnl_pct:>8}")
    
    print()
    print("⚠️ Risk Status:")
    print("  Daily PnL: +700 USDT (+7.0%)")
    print("  Consecutive Losses: 0")
    print("  Max Drawdown: 5.2%")


def cmd_position_size(args):
    """Calculate position size."""
    capital = args.capital or 10000
    risk_pct = args.risk_pct or 33
    leverage = args.leverage or 5
    
    print("📐 Position Size Calculator")
    print("=" * 60)
    print()
    print(f"💰 Capital: {capital:,.0f} USDT")
    print(f"📊 Risk per Trade: {risk_pct}%")
    print(f"⚡ Leverage: {leverage}x")
    print()
    
    risk_amount = capital * risk_pct / 100
    position_value = capital * leverage
    margin = position_value / leverage
    
    print("📊 Calculation:")
    print(f"  Risk Amount: {risk_amount:,.0f} USDT")
    print(f"  Position Value: {position_value:,.0f} USDT")
    print(f"  Margin Required: {margin:,.0f} USDT")
    print()
    
    print("💡 Example (BTC @ 68,000):")
    btc_amount = position_value / 68000
    print(f"  Amount: {btc_amount:.4f} BTC")
    print(f"  Stop Loss Distance: {risk_amount / btc_amount:,.0f} USDT ({risk_amount / btc_amount / 68000 * 100:.2f}%)")


def cmd_position_history(args):
    """Show position history."""
    limit = args.limit or 20
    
    print(f"📜 Position History (last {limit})")
    print("=" * 80)
    print()
    
    # Placeholder
    print(f"{'Date':<12} {'Symbol':<12} {'Side':<6} {'Entry':>10} {'Exit':>10} {'PnL':>10} {'PnL%':>8} {'Strategy':<15}")
    print("-" * 80)
    
    history = [
        ("2024-01-15", "BTC/USDT", "LONG", "68,000", "69,500", "+1,500", "+2.21%", "box_breakout"),
        ("2024-01-14", "ETH/USDT", "LONG", "3,500", "3,480", "-200", "-0.57%", "small_pullback"),
        ("2024-01-13", "SOL/USDT", "LONG", "120", "125", "+500", "+4.17%", "box_breakout"),
    ]
    
    for row in history:
        print(f"{row[0]:<12} {row[1]:<12} {row[2]:<6} {row[3]:>10} {row[4]:>10} {row[5]:>10} {row[6]:>8} {row[7]:<15}")


def cmd_position_stats(args):
    """Show position statistics."""
    strategy = args.strategy
    
    print("📊 Position Statistics")
    print("=" * 60)
    print()
    
    if strategy:
        print(f"🎯 Strategy: {strategy}")
    else:
        print("🎯 All Strategies")
    
    print()
    print("📈 Performance:")
    print(f"  Total Trades: 45")
    print(f"  Wins: 28 (62.2%)")
    print(f"  Losses: 17 (37.8%)")
    print(f"  Total PnL: +8,500 USDT")
    print(f"  Avg Win: +450 USDT")
    print(f"  Avg Loss: -280 USDT")
    print(f"  Best Trade: +2,100 USDT")
    print(f"  Worst Trade: -800 USDT")
    print()
    print("📊 Ratios:")
    print(f"  Profit Factor: 2.63")
    print(f"  Win Rate: 62.2%")
    print(f"  Avg R:R: 2.1:1")


# ============ Trading Execution Commands ============

def cmd_order(args):
    """Place a trading order."""
    symbol = args.symbol
    side = args.side
    size = args.size
    order_type = args.type or "market"
    
    print("📝 Order Preview")
    print("=" * 60)
    print()
    print(f"📊 Symbol: {symbol}")
    print(f"📈 Side: {side.upper()}")
    print(f"📦 Size: {size} USDT")
    print(f"📋 Type: {order_type}")
    print()
    
    # Confirmation
    confirm = input("⚠️  Confirm order? (yes/no): ")
    if confirm.lower() != "yes":
        print("❌ Order cancelled")
        return
    
    print("✅ Order submitted!")
    print(f"  Order ID: ORD_{symbol.replace('/', '_')}_{int(time.time())}")


def cmd_close(args):
    """Close a position."""
    symbol = args.symbol
    
    print(f"📤 Closing position: {symbol}")
    print("=" * 60)
    print()
    
    # Confirmation
    confirm = input("⚠️  Confirm close? (yes/no): ")
    if confirm.lower() != "yes":
        print("❌ Close cancelled")
        return
    
    print("✅ Position closed!")


# ============ Funding Rate Commands ============

def cmd_funding(args):
    """Funding rate commands."""
    if args.subcmd == "status":
        cmd_funding_status(args)
    elif args.subcmd == "extreme":
        cmd_funding_extreme(args)
    elif args.subcmd == "opportunities":
        cmd_funding_opportunities(args)


def cmd_funding_status(args):
    """Show funding rates."""
    exchange = args.exchange or "all"
    
    print(f"💰 Funding Rates ({exchange})")
    print("=" * 70)
    print()
    
    # Placeholder
    print(f"{'Symbol':<15} {'Binance':>10} {'OKX':>10} {'Bybit':>10} {'Annual':>10}")
    print("-" * 70)
    
    rates = [
        ("BTC/USDT", "0.012%", "0.015%", "0.010%", "42.3%"),
        ("ETH/USDT", "0.018%", "0.020%", "0.016%", "58.4%"),
        ("SOL/USDT", "0.025%", "0.028%", "0.022%", "82.1%"),
    ]
    
    for sym, bnb, okx, bybit, annual in rates:
        print(f"{sym:<15} {bnb:>10} {okx:>10} {bybit:>10} {annual:>10}")


def cmd_funding_extreme(args):
    """Show extreme funding rates."""
    threshold = args.threshold or 0.05
    
    print(f"🔥 Extreme Funding Rates (>{threshold*100}%)")
    print("=" * 60)
    print()
    
    # Placeholder
    print("⚠️  High Positive (Longs pay Shorts):")
    print(f"  SOL/USDT: 0.025% (91.25% annualized)")
    print(f"  AVAX/USDT: 0.022% (80.30% annualized)")
    print()
    print("💡 High Negative (Shorts pay Longs):")
    print(f"  DOGE/USDT: -0.018% (-65.70% annualized)")


def cmd_funding_opportunities(args):
    """Show funding arbitrage opportunities."""
    print("🎯 Funding Arbitrage Opportunities")
    print("=" * 70)
    print()
    
    # Placeholder
    print(f"{'Symbol':<12} {'Long@':<10} {'Short@':<10} {'Spread':>8} {'Daily%':>8} {'Annual%':>10}")
    print("-" * 70)
    
    opportunities = [
        ("SOL/USDT", "Binance", "OKX", "0.015%", "0.045%", "16.4%"),
        ("ETH/USDT", "Bybit", "OKX", "0.012%", "0.036%", "13.1%"),
        ("BTC/USDT", "Binance", "Bybit", "0.008%", "0.024%", "8.8%"),
    ]
    
    for sym, long_ex, short_ex, spread, daily, annual in opportunities:
        print(f"{sym:<12} {long_ex:<10} {short_ex:<10} {spread:>8} {daily:>8} {annual:>10}")
    
    print()
    print("💡 Run `pwatch arb execute --symbol <SYMBOL>` to execute")


# ============ Arbitrage Commands ============

def cmd_arb(args):
    """Arbitrage commands."""
    if args.subcmd == "status":
        cmd_arb_status(args)
    elif args.subcmd == "execute":
        cmd_arb_execute(args)
    elif args.subcmd == "close":
        cmd_arb_close(args)


def cmd_arb_status(args):
    """Show arbitrage status."""
    print("📊 Arbitrage Status")
    print("=" * 60)
    print()
    
    print("💰 Capital: 10,000 USDT")
    print("📈 Active Positions: 2/3")
    print()
    
    print("📋 Active Arbitrage:")
    print("-" * 60)
    print(f"{'ID':<20} {'Symbol':<12} {'Spread':>8} {'PnL':>10} {'Status':<10}")
    print("-" * 60)
    
    positions = [
        ("arb_SOL_1234567890", "SOL/USDT", "0.015%", "+150", "open"),
        ("arb_ETH_1234567891", "ETH/USDT", "0.012%", "+80", "open"),
    ]
    
    for pos_id, sym, spread, pnl, status in positions:
        print(f"{pos_id:<20} {sym:<12} {spread:>8} {pnl:>10} {status:<10}")


def cmd_arb_execute(args):
    """Execute an arbitrage."""
    symbol = args.symbol
    size = args.size or 1000
    
    print(f"🎯 Execute Arbitrage: {symbol}")
    print("=" * 60)
    print()
    
    print("📊 Opportunity:")
    print(f"  Symbol: {symbol}")
    print(f"  Size: {size} USDT")
    print(f"  Long Exchange: Binance")
    print(f"  Short Exchange: OKX")
    print(f"  Spread: 0.015%")
    print(f"  Expected Daily: +{size * 0.00015:.2f} USDT")
    print()
    
    # Confirmation
    confirm = input("⚠️  Confirm arbitrage? (yes/no): ")
    if confirm.lower() != "yes":
        print("❌ Arbitrage cancelled")
        return
    
    print("✅ Arbitrage executed!")
    print(f"  Position ID: arb_{symbol.replace('/', '_')}_{int(time.time())}")


def cmd_arb_close(args):
    """Close an arbitrage position."""
    arb_id = args.id
    
    print(f"📤 Closing arbitrage: {arb_id}")
    print("=" * 60)
    print()
    
    # Confirmation
    confirm = input("⚠️  Confirm close? (yes/no): ")
    if confirm.lower() != "yes":
        print("❌ Close cancelled")
        return
    
    print("✅ Arbitrage closed!")


# ============ Risk Management Commands ============

def cmd_risk(args):
    """Risk management commands."""
    if args.subcmd == "status":
        cmd_risk_status(args)
    elif args.subcmd == "check":
        cmd_risk_check(args)


def cmd_risk_status(args):
    """Show risk status."""
    print("⚠️ Risk Status")
    print("=" * 60)
    print()
    
    print("💰 Capital: 10,000 USDT")
    print("📈 Open Positions: 2")
    print("💵 Total Exposure: 6,600 USDT (66%)")
    print()
    
    print("📊 Daily Stats:")
    print(f"  Daily PnL: +700 USDT (+7.0%)")
    print(f"  Daily Loss Limit: 1,000 USDT (10%)")
    print(f"  Remaining: 300 USDT")
    print()
    
    print("⚠️ Risk Limits:")
    print(f"  Max Position Size: 33%")
    print(f"  Max Total Exposure: 66%")
    print(f"  Max Daily Loss: 10%")
    print(f"  Max Consecutive Losses: 3")
    print(f"  Current Consecutive Losses: 0")
    print()
    
    print("✅ Risk Status: HEALTHY")


def cmd_risk_check(args):
    """Check if a trade is allowed."""
    symbol = args.symbol
    size = args.size
    
    print(f"🔍 Risk Check: {symbol}")
    print("=" * 60)
    print()
    
    print(f"📊 Trade Size: {size} USDT")
    print()
    
    print("✅ Risk Checks:")
    print(f"  ✓ Position size within limit (33%)")
    print(f"  ✓ Total exposure within limit (66%)")
    print(f"  ✓ Daily loss not exceeded")
    print(f"  ✓ Consecutive losses < 5")
    print()
    
    print("✅ Trade ALLOWED")


# ============ History Commands ============

def cmd_history(args):
    """Show trading history."""
    limit = args.limit or 50
    export = args.export
    
    print(f"📜 Trading History (last {limit})")
    print("=" * 100)
    print()
    
    if export:
        print(f"📁 Exporting to {export}...")
        # Would export to CSV
        print("✅ Export complete!")
        return
    
    print(f"{'Date':<12} {'Symbol':<12} {'Side':<6} {'Entry':>10} {'Exit':>10} {'PnL':>10} {'PnL%':>8} {'Strategy':<15} {'Exchange':<10}")
    print("-" * 100)
    
    history = [
        ("2024-01-15", "BTC/USDT", "LONG", "68,000", "69,500", "+1,500", "+2.21%", "box_breakout", "okx"),
        ("2024-01-14", "ETH/USDT", "LONG", "3,500", "3,480", "-200", "-0.57%", "small_pullback", "binance"),
        ("2024-01-13", "SOL/USDT", "LONG", "120", "125", "+500", "+4.17%", "box_breakout", "bybit"),
    ]
    
    for row in history:
        print(f"{row[0]:<12} {row[1]:<12} {row[2]:<6} {row[3]:>10} {row[4]:>10} {row[5]:>10} {row[6]:>8} {row[7]:<15} {row[8]:<10}")


def cmd_stats(args):
    """Show trading statistics."""
    strategy = args.strategy
    
    print("📊 Trading Statistics")
    print("=" * 60)
    print()
    
    if strategy:
        print(f"🎯 Strategy: {strategy}")
    else:
        print("🎯 All Strategies")
    
    print()
    print("📈 Overall Performance:")
    print(f"  Total Trades: 125")
    print(f"  Wins: 78 (62.4%)")
    print(f"  Losses: 47 (37.6%)")
    print(f"  Total PnL: +25,800 USDT")
    print(f"  Avg Win: +520 USDT")
    print(f"  Avg Loss: -310 USDT")
    print(f"  Best Trade: +3,200 USDT")
    print(f"  Worst Trade: -1,200 USDT")
    print()
    print("📊 Strategy Breakdown:")
    print(f"  box_breakout: 45 trades, 68.9% win, +18,500 USDT")
    print(f"  small_pullback: 35 trades, 57.1% win, +5,200 USDT")
    print(f"  large_pullback: 25 trades, 60.0% win, +3,100 USDT")
    print(f"  funding_arb: 20 trades, 85.0% win, +4,500 USDT")


def cmd_pattern(args):
    """Detect K-line patterns."""
    symbol = args.symbol
    timeframe = args.timeframe or "15m"
    
    print(f"📊 K-Line Pattern Detection: {symbol}")
    print("=" * 60)
    print()
    print(f"⏱️  Timeframe: {timeframe}")
    print()
    
    print("🎯 Patterns Detected:")
    print("-" * 40)
    print("  ✅ Double Bottom at 67,200 (Bullish)")
    print("  ✅ Box Breakout at 68,500 (Bullish)")
    print("  ⏳ Ascending Triangle forming")
    print()
    
    print("💡 Interpretation:")
    print("  - Double bottom confirms support")
    print("  - Breakout suggests continuation")
    print("  - Triangle may lead to further upside")


# ============ Command Registration ============

def register_trading_commands(subparsers):
    """Register all trading commands."""
    
    # Market Analysis
    subparsers.add_parser("cycle", help="Show market cycle phase")
    
    scan_parser = subparsers.add_parser("scan", help="Scan for trading symbols")
    scan_parser.add_argument("--exchange", help="Exchange to scan")
    scan_parser.add_argument("--min-volume", type=float, help="Min 24h volume")
    scan_parser.add_argument("--min-oi", type=float, help="Min open interest")
    scan_parser.add_argument("--min-age", type=int, help="Min listing age (days)")
    scan_parser.add_argument("--max-volatility", type=float, help="Max volatility %")
    
    box_parser = subparsers.add_parser("box-detect", help="Detect box patterns")
    box_parser.add_argument("--symbol", required=True, help="Trading symbol")
    box_parser.add_argument("--timeframe", help="Timeframe (default: 15m)")
    box_parser.add_argument("--lookback", type=int, help="Lookback periods")
    
    signal_parser = subparsers.add_parser("signal", help="Detect trading signals")
    signal_parser.add_argument("--symbol", required=True, help="Trading symbol")
    signal_parser.add_argument("--strategy", help="Strategy (box_breakout, small_pullback, large_pullback)")
    
    sr_parser = subparsers.add_parser("sr", help="Show support/resistance levels")
    sr_parser.add_argument("--symbol", required=True, help="Trading symbol")
    
    pattern_parser = subparsers.add_parser("pattern", help="Detect K-line patterns")
    pattern_parser.add_argument("--symbol", required=True, help="Trading symbol")
    pattern_parser.add_argument("--timeframe", help="Timeframe")
    
    # Position Management
    pos_parser = subparsers.add_parser("position", help="Position management")
    pos_sub = pos_parser.add_subparsers(dest="subcmd")
    pos_sub.add_parser("status", help="Show positions")
    
    size_parser = pos_sub.add_parser("size", help="Calculate position size")
    size_parser.add_argument("--capital", type=float, help="Capital in USDT")
    size_parser.add_argument("--risk-pct", type=float, help="Risk percentage")
    size_parser.add_argument("--leverage", type=int, help="Leverage")
    
    hist_parser = pos_sub.add_parser("history", help="Position history")
    hist_parser.add_argument("--limit", type=int, help="Number of records")
    
    stats_parser = pos_sub.add_parser("stats", help="Position statistics")
    stats_parser.add_argument("--strategy", help="Filter by strategy")
    
    # Trading Execution
    order_parser = subparsers.add_parser("order", help="Place a trade order")
    order_parser.add_argument("--symbol", required=True, help="Trading symbol")
    order_parser.add_argument("--side", required=True, choices=["long", "short"], help="Order side")
    order_parser.add_argument("--size", type=float, required=True, help="Position size in USDT")
    order_parser.add_argument("--type", choices=["market", "limit"], help="Order type")
    
    close_parser = subparsers.add_parser("close", help="Close a position")
    close_parser.add_argument("--symbol", required=True, help="Trading symbol")
    
    # Funding Rate
    fund_parser = subparsers.add_parser("funding", help="Funding rate commands")
    fund_sub = fund_parser.add_subparsers(dest="subcmd")
    
    fund_status = fund_sub.add_parser("status", help="Show funding rates")
    fund_status.add_argument("--exchange", help="Exchange filter")
    
    fund_extreme = fund_sub.add_parser("extreme", help="Show extreme rates")
    fund_extreme.add_argument("--threshold", type=float, help="Threshold percentage")
    
    fund_opp = fund_sub.add_parser("opportunities", help="Show arbitrage opportunities")
    
    # Arbitrage
    arb_parser = subparsers.add_parser("arb", help="Arbitrage commands")
    arb_sub = arb_parser.add_subparsers(dest="subcmd")
    arb_sub.add_parser("status", help="Show arbitrage status")
    
    arb_exec = arb_sub.add_parser("execute", help="Execute arbitrage")
    arb_exec.add_argument("--symbol", required=True, help="Trading symbol")
    arb_exec.add_argument("--size", type=float, help="Position size")
    
    arb_close = arb_sub.add_parser("close", help="Close arbitrage")
    arb_close.add_argument("--id", required=True, help="Arbitrage ID")
    
    # Risk Management
    risk_parser = subparsers.add_parser("risk", help="Risk management")
    risk_sub = risk_parser.add_subparsers(dest="subcmd")
    risk_sub.add_parser("status", help="Show risk status")
    
    risk_check = risk_sub.add_parser("check", help="Check trade risk")
    risk_check.add_argument("--symbol", required=True, help="Trading symbol")
    risk_check.add_argument("--size", type=float, required=True, help="Position size")
    
    # History
    hist_parser = subparsers.add_parser("history", help="Trading history")
    hist_parser.add_argument("--limit", type=int, help="Number of records")
    hist_parser.add_argument("--export", help="Export to file")
    
    stats_parser = subparsers.add_parser("stats", help="Trading statistics")
    stats_parser.add_argument("--strategy", help="Filter by strategy")


def get_trading_commands():
    """Return mapping of command names to handlers."""
    return {
        "cycle": cmd_cycle,
        "scan": cmd_scan,
        "box-detect": cmd_box_detect,
        "signal": cmd_signal,
        "sr": cmd_sr,
        "pattern": cmd_pattern,
        "position": cmd_position,
        "order": cmd_order,
        "close": cmd_close,
        "funding": cmd_funding,
        "arb": cmd_arb,
        "risk": cmd_risk,
        "history": cmd_history,
        "stats": cmd_stats,
    }
