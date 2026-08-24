"""PnL mathematics tests."""

from __future__ import annotations

import pytest

from app.core.constants import PositionSide
from app.portfolio.pnl import (
    compute_trade_pnl,
    fee_cost,
    funding_cost,
    gross_pnl,
    round_trip_fees,
    unrealized_pnl,
)


def test_long_profit() -> None:
    assert gross_pnl(PositionSide.LONG, 100.0, 110.0, 2.0) == pytest.approx(20.0)


def test_long_loss() -> None:
    assert gross_pnl(PositionSide.LONG, 100.0, 90.0, 2.0) == pytest.approx(-20.0)


def test_short_profit() -> None:
    assert gross_pnl(PositionSide.SHORT, 100.0, 90.0, 2.0) == pytest.approx(20.0)


def test_short_loss() -> None:
    assert gross_pnl(PositionSide.SHORT, 100.0, 110.0, 2.0) == pytest.approx(-20.0)


def test_unrealized_matches_gross() -> None:
    assert unrealized_pnl(PositionSide.LONG, 100.0, 105.0, 1.0) == pytest.approx(5.0)


def test_fees_are_charged_on_both_sides() -> None:
    assert fee_cost(1000.0, 0.04) == pytest.approx(0.4)
    assert round_trip_fees(1000.0, 1100.0, 0.04) == pytest.approx(0.84)


def test_longs_pay_funding_when_the_rate_is_positive() -> None:
    assert funding_cost(PositionSide.LONG, 1000.0, 0.01, 3) == pytest.approx(0.3)
    assert funding_cost(PositionSide.SHORT, 1000.0, 0.01, 3) == pytest.approx(-0.3)
    assert funding_cost(PositionSide.LONG, 1000.0, 0.01, 0) == 0.0


def test_net_pnl_subtracts_every_cost() -> None:
    result = compute_trade_pnl(
        side=PositionSide.LONG,
        entry_price=100.0,
        exit_price=110.0,
        quantity=10.0,
        fee_pct=0.04,
        funding_paid=1.0,
    )
    assert result.gross == pytest.approx(100.0)
    assert result.fees == pytest.approx(0.84)
    assert result.net == pytest.approx(100.0 - 0.84 - 1.0)
    assert result.net < result.gross


def test_a_small_win_can_become_a_loss_after_costs() -> None:
    result = compute_trade_pnl(
        side=PositionSide.LONG,
        entry_price=100.0,
        exit_price=100.05,
        quantity=10.0,
        fee_pct=0.04,
        funding_paid=0.2,
    )
    assert result.gross > 0
    assert result.net < 0
