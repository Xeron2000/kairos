#!/usr/bin/env python3
"""Chart Generator MCP Server for kairos trading system.

Generates annotated K-line charts with box patterns, support/resistance levels,
entry/exit markers, and cycle phase overlays using mplfinance.

Designed with dark theme, clear annotations, compact file size.

Usage:
    python -m kairos.mcp.chart_server
"""

import logging
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger("kairos-chart-mcp")

mcp = FastMCP(name="Kairos-Chart", json_response=True)

# ── Chart Constants ─────────────────────────────────────────────────────────
BG_COLOR = "#1a1a2e"
GRID_COLOR = "#2a2a3e"
TEXT_COLOR = "#e0e0e0"
BULL_COLOR = "#26a69a"
BEAR_COLOR = "#ef5350"
LABEL_BG = "#333355"
LABEL_TEXT = "#ffffff"
VOL_UP_COLOR = "#26a69a"
VOL_DOWN_COLOR = "#ef5350"
ENTRY_ARROW_COLOR = "#00ff00"
EXIT_ARROW_COLOR = "#ff6600"

CYCLE_EMOJI = {
    "spring": "\U0001f338",
    "summer": "\u2600\ufe0f",
    "autumn": "\U0001f342",
    "winter": "\u2744\ufe0f",
}

TMP_DIR = Path(tempfile.gettempdir()) / "kairos_charts"


def _ensure_tmp() -> Path:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    return TMP_DIR


def _cleanup_old_charts(max_age_seconds: int = 3600) -> None:
    try:
        now = time.time()
        for f in TMP_DIR.glob("kairos_chart_*.png"):
            if now - f.stat().st_mtime > max_age_seconds:
                f.unlink(missing_ok=True)
    except Exception:
        pass


def _to_numpy(data: Any) -> np.ndarray:
    if isinstance(data, np.ndarray):
        return data.astype(float)
    return np.array(data, dtype=float)


def _parse_ohlcv(ohlcv_data: Any) -> Optional[Dict[str, np.ndarray]]:
    """Parse OHLCV from dict {opens,highs,lows,closes,volumes,timestamps} or list of rows."""
    if ohlcv_data is None:
        return None
    if isinstance(ohlcv_data, dict):
        required = {"opens", "highs", "lows", "closes", "volumes"}
        if required.issubset(ohlcv_data.keys()):
            return {
                "timestamps": _to_numpy(ohlcv_data.get("timestamps", [])),
                "opens": _to_numpy(ohlcv_data["opens"]),
                "highs": _to_numpy(ohlcv_data["highs"]),
                "lows": _to_numpy(ohlcv_data["lows"]),
                "closes": _to_numpy(ohlcv_data["closes"]),
                "volumes": _to_numpy(ohlcv_data["volumes"]),
            }
    if isinstance(ohlcv_data, list):
        arr = _to_numpy(ohlcv_data)
        if arr.ndim == 2 and arr.shape[1] >= 5:
            return {
                "timestamps": arr[:, 0] if arr.shape[1] >= 6 else np.arange(len(arr)),
                "opens": arr[:, 1],
                "highs": arr[:, 2],
                "lows": arr[:, 3],
                "closes": arr[:, 4],
                "volumes": arr[:, 5] if arr.shape[1] >= 6 else np.zeros(len(arr)),
            }
    return None


def _build_dataframe(data: dict):
    """Parse timestamps and build DataFrame. Returns None on all-NaT."""
    import pandas as pd

    dt_index = pd.DatetimeIndex(pd.to_datetime(data["timestamps"], unit="ms", errors="coerce"))
    df = pd.DataFrame(
        {"Open": data["opens"], "High": data["highs"], "Low": data["lows"], "Close": data["closes"]},
        index=dt_index,
    )
    return df[df.index.notna()] if not df.index.isna().all() else None


# ── Shared drawing helpers (used by multi-TF and BTC-comparison) ────────────


def _draw_candles(ax: Any, df: Any, n_bars: int) -> None:
    """Draw OHLC candles manually for consistent dark theme."""
    for j in range(len(df)):
        color = BULL_COLOR if df["Close"].iloc[j] >= df["Open"].iloc[j] else BEAR_COLOR
        body_bottom = min(df["Open"].iloc[j], df["Close"].iloc[j])
        body_height = abs(df["Close"].iloc[j] - df["Open"].iloc[j])
        ax.bar(j, body_height, 0.6, bottom=body_bottom, color=color, edgecolor=color, linewidth=0.5)
        ax.plot([j, j], [df["Low"].iloc[j], df["High"].iloc[j]], color=color, linewidth=0.8)


def _draw_boxes(ax: Any, boxes: list, n_bars: int, alpha: float = 0.08) -> None:
    """Draw box rectangles on an axis. Silently skips malformed entries."""
    import matplotlib.patches as mpatches

    for box in boxes:
        try:
            h, lo = float(box["high"]), float(box["low"])
            s, e = max(0, int(box.get("start_idx", 0))), min(n_bars - 1, int(box.get("end_idx", n_bars - 1)))
            rect = mpatches.Rectangle(
                (s - 0.5, lo),
                e - s + 1,
                h - lo,
                linewidth=1.5,
                edgecolor="gold",
                facecolor="green",
                alpha=alpha,
                linestyle="--",
            )
            ax.add_patch(rect)
        except (ValueError, TypeError, KeyError):
            pass


def _draw_sr_lines(ax: Any, support_levels: list, resistance_levels: list) -> None:
    """Draw support (lime) and resistance (tomato) horizontal lines."""
    for levels, color in [(support_levels, "lime"), (resistance_levels, "tomato")]:
        for lvl in levels:
            try:
                ax.axhline(y=float(lvl["price"]), color=color, linestyle="--", linewidth=1.0, alpha=0.5)
            except (ValueError, TypeError, KeyError):
                pass


def _style_axis(ax: Any, ylabel: str) -> None:
    ax.set_ylabel(ylabel, color=TEXT_COLOR, fontsize=10, fontweight="bold")
    ax.tick_params(colors=TEXT_COLOR, labelsize=7)
    ax.set_facecolor(BG_COLOR)
    ax.grid(True, color=GRID_COLOR, linestyle=":", alpha=0.5)


def _make_output_path(symbol: str, suffix: str, output_path: Optional[str] = None) -> str:
    if output_path:
        return output_path
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = symbol.replace("/", "_").replace(":", "_")
    return str(_ensure_tmp() / f"kairos_{safe}_{suffix}_{ts}.png")


def _title_info(cycle_info: dict) -> tuple[str, str, str]:
    phase = cycle_info.get("phase", "unknown")
    emoji = CYCLE_EMOJI.get(phase, "\U0001f4ca")
    advice = cycle_info.get("advice", "")
    return phase, emoji, advice


# ── Chart Generation Tools ──────────────────────────────────────────────────


@mcp.tool()
async def generate_analysis_chart(
    symbol: str,
    timeframe: str,
    ohlcv_data: Any,
    annotations: Optional[Dict[str, Any]] = None,
    cycle_info: Optional[Dict[str, Any]] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate an annotated K-line chart with trading analysis overlays.

    Args:
        symbol: Trading pair, e.g. 'BTC/USDT'.
        timeframe: Chart timeframe, e.g. '15m', '4h', '1d'.
        ohlcv_data: OHLCV dict or list of [ts, o, h, l, c, v] rows.
        annotations: Dict with optional boxes, support_levels, resistance_levels,
            entry_points, exit_points, divergence_labels.
        cycle_info: Dict with 'phase', 'btc_change_30d', 'volatility', 'advice'.
        output_path: Where to save PNG (auto-generated if not set).
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    import mplfinance as mpf

    _cleanup_old_charts()

    data = _parse_ohlcv(ohlcv_data)
    if data is None:
        return {"success": False, "error": "Invalid OHLCV data", "path": ""}

    closes = data["closes"]
    highs = data["highs"]
    lows = data["lows"]
    n_bars = len(closes)
    if n_bars < 5:
        return {"success": False, "error": f"Not enough bars: {n_bars}", "path": ""}

    annotations = annotations or {}
    cycle_info = cycle_info or {}
    output_path = _make_output_path(symbol, f"{timeframe}", output_path)

    mc = mpf.make_marketcolors(
        up=BULL_COLOR,
        down=BEAR_COLOR,
        edge="inherit",
        wick="inherit",
        volume={"up": VOL_UP_COLOR, "down": VOL_DOWN_COLOR},
    )
    style = mpf.make_mpf_style(
        marketcolors=mc, facecolor=BG_COLOR, figcolor=BG_COLOR, gridcolor=GRID_COLOR, gridstyle=":", y_on_right=False
    )

    phase, emoji, advice = _title_info(cycle_info)
    title = f"{emoji} {symbol}  {timeframe}"
    if phase != "unknown":
        title += f"  |  {phase.upper()}"
    if advice:
        title += f"\n{advice}"

    # DataFrame via shared helper
    import pandas as pd

    dt_index = pd.DatetimeIndex(pd.to_datetime(data["timestamps"], unit="ms", errors="coerce"))
    df = pd.DataFrame(
        {"Open": data["opens"], "High": data["highs"], "Low": data["lows"], "Close": closes, "Volume": data["volumes"]},
        index=dt_index,
    )
    df = df[df.index.notna()]
    if len(df) < 5:
        return {"success": False, "error": "Not enough valid datetimes", "path": ""}

    fig, axes = mpf.plot(
        df, type="candle", style=style, title=title, volume=True, figsize=(16, 10), returnfig=True, tight_layout=False
    )
    ax_main = axes[0] if len(axes) > 0 else plt.gca()
    price_range = highs.max() - lows.min()

    # Boxes (rich style)
    for box in annotations.get("boxes", []):
        try:
            h, lo = float(box["high"]), float(box["low"])
            s = max(0, min(int(box.get("start_idx", 0)), n_bars - 1))
            e = max(s, min(int(box.get("end_idx", n_bars - 1)), n_bars - 1))
            status = box.get("status", "")
            rect = mpatches.Rectangle(
                (s - 0.5, lo),
                e - s + 1,
                h - lo,
                linewidth=1.5,
                edgecolor="lime" if status == "breakout_up" else "gold",
                facecolor="green" if lo > closes[-1] else "red",
                alpha=0.12,
                linestyle="--" if status == "forming" else "-",
            )
            ax_main.add_patch(rect)
            if label := box.get("label", ""):
                ax_main.annotate(
                    label,
                    xy=(s, h),
                    xytext=(s, h * 1.005),
                    color=LABEL_TEXT,
                    fontsize=8,
                    fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor=LABEL_BG, alpha=0.7),
                )
        except (ValueError, TypeError, KeyError):
            pass

    # S/R levels (rich style)
    for sr_list, sr_color in [
        (annotations.get("support_levels", []), "lime"),
        (annotations.get("resistance_levels", []), "tomato"),
    ]:
        for lvl in sr_list:
            try:
                price = float(lvl["price"])
                strength = lvl.get("strength", 1)
                lw = max(0.8, 1.2 * min(strength, 3) / 1.5)
                ax_main.axhline(y=price, color=sr_color, linestyle="--", linewidth=lw, alpha=0.7)
                if label := lvl.get("label", ""):
                    ax_main.text(
                        0,
                        price,
                        f" {label}",
                        color=sr_color,
                        fontsize=7,
                        va="center",
                        ha="left",
                        fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.1", facecolor=LABEL_BG, alpha=0.6),
                    )
            except (ValueError, TypeError, KeyError):
                pass

    # Entry/exit arrows
    arrow_offset = price_range * 0.02
    for point_list, arrow_color in [
        (annotations.get("entry_points", []), ENTRY_ARROW_COLOR),
        (annotations.get("exit_points", []), EXIT_ARROW_COLOR),
    ]:
        for pt in point_list:
            try:
                px = max(0, min(int(pt.get("idx", 0)), n_bars - 1))
                py = float(pt["price"])
                direction = pt.get("direction", "up")
                arrow_y = py - arrow_offset if direction == "up" else py + arrow_offset
                ax_main.annotate(
                    pt.get("label", ""),
                    xy=(px, py),
                    xytext=(px, arrow_y),
                    arrowprops=dict(arrowstyle="->", color=arrow_color, lw=2.0, connectionstyle="arc3,rad=0.1"),
                    color=arrow_color,
                    fontsize=8,
                    fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor=LABEL_BG, alpha=0.8),
                )
            except (ValueError, TypeError, KeyError):
                pass

    # Divergence labels
    for div in annotations.get("divergence_labels", []):
        try:
            idx = max(0, min(int(div.get("idx", 0)), n_bars - 1))
            price = float(div.get("price", 0))
            ax_main.annotate(
                div.get("text", ""),
                xy=(idx, price),
                xytext=(idx, price * 1.03),
                color="#ffaa00",
                fontsize=9,
                fontweight="bold",
                ha="center",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#442200", alpha=0.85),
                arrowprops=dict(arrowstyle="->", color="#ffaa00", lw=1.5),
            )
        except (ValueError, TypeError, KeyError):
            pass

    ax_main.set_ylabel("Price", color=TEXT_COLOR)
    ax_main.tick_params(colors=TEXT_COLOR, labelsize=8)
    ax_main.set_facecolor(BG_COLOR)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, facecolor=BG_COLOR, bbox_inches="tight")
    plt.close(fig)

    file_size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
    logger.info("Chart saved: %s (%d bytes)", output_path, file_size)

    return {
        "success": True,
        "path": output_path,
        "file_size_bytes": file_size,
        "symbol": symbol,
        "timeframe": timeframe,
        "message": f"Chart generated: {symbol} {timeframe}",
    }


@mcp.tool()
async def generate_multi_tf_chart(
    symbol: str,
    timeframes: List[Dict[str, Any]],
    cycle_info: Optional[Dict[str, Any]] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a multi-timeframe comparison chart (stacked panels)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _cleanup_old_charts()

    if not timeframes:
        return {"success": False, "error": "No timeframe data provided", "path": ""}

    cycle_info = cycle_info or {}
    output_path = _make_output_path(symbol, "mtf", output_path)
    phase, emoji, advice = _title_info(cycle_info)

    n_panels = len(timeframes)
    fig, axes = plt.subplots(n_panels, 1, figsize=(16, 5 * n_panels), sharex=False)
    if n_panels == 1:
        axes = [axes]
    fig.patch.set_facecolor(BG_COLOR)
    fig.suptitle(
        f"{emoji} {symbol}  Multi-Timeframe  |  {phase.upper()}\n{advice}",
        color=TEXT_COLOR,
        fontsize=14,
        fontweight="bold",
        y=0.99,
    )

    for i, tf_data in enumerate(timeframes):
        ax = axes[i]
        tf_name = tf_data.get("timeframe", f"TF{i}")
        annotations = tf_data.get("annotations", {})

        data = _parse_ohlcv(tf_data.get("ohlcv_data"))
        if data is None:
            ax.text(0.5, 0.5, f"No data for {tf_name}", transform=ax.transAxes, color=TEXT_COLOR, ha="center")
            ax.set_facecolor(BG_COLOR)
            continue

        df = _build_dataframe(data)
        if df is None or len(df) < 2:
            continue
        n_bars = len(df)

        _draw_candles(ax, df, n_bars)
        _draw_boxes(ax, annotations.get("boxes", []), n_bars)
        _draw_sr_lines(ax, annotations.get("support_levels", []), annotations.get("resistance_levels", []))
        _style_axis(ax, tf_name)
        ax.set_xlim(-0.5, n_bars + 0.5)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, facecolor=BG_COLOR, bbox_inches="tight")
    plt.close(fig)

    file_size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
    logger.info("Multi-TF chart saved: %s (%d bytes)", output_path, file_size)
    return {
        "success": True,
        "path": output_path,
        "file_size_bytes": file_size,
        "symbol": symbol,
        "message": f"Multi-TF chart: {symbol}",
    }


@mcp.tool()
async def generate_btc_comparison_chart(
    altcoin_symbol: str,
    btc_ohlcv: Any,
    altcoin_ohlcv: Any,
    timeframe: str = "15m",
    annotations: Optional[Dict[str, Any]] = None,
    cycle_info: Optional[Dict[str, Any]] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate BTC vs altcoin comparison chart (side-by-side panels)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _cleanup_old_charts()

    btc_data = _parse_ohlcv(btc_ohlcv)
    alt_data = _parse_ohlcv(altcoin_ohlcv)
    if btc_data is None or alt_data is None:
        return {"success": False, "error": "Invalid OHLCV data", "path": ""}

    annotations = annotations or {}
    cycle_info = cycle_info or {}
    output_path = _make_output_path(altcoin_symbol, "btc_vs", output_path)
    phase, emoji, _ = _title_info(cycle_info)

    fig, (ax_btc, ax_alt) = plt.subplots(1, 2, figsize=(20, 8))
    fig.patch.set_facecolor(BG_COLOR)
    fig.suptitle(
        f"{emoji} BTC vs {altcoin_symbol}  {timeframe}  |  {phase.upper()}",
        color=TEXT_COLOR,
        fontsize=13,
        fontweight="bold",
    )

    for ax, label, raw_data, annot in [
        (ax_btc, "BTC/USDT", btc_data, {}),
        (ax_alt, altcoin_symbol, alt_data, annotations),
    ]:
        df = _build_dataframe(raw_data)
        if df is None or len(df) < 2:
            continue
        n_bars = len(df)

        _draw_candles(ax, df, n_bars)
        _draw_boxes(ax, annot.get("boxes", []), n_bars)
        _draw_sr_lines(ax, annot.get("support_levels", []), annot.get("resistance_levels", []))
        _style_axis(ax, label)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, facecolor=BG_COLOR, bbox_inches="tight")
    plt.close(fig)

    file_size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
    logger.info("BTC comparison chart saved: %s (%d bytes)", output_path, file_size)
    return {
        "success": True,
        "path": output_path,
        "file_size_bytes": file_size,
        "symbol": altcoin_symbol,
        "message": f"BTC comparison chart: BTC vs {altcoin_symbol}",
    }


# ── Entry Point ──────────────────────────────────────────────────────────────


def main() -> None:
    logger.info("Starting Chart Generator MCP server")
    _ensure_tmp()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
