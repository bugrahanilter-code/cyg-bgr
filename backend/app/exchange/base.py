"""Exchange gateway abstraction.

Every module above this one talks to an ExchangeGateway, never to Binance
directly. That keeps the trading engine independent of the venue and makes it
trivial to plug the simulated gateway in for paper trading and tests.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.constants import OrderSide, OrderStatus, OrderType, PositionSide
from app.exchange.filters import SymbolFilters


@dataclass(slots=True)
class Ticker:
    """Latest price snapshot for one market."""

    symbol: str
    last: float
    bid: float | None = None
    ask: float | None = None
    timestamp: datetime | None = None

    @property
    def spread_pct(self) -> float | None:
        """Bid/ask spread as a percentage of the mid price."""
        if not self.bid or not self.ask or self.bid <= 0 or self.ask <= 0:
            return None
        mid = (self.bid + self.ask) / 2.0
        if mid <= 0:
            return None
        return (self.ask - self.bid) / mid * 100.0

    @property
    def mid(self) -> float:
        if self.bid and self.ask:
            return (self.bid + self.ask) / 2.0
        return self.last


@dataclass(slots=True)
class AccountBalance:
    """Account balance in the quote currency."""

    asset: str = "USDT"
    total: float = 0.0
    available: float = 0.0
    unrealized_pnl: float = 0.0

    @property
    def equity(self) -> float:
        return self.total + self.unrealized_pnl


@dataclass(slots=True)
class ExchangePosition:
    """A position as reported by the exchange."""

    symbol: str
    side: PositionSide
    quantity: float
    entry_price: float
    mark_price: float = 0.0
    unrealized_pnl: float = 0.0
    leverage: float = 1.0
    margin: float = 0.0
    liquidation_price: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExchangeOrder:
    """An order as reported by the exchange."""

    symbol: str
    side: OrderSide
    order_type: OrderType
    status: OrderStatus
    quantity: float
    client_order_id: str | None = None
    exchange_order_id: str | None = None
    price: float | None = None
    stop_price: float | None = None
    filled_quantity: float = 0.0
    average_price: float | None = None
    fee: float = 0.0
    reduce_only: bool = False
    created_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_filled(self) -> bool:
        return self.status == OrderStatus.FILLED


class ExchangeGateway(ABC):
    """Interface every exchange connector must implement."""

    name: str = "abstract"
    supports_real_orders: bool = False

    # -- lifecycle ----------------------------------------------------------
    @abstractmethod
    async def connect(self) -> None:
        """Prepare the connection (load markets, verify credentials)."""

    @abstractmethod
    async def close(self) -> None:
        """Release network resources."""

    # -- market data --------------------------------------------------------
    @abstractmethod
    async def fetch_ohlcv(
        self, symbol: str, timeframe: str, since_ms: int | None = None, limit: int = 500
    ) -> list[list[float]]:
        """Return raw OHLCV rows: [open_time_ms, open, high, low, close, volume]."""

    @abstractmethod
    async def fetch_ticker(self, symbol: str) -> Ticker:
        """Return the latest ticker for a market."""

    @abstractmethod
    async def fetch_symbol_filters(self, symbol: str) -> SymbolFilters:
        """Return the trading rules for a market."""

    # -- account ------------------------------------------------------------
    @abstractmethod
    async def fetch_balance(self) -> AccountBalance:
        """Return the account balance in the quote currency."""

    @abstractmethod
    async def fetch_positions(self, symbols: list[str] | None = None) -> list[ExchangePosition]:
        """Return every non-zero position."""

    @abstractmethod
    async def fetch_open_orders(self, symbol: str | None = None) -> list[ExchangeOrder]:
        """Return every open order."""

    @abstractmethod
    async def fetch_order(self, symbol: str, client_order_id: str) -> ExchangeOrder | None:
        """Return one order by its client order id, or None when unknown."""

    # -- trading ------------------------------------------------------------
    @abstractmethod
    async def create_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        reduce_only: bool = False,
        client_order_id: str | None = None,
    ) -> ExchangeOrder:
        """Submit an order."""

    @abstractmethod
    async def cancel_order(self, symbol: str, client_order_id: str) -> bool:
        """Cancel an order. Returns True when the exchange confirmed."""

    @abstractmethod
    async def set_leverage(self, symbol: str, leverage: int) -> None:
        """Set the leverage for a futures market (no-op on spot)."""
