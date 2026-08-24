"""MACD momentum with a trend filter (MEDIUM risk).

The most widely used momentum oscillator, kept honest by a long-term trend
filter so it does not fight the dominant direction.
See docs/strategies/05-medium-risk-strategies.md.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.core.constants import RiskLevel, SignalType
from app.indicators import adx, atr, crossed_above, crossed_below, ema, macd, safe_float
from app.regime.engine import RegimeResult
from app.signals.models import StrategySignal
from app.strategies.base import BaseStrategy, clamp01
from app.strategies.helpers import atr_entry_signal, close_signal

INDICATOR_COLUMNS = ["macd", "macd_signal", "macd_hist", "atr", "ema_trend", "adx"]


class MacdMomentumParams(BaseModel):
    """Configurable parameters."""

    fast_period: int = Field(default=12, ge=2, le=200)
    slow_period: int = Field(default=26, ge=3, le=400)
    signal_period: int = Field(default=9, ge=2, le=100)
    trend_ema: int = Field(default=200, ge=10, le=1000)
    use_trend_filter: bool = Field(default=True)
    require_zero_line: bool = Field(
        default=True, description="Only take longs while MACD is above zero"
    )
    min_adx: float = Field(default=15.0, ge=0.0, le=60.0)
    atr_period: int = Field(default=14, ge=2, le=100)
    atr_stop_multiplier: float = Field(default=2.0, gt=0.1, le=10.0)
    take_profit_r: float = Field(default=2.0, gt=0.1, le=20.0)
    trailing_atr_multiplier: float = Field(default=2.5, ge=0.0, le=20.0)
    allow_short: bool = Field(default=True)
    exit_on_opposite_cross: bool = Field(default=True)
    avoid_extreme_volatility: bool = Field(default=True)


class MacdMomentumStrategy(BaseStrategy):
    """MACD signal-line crossover, filtered by trend and trend strength."""

    key = "macd_momentum"
    name = "MACD Momentum"
    family = "momentum"
    risk_level = RiskLevel.MEDIUM
    description = (
        "Takes MACD signal-line crossovers in the direction of a long-term EMA. "
        "Reliable in trends, prone to whipsaws when the market goes sideways."
    )
    params_model = MacdMomentumParams

    @property
    def warmup_bars(self) -> int:
        params: MacdMomentumParams = self.params  # type: ignore[assignment]
        return max(params.trend_ema, params.slow_period * 3) + 20

    def prepare(self, frame: pd.DataFrame, timeframe: str = "") -> pd.DataFrame:
        params: MacdMomentumParams = self.params  # type: ignore[assignment]
        result = frame.copy()
        high, low, close = result["high"], result["low"], result["close"]

        lines = macd(close, params.fast_period, params.slow_period, params.signal_period)
        for column in lines.columns:
            result[column] = lines[column]
        result["macd_cross_up"] = crossed_above(result["macd"], result["macd_signal"])
        result["macd_cross_down"] = crossed_below(result["macd"], result["macd_signal"])
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
        params: MacdMomentumParams = self.params  # type: ignore[assignment]
        row = self._row(prepared, index)
        indicators: dict[str, Any] = self._indicator_snapshot(row, INDICATOR_COLUMNS)
        indicators["close"] = safe_float(row["close"])

        close = safe_float(row["close"])
        atr_value = safe_float(row["atr"])
        macd_value = safe_float(row["macd"])
        histogram = safe_float(row["macd_hist"])
        trend_value = safe_float(row["ema_trend"])
        adx_value = safe_float(row["adx"]) or 0.0
        cross_up = bool(row.get("macd_cross_up", False))
        cross_down = bool(row.get("macd_cross_down", False))

        if None in (close, atr_value, macd_value, histogram) or not atr_value:
            return self._hold(symbol, timeframe, row, "MACD not ready", indicators, regime)

        if position_side and params.exit_on_opposite_cross:
            side = position_side.upper()
            if side == "LONG" and cross_down:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="MACD crossed below its signal line",
                    indicators=indicators,
                    regime=regime,
                )
            if side == "SHORT" and cross_up:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="MACD crossed above its signal line",
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

        trend_ok_long = not params.use_trend_filter or trend_value is None or close > trend_value
        trend_ok_short = not params.use_trend_filter or trend_value is None or close < trend_value
        zero_ok_long = not params.require_zero_line or macd_value > 0
        zero_ok_short = not params.require_zero_line or macd_value < 0
        strength = clamp01(abs(histogram) / (atr_value * 0.5))
        trend_component = clamp01((adx_value - params.min_adx) / 25.0)

        if cross_up and trend_ok_long and zero_ok_long:
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
                confidence=clamp01(0.35 + 0.35 * strength + 0.30 * trend_component),
                explanation=(
                    f"MACD crossed above its signal line (histogram {histogram:.4f}, "
                    f"ADX {adx_value:.1f})."
                ),
                indicators=indicators,
                regime=regime,
                trailing_multiplier=params.trailing_atr_multiplier,
            )
        if params.allow_short and cross_down and trend_ok_short and zero_ok_short:
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
                confidence=clamp01(0.35 + 0.35 * strength + 0.30 * trend_component),
                explanation=(
                    f"MACD crossed below its signal line (histogram {histogram:.4f}, "
                    f"ADX {adx_value:.1f})."
                ),
                indicators=indicators,
                regime=regime,
                trailing_multiplier=params.trailing_atr_multiplier,
            )

        return self._hold(symbol, timeframe, row, "No MACD crossover", indicators, regime)
