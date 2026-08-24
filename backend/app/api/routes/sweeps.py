"""Matrix backtests: run the whole strategy x market x timeframe grid."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import Field
from sqlalchemy import func, select

from app.api.deps import Context, DbSession
from app.backtesting import sweep as sweep_engine
from app.backtesting.sweep import SweepPlan
from app.core.constants import SUPPORTED_TIMEFRAMES, BacktestStatus
from app.models.market import Symbol
from app.models.sweep import BacktestSweep, SweepRun
from app.schemas.common import MessageResponse
from app.services import event_service, settings_service, universe_service
from app.strategies.registry import available_keys

router = APIRouter(prefix="/sweeps", tags=["sweeps"])

#: How the market list for a sweep is chosen.
SYMBOL_SOURCES = ("explicit", "enabled", "database", "top_volume", "all")


class SweepRequest(SweepPlan):
    """A sweep plan plus how to resolve the market list."""

    symbol_source: str = "top_volume"
    top_n: int = Field(default=30, ge=1, le=600)
    min_quote_volume: float = 0.0


async def _resolve_symbols(request: SweepRequest, db, context) -> list[str]:
    """Turn the requested market source into a concrete, ordered symbol list."""
    source = request.symbol_source
    if source not in SYMBOL_SOURCES:
        raise HTTPException(status_code=400, detail=f"Unknown symbol_source: {source}")

    if source == "explicit":
        if not request.symbols:
            raise HTTPException(status_code=400, detail="No markets were given")
        return [symbol.upper() for symbol in request.symbols]

    if source == "enabled":
        config = settings_service.get_trading_config(db)
        return [symbol.upper() for symbol in config.enabled_symbols]

    if source == "database":
        return universe_service.stored_symbols(db)

    try:
        snapshot = await universe_service.load_universe(context, with_context=False)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not reach Binance: {exc}") from exc

    rows = [row for row in snapshot["rows"] if row["quote_volume_24h"] >= request.min_quote_volume]
    if source == "top_volume":
        rows = rows[: request.top_n]
    return [row["symbol"] for row in rows]


@router.get("/options", summary="What a sweep can be built from")
def options(db: DbSession) -> dict[str, Any]:
    stored = db.execute(select(func.count(Symbol.id))).scalar_one()
    return {
        "strategies": available_keys(),
        "timeframes": list(SUPPORTED_TIMEFRAMES),
        "symbol_sources": list(SYMBOL_SOURCES),
        "symbols_in_database": int(stored),
        "enabled_symbols": settings_service.get_trading_config(db).enabled_symbols,
        "throughput_bars_per_second": sweep_engine.BAR_EVALS_PER_SECOND,
    }


@router.post("/estimate", summary="Cost of a sweep before running it")
async def estimate(request: SweepRequest, db: DbSession, context: Context) -> dict[str, Any]:
    """Runtime, downloads and storage the grid will need.

    Always call this first for a large grid. "Every strategy on every coin on
    every timeframe" is several days of CPU and hundreds of gigabytes of
    candles; the numbers here are what makes that visible before it starts.
    """
    symbols = await _resolve_symbols(request, db, context)
    if not symbols:
        raise HTTPException(status_code=400, detail="The market list resolved to nothing")
    result = sweep_engine.estimate_sweep(request, symbols).to_dict()
    result["symbols_preview"] = symbols[:20]
    result["symbol_count"] = len(symbols)
    return result


@router.post("", summary="Start a sweep")
async def create(request: SweepRequest, db: DbSession, context: Context) -> dict[str, Any]:
    if context.market_data is None:
        raise HTTPException(status_code=503, detail="Market data service is not ready")

    symbols = await _resolve_symbols(request, db, context)
    if not symbols:
        raise HTTPException(status_code=400, detail="The market list resolved to nothing")

    risk = settings_service.get_risk_config(db)
    estimate_result = sweep_engine.estimate_sweep(request, symbols)
    record = sweep_engine.create_sweep(db, request, symbols, risk)
    sweep_engine.launch(record.id, context.market_data, request)

    event_service.audit(
        db,
        action="start_backtest_sweep",
        entity="backtest_sweep",
        after={"uid": record.uid, "cells": record.total_runs},
    )
    return {
        "sweep": _sweep_to_dict(record),
        "estimate": estimate_result.to_dict(),
        "message": (
            f"Sweep started: {record.total_runs:,} backtests "
            f"({estimate_result.estimated_seconds / 60:.0f} minutes estimated). "
            "It runs in the background; this page can be closed."
        ),
    }


@router.get("", summary="Sweep history")
def list_sweeps(
    db: DbSession, limit: int = Query(default=30, ge=1, le=200)
) -> list[dict[str, Any]]:
    rows = (
        db.execute(select(BacktestSweep).order_by(BacktestSweep.id.desc()).limit(limit))
        .scalars()
        .all()
    )
    return [_sweep_to_dict(row) for row in rows]


@router.get("/{sweep_id}", summary="Sweep progress and summary")
def get_sweep(sweep_id: int, db: DbSession) -> dict[str, Any]:
    record = db.get(BacktestSweep, sweep_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Sweep not found")
    payload = _sweep_to_dict(record)
    payload["leaderboard"] = sweep_engine.sweep_leaderboard(db, sweep_id, limit=25)
    payload["summary"] = _summary(db, sweep_id)
    return payload


@router.get("/{sweep_id}/results", summary="Every cell of a sweep")
def results(
    sweep_id: int,
    db: DbSession,
    strategy: str | None = None,
    symbol: str | None = None,
    timeframe: str | None = None,
    status: str | None = None,
    min_trades: int = Query(default=0, ge=0),
    sort: str = "sharpe_ratio",
    descending: bool = True,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    if db.get(BacktestSweep, sweep_id) is None:
        raise HTTPException(status_code=404, detail="Sweep not found")

    query = select(SweepRun).where(SweepRun.sweep_id == sweep_id)
    count_query = select(func.count(SweepRun.id)).where(SweepRun.sweep_id == sweep_id)
    for clause in _filters(strategy, symbol, timeframe, status, min_trades):
        query = query.where(clause)
        count_query = count_query.where(clause)

    column = getattr(SweepRun, sort, None)
    if column is None:
        column = SweepRun.sharpe_ratio
    query = query.order_by(column.desc() if descending else column.asc())

    total = db.execute(count_query).scalar_one()
    rows = db.execute(query.offset(offset).limit(limit)).scalars().all()
    return {
        "rows": [sweep_engine.run_to_dict(row) for row in rows],
        "total": int(total),
        "offset": offset,
        "limit": limit,
    }


@router.get("/{sweep_id}/matrix", summary="Aggregated view of a sweep")
def matrix(
    sweep_id: int,
    db: DbSession,
    rows: str = "strategy_key",
    columns: str = "timeframe",
    metric: str = "expectancy_r",
    min_trades: int = Query(default=20, ge=0),
) -> dict[str, Any]:
    """Average a metric across a two dimensional pivot.

    The default pivot (strategy x timeframe, averaging expectancy in R) is the
    one that answers the question a sweep is usually run to answer: is there any
    combination where the edge survives the transaction costs?
    """
    if db.get(BacktestSweep, sweep_id) is None:
        raise HTTPException(status_code=404, detail="Sweep not found")

    valid_axes = {"strategy_key", "symbol", "timeframe"}
    if rows not in valid_axes or columns not in valid_axes or rows == columns:
        raise HTTPException(
            status_code=400, detail="Axes must be two different of " + str(valid_axes)
        )
    if not hasattr(SweepRun, metric):
        raise HTTPException(status_code=400, detail="Unknown metric: " + metric)

    row_col = getattr(SweepRun, rows)
    col_col = getattr(SweepRun, columns)
    metric_col = getattr(SweepRun, metric)

    records = db.execute(
        select(
            row_col,
            col_col,
            func.avg(metric_col),
            func.count(SweepRun.id),
            func.sum(SweepRun.total_trades),
        )
        .where(
            SweepRun.sweep_id == sweep_id,
            SweepRun.status == BacktestStatus.COMPLETED.value,
            SweepRun.total_trades >= min_trades,
        )
        .group_by(row_col, col_col)
    ).all()

    cells: dict[str, dict[str, Any]] = {}
    row_keys: set[str] = set()
    column_keys: set[str] = set()
    for row_value, col_value, average, cell_count, trades in records:
        row_keys.add(str(row_value))
        column_keys.add(str(col_value))
        cells.setdefault(str(row_value), {})[str(col_value)] = {
            "value": float(average) if average is not None else None,
            "cells": int(cell_count),
            "trades": int(trades or 0),
        }

    order = list(SUPPORTED_TIMEFRAMES)
    column_list = sorted(column_keys)
    if columns == "timeframe":
        column_list = sorted(
            column_keys, key=lambda item: order.index(item) if item in order else 99
        )
    return {
        "metric": metric,
        "rows": sorted(row_keys),
        "columns": column_list,
        "cells": cells,
        "min_trades": min_trades,
    }


@router.post("/{sweep_id}/cancel", response_model=MessageResponse, summary="Stop a sweep")
def cancel(sweep_id: int, db: DbSession) -> MessageResponse:
    if not sweep_engine.request_cancel(db, sweep_id):
        raise HTTPException(status_code=404, detail="Sweep not found")
    return MessageResponse(message="Cancellation requested. The current cell finishes first.")


@router.delete("/{sweep_id}", response_model=MessageResponse, summary="Delete a sweep")
def delete_sweep(sweep_id: int, db: DbSession) -> MessageResponse:
    record = db.get(BacktestSweep, sweep_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Sweep not found")
    if sweep_engine.is_running(sweep_id):
        raise HTTPException(status_code=409, detail="Cancel the sweep before deleting it")
    db.query(SweepRun).filter(SweepRun.sweep_id == sweep_id).delete()
    db.delete(record)
    db.commit()
    return MessageResponse(message="Sweep deleted.")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _filters(strategy, symbol, timeframe, status, min_trades) -> list[Any]:
    clauses: list[Any] = []
    if strategy:
        clauses.append(SweepRun.strategy_key == strategy)
    if symbol:
        clauses.append(SweepRun.symbol == symbol.upper())
    if timeframe:
        clauses.append(SweepRun.timeframe == timeframe)
    if status:
        clauses.append(SweepRun.status == status.upper())
    if min_trades:
        clauses.append(SweepRun.total_trades >= min_trades)
    return clauses


def _summary(db, sweep_id: int) -> dict[str, Any]:
    """Headline numbers: how many cells actually beat their costs.

    ``min_trades`` matters here. A cell with three trades can show a spectacular
    return and mean nothing, so the percentages below are computed only over
    cells that traded enough to be worth reading.
    """
    completed = BacktestStatus.COMPLETED.value
    base = (SweepRun.sweep_id == sweep_id, SweepRun.status == completed)

    def count(*extra) -> int:
        return int(db.execute(select(func.count(SweepRun.id)).where(*base, *extra)).scalar_one())

    enough = SweepRun.total_trades >= 20
    total = count()
    traded = count(enough)
    profitable = count(enough, SweepRun.net_pnl > 0)
    beat_hold = count(enough, SweepRun.return_pct > SweepRun.buy_hold_return_pct)
    positive_r = count(enough, SweepRun.expectancy_r > 0)
    average_r = db.execute(
        select(func.avg(SweepRun.expectancy_r)).where(*base, enough)
    ).scalar_one()

    return {
        "completed_cells": total,
        "cells_with_enough_trades": traded,
        "profitable_cells": profitable,
        "profitable_pct": round(profitable / traded * 100.0, 1) if traded else 0.0,
        "beat_buy_and_hold": beat_hold,
        "beat_buy_and_hold_pct": round(beat_hold / traded * 100.0, 1) if traded else 0.0,
        "positive_expectancy_r_cells": positive_r,
        "average_expectancy_r": round(float(average_r), 4) if average_r is not None else 0.0,
        "min_trades_for_inclusion": 20,
    }


def _sweep_to_dict(record: BacktestSweep) -> dict[str, Any]:
    done = record.completed_runs + record.failed_runs + record.skipped_runs
    return {
        "id": record.id,
        "uid": record.uid,
        "name": record.name,
        "status": record.status,
        "strategy_keys": record.strategy_keys,
        "symbols": record.symbols,
        "timeframes": record.timeframes,
        "symbol_count": len(record.symbols or []),
        "start_date": record.start_date,
        "end_date": record.end_date,
        "starting_capital": record.starting_capital,
        "leverage": record.leverage,
        "cost_model": record.cost_model,
        "total_runs": record.total_runs,
        "completed_runs": record.completed_runs,
        "failed_runs": record.failed_runs,
        "skipped_runs": record.skipped_runs,
        "finished_runs": done,
        "progress_pct": round(done / record.total_runs * 100.0, 1) if record.total_runs else 0.0,
        "current_task": record.current_task,
        "started_at": record.started_at,
        "completed_at": record.completed_at,
        "duration_seconds": record.duration_seconds,
        "error_message": record.error_message,
        "cancel_requested": bool(record.cancel_requested),
        "is_running": sweep_engine.is_running(record.id),
    }
