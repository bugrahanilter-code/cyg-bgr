"""RSI divergence reversal (RISKY).

Fades a move when price and RSI disagree: price makes a lower low while RSI
makes a higher low (bullish), or the mirror image (bearish).

This is counter-trend trading. It is the most dangerous family in the platform
because a divergence can persist for a very long time in a strong trend, which
is why the regime filter and a hard stop are mandatory here.
See docs/strategies/04-risky-strategies.md.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.core.constants import RiskLevel, SignalType
from app.indicators import atr, ema, rsi, safe_float
from app.regime.engine import RegimeResult
from app.signals.models import StrategySignal
from app.strategies.base import BaseStrategy, clamp01
from app.strategies.helpers import atr_entry_signal, close_signal

INDICATOR_COLUMNS = ["rsi", "atr", "price_change", "rsi_change", "ema_trend"]


class RsiDivergenceParams(BaseModel):
    """Configurable parameters."""

    rsi_period: int = Field(default=14, ge=2, le=100)
    lookback: int = Field(default=14, ge=2, le=200, description="Bars used to compare the swing")
    oversold: float = Field(default=38.0, ge=1.0, le=49.0)
    overbought: float = Field(default=62.0, ge=51.0, le=99.0)
    min_price_move_pct: float = Field(
        default=0.5, ge=0.0, le=50.0, description="Minimum move before a divergence counts"
    )
    min_rsi_gap: float = Field(default=3.0, ge=0.0, le=50.0)
    atr_period: int = Field(default=14, ge=2, le=100)
    atr_stop_multiplier: float = Field(default=1.5, gt=0.1, le=10.0)
    take_profit_r: float = Field(default=2.0, gt=0.1, le=20.0)
    exit_rsi_neutral: float = Field(default=50.0, ge=20.0, le=80.0)
    disable_in_trending_regime: bool = Field(default=True)
    trend_ema: int = Field(default=200, ge=10, le=1000)
    allow_short: bool = Field(default=True)
    avoid_extreme_volatility: bool = Field(default=True)


class RsiDivergenceStrategy(BaseStrategy):
    """Counter-trend reversal on price/RSI disagreement."""

    key = "rsi_divergence"
    name = "RSI Divergence Reversal"
    family = "mean_reversion"
    risk_level = RiskLevel.RISKY
    description = (
        "Buys when price makes a lower low but RSI does not, and sells the "
        "mirror case. Counter-trend by construction: it can be wrong for a "
        "long time during a strong move."
    )
    params_model = RsiDivergenceParams

    @property
    def warmup_bars(self) -> int:
        params: RsiDivergenceParams = self.params  # type: ignore[assignment]
        return max(params.trend_ema, params.lookback * 3, params.rsi_period * 3) + 10

    def prepare(self, frame: pd.DataFrame, timeframe: str = "") -> pd.DataFrame:
        params: RsiDivergenceParams = self.params  # type: ignore[assignment]
        result = frame.copy()
        close = result["close"]
        result["rsi"] = rsi(close, params.rsi_period)
        result["atr"] = atr(result["high"], result["low"], close, params.atr_period)
        previous_close = close.shift(params.lookback)
        result["price_change"] = (close - previous_close) / previous_close * 100.0
        result["rsi_change"] = result["rsi"] - result["rsi"].shift(params.lookback)
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
        params: RsiDivergenceParams = self.params  # type: ignore[assignment]
        row = self._row(prepared, index)
        indicators: dict[str, Any] = self._indicator_snapshot(row, INDICATOR_COLUMNS)
        indicators["close"] = safe_float(row["close"])

        close = safe_float(row["close"])
        rsi_value = safe_float(row["rsi"])
        atr_value = safe_float(row["atr"])
        price_change = safe_float(row["price_change"])
        rsi_change = safe_float(row["rsi_change"])

        if None in (close, rsi_value, atr_value, price_change, rsi_change) or not atr_value:
            return self._hold(symbol, timeframe, row, "Indicators not ready", indicators, regime)

        if position_side:
            side = position_side.upper()
            if side == "LONG" and rsi_value >= params.exit_rsi_neutral:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="RSI back to neutral",
                    indicators=indicators,
                    regime=regime,
                )
            if side == "SHORT" and rsi_value <= params.exit_rsi_neutral:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="RSI back to neutral",
                    indicators=indicators,
                    regime=regime,
                )

        if regime is not None:
            if params.avoid_extreme_volatility and regime.is_extreme:
                return self._hold(
                    symbol,
                    timeframe,
                    row,
                    "Extreme volatility: reversal disabled",
                    indicators,
                    regime,
                )
            if params.disable_in_trending_regime and regime.is_trending:
                return self._hold(
                    symbol,
                    timeframe,
                    row,
                    f"Trending regime ({regime.regime.value}): fading it is too dangerous",
                    indicators,
                    regime,
                )

        bullish = (
            price_change <= -params.min_price_move_pct
            and rsi_change >= params.min_rsi_gap
            and rsi_value <= params.oversold
        )
        bearish = (
            price_change >= params.min_price_move_pct
            and rsi_change <= -params.min_rsi_gap
            and rsi_value >= params.overbought
        )

        if bullish:
            confidence = clamp01(
                0.3
                + 0.35 * clamp01(rsi_change / 15.0)
                + 0.35 * clamp01((params.oversold - rsi_value) / 15.0)
            )
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
                    f"Bullish divergence: price {price_change:.2f} percent lower over "
                    f"{params.lookback} bars while RSI rose {rsi_change:.1f} to {rsi_value:.1f}."
                ),
                indicators=indicators,
                regime=regime,
            )
        if params.allow_short and bearish:
            confidence = clamp01(
                0.3
                + 0.35 * clamp01(-rsi_change / 15.0)
                + 0.35 * clamp01((rsi_value - params.overbought) / 15.0)
            )
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
                    f"Bearish divergence: price {price_change:.2f} percent higher over "
                    f"{params.lookback} bars while RSI fell {rsi_change:.1f} to {rsi_value:.1f}."
                ),
                indicators=indicators,
                regime=regime,
            )

        return self._hold(
            symbol, timeframe, row, f"No divergence (RSI {rsi_value:.1f})", indicators, regime
        )
