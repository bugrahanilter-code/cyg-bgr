"""Market Regime Engine.

The regime is computed once, centrally, and handed to the strategies. It is
deliberately NOT embedded inside a strategy: several strategies need the same
answer, and a shared definition makes the behaviour reproducible and testable.

Measurements used (all standard, all causal):

* ADX          - trend strength
* EMA stack    - trend direction
* ATR / price  - normalised volatility
* percentile   - is the current volatility unusual for THIS market?
* realised vol - annualised volatility of log returns
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.core.constants import MarketRegime, TrendRegime, VolatilityRegime
from app.indicators import adx, atr, ema, percentile_rank, realized_volatility, safe_float


class RegimeConfig(BaseModel):
    """Tunable thresholds for the regime classifier."""

    adx_period: int = Field(default=14, ge=5, le=100)
    adx_trend_threshold: float = Field(default=22.0, ge=5.0, le=60.0)
    fast_ema: int = Field(default=50, ge=5, le=400)
    slow_ema: int = Field(default=200, ge=10, le=1000)
    atr_period: int = Field(default=14, ge=5, le=100)
    volatility_lookback: int = Field(default=100, ge=20, le=1000)
    low_volatility_percentile: float = Field(default=0.25, ge=0.0, le=1.0)
    high_volatility_percentile: float = Field(default=0.80, ge=0.0, le=1.0)
    extreme_volatility_percentile: float = Field(default=0.97, ge=0.0, le=1.0)
    extreme_atr_pct: float = Field(
        default=8.0,
        ge=0.5,
        le=100.0,
        description="Absolute ATR percentage that is extreme on its own",
    )
    high_volatility_ratio: float = Field(
        default=1.5,
        ge=1.0,
        le=10.0,
        description="Current ATR percentage divided by its own median, for HIGH",
    )
    extreme_volatility_ratio: float = Field(
        default=2.5,
        ge=1.0,
        le=20.0,
        description="Current ATR percentage divided by its own median, for EXTREME",
    )
    realized_vol_period: int = Field(default=30, ge=5, le=500)


DEFAULT_REGIME_CONFIG = RegimeConfig()

REGIME_COLUMNS = [
    "regime_adx",
    "regime_atr",
    "regime_atr_pct",
    "regime_vol_rank",
    "regime_vol_ratio",
    "regime_realized_vol",
    "regime_ema_fast",
    "regime_ema_slow",
    "regime_trend",
    "regime_volatility",
    "regime",
]


@dataclass(slots=True)
class RegimeResult:
    """Classification result for a single point in time."""

    regime: MarketRegime = MarketRegime.UNKNOWN
    trend: TrendRegime = TrendRegime.UNKNOWN
    volatility: VolatilityRegime = VolatilityRegime.UNKNOWN
    adx: float | None = None
    atr: float | None = None
    atr_pct: float | None = None
    volatility_rank: float | None = None
    volatility_ratio: float | None = None
    realized_volatility: float | None = None
    ema_fast: float | None = None
    ema_slow: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_trending(self) -> bool:
        return self.trend in (TrendRegime.TRENDING_UP, TrendRegime.TRENDING_DOWN)

    @property
    def is_extreme(self) -> bool:
        return self.volatility == VolatilityRegime.EXTREME

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime.value,
            "trend": self.trend.value,
            "volatility": self.volatility.value,
            "adx": self.adx,
            "atr": self.atr,
            "atr_pct": self.atr_pct,
            "volatility_rank": self.volatility_rank,
            "volatility_ratio": self.volatility_ratio,
            "realized_volatility": self.realized_volatility,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
        }


class MarketRegimeEngine:
    """Classifies the market into a trend regime and a volatility regime."""

    def __init__(self, config: RegimeConfig | None = None) -> None:
        self.config = config or DEFAULT_REGIME_CONFIG

    # -- vectorised annotation (used by the backtester) ---------------------
    def annotate(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Add regime columns to a candle frame without any look-ahead."""
        config = self.config
        result = frame.copy()
        high, low, close = result["high"], result["low"], result["close"]

        adx_values, _, _ = adx(high, low, close, config.adx_period)
        atr_values = atr(high, low, close, config.atr_period)
        safe_close = close.replace(0.0, pd.NA).astype("float64")
        atr_pct = atr_values / safe_close * 100.0

        result["regime_adx"] = adx_values
        result["regime_atr"] = atr_values
        result["regime_atr_pct"] = atr_pct
        result["regime_vol_rank"] = percentile_rank(atr_pct, config.volatility_lookback)
        median_atr_pct = atr_pct.rolling(
            window=config.volatility_lookback, min_periods=max(10, config.volatility_lookback // 5)
        ).median()
        result["regime_vol_ratio"] = atr_pct / median_atr_pct.replace(0.0, pd.NA).astype("float64")
        result["regime_realized_vol"] = realized_volatility(close, config.realized_vol_period)
        result["regime_ema_fast"] = ema(close, config.fast_ema)
        result["regime_ema_slow"] = ema(close, config.slow_ema)

        trend_labels: list[str] = []
        volatility_labels: list[str] = []
        regime_labels: list[str] = []
        for row in result.itertuples(index=False):
            trend = self._classify_trend(
                safe_float(row.regime_adx),
                safe_float(row.regime_ema_fast),
                safe_float(row.regime_ema_slow),
                safe_float(row.close),
            )
            volatility = self._classify_volatility(
                safe_float(row.regime_atr_pct),
                safe_float(row.regime_vol_rank),
                safe_float(row.regime_vol_ratio),
            )
            trend_labels.append(trend.value)
            volatility_labels.append(volatility.value)
            regime_labels.append(self._combine(trend, volatility).value)

        result["regime_trend"] = trend_labels
        result["regime_volatility"] = volatility_labels
        result["regime"] = regime_labels
        return result

    # -- single point classification ---------------------------------------
    def classify(self, frame: pd.DataFrame) -> RegimeResult:
        """Classify the LAST closed candle of the given frame."""
        minimum = max(
            self.config.slow_ema, self.config.volatility_lookback, self.config.adx_period * 3
        )
        if frame is None or frame.empty:
            return RegimeResult()
        annotated = self.annotate(frame)
        return self.result_at(annotated, len(annotated) - 1, warmup=minimum)

    def result_at(self, annotated: pd.DataFrame, index: int, warmup: int = 0) -> RegimeResult:
        """Build a RegimeResult from an already annotated frame."""
        if index < 0 or index >= len(annotated):
            return RegimeResult()
        row = annotated.iloc[index]
        trend = TrendRegime(str(row.get("regime_trend", TrendRegime.UNKNOWN.value)))
        volatility = VolatilityRegime(
            str(row.get("regime_volatility", VolatilityRegime.UNKNOWN.value))
        )
        regime = MarketRegime(str(row.get("regime", MarketRegime.UNKNOWN.value)))
        return RegimeResult(
            regime=regime,
            trend=trend,
            volatility=volatility,
            adx=safe_float(row.get("regime_adx")),
            atr=safe_float(row.get("regime_atr")),
            atr_pct=safe_float(row.get("regime_atr_pct")),
            volatility_rank=safe_float(row.get("regime_vol_rank")),
            volatility_ratio=safe_float(row.get("regime_vol_ratio")),
            realized_volatility=safe_float(row.get("regime_realized_vol")),
            ema_fast=safe_float(row.get("regime_ema_fast")),
            ema_slow=safe_float(row.get("regime_ema_slow")),
            details={"warmup_bars": warmup, "bar_index": int(index)},
        )

    # -- classification rules ----------------------------------------------
    def _classify_trend(
        self,
        adx_value: float | None,
        ema_fast: float | None,
        ema_slow: float | None,
        close: float | None,
    ) -> TrendRegime:
        if adx_value is None or ema_fast is None or ema_slow is None or close is None:
            return TrendRegime.UNKNOWN
        if adx_value < self.config.adx_trend_threshold:
            return TrendRegime.RANGING
        if ema_fast > ema_slow and close > ema_slow:
            return TrendRegime.TRENDING_UP
        if ema_fast < ema_slow and close < ema_slow:
            return TrendRegime.TRENDING_DOWN
        return TrendRegime.RANGING

    def _classify_volatility(
        self,
        atr_pct: float | None,
        rank: float | None,
        ratio: float | None,
    ) -> VolatilityRegime:
        """Classify volatility from an absolute level, a percentile and a ratio.

        A percentile on its own is not evidence of anything: inside any rolling
        window some bar is always at the 98th percentile, so ranking alone would
        report EXTREME during perfectly ordinary conditions and permanently
        block trading. A bar therefore only counts as elevated when it is BOTH
        unusual for this market (percentile) AND materially larger than the
        market's own typical level (ratio to the rolling median).
        """
        config = self.config
        if atr_pct is None:
            return VolatilityRegime.UNKNOWN
        if atr_pct >= config.extreme_atr_pct:
            return VolatilityRegime.EXTREME
        if rank is None or ratio is None:
            return VolatilityRegime.NORMAL
        if (
            rank >= config.extreme_volatility_percentile
            and ratio >= config.extreme_volatility_ratio
        ):
            return VolatilityRegime.EXTREME
        if rank >= config.high_volatility_percentile and ratio >= config.high_volatility_ratio:
            return VolatilityRegime.HIGH
        if rank <= config.low_volatility_percentile:
            return VolatilityRegime.LOW
        return VolatilityRegime.NORMAL

    def _combine(self, trend: TrendRegime, volatility: VolatilityRegime) -> MarketRegime:
        """Collapse the two dimensions into the primary label."""
        if volatility == VolatilityRegime.EXTREME:
            return MarketRegime.EXTREME_VOLATILITY
        if trend == TrendRegime.TRENDING_UP:
            return MarketRegime.TRENDING_UP
        if trend == TrendRegime.TRENDING_DOWN:
            return MarketRegime.TRENDING_DOWN
        if volatility == VolatilityRegime.HIGH:
            return MarketRegime.HIGH_VOLATILITY
        if volatility == VolatilityRegime.LOW:
            return MarketRegime.LOW_VOLATILITY
        if trend == TrendRegime.RANGING:
            return MarketRegime.RANGING
        return MarketRegime.UNKNOWN
