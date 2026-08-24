"""Persistent bot state: status, emergency stop and live-trading confirmation.

Everything here survives a restart, which is what makes a kill switch a real
kill switch: if the user stops the bot and the machine reboots, the bot does
NOT come back trading.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import (
    BotStatus,
    EmergencyStopLevel,
    EventSeverity,
    ReconciliationStatus,
    TradingMode,
)
from app.core.logging import get_logger
from app.core.time_utils import utcnow
from app.models.system import BotState
from app.services.event_service import audit, log_event

logger = get_logger(__name__)


def get_state(db: Session) -> BotState:
    """Return the singleton state row, creating it on first use."""
    state = db.execute(select(BotState).order_by(BotState.id.asc()).limit(1)).scalar_one_or_none()
    if state is None:
        state = BotState(
            status=BotStatus.STOPPED.value,
            mode=TradingMode.PAPER.value,
            emergency_stop_level=EmergencyStopLevel.NONE.value,
            live_trading_confirmed=False,
            reconciliation_status=ReconciliationStatus.NEVER_RUN.value,
        )
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def update_state(db: Session, **fields: Any) -> BotState:
    """Patch the state row."""
    state = get_state(db)
    for key, value in fields.items():
        if hasattr(state, key):
            setattr(state, key, value)
    db.commit()
    db.refresh(state)
    return state


def set_status(db: Session, status: BotStatus, error: str = "") -> BotState:
    fields: dict[str, Any] = {"status": status.value}
    if status == BotStatus.RUNNING:
        fields["started_at"] = utcnow()
        fields["last_error"] = ""
    if status == BotStatus.STOPPED:
        fields["stopped_at"] = utcnow()
    if error:
        fields["last_error"] = error[:1000]
    return update_state(db, **fields)


def heartbeat(db: Session) -> None:
    """Record that the engine loop is alive."""
    update_state(db, last_heartbeat=utcnow())


def set_emergency_stop(
    db: Session, level: EmergencyStopLevel, reason: str = "", actor: str = "dashboard"
) -> BotState:
    """Arm or clear the emergency stop."""
    previous = get_state(db)
    before = {
        "level": previous.emergency_stop_level,
        "status": previous.status,
    }
    fields: dict[str, Any] = {"emergency_stop_level": level.value, "halt_reason": reason}
    if level == EmergencyStopLevel.FULL_STOP:
        fields["status"] = BotStatus.EMERGENCY_STOPPED.value
    elif level != EmergencyStopLevel.NONE:
        fields["status"] = BotStatus.PAUSED.value
    state = update_state(db, **fields)

    log_event(
        db,
        message=f"Emergency stop set to {level.value}",
        category="emergency_stop",
        severity=EventSeverity.CRITICAL if level != EmergencyStopLevel.NONE else EventSeverity.INFO,
        details={"reason": reason, "actor": actor},
    )
    audit(
        db,
        action="emergency_stop",
        entity="bot_state",
        entity_id=str(state.id),
        before=before,
        after={"level": level.value, "status": state.status},
        actor=actor,
        note=reason,
    )
    return state


def confirm_live_trading(db: Session, confirmed: bool, actor: str = "dashboard") -> BotState:
    """Second half of the two-step live trading activation."""
    state = update_state(
        db,
        live_trading_confirmed=confirmed,
        live_confirmed_at=utcnow() if confirmed else None,
    )
    log_event(
        db,
        message=("Live trading confirmed by the user" if confirmed else "Live trading disabled"),
        category="live_trading",
        severity=EventSeverity.CRITICAL if confirmed else EventSeverity.INFO,
        details={"actor": actor},
    )
    audit(
        db,
        action="confirm_live_trading",
        entity="bot_state",
        entity_id=str(state.id),
        after={"live_trading_confirmed": confirmed},
        actor=actor,
    )
    return state


def set_reconciliation(
    db: Session, status: ReconciliationStatus, details: dict[str, Any] | None = None
) -> BotState:
    """Store the outcome of the latest reconciliation run."""
    return update_state(
        db,
        reconciliation_status=status.value,
        last_reconciliation_at=utcnow(),
        reconciliation_details=details or {},
    )


def is_trading_halted(state: BotState) -> bool:
    """True when no new position may be opened."""
    return state.emergency_stop_level != EmergencyStopLevel.NONE.value or state.status in (
        BotStatus.EMERGENCY_STOPPED.value,
        BotStatus.ERROR.value,
    )
