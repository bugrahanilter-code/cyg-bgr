"""Persistence layer for historical candles.

Historical data is cached locally so backtests are reproducible and do not
hammer the exchange rate limits.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.time_utils import utcnow
from app.market_data.candles import OHLCV_COLUMNS, rows_to_dataframe
from app.models.market import Candle

logger = get_logger(__name__)


def latest_open_time(db: Session, symbol: str, timeframe: str) -> int | None:
    """Newest stored candle open time, or None when nothing is cached."""
    result = db.execute(
        select(func.max(Candle.open_time)).where(
            Candle.symbol == symbol, Candle.timeframe == timeframe
        )
    ).scalar()
    return int(result) if result is not None else None


def earliest_open_time(db: Session, symbol: str, timeframe: str) -> int | None:
    """Oldest stored candle open time."""
    result = db.execute(
        select(func.min(Candle.open_time)).where(
            Candle.symbol == symbol, Candle.timeframe == timeframe
        )
    ).scalar()
    return int(result) if result is not None else None


def count_candles(db: Session, symbol: str, timeframe: str) -> int:
    """Number of cached candles for a market/timeframe."""
    result = db.execute(
        select(func.count(Candle.id)).where(Candle.symbol == symbol, Candle.timeframe == timeframe)
    ).scalar()
    return int(result or 0)


def save_candles(db: Session, symbol: str, timeframe: str, frame: pd.DataFrame) -> int:
    """Insert candles that are not stored yet. Returns the number inserted.

    Uses a single bulk INSERT rather than one ORM object per row. Downloading a
    year of 15 minute candles means 35,000 rows per market, and a matrix
    backtest does that hundreds of times, so the difference between building
    35,000 mapped objects and issuing one executemany is most of the wall clock
    of a sweep.
    """
    if frame is None or frame.empty:
        return 0

    open_times = [int(value) for value in frame["open_time"].tolist()]
    existing = set(
        db.execute(
            select(Candle.open_time).where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
                Candle.open_time.in_(open_times),
            )
        )
        .scalars()
        .all()
    )

    timeframe_ms = int(frame["open_time"].diff().median()) if len(frame) > 1 else 0
    ingested = utcnow()
    payload: list[dict] = []
    for row in frame.itertuples(index=False):
        open_time = int(row.open_time)
        if open_time in existing:
            continue
        payload.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "open_time": open_time,
                "close_time": open_time + timeframe_ms - 1 if timeframe_ms else open_time,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
                "ingested_at": ingested,
                "created_at": ingested,
                "updated_at": ingested,
            }
        )

    if not payload:
        return 0
    db.execute(insert(Candle), payload)
    db.commit()
    return len(payload)


def load_candles(
    db: Session,
    symbol: str,
    timeframe: str,
    start_ms: int | None = None,
    end_ms: int | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """Load cached candles as the canonical DataFrame."""
    query = select(
        Candle.open_time, Candle.open, Candle.high, Candle.low, Candle.close, Candle.volume
    ).where(Candle.symbol == symbol, Candle.timeframe == timeframe)

    if start_ms is not None:
        query = query.where(Candle.open_time >= start_ms)
    if end_ms is not None:
        query = query.where(Candle.open_time <= end_ms)

    if limit is not None:
        query = query.order_by(Candle.open_time.desc()).limit(limit)
        rows = list(db.execute(query).all())
        rows.reverse()
    else:
        query = query.order_by(Candle.open_time.asc())
        rows = list(db.execute(query).all())

    if not rows:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    return rows_to_dataframe([[float(value) for value in row] for row in rows])


def delete_candles(db: Session, symbol: str, timeframe: str) -> int:
    """Remove every cached candle for a market/timeframe (maintenance helper)."""
    deleted = (
        db.query(Candle).filter(Candle.symbol == symbol, Candle.timeframe == timeframe).delete()
    )
    db.commit()
    return int(deleted or 0)


def range_coverage(
    db: Session, symbol: str, timeframe: str, start_ms: int, end_ms: int
) -> tuple[int, int | None, int | None]:
    """How much of ``[start_ms, end_ms]`` is already cached.

    Returns ``(count, first_open_time, last_open_time)``. Used to avoid
    re-downloading candles the database already holds, which is the difference
    between a matrix backtest taking hours and taking days.
    """
    row = db.execute(
        select(
            func.count(Candle.id),
            func.min(Candle.open_time),
            func.max(Candle.open_time),
        ).where(
            Candle.symbol == symbol,
            Candle.timeframe == timeframe,
            Candle.open_time >= start_ms,
            Candle.open_time <= end_ms,
        )
    ).one()
    count = int(row[0] or 0)
    return (
        count,
        (int(row[1]) if row[1] is not None else None),
        (int(row[2]) if row[2] is not None else None),
    )
