"""Open-position figures shown to the user.

Two things are easy to get wrong here and both mislead in the same direction:
reporting the raw price difference as "profit" while a round trip would still
leave you behind, and showing one percentage when leverage makes two of them
mean very different things.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.constants import PositionStatus, TradingMode
from app.core.time_utils import utcnow
from app.models.trading import Position
from app.services.dashboard_service import _position_payload


def position(**overrides) -> Position:
    payload = {
        "uid": uuid.uuid4().hex[:24],
        "symbol": "BTC/USDT",
        "strategy_key": "trend_following",
        "mode": TradingMode.PAPER.value,
        "side": "LONG",
        "status": PositionStatus.OPEN.value,
        "quantity": 10.0,
        "entry_price": 100.0,
        "leverage": 20.0,
        "margin": 50.0,
        "fees_paid": 0.4,
        "funding_paid": 0.1,
        "opened_at": utcnow(),
    }
    payload.update(overrides)
    return Position(**payload)


class TestCostsAreIncluded:
    def test_profit_is_reported_after_every_cost(self) -> None:
        """A 1% move on $1,000 is $10 gross. The entry fee, the funding and the
        exit fee that closing will cost all come off before it is called profit."""
        payload = _position_payload(position(), price=101.0, taker_fee_pct=0.04)
        assert payload["unrealized_pnl_gross"] == pytest.approx(10.0)
        # 0.4 entry fee + 0.1 funding + 1010 * 0.04% exit fee
        assert payload["total_costs"] == pytest.approx(0.4 + 0.1 + 0.404)
        assert payload["unrealized_pnl"] == pytest.approx(10.0 - 0.904)

    def test_a_small_gross_gain_can_be_a_net_loss(self) -> None:
        """The case that matters: the screen says you are up, and closing would
        actually take money off the account."""
        payload = _position_payload(position(), price=100.05, taker_fee_pct=0.04)
        assert payload["unrealized_pnl_gross"] > 0
        assert payload["unrealized_pnl"] < 0

    def test_the_breakeven_move_is_reported(self) -> None:
        payload = _position_payload(position(), price=100.0, taker_fee_pct=0.04)
        assert payload["breakeven_move_pct"] > 0
        assert payload["breakeven_move_pct"] == pytest.approx(
            payload["total_costs"] / payload["current_notional"] * 100.0
        )

    def test_a_short_is_profitable_when_price_falls(self) -> None:
        payload = _position_payload(position(side="SHORT"), price=95.0, taker_fee_pct=0.04)
        assert payload["unrealized_pnl_gross"] == pytest.approx(50.0)
        assert payload["unrealized_pnl"] < payload["unrealized_pnl_gross"]
        assert payload["unrealized_pnl"] > 0


class TestTheTwoPercentages:
    def test_price_change_ignores_leverage(self) -> None:
        low = _position_payload(position(leverage=2.0), price=101.0)
        high = _position_payload(position(leverage=20.0), price=101.0)
        assert low["price_change_pct"] == pytest.approx(1.0)
        assert high["price_change_pct"] == pytest.approx(1.0)

    def test_margin_return_is_multiplied_by_leverage(self) -> None:
        """The number that alarms people: at 20x a 1% move is a 20% swing on the
        margin committed. Both are true and they are not the same number."""
        small_margin = _position_payload(position(margin=50.0), price=101.0)
        large_margin = _position_payload(position(margin=500.0), price=101.0)
        assert abs(small_margin["return_on_margin_pct"]) > abs(large_margin["return_on_margin_pct"])

    def test_price_change_is_negative_for_a_long_that_fell(self) -> None:
        payload = _position_payload(position(), price=98.0)
        assert payload["price_change_pct"] == pytest.approx(-2.0)
        assert payload["unrealized_pnl"] < 0


class TestPositionValue:
    def test_current_value_uses_the_live_price(self) -> None:
        payload = _position_payload(position(quantity=10.0), price=120.0)
        assert payload["current_notional"] == pytest.approx(1200.0)
        assert payload["notional"] == pytest.approx(1000.0)

    def test_value_falls_with_the_price(self) -> None:
        payload = _position_payload(position(quantity=10.0), price=80.0)
        assert payload["current_notional"] == pytest.approx(800.0)
