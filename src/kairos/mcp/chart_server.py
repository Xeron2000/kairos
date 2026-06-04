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

mcp = FastMCP(
    name="Kairos-Chart",
    json_response=True,
)

# ── Chart Constants ─────────────────────────────────────────────────────────

# Dark theme colors
BG_COLOR = "#1a1a2e"
GRID_COLOR = "#2a2a3e"
TEXT_COLOR = "#e0e0e0"
BULL_COLOR = "#26a69a"
BEAR_COLOR = "#ef5350"
BOX_COLOR = "green"
BOX_ALPHA = 0.12
SR_LINE_COLOR = "gold"
SR_LINE_STYLE = "--"
SR_LINE_WIDTH = 1.2
ENTRY_ARROW_COLOR = "#00ff00"
EXIT_ARROW_COLOR = "#ff6600"
LABEL_BG = "#333355"
LABEL_TEXT = "#ffffff"
VOL_UP_COLOR = "#26a69a"
VOL_DOWN_COLOR = "#ef5350"
CYCLE_COLORS = {
    "spring": "#4caf50",
    "summer": "#ff9800",
    "autumn": "#ff5722",
    "winter": "#2196f3",
}
CYCLE_EMOJI = {
    "spring": "\U0001f338",
    "summer": "\u2600\ufe0f",
    "autumn": "\U0001f342",
    "winter": "\u2744\ufe0f",
}

TMP_DIR = Path(tempfile.gettempdir()) / "kairos_charts"


def _ensure_tmp() -> Path:
    """Ensure temp directory exists."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    return TMP_DIR


def _cleanup_old_charts(max_age_seconds: int = 3600) -> None:
    """Remove chart files older than max_age_seconds."""
    try:
        now = time.time()
        for f in TMP_DIR.glob("kairos_chart_*.png"):
            if now - f.stat().st_mtime > max_age_seconds:
                f.unlink(missing_ok=True)
    except Exception:
        pass


def _to_numpy(data: Any) -> np.ndarray:
    """Convert list/tuple to numpy float array."""
    if isinstance(data, np.ndarray):
        return data.astype(float)
    return np.array(data, dtype=float)


def _parse_ohlcv(ohlcv_data: Any) -> Optional[Dict[str, np.ndarray]]:
    """Parse OHLCV data from JSON-serializable format.

    Accepts either:
    - dict with keys: timestamps, opens, highs, lows, closes, volumes
    - list of [ts, o, h, l, c, v] rows
    """
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
        ohlcv_data: OHLCV dict with timestamps/opens/highs/lows/closes/volumes,
            or list of [ts, o, h, l, c, v] rows.
        annotations: Dict with optional keys:
            - boxes: [{high, low, start_idx, end_idx, label, status}]
            - support_levels: [{price, strength, label}]
            - resistance_levels: [{price, strength, label}]
            - entry_points: [{price, idx, direction, label}]
            - exit_points: [{price, idx, direction, label}]
            - divergence_labels: [{text, idx, price}]
        cycle_info: Dict with 'phase', 'btc_change_30d', 'volatility', 'advice'.
        output_path: Where to save PNG (auto-generated in /tmp/kairos_charts/ if not set).

    Returns:
        dict with 'success', 'path', 'message'.
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
    volumes = data["volumes"]
    n_bars = len(closes)

    if n_bars < 5:
        return {"success": False, "error": f"Not enough bars: {n_bars}", "path": ""}

    annotations = annotations or {}
    cycle_info = cycle_info or {}

    # Build output path
    if not output_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_symbol = symbol.replace("/", "_").replace(":", "_")
        output_path = str(_ensure_tmp() / f"kairos_chart_{safe_symbol}_{timeframe}_{ts}.png")

    # ── Build mplfinance style ───────────────────────────────────────────
    mc = mpf.make_marketcolors(
        up=BULL_COLOR,
        down=BEAR_COLOR,
        edge="inherit",
        wick="inherit",
        volume={"up": VOL_UP_COLOR, "down": VOL_DOWN_COLOR},
    )
    style = mpf.make_mpf_style(
        marketcolors=mc,
        facecolor=BG_COLOR,
        figcolor=BG_COLOR,
        gridcolor=GRID_COLOR,
        gridstyle=":",
        y_on_right=False,
    )

    # ── Title ────────────────────────────────────────────────────────────
    phase = cycle_info.get("phase", "unknown")
    emoji = CYCLE_EMOJI.get(phase, "\U0001f4ca")
    title = f"{emoji} {symbol}  {timeframe}"
    if phase != "unknown":
        title += f"  |  {phase.upper()}"
    advice = cycle_info.get("advice", "")
    if advice:
        title += f"\n{advice}"

    # ── Build DataFrame ──────────────────────────────────────────────────
    import pandas as pd

    dt_index = pd.DatetimeIndex(pd.to_datetime(data["timestamps"], unit="ms", errors="coerce"))
    df = pd.DataFrame(
        {
            "Open": data["opens"],
            "High": data["highs"],
            "Low": data["lows"],
            "Close": closes,
            "Volume": volumes,
        },
        index=dt_index,
    )

    # Drop rows where index is NaT
    df = df[df.index.notna()]
    if len(df) < 5:
        return {"success": False, "error": "Not enough valid datetimes", "path": ""}

    # ── Create figure ────────────────────────────────────────────────────
    fig, axes = mpf.plot(
        df,
        type="candle",
        style=style,
        title=title,
        volume=True,
        figsize=(16, 10),
        returnfig=True,
        tight_layout=False,
    )

    ax_main = axes[0] if len(axes) > 0 else plt.gca()

    # ── Draw boxes ───────────────────────────────────────────────────────
    for box in annotations.get("boxes", []):
        try:
            box_high = float(box.get("high", 0))
            box_low = float(box.get("low", 0))
            start_idx = int(box.get("start_idx", 0))
            end_idx = int(box.get("end_idx", n_bars - 1))
            label = box.get("label", "")
            status = box.get("status", "")

            start_idx = max(0, min(start_idx, n_bars - 1))
            end_idx = max(start_idx, min(end_idx, n_bars - 1))

            rect = mpatches.Rectangle(
                (start_idx - 0.5, box_low),
                end_idx - start_idx + 1,
                box_high - box_low,
                linewidth=1.5,
                edgecolor="lime" if status == "breakout_up" else "gold",
                facecolor="green" if box_low > closes[-1] else "red",
                alpha=BOX_ALPHA,
                linestyle="--" if status == "forming" else "-",
            )
            ax_main.add_patch(rect)

            if label:
                ax_main.annotate(
                    label,
                    xy=(start_idx, box_high),
                    xytext=(start_idx, box_high * 1.005),
                    color=LABEL_TEXT,
                    fontsize=8,
                    fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor=LABEL_BG, alpha=0.7),
                )
        except (ValueError, TypeError, KeyError) as e:
            logger.debug("Skipping box annotation: %s", e)

    # ── Draw S/R levels ──────────────────────────────────────────────────
    for sr_list, sr_color in [
        (annotations.get("support_levels", []), "lime"),
        (annotations.get("resistance_levels", []), "tomato"),
    ]:
        for level in sr_list:
            try:
                price = float(level.get("price", 0))
                label = level.get("label", "")
                strength = level.get("strength", 1)
                lw = max(0.8, SR_LINE_WIDTH * min(strength, 3) / 1.5)
                ax_main.axhline(
                    y=price,
                    color=sr_color,
                    linestyle=SR_LINE_STYLE,
                    linewidth=lw,
                    alpha=0.7,
                )
                if label:
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
            except (ValueError, TypeError, KeyError) as e:
                logger.debug("Skipping S/R annotation: %s", e)

    # ── Draw entry/exit points ───────────────────────────────────────────
    for point_list, arrow_color in [
        (annotations.get("entry_points", []), ENTRY_ARROW_COLOR),
        (annotations.get("exit_points", []), EXIT_ARROW_COLOR),
    ]:
        for pt in point_list:
            try:
                px = int(pt.get("idx", 0))
                py = float(pt.get("price", 0))
                direction = pt.get("direction", "up")
                label = pt.get("label", "")

                px = max(0, min(px, n_bars - 1))
                arrow_offset = (highs.max() - lows.min()) * 0.02
                arrow_y = py - arrow_offset if direction == "up" else py + arrow_offset
                arrow_dir = (0, arrow_offset * 2) if direction == "up" else (0, -arrow_offset * 2)

                ax_main.annotate(
                    label,
                    xy=(px, py),
                    xytext=(px, arrow_y),
                    arrowprops=dict(
                        arrowstyle="->",
                        color=arrow_color,
                        lw=2.0,
                        connectionstyle="arc3,rad=0.1",
                    ),
                    color=arrow_color,
                    fontsize=8,
                    fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor=LABEL_BG, alpha=0.8),
                )
            except (ValueError, TypeError, KeyError) as e:
                logger.debug("Skipping entry/exit annotation: %s", e)

    # ── Divergence labels ────────────────────────────────────────────────
    for div in annotations.get("divergence_labels", []):
        try:
            text = div.get("text", "")
            idx = int(div.get("idx", 0))
            price = float(div.get("price", 0))
            idx = max(0, min(idx, n_bars - 1))
            ax_main.annotate(
                text,
                xy=(idx, price),
                xytext=(idx, price * 1.03),
                color="#ffaa00",
                fontsize=9,
                fontweight="bold",
                ha="center",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#442200", alpha=0.85),
                arrowprops=dict(
                    arrowstyle="->",
                    color="#ffaa00",
                    lw=1.5,
                ),
            )
        except (ValueError, TypeError, KeyError) as e:
            logger.debug("Skipping divergence label: %s", e)

    # ── Finalize and save ────────────────────────────────────────────────
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
    """Generate a multi-timeframe comparison chart.

    Stacked panels: daily on top, 4H middle, 15m bottom.

    Args:
        symbol: Trading pair symbol.
        timeframes: List of {timeframe, ohlcv_data, annotations} dicts.
            Ordered top-to-bottom (largest timeframe first).
        cycle_info: Dict with 'phase', 'btc_change_30d', 'volatility', 'advice'.
        output_path: Where to save PNG.

    Returns:
        dict with 'success', 'path', 'message'.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    import pandas as pd

    _cleanup_old_charts()

    if not timeframes:
        return {"success": False, "error": "No timeframe data provided", "path": ""}

    cycle_info = cycle_info or {}

    if not output_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_symbol = symbol.replace("/", "_").replace(":", "_")
        output_path = str(_ensure_tmp() / f"kairos_mtf_{safe_symbol}_{ts}.png")

    phase = cycle_info.get("phase", "unknown")
    emoji = CYCLE_EMOJI.get(phase, "\U0001f4ca")
    advice = cycle_info.get("advice", "")

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
        ohlcv_raw = tf_data.get("ohlcv_data")
        annotations = tf_data.get("annotations", {})

        data = _parse_ohlcv(ohlcv_raw)
        if data is None:
            ax.text(0.5, 0.5, f"No data for {tf_name}", transform=ax.transAxes, color=TEXT_COLOR, ha="center")
            ax.set_facecolor(BG_COLOR)
            continue

        closes = data["closes"]
        highs = data["highs"]
        lows = data["lows"]
        n_bars = len(closes)

        dt_index = pd.DatetimeIndex(pd.to_datetime(data["timestamps"], unit="ms", errors="coerce"))
        df = pd.DataFrame(
            {"Open": data["opens"], "High": highs, "Low": lows, "Close": closes},
            index=dt_index,
        )
        df = df[df.index.notna()]
        if len(df) < 2:
            continue

        # Plot candles manually for dark theme
        colors = [BULL_COLOR if df["Close"].iloc[j] >= df["Open"].iloc[j] else BEAR_COLOR for j in range(len(df))]
        width = 0.6
        for j in range(len(df)):
            body_bottom = min(df["Open"].iloc[j], df["Close"].iloc[j])
            body_height = abs(df["Close"].iloc[j] - df["Open"].iloc[j])
            ax.bar(
                j,
                body_height,
                width,
                bottom=body_bottom,
                color=colors[j],
                edgecolor=colors[j],
                linewidth=0.5,
            )
            ax.plot(
                [j, j],
                [df["Low"].iloc[j], df["High"].iloc[j]],
                color=colors[j],
                linewidth=0.8,
            )

        # Draw boxes for this timeframe
        for box in annotations.get("boxes", []):
            try:
                box_high = float(box.get("high", 0))
                box_low = float(box.get("low", 0))
                start_idx = int(box.get("start_idx", 0))
                end_idx = int(box.get("end_idx", n_bars - 1))
                start_idx = max(0, min(start_idx, n_bars - 1))
                end_idx = max(start_idx, min(end_idx, n_bars - 1))
                rect = mpatches.Rectangle(
                    (start_idx - 0.5, box_low),
                    end_idx - start_idx + 1,
                    box_high - box_low,
                    linewidth=1.5,
                    edgecolor="gold",
                    facecolor="green",
                    alpha=0.08,
                    linestyle="--",
                )
                ax.add_patch(rect)
                label = box.get("label", "")
                if label:
                    ax.text(
                        start_idx,
                        box_high * 1.002,
                        label,
                        color="gold",
                        fontsize=7,
                        fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.1", facecolor=LABEL_BG, alpha=0.7),
                    )
            except (ValueError, TypeError, KeyError):
                pass

        # S/R lines
        for sr_list, sr_color in [
            (annotations.get("support_levels", []), "lime"),
            (annotations.get("resistance_levels", []), "tomato"),
        ]:
            for level in sr_list:
                try:
                    ax.axhline(y=float(level.get("price", 0)), color=sr_color, linestyle="--", linewidth=1.0, alpha=0.5)
                except (ValueError, TypeError, KeyError):
                    pass

        ax.set_ylabel(tf_name, color=TEXT_COLOR, fontsize=10, fontweight="bold")
        ax.tick_params(colors=TEXT_COLOR, labelsize=7)
        ax.set_facecolor(BG_COLOR)
        ax.grid(True, color=GRID_COLOR, linestyle=":", alpha=0.5)
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
    """Generate a BTC vs altcoin comparison chart for resonance analysis.

    Two panels side by side: BTC (left) and altcoin (right), same timeframe.

    Args:
        altcoin_symbol: Altcoin trading pair symbol.
        btc_ohlcv: BTC OHLCV data.
        altcoin_ohlcv: Altcoin OHLCV data.
        timeframe: Shared timeframe for both panels.
        annotations: Altcoin annotations (dict with boxes, S/R, etc).
        cycle_info: Dict with 'phase', 'btc_change_30d', 'volatility', 'advice'.
        output_path: Where to save PNG.

    Returns:
        dict with 'success', 'path', 'message'.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    import pandas as pd

    _cleanup_old_charts()

    annotations = annotations or {}
    cycle_info = cycle_info or {}

    if not output_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_symbol = altcoin_symbol.replace("/", "_").replace(":", "_")
        output_path = str(_ensure_tmp() / f"kairos_btc_vs_{safe_symbol}_{ts}.png")

    btc_data = _parse_ohlcv(btc_ohlcv)
    alt_data = _parse_ohlcv(altcoin_ohlcv)

    if btc_data is None or alt_data is None:
        return {"success": False, "error": "Invalid OHLCV data", "path": ""}

    phase = cycle_info.get("phase", "unknown")
    emoji = CYCLE_EMOJI.get(phase, "\U0001f4ca")

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
        closes = raw_data["closes"]
        highs = raw_data["highs"]
        lows = raw_data["lows"]
        n_bars = len(closes)

        dt_index = pd.DatetimeIndex(pd.to_datetime(raw_data["timestamps"], unit="ms", errors="coerce"))
        df = pd.DataFrame(
            {"Open": raw_data["opens"], "High": highs, "Low": lows, "Close": closes},
            index=dt_index,
        )
        df = df[df.index.notna()]
        n_valid = len(df)

        # Plot candles
        for j in range(n_valid):
            color = BULL_COLOR if df["Close"].iloc[j] >= df["Open"].iloc[j] else BEAR_COLOR
            body_bottom = min(df["Open"].iloc[j], df["Close"].iloc[j])
            body_height = abs(df["Close"].iloc[j] - df["Open"].iloc[j])
            ax.bar(j, body_height, 0.6, bottom=body_bottom, color=color, edgecolor=color, linewidth=0.5)
            ax.plot([j, j], [df["Low"].iloc[j], df["High"].iloc[j]], color=color, linewidth=0.8)

        # Annotations (for altcoin only)
        for box in annot.get("boxes", []):
            try:
                box_high = float(box.get("high", 0))
                box_low = float(box.get("low", 0))
                start_idx = int(box.get("start_idx", 0))
                end_idx = int(box.get("end_idx", n_bars - 1))
                start_idx = max(0, min(start_idx, n_valid - 1))
                end_idx = max(start_idx, min(end_idx, n_valid - 1))
                rect = mpatches.Rectangle(
                    (start_idx - 0.5, box_low),
                    end_idx - start_idx + 1,
                    box_high - box_low,
                    linewidth=1.5,
                    edgecolor="gold",
                    facecolor="green",
                    alpha=0.1,
                    linestyle="--",
                )
                ax.add_patch(rect)
            except (ValueError, TypeError, KeyError):
                pass

        for sr_list, sr_color in [
            (annot.get("support_levels", []), "lime"),
            (annot.get("resistance_levels", []), "tomato"),
        ]:
            for level in sr_list:
                try:
                    ax.axhline(y=float(level.get("price", 0)), color=sr_color, linestyle="--", linewidth=1.0, alpha=0.5)
                except (ValueError, TypeError, KeyError):
                    pass

        ax.set_ylabel(label, color=TEXT_COLOR, fontsize=10, fontweight="bold")
        ax.tick_params(colors=TEXT_COLOR, labelsize=7)
        ax.set_facecolor(BG_COLOR)
        ax.grid(True, color=GRID_COLOR, linestyle=":", alpha=0.5)

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
    """Run the Chart Generator MCP server via stdio."""
    logger.info("Starting Chart Generator MCP server")
    _ensure_tmp()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
