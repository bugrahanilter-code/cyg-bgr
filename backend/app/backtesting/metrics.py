"""Performance metrics.

Every number the dashboard shows about a backtest is computed here, from the
equity curve and the list of closed trades. Nothing is annualised with magic
constants: the number of bars per year is derived from the timeframe.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.constants import timeframe_to_minutes

TRADING_MINUTES_PER_YEAR = 365 * 24 * 60


def bars_per_year(timeframe: str) -> float:
    """Crypto trades non-stop, so a year really is 365 days of candles."""
    return TRADING_MINUTES_PER_YEAR / max(timeframe_to_minutes(timeframe), 1)


@dataclass(slots=True)
class DrawdownInfo:
    max_drawdown_pct: float = 0.0
    max_drawdown_value: float = 0.0
    peak_equity: float = 0.0
    trough_equity: float = 0.0
    curve: list[float] = field(default_factory=list)


def drawdown_series(equity: list[float]) -> DrawdownInfo:
    """Running drawdown of an equity curve."""
    info = DrawdownInfo()
    if not equity:
        return info
    values = np.asarray(equity, dtype="float64")
    running_peak = np.maximum.accumulate(values)
    safe_peak = np.where(running_peak == 0, np.nan, running_peak)
    drawdowns = (running_peak - values) / safe_peak * 100.0
    drawdowns = np.nan_to_num(drawdowns, nan=0.0, posinf=0.0, neginf=0.0)
    worst_index = int(np.argmax(drawdowns)) if drawdowns.size else 0
    info.curve = [float(value) for value in drawdowns]
    info.max_drawdown_pct = float(drawdowns[worst_index]) if drawdowns.size else 0.0
    info.peak_equity = float(running_peak[worst_index]) if drawdowns.size else 0.0
    info.trough_equity = float(values[worst_index]) if drawdowns.size else 0.0
    info.max_drawdown_value = info.peak_equity - info.trough_equity
    return info


def periodic_returns(equity: list[float]) -> np.ndarray:
    """Simple returns between consecutive equity points."""
    if len(equity) < 2:
        return np.asarray([], dtype="float64")
    values = np.asarray(equity, dtype="float64")
    previous = values[:-1]
    safe_previous = np.where(previous == 0, np.nan, previous)
    result = (values[1:] - previous) / safe_previous
    return np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)


def sharpe_ratio(returns: np.ndarray, periods: float, risk_free_rate: float = 0.0) -> float:
    """Annualised Sharpe ratio."""
    if returns.size < 2:
        return 0.0
    excess = returns - risk_free_rate / periods
    deviation = float(np.std(excess, ddof=1))
    if deviation == 0 or math.isnan(deviation):
        return 0.0
    return float(np.mean(excess) / deviation * math.sqrt(periods))


def sortino_ratio(returns: np.ndarray, periods: float, risk_free_rate: float = 0.0) -> float:
    """Annualised Sortino ratio (downside deviation only)."""
    if returns.size < 2:
        return 0.0
    excess = returns - risk_free_rate / periods
    downside = excess[excess < 0]
    if downside.size == 0:
        return 0.0
    deviation = float(np.sqrt(np.mean(np.square(downside))))
    if deviation == 0 or math.isnan(deviation):
        return 0.0
    return float(np.mean(excess) / deviation * math.sqrt(periods))


def calmar_ratio(total_return_pct: float, max_drawdown_pct: float, years: float) -> float:
    """Annualised return divided by the maximum drawdown."""
    if max_drawdown_pct <= 0 or years <= 0:
        return 0.0
    growth = 1.0 + total_return_pct / 100.0
    if growth <= 0:
        return 0.0
    annualised = (growth ** (1.0 / years) - 1.0) * 100.0
    return float(annualised / max_drawdown_pct)


def max_consecutive(values: list[bool]) -> int:
    """Longest run of True values."""
    best = 0
    current = 0
    for value in values:
        current = current + 1 if value else 0
        best = max(best, current)
    return best


def compute_metrics(
    *,
    trades: list[dict[str, Any]],
    equity_curve: list[dict[str, Any]],
    starting_capital: float,
    timeframe: str,
    duration_days: float,
) -> dict[str, Any]:
    """Build the full metric set shown on the backtest page."""
    equity_values = [float(point["equity"]) for point in equity_curve] or [starting_capital]
    final_equity = equity_values[-1]
    net_pnl = final_equity - starting_capital
    total_return_pct = (net_pnl / starting_capital * 100.0) if starting_capital > 0 else 0.0

    wins = [trade for trade in trades if float(trade.get("net_pnl", 0.0)) > 0]
    losses = [trade for trade in trades if float(trade.get("net_pnl", 0.0)) <= 0]
    gross_profit = sum(float(trade["net_pnl"]) for trade in wins)
    gross_loss = abs(sum(float(trade["net_pnl"]) for trade in losses))

    win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
    average_win = (gross_profit / len(wins)) if wins else 0.0
    average_loss = (gross_loss / len(losses)) if losses else 0.0
    profit_factor = (
        (gross_profit / gross_loss)
        if gross_loss > 0
        else (float("inf") if gross_profit > 0 else 0.0)
    )
    expectancy = (
        (win_rate / 100.0) * average_win - (1.0 - win_rate / 100.0) * average_loss
        if trades
        else 0.0
    )

    drawdown = drawdown_series(equity_values)
    returns = periodic_returns(equity_values)
    periods = bars_per_year(timeframe)
    years = max(duration_days / 365.0, 1e-9)

    durations = [float(trade.get("duration_seconds", 0.0)) for trade in trades]
    fees = sum(float(trade.get("fees", 0.0)) for trade in trades)
    funding = sum(float(trade.get("funding", 0.0)) for trade in trades)
    slippage = sum(float(trade.get("slippage_cost", 0.0)) for trade in trades)
    gross_pnl_total = sum(float(trade.get("gross_pnl", 0.0)) for trade in trades)

    return {
        "starting_capital": starting_capital,
        "final_balance": final_equity,
        "net_pnl": net_pnl,
        "gross_pnl": gross_pnl_total,
        "total_return_pct": total_return_pct,
        "total_trades": len(trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate_pct": win_rate,
        "average_win": average_win,
        "average_loss": average_loss,
        "largest_win": max((float(t["net_pnl"]) for t in wins), default=0.0),
        "largest_loss": min((float(t["net_pnl"]) for t in losses), default=0.0),
        "profit_factor": None if profit_factor == float("inf") else profit_factor,
        "expectancy": expectancy,
        "max_drawdown_pct": drawdown.max_drawdown_pct,
        "max_drawdown_value": drawdown.max_drawdown_value,
        "sharpe_ratio": sharpe_ratio(returns, periods),
        "sortino_ratio": sortino_ratio(returns, periods),
        "calmar_ratio": calmar_ratio(total_return_pct, drawdown.max_drawdown_pct, years),
        "max_consecutive_losses": max_consecutive(
            [float(trade.get("net_pnl", 0.0)) <= 0 for trade in trades]
        ),
        "max_consecutive_wins": max_consecutive(
            [float(trade.get("net_pnl", 0.0)) > 0 for trade in trades]
        ),
        "average_trade_duration_seconds": (sum(durations) / len(durations)) if durations else 0.0,
        "total_fees": fees,
        "total_funding": funding,
        "total_slippage": slippage,
        "duration_days": duration_days,
        "exposure_trades_per_day": (len(trades) / duration_days) if duration_days > 0 else 0.0,
    }


def monthly_returns(equity_curve: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate the equity curve into calendar month returns."""
    if not equity_curve:
        return []
    buckets: dict[str, list[float]] = {}
    for point in equity_curve:
        timestamp = point.get("time")
        if timestamp is None:
            continue
        label = str(timestamp)[:7]
        buckets.setdefault(label, []).append(float(point["equity"]))
    result = []
    for label in sorted(buckets):
        values = buckets[label]
        start, end = values[0], values[-1]
        result.append(
            {
                "month": label,
                "start_equity": start,
                "end_equity": end,
                "return_pct": ((end - start) / start * 100.0) if start > 0 else 0.0,
            }
        )
    return result


def trade_distribution(trades: list[dict[str, Any]], buckets: int = 12) -> dict[str, Any]:
    """Histogram of trade returns, plus a per-strategy and per-symbol split."""
    if not trades:
        return {"histogram": [], "by_symbol": [], "by_exit_reason": []}
    returns = [float(trade.get("return_pct", 0.0)) for trade in trades]
    low, high = min(returns), max(returns)
    if math.isclose(low, high):
        low, high = low - 1.0, high + 1.0
    edges = np.linspace(low, high, buckets + 1)
    counts, _ = np.histogram(returns, bins=edges)
    histogram = [
        {
            "from": float(edges[index]),
            "to": float(edges[index + 1]),
            "count": int(counts[index]),
        }
        for index in range(len(counts))
    ]

    def _group(key: str) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, float]] = {}
        for trade in trades:
            label = str(trade.get(key, "unknown"))
            entry = grouped.setdefault(label, {"count": 0.0, "net_pnl": 0.0, "wins": 0.0})
            entry["count"] += 1
            entry["net_pnl"] += float(trade.get("net_pnl", 0.0))
            entry["wins"] += 1 if float(trade.get("net_pnl", 0.0)) > 0 else 0
        return [
            {
                "label": label,
                "count": int(values["count"]),
                "net_pnl": values["net_pnl"],
                "win_rate_pct": values["wins"] / values["count"] * 100.0
                if values["count"]
                else 0.0,
            }
            for label, values in sorted(grouped.items())
        ]

    return {
        "histogram": histogram,
        "by_symbol": _group("symbol"),
        "by_exit_reason": _group("exit_reason"),
    }
