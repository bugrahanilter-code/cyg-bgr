"""Choosing a strategy and timeframe from a matrix backtest.

The problem this has to survive
-------------------------------
Running 14 strategies across 6 timeframes gives 84 combinations. Picking the
best one and trading it is the classic way to fool yourself: with 84 draws from
noise, the winner's backtest number is roughly a 99th percentile result even if
every strategy is worthless. The apparent edge is mostly the selection.

So "best" is not defined as "highest return". It is defined as a combination
that survives four separate ways of being wrong:

1. **Enough trades.** Twenty trades can show any number at all.
2. **Breadth, not one lucky market.** The combination has to be profitable on a
   majority of the markets it was tested on, scored on the *median* market
   rather than the mean, so one outlier cannot carry it.
3. **Cost-aware.** Expectancy is measured in R, after fees, spread and slippage.
4. **Out-of-sample.** The winner is re-run on a later window that was not part
   of the selection. If it does not hold there, it is not accepted.

If nothing passes, that is a result. :func:`select_best` returns a verdict of
``NO_QUALIFYING_COMBINATION`` rather than the least bad row, because handing
back the least bad row is how a losing configuration ends up trading.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import BacktestStatus
from app.core.logging import get_logger
from app.models.sweep import BacktestSweep, SweepRun

logger = get_logger(__name__)


class SelectionCriteria(BaseModel):
    """The bar a combination has to clear to be considered tradable."""

    #: Trades summed across every market for this strategy/timeframe.
    min_total_trades: int = Field(default=100, ge=10)
    #: Trades required on an individual market for it to count at all.
    min_trades_per_market: int = Field(default=20, ge=5)
    #: Markets the combination must be tested on before breadth means anything.
    min_markets: int = Field(default=5, ge=1)
    #: Share of those markets that must be profitable.
    min_profitable_markets_pct: float = Field(default=55.0, ge=0.0, le=100.0)
    #: Median expectancy per trade, in units of risk, after all costs.
    min_median_expectancy_r: float = Field(default=0.01, ge=-1.0)
    min_median_profit_factor: float = Field(default=1.05, ge=0.0)
    #: Reject a combination whose drawdown makes it untradable in practice.
    max_median_drawdown_pct: float = Field(default=35.0, gt=0.0)


@dataclass(slots=True)
class Candidate:
    """One strategy/timeframe combination, aggregated across markets."""

    strategy_key: str
    timeframe: str
    markets: int
    markets_profitable: int
    total_trades: int
    median_expectancy_r: float
    mean_expectancy_r: float
    median_profit_factor: float
    median_return_pct: float
    median_drawdown_pct: float
    median_excess_vs_hold_pct: float
    worst_market_return_pct: float
    passed: bool = False
    failures: list[str] = field(default_factory=list)

    @property
    def profitable_pct(self) -> float:
        return self.markets_profitable / self.markets * 100.0 if self.markets else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_key": self.strategy_key,
            "timeframe": self.timeframe,
            "markets": self.markets,
            "markets_profitable": self.markets_profitable,
            "profitable_pct": round(self.profitable_pct, 1),
            "total_trades": self.total_trades,
            "median_expectancy_r": round(self.median_expectancy_r, 4),
            "mean_expectancy_r": round(self.mean_expectancy_r, 4),
            "median_profit_factor": round(self.median_profit_factor, 3),
            "median_return_pct": round(self.median_return_pct, 2),
            "median_drawdown_pct": round(self.median_drawdown_pct, 2),
            "median_excess_vs_hold_pct": round(self.median_excess_vs_hold_pct, 2),
            "worst_market_return_pct": round(self.worst_market_return_pct, 2),
            "passed": self.passed,
            "failures": self.failures,
        }


def _aggregate(rows: list[SweepRun], criteria: SelectionCriteria) -> list[Candidate]:
    """Group sweep cells into strategy/timeframe candidates."""
    groups: dict[tuple[str, str], list[SweepRun]] = {}
    for row in rows:
        if row.total_trades < criteria.min_trades_per_market:
            continue
        groups.setdefault((row.strategy_key, row.timeframe), []).append(row)

    candidates: list[Candidate] = []
    for (strategy_key, timeframe), cells in groups.items():
        expectancies = [cell.expectancy_r for cell in cells]
        factors = [cell.profit_factor for cell in cells]
        returns = [cell.return_pct for cell in cells]
        drawdowns = [cell.max_drawdown_pct for cell in cells]
        excess = [cell.return_pct - cell.buy_hold_return_pct for cell in cells]

        candidates.append(
            Candidate(
                strategy_key=strategy_key,
                timeframe=timeframe,
                markets=len(cells),
                markets_profitable=sum(1 for cell in cells if cell.net_pnl > 0),
                total_trades=sum(cell.total_trades for cell in cells),
                median_expectancy_r=statistics.median(expectancies),
                mean_expectancy_r=statistics.fmean(expectancies),
                median_profit_factor=statistics.median(factors),
                median_return_pct=statistics.median(returns),
                median_drawdown_pct=statistics.median(drawdowns),
                median_excess_vs_hold_pct=statistics.median(excess),
                worst_market_return_pct=min(returns),
            )
        )
    return candidates


def _apply_criteria(candidate: Candidate, criteria: SelectionCriteria) -> Candidate:
    """Record every reason a candidate fails, not just the first."""
    failures: list[str] = []
    if candidate.markets < criteria.min_markets:
        failures.append(f"tested on {candidate.markets} markets, needs {criteria.min_markets}")
    if candidate.total_trades < criteria.min_total_trades:
        failures.append(f"{candidate.total_trades} trades, needs {criteria.min_total_trades}")
    if candidate.profitable_pct < criteria.min_profitable_markets_pct:
        failures.append(
            f"profitable on {candidate.profitable_pct:.0f}% of markets, "
            f"needs {criteria.min_profitable_markets_pct:.0f}%"
        )
    if candidate.median_expectancy_r < criteria.min_median_expectancy_r:
        failures.append(
            f"median expectancy {candidate.median_expectancy_r:+.4f}R, "
            f"needs {criteria.min_median_expectancy_r:+.4f}R"
        )
    if candidate.median_profit_factor < criteria.min_median_profit_factor:
        failures.append(
            f"median profit factor {candidate.median_profit_factor:.2f}, "
            f"needs {criteria.min_median_profit_factor:.2f}"
        )
    if candidate.median_drawdown_pct > criteria.max_median_drawdown_pct:
        failures.append(
            f"median drawdown {candidate.median_drawdown_pct:.1f}%, "
            f"limit {criteria.max_median_drawdown_pct:.1f}%"
        )
    candidate.failures = failures
    candidate.passed = not failures
    return candidate


def _rank_key(candidate: Candidate) -> tuple:
    """Rank by robustness first, size of the number second.

    Breadth across markets comes before the headline figure on purpose: a
    combination that works on eight of ten markets at +0.02R is a better bet
    than one that works on three at +0.20R, even though the second looks better
    in a table.
    """
    return (
        candidate.profitable_pct,
        candidate.median_expectancy_r,
        candidate.median_excess_vs_hold_pct,
    )


def select_best(
    db: Session, sweep_id: int, criteria: SelectionCriteria | None = None
) -> dict[str, Any]:
    """Rank every strategy/timeframe combination in a sweep and pick a winner.

    Returns a verdict, never a bare row. ``NO_QUALIFYING_COMBINATION`` is a
    legitimate and common answer: handing back the least bad combination is how
    a losing configuration ends up being traded.
    """
    criteria = criteria or SelectionCriteria()
    sweep = db.get(BacktestSweep, sweep_id)
    if sweep is None:
        raise ValueError(f"Sweep {sweep_id} not found")

    rows = (
        db.execute(
            select(SweepRun).where(
                SweepRun.sweep_id == sweep_id,
                SweepRun.status == BacktestStatus.COMPLETED.value,
            )
        )
        .scalars()
        .all()
    )

    candidates = [_apply_criteria(item, criteria) for item in _aggregate(rows, criteria)]
    candidates.sort(key=_rank_key, reverse=True)
    qualifying = [item for item in candidates if item.passed]

    combinations_tested = len(candidates)
    verdict = "QUALIFIED" if qualifying else "NO_QUALIFYING_COMBINATION"
    winner = qualifying[0] if qualifying else None

    # The multiple-comparisons warning is not decoration: it is the single most
    # likely reason a winner here fails in live trading.
    selection_note = (
        f"{combinations_tested} strategy/timeframe combinations were compared. "
        "With that many draws the best backtest number is inflated by chance "
        "alone, so the winner means nothing until it is confirmed on a window "
        "that was not used to choose it."
    )

    return {
        "sweep_id": sweep_id,
        "sweep_name": sweep.name,
        "window": {"start": sweep.start_date, "end": sweep.end_date},
        "verdict": verdict,
        "winner": winner.to_dict() if winner else None,
        "qualifying_count": len(qualifying),
        "combinations_tested": combinations_tested,
        "criteria": criteria.model_dump(),
        "ranked": [item.to_dict() for item in candidates[:25]],
        "selection_bias_note": selection_note,
        "next_step": (
            "Confirm the winner out of sample before enabling it."
            if winner
            else "Nothing cleared the bar. Widen the window or accept that no "
            "combination in this grid is tradable as configured."
        ),
    }


def build_validation_plan(
    winner: dict[str, Any],
    symbols: list[str],
    holdout_days: int = 90,
) -> dict[str, Any]:
    """Describe the out-of-sample run that has to pass before going live.

    Returned as a plan rather than executed here so the caller can start it as
    an ordinary sweep and watch it in the same UI as any other backtest.
    """
    from datetime import timedelta

    from app.core.time_utils import utcnow

    end = utcnow()
    start = end - timedelta(days=holdout_days)
    return {
        "name": (f"Out-of-sample check: {winner['strategy_key']} on {winner['timeframe']}"),
        "strategy_keys": [winner["strategy_key"]],
        "timeframes": [winner["timeframe"]],
        "symbols": symbols,
        "symbol_source": "explicit",
        "start": start,
        "end": end,
        "acceptance": {
            "min_median_expectancy_r": 0.0,
            "min_profitable_markets_pct": 50.0,
            "note": (
                "The bar out of sample is lower than the selection bar on "
                "purpose: the question is whether the edge survives at all, not "
                "whether it repeats its best window."
            ),
        },
    }
