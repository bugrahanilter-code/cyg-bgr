"""Position sizing tests."""

from __future__ import annotations

import pytest

from app.core.constants import RiskRejectionCode, SignalType
from app.exchange.filters import SymbolFilters, default_filters_for, floor_to_increment
from app.risk.position_sizing import calculate_position_size, estimate_liquidation_price


def size(**overrides):
    payload = {
        "equity": 10_000.0,
        "available_balance": 10_000.0,
        "entry_price": 30_000.0,
        "stop_loss": 29_400.0,
        "side": SignalType.LONG,
        "filters": default_filters_for("BTC/USDT"),
        "risk_per_trade_pct": 0.5,
        "max_position_notional_pct": 100.0,
        "max_total_exposure_pct": 200.0,
        "current_exposure": 0.0,
        "leverage": 3.0,
    }
    payload.update(overrides)
    return calculate_position_size(**payload)


def test_risk_per_trade_defines_the_size() -> None:
    result = size()
    assert result.valid
    # 0.5 percent of 10.000 = 50 USDT risked over a 600 USDT stop distance.
    assert result.quantity == pytest.approx(0.083, abs=0.001)
    assert result.risk_amount <= 50.0 + 1e-6


def test_size_is_not_derived_from_leverage_alone() -> None:
    low = size(leverage=2.0)
    high = size(leverage=10.0)
    assert low.quantity == pytest.approx(high.quantity)
    assert high.margin < low.margin


def test_wider_stop_means_smaller_position() -> None:
    tight = size(stop_loss=29_700.0)
    wide = size(stop_loss=28_500.0)
    assert tight.quantity > wide.quantity


def test_notional_cap_is_applied() -> None:
    result = size(max_position_notional_pct=5.0, stop_loss=29_990.0)
    assert result.valid
    assert result.notional <= 10_000.0 * 0.05 + 1e-6
    assert "max_position_notional" in result.caps_applied


def test_exposure_cap_is_applied() -> None:
    result = size(current_exposure=19_500.0, max_total_exposure_pct=200.0, stop_loss=29_900.0)
    assert result.notional <= 500.0 + 1e-6


def test_margin_cap_is_applied() -> None:
    result = size(available_balance=100.0, leverage=2.0, stop_loss=29_990.0)
    assert result.margin <= 100.0 * 0.95 + 1e-6


def test_quantity_respects_the_step_size() -> None:
    filters = SymbolFilters(symbol="BTC/USDT", step_size=0.01, min_quantity=0.01, min_notional=5.0)
    result = size(filters=filters)
    assert result.quantity == floor_to_increment(result.quantity, 0.01)


def test_below_minimum_quantity_is_rejected() -> None:
    result = size(equity=10.0, available_balance=10.0)
    assert not result.valid
    assert result.rejection_code in (
        RiskRejectionCode.POSITION_SIZE_TOO_SMALL,
        RiskRejectionCode.MIN_NOTIONAL_NOT_MET,
    )


def test_invalid_stop_direction_is_rejected() -> None:
    result = size(stop_loss=30_500.0)
    assert not result.valid
    assert result.rejection_code == RiskRejectionCode.INVALID_STOP_LOSS


def test_short_position_sizing() -> None:
    result = size(side=SignalType.SHORT, stop_loss=30_600.0)
    assert result.valid
    assert result.quantity > 0


def test_liquidation_price_estimates() -> None:
    long_liquidation = estimate_liquidation_price(30_000.0, SignalType.LONG, 10, 0.005)
    short_liquidation = estimate_liquidation_price(30_000.0, SignalType.SHORT, 10, 0.005)
    assert long_liquidation is not None and long_liquidation < 30_000.0
    assert short_liquidation is not None and short_liquidation > 30_000.0
