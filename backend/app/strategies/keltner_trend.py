"""Keltner channel trend riding (SAFE).

Enters only when price closes outside a Keltner channel in the direction of a
confirmed long-term trend, and holds until price closes back through the middle
line. Conservative filters, wide stops, few trades.
See docs/strategies/06-safe-strategies.md.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.core.constants import RiskLevel, SignalType
from app.indicators import adx, atr, ema, keltner_channels, safe_float, volume_ratio
from app.regime.engine import RegimeResult
from app.signals.models import StrategySignal
from app.strategies.base import BaseStrategy, clamp01, higher_timeframe_ema
from app.strategies.helpers import atr_entry_signal, close_signal

INDICATOR_COLUMNS = [
    "keltner_upper",
    "keltner_middle",
    "keltner_lower",
    "atr",
    "ema_trend",
    "adx",
    "volume_ratio",
    "htf_ema",
]


class KeltnerTrendParams(BaseModel):
    """Configurable parameters."""

    ema_period: int = Field(default=20, ge=2, le=400)
    atr_period: int = Field(default=10, ge=2, le=100)
    multiplier: float = Field(default=2.0, gt=0.1, le=10.0)
    trend_ema: int = Field(default=200, ge=10, le=1000)
    use_higher_timeframe: bool = Field(default=True)
    higher_timeframe: str = Field(default="4h")
    higher_timeframe_ema: int = Field(default=50, ge=2, le=400)
    min_adx: float = Field(default=20.0, ge=0.0, le=60.0)
    use_volume_filter: bool = Field(default=True)
    min_volume_ratio: float = Field(default=1.0, ge=0.0, le=10.0)
    atr_stop_multiplier: float = Field(default=2.5, gt=0.1, le=20.0)
    take_profit_r: float = Field(default=3.0, gt=0.1, le=50.0)
    trailing_atr_multiplier: float = Field(default=3.5, ge=0.0, le=30.0)
    allow_short: bool = Field(default=False, description="Long-only is the safer default")
    exit_on_middle_cross: bool = Field(default=True)
    avoid_extreme_volatility: bool = Field(default=True)


class KeltnerTrendStrategy(BaseStrategy):
    """Rides trends that push outside a Keltner channel."""

    key = "keltner_trend"
    name = "Keltner Channel Trend"
    family = "trend"
    risk_level = RiskLevel.SAFE
    description = (
        "Enters only when price closes outside the Keltner channel with the "
        "higher timeframe, trend strength and volume all agreeing, then holds "
        "until price closes back through the middle line."
    )
    params_model = KeltnerTrendParams

    @property
    def warmup_bars(self) -> int:
        params: KeltnerTrendParams = self.params  # type: ignore[assignment]
        return max(params.trend_ema, params.ema_period * 3, params.atr_period * 5) + 30

    def prepare(self, frame: pd.DataFrame, timeframe: str = "") -> pd.DataFrame:
        params: KeltnerTrendParams = self.params  # type: ignore[assignment]
        result = frame.copy()
        high, low, close = result["high"], result["low"], result["close"]

        channels = keltner_channels(
            high, low, close, params.ema_period, params.atr_period, params.multiplier
        )
        for column in channels.columns:
            result[column] = channels[column]
        result["atr"] = atr(high, low, close, params.atr_period)
        result["ema_trend"] = ema(close, params.trend_ema)
        adx_values, _, _ = adx(high, low, close, 14)
        result["adx"] = adx_values
        result["volume_ratio"] = volume_ratio(result["volume"], 20)
        if params.use_higher_timeframe:
            result["htf_ema"] = higher_timeframe_ema(
                result, params.higher_timeframe, params.higher_timeframe_ema
            )
        else:
            result["htf_ema"] = pd.Series(float("nan"), index=result.index)
        return result

    def evaluate(
        self,
        prepared: pd.DataFrame,
        index: int,
        *,
        symbol: str,
        timeframe: str,
        regime: RegimeResult | None = None,
        position_side: str | None = None,
    ) -> StrategySignal:
        params: KeltnerTrendParams = self.params  # type: ignore[assignment]
        row = prepared.iloc[index]
        indicators: dict[str, Any] = self._indicator_snapshot(row, INDICATOR_COLUMNS)
        indicators["close"] = safe_float(row["close"])

        close = safe_float(row["close"])
        atr_value = safe_float(row["atr"])
        upper = safe_float(row["keltner_upper"])
        middle = safe_float(row["keltner_middle"])
        lower = safe_float(row["keltner_lower"])
        trend_value = safe_float(row["ema_trend"])
        adx_value = safe_float(row["adx"]) or 0.0
        volume_confirmation = safe_float(row["volume_ratio"])
        htf = safe_float(row["htf_ema"])

        if None in (close, atr_value, upper, middle, lower, trend_value) or not atr_value:
            return self._hold(symbol, timeframe, row, "Channel not ready", indicators, regime)

        if position_side and params.exit_on_middle_cross:
            side = position_side.upper()
            if side == "LONG" and close < middle:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="Price closed back inside the channel",
                    indicators=indicators,
                    regime=regime,
                )
            if side == "SHORT" and close > middle:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="Price closed back inside the channel",
                    indicators=indicators,
                    regime=regime,
                )

        if regime is not None and params.avoid_extreme_volatility and regime.is_extreme:
            return self._hold(
                symbol, timeframe, row, "Extreme volatility: standing aside", indicators, regime
            )
        if adx_value < params.min_adx:
            return self._hold(
                symbol, timeframe, row, f"Trend too weak (ADX {adx_value:.1f})", indicators, regime
            )

        volume_ok = (
            not params.use_volume_filter
            or volume_confirmation is None
            or volume_confirmation >= params.min_volume_ratio
        )
        htf_bullish = htf is None or close > htf
        htf_bearish = htf is None or close < htf
        push = abs(close - (upper if close > upper else lower)) / atr_value
        confidence = clamp01(
            0.4 + 0.3 * clamp01((adx_value - params.min_adx) / 25.0) + 0.3 * clamp01(push)
        )

        if close > upper and close > trend_value and htf_bullish and volume_ok:
            return atr_entry_signal(
                strategy_key=self.key,
                symbol=symbol,
                timeframe=timeframe,
                row=row,
                direction=SignalType.LONG,
                entry_price=close,
                atr_value=atr_value,
                stop_multiplier=params.atr_stop_multiplier,
                take_profit_r=params.take_profit_r,
                confidence=confidence,
                explanation=(
                    f"Close above the Keltner upper band {upper:.2f} with ADX "
                    f"{adx_value:.1f} and the higher timeframe agreeing."
                ),
                indicators=indicators,
                regime=regime,
                trailing_multiplier=params.trailing_atr_multiplier,
            )
        if (
            params.allow_short
            and close < lower
            and close < trend_value
            and htf_bearish
            and volume_ok
        ):
            return atr_entry_signal(
                strategy_key=self.key,
                symbol=symbol,
                timeframe=timeframe,
                row=row,
                direction=SignalType.SHORT,
                entry_price=close,
                atr_value=atr_value,
                stop_multiplier=params.atr_stop_multiplier,
                take_profit_r=params.take_profit_r,
                confidence=confidence,
                explanation=(
                    f"Close below the Keltner lower band {lower:.2f} with ADX "
                    f"{adx_value:.1f} and the higher timeframe agreeing."
                ),
                indicators=indicators,
                regime=regime,
                trailing_multiplier=params.trailing_atr_multiplier,
            )

        return self._hold(symbol, timeframe, row, "Price inside the channel", indicators, regime)
