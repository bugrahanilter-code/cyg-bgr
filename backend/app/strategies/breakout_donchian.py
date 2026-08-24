"""Strategy 2 - Donchian channel breakout.

Systematic breakout trading: buy when price closes above the highest high of
the previous N candles, sell when it closes below the lowest low. This is the
classic public "channel breakout" family. See
docs/strategies/02-breakout-donchian.md.

Look-ahead safety: the channel is built with a one-bar shift, so the level a
breakout is measured against never contains the breakout candle itself.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.core.constants import RiskLevel, SignalType
from app.indicators import atr, donchian_channel, ema, safe_float, volume_ratio
from app.regime.engine import RegimeResult
from app.signals.models import StrategySignal
from app.strategies.base import BaseStrategy, clamp01

INDICATOR_COLUMNS = [
    "donchian_upper",
    "donchian_lower",
    "donchian_middle",
    "exit_upper",
    "exit_lower",
    "atr",
    "atr_pct",
    "volume_ratio",
    "ema_trend",
]


class BreakoutParams(BaseModel):
    """Configurable breakout parameters."""

    channel_period: int = Field(default=20, ge=3, le=400, description="Entry channel length")
    exit_channel_period: int = Field(default=10, ge=2, le=400, description="Exit channel length")
    breakout_buffer_atr: float = Field(
        default=0.10, ge=0.0, le=5.0, description="Extra distance beyond the channel, in ATR"
    )
    atr_period: int = Field(default=14, ge=2, le=100)
    atr_stop_multiplier: float = Field(default=2.0, gt=0.1, le=10.0)
    take_profit_r: float = Field(default=2.5, gt=0.1, le=20.0)
    trailing_atr_multiplier: float = Field(default=3.0, ge=0.0, le=20.0)
    use_volume_confirmation: bool = Field(default=True)
    volume_period: int = Field(default=20, ge=2, le=400)
    min_volume_ratio: float = Field(default=1.15, ge=0.0, le=10.0)
    use_trend_filter: bool = Field(default=True)
    trend_ema: int = Field(default=100, ge=5, le=1000)
    min_atr_pct: float = Field(
        default=0.15, ge=0.0, le=50.0, description="Skip breakouts in dead markets"
    )
    max_atr_pct: float = Field(default=8.0, ge=0.1, le=100.0)
    allow_short: bool = Field(default=True)
    avoid_extreme_volatility: bool = Field(default=True)
    exit_on_opposite_channel: bool = Field(default=True)


class DonchianBreakoutStrategy(BaseStrategy):
    """Channel breakout with volume, trend and volatility filters."""

    key = "breakout_donchian"
    name = "Donchian Channel Breakout"
    family = "breakout"
    risk_level = RiskLevel.MEDIUM
    description = (
        "Buys new N-bar highs and sells new N-bar lows, filtered by volume, "
        "trend and volatility. Suffers from false breakouts in ranging markets."
    )
    params_model = BreakoutParams

    @property
    def warmup_bars(self) -> int:
        params: BreakoutParams = self.params  # type: ignore[assignment]
        return max(params.channel_period, params.trend_ema, params.atr_period * 3) + 10

    def prepare(self, frame: pd.DataFrame, timeframe: str = "") -> pd.DataFrame:
        params: BreakoutParams = self.params  # type: ignore[assignment]
        result = frame.copy()
        high, low, close = result["high"], result["low"], result["close"]

        channel = donchian_channel(high, low, params.channel_period, shift=1)
        result["donchian_upper"] = channel["donchian_upper"]
        result["donchian_lower"] = channel["donchian_lower"]
        result["donchian_middle"] = channel["donchian_middle"]

        exit_channel = donchian_channel(high, low, params.exit_channel_period, shift=1)
        result["exit_upper"] = exit_channel["donchian_upper"]
        result["exit_lower"] = exit_channel["donchian_lower"]

        result["atr"] = atr(high, low, close, params.atr_period)
        result["atr_pct"] = result["atr"] / close.replace(0.0, pd.NA).astype("float64") * 100.0
        result["volume_ratio"] = volume_ratio(result["volume"], params.volume_period)
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
        params: BreakoutParams = self.params  # type: ignore[assignment]
        row = self._row(prepared, index)
        indicators: dict[str, Any] = self._indicator_snapshot(row, INDICATOR_COLUMNS)
        indicators["close"] = safe_float(row["close"])

        close = safe_float(row["close"])
        upper = safe_float(row["donchian_upper"])
        lower = safe_float(row["donchian_lower"])
        atr_value = safe_float(row["atr"])
        atr_pct = safe_float(row["atr_pct"])
        volume_confirmation = safe_float(row["volume_ratio"])
        trend_ema_value = safe_float(row["ema_trend"])

        if None in (close, upper, lower, atr_value) or not atr_value:
            return self._hold(symbol, timeframe, row, "Channel not ready", indicators, regime)

        # Channel exit for an open position.
        if position_side and params.exit_on_opposite_channel:
            exit_upper = safe_float(row["exit_upper"])
            exit_lower = safe_float(row["exit_lower"])
            side = position_side.upper()
            if side == "LONG" and exit_lower is not None and close < exit_lower:
                return self._close(
                    symbol, timeframe, row, indicators, regime, "Closed below the exit channel"
                )
            if side == "SHORT" and exit_upper is not None and close > exit_upper:
                return self._close(
                    symbol, timeframe, row, indicators, regime, "Closed above the exit channel"
                )

        if regime is not None and params.avoid_extreme_volatility and regime.is_extreme:
            return self._hold(
                symbol, timeframe, row, "Extreme volatility: breakout skipped", indicators, regime
            )

        if atr_pct is not None and (atr_pct < params.min_atr_pct or atr_pct > params.max_atr_pct):
            return self._hold(
                symbol,
                timeframe,
                row,
                f"Volatility outside the tradable band (ATR {atr_pct:.2f} percent)",
                indicators,
                regime,
            )

        buffer_distance = params.breakout_buffer_atr * atr_value
        volume_ok = (
            not params.use_volume_confirmation
            or volume_confirmation is None
            or volume_confirmation >= params.min_volume_ratio
        )

        long_breakout = close > upper + buffer_distance
        short_breakout = close < lower - buffer_distance
        trend_ok_long = (
            not params.use_trend_filter or trend_ema_value is None or close > trend_ema_value
        )
        trend_ok_short = (
            not params.use_trend_filter or trend_ema_value is None or close < trend_ema_value
        )

        if long_breakout and volume_ok and trend_ok_long:
            return self._breakout_signal(
                symbol,
                timeframe,
                row,
                indicators,
                regime,
                SignalType.LONG,
                close,
                upper,
                atr_value,
                volume_confirmation,
            )
        if params.allow_short and short_breakout and volume_ok and trend_ok_short:
            return self._breakout_signal(
                symbol,
                timeframe,
                row,
                indicators,
                regime,
                SignalType.SHORT,
                close,
                lower,
                atr_value,
                volume_confirmation,
            )

        if long_breakout and not volume_ok:
            reason = "Breakout rejected: volume confirmation missing"
        elif long_breakout and not trend_ok_long:
            reason = "Breakout rejected: against the trend filter"
        else:
            reason = "Price inside the channel"
        return self._hold(symbol, timeframe, row, reason, indicators, regime)

    # -- signal builders ----------------------------------------------------
    def _breakout_signal(
        self,
        symbol: str,
        timeframe: str,
        row: pd.Series,
        indicators: dict[str, Any],
        regime: RegimeResult | None,
        direction: SignalType,
        close: float,
        level: float,
        atr_value: float,
        volume_confirmation: float | None,
    ) -> StrategySignal:
        params: BreakoutParams = self.params  # type: ignore[assignment]
        stop_distance = atr_value * params.atr_stop_multiplier
        if direction == SignalType.LONG:
            stop_loss = close - stop_distance
            take_profit = close + stop_distance * params.take_profit_r
        else:
            stop_loss = close + stop_distance
            take_profit = close - stop_distance * params.take_profit_r

        penetration = abs(close - level) / atr_value
        penetration_component = clamp01(penetration / 1.5)
        volume_component = clamp01(((volume_confirmation or 1.0) - 1.0) / 1.5)
        regime_component = 0.8 if (regime is None or not regime.is_trending) else 1.0
        confidence = clamp01(
            0.45 * penetration_component + 0.30 * volume_component + 0.25 * regime_component
        )

        channel_text = f"the {params.channel_period}-bar channel at {level:.2f}"
        if volume_confirmation is not None:
            explanation = (
                f"{direction.value} breakout of {channel_text} "
                f"({penetration:.2f} ATR beyond it), volume ratio "
                f"{volume_confirmation:.2f}."
            )
        else:
            explanation = f"{direction.value} breakout of {channel_text}."
        indicators["breakout_level"] = level
        indicators["penetration_atr"] = penetration
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

    def _close(
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
