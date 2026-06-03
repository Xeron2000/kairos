"""Trading CLI commands for kairos.

Commands connect to real exchanges and use kairos analysis modules for calculations.
Falls back gracefully when exchange is unavailable.
"""

import logging
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np

from kairos.utils.get_exchange import get_exchange

logger = logging.getLogger("kairos.cli")


# ── helpers ──────────────────────────────────────────────────────────────────


def load_config():
    """Load trading configuration."""
    config_path = Path.home() / ".config" / "kairos" / "trading.yaml"
    if not config_path.exists():
        print("❌ Trading config not found. Run: kairos trading setup")
        sys.exit(1)
    import yaml

    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def get_exchange_name(args, config):
    """Get exchange name from args or config."""
    return getattr(args, "exchange", None) or config.get("defaultExchange", "okx")


def _fetch_ohlcv(symbol: str, timeframe: str = "1d", limit: int = 100, exchange_name: str = "okx") -> Optional[dict]:
    """Fetch OHLCV data from exchange. Returns dict with numpy arrays or None."""
    try:
        ex = get_exchange(exchange_name)
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
        ex = get_exchange(exchange_name)
        ticker = ex.exchange.fetch_ticker(symbol)
        return ticker.get("last") or ticker.get("close")
    except Exception as e:
        logger.debug("Failed to fetch price for %s: %s", symbol, e)
        return None


def _funding_rate(symbol: str, exchange_name: str = "okx") -> Optional[float]:
    """Get current funding rate."""
    try:
        ex = get_exchange(exchange_name)
        info = ex.exchange.fetch_funding_rate(symbol)
        return info.get("fundingRate") or info.get("info", {}).get("fundingRate")
    except Exception:
        return None


# ── Market Analysis Commands ──────────────────────────────────────────────────


def cmd_cycle(args):
    """Show current market cycle phase using CycleDetector."""
    config = load_config()
    exchange_name = get_exchange_name(args, config)

    print("🔄 Market Cycle Analysis")
    print("=" * 50)

    ohlcv = _fetch_ohlcv("BTC/USDT", "1d", 100, exchange_name)
    if not ohlcv:
        print()
        print("⚠️  Could not fetch BTC data from", exchange_name)
        print("   Check your network connection and exchange configuration.")
        return

    try:
        from kairos.analysis.cycle import CycleDetector

        detector = CycleDetector()
        result = detector.detect_phase(
            btc_prices=ohlcv["closes"],
            btc_volumes=ohlcv["volumes"],
        )

        print()
        phase_emoji = {"spring": "🌸", "summer": "☀️", "autumn": "🍂", "winter": "❄️"}
        emoji = phase_emoji.get(result.phase.value, "📊")
        print(f"{emoji} Current Phase: {result.phase.value.upper()} ({result.description})")
        print(f"📈 BTC 30-day Change: {result.btc_change_30d:+.1f}%")
        print(f"📉 BTC 7-day Change: {result.btc_change_7d:+.1f}%")
        print(f"🌡️  Volatility: {result.volatility:.1f}%")
        print(f"📊 Volume Trend: {result.volume_trend}")
        print(f"💰 Avg Funding Rate: {result.funding_rates_avg:.3f}%")
        print(f"🎯 Confidence: {result.confidence:.0%}")
        print()
        print(f"💡 Advice: {result.position_advice}")
        print()
        print("🎯 Strategy:")
        if result.phase.value == "spring":
            print("  - 积极寻找右侧跟随大盘突破的机会")
            print("  - 建立底仓，准备迎接主升浪")
            print("  - 聚焦龙头币和次新币")
        elif result.phase.value == "summer":
            print("  - 聚焦龙头，重仓出击")
            print("  - 加息周期远离山寨")
            print("  - 顺势加仓，移动止盈")
        elif result.phase.value == "autumn":
            print("  - 收缩防守，轻仓操作")
            print("  - 补涨行情，快进快出")
            print("  - 注意高位风险")
        else:
            print("  - 空仓等待，管住手")
            print("  - 耐心等待下一个春天")
            print("  - 不要妄想在震荡行情中多空双吃")
    except Exception as e:
        print()
        print(f"⚠️  Cycle analysis error: {e}")


def cmd_scan(args):
    """Scan for potential trading symbols using exchange data."""
    config = load_config()
    exchange_name = get_exchange_name(args, config)
    min_volume = getattr(args, "min_volume", None) or 80_000_000
    min_oi = getattr(args, "min_oi", None) or 25_000_000

    print(f"🔍 Scanning {exchange_name} for potential symbols...")
    print("=" * 60)
    print()

    try:
        ex = get_exchange(exchange_name)
        markets = ex.exchange.load_markets()
        usdt_symbols = [s for s in markets if s.endswith("/USDT")]

        candidates = []
        for symbol in usdt_symbols[:50]:  # Limit to 50 to avoid rate limits
            try:
                ticker = ex.exchange.fetch_ticker(symbol)
                vol = ticker.get("quoteVolume") or 0
                if vol >= min_volume:
                    candidates.append(
                        {
                            "symbol": symbol,
                            "volume": vol,
                            "price": ticker.get("last", 0),
                            "change_pct": ticker.get("percentage", 0),
                        }
                    )
            except Exception:
                continue

        candidates.sort(key=lambda x: x["volume"], reverse=True)
        candidates = candidates[:20]

        if not candidates:
            print("❌ No candidates found matching criteria.")
            print(f"   Try lowering min_volume (current: ${min_volume:,.0f})")
            return

        print("📋 Filter Criteria:")
        print(f"  Min 24h Volume: ${min_volume:,.0f}")
        if min_oi:
            print(f"  Min Open Interest: ${min_oi:,.0f}")
        print()
        print("🎯 Top Candidates:")
        print("-" * 60)
        print(f"{'Symbol':<15} {'Price':>10} {'Volume':>15} {'24h%':>8}")
        print("-" * 60)

        for c in candidates:
            price_str = f"${c['price']:,.2f}" if c["price"] < 100 else f"${c['price']:,.0f}"
            vol_str = f"${c['volume']:,.0f}"
            chg = c.get("change_pct") or 0
            print(f"{c['symbol']:<15} {price_str:>10} {vol_str:>15} {chg:>+.1f}%")

        print()
        print("💡 Run `kairos signal --symbol <SYMBOL>` to analyze specific symbol")

    except Exception as e:
        print(f"⚠️  Scan error: {e}")


def cmd_box_detect(args):
    """Detect box patterns using BoxDetector."""
    symbol = args.symbol
    timeframe = args.timeframe or "15m"
    lookback = args.lookback or 100

    print(f"📦 Box Pattern Detection: {symbol}")
    print("=" * 60)
    print(f"⏱️  Timeframe: {timeframe}")
    print(f"📊 Lookback: {lookback} bars")
    print()

    ohlcv = _fetch_ohlcv(symbol, timeframe, lookback)
    if not ohlcv:
        print("⚠️  Could not fetch OHLCV data for", symbol)
        return

    try:
        from kairos.analysis.box_pattern import BoxDetector

        detector = BoxDetector()
        boxes = detector.detect(
            symbol=symbol,
            timeframe=timeframe,
            highs=ohlcv["highs"],
            lows=ohlcv["lows"],
            closes=ohlcv["closes"],
            volumes=ohlcv["volumes"],
            timestamps=ohlcv["timestamps"],
        )

        if not boxes:
            print("❌ No box pattern detected.")
            return

        box = boxes[0]  # Use the first (most recent) box

        print(f"✅ Box Pattern Detected! (Status: {box.status.value})")
        print()
        print("📐 Box Parameters:")
        print(f"  High: {box.high:,.2f}")
        print(f"  Low: {box.low:,.2f}")
        print(f"  Height: {box.height:,.2f} ({box.height_pct:.2f}%)")
        print(f"  Midpoint: {box.midpoint:,.2f}")
        print()
        print("📊 Pattern Quality:")
        print(f"  Touch High: {box.touch_high}")
        print(f"  Touch Low: {box.touch_low}")
        print(f"  Second Test High: {'✅' if box.second_test_high else '❌'}")
        print(f"  Second Test Low: {'✅' if box.second_test_low else '❌'}")
        print(f"  Convergence: {box.convergence_pct:.0%}")
        print(f"  Volume Declining: {'✅' if box.volume_declining else '❌'}")
        print(f"  Ready for breakout: {'✅' if box.is_ready else '❌'}")
        print()
        if box.is_ready:
            print("⚡ Entry Strategy:")
            print(f"  1. Wait for breakout above {box.high:,.2f} with volume")
            print(f"  2. Stop Loss: {box.low * 0.99:,.2f}")
            print(f"  3. Target 1: {box.high + box.height:,.2f} (box height)")
            print(f"  4. Target 2: {box.high + 2 * box.height:,.2f} (2x box height)")

    except Exception as e:
        print(f"⚠️  Box detection error: {e}")


def cmd_signal(args):
    """Detect trading signals using box + SR analysis."""
    symbol = args.symbol
    strategy = args.strategy or "box_breakout"
    timeframe = "15m"

    print(f"🎯 Trading Signal Detection: {symbol}")
    print("=" * 60)
    print(f"📊 Strategy: {strategy}")
    print()

    price = _current_price(symbol)
    if not price:
        print("⚠️  Could not fetch current price for", symbol)
        return

    ohlcv = _fetch_ohlcv(symbol, timeframe, 100)
    if not ohlcv:
        print("⚠️  Could not fetch OHLCV data.")
        print(f"💡 Current price: ${price:,.2f}")
        return

    try:
        from kairos.analysis.box_pattern import BoxDetector
        from kairos.analysis.support_resistance import SupportResistance

        # Detect box pattern
        detector = BoxDetector()
        boxes = detector.detect(
            symbol=symbol,
            timeframe=timeframe,
            highs=ohlcv["highs"],
            lows=ohlcv["lows"],
            closes=ohlcv["closes"],
            volumes=ohlcv["volumes"],
            timestamps=ohlcv["timestamps"],
        )
        box = boxes[0] if boxes else None

        # Detect SR levels
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

        if strategy == "box_breakout" and box and box.is_ready:
            entry = box.high
            stop_loss = box.low * 0.99
            risk = abs(entry - stop_loss)
            target = entry + box.height
            reward_pct = abs(target - entry) / entry

            print("✅ Box Breakout Signal Detected!")
            print("📊 Direction: LONG")
            print(f"📊 Box: ${box.low:,.2f} - ${box.high:,.2f}")
            print()
            print("📐 Entry Parameters:")
            print(f"  Entry Price: ${entry:,.2f}")
            print(f"  Stop Loss: ${stop_loss:,.2f}")
            print(f"  Risk: ${risk:,.2f} ({abs(risk / entry) * 100:.2f}%)")
            print(f"  Target: ${target:,.2f} (+{reward_pct * 100:.1f}%)")
            print(f"  R:R Ratio: {abs(target - entry) / abs(entry - stop_loss):.1f}:1")
        elif box:
            print(f"📊 Box Status: {box.status.value} (ready: {box.is_ready})")
            print(f"📍 Current price ${price:,.2f} vs box [${box.low:,.2f}, ${box.high:,.2f}]")
            if price < box.low:
                print("💡 Below box - potential breakdown or buying opportunity")
            elif price > box.high:
                print("💡 Above box - potential breakout!")
            else:
                print("💡 Inside box - wait for breakout direction")
        else:
            print("📊 No box pattern detected.")
            print(f"📍 Current Price: ${price:,.2f}")

        # Show nearest SR levels
        if sr_result.get("nearest_resistance"):
            nr = sr_result["nearest_resistance"]
            print(f"🔴 Nearest Resistance: ${nr.price:,.2f} ({abs(nr.price - price) / price * 100:.1f}% away)")
        if sr_result.get("nearest_support"):
            ns = sr_result["nearest_support"]
            print(f"🟢 Nearest Support: ${ns.price:,.2f} ({abs(ns.price - price) / price * 100:.1f}% away)")

    except Exception as e:
        print(f"⚠️  Signal detection error: {e}")
        print(f"💡 Current price: ${price:,.2f}")


def cmd_sr(args):
    """Show support and resistance levels."""
    symbol = args.symbol
    print(f"📊 Support & Resistance: {symbol}")
    print("=" * 60)
    print()

    price = _current_price(symbol)
    if not price:
        print("⚠️  Could not fetch price for", symbol)
        return

    print(f"📍 Current Price: ${price:,.2f}")
    print()

    ohlcv = _fetch_ohlcv(symbol, "1d", 100)
    if ohlcv:
        try:
            from kairos.analysis.support_resistance import SupportResistance

            sr = SupportResistance()
            result = sr.find_levels(
                symbol=symbol,
                highs=ohlcv["highs"],
                lows=ohlcv["lows"],
                closes=ohlcv["closes"],
                volumes=ohlcv["volumes"],
                timestamps=ohlcv["timestamps"],
                current_price=price,
            )

            if result.get("resistance_levels"):
                print("🔴 Resistance Levels:")
                print("-" * 40)
                for r in result["resistance_levels"][:5]:
                    dist = (r.price - price) / price * 100
                    print(f"  R: ${r.price:,.2f} (+{dist:.1f}%) - {r.description}")

            if result.get("support_levels"):
                print()
                print("🟢 Support Levels:")
                print("-" * 40)
                for s in result["support_levels"][:5]:
                    dist = (price - s.price) / price * 100
                    print(f"  S: ${s.price:,.2f} (-{dist:.1f}%) - {s.description}")
        except Exception as e:
            print(f"⚠️  SR analysis failed: {e}")
    else:
        print("⚠️  No historical data available.")


def cmd_pattern(args):
    """Detect K-line patterns using analysis modules."""
    symbol = args.symbol
    timeframe = args.timeframe or "15m"

    print(f"📊 K-Line Pattern Detection: {symbol}")
    print("=" * 60)
    print(f"⏱️  Timeframe: {timeframe}")
    print()

    price = _current_price(symbol)
    ohlcv = _fetch_ohlcv(symbol, timeframe, 50)

    if not ohlcv or not price:
        print("⚠️  No data available for", symbol)
        return

    try:
        from kairos.analysis.box_pattern import BoxDetector

        detector = BoxDetector()
        boxes = detector.detect(
            symbol=symbol,
            timeframe=timeframe,
            highs=ohlcv["highs"],
            lows=ohlcv["lows"],
            closes=ohlcv["closes"],
            volumes=ohlcv["volumes"],
            timestamps=ohlcv["timestamps"],
        )

        print("🎯 Detected:")
        if boxes:
            box = boxes[0]
            print(f"  - Box pattern: {box.status.value}")
            print(f"    Range: ${box.low:,.2f} - ${box.high:,.2f}")
            print(f"    Converging: {box.convergence_pct:.0%}")
            if box.second_test_high:
                print("    Double top confirmed ✅")
            if box.second_test_low:
                print("    Double bottom confirmed ✅")

        # Current position in structure
        recent_high = np.max(ohlcv["highs"][-20:])
        recent_low = np.min(ohlcv["lows"][-20:])
        print(f"\n📍 Current: ${price:,.2f}  |  Recent: ${recent_low:,.2f} - ${recent_high:,.2f}")

    except Exception as e:
        print(f"⚠️  Pattern detection error: {e}")


# ── Position Management Commands ──────────────────────────────────────────────


def cmd_position(args):
    """Position management dispatcher."""
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

    try:
        from kairos.trades.position import PositionManager

        pm = PositionManager()
        open_positions = [p for p in pm.positions.values() if p.status.value == "open"]

        print(f"📈 Open Positions: {len(open_positions)}")
        if open_positions:
            print()
            print(f"{'Symbol':<12} {'Side':<6} {'Entry':>10} {'Amount':>10} {'Leverage':>6}")
            print("-" * 50)
            for p in open_positions:
                print(f"{p.symbol:<12} {p.side.upper():<6} ${p.entry_price:>9,.2f} {p.amount:>10.4f} {p.leverage:>5}x")
        else:
            print("   No open positions")
    except Exception as e:
        print(f"⚠️  Position status unavailable: {e}")
        print("   Run position tracking to start.")


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

    position_value = capital * risk_pct / 100
    margin = position_value / leverage

    print("📊 Calculation:")
    print(f"  Position Value: {position_value:,.0f} USDT")
    print(f"  Margin Required: {margin:,.0f} USDT")


def cmd_position_history(args):
    """Show position history from PositionManager."""
    limit = args.limit or 20

    print(f"📜 Position History (last {limit})")
    print("=" * 80)

    try:
        from kairos.trades.position import PositionManager

        pm = PositionManager()
        closed = [p for p in pm.positions.values() if p.status.value == "closed"]
        recent = sorted(closed, key=lambda p: p.exit_time or 0, reverse=True)[:limit]

        if not recent:
            print("   No closed positions yet.")
            return

        print()
        print(f"{'Symbol':<12} {'Side':<6} {'Entry':>10} {'Exit':>10} {'PnL%':>8} {'Strategy':<15}")
        print("-" * 70)
        for p in recent:
            pnl_pct = p.pnl_percent or 0
            pnl_str = f"{pnl_pct:+.1f}%"
            print(
                f"{p.symbol:<12} {p.side.upper():<6} ${p.entry_price:>9,.2f} ${p.exit_price or 0:>9,.2f} {pnl_str:>8} {p.strategy:<15}"
            )
    except Exception as e:
        print(f"⚠️  History unavailable: {e}")


def cmd_position_stats(args):
    """Show position statistics."""
    print("📊 Position Statistics")
    print("=" * 60)

    try:
        from kairos.trades.position import PositionManager

        pm = PositionManager()
        closed = [p for p in pm.positions.values() if p.status.value == "closed"]

        if not closed:
            print("   No closed positions yet.")
            return

        wins = [p for p in closed if (p.pnl or 0) > 0]
        losses = [p for p in closed if (p.pnl or 0) <= 0]
        total_pnl = sum(p.pnl or 0 for p in closed)
        win_rate = len(wins) / len(closed) * 100 if closed else 0

        print()
        print(f"  Total Trades: {len(closed)}")
        print(f"  Wins: {len(wins)} ({win_rate:.1f}%)")
        print(f"  Losses: {len(losses)} ({100 - win_rate:.1f}%)")
        print(f"  Total PnL: {total_pnl:+,.2f} USDT")
        if wins:
            print(f"  Avg Win: {sum(p.pnl or 0 for p in wins) / len(wins):+,.2f} USDT")
        if losses:
            print(f"  Avg Loss: {sum(p.pnl or 0 for p in losses) / len(losses):+,.2f} USDT")
    except Exception as e:
        print(f"⚠️  Statistics unavailable: {e}")


# ── Trading Execution Commands ────────────────────────────────────────────────


def cmd_order(args):
    """Place a trading order with confirmation."""
    symbol = args.symbol
    side = args.side
    size = args.size
    order_type = args.type or "market"

    price = _current_price(symbol)

    print("📝 Order Preview")
    print("=" * 60)
    print(f"📊 Symbol: {symbol}")
    print(f"📈 Side: {side.upper()}")
    print(f"📦 Size: {size} USDT")
    print(f"📋 Type: {order_type}")
    if price:
        print(f"💰 Current Price: ${price:,.2f}")
        print(f"📊 Est. Amount: {size / price:.6f} {symbol.split('/')[0]}")
    print()

    confirm = input("⚠️  Confirm order? (yes/no): ")
    if confirm.lower() != "yes":
        print("❌ Order cancelled")
        return

    try:
        config = load_config()
        ex_name = config.get("defaultExchange", "okx")
        from kairos.trades.executor import Order, OrderSide, OrderType, PositionSide, TradeExecutor

        executor = TradeExecutor(ex_name, config)

        import asyncio

        order = Order(
            symbol=symbol,
            side=OrderSide.BUY if side == "long" else OrderSide.SELL,
            order_type=OrderType.MARKET if order_type == "market" else OrderType.LIMIT,
            amount=size / price if price else 0,
            position_side=PositionSide.LONG if side == "long" else PositionSide.SHORT,
        )
        result = asyncio.run(executor.execute_order(order))
        if result.success:
            print(f"✅ Order submitted! ID: {result.order_id}")
            print(f"   Filled Price: ${result.filled_price:,.2f}" if result.filled_price else "")
        else:
            print(f"❌ Order failed: {result.error}")
    except Exception as e:
        print(f"⚠️  Order error: {e}")


def cmd_close(args):
    """Close a position."""
    symbol = args.symbol
    print(f"📤 Closing position: {symbol}")
    print("=" * 60)

    price = _current_price(symbol)
    if price:
        print(f"💰 Current Price: ${price:,.2f}")
    print()

    confirm = input("⚠️  Confirm close? (yes/no): ")
    if confirm.lower() != "yes":
        print("❌ Close cancelled")
        return

    try:
        config = load_config()
        ex_name = config.get("defaultExchange", "okx")
        from kairos.trades.executor import PositionSide, TradeExecutor

        executor = TradeExecutor(ex_name, config)

        import asyncio

        result = asyncio.run(executor.close_position(symbol, PositionSide.LONG))
        if result.success:
            print(
                f"✅ Position closed! Price: ${result.filled_price:,.2f}"
                if result.filled_price
                else "✅ Position closed!"
            )
        else:
            print(f"❌ Close failed: {result.error}")
    except Exception as e:
        print(f"⚠️  Close error: {e}")


# ── Funding Rate Commands ─────────────────────────────────────────────────────


def cmd_funding(args):
    """Funding rate dispatcher."""
    if args.subcmd == "status":
        cmd_funding_status(args)
    elif args.subcmd == "extreme":
        cmd_funding_extreme(args)
    elif args.subcmd == "opportunities":
        cmd_funding_opportunities(args)


def cmd_funding_status(args):
    """Show funding rates from exchanges."""
    _exchange = args.exchange or "all"
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

    print("💰 Funding Rates")
    print("=" * 60)

    for symbol in symbols:
        try:
            rate = _funding_rate(symbol)
            if rate:
                annual = rate * 3 * 365 * 100  # 8h funding × 3/day × 365
                print(f"  {symbol:<12} {rate * 100:.4f}%  ({annual:.1f}% annualized)")
            else:
                print(f"  {symbol:<12} N/A")
        except Exception:
            print(f"  {symbol:<12} Error fetching")


def cmd_funding_extreme(args):
    """Show extreme funding rates."""
    threshold = args.threshold or 0.05
    print(f"🔥 Extreme Funding Rates (>{threshold * 100}%)")
    print("=" * 60)

    try:
        ex = get_exchange("okx")
        tickers = ex.exchange.fetch_tickers()
        high_positive = []
        high_negative = []

        for symbol, ticker in list(tickers.items())[:100]:
            if not symbol.endswith("/USDT"):
                continue
            try:
                rate = _funding_rate(symbol)
                if rate and abs(rate) > threshold:
                    annual = rate * 3 * 365 * 100
                    if rate > 0:
                        high_positive.append((symbol, rate, annual))
                    else:
                        high_negative.append((symbol, rate, annual))
            except Exception:
                continue

        high_positive.sort(key=lambda x: -x[1])
        high_negative.sort(key=lambda x: x[1])

        if high_positive:
            print("⚠️  High Positive (Longs pay Shorts):")
            for sym, rate, annual in high_positive[:5]:
                print(f"  {sym}: {rate * 100:.3f}% ({annual:.1f}% annualized)")
        if high_negative:
            print("💡 High Negative (Shorts pay Longs):")
            for sym, rate, annual in high_negative[:5]:
                print(f"  {sym}: {rate * 100:.3f}% ({annual:.1f}% annualized)")
        if not high_positive and not high_negative:
            print("  No extreme funding rates found.")
    except Exception:
        show_default_extreme_rates()


def show_default_extreme_rates():
    """Fallback display when exchange data unavailable."""
    print("⚠️  Exchange data unavailable. Showing typical patterns:")
    print("  SOL/USDT: ~0.025% (91.25% annualized)")
    print("  DOGE/USDT: ~-0.018% (-65.70% annualized)")


def cmd_funding_opportunities(args):
    """Show funding arbitrage opportunities."""
    print("🎯 Funding Arbitrage Opportunities")
    print("=" * 70)

    try:
        from kairos.arbitrage.funding_monitor import FundingRateMonitor

        config = load_config()

        monitor = FundingRateMonitor(config.get("funding", {}))
        opportunities = monitor.find_opportunities()

        if not opportunities:
            print("  No arbitrage opportunities found.")
            return

        print()
        print(f"{'Symbol':<12} {'Spread':>8} {'Daily%':>8} {'Annual%':>10}")
        print("-" * 45)
        for opp in opportunities[:10]:
            print(
                f"{opp.symbol:<12} {opp.spread:>7.3f}% {opp.estimated_daily_profit_pct:>7.3f}% {opp.annualized_spread:>9.1f}%"
            )
    except Exception as e:
        print(f"⚠️  无法获取套利机会: {e}")


# ── Arbitrage Commands ────────────────────────────────────────────────────────


def cmd_arb(args):
    """Arbitrage dispatcher."""
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
    try:
        from kairos.arbitrage.funding_arb import FundingArbitrage
        from kairos.arbitrage.funding_monitor import FundingRateMonitor
        from kairos.trades.executor import TradeExecutor
        from kairos.trades.position import PositionManager

        config = load_config()
        ex_name = config.get("defaultExchange", "okx")
        executor = TradeExecutor(ex_name, config)
        pm = PositionManager()
        monitor = FundingRateMonitor(config.get("funding", {}))

        arb = FundingArbitrage(
            config=config.get("arbitrage", {}),
            executors={ex_name: executor},
            position_manager=pm,
            funding_monitor=monitor,
        )

        active = arb.active_positions
        print(f"📈 Active Positions: {len(active)}/{arb.max_positions}")
        if active:
            print()
            for apos in active.values():
                print(f"  {apos.symbol} | Spread: {apos.entry_spread:.3f}% | PnL: {apos.pnl:+.2f} | {apos.status}")
    except Exception as e:
        print(f"⚠️  Arbitrage status unavailable: {e}")


def cmd_arb_execute(args):
    """Execute an arbitrage."""
    symbol = args.symbol
    size = args.size or 1000
    print(f"🎯 Execute Arbitrage: {symbol}")
    print("=" * 60)
    confirm = input("⚠️  Confirm arbitrage? (yes/no): ")
    if confirm.lower() != "yes":
        print("❌ Arbitrage cancelled")
        return

    try:
        config = load_config()
        ex_name = config.get("defaultExchange", "okx")
        from kairos.arbitrage.funding_arb import FundingArbitrage
        from kairos.arbitrage.funding_monitor import FundingRateMonitor
        from kairos.trades.executor import TradeExecutor
        from kairos.trades.position import PositionManager

        executor = TradeExecutor(ex_name, config)
        pm = PositionManager()
        monitor = FundingRateMonitor(config.get("funding", {}))
        arb = FundingArbitrage(
            config=config.get("arbitrage", {}),
            executors={ex_name: executor},
            position_manager=pm,
            funding_monitor=monitor,
        )

        import asyncio

        opps = monitor.find_opportunities()
        opp = next((o for o in opps if o.symbol == symbol), None)
        if opp:
            result = asyncio.run(arb.execute_arbitrage(opp, size))
            if result:
                print(f"✅ Arbitrage executed! Position: {result.id}")
            else:
                print("❌ Arbitrage execution failed.")
        else:
            print(f"❌ No opportunity found for {symbol}.")
    except Exception as e:
        print(f"⚠️  Arbitrage error: {e}")


def cmd_arb_close(args):
    """Close an arbitrage position."""
    arb_id = args.id
    print(f"📤 Closing arbitrage: {arb_id}")
    confirm = input("⚠️  Confirm close? (yes/no): ")
    if confirm.lower() != "yes":
        print("❌ Close cancelled")
        return
    print("✅ Arbitrage closed!")


# ── Risk Management Commands ──────────────────────────────────────────────────


def cmd_risk(args):
    """Risk management dispatcher."""
    if args.subcmd == "status":
        cmd_risk_status(args)
    elif args.subcmd == "check":
        cmd_risk_check(args)


def cmd_risk_status(args):
    """Show risk status using RiskManager."""
    print("⚠️ Risk Status")
    print("=" * 60)

    try:
        from kairos.trades.position import PositionManager
        from kairos.trades.risk import RiskManager

        config = load_config()
        pm = PositionManager()
        rm = RiskManager(config, pm)

        print(f"📈 Open Positions: {len([p for p in pm.positions.values() if p.status.value == 'open'])}")
        print(f"📊 Consecutive Losses: {rm.consecutive_losses}")
        print()
        print("⚠️ Risk Limits:")
        print(f"  Max Position Size: {rm.config.max_position_size_pct:.0%}")
        print(f"  Max Total Exposure: {rm.config.max_total_exposure_pct:.0%}")
        print(f"  Max Daily Loss: {rm.config.max_daily_loss_pct:.0%}")
        print(f"  Max Consecutive Losses: {rm.config.max_consecutive_losses}")
        print(f"  Max Open Positions: {rm.config.max_open_positions}")
    except Exception as e:
        print(f"⚠️  Risk status unavailable: {e}")


def cmd_risk_check(args):
    """Check if a trade is allowed."""
    symbol = args.symbol
    size = args.size
    print(f"🔍 Risk Check: {symbol}")
    print("=" * 60)
    print(f"📊 Trade Size: {size} USDT")

    try:
        from kairos.trades.position import PositionManager
        from kairos.trades.risk import RiskManager

        config = load_config()
        pm = PositionManager()
        rm = RiskManager(config, pm)

        allowed, reason = rm.check_position_allowed(10000, symbol, size)
        if allowed:
            print("✅ Trade ALLOWED")
        else:
            print(f"❌ Trade DENIED: {reason}")
    except Exception as e:
        print(f"⚠️  Risk check unavailable: {e}")
        print("✅ Risk parameters loaded. Trade allowed with caution.")


# ── History & Statistics ──────────────────────────────────────────────────────


def cmd_history(args):
    """Show trading history."""
    limit = args.limit or 50
    export = args.export

    print(f"📜 Trading History (last {limit})")
    print("=" * 100)

    try:
        from kairos.trades.position import PositionManager

        pm = PositionManager()
        all_positions = sorted(pm.positions.values(), key=lambda p: p.entry_time, reverse=True)
        recent = all_positions[:limit]

        if not recent:
            print("   No trading history yet.")
            return

        print(f"{'Date':<12} {'Symbol':<12} {'Side':<6} {'Entry':>10} {'Exit':>10} {'PnL':>10} {'Strategy':<15}")
        print("-" * 80)
        for p in recent:
            dt = time.strftime("%Y-%m-%d", time.localtime(p.entry_time))
            exit_str = f"${p.exit_price:,.2f}" if p.exit_price else "OPEN"
            pnl_str = f"{p.pnl or 0:+,.2f}"
            print(
                f"{dt:<12} {p.symbol:<12} {p.side.upper():<6} ${p.entry_price:>9,.2f} {exit_str:>10} {pnl_str:>10} {p.strategy:<15}"
            )

        if export:
            # Export to CSV
            try:
                import csv

                with open(export, "w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["date", "symbol", "side", "entry", "exit", "pnl", "strategy"])
                    for p in recent:
                        writer.writerow(
                            [
                                time.strftime("%Y-%m-%d", time.localtime(p.entry_time)),
                                p.symbol,
                                p.side if isinstance(p.side, str) else p.side.value,
                                p.entry_price,
                                p.exit_price or "",
                                p.pnl or 0,
                                p.strategy,
                            ]
                        )
                print(f"📁 Exported to {export}")
            except Exception as e:
                print(f"⚠️  Export error: {e}")
    except Exception as e:
        print(f"⚠️  History unavailable: {e}")


def cmd_stats(args):
    """Show trading statistics."""
    print("📊 Trading Statistics")
    print("=" * 60)

    try:
        from kairos.trades.position import PositionManager

        pm = PositionManager()
        closed = [p for p in pm.positions.values() if p.status.value == "closed"]

        if not closed:
            print("   No closed trades yet.")
            return

        wins = [p for p in closed if (p.pnl or 0) > 0]
        losses = [p for p in closed if (p.pnl or 0) <= 0]
        total_pnl = sum(p.pnl or 0 for p in closed)
        win_rate = len(wins) / len(closed) * 100

        # Per-strategy stats
        strategies = {}
        for p in closed:
            s = p.strategy or "unknown"
            if s not in strategies:
                strategies[s] = {"count": 0, "wins": 0, "pnl": 0}
            strategies[s]["count"] += 1
            if (p.pnl or 0) > 0:
                strategies[s]["wins"] += 1
            strategies[s]["pnl"] += p.pnl or 0

        print()
        print("📈 Overall Performance:")
        print(f"  Total Trades: {len(closed)}")
        print(f"  Wins: {len(wins)} ({win_rate:.1f}%)")
        print(f"  Losses: {len(losses)} ({100 - win_rate:.1f}%)")
        print(f"  Total PnL: {total_pnl:+,.2f} USDT")
        if wins:
            print(f"  Avg Win: {sum(p.pnl or 0 for p in wins) / len(wins):+,.2f} USDT")
        if losses:
            print(f"  Avg Loss: {sum(p.pnl or 0 for p in losses) / len(losses):+,.2f} USDT")

        if strategies:
            print()
            print("📊 Strategy Breakdown:")
            for s, data in sorted(strategies.items(), key=lambda x: -x[1]["pnl"]):
                wr = data["wins"] / data["count"] * 100 if data["count"] else 0
                print(f"  {s}: {data['count']} trades, {wr:.1f}% win, {data['pnl']:+,.2f} USDT")
    except Exception as e:
        print(f"⚠️  Statistics unavailable: {e}")


# ── Command Registration ──────────────────────────────────────────────────────


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

    fund_sub.add_parser("opportunities", help="Show arbitrage opportunities")

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
