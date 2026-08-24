"""Candle containers and conversions.

The rest of the platform works with a pandas DataFrame that has exactly these
columns: open_time, open, high, low, close, volume. Having one canonical shape
means indicators, strategies and the backtester can never disagree about the
data layout.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.core.exceptions import InsufficientDataError
from app.core.time_utils import from_ms

OHLCV_COLUMNS = ["open_time", "open", "high", "low", "close", "volume"]


@dataclass(frozen=True, slots=True)
class Candle:
    """A single OHLCV bar."""

    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def timestamp(self):
        return from_ms(self.open_time)


def rows_to_dataframe(rows: list[list[float]]) -> pd.DataFrame:
    """Convert raw exchange OHLCV rows into the canonical DataFrame."""
    frame = pd.DataFrame(rows, columns=OHLCV_COLUMNS)
    if frame.empty:
        return frame
    frame["open_time"] = frame["open_time"].astype("int64")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    frame = frame.dropna(subset=["open", "high", "low", "close"])
    frame = frame.drop_duplicates(subset=["open_time"], keep="last")
    frame = frame.sort_values("open_time").reset_index(drop=True)
    return frame


def dataframe_to_candles(frame: pd.DataFrame) -> list[Candle]:
    """Convert the canonical DataFrame into Candle objects."""
    return [
        Candle(
            open_time=int(row.open_time),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for row in frame.itertuples(index=False)
    ]


def require_min_length(frame: pd.DataFrame, minimum: int, context: str = "strategy") -> None:
    """Raise a typed error when there is not enough history to decide safely."""
    if len(frame) < minimum:
        raise InsufficientDataError(
            f"{context} needs at least {minimum} candles, received {len(frame)}"
        )


def drop_unclosed_candle(frame: pd.DataFrame, timeframe_ms: int, now_ms: int) -> pd.DataFrame:
    """Remove the candle that is still forming.

    Strategies must only ever see CLOSED candles. Feeding a partially formed
    bar into a strategy is the most common source of accidental look-ahead
    bias in live trading.
    """
    if frame.empty:
        return frame
    last_open = int(frame["open_time"].iloc[-1])
    if last_open + timeframe_ms > now_ms:
        return frame.iloc[:-1].reset_index(drop=True)
    return frame
