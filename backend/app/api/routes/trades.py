"""Trade journal and order history endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import DbSession
from app.models.trading import Order, Signal, Trade
from app.schemas.responses import OrderOut, SignalOut, TradeOut

router = APIRouter(tags=["trades"])


@router.get("/trades", response_model=list[TradeOut], summary="Filterable trade journal")
def list_trades(
    db: DbSession,
    mode: str | None = None,
    symbol: str | None = None,
    strategy: str | None = None,
    side: str | None = None,
    result: str | None = Query(default=None, description="win or loss"),
    backtest_id: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> list[TradeOut]:
    query = select(Trade)
    if mode:
        query = query.where(Trade.mode == mode)
    if symbol:
        query = query.where(Trade.symbol == symbol.upper())
    if strategy:
        query = query.where(Trade.strategy_key == strategy)
    if side:
        query = query.where(Trade.side == side.upper())
    if result == "win":
        query = query.where(Trade.is_win.is_(True))
    elif result == "loss":
        query = query.where(Trade.is_win.is_(False))
    if backtest_id is not None:
        query = query.where(Trade.backtest_id == backtest_id)
    if start is not None:
        query = query.where(Trade.closed_at >= start)
    if end is not None:
        query = query.where(Trade.closed_at <= end)
    query = query.order_by(Trade.closed_at.desc()).offset(offset).limit(limit)
    return [TradeOut.model_validate(row) for row in db.execute(query).scalars().all()]


@router.get("/orders", response_model=list[OrderOut], summary="Order history")
def list_orders(
    db: DbSession,
    mode: str | None = None,
    symbol: str | None = None,
    status: str | None = None,
    limit: int = Query(default=200, ge=1, le=2000),
) -> list[OrderOut]:
    query = select(Order)
    if mode:
        query = query.where(Order.mode == mode)
    if symbol:
        query = query.where(Order.symbol == symbol.upper())
    if status:
        query = query.where(Order.status == status.upper())
    query = query.order_by(Order.id.desc()).limit(limit)
    return [OrderOut.model_validate(row) for row in db.execute(query).scalars().all()]


@router.get("/signals", response_model=list[SignalOut], summary="Generated signals")
def list_signals(
    db: DbSession,
    mode: str | None = None,
    symbol: str | None = None,
    strategy: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[SignalOut]:
    query = select(Signal)
    if mode:
        query = query.where(Signal.mode == mode)
    if symbol:
        query = query.where(Signal.symbol == symbol.upper())
    if strategy:
        query = query.where(Signal.strategy_key == strategy)
    if status:
        query = query.where(Signal.status == status)
    query = query.order_by(Signal.id.desc()).limit(limit)
    return [SignalOut.model_validate(row) for row in db.execute(query).scalars().all()]
