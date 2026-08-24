"""A TradingView UDF datafeed served from our own candle store.

UDF ("Universal Data Feed") is the REST contract TradingView's *Advanced Charts*
library speaks. Implementing it here means the chart shows exactly the candles
the backtester used, rather than a visually similar series fetched from
somewhere else - which is the whole point of putting a chart next to a backtest.

Two TradingView products, two different things
---------------------------------------------
* The free **embedded widget** renders TradingView's own data inside an iframe.
  It needs no backend and is what the market browser uses today.
* The **Advanced Charts** library renders data *you* serve over exactly these
  endpoints. It is free but access has to be requested from TradingView, so the
  library file is not vendored here. When it is dropped in, this datafeed is
  already waiting for it at ``/api/udf``.

Nothing here is a data *source*: it is our own candles, re-shaped into someone
else's protocol.
"""

from __future__ import annotations

import contextlib
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import Context, DbSession
from app.core.constants import SUPPORTED_TIMEFRAMES, timeframe_to_minutes
from app.models.market import Symbol

router = APIRouter(prefix="/udf", tags=["udf"])

#: UDF resolutions -> our timeframe keys. "D"/"W" are the UDF spellings.
RESOLUTION_TO_TIMEFRAME: dict[str, str] = {
    "1": "1m",
    "3": "3m",
    "5": "5m",
    "15": "15m",
    "30": "30m",
    "60": "1h",
    "120": "2h",
    "240": "4h",
    "360": "6h",
    "480": "8h",
    "720": "12h",
    "1D": "1d",
    "D": "1d",
    "3D": "3d",
    "1W": "1w",
    "W": "1w",
}

SUPPORTED_RESOLUTIONS = [
    key for key, value in RESOLUTION_TO_TIMEFRAME.items() if value in SUPPORTED_TIMEFRAMES
]


def _to_timeframe(resolution: str) -> str:
    return RESOLUTION_TO_TIMEFRAME.get(str(resolution).upper(), "15m")


def _to_canonical(ticker: str) -> str:
    """``BINANCE:BTCUSDT.P`` / ``BTCUSDT`` / ``BTC/USDT`` -> ``BTC/USDT``."""
    body = ticker.split(":")[-1].upper()
    if body.endswith(".P"):
        body = body[:-2]
    if "/" in body:
        return body
    for quote in ("USDT", "USDC", "FDUSD", "BUSD", "BTC", "ETH", "BNB"):
        if body.endswith(quote) and len(body) > len(quote):
            return f"{body[: -len(quote)]}/{quote}"
    return body


@router.get("/config", summary="UDF datafeed capabilities")
def config() -> dict[str, Any]:
    return {
        "supports_search": True,
        "supports_group_request": False,
        "supports_marks": False,
        "supports_timescale_marks": False,
        "supports_time": True,
        "supported_resolutions": SUPPORTED_RESOLUTIONS,
        "currency_codes": ["USDT"],
        "exchanges": [{"value": "BINANCE", "name": "Binance", "desc": "Binance"}],
        "symbols_types": [{"name": "crypto", "value": "crypto"}],
    }


@router.get("/time", summary="Server time in seconds")
def server_time() -> int:
    from app.core.time_utils import utcnow

    return int(utcnow().timestamp())


@router.get("/search", summary="Symbol search")
def search(
    db: DbSession,
    query: str = "",
    limit: int = Query(default=30, ge=1, le=200),
    type: str = "",
    exchange: str = "",
) -> list[dict[str, Any]]:
    needle = query.strip().upper()
    statement = select(Symbol).order_by(Symbol.symbol.asc())
    rows = db.execute(statement).scalars().all()
    matches = [
        row
        for row in rows
        if not needle or needle in row.symbol.replace("/", "") or needle in row.base_asset
    ][:limit]
    return [
        {
            "symbol": row.symbol.replace("/", ""),
            "full_name": f"BINANCE:{row.symbol.replace('/', '')}",
            "description": f"{row.base_asset} / {row.quote_asset}",
            "exchange": "BINANCE",
            "ticker": row.symbol,
            "type": "crypto",
        }
        for row in matches
    ]


@router.get("/symbols", summary="Symbol metadata")
def symbol_info(db: DbSession, symbol: str) -> dict[str, Any]:
    canonical = _to_canonical(symbol)
    record = db.execute(select(Symbol).where(Symbol.symbol == canonical)).scalar_one_or_none()
    price_precision = record.price_precision if record else 2
    return {
        "name": canonical.replace("/", ""),
        "ticker": canonical,
        "description": canonical,
        "type": "crypto",
        "session": "24x7",
        "timezone": "Etc/UTC",
        "exchange": "BINANCE",
        "listed_exchange": "BINANCE",
        "minmov": 1,
        "pricescale": int(10 ** min(price_precision, 8)),
        "has_intraday": True,
        "has_daily": True,
        "has_weekly_and_monthly": True,
        "supported_resolutions": SUPPORTED_RESOLUTIONS,
        "volume_precision": 4,
        "data_status": "streaming",
        "currency_code": canonical.split("/")[-1],
    }


@router.get("/history", summary="OHLCV history in UDF form")
async def history(
    db: DbSession,
    context: Context,
    symbol: str,
    resolution: str = "60",
    from_seconds: int = Query(default=0, alias="from"),
    to_seconds: int = Query(default=0, alias="to"),
    countback: int | None = None,
) -> dict[str, Any]:
    """Candles between ``from`` and ``to``, which UDF sends in whole seconds.

    The response uses UDF's status codes: ``ok`` with parallel arrays, ``no_data``
    plus a ``nextTime`` hint when the window is empty so the chart knows to jump
    back instead of paging through emptiness one screen at a time.
    """
    canonical = _to_canonical(symbol)
    timeframe = _to_timeframe(resolution)

    if context.market_data is None:
        return {"s": "error", "errmsg": "Market data service is not ready"}

    end_ms = int(to_seconds * 1000) if to_seconds else int(server_time() * 1000)
    if countback:
        span_ms = countback * timeframe_to_minutes(timeframe) * 60_000
        start_ms = end_ms - span_ms
    else:
        start_ms = int(from_seconds * 1000)

    if start_ms <= 0 or start_ms >= end_ms:
        return {"s": "no_data"}

    # A failed download is not fatal: whatever is already cached is still worth
    # drawing, and the chart must never go blank because the network blinked.
    with contextlib.suppress(Exception):
        await context.market_data.download_range(canonical, timeframe, start_ms, end_ms, db=db)

    frame = context.market_data.load_range(canonical, timeframe, start_ms, end_ms, db=db)
    if frame is None or frame.empty:
        return {"s": "no_data"}

    return {
        "s": "ok",
        "t": [int(value) // 1000 for value in frame["open_time"].tolist()],
        "o": [float(value) for value in frame["open"].tolist()],
        "h": [float(value) for value in frame["high"].tolist()],
        "l": [float(value) for value in frame["low"].tolist()],
        "c": [float(value) for value in frame["close"].tolist()],
        "v": [float(value) for value in frame["volume"].tolist()],
    }
