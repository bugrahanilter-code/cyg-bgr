"""Execution Engine.

THE ONLY component allowed to send an order to an exchange.

Safety properties:

* real orders require an explicit allow_real_orders flag on top of the gateway
  capability, so a misconfiguration cannot silently trade real money
* every order is written to the database BEFORE it is submitted
* every order carries a deterministic client order id (no double execution)
* an API response is not treated as success: the order state is verified
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import (
    EventSeverity,
    ExitReason,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    SignalType,
    TradingMode,
)
from app.core.exceptions import ExecutionError, LiveTradingDisabledError, OrderValidationError
from app.core.logging import get_logger
from app.core.time_utils import utcnow
from app.exchange.base import ExchangeGateway, ExchangeOrder
from app.exchange.filters import SymbolFilters, default_filters_for
from app.execution.idempotency import build_client_order_id
from app.execution.validators import validate_order
from app.models.trading import Order, Position
from app.portfolio.engine import PortfolioEngine
from app.risk.exit_policy import ExitLevels
from app.risk.position_sizing import PositionSizing
from app.services.event_service import log_event
from app.signals.models import StrategySignal

logger = get_logger(__name__)

FiltersProvider = Callable[[str], SymbolFilters]


class ExecutionEngine:
    """Turns approved signals into verified exchange orders."""

    def __init__(
        self,
        gateway: ExchangeGateway,
        *,
        mode: TradingMode,
        portfolio: PortfolioEngine,
        filters_provider: FiltersProvider | None = None,
        taker_fee_pct: float = 0.04,
        max_leverage: int = 125,
        allow_real_orders: bool = False,
        verify_attempts: int = 3,
        verify_delay_seconds: float = 0.6,
    ) -> None:
        self.gateway = gateway
        self.mode = mode
        self.portfolio = portfolio
        self.filters_provider = filters_provider or default_filters_for
        self.taker_fee_pct = taker_fee_pct
        self.max_leverage = max_leverage
        self.allow_real_orders = allow_real_orders
        self.verify_attempts = verify_attempts
        self.verify_delay_seconds = verify_delay_seconds

    # -- guards -------------------------------------------------------------
    def _assert_allowed(self) -> None:
        """Defence in depth against accidentally trading real money."""
        if self.gateway.supports_real_orders and not self.allow_real_orders:
            raise LiveTradingDisabledError(
                "Real orders are not enabled. Confirm live trading from the dashboard first."
            )

    # -- entries ------------------------------------------------------------
    async def execute_entry(
        self,
        db: Session,
        *,
        signal: StrategySignal,
        sizing: PositionSizing,
        leverage: float,
        timeframe: str = "",
        signal_row_id: int | None = None,
        exits: ExitLevels | None = None,
    ) -> Position | None:
        """Open a position for an approved signal.

        ``exits`` carries the levels the Risk Engine decided. They replace what
        the strategy proposed, because the risk configuration may have widened,
        tightened or removed them, and the position has to be opened with the
        levels its size was calculated from. It is passed as an object rather
        than two floats so that "no take profit" stays distinguishable from
        "no opinion" - a None target is a decision, not a missing value.
        """
        self._assert_allowed()
        side = OrderSide.BUY if signal.signal == SignalType.LONG else OrderSide.SELL
        position_side = (
            PositionSide.LONG if signal.signal == SignalType.LONG else PositionSide.SHORT
        )
        filters = self.filters_provider(signal.symbol)

        client_order_id = build_client_order_id(
            mode=self.mode.value,
            symbol=signal.symbol,
            strategy=signal.strategy_key,
            candle_open_time=signal.candle_open_time,
            side=side.value,
            purpose="entry",
        )

        if self.mode == TradingMode.LIVE:
            await self.gateway.set_leverage(signal.symbol, int(leverage))

        order_row, exchange_order = await self._submit(
            db,
            symbol=signal.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=sizing.quantity,
            price=None,
            stop_price=None,
            reduce_only=False,
            client_order_id=client_order_id,
            strategy_key=signal.strategy_key,
            signal_row_id=signal_row_id,
            reference_price=signal.entry_price,
            leverage=leverage,
            filters=filters,
        )
        if exchange_order is None or exchange_order.status != OrderStatus.FILLED:
            log_event(
                db,
                message="Entry order was not filled",
                category="execution",
                severity=EventSeverity.ERROR,
                details={"client_order_id": client_order_id, "symbol": signal.symbol},
                mode=self.mode.value,
                symbol=signal.symbol,
            )
            return None

        fill_price = exchange_order.average_price or signal.entry_price or 0.0
        quantity = exchange_order.filled_quantity or sizing.quantity
        notional = fill_price * quantity
        fee = exchange_order.fee or notional * self.taker_fee_pct / 100.0
        slippage = abs(fill_price - (signal.entry_price or fill_price)) * quantity

        position = self.portfolio.create_position(
            db,
            symbol=signal.symbol,
            side=position_side,
            quantity=quantity,
            entry_price=fill_price,
            stop_loss=exits.stop_loss if exits is not None else signal.stop_loss,
            take_profit=exits.take_profit if exits is not None else signal.take_profit,
            leverage=leverage,
            margin=notional / max(leverage, 1.0),
            strategy_key=signal.strategy_key,
            signal_id=signal_row_id,
            entry_reason=signal.explanation,
            market_regime=signal.regime.regime.value if signal.regime else "UNKNOWN",
            signal_confidence=signal.confidence,
            fees_paid=fee,
            slippage_cost=slippage,
            liquidation_price=sizing.liquidation_price,
            meta={"timeframe": timeframe, "atr": signal.metadata.get("atr")},
        )
        order_row.position_id = position.id
        db.commit()

        if self.mode == TradingMode.LIVE:
            await self.place_protective_orders(db, position)
        return position

    # -- exits --------------------------------------------------------------
    async def execute_exit(
        self,
        db: Session,
        position: Position,
        *,
        reason: ExitReason,
        price_hint: float | None = None,
        timeframe: str = "",
        quantity: float | None = None,
    ):
        """Close a position, or part of one, with a reduce-only market order.

        ``quantity`` closes only that much and leaves the rest open. It is
        rounded to the exchange step size first, because an order the exchange
        rejects for precision would leave the position untouched while the
        caller believes it shrank.
        """
        self._assert_allowed()
        side = OrderSide.SELL if position.side == PositionSide.LONG.value else OrderSide.BUY
        filters = self.filters_provider(position.symbol)
        client_order_id = build_client_order_id(
            mode=self.mode.value,
            symbol=position.symbol,
            strategy=position.strategy_key,
            candle_open_time=int(position.opened_at.timestamp()),
            side=side.value,
            purpose="exit",
            nonce=position.uid,
        )

        open_quantity = float(position.quantity)
        close_quantity = open_quantity
        if quantity is not None:
            close_quantity = filters.round_quantity(min(abs(float(quantity)), open_quantity))
            if close_quantity <= 0 or not filters.is_valid_quantity(close_quantity):
                raise OrderValidationError(
                    f"{close_quantity} is below the minimum tradable size for "
                    f"{position.symbol} ({filters.min_quantity})"
                )
        is_partial = close_quantity < open_quantity

        if self.mode == TradingMode.LIVE and not is_partial:
            await self.cancel_protective_orders(db, position)

        order_row, exchange_order = await self._submit(
            db,
            symbol=position.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=close_quantity,
            price=None,
            stop_price=None,
            reduce_only=True,
            client_order_id=client_order_id,
            strategy_key=position.strategy_key,
            signal_row_id=None,
            reference_price=price_hint,
            leverage=float(position.leverage or 1.0),
            filters=filters,
        )
        if exchange_order is None or exchange_order.status != OrderStatus.FILLED:
            log_event(
                db,
                message="Exit order was not filled, position stays open",
                category="execution",
                severity=EventSeverity.CRITICAL,
                details={"client_order_id": client_order_id, "symbol": position.symbol},
                mode=self.mode.value,
                symbol=position.symbol,
            )
            return None

        exit_price = exchange_order.average_price or price_hint or float(position.entry_price)
        exit_notional = exit_price * close_quantity
        exit_fee = exchange_order.fee or exit_notional * self.taker_fee_pct / 100.0
        slippage = abs(exit_price - (price_hint or exit_price)) * close_quantity

        order_row.position_id = position.id
        db.commit()

        if is_partial:
            return self.portfolio.reduce_position(
                db,
                position,
                quantity=close_quantity,
                exit_price=exit_price,
                exit_reason=reason,
                exit_fees=exit_fee,
                slippage_cost=slippage,
                exit_order_id=client_order_id,
                timeframe=timeframe,
            )

        trade = self.portfolio.close_position(
            db,
            position,
            exit_price=exit_price,
            exit_reason=reason,
            exit_fees=exit_fee,
            slippage_cost=slippage,
            exit_order_id=client_order_id,
            timeframe=timeframe or str((position.meta or {}).get("timeframe", "")),
        )
        return trade

    # -- protective orders (live futures) -----------------------------------
    async def place_protective_orders(self, db: Session, position: Position) -> None:
        """Put the stop loss and take profit on the exchange itself.

        Exchange-side protection keeps working even if this application, the
        network or the computer goes down.
        """
        if self.mode != TradingMode.LIVE:
            return
        side = OrderSide.SELL if position.side == PositionSide.LONG.value else OrderSide.BUY
        filters = self.filters_provider(position.symbol)

        for purpose, order_type, trigger in (
            ("stoploss", OrderType.STOP_MARKET, position.stop_loss),
            ("takeprofit", OrderType.TAKE_PROFIT_MARKET, position.take_profit),
        ):
            if not trigger:
                continue
            client_order_id = build_client_order_id(
                mode=self.mode.value,
                symbol=position.symbol,
                strategy=position.strategy_key,
                candle_open_time=int(position.opened_at.timestamp()),
                side=side.value,
                purpose=purpose,
                nonce=position.uid,
            )
            try:
                await self._submit(
                    db,
                    symbol=position.symbol,
                    side=side,
                    order_type=order_type,
                    quantity=float(position.quantity),
                    price=None,
                    stop_price=float(trigger),
                    reduce_only=True,
                    client_order_id=client_order_id,
                    strategy_key=position.strategy_key,
                    signal_row_id=None,
                    reference_price=float(position.entry_price),
                    leverage=float(position.leverage or 1.0),
                    filters=filters,
                    verify=False,
                )
            except (ExecutionError, OrderValidationError) as exc:
                log_event(
                    db,
                    message=f"Could not place the {purpose} order: {exc}",
                    category="execution",
                    severity=EventSeverity.ERROR,
                    mode=self.mode.value,
                    symbol=position.symbol,
                )

    async def cancel_protective_orders(self, db: Session, position: Position) -> None:
        """Cancel resting stop-loss / take-profit orders for a position."""
        rows = (
            db.execute(
                select(Order).where(
                    Order.position_id == position.id,
                    Order.mode == self.mode.value,
                    Order.status.in_([OrderStatus.NEW.value, OrderStatus.PENDING.value]),
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            try:
                cancelled = await self.gateway.cancel_order(row.symbol, row.client_order_id)
                if cancelled:
                    row.status = OrderStatus.CANCELED.value
            except Exception as exc:  # pragma: no cover - best effort
                logger.warning("Cancel failed", extra={"error": str(exc)})
        db.commit()

    # -- low level submission ----------------------------------------------
    async def _submit(
        self,
        db: Session,
        *,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None,
        stop_price: float | None,
        reduce_only: bool,
        client_order_id: str,
        strategy_key: str,
        signal_row_id: int | None,
        reference_price: float | None,
        leverage: float,
        filters: SymbolFilters,
        verify: bool = True,
    ) -> tuple[Order, ExchangeOrder | None]:
        """Validate, persist, submit and verify a single order."""
        existing = db.execute(
            select(Order).where(Order.client_order_id == client_order_id)
        ).scalar_one_or_none()
        if existing is not None and existing.status not in (
            OrderStatus.REJECTED.value,
            OrderStatus.EXPIRED.value,
        ):
            logger.warning(
                "Duplicate order suppressed",
                extra={"client_order_id": client_order_id, "symbol": symbol},
            )
            known = await self._fetch_exchange_order(symbol, client_order_id)
            return existing, known

        validation = validate_order(
            symbol=symbol,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            order_type=order_type,
            filters=filters,
            reference_price=reference_price,
            leverage=leverage,
            max_leverage=self.max_leverage,
        )
        if not validation.valid:
            raise OrderValidationError("; ".join(validation.errors))

        order_row = Order(
            client_order_id=client_order_id,
            symbol=symbol,
            mode=self.mode.value,
            strategy_key=strategy_key,
            side=side.value,
            order_type=order_type.value,
            status=OrderStatus.PENDING.value,
            quantity=validation.quantity,
            price=validation.price,
            stop_price=validation.stop_price,
            reduce_only=reduce_only,
            signal_id=signal_row_id,
            submitted_at=utcnow(),
        )
        db.add(order_row)
        db.commit()
        db.refresh(order_row)

        try:
            response = await self.gateway.create_order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=validation.quantity,
                price=validation.price,
                stop_price=validation.stop_price,
                reduce_only=reduce_only,
                client_order_id=client_order_id,
            )
        except Exception as exc:
            order_row.status = OrderStatus.REJECTED.value
            order_row.error_message = str(exc)[:1000]
            db.commit()
            logger.error(
                "Order submission failed",
                extra={"symbol": symbol, "client_order_id": client_order_id, "error": str(exc)},
            )
            raise ExecutionError(f"Order submission failed: {exc}") from exc

        if verify and response.status != OrderStatus.FILLED and order_type == OrderType.MARKET:
            response = await self._verify(symbol, client_order_id, response)

        self._apply_response(order_row, response)
        db.commit()
        logger.info(
            "Order submitted",
            extra={
                "symbol": symbol,
                "side": side.value,
                "type": order_type.value,
                "quantity": validation.quantity,
                "status": order_row.status,
                "mode": self.mode.value,
                "client_order_id": client_order_id,
            },
        )
        return order_row, response

    async def _verify(
        self, symbol: str, client_order_id: str, fallback: ExchangeOrder
    ) -> ExchangeOrder:
        """Never trust the submit response alone: read the state back."""
        for attempt in range(self.verify_attempts):
            await asyncio.sleep(self.verify_delay_seconds * (attempt + 1))
            confirmed = await self._fetch_exchange_order(symbol, client_order_id)
            if confirmed is not None and confirmed.status in (
                OrderStatus.FILLED,
                OrderStatus.CANCELED,
                OrderStatus.REJECTED,
                OrderStatus.EXPIRED,
            ):
                return confirmed
        return fallback

    async def _fetch_exchange_order(
        self, symbol: str, client_order_id: str
    ) -> ExchangeOrder | None:
        try:
            return await self.gateway.fetch_order(symbol, client_order_id)
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("Order verification failed", extra={"error": str(exc)})
            return None

    @staticmethod
    def _apply_response(order_row: Order, response: ExchangeOrder) -> None:
        order_row.exchange_order_id = response.exchange_order_id
        order_row.status = response.status.value
        order_row.filled_quantity = response.filled_quantity
        order_row.average_fill_price = response.average_price
        order_row.fee = response.fee
        order_row.raw_response = response.raw if isinstance(response.raw, dict) else {}
        if response.status == OrderStatus.FILLED:
            order_row.filled_at = utcnow()
