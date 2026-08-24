"""Strategy, signal, order, position and trade-journal models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import OrderStatus, PositionStatus, SignalStatus, TradingMode
from app.database.base import Amount, Base, TimestampMixin


class StrategyRecord(TimestampMixin, Base):
    """Registry row for one strategy implementation."""

    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    family: Mapped[str] = mapped_column(String(64), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class StrategyParameter(TimestampMixin, Base):
    """Configurable parameters for a strategy.

    A NULL symbol means "default for every symbol"; a row with a symbol
    overrides the default for that market only.
    """

    __tablename__ = "strategy_parameters"
    __table_args__ = (
        UniqueConstraint(
            "strategy_key", "symbol", "timeframe", name="uq_strategy_parameter_scope"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    timeframe: Mapped[str | None] = mapped_column(String(8), nullable=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)


class Signal(TimestampMixin, Base):
    """A strategy decision. A signal is NOT an order."""

    __tablename__ = "signals"
    __table_args__ = (
        Index("ix_signals_symbol_created", "symbol", "created_at"),
        UniqueConstraint(
            "strategy_key",
            "symbol",
            "timeframe",
            "candle_open_time",
            "mode",
            name="uq_signal_per_candle",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    strategy_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default=TradingMode.PAPER.value, index=True)
    candle_open_time: Mapped[int] = mapped_column(BigInteger, nullable=False)

    signal_type: Mapped[str] = mapped_column(String(8), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    market_regime: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    trend_regime: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    volatility_regime: Mapped[str] = mapped_column(String(24), default="UNKNOWN")

    entry_price: Mapped[float | None] = mapped_column(Amount, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Amount, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Amount, nullable=True)

    explanation: Mapped[str] = mapped_column(Text, default="")
    indicators: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default=SignalStatus.GENERATED.value)
    rejection_codes: Mapped[list] = mapped_column(JSON, default=list)
    rejection_details: Mapped[str] = mapped_column(Text, default="")


class Position(TimestampMixin, Base):
    """An open (or historical) position, per symbol and trading mode."""

    __tablename__ = "positions"
    __table_args__ = (Index("ix_positions_mode_status", "mode", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(16), default=TradingMode.PAPER.value, index=True)
    strategy_key: Mapped[str] = mapped_column(String(64), default="")
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=PositionStatus.OPEN.value)

    quantity: Mapped[float] = mapped_column(Amount, nullable=False)
    entry_price: Mapped[float] = mapped_column(Amount, nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Amount, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Amount, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Amount, nullable=True)
    trailing_stop: Mapped[float | None] = mapped_column(Amount, nullable=True)
    leverage: Mapped[float] = mapped_column(Float, default=1.0)
    margin: Mapped[float] = mapped_column(Amount, default=0.0)
    liquidation_price: Mapped[float | None] = mapped_column(Amount, nullable=True)

    unrealized_pnl: Mapped[float] = mapped_column(Amount, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Amount, default=0.0)
    fees_paid: Mapped[float] = mapped_column(Amount, default=0.0)
    funding_paid: Mapped[float] = mapped_column(Amount, default=0.0)
    slippage_cost: Mapped[float] = mapped_column(Amount, default=0.0)

    highest_price: Mapped[float | None] = mapped_column(Amount, nullable=True)
    lowest_price: Mapped[float | None] = mapped_column(Amount, nullable=True)

    opened_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_funding_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    signal_id: Mapped[int | None] = mapped_column(
        ForeignKey("signals.id", ondelete="SET NULL"), nullable=True
    )
    entry_reason: Mapped[str] = mapped_column(Text, default="")
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    market_regime: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    signal_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Order(TimestampMixin, Base):
    """Every order the Execution Engine created, successful or not.

    client_order_id is the idempotency key: the same logical order can never be
    submitted twice, even after a crash or a network timeout.
    """

    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_mode_status", "mode", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    exchange_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(16), default=TradingMode.PAPER.value, index=True)
    strategy_key: Mapped[str] = mapped_column(String(64), default="")
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default=OrderStatus.PENDING.value)

    quantity: Mapped[float] = mapped_column(Amount, nullable=False)
    price: Mapped[float | None] = mapped_column(Amount, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Amount, nullable=True)
    filled_quantity: Mapped[float] = mapped_column(Amount, default=0.0)
    average_fill_price: Mapped[float | None] = mapped_column(Amount, nullable=True)
    fee: Mapped[float] = mapped_column(Amount, default=0.0)
    reduce_only: Mapped[bool] = mapped_column(Boolean, default=False)

    position_id: Mapped[int | None] = mapped_column(
        ForeignKey("positions.id", ondelete="SET NULL"), nullable=True
    )
    signal_id: Mapped[int | None] = mapped_column(
        ForeignKey("signals.id", ondelete="SET NULL"), nullable=True
    )

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[dict] = mapped_column(JSON, default=dict)


class Trade(TimestampMixin, Base):
    """Trade journal: one row per completed round trip.

    Backtest, paper and live trades share this table (distinguished by mode) so
    the analytics layer has exactly one source of truth.
    """

    __tablename__ = "trades"
    __table_args__ = (
        Index("ix_trades_mode_closed", "mode", "closed_at"),
        Index("ix_trades_symbol_strategy", "symbol", "strategy_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    position_id: Mapped[int | None] = mapped_column(
        ForeignKey("positions.id", ondelete="SET NULL"), nullable=True
    )
    entry_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exit_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    backtest_id: Mapped[int | None] = mapped_column(
        ForeignKey("backtests.id", ondelete="CASCADE"), nullable=True, index=True
    )

    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    strategy_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    mode: Mapped[str] = mapped_column(String(16), default=TradingMode.PAPER.value, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), default="")
    side: Mapped[str] = mapped_column(String(8), nullable=False)

    quantity: Mapped[float] = mapped_column(Amount, nullable=False)
    entry_price: Mapped[float] = mapped_column(Amount, nullable=False)
    exit_price: Mapped[float] = mapped_column(Amount, nullable=False)
    leverage: Mapped[float] = mapped_column(Float, default=1.0)
    stop_loss: Mapped[float | None] = mapped_column(Amount, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Amount, nullable=True)
    notional: Mapped[float] = mapped_column(Amount, default=0.0)

    opened_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    closed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)

    gross_pnl: Mapped[float] = mapped_column(Amount, default=0.0)
    fees: Mapped[float] = mapped_column(Amount, default=0.0)
    funding: Mapped[float] = mapped_column(Amount, default=0.0)
    slippage_cost: Mapped[float] = mapped_column(Amount, default=0.0)
    net_pnl: Mapped[float] = mapped_column(Amount, default=0.0)
    return_pct: Mapped[float] = mapped_column(Float, default=0.0)
    equity_after: Mapped[float | None] = mapped_column(Amount, nullable=True)
    is_win: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    signal_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    market_regime: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    entry_reason: Mapped[str] = mapped_column(Text, default="")
    exit_reason: Mapped[str] = mapped_column(String(32), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
