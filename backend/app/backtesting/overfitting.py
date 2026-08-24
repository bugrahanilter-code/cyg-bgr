"""Measuring how much of a backtest result is selection rather than skill.

Why this module exists
----------------------
Twice in this project a strategy was chosen as the best of many combinations,
looked excellent, and then failed on data it had not been chosen on:

* 19 combinations compared, winner 62% profitable at +0.089R.
  Out of sample: 20% profitable at -0.045R.
* 74 combinations compared, 11 passed every gate.
  Out of sample: 0 of 11 passed.

Both were caught by re-running on a holdout, which works but is slow and only
tells you about the one winner. The two measures here quantify the same thing
directly from the trial results, before any holdout is run:

``deflated_sharpe_ratio``
    A Sharpe ratio is a sample statistic. Run enough variants and one of them
    will look good by chance alone. The DSR discounts an observed Sharpe by how
    many trials it was selected from, how long the sample is, and how non-normal
    the returns are. It answers: is this Sharpe distinguishable from the best
    you would expect from luck?

``probability_of_backtest_overfitting``
    Splits the trial results into many train/test partitions and asks how often
    the configuration that looked best on the training half landed below median
    on the testing half. That fraction is the PBO. Above roughly 0.5 the
    selection procedure is worse than random.

Both are from Bailey and López de Prado. The conventional reading is that a
strategy with PBO above 0.05 should not be trusted, and this codebase has yet to
produce one below it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import numpy as np

#: Euler-Mascheroni constant, used in the expected-maximum-Sharpe estimate.
EULER_MASCHERONI = 0.5772156649015329


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _normal_ppf(p: float) -> float:
    """Inverse normal CDF (Acklam's rational approximation, ~1e-9 accurate)."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf

    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]

    low, high = 0.02425, 1 - 0.02425
    if p < low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > high:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


@dataclass(slots=True)
class DeflatedSharpe:
    """An observed Sharpe, and what is left of it after the trials are counted."""

    observed_sharpe: float
    #: The Sharpe you would expect the best of ``trials`` random strategies to
    #: reach by luck alone. The observed value has to beat this to mean anything.
    expected_max_sharpe: float
    deflated_sharpe: float
    trials: int
    observations: int
    skew: float
    kurtosis: float

    @property
    def significant(self) -> bool:
        """True when the Sharpe survives the trial count at 95% confidence."""
        return self.deflated_sharpe >= 0.95

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_sharpe": round(self.observed_sharpe, 4),
            "expected_max_sharpe_from_luck": round(self.expected_max_sharpe, 4),
            "deflated_sharpe": round(self.deflated_sharpe, 4),
            "significant": self.significant,
            "trials": self.trials,
            "observations": self.observations,
            "verdict": (
                "The Sharpe survives the number of variants tried."
                if self.significant
                else "Indistinguishable from the best of that many random tries."
            ),
        }


def expected_max_sharpe(trials: int, sharpe_variance: float = 1.0) -> float:
    """Sharpe the best of ``trials`` unskilled strategies reaches by chance.

    This is the bar an observed Sharpe has to clear. It grows with the number of
    variants tried, which is why comparing 74 strategy/timeframe combinations
    and keeping the winner is not the same as testing one strategy.
    """
    if trials < 2:
        return 0.0
    deviation = math.sqrt(max(sharpe_variance, 0.0))
    upper = _normal_ppf(1.0 - 1.0 / trials)
    lower = _normal_ppf(1.0 - 1.0 / (trials * math.e))
    return deviation * ((1.0 - EULER_MASCHERONI) * upper + EULER_MASCHERONI * lower)


def deflated_sharpe_ratio(
    returns: list[float] | np.ndarray,
    trials: int,
    sharpe_variance: float | None = None,
) -> DeflatedSharpe:
    """Discount a Sharpe ratio by the number of variants it was chosen from.

    ``returns`` are per-trade or per-period returns of the selected strategy.
    ``trials`` is how many configurations were compared to arrive at it - the
    honest number, not one.
    """
    values = np.asarray(list(returns), dtype=float)
    values = values[np.isfinite(values)]
    observations = values.size

    if observations < 3:
        return DeflatedSharpe(0.0, 0.0, 0.0, trials, observations, 0.0, 3.0)

    mean = float(values.mean())
    deviation = float(values.std(ddof=1))

    # A constant series has a standard deviation of zero in theory and of about
    # 1e-17 in floating point, which would divide out to a Sharpe of 1e15 and be
    # reported as overwhelmingly significant. The comparison has to be relative
    # to the size of the numbers involved, not against exact zero.
    scale = max(abs(mean), float(np.abs(values).max()), 1.0)
    if deviation <= scale * 1e-12:
        return DeflatedSharpe(0.0, 0.0, 0.0, trials, observations, 0.0, 3.0)

    observed = mean / deviation
    centred = (values - mean) / deviation
    skew = float(np.mean(centred**3))
    kurtosis = float(np.mean(centred**4))

    if sharpe_variance is None:
        # Variance of the Sharpe estimator across trials. Without the real
        # spread of the trials, the standard approximation is used.
        sharpe_variance = (1.0 - skew * observed + (kurtosis - 1.0) / 4.0 * observed**2) / max(
            observations - 1, 1
        )

    threshold = expected_max_sharpe(trials, max(sharpe_variance, 1e-12))

    denominator = 1.0 - skew * observed + (kurtosis - 1.0) / 4.0 * observed**2
    denominator = max(denominator, 1e-12)
    statistic = (
        (observed - threshold) * math.sqrt(max(observations - 1, 1)) / math.sqrt(denominator)
    )
    return DeflatedSharpe(
        observed_sharpe=observed,
        expected_max_sharpe=threshold,
        deflated_sharpe=_normal_cdf(statistic),
        trials=trials,
        observations=observations,
        skew=skew,
        kurtosis=kurtosis,
    )


@dataclass(slots=True)
class OverfittingReport:
    """How often the in-sample winner turns out to be below average later."""

    pbo: float
    partitions: int
    trials: int
    #: Median out-of-sample rank of the in-sample winner, 0 worst to 1 best.
    median_oos_rank: float
    #: Out-of-sample performance of the in-sample winner, per partition.
    oos_performance: list[float]
    #: How much worse the winner did out of sample, on average.
    performance_decay: float

    @property
    def acceptable(self) -> bool:
        """The conventional bar: above 0.05 the selection is not trustworthy."""
        return self.pbo <= 0.05

    def to_dict(self) -> dict[str, Any]:
        return {
            "pbo": round(self.pbo, 4),
            "acceptable": self.acceptable,
            "partitions": self.partitions,
            "trials": self.trials,
            "median_oos_rank": round(self.median_oos_rank, 4),
            "performance_decay": round(self.performance_decay, 4),
            "verdict": (
                "The selection procedure holds up out of sample."
                if self.acceptable
                else f"{self.pbo:.0%} of the time the in-sample winner lands below median "
                "out of sample. The ranking is mostly noise."
            ),
        }


def probability_of_backtest_overfitting(
    performance: np.ndarray | list[list[float]],
    partitions: int = 8,
) -> OverfittingReport:
    """PBO by combinatorially symmetric cross-validation.

    ``performance`` is a matrix with one row per observation (a trade, a day)
    and one column per configuration tried. The rows are split into ``partitions``
    equal blocks; every way of choosing half of them becomes a training set and
    the remaining half a test set. In each split the configuration with the best
    training performance is found, and its *rank* among all configurations on the
    test half is recorded.

    If selection worked, the winner would rank near the top out of sample. PBO is
    the share of splits where it landed in the bottom half instead. At 0.5 the
    procedure has no skill at all; the usual threshold for trusting a result is
    0.05.
    """
    matrix = np.asarray(performance, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] < 2:
        raise ValueError("Need a matrix with at least two configurations to compare")

    partitions = max(2, partitions - partitions % 2)
    observations, trials = matrix.shape
    if observations < partitions:
        raise ValueError(f"{observations} observations cannot be split into {partitions} blocks")

    blocks = np.array_split(np.arange(observations), partitions)
    half = partitions // 2

    logits: list[float] = []
    ranks: list[float] = []
    oos_performance: list[float] = []
    decay: list[float] = []

    for train_blocks in combinations(range(partitions), half):
        test_blocks = [b for b in range(partitions) if b not in train_blocks]
        train_rows = np.concatenate([blocks[b] for b in train_blocks])
        test_rows = np.concatenate([blocks[b] for b in test_blocks])

        train_score = _sharpe_per_column(matrix[train_rows])
        test_score = _sharpe_per_column(matrix[test_rows])
        if not np.isfinite(train_score).any() or not np.isfinite(test_score).any():
            continue

        winner = int(np.nanargmax(train_score))
        # Relative rank of the winner out of sample: 1 is best, 0 is worst.
        finite = np.isfinite(test_score)
        if finite.sum() < 2:
            continue
        order = np.argsort(np.argsort(np.where(finite, test_score, -np.inf)))
        relative_rank = order[winner] / (trials - 1)
        # Keep the logit finite at the extremes.
        clipped = min(max(relative_rank, 1e-6), 1 - 1e-6)

        logits.append(math.log(clipped / (1 - clipped)))
        ranks.append(relative_rank)
        oos_performance.append(float(test_score[winner]))
        decay.append(float(train_score[winner] - test_score[winner]))

    if not logits:
        raise ValueError("No usable partition produced a comparison")

    pbo = float(np.mean([1.0 if value <= 0 else 0.0 for value in logits]))
    return OverfittingReport(
        pbo=pbo,
        partitions=len(logits),
        trials=trials,
        median_oos_rank=float(np.median(ranks)),
        oos_performance=oos_performance,
        performance_decay=float(np.mean(decay)),
    )


def _sharpe_per_column(block: np.ndarray) -> np.ndarray:
    """Sharpe of every configuration over one block of observations."""
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.nanmean(block, axis=0)
        deviation = np.nanstd(block, axis=0, ddof=1)
        return np.where(deviation > 0, mean / deviation, np.nan)
