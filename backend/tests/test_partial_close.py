"""Closing part of a position.

The accounting has to hold: the two halves of one position must add up to the
same money as closing it in one go, and the costs already carried by the
position must be split rather than charged twice.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.constants import ExitReason, PositionStatus, TradingMode
from app.models.trading import Position
from app.portfolio.engine import PortfolioEngine


def make_position(db, *, quantity=2.0, entry=100.0, margin=100.0, fees=0.8, side="LONG"):
    from app.core.time_utils import utcnow

    position = Position(
        uid=uuid.uuid4().hex[:24],
        symbol="BTC/USDT",
        strategy_key="trend_following",
        mode=TradingMode.PAPER.value,
        side=side,
        status=PositionStatus.OPEN.value,
        quantity=quantity,
        entry_price=entry,
        leverage=2.0,
        margin=margin,
        fees_paid=fees,
        funding_paid=0.2,
        slippage_cost=0.4,
        opened_at=utcnow(),
    )
    db.add(position)
    db.commit()
    db.refresh(position)
    return position


@pytest.fixture
def portfolio() -> PortfolioEngine:
    return PortfolioEngine(TradingMode.PAPER)


class TestQuantityBookkeeping:
    def test_half_a_position_leaves_half_open(self, db, portfolio) -> None:
        position = make_position(db, quantity=2.0)
        trade = portfolio.reduce_position(
            db, position, quantity=1.0, exit_price=110.0, exit_reason=ExitReason.MANUAL
        )
        assert trade.quantity == pytest.approx(1.0)
        assert float(position.quantity) == pytest.approx(1.0)
        assert position.status == PositionStatus.OPEN.value

    def test_margin_shrinks_with_the_quantity(self, db, portfolio) -> None:
        position = make_position(db, quantity=4.0, margin=200.0)
        portfolio.reduce_position(
            db, position, quantity=1.0, exit_price=110.0, exit_reason=ExitReason.MANUAL
        )
        assert float(position.margin) == pytest.approx(150.0)

    def test_closing_more_than_is_open_closes_what_is_there(self, db, portfolio) -> None:
        position = make_position(db, quantity=2.0)
        trade = portfolio.reduce_position(
            db, position, quantity=99.0, exit_price=110.0, exit_reason=ExitReason.MANUAL
        )
        assert trade.quantity == pytest.approx(2.0)
        assert float(position.quantity) == pytest.approx(0.0)

    def test_zero_quantity_is_rejected(self, db, portfolio) -> None:
        position = make_position(db)
        with pytest.raises(ValueError, match="greater than zero"):
            portfolio.reduce_position(
                db, position, quantity=0.0, exit_price=110.0, exit_reason=ExitReason.MANUAL
            )


class TestCostsAreSplitNotDuplicated:
    def test_entry_costs_are_shared_in_proportion(self, db, portfolio) -> None:
        """Charging the whole entry fee to the first partial exit would make it
        look far worse than it was and the remainder far better."""
        position = make_position(db, quantity=4.0, fees=1.0)
        trade = portfolio.reduce_position(
            db, position, quantity=1.0, exit_price=110.0, exit_reason=ExitReason.MANUAL
        )
        # A quarter of the position closed, so a quarter of the entry fee.
        assert trade.fees == pytest.approx(0.25)
        assert float(position.fees_paid) == pytest.approx(0.75)

    def test_the_remainder_keeps_its_entry_price(self, db, portfolio) -> None:
        position = make_position(db, quantity=2.0, entry=100.0)
        portfolio.reduce_position(
            db, position, quantity=1.0, exit_price=130.0, exit_reason=ExitReason.MANUAL
        )
        assert float(position.entry_price) == pytest.approx(100.0)


class TestTheHalvesAddUp:
    def test_two_partials_equal_one_full_close(self, db, portfolio) -> None:
        """The whole point of the proportional split: closing in two steps at
        the same price must produce the same money as closing once."""
        one_shot = make_position(db, quantity=2.0, margin=100.0, fees=1.0)
        full = portfolio.close_position(
            db, one_shot, exit_price=110.0, exit_reason=ExitReason.MANUAL
        )

        stepped = make_position(db, quantity=2.0, margin=100.0, fees=1.0)
        first = portfolio.reduce_position(
            db, stepped, quantity=1.0, exit_price=110.0, exit_reason=ExitReason.MANUAL
        )
        second = portfolio.close_position(
            db, stepped, exit_price=110.0, exit_reason=ExitReason.MANUAL
        )

        assert first.net_pnl + second.net_pnl == pytest.approx(full.net_pnl, rel=1e-9)
        assert first.fees + second.fees == pytest.approx(full.fees, rel=1e-9)

    def test_a_short_partial_is_profitable_when_price_falls(self, db, portfolio) -> None:
        position = make_position(db, quantity=2.0, entry=100.0, side="SHORT")
        trade = portfolio.reduce_position(
            db, position, quantity=1.0, exit_price=90.0, exit_reason=ExitReason.MANUAL
        )
        assert trade.gross_pnl == pytest.approx(10.0)
        assert trade.net_pnl > 0
