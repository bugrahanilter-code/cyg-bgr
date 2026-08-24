"""Dual momentum (SAFE).

Absolute momentum ("is this asset going up at all?") combined with a long-term
trend filter, in the spirit of Gary Antonacci's public dual momentum work.
Long-only by default and slow to change its mind.
See docs/strategies/06-safe-strategies.md.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.core.constants import RiskLevel, SignalType
from app.indicators import atr, ema, rate_of_change, safe_float
from app.regime.engine import RegimeResult
from app.signals.models import StrategySignal
from app.strategies.base import BaseStrategy, clamp01
from app.strategies.helpers import atr_entry_signal, close_signal

INDICATOR_COLUMNS = ["momentum_pct", "ema_trend", "ema_medium", "atr"]


class DualMomentumParams(BaseModel):
    """Configurable parameters."""

    momentum_period: int = Field(
        default=96, ge=5, le=2000, description="Bars used for absolute momentum"
    )
    min_momentum_pct: float = Field(default=2.0, ge=0.0, le=100.0)
    exit_momentum_pct: float = Field(
        default=0.0, ge=-100.0, le=100.0, description="Close when momentum falls below this"
    )
    trend_ema: int = Field(default=200, ge=10, le=1000)
    medium_ema: int = Field(default=50, ge=5, le=500)
    require_trend_alignment: bool = Field(default=True)
    atr_period: int = Field(default=14, ge=2, le=100)
    atr_stop_multiplier: float = Field(default=3.0, gt=0.1, le=20.0)
    take_profit_r: float = Field(default=3.0, gt=0.1, le=50.0)
    trailing_atr_multiplier: float = Field(default=4.0, ge=0.0, le=30.0)
    allow_short: bool = Field(default=False, description="Long-only is the safer default")
    avoid_extreme_volatility: bool = Field(default=True)


class DualMomentumStrategy(BaseStrategy):
    """Absolute momentum plus trend alignment."""

    key = "dual_momentum"
    name = "Dual Momentum"
    family = "momentum"
    risk_level = RiskLevel.SAFE
    description = (
        "Holds only while the asset has positive momentum over a long lookback "
        "and price is above its long-term average. Misses the first part of "
        "every move and exits late, in exchange for far fewer bad trades."
    )
    params_model = DualMomentumParams

    @property
    def warmup_bars(self) -> int:
        params: DualMomentumParams = self.params  # type: ignore[assignment]
        return max(params.trend_ema, params.momentum_period) + 50

    def prepare(self, frame: pd.DataFrame, timeframe: str = "") -> pd.DataFrame:
        params: DualMomentumParams = self.params  # type: ignore[assignment]
        result = frame.copy()
        high, low, close = result["high"], result["low"], result["close"]

        result["momentum_pct"] = rate_of_change(close, params.momentum_period) * 100.0
        result["ema_trend"] = ema(close, params.trend_ema)
        result["ema_medium"] = ema(close, params.medium_ema)
        result["atr"] = atr(high, low, close, params.atr_period)
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
        params: DualMomentumParams = self.params  # type: ignore[assignment]
        row = self._row(prepared, index)
        indicators: dict[str, Any] = self._indicator_snapshot(row, INDICATOR_COLUMNS)
        indicators["close"] = safe_float(row["close"])

        close = safe_float(row["close"])
        atr_value = safe_float(row["atr"])
        momentum = safe_float(row["momentum_pct"])
        trend_value = safe_float(row["ema_trend"])
        medium_value = safe_float(row["ema_medium"])

        if None in (close, atr_value, momentum, trend_value) or not atr_value:
            return self._hold(symbol, timeframe, row, "Momentum not ready", indicators, regime)

        if position_side:
            side = position_side.upper()
            if side == "LONG" and momentum <= params.exit_momentum_pct:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason=f"Momentum faded to {momentum:.2f} percent",
                    indicators=indicators,
                    regime=regime,
                )
            if side == "SHORT" and momentum >= -params.exit_momentum_pct:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason=f"Momentum recovered to {momentum:.2f} percent",
                    indicators=indicators,
                    regime=regime,
                )

        if regime is not None and params.avoid_extreme_volatility and regime.is_extreme:
            return self._hold(
                symbol, timeframe, row, "Extreme volatility: standing aside", indicators, regime
            )

        aligned_long = not params.require_trend_alignment or (
            close > trend_value and (medium_value is None or close > medium_value)
        )
        aligned_short = not params.require_trend_alignment or (
            close < trend_value and (medium_value is None or close < medium_value)
        )
        strength = clamp01(abs(momentum) / max(params.min_momentum_pct * 3.0, 1e-9))

        if momentum >= params.min_momentum_pct and aligned_long:
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
                confidence=clamp01(0.45 + 0.45 * strength),
                explanation=(
                    f"Absolute momentum {momentum:.2f} percent over {params.momentum_period} "
                    f"bars with price above the {params.trend_ema} EMA."
                ),
                indicators=indicators,
                regime=regime,
                trailing_multiplier=params.trailing_atr_multiplier,
            )
        if params.allow_short and momentum <= -params.min_momentum_pct and aligned_short:
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
                confidence=clamp01(0.45 + 0.45 * strength),
                explanation=(
                    f"Absolute momentum {momentum:.2f} percent over {params.momentum_period} "
                    f"bars with price below the {params.trend_ema} EMA."
                ),
                indicators=indicators,
                regime=regime,
                trailing_multiplier=params.trailing_atr_multiplier,
            )

        return self._hold(
            symbol,
            timeframe,
            row,
            f"Momentum {momentum:.2f} percent is not enough",
            indicators,
            regime,
        )
