"""Binance API credential storage.

Security contract:

* the secret is encrypted with Fernet before it touches the database
* the secret is never returned by any API endpoint
* only a masked preview of the API key is ever shown
* the plaintext secret only exists inside the exchange gateway
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import MarketType
from app.core.logging import get_logger
from app.core.security import decrypt_secret, encrypt_secret, mask_secret, register_sensitive_value
from app.core.time_utils import utcnow
from app.models.system import ApiCredential

logger = get_logger(__name__)


@dataclass(slots=True)
class ResolvedCredentials:
    """Decrypted credentials plus where they came from."""

    api_key: str
    api_secret: str
    market_type: MarketType
    testnet: bool
    source: str  # "database" or "environment" or "none"

    @property
    def is_present(self) -> bool:
        return bool(self.api_key and self.api_secret)


def get_active_credential(db: Session) -> ApiCredential | None:
    """The credential row currently marked active."""
    return db.execute(
        select(ApiCredential)
        .where(ApiCredential.is_active.is_(True))
        .order_by(ApiCredential.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def resolve_credentials(db: Session | None = None) -> ResolvedCredentials:
    """Return usable credentials: database first, environment as a fallback."""
    settings = get_settings()
    if db is not None:
        row = get_active_credential(db)
        if row is not None and row.api_key_encrypted and row.api_secret_encrypted:
            api_key = decrypt_secret(row.api_key_encrypted)
            api_secret = decrypt_secret(row.api_secret_encrypted)
            register_sensitive_value(api_secret)
            return ResolvedCredentials(
                api_key=api_key,
                api_secret=api_secret,
                market_type=MarketType(row.market_type),
                testnet=bool(row.testnet),
                source="database",
            )
    if settings.has_api_credentials:
        register_sensitive_value(settings.binance_api_secret)
        return ResolvedCredentials(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            market_type=settings.binance_market_type,
            testnet=settings.binance_testnet,
            source="environment",
        )
    return ResolvedCredentials(
        api_key="",
        api_secret="",
        market_type=settings.binance_market_type,
        testnet=settings.binance_testnet,
        source="none",
    )


def save_credentials(
    db: Session,
    *,
    api_key: str,
    api_secret: str,
    market_type: MarketType,
    testnet: bool = False,
    label: str = "default",
) -> ApiCredential:
    """Encrypt and store a credential pair, deactivating any previous one."""
    api_key = api_key.strip()
    api_secret = api_secret.strip()
    if not api_key or not api_secret:
        raise ValueError("Both the API key and the API secret are required")

    for existing in db.execute(select(ApiCredential)).scalars().all():
        existing.is_active = False

    row = ApiCredential(
        exchange="binance",
        label=label,
        api_key_encrypted=encrypt_secret(api_key),
        api_secret_encrypted=encrypt_secret(api_secret),
        api_key_masked=mask_secret(api_key),
        market_type=market_type.value,
        testnet=testnet,
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info(
        "Binance credentials stored",
        extra={"masked_key": row.api_key_masked, "testnet": testnet, "market": market_type.value},
    )
    return row


def delete_credentials(db: Session) -> int:
    """Remove every stored credential."""
    deleted = db.query(ApiCredential).delete()
    db.commit()
    logger.info("Binance credentials removed", extra={"count": deleted})
    return int(deleted or 0)


def record_test_result(
    db: Session, *, ok: bool, message: str, permissions: dict[str, Any] | None = None
) -> None:
    """Persist the outcome of a connection test."""
    row = get_active_credential(db)
    if row is None:
        return
    row.last_tested_at = utcnow()
    row.last_test_ok = ok
    row.last_test_message = message[:500]
    if permissions and permissions.get("withdrawals_enabled") is True:
        row.withdrawal_permission_warning = True
    db.commit()


def masked_view(db: Session) -> dict[str, Any]:
    """Safe representation for the settings page."""
    row = get_active_credential(db)
    settings = get_settings()
    if row is None:
        return {
            "configured": settings.has_api_credentials,
            "source": "environment" if settings.has_api_credentials else "none",
            "api_key_masked": mask_secret(settings.binance_api_key),
            "market_type": settings.binance_market_type.value,
            "testnet": settings.binance_testnet,
            "last_tested_at": None,
            "last_test_ok": False,
            "last_test_message": "",
            "withdrawal_permission_warning": False,
        }
    return {
        "configured": True,
        "source": "database",
        "api_key_masked": row.api_key_masked,
        "market_type": row.market_type,
        "testnet": bool(row.testnet),
        "last_tested_at": row.last_tested_at,
        "last_test_ok": bool(row.last_test_ok),
        "last_test_message": row.last_test_message,
        "withdrawal_permission_warning": bool(row.withdrawal_permission_warning),
    }
