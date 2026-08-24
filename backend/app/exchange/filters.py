"""Exchange trading rules (tick size, step size, minimum notional).

Getting these wrong is one of the most common causes of rejected orders, so
the rounding logic lives in one tested place and is applied by the Execution
Engine before every single order.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SymbolFilters:
    """Normalised trading rules for one market."""

    symbol: str
    tick_size: float = 0.01
    step_size: float = 0.001
    min_quantity: float = 0.0
    min_notional: float = 5.0
    price_precision: int = 2
    quantity_precision: int = 3
    max_leverage: int = 20
    maintenance_margin_rate: float = 0.005

    def round_price(self, price: float) -> float:
        """Round a price down/up to the nearest valid tick."""
        return round_to_increment(price, self.tick_size, self.price_precision)

    def round_quantity(self, quantity: float) -> float:
        """Round a quantity DOWN to the nearest valid lot size.

        Rounding down is deliberate: it can never turn an affordable order into
        one that exceeds the available margin.
        """
        return floor_to_increment(quantity, self.step_size, self.quantity_precision)

    def is_valid_quantity(self, quantity: float) -> bool:
        return quantity > 0 and quantity + 1e-12 >= self.min_quantity

    def is_valid_notional(self, quantity: float, price: float) -> bool:
        return quantity * price + 1e-9 >= self.min_notional


def _decimals_for(increment: float, fallback: int) -> int:
    if increment <= 0:
        return fallback
    text = f"{increment:.12f}".rstrip("0")
    if "." not in text:
        return 0
    return max(0, len(text.split(".")[1]))


def round_to_increment(value: float, increment: float, precision: int = 8) -> float:
    """Round a value to the nearest multiple of increment."""
    if increment <= 0:
        return round(value, precision)
    steps = round(value / increment)
    return round(steps * increment, _decimals_for(increment, precision))


def floor_to_increment(value: float, increment: float, precision: int = 8) -> float:
    """Round a value DOWN to a multiple of increment."""
    if increment <= 0:
        return round(value, precision)
    steps = math.floor((value + 1e-12) / increment)
    return round(steps * increment, _decimals_for(increment, precision))


def ceil_to_increment(value: float, increment: float, precision: int = 8) -> float:
    """Round a value UP to a multiple of increment."""
    if increment <= 0:
        return round(value, precision)
    steps = math.ceil((value - 1e-12) / increment)
    return round(steps * increment, _decimals_for(increment, precision))


DEFAULT_FILTERS: dict[str, SymbolFilters] = {
    "BTC/USDT": SymbolFilters(
        symbol="BTC/USDT",
        tick_size=0.1,
        step_size=0.001,
        min_quantity=0.001,
        min_notional=5.0,
        price_precision=1,
        quantity_precision=3,
        max_leverage=125,
        maintenance_margin_rate=0.004,
    ),
    "ETH/USDT": SymbolFilters(
        symbol="ETH/USDT",
        tick_size=0.01,
        step_size=0.001,
        min_quantity=0.001,
        min_notional=5.0,
        price_precision=2,
        quantity_precision=3,
        max_leverage=100,
        maintenance_margin_rate=0.005,
    ),
}


def default_filters_for(symbol: str) -> SymbolFilters:
    """Conservative fallback used until the real filters are downloaded.

    These are only defaults; the real values are fetched from the exchange and
    stored in the symbols table as soon as a connection is available.
    """
    known = DEFAULT_FILTERS.get(symbol.upper())
    if known is not None:
        return known
    return SymbolFilters(symbol=symbol.upper())
