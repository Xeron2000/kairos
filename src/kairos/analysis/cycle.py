"""Market cycle detection based on Bit浪浪's spring/summer/autumn/winter theory."""

import logging
from dataclasses import dataclass
from enum import Enum

import numpy as np


class MarketPhase(str, Enum):
    """Market phases (春夏秋冬)."""
    SPRING = "spring"  # 牛市初期，行情启动
    SUMMER = "summer"  # 主升浪狂热期
    AUTUMN = "autumn"  # 高位震荡，补涨期
    WINTER = "winter"  # 下跌与无序震荡期


@dataclass
class MarketCycle:
    """Represents current market cycle state."""
    phase: MarketPhase
    confidence: float  # 0-1 confidence in phase detection
    btc_trend: str  # "up", "down", "sideways"
    btc_change_30d: float  # BTC 30-day change %
    btc_change_7d: float  # BTC 7-day change %
    volatility: float  # Current volatility (ATR %)
    volume_trend: str  # "increasing", "decreasing", "stable"
    altcoin_correlation: float  # How correlated altcoins are with BTC
    funding_rates_avg: float  # Average funding rates
    market_cap_change_30d: float  # Total market cap 30-day change %

    @property
    def description(self) -> str:
        """Human-readable description of the phase."""
        descriptions = {
            MarketPhase.SPRING: "行情启动期，百花齐放，开始试仓",
            MarketPhase.SUMMER: "主升浪狂热期，聚焦龙头，重仓出击",
            MarketPhase.AUTUMN: "高位震荡期，补涨行情，收缩防守",
            MarketPhase.WINTER: "下跌震荡期，空仓冬眠，管住手"
        }
        return descriptions.get(self.phase, "未知")

    @property
    def position_advice(self) -> str:
        """Position sizing advice."""
        advice = {
            MarketPhase.SPRING: "开始建仓，正常杠杆",
            MarketPhase.SUMMER: "重仓出击，激进杠杆",
            MarketPhase.AUTUMN: "轻仓防守，保守杠杆",
            MarketPhase.WINTER: "空仓等待，无杠杆"
        }
        return advice.get(self.phase, "观望")


class CycleDetector:
    """Detects market cycle phase using quantitative indicators."""

    def __init__(self, config: dict | None = None):
        self.logger = logging.getLogger("kairos.analysis.cycle")
        config = config or {}

        # Thresholds for phase detection
        self.spring_btc_change_min = config.get("springBtcChangeMin", 10)  # BTC up 10%+ from bottom
        self.summer_btc_change_min = config.get("summerBtcChangeMin", 30)  # BTC up 30%+
        self.autumn_btc_change_max = config.get("autumnBtcChangeMax", 50)  # BTC up 50%+ but stalling
        self.winter_btc_change_max = config.get("winterBtcChangeMax", -10)  # BTC down 10%+

        self.high_volatility_threshold = config.get("highVolatilityThreshold", 5)  # ATR > 5%
        self.low_volatility_threshold = config.get("lowVolatilityThreshold", 2)  # ATR < 2%

        self.high_funding_threshold = config.get("highFundingThreshold", 0.05)  # 0.05% per 8h = ~55% annualized
        self.low_funding_threshold = config.get("lowFundingThreshold", -0.01)  # Negative funding

    def detect_phase(
        self,
        btc_prices: np.ndarray,
        btc_volumes: np.ndarray,
        altcoin_correlation: float = 0.8,
        avg_funding_rate: float = 0.01,
        total_market_cap_change_30d: float = 0
    ) -> MarketCycle:
        """Detect current market phase."""
        if len(btc_prices) < 30:
            return self._default_cycle()

        # Calculate metrics
        btc_change_7d = self._calculate_change(btc_prices, 7)
        btc_change_30d = self._calculate_change(btc_prices, 30)
        volatility = self._calculate_volatility(btc_prices)
        volume_trend = self._calculate_volume_trend(btc_volumes)
        btc_trend = self._determine_trend(btc_prices)

        # Phase detection logic
        phase, confidence = self._determine_phase(
            btc_change_7d, btc_change_30d, volatility,
            volume_trend, altcoin_correlation, avg_funding_rate,
            total_market_cap_change_30d
        )

        return MarketCycle(
            phase=phase,
            confidence=confidence,
            btc_trend=btc_trend,
            btc_change_30d=btc_change_30d,
            btc_change_7d=btc_change_7d,
            volatility=volatility,
            volume_trend=volume_trend,
            altcoin_correlation=altcoin_correlation,
            funding_rates_avg=avg_funding_rate,
            market_cap_change_30d=total_market_cap_change_30d
        )

    def _calculate_change(self, prices: np.ndarray, days: int) -> float:
        """Calculate price change over N days."""
        if len(prices) < days:
            return 0
        return ((prices[-1] - prices[-days]) / prices[-days]) * 100

    def _calculate_volatility(self, prices: np.ndarray, period: int = 14) -> float:
        """Calculate ATR-like volatility as percentage."""
        if len(prices) < period + 1:
            return 0

        # Simple daily returns volatility
        returns = np.diff(prices) / prices[:-1]
        return np.std(returns[-period:]) * 100 * np.sqrt(365)  # Annualized

    def _calculate_volume_trend(self, volumes: np.ndarray, period: int = 7) -> str:
        """Determine volume trend."""
        if len(volumes) < period * 2:
            return "stable"

        recent_avg = np.mean(volumes[-period:])
        prior_avg = np.mean(volumes[-period*2:-period])

        if recent_avg > prior_avg * 1.2:
            return "increasing"
        elif recent_avg < prior_avg * 0.8:
            return "decreasing"
        return "stable"

    def _determine_trend(self, prices: np.ndarray, period: int = 20) -> str:
        """Determine price trend."""
        if len(prices) < period:
            return "sideways"

        # Simple trend based on slope of recent prices
        recent = prices[-period:]
        slope = np.polyfit(range(len(recent)), recent, 1)[0]

        if slope > prices[-1] * 0.001:  # Upward slope
            return "up"
        elif slope < -prices[-1] * 0.001:  # Downward slope
            return "down"
        return "sideways"

    def _determine_phase(
        self,
        btc_7d: float,
        btc_30d: float,
        volatility: float,
        volume_trend: str,
        altcoin_corr: float,
        funding_rate: float,
        mcap_change_30d: float
    ) -> tuple[MarketPhase, float]:
        """Determine market phase based on indicators."""
        scores = {
            MarketPhase.SPRING: 0,
            MarketPhase.SUMMER: 0,
            MarketPhase.AUTUMN: 0,
            MarketPhase.WINTER: 0
        }

        # BTC 30-day change signals
        if btc_30d > self.summer_btc_change_min:
            scores[MarketPhase.SUMMER] += 2
            scores[MarketPhase.AUTUMN] += 1
        elif btc_30d > self.spring_btc_change_min:
            scores[MarketPhase.SPRING] += 2
            scores[MarketPhase.SUMMER] += 1
        elif btc_30d < self.winter_btc_change_max:
            scores[MarketPhase.WINTER] += 2
        else:
            scores[MarketPhase.AUTUMN] += 1
            scores[MarketPhase.WINTER] += 1

        # Recent momentum (7d)
        if btc_7d > 10:
            scores[MarketPhase.SUMMER] += 1
        elif btc_7d > 5:
            scores[MarketPhase.SPRING] += 1
        elif btc_7d < -10:
            scores[MarketPhase.WINTER] += 2

        # Volatility signals
        if volatility > self.high_volatility_threshold:
            scores[MarketPhase.SUMMER] += 1
            scores[MarketPhase.WINTER] += 1
        elif volatility < self.low_volatility_threshold:
            scores[MarketPhase.AUTUMN] += 1

        # Volume trend
        if volume_trend == "increasing":
            scores[MarketPhase.SPRING] += 1
            scores[MarketPhase.SUMMER] += 1
        elif volume_trend == "decreasing":
            scores[MarketPhase.AUTUMN] += 1
            scores[MarketPhase.WINTER] += 1

        # Funding rates (high positive = overheated)
        if funding_rate > self.high_funding_threshold:
            scores[MarketPhase.SUMMER] += 1
            scores[MarketPhase.AUTUMN] += 1
        elif funding_rate < self.low_funding_threshold:
            scores[MarketPhase.WINTER] += 1

        # Altcoin correlation (high = still in trend, low = rotation)
        if altcoin_corr > 0.8:
            scores[MarketPhase.SPRING] += 1
            scores[MarketPhase.SUMMER] += 1
        elif altcoin_corr < 0.5:
            scores[MarketPhase.AUTUMN] += 1  # Rotation/补涨

        # Find phase with highest score
        phase = max(scores, key=scores.get)
        total = sum(scores.values())
        confidence = scores[phase] / total if total > 0 else 0

        return phase, round(confidence, 2)

    def _default_cycle(self) -> MarketCycle:
        """Return default cycle when insufficient data."""
        return MarketCycle(
            phase=MarketPhase.WINTER,
            confidence=0.5,
            btc_trend="sideways",
            btc_change_30d=0,
            btc_change_7d=0,
            volatility=0,
            volume_trend="stable",
            altcoin_correlation=0,
            funding_rates_avg=0,
            market_cap_change_30d=0
        )
