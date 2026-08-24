"""System control: health, engine lifecycle, emergency stop, event log."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import Context, DbSession
from app.core.constants import BotStatus, EmergencyStopLevel, ExitReason
from app.monitoring.health import build_health_report
from app.schemas.common import MessageResponse
from app.schemas.requests import EmergencyStopRequest
from app.schemas.responses import AuditLogOut, SystemEventOut
from app.services import bot_state_service, event_service

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health", summary="Component by component health")
def health(db: DbSession, context: Context) -> dict[str, Any]:
    return build_health_report(db, context.health(db))


@router.get("/status", summary="Short bot status")
def status(db: DbSession, context: Context) -> dict[str, Any]:
    state = bot_state_service.get_state(db)
    return {
        "status": state.status,
        "mode": state.mode,
        "emergency_stop_level": state.emergency_stop_level,
        "live_trading_confirmed": bool(state.live_trading_confirmed),
        "reconciliation_status": state.reconciliation_status,
        "last_heartbeat": state.last_heartbeat,
        "engine": context.engine.status() if context.engine else {"running": False},
    }


@router.post("/engine/start", response_model=MessageResponse, summary="Start the trading engine")
async def start_engine(db: DbSession, context: Context) -> MessageResponse:
    state = bot_state_service.get_state(db)
    if state.emergency_stop_level == EmergencyStopLevel.FULL_STOP.value:
        return MessageResponse(
            ok=False, message="Clear the emergency stop before starting the engine."
        )
    if context.engine is None:
        await context.startup()
    if context.engine is None:
        return MessageResponse(ok=False, message="Engine could not be created.")
    await context.engine.start()
    return MessageResponse(message="Trading engine started.")


@router.post("/engine/stop", response_model=MessageResponse, summary="Stop the trading engine")
async def stop_engine(context: Context) -> MessageResponse:
    if context.engine is not None:
        await context.engine.stop()
    return MessageResponse(message="Trading engine stopped. Open positions were left untouched.")


@router.post(
    "/emergency-stop",
    response_model=MessageResponse,
    summary="Arm or clear the emergency stop",
)
async def emergency_stop(
    payload: EmergencyStopRequest, db: DbSession, context: Context
) -> MessageResponse:
    bot_state_service.set_emergency_stop(db, payload.level, payload.reason)
    closed = 0
    if payload.level == EmergencyStopLevel.CLOSE_ALL_POSITIONS and context.engine is not None:
        closed = await context.engine.close_all_positions(db, ExitReason.EMERGENCY_STOP)
    if payload.level == EmergencyStopLevel.FULL_STOP and context.engine is not None:
        await context.engine.stop()
        bot_state_service.set_status(db, BotStatus.EMERGENCY_STOPPED)
    if payload.level == EmergencyStopLevel.NONE:
        bot_state_service.set_status(db, BotStatus.STOPPED)
    return MessageResponse(
        message=f"Emergency stop level set to {payload.level.value}.",
        details={"positions_closed": closed},
    )


@router.get("/events", response_model=list[SystemEventOut], summary="Recent system events")
def events(
    db: DbSession,
    limit: int = Query(default=100, ge=1, le=1000),
    severity: str | None = None,
    category: str | None = None,
) -> list[SystemEventOut]:
    rows = event_service.recent_events(db, limit=limit, severity=severity, category=category)
    return [SystemEventOut.model_validate(row) for row in rows]


@router.get("/audit", response_model=list[AuditLogOut], summary="Configuration audit trail")
def audit(db: DbSession, limit: int = Query(default=100, ge=1, le=1000)) -> list[AuditLogOut]:
    return [AuditLogOut.model_validate(row) for row in event_service.recent_audit(db, limit)]
