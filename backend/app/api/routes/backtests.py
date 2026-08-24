"""Backtest lab endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import Context, DbSession
from app.backtesting.engine import BacktestRequest
from app.backtesting.service import execute_backtest
from app.backtesting.walk_forward import WalkForwardRequest
from app.core.constants import DatasetSplit
from app.core.exceptions import TradingPlatformError
from app.models.backtest import Backtest, BacktestResult
from app.models.trading import Trade
from app.schemas.common import MessageResponse
from app.schemas.requests import BacktestRunRequest
from app.schemas.responses import BacktestDetailOut, BacktestOut, TradeOut
from app.services import settings_service

router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.post("/run", response_model=BacktestDetailOut, summary="Run a backtest")
async def run_backtest(
    payload: BacktestRunRequest, db: DbSession, context: Context
) -> BacktestDetailOut:
    if context.market_data is None:
        raise HTTPException(status_code=503, detail="Market data service is not ready")

    risk = payload.risk or settings_service.get_risk_config(db)
    request = BacktestRequest(
        strategy_key=payload.strategy_key,
        symbol=payload.symbol.upper(),
        timeframe=payload.timeframe,
        start=payload.start,
        end=payload.end,
        starting_capital=payload.starting_capital,
        leverage=payload.leverage,
        params=payload.params,
        risk=risk,
        split=DatasetSplit.FULL,
        name=payload.name,
        respect_daily_limits=payload.respect_daily_limits,
    )
    request.cost_model.taker_fee_pct = payload.taker_fee_pct
    request.cost_model.slippage_pct = payload.slippage_pct
    request.cost_model.funding_rate_pct_per_8h = payload.funding_rate_pct_per_8h
    request.cost_model.apply_funding = payload.apply_funding

    walk_forward = (
        WalkForwardRequest(folds=payload.walk_forward_folds, param_grid=payload.param_grid)
        if payload.walk_forward
        else None
    )

    try:
        record = await execute_backtest(db, context.market_data, request, walk_forward=walk_forward)
    except TradingPlatformError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _detail(db, record)


@router.get("", response_model=list[BacktestOut], summary="Backtest history")
def list_backtests(
    db: DbSession,
    strategy: str | None = None,
    symbol: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[BacktestOut]:
    query = select(Backtest)
    if strategy:
        query = query.where(Backtest.strategy_key == strategy)
    if symbol:
        query = query.where(Backtest.symbol == symbol.upper())
    query = query.order_by(Backtest.id.desc()).limit(limit)
    return [BacktestOut.model_validate(row) for row in db.execute(query).scalars().all()]


@router.get("/{backtest_id}", response_model=BacktestDetailOut, summary="Backtest detail")
def get_backtest(backtest_id: int, db: DbSession) -> BacktestDetailOut:
    record = db.get(Backtest, backtest_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Backtest not found")
    return _detail(db, record)


@router.delete("/{backtest_id}", response_model=MessageResponse, summary="Delete a backtest")
def delete_backtest(backtest_id: int, db: DbSession) -> MessageResponse:
    record = db.get(Backtest, backtest_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Backtest not found")
    db.query(Trade).filter(Trade.backtest_id == backtest_id).delete()
    db.query(BacktestResult).filter(BacktestResult.backtest_id == backtest_id).delete()
    db.delete(record)
    db.commit()
    return MessageResponse(message="Backtest deleted.")


def _detail(db, record: Backtest) -> BacktestDetailOut:
    result = db.execute(
        select(BacktestResult).where(BacktestResult.backtest_id == record.id)
    ).scalar_one_or_none()
    trades = (
        db.execute(
            select(Trade).where(Trade.backtest_id == record.id).order_by(Trade.opened_at.asc())
        )
        .scalars()
        .all()
    )
    payload: dict[str, Any] = {
        "backtest": BacktestOut.model_validate(record),
        "trades": [TradeOut.model_validate(trade) for trade in trades],
    }
    if result is not None:
        payload.update(
            metrics=result.metrics or {},
            equity_curve=result.equity_curve or [],
            drawdown_curve=result.drawdown_curve or [],
            monthly_returns=result.monthly_returns or [],
            trade_distribution=result.trade_distribution or {},
            walk_forward=result.walk_forward,
        )
    return BacktestDetailOut(**payload)
