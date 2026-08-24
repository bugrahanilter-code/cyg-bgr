"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.services.container import AppContext, context


def get_context() -> AppContext:
    """Return the application context singleton."""
    return context


DbSession = Annotated[Session, Depends(get_db)]
Context = Annotated[AppContext, Depends(get_context)]
