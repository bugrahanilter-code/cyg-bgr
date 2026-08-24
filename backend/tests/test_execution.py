"""Order validation, idempotency and execution engine tests."""

from __future__ import annotations

import pytest

from app.core.constants import OrderType, SignalType, TradingMode
from app.exchange.filters import SymbolFilters
from app.execution.engine import ExecutionEngine
from app.execution.idempotency import build_client_order_id
from app.execution.validators import validate_order
from app.portfolio.engine import PortfolioEngine
from app.risk.position_sizing import calculate_position_size
from app.signals.models import StrategySignal
from tests.mocks import MockGateway

FILTERS = SymbolFilters(
    symbol="BTC/USDT",
    tick_size=0.1,
    step_size=0.001,
    min_quantity=0.001,
    min_notional=5.0,
    max_leverage=20,
)


def test_quantity_is_rounded_to_the_step_size() -> None:
    result = validate_order(
        symbol="BTC/USDT",
        quantity=0.0123456,
        price=None,
        stop_price=None,
        order_type=OrderType.MARKET,
        filters=FILTERS,
        reference_price=30_000.0,
    )
    assert result.valid
    assert result.quantity == pytest.approx(0.012)


def test_price_is_rounded_to_the_tick_size() -> None:
    result = validate_order(
        symbol="BTC/USDT",
        quantity=0.01,
        price=30_000.07,
        stop_price=None,
        order_type=OrderType.LIMIT,
        filters=FILTERS,
        reference_price=30_000.0,
    )
    assert result.price == pytest.approx(30_000.1)


def test_below_min_notional_is_rejected() -> None:
    result = validate_order(
        symbol="BTC/USDT",
        quantity=0.0001,
        price=None,
        stop_price=None,
        order_type=OrderType.MARKET,
        filters=FILTERS,
        reference_price=30_000.0,
    )
    assert not result.valid


def test_leverage_above_the_limit_is_rejected() -> None:
    result = validate_order(
        symbol="BTC/USDT",
        quantity=0.01,
        price=None,
        stop_price=None,
        order_type=OrderType.MARKET,
        filters=FILTERS,
        reference_price=30_000.0,
        leverage=50,
        max_leverage=5,
    )
    assert not result.valid


def test_conditional_order_requires_a_stop_price() -> None:
    result = validate_order(
        symbol="BTC/USDT",
        quantity=0.01,
        price=None,
        stop_price=None,
        order_type=OrderType.STOP_MARKET,
        filters=FILTERS,
        reference_price=30_000.0,
    )
    assert not result.valid


def test_client_order_id_is_deterministic() -> None:
    first = build_client_order_id(
        mode="paper",
        symbol="BTC/USDT",
        strategy="trend_following",
        candle_open_time=1_700_000_000_000,
        side="BUY",
    )
    second = build_client_order_id(
        mode="paper",
        symbol="BTC/USDT",
        strategy="trend_following",
        candle_open_time=1_700_000_000_000,
        side="BUY",
    )
    assert first == second
    assert len(first) <= 36


def test_client_order_id_changes_with_the_candle() -> None:
    first = build_client_order_id(
        mode="paper", symbol="BTC/USDT", strategy="s", candle_open_time=1, side="BUY"
    )
    second = build_client_order_id(
        mode="paper", symbol="BTC/USDT", strategy="s", candle_open_time=2, side="BUY"
    )
    assert first != second


@pytest.fixture
def execution_setup(db):
    """Execution engine wired to the mock gateway in paper mode."""
    gateway = MockGateway(price=30_000.0)
    portfolio = PortfolioEngine(TradingMode.PAPER)
    engine = ExecutionEngine(
        gateway,
        mode=TradingMode.PAPER,
        portfolio=portfolio,
        filters_provider=lambda symbol: FILTERS,
        allow_real_orders=True,
        verify_attempts=1,
        verify_delay_seconds=0.0,
    )
    return engine, gateway, portfolio


def _signal(symbol: str = "BTC/USDT", candle: int = 1_700_000_000_000) -> StrategySignal:
    return StrategySignal(
        symbol=symbol,
        timeframe="15m",
        strategy_key="trend_following",
        signal=SignalType.LONG,
        candle_open_time=candle,
        confidence=0.9,
        entry_price=30_000.0,
        stop_loss=29_400.0,
        take_profit=31_200.0,
        explanation="test entry",
    )


def _sizing():
    return calculate_position_size(
        equity=10_000.0,
        available_balance=10_000.0,
        entry_price=30_000.0,
        stop_loss=29_400.0,
        side=SignalType.LONG,
        filters=FILTERS,
        risk_per_trade_pct=0.5,
        max_position_notional_pct=100.0,
        max_total_exposure_pct=200.0,
        current_exposure=0.0,
        leverage=2.0,
    )


async def test_entry_creates_a_position(execution_setup, db) -> None:
    engine, gateway, portfolio = execution_setup
    position = await engine.execute_entry(
        db, signal=_signal(), sizing=_sizing(), leverage=2.0, timeframe="15m"
    )
    assert position is not None
    assert position.symbol == "BTC/USDT"
    assert position.quantity > 0
    assert gateway.create_calls == 1


async def test_duplicate_entry_is_suppressed(execution_setup, db) -> None:
    """The same signal must never open two positions."""
    engine, gateway, portfolio = execution_setup
    candle = 1_700_000_111_000
    await engine.execute_entry(db, signal=_signal(candle=candle), sizing=_sizing(), leverage=2.0)
    calls_after_first = gateway.create_calls
    await engine.execute_entry(db, signal=_signal(candle=candle), sizing=_sizing(), leverage=2.0)
    assert gateway.create_calls == calls_after_first


async def test_real_orders_are_blocked_without_confirmation(db) -> None:
    gateway = MockGateway()
    engine = ExecutionEngine(
        gateway,
        mode=TradingMode.LIVE,
        portfolio=PortfolioEngine(TradingMode.LIVE),
        filters_provider=lambda symbol: FILTERS,
        allow_real_orders=False,
    )
    from app.core.exceptions import LiveTradingDisabledError

    with pytest.raises(LiveTradingDisabledError):
        await engine.execute_entry(db, signal=_signal(), sizing=_sizing(), leverage=2.0)
    assert gateway.create_calls == 0
