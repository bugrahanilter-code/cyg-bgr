"""Matrix backtests: sweep jobs and their per-cell results.

A sweep runs one strategy x market x timeframe grid as a single background job.
Only the flat metric row of each cell is stored: a grid can hold tens of
thousands of runs, and keeping an equity curve and a trade list for each would
add gigabytes nobody reads. Every cell stays reproducible because the sweep
records the configuration it ran with.

Revision ID: 0002_backtest_sweeps
Revises: 0001_initial
Create Date: 2026-08-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_backtest_sweeps"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backtest_sweeps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uid", sa.String(length=48), nullable=False, unique=True),
        sa.Column("name", sa.String(length=160), server_default=""),
        sa.Column("strategy_keys", sa.JSON(), nullable=True),
        sa.Column("symbols", sa.JSON(), nullable=True),
        sa.Column("timeframes", sa.JSON(), nullable=True),
        sa.Column("start_date", sa.DateTime(), nullable=False),
        sa.Column("end_date", sa.DateTime(), nullable=False),
        sa.Column("starting_capital", sa.Numeric(24, 8), nullable=True),
        sa.Column("leverage", sa.Integer(), server_default="2"),
        sa.Column("cost_model", sa.JSON(), nullable=True),
        sa.Column("risk_config", sa.JSON(), nullable=True),
        sa.Column("download_missing", sa.Boolean(), server_default=sa.true()),
        sa.Column("status", sa.String(length=16), server_default="PENDING"),
        sa.Column("total_runs", sa.Integer(), server_default="0"),
        sa.Column("completed_runs", sa.Integer(), server_default="0"),
        sa.Column("failed_runs", sa.Integer(), server_default="0"),
        sa.Column("skipped_runs", sa.Integer(), server_default="0"),
        sa.Column("current_task", sa.String(length=200), server_default=""),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "backtest_sweep_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sweep_id", sa.Integer(), nullable=False),
        sa.Column("strategy_key", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="PENDING"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("total_trades", sa.Integer(), server_default="0"),
        sa.Column("net_pnl", sa.Numeric(24, 8), nullable=True),
        sa.Column("return_pct", sa.Float(), server_default="0"),
        sa.Column("win_rate_pct", sa.Float(), server_default="0"),
        sa.Column("profit_factor", sa.Float(), server_default="0"),
        sa.Column("sharpe_ratio", sa.Float(), server_default="0"),
        sa.Column("sortino_ratio", sa.Float(), server_default="0"),
        sa.Column("max_drawdown_pct", sa.Float(), server_default="0"),
        sa.Column("expectancy", sa.Float(), server_default="0"),
        sa.Column("expectancy_r", sa.Float(), server_default="0"),
        sa.Column("total_fees", sa.Numeric(24, 8), nullable=True),
        sa.Column("buy_hold_return_pct", sa.Float(), server_default="0"),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("candles_used", sa.Integer(), server_default="0"),
        sa.Column("duration_seconds", sa.Float(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["sweep_id"], ["backtest_sweeps.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_backtest_sweep_runs_sweep_id", "backtest_sweep_runs", ["sweep_id"]
    )
    op.create_index(
        "ix_sweep_runs_lookup",
        "backtest_sweep_runs",
        ["sweep_id", "strategy_key", "symbol", "timeframe"],
    )


def downgrade() -> None:
    op.drop_index("ix_sweep_runs_lookup", table_name="backtest_sweep_runs")
    op.drop_index("ix_backtest_sweep_runs_sweep_id", table_name="backtest_sweep_runs")
    op.drop_table("backtest_sweep_runs")
    op.drop_table("backtest_sweeps")
