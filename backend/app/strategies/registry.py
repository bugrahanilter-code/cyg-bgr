"""Strategy registry.

Adding a fourth strategy is a two-line change: implement BaseStrategy and call
register_strategy(). Nothing else in the platform needs to know about it.
"""

from __future__ import annotations

from typing import Any

from app.core.constants import RISK_LEVEL_ORDER
from app.core.exceptions import NotFoundError
from app.strategies.adaptive_momentum import AdaptiveMomentumStrategy
from app.strategies.base import BaseStrategy
from app.strategies.breakout_donchian import DonchianBreakoutStrategy
from app.strategies.dual_momentum import DualMomentumStrategy
from app.strategies.golden_cross import GoldenCrossStrategy
from app.strategies.ichimoku_trend import IchimokuStrategy
from app.strategies.keltner_trend import KeltnerTrendStrategy
from app.strategies.macd_momentum import MacdMomentumStrategy
from app.strategies.mean_reversion import MeanReversionStrategy
from app.strategies.rsi_divergence import RsiDivergenceStrategy
from app.strategies.squeeze_momentum import SqueezeMomentumStrategy
from app.strategies.supertrend_follow import SupertrendStrategy
from app.strategies.trend_following import TrendFollowingStrategy
from app.strategies.volatility_breakout import VolatilityBreakoutStrategy
from app.strategies.vwap_pullback import VwapPullbackStrategy

_REGISTRY: dict[str, type[BaseStrategy]] = {}


def register_strategy(strategy_class: type[BaseStrategy]) -> type[BaseStrategy]:
    """Register a strategy implementation under its key."""
    _REGISTRY[strategy_class.key] = strategy_class
    return strategy_class


#: Every strategy that ships with the platform, grouped by risk level.
BUILTIN_STRATEGIES: tuple[type[BaseStrategy], ...] = (
    # Safe: few trades, wide stops, trend aligned, long-only by default
    GoldenCrossStrategy,
    DualMomentumStrategy,
    VwapPullbackStrategy,
    KeltnerTrendStrategy,
    # Medium: standard systematic families with filters
    TrendFollowingStrategy,
    DonchianBreakoutStrategy,
    MacdMomentumStrategy,
    AdaptiveMomentumStrategy,
    IchimokuStrategy,
    SupertrendStrategy,
    # Risky: counter-trend, high frequency or direction-agnostic entries
    MeanReversionStrategy,
    RsiDivergenceStrategy,
    VolatilityBreakoutStrategy,
    SqueezeMomentumStrategy,
)

for _strategy in BUILTIN_STRATEGIES:
    register_strategy(_strategy)


def available_keys() -> list[str]:
    """Keys of every registered strategy, in a stable order."""
    return list(_REGISTRY.keys())


def get_strategy_class(key: str) -> type[BaseStrategy]:
    """Look up a strategy class by key."""
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        raise NotFoundError(f"Unknown strategy: {key}") from exc


def create_strategy(key: str, params: dict[str, Any] | None = None) -> BaseStrategy:
    """Instantiate a strategy with the given (partial) parameters."""
    return get_strategy_class(key)(params)


def strategy_metadata() -> list[dict[str, Any]]:
    """Describe every strategy for the dashboard."""
    return [
        {
            "key": cls.key,
            "name": cls.name,
            "family": cls.family,
            "risk_level": cls.risk_level.value,
            "description": cls.description,
            "default_params": cls.default_params(),
            "param_schema": cls.param_schema(),
        }
        for cls in sorted(
            _REGISTRY.values(),
            key=lambda item: (RISK_LEVEL_ORDER.get(item.risk_level.value, 9), item.name),
        )
    ]
