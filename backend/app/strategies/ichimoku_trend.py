"""Ichimoku cloud trend following (MEDIUM risk).

A complete Japanese trend system: the cloud defines the trend, the conversion
and base lines define the trigger. It is slow and conservative compared with a
simple crossover, which is exactly why it is included.
See docs/strategies/05-medium-risk-strategies.md.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.core.constants import RiskLevel, SignalType
from app.indicators import atr, crossed_above, crossed_below, ichimoku, safe_float
from app.regime.engine import RegimeResult
from app.signals.models import StrategySignal
from app.strategies.base import BaseStrategy, clamp01
from app.strategies.helpers import atr_entry_signal, close_signal

INDICATOR_COLUMNS = ["tenkan", "kijun", "senkou_a", "senkou_b", "cloud_top", "cloud_bottom", "atr"]


class IchimokuParams(BaseModel):
    """Configurable parameters."""

    tenkan_period: int = Field(default=9, ge=2, le=100, description="Conversion line")
    kijun_period: int = Field(default=26, ge=2, le=200, description="Base line")
    senkou_b_period: int = Field(default=52, ge=5, le=400)
    require_price_above_cloud: bool = Field(default=True)
    require_cloud_direction: bool = Field(
        default=True, description="Senkou A above Senkou B for longs"
    )
    atr_period: int = Field(default=14, ge=2, le=100)
    atr_stop_multiplier: float = Field(default=2.0, gt=0.1, le=10.0)
    take_profit_r: float = Field(default=2.5, gt=0.1, le=20.0)
    trailing_atr_multiplier: float = Field(default=3.0, ge=0.0, le=20.0)
    use_kijun_as_stop: bool = Field(default=False)
    allow_short: bool = Field(default=True)
    exit_on_kijun_cross: bool = Field(default=True)
    avoid_extreme_volatility: bool = Field(default=True)


class IchimokuStrategy(BaseStrategy):
    """Tenkan/Kijun crossover confirmed by the cloud."""

    key = "ichimoku_trend"
    name = "Ichimoku Bulut Trendi"
    family = "trend"
    risk_level = RiskLevel.MEDIUM
    description = (
        "Fiyat bulutun doğru tarafındayken dönüşüm/temel çizgi kesişiminde girer. "
        "Tepkisi yavaştır; bu hem yanlış sinyalleri hem de her hareketin başlangıcını "
        "keser."
    )
    params_model = IchimokuParams

    @property
    def warmup_bars(self) -> int:
        params: IchimokuParams = self.params  # type: ignore[assignment]
        return params.senkou_b_period + params.kijun_period * 2 + 30

    def prepare(self, frame: pd.DataFrame, timeframe: str = "") -> pd.DataFrame:
        params: IchimokuParams = self.params  # type: ignore[assignment]
        result = frame.copy()
        high, low, close = result["high"], result["low"], result["close"]

        lines = ichimoku(
            high, low, close, params.tenkan_period, params.kijun_period, params.senkou_b_period
        )
        for column in lines.columns:
            result[column] = lines[column]
        result["tenkan_cross_up"] = crossed_above(result["tenkan"], result["kijun"])
        result["tenkan_cross_down"] = crossed_below(result["tenkan"], result["kijun"])
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
        params: IchimokuParams = self.params  # type: ignore[assignment]
        row = self._row(prepared, index)
        indicators: dict[str, Any] = self._indicator_snapshot(row, INDICATOR_COLUMNS)
        indicators["close"] = safe_float(row["close"])

        close = safe_float(row["close"])
        atr_value = safe_float(row["atr"])
        tenkan = safe_float(row["tenkan"])
        kijun = safe_float(row["kijun"])
        cloud_top = safe_float(row["cloud_top"])
        cloud_bottom = safe_float(row["cloud_bottom"])
        senkou_a = safe_float(row["senkou_a"])
        senkou_b = safe_float(row["senkou_b"])

        if None in (close, atr_value, tenkan, kijun, cloud_top, cloud_bottom) or not atr_value:
            return self._hold(symbol, timeframe, row, "Cloud not ready", indicators, regime)

        if position_side and params.exit_on_kijun_cross:
            side = position_side.upper()
            if side == "LONG" and close < kijun:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="Price closed below the base line",
                    indicators=indicators,
                    regime=regime,
                )
            if side == "SHORT" and close > kijun:
                return close_signal(
                    strategy_key=self.key,
                    symbol=symbol,
                    timeframe=timeframe,
                    row=row,
                    reason="Price closed above the base line",
                    indicators=indicators,
                    regime=regime,
                )

        if regime is not None and params.avoid_extreme_volatility and regime.is_extreme:
            return self._hold(
                symbol, timeframe, row, "Extreme volatility: standing aside", indicators, regime
            )

        cross_up = bool(row.get("tenkan_cross_up", False))
        cross_down = bool(row.get("tenkan_cross_down", False))
        above_cloud = not params.require_price_above_cloud or close > cloud_top
        below_cloud = not params.require_price_above_cloud or close < cloud_bottom
        cloud_bullish = (
            not params.require_cloud_direction
            or senkou_a is None
            or senkou_b is None
            or senkou_a > senkou_b
        )
        cloud_bearish = (
            not params.require_cloud_direction
            or senkou_a is None
            or senkou_b is None
            or senkou_a < senkou_b
        )
        thickness = abs((senkou_a or 0.0) - (senkou_b or 0.0)) / atr_value
        confidence = clamp01(0.45 + 0.35 * clamp01(thickness / 3.0))

        if cross_up and above_cloud and cloud_bullish:
            stop = kijun if params.use_kijun_as_stop and kijun < close else None
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
                    f"Conversion line crossed above the base line with price above the "
                    f"cloud ({cloud_top:.2f})."
                ),
                indicators=indicators,
                regime=regime,
                trailing_multiplier=params.trailing_atr_multiplier,
                stop_override=stop,
            )
        if params.allow_short and cross_down and below_cloud and cloud_bearish:
            stop = kijun if params.use_kijun_as_stop and kijun > close else None
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
                    f"Conversion line crossed below the base line with price under the "
                    f"cloud ({cloud_bottom:.2f})."
                ),
                indicators=indicators,
                regime=regime,
                trailing_multiplier=params.trailing_atr_multiplier,
                stop_override=stop,
            )

        return self._hold(symbol, timeframe, row, "No confirmed cloud setup", indicators, regime)
