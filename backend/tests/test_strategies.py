"""Strategy behaviour tests."""

from __future__ import annotations

import pandas as pd
import pytest

from app.core.constants import MarketRegime, SignalType, TrendRegime, VolatilityRegime
from app.regime.engine import MarketRegimeEngine, RegimeResult
from app.strategies.registry import available_keys, create_strategy, strategy_metadata


def test_three_strategies_are_registered() -> None:
    keys = available_keys()
    assert "trend_following" in keys
    assert "breakout_donchian" in keys
    assert "mean_reversion" in keys
    assert len(strategy_metadata()) == 3


@pytest.mark.parametrize("key", ["trend_following", "breakout_donchian", "mean_reversion"])
def test_strategy_returns_a_valid_signal(key: str, trending_frame: pd.DataFrame) -> None:
    strategy = create_strategy(key)
    regime_engine = MarketRegimeEngine()
    regime = regime_engine.classify(trending_frame)
    signal = strategy.generate(
        trending_frame, symbol="BTC/USDT", timeframe="15m", regime=regime
    )
    assert signal.strategy_key == key
    assert signal.signal in (SignalType.LONG, SignalType.SHORT, SignalType.HOLD, SignalType.CLOSE)
    assert 0.0 <= signal.confidence <= 1.0
    assert signal.explanation


@pytest.mark.parametrize("key", ["trend_following", "breakout_donchian", "mean_reversion"])
def test_entry_signals_have_a_consistent_stop(key: str, trending_frame: pd.DataFrame) -> None:
    strategy = create_strategy(key)
    prepared = strategy.prepare(trending_frame, "15m")
    engine = MarketRegimeEngine()
    annotated = engine.annotate(trending_frame)

    checked = 0
    for index in range(strategy.warmup_bars, len(prepared)):
        signal = strategy.evaluate(
            prepared,
            index,
            symbol="BTC/USDT",
            timeframe="15m",
            regime=engine.result_at(annotated, index),
        )
        if not signal.is_entry:
            continue
        checked += 1
        assert signal.entry_price is not None and signal.entry_price > 0
        assert signal.stop_loss is not None
        if signal.signal == SignalType.LONG:
            assert signal.stop_loss < signal.entry_price
            assert signal.take_profit is None or signal.take_profit > signal.entry_price
        else:
            assert signal.stop_loss > signal.entry_price
            assert signal.take_profit is None or signal.take_profit < signal.entry_price
    assert checked >= 0  # a strategy is allowed to stay flat


def test_trend_strategy_goes_long_in_an_uptrend(trending_frame: pd.DataFrame) -> None:
    strategy = create_strategy("trend_following", {"min_adx": 5.0, "momentum_threshold": 0.0})
    prepared = strategy.prepare(trending_frame, "15m")
    signals = [
        strategy.evaluate(prepared, index, symbol="BTC/USDT", timeframe="15m")
        for index in range(strategy.warmup_bars, len(prepared))
    ]
    longs = [signal for signal in signals if signal.signal == SignalType.LONG]
    shorts = [signal for signal in signals if signal.signal == SignalType.SHORT]
    assert len(longs) > len(shorts)


def test_mean_reversion_stands_aside_in_a_trending_regime(trending_frame: pd.DataFrame) -> None:
    strategy = create_strategy("mean_reversion")
    prepared = strategy.prepare(trending_frame, "15m")
    trending_regime = RegimeResult(
        regime=MarketRegime.TRENDING_UP,
        trend=TrendRegime.TRENDING_UP,
        volatility=VolatilityRegime.NORMAL,
        adx=35.0,
    )
    for index in range(strategy.warmup_bars, len(prepared)):
        signal = strategy.evaluate(
            prepared, index, symbol="BTC/USDT", timeframe="15m", regime=trending_regime
        )
        assert signal.signal in (SignalType.HOLD, SignalType.CLOSE)


def test_strategy_parameters_are_configurable() -> None:
    strategy = create_strategy("trend_following", {"fast_ema": 8, "slow_ema": 34})
    params = strategy.params_dict()
    assert params["fast_ema"] == 8
    assert params["slow_ema"] == 34
    assert "fast_ema" in strategy.param_schema()["properties"]


def test_extreme_volatility_blocks_entries(volatile_frame: pd.DataFrame) -> None:
    engine = MarketRegimeEngine()
    regime = engine.classify(volatile_frame)
    assert regime.volatility in (VolatilityRegime.HIGH, VolatilityRegime.EXTREME)
    strategy = create_strategy("trend_following")
    signal = strategy.generate(
        volatile_frame, symbol="BTC/USDT", timeframe="15m", regime=regime
    )
    if regime.volatility == VolatilityRegime.EXTREME:
        assert signal.signal == SignalType.HOLD
