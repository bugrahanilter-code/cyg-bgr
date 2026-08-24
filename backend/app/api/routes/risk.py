"""Risk settings endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import Context, DbSession
from app.risk.config import RiskConfig
from app.schemas.requests import RiskConfigRequest
from app.services import event_service, settings_service

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("", summary="Current risk limits")
def get_risk(db: DbSession) -> dict[str, Any]:
    config = settings_service.get_risk_config(db)
    return {
        "config": config.model_dump(),
        "defaults": RiskConfig.from_settings().model_dump(),
        "schema": RiskConfig.model_json_schema(),
    }


@router.put("", summary="Update the risk limits")
def update_risk(payload: RiskConfigRequest, db: DbSession, context: Context) -> dict[str, Any]:
    before = settings_service.get_risk_config(db).model_dump()
    config = RiskConfig(**payload.model_dump())
    settings_service.save_risk_config(db, config)
    event_service.audit(
        db, action="update_risk_config", entity="risk", before=before, after=config.model_dump()
    )
    if context.engine is not None:
        context.engine.risk_engine.config = config
    return {"config": config.model_dump(), "message": "Risk settings saved."}
