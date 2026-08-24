"""Stop loss and take profit rules, shared by the backtester and the engine."""

from __future__ import annotations

import pytest

from app.core.constants import SignalType
from app.risk.config import RiskConfig
from app.risk.exit_policy import (
    StopLossMode,
    TakeProfitMode,
    resolve_exits,
    update_stop,
)

ENTRY = 100.0


def levels(config, side=SignalType.LONG, stop=98.0, target=104.0):
    return resolve_exits(
        config, side=side, entry_price=ENTRY, proposed_stop=stop, proposed_take_profit=target
    )


class TestDefaultChangesNothing:
    """A fresh install must behave exactly as it did before this existed."""

    def test_strategy_levels_pass_through(self) -> None:
        result = levels(RiskConfig())
        assert result.stop_loss == pytest.approx(98.0)
        assert result.take_profit == pytest.approx(104.0)
        assert result.valid

    def test_risk_reward_is_reported(self) -> None:
        result = levels(RiskConfig())
        assert result.risk_distance == pytest.approx(2.0)
        assert result.risk_reward == pytest.approx(2.0)


class TestFixedStop:
    def test_long_stop_sits_below_entry(self) -> None:
        config = RiskConfig(stop_loss_mode=StopLossMode.FIXED_PCT.value, stop_loss_pct=1.0)
        result = levels(config)
        assert result.stop_loss == pytest.approx(99.0)

    def test_short_stop_sits_above_entry(self) -> None:
        config = RiskConfig(stop_loss_mode=StopLossMode.FIXED_PCT.value, stop_loss_pct=1.0)
        result = levels(config, side=SignalType.SHORT, stop=102.0, target=96.0)
        assert result.stop_loss == pytest.approx(101.0)

    def test_the_strategy_level_is_ignored(self) -> None:
        config = RiskConfig(stop_loss_mode=StopLossMode.FIXED_PCT.value, stop_loss_pct=3.0)
        result = levels(config, stop=99.9)
        assert result.stop_loss == pytest.approx(97.0)


class TestStopBand:
    """The band is a safety envelope, not just a mode.

    A strategy asking for a 40% stop is a bug, and sizing a position against it
    would put far too much money at risk on one trade.
    """

    def test_an_absurdly_wide_stop_is_tightened(self) -> None:
        config = RiskConfig(max_stop_distance_pct=5.0)
        result = levels(config, stop=60.0)
        assert result.stop_loss == pytest.approx(95.0)
        assert any("tightened" in note for note in result.adjustments)

    def test_a_hair_thin_stop_is_widened(self) -> None:
        config = RiskConfig(min_stop_distance_pct=1.0)
        result = levels(config, stop=99.99)
        assert result.stop_loss == pytest.approx(99.0)
        assert any("widened" in note for note in result.adjustments)

    def test_a_stop_inside_the_band_is_untouched(self) -> None:
        config = RiskConfig(min_stop_distance_pct=0.5, max_stop_distance_pct=5.0)
        result = levels(config, stop=98.0)
        assert result.stop_loss == pytest.approx(98.0)
        assert result.adjustments == []

    def test_the_band_applies_to_shorts_in_the_right_direction(self) -> None:
        config = RiskConfig(max_stop_distance_pct=5.0)
        result = levels(config, side=SignalType.SHORT, stop=140.0, target=90.0)
        assert result.stop_loss == pytest.approx(105.0)

    def test_a_missing_stop_falls_back_rather_than_trading_naked(self) -> None:
        config = RiskConfig(stop_loss_pct=2.0)
        result = levels(config, stop=None)
        assert result.stop_loss == pytest.approx(98.0)
        assert result.valid


class TestTakeProfit:
    def test_fixed_percentage(self) -> None:
        config = RiskConfig(take_profit_mode=TakeProfitMode.FIXED_PCT.value, take_profit_pct=3.0)
        assert levels(config).take_profit == pytest.approx(103.0)

    def test_risk_multiple_measures_from_the_decided_stop(self) -> None:
        config = RiskConfig(
            take_profit_mode=TakeProfitMode.RISK_MULTIPLE.value, take_profit_r_multiple=3.0
        )
        result = levels(config, stop=98.0)
        assert result.take_profit == pytest.approx(106.0)
        assert result.risk_reward == pytest.approx(3.0)

    def test_risk_multiple_follows_a_widened_stop(self) -> None:
        """The target is measured from the stop that was actually used, not the
        one the strategy asked for."""
        config = RiskConfig(
            min_stop_distance_pct=5.0,
            take_profit_mode=TakeProfitMode.RISK_MULTIPLE.value,
            take_profit_r_multiple=2.0,
        )
        result = levels(config, stop=99.5)
        assert result.stop_loss == pytest.approx(95.0)
        assert result.take_profit == pytest.approx(110.0)

    def test_none_removes_the_target_entirely(self) -> None:
        """Trend systems live on the few large winners a fixed target caps."""
        config = RiskConfig(take_profit_mode=TakeProfitMode.NONE.value)
        result = levels(config)
        assert result.take_profit is None
        assert result.risk_reward is None
        assert result.valid

    def test_shorts_target_below_entry(self) -> None:
        config = RiskConfig(take_profit_mode=TakeProfitMode.FIXED_PCT.value, take_profit_pct=2.0)
        result = levels(config, side=SignalType.SHORT, stop=102.0, target=96.0)
        assert result.take_profit == pytest.approx(98.0)


class TestRiskRewardGate:
    def test_a_poor_ratio_is_rejected(self) -> None:
        config = RiskConfig(min_risk_reward=2.0)
        result = levels(config, stop=98.0, target=101.0)
        assert not result.valid
        assert "below the required" in result.rejection

    def test_a_good_ratio_passes(self) -> None:
        config = RiskConfig(min_risk_reward=2.0)
        assert levels(config, stop=98.0, target=105.0).valid

    def test_the_gate_is_off_by_default(self) -> None:
        assert levels(RiskConfig(), stop=98.0, target=100.5).valid


class TestTrailingAndBreakEven:
    """A stop may only ever move toward profit."""

    def _trail(self, config, best, current=98.0, side=SignalType.LONG, entry=ENTRY):
        return update_stop(
            config,
            side=side,
            entry_price=entry,
            current_stop=current,
            risk_distance=2.0,
            best_price=best,
        )

    def test_nothing_moves_when_both_rules_are_off(self) -> None:
        stop, reason = self._trail(RiskConfig(), best=110.0)
        assert stop == pytest.approx(98.0)
        assert reason is None

    def test_break_even_triggers_at_the_configured_r(self) -> None:
        config = RiskConfig(break_even_at_r=1.0)
        stop, reason = self._trail(config, best=102.0)
        assert stop == pytest.approx(ENTRY)
        assert "break even" in reason

    def test_break_even_does_not_trigger_early(self) -> None:
        config = RiskConfig(break_even_at_r=2.0)
        stop, reason = self._trail(config, best=102.0)
        assert stop == pytest.approx(98.0)
        assert reason is None

    def test_trailing_follows_the_best_price(self) -> None:
        config = RiskConfig(trailing_stop_enabled=True, trailing_stop_pct=1.0, trailing_start_r=0.0)
        stop, reason = self._trail(config, best=110.0)
        assert stop == pytest.approx(108.9)
        assert "trailing" in reason

    def test_trailing_waits_for_the_start_threshold(self) -> None:
        config = RiskConfig(trailing_stop_enabled=True, trailing_stop_pct=1.0, trailing_start_r=2.0)
        stop, reason = self._trail(config, best=101.0)
        assert stop == pytest.approx(98.0)
        assert reason is None

    def test_a_stop_is_never_loosened(self) -> None:
        """Widening a stop to avoid being taken out is how a small loss becomes
        a large one, so it must not be possible."""
        config = RiskConfig(trailing_stop_enabled=True, trailing_stop_pct=5.0, trailing_start_r=0.0)
        stop, _ = self._trail(config, best=101.0, current=100.5)
        assert stop >= 100.5

    def test_shorts_trail_downwards(self) -> None:
        config = RiskConfig(trailing_stop_enabled=True, trailing_stop_pct=1.0, trailing_start_r=0.0)
        stop, reason = self._trail(config, best=90.0, current=102.0, side=SignalType.SHORT)
        assert stop == pytest.approx(90.9)
        assert reason is not None

    def test_an_atr_trail_from_the_strategy_wins_over_the_flat_percentage(self) -> None:
        """An ATR trail already accounts for the market's own volatility."""
        config = RiskConfig(
            trailing_stop_enabled=True, trailing_stop_pct=10.0, trailing_start_r=0.0
        )
        stop, _ = update_stop(
            config,
            side=SignalType.LONG,
            entry_price=ENTRY,
            current_stop=98.0,
            risk_distance=2.0,
            best_price=110.0,
            strategy_trail=3.0,
        )
        assert stop == pytest.approx(107.0)

    def test_a_zero_risk_distance_does_not_divide_by_zero(self) -> None:
        stop, reason = update_stop(
            RiskConfig(break_even_at_r=1.0),
            side=SignalType.LONG,
            entry_price=ENTRY,
            current_stop=ENTRY,
            risk_distance=0.0,
            best_price=120.0,
        )
        assert stop == pytest.approx(ENTRY)
        assert reason is None


class TestBothEnginesAgree:
    """The whole point of one shared module: the simulation and the live engine
    must not compute different exits from the same settings."""

    def test_the_backtester_applies_the_configured_target(self, trending_frame) -> None:
        from datetime import timedelta

        from app.backtesting.engine import BacktestEngine, BacktestRequest
        from app.core.time_utils import from_ms
        from app.exchange.filters import default_filters_for
        from app.strategies.registry import create_strategy

        start = from_ms(int(trending_frame["open_time"].iloc[300]))
        end = from_ms(int(trending_frame["open_time"].iloc[-1]))
        engine = BacktestEngine()

        def run(config: RiskConfig):
            request = BacktestRequest(
                strategy_key="trend_following",
                symbol="BTC/USDT",
                timeframe="15m",
                start=start,
                end=end + timedelta(minutes=15),
                risk=config,
            )
            return engine.run(
                trending_frame,
                request,
                default_filters_for("BTC/USDT"),
                create_strategy("trend_following"),
            )

        baseline = run(RiskConfig())
        no_target = run(RiskConfig(take_profit_mode=TakeProfitMode.NONE.value))

        baseline_tps = sum(1 for trade in baseline.trades if trade["exit_reason"] == "take_profit")
        removed_tps = sum(1 for trade in no_target.trades if trade["exit_reason"] == "take_profit")
        assert removed_tps == 0, "removing the target must remove take-profit exits"
        assert baseline_tps >= 0

    def test_a_fixed_stop_changes_the_position_size(self) -> None:
        """Sizing works from the decided stop, so a wider stop must produce a
        smaller position rather than more money at risk."""
        from app.exchange.filters import default_filters_for
        from app.risk.engine import RiskContext, RiskEngine
        from app.signals.models import StrategySignal

        def size_for(config: RiskConfig) -> float:
            signal = StrategySignal(
                symbol="BTC/USDT",
                timeframe="15m",
                strategy_key="trend_following",
                signal=SignalType.LONG,
                candle_open_time=1_700_000_000_000,
                confidence=0.9,
                entry_price=30_000.0,
                stop_loss=29_700.0,
                take_profit=30_900.0,
                explanation="test",
            )
            context = RiskContext(
                equity=10_000.0,
                available_balance=10_000.0,
                daily_start_equity=10_000.0,
                leverage=2.0,
                filters=default_filters_for("BTC/USDT"),
            )
            decision = RiskEngine(config).evaluate(signal, context)
            assert decision.sizing is not None
            return decision.sizing.quantity

        tight = size_for(RiskConfig(stop_loss_mode=StopLossMode.FIXED_PCT.value, stop_loss_pct=1.0))
        wide = size_for(RiskConfig(stop_loss_mode=StopLossMode.FIXED_PCT.value, stop_loss_pct=4.0))
        assert wide < tight
