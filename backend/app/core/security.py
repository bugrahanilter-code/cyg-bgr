"""Secret handling.

Rules enforced by this module:

* API secrets are NEVER stored in plaintext in the database.
* API secrets are NEVER returned to the frontend (only a masked preview).
* Every secret that passes through here is registered in a redaction registry
  so the logging layer can scrub it if it ever reaches a log record.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import secrets
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.exceptions import ConfigurationError

_lock = threading.Lock()
_SENSITIVE_VALUES: set[str] = set()
_MIN_REDACTABLE_LENGTH = 6


def register_sensitive_value(value: str | None) -> None:
    """Remember a value so the logging filter can redact it."""
    if not value or len(value) < _MIN_REDACTABLE_LENGTH:
        return
    with _lock:
        _SENSITIVE_VALUES.add(value)


def sensitive_values() -> tuple[str, ...]:
    """Return a snapshot of every registered secret."""
    with _lock:
        return tuple(_SENSITIVE_VALUES)


def mask_secret(value: str | None, *, keep: int = 4) -> str:
    """Return a display-safe preview such as abcd...wxyz."""
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}...{value[-keep:]}"


def _resolve_key_material() -> str:
    """Return the raw key material used to derive the encryption key.

    If SECRET_KEY is not configured a random key is generated once and stored
    inside the data directory with restrictive permissions. This keeps the
    platform usable for non-technical users without ever shipping a hard-coded
    default key.
    """
    settings = get_settings()
    if settings.secret_key:
        return settings.secret_key

    key_file: Path = settings.data_path / ".secret_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()

    generated = secrets.token_urlsafe(48)
    key_file.write_text(generated, encoding="utf-8")
    # chmod is POSIX only and is silently ignored on Windows.
    with contextlib.suppress(OSError):
        key_file.chmod(0o600)
    return generated


def _fernet() -> Fernet:
    material = _resolve_key_material()
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret for storage at rest."""
    if not plaintext:
        return ""
    register_sensitive_value(plaintext)
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    """Decrypt a secret previously produced by encrypt_secret."""
    if not token:
        return ""
    try:
        plaintext = _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ConfigurationError(
            "Stored API credentials could not be decrypted. "
            "The SECRET_KEY probably changed, please re-enter your API keys."
        ) from exc
    register_sensitive_value(plaintext)
    return plaintext


def redact(text: str) -> str:
    """Replace every known secret inside text with a placeholder."""
    result = text
    for value in sensitive_values():
        if value and value in result:
            result = result.replace(value, "***REDACTED***")
    return result
