"""System state, settings, audit trail and encrypted API credentials."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import (
    BotStatus,
    EmergencyStopLevel,
    EventSeverity,
    ReconciliationStatus,
    TradingMode,
)
from app.database.base import Base, TimestampMixin


class AppSetting(TimestampMixin, Base):
    """Key/value store for runtime configuration edited from the dashboard.

    Secrets are NEVER stored here: they live in api_credentials, encrypted.
    """

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str] = mapped_column(Text, default="")


class ApiCredential(TimestampMixin, Base):
    """Exchange API credentials, encrypted at rest.

    Only the masked key is ever returned by the API. The secret never leaves
    the backend process in plaintext.
    """

    __tablename__ = "api_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exchange: Mapped[str] = mapped_column(String(32), default="binance")
    label: Mapped[str] = mapped_column(String(64), default="default")
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    api_secret_encrypted: Mapped[str] = mapped_column(Text, default="")
    api_key_masked: Mapped[str] = mapped_column(String(64), default="")
    market_type: Mapped[str] = mapped_column(String(16), default="futures")
    testnet: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_test_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    last_test_message: Mapped[str] = mapped_column(Text, default="")
    #: Set when the exchange reports that withdrawals are enabled on the key.
    withdrawal_permission_warning: Mapped[bool] = mapped_column(Boolean, default=False)


class BotState(TimestampMixin, Base):
    """Singleton row holding the live state of the trading engine.

    Persisting this makes restart recovery possible: an emergency stop or a
    halted state survives a crash or a machine reboot.
    """

    __tablename__ = "bot_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default=BotStatus.STOPPED.value)
    mode: Mapped[str] = mapped_column(String(16), default=TradingMode.PAPER.value)
    emergency_stop_level: Mapped[str] = mapped_column(
        String(32), default=EmergencyStopLevel.NONE.value
    )
    #: Two-step live trading activation. Both this flag and the environment
    #: switch must be true before a real order can be sent.
    live_trading_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    live_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_cycle_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    reconciliation_status: Mapped[str] = mapped_column(
        String(24), default=ReconciliationStatus.NEVER_RUN.value
    )
    last_reconciliation_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reconciliation_details: Mapped[dict] = mapped_column(JSON, default=dict)

    halt_reason: Mapped[str] = mapped_column(Text, default="")
    last_error: Mapped[str] = mapped_column(Text, default="")


class SystemEvent(TimestampMixin, Base):
    """Structured, queryable audit of everything important the system did."""

    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    severity: Mapped[str] = mapped_column(String(16), default=EventSeverity.INFO.value, index=True)
    category: Mapped[str] = mapped_column(String(48), default="system", index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(16), default="")
    symbol: Mapped[str] = mapped_column(String(32), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditLog(TimestampMixin, Base):
    """Who changed what (dashboard actions, configuration changes)."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(64), default="dashboard")
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity: Mapped[str] = mapped_column(String(64), default="")
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    before: Mapped[dict] = mapped_column(JSON, default=dict)
    after: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str] = mapped_column(Text, default="")
