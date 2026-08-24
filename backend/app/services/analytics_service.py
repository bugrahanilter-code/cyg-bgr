"""Trade analytics shared by the strategies page and the comparison page."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.metrics import drawdown_series, max_consecutive
from app.core.constants import TradingMode
from app.core.time_utils import utcnow
from app.models.trading import Trade


def load_trades(
    db: Session,
    *,
    mode: TradingMode | None = None,
    symbol: str | None = None,
    strategy_key: str | None = None,
    since: datetime | None = None,
    backtest_id: int | None = None,
    limit: int | None = None,
) -> list[Trade]:
    """Query the trade journal with the usual filters."""
    query = select(Trade)
    if mode is not None:
        query = query.where(Trade.mode == mode.value)
    if symbol:
        query = query.where(Trade.symbol == symbol.upper())
    if strategy_key:
        query = query.where(Trade.strategy_key == strategy_key)
    if since is not None:
        query = query.where(Trade.closed_at >= since)
    if backtest_id is not None:
        query = query.where(Trade.backtest_id == backtest_id)
    query = query.order_by(Trade.closed_at.asc())
    if limit:
        query = query.limit(limit)
    return list(db.execute(query).scalars().all())


def summarise(trades: list[Trade], starting_capital: float = 0.0) -> dict[str, Any]:
    """Aggregate a list of trades into the headline performance numbers."""
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "net_pnl": 0.0,
            "gross_pnl": 0.0,
            "fees": 0.0,
            "funding": 0.0,
            "profit_factor": None,
            "expectancy": 0.0,
            "average_win": 0.0,
            "average_loss": 0.0,
            "max_drawdown_pct": 0.0,
            "max_consecutive_losses": 0,
            "average_duration_seconds": 0.0,
            "average_return_pct": 0.0,
        }

    net_values = [float(trade.net_pnl or 0.0) for trade in trades]
    wins = [value for value in net_values if value > 0]
    losses = [value for value in net_values if value <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    win_rate = len(wins) / len(net_values) * 100.0
    average_win = gross_profit / len(wins) if wins else 0.0
    average_loss = gross_loss / len(losses) if losses else 0.0

    equity = starting_capital if starting_capital > 0 else max(abs(sum(net_values)) * 10, 1000.0)
    curve = [equity]
    for value in net_values:
        equity += value
        curve.append(equity)
    drawdown = drawdown_series(curve)

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": win_rate,
        "net_pnl": sum(net_values),
        "gross_pnl": sum(float(trade.gross_pnl or 0.0) for trade in trades),
        "fees": sum(float(trade.fees or 0.0) for trade in trades),
        "funding": sum(float(trade.funding or 0.0) for trade in trades),
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else None,
        "expectancy": (win_rate / 100.0) * average_win - (1 - win_rate / 100.0) * average_loss,
        "average_win": average_win,
        "average_loss": average_loss,
        "max_drawdown_pct": drawdown.max_drawdown_pct,
        "max_consecutive_losses": max_consecutive([value <= 0 for value in net_values]),
        "average_duration_seconds": sum(int(trade.duration_seconds or 0) for trade in trades)
        / len(trades),
        "average_return_pct": sum(float(trade.return_pct or 0.0) for trade in trades) / len(trades),
    }


def pnl_since(db: Session, mode: TradingMode, days: int) -> float:
    """Realised PnL over the last N days."""
    since = utcnow() - timedelta(days=days)
    trades = load_trades(db, mode=mode, since=since)
    return sum(float(trade.net_pnl or 0.0) for trade in trades)


def strategy_breakdown(
    db: Session,
    mode: TradingMode,
    strategy_keys: list[str],
    symbols: list[str] | None = None,
    starting_capital: float = 0.0,
) -> list[dict[str, Any]]:
    """Performance of every strategy, optionally split per market."""
    rows: list[dict[str, Any]] = []
    for key in strategy_keys:
        overall = summarise(load_trades(db, mode=mode, strategy_key=key), starting_capital)
        entry: dict[str, Any] = {"strategy": key, "overall": overall, "by_symbol": []}
        for symbol in symbols or []:
            entry["by_symbol"].append(
                {
                    "symbol": symbol,
                    **summarise(
                        load_trades(db, mode=mode, strategy_key=key, symbol=symbol),
                        starting_capital,
                    ),
                }
            )
        rows.append(entry)
    return rows
