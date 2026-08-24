"""Provider interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class MarketStats:
    """Context for one market, merged from one or more providers."""

    symbol: str
    source: str
    last_price: float | None = None
    change_24h_pct: float | None = None
    high_24h: float | None = None
    low_24h: float | None = None
    volume_24h: float | None = None
    #: Provider specific extras (technical rating, RSI, ATR, ...).
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "source": self.source,
            "last_price": self.last_price,
            "change_24h_pct": self.change_24h_pct,
            "high_24h": self.high_24h,
            "low_24h": self.low_24h,
            "volume_24h": self.volume_24h,
            **self.extra,
        }


@runtime_checkable
class MarketContextProvider(Protocol):
    """Anything that can describe markets without being the order gateway."""

    name: str

    async def fetch_context(self, symbols: list[str] | None = None) -> dict[str, MarketStats]:
        """Return context keyed by canonical symbol (``BTC/USDT``)."""
        ...
