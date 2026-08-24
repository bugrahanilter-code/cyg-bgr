"""Simulated exchange used by paper trading (and by the tests).

It consumes REAL market data but never sends anything to Binance. Fills are
priced with the same cost model as the backtester (taker fee + slippage) so
paper results stay comparable with backtest results.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from app.core.constants import MarketType, OrderSide, OrderStatus, OrderType
from app.core.exceptions import ExchangeError
from app.core.logging import get_logger
from app.core.time_utils import utcnow
from app.exchange.base import (
    AccountBalance,
    ExchangeGateway,
    ExchangeOrder,
    ExchangePosition,
    Ticker,
)
from app.exchange.filters import SymbolFilters, default_filters_for

logger = get_logger(__name__)

PriceProvider = Callable[[str], Ticker | None]
BalanceProvider = Callable[[], AccountBalance]
PositionProvider = Callable[[], list[ExchangePosition]]
FiltersProvider = Callable[[str], SymbolFilters]


class SimulatedGateway(ExchangeGateway):
    """Paper-trading gateway: real prices in, simulated fills out."""

    name = "simulated"
    supports_real_orders = False

    def __init__(
        self,
        *,
        price_provider: PriceProvider,
        balance_provider: BalanceProvider,
        position_provider: PositionProvider,
        filters_provider: FiltersProvider | None = None,
        data_gateway: ExchangeGateway | None = None,
        taker_fee_pct: float = 0.04,
        slippage_pct: float = 0.02,
        market_type: MarketType = MarketType.FUTURES,
    ) -> None:
        self._price_provider = price_provider
        self._balance_provider = balance_provider
        self._position_provider = position_provider
        self._filters_provider = filters_provider or default_filters_for
        self._data_gateway = data_gateway
        self.taker_fee_pct = taker_fee_pct
        self.slippage_pct = slippage_pct
        self.market_type = market_type
        self.submitted_orders: dict[str, ExchangeOrder] = {}

    # -- lifecycle ----------------------------------------------------------
    async def connect(self) -> None:
        if self._data_gateway is not None:
            await self._data_gateway.connect()

    async def close(self) -> None:
        if self._data_gateway is not None:
            await self._data_gateway.close()

    # -- market data (delegated to the real public data feed) ---------------
    async def fetch_ohlcv(
        self, symbol: str, timeframe: str, since_ms: int | None = None, limit: int = 500
    ) -> list[list[float]]:
        if self._data_gateway is None:
            raise ExchangeError("No market data source configured for the simulated gateway")
        return await self._data_gateway.fetch_ohlcv(symbol, timeframe, since_ms, limit)

    async def fetch_ticker(self, symbol: str) -> Ticker:
        ticker = self._price_provider(symbol)
        if ticker is not None:
            return ticker
        if self._data_gateway is None:
            raise ExchangeError(f"No price available for {symbol}")
        return await self._data_gateway.fetch_ticker(symbol)

    async def fetch_symbol_filters(self, symbol: str) -> SymbolFilters:
        return self._filters_provider(symbol)

    # -- account (local paper state) ----------------------------------------
    async def fetch_balance(self) -> AccountBalance:
        return self._balance_provider()

    async def fetch_positions(self, symbols: list[str] | None = None) -> list[ExchangePosition]:
        positions = self._position_provider()
        if symbols:
            wanted = {symbol.upper() for symbol in symbols}
            return [p for p in positions if p.symbol.upper() in wanted]
        return positions

    async def fetch_open_orders(self, symbol: str | None = None) -> list[ExchangeOrder]:
        # Paper trading never leaves resting orders on an exchange: stop-loss
        # and take-profit are evaluated locally against live prices.
        return []

    async def fetch_order(self, symbol: str, client_order_id: str) -> ExchangeOrder | None:
        return self.submitted_orders.get(client_order_id)

    # -- trading ------------------------------------------------------------
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
        ticker = await self.fetch_ticker(symbol)
        reference_price = price if (order_type == OrderType.LIMIT and price) else ticker.last
        if not reference_price or reference_price <= 0:
            raise ExchangeError(f"Cannot simulate a fill for {symbol}: no valid price")

        fill_price = self.apply_slippage(reference_price, side)
        filters = self._filters_provider(symbol)
        fill_price = filters.round_price(fill_price)
        notional = fill_price * quantity
        fee = notional * self.taker_fee_pct / 100.0

        order = ExchangeOrder(
            symbol=symbol,
            side=side,
            order_type=order_type,
            status=OrderStatus.FILLED,
            quantity=quantity,
            client_order_id=client_order_id or f"sim-{uuid.uuid4().hex[:16]}",
            exchange_order_id=f"SIM-{uuid.uuid4().hex[:12]}",
            price=price,
            stop_price=stop_price,
            filled_quantity=quantity,
            average_price=fill_price,
            fee=fee,
            reduce_only=reduce_only,
            created_at=utcnow(),
            raw={"simulated": True, "reference_price": reference_price},
        )
        self.submitted_orders[order.client_order_id or ""] = order
        return order

    async def cancel_order(self, symbol: str, client_order_id: str) -> bool:
        return self.submitted_orders.pop(client_order_id, None) is not None

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        return None

    # -- helpers ------------------------------------------------------------
    def apply_slippage(self, price: float, side: OrderSide) -> float:
        """Buys fill slightly above and sells slightly below the quoted price."""
        factor = self.slippage_pct / 100.0
        if side == OrderSide.BUY:
            return price * (1.0 + factor)
        return price * (1.0 - factor)
