"""Trading strategies.

Three independent, publicly documented systematic families:

1. trend_following   - time series momentum
2. breakout_donchian - channel breakout
3. mean_reversion    - statistical reversion (regime filtered)

None of them is guaranteed to be profitable. Each one has a documented set of
market conditions in which it is expected to lose money.
"""

from app.strategies.base import BaseStrategy
from app.strategies.breakout_donchian import DonchianBreakoutStrategy
from app.strategies.mean_reversion import MeanReversionStrategy
from app.strategies.registry import (
    available_keys,
    create_strategy,
    get_strategy_class,
    register_strategy,
    strategy_metadata,
)
from app.strategies.trend_following import TrendFollowingStrategy

__all__ = [
    "BaseStrategy",
    "DonchianBreakoutStrategy",
    "MeanReversionStrategy",
    "TrendFollowingStrategy",
    "available_keys",
    "create_strategy",
    "get_strategy_class",
    "register_strategy",
    "strategy_metadata",
]
