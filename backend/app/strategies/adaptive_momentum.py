"""Adaptive EMA + RSI + ATR Momentum Day Trader.

A rule-based intraday momentum system: a 1 hour EMA trend filter gates a 15
minute entry system built from EMA structure, RSI momentum, volume
confirmation, ADX trend strength, VWAP location and a short breakout.

Instead of an all-or-nothing set of conditions, each component contributes to a
0-100 signal score and only scores above a configurable threshold are traded.
That makes the strictness itself a single tunable number rather than a wall of
booleans, and it lets the research pipeline measure how sensitive the results
are to it.

Look-ahead safety:
* the 1h trend is computed from CLOSED 1h candles only (shifted one bucket)
* the breakout level uses the previous N highs/lows, shifted by one bar
* every indicator is causal and evaluate() reads a single row

See docs/strategies/07-adaptive-momentum.md.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.core.constants import RiskLevel, SignalType
from app.indicators import (
    adx,
    atr,
    ema,
    highest,
    lowest,
    rolling_vwap,
    rsi,
    safe_float,
    sma,
)
from app.regime.engine import RegimeResult
from app.signals.models import StrategySignal
from app.strategies.base import BaseStrategy, clamp01, higher_timeframe_trend
from app.strategies.helpers import atr_entry_signal, close_signal

INDICATOR_COLUMNS = [
    "ema_fast",
    "ema_slow",
    "rsi",
    "adx",
    "atr",
    "atr_pct",
    "vwap",
    "volume_sma",
    "volume_ratio",
    "breakout_high",
    "breakout_low",
    "htf_ema_fast",
    "htf_ema_slow",
    "htf_close",
]

#: Component weights of the 0-100 signal score. They must add up to 100.
SCORE_WEIGHTS: dict[str, float] = {
    "trend": 20.0,
    "ema_momentum": 15.0,
    "rsi": 10.0,
    "volume": 15.0,
    "adx": 10.0,
    "vwap": 10.0,
    "breakout": 20.0,
}


class AdaptiveMomentumParams(BaseModel):
    """Every rule of the strategy, exposed as a tunable parameter."""

    # -- entry structure ----------------------------------------------------
    ema_fast: int = Field(default=20, ge=5, le=60, description="Fast EMA on the trading timeframe")
    ema_slow: int = Field(
        default=50, ge=10, le=200, description="Slow EMA on the trading timeframe"
    )
    rsi_period: int = Field(default=14, ge=5, le=30)
    rsi_long_min: float = Field(default=52.0, ge=45.0, le=60.0)
    rsi_long_max: float = Field(default=72.0, ge=60.0, le=90.0)
    rsi_short_max: float = Field(default=48.0, ge=40.0, le=55.0)
    rsi_short_min: float = Field(default=28.0, ge=10.0, le=40.0)
    adx_period: int = Field(default=14, ge=5, le=30)
    min_adx: float = Field(default=20.0, ge=10.0, le=40.0)
    volume_period: int = Field(default=20, ge=5, le=100)
    volume_multiplier: float = Field(default=1.20, ge=0.8, le=3.0)
    vwap_period: int = Field(default=48, ge=10, le=200)
    breakout_lookback: int = Field(default=5, ge=2, le=20)

    # -- higher timeframe trend filter --------------------------------------
    higher_timeframe: str = Field(default="1h")
    htf_ema_fast: int = Field(default=50, ge=10, le=200)
    htf_ema_slow: int = Field(default=200, ge=50, le=400)
    require_htf_trend: bool = Field(default=True)

    # -- scoring ------------------------------------------------------------
    min_signal_score: float = Field(
        default=70.0, ge=40.0, le=100.0, description="Minimum 0-100 score required to trade"
    )
    require_all_hard_rules: bool = Field(
        default=False,
        description="When true every rule must pass, not just the score threshold",
    )

    # -- risk ---------------------------------------------------------------
    atr_period: int = Field(default=14, ge=5, le=30)
    atr_stop_multiplier: float = Field(default=1.5, ge=0.8, le=4.0)
    take_profit_r: float = Field(default=2.0, ge=0.5, le=6.0)

    # -- exit model ---------------------------------------------------------
    exit_model: str = Field(
        default="atr",
        description="atr (ATR trailing), ema (close through the fast EMA) or hybrid",
    )
    trailing_atr_multiplier: float = Field(default=1.5, ge=0.0, le=6.0)

    # -- market quality filters --------------------------------------------
    min_atr_pct: float = Field(
        default=0.30, ge=0.0, le=5.0, description="Skip dead markets (ATR as percent of price)"
    )
    max_atr_pct: float = Field(default=5.0, ge=0.5, le=30.0)
    avoid_extreme_volatility: bool = Field(default=True)
    trade_only_in_trending_regime: bool = Field(
        default=False, description="Require the regime engine to confirm a trend"
    )
    allow_short: bool = Field(default=True)


class AdaptiveMomentumStrategy(BaseStrategy):
    """Scored intraday momentum system with a higher timeframe trend gate."""

    key = "adaptive_momentum"
    name = "Adaptive EMA + RSI + ATR Momentum Day Trader"
    family = "momentum"
    risk_level = RiskLevel.MEDIUM
    description = (
        "Intraday momentum on 15m gated by a 1h EMA trend filter. Seven "
        "components (trend, EMA structure, RSI, volume, ADX, VWAP, breakout) "
        "produce a 0-100 score and only high scores are traded. Designed for "
        "trending intraday conditions; it loses money in chop and pays a large "
        "cost bill if the score threshold is set too low."
    )
    params_model = AdaptiveMomentumParams

    @property
    def warmup_bars(self) -> int:
        params: AdaptiveMomentumParams = self.params  # type: ignore[assignment]
        htf_bars_needed = params.htf_ema_slow * 4  # 1h buckets seen from 15m bars
        return max(params.ema_slow * 3, params.vwap_period * 2, htf_bars_needed, 250) + 20

    def prepare(self, frame: pd.DataFrame, timeframe: str = "") -> pd.DataFrame:
        params: AdaptiveMomentumParams = self.params  # type: ignore[assignment]
        result = frame.copy()
        high, low, close, volume = (
            result["high"],
            result["low"],
            result["close"],
            result["volume"],
        )

        result["ema_fast"] = ema(close, params.ema_fast)
        result["ema_slow"] = ema(close, params.ema_slow)
        result["rsi"] = rsi(close, params.rsi_period)
        adx_values, _, _ = adx(high, low, close, params.adx_period)
        result["adx"] = adx_values
        result["atr"] = atr(high, low, close, params.atr_period)
        result["atr_pct"] = result["atr"] / close.replace(0.0, pd.NA).astype("float64") * 100.0
        result["vwap"] = rolling_vwap(high, low, close, volume, params.vwap_period)

        result["volume_sma"] = sma(volume, params.volume_period)
        safe_volume_sma = result["volume_sma"].replace(0.0, pd.NA).astype("float64")
        result["volume_ratio"] = volume / safe_volume_sma

        # Shifted by one bar: the level a candle breaks out of must be built
        # from the candles BEFORE it, never including itself.
        result["breakout_high"] = highest(high, params.breakout_lookback, shift=1)
        result["breakout_low"] = lowest(low, params.breakout_lookback, shift=1)

        htf = higher_timeframe_trend(
            result, params.higher_timeframe, params.htf_ema_fast, params.htf_ema_slow
        )
        for column in htf.columns:
            result[column] = htf[column]
        return result

    # -- scoring ------------------------------------------------------------
    def _score(self, row: Any, direction: SignalType) -> tuple[float, dict[str, float]]:
        """Return the 0-100 signal score and the contribution of each component.

        Every component is a hard rule; the score simply records how many of
        them agreed. Reporting the breakdown means a rejected signal can always
        be explained to the user.
        """
        params: AdaptiveMomentumParams = self.params  # type: ignore[assignment]
        long_side = direction == SignalType.LONG

        close = safe_float(row["close"])
        ema_fast = safe_float(row["ema_fast"])
        ema_slow = safe_float(row["ema_slow"])
        rsi_value = safe_float(row["rsi"])
        adx_value = safe_float(row["adx"])
        vwap_value = safe_float(row["vwap"])
        volume_ratio = safe_float(row["volume_ratio"])
        breakout_high = safe_float(row["breakout_high"])
        breakout_low = safe_float(row["breakout_low"])
        high = safe_float(row["high"])
        low = safe_float(row["low"])
        htf_fast = safe_float(row["htf_ema_fast"])
        htf_slow = safe_float(row["htf_ema_slow"])
        htf_close = safe_float(row["htf_close"])

        components: dict[str, float] = dict.fromkeys(SCORE_WEIGHTS, 0.0)

        # 1h trend filter
        if htf_fast is not None and htf_slow is not None and htf_close is not None:
            trend_ok = (
                (htf_fast > htf_slow and htf_close > htf_slow)
                if long_side
                else (htf_fast < htf_slow and htf_close < htf_slow)
            )
            if trend_ok:
                components["trend"] = SCORE_WEIGHTS["trend"]
        elif not params.require_htf_trend:
            components["trend"] = SCORE_WEIGHTS["trend"]

        # EMA structure on the trading timeframe
        if None not in (close, ema_fast, ema_slow):
            stack_ok = (
                (ema_fast > ema_slow and close > ema_fast)
                if long_side
                else (ema_fast < ema_slow and close < ema_fast)
            )
            if stack_ok:
                components["ema_momentum"] = SCORE_WEIGHTS["ema_momentum"]

        # RSI momentum band
        if rsi_value is not None:
            rsi_ok = (
                params.rsi_long_min < rsi_value < params.rsi_long_max
                if long_side
                else params.rsi_short_min < rsi_value < params.rsi_short_max
            )
            if rsi_ok:
                components["rsi"] = SCORE_WEIGHTS["rsi"]

        # Volume confirmation
        if volume_ratio is not None and volume_ratio >= params.volume_multiplier:
            components["volume"] = SCORE_WEIGHTS["volume"]

        # Trend strength
        if adx_value is not None and adx_value > params.min_adx:
            components["adx"] = SCORE_WEIGHTS["adx"]

        # Location relative to VWAP
        if None not in (close, vwap_value):
            vwap_ok = close > vwap_value if long_side else close < vwap_value
            if vwap_ok:
                components["vwap"] = SCORE_WEIGHTS["vwap"]

        # Short breakout confirmation
        level = breakout_high if long_side else breakout_low
        probe = high if long_side else low
        if level is not None and probe is not None:
            broke = probe > level if long_side else probe < level
            if broke:
                components["breakout"] = SCORE_WEIGHTS["breakout"]

        return sum(components.values()), components

    def evaluate(
        self,
        prepared: Any,
        index: int,
        *,
        symbol: str,
        timeframe: str,
        regime: RegimeResult | None = None,
        position_side: str | None = None,
    ) -> StrategySignal:
        params: AdaptiveMomentumParams = self.params  # type: ignore[assignment]
        row = self._row(prepared, index)
        indicators: dict[str, Any] = self._indicator_snapshot(row, INDICATOR_COLUMNS)
        indicators["close"] = safe_float(row["close"])

        close = safe_float(row["close"])
        atr_value = safe_float(row["atr"])
        atr_pct = safe_float(row["atr_pct"])
        ema_fast = safe_float(row["ema_fast"])

        if None in (close, atr_value) or not atr_value:
            return self._hold(symbol, timeframe, row, "Indicators not ready", indicators, regime)

        # --- exit management for an open position --------------------------
        if position_side:
            side = position_side.upper()
            if params.exit_model in ("ema", "hybrid") and ema_fast is not None:
                if side == "LONG" and close < ema_fast:
                    return close_signal(
                        strategy_key=self.key,
                        symbol=symbol,
                        timeframe=timeframe,
                        row=row,
                        reason=f"Closed below the {params.ema_fast} EMA",
                        indicators=indicators,
                        regime=regime,
                    )
                if side == "SHORT" and close > ema_fast:
                    return close_signal(
                        strategy_key=self.key,
                        symbol=symbol,
                        timeframe=timeframe,
                        row=row,
                        reason=f"Closed above the {params.ema_fast} EMA",
                        indicators=indicators,
                        regime=regime,
                    )

        # --- market quality gates ------------------------------------------
        if regime is not None and params.avoid_extreme_volatility and regime.is_extreme:
            return self._hold(
                symbol, timeframe, row, "Extreme volatility: standing aside", indicators, regime
            )
        if regime is not None and params.trade_only_in_trending_regime and not regime.is_trending:
            return self._hold(symbol, timeframe, row, "Regime is not trending", indicators, regime)
        if atr_pct is not None and atr_pct < params.min_atr_pct:
            return self._hold(
                symbol,
                timeframe,
                row,
                f"Volatility too low to cover costs (ATR {atr_pct:.2f} percent)",
                indicators,
                regime,
            )
        if atr_pct is not None and atr_pct > params.max_atr_pct:
            return self._hold(
                symbol,
                timeframe,
                row,
                f"Volatility too high (ATR {atr_pct:.2f} percent)",
                indicators,
                regime,
            )

        # --- score both directions and take the better one -----------------
        long_score, long_parts = self._score(row, SignalType.LONG)
        short_score, short_parts = self._score(row, SignalType.SHORT)
        if not params.allow_short:
            short_score = 0.0

        direction = SignalType.LONG if long_score >= short_score else SignalType.SHORT
        score, parts = (
            (long_score, long_parts) if direction == SignalType.LONG else (short_score, short_parts)
        )
        indicators["signal_score"] = score
        indicators.update({f"score_{name}": value for name, value in parts.items()})

        # The higher timeframe filter exists so the 15m system does not keep
        # trading against the dominant trend. Scoring alone would let a signal
        # through at 80/100 with the trend component missing, so when the
        # filter is switched on it is a hard gate rather than 20 points.
        if params.require_htf_trend and parts["trend"] == 0.0:
            return self._hold(
                symbol,
                timeframe,
                row,
                f"{params.higher_timeframe} trend does not confirm {direction.value}",
                indicators,
                regime,
            )

        if score < params.min_signal_score:
            missing = [name for name, value in parts.items() if value == 0.0]
            return self._hold(
                symbol,
                timeframe,
                row,
                f"Score {score:.0f}/100 below the {params.min_signal_score:.0f} threshold "
                f"(missing: {', '.join(missing) or 'none'})",
                indicators,
                regime,
            )
        if params.require_all_hard_rules and score < 100.0:
            missing = [name for name, value in parts.items() if value == 0.0]
            return self._hold(
                symbol,
                timeframe,
                row,
                f"Strict mode: {', '.join(missing)} did not confirm",
                indicators,
                regime,
            )

        trailing = params.trailing_atr_multiplier if params.exit_model in ("atr", "hybrid") else 0.0
        confirmed = [name for name, value in parts.items() if value > 0.0]
        return atr_entry_signal(
            strategy_key=self.key,
            symbol=symbol,
            timeframe=timeframe,
            row=row,
            direction=direction,
            entry_price=close,
            atr_value=atr_value,
            stop_multiplier=params.atr_stop_multiplier,
            take_profit_r=params.take_profit_r,
            confidence=clamp01(score / 100.0),
            explanation=(
                f"{direction.value} score {score:.0f}/100 "
                f"({', '.join(confirmed)}); stop {params.atr_stop_multiplier} ATR, "
                f"target {params.take_profit_r}R, exit model {params.exit_model}."
            ),
            indicators=indicators,
            regime=regime,
            trailing_multiplier=trailing,
        )
