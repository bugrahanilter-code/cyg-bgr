"""Automatic market rotation: the audit trail of what was enabled and why.

Rotation changes what the bot trades without a human in the loop, so every run
is recorded: which markets came in, which went out, which were held back and for
what reason. Without that record a surprising position has no explanation.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class RotationRun(TimestampMixin, Base):
    """One pass of the top-gainer selection."""

    __tablename__ = "rotation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    #: True when the run only reported what it would do.
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    triggered_by: Mapped[str] = mapped_column(String(24), default="schedule")

    #: The ranked candidates that passed every quality filter.
    selected: Mapped[list] = mapped_column(JSON, default=list)
    added: Mapped[list] = mapped_column(JSON, default=list)
    removed: Mapped[list] = mapped_column(JSON, default=list)
    unchanged: Mapped[list] = mapped_column(JSON, default=list)
    #: Markets that would have been dropped but were kept because a position is
    #: still open on them.
    held_open: Mapped[list] = mapped_column(JSON, default=list)
    #: Candidates rejected by a filter, with the reason, so the ranking is
    #: explainable rather than mysterious.
    rejected: Mapped[list] = mapped_column(JSON, default=list)

    candidates_considered: Mapped[int] = mapped_column(Integer, default=0)
    enabled_after: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        added = len(self.added or [])
        removed = len(self.removed or [])
        return f"<RotationRun {self.ran_at:%Y-%m-%d %H:%M} +{added} -{removed}>"
