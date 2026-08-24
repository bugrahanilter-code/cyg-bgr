"""Trading strategies.

Thirteen independent, publicly documented systematic families, grouped by how
aggressive they are:

* safe   - few trades, wide stops, trend aligned, long-only by default
* medium - standard systematic families with trend and strength filters
* risky  - counter-trend, high frequency or direction-agnostic entries

None of them is guaranteed to be profitable. Each one documents the market
conditions in which it is expected to lose money.
"""

from app.strategies.base import BaseStrategy
from app.strategies.registry import (
    BUILTIN_STRATEGIES,
    available_keys,
    create_strategy,
    get_strategy_class,
    register_strategy,
    strategy_metadata,
)

__all__ = [
    "BUILTIN_STRATEGIES",
    "BaseStrategy",
    "available_keys",
    "create_strategy",
    "get_strategy_class",
    "register_strategy",
    "strategy_metadata",
]
