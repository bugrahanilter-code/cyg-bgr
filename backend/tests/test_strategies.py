"""Strategy behaviour tests."""

from __future__ import annotations

import pandas as pd
import pytest

from app.core.constants import MarketRegime, RiskLevel, SignalType, TrendRegime, VolatilityRegime
from app.regime.engine import MarketRegimeEngine, RegimeResult
from app.strategies.registry import available_keys, create_strategy, strategy_metadata

ALL_KEYS = available_keys()


def test_thirteen_strategies_are_registered() -> None:
    keys = set(ALL_KEYS)
    assert {"trend_following", "breakout_donchian", "mean_reversion"} <= keys
    assert {"volatility_breakout", "rsi_divergence", "squeeze_momentum"} <= keys
    assert {"macd_momentum", "ichimoku_trend", "supertrend_follow"} <= keys
    assert {"golden_cross", "dual_momentum", "vwap_pullback", "keltner_trend"} <= keys
    assert len(strategy_metadata()) == 13


def test_every_strategy_declares_a_risk_level() -> None:
    levels = [meta["risk_level"] for meta in strategy_metadata()]
    assert set(levels) <= {level.value for level in RiskLevel}
    assert levels.count("safe") == 4
    assert levels.count("risky") == 4
    assert levels.count("medium") == 5


def test_strategies_are_listed_safest_first() -> None:
    levels = [meta["risk_level"] for meta in strategy_metadata()]
    order = {"safe": 0, "medium": 1, "risky": 2}
    assert levels == sorted(levels, key=lambda level: order[level])


@pytest.mark.parametrize("key", ALL_KEYS)
def test_strategy_returns_a_valid_signal(key: str, trending_frame: pd.DataFrame) -> None:
    strategy = create_strategy(key)
    regime_engine = MarketRegimeEngine()
    regime = regime_engine.classify(trending_frame)
    signal = strategy.generate(trending_frame, symbol="BTC/USDT", timeframe="15m", regime=regime)
    assert signal.strategy_key == key
    assert signal.signal in (SignalType.LONG, SignalType.SHORT, SignalType.HOLD, SignalType.CLOSE)
    assert 0.0 <= signal.confidence <= 1.0
    assert signal.explanation


@pytest.mark.parametrize("key", ALL_KEYS)
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
    signal = strategy.generate(volatile_frame, symbol="BTC/USDT", timeframe="15m", regime=regime)
    if regime.volatility == VolatilityRegime.EXTREME:
        assert signal.signal == SignalType.HOLD


def test_golden_cross_actually_produces_entries(mixed_frame: pd.DataFrame) -> None:
    """Regression test: the crossover bar itself has almost no separation.

    Requiring a minimum gap ON the crossover bar rejected every signal, so the
    strategy never traded at all. The entry now fires on the bar where the gap
    first becomes meaningful, which is a confirmed cross.
    """
    strategy = create_strategy("golden_cross", {"fast_period": 20, "slow_period": 60})
    prepared = strategy.prepare(mixed_frame, "15m")
    entries = [
        strategy.evaluate(prepared, index, symbol="BTC/USDT", timeframe="15m")
        for index in range(strategy.warmup_bars, len(prepared))
    ]
    assert any(signal.is_entry for signal in entries)


def test_every_strategy_can_produce_an_entry_somewhere(
    mixed_frame: pd.DataFrame,
    trending_frame: pd.DataFrame,
    ranging_frame: pd.DataFrame,
) -> None:
    """A strategy that can never fire is a bug, not a conservative filter."""
    never_fired: list[str] = []
    for key in ALL_KEYS:
        strategy = create_strategy(key)
        fired = False
        for frame in (mixed_frame, trending_frame, ranging_frame):
            prepared = strategy.prepare(frame, "15m")
            for index in range(strategy.warmup_bars, len(prepared)):
                signal = strategy.evaluate(prepared, index, symbol="BTC/USDT", timeframe="15m")
                if signal.is_entry:
                    fired = True
                    break
            if fired:
                break
        if not fired:
            never_fired.append(key)
    assert not never_fired, f"These strategies never produced an entry: {never_fired}"
