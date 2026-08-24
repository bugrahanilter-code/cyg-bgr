"""System events and audit trail."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import EventSeverity
from app.core.logging import get_logger
from app.models.system import AuditLog, SystemEvent

logger = get_logger(__name__)

_LOG_METHODS = {
    EventSeverity.DEBUG: logger.debug,
    EventSeverity.INFO: logger.info,
    EventSeverity.WARNING: logger.warning,
    EventSeverity.ERROR: logger.error,
    EventSeverity.CRITICAL: logger.critical,
}


def log_event(
    db: Session,
    *,
    message: str,
    category: str = "system",
    severity: EventSeverity = EventSeverity.INFO,
    details: dict[str, Any] | None = None,
    mode: str = "",
    symbol: str = "",
) -> SystemEvent:
    """Write a structured event to the database and to the log stream."""
    event = SystemEvent(
        severity=severity.value,
        category=category,
        message=message,
        details=details or {},
        mode=mode,
        symbol=symbol,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    _LOG_METHODS.get(severity, logger.info)(
        message, extra={"category": category, "mode": mode, "symbol": symbol}
    )
    return event


def recent_events(
    db: Session,
    limit: int = 100,
    severity: str | None = None,
    category: str | None = None,
) -> list[SystemEvent]:
    """Most recent events, newest first."""
    query = select(SystemEvent).order_by(SystemEvent.id.desc()).limit(min(limit, 1000))
    if severity:
        query = query.where(SystemEvent.severity == severity.upper())
    if category:
        query = query.where(SystemEvent.category == category)
    return list(db.execute(query).scalars().all())


def audit(
    db: Session,
    *,
    action: str,
    entity: str = "",
    entity_id: str = "",
    before: dict | None = None,
    after: dict | None = None,
    actor: str = "dashboard",
    note: str = "",
) -> AuditLog:
    """Record who changed what."""
    entry = AuditLog(
        actor=actor,
        action=action,
        entity=entity,
        entity_id=str(entity_id),
        before=before or {},
        after=after or {},
        note=note,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def recent_audit(db: Session, limit: int = 100) -> list[AuditLog]:
    return list(
        db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000)))
        .scalars()
        .all()
    )
