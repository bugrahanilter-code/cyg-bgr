"""System health aggregation for the monitoring page."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.constants import (
    BotStatus,
    ConnectionStatus,
    HealthStatus,
    ReconciliationStatus,
)
from app.core.time_utils import seconds_since, utcnow

HEARTBEAT_WARNING_SECONDS = 60.0
HEARTBEAT_CRITICAL_SECONDS = 180.0


def _component(name: str, status: HealthStatus, detail: str = "", **extra: Any) -> dict[str, Any]:
    payload = {"name": name, "status": status.value, "detail": detail}
    payload.update(extra)
    return payload


def build_health_report(db: Session, raw: dict[str, Any]) -> dict[str, Any]:
    """Translate the raw context health into a stable UI contract."""
    market = raw.get("market_data", {})
    engine = raw.get("engine", {})
    exchange = raw.get("exchange", {})
    reconciliation = raw.get("reconciliation", {})
    bot_state = raw.get("bot_state", {})
    database = raw.get("database", {})

    components: list[dict[str, Any]] = []

    market_status = HealthStatus(market.get("status", HealthStatus.UNKNOWN.value))
    components.append(
        _component(
            "Market Data",
            market_status,
            "Fiyatlar bayat" if market.get("stale") else "Fiyatlar güncel",
            data_age_seconds=market.get("data_age_seconds", {}),
        )
    )

    websocket_status = market.get("websocket_status", ConnectionStatus.DISCONNECTED.value)
    components.append(
        _component(
            "WebSocket",
            HealthStatus.OK
            if websocket_status == ConnectionStatus.CONNECTED.value
            else HealthStatus.DEGRADED,
            websocket_status,
            last_message=market.get("websocket_last_message"),
            reconnects=market.get("websocket_reconnects", 0),
        )
    )

    exchange_status = exchange.get("status", ConnectionStatus.DISCONNECTED.value)
    components.append(
        _component(
            "Binance API",
            HealthStatus.OK
            if exchange_status == ConnectionStatus.CONNECTED.value
            else HealthStatus.DEGRADED,
            exchange.get("error") or exchange_status,
            gateway=exchange.get("gateway"),
        )
    )

    components.append(
        _component(
            "Database",
            HealthStatus(database.get("status", HealthStatus.UNKNOWN.value)),
            str(database.get("dialect", "database")) + " connection",
        )
    )

    heartbeat_age = seconds_since(bot_state.get("last_heartbeat"))
    if not engine.get("running"):
        heartbeat_health = HealthStatus.DOWN
        heartbeat_detail = "Engine is not running"
    elif heartbeat_age is None or heartbeat_age > HEARTBEAT_CRITICAL_SECONDS:
        heartbeat_health = HealthStatus.DOWN
        heartbeat_detail = "No heartbeat"
    elif heartbeat_age > HEARTBEAT_WARNING_SECONDS:
        heartbeat_health = HealthStatus.DEGRADED
        heartbeat_detail = f"Last heartbeat {heartbeat_age:.0f}s ago"
    else:
        heartbeat_health = HealthStatus.OK
        heartbeat_detail = f"Last heartbeat {heartbeat_age:.0f}s ago"

    for name in ("Strategy Engine", "Risk Engine", "Execution Engine"):
        components.append(_component(name, heartbeat_health, heartbeat_detail))

    reconciliation_status = reconciliation.get("status", ReconciliationStatus.NEVER_RUN.value)
    if reconciliation_status == ReconciliationStatus.IN_SYNC.value:
        reconciliation_health = HealthStatus.OK
    elif reconciliation_status == ReconciliationStatus.NEVER_RUN.value:
        reconciliation_health = HealthStatus.DEGRADED
    else:
        reconciliation_health = HealthStatus.DOWN
    components.append(
        _component(
            "Reconciliation",
            reconciliation_health,
            reconciliation_status,
            last_run=reconciliation.get("last_run"),
        )
    )

    statuses = [component["status"] for component in components]
    if HealthStatus.DOWN.value in statuses:
        overall = HealthStatus.DOWN
    elif HealthStatus.DEGRADED.value in statuses:
        overall = HealthStatus.DEGRADED
    else:
        overall = HealthStatus.OK

    return {
        "overall": overall.value,
        "checked_at": utcnow(),
        "components": components,
        "bot_status": bot_state.get("status", BotStatus.STOPPED.value),
        "mode": bot_state.get("mode"),
        "emergency_stop_level": bot_state.get("emergency_stop_level"),
        "live_trading_confirmed": bot_state.get("live_trading_confirmed", False),
        "last_heartbeat": bot_state.get("last_heartbeat"),
        "last_market_data": market.get("websocket_last_message"),
        "engine": engine,
    }
