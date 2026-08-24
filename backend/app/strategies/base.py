"""Strategy base class.

Every strategy follows the same two-step contract:

1. prepare(frame)  - vectorised, causal indicator computation for the whole
   candle history. Called once per backtest, or once per new candle live.
2. evaluate(prepared, index, ...) - reads ONE row and returns a signal.

Splitting the work this way is what makes the backtest fast and, much more
importantly, what makes look-ahead bias structurally impossible: evaluate can
only see row `index`, and every column was produced by a causal indicator.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd
from pydantic import BaseModel

from app.core.constants import SignalType, timeframe_to_ms
from app.core.exceptions import StrategyError
from app.indicators import ema, safe_float
from app.regime.engine import RegimeResult
from app.signals.models import StrategySignal, hold


def clamp01(value: float) -> float:
    """Clamp a confidence score into the [0, 1] interval."""
    if value != value:  # NaN check without importing math
        return 0.0
    return max(0.0, min(1.0, float(value)))


def higher_timeframe_ema(frame: pd.DataFrame, higher_timeframe: str, period: int) -> pd.Series:
    """EMA of a higher timeframe, mapped back onto the lower timeframe bars.

    Only *completed* higher-timeframe candles are used (the series is shifted
    by one bucket), so a 15m bar never sees the 4h candle it belongs to.
    """
    bucket_ms = timeframe_to_ms(higher_timeframe)
    buckets = (frame["open_time"] // bucket_ms).astype("int64")
    closes = frame.groupby(buckets)["close"].last()
    htf_ema = ema(closes, period).shift(1)
    mapped = buckets.map(htf_ema)
    return pd.Series(mapped.to_numpy(), index=frame.index, dtype="float64")


class BaseStrategy(ABC):
    """Interface shared by every strategy in the platform."""

    key: str = "base"
    name: str = "Base strategy"
    family: str = "generic"
    description: str = ""
    params_model: type[BaseModel] = BaseModel

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        try:
            self.params = self.params_model(**(params or {}))
        except Exception as exc:  # pragma: no cover - surfaced through the API
            raise StrategyError(f"Invalid parameters for {self.key}: {exc}") from exc

    # -- configuration ------------------------------------------------------
    @classmethod
    def default_params(cls) -> dict[str, Any]:
        """Default parameter values as a plain dictionary."""
        return cls.params_model().model_dump()

    @classmethod
    def param_schema(cls) -> dict[str, Any]:
        """JSON schema used by the dashboard to render the settings form."""
        return cls.params_model.model_json_schema()

    def params_dict(self) -> dict[str, Any]:
        return self.params.model_dump()

    @property
    @abstractmethod
    def warmup_bars(self) -> int:
        """Number of candles required before the strategy may trade."""

    # -- computation --------------------------------------------------------
    @abstractmethod
    def prepare(self, frame: pd.DataFrame, timeframe: str = "") -> pd.DataFrame:
        """Return the candle frame enriched with this strategy's indicators."""

    @abstractmethod
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
        """Return the decision for the candle at the given index."""

    # -- convenience --------------------------------------------------------
    def generate(
        self,
        frame: pd.DataFrame,
        *,
        symbol: str,
        timeframe: str,
        regime: RegimeResult | None = None,
        position_side: str | None = None,
    ) -> StrategySignal:
        """Prepare and evaluate the most recent closed candle (live path)."""
        if frame is None or frame.empty:
            return hold(symbol, timeframe, self.key, 0, "No candles available")
        if len(frame) < self.warmup_bars:
            return hold(
                symbol,
                timeframe,
                self.key,
                int(frame["open_time"].iloc[-1]),
                f"Warming up: {len(frame)}/{self.warmup_bars} candles",
            )
        prepared = self.prepare(frame, timeframe)
        return self.evaluate(
            prepared,
            len(prepared) - 1,
            symbol=symbol,
            timeframe=timeframe,
            regime=regime,
            position_side=position_side,
        )

    # -- shared helpers -----------------------------------------------------
    @staticmethod
    def _value(row: pd.Series, column: str) -> float | None:
        return safe_float(row.get(column))

    @staticmethod
    def _indicator_snapshot(row: pd.Series, columns: list[str]) -> dict[str, float | None]:
        return {column: safe_float(row.get(column)) for column in columns}

    def _hold(
        self,
        symbol: str,
        timeframe: str,
        row: pd.Series,
        reason: str,
        indicators: dict[str, Any] | None = None,
        regime: RegimeResult | None = None,
    ) -> StrategySignal:
        return StrategySignal(
            symbol=symbol,
            timeframe=timeframe,
            strategy_key=self.key,
            signal=SignalType.HOLD,
            candle_open_time=int(row["open_time"]),
            confidence=0.0,
            explanation=reason,
            indicators=indicators or {},
            regime=regime,
        )
