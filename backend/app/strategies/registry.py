"""Strategy registry.

Adding a fourth strategy is a two-line change: implement BaseStrategy and call
register_strategy(). Nothing else in the platform needs to know about it.
"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import NotFoundError
from app.strategies.base import BaseStrategy
from app.strategies.breakout_donchian import DonchianBreakoutStrategy
from app.strategies.mean_reversion import MeanReversionStrategy
from app.strategies.trend_following import TrendFollowingStrategy

_REGISTRY: dict[str, type[BaseStrategy]] = {}


def register_strategy(strategy_class: type[BaseStrategy]) -> type[BaseStrategy]:
    """Register a strategy implementation under its key."""
    _REGISTRY[strategy_class.key] = strategy_class
    return strategy_class


for _strategy in (TrendFollowingStrategy, DonchianBreakoutStrategy, MeanReversionStrategy):
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
            "description": cls.description,
            "default_params": cls.default_params(),
            "param_schema": cls.param_schema(),
        }
        for cls in _REGISTRY.values()
    ]
