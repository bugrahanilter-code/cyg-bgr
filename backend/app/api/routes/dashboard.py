"""Dashboard overview endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import Context, DbSession
from app.services.dashboard_service import build_overview

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview", summary="Everything the overview page needs")
def overview(db: DbSession, context: Context) -> dict[str, Any]:
    return build_overview(db, context)
