"""Indicator unit tests, including explicit look-ahead bias checks."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.indicators import (
    atr,
    bollinger_bands,
    donchian_channel,
    ema,
    rsi,
    sma,
    true_range,
    zscore,
)


@pytest.fixture
def prices() -> pd.Series:
    return pd.Series([float(value) for value in range(1, 101)])


def test_sma_matches_manual_average(prices: pd.Series) -> None:
    result = sma(prices, 5)
    assert np.isnan(result.iloc[3])
    assert result.iloc[4] == pytest.approx(3.0)
    assert result.iloc[-1] == pytest.approx(98.0)


def test_ema_reacts_faster_than_sma(prices: pd.Series) -> None:
    fast = ema(prices, 10).iloc[-1]
    slow = sma(prices, 10).iloc[-1]
    assert fast > slow


def test_true_range_uses_previous_close() -> None:
    high = pd.Series([10.0, 12.0])
    low = pd.Series([9.0, 11.0])
    close = pd.Series([9.5, 11.5])
    result = true_range(high, low, close)
    assert result.iloc[1] == pytest.approx(2.5)


def test_atr_is_positive(trending_frame: pd.DataFrame) -> None:
    values = atr(trending_frame["high"], trending_frame["low"], trending_frame["close"], 14)
    assert values.dropna().gt(0).all()


def test_rsi_bounds(trending_frame: pd.DataFrame) -> None:
    values = rsi(trending_frame["close"], 14).dropna()
    assert values.between(0, 100).all()
    # A pure uptrend should read as strong.
    assert values.iloc[-1] > 45


def test_bollinger_bands_ordering(ranging_frame: pd.DataFrame) -> None:
    bands = bollinger_bands(ranging_frame["close"], 20, 2.0).dropna()
    assert (bands["bb_upper"] >= bands["bb_middle"]).all()
    assert (bands["bb_middle"] >= bands["bb_lower"]).all()


def test_zscore_is_centred(ranging_frame: pd.DataFrame) -> None:
    values = zscore(ranging_frame["close"], 20).dropna()
    assert abs(values.mean()) < 1.0


def test_donchian_channel_has_no_lookahead() -> None:
    """The channel of bar t must not contain the high/low of bar t."""
    high = pd.Series([1.0, 2.0, 3.0, 10.0, 4.0])
    low = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0])
    channel = donchian_channel(high, low, period=3, shift=1)
    # Bar 3 spikes to 10; the level used to test bar 3 comes from bars 0-2.
    assert channel["donchian_upper"].iloc[3] == pytest.approx(3.0)
    # Only the NEXT bar may know about the spike.
    assert channel["donchian_upper"].iloc[4] == pytest.approx(10.0)


def test_indicators_are_causal(trending_frame: pd.DataFrame) -> None:
    """Recomputing on a truncated history must not change past values."""
    full = ema(trending_frame["close"], 21)
    truncated = ema(trending_frame["close"].iloc[:-50], 21)
    pd.testing.assert_series_equal(full.iloc[:-50], truncated, check_names=False)
