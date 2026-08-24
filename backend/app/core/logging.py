"""Structured logging with automatic secret redaction.

Every log record passes through SecretRedactionFilter, which strips any value
registered in app.core.security. That is the last line of defence keeping API
secrets out of log files.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys
from typing import Any

from app.core.config import get_settings
from app.core.security import redact

_RESERVED = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}

_SENSITIVE_KEYS = {
    "api_secret",
    "apisecret",
    "secret",
    "password",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "signature",
    "private_key",
}


class SecretRedactionFilter(logging.Filter):
    """Removes known secrets and masks sensitive-looking fields."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Logging must never break the application, so failures are swallowed.
        with contextlib.suppress(Exception):
            record.msg = redact(str(record.msg))
        for key in list(record.__dict__.keys()):
            value = record.__dict__[key]
            if key.lower() in _SENSITIVE_KEYS:
                record.__dict__[key] = "***REDACTED***"
            elif isinstance(value, str) and key not in _RESERVED:
                record.__dict__[key] = redact(value)
        return True


class JsonFormatter(logging.Formatter):
    """Minimal dependency-free JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = str(value)
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human friendly formatter for local development."""

    def __init__(self) -> None:
        super().__init__(
            "%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s",
            "%H:%M:%S",
        )


_configured = False


def configure_logging(force: bool = False) -> None:
    """Install handlers on the root logger (idempotent)."""
    global _configured
    if _configured and not force:
        return

    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if settings.log_json else ConsoleFormatter())
    handler.addFilter(SecretRedactionFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, settings.log_level, logging.INFO))

    for noisy in ("uvicorn.access", "ccxt", "websockets.client", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger."""
    configure_logging()
    return logging.getLogger(name)
