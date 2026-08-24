"""Strategy 3 - Statistical mean reversion.

Fades statistically extreme deviations from a short-term mean (Bollinger
bands, z-score, RSI, VWAP). See docs/strategies/03-mean-reversion.md.

CRITICAL SAFETY RULE
--------------------
Mean reversion is the fastest way to lose money in a strong trend, so this
strategy is regime aware: by default it stands aside whenever the Market
Regime Engine reports a trending market and only trades in ranging conditions.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.core.constants import SignalType
from app.indicators import adx, atr, bollinger_bands, rolling_vwap, rsi, safe_float, zscore
from app.regime.engine import RegimeResult
from app.signals.models import StrategySignal
from app.strategies.base import BaseStrategy, clamp01

INDICATOR_COLUMNS = [
    "bb_middle",
    "bb_upper",
    "bb_lower",
    "bb_percent_b",
    "bb_bandwidth",
    "zscore",
    "rsi",
    "vwap",
    "atr",
    "atr_pct",
    "adx",
]


class MeanReversionParams(BaseModel):
    """Configurable mean reversion parameters."""

    bb_period: int = Field(default=20, ge=5, le=400)
    bb_std: float = Field(default=2.0, gt=0.1, le=6.0)
    zscore_period: int = Field(default=20, ge=5, le=400)
    zscore_entry: float = Field(default=2.0, gt=0.1, le=6.0)
    zscore_exit: float = Field(default=0.3, ge=0.0, le=3.0)
    rsi_period: int = Field(default=14, ge=2, le=100)
    rsi_oversold: float = Field(default=30.0, ge=1.0, le=49.0)
    rsi_overbought: float = Field(default=70.0, ge=51.0, le=99.0)
    use_vwap_filter: bool = Field(default=True)
    vwap_period: int = Field(default=20, ge=2, le=400)
    atr_period: int = Field(default=14, ge=2, le=100)
    atr_stop_multiplier: float = Field(default=1.5, gt=0.1, le=10.0)
    take_profit_r: float = Field(default=1.5, gt=0.1, le=20.0)
    max_adx: float = Field(
        default=22.0, ge=1.0, le=60.0, description="Above this the market is trending, stand aside"
    )
    disable_in_trending_regime: bool = Field(
        default=True, description="Respect the Market Regime Engine verdict"
    )
    max_atr_pct: float = Field(default=6.0, ge=0.1, le=100.0)
    allow_short: bool = Field(default=True)
    exit_at_mean: bool = Field(default=True)
    avoid_extreme_volatility: bool = Field(default=True)


class MeanReversionStrategy(BaseStrategy):
    """Bollinger / z-score / RSI reversion, only in ranging markets."""

    key = "mean_reversion"
    name = "Statistical Mean Reversion"
    family = "mean_reversion"
    description = (
        "Fades extreme deviations from a rolling mean while a regime filter "
        "keeps it out of trending markets. Vulnerable to sustained trends and "
        "to volatility expansions."
    )
    params_model = MeanReversionParams

    @property
    def warmup_bars(self) -> int:
        params: MeanReversionParams = self.params  # type: ignore[assignment]
        return max(params.bb_period, params.zscore_period, params.vwap_period, 50) + 10

    def prepare(self, frame: pd.DataFrame, timeframe: str = "") -> pd.DataFrame:
        params: MeanReversionParams = self.params  # type: ignore[assignment]
        result = frame.copy()
        high, low, close, volume = (
            result["high"],
            result["low"],
            result["close"],
            result["volume"],
        )
        bands = bollinger_bands(close, params.bb_period, params.bb_std)
        for column in bands.columns:
            result[column] = bands[column]
        result["zscore"] = zscore(close, params.zscore_period)
        result["rsi"] = rsi(close, params.rsi_period)
        result["vwap"] = rolling_vwap(high, low, close, volume, params.vwap_period)
        result["atr"] = atr(high, low, close, params.atr_period)
        result["atr_pct"] = result["atr"] / close.replace(0.0, pd.NA).astype("float64") * 100.0
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
        params: MeanReversionParams = self.params  # type: ignore[assignment]
        row = prepared.iloc[index]
        indicators: dict[str, Any] = self._indicator_snapshot(row, INDICATOR_COLUMNS)
        indicators["close"] = safe_float(row["close"])

        close = safe_float(row["close"])
        middle = safe_float(row["bb_middle"])
        upper = safe_float(row["bb_upper"])
        lower = safe_float(row["bb_lower"])
        z_value = safe_float(row["zscore"])
        rsi_value = safe_float(row["rsi"])
        vwap_value = safe_float(row["vwap"])
        atr_value = safe_float(row["atr"])
        atr_pct = safe_float(row["atr_pct"])
        adx_value = safe_float(row["adx"])

        if None in (close, middle, upper, lower, z_value, rsi_value, atr_value) or not atr_value:
            return self._hold(symbol, timeframe, row, "Indicators not ready", indicators, regime)

        # Exit as soon as price has reverted to the mean.
        if position_side and params.exit_at_mean:
            side = position_side.upper()
            if side == "LONG" and z_value >= -params.zscore_exit:
                return self._close(
                    symbol, timeframe, row, indicators, regime, "Reverted to the mean"
                )
            if side == "SHORT" and z_value <= params.zscore_exit:
                return self._close(
                    symbol, timeframe, row, indicators, regime, "Reverted to the mean"
                )

        # --- Regime guards: this is what keeps the strategy out of trends ---
        if regime is not None:
            if params.avoid_extreme_volatility and regime.is_extreme:
                return self._hold(
                    symbol,
                    timeframe,
                    row,
                    "Extreme volatility: reversion disabled",
                    indicators,
                    regime,
                )
            if params.disable_in_trending_regime and regime.is_trending:
                return self._hold(
                    symbol,
                    timeframe,
                    row,
                    f"Trending regime ({regime.regime.value}): mean reversion disabled",
                    indicators,
                    regime,
                )

        if adx_value is not None and adx_value > params.max_adx:
            return self._hold(
                symbol,
                timeframe,
                row,
                f"ADX {adx_value:.1f} above {params.max_adx}: market is trending",
                indicators,
                regime,
            )
        if atr_pct is not None and atr_pct > params.max_atr_pct:
            return self._hold(
                symbol, timeframe, row, "Volatility too high for reversion", indicators, regime
            )

        vwap_long_ok = not params.use_vwap_filter or vwap_value is None or close < vwap_value
        vwap_short_ok = not params.use_vwap_filter or vwap_value is None or close > vwap_value

        long_setup = (
            z_value <= -params.zscore_entry and rsi_value <= params.rsi_oversold and close <= lower
        )
        short_setup = (
            z_value >= params.zscore_entry and rsi_value >= params.rsi_overbought and close >= upper
        )

        if long_setup and vwap_long_ok:
            return self._reversion_signal(
                symbol,
                timeframe,
                row,
                indicators,
                regime,
                SignalType.LONG,
                close,
                middle,
                atr_value,
                z_value,
                rsi_value,
            )
        if params.allow_short and short_setup and vwap_short_ok:
            return self._reversion_signal(
                symbol,
                timeframe,
                row,
                indicators,
                regime,
                SignalType.SHORT,
                close,
                middle,
                atr_value,
                z_value,
                rsi_value,
            )

        return self._hold(
            symbol,
            timeframe,
            row,
            f"No reversion setup (z-score {z_value:.2f}, RSI {rsi_value:.1f})",
            indicators,
            regime,
        )

    # -- signal builders ----------------------------------------------------
    def _reversion_signal(
        self,
        symbol: str,
        timeframe: str,
        row: pd.Series,
        indicators: dict[str, Any],
        regime: RegimeResult | None,
        direction: SignalType,
        close: float,
        middle: float,
        atr_value: float,
        z_value: float,
        rsi_value: float,
    ) -> StrategySignal:
        params: MeanReversionParams = self.params  # type: ignore[assignment]
        stop_distance = atr_value * params.atr_stop_multiplier
        if direction == SignalType.LONG:
            stop_loss = close - stop_distance
            take_profit = middle if middle > close else close + stop_distance * params.take_profit_r
        else:
            stop_loss = close + stop_distance
            take_profit = middle if middle < close else close - stop_distance * params.take_profit_r

        z_component = clamp01((abs(z_value) - params.zscore_entry) / 1.5 + 0.4)
        if direction == SignalType.LONG:
            rsi_component = clamp01((params.rsi_oversold - rsi_value) / 20.0 + 0.3)
        else:
            rsi_component = clamp01((rsi_value - params.rsi_overbought) / 20.0 + 0.3)
        regime_component = 1.0 if (regime is not None and not regime.is_trending) else 0.5
        confidence = clamp01(0.4 * z_component + 0.3 * rsi_component + 0.3 * regime_component)

        explanation = (
            f"{direction.value} reversion: z-score {z_value:.2f}, RSI {rsi_value:.1f}, "
            f"target the {params.bb_period}-period mean at {middle:.2f}."
        )
        indicators["mean_target"] = middle
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
            metadata={"atr": atr_value, "trailing_atr_multiplier": 0.0},
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
