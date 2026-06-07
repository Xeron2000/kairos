"""Scanner-first market analysis MVP for the architecture baseline."""

from __future__ import annotations

import hashlib
import logging
from enum import Enum
from typing import Any, Callable, Mapping, Protocol

import numpy as np

from kairos.analysis.box_pattern import BoxDetector
from kairos.analysis.cycle import CycleDetector, MarketCycle
from kairos.config import KairosArchitectureConfig, load_architecture_config, load_config
from kairos.mcp_schema import make_mcp_envelope, normalize_symbol
from kairos.utils.blacklist import Blacklist
from kairos.utils.get_exchange import get_exchange

logger = logging.getLogger(__name__)

ExchangeGetter = Callable[[str], Any]


class BlacklistLike(Protocol):
    """Minimal blacklist interface used by the scanner."""

    def is_blocked(self, symbol: str) -> bool:
        """Return whether a symbol should be skipped."""
        ...


class ActionState(str, Enum):
    """Explicit scanner action states."""

    NO_TRADE = "no_trade"
    WATCH = "watch"
    PREPARE = "prepare"
    TRADE_CANDIDATE = "trade_candidate"


class Direction(str, Enum):
    """Setup direction."""

    LONG = "long"
    SHORT = "short"


class MarketScanner:
    """Deterministic scanner and setup analyzer used by MCP tools."""

    def __init__(
        self,
        config: Mapping[str, Any] | KairosArchitectureConfig | None = None,
        exchange_getter: ExchangeGetter | None = None,
        blacklist: BlacklistLike | None = None,
    ) -> None:
        self.config = config if isinstance(config, KairosArchitectureConfig) else load_architecture_config(config)
        self.exchange_getter = exchange_getter or get_exchange
        self.blacklist = blacklist or Blacklist()
        self.box_detector = BoxDetector()
        self.cycle_detector = CycleDetector()

    def scan_market(self, exchange: str | None = None) -> dict[str, Any]:
        """Run the scanner workflow across the default futures universe."""
        exchange_name = exchange or self.config.exchanges.primary
        warnings: list[str] = []
        errors: list[str] = []

        try:
            wrapper, api = self._get_exchange_api(exchange_name)
        except Exception as exc:
            logger.exception("Scanner exchange init failed: %s", exchange_name)
            return make_mcp_envelope(
                success=False,
                data={"exchange": exchange_name, "candidates": [], "setups": [], "qualified_setups": []},
                warnings=warnings,
                errors=[f"Cannot connect to {exchange_name}: {exc}"],
            )

        candidates, universe_size, discovery_warnings = self._discover_candidates(api, exchange_name)
        warnings.extend(discovery_warnings)
        if not candidates and exchange is None:
            for backup_exchange in self.config.exchanges.backups:
                try:
                    backup_wrapper, backup_api = self._get_exchange_api(backup_exchange)
                    backup_candidates, backup_universe_size, backup_warnings = self._discover_candidates(
                        backup_api, backup_exchange
                    )
                except Exception as exc:
                    warnings.append(f"{backup_exchange} backup discovery failed: {exc}")
                    continue
                warnings.extend(backup_warnings)
                if backup_candidates:
                    warnings.append(f"{exchange_name} returned no candidates; using {backup_exchange} backup universe.")
                    exchange_name = backup_exchange
                    wrapper = backup_wrapper
                    api = backup_api
                    candidates = backup_candidates
                    universe_size = backup_universe_size
                    break

        btc_context, btc_warnings = self._load_btc_context(wrapper, api)
        warnings.extend(btc_warnings)

        setups: list[dict[str, Any]] = []
        qualified_setups: list[dict[str, Any]] = []
        if btc_context is None:
            warnings.append("BTC critical context unavailable; candidates returned but trade setups withheld.")
        else:
            for candidate in candidates[: self.config.scanner.deep_analysis_limit]:
                try:
                    setup = self._analyze_candidate(wrapper, api, candidate, btc_context)
                except Exception as exc:
                    symbol = candidate.get("symbol", "unknown")
                    logger.exception("Deep analysis failed for %s", symbol)
                    errors.append(f"{symbol}: {exc}")
                    continue
                setups.append(setup)
                if setup["action_state"] == ActionState.TRADE_CANDIDATE.value:
                    qualified_setups.append(setup)

        data = {
            "exchange": exchange_name,
            "universe": {
                "source": f"{exchange_name}_futures_volume_top",
                "requested_size": self.config.scanner.universe_size,
                "actual_size": universe_size,
                "default": exchange_name == "okx",
            },
            "limits": {
                "candidate_limit": self.config.scanner.candidate_limit,
                "deep_analysis_limit": self.config.scanner.deep_analysis_limit,
                "total_timeout_seconds": self.config.scanner.total_timeout_seconds,
                "exchange_request_timeout_seconds": self.config.scanner.exchange_request_timeout_seconds,
                "symbol_analysis_timeout_seconds": self.config.scanner.symbol_analysis_timeout_seconds,
            },
            "candidates": candidates,
            "setups": setups,
            "qualified_setups": qualified_setups,
            "scanner_policy": {
                "primary_workflow": "scanner",
                "websocket_role": "candidate_hint_only",
                "charts_generated": False,
                "telegram_pushed": False,
                "execution_enabled": False,
            },
        }
        score = {
            "candidate_count": len(candidates),
            "analyzed_count": len(setups),
            "qualified_setup_count": len(qualified_setups),
        }
        if btc_context:
            score["btc_cycle"] = btc_context["cycle"]["phase"]

        return make_mcp_envelope(
            success=True,
            data=data,
            score=score,
            reasons=["scanner workflow completed with deterministic Kairos scoring"],
            warnings=warnings,
            errors=errors,
        )

    def analyze_symbol_setup(self, symbol: str, exchange: str | None = None) -> dict[str, Any]:
        """Run the high-level setup analyzer for a manually requested symbol."""
        exchange_name = exchange or self.config.exchanges.primary
        warnings: list[str] = []
        errors: list[str] = []

        try:
            canonical_symbol = normalize_symbol(symbol)
        except ValueError as exc:
            return make_mcp_envelope(
                success=False,
                data={},
                symbol=None,
                errors=[str(exc)],
            )

        try:
            wrapper, api = self._get_exchange_api(exchange_name)
        except Exception as exc:
            logger.exception("Symbol analysis exchange init failed: %s", exchange_name)
            return make_mcp_envelope(
                success=False,
                data={"exchange": exchange_name},
                symbol=canonical_symbol,
                errors=[f"Cannot connect to {exchange_name}: {exc}"],
            )

        ticker = self._fetch_ticker(api, canonical_symbol)
        quote_volume = _extract_quote_volume(ticker)
        candidate = self._score_candidate(canonical_symbol, exchange_name, ticker)
        minimum_liquidity = self.config.scoring.minimum_liquidity_quote_volume

        if quote_volume < minimum_liquidity:
            action_state = ActionState.WATCH.value if quote_volume > 0 else ActionState.NO_TRADE.value
            warning = (
                f"{canonical_symbol} quoteVolume {quote_volume:.0f} is below minimum "
                f"{minimum_liquidity:.0f}; not eligible for trade_candidate."
            )
            warnings.append(warning)
            setup = self._empty_setup(
                symbol=canonical_symbol,
                action_state=action_state,
                reasons=["minimum liquidity not satisfied"],
                warnings=[warning],
            )
            return make_mcp_envelope(
                success=True,
                symbol=canonical_symbol,
                data={"exchange": exchange_name, "candidate": candidate, "setup": setup},
                score={"candidate_score": candidate["candidate_score"], "setup_score": 0.0},
                reasons=["manual symbol analysis completed with liquidity gate"],
                warnings=warnings,
                errors=errors,
            )

        btc_context, btc_warnings = self._load_btc_context(wrapper, api)
        warnings.extend(btc_warnings)
        if btc_context is None:
            setup = self._empty_setup(
                symbol=canonical_symbol,
                action_state=ActionState.WATCH.value,
                reasons=["BTC context is required before a trade candidate can be returned"],
                warnings=btc_warnings,
            )
        else:
            try:
                setup = self._analyze_candidate(wrapper, api, candidate, btc_context)
            except Exception as exc:
                logger.exception("Symbol setup analysis failed for %s", canonical_symbol)
                errors.append(str(exc))
                setup = self._empty_setup(
                    symbol=canonical_symbol,
                    action_state=ActionState.NO_TRADE.value,
                    reasons=["symbol setup analysis failed"],
                    warnings=[],
                )

        return make_mcp_envelope(
            success=True,
            symbol=canonical_symbol,
            data={"exchange": exchange_name, "candidate": candidate, "setup": setup},
            score={
                "candidate_score": candidate["candidate_score"],
                "setup_score": setup.get("setup_score", 0.0),
                "threshold": setup.get("threshold"),
            },
            reasons=["manual symbol analysis completed with deterministic Kairos scoring"],
            warnings=_dedupe_strings(warnings + setup.get("warnings", [])),
            errors=errors,
        )

    def _get_exchange_api(self, exchange_name: str) -> tuple[Any, Any]:
        wrapper = self.exchange_getter(exchange_name)
        return wrapper, getattr(wrapper, "exchange", wrapper)

    def _discover_candidates(self, api: Any, exchange_name: str) -> tuple[list[dict[str, Any]], int, list[str]]:
        warnings: list[str] = []
        tickers = self._fetch_tickers(api)
        if not tickers:
            return [], 0, [f"{exchange_name} did not return ticker data."]

        universe: list[dict[str, Any]] = []
        for raw_symbol, ticker in tickers.items():
            if not isinstance(raw_symbol, str) or not isinstance(ticker, Mapping):
                continue
            if not _looks_like_usdt_perpetual(raw_symbol, ticker):
                continue
            try:
                symbol = normalize_symbol(raw_symbol)
            except ValueError:
                continue
            if self.blacklist.is_blocked(symbol):
                continue

            quote_volume = _extract_quote_volume(ticker)
            if quote_volume <= 0:
                warnings.append(f"{symbol} missing quoteVolume; skipped from volume Top universe.")
                continue

            universe.append(
                {
                    "symbol": symbol,
                    "ticker": ticker,
                    "quote_volume_24h": quote_volume,
                }
            )

        universe.sort(key=lambda item: item["quote_volume_24h"], reverse=True)
        top_universe = universe[: self.config.scanner.universe_size]
        scored = [self._score_candidate(item["symbol"], exchange_name, item["ticker"]) for item in top_universe]
        scored.sort(key=lambda item: (item["candidate_score"], item["quote_volume_24h"]), reverse=True)
        return scored[: self.config.scanner.candidate_limit], len(top_universe), warnings

    def _fetch_tickers(self, api: Any) -> dict[str, Any]:
        fetch_tickers = getattr(api, "fetch_tickers", None)
        if callable(fetch_tickers):
            try:
                tickers = fetch_tickers()
            except Exception as exc:
                logger.warning("Failed to fetch tickers: %s", exc)
                return {}
            if isinstance(tickers, dict):
                return tickers
        return {}

    def _fetch_ticker(self, api: Any, symbol: str) -> Mapping[str, Any]:
        fetch_ticker = getattr(api, "fetch_ticker", None)
        if callable(fetch_ticker):
            try:
                ticker = fetch_ticker(symbol)
            except Exception as exc:
                logger.warning("Failed to fetch ticker for %s: %s", symbol, exc)
                return {}
            if isinstance(ticker, Mapping):
                return ticker
        return {}

    def _fetch_ohlcv(self, wrapper: Any, api: Any, symbol: str, timeframe: str, limit: int) -> dict[str, np.ndarray] | None:
        fetch_ohlcv = getattr(api, "fetch_ohlcv", None)
        if not callable(fetch_ohlcv):
            return None

        params_provider = getattr(wrapper, "_get_ohlcv_params", None)
        params = params_provider(symbol) if callable(params_provider) else {}
        try:
            raw = fetch_ohlcv(symbol, timeframe, limit=limit, params=params)
        except TypeError:
            try:
                raw = fetch_ohlcv(symbol, timeframe, limit=limit)
            except Exception as exc:
                logger.warning("Failed to fetch OHLCV for %s %s: %s", symbol, timeframe, exc)
                return None
        except Exception as exc:
            logger.warning("Failed to fetch OHLCV for %s %s: %s", symbol, timeframe, exc)
            return None
        return _ohlcv_to_arrays(raw)

    def _score_candidate(self, symbol: str, exchange_name: str, ticker: Mapping[str, Any]) -> dict[str, Any]:
        quote_volume = _extract_quote_volume(ticker)
        last_price = _extract_last_price(ticker)
        change_pct = _extract_change_pct(ticker)
        open_interest = _extract_open_interest(ticker)
        funding_rate = _extract_funding_rate(ticker)
        weights = self.config.scoring.candidate_weights
        minimum_liquidity = self.config.scoring.minimum_liquidity_quote_volume

        score = 0.0
        reasons: list[str] = []
        warnings: list[str] = []

        if quote_volume > 0:
            volume_ratio = quote_volume / minimum_liquidity
            volume_component = min(weights.get("quoteVolume", 4.0), weights.get("quoteVolume", 4.0) * min(volume_ratio, 4.0) / 4.0)
            score += volume_component
            reasons.append(f"quote volume component={volume_component:.2f}")
        else:
            warnings.append("missing quoteVolume")

        if change_pct is not None:
            velocity_component = min(weights.get("priceVelocity", 2.0), abs(change_pct) / 5.0 * weights.get("priceVelocity", 2.0))
            score += velocity_component
            reasons.append(f"24h change component={velocity_component:.2f}")
            if change_pct > 0:
                rs_component = min(weights.get("relativeStrength", 2.0), change_pct / 8.0 * weights.get("relativeStrength", 2.0))
                score += max(0.0, rs_component)
                if rs_component > 0:
                    reasons.append(f"relative strength component={rs_component:.2f}")
        else:
            warnings.append("missing 24h percentage change")

        if open_interest is not None and open_interest > 0:
            score += min(weights.get("openInterest", 1.0), weights.get("openInterest", 1.0) * 0.5)
            reasons.append("open interest available")
        else:
            warnings.append("missing open interest data; confidence degraded")

        if funding_rate is not None:
            funding_component = weights.get("funding", 1.0) * 0.5
            if abs(funding_rate) > 0.001:
                warnings.append("funding rate is elevated; crowded positioning risk")
                funding_component *= 0.5
            score += funding_component
            reasons.append(f"funding component={funding_component:.2f}")
        else:
            warnings.append("missing funding data; confidence degraded")

        return {
            "symbol": symbol,
            "exchange": exchange_name,
            "quote_volume_24h": round(quote_volume, 2),
            "last_price": last_price,
            "change_24h_pct": change_pct,
            "candidate_score": round(min(score, 10.0), 2),
            "score_reasons": reasons,
            "warnings": warnings,
        }

    def _load_btc_context(self, wrapper: Any, api: Any) -> tuple[dict[str, Any] | None, list[str]]:
        warnings: list[str] = []
        btc_symbol = normalize_symbol("BTC/USDT")
        ohlcv = self._fetch_ohlcv(wrapper, api, btc_symbol, "1d", 100)
        if not ohlcv or len(ohlcv["closes"]) < 30:
            return None, ["BTC 1d OHLCV unavailable or insufficient; setup scoring withheld."]

        cycle = self.cycle_detector.detect_phase(
            btc_prices=ohlcv["closes"],
            btc_volumes=ohlcv["volumes"],
        )
        if cycle.confidence < 0.4:
            warnings.append("BTC cycle confidence is low; setup confidence degraded.")
        return {
            "symbol": btc_symbol,
            "ohlcv": ohlcv,
            "cycle": _cycle_to_dict(cycle),
        }, warnings

    def _analyze_candidate(
        self,
        wrapper: Any,
        api: Any,
        candidate: Mapping[str, Any],
        btc_context: Mapping[str, Any],
    ) -> dict[str, Any]:
        symbol = str(candidate["symbol"])
        warnings: list[str] = []
        timeframe_data: dict[str, dict[str, np.ndarray]] = {}

        for timeframe in self.config.scanner.timeframes:
            limit = 120 if timeframe in {"4h", "15m"} else 100
            ohlcv = self._fetch_ohlcv(wrapper, api, symbol, timeframe, limit)
            if not ohlcv or len(ohlcv["closes"]) < 30:
                warnings.append(f"{timeframe} OHLCV unavailable or insufficient")
                continue
            timeframe_data[timeframe] = ohlcv

        missing = [timeframe for timeframe in self.config.scanner.timeframes if timeframe not in timeframe_data]
        if missing:
            return self._empty_setup(
                symbol=symbol,
                action_state=ActionState.WATCH.value,
                reasons=[f"missing required timeframes: {', '.join(missing)}"],
                warnings=warnings,
            )

        current_price = float(timeframe_data["15m"]["closes"][-1])
        daily_trend = _trend(timeframe_data["1d"])
        structure = self._structure(symbol, "4h", timeframe_data["4h"], current_price)
        volume_confirmed = _volume_confirmed(timeframe_data["15m"])

        long_setup = self._score_direction(
            Direction.LONG,
            symbol,
            candidate,
            daily_trend,
            structure,
            current_price,
            volume_confirmed,
            btc_context,
        )
        short_setup = self._score_direction(
            Direction.SHORT,
            symbol,
            candidate,
            daily_trend,
            structure,
            current_price,
            volume_confirmed,
            btc_context,
        )
        setup = max([long_setup, short_setup], key=lambda item: item["setup_score"])
        setup["warnings"].extend(warnings)
        return setup

    def _structure(
        self,
        symbol: str,
        timeframe: str,
        ohlcv: Mapping[str, np.ndarray],
        current_price: float,
    ) -> dict[str, Any]:
        try:
            boxes = self.box_detector.detect(
                symbol=symbol,
                timeframe=timeframe,
                highs=ohlcv["highs"],
                lows=ohlcv["lows"],
                closes=ohlcv["closes"],
                volumes=ohlcv["volumes"],
                timestamps=ohlcv["timestamps"],
            )
        except Exception:
            boxes = []

        if boxes:
            box = boxes[-1]
            return {
                "type": "box",
                "source": "box_detector",
                "timeframe": timeframe,
                "high": float(box.high),
                "low": float(box.low),
                "height": float(box.height),
                "height_pct": float(box.height_pct),
                "status": box.status.value,
                "ready": bool(box.is_ready),
                "current_price": current_price,
            }

        highs = ohlcv["highs"][-40:]
        lows = ohlcv["lows"][-40:]
        high = float(np.max(highs))
        low = float(np.min(lows))
        height = high - low
        height_pct = height / low * 100 if low > 0 else 0.0
        ready = 1.0 <= height_pct <= 15.0
        return {
            "type": "range",
            "source": "recent_range",
            "timeframe": timeframe,
            "high": high,
            "low": low,
            "height": height,
            "height_pct": height_pct,
            "status": "range_ready" if ready else "range_unusable",
            "ready": ready,
            "current_price": current_price,
        }

    def _score_direction(
        self,
        direction: Direction,
        symbol: str,
        candidate: Mapping[str, Any],
        daily_trend: str,
        structure: Mapping[str, Any],
        current_price: float,
        volume_confirmed: bool,
        btc_context: Mapping[str, Any],
    ) -> dict[str, Any]:
        score = 0.0
        reasons: list[str] = []
        warnings: list[str] = []
        weights = self.config.scoring.setup_weights
        cycle = btc_context["cycle"]
        phase = str(cycle["phase"])
        btc_trend = str(cycle["btc_trend"])

        if (direction == Direction.LONG and daily_trend == "up") or (direction == Direction.SHORT and daily_trend == "down"):
            score += weights.get("dailyTrend", 1.5)
            reasons.append(f"1d trend supports {direction.value}")
        elif daily_trend == "sideways":
            score += weights.get("dailyTrend", 1.5) * 0.4
            reasons.append("1d trend is sideways")
        else:
            warnings.append(f"1d trend conflicts with {direction.value}")

        if structure["ready"]:
            score += weights.get("structure", 2.0)
            reasons.append(f"4h {structure['type']} structure is usable")
        else:
            warnings.append("4h structure is not usable")

        risk = self._risk_bounds(direction, symbol, structure, current_price, phase, btc_trend)
        if risk["triggered"]:
            score += weights.get("entryTrigger", 2.0)
            reasons.append("15m trigger is active near structure boundary")
        elif risk["near_trigger"]:
            score += weights.get("entryTrigger", 2.0) * 0.5
            reasons.append("15m price is near trigger; prepare only")

        btc_supports = (direction == Direction.LONG and btc_trend == "up") or (
            direction == Direction.SHORT and btc_trend == "down"
        )
        if symbol.startswith("BTC/"):
            score += weights.get("btcResonance", 1.0)
            reasons.append("BTC setup has no separate BTC resonance requirement")
        elif btc_supports:
            score += weights.get("btcResonance", 1.0)
            reasons.append("BTC resonance supports direction")
        elif btc_trend == "sideways":
            score += weights.get("btcResonance", 1.0) * 0.4
            warnings.append("BTC resonance is neutral")
        else:
            warnings.append("BTC resonance conflicts with setup direction")

        cycle_component = self._cycle_component(direction, phase)
        score += cycle_component
        if cycle_component > 0:
            reasons.append(f"cycle component={cycle_component:.2f}")
        else:
            warnings.append(f"{phase} cycle does not support {direction.value}")

        if volume_confirmed:
            score += weights.get("volumeConfirmation", 1.0)
            reasons.append("15m volume confirms move")
        else:
            warnings.append("15m volume confirmation missing")

        required_rr = self._required_rr(direction, phase, btc_trend)
        if risk["risk_reward"] >= required_rr:
            score += weights.get("riskReward", 1.5)
            reasons.append(f"risk/reward {risk['risk_reward']:.2f} meets requirement {required_rr:.2f}")
        elif risk["risk_reward"] > 0:
            score += weights.get("riskReward", 1.5) * 0.25
            warnings.append(f"risk/reward {risk['risk_reward']:.2f} below requirement {required_rr:.2f}")
        else:
            warnings.append("structural stop or target unavailable")

        threshold = self._threshold(direction, phase, btc_trend)
        setup_score = round(min(score, 10.0), 2)
        action_state = self._action_state(
            setup_score=setup_score,
            threshold=threshold,
            risk_reward=risk["risk_reward"],
            required_rr=required_rr,
            triggered=bool(risk["triggered"]),
            near_trigger=bool(risk["near_trigger"]),
            candidate_score=float(candidate.get("candidate_score", 0.0)),
        )
        if action_state != ActionState.TRADE_CANDIDATE.value and setup_score >= threshold:
            warnings.append("score threshold met but trigger/RR requirements block trade_candidate")

        setup_type = f"{structure['type']}_{'breakout' if direction == Direction.LONG else 'breakdown'}"
        fingerprint = self._fingerprint(symbol, direction.value, setup_type, structure, risk)
        return {
            "symbol": symbol,
            "direction": direction.value,
            "setup_type": setup_type,
            "action_state": action_state,
            "setup_score": setup_score,
            "threshold": threshold,
            "required_risk_reward": required_rr,
            "structure": dict(structure),
            "risk": risk,
            "chart_spec": self._chart_spec(symbol, setup_score, setup_type),
            "fingerprint": fingerprint,
            "reasons": reasons,
            "warnings": warnings,
            "execution": {"enabled": False},
        }

    def _risk_bounds(
        self,
        direction: Direction,
        symbol: str,
        structure: Mapping[str, Any],
        current_price: float,
        phase: str,
        btc_trend: str,
    ) -> dict[str, Any]:
        high = float(structure["high"])
        low = float(structure["low"])
        height = float(structure["height"])
        symbol_class = "major" if symbol.startswith(("BTC/", "ETH/")) else "altcoin"
        max_position_pct = self.config.risk.max_position_pct.get(symbol_class, 33.0)
        max_leverage = self.config.risk.max_leverage.get(symbol_class, 5.0)

        if phase in {"autumn", "winter"}:
            max_position_pct *= self.config.risk.weak_cycle_position_multiplier
        if direction == Direction.SHORT:
            max_position_pct *= self.config.risk.short_position_multiplier
            if btc_trend != "down":
                max_leverage = min(max_leverage, 3.0)

        if direction == Direction.LONG:
            entry_zone = [high, high * 1.003]
            entry_mid = sum(entry_zone) / 2
            stop = low * 0.995
            targets = [high + height, high + 2 * height]
            risk = entry_mid - stop
            triggered = current_price >= high * 1.003
            near_trigger = current_price >= high * 0.99
            invalidation = "long setup invalid below 4h structure low"
        else:
            entry_zone = [low * 0.997, low]
            entry_mid = sum(entry_zone) / 2
            stop = high * 1.005
            targets = [low - height, low - 2 * height]
            risk = stop - entry_mid
            triggered = current_price <= low * 0.997
            near_trigger = current_price <= low * 1.01
            invalidation = "short setup invalid above 4h structure high"

        valid_targets = [round(float(value), 8) for value in targets if value > 0]
        risk_reward_target = valid_targets[-1] if valid_targets else None
        if risk_reward_target is None:
            reward = 0.0
        elif direction == Direction.LONG:
            reward = risk_reward_target - entry_mid
        else:
            reward = entry_mid - risk_reward_target
        rr = reward / risk if risk > 0 and reward > 0 else 0.0
        return {
            "max_position_pct": round(max_position_pct, 2),
            "max_leverage": round(max_leverage, 2),
            "entry_zone": [round(float(value), 8) for value in entry_zone],
            "structural_stop": round(float(stop), 8),
            "targets": valid_targets,
            "risk_reward": round(float(rr), 2),
            "risk_reward_target": risk_reward_target,
            "invalidation": invalidation,
            "triggered": triggered,
            "near_trigger": near_trigger,
            "account_sizing": False,
        }

    def _cycle_component(self, direction: Direction, phase: str) -> float:
        weight = self.config.scoring.setup_weights.get("marketCycle", 1.0)
        if direction == Direction.LONG and phase in {"spring", "summer"}:
            return weight
        if direction == Direction.SHORT and phase == "winter":
            return weight
        if phase == "autumn":
            return weight * 0.4
        return 0.0

    def _required_rr(self, direction: Direction, phase: str, btc_trend: str) -> float:
        if direction == Direction.SHORT and (phase != "winter" or btc_trend != "down"):
            return self.config.scoring.strict_risk_reward
        if phase == "winter" and direction == Direction.LONG:
            return self.config.scoring.strict_risk_reward
        return self.config.scoring.minimum_risk_reward

    def _threshold(self, direction: Direction, phase: str, btc_trend: str) -> float:
        threshold = self.config.scoring.cycle_thresholds.get(phase, self.config.scoring.cycle_thresholds["winter"])
        if direction == Direction.SHORT and btc_trend != "down":
            threshold += self.config.scoring.short_threshold_premium
        return threshold

    def _action_state(
        self,
        *,
        setup_score: float,
        threshold: float,
        risk_reward: float,
        required_rr: float,
        triggered: bool,
        near_trigger: bool,
        candidate_score: float,
    ) -> str:
        if setup_score >= threshold and risk_reward >= required_rr and triggered:
            return ActionState.TRADE_CANDIDATE.value
        if setup_score >= threshold - 1.0 and near_trigger:
            return ActionState.PREPARE.value
        if candidate_score >= 2.0:
            return ActionState.WATCH.value
        return ActionState.NO_TRADE.value

    def _chart_spec(self, symbol: str, setup_score: float, setup_type: str) -> dict[str, Any]:
        timeframes = ["15m"]
        if setup_score >= self.config.charts.multi_timeframe_score_threshold or "range" not in setup_type:
            timeframes = ["1d", "4h", "15m"]
        return {
            "symbol": symbol,
            "timeframes": timeframes,
            "default_chart_count": self.config.charts.default_chart_count,
            "overlays": ["structure", "entry_zone", "structural_stop", "targets"],
            "generate_now": self.config.scanner.generate_charts_by_default,
            "output_path": self.config.charts.output_path,
        }

    def _fingerprint(
        self,
        symbol: str,
        direction: str,
        setup_type: str,
        structure: Mapping[str, Any],
        risk: Mapping[str, Any],
    ) -> str:
        payload = "|".join(
            [
                symbol,
                direction,
                setup_type,
                str(structure.get("timeframe", "")),
                f"{float(structure.get('high', 0.0)):.8f}",
                f"{float(structure.get('low', 0.0)):.8f}",
                ",".join(str(value) for value in risk.get("entry_zone", [])),
                str(risk.get("structural_stop", "")),
                ",".join(str(value) for value in risk.get("targets", [])),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    def _empty_setup(
        self,
        *,
        symbol: str,
        action_state: str,
        reasons: list[str],
        warnings: list[str],
    ) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "direction": None,
            "setup_type": None,
            "action_state": action_state,
            "setup_score": 0.0,
            "threshold": None,
            "required_risk_reward": None,
            "structure": {},
            "risk": {
                "max_position_pct": 0.0,
                "max_leverage": 0.0,
                "entry_zone": [],
                "structural_stop": None,
                "targets": [],
                "risk_reward": 0.0,
                "risk_reward_target": None,
                "invalidation": None,
                "triggered": False,
                "near_trigger": False,
                "account_sizing": False,
            },
            "chart_spec": self._chart_spec(symbol, 0.0, "none"),
            "fingerprint": "",
            "reasons": reasons,
            "warnings": warnings,
            "execution": {"enabled": False},
        }


def scan_market(
    config: Mapping[str, Any] | KairosArchitectureConfig | None = None,
    exchange_getter: ExchangeGetter | None = None,
    exchange: str | None = None,
    blacklist: BlacklistLike | None = None,
) -> dict[str, Any]:
    """Public callable used by MCP and tests."""
    raw_config = load_config() if config is None else config
    return MarketScanner(raw_config, exchange_getter=exchange_getter, blacklist=blacklist).scan_market(exchange=exchange)


def analyze_symbol_setup(
    symbol: str,
    config: Mapping[str, Any] | KairosArchitectureConfig | None = None,
    exchange_getter: ExchangeGetter | None = None,
    exchange: str | None = None,
    blacklist: BlacklistLike | None = None,
) -> dict[str, Any]:
    """Public callable used by MCP and tests."""
    raw_config = load_config() if config is None else config
    return MarketScanner(raw_config, exchange_getter=exchange_getter, blacklist=blacklist).analyze_symbol_setup(
        symbol, exchange=exchange
    )


def _looks_like_usdt_perpetual(symbol: str, ticker: Mapping[str, Any]) -> bool:
    if "/USDT:USDT" in symbol and symbol.endswith(":USDT"):
        return True
    info = ticker.get("info", {})
    if isinstance(info, Mapping):
        inst_type = str(info.get("instType", "")).upper()
        contract_type = str(info.get("contractType", "")).upper()
        return inst_type in {"SWAP", "PERPETUAL"} or contract_type in {"SWAP", "PERPETUAL"}
    return False


def _ohlcv_to_arrays(raw: Any) -> dict[str, np.ndarray] | None:
    if raw is None:
        return None
    try:
        data = np.array(raw, dtype=float)
    except (TypeError, ValueError):
        return None
    if data.ndim != 2 or data.shape[0] == 0 or data.shape[1] < 6:
        return None
    return {
        "timestamps": data[:, 0],
        "opens": data[:, 1],
        "highs": data[:, 2],
        "lows": data[:, 3],
        "closes": data[:, 4],
        "volumes": data[:, 5],
    }


def _extract_quote_volume(ticker: Mapping[str, Any]) -> float:
    direct = _first_float(ticker, ["quoteVolume", "quoteVolume24h", "turnover", "turnover24h"])
    if direct is not None:
        return direct
    info = ticker.get("info", {})
    if isinstance(info, Mapping):
        nested = _first_float(info, ["volCcy24h", "volumeCcy24h", "quoteVolume", "turnover24h"])
        if nested is not None:
            return nested
    base_volume = _first_float(ticker, ["baseVolume", "volume"])
    price = _extract_last_price(ticker)
    return base_volume * price if base_volume is not None and price is not None else 0.0


def _extract_last_price(ticker: Mapping[str, Any]) -> float | None:
    value = _first_float(ticker, ["last", "close", "markPrice", "lastPrice"])
    if value is not None:
        return value
    info = ticker.get("info", {})
    if isinstance(info, Mapping):
        return _first_float(info, ["last", "lastPrice", "markPx", "idxPx"])
    return None


def _extract_change_pct(ticker: Mapping[str, Any]) -> float | None:
    value = _first_float(ticker, ["percentage", "changePercentage", "changePct"])
    if value is not None:
        return value
    open_price = _first_float(ticker, ["open"])
    last_price = _extract_last_price(ticker)
    if open_price and last_price:
        return (last_price / open_price - 1.0) * 100.0
    return None


def _extract_open_interest(ticker: Mapping[str, Any]) -> float | None:
    value = _first_float(ticker, ["openInterest"])
    if value is not None:
        return value
    info = ticker.get("info", {})
    if isinstance(info, Mapping):
        return _first_float(info, ["openInterest", "oi", "openInterestValue"])
    return None


def _extract_funding_rate(ticker: Mapping[str, Any]) -> float | None:
    value = _first_float(ticker, ["fundingRate"])
    if value is not None:
        return value
    info = ticker.get("info", {})
    if isinstance(info, Mapping):
        return _first_float(info, ["fundingRate", "funding_rate"])
    return None


def _first_float(mapping: Mapping[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = mapping.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _trend(ohlcv: Mapping[str, np.ndarray]) -> str:
    closes = ohlcv["closes"]
    if len(closes) < 20:
        return "sideways"
    recent_mean = float(np.mean(closes[-20:]))
    current = float(closes[-1])
    if current > recent_mean * 1.005:
        return "up"
    if current < recent_mean * 0.995:
        return "down"
    return "sideways"


def _volume_confirmed(ohlcv: Mapping[str, np.ndarray]) -> bool:
    volumes = ohlcv["volumes"]
    if len(volumes) < 20:
        return False
    recent = float(volumes[-1])
    baseline = float(np.mean(volumes[-20:-1]))
    return baseline > 0 and recent >= baseline * 1.2


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _cycle_to_dict(cycle: MarketCycle) -> dict[str, Any]:
    return {
        "phase": cycle.phase.value,
        "confidence": cycle.confidence,
        "btc_trend": cycle.btc_trend,
        "btc_change_30d": cycle.btc_change_30d,
        "btc_change_7d": cycle.btc_change_7d,
        "volatility": cycle.volatility,
        "volume_trend": cycle.volume_trend,
        "funding_rates_avg": cycle.funding_rates_avg,
    }
