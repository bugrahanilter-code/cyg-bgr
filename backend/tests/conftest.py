"""Test configuration.

Every test runs against an in-memory SQLite database and never touches the
network: the Binance gateway is replaced by a deterministic mock.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-not-used-in-production")
os.environ.setdefault("ENABLE_BACKGROUND_ENGINE", "false")
os.environ.setdefault("AUTO_CREATE_TABLES", "true")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("PAPER_STARTING_BALANCE", "10000")
os.environ.setdefault("LIVE_TRADING_ENABLED", "false")

import numpy as np
import pandas as pd
import pytest

from app.database.base import Base
from app.database.init_db import init_database
from app.database.session import SessionLocal, engine


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    """Create the schema and the seed data once per test session."""
    Base.metadata.create_all(bind=engine)
    init_database(create=True)


@pytest.fixture
def db():
    """A database session per test."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _frame_from_prices(prices: np.ndarray, start_ms: int, step_ms: int) -> pd.DataFrame:
    """Build a canonical OHLCV frame from a close price series.

    Volume varies with the size of each candle, the way it does in a real
    market. A constant volume would silently disable every volume filter and
    make the tests pass for the wrong reason.
    """
    rng = np.random.default_rng(7)
    highs = prices * (1.0 + np.abs(rng.normal(0, 0.001, len(prices))))
    lows = prices * (1.0 - np.abs(rng.normal(0, 0.001, len(prices))))
    opens = np.concatenate([[prices[0]], prices[:-1]])

    moves = np.abs(np.concatenate([[0.0], np.diff(prices)])) / np.maximum(prices, 1e-9)
    volume = 1000.0 * (1.0 + 40.0 * moves) * rng.lognormal(0.0, 0.35, len(prices))

    return pd.DataFrame(
        {
            "open_time": [start_ms + index * step_ms for index in range(len(prices))],
            "open": opens,
            "high": np.maximum.reduce([highs, opens, prices]),
            "low": np.minimum.reduce([lows, opens, prices]),
            "close": prices,
            "volume": volume,
        }
    )


@pytest.fixture
def trending_frame() -> pd.DataFrame:
    """A clean up-trend with small noise (900 candles of 15 minutes)."""
    rng = np.random.default_rng(42)
    steps = 900
    drift = np.linspace(0.0, 0.55, steps)
    noise = rng.normal(0.0, 0.004, steps).cumsum() * 0.15
    prices = 30_000.0 * np.exp(drift + noise)
    return _frame_from_prices(prices, 1_700_000_000_000, 900_000)


@pytest.fixture
def ranging_frame() -> pd.DataFrame:
    """A sideways, mean-reverting market."""
    rng = np.random.default_rng(4)
    steps = 900
    base = 2_000.0
    oscillation = np.sin(np.linspace(0, 24 * np.pi, steps)) * 40.0
    noise = rng.normal(0.0, 3.0, steps)
    prices = base + oscillation + noise
    return _frame_from_prices(prices, 1_700_000_000_000, 900_000)


@pytest.fixture
def volatile_frame() -> pd.DataFrame:
    """A calm market that ends in a violent volatility spike.

    The regime engine measures volatility RELATIVE to a market's own recent
    history, so a uniformly wild series is not "extreme" - a sudden expansion
    after a quiet period is. This fixture reproduces that realistic case.
    """
    rng = np.random.default_rng(99)
    calm_steps = 870
    spike_steps = 30
    calm = rng.normal(0.0, 0.0015, calm_steps)
    spike = rng.normal(0.0, 0.05, spike_steps)
    returns = np.concatenate([calm, spike])
    prices = 1_000.0 * np.exp(np.cumsum(returns))
    return _frame_from_prices(prices, 1_700_000_000_000, 900_000)


@pytest.fixture
def mixed_frame() -> pd.DataFrame:
    """A market that goes through every regime, like a real one does.

    Down-trend, then a quiet range, then a strong up-trend, then a volatility
    spike, then a drift back down. A single-regime fixture would let a broken
    strategy look "conservative" simply because its setup never appeared.
    """
    rng = np.random.default_rng(2024)
    segments = [
        rng.normal(-0.0010, 0.0035, 320),  # downtrend
        rng.normal(0.0000, 0.0012, 320),  # quiet range
        rng.normal(0.0016, 0.0030, 400),  # strong uptrend
        rng.normal(0.0000, 0.0180, 90),  # volatility spike
        rng.normal(-0.0008, 0.0040, 270),  # drift back down
    ]
    prices = 30_000.0 * np.exp(np.cumsum(np.concatenate(segments)))
    return _frame_from_prices(prices, 1_700_000_000_000, 900_000)
