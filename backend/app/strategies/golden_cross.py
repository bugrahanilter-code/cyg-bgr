"""Golden cross moving average trend (SAFE).

The classic 50/200 moving average crossover. Very low trade frequency, wide
stops, long-only by default: it aims to capture the few large trends per year
and to sit out everything else.
See docs/strategies/06-safe-strategies.md.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.core.constants import RiskLevel, SignalType
from app.indicators import atr, crossed_above, crossed_below, ema, safe_float, sma
from app.regime.engine import RegimeResult
from app.signals.models import StrategySignal
from app.strategies.base import BaseStrategy, clamp01
from app.strategies.helpers import atr_entry_signal, close_signal

INDICATOR_COLUMNS = ["ma_fast", "ma_slow", "atr", "separation_pct"]


class GoldenCrossParams(BaseModel):
    """Configurable parameters."""

    fast_period: int = Field(default=50, ge=2, le=500)
    slow_period: int = Field(default=200, ge=5, le=1000)
    use_ema: bool = Field(default=True, description="EMA instead of SMA")
    min_separation_pct: float = Field(
        default=0.15, ge=0.0, le=20.0, description="Minimum gap between the averages"
    )
    atr_period: int = Field(default=14, ge=2, le=100)
    atr_stop_multiplier: float = Field(
        default=3.0, gt=0.1, le=20.0, description="Wide stop: this strategy needs room"
    )
    take_profit_r: float = Field(default=3.0, gt=0.1, le=50.0)
    trailing_atr_multiplier: float = Field(default=4.0, ge=0.0, le=30.0)
    allow_short: bool = Field(default=False, description="Long-only is the safer default")
    exit_on_death_cross: bool = Field(default=True)
    avoid_extreme_volatility: bool = Field(default=True)


class GoldenCrossStrategy(BaseStrategy):
    """Long-term moving average crossover."""

    key = "golden_cross"
    name = "Golden Cross Trend"
    family = "trend"
    risk_level = RiskLevel.SAFE
    description = (
        "Buys when the fast moving average crosses above the slow one and holds "
        "until it crosses back. Very few trades, wide stops, long-only by "
        "default. Gives back a large part of every trend at the exit."
    )
    params_model = GoldenCrossParams

    @property
    def warmup_bars(self) -> int:
        params: GoldenCrossParams = self.params  # type: ignore[assignment]
        return params.slow_period + 50

    def prepare(self, frame: pd.DataFrame, timeframe: str = "") -> pd.DataFrame:
        params: GoldenCrossParams = self.params  # type: ignore[assignment]
        result = frame.copy()
        high, low, close = result["high"], result["low"], result["close"]

        average = ema if params.use_ema else sma
        result["ma_fast"] = average(close, params.fast_period)
        result["ma_slow"] = average(close, params.slow_period)
        result["cross_up"] = crossed_above(result["ma_fast"], result["ma_slow"])
        result["cross_down"] = crossed_below(result["ma_fast"], result["ma_slow"])
        safe_slow = result["ma_slow"].replace(0.0, pd.NA).astype("float64")
        result["separation_pct"] = (result["ma_fast"] - result["ma_slow"]) / safe_slow * 100.0
        result["separation_pct"] = (result["ma_fast"] - result["ma_slow"]) / safe_slow * 100.0
        # A raw crossover bar has the two averages sitting on top of each other,
        # so its separation is nearly zero by definition. Requiring a minimum
        # separation on that bar would reject almost every signal. Instead the
        # entry fires on the bar where the gap first becomes meaningful, which
        # is a confirmed cross rather than a momentary touch.
        gap = result["separation_pct"]
        result["confirmed_up"] = (gap >= params.min_separation_pct) & (
            gap.shift(1) < params.min_separation_pct
        )
        result["confirmed_down"] = (gap <= -params.min_separation_pct) & (
            gap.shift(1) > -params.min_separation_pct
        )
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
        params: GoldenCrossParams = self.params  # type: ignore[assignment]
        row = prepared.iloc[index]
        indicators: dict[str, Any] = self._indicator_snapshot(row, INDICATOR_COLUMNS)
        indicators["close"] = safe_float(row["close"])

        close = safe_float(row["close"])
        atr_value = safe_float(row["atr"])
        fast = safe_float(row["ma_fast"])
        slow = safe_float(row["ma_slow"])
        separation = safe_float(row["separation_pct"])

        if None in (close, atr_value, fast, slow, separation) or not atr_value:
            return self._hold(symbol, timeframe, row, "Averages not ready", indicators, regime)

        if position_side and params.exit_on_death_cross:
            side = position_side.upper()
            if side == "LONG" and bool(row.get("cross_down", False)):
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="Death cross: fast average crossed below the slow one",
                    indicators=indicators,
                    regime=regime,
                )
            if side == "SHORT" and bool(row.get("cross_up", False)):
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="Golden cross against the short position",
                    indicators=indicators,
                    regime=regime,
                )

        if regime is not None and params.avoid_extreme_volatility and regime.is_extreme:
            return self._hold(
                symbol, timeframe, row, "Extreme volatility: standing aside", indicators, regime
            )

        if bool(row.get("confirmed_up", False)):
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
                confidence=clamp01(0.45 + 0.4 * clamp01(separation / 2.0)),
                explanation=(
                    f"Golden cross: MA{params.fast_period} crossed above MA{params.slow_period} "
                    f"({separation:.2f} percent apart)."
                ),
                indicators=indicators,
                regime=regime,
                trailing_multiplier=params.trailing_atr_multiplier,
            )
        if params.allow_short and bool(row.get("confirmed_down", False)):
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
                confidence=clamp01(0.45 + 0.4 * clamp01(abs(separation) / 2.0)),
                explanation=(
                    f"Death cross: MA{params.fast_period} crossed below MA{params.slow_period} "
                    f"({separation:.2f} percent apart)."
                ),
                indicators=indicators,
                regime=regime,
                trailing_multiplier=params.trailing_atr_multiplier,
            )

        return self._hold(symbol, timeframe, row, "No moving average crossover", indicators, regime)
