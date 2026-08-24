"""Automatic market rotation: the audit trail of each pass.

Rotation changes what the bot trades without a human in the loop, so every run
records what came in, what went out, what was held back because a position was
still open, and why each candidate was rejected.

The rotation *configuration* needs no migration: it is stored in the existing
app_settings JSON table, as is the new min_leverage risk field.

Revision ID: 0003_rotation_runs
Revises: 0002_backtest_sweeps
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_rotation_runs"
down_revision = "0002_backtest_sweeps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rotation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ran_at", sa.DateTime(), nullable=False),
        sa.Column("dry_run", sa.Boolean(), server_default=sa.true()),
        sa.Column("triggered_by", sa.String(length=24), server_default="schedule"),
        sa.Column("selected", sa.JSON(), nullable=True),
        sa.Column("added", sa.JSON(), nullable=True),
        sa.Column("removed", sa.JSON(), nullable=True),
        sa.Column("unchanged", sa.JSON(), nullable=True),
        sa.Column("held_open", sa.JSON(), nullable=True),
        sa.Column("rejected", sa.JSON(), nullable=True),
        sa.Column("candidates_considered", sa.Integer(), server_default="0"),
        sa.Column("enabled_after", sa.Integer(), server_default="0"),
        sa.Column("duration_seconds", sa.Float(), server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_rotation_runs_ran_at", "rotation_runs", ["ran_at"])


def downgrade() -> None:
    op.drop_index("ix_rotation_runs_ran_at", table_name="rotation_runs")
    op.drop_table("rotation_runs")
