"""Matrix backtests: the cost estimate and the grid bookkeeping."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from app.backtesting.sweep import (
    BAR_EVALS_PER_SECOND,
    SweepPlan,
    _buy_and_hold_pct,
    _expectancy_r,
    estimate_sweep,
)
from app.core.constants import SUPPORTED_TIMEFRAMES
from app.strategies.registry import available_keys

END = datetime(2026, 1, 1, tzinfo=UTC)
START = END - timedelta(days=365)


def plan(**overrides) -> SweepPlan:
    payload = {"start": START, "end": END}
    payload.update(overrides)
    return SweepPlan(**payload)


class TestPlanResolution:
    def test_empty_strategy_list_means_every_strategy(self) -> None:
        assert plan().resolved_strategies() == available_keys()

    def test_empty_timeframe_list_means_every_timeframe(self) -> None:
        assert plan().resolved_timeframes() == list(SUPPORTED_TIMEFRAMES)

    def test_timeframes_come_back_in_canonical_order(self) -> None:
        """A grid built from an unordered UI selection still reads 1m -> 1d."""
        result = plan(timeframes=["1d", "5m", "1h", "15m"]).resolved_timeframes()
        assert result == ["5m", "15m", "1h", "1d"]

    def test_unknown_timeframes_are_dropped(self) -> None:
        assert plan(timeframes=["1h", "7y"]).resolved_timeframes() == ["1h"]


class TestEstimate:
    def test_cells_are_the_product_of_the_three_axes(self) -> None:
        result = estimate_sweep(
            plan(strategy_keys=["trend_following", "mean_reversion"], timeframes=["1h", "4h"]),
            ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        )
        assert result.cells == 2 * 2 * 3

    def test_candle_count_scales_with_the_timeframe(self) -> None:
        """A 1h grid must contain four times the candles of the same 4h grid."""
        hourly = estimate_sweep(plan(timeframes=["1h"]), ["BTC/USDT"])
        four_hourly = estimate_sweep(plan(timeframes=["4h"]), ["BTC/USDT"])
        assert hourly.total_candles == pytest.approx(four_hourly.total_candles * 4, rel=0.01)

    def test_runtime_follows_the_measured_throughput(self) -> None:
        result = estimate_sweep(
            plan(strategy_keys=["trend_following"], timeframes=["1h"]), ["BTC/USDT"]
        )
        assert result.estimated_seconds == pytest.approx(
            result.bar_evaluations / BAR_EVALS_PER_SECOND
        )

    def test_a_huge_grid_is_flagged_before_it_is_started(self) -> None:
        """The whole exchange on every timeframe is days of CPU: say so first."""
        result = estimate_sweep(plan(), [f"COIN{index}/USDT" for index in range(500)])
        assert result.estimated_seconds > 4 * 3600
        assert result.warnings
        assert any("hours of CPU" in warning for warning in result.warnings)

    def test_a_small_grid_produces_no_warnings(self) -> None:
        result = estimate_sweep(
            plan(strategy_keys=["trend_following"], timeframes=["4h"]), ["BTC/USDT"]
        )
        assert result.warnings == []

    def test_low_timeframes_on_many_markets_are_called_out(self) -> None:
        result = estimate_sweep(
            plan(strategy_keys=["trend_following"], timeframes=["1m"]),
            [f"COIN{index}/USDT" for index in range(60)],
        )
        assert any("dominates the runtime" in warning for warning in result.warnings)


class TestBuyAndHoldBaseline:
    def test_matches_the_first_and_last_close(self) -> None:
        frame = pd.DataFrame({"close": [100.0, 120.0, 150.0]})
        assert _buy_and_hold_pct(frame) == pytest.approx(50.0)

    def test_reports_a_loss_for_a_falling_market(self) -> None:
        frame = pd.DataFrame({"close": [200.0, 100.0]})
        assert _buy_and_hold_pct(frame) == pytest.approx(-50.0)

    def test_a_broken_frame_does_not_stop_the_sweep(self) -> None:
        assert _buy_and_hold_pct(pd.DataFrame({"close": []})) == 0.0


class TestExpectancyInR:
    def test_averages_the_r_multiples(self) -> None:
        trades = [{"r_multiple": 2.0}, {"r_multiple": -1.0}, {"r_multiple": -1.0}]
        assert _expectancy_r(trades) == pytest.approx(0.0)

    def test_trades_without_an_r_multiple_are_skipped(self) -> None:
        trades = [{"r_multiple": 1.0}, {"r_multiple": None}, {}]
        assert _expectancy_r(trades) == pytest.approx(1.0)

    def test_no_trades_is_zero_not_a_crash(self) -> None:
        assert _expectancy_r([]) == 0.0


class TestWarmupSizing:
    def test_covers_the_hungriest_strategy_in_the_grid(self) -> None:
        """One frame is shared by every strategy of a group, so it has to start
        early enough for whichever of them needs the longest history."""
        from app.backtesting.sweep import warmup_bars_for
        from app.strategies.registry import create_strategy

        keys = ["trend_following", "adaptive_momentum"]
        longest = max(create_strategy(key).warmup_bars for key in keys)
        assert warmup_bars_for(keys) >= longest

    def test_has_a_floor_for_short_warmup_strategies(self) -> None:
        from app.backtesting.sweep import warmup_bars_for

        assert warmup_bars_for(["golden_cross"]) >= 220

    def test_an_unknown_key_does_not_crash_the_sizing(self) -> None:
        from app.backtesting.sweep import warmup_bars_for

        assert warmup_bars_for(["not_a_strategy"]) >= 220

    def test_more_strategies_never_shrink_the_warmup(self) -> None:
        from app.backtesting.sweep import warmup_bars_for

        one = warmup_bars_for(["adaptive_momentum"])
        both = warmup_bars_for(["adaptive_momentum", "golden_cross"])
        assert both >= one


class TestStatisticalValidityWarnings:
    """Runtime is not the only way a grid can be a bad idea.

    A grid over three weeks of history finishes quickly and produces numbers
    that look like results but cannot support a conclusion, so the estimate has
    to say so before the run starts.
    """

    def test_a_short_window_is_flagged(self) -> None:
        short = plan(start=END - timedelta(days=30), timeframes=["4h"])
        result = estimate_sweep(short, ["BTC/USDT"])
        assert any("test window is only" in warning for warning in result.warnings)

    def test_a_twelve_month_window_is_not_flagged_as_short(self) -> None:
        result = estimate_sweep(plan(timeframes=["4h"]), ["BTC/USDT"])
        assert not any("test window is only" in warning for warning in result.warnings)

    def test_too_few_candles_per_market_is_flagged(self) -> None:
        """One month of daily candles is 30 bars: nothing can be concluded."""
        short = plan(start=END - timedelta(days=30), timeframes=["1d"])
        result = estimate_sweep(short, ["BTC/USDT"])
        assert any("Too little history per market" in warning for warning in result.warnings)

    def test_the_thin_timeframes_are_named(self) -> None:
        short = plan(start=END - timedelta(days=30), timeframes=["15m", "1d"])
        result = estimate_sweep(short, ["BTC/USDT"])
        thin = [w for w in result.warnings if "Too little history" in w]
        assert thin, "expected a thin-history warning"
        # 15m has 2,880 candles in a month and is fine; 1d has 30 and is not.
        assert "1d" in thin[0]
        assert "15m" not in thin[0]

    def test_a_long_window_on_high_timeframes_is_clean(self) -> None:
        result = estimate_sweep(
            plan(
                start=END - timedelta(days=730),
                strategy_keys=["trend_following"],
                timeframes=["4h"],
            ),
            ["BTC/USDT"],
        )
        assert result.warnings == []
