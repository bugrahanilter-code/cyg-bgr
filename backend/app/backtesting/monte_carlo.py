"""Monte Carlo analysis of a trade sequence.

A single backtest is one draw from a distribution. Reshuffling and resampling
the realised trades shows how much of the result was the *order* of the trades
(luck) rather than the edge itself, and how bad the drawdown could plausibly
have been with the same trades in a different sequence.

This cannot tell you whether the edge is real. It can tell you that a result
which looks good is inside the range you would expect from randomness.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def _max_drawdown_pct(equity: np.ndarray) -> float:
    """Worst peak-to-trough fall of an equity path, in percent."""
    running_peak = np.maximum.accumulate(equity)
    safe_peak = np.where(running_peak == 0, np.nan, running_peak)
    drawdowns = (running_peak - equity) / safe_peak * 100.0
    return float(np.nanmax(np.nan_to_num(drawdowns, nan=0.0)))


def _longest_losing_streak(returns: np.ndarray) -> int:
    """Longest run of consecutive losing trades."""
    best = 0
    current = 0
    for value in returns:
        if value <= 0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def run_monte_carlo(
    trade_returns: list[float],
    starting_capital: float,
    simulations: int = 10_000,
    method: str = "bootstrap",
    seed: int = 12345,
) -> dict[str, Any]:
    """Resample a trade sequence and report the distribution of outcomes.

    Args:
        trade_returns: net PnL of each closed trade, in account currency.
        starting_capital: the equity the paths start from.
        simulations: how many synthetic sequences to build.
        method: "bootstrap" resamples with replacement (changes which trades
            occur), "shuffle" only reorders the realised trades.
        seed: fixed so a report can be reproduced exactly.
    """
    trades = np.asarray([float(value) for value in trade_returns], dtype="float64")
    count = trades.size
    if count < 5:
        return {
            "ran": False,
            "reason": f"Only {count} trades: a Monte Carlo on this is meaningless.",
            "trades": int(count),
        }

    rng = np.random.default_rng(seed)
    final_returns = np.empty(simulations, dtype="float64")
    drawdowns = np.empty(simulations, dtype="float64")
    streaks = np.empty(simulations, dtype="int64")
    ruin = 0

    for index in range(simulations):
        if method == "shuffle":
            sample = rng.permutation(trades)
        else:
            sample = trades[rng.integers(0, count, count)]

        equity = starting_capital + np.cumsum(sample)
        equity_path = np.concatenate([[starting_capital], equity])
        final_returns[index] = (equity_path[-1] - starting_capital) / starting_capital * 100.0
        drawdowns[index] = _max_drawdown_pct(equity_path)
        streaks[index] = _longest_losing_streak(sample)
        if equity_path.min() <= 0:
            ruin += 1

    return {
        "ran": True,
        "method": method,
        "simulations": int(simulations),
        "trades": int(count),
        "median_return_pct": float(np.median(final_returns)),
        "mean_return_pct": float(np.mean(final_returns)),
        "return_p5_pct": float(np.percentile(final_returns, 5)),
        "return_p95_pct": float(np.percentile(final_returns, 95)),
        "probability_of_profit_pct": float((final_returns > 0).mean() * 100.0),
        "median_max_drawdown_pct": float(np.median(drawdowns)),
        "drawdown_p95_pct": float(np.percentile(drawdowns, 95)),
        "worst_drawdown_pct": float(np.max(drawdowns)),
        "median_losing_streak": int(np.median(streaks)),
        "worst_losing_streak": int(np.max(streaks)),
        "risk_of_ruin_pct": float(ruin / simulations * 100.0),
    }
