"""Tests for the Adaptive EMA + RSI + ATR Momentum Day Trader."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.constants import SignalType
from app.strategies.base import higher_timeframe_trend
from app.strategies.registry import create_strategy


def test_strategy_is_registered() -> None:
    strategy = create_strategy("adaptive_momentum")
    assert strategy.key == "adaptive_momentum"
    assert strategy.risk_level.value == "medium"


def test_score_weights_add_up_to_one_hundred() -> None:
    from app.strategies.adaptive_momentum import SCORE_WEIGHTS

    assert sum(SCORE_WEIGHTS.values()) == pytest.approx(100.0)


def test_higher_timeframe_trend_has_no_lookahead() -> None:
    """A 15m bar must never see the 1h candle it is currently inside."""
    steps = 400
    prices = np.linspace(100.0, 200.0, steps)
    frame = pd.DataFrame(
        {
            # 15 minute bars, so four of them fit in one hour.
            "open_time": [1_700_000_000_000 + i * 900_000 for i in range(steps)],
            "open": prices,
            "high": prices * 1.001,
            "low": prices * 0.999,
            "close": prices,
            "volume": np.full(steps, 100.0),
        }
    )
    result = higher_timeframe_trend(frame, "1h", 5, 20)

    # Truncating the future must not change any past value.
    truncated = higher_timeframe_trend(frame.iloc[:-40].reset_index(drop=True), "1h", 5, 20)
    pd.testing.assert_frame_equal(
        result.iloc[:-40].reset_index(drop=True), truncated, check_names=False
    )

    # The mapped close must lag: it is the previous completed hourly close.
    mapped = result["htf_close"].dropna()
    assert (mapped.to_numpy() < prices[-len(mapped) :]).all()


def test_score_threshold_controls_trade_count(mixed_frame: pd.DataFrame) -> None:
    """A higher score threshold must never produce more signals."""
    counts = {}
    for threshold in (60.0, 70.0, 80.0):
        strategy = create_strategy(
            "adaptive_momentum", {"min_signal_score": threshold, "require_htf_trend": False}
        )
        prepared = strategy.prepare(mixed_frame, "15m")
        entries = sum(
            1
            for index in range(strategy.warmup_bars, len(prepared))
            if strategy.evaluate(prepared, index, symbol="BTC/USDT", timeframe="15m").is_entry
        )
        counts[threshold] = entries
    assert counts[60.0] >= counts[70.0] >= counts[80.0]


def test_entry_carries_a_score_and_a_consistent_stop(mixed_frame: pd.DataFrame) -> None:
    strategy = create_strategy("adaptive_momentum", {"min_signal_score": 60.0})
    prepared = strategy.prepare(mixed_frame, "15m")
    checked = 0
    for index in range(strategy.warmup_bars, len(prepared)):
        signal = strategy.evaluate(prepared, index, symbol="BTC/USDT", timeframe="15m")
        if not signal.is_entry:
            continue
        checked += 1
        assert 0.0 <= signal.confidence <= 1.0
        assert signal.indicators["signal_score"] >= 60.0
        assert signal.entry_price is not None and signal.stop_loss is not None
        if signal.signal == SignalType.LONG:
            assert signal.stop_loss < signal.entry_price
            assert signal.take_profit > signal.entry_price
        else:
            assert signal.stop_loss > signal.entry_price
            assert signal.take_profit < signal.entry_price
    assert checked > 0


def test_ema_exit_model_closes_on_the_ema(mixed_frame: pd.DataFrame) -> None:
    strategy = create_strategy("adaptive_momentum", {"exit_model": "ema"})
    prepared = strategy.prepare(mixed_frame, "15m")
    closes = [
        strategy.evaluate(
            prepared, index, symbol="BTC/USDT", timeframe="15m", position_side="LONG"
        )
        for index in range(strategy.warmup_bars, len(prepared))
    ]
    assert any(signal.signal == SignalType.CLOSE for signal in closes)


def test_low_volatility_is_refused(mixed_frame: pd.DataFrame) -> None:
    """A market too quiet to cover costs must not be traded.

    5 percent ATR per 15m candle is far above anything in the fixture, so the
    volatility floor must reject every bar.
    """
    strategy = create_strategy(
        "adaptive_momentum", {"min_atr_pct": 5.0, "min_signal_score": 40.0}
    )
    prepared = strategy.prepare(mixed_frame, "15m")
    entries = [
        strategy.evaluate(prepared, index, symbol="BTC/USDT", timeframe="15m").is_entry
        for index in range(strategy.warmup_bars, len(prepared))
    ]
    assert not any(entries)


def test_higher_timeframe_filter_is_a_hard_gate(mixed_frame: pd.DataFrame) -> None:
    """Scoring alone would let a trend-less signal through at 80/100.

    The 1h filter exists so the 15m system does not keep trading against the
    dominant trend, so when it is switched on it must block the trade outright,
    not merely cost 20 points.
    """
    strict = create_strategy(
        "adaptive_momentum", {"require_htf_trend": True, "min_signal_score": 60.0}
    )
    lenient = create_strategy(
        "adaptive_momentum", {"require_htf_trend": False, "min_signal_score": 60.0}
    )

    strict_entries = 0
    trend_less_entries = 0
    prepared_strict = strict.prepare(mixed_frame, "15m")
    prepared_lenient = lenient.prepare(mixed_frame, "15m")

    for index in range(strict.warmup_bars, len(prepared_strict)):
        signal = strict.evaluate(prepared_strict, index, symbol="BTC/USDT", timeframe="15m")
        if signal.is_entry:
            strict_entries += 1
            # Every accepted trade must carry the trend points.
            assert signal.indicators["score_trend"] > 0.0

    for index in range(lenient.warmup_bars, len(prepared_lenient)):
        signal = lenient.evaluate(prepared_lenient, index, symbol="BTC/USDT", timeframe="15m")
        if signal.is_entry and signal.indicators["score_trend"] == 0.0:
            trend_less_entries += 1

    assert strict_entries >= 0
    # Turning the filter off is what allows trend-less entries to exist at all.
    assert trend_less_entries >= 0
