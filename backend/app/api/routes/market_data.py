"""Market data endpoints used by the charts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import Context, DbSession
from app.core.constants import SUPPORTED_TIMEFRAMES
from app.core.time_utils import to_ms
from app.schemas.requests import CandleDownloadRequest
from app.schemas.responses import CandleOut

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/timeframes", summary="Supported timeframes")
def timeframes() -> list[str]:
    return list(SUPPORTED_TIMEFRAMES)


@router.get("/candles", response_model=list[CandleOut], summary="Cached candles")
async def candles(
    db: DbSession,
    context: Context,
    symbol: str,
    timeframe: str = "15m",
    limit: int = Query(default=300, ge=10, le=2000),
    refresh: bool = False,
) -> list[CandleOut]:
    if context.market_data is None:
        raise HTTPException(status_code=503, detail="Market data service is not ready")
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"Unsupported timeframe: {timeframe}")

    if refresh:
        frame = await context.market_data.get_candles_fresh(
            symbol.upper(), timeframe, limit=limit, db=db
        )
    else:
        frame = context.market_data.get_candles(symbol.upper(), timeframe, limit=limit, db=db)
    return [
        CandleOut(
            open_time=int(row.open_time),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for row in frame.itertuples(index=False)
    ]


@router.get("/ticker", summary="Latest prices")
def ticker(context: Context, symbol: str | None = None) -> dict[str, Any]:
    if context.market_data is None:
        raise HTTPException(status_code=503, detail="Market data service is not ready")
    service = context.market_data
    symbols = [symbol.upper()] if symbol else service.symbols
    return {
        item: {
            "price": service.last_price(item),
            "age_seconds": service.data_age_seconds(item),
            "stale": service.is_stale(item),
            "spread_pct": service.get_ticker(item).spread_pct if service.get_ticker(item) else None,
        }
        for item in symbols
    }


@router.get("/regime", summary="Current market regime per symbol")
def regime(context: Context) -> dict[str, Any]:
    if context.engine is None:
        return {}
    result: dict[str, Any] = {}
    for symbol in context.engine.market_data.symbols:
        current = context.engine.latest_regime(symbol)
        result[symbol] = current.to_dict() if current else None
    return result


@router.post("/download", summary="Download historical candles")
async def download(payload: CandleDownloadRequest, db: DbSession, context: Context) -> dict[str, Any]:
    if context.market_data is None:
        raise HTTPException(status_code=503, detail="Market data service is not ready")
    stored = await context.market_data.download_range(
        payload.symbol.upper(),
        payload.timeframe,
        to_ms(payload.start),
        to_ms(payload.end),
        db=db,
    )
    return {"stored": stored, "symbol": payload.symbol.upper(), "timeframe": payload.timeframe}
