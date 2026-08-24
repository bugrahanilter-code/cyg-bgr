"""Strategy 1 - Trend following / time-series momentum.

Public, well documented systematic approach: trade in the direction of an
established trend and let a volatility-scaled stop define the risk. See
docs/strategies/01-trend-following.md for the literature and the failure modes.

Nothing here is proprietary and nothing here guarantees a profit. Trend
following is known to lose money in choppy, mean-reverting markets and to pay
for that with a small number of large winning trades.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.core.constants import SignalType
from app.indicators import adx, atr, ema, rate_of_change, safe_float
from app.regime.engine import RegimeResult
from app.signals.models import StrategySignal
from app.strategies.base import BaseStrategy, clamp01, higher_timeframe_ema

INDICATOR_COLUMNS = [
    "ema_fast",
    "ema_slow",
    "ema_trend",
    "atr",
    "momentum",
    "adx",
    "htf_ema",
]


class TrendFollowingParams(BaseModel):
    """Every knob of the strategy. Nothing is hard-coded."""

    fast_ema: int = Field(default=21, ge=2, le=200, description="Fast EMA period")
    slow_ema: int = Field(default=55, ge=3, le=400, description="Slow EMA period")
    trend_ema: int = Field(default=200, ge=10, le=1000, description="Trend filter EMA period")
    use_higher_timeframe: bool = Field(default=True, description="Confirm with a higher timeframe")
    higher_timeframe: str = Field(default="4h", description="Higher timeframe used for confirmation")
    higher_timeframe_ema: int = Field(default=50, ge=2, le=400)
    atr_period: int = Field(default=14, ge=2, le=100)
    atr_stop_multiplier: float = Field(default=2.0, gt=0.1, le=10.0)
    take_profit_r: float = Field(default=2.0, gt=0.1, le=20.0, description="Take profit in R")
    trailing_atr_multiplier: float = Field(
        default=2.5, ge=0.0, le=20.0, description="0 disables the trailing stop"
    )
    momentum_period: int = Field(default=10, ge=1, le=200)
    momentum_threshold: float = Field(
        default=0.004, ge=0.0, le=1.0, description="Minimum move over the momentum period"
    )
    min_adx: float = Field(default=18.0, ge=0.0, le=60.0)
    max_entry_distance_atr: float = Field(
        default=2.0, gt=0.0, le=20.0, description="Do not chase price far from the fast EMA"
    )
    allow_short: bool = Field(default=True)
    avoid_extreme_volatility: bool = Field(default=True)
    exit_on_trend_flip: bool = Field(default=True)


class TrendFollowingStrategy(BaseStrategy):
    """EMA stack + higher timeframe filter + momentum + ATR based risk."""

    key = "trend_following"
    name = "Trend Following / Time Series Momentum"
    family = "trend"
    description = (
        "Enters in the direction of an established trend confirmed on a higher "
        "timeframe, sized and stopped by ATR. Performs poorly in sideways markets."
    )
    params_model = TrendFollowingParams

    @property
    def warmup_bars(self) -> int:
        params: TrendFollowingParams = self.params  # type: ignore[assignment]
        return max(params.trend_ema, params.slow_ema, params.atr_period * 3) + 10

    def prepare(self, frame: pd.DataFrame, timeframe: str = "") -> pd.DataFrame:
        params: TrendFollowingParams = self.params  # type: ignore[assignment]
        result = frame.copy()
        close = result["close"]
        result["ema_fast"] = ema(close, params.fast_ema)
        result["ema_slow"] = ema(close, params.slow_ema)
        result["ema_trend"] = ema(close, params.trend_ema)
        result["atr"] = atr(result["high"], result["low"], close, params.atr_period)
        result["momentum"] = rate_of_change(close, params.momentum_period)
        adx_values, _, _ = adx(result["high"], result["low"], close, 14)
        result["adx"] = adx_values
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
        params: TrendFollowingParams = self.params  # type: ignore[assignment]
        row = prepared.iloc[index]
        indicators: dict[str, Any] = self._indicator_snapshot(row, INDICATOR_COLUMNS)
        indicators["close"] = safe_float(row["close"])

        close = safe_float(row["close"])
        fast = safe_float(row["ema_fast"])
        slow = safe_float(row["ema_slow"])
        trend = safe_float(row["ema_trend"])
        atr_value = safe_float(row["atr"])
        momentum = safe_float(row["momentum"])
        adx_value = safe_float(row["adx"]) or 0.0
        htf = safe_float(row["htf_ema"])

        if None in (close, fast, slow, trend, atr_value) or not atr_value:
            return self._hold(symbol, timeframe, row, "Indicators not ready", indicators, regime)

        bullish_stack = fast > slow and close > trend
        bearish_stack = fast < slow and close < trend

        # Exit management for an open position comes first.
        if position_side and params.exit_on_trend_flip:
            if position_side.upper() == "LONG" and fast < slow:
                return self._exit_signal(symbol, timeframe, row, indicators, regime, "Trend flipped down")
            if position_side.upper() == "SHORT" and fast > slow:
                return self._exit_signal(symbol, timeframe, row, indicators, regime, "Trend flipped up")

        if regime is not None and params.avoid_extreme_volatility and regime.is_extreme:
            return self._hold(
                symbol, timeframe, row, "Extreme volatility regime: standing aside", indicators, regime
            )

        if adx_value < params.min_adx:
            return self._hold(
                symbol,
                timeframe,
                row,
                f"Trend too weak (ADX {adx_value:.1f} < {params.min_adx})",
                indicators,
                regime,
            )

        distance_ok = abs(close - fast) <= params.max_entry_distance_atr * atr_value
        if not distance_ok:
            return self._hold(
                symbol, timeframe, row, "Price too far from the fast EMA to chase", indicators, regime
            )

        momentum_value = momentum if momentum is not None else 0.0
        htf_bullish = htf is None or close > htf
        htf_bearish = htf is None or close < htf

        if bullish_stack and momentum_value >= params.momentum_threshold and htf_bullish:
            return self._entry_signal(
                symbol, timeframe, row, indicators, regime, SignalType.LONG,
                close, atr_value, adx_value, momentum_value,
            )
        if (
            params.allow_short
            and bearish_stack
            and momentum_value <= -params.momentum_threshold
            and htf_bearish
        ):
            return self._entry_signal(
                symbol, timeframe, row, indicators, regime, SignalType.SHORT,
                close, atr_value, adx_value, momentum_value,
            )

        return self._hold(symbol, timeframe, row, "No trend entry condition met", indicators, regime)

    # -- signal builders ----------------------------------------------------
    def _entry_signal(
        self,
        symbol: str,
        timeframe: str,
        row: pd.Series,
        indicators: dict[str, Any],
        regime: RegimeResult | None,
        direction: SignalType,
        close: float,
        atr_value: float,
        adx_value: float,
        momentum_value: float,
    ) -> StrategySignal:
        params: TrendFollowingParams = self.params  # type: ignore[assignment]
        stop_distance = atr_value * params.atr_stop_multiplier
        if direction == SignalType.LONG:
            stop_loss = close - stop_distance
            take_profit = close + stop_distance * params.take_profit_r
        else:
            stop_loss = close + stop_distance
            take_profit = close - stop_distance * params.take_profit_r

        adx_component = clamp01((adx_value - params.min_adx) / 30.0)
        momentum_component = clamp01(
            abs(momentum_value) / max(params.momentum_threshold * 4.0, 1e-9)
        )
        alignment_component = 1.0 if indicators.get("htf_ema") is not None else 0.6
        confidence = clamp01(
            0.35 * adx_component + 0.35 * momentum_component + 0.30 * alignment_component
        )

        explanation = (
            f"{direction.value}: EMA{params.fast_ema}/EMA{params.slow_ema} aligned, "
            f"ADX {adx_value:.1f}, momentum {momentum_value * 100:.2f} percent over "
            f"{params.momentum_period} bars, stop {params.atr_stop_multiplier} ATR away."
        )
        indicators["atr_stop_distance"] = stop_distance
        return StrategySignal(
            symbol=symbol,
            timeframe=timeframe,
            strategy_key=self.key,
            signal=direction,
            candle_open_time=int(row["open_time"]),
            confidence=confidence,
            entry_price=close,
            stop_loss=stop_loss,
            take_profit=take_profit,
            explanation=explanation,
            indicators=indicators,
            regime=regime,
            metadata={
                "trailing_atr_multiplier": params.trailing_atr_multiplier,
                "atr": atr_value,
            },
        )

    def _exit_signal(
        self,
        symbol: str,
        timeframe: str,
        row: pd.Series,
        indicators: dict[str, Any],
        regime: RegimeResult | None,
        reason: str,
    ) -> StrategySignal:
        return StrategySignal(
            symbol=symbol,
            timeframe=timeframe,
            strategy_key=self.key,
            signal=SignalType.CLOSE,
            candle_open_time=int(row["open_time"]),
            confidence=0.6,
            entry_price=safe_float(row["close"]),
            explanation=reason,
            indicators=indicators,
            regime=regime,
        )
