"""Backtest orchestration: data loading, execution and persistence."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.backtesting.engine import BacktestEngine, BacktestOutput, BacktestRequest
from app.backtesting.walk_forward import WalkForwardRequest, run_walk_forward
from app.core.constants import BacktestStatus, EventSeverity, TradingMode, timeframe_to_ms
from app.core.exceptions import InsufficientDataError
from app.core.logging import get_logger
from app.core.time_utils import from_ms, to_ms, utcnow
from app.exchange.filters import default_filters_for
from app.market_data.service import MarketDataService
from app.models.backtest import Backtest, BacktestResult
from app.models.trading import Trade
from app.services.event_service import log_event
from app.strategies.registry import create_strategy

logger = get_logger(__name__)

WARMUP_MULTIPLIER = 1.5


async def execute_backtest(
    db: Session,
    market_data: MarketDataService,
    request: BacktestRequest,
    *,
    walk_forward: WalkForwardRequest | None = None,
    persist_trades: bool = True,
) -> Backtest:
    """Run a backtest end to end and store everything in the database."""
    strategy = create_strategy(request.strategy_key, request.params)
    record = Backtest(
        uid=uuid.uuid4().hex[:24],
        name=request.name or f"{request.strategy_key} {request.symbol} {request.timeframe}",
        strategy_key=request.strategy_key,
        symbol=request.symbol,
        timeframe=request.timeframe,
        start_date=request.start,
        end_date=request.end,
        starting_capital=float(request.starting_capital),
        params=strategy.params_dict(),
        cost_model=request.cost_model.model_dump(),
        risk_config=request.risk.model_dump(),
        split=request.split.value,
        status=BacktestStatus.RUNNING.value,
        started_at=utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    started = utcnow()
    try:
        frame = await _load_candles(db, market_data, request, strategy.warmup_bars)
        engine = BacktestEngine()
        output: BacktestOutput = await asyncio.to_thread(
            engine.run, frame, request, default_filters_for(request.symbol), strategy
        )

        walk_forward_result: dict[str, Any] | None = None
        if walk_forward is not None:
            walk_forward_result = await asyncio.to_thread(
                run_walk_forward, frame, request, walk_forward, engine
            )

        result = BacktestResult(
            backtest_id=record.id,
            metrics=output.metrics,
            equity_curve=output.equity_curve,
            drawdown_curve=output.drawdown_curve,
            monthly_returns=output.monthly_returns,
            trade_distribution=output.trade_distribution,
            walk_forward=walk_forward_result,
        )
        db.add(result)

        if persist_trades:
            _persist_trades(db, record, output)

        record.status = BacktestStatus.COMPLETED.value
        record.completed_at = utcnow()
        record.duration_seconds = (record.completed_at - started).total_seconds()
        record.candles_used = output.candles_used
        db.commit()
        db.refresh(record)

        log_event(
            db,
            message=f"Backtest completed: {record.name}",
            category="backtest",
            details={
                "net_pnl": output.metrics.get("net_pnl"),
                "total_trades": output.metrics.get("total_trades"),
                "warnings": output.warnings,
            },
            mode=TradingMode.BACKTEST.value,
            symbol=request.symbol,
        )
        return record
    except Exception as exc:
        record.status = BacktestStatus.FAILED.value
        record.error_message = str(exc)[:1000]
        record.completed_at = utcnow()
        db.commit()
        log_event(
            db,
            message=f"Backtest failed: {exc}",
            category="backtest",
            severity=EventSeverity.ERROR,
            mode=TradingMode.BACKTEST.value,
            symbol=request.symbol,
        )
        raise


async def _load_candles(
    db: Session, market_data: MarketDataService, request: BacktestRequest, warmup_bars: int
):
    """Fetch (and cache) the candles needed, including the indicator warm-up."""
    timeframe_ms = timeframe_to_ms(request.timeframe)
    warmup_ms = int(warmup_bars * WARMUP_MULTIPLIER) * timeframe_ms
    start_ms = to_ms(request.start) - warmup_ms
    end_ms = to_ms(request.end)
    if end_ms <= start_ms:
        raise InsufficientDataError("The end date must be after the start date")

    try:
        await market_data.download_range(
            request.symbol, request.timeframe, start_ms, end_ms, db=db
        )
    except Exception as exc:
        logger.warning(
            "Could not download candles, using the local cache",
            extra={"error": str(exc), "symbol": request.symbol},
        )

    frame = market_data.load_range(request.symbol, request.timeframe, start_ms, end_ms, db=db)
    if frame.empty:
        raise InsufficientDataError(
            "No candles are available for this range. Check the internet connection or "
            "choose a different period."
        )
    logger.info(
        "Backtest data loaded",
        extra={
            "symbol": request.symbol,
            "timeframe": request.timeframe,
            "candles": len(frame),
            "from": from_ms(int(frame["open_time"].iloc[0])).isoformat(),
            "to": from_ms(int(frame["open_time"].iloc[-1])).isoformat(),
        },
    )
    return frame


def _persist_trades(db: Session, record: Backtest, output: BacktestOutput) -> None:
    """Write backtest trades into the shared trade journal."""
    for item in output.trades:
        db.add(
            Trade(
                uid=uuid.uuid4().hex[:24],
                backtest_id=record.id,
                symbol=item["symbol"],
                strategy_key=item["strategy"],
                mode=TradingMode.BACKTEST.value,
                timeframe=item["timeframe"],
                side=item["side"],
                quantity=item["quantity"],
                entry_price=item["entry_price"],
                exit_price=item["exit_price"],
                leverage=item["leverage"],
                stop_loss=item["stop_loss"],
                take_profit=item["take_profit"],
                notional=item["notional"],
                opened_at=from_ms(item["opened_ms"]),
                closed_at=from_ms(item["closed_ms"]),
                duration_seconds=item["duration_seconds"],
                gross_pnl=item["gross_pnl"],
                fees=item["fees"],
                funding=item["funding"],
                slippage_cost=item["slippage_cost"],
                net_pnl=item["net_pnl"],
                return_pct=item["return_pct"],
                equity_after=item["equity_after"],
                is_win=item["is_win"],
                signal_confidence=item["signal_confidence"],
                market_regime=item["market_regime"],
                entry_reason=item["entry_reason"],
                exit_reason=item["exit_reason"],
            )
        )
    db.commit()
