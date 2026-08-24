"""Trading Engine: the orchestrator that runs the whole pipeline.

    market data -> regime -> strategies -> signals -> risk -> execution

It is deliberately boring and defensive:

* it never opens a position while the market data is stale
* it never opens a position while the local state disagrees with the exchange
* it re-evaluates a strategy only when a NEW candle has closed
* the emergency stop is checked on every single cycle
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import (
    BotStatus,
    EmergencyStopLevel,
    EventSeverity,
    ExitReason,
    MarketRegime,
    PositionSide,
    ReconciliationStatus,
    SignalStatus,
    SignalType,
    TradingMode,
)
from app.core.exceptions import TradingPlatformError
from app.core.logging import get_logger
from app.core.time_utils import seconds_since, utcnow
from app.database.session import SessionLocal
from app.exchange.base import ExchangeGateway
from app.exchange.filters import SymbolFilters, default_filters_for
from app.execution.engine import ExecutionEngine
from app.market_data.service import MarketDataService
from app.models.trading import Position, Signal
from app.portfolio.engine import PortfolioEngine
from app.reconciliation.engine import ReconciliationEngine
from app.regime.engine import MarketRegimeEngine, RegimeResult
from app.risk.engine import OpenPositionInfo, RiskContext, RiskEngine
from app.services import bot_state_service, settings_service
from app.services.event_service import log_event
from app.signals.models import StrategySignal
from app.strategies.registry import create_strategy

logger = get_logger(__name__)


@dataclass(slots=True)
class EngineSnapshot:
    """Lightweight view of the engine, exposed through the API."""

    running: bool = False
    mode: str = TradingMode.PAPER.value
    status: str = BotStatus.STOPPED.value
    last_cycle_at: datetime | None = None
    cycles: int = 0
    errors: int = 0
    last_error: str = ""
    last_signals: dict[str, Any] = field(default_factory=dict)
    blocked_reasons: list[str] = field(default_factory=list)


class TradingEngine:
    """Runs paper or live trading in a single asyncio task."""

    def __init__(
        self,
        *,
        market_data: MarketDataService,
        gateway: ExchangeGateway,
        mode: TradingMode,
        loop_interval: float = 5.0,
        reconciliation_interval: float = 60.0,
        allow_real_orders: bool = False,
        filters: dict[str, SymbolFilters] | None = None,
    ) -> None:
        self.market_data = market_data
        self.gateway = gateway
        self.mode = mode
        self.loop_interval = loop_interval
        self.reconciliation_interval = reconciliation_interval
        self.filters = filters or {}

        self.portfolio = PortfolioEngine(mode)
        self.regime_engine = MarketRegimeEngine()
        self.risk_engine = RiskEngine()
        self.execution = ExecutionEngine(
            gateway,
            mode=mode,
            portfolio=self.portfolio,
            filters_provider=self.symbol_filters,
            allow_real_orders=allow_real_orders,
        )
        self.reconciliation = ReconciliationEngine(gateway, self.portfolio, mode)

        self.snapshot = EngineSnapshot(mode=mode.value)
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._last_candle: dict[str, int] = {}
        self._last_reconciliation: datetime | None = None
        self._latest_signals: dict[str, dict[str, Any]] = {}
        self._latest_regimes: dict[str, RegimeResult] = {}

    # -- helpers ------------------------------------------------------------
    def symbol_filters(self, symbol: str) -> SymbolFilters:
        return self.filters.get(symbol.upper(), default_filters_for(symbol))

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def latest_signals(self) -> dict[str, dict[str, Any]]:
        return self._latest_signals

    def latest_regime(self, symbol: str) -> RegimeResult | None:
        return self._latest_regimes.get(symbol.upper())

    # -- lifecycle ----------------------------------------------------------
    async def start(self) -> None:
        """Start the engine loop after a successful state recovery."""
        if self.is_running:
            return
        self._stopping.clear()
        with SessionLocal() as db:
            bot_state_service.set_status(db, BotStatus.STARTING)
            await self.recover_state(db)
            bot_state_service.set_status(db, BotStatus.RUNNING)
            log_event(
                db,
                message=f"Trading engine started in {self.mode.value} mode",
                category="engine",
                mode=self.mode.value,
            )
        self.snapshot.running = True
        self.snapshot.status = BotStatus.RUNNING.value
        self._task = asyncio.create_task(self._loop(), name="trading-engine")

    async def stop(self) -> None:
        """Stop the loop (positions are left untouched)."""
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.snapshot.running = False
        self.snapshot.status = BotStatus.STOPPED.value
        with SessionLocal() as db:
            bot_state_service.set_status(db, BotStatus.STOPPED)
            log_event(db, message="Trading engine stopped", category="engine", mode=self.mode.value)

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                self.snapshot.errors += 1
                self.snapshot.last_error = str(exc)[:500]
                logger.exception("Trading cycle failed")
                with SessionLocal() as db:
                    log_event(
                        db,
                        message=f"Trading cycle failed: {exc}",
                        category="engine",
                        severity=EventSeverity.ERROR,
                        mode=self.mode.value,
                    )
            await asyncio.sleep(self.loop_interval)

    # -- restart recovery ---------------------------------------------------
    async def recover_state(self, db: Session) -> None:
        """Rebuild a trustworthy picture of the world before trading again.

        1. local database is already loaded through the session
        2. connect to the exchange
        3. read balance, positions and open orders
        4. reconcile with the local state
        5. only then is trading allowed to continue
        """
        try:
            await self.gateway.connect()
        except Exception as exc:
            log_event(
                db,
                message=f"Exchange connection failed during recovery: {exc}",
                category="recovery",
                severity=EventSeverity.ERROR,
                mode=self.mode.value,
            )

        state = bot_state_service.get_state(db)
        if state.emergency_stop_level != EmergencyStopLevel.NONE.value:
            log_event(
                db,
                message=(
                    "Emergency stop is still armed from a previous session. "
                    "No new position will be opened until it is cleared."
                ),
                category="recovery",
                severity=EventSeverity.WARNING,
                mode=self.mode.value,
            )

        # Restore the last processed candle so a restart cannot replay signals.
        for signal in (
            db.query(Signal)
            .filter(Signal.mode == self.mode.value)
            .order_by(Signal.id.desc())
            .limit(200)
            .all()
        ):
            key = f"{signal.strategy_key}:{signal.symbol}:{signal.timeframe}"
            self._last_candle.setdefault(key, int(signal.candle_open_time))

        report = await self.reconciliation.reconcile(db, self._enabled_symbols(db))
        log_event(
            db,
            message=f"Restart recovery finished: {report.status.value}",
            category="recovery",
            severity=EventSeverity.INFO if report.ok else EventSeverity.CRITICAL,
            details={"differences": [d.to_dict() for d in report.differences]},
            mode=self.mode.value,
        )
        self._last_reconciliation = utcnow()

    def _enabled_symbols(self, db: Session) -> list[str]:
        return settings_service.get_trading_config(db).enabled_symbols

    # -- main cycle ---------------------------------------------------------
    async def run_cycle(self) -> None:
        """One full pass of the pipeline."""
        with SessionLocal() as db:
            bot_state_service.heartbeat(db)
            self.snapshot.cycles += 1
            self.snapshot.last_cycle_at = utcnow()

            trading_config = settings_service.get_trading_config(db)
            risk_config = settings_service.get_risk_config(db)
            self.risk_engine.config = risk_config
            state = bot_state_service.get_state(db)

            # 1. keep the account marked to market
            account = self.portfolio.account_state(db, self.market_data.last_price)
            if self.snapshot.cycles % 12 == 1:
                self.portfolio.record_balance_snapshot(db, account)

            # 2. handle emergency stop levels
            if state.emergency_stop_level == EmergencyStopLevel.CLOSE_ALL_POSITIONS.value:
                await self.close_all_positions(db, ExitReason.EMERGENCY_STOP)
                bot_state_service.update_state(
                    db, emergency_stop_level=EmergencyStopLevel.HALT_NEW_ENTRIES.value
                )
                return
            if state.emergency_stop_level == EmergencyStopLevel.FULL_STOP.value:
                self.snapshot.blocked_reasons = ["FULL_STOP"]
                return

            # 3. protective order sync and position management
            if self.mode == TradingMode.LIVE:
                await self._sync_protective_fills(db)
            await self._manage_positions(db, trading_config)

            # 4. periodic reconciliation
            if self._should_reconcile():
                await self.reconciliation.reconcile(db, trading_config.enabled_symbols)
                self._last_reconciliation = utcnow()

            # 5. entries
            await self._look_for_entries(db, trading_config, risk_config, account, state)

            bot_state_service.update_state(db, last_cycle_at=utcnow(), mode=self.mode.value)

    def _should_reconcile(self) -> bool:
        age = seconds_since(self._last_reconciliation)
        return age is None or age >= self.reconciliation_interval

    # -- open position management ------------------------------------------
    async def _manage_positions(self, db: Session, trading_config) -> None:
        """Check stop loss, take profit and trailing stops on live prices."""
        for position in self.portfolio.open_positions(db):
            price = self.market_data.last_price(position.symbol)
            if price is None or price <= 0:
                continue
            self._update_trailing_stop(position, price)
            reason = self._exit_reason_for(position, price)
            if reason is not None:
                try:
                    await self.execution.execute_exit(
                        db,
                        position,
                        reason=reason,
                        price_hint=price,
                        timeframe=trading_config.timeframe,
                    )
                except TradingPlatformError as exc:
                    log_event(
                        db,
                        message=f"Could not close {position.symbol}: {exc}",
                        category="execution",
                        severity=EventSeverity.CRITICAL,
                        mode=self.mode.value,
                        symbol=position.symbol,
                    )

    @staticmethod
    def _exit_reason_for(position: Position, price: float) -> ExitReason | None:
        """Decide whether a live price has triggered an exit level."""
        is_long = position.side == PositionSide.LONG.value
        stop = position.trailing_stop if position.trailing_stop is not None else position.stop_loss
        if stop is not None:
            if is_long and price <= float(stop):
                return (
                    ExitReason.TRAILING_STOP
                    if position.trailing_stop is not None
                    else ExitReason.STOP_LOSS
                )
            if not is_long and price >= float(stop):
                return (
                    ExitReason.TRAILING_STOP
                    if position.trailing_stop is not None
                    else ExitReason.STOP_LOSS
                )
        if position.take_profit is not None:
            if is_long and price >= float(position.take_profit):
                return ExitReason.TAKE_PROFIT
            if not is_long and price <= float(position.take_profit):
                return ExitReason.TAKE_PROFIT
        return None

    def _update_trailing_stop(self, position: Position, price: float) -> None:
        """Move the stop in the profitable direction only."""
        meta = position.meta or {}
        atr = meta.get("atr")
        multiplier = float(meta.get("trailing_atr_multiplier", 0.0) or 0.0)
        if not atr or multiplier <= 0:
            return
        distance = float(atr) * multiplier
        if position.side == PositionSide.LONG.value:
            candidate = price - distance
            floor_value = float(position.stop_loss or candidate)
            best = max(candidate, floor_value)
            if position.trailing_stop is None or best > float(position.trailing_stop):
                position.trailing_stop = best
        else:
            candidate = price + distance
            ceiling = float(position.stop_loss or candidate)
            best = min(candidate, ceiling)
            if position.trailing_stop is None or best < float(position.trailing_stop):
                position.trailing_stop = best

    async def _sync_protective_fills(self, db: Session) -> None:
        """Detect stop/take-profit orders that the exchange already filled."""
        from app.core.constants import OrderStatus
        from app.models.trading import Order

        for position in self.portfolio.open_positions(db):
            orders = (
                db.query(Order)
                .filter(
                    Order.position_id == position.id,
                    Order.mode == self.mode.value,
                    Order.status.in_([OrderStatus.NEW.value, OrderStatus.PENDING.value]),
                )
                .all()
            )
            for order in orders:
                confirmed = await self.execution._fetch_exchange_order(
                    order.symbol, order.client_order_id
                )
                if confirmed is None or confirmed.status != OrderStatus.FILLED:
                    continue
                order.status = OrderStatus.FILLED.value
                order.filled_quantity = confirmed.filled_quantity
                order.average_fill_price = confirmed.average_price
                db.commit()
                reason = (
                    ExitReason.STOP_LOSS
                    if "stoploss" in order.client_order_id
                    else ExitReason.TAKE_PROFIT
                )
                self.portfolio.close_position(
                    db,
                    position,
                    exit_price=float(confirmed.average_price or position.entry_price),
                    exit_reason=reason,
                    exit_fees=confirmed.fee,
                    exit_order_id=order.client_order_id,
                )
                break

    async def close_all_positions(self, db: Session, reason: ExitReason) -> int:
        """Emergency helper: flatten everything in this mode."""
        closed = 0
        for position in self.portfolio.open_positions(db):
            price = self.market_data.last_price(position.symbol) or float(position.entry_price)
            try:
                await self.execution.execute_exit(db, position, reason=reason, price_hint=price)
                closed += 1
            except TradingPlatformError as exc:
                log_event(
                    db,
                    message=f"Emergency close failed for {position.symbol}: {exc}",
                    category="emergency_stop",
                    severity=EventSeverity.CRITICAL,
                    mode=self.mode.value,
                    symbol=position.symbol,
                )
        if closed:
            log_event(
                db,
                message=f"Closed {closed} position(s): {reason.value}",
                category="emergency_stop",
                severity=EventSeverity.CRITICAL,
                mode=self.mode.value,
            )
        return closed

    # -- entries ------------------------------------------------------------
    async def _look_for_entries(
        self, db: Session, trading_config, risk_config, account, state
    ) -> None:
        """Generate signals for every enabled market and strategy."""
        context = self._build_risk_context(db, trading_config, risk_config, account, state)
        gate = self.risk_engine.can_open_new_positions(context)
        self.snapshot.blocked_reasons = gate.codes

        for symbol in trading_config.enabled_symbols:
            frame = await self._candles_for(db, symbol, trading_config.timeframe)
            if frame is None or frame.empty:
                continue
            annotated = self.regime_engine.annotate(frame)
            regime = self.regime_engine.result_at(annotated, len(annotated) - 1)
            self._latest_regimes[symbol.upper()] = regime
            candle_open_time = int(frame["open_time"].iloc[-1])
            position = self.portfolio.get_position(db, symbol)

            for strategy_key, enabled in trading_config.enabled_strategies.items():
                if not enabled:
                    continue
                key = f"{strategy_key}:{symbol}:{trading_config.timeframe}"
                if self._last_candle.get(key) == candle_open_time and position is None:
                    continue
                signal = await self._evaluate_strategy(
                    db, strategy_key, symbol, trading_config, frame, regime, position
                )
                if signal is None:
                    continue
                self._last_candle[key] = candle_open_time
                self._latest_signals[key] = signal.to_dict()

                if signal.signal == SignalType.CLOSE and position is not None:
                    if position.strategy_key == strategy_key:
                        await self.execution.execute_exit(
                            db,
                            position,
                            reason=ExitReason.SIGNAL_EXIT,
                            price_hint=self.market_data.last_price(symbol),
                            timeframe=trading_config.timeframe,
                        )
                        position = None
                    continue

                if not signal.is_entry or position is not None:
                    continue

                await self._process_entry(db, signal, context, trading_config, gate)

    async def _evaluate_strategy(
        self, db: Session, strategy_key: str, symbol: str, trading_config, frame, regime, position
    ) -> StrategySignal | None:
        """Run one strategy and persist its decision."""
        try:
            stored_params = settings_service.get_json_setting(db, f"strategy_params:{strategy_key}", {})
            strategy = create_strategy(strategy_key, stored_params)
            signal = strategy.generate(
                frame,
                symbol=symbol,
                timeframe=trading_config.timeframe,
                regime=regime,
                position_side=position.side if position else None,
            )
        except TradingPlatformError as exc:
            log_event(
                db,
                message=f"Strategy {strategy_key} failed on {symbol}: {exc}",
                category="strategy",
                severity=EventSeverity.ERROR,
                mode=self.mode.value,
                symbol=symbol,
            )
            return None
        self._persist_signal(db, signal)
        return signal

    def _persist_signal(self, db: Session, signal: StrategySignal) -> Signal | None:
        """Store a signal, ignoring duplicates for the same candle."""
        row = Signal(
            uid=signal.uid,
            symbol=signal.symbol,
            strategy_key=signal.strategy_key,
            timeframe=signal.timeframe,
            mode=self.mode.value,
            candle_open_time=signal.candle_open_time,
            signal_type=signal.signal.value,
            confidence=signal.confidence,
            market_regime=signal.regime.regime.value if signal.regime else MarketRegime.UNKNOWN.value,
            trend_regime=signal.regime.trend.value if signal.regime else "UNKNOWN",
            volatility_regime=signal.regime.volatility.value if signal.regime else "UNKNOWN",
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            explanation=signal.explanation,
            indicators=signal.indicators,
            status=SignalStatus.GENERATED.value,
        )
        try:
            db.add(row)
            db.commit()
            db.refresh(row)
            return row
        except IntegrityError:
            db.rollback()
            return None

    async def _process_entry(self, db: Session, signal: StrategySignal, context, trading_config, gate) -> None:
        """Risk-check a signal and, if approved, execute it."""
        context.symbol_enabled = trading_config.is_symbol_enabled(signal.symbol)
        context.strategy_enabled = trading_config.is_strategy_enabled(signal.strategy_key)
        context.leverage = float(trading_config.leverage)
        context.filters = self.symbol_filters(signal.symbol)
        context.regime = signal.regime
        ticker = self.market_data.get_ticker(signal.symbol)
        context.spread_pct = ticker.spread_pct if ticker else None
        context.now = utcnow()

        decision = self.risk_engine.evaluate(signal, context)
        row = (
            db.query(Signal)
            .filter(Signal.uid == signal.uid)
            .one_or_none()
        )
        if not decision.approved:
            if row is not None:
                row.status = SignalStatus.REJECTED_BY_RISK.value
                row.rejection_codes = decision.codes
                row.rejection_details = decision.summary[:1000]
                db.commit()
            return

        if row is not None:
            row.status = SignalStatus.ACCEPTED.value
            db.commit()

        try:
            position = await self.execution.execute_entry(
                db,
                signal=signal,
                sizing=decision.sizing,
                leverage=context.leverage,
                timeframe=trading_config.timeframe,
                signal_row_id=row.id if row else None,
            )
        except TradingPlatformError as exc:
            if row is not None:
                row.status = SignalStatus.EXECUTION_FAILED.value
                row.rejection_details = str(exc)[:1000]
                db.commit()
            log_event(
                db,
                message=f"Execution failed for {signal.symbol}: {exc}",
                category="execution",
                severity=EventSeverity.ERROR,
                mode=self.mode.value,
                symbol=signal.symbol,
            )
            return

        if position is not None and row is not None:
            row.status = SignalStatus.EXECUTED.value
            db.commit()

    # -- data ---------------------------------------------------------------
    async def _candles_for(self, db: Session, symbol: str, timeframe: str):
        """Return closed candles, syncing at most once per candle period."""
        from app.core.constants import timeframe_to_ms

        bucket = int(utcnow().timestamp() * 1000) // timeframe_to_ms(timeframe)
        key = f"sync:{symbol}:{timeframe}"
        if self._last_candle.get(key) != bucket:
            self._last_candle[key] = bucket
            try:
                await self.market_data.sync_recent(symbol, timeframe, lookback=600, db=db)
            except Exception as exc:
                logger.warning(
                    "Candle sync failed", extra={"symbol": symbol, "error": str(exc)}
                )
        return self.market_data.get_candles(symbol, timeframe, limit=600, db=db)

    # -- risk context -------------------------------------------------------
    def _build_risk_context(self, db: Session, trading_config, risk_config, account, state) -> RiskContext:
        """Assemble the state the risk rules need."""
        stats = self.portfolio.daily_stats(db)
        positions = self.portfolio.open_positions(db)
        open_infos = [
            OpenPositionInfo(
                symbol=position.symbol,
                side=SignalType.LONG
                if position.side == PositionSide.LONG.value
                else SignalType.SHORT,
                notional=float(position.entry_price) * float(position.quantity),
                margin=float(position.margin or 0.0),
            )
            for position in positions
        ]
        peak = max(
            float(stats.peak_equity or 0.0),
            float(stats.starting_equity or 0.0),
            account.equity,
        )
        return RiskContext(
            equity=account.equity,
            available_balance=account.available,
            mode=self.mode,
            open_positions=open_infos,
            daily_start_equity=float(stats.starting_equity or account.equity),
            daily_realized_pnl=float(stats.realized_pnl or 0.0),
            trades_today=int(stats.trades_count or 0),
            consecutive_losses=int(stats.consecutive_losses or 0),
            last_loss_at=stats.last_loss_at,
            peak_equity=peak,
            market_data_stale=self.market_data.is_stale(),
            reconciliation_ok=state.reconciliation_status
            in (ReconciliationStatus.IN_SYNC.value, ReconciliationStatus.NEVER_RUN.value),
            emergency_stop=EmergencyStopLevel(state.emergency_stop_level),
            trading_enabled=state.status
            not in (BotStatus.EMERGENCY_STOPPED.value, BotStatus.ERROR.value),
            live_trading_confirmed=bool(state.live_trading_confirmed),
            leverage=float(trading_config.leverage),
            now=utcnow(),
        )

    # -- reporting ----------------------------------------------------------
    def status(self) -> dict[str, Any]:
        """Engine status for the dashboard."""
        return {
            "running": self.is_running,
            "mode": self.mode.value,
            "cycles": self.snapshot.cycles,
            "errors": self.snapshot.errors,
            "last_error": self.snapshot.last_error,
            "last_cycle_at": self.snapshot.last_cycle_at,
            "blocked_reasons": self.snapshot.blocked_reasons,
            "allow_real_orders": self.execution.allow_real_orders,
            "gateway": self.gateway.name,
        }
