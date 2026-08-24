"""Walk-forward analysis.

Optimising a strategy on the whole history and then reporting the result on
that same history is meaningless. This module enforces the honest workflow:

    IN SAMPLE  -> pick parameters
    VALIDATION -> sanity check (optional, part of the in-sample block)
    OUT OF SAMPLE -> the only numbers worth reporting

The out-of-sample windows are never used to choose parameters.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from app.backtesting.engine import BacktestEngine, BacktestRequest
from app.core.constants import DatasetSplit
from app.core.exceptions import InsufficientDataError
from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_COMBINATIONS = 60


class WalkForwardRequest(BaseModel):
    """Configuration of a walk-forward run."""

    folds: int = Field(default=4, ge=2, le=12)
    in_sample_ratio: float = Field(default=0.7, gt=0.2, lt=0.95)
    param_grid: dict[str, list[Any]] = Field(default_factory=dict)
    objective: str = Field(default="sharpe_ratio")
    min_trades: int = Field(default=5, ge=0, le=1000)


@dataclass(slots=True)
class FoldResult:
    """One in-sample / out-of-sample pair."""

    index: int
    in_sample_metrics: dict[str, Any] = field(default_factory=dict)
    out_of_sample_metrics: dict[str, Any] = field(default_factory=dict)
    best_params: dict[str, Any] = field(default_factory=dict)
    in_sample_range: tuple[str, str] = ("", "")
    out_of_sample_range: tuple[str, str] = ("", "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold": self.index,
            "best_params": self.best_params,
            "in_sample": self.in_sample_metrics,
            "out_of_sample": self.out_of_sample_metrics,
            "in_sample_range": list(self.in_sample_range),
            "out_of_sample_range": list(self.out_of_sample_range),
        }


def _combinations(param_grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Expand a parameter grid, capped so a UI click cannot lock up the server."""
    if not param_grid:
        return [{}]
    keys = list(param_grid.keys())
    values = [param_grid[key] for key in keys]
    combos = [dict(zip(keys, combo, strict=False)) for combo in itertools.product(*values)]
    if len(combos) > MAX_COMBINATIONS:
        logger.warning(
            "Parameter grid truncated", extra={"requested": len(combos), "used": MAX_COMBINATIONS}
        )
        combos = combos[:MAX_COMBINATIONS]
    return combos


def run_walk_forward(
    frame: pd.DataFrame,
    base_request: BacktestRequest,
    config: WalkForwardRequest,
    engine: BacktestEngine | None = None,
) -> dict[str, Any]:
    """Run a rolling in-sample / out-of-sample analysis."""
    engine = engine or BacktestEngine()
    frame = frame.sort_values("open_time").reset_index(drop=True)
    total = len(frame)
    fold_size = total // config.folds
    if fold_size < 400:
        raise InsufficientDataError(
            "Not enough candles for a walk-forward analysis. Use a longer date range, "
            "a smaller timeframe or fewer folds."
        )

    folds: list[FoldResult] = []
    for fold_index in range(config.folds):
        start = fold_index * fold_size
        end = total if fold_index == config.folds - 1 else (fold_index + 1) * fold_size
        window = frame.iloc[start:end].reset_index(drop=True)
        split_at = int(len(window) * config.in_sample_ratio)
        in_sample = window.iloc[:split_at].reset_index(drop=True)
        out_of_sample = window.iloc[split_at:].reset_index(drop=True)
        if len(in_sample) < 300 or len(out_of_sample) < 100:
            continue

        best_params: dict[str, Any] = {}
        best_score = float("-inf")
        best_metrics: dict[str, Any] = {}
        for candidate in _combinations(config.param_grid):
            params = {**base_request.params, **candidate}
            request = base_request.model_copy(
                update={"params": params, "split": DatasetSplit.IN_SAMPLE}
            )
            try:
                result = engine.run(in_sample, request)
            except InsufficientDataError:
                continue
            metrics = result.metrics
            if metrics.get("total_trades", 0) < config.min_trades:
                continue
            score = float(metrics.get(config.objective) or float("-inf"))
            if score > best_score:
                best_score = score
                best_params = candidate
                best_metrics = metrics

        params = {**base_request.params, **best_params}
        oos_request = base_request.model_copy(
            update={"params": params, "split": DatasetSplit.OUT_OF_SAMPLE}
        )
        try:
            oos_result = engine.run(out_of_sample, oos_request)
            oos_metrics = oos_result.metrics
        except InsufficientDataError:
            oos_metrics = {}

        folds.append(
            FoldResult(
                index=fold_index + 1,
                in_sample_metrics=best_metrics,
                out_of_sample_metrics=oos_metrics,
                best_params=best_params,
                in_sample_range=(
                    str(in_sample["open_time"].iloc[0]),
                    str(in_sample["open_time"].iloc[-1]),
                ),
                out_of_sample_range=(
                    str(out_of_sample["open_time"].iloc[0]),
                    str(out_of_sample["open_time"].iloc[-1]),
                ),
            )
        )

    aggregate = _aggregate([fold.out_of_sample_metrics for fold in folds])
    return {
        "folds": [fold.to_dict() for fold in folds],
        "out_of_sample_summary": aggregate,
        "objective": config.objective,
        "warning": (
            "Out-of-sample numbers are the only ones that carry information. "
            "In-sample results are optimistic by construction."
        ),
    }


def _aggregate(metric_sets: list[dict[str, Any]]) -> dict[str, Any]:
    """Average the out-of-sample metrics across folds."""
    usable = [metrics for metrics in metric_sets if metrics]
    if not usable:
        return {}
    keys = [
        "total_return_pct",
        "net_pnl",
        "win_rate_pct",
        "profit_factor",
        "sharpe_ratio",
        "sortino_ratio",
        "max_drawdown_pct",
        "total_trades",
    ]
    summary: dict[str, Any] = {"folds_evaluated": len(usable)}
    for key in keys:
        values = [
            float(metrics[key])
            for metrics in usable
            if metrics.get(key) is not None and isinstance(metrics.get(key), int | float)
        ]
        summary[key] = sum(values) / len(values) if values else None
    summary["profitable_folds"] = sum(
        1 for metrics in usable if float(metrics.get("net_pnl") or 0.0) > 0
    )
    return summary
