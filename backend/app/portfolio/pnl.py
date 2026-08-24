"""Profit and loss mathematics.

One formula, used everywhere: backtest, paper trading and live trading all
call these functions so their numbers are directly comparable.

    Net PnL = Gross PnL - Fees - Funding

Slippage is not subtracted separately: it is already embedded in the fill
prices. It is still reported so the user can see what execution costs.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.constants import PositionSide, SignalType


def direction_multiplier(side: PositionSide | SignalType | str) -> float:
    """+1 for a long position, -1 for a short position."""
    text = str(getattr(side, "value", side)).upper()
    if text in ("LONG", "BUY"):
        return 1.0
    if text in ("SHORT", "SELL"):
        return -1.0
    return 0.0


def gross_pnl(
    side: PositionSide | SignalType | str, entry: float, exit_price: float, quantity: float
) -> float:
    """Price difference multiplied by size and direction."""
    return (exit_price - entry) * quantity * direction_multiplier(side)


def unrealized_pnl(
    side: PositionSide | SignalType | str, entry: float, mark_price: float, quantity: float
) -> float:
    """Mark-to-market PnL of an open position."""
    return gross_pnl(side, entry, mark_price, quantity)


def fee_cost(notional: float, fee_pct: float) -> float:
    """Trading fee for one side of a trade."""
    return abs(notional) * fee_pct / 100.0


def round_trip_fees(entry_notional: float, exit_notional: float, fee_pct: float) -> float:
    """Fees for opening and closing a position."""
    return fee_cost(entry_notional, fee_pct) + fee_cost(exit_notional, fee_pct)


def funding_cost(
    side: PositionSide | SignalType | str,
    notional: float,
    funding_rate_pct: float,
    intervals: int,
) -> float:
    """Perpetual funding paid (positive) or received (negative).

    With a positive funding rate longs pay shorts, which is the normal state of
    a bullish perpetual market.
    """
    if intervals <= 0:
        return 0.0
    direction = direction_multiplier(side)
    return abs(notional) * funding_rate_pct / 100.0 * intervals * direction


def slippage_cost(
    side: PositionSide | SignalType | str, intended_price: float, fill_price: float, quantity: float
) -> float:
    """Money lost to a worse-than-intended fill (always reported as a cost)."""
    direction = direction_multiplier(side)
    return abs((fill_price - intended_price) * quantity * direction) if intended_price else 0.0


@dataclass(slots=True)
class TradePnL:
    """Full cost breakdown of one round trip."""

    gross: float = 0.0
    fees: float = 0.0
    funding: float = 0.0
    slippage: float = 0.0
    net: float = 0.0
    return_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            "gross_pnl": self.gross,
            "fees": self.fees,
            "funding": self.funding,
            "slippage": self.slippage,
            "net_pnl": self.net,
            "return_pct": self.return_pct,
        }


def compute_trade_pnl(
    *,
    side: PositionSide | SignalType | str,
    entry_price: float,
    exit_price: float,
    quantity: float,
    fee_pct: float = 0.04,
    funding_paid: float = 0.0,
    slippage: float = 0.0,
    capital_base: float | None = None,
) -> TradePnL:
    """Compute gross, fees, funding and net PnL for a completed trade."""
    entry_notional = entry_price * quantity
    exit_notional = exit_price * quantity
    gross = gross_pnl(side, entry_price, exit_price, quantity)
    fees = round_trip_fees(entry_notional, exit_notional, fee_pct)
    net = gross - fees - funding_paid
    base = capital_base if capital_base and capital_base > 0 else entry_notional
    return TradePnL(
        gross=gross,
        fees=fees,
        funding=funding_paid,
        slippage=slippage,
        net=net,
        return_pct=(net / base * 100.0) if base > 0 else 0.0,
    )


def funding_intervals_between(seconds: float, interval_hours: float = 8.0) -> int:
    """How many funding events a position of this duration would have paid."""
    if seconds <= 0 or interval_hours <= 0:
        return 0
    return int(seconds // (interval_hours * 3600))
