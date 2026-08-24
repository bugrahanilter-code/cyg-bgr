"""Matrix backtesting: every strategy against every market on every timeframe.

The honest arithmetic
---------------------
"Backtest everything" is a bigger request than it looks. The work is not
proportional to the number of cells in the grid, it is proportional to the
number of *candles* in it, and low timeframes dominate everything else. One year
of history per market:

======  =========  ==================================
 TF      candles    x 14 strategies x 500 markets
======  =========  ==================================
 1d          365    2.6M bar-evaluations
 4h        2,190    15M
 1h        8,760    61M
 15m      35,040    245M
 5m      105,120    736M
 1m      525,600    3.7 billion
======  =========  ==================================

At the measured ~10k bar-evaluations per second per core, the 1m row alone is
over four days of pure CPU, and storing its candles is hundreds of gigabytes.
That is why :func:`estimate_sweep` exists and why the dashboard shows the
estimate before the run starts: the user picks the depth, having seen the price.

The engineering response to the same arithmetic is to make the expensive part
happen once. Candles are loaded per ``(symbol, timeframe)`` and reused for all
14 strategies, so a grid of 14 strategies costs one database read, not 14.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.costs import CostModel
from app.backtesting.engine import BacktestEngine, BacktestRequest
from app.core.constants import (
    SUPPORTED_TIMEFRAMES,
    BacktestStatus,
    DatasetSplit,
    EventSeverity,
    timeframe_to_minutes,
    timeframe_to_ms,
)
from app.core.exceptions import InsufficientDataError
from app.core.logging import get_logger
from app.core.time_utils import to_ms, utcnow
from app.exchange.filters import default_filters_for
from app.models.sweep import BacktestSweep, SweepRun
from app.risk.config import RiskConfig
from app.strategies.registry import available_keys, create_strategy

logger = get_logger(__name__)

#: Measured on this machine: one strategy evaluating one candle, single core.
BAR_EVALS_PER_SECOND = 9_000.0

#: Binance returns at most this many candles per klines request.
CANDLES_PER_REQUEST = 1_500

#: Multiplier applied to a strategy's declared warm-up, matching the single
#: backtest path in app/backtesting/service.py.
WARMUP_MULTIPLIER = 1.5

#: Not a BacktestStatus value: a cell that never ran because the history was
#: too short is neither completed nor failed.
SKIPPED_STATUS = "SKIPPED"


class SweepPlan(BaseModel):
    """What to run. Empty lists mean 'everything available'."""

    name: str = ""
    strategy_keys: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    timeframes: list[str] = Field(default_factory=list)
    start: datetime
    end: datetime
    starting_capital: float = Field(default=10_000.0, gt=0.0)
    leverage: int = Field(default=2, ge=1, le=125)
    taker_fee_pct: float = 0.04
    slippage_pct: float = 0.02
    funding_rate_pct_per_8h: float = 0.01
    apply_funding: bool = True
    respect_daily_limits: bool = True
    download_missing: bool = True
    #: Cells with fewer candles than this are skipped instead of failing: a coin
    #: listed three months ago has no two year history and that is not an error.
    min_candles: int = 600

    def resolved_strategies(self) -> list[str]:
        return self.strategy_keys or available_keys()

    def resolved_timeframes(self) -> list[str]:
        chosen = self.timeframes or list(SUPPORTED_TIMEFRAMES)
        return [tf for tf in SUPPORTED_TIMEFRAMES if tf in set(chosen)]

    def cost_model(self) -> CostModel:
        model = CostModel()
        model.taker_fee_pct = self.taker_fee_pct
        model.slippage_pct = self.slippage_pct
        model.funding_rate_pct_per_8h = self.funding_rate_pct_per_8h
        model.apply_funding = self.apply_funding
        return model


@dataclass(slots=True)
class SweepEstimate:
    """What the requested grid will actually cost, before committing to it."""

    cells: int
    strategies: int
    symbols: int
    timeframes: int
    total_candles: int
    bar_evaluations: int
    estimated_seconds: float
    estimated_download_requests: int
    estimated_storage_mb: float
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cells": self.cells,
            "strategies": self.strategies,
            "symbols": self.symbols,
            "timeframes": self.timeframes,
            "total_candles": self.total_candles,
            "bar_evaluations": self.bar_evaluations,
            "estimated_seconds": round(self.estimated_seconds, 1),
            "estimated_minutes": round(self.estimated_seconds / 60.0, 1),
            "estimated_hours": round(self.estimated_seconds / 3600.0, 2),
            "estimated_download_requests": self.estimated_download_requests,
            "estimated_storage_mb": round(self.estimated_storage_mb, 1),
            "warnings": self.warnings,
        }


def estimate_sweep(plan: SweepPlan, symbols: list[str]) -> SweepEstimate:
    """Predict runtime, download volume and storage for a plan."""
    strategies = plan.resolved_strategies()
    timeframes = plan.resolved_timeframes()
    span_minutes = max((plan.end - plan.start).total_seconds() / 60.0, 0.0)

    total_candles = 0
    for timeframe in timeframes:
        per_market = span_minutes / timeframe_to_minutes(timeframe)
        total_candles += int(per_market * len(symbols))

    bar_evaluations = total_candles * len(strategies)
    seconds = bar_evaluations / BAR_EVALS_PER_SECOND
    requests = -(-total_candles // CANDLES_PER_REQUEST) if total_candles else 0

    warnings: list[str] = []
    if seconds > 4 * 3600:
        warnings.append(
            f"This grid needs about {seconds / 3600:.1f} hours of CPU time. "
            "Consider fewer markets or dropping the 1m/3m/5m timeframes."
        )
    fast = [tf for tf in timeframes if timeframe_to_minutes(tf) <= 5]
    if fast and len(symbols) > 40:
        warnings.append(
            f"{', '.join(fast)} on {len(symbols)} markets dominates the runtime and the "
            "download. These timeframes were also where transaction costs beat the edge "
            "in every study so far."
        )
    if requests > 20_000:
        warnings.append(
            f"About {requests:,} candle downloads are needed. Binance rate limits apply, "
            "so the download alone can take hours on the first run."
        )

    # Runtime and storage are not the only way a grid can be a bad idea. A grid
    # that runs in ten minutes because the window is three weeks long produces
    # numbers that look like results and are not: too few trades per cell, and
    # a single market regime behind all of them.
    span_days = span_minutes / 1440.0
    if span_days < 180:
        warnings.append(
            f"The test window is only {span_days:.0f} days. Expect very few trades per "
            "cell and a single market regime behind every number. Twelve months or more "
            "is the minimum for a result worth reading."
        )
    thin = [
        timeframe
        for timeframe in timeframes
        if span_minutes / timeframe_to_minutes(timeframe) < 400
    ]
    if thin:
        per_market = {
            timeframe: int(span_minutes / timeframe_to_minutes(timeframe)) for timeframe in thin
        }
        detail = ", ".join(f"{tf} ({count} candles)" for tf, count in per_market.items())
        warnings.append(
            f"Too little history per market on {detail}. These cells will either be "
            "skipped or trade a handful of times, which cannot support a conclusion."
        )

    return SweepEstimate(
        cells=len(strategies) * len(symbols) * len(timeframes),
        strategies=len(strategies),
        symbols=len(symbols),
        timeframes=len(timeframes),
        total_candles=total_candles,
        bar_evaluations=bar_evaluations,
        estimated_seconds=seconds,
        estimated_download_requests=requests,
        # Measured against the existing SQLite file: ~0.7 kB per stored candle
        # once the covering index is included.
        estimated_storage_mb=total_candles * 0.0007,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Job management
# ---------------------------------------------------------------------------
_RUNNING: dict[int, asyncio.Task] = {}


def create_sweep(
    db: Session, plan: SweepPlan, symbols: list[str], risk: RiskConfig
) -> BacktestSweep:
    """Persist a sweep in PENDING state together with every cell it will run."""
    strategies = plan.resolved_strategies()
    timeframes = plan.resolved_timeframes()

    record = BacktestSweep(
        uid=uuid.uuid4().hex[:24],
        name=plan.name or f"{len(strategies)}x{len(symbols)}x{len(timeframes)} sweep",
        strategy_keys=strategies,
        symbols=symbols,
        timeframes=timeframes,
        start_date=plan.start,
        end_date=plan.end,
        starting_capital=float(plan.starting_capital),
        leverage=int(plan.leverage),
        cost_model=plan.cost_model().model_dump(),
        risk_config=risk.model_dump(),
        download_missing=bool(plan.download_missing),
        status=BacktestStatus.PENDING.value,
        total_runs=len(strategies) * len(symbols) * len(timeframes),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def request_cancel(db: Session, sweep_id: int) -> bool:
    """Ask a running sweep to stop after the cell it is currently on."""
    record = db.get(BacktestSweep, sweep_id)
    if record is None:
        return False
    record.cancel_requested = True
    db.commit()
    return True


def is_running(sweep_id: int) -> bool:
    task = _RUNNING.get(sweep_id)
    return task is not None and not task.done()


def launch(sweep_id: int, market_data: Any, plan: SweepPlan) -> None:
    """Start the sweep in the background so the HTTP request can return."""
    if is_running(sweep_id):
        return
    task = asyncio.create_task(_run_sweep(sweep_id, market_data, plan))
    _RUNNING[sweep_id] = task
    task.add_done_callback(lambda _: _RUNNING.pop(sweep_id, None))


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------
async def _run_sweep(sweep_id: int, market_data: Any, plan: SweepPlan) -> None:
    """Walk the grid one (symbol, timeframe) group at a time."""
    from app.database.session import SessionLocal
    from app.services.event_service import log_event

    db = SessionLocal()
    engine = BacktestEngine()
    started = utcnow()
    try:
        record = db.get(BacktestSweep, sweep_id)
        if record is None:
            return
        record.status = BacktestStatus.RUNNING.value
        record.started_at = started
        db.commit()

        strategies = list(record.strategy_keys)
        symbols = list(record.symbols)
        timeframes = list(record.timeframes)
        risk = RiskConfig(**(record.risk_config or {}))
        warmup = warmup_bars_for(strategies)
        cost_model = CostModel(**(record.cost_model or {}))

        for symbol in symbols:
            for timeframe in timeframes:
                db.refresh(record)
                if record.cancel_requested:
                    record.status = BacktestStatus.FAILED.value
                    record.error_message = "Cancelled by the user."
                    break

                record.current_task = f"{symbol} {timeframe}"
                db.commit()

                frame = await _prepare_frame(
                    db, market_data, record, symbol, timeframe, plan.download_missing, warmup
                )
                if frame is None or len(frame) < plan.min_candles:
                    _skip_group(
                        db,
                        record,
                        strategies,
                        symbol,
                        timeframe,
                        reason=(
                            f"only {0 if frame is None else len(frame)} candles available "
                            f"(needs {plan.min_candles})"
                        ),
                    )
                    continue

                buy_hold = _buy_and_hold_pct(frame)
                filters = default_filters_for(symbol)

                for strategy_key in strategies:
                    db.refresh(record)
                    if record.cancel_requested:
                        break
                    await _run_cell(
                        db,
                        engine,
                        record,
                        strategy_key,
                        symbol,
                        timeframe,
                        frame,
                        filters,
                        risk,
                        cost_model,
                        buy_hold,
                        plan,
                    )
            if record.cancel_requested:
                break

        if not record.cancel_requested:
            record.status = BacktestStatus.COMPLETED.value
        record.current_task = ""
        record.completed_at = utcnow()
        record.duration_seconds = (record.completed_at - started).total_seconds()
        db.commit()

        log_event(
            db,
            message=f"Sweep finished: {record.name}",
            category="backtest",
            details={
                "completed": record.completed_runs,
                "failed": record.failed_runs,
                "skipped": record.skipped_runs,
                "seconds": round(record.duration_seconds, 1),
            },
        )
    except Exception as exc:
        logger.exception("Sweep crashed", extra={"sweep_id": sweep_id})
        record = db.get(BacktestSweep, sweep_id)
        if record is not None:
            record.status = BacktestStatus.FAILED.value
            record.error_message = str(exc)[:1000]
            record.completed_at = utcnow()
            db.commit()
        log_event(
            db,
            message=f"Sweep failed: {exc}",
            category="backtest",
            severity=EventSeverity.ERROR,
        )
    finally:
        db.close()


def warmup_bars_for(strategy_keys: list[str]) -> int:
    """Warm-up long enough for the hungriest strategy in the grid.

    Every strategy in a group shares one candle frame, so the frame has to start
    early enough for whichever of them needs the longest history. Using a fixed
    number instead would quietly starve the slowest indicators - or fail them
    outright, which is how this was found.
    """
    longest = 0
    for key in strategy_keys:
        try:
            longest = max(longest, create_strategy(key).warmup_bars)
        except Exception:  # an unknown key fails later, with a better message
            continue
    return int(max(longest, 220) * WARMUP_MULTIPLIER)


async def _prepare_frame(
    db: Session,
    market_data: Any,
    record: BacktestSweep,
    symbol: str,
    timeframe: str,
    download_missing: bool,
    warmup_bars: int,
) -> pd.DataFrame | None:
    """Load candles for one group, downloading them first when allowed.

    Loaded once per ``(symbol, timeframe)`` and reused by every strategy in the
    grid, which is where most of the saving in a sweep comes from.
    """
    timeframe_ms = timeframe_to_ms(timeframe)
    start_ms = to_ms(record.start_date) - warmup_bars * timeframe_ms
    end_ms = to_ms(record.end_date)

    if download_missing:
        try:
            await market_data.download_range(symbol, timeframe, start_ms, end_ms, db=db)
        except Exception as exc:
            logger.warning(
                "Sweep download failed, using the cache",
                extra={"symbol": symbol, "timeframe": timeframe, "error": str(exc)[:160]},
            )

    try:
        frame = market_data.load_range(symbol, timeframe, start_ms, end_ms, db=db)
    except Exception as exc:
        logger.warning(
            "Sweep could not load candles",
            extra={"symbol": symbol, "timeframe": timeframe, "error": str(exc)[:160]},
        )
        return None
    return None if frame is None or frame.empty else frame


def _buy_and_hold_pct(frame: pd.DataFrame) -> float:
    """Return of holding the coin across the frame, as a percentage.

    Every strategy result is stored next to this number. A strategy that made
    +40% while the coin made +180% did not find an edge, it found a slow way to
    be long, and the table should make that obvious at a glance.
    """
    try:
        first = float(frame["close"].iloc[0])
        last = float(frame["close"].iloc[-1])
        return (last / first - 1.0) * 100.0 if first > 0 else 0.0
    except Exception:
        return 0.0


def _expectancy_r(trades: list[dict[str, Any]]) -> float:
    """Average R multiple per trade, the cost-comparable measure of edge."""
    values = [float(trade["r_multiple"]) for trade in trades if trade.get("r_multiple") is not None]
    return sum(values) / len(values) if values else 0.0


async def _run_cell(
    db: Session,
    engine: BacktestEngine,
    record: BacktestSweep,
    strategy_key: str,
    symbol: str,
    timeframe: str,
    frame: pd.DataFrame,
    filters: Any,
    risk: RiskConfig,
    cost_model: CostModel,
    buy_hold: float,
    plan: SweepPlan,
) -> None:
    """Run one grid cell and store its flat metric row."""
    started = utcnow()
    run = SweepRun(
        sweep_id=record.id,
        strategy_key=strategy_key,
        symbol=symbol,
        timeframe=timeframe,
        buy_hold_return_pct=buy_hold,
        status=BacktestStatus.RUNNING.value,
    )
    db.add(run)

    request = BacktestRequest(
        strategy_key=strategy_key,
        symbol=symbol,
        timeframe=timeframe,
        start=record.start_date,
        end=record.end_date,
        starting_capital=float(record.starting_capital),
        leverage=int(record.leverage),
        risk=risk,
        cost_model=cost_model,
        split=DatasetSplit.FULL,
        respect_daily_limits=plan.respect_daily_limits,
    )

    try:
        strategy = create_strategy(strategy_key)
        output = await asyncio.to_thread(engine.run, frame, request, filters, strategy)
        metrics = output.metrics or {}

        run.status = BacktestStatus.COMPLETED.value
        run.total_trades = int(metrics.get("total_trades") or 0)
        run.net_pnl = float(metrics.get("net_pnl") or 0.0)
        run.return_pct = float(metrics.get("total_return_pct") or 0.0)
        run.win_rate_pct = float(metrics.get("win_rate_pct") or 0.0)
        run.profit_factor = float(metrics.get("profit_factor") or 0.0)
        run.sharpe_ratio = float(metrics.get("sharpe_ratio") or 0.0)
        run.sortino_ratio = float(metrics.get("sortino_ratio") or 0.0)
        run.max_drawdown_pct = float(metrics.get("max_drawdown_pct") or 0.0)
        run.expectancy = float(metrics.get("expectancy") or 0.0)
        run.expectancy_r = _expectancy_r(output.trades)
        run.total_fees = float(metrics.get("total_fees") or 0.0)
        run.metrics = metrics
        run.candles_used = int(output.candles_used or 0)
        record.completed_runs += 1
    except InsufficientDataError as exc:
        # A coin listed six months ago genuinely cannot be tested over two years,
        # and a strategy with a 550 bar warm-up genuinely cannot run on one year
        # of daily candles. That is missing history, not a broken strategy, so it
        # is recorded as SKIPPED and kept out of the failure count.
        run.status = SKIPPED_STATUS
        run.error_message = str(exc)[:1000]
        record.skipped_runs += 1
    except Exception as exc:
        run.status = BacktestStatus.FAILED.value
        run.error_message = f"{type(exc).__name__}: {exc}"[:1000]
        record.failed_runs += 1

    run.duration_seconds = (utcnow() - started).total_seconds()
    db.commit()


def _skip_group(
    db: Session,
    record: BacktestSweep,
    strategies: list[str],
    symbol: str,
    timeframe: str,
    reason: str,
) -> None:
    """Mark every strategy of a group as skipped when the data is not there.

    A coin listed last month genuinely has no two year history. Recording that
    as SKIPPED rather than FAILED keeps the difference between "no data" and
    "the strategy broke" visible in the results table.
    """
    for strategy_key in strategies:
        db.add(
            SweepRun(
                sweep_id=record.id,
                strategy_key=strategy_key,
                symbol=symbol,
                timeframe=timeframe,
                status=SKIPPED_STATUS,
                error_message=reason,
            )
        )
        record.skipped_runs += 1
    db.commit()


# ---------------------------------------------------------------------------
# Reading results back
# ---------------------------------------------------------------------------
def sweep_leaderboard(db: Session, sweep_id: int, limit: int = 50) -> list[dict[str, Any]]:
    """Best cells of a sweep, ranked by risk adjusted return.

    Ranking by raw return would put a single lucky low-liquidity coin at the
    top. Requiring a minimum number of trades and sorting by Sharpe keeps the
    table pointed at results that could plausibly repeat.
    """
    query = (
        select(SweepRun)
        .where(
            SweepRun.sweep_id == sweep_id,
            SweepRun.status == BacktestStatus.COMPLETED.value,
            SweepRun.total_trades >= 30,
        )
        .order_by(SweepRun.sharpe_ratio.desc())
        .limit(limit)
    )
    return [run_to_dict(row) for row in db.execute(query).scalars().all()]


def run_to_dict(row: SweepRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "strategy_key": row.strategy_key,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "status": row.status,
        "total_trades": row.total_trades,
        "net_pnl": row.net_pnl,
        "return_pct": row.return_pct,
        "buy_hold_return_pct": row.buy_hold_return_pct,
        "excess_return_pct": row.return_pct - row.buy_hold_return_pct,
        "win_rate_pct": row.win_rate_pct,
        "profit_factor": row.profit_factor,
        "sharpe_ratio": row.sharpe_ratio,
        "sortino_ratio": row.sortino_ratio,
        "max_drawdown_pct": row.max_drawdown_pct,
        "expectancy": row.expectancy,
        "expectancy_r": row.expectancy_r,
        "total_fees": row.total_fees,
        "candles_used": row.candles_used,
        "duration_seconds": row.duration_seconds,
        "error_message": row.error_message,
    }
