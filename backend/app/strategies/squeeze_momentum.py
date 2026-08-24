"""Bollinger/Keltner squeeze momentum (RISKY).

Volatility compresses (Bollinger bands squeeze inside the Keltner channel),
then expands. The strategy waits for the squeeze to release and takes the
direction of momentum.

Risky because the release direction is genuinely uncertain: a squeeze tells you
that a move is coming, not which way. See docs/strategies/04-risky-strategies.md.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.core.constants import RiskLevel, SignalType
from app.indicators import atr, bollinger_bands, ema, keltner_channels, rate_of_change, safe_float
from app.regime.engine import RegimeResult
from app.signals.models import StrategySignal
from app.strategies.base import BaseStrategy, clamp01
from app.strategies.helpers import atr_entry_signal, close_signal

INDICATOR_COLUMNS = [
    "bb_upper",
    "bb_lower",
    "keltner_upper",
    "keltner_lower",
    "squeeze_on",
    "momentum",
    "atr",
    "ema_trend",
]


class SqueezeMomentumParams(BaseModel):
    """Configurable parameters."""

    bb_period: int = Field(default=20, ge=5, le=200)
    bb_std: float = Field(default=2.0, gt=0.1, le=6.0)
    keltner_period: int = Field(default=20, ge=5, le=200)
    keltner_multiplier: float = Field(default=1.5, gt=0.1, le=10.0)
    atr_period: int = Field(default=14, ge=2, le=100)
    momentum_period: int = Field(default=12, ge=1, le=200)
    min_squeeze_bars: int = Field(
        default=4, ge=1, le=100, description="How long the squeeze must last first"
    )
    min_momentum_pct: float = Field(default=0.15, ge=0.0, le=20.0)
    atr_stop_multiplier: float = Field(default=2.0, gt=0.1, le=10.0)
    take_profit_r: float = Field(default=2.0, gt=0.1, le=20.0)
    trailing_atr_multiplier: float = Field(default=2.5, ge=0.0, le=20.0)
    use_trend_filter: bool = Field(default=True)
    trend_ema: int = Field(default=100, ge=5, le=1000)
    allow_short: bool = Field(default=True)
    avoid_extreme_volatility: bool = Field(default=True)


class SqueezeMomentumStrategy(BaseStrategy):
    """Trades the release of a volatility squeeze."""

    key = "squeeze_momentum"
    name = "Sıkışma Momentumu"
    family = "breakout"
    risk_level = RiskLevel.RISKY
    description = (
        "Bollinger bantları Keltner kanalının içine girdiğinde (sıkışma) bekler, "
        "sıkışma çözüldüğünde momentum yönünde girer. Sıkışmanın ne zaman "
        "çözüleceğini bilmez."
    )
    params_model = SqueezeMomentumParams

    @property
    def warmup_bars(self) -> int:
        params: SqueezeMomentumParams = self.params  # type: ignore[assignment]
        return max(params.trend_ema, params.bb_period, params.keltner_period) + 30

    def prepare(self, frame: pd.DataFrame, timeframe: str = "") -> pd.DataFrame:
        params: SqueezeMomentumParams = self.params  # type: ignore[assignment]
        result = frame.copy()
        high, low, close = result["high"], result["low"], result["close"]

        bands = bollinger_bands(close, params.bb_period, params.bb_std)
        channels = keltner_channels(
            high, low, close, params.keltner_period, params.atr_period, params.keltner_multiplier
        )
        for column in bands.columns:
            result[column] = bands[column]
        for column in channels.columns:
            result[column] = channels[column]

        squeeze = (result["bb_upper"] < result["keltner_upper"]) & (
            result["bb_lower"] > result["keltner_lower"]
        )
        result["squeeze_on"] = squeeze.astype("float64")
        result["squeeze_bars"] = squeeze.groupby((~squeeze).cumsum()).cumcount() + 1
        result["squeeze_bars"] = result["squeeze_bars"].where(squeeze, 0)
        result["momentum"] = rate_of_change(close, params.momentum_period) * 100.0
        result["atr"] = atr(high, low, close, params.atr_period)
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
        params: SqueezeMomentumParams = self.params  # type: ignore[assignment]
        row = self._row(prepared, index)
        indicators: dict[str, Any] = self._indicator_snapshot(row, INDICATOR_COLUMNS)
        indicators["close"] = safe_float(row["close"])

        close = safe_float(row["close"])
        atr_value = safe_float(row["atr"])
        momentum = safe_float(row["momentum"])
        trend_value = safe_float(row["ema_trend"])
        squeeze_now = bool(safe_float(row["squeeze_on"]) or 0.0)

        if None in (close, atr_value, momentum) or not atr_value or index == 0:
            return self._hold(symbol, timeframe, row, "Indicators not ready", indicators, regime)

        previous = self._row(prepared, index - 1)
        squeeze_before = safe_float(previous.get("squeeze_bars")) or 0.0
        released = (not squeeze_now) and squeeze_before >= params.min_squeeze_bars
        indicators["squeeze_bars_before_release"] = squeeze_before

        if position_side:
            side = position_side.upper()
            if side == "LONG" and momentum < 0:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="Momentum turned negative",
                    indicators=indicators,
                    regime=regime,
                )
            if side == "SHORT" and momentum > 0:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="Momentum turned positive",
                    indicators=indicators,
                    regime=regime,
                )

        if regime is not None and params.avoid_extreme_volatility and regime.is_extreme:
            return self._hold(
                symbol,
                timeframe,
                row,
                "Extreme volatility: squeeze trade skipped",
                indicators,
                regime,
            )

        if not released:
            reason = (
                f"Squeeze still building ({squeeze_before:.0f} bars)"
                if squeeze_now
                else "No squeeze release"
            )
            return self._hold(symbol, timeframe, row, reason, indicators, regime)

        trend_ok_long = not params.use_trend_filter or trend_value is None or close > trend_value
        trend_ok_short = not params.use_trend_filter or trend_value is None or close < trend_value
        strength = clamp01(abs(momentum) / max(params.min_momentum_pct * 4.0, 1e-9))
        duration = clamp01(squeeze_before / 20.0)

        if momentum >= params.min_momentum_pct and trend_ok_long:
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
                confidence=clamp01(0.3 + 0.45 * strength + 0.25 * duration),
                explanation=(
                    f"Squeeze released after {squeeze_before:.0f} bars with momentum "
                    f"{momentum:.2f} percent: LONG."
                ),
                indicators=indicators,
                regime=regime,
                trailing_multiplier=params.trailing_atr_multiplier,
            )
        if params.allow_short and momentum <= -params.min_momentum_pct and trend_ok_short:
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
                confidence=clamp01(0.3 + 0.45 * strength + 0.25 * duration),
                explanation=(
                    f"Squeeze released after {squeeze_before:.0f} bars with momentum "
                    f"{momentum:.2f} percent: SHORT."
                ),
                indicators=indicators,
                regime=regime,
                trailing_multiplier=params.trailing_atr_multiplier,
            )

        return self._hold(
            symbol, timeframe, row, "Squeeze released but momentum is too weak", indicators, regime
        )
