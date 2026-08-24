"""Deterministic client order ids.

The same logical decision always produces the same client order id. If a
network timeout makes the platform retry, or if the process restarts in the
middle of an order, the exchange sees a duplicate id and refuses to open a
second position. This is the core protection against double execution.
"""

from __future__ import annotations

import hashlib
import re

#: Binance accepts up to 36 characters from this alphabet.
_ALLOWED = re.compile(r"[^A-Za-z0-9_:./-]")
PREFIX = "ctp"


def _slug(text: str, length: int = 6) -> str:
    cleaned = _ALLOWED.sub("", text.replace("/", ""))
    return cleaned[:length].lower()


def build_client_order_id(
    *,
    mode: str,
    symbol: str,
    strategy: str,
    candle_open_time: int,
    side: str,
    purpose: str = "entry",
    nonce: str = "",
) -> str:
    """Return a deterministic, exchange-safe client order id."""
    raw = f"{mode}|{symbol}|{strategy}|{candle_open_time}|{side}|{purpose}|{nonce}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    identifier = f"{PREFIX}-{_slug(purpose, 3)}-{_slug(symbol, 6)}-{digest}"
    return identifier[:36]


def is_duplicate_error(message: str) -> bool:
    """Detect the exchange error that means "this order id already exists"."""
    lowered = (message or "").lower()
    return "duplicate" in lowered or "-4015" in lowered or "clientorderid" in lowered
