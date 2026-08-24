"""Volatility breakout (RISKY).

A short-horizon range breakout in the spirit of Larry Williams: take the range
of the previous candles, project a fraction of it from the current open, and
trade the break of that level.

It trades often and holds briefly, so transaction costs matter enormously and
false breaks are frequent. See docs/strategies/04-risky-strategies.md.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.core.constants import RiskLevel, SignalType
from app.indicators import atr, ema, safe_float, volume_ratio
from app.regime.engine import RegimeResult
from app.signals.models import StrategySignal
from app.strategies.base import BaseStrategy, clamp01
from app.strategies.helpers import atr_entry_signal, close_signal

INDICATOR_COLUMNS = [
    "atr",
    "range_reference",
    "upper_trigger",
    "lower_trigger",
    "volume_ratio",
    "ema_trend",
]


class VolatilityBreakoutParams(BaseModel):
    """Configurable parameters."""

    range_period: int = Field(default=4, ge=1, le=100, description="Candles used for the range")
    breakout_factor: float = Field(
        default=0.5, gt=0.0, le=5.0, description="Fraction of the range projected from the open"
    )
    atr_period: int = Field(default=14, ge=2, le=100)
    atr_stop_multiplier: float = Field(default=1.0, gt=0.1, le=10.0)
    take_profit_r: float = Field(default=1.5, gt=0.1, le=20.0)
    max_hold_bars: int = Field(default=8, ge=1, le=200, description="Force an exit after N candles")
    use_volume_filter: bool = Field(default=True)
    min_volume_ratio: float = Field(default=1.1, ge=0.0, le=10.0)
    use_trend_filter: bool = Field(default=False, description="Trade only with the trend")
    trend_ema: int = Field(default=100, ge=5, le=1000)
    allow_short: bool = Field(default=True)
    avoid_extreme_volatility: bool = Field(default=True)


class VolatilityBreakoutStrategy(BaseStrategy):
    """Intraday range breakout with a tight ATR stop."""

    key = "volatility_breakout"
    name = "Volatility Breakout"
    family = "breakout"
    risk_level = RiskLevel.RISKY
    description = (
        "Trades a break of a fraction of the recent range projected from the "
        "candle open. High frequency and tight stops: costs and false breaks "
        "are its main enemies."
    )
    params_model = VolatilityBreakoutParams

    @property
    def warmup_bars(self) -> int:
        params: VolatilityBreakoutParams = self.params  # type: ignore[assignment]
        return max(params.trend_ema, params.range_period, params.atr_period * 3) + 10

    def prepare(self, frame: pd.DataFrame, timeframe: str = "") -> pd.DataFrame:
        params: VolatilityBreakoutParams = self.params  # type: ignore[assignment]
        result = frame.copy()
        high, low, close = result["high"], result["low"], result["close"]

        candle_range = (high - low).rolling(params.range_period, min_periods=params.range_period)
        # Shifted by one bar: the trigger for this candle may only use closed bars.
        result["range_reference"] = candle_range.mean().shift(1)
        result["upper_trigger"] = (
            result["open"] + params.breakout_factor * result["range_reference"]
        )
        result["lower_trigger"] = (
            result["open"] - params.breakout_factor * result["range_reference"]
        )
        result["atr"] = atr(high, low, close, params.atr_period)
        result["volume_ratio"] = volume_ratio(result["volume"], 20)
        result["ema_trend"] = ema(close, params.trend_ema)
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
        params: VolatilityBreakoutParams = self.params  # type: ignore[assignment]
        row = prepared.iloc[index]
        indicators: dict[str, Any] = self._indicator_snapshot(row, INDICATOR_COLUMNS)
        indicators["close"] = safe_float(row["close"])

        close = safe_float(row["close"])
        atr_value = safe_float(row["atr"])
        upper = safe_float(row["upper_trigger"])
        lower = safe_float(row["lower_trigger"])
        volume_confirmation = safe_float(row["volume_ratio"])
        trend_value = safe_float(row["ema_trend"])

        if None in (close, atr_value, upper, lower) or not atr_value:
            return self._hold(symbol, timeframe, row, "Range not ready", indicators, regime)

        if position_side:
            # The edge decays quickly, so a stale position is closed on time.
            side = position_side.upper()
            if side == "LONG" and close < lower:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="Price fell back through the lower trigger",
                    indicators=indicators,
                    regime=regime,
                )
            if side == "SHORT" and close > upper:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="Price pushed back through the upper trigger",
                    indicators=indicators,
                    regime=regime,
                )

        if regime is not None and params.avoid_extreme_volatility and regime.is_extreme:
            return self._hold(
                symbol, timeframe, row, "Extreme volatility: breakout skipped", indicators, regime
            )

        volume_ok = (
            not params.use_volume_filter
            or volume_confirmation is None
            or volume_confirmation >= params.min_volume_ratio
        )
        trend_ok_long = not params.use_trend_filter or trend_value is None or close > trend_value
        trend_ok_short = not params.use_trend_filter or trend_value is None or close < trend_value

        if close > upper and volume_ok and trend_ok_long:
            strength = clamp01((close - upper) / atr_value)
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
                confidence=clamp01(
                    0.35 + 0.4 * strength + 0.25 * min(volume_confirmation or 1.0, 2.0) / 2.0
                ),
                explanation=(
                    f"LONG volatility breakout above {upper:.2f} "
                    f"({params.breakout_factor} of the {params.range_period}-bar range)."
                ),
                indicators=indicators,
                regime=regime,
            )
        if params.allow_short and close < lower and volume_ok and trend_ok_short:
            strength = clamp01((lower - close) / atr_value)
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
                confidence=clamp01(
                    0.35 + 0.4 * strength + 0.25 * min(volume_confirmation or 1.0, 2.0) / 2.0
                ),
                explanation=(
                    f"SHORT volatility breakout below {lower:.2f} "
                    f"({params.breakout_factor} of the {params.range_period}-bar range)."
                ),
                indicators=indicators,
                regime=regime,
            )

        return self._hold(
            symbol, timeframe, row, "Price inside the trigger range", indicators, regime
        )
