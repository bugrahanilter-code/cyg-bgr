"""SuperTrend following (MEDIUM risk).

SuperTrend is an ATR trailing stop that flips between a long and a short state.
It is one of the most widely used indicators in crypto because it produces an
unambiguous state and a natural stop level.
See docs/strategies/05-medium-risk-strategies.md.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.core.constants import RiskLevel, SignalType
from app.indicators import adx, atr, ema, safe_float, supertrend
from app.regime.engine import RegimeResult
from app.signals.models import StrategySignal
from app.strategies.base import BaseStrategy, clamp01
from app.strategies.helpers import atr_entry_signal, close_signal

INDICATOR_COLUMNS = ["supertrend", "supertrend_direction", "atr", "ema_trend", "adx"]


class SupertrendParams(BaseModel):
    """Configurable parameters."""

    period: int = Field(default=10, ge=2, le=100, description="ATR period of the SuperTrend")
    multiplier: float = Field(default=3.0, gt=0.1, le=20.0)
    atr_period: int = Field(default=14, ge=2, le=100)
    use_supertrend_as_stop: bool = Field(
        default=True, description="Place the stop on the SuperTrend line itself"
    )
    atr_stop_multiplier: float = Field(default=2.0, gt=0.1, le=10.0)
    take_profit_r: float = Field(default=2.5, gt=0.1, le=20.0)
    trailing_atr_multiplier: float = Field(default=3.0, ge=0.0, le=20.0)
    use_trend_filter: bool = Field(default=True)
    trend_ema: int = Field(default=200, ge=10, le=1000)
    min_adx: float = Field(default=15.0, ge=0.0, le=60.0)
    allow_short: bool = Field(default=True)
    exit_on_flip: bool = Field(default=True)
    avoid_extreme_volatility: bool = Field(default=True)


class SupertrendStrategy(BaseStrategy):
    """Enters when SuperTrend flips and rides the move."""

    key = "supertrend_follow"
    name = "Supertrend Takibi"
    family = "trend"
    risk_level = RiskLevel.MEDIUM
    description = (
        "ATR tabanlı Supertrend çizgisi yön değiştirdiğinde girer ve tekrar dönene "
        "kadar tutar. Oynaklık sıkıştığında sık sık yön değiştirir."
    )
    params_model = SupertrendParams

    @property
    def warmup_bars(self) -> int:
        params: SupertrendParams = self.params  # type: ignore[assignment]
        return max(params.trend_ema, params.period * 5) + 20

    def prepare(self, frame: pd.DataFrame, timeframe: str = "") -> pd.DataFrame:
        params: SupertrendParams = self.params  # type: ignore[assignment]
        result = frame.copy()
        high, low, close = result["high"], result["low"], result["close"]

        lines = supertrend(high, low, close, params.period, params.multiplier)
        result["supertrend"] = lines["supertrend"]
        result["supertrend_direction"] = lines["supertrend_direction"]
        result["supertrend_flip"] = result["supertrend_direction"].diff().fillna(0.0)
        result["atr"] = atr(high, low, close, params.atr_period)
        result["ema_trend"] = ema(close, params.trend_ema)
        adx_values, _, _ = adx(high, low, close, 14)
        result["adx"] = adx_values
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
        params: SupertrendParams = self.params  # type: ignore[assignment]
        row = self._row(prepared, index)
        indicators: dict[str, Any] = self._indicator_snapshot(row, INDICATOR_COLUMNS)
        indicators["close"] = safe_float(row["close"])

        close = safe_float(row["close"])
        atr_value = safe_float(row["atr"])
        line = safe_float(row["supertrend"])
        direction = safe_float(row["supertrend_direction"])
        flip = safe_float(row["supertrend_flip"]) or 0.0
        trend_value = safe_float(row["ema_trend"])
        adx_value = safe_float(row["adx"]) or 0.0

        if None in (close, atr_value, line, direction) or not atr_value:
            return self._hold(symbol, timeframe, row, "SuperTrend not ready", indicators, regime)

        if position_side and params.exit_on_flip:
            side = position_side.upper()
            if side == "LONG" and direction < 0:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="SuperTrend flipped bearish",
                    indicators=indicators,
                    regime=regime,
                )
            if side == "SHORT" and direction > 0:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="SuperTrend flipped bullish",
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
        if flip == 0.0:
            return self._hold(symbol, timeframe, row, "No SuperTrend flip", indicators, regime)

        trend_ok_long = not params.use_trend_filter or trend_value is None or close > trend_value
        trend_ok_short = not params.use_trend_filter or trend_value is None or close < trend_value
        confidence = clamp01(0.4 + 0.6 * clamp01((adx_value - params.min_adx) / 25.0))

        if direction > 0 and trend_ok_long:
            stop = line if params.use_supertrend_as_stop and line < close else None
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
                explanation=f"SuperTrend flipped bullish at {line:.2f} (ADX {adx_value:.1f}).",
                indicators=indicators,
                regime=regime,
                trailing_multiplier=params.trailing_atr_multiplier,
                stop_override=stop,
            )
        if params.allow_short and direction < 0 and trend_ok_short:
            stop = line if params.use_supertrend_as_stop and line > close else None
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
                explanation=f"SuperTrend flipped bearish at {line:.2f} (ADX {adx_value:.1f}).",
                indicators=indicators,
                regime=regime,
                trailing_multiplier=params.trailing_atr_multiplier,
                stop_override=stop,
            )

        return self._hold(
            symbol, timeframe, row, "SuperTrend flip against the trend filter", indicators, regime
        )
