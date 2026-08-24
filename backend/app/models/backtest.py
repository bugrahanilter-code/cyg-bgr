"""Backtest run configuration and results."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import BacktestStatus, DatasetSplit
from app.database.base import Amount, Base, TimestampMixin


class Backtest(TimestampMixin, Base):
    """One backtest run request plus its execution status."""

    __tablename__ = "backtests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), default="")
    strategy_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)

    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    starting_capital: Mapped[float] = mapped_column(Amount, default=10_000.0)

    params: Mapped[dict] = mapped_column(JSON, default=dict)
    cost_model: Mapped[dict] = mapped_column(JSON, default=dict)
    risk_config: Mapped[dict] = mapped_column(JSON, default=dict)
    split: Mapped[str] = mapped_column(String(20), default=DatasetSplit.FULL.value)

    status: Mapped[str] = mapped_column(String(16), default=BacktestStatus.PENDING.value)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    candles_used: Mapped[int] = mapped_column(Integer, default=0)


class BacktestResult(TimestampMixin, Base):
    """Metrics and curves produced by a completed backtest."""

    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    backtest_id: Mapped[int] = mapped_column(
        ForeignKey("backtests.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    equity_curve: Mapped[list] = mapped_column(JSON, default=list)
    drawdown_curve: Mapped[list] = mapped_column(JSON, default=list)
    monthly_returns: Mapped[list] = mapped_column(JSON, default=list)
    trade_distribution: Mapped[dict] = mapped_column(JSON, default=dict)
    walk_forward: Mapped[dict | None] = mapped_column(JSON, nullable=True)
