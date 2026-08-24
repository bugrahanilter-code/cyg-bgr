"""Matrix backtests: one strategy x symbol x timeframe grid, run as a batch.

Why this is separate from :mod:`app.models.backtest`
----------------------------------------------------
A single backtest stores everything: the equity curve, the drawdown curve, the
monthly table and every individual trade. That is the right amount of detail
when a human is studying one run.

A sweep produces thousands of runs. Keeping full detail for each would add
gigabytes and would not be read. A sweep therefore stores only the flat metric
row per cell, which is what a comparison table needs. Any cell can be re-run as
a normal backtest afterwards to get the full detail back — the configuration is
stored, so the run is reproducible.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import BacktestStatus
from app.database.base import Amount, Base, TimestampMixin


class BacktestSweep(TimestampMixin, Base):
    """One batch job covering a grid of strategies, symbols and timeframes."""

    __tablename__ = "backtest_sweeps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), default="")

    strategy_keys: Mapped[list] = mapped_column(JSON, default=list)
    symbols: Mapped[list] = mapped_column(JSON, default=list)
    timeframes: Mapped[list] = mapped_column(JSON, default=list)

    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    starting_capital: Mapped[float] = mapped_column(Amount, default=10_000.0)
    leverage: Mapped[int] = mapped_column(Integer, default=2)

    cost_model: Mapped[dict] = mapped_column(JSON, default=dict)
    risk_config: Mapped[dict] = mapped_column(JSON, default=dict)
    #: When true the runner downloads any candles it is missing before running.
    download_missing: Mapped[bool] = mapped_column(Boolean, default=True)

    status: Mapped[str] = mapped_column(String(16), default=BacktestStatus.PENDING.value)
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    completed_runs: Mapped[int] = mapped_column(Integer, default=0)
    failed_runs: Mapped[int] = mapped_column(Integer, default=0)
    skipped_runs: Mapped[int] = mapped_column(Integer, default=0)
    #: Human readable "what is it doing right now", polled by the dashboard.
    current_task: Mapped[str] = mapped_column(String(200), default="")

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<BacktestSweep {self.uid} {self.status} {self.completed_runs}/{self.total_runs}>"


class SweepRun(TimestampMixin, Base):
    """One cell of the grid: a single strategy on a single market and timeframe."""

    __tablename__ = "backtest_sweep_runs"
    __table_args__ = (
        Index("ix_sweep_runs_lookup", "sweep_id", "strategy_key", "symbol", "timeframe"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sweep_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_sweeps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    strategy_key: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)

    status: Mapped[str] = mapped_column(String(16), default=BacktestStatus.PENDING.value)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Flat metrics, duplicated as columns so the results table can sort in SQL
    # instead of pulling thousands of JSON blobs into Python.
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    net_pnl: Mapped[float] = mapped_column(Amount, default=0.0)
    return_pct: Mapped[float] = mapped_column(Float, default=0.0)
    win_rate_pct: Mapped[float] = mapped_column(Float, default=0.0)
    profit_factor: Mapped[float] = mapped_column(Float, default=0.0)
    sharpe_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    sortino_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    expectancy: Mapped[float] = mapped_column(Float, default=0.0)
    #: Average profit per trade measured in units of risk. Comparable across
    #: markets and account sizes in a way that a dollar figure is not.
    expectancy_r: Mapped[float] = mapped_column(Float, default=0.0)
    total_fees: Mapped[float] = mapped_column(Amount, default=0.0)
    #: Return of simply holding the coin over the same window, for reference.
    buy_hold_return_pct: Mapped[float] = mapped_column(Float, default=0.0)

    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    candles_used: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<SweepRun {self.strategy_key} {self.symbol} {self.timeframe} {self.status}>"
