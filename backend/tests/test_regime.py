"""Market Regime Engine tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.constants import TrendRegime, VolatilityRegime
from app.regime.engine import MarketRegimeEngine


def _frame(returns: np.ndarray, start_price: float = 30_000.0) -> pd.DataFrame:
    prices = start_price * np.exp(np.cumsum(returns))
    opens = np.concatenate([[prices[0]], prices[:-1]])
    return pd.DataFrame(
        {
            "open_time": [1_700_000_000_000 + index * 900_000 for index in range(len(prices))],
            "open": opens,
            "high": np.maximum(opens, prices) * 1.0005,
            "low": np.minimum(opens, prices) * 0.9995,
            "close": prices,
            "volume": np.full(len(prices), 1000.0),
        }
    )


def test_ordinary_market_is_not_extreme() -> None:
    """A quiet market must never be labelled EXTREME.

    Regression test: ranking volatility by percentile alone reported EXTREME
    during completely ordinary conditions, because inside any rolling window
    some bar is always at the top percentile. That permanently blocked trading.
    """
    rng = np.random.default_rng(3)
    frame = _frame(rng.normal(0.0, 0.002, 600))
    result = MarketRegimeEngine().classify(frame)

    assert result.volatility != VolatilityRegime.EXTREME
    assert result.atr_pct is not None and result.atr_pct < 2.0
    assert result.regime.value != "EXTREME_VOLATILITY"


def test_genuine_volatility_spike_is_extreme() -> None:
    """A real expansion after a calm period must be detected."""
    rng = np.random.default_rng(5)
    calm = rng.normal(0.0, 0.001, 570)
    spike = rng.normal(0.0, 0.05, 30)
    frame = _frame(np.concatenate([calm, spike]))
    result = MarketRegimeEngine().classify(frame)

    assert result.volatility in (VolatilityRegime.HIGH, VolatilityRegime.EXTREME)
    assert result.volatility_ratio is not None and result.volatility_ratio > 1.5


def test_trend_is_detected_in_a_strong_uptrend() -> None:
    rng = np.random.default_rng(11)
    returns = rng.normal(0.0015, 0.001, 600)
    result = MarketRegimeEngine().classify(_frame(returns))

    assert result.trend == TrendRegime.TRENDING_UP
    assert result.adx is not None and result.adx > 20


def test_empty_frame_is_unknown() -> None:
    result = MarketRegimeEngine().classify(pd.DataFrame())
    assert result.volatility == VolatilityRegime.UNKNOWN
    assert result.trend == TrendRegime.UNKNOWN
