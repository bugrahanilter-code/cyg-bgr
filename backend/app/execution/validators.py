"""Pre-flight order validation.

Every order is validated locally before it is sent. A rejected order costs
time and can leave the platform in an unclear state, so the cheap checks are
always done first.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.constants import OrderType
from app.exchange.filters import SymbolFilters


@dataclass(slots=True)
class OrderValidation:
    """Result of validating one order request."""

    valid: bool = True
    errors: list[str] = field(default_factory=list)
    quantity: float = 0.0
    price: float | None = None
    stop_price: float | None = None

    def fail(self, message: str) -> None:
        self.valid = False
        self.errors.append(message)


def validate_order(
    *,
    symbol: str,
    quantity: float,
    price: float | None,
    stop_price: float | None,
    order_type: OrderType,
    filters: SymbolFilters,
    reference_price: float | None = None,
    leverage: float = 1.0,
    max_leverage: int = 125,
) -> OrderValidation:
    """Round the order to exchange precision and check every trading rule."""
    result = OrderValidation()

    if not symbol:
        result.fail("Symbol is missing")
    if quantity is None or quantity <= 0:
        result.fail("Quantity must be greater than zero")
        return result

    rounded_quantity = filters.round_quantity(quantity)
    result.quantity = rounded_quantity
    if not filters.is_valid_quantity(rounded_quantity):
        result.fail(
            f"Quantity {rounded_quantity} is below the minimum {filters.min_quantity} for {symbol}"
        )

    if price is not None:
        result.price = filters.round_price(price)
        if result.price <= 0:
            result.fail("Price must be greater than zero")
    if stop_price is not None:
        result.stop_price = filters.round_price(stop_price)
        if result.stop_price <= 0:
            result.fail("Stop price must be greater than zero")

    if order_type == OrderType.LIMIT and result.price is None:
        result.fail("A limit order requires a price")
    if order_type in (OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET) and result.stop_price is None:
        result.fail("A conditional order requires a stop price")

    notional_reference = result.price or reference_price
    if notional_reference and not filters.is_valid_notional(rounded_quantity, notional_reference):
        result.fail(
            f"Order value {rounded_quantity * notional_reference:.2f} is below the exchange "
            f"minimum {filters.min_notional}"
        )

    if leverage < 1:
        result.fail("Leverage must be at least 1")
    if leverage > max_leverage or leverage > filters.max_leverage:
        result.fail(
            f"Leverage {leverage} exceeds the maximum allowed "
            f"({min(max_leverage, filters.max_leverage)})"
        )
    return result
