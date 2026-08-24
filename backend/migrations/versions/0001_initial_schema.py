"""Initial schema baseline.

This first revision creates the schema directly from the SQLAlchemy metadata.
That guarantees the migration and the ORM models can never disagree on day one.

Every FOLLOWING migration must be a normal, explicit Alembic revision. Generate
them with:

    alembic revision --autogenerate -m "describe the change"

and review the generated file before committing it.

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01
"""

from __future__ import annotations

from alembic import op

import app.models  # noqa: F401  (registers every table)
from app.database.base import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
