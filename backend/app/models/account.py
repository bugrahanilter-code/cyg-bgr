"""Account level bookkeeping: balances and daily statistics."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import TradingMode
from app.database.base import Amount, Base, TimestampMixin


class BalanceSnapshot(TimestampMixin, Base):
    """Point-in-time account snapshot, used for the equity curve."""

    __tablename__ = "balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), default=TradingMode.PAPER.value, index=True)
    source: Mapped[str] = mapped_column(String(16), default="local")
    asset: Mapped[str] = mapped_column(String(16), default="USDT")
    total_balance: Mapped[float] = mapped_column(Amount, default=0.0)
    available_balance: Mapped[float] = mapped_column(Amount, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Amount, default=0.0)
    equity: Mapped[float] = mapped_column(Amount, default=0.0)
    taken_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class DailyStatistic(TimestampMixin, Base):
    """Daily aggregates powering the profit target / loss limit guards."""

    __tablename__ = "daily_statistics"
    __table_args__ = (UniqueConstraint("mode", "day", name="uq_daily_statistics_mode_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), default=TradingMode.PAPER.value)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    starting_equity: Mapped[float] = mapped_column(Amount, default=0.0)
    ending_equity: Mapped[float] = mapped_column(Amount, default=0.0)
    peak_equity: Mapped[float] = mapped_column(Amount, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Amount, default=0.0)
    fees: Mapped[float] = mapped_column(Amount, default=0.0)
    funding: Mapped[float] = mapped_column(Amount, default=0.0)

    trades_count: Mapped[int] = mapped_column(Integer, default=0)
    winning_trades: Mapped[int] = mapped_column(Integer, default=0)
    losing_trades: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_losses: Mapped[int] = mapped_column(Integer, default=0)

    daily_return_pct: Mapped[float] = mapped_column(Float, default=0.0)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    profit_target_reached: Mapped[bool] = mapped_column(Boolean, default=False)
    loss_limit_reached: Mapped[bool] = mapped_column(Boolean, default=False)
    last_loss_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
