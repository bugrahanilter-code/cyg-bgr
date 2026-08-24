"""VWAP pullback in an established trend (SAFE).

Instead of chasing a breakout, this waits for price to pull back towards the
volume weighted average price inside a confirmed uptrend and buys the dip,
provided momentum has not actually broken down.
See docs/strategies/06-safe-strategies.md.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.core.constants import RiskLevel, SignalType
from app.indicators import atr, ema, rolling_vwap, rsi, safe_float
from app.regime.engine import RegimeResult
from app.signals.models import StrategySignal
from app.strategies.base import BaseStrategy, clamp01
from app.strategies.helpers import atr_entry_signal, close_signal

INDICATOR_COLUMNS = ["vwap", "ema_trend", "rsi", "atr", "distance_atr"]


class VwapPullbackParams(BaseModel):
    """Configurable parameters."""

    vwap_period: int = Field(default=50, ge=5, le=500)
    trend_ema: int = Field(default=200, ge=10, le=1000)
    rsi_period: int = Field(default=14, ge=2, le=100)
    rsi_floor: float = Field(
        default=40.0, ge=1.0, le=70.0, description="Below this the pullback is a breakdown"
    )
    rsi_ceiling: float = Field(default=60.0, ge=30.0, le=99.0)
    max_distance_atr: float = Field(
        default=0.5, gt=0.0, le=10.0, description="How close to VWAP price must come"
    )
    atr_period: int = Field(default=14, ge=2, le=100)
    atr_stop_multiplier: float = Field(default=2.0, gt=0.1, le=10.0)
    take_profit_r: float = Field(default=2.0, gt=0.1, le=20.0)
    trailing_atr_multiplier: float = Field(default=3.0, ge=0.0, le=20.0)
    allow_short: bool = Field(default=False, description="Long-only is the safer default")
    exit_below_trend: bool = Field(default=True)
    avoid_extreme_volatility: bool = Field(default=True)


class VwapPullbackStrategy(BaseStrategy):
    """Buys dips to VWAP while the larger trend is intact."""

    key = "vwap_pullback"
    name = "VWAP Trend Pullback"
    family = "trend"
    risk_level = RiskLevel.SAFE
    description = (
        "Waits for a pullback to the volume weighted average price inside an "
        "established trend instead of chasing breakouts. Misses trends that "
        "never pull back, and fails when a pullback becomes a reversal."
    )
    params_model = VwapPullbackParams

    @property
    def warmup_bars(self) -> int:
        params: VwapPullbackParams = self.params  # type: ignore[assignment]
        return max(params.trend_ema, params.vwap_period * 2) + 30

    def prepare(self, frame: pd.DataFrame, timeframe: str = "") -> pd.DataFrame:
        params: VwapPullbackParams = self.params  # type: ignore[assignment]
        result = frame.copy()
        high, low, close, volume = (
            result["high"],
            result["low"],
            result["close"],
            result["volume"],
        )
        result["vwap"] = rolling_vwap(high, low, close, volume, params.vwap_period)
        result["ema_trend"] = ema(close, params.trend_ema)
        result["rsi"] = rsi(close, params.rsi_period)
        result["atr"] = atr(high, low, close, params.atr_period)
        safe_atr = result["atr"].replace(0.0, pd.NA).astype("float64")
        result["distance_atr"] = (close - result["vwap"]) / safe_atr
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
        params: VwapPullbackParams = self.params  # type: ignore[assignment]
        row = self._row(prepared, index)
        indicators: dict[str, Any] = self._indicator_snapshot(row, INDICATOR_COLUMNS)
        indicators["close"] = safe_float(row["close"])

        close = safe_float(row["close"])
        atr_value = safe_float(row["atr"])
        vwap_value = safe_float(row["vwap"])
        trend_value = safe_float(row["ema_trend"])
        rsi_value = safe_float(row["rsi"])
        distance = safe_float(row["distance_atr"])

        if (
            None in (close, atr_value, vwap_value, trend_value, rsi_value, distance)
            or not atr_value
        ):
            return self._hold(symbol, timeframe, row, "Indicators not ready", indicators, regime)

        if position_side and params.exit_below_trend:
            side = position_side.upper()
            if side == "LONG" and close < trend_value:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="Price lost the long-term trend line",
                    indicators=indicators,
                    regime=regime,
                )
            if side == "SHORT" and close > trend_value:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="Price reclaimed the long-term trend line",
                    indicators=indicators,
                    regime=regime,
                )

        if regime is not None and params.avoid_extreme_volatility and regime.is_extreme:
            return self._hold(
                symbol, timeframe, row, "Extreme volatility: standing aside", indicators, regime
            )

        uptrend = close > trend_value
        downtrend = close < trend_value
        near_vwap = abs(distance) <= params.max_distance_atr
        proximity = clamp01(1.0 - abs(distance) / params.max_distance_atr)

        if uptrend and near_vwap and distance <= 0 and rsi_value >= params.rsi_floor:
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
                    0.4 + 0.35 * proximity + 0.25 * clamp01((rsi_value - params.rsi_floor) / 20.0)
                ),
                explanation=(
                    f"Pullback to VWAP {vwap_value:.2f} in an uptrend "
                    f"({distance:.2f} ATR away, RSI {rsi_value:.1f})."
                ),
                indicators=indicators,
                regime=regime,
                trailing_multiplier=params.trailing_atr_multiplier,
            )
        if (
            params.allow_short
            and downtrend
            and near_vwap
            and distance >= 0
            and rsi_value <= params.rsi_ceiling
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
                confidence=clamp01(
                    0.4 + 0.35 * proximity + 0.25 * clamp01((params.rsi_ceiling - rsi_value) / 20.0)
                ),
                explanation=(
                    f"Rally back to VWAP {vwap_value:.2f} in a downtrend "
                    f"({distance:.2f} ATR away, RSI {rsi_value:.1f})."
                ),
                indicators=indicators,
                regime=regime,
                trailing_multiplier=params.trailing_atr_multiplier,
            )

        return self._hold(symbol, timeframe, row, "No pullback setup", indicators, regime)
