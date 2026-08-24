"""Deterministic exchange mock so the tests never touch the network."""

from __future__ import annotations

import uuid

from app.core.constants import MarketType, OrderSide, OrderStatus, OrderType, PositionSide
from app.core.time_utils import utcnow
from app.exchange.base import AccountBalance, ExchangeGateway, ExchangeOrder, ExchangePosition, Ticker
from app.exchange.filters import SymbolFilters, default_filters_for


class MockGateway(ExchangeGateway):
    """In-memory exchange with fully predictable behaviour."""

    name = "mock"
    supports_real_orders = True

    def __init__(
        self,
        price: float = 30_000.0,
        balance: float = 10_000.0,
        market_type: MarketType = MarketType.FUTURES,
        fail_orders: bool = False,
    ) -> None:
        self.prices: dict[str, float] = {}
        self.default_price = price
        self.balance = balance
        self.market_type = market_type
        self.fail_orders = fail_orders
        self.orders: dict[str, ExchangeOrder] = {}
        self.positions: list[ExchangePosition] = []
        self.leverage_calls: list[tuple[str, int]] = []
        self.create_calls = 0
        self.connected = False

    # -- lifecycle ---------------------------------------------------------
    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.connected = False

    # -- market data -------------------------------------------------------
    def set_price(self, symbol: str, price: float) -> None:
        self.prices[symbol.upper()] = price

    def price_of(self, symbol: str) -> float:
        return self.prices.get(symbol.upper(), self.default_price)

    async def fetch_ohlcv(self, symbol, timeframe, since_ms=None, limit=500):
        price = self.price_of(symbol)
        start = since_ms or 1_700_000_000_000
        step = 900_000
        return [
            [start + index * step, price, price * 1.001, price * 0.999, price, 100.0]
            for index in range(min(limit, 10))
        ]

    async def fetch_ticker(self, symbol: str) -> Ticker:
        price = self.price_of(symbol)
        return Ticker(
            symbol=symbol.upper(),
            last=price,
            bid=price * 0.9999,
            ask=price * 1.0001,
            timestamp=utcnow(),
        )

    async def fetch_symbol_filters(self, symbol: str) -> SymbolFilters:
        return default_filters_for(symbol)

    # -- account -----------------------------------------------------------
    async def fetch_balance(self) -> AccountBalance:
        return AccountBalance(
            asset="USDT", total=self.balance, available=self.balance, unrealized_pnl=0.0
        )

    async def fetch_positions(self, symbols=None) -> list[ExchangePosition]:
        if symbols:
            wanted = {symbol.upper() for symbol in symbols}
            return [p for p in self.positions if p.symbol.upper() in wanted]
        return list(self.positions)

    async def fetch_open_orders(self, symbol=None) -> list[ExchangeOrder]:
        return [
            order for order in self.orders.values() if order.status in (OrderStatus.NEW,)
        ]

    async def fetch_order(self, symbol: str, client_order_id: str) -> ExchangeOrder | None:
        return self.orders.get(client_order_id)

    # -- trading -----------------------------------------------------------
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
        self.create_calls += 1
        if self.fail_orders:
            raise RuntimeError("Simulated exchange failure")
        if client_order_id and client_order_id in self.orders:
            raise RuntimeError("Duplicate clientOrderId")

        fill_price = price if price else self.price_of(symbol)
        status = (
            OrderStatus.FILLED
            if order_type == OrderType.MARKET
            else OrderStatus.NEW
        )
        order = ExchangeOrder(
            symbol=symbol.upper(),
            side=side,
            order_type=order_type,
            status=status,
            quantity=quantity,
            client_order_id=client_order_id or uuid.uuid4().hex[:12],
            exchange_order_id=uuid.uuid4().hex[:10],
            price=price,
            stop_price=stop_price,
            filled_quantity=quantity if status == OrderStatus.FILLED else 0.0,
            average_price=fill_price if status == OrderStatus.FILLED else None,
            fee=fill_price * quantity * 0.0004 if status == OrderStatus.FILLED else 0.0,
            reduce_only=reduce_only,
            created_at=utcnow(),
            raw={"mock": True},
        )
        self.orders[order.client_order_id or ""] = order

        if status == OrderStatus.FILLED and not reduce_only:
            self.positions.append(
                ExchangePosition(
                    symbol=symbol.upper(),
                    side=PositionSide.LONG if side == OrderSide.BUY else PositionSide.SHORT,
                    quantity=quantity,
                    entry_price=fill_price,
                    mark_price=fill_price,
                    leverage=1.0,
                )
            )
        elif status == OrderStatus.FILLED and reduce_only:
            self.positions = [p for p in self.positions if p.symbol != symbol.upper()]
        return order

    async def cancel_order(self, symbol: str, client_order_id: str) -> bool:
        order = self.orders.get(client_order_id)
        if order is None:
            return False
        order.status = OrderStatus.CANCELED
        return True

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        self.leverage_calls.append((symbol, leverage))
