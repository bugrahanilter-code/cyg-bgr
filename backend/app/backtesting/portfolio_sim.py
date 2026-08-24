"""Portfolio-level simulation on top of per-market backtests.

The bar-by-bar engine trades one market at a time. Running it per market and
then merging the trades chronologically gives a portfolio view, and lets the
portfolio rules the single-market engine cannot express be applied: a cap on
concurrent positions, a cap on total risk at any moment, and a correlation
group cap so three "different" long positions that are really one bet on the
same market direction cannot all be opened.

This is an approximation, and an honest one: signals were generated without
knowledge of the portfolio state, so a trade skipped here would in reality have
freed capacity for a later signal. It is a conservative view, not an exact one.
"""

from __future__ import annotations

from typing import Any

from app.backtesting.metrics import drawdown_series, max_consecutive

#: Assets that mostly move together. One directional bet, three tickers.
DEFAULT_CORRELATION_GROUPS: dict[str, str] = {
    "BTC": "majors",
    "ETH": "majors",
    "SOL": "majors",
    "BNB": "majors",
    "AVAX": "alt_l1",
    "ADA": "alt_l1",
    "LINK": "alt_l1",
    "XRP": "payments",
    "DOGE": "meme",
}


def _group_of(symbol: str, groups: dict[str, str]) -> str:
    base = symbol.split("/")[0].upper()
    return groups.get(base, base)


def simulate_portfolio(
    trades_by_symbol: dict[str, list[dict[str, Any]]],
    *,
    starting_capital: float,
    risk_per_trade_pct: float = 0.5,
    max_open_positions: int = 3,
    max_portfolio_risk_pct: float = 1.5,
    max_per_correlation_group: int = 2,
    correlation_groups: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Merge per-market trades into one account and apply portfolio limits."""
    groups = correlation_groups or DEFAULT_CORRELATION_GROUPS

    merged: list[dict[str, Any]] = []
    for symbol, trades in trades_by_symbol.items():
        for trade in trades:
            entry = dict(trade)
            entry["symbol"] = symbol
            merged.append(entry)
    merged.sort(key=lambda item: item["opened_ms"])

    equity = starting_capital
    open_positions: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = [{"time_ms": 0, "equity": equity}]
    skipped = {"max_positions": 0, "portfolio_risk": 0, "correlation": 0}

    for trade in merged:
        opened = trade["opened_ms"]
        # Close everything that finished before this trade opens.
        still_open = []
        for position in open_positions:
            if position["closed_ms"] <= opened:
                equity += position["net_pnl"]
                equity_curve.append({"time_ms": position["closed_ms"], "equity": equity})
            else:
                still_open.append(position)
        open_positions = still_open

        if len(open_positions) >= max_open_positions:
            skipped["max_positions"] += 1
            continue

        group = _group_of(trade["symbol"], groups)
        same_group = sum(
            1 for position in open_positions if _group_of(position["symbol"], groups) == group
        )
        if same_group >= max_per_correlation_group:
            skipped["correlation"] += 1
            continue

        open_risk_pct = risk_per_trade_pct * len(open_positions)
        if open_risk_pct + risk_per_trade_pct > max_portfolio_risk_pct + 1e-9:
            skipped["portfolio_risk"] += 1
            continue

        open_positions.append(trade)
        accepted.append(trade)

    for position in sorted(open_positions, key=lambda item: item["closed_ms"]):
        equity += position["net_pnl"]
        equity_curve.append({"time_ms": position["closed_ms"], "equity": equity})

    values = [point["equity"] for point in equity_curve]
    drawdown = drawdown_series(values)
    net_values = [trade["net_pnl"] for trade in accepted]
    wins = [value for value in net_values if value > 0]
    losses = [value for value in net_values if value <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    return {
        "starting_capital": starting_capital,
        "final_balance": equity,
        "net_pnl": equity - starting_capital,
        "total_return_pct": (equity - starting_capital) / starting_capital * 100.0,
        "total_trades": len(accepted),
        "signals_skipped": skipped,
        "signals_seen": len(merged),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate_pct": (len(wins) / len(accepted) * 100.0) if accepted else 0.0,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else None,
        "expectancy": (sum(net_values) / len(net_values)) if net_values else 0.0,
        "max_drawdown_pct": drawdown.max_drawdown_pct,
        "max_consecutive_losses": max_consecutive([value <= 0 for value in net_values]),
        "equity_curve": equity_curve,
        "trade_returns": net_values,
    }
