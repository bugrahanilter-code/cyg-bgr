"""Declarative base and shared column types.

A single naming convention is configured so Alembic can autogenerate stable
migration names for indexes and constraints.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, MetaData, Numeric
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.time_utils import utcnow

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

#: Money / price / quantity column type.
#: asdecimal=False keeps Python-side values as plain floats, which behaves
#: identically on PostgreSQL and on the SQLite database used by the tests.
Amount = Numeric(30, 12, asdecimal=False)


class Base(DeclarativeBase):
    """Base class for every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Adds created_at / updated_at bookkeeping columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
