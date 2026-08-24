"""Measuring selection bias rather than discovering it after the fact.

Both measures are checked against data where the answer is known: pure noise
must be called noise, and a genuine edge must survive.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.backtesting.overfitting import (
    deflated_sharpe_ratio,
    expected_max_sharpe,
    probability_of_backtest_overfitting,
)


@pytest.fixture
def noise() -> np.ndarray:
    """Fifty configurations with no skill in any of them."""
    return np.random.default_rng(42).normal(0, 1, size=(500, 50))


class TestExpectedMaxSharpe:
    def test_a_single_trial_needs_no_discount(self) -> None:
        assert expected_max_sharpe(1) == 0.0

    def test_more_trials_raise_the_bar(self) -> None:
        """The whole point: comparing 74 combinations is not the same as
        testing one, and the bar for calling the winner skilled goes up."""
        assert expected_max_sharpe(74) > expected_max_sharpe(20) > expected_max_sharpe(5)

    def test_it_scales_with_the_spread_of_the_trials(self) -> None:
        assert expected_max_sharpe(50, 4.0) > expected_max_sharpe(50, 1.0)


class TestDeflatedSharpe:
    def test_the_luckiest_of_many_noise_strategies_is_not_significant(
        self, noise: np.ndarray
    ) -> None:
        sharpes = noise.mean(axis=0) / noise.std(axis=0)
        luckiest = noise[:, int(np.argmax(sharpes))]
        result = deflated_sharpe_ratio(luckiest, trials=noise.shape[1])
        assert not result.significant

    def test_a_genuine_edge_survives(self, noise: np.ndarray) -> None:
        skilled = noise[:, 0] + 0.25
        result = deflated_sharpe_ratio(skilled, trials=noise.shape[1])
        assert result.significant
        assert result.observed_sharpe > result.expected_max_sharpe

    def test_the_same_returns_look_worse_after_more_trials(self, noise: np.ndarray) -> None:
        """One strategy tested once is a result. The same numbers picked out of
        a thousand variants are not."""
        series = noise[:, 0] + 0.15
        few = deflated_sharpe_ratio(series, trials=2)
        many = deflated_sharpe_ratio(series, trials=5000)
        assert few.deflated_sharpe > many.deflated_sharpe

    def test_too_little_data_returns_zero_rather_than_a_wrong_number(self) -> None:
        assert deflated_sharpe_ratio([0.1, 0.2], trials=10).deflated_sharpe == 0.0

    def test_a_flat_series_has_no_sharpe(self) -> None:
        assert deflated_sharpe_ratio([0.05] * 50, trials=10).deflated_sharpe == 0.0


class TestProbabilityOfBacktestOverfitting:
    def test_pure_noise_is_called_out(self, noise: np.ndarray) -> None:
        """With no skill anywhere, the in-sample winner is simply whichever got
        luckiest, and luck reverses. PBO lands at or above one half."""
        result = probability_of_backtest_overfitting(noise, partitions=8)
        assert result.pbo > 0.5
        assert not result.acceptable

    def test_a_real_edge_is_recognised(self, noise: np.ndarray) -> None:
        skilled = noise.copy()
        skilled[:, 7] += 0.25
        result = probability_of_backtest_overfitting(skilled, partitions=8)
        assert result.pbo < 0.05
        assert result.acceptable
        assert result.median_oos_rank > 0.9

    def test_it_reports_how_much_performance_decays(self, noise: np.ndarray) -> None:
        result = probability_of_backtest_overfitting(noise, partitions=8)
        assert result.performance_decay > 0, "the in-sample winner must do worse later"

    def test_one_configuration_cannot_be_compared(self) -> None:
        with pytest.raises(ValueError, match="at least two configurations"):
            probability_of_backtest_overfitting(np.zeros((100, 1)))

    def test_too_few_observations_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cannot be split"):
            probability_of_backtest_overfitting(np.zeros((4, 10)), partitions=8)

    def test_partitions_are_forced_even(self, noise: np.ndarray) -> None:
        """The split needs equal halves, so an odd request is rounded down."""
        result = probability_of_backtest_overfitting(noise, partitions=7)
        assert result.partitions == 20  # C(6,3)
