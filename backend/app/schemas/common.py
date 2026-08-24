"""Shared response envelopes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.time_utils import utcnow


class MessageResponse(BaseModel):
    """Simple acknowledgement."""

    ok: bool = True
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Uniform error body returned by the exception handlers."""

    ok: bool = False
    code: str = "error"
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class Paginated(BaseModel):
    """Envelope for list endpoints."""

    items: list[Any] = Field(default_factory=list)
    total: int = 0
    limit: int = 100
    offset: int = 0


class TimestampedPayload(BaseModel):
    generated_at: datetime = Field(default_factory=utcnow)
    data: dict[str, Any] = Field(default_factory=dict)
