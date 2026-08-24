"""Research helpers: benchmarks, parameter stability and cost sensitivity.

These exist so a strategy can never be judged on net profit alone. A result is
only interesting when it survives a comparison against doing nothing clever,
a sweep of neighbouring parameter values and a worse cost assumption.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pandas as pd

from app.backtesting.engine import BacktestEngine, BacktestRequest
from app.backtesting.metrics import bars_per_year, drawdown_series, sharpe_ratio
from app.core.logging import get_logger

logger = get_logger(__name__)


def buy_and_hold(frame: pd.DataFrame, starting_capital: float, timeframe: str) -> dict[str, Any]:
    """The benchmark every strategy has to beat on a risk-adjusted basis."""
    if frame is None or len(frame) < 2:
        return {}
    closes = frame["close"].to_numpy(dtype="float64")
    units = starting_capital / closes[0]
    equity = units * closes
    returns = np.diff(equity) / equity[:-1]
    drawdown = drawdown_series([float(value) for value in equity])
    total_return = (equity[-1] - starting_capital) / starting_capital * 100.0
    return {
        "label": "Buy and hold",
        "total_return_pct": float(total_return),
        "max_drawdown_pct": drawdown.max_drawdown_pct,
        "sharpe_ratio": sharpe_ratio(returns, bars_per_year(timeframe)),
        "final_balance": float(equity[-1]),
        "total_trades": 1,
    }


def run_variant(
    frame: pd.DataFrame,
    base_request: BacktestRequest,
    overrides: dict[str, Any],
    engine: BacktestEngine | None = None,
) -> dict[str, Any]:
    """Run one parameter variant and return only its metrics."""
    engine = engine or BacktestEngine()
    params = {**base_request.params, **overrides}
    request = base_request.model_copy(update={"params": params})
    try:
        return engine.run(frame, request).metrics
    except Exception as exc:  # pragma: no cover - a variant may be unusable
        logger.warning("Variant failed", extra={"overrides": overrides, "error": str(exc)})
        return {}


def parameter_stability(
    frame: pd.DataFrame,
    base_request: BacktestRequest,
    parameter: str,
    values: list[Any],
    metric: str = "profit_factor",
    engine: BacktestEngine | None = None,
) -> dict[str, Any]:
    """Sweep one parameter and judge whether the result is a plateau or a spike.

    A genuine edge is a *plateau*: neighbouring values give similar results. A
    single value that shines while its neighbours are poor is the signature of
    curve fitting, not of an edge.
    """
    engine = engine or BacktestEngine()
    rows: list[dict[str, Any]] = []
    for value in values:
        metrics = run_variant(frame, base_request, {parameter: value}, engine)
        rows.append(
            {
                "value": value,
                "metric": _safe_metric(metrics, metric),
                "total_return_pct": _safe_metric(metrics, "total_return_pct"),
                "profit_factor": _safe_metric(metrics, "profit_factor"),
                "sharpe_ratio": _safe_metric(metrics, "sharpe_ratio"),
                "max_drawdown_pct": _safe_metric(metrics, "max_drawdown_pct"),
                "total_trades": _safe_metric(metrics, "total_trades"),
            }
        )

    scores = [row["metric"] for row in rows if row["metric"] is not None]
    verdict = "insufficient data"
    spike_ratio = None
    if len(scores) >= 3:
        best = max(scores)
        others = sorted(scores, reverse=True)[1:]
        neighbour_average = sum(others) / len(others)
        if best <= 0:
            verdict = "no configuration worked"
        elif neighbour_average <= 0:
            verdict = "OVERFITTING RISK: only one value is positive"
            spike_ratio = float("inf")
        else:
            spike_ratio = best / neighbour_average
            if spike_ratio > 1.8:
                verdict = "OVERFITTING RISK: the best value is a spike, not a plateau"
            elif spike_ratio > 1.35:
                verdict = "caution: mild sensitivity around the best value"
            else:
                verdict = "stable: neighbouring values behave similarly"

    return {
        "parameter": parameter,
        "metric": metric,
        "rows": rows,
        "verdict": verdict,
        "spike_ratio": spike_ratio,
    }


def cost_sensitivity(
    frame: pd.DataFrame,
    base_request: BacktestRequest,
    slippage_values: list[float],
    engine: BacktestEngine | None = None,
) -> dict[str, Any]:
    """Re-run the same strategy under worse execution assumptions.

    A strategy that only works at optimistic slippage is not a strategy, it is
    a rounding error.
    """
    engine = engine or BacktestEngine()
    rows: list[dict[str, Any]] = []
    for slippage in slippage_values:
        costs = copy.deepcopy(base_request.cost_model)
        costs.slippage_pct = slippage
        request = base_request.model_copy(update={"cost_model": costs})
        try:
            metrics = engine.run(frame, request).metrics
        except Exception:  # pragma: no cover - defensive
            metrics = {}
        rows.append(
            {
                "slippage_pct": slippage,
                "total_return_pct": _safe_metric(metrics, "total_return_pct"),
                "profit_factor": _safe_metric(metrics, "profit_factor"),
                "net_pnl": _safe_metric(metrics, "net_pnl"),
                "total_trades": _safe_metric(metrics, "total_trades"),
            }
        )

    positive = [row for row in rows if (row["net_pnl"] or 0) > 0]
    survives = len(positive) == len(rows) and bool(rows)
    return {
        "rows": rows,
        "survives_all_assumptions": survives,
        "verdict": (
            "robust to execution costs"
            if survives
            else "FRAGILE: profitability depends on the cost assumption"
        ),
    }


def _safe_metric(metrics: dict[str, Any], key: str) -> Any:
    value = metrics.get(key)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(number) or np.isinf(number):
        return None
    return number
